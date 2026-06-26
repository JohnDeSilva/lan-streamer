# Code Review: Threading Refactor (`parallelization_2` branch)

**Commits reviewed:** `f656dd0` · `0dc78b5`
**Reviewer:** Antigravity (senior review pass)
**Date:** 2026-06-25
**Files changed:** `controller.py`, `threading_manager.py` (new), `docs/threading.md` (new), multiple test files

---

## Executive Summary

The refactor correctly eliminates the 11 scattered `_*_worker_instance` attributes and the buggy bare `QObject.disconnect()` call from `_stop_worker()`. The `WorkerSlot` / `WorkerManager` abstraction is clean and the direction is sound. However, **several real bugs and antipatterns remain** that could cause crashes, hangs, incorrect UI state, or data loss in production. There are also significant test gaps for the new infrastructure itself.

---

## Bugs & Issues Catalogue

---

### BUG-1 — UI Thread Blocks During `WorkerSlot.stop()` (Potential Deadlock / Freeze)

**Severity:** 🔴 Critical
**Danger:** Application hang / UI freeze for up to 5 seconds per slot, or permanent deadlock
**Likelihood:** Medium — triggered whenever a new scan is started while the previous one is still running
**Fix complexity:** Medium

**Location:** [`threading_manager.py` L71–96](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/threading_manager.py#L71-L96)

**Description:**

`WorkerSlot.stop()` calls `worker.wait(self._timeout_ms)` **on the Qt main/UI thread**. `QThread.wait()` is a blocking call. If the worker thread:
- Is blocked on disk I/O (network share scan, database write, ffmpeg operation)
- Is blocked waiting on the `DatabaseWriterThread` queue's `threading.Event`
- Is inside a long VLC or TMDB network call

…then the entire Qt event loop freezes for up to 5,000 ms. The UI is unresponsive and cannot repaint, process input, or even dispatch the `finished` signal from the very thread we are waiting on.

Worse, there is a **classic deadlock scenario**: if the background worker emits a signal just as `stop()` blocks, the Qt cross-thread queued-connection delivery is deferred to the main event loop — which is now blocked by `wait()`. The signal can never be delivered, the worker can never finish, and `wait()` times out (best case) or hangs forever (worst case if the worker is waiting on a `threading.Event` that the main thread must service).

**This was present in the original `_stop_worker()` too**, but it was called far less often. In the new design `start()` unconditionally calls `stop()` first, so *every single new worker creation* goes through this blocking path.

**Proof of trigger path:**
```
User clicks "Scan" while previous scan still running
  → trigger_scan() called
    → worker_manager.scan.start()     ← calls stop() internally
      → worker.wait(5000)             ← BLOCKS UI THREAD
```

**Fix:**
```python
# Option A (preferred): Never block the UI thread. Async stop.
def stop(self) -> None:
    worker = self._instance
    if worker is None:
        return
    try:
        worker.requestInterruption()
        worker.quit()
        worker.deleteLater()          # Let Qt clean up asynchronously
    except RuntimeError as error:
        logger.debug("WorkerSlot: RuntimeError while stopping %s: %s",
                     worker.__class__.__name__, error)
    self._instance = None

# Option B: At minimum, pump the event loop during wait() to stay responsive:
def stop(self) -> None:
    worker = self._instance
    if worker is None:
        return
    try:
        worker.requestInterruption()
        worker.quit()
        deadline = QDeadlineTimer(self._timeout_ms)
        while not worker.wait(50) and not deadline.hasExpired():
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if worker.isRunning():
            logger.warning("WorkerSlot: %s did not finish within %d ms",
                           worker.__class__.__name__, self._timeout_ms)
        worker.deleteLater()
    except RuntimeError as error:
        logger.debug(...)
    self._instance = None
```

Option A is cleanest: `requestInterruption()` + `quit()` + `deleteLater()` is exactly what Qt documentation recommends for non-blocking teardown.

---

### BUG-2 — `WorkerSlot.instance` Is Potentially `None` / Wrong When `_on_*_finished` Handlers Run (TOCTOU Race)

**Severity:** 🔴 Critical
**Danger:** Crashes (`AttributeError`) or silent data loss from reading the wrong worker's attributes
**Likelihood:** Low–Medium (requires a rapid re-trigger of the same slot between signal queuing and handler execution)
**Fix complexity:** Low

**Location:** [`controller.py` L353–355, L537, L580, L644, L1208–1219, L1260–1271](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/controller.py#L353)

**Description:**

The pattern used throughout the new controller is:

```python
def _on_scan_finished(self, updated_library):
    scan_worker = self.worker_manager.scan.instance   # read _instance NOW
    scanned_library_name = getattr(scan_worker, "library_name", None) or ...
    unavailable = getattr(scan_worker, "unavailable_directories", [])
    changed_seasons = getattr(scan_worker, "changed_season_ids", None)
```

`WorkerSlot.instance` returns `self._instance`. `self._instance` is set to `None` in `stop()`, and to the new worker in `start()`. If anything calls `scan.start()` again between the `finished` signal being queued and the handler actually running (possible in a busy event loop), `self._instance` will be the *new* worker or `None` — not the one that just finished.

**Concrete failure:** `_on_scan_and_update_cleanup_finished` reads `self.worker_manager.scan.instance` to get `changed_season_ids`, but at that point a new scan could have been started.

**Fix:**
Capture the worker reference in the lambda at connection time, not at handler execution time:

```python
# In WorkerSlot.start(), wrap the finished slot:
worker: W = factory()
self._instance = worker
_captured_worker = worker   # local capture, immune to later reassignment

for signal_name, slot in signal_slots.items():
    if slot is not None:
        signal = getattr(worker, signal_name, None)
        if signal is not None:
            signal.connect(slot)

# In controller, handlers should receive the worker via a parameter instead of
# re-reading self.worker_manager.X.instance. One approach is to pass it:
worker.finished.connect(lambda *args: self._on_scan_finished_with_worker(_captured, *args))
```

---

### BUG-3 — `MetadataApplyWorker` Created with `parent=self` (Controller) — Ownership Conflict

**Severity:** 🔴 Critical (intermittent crash)
**Danger:** `RuntimeError: Internal C++ object already deleted` or double-free
**Likelihood:** Low–Medium (triggered by rapid re-triggering of metadata apply)
**Fix complexity:** Low (remove one argument)

**Location:** [`controller.py` L972](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/controller.py#L972)

**Description:**

```python
self.worker_manager.metadata_apply.start(
    lambda: MetadataApplyWorker(
        ...
        parent=self,   # ← Controller is the QObject parent
    ),
    ...
)
```

`WorkerSlot.stop()` calls `worker.deleteLater()` to schedule deferred deletion. But the worker also has `parent=self` (the `Controller`), meaning Qt *also* holds ownership. This creates a **double-delete**: `deleteLater()` queues a delete, and parent-child destruction also tries to delete it.

Additionally, `QThread` objects with a parent that lives on a different thread can cause Qt internal warnings and undefined behavior. All other workers are created without a parent — this is an inconsistency and a bug.

**Fix:**
```python
lambda: MetadataApplyWorker(
    ...
    # parent=self,  ← REMOVE THIS
),
```

---

### BUG-4 — `cleanup` Slot Reused for Three Incompatible Signal Connections (Signal Leak / Wrong Callback)

**Severity:** 🟠 High
**Danger:** Wrong `finished` handler fires, causing state corruption or incorrect status messages
**Likelihood:** Medium — happens whenever `scan_and_update` and `trigger_global_cleanup` are interleaved
**Fix complexity:** Low

**Location:** [`controller.py` L404, L439, L518](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/controller.py#L404)

**Description:**

The single `worker_manager.cleanup` slot is used with **three different `finished` callbacks**:

| Call site | `finished=` |
|---|---|
| `trigger_cleanup()` | `self._on_cleanup_finished` |
| `_run_next_global_cleanup()` | `self._on_global_cleanup_step_finished` |
| `_on_scan_and_update_scan_finished()` | `self._on_scan_and_update_cleanup_finished` |

`WorkerSlot.stop()` calls `worker.deleteLater()` — it does **not** explicitly call signal `disconnect()`. Signal connections on a `QObject` are cleaned up when the object is destroyed, but `deleteLater()` defers destruction to the next event loop iteration. Until then, all previously connected slots are still live.

If a new cleanup worker is started before the previous one's C++ object is destroyed, the old `finished` signal connection may fire for the new worker's completion — triggering the wrong callback.

**Fix (Option A — preferred):** Use separate `WorkerSlot` instances per distinct finished-callback:
```python
# In WorkerManager.__init__:
self.cleanup: WorkerSlot = WorkerSlot(self)          # trigger_cleanup()
self.cleanup_global: WorkerSlot = WorkerSlot(self)   # trigger_global_cleanup()
self.cleanup_scan_update: WorkerSlot = WorkerSlot(self)  # scan_and_update
```

**Fix (Option B):** Track and disconnect signals explicitly in `stop()`:
```python
# Store which signal names were connected during start()
self._connected_signals: List[str] = []

def stop(self) -> None:
    worker = self._instance
    if worker is None:
        return
    for sig_name in self._connected_signals:
        sig = getattr(worker, sig_name, None)
        if sig is not None:
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass
    self._connected_signals.clear()
    ...
```

---

### BUG-5 — `_slots()` Uses `dir()` — Fragile and Slow

**Severity:** 🟡 Medium
**Danger:** Performance degradation; future `WorkerSlot` attributes may be missed or double-counted
**Likelihood:** High (runs on every `stop_all()` call, including application shutdown)
**Fix complexity:** Low

**Location:** [`threading_manager.py` L152–158](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/threading_manager.py#L152-L158)

**Description:**

```python
def _slots(self) -> List[WorkerSlot]:
    result: List[WorkerSlot] = []
    for attr_name in dir(self):          # dir() on QObject is expensive
        attr = getattr(self, attr_name, None)
        if isinstance(attr, WorkerSlot):
            result.append(attr)
    return result
```

`dir()` on a `QObject` returns everything — inherited Qt methods, Python dunder attributes, Qt properties. It is slow and order is alphabetical, not intentional. A new `WorkerSlot` added by a subclass but not in `dir()` order could be skipped.

**Fix:**
```python
def __init__(self, parent=None) -> None:
    super().__init__(parent)
    self.scan: WorkerSlot = WorkerSlot(self)
    # ... (all slots) ...
    self._all_slots: List[WorkerSlot] = [
        self.scan, self.scan_all, self.cleanup,
        self.jellyfin_pull, self.jellyfin_push,
        self.file_property, self.subtitle_merge,
        self.metadata_embed, self.metadata_apply,
        self.refresh, self.scan_series,
    ]

def _slots(self) -> List[WorkerSlot]:
    return self._all_slots
```

---

### BUG-6 — No `stop_all()` Called at Application Shutdown

**Severity:** 🟠 High
**Danger:** Background threads still running when Qt event loop exits → crash on exit, zombie `DatabaseWriterThread`, potential partial DB writes
**Likelihood:** High — any time the user closes the app during a scan
**Fix complexity:** Low (one line in `main.py`)

**Location:** [`main.py`](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/main.py) — no `aboutToQuit` or `stop_all` reference

**Description:**

`WorkerManager.stop_all()` exists but is **never called**. When the user closes the app:
- Qt destroys the `Controller` QObject (and by parenting, the `WorkerManager` and `WorkerSlot` objects)
- Active `QThread` objects destroyed while still running → undefined behavior / crash
- `DatabaseWriterThread` (a `daemon=True` threading.Thread) dies, possibly mid-write
- SQLite transactions may be left open or partially committed

**Fix:**
```python
# In main.py, after creating the QApplication and Controller:
app.aboutToQuit.connect(controller.worker_manager.stop_all)
```

---

### BUG-7 — `start()` Silently Ignores Unknown Signal Names

**Severity:** 🟡 Medium
**Danger:** Signals never connected → features silently broken (e.g., no `finished` callback, no error reporting)
**Likelihood:** Low (currently), but High if a developer misspells a signal name
**Fix complexity:** Low

**Location:** [`threading_manager.py` L57–61](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/threading_manager.py#L57-L61)

**Description:**

```python
signal = getattr(worker, signal_name, None)
if signal is not None:              # ← silently ignores missing signals
    signal.connect(slot)
```

A typo like `finsihed=self._on_finished` silently does nothing. No warning is logged.

**Fix:**
```python
if signal is None:
    logger.warning(
        "WorkerSlot.start(): worker %s has no signal '%s' — slot not connected",
        worker.__class__.__name__, signal_name,
    )
else:
    signal.connect(slot)
```

---

### BUG-8 — `start_if_not_running()` Is Defined but Never Used (Dead API / Pattern Inconsistency)

**Severity:** 🟡 Medium (dead code / future confusion)
**Danger:** Developers may add new slots without a concurrency guard, relying on `start()` being safe
**Likelihood:** N/A
**Fix complexity:** Low

**Location:** [`threading_manager.py` L98–113](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/threading_manager.py#L98-L113)

**Description:**

`start_if_not_running()` is never called. All callers implement their own `if self.worker_manager.X.is_running: return` guard. Some slots (cleanup, jellyfin_pull/push) have **no guard at all** — `start()` is called directly, silently killing the running worker and starting a new one.

This two-pattern API is a footgun. The fix should standardize: either always use `start_if_not_running()` at the call site, or add the guard logic into `start()` itself and rename appropriately.

---

### BUG-9 — Tests Directly Access `._instance` Private Attribute (Breaks Encapsulation)

**Severity:** 🟡 Medium
**Danger:** Tests are fragile; setting `._instance` bypasses the full lifecycle and can give false confidence
**Likelihood:** High — already done in 15+ test locations across 6 test files
**Fix complexity:** Low–Medium

**Location:** `tests/unit/ui_views/test_controller*.py`, `tests/e2e/test_e2e_workflow.py`

**Description:**

```python
# 15+ occurrences of this pattern:
controller_instance.worker_manager.scan._instance = mock_worker
```

This bypasses `stop()`, any initialization logic in `start()`, and breaks the encapsulation contract of `WorkerSlot`. If `WorkerSlot` is ever refactored internally, all these tests break.

**Fix:** Add a test-only helper or use `PropertyMock`:
```python
# Option A: test helper method
def _inject_mock_for_test(self, mock_worker):
    """Only for tests. Injects a mock instance."""
    self._instance = mock_worker

# Option B: patch the property
with patch.object(
    type(controller.worker_manager.scan), "is_running",
    new_callable=PropertyMock, return_value=True
):
    controller.trigger_scan()
```

---

### BUG-10 — No Unit Tests for `WorkerSlot` / `WorkerManager` Themselves

**Severity:** 🟠 High
**Danger:** Core threading infrastructure has zero direct test coverage
**Likelihood:** N/A (gap, not a runtime bug)
**Fix complexity:** Medium

**Location:** `tests/unit/system/` — no `test_threading_manager.py`

**Description:**

`threading_manager.py` is new code that manages the entire threading lifecycle. There are no tests for:
- `WorkerSlot.start()` connects signals correctly
- `WorkerSlot.stop()` calls `requestInterruption()` and `quit()`
- `WorkerSlot.is_running` returns correct values before/during/after worker
- `WorkerSlot.start_if_not_running()` short-circuits correctly
- `WorkerManager.stop_all()` calls `stop()` on every slot
- `WorkerManager._slots()` returns all 11 slots

This violates the project's 90% coverage requirement.

**Fix:** Create `tests/unit/system/test_threading_manager.py` with mocked `QThread` workers.

---

### ISSUE-11 — `stop()` Swallows All `RuntimeError` Without Specificity

**Severity:** 🟢 Low
**Danger:** Legitimate errors silently suppressed at `DEBUG` level
**Likelihood:** Low
**Fix complexity:** Low

**Location:** [`threading_manager.py` L89–94](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/threading_manager.py#L89-L94)

**Description:**

Any `RuntimeError` is caught — including ones that indicate bugs (e.g., `"QThread: Destroyed while thread is still running"`). Logging at `DEBUG` means these will be invisible in production.

**Fix:** Narrow the catch to known-safe error messages, log others at `WARNING`.

---

### ISSUE-12 — Alphabetical Shutdown Order via `dir()` in `stop_all()`

**Severity:** 🟢 Low
**Danger:** Wrong shutdown order for dependent workers
**Fix complexity:** Resolved by BUG-5 fix

---

## What Works Well

| Item | Assessment |
|---|---|
| Removal of bare `worker.disconnect()` | ✅ Correct fix for the PySide6 `TypeError` |
| Named `WorkerSlot` per role | ✅ Clean, self-documenting |
| `getattr(worker, "attr", default)` pattern | ✅ Defensive, handles `None` cleanly |
| `threading.md` documentation | ✅ Excellent — clear diagrams, patterns, taxonomy |
| ~177 lines of boilerplate removed | ✅ Major readability win |
| `WorkerSlot` as `QObject` with parent | ✅ Correct Qt memory management |
| Test suite updated for new API | ✅ All old attribute references updated |

---

## Priority Matrix

| ID | Issue | Danger | Likelihood | Fix Complexity | Priority |
|---|---|---|---|---|---|
| BUG-1 | UI thread blocks in `stop()` (freeze/deadlock) | 🔴 Critical | Medium | Medium | **P0 — Must Fix** |
| BUG-3 | `parent=self` on `MetadataApplyWorker` → double-delete | 🔴 Critical | Low–Med | Low | **P0 — Must Fix** |
| BUG-6 | No `stop_all()` at shutdown → crash / DB corruption | 🟠 High | High | Low | **P0 — Must Fix** |
| BUG-2 | TOCTOU race on `instance` in `_on_*_finished` handlers | 🔴 Critical | Low | Low | **P1 — Fix Before Merge** |
| BUG-4 | Signal leak — `cleanup` slot reused with different callbacks | 🟠 High | Medium | Low | **P1 — Fix Before Merge** |
| BUG-10 | Zero tests for `WorkerSlot` / `WorkerManager` | 🟠 High | N/A (gap) | Medium | **P1 — Fix Before Merge** |
| BUG-5 | `_slots()` uses `dir()` — fragile and slow | 🟡 Medium | High | Low | **P2 — Fix Soon** |
| BUG-7 | Silent failure on unknown signal name | 🟡 Medium | Low | Low | **P2 — Fix Soon** |
| BUG-8 | `start_if_not_running()` dead API / inconsistent pattern | 🟡 Medium | N/A | Low | **P2 — Fix Soon** |
| BUG-9 | Tests access `._instance` private attr directly | 🟡 Medium | High | Low–Med | **P2 — Fix Soon** |
| ISSUE-11 | `RuntimeError` catch too broad in `stop()` | 🟢 Low | Low | Low | **P3 — Nice to Have** |
| ISSUE-12 | Alphabetical shutdown order | 🟢 Low | Low | Low | **P3 — Resolved by BUG-5 fix** |

---

## Recommended Fix Sequence

### Phase 1 — Blockers (must fix before merge)

1. **Remove `parent=self` from `MetadataApplyWorker`** (BUG-3) — 1 line
2. **Wire `stop_all()` to `app.aboutToQuit`** (BUG-6) — 1 line in `main.py`
3. **Make `WorkerSlot.stop()` non-blocking** (BUG-1) — remove `wait()`, use `requestInterruption()` + `quit()` + `deleteLater()`
4. **Add warning log for unknown signal names in `start()`** (BUG-7) — 3 lines
5. **Replace `dir()` in `_slots()` with explicit list** (BUG-5) — 5 lines

### Phase 2 — High priority (same PR or immediate follow-up)

6. **Fix TOCTOU in `_on_*_finished` handlers** (BUG-2) — capture worker reference in closure at connect time
7. **Separate cleanup slots or explicitly disconnect signals** (BUG-4) — add `cleanup_global` / `cleanup_scan_update` slots
8. **Add `tests/unit/system/test_threading_manager.py`** (BUG-10)

### Phase 3 — Improvements

9. **Resolve `start_if_not_running()` API ambiguity** (BUG-8)
10. **Add test helper method instead of `._instance` direct access** (BUG-9)
11. **Narrow `RuntimeError` catch** (ISSUE-11)

---

## Verdict

**Do not merge as-is.** BUG-1, BUG-3, and BUG-6 can cause real crashes and data corruption. BUG-2 and BUG-4 are subtle threading races that are extremely difficult to reproduce and debug in production. The PR direction is correct and the design is sound — these are fixable with small, targeted diffs. Address Phase 1 and Phase 2 items, add unit tests for `WorkerSlot`/`WorkerManager`, then merge.
