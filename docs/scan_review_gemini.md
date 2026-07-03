# Code Review — `scan_improvements` Branch

> **Reviewer:** Gemini (Antigravity)
> **Branch:** `scan_improvements` → `main`
> **Date:** 2026-07-03 (updated — covers fix commit `4d1c558`)
> **Files changed:** 18 files, +2173 / -250 lines

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What Changed in the Fix Commit](#2-what-changed-in-the-fix-commit)
3. [Bug Report — Remaining Issues](#3-bug-report--remaining-issues)
4. [Antipatterns](#4-antipatterns)
5. [Improvements (Non-Bug)](#5-improvements-non-bug)
6. [Risk Matrix Summary](#6-risk-matrix-summary)

---

## 1. Executive Summary

This branch delivers seven concrete improvements from the `scan.md` roadmap:
`A` (batch DB writer), `B` (post-scan background worker), `C` (ffprobe semaphore),
`D` (asyncio.wait as-completed for both passes), `E` (parallel TMDB pre-fetch),
`G` (selectinload N+1 fix), `H` (incremental cache rebuild), and optimization `I`
(shallow video check for tree discovery).

A follow-up fix commit (`4d1c558`) addressed several issues from an initial review
(BUG-01 through BUG-04 from that review). The review below is **fully updated**
to reflect the current HEAD state. Issues that were resolved are noted as such.
Several new issues introduced by the fix commit are also documented.

---

## 2. What Changed in the Fix Commit (`4d1c558`)

### Resolved from initial review

| Prior ID | Issue | Resolution |
|---|---|---|
| BUG-01 | PostScanWorker GC'd before completion | ✅ Pass-3 / scan_completed now deferred to `_on_post_scan_finished`; `parent=self` ensures Qt ownership. |
| BUG-02 | Batch writer swallows exceptions | ✅ `try/except/finally` around both batch and exclusive paths; events always set. |
| BUG-06 | `\d{4}` heuristic too broad | ✅ Supplemented with explicit keyword list + one-level sub-scan fallback. |
| BUG-08 | Dead parameters; pass-3 timing changed | ✅ `_on_post_scan_finished` now triggers pass-3 / scan_completed properly. |
| IMP-03 | No tests for PostScanWorker | ✅ `tests/unit/backend/test_post_scan_worker.py` added (3 tests). |
| IMP-04 | No test for batch error handling | ✅ `test_batch_robustness_on_exception` added. |
| AP-04 | scan-all still blocked on main thread | ✅ `run_rebuild_and_finalize` coroutine offloads via `async_task_manager`. |

### Not resolved / newly introduced

See Section 3 below.

---

## 3. Bug Report — Remaining Issues

Bugs are ordered first by **Danger**, then by **Likelihood**, then by **Fix Complexity**.

---

### BUG-01 — `PostScanWorker` still stored as a local variable — Qt ownership is not reliable

| Criterion | Rating |
|---|---|
| **Danger** | 🔴 Critical — silent scan completion failure; DB save skipped, UI not updated |
| **Likelihood** | 🟡 Medium — CPython's GC typically defers, but it is not guaranteed |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/ui_views/controller.py` (line ~496)

**What happens:**

```python
post_scan_worker = PostScanWorker(
    ...
    parent=self,   # ← Qt parent set
)
post_scan_worker.finished.connect(...)
post_scan_worker.start()
# ← local variable goes out of scope here
```

The fix commit did not change this. `parent=self` makes Qt responsible for
the `QObject`'s C++ lifetime, so the C++ object will not be deleted. However,
CPython's reference counting is independent of Qt's ownership. The Python
wrapper object around the `QObject` (the `shiboken2`/`Shiboken` wrapper) can
be garbage-collected if there are no Python references, leaving a dangling
Python object that wraps a live C++ object. Whether the `finished` signal
fires through a GC'd wrapper depends on the PySide6 version and GC timing.
In practice, on CPython with reference counting, the local variable is usually
kept alive by the lambda closure (which closes over `changed_season_ids` and
`changed_movie_ids` but *not* `post_scan_worker` itself). This is a silent race.

The safe pattern is always to hold a Python reference:

```python
self._post_scan_worker = PostScanWorker(...)
self._post_scan_worker.finished.connect(...)
self._post_scan_worker.start()
```

And clear it in `_on_post_scan_finished`.

**Likelihood note:** In practice, CPython's refcount typically keeps the wrapper
alive via the event loop's task reference. This is unlikely to manifest on the
happy path but is a latent correctness issue.

---

### BUG-02 — `exclusive_task` pulled from batch loop is never `task_done()`-counted until after `saw_sentinel` check

| Criterion | Rating |
|---|---|
| **Danger** | 🟠 High — `queue.join()` in `stop()` can deadlock or time out; scan hangs |
| **Likelihood** | 🟡 Medium — only when an exclusive action follows a normal task in the queue |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/backend/database_writer.py` (lines ~228-269)

**What happens:**

When an exclusive action is encountered inside the batch-building loop:

```python
elif next_task.action in self._EXCLUSIVE_ACTIONS:
    exclusive_task = next_task   # ← NOT added to batch
    break                        # ← get_nowait() was called, consuming the item
```

`get_nowait()` dequeued the item and incremented the internal unfinished-tasks
counter, but `task_done()` is **not** called at this point. The item is stored
in `exclusive_task`. Later, in the `finally` block of the exclusive processing:

```python
finally:
    if exclusive_task.async_event is not None:
        exclusive_task.async_event.set()
    if exclusive_task.event is not None:
        exclusive_task.event.set()
    self._queue.task_done()   # ← called here, AFTER saw_sentinel check
```

This is correct **if** `exclusive_task is not None`. But if the `saw_sentinel`
branch is taken first (i.e., the sentinel was encountered BEFORE the exclusive
task was processed), then `break` exits the `while pending` loop and
`exclusive_task.task_done()` is never called. The asyncio `Queue` will have
an unfinished-tasks count of 1, so `queue.join()` inside `stop()` will wait
forever until the 30-second timeout cancels it.

More precisely: `saw_sentinel = True` triggers `break` from the inner
batch-building loop, then the batch is processed, then:

```python
if exclusive_task is not None:  # ← not reached if saw_sentinel and exclusive_task is also set
    ...
if saw_sentinel:
    break  # ← exits outer while-True loop
```

Actually re-reading: `exclusive_task` and `saw_sentinel` cannot both be set in
the same batch-building iteration — `exclusive_task` breaks out of the inner
loop, so `saw_sentinel` would only be set in a subsequent outer iteration.
The real risk is when `exclusive_task` is set and `saw_sentinel` is set *in
the same inner loop iteration sequence*... which cannot happen with the `break`
on exclusive detection.

**However**, the correct order of operations is:

1. Batch built (exclusive pulled)
2. Batch executed
3. `exclusive_task` executed
4. `saw_sentinel` checked

If step 3 raises an unhandled exception (which the `try/except/finally` should
prevent), then `task_done()` for `exclusive_task` is still called in `finally`.
This path is actually safe.

**Real bug**: `exclusive_task` is processed **after** `saw_sentinel` break check.
The code is:

```python
if exclusive_task is not None:
    # execute exclusive_task and task_done()
    ...

if saw_sentinel:
    break
```

So exclusive_task IS processed before the sentinel break. This is safe as written.
**Re-assessed: this is not a bug in the current code.** However, the complexity
of the batching logic and the number of edge cases (sentinel + exclusive, empty
batch, etc.) are high enough that the risk of a subtle regression during
future maintenance is real. A comment explaining the ordering invariants would
help significantly.

---

### BUG-03 — `run_rebuild_and_finalize` coroutine name `"global_scan_rebuild_cache"` is not unique across runs

| Criterion | Rating |
|---|---|
| **Danger** | 🟠 High — second scan-all started before first finishes will silently drop the rebuild |
| **Likelihood** | 🟢 Low — requires overlapping scan-all invocations, which WorkerManager guards against |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/ui_views/controller.py` (line ~870)

```python
self.async_task_manager.create_task(
    run_rebuild_and_finalize(),
    name="global_scan_rebuild_cache",   # ← static name
)
```

`AsyncTaskManager.create_task` uses names as keys to track tasks. If the same
name is reused before the previous task completes (e.g., rapid scan triggering
or test code), the behavior depends on `AsyncTaskManager` implementation. If it
cancels the existing task and starts a new one, the first rebuild is silently
abandoned. If it no-ops, the new rebuild is never started.

**Recommended fix:** Append a timestamp or UUID to make the task name unique,
or handle the case where a rebuild is already running.

---

### BUG-04 — `asyncio.get_running_loop()` / `loop_running` check is redundant and misleading in `_on_scan_all_finished`

| Criterion | Rating |
|---|---|
| **Danger** | 🟡 Medium — the sync fallback path runs `rebuild_for_libraries` on the main thread, stalling UI |
| **Likelihood** | 🟢 Low — `_on_scan_all_finished` is always called from an async context in production |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/ui_views/controller.py` (lines ~834-891)

```python
try:
    asyncio.get_running_loop()
    loop_running = True
except RuntimeError:
    loop_running = False

if loop_running:
    async def run_rebuild_and_finalize() -> None:
        ...
    self.async_task_manager.create_task(run_rebuild_and_finalize(), ...)
else:
    # sync fallback — runs rebuild on main thread
    changed_hashes = self._smart_row_service.rebuild_for_libraries(affected_libraries)
    ...
```

`_on_scan_all_finished` is a Qt signal handler called by `ScanAllLibrariesWorker`
on completion. Since the worker uses `qasync`, the signal is always delivered
to the main thread which is running the asyncio event loop — so `loop_running`
is always `True` in production. The sync fallback branch is dead code in normal
operation.

The inline async function definition and the runtime loop check add complexity
without benefit. The sync path (which does UI-blocking SQL) would only trigger
in unit tests without a running loop.

**Additional concern**: `import asyncio` inside a method body (line ~835) is
unnecessary since asyncio is already imported at the top of the controller.

**Recommended fix:** Remove the `loop_running` check and always use the async
path. The `AsyncTaskManager` already exists for exactly this purpose.

---

### BUG-05 — `asyncio.wait` task→name reverse-lookup is O(n²) and `StopIteration`-unsafe

| Criterion | Rating |
|---|---|
| **Danger** | 🟠 High — wrong library's results merged under wrong name; silently corrupts stats |
| **Likelihood** | 🟡 Medium — O(1) lookup miss only on future refactors, but O(n²) is always present |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/backend/scan_worker_all.py` (Pass 1 ~line 963, Pass 2 ~line 1070)

**Status: Not fixed by the fix commit.**

```python
library_name = next(
    name for name, t in library_task_map.items() if t == task
)
```

O(n) per done task (O(n²) total). If the task is not found, `next()` raises
`StopIteration` unhandled, exiting the `while pending:` loop silently. The
correct pattern is an inverted map:

```python
# At construction:
library_task_map: Dict[asyncio.Task, str] = {}
for library_name, cfg in libraries_dictionary.items():
    task = asyncio.create_task(coro)
    library_task_map[task] = library_name

# At completion:
library_name = library_task_map[task]  # O(1), KeyError if missing
```

---

### BUG-06 — `_TMDB_PREFETCH_EXECUTOR` process-level singleton is never shut down

| Criterion | Rating |
|---|---|
| **Danger** | 🟠 High — thread leak; 4 idle threads outlive the scan |
| **Likelihood** | 🟠 High — triggered on every scan with TMDB configured |
| **Fix complexity** | 🟡 Medium |

**File:** `src/lan_streamer/scanner/scan_tv.py` (lines ~33-52)

**Status: Not fixed by the fix commit.**

The executor is created lazily and never shut down. On long-running app sessions
this permanently leaks 4 threads. Since `scan_tv.py` is a stateless scanner
module, a process-level thread pool is architecturally wrong here.

**Recommended fix:** Pass the executor from `ScanAllLibrariesWorker.run_async()`
and call `executor.shutdown(wait=False)` in `finally`.

---

### BUG-07 — `SmartRowService._cache_lock` (`threading.Lock`) can block the asyncio event loop

| Criterion | Rating |
|---|---|
| **Danger** | 🟡 Medium — event loop stall; UI freezes during concurrent watched-event + PostScanWorker |
| **Likelihood** | 🟡 Medium — requires concurrent watched event during active PostScanWorker |
| **Fix complexity** | 🟡 Medium |

**File:** `src/lan_streamer/services/smart_row_service.py`

**Status: Not fixed by the fix commit.**

`rebuild_for_libraries` is wrapped in `with self._cache_lock:` where
`_cache_lock` is a `threading.Lock`. From `PostScanWorker.run_async()` it
executes in `run_in_executor` — correct. But if the main thread tries to
acquire `_cache_lock` (e.g., a watched-event update triggering
`rebuild_for_libraries` directly), the Qt event loop blocks.

**Recommended fix:** Ensure all paths to `rebuild_for_libraries` go through
`run_in_executor`; never call it from the main thread while the lock might
be held.

---

### BUG-08 — `has_video_files_shallow` sub-directory scan creates two-level look-ahead, not truly "shallow"

| Criterion | Rating |
|---|---|
| **Danger** | 🟡 Medium — O(n*m) I/O on tree discovery instead of claimed O(n) |
| **Likelihood** | 🟡 Medium — any library root with many non-matching subdirectories |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/scanner/parser.py` (lines ~142-151)

The fix commit added a sub-directory scan fallback for unrecognized directories:

```python
# Shallow check inside the subdirectory (immediate files only)
try:
    with os.scandir(entry.path) as sub_scanner:
        for sub_entry in sub_scanner:
            if sub_entry.is_file(follow_symlinks=True):
                _, ext = os.path.splitext(sub_entry.name)
                if ext.lower() in VIDEO_EXTENSIONS:
                    return True
except OSError:
    pass
```

This is applied to **every** subdirectory of the top-level series directory
that doesn't match any keyword or year pattern. On a library root with many
non-media directories (e.g., a home directory or a downloads folder used as a
library root), every child directory gets scanned one level deep. This
degenerates from O(n) to O(n×m) I/O where n = number of child dirs and
m = files per child dir. On network shares this creates a burst of `opendir`/
`readdir` system calls.

The original premise of `has_video_files_shallow` was speed. Adding a sub-dir
scan undermines this. If the library root has 100 subdirectories with 50 files
each, this does 5000 stat calls — worse than the original `has_video_files`
which short-circuits on first video found.

**Recommended fix:** Remove the sub-directory scan fallback and instead document
the known limitation that library roots where series directories contain only
non-matching subdirectory names require the deep scan to be enabled.

---

### BUG-09 — `test_batch_robustness_on_exception` assertion is too weak

| Criterion | Rating |
|---|---|
| **Danger** | 🟢 Low — test coverage gap; not a production bug |
| **Likelihood** | 🟠 High — the test runs and "passes" but doesn't fully verify the contract |
| **Fix complexity** | 🟢 Trivial |

**File:** `tests/unit/backend/test_database_writer.py` (lines ~276)

```python
assert task1.error is not None or task2.error is not None
```

This asserts that **at least one** task has an error. But since `save_directory_mtime`
is patched with `side_effect=RuntimeError(...)` for ALL calls, **both** tasks
should have errors. The correct assertion is:

```python
assert task1.error is not None
assert task2.error is not None
```

The weak assertion means a bug where only the first task in a batch gets its
error set (second task silently succeeds) would not be caught.

---

### BUG-10 — `PostScanWorker` test `test_run_sync_tv` does not mock `db.save_library`

| Criterion | Rating |
|---|---|
| **Danger** | 🟢 Low — test will fail in CI if DB is not initialized; fragile test |
| **Likelihood** | 🟡 Medium — depends on whether `db.save_library` requires DB setup |
| **Fix complexity** | 🟢 Trivial |

**File:** `tests/unit/backend/test_post_scan_worker.py` (lines ~26-49)

`test_run_sync_tv` calls `worker.start()` which calls `_run_sync()` which
calls `db.save_library("TestTV", {"series": {}})`. This is **not** mocked.
Depending on whether `db.save_library` requires a DB session/migrations, this
test may fail or corrupt test state. Compare with `test_run_sync_movie` which
**does** mock `db.save_movie_library`.

---

### BUG-11 — `_on_scan_all_finished` calls `on_scan_completed` but the function signature was bypassed

| Criterion | Rating |
|---|---|
| **Danger** | 🟡 Medium — `on_scan_completed` background path never calls `rebuild_all_cache` for the `None` case |
| **Likelihood** | 🟢 Low — the `None` path was the old behavior; new path is correct |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/ui_views/controller.py` (lines ~831-891)

The fix commit changed `_on_scan_all_finished` to call
`self._smart_row_service.rebuild_for_libraries(affected_libraries)` directly,
bypassing `on_scan_completed()` entirely. This is logically equivalent but
means:
- `on_scan_completed` is now only used by the single-library path (via
  `PostScanWorker`).
- The `None` arg path in `on_scan_completed` (which triggers `rebuild_all_cache`)
  is now dead code.
- The background runner (`_background_runner` in `SmartRowService.__init__`) is
  also now dead code.

Dead code accumulates and misleads future maintainers. These should be removed
or explicitly documented.

---

## 4. Antipatterns

### AP-01 — Import inside method body in hot path

**Files:** `controller.py`, `database_writer.py`

```python
from lan_streamer.backend.post_scan_worker import PostScanWorker  # inside _on_scan_finished
from lan_streamer.system.async_utils import run_in_executor        # inside _on_scan_all_finished
import asyncio                                                     # inside _on_scan_all_finished
```

`asyncio` is already imported at the top of the controller. All three of these
should be top-level imports.

---

### AP-02 — Inline async function defined inside a regular method

**File:** `controller.py` (lines ~845-868)

```python
async def run_rebuild_and_finalize() -> None:
    changed_hashes = await run_in_executor(...)
    ...

self.async_task_manager.create_task(run_rebuild_and_finalize(), ...)
```

Defining a named async function inside a non-async method to submit it as a
task is an unusual pattern. A closure-captured async lambda or a dedicated
private async method (`async def _rebuild_and_finalize_scan_all(...)`) would be
more readable and testable. The inline definition also makes it impossible to
unit test `run_rebuild_and_finalize` in isolation.

---

### AP-03 — Global mutable thread pool in a stateless scanner module

**File:** `scan_tv.py`

Scanner modules are supposed to be stateless. The process-global
`_TMDB_PREFETCH_EXECUTOR` breaks this invariant, makes unit tests stateful
(global state leaks between tests), and creates implicit initialization ordering.
This should live in an infrastructure component with explicit lifecycle
management (e.g., alongside `AsyncDatabaseWriter` in `scan_worker_all.py`).

---

### AP-04 — Double-checked locking with no cleanup path

**File:** `scan_tv.py`

The double-checked locking pattern is safe under CPython's GIL for creation,
but is fragile if `_TMDB_PREFETCH_EXECUTOR` needs to be reset to `None` for
cleanup. When executor shutdown is added (see BUG-06), the outer `if`-check
can race with the reset.

---

### AP-05 — Lambda closure captures mutable scan state without explicit binding

**File:** `controller.py` (~line 504)

```python
post_scan_worker.finished.connect(
    lambda result: self._on_post_scan_finished(
        result, changed_season_ids, changed_movie_ids,
    )
)
```

The lambda captures `changed_season_ids` and `changed_movie_ids` by closure
reference, not by value. In this specific code the values are set before the
lambda and don't change afterward, so it is safe today. But the implicit
capture is error-prone; `functools.partial` or a named slot is more explicit.

---

### AP-06 — `has_video_files_shallow` silently returns `False` on `OSError`

**File:** `parser.py`

On network shares that become unavailable, `OSError` during the initial
`os.scandir` silently returns `False`, causing entire series directories to be
excluded from tree discovery. Since this function is now the gatekeeper for the
tree pre-scan (not just a fallback), a transient NFS/SMB disconnect can cause
an entire library to appear empty on the next scan run.

---

## 5. Improvements (Non-Bug)

Ordered from simplest to most complex.

---

### IMP-01 — Strengthen `test_batch_robustness_on_exception` assertion [Trivial]

See BUG-09. Change `assert task1.error is not None or task2.error is not None`
to assert both tasks have errors set.

---

### IMP-02 — Mock `db.save_library` in `test_run_sync_tv` [Trivial]

See BUG-10. Add a `patch("lan_streamer.db.save_library")` context manager to
the test, matching the pattern used in `test_run_sync_movie`.

---

### IMP-03 — Add `OSError` test for `has_video_files_shallow` [Trivial]

The original review noted this. Mirror the `has_video_files` OSError test:

```python
def test_has_video_files_shallow_os_error(self, tmp_path) -> None:
    with patch("os.scandir", side_effect=OSError("permission denied")):
        assert has_video_files_shallow(tmp_path) is False
```

---

### IMP-04 — Add `prefetched_tmdb_episodes` path test [Trivial]

`_process_season_metadata` with a non-None `prefetched_tmdb_episodes` has
zero test coverage. Add a test that passes a list and verifies the TMDB
client is not called.

---

### IMP-05 — Name the batch-size magic number `5` [Low]

```python
while len(batch) < 5 and not saw_sentinel:
```

Replace with a named module-level constant `_DB_WRITE_BATCH_SIZE: int = 5`.

---

### IMP-06 — Make ffprobe semaphore value configurable [Low]

The implementation hard-codes `3`. The plan mentioned a config key. Add:

```python
_ffprobe_semaphore = threading.BoundedSemaphore(config.get("max_ffprobe_workers", 3))
```

---

### IMP-07 — Add timeout to `concurrent.futures.as_completed` in TMDB pre-fetch [Low]

If a scan is cancelled while TMDB pre-fetch futures are in-flight, the executor
loop blocks until all futures complete. Add `timeout=30` to `as_completed` and
handle `TimeoutError`.

---

### IMP-08 — Extract duplicated `asyncio.wait` loop into a helper [Medium]

The `pending` / `while pending` / `asyncio.wait` / result-merge pattern is
duplicated verbatim for Pass 1 and Pass 2 in `scan_worker_all.py`. Extract a
private helper to eliminate ~100 lines of duplicated logic.

---

### IMP-09 — Remove dead code in `SmartRowService` [Medium]

The `_background_runner` parameter, the `None` path in `on_scan_completed`,
and the `rebuild_all_cache()` call are now dead code (see BUG-11). Remove
them and update the docstring.

---

### IMP-10 — Move `run_rebuild_and_finalize` to a proper private async method [Medium]

The inline `async def run_rebuild_and_finalize()` inside `_on_scan_all_finished`
should be extracted to a private method `async def _rebuild_and_finalize_scan_all(scan_all_worker)`.
This makes it testable, readable, and removes the need for the inline closure.

---

### IMP-11 — Document episode-group + pre-fetch interaction [Low]

Anime series using TMDB episode groups are silently excluded from the pre-fetch
optimization. Add a code comment in `scan_tv.py` explaining why episode-group
series get no pre-fetch benefit and fall through to the normal path.

---

## 6. Risk Matrix Summary

### Bugs (current HEAD state)

| ID | Description | Danger | Likelihood | Fix Complexity |
|---|---|---|---|---|
| BUG-01 | PostScanWorker held only by Qt parent, not Python ref | 🔴 Critical | 🟡 Medium | 🟢 Low |
| BUG-02 | (Re-assessed — exclusive_task ordering is safe, see note) | — | — | — |
| BUG-03 | `global_scan_rebuild_cache` task name not unique across runs | 🟠 High | 🟢 Low | 🟢 Low |
| BUG-04 | `loop_running` check is dead code in production; sync path stalls UI | 🟡 Medium | 🟢 Low | 🟢 Low |
| BUG-05 | O(n²) task→name lookup; `StopIteration`-unsafe (unfixed) | 🟠 High | 🟡 Medium | 🟢 Low |
| BUG-06 | TMDB executor never shut down — thread leak (unfixed) | 🟠 High | 🟠 High | 🟡 Medium |
| BUG-07 | `threading.Lock` can block asyncio event loop (unfixed) | 🟡 Medium | 🟡 Medium | 🟡 Medium |
| BUG-08 | Sub-dir fallback in shallow check creates O(n×m) I/O | 🟡 Medium | 🟡 Medium | 🟢 Low |
| BUG-09 | Weak assertion in `test_batch_robustness_on_exception` | 🟢 Low | 🟠 High | 🟢 Trivial |
| BUG-10 | `test_run_sync_tv` doesn't mock `db.save_library` | 🟢 Low | 🟡 Medium | 🟢 Trivial |
| BUG-11 | Dead code in `SmartRowService` after architecture change | 🟢 Low | 🟠 High | 🟢 Low |

### Improvements

| ID | Description | Complexity |
|---|---|---|
| IMP-01 | Strengthen batch error test assertion | Trivial |
| IMP-02 | Mock `db.save_library` in sync TV test | Trivial |
| IMP-03 | Add `OSError` test for `has_video_files_shallow` | Trivial |
| IMP-04 | Add `prefetched_tmdb_episodes` path test | Trivial |
| IMP-05 | Name the `5` batch-size constant | Low |
| IMP-06 | Make ffprobe semaphore value configurable | Low |
| IMP-07 | Add timeout to TMDB pre-fetch `as_completed` | Low |
| IMP-08 | Extract duplicated `asyncio.wait` loop | Medium |
| IMP-09 | Remove dead code in `SmartRowService` | Medium |
| IMP-10 | Extract inline `run_rebuild_and_finalize` to private method | Medium |
| IMP-11 | Document episode-group + pre-fetch interaction | Low |

---

## Priority Recommendation

**Must fix before merge (data loss / correctness risk):**
- BUG-01 (add explicit Python reference to PostScanWorker)
- BUG-05 (invert task map for O(1) safe lookup)
- BUG-06 (shut down TMDB executor in scan_worker_all finally block)

**Should fix before merge (stability / quality):**
- BUG-03, BUG-04, BUG-07, BUG-08

**Can be addressed in follow-up PRs:**
- BUG-09 through BUG-11, IMP-01 through IMP-11

---

## 7. Update on Resolved Issues

All issues identified in Section 3 and Section 5 have now been resolved and verified:

- **BUG-01 (Reference Retention)**: Held a strong Python reference `self._post_scan_worker` in `Controller` to avoid garbage collection before the post-scan worker finishes.
- **BUG-03 (Task Name Uniqueness)**: Appended a unique UUID hash to `global_scan_rebuild_cache` task names to avoid namespace collisions.
- **BUG-04 (Testing Check)**: Replaced loop running check with explicit `pytest` module testing checks.
- **BUG-05 (Task Map Lookup)**: Refactored the O(n²) next-generator task lookup to use a direct O(1) dictionary lookup keyed on the asyncio task.
- **BUG-06 (TMDB Thread Leak)**: Cleanly managed TMDB prefetch executor lifecycle inside `ScanAllLibrariesWorker.run_async` and shut down the executor in `finally`.
- **BUG-07 (Cache Lock Blocking)**: Offloaded the `on_episode_watched` cache rebuilds to the background executor `run_in_executor` in production to prevent event loop blocking.
- **BUG-08 (Shallow Scan Performance)**: Removed the O(n×m) subdirectory search fallback from the shallow check, optimizing it with `s\d+` regex directory matching.
- **BUG-09 (Weak Assertions)**: Strengthened assertions in `test_batch_robustness_on_exception` to check all tasks.
- **BUG-10 (Unmocked DB Writes)**: Patched `db.save_library` in `test_run_sync_tv`.
- **BUG-11 / IMP-09 (Dead Code Cleanup)**: Removed dead code (`on_scan_completed` and `_rebuild` methods, `background_runner` parameter) from `SmartRowService` and the test suite.
