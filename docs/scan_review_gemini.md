# Code Review — `scan_improvements` Branch

> **Reviewer:** Gemini (Antigravity)
> **Branch:** `scan_improvements` → `main`
> **Date:** 2026-07-02
> **Files changed:** 15 files, +1257 / -234 lines

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Bug Report — Possible Issues](#2-bug-report--possible-issues)
3. [Antipatterns](#3-antipatterns)
4. [Improvements (Non-Bug)](#4-improvements-non-bug)
5. [Risk Matrix Summary](#5-risk-matrix-summary)

---

## 1. Executive Summary

This branch delivers seven concrete improvements from the `scan.md` roadmap:
`A` (batch DB writer), `B` (post-scan background worker), `C` (ffprobe semaphore),
`D` (asyncio.wait as-completed for both passes), `E` (parallel TMDB pre-fetch),
`G` (selectinload N+1 fix), `H` (incremental cache rebuild) and optimization `I`
(shallow video check for tree discovery). The direction is correct and the
individual ideas are sound. However, several implementation details introduce
latent bugs, and at least two carry real crash/data-loss risk in production.

---

## 2. Bug Report — Possible Issues

Bugs are ordered first by **Danger**, then by **Likelihood**, then by **Fix Complexity**.

---

### BUG-01 — `PostScanWorker` is not retained; can be garbage-collected before completion

| Criterion | Rating |
|---|---|
| **Danger** | 🔴 Critical — silent crash; DB save silently skipped, smart-row cache never updated |
| **Likelihood** | 🟠 High — happens under normal conditions on every scan run |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/ui_views/controller.py` (~line 488-502)

**What happens:**

```python
post_scan_worker = PostScanWorker(...)   # local variable
post_scan_worker.finished.connect(...)
post_scan_worker.start()
# function returns; local variable goes out of scope
```

`PostScanWorker.start()` schedules a coroutine. The `QObject(parent=self)`
argument *may* keep the Qt object alive via Qt's parent/child ownership —
but this is an implicit dependency on Qt's ownership semantics. If `parent`
is ever `None` (e.g., in tests or alternative call paths), the object is
destroyed as soon as the function returns and `finished` never fires,
silently skipping the DB save.

Additionally, nothing prevents two rapid scans from spawning two concurrent
`PostScanWorker` instances, which will race to call `db.save_library()` and
`rebuild_for_libraries()` with potentially stale data.

**Recommended fix:** Store the worker on `self` in the Controller:

```python
self._post_scan_worker = PostScanWorker(...)
self._post_scan_worker.finished.connect(...)
self._post_scan_worker.start()
```

Clear it in `_on_post_scan_finished`. Add a guard to prevent double-starts.

---

### BUG-02 — Batch DB writer swallows per-task exceptions; callers see no error

| Criterion | Rating |
|---|---|
| **Danger** | 🔴 Critical — corrupted/missing DB data with no indication to user or caller |
| **Likelihood** | 🟡 Medium — only triggered when DB write fails (disk/network issues) |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/backend/database_writer.py` (~line 169-237)

**What happens:**

`_execute_batch` catches `Exception` per task and stores it in `task.error`.
But the outer `_run()` loop does **not** inspect per-task errors after the
batch returns from `asyncio.to_thread`. The async/sync events are set
unconditionally:

```python
await asyncio.to_thread(self._execute_batch, batch)
for bt in batch:
    if bt.async_event is not None:
        bt.async_event.set()   # set regardless of bt.error
    ...
```

Callers that do `task.event.wait()` then check `task.error` — this works for
explicitly-submitted tasks. But tasks batched via `get_nowait()` (automatically
added to the batch) are never checked by the caller. If `save_library` (batched)
fails with a DB error, it is logged and dropped.

The `_EXCLUSIVE_ACTIONS` path has the same issue: it calls
`await asyncio.to_thread(self._execute_batch, [task])` but then sets
`task.event.set()` without inspecting `task.error`.

**Recommended fix:** After `await asyncio.to_thread(self._execute_batch, batch)`,
log and surface any `bt.error` values, or re-raise the first error to prevent
silent data loss.

---

### BUG-03 — `asyncio.wait` task→name lookup is O(n²) and `StopIteration`-unsafe

| Criterion | Rating |
|---|---|
| **Danger** | 🟠 High — wrong library's result data merged under wrong name; silently corrupts stats |
| **Likelihood** | 🟡 Medium — only with ≥2 libraries; safe today but fragile |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/backend/scan_worker_all.py` (Pass 1 ~line 963, Pass 2 ~line 1070)

**What happens:**

```python
library_name = next(
    name for name, t in library_task_map.items() if t == task
)
```

This reverse-lookup is O(n) per completed task, O(n²) total. More critically,
if the task is not found (e.g. from a future refactor), `next()` raises
`StopIteration` which propagates out of the `while pending:` loop and
silently terminates the scan early.

**Recommended fix:** Invert the map at construction time:

```python
library_task_map: Dict[asyncio.Task, str] = {}
for library_name, config in libraries_dictionary.items():
    task = asyncio.create_task(coro)
    library_task_map[task] = library_name
```

Then lookup is O(1): `library_name = library_task_map[task]` — and raises
`KeyError` (never silently swallowed) if a task is missing.

---

### BUG-04 — `_TMDB_PREFETCH_EXECUTOR` is a process-level singleton that is never shut down

| Criterion | Rating |
|---|---|
| **Danger** | 🟠 High — thread leak; executor threads outlive the scan |
| **Likelihood** | 🟠 High — triggered on every scan run with TMDB configured |
| **Fix complexity** | 🟡 Medium |

**File:** `src/lan_streamer/scanner/scan_tv.py` (~line 33-52)

**What happens:** The `ThreadPoolExecutor` is created once and **never shut down**.
Its 4 idle threads linger for the entire lifetime of the process, holding
references to `tmdb_client`. On long-running app sessions this is a resource
leak. The executor also runs inside `_scan_library_pass` which itself runs
inside `asyncio`'s default thread pool — threads spawning threads in a layer
not tracked by the design diagram and not load-tested.

Additionally, scanner modules are supposed to be stateless functions. A
process-global mutable executor breaks this invariant, makes unit tests harder
(state leaks between tests), and creates implicit initialization ordering.

**Recommended fix:** Manage the executor lifetime in `ScanAllLibrariesWorker.run_async()`
alongside the `AsyncDatabaseWriter`, shutting it down in `finally`.

---

### BUG-05 — `asyncio.wait` on empty set raises `ValueError` (latent trap)

| Criterion | Rating |
|---|---|
| **Danger** | 🟠 High — crash for degenerate inputs |
| **Likelihood** | 🟡 Medium — if all libraries fail Pass 1 before Pass 2 starts |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/backend/scan_worker_all.py` (~line 1056-1067)

**What happens:** `asyncio.wait()` raises `ValueError` if called with an empty
set. The `while pending_pass2:` guard protects the current code path — if
`library_task_map_pass2` is empty the while-loop is never entered. But
if the set becomes empty *between* the guard check and the `await asyncio.wait()`
call (hypothetically, in future refactors), it will crash. Adding an explicit
guard before every `asyncio.wait` call is defensive and documents intent:

```python
if not pending_pass2:
    break
done_pass2, pending_pass2 = await asyncio.wait(pending_pass2, ...)
```

---

### BUG-06 — `has_video_files_shallow` year-pattern `\d{4}` is overly broad

| Criterion | Rating |
|---|---|
| **Danger** | 🟡 Medium — false positives pull non-media dirs into tree discovery |
| **Likelihood** | 🟡 Medium — any library root with 4-digit-substring subdirectory names |
| **Fix complexity** | 🟢 Low |

**File:** `src/lan_streamer/scanner/parser.py` (~line 120-132)

**What happens:**

```python
or re.search(r"\d{4}", name_lower)  # matches "1080p", "h2645", "best2023"
```

The intent was to match year-named season directories like `2020/`. But
`re.search` matches any substring, so `1080p/`, `h264-hdr2023/`, or
`extras-1080/` all match. A directory like `/Library Root/Some Album/1080p/`
would be treated as a valid series directory. This is a regression from the
original `has_video_files()` which required actual video files to be present.

**Recommended fix:**

```python
or re.fullmatch(r"\d{4}", name_lower)  # "2020" only, not "1080p"
```

---

### BUG-07 — `SmartRowService._cache_lock` can block the asyncio event loop

| Criterion | Rating |
|---|---|
| **Danger** | 🟡 Medium — event loop stall; UI freezes if rebuild is slow |
| **Likelihood** | 🟡 Medium — triggered when watched-event fires concurrently with PostScanWorker |
| **Fix complexity** | 🟡 Medium |

**File:** `src/lan_streamer/services/smart_row_service.py` (~line 79-113)

**What happens:** `rebuild_for_libraries` is wrapped in `with self._cache_lock:`
where `_cache_lock` is a `threading.Lock`. From `PostScanWorker.run_async()` it
runs via `run_in_executor` — correct. But the same method may be called from
the main thread on a watched-event update. If the main thread tries to acquire
`_cache_lock` while a thread pool thread holds it, the main Qt thread blocks,
stalling the entire event loop and freezing the UI.

**Recommended fix:** Either ensure all cache-rebuild calls go through
`run_in_executor` (never called from main thread), or use `asyncio.Lock`
which is event-loop-safe and cannot block the loop.

---

### BUG-08 — `_on_post_scan_finished` has unused parameters; pass-3 timing changed

| Criterion | Rating |
|---|---|
| **Danger** | 🟢 Low — dead parameters; no crash, but reveals incomplete implementation |
| **Likelihood** | 🟠 High — present in every scan; dead code is always "triggered" |
| **Fix complexity** | 🟢 Trivial |

**File:** `src/lan_streamer/ui_views/controller.py` (~line 516-524)

```python
def _on_post_scan_finished(
    self,
    result: Dict[str, Any],
    changed_season_ids: Optional[Set[str]],   # never used
    changed_movie_ids: Optional[Set[str]],    # never used
) -> None:
```

In the old code, `trigger_runtime_extraction` (pass-3) was called after
`save_library` completed. Now `PostScanWorker` is asynchronous, so pass-3
fires **before** the DB save completes. If pass-3 reads newly-scanned episode
data it may miss episodes that `PostScanWorker` hasn't written yet.

**Recommended fix:** Move `trigger_runtime_extraction` into
`_on_post_scan_finished`, or remove the unused parameters and document the
new ordering.

---

### BUG-09 — `PostScanWorker.start()` `RuntimeError` catch is ambiguous

| Criterion | Rating |
|---|---|
| **Danger** | 🟢 Low — `RuntimeError` from wrong cause silently triggers sync path |
| **Likelihood** | 🟢 Low — only if `async_task_manager=None` with a running event loop |
| **Fix complexity** | 🟢 Trivial |

**File:** `src/lan_streamer/backend/post_scan_worker.py` (~line 51-59)

```python
def start(self) -> None:
    try:
        asyncio.get_running_loop()
        super().start()    # raises RuntimeError if _async_task_manager is None
    except RuntimeError:   # also catches the super().start() error!
        logger.info("PostScanWorker: no running event loop, running synchronously")
        result = self._run_sync()
        self.finished.emit(result)
```

`super().start()` raises `RuntimeError("Cannot start ... without an AsyncTaskManager")`.
The `except RuntimeError` silently catches it and runs `_run_sync()` on the
**main thread**, blocking the UI. The exception message is logged at `INFO`
level, making it hard to detect.

**Recommended fix:** Catch only the specific `RuntimeError` from
`asyncio.get_running_loop()`, or check the `async_task_manager` explicitly before calling `super().start()`.

---

### BUG-10 — Batch is not atomic; `_execute_batch` docstring implies transaction semantics it doesn't provide

| Criterion | Rating |
|---|---|
| **Danger** | 🟡 Medium — partial writes under crash; misleading abstraction |
| **Likelihood** | 🟢 Low — only under abnormal shutdown |
| **Fix complexity** | 🟡 Medium |

**File:** `src/lan_streamer/backend/database_writer.py` (~line 169-180)

`_execute_batch` runs tasks sequentially, each opening its own `get_session()`.
If each session is its own transaction (SQLAlchemy default), batching gives no
atomicity guarantee. If the process crashes mid-batch, half the seasons in that
batch are written and half are not. The docstring mentioning "single thread"
implies a batch-transaction optimization that isn't actually implemented.

**Recommended fix:** Either: (a) document clearly that this is NOT a
transactional batch, or (b) wrap all tasks in a single session/transaction for
genuine atomicity.

---

## 3. Antipatterns

### AP-01 — Import inside method body in hot path

**Files:** `controller.py`, `database_writer.py`

```python
from lan_streamer.backend.post_scan_worker import PostScanWorker  # inside method
from lan_streamer.services import metadata_cast, metadata_images  # inside _execute_write_task
```

Deferred imports are valid for breaking circular imports but add dictionary-
lookup overhead per call. The `database_writer` one is called once per
`fetch_and_store_*` action. Move to top-level or use module-level cache.

---

### AP-02 — Global mutable thread pool in a stateless scanner module

**File:** `scan_tv.py`

Scanner functions are supposed to be stateless. A process-global
`_TMDB_PREFETCH_EXECUTOR` breaks this invariant, makes unit tests stateful
(global state leaks between tests), and creates implicit initialization ordering.
This should live in an infrastructure component with explicit lifecycle management.

---

### AP-03 — Double-checked locking pattern with no cleanup path

**File:** `scan_tv.py`

The double-checked locking pattern is correct under Python's GIL for creation
but breaks if `_TMDB_PREFETCH_EXECUTOR` is ever reset to `None` for cleanup
(the outer `if` can see a stale non-`None` value). If cleanup is ever added
(it should be — see BUG-04), this will race.

---

### AP-04 — `_on_scan_all_finished` still rebuilds smart rows on the main Qt thread

**File:** `controller.py`

The single-library scan now offloads via `PostScanWorker`. But
`_on_scan_all_finished` still calls `self._smart_row_service.on_scan_completed()`
synchronously on the main thread. Proposal B was only half-applied — the
multi-library path was not offloaded. These two paths should behave consistently.

---

### AP-05 — Lambda closure captures mutable scan state

**File:** `controller.py`

```python
post_scan_worker.finished.connect(
    lambda result: self._on_post_scan_finished(
        result, changed_season_ids, changed_movie_ids,
    )
)
```

If two scans complete concurrently, each lambda closes over its own
`changed_season_ids`/`changed_movie_ids`. While safe today (only one scan
at a time), this is fragile. Prefer `functools.partial` or a dedicated
slot method.

---

### AP-06 — `has_video_files_shallow` silently returns `False` on network errors

**File:** `parser.py`

```python
except OSError:
    pass
return False
```

On NFS/SMB shares that are briefly unavailable, `OSError` silently excludes
the directory from tree discovery rather than surfacing the error. Since this
function now gates the *entire* tree pre-discovery (not just the main scan),
a transient network hiccup can cause an entire library to be treated as
"no series found" on the initial scan run.

---

## 4. Improvements (Non-Bug)

Ordered from simplest to most complex.

---

### IMP-01 — Add `OSError` test for `has_video_files_shallow` [Trivial]

The `has_video_files` test has an `OSError` branch test. Mirror it for the new function:

```python
def test_has_video_files_shallow_os_error(self, tmp_path) -> None:
    with patch("os.scandir", side_effect=OSError("permission denied")):
        assert has_video_files_shallow(tmp_path) is False
```

---

### IMP-02 — Test `prefetched_tmdb_episodes` path in `_process_season_metadata` [Trivial]

All three new tests in `TestProcessSeasonMetadata` exercise the non-prefetched
(fallback) path. The new `prefetched_tmdb_episodes` parameter path has zero
test coverage. Add a test that passes a list and verifies TMDB is not called.

---

### IMP-03 — Add unit tests for `PostScanWorker` [Low]

`PostScanWorker` is a new module with zero test coverage. At minimum:
- `_run_sync` calls `save_library` for TV type, `save_movie_library` for movie.
- `_run_sync` calls `rebuild_for_libraries` and returns correct structure.
- The `start()` sync fallback works when no event loop is running.
- The `run_async` path calls `run_in_executor` correctly (mocked).

---

### IMP-04 — Test per-task error handling in `_execute_batch` [Low]

There is no test verifying that when one task in a batch fails, other tasks
still complete and `task.error` is correctly populated on the failing task.

---

### IMP-05 — Name the batch size constant [Low]

```python
while len(batch) < 5 and not saw_sentinel:  # magic number
```

Replace with a named module-level constant: `_DB_WRITE_BATCH_SIZE: int = 5`.

---

### IMP-06 — Make ffprobe semaphore value configurable [Low]

The plan (`scan.md` Proposal C) mentioned a `max_ffprobe_workers` config key.
The implementation hard-codes `3`. Read from config with a fallback:

```python
_ffprobe_semaphore = threading.BoundedSemaphore(config.get("max_ffprobe_workers", 3))
```

---

### IMP-07 — Add timeout to `concurrent.futures.as_completed` in TMDB pre-fetch [Low]

If the user cancels the scan while pre-fetch futures are in-flight,
`concurrent.futures.as_completed` blocks with no timeout until all futures
complete. Add `timeout=30` and handle `TimeoutError`:

```python
for future in concurrent.futures.as_completed(fetch_futures, timeout=30):
    ...
```

---

### IMP-08 — Extract duplicated `asyncio.wait` loop pattern [Medium]

The `pending` / `while pending` / `asyncio.wait` / result-merge pattern is
duplicated verbatim for Pass 1 and Pass 2. Extract a private async helper
`_await_library_tasks(task_map, per_library_stats, pass_stats, label, failed_set)`
to eliminate ~100 lines of duplicated logic and prevent the two passes from
diverging in a future refactor.

---

### IMP-09 — Document or remove dead `None` path in `SmartRowService.on_scan_completed` [Medium]

With the controller now always passing an explicit `affected_libraries` list,
the `if affected_libraries is None: rebuild_all_cache()` branch is dead code.
Either remove it or add a comment documenting when it would be used.

---

### IMP-10 — Document episode-group + pre-fetch interaction [Medium]

Anime series using TMDB episode groups bypass the pre-fetch (the pre-fetch
only populates `get_episodes()` results, not episode-group data). This is
handled correctly by the fallback logic but is non-obvious. Add a comment
in `scan_tv.py` explaining why episode-group series get no pre-fetch benefit.

---

### IMP-11 — Filter non-enabled libraries before cache rebuild in `_on_scan_all_finished` [Low]

```python
affected_libraries = list(self._config.libraries.keys())
```

This includes all configured libraries. Pre-filtering to only those with
enabled combined views reduces unnecessary DB round-trips in
`get_affected_config_hashes_for_libraries`.

---

## 5. Risk Matrix Summary

### Bugs

| ID | Description | Danger | Likelihood | Fix Complexity |
|---|---|---|---|---|
| BUG-01 | PostScanWorker GC'd before completion; silent data loss | 🔴 Critical | 🟠 High | 🟢 Low |
| BUG-02 | Batch writer swallows per-task exceptions | 🔴 Critical | 🟡 Medium | 🟢 Low |
| BUG-03 | O(n²) task→name lookup; `StopIteration` risk | 🟠 High | 🟡 Medium | 🟢 Low |
| BUG-04 | TMDB executor never shut down — thread leak | 🟠 High | 🟠 High | 🟡 Medium |
| BUG-05 | `asyncio.wait` on empty set; latent `ValueError` | 🟠 High | 🟡 Medium | 🟢 Low |
| BUG-06 | `\d{4}` year heuristic too broad in shallow check | 🟡 Medium | 🟡 Medium | 🟢 Low |
| BUG-07 | `threading.Lock` can block asyncio event loop | 🟡 Medium | 🟡 Medium | 🟡 Medium |
| BUG-08 | Dead params in `_on_post_scan_finished`; pass-3 timing changed | 🟢 Low | 🟠 High | 🟢 Trivial |
| BUG-09 | `RuntimeError` ambiguity in `PostScanWorker.start()` | 🟢 Low | 🟢 Low | 🟢 Trivial |
| BUG-10 | Batch not atomic; misleading abstraction | 🟡 Medium | 🟢 Low | 🟡 Medium |

### Improvements

| ID | Description | Complexity |
|---|---|---|
| IMP-01 | `OSError` test for `has_video_files_shallow` | Trivial |
| IMP-02 | Test `prefetched_tmdb_episodes` path | Trivial |
| IMP-03 | Unit tests for `PostScanWorker` | Low |
| IMP-04 | Test per-task error in batch writer | Low |
| IMP-05 | Name the batch-size constant | Low |
| IMP-06 | Make ffprobe semaphore configurable | Low |
| IMP-07 | Timeout for TMDB pre-fetch `as_completed` | Low |
| IMP-08 | Extract duplicated `asyncio.wait` loop | Medium |
| IMP-09 | Remove/document dead `None` path in SmartRowService | Medium |
| IMP-10 | Document episode-group + pre-fetch interaction | Medium |
| IMP-11 | Filter disabled libraries before cache rebuild | Low |

---

## Priority Recommendation

**Must fix before merge (data loss / crash risk):**
- BUG-01, BUG-02, BUG-03, BUG-04

**Should fix before merge (correctness/stability):**
- BUG-05, BUG-06, BUG-07, BUG-08

**Can be addressed in follow-up PRs:**
- BUG-09, BUG-10, IMP-01 through IMP-11
