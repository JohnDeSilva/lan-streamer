# Code Review: Scan Improvements Branch

**Reviewer:** opencode
**Date:** 2026-07-03
**Branch:** scan_improvements (13 commits since v0.40.0)
**Files changed:** 30 files, ~3,040 additions, ~348 deletions

---

## Executive Summary

This branch implements most of the proposals from `docs/scan.md`:
- **Proposal A** (parallelize DB writer): Batched writes with exclusive task isolation
- **Proposal B** (offload post-scan): Background `PostScanWorker`
- **Proposal C** (throttle ffprobe): Threading semaphore
- **Proposal D** (true parallel scanning): `asyncio.wait(FIRST_COMPLETED)`
- **Proposal E** (batch TMDB season fetches): Parallel pre-fetch
- **Proposal G** (N+1 playback queries): `selectinload` eager loading
- **Proposal H** (incremental cache rebuild): `changed_libraries` tracking
- **Proposal I** (optimize tree discovery): `has_video_files_shallow`

Overall the changes are well-structured, the commit history is clean, and tests are comprehensive. Below are the issues found, organized by severity.

---

## BUGS & ISSUES

### BUG-01 (🔴 High Danger, Low Likelihood, Medium Complexity): PostScanWorker emits `scan_completed` before `_on_scan_finished` returns

**Location:** `src/lan_streamer/ui_views/controller.py:1631-1637`

**Issue:** When `scanned_library_name` is falsy (edge case), `_on_scan_finished` now returns early and directly emits `scan_completed` or calls `trigger_runtime_extraction`. Previously it would also do this, but now the early-return path has been added for the case where `scanned_library_name` is None/empty. The issue is that `_on_scan_and_update_scan_finished` calls `_on_scan_finished` and expects the returned `(changed_season_ids, changed_movie_ids)` tuple. This still works because the return values are now set before the early-return paths.

**Likelihood:** Very low — only triggers when `current_library_name` is empty after a scan.
**Fix:** Add a safety assertion or conditional check.

---

### BUG-02 (🔴 High Danger, Medium Likelihood, High Complexity): `_on_scan_all_finished` runs cache rebuild via async task that captures `scan_all_worker` by reference after the function scope exits

**Location:** `src/lan_streamer/ui_views/controller.py:1686-1718`

**Issue:** The inner coroutine `run_rebuild_and_finalize()` accesses `scan_all_worker` which is a function parameter. This works in CPython because closures over locals keep them alive, but it's fragile. More importantly, `scan_all_worker` could theoretically be mutated or replaced by the time the coroutine actually runs (since it's scheduled as a task).

Additionally, `self._running_pass3_after_scan`, `self._running_cleanup_after_scan`, and `self._scan_had_unavailable_directories` are all read inside this async closure. If another scan is triggered between scheduling and execution, state could be inconsistent.

**Likelihood:** Low in practice because scan-all is typically the only scan operation.
**Fix:** Capture all needed state into local variables before the closure.

```python
# Fix: snapshot all mutable state
running_pass3 = self._running_pass3_after_scan
running_cleanup = self._running_cleanup_after_scan
had_unavailable = self._scan_had_unavailable_directories
changed_seasons = getattr(scan_all_worker, "changed_season_ids", None)
changed_movies = getattr(scan_all_worker, "changed_movie_ids", None)

async def run_rebuild_and_finalize() -> None:
    changed_hashes = await run_in_executor(...)
    ...
    if running_pass3:
        self.trigger_runtime_extraction(changed_seasons, changed_movies)
    elif running_cleanup:
        ...
```

---

### BUG-03 (🟠 High Danger, Low Likelihood, Medium Complexity): `PostScanWorker.start()` fallback creates `finished` signal but never connects it to cleanup

**Location:** `src/lan_streamer/backend/post_scan_worker.py:205-213`

**Issue:** When `start()` detects no running event loop, it falls back to `_run_sync()` and emits `finished` directly. This bypasses the `AsyncWorkerBase._run_wrapper()` exception handling. The `_run_sync()` method has its own try-catch for exceptions at the signal site in the controller, so this is not a crash bug. However, the synchronous fallback path does not handle `asyncio.CancelledError` or propagate errors through the `error` signal.

**Likelihood:** Low — only triggers when `start()` is called outside the qasync event loop context.
**Fix:** Wrap `_run_sync()` in try/except in the fallback path:

```python
def start(self) -> None:
    try:
        asyncio.get_running_loop()
        super().start()
    except RuntimeError:
        try:
            result = self._run_sync()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
```

---

### BUG-04 (🟠 High Danger, Low Likelihood, Low Complexity): `_on_scan_finished` still returns `changed_season_ids/changed_movie_ids` but callers may not expect the new PostScanWorker offloading

**Location:** `src/lan_streamer/ui_views/controller.py:1637`

**Issue:** `_on_scan_finished` now returns early (line 1637) with the changed IDs *before* the PostScanWorker has actually persisted data to the database. The caller `_on_scan_and_update_scan_finished` captures these returned values and passes them to the cleanup worker. The cleanup worker runs in the background and may start before `PostScanWorker` finishes its DB save. If the cleanup worker tries to read data that hasn't been saved yet, it will see stale data.

**Likelihood:** Medium — `scan_and_update` triggers this path, which chains cleanup after scan.
**Fix:** Postpone the cleanup chain start until after `_on_post_scan_finished` completes, OR have the PostScanWorker signal back the changed IDs so the cleanup chain is ordered correctly.

---

### BUG-05 (🟠 High Danger, Low Likelihood, Low Complexity): `BoundedSemaphore(3)` in `file_property_scanner.py` has no timeout

**Location:** `src/lan_streamer/scanner/file_property_scanner.py:14, 69-70, 130-131`

**Issue:** `threading.BoundedSemaphore.acquire()` blocks indefinitely by default. If all 3 slots are occupied by hanging ffprobe processes (e.g., stuck on a network filesystem), the fourth call blocks forever. Combined with `subprocess.run()` having its own 5-10s timeout, this means 3 stuck processes can block the entire scanner thread pool.

**Likelihood:** Medium — can happen with NFS/CIFS timeouts on large libraries.
**Fix:** Use `acquire(timeout=30)` and log a warning, or use a semaphore with a context manager and timeout.

```python
_ffprobe_semaphore = threading.BoundedSemaphore(3)

def get_detailed_file_info(file_path: str) -> Dict[str, Any]:
    if not _ffprobe_semaphore.acquire(timeout=30):
        logger.warning("ffprobe semaphore timeout, skipping %s", file_path)
        return get_stub_file_info(file_path)
    try:
        ...
    finally:
        _ffprobe_semaphore.release()
```

---

### BUG-06 (🟠 High Danger, Medium Likelihood, High Complexity): AsyncDatabaseWriter batching breaks exclusive task response order

**Location:** `src/lan_streamer/backend/database_writer.py:228-271`

**Issue:** The batching loop processes queue items in order but when it encounters an exclusive task (`EXCLUSIVE_ACTIONS`) during batching, it stores it in `exclusive_task`, then processes the batch first, then the exclusive task. However, tasks that arrived *after* the exclusive task but are still in the queue (not yet peeked by `get_nowait()`) will be processed *before* the exclusive task in the next iteration. This violates FIFO ordering semantics. While this is intentional (exclusive tasks are long-running HTTP calls), the ordering of non-exclusive tasks relative to exclusive tasks is not deterministic.

More critically: if a non-exclusive task is enqueued between two exclusive tasks, it will be batched with the first exclusive task's batch. But the exclusive task is removed from the batch by the `elif next_task.action in self._EXCLUSIVE_ACTIONS` check. So the non-exclusive task stays in the batch, and the exclusive task runs separately after the batch. This means a non-exclusive task that arrived *after* an exclusive task could be processed *before* it. This could cause issues if the non-exclusive task depends on data that the exclusive task was supposed to populate.

**Likelihood:** Low in current usage (exclusive tasks are only cast/image fetches, non-exclusives are DB saves; no known data dependency).
**Fix:** Either document this as intentional (with a strong comment) or implement priority queue behavior where exclusive tasks are always drained before the next batch of non-exclusive ones.

---

### BUG-07 (🟡 Medium Danger, Medium Likelihood, Medium Complexity): `LAN_STREAMER_TESTING` env var creates two code paths that are tested differently

**Location:** `src/lan_streamer/ui_views/controller.py:1509-1529, 1682-1718` also `tests/conftest.py:37`

**Issue:** The `LAN_STREAMER_TESTING=1` env var (set in `conftest.py:37`) causes test code to take the synchronous path while production code takes the async path. This means:
1. Tests don't actually exercise the async code that runs in production
2. Any async-specific bugs (race conditions, missing `await`, event loop issues) are invisible to tests
3. The testing env var leaks into all test files via conftest

**Likelihood:** 100% — every test runs with this env var.
**Fix options:**
- **Preferred:** Remove the testing env var and make the watched-update path always async. The tests that need synchronous execution should use `run_until_complete` on the created task.
- **Acceptable:** Keep the testing env var but add dedicated async integration tests that unset it.
- **Minimal:** Document in AGENTS.md that async paths are not covered by unit tests.

---

### BUG-08 (🟡 Medium Danger, Medium Likelihood, Low Complexity): `_on_post_scan_finished` double-emits `scan_completed` in some paths

**Location:** `src/lan_streamer/ui_views/controller.py:1639-1659, 1611-1618`

**Issue:** When `_on_scan_finished` is called and `scanned_library_name` is set, it creates a PostScanWorker and registers `_on_post_scan_done` as the finished callback. This callback calls `_on_post_scan_finished` which emits `scan_completed` (line 1653). However, if `self._doing_scan_and_update` is True AND `self._running_pass3_after_scan` is also True, the `_on_post_scan_finished` method will call `trigger_runtime_extraction` (line 1650) which starts the runtime extraction worker. But `_on_scan_finished` was called from `_on_scan_and_update_scan_finished`, which also chains to the cleanup worker. The cleanup worker completion may race with the PostScanWorker completion.

**Likelihood:** Medium — triggers in the scan-and-update flow.
**Fix:** Review the full chain of `_on_scan_and_update_scan_finished` → `_on_scan_finished` → PostScanWorker → `_on_post_scan_finished` → runtime extraction → cleanup → final completion. Ensure no double `scan_completed` emissions.

---

### BUG-09 (🟡 Medium Danger, Low Likelihood, Low Complexity): `_fetch_tmdb_episodes_parallel` uses `as_completed` but never sorts results back into original season order

**Location:** `src/lan_streamer/scanner/scan_tv.py:1106-1117`

**Issue:** `prefetched` dict is populated in completion order, not original season order. This is fine because downstream code (`prefetched_season_episodes.get(season_name)`) uses dict lookup. However, the TMDB API results contain episode lists with `episode_number` fields that need to be ordered — the episode ordering is preserved within each list, but the per-season iteration in `scan_series` (Phase 4, line 1177) processes seasons in `seasons_to_process` order. Since `prefetched` is a dict with `get()` lookups, this is not a problem.

**Verdict:** Not actually a bug, but worth noting in review.

---

### BUG-10 (🟡 Medium Danger, High Likelihood, Low Complexity): `_on_scan_all_finished` ignores `_doing_scan_and_update` flag in the async rebuild path

**Location:** `src/lan_streamer/ui_views/controller.py:1686-1718`

**Issue:** The `run_rebuild_and_finalize()` closure captures `self` directly but does NOT check or reset `self._doing_scan_and_update`. The old code (removed in this diff) was a simple `self._smart_row_service.on_scan_completed(affected_libraries=None)` followed by `trigger_runtime_extraction` or `trigger_global_cleanup`. The new code goes through `run_in_executor` first, then does the chaining. If `_doing_scan_and_update` was True when the scan-all finished, the old code would still chain correctly. The new code may not handle this properly because `_on_scan_all_finished` was primarily designed for the global scan (triggered from settings), not the scan-and-update flow.

**Fix:** Add explicit check for `_doing_scan_and_update` in the async closure.

---

### BUG-11 (🟢 Low Danger, Low Likelihood, Low Complexity): `has_video_files_shallow` OSError in fallback sub-scanner silently returns without checking subdirectories of other entries

**Location:** `src/lan_streamer/scanner/parser.py:1020-1028`

**Issue:** The fallback sub-scanner catches OSError and `continue`s to the next entry. However, if a subdirectory exists and is readable, but has no video files, it still continues correctly. The only issue is if an OSError occurs on a subdirectory that *does* contain video files — the function incorrectly reports False. This is a false negative, which only means that particular directory tree won't be scanned. Since `has_video_files_shallow` is used only for tree discovery (deciding which top-level dirs to scan), a false negative means a valid series/movie directory might be missed.

**Likelihood:** Low — OSError on readable directories is rare.
**Fix:** Log the OSError at debug level so it's diagnosable.

---

### BUG-12 (🟢 Low Danger, Medium Likelihood, Low Complexity): `_get_fallback_executor` creates a module-level singleton that is never shut down

**Location:** `src/lan_streamer/scanner/scan_tv.py:1062-1075`

**Issue:** The fallback executor `_fallback_tmdb_executor` is created lazily when `scan_series` is called without a `tmdb_prefetch_executor` parameter. This executor is NEVER shut down — not even at application exit. This leaks 4 threads for the lifetime of the process.

**Likelihood:** High — any single-library scan or `ScanSingleSeriesWorker` triggers this.
**Fix:** Either:
- Remove the fallback: always require `tmdb_prefetch_executor` to be passed
- Or register `atexit` cleanup for the fallback executor
- Or set `thread_name_prefix` with a recognizable name and document that these threads persist

---

## CONS

1. **Test coverage gap for async code paths (BUG-07)** — The `LAN_STREAMER_TESTING` env var means ~95% of controller tests run the synchronous path, while production uses async. This is the most significant testing concern.

2. **Increased complexity in `_on_scan_finished`** — The function grew from ~30 lines to ~80+ lines with nested closures, signal wiring, and two different code paths. This makes it harder to reason about.

3. **Batching non-determinism (BUG-06)** — The batch drain order of exclusive vs. non-exclusive tasks is not identical to enqueue order, which could surprise future developers.

4. **Fallback executor leak (BUG-12)** — The module-level singleton executor pattern is inconsistent with the strategy of passing `tmdb_prefetch_executor` through the call chain.

5. **`see_sentinel` misspelling** — on line 229 of database_writer.py, the variable is named `saw_sentinel` which is correct English (past tense of "see" is "saw"), but note that the sentinel handling at line 271-272 could be surprising: if a sentinel is seen during batching, the `_run` loop breaks immediately, discarding any tasks still in the queue. This seems correct but worth highlighting.

---

## PROS

1. **Excellent test coverage** — The branch adds 5 new test files and extends several existing ones, covering edge cases and new behavior.

2. **Clean separation of concerns** — `PostScanWorker` is a well-factored class that cleanly separates DB persistence and cache rebuild from UI thread logic.

3. **Thread safety awareness** — The `SmartRowService._cache_lock`, `scan_worker_all._lock`, and the `exclusive_task` isolation in `AsyncDatabaseWriter` all show good threading hygiene.

4. **Graceful degradation** — The `start()` fallback in `PostScanWorker` (sync mode when no event loop) and the `is_testing` checks show awareness of different runtime contexts.

5. **Incremental improvements** — The `changed_libraries` tracking means post-scan cache rebuilds do less work, and the `as_completed` pattern means fast libraries aren't blocked by slow ones.

6. **Memory safety** — The `_post_scan_workers` list prevents garbage collection of in-flight workers, and the cleanup in signal callbacks prevents leaks.

7. **No observable regression** — Existing tests pass, and the fundamental behavior is preserved.

---

## IMPROVEMENTS (Non-Bug)

### Improvement 1 (Easy): Log structured data instead of f-strings

**Location:** Various files

**Current pattern:**
```python
logger.info(f"Pre-fetched {len(episodes)} TMDB episodes for season '{season_name}'")
```

**Better pattern (structured logging):**
```python
logger.info("Pre-fetched TMDB episodes for season", extra={"count": len(episodes), "season": season_name})
```

This enables log aggregation tools to parse structured fields.

---

### Improvement 2 (Easy): Add docstring to `_execute_batch` explaining ordering guarantees

**Location:** `src/lan_streamer/backend/database_writer.py:171`

The method processes tasks sequentially within a batch but has a comment about the exclusive task being removed. A docstring explaining the FIFO-within-batch but non-deterministic-across-exclusive-boundaries semantics would help future readers.

---

### Improvement 3 (Medium): Extract `_on_scan_finished` closures into named methods

**Location:** `src/lan_streamer/ui_views/controller.py:1610-1630`

The nested closures `_on_post_scan_done` and `_on_post_scan_error` are defined inside `_on_scan_finished` but contain non-trivial logic. Extracting them into private methods would reduce nesting and make unit testing easier.

---

### Improvement 4 (Medium): Add shutdown for fallback executor at application exit

**Location:** `src/lan_streamer/scanner/scan_tv.py:1062-1075`

Either remove the fallback entirely (require all callers to pass an executor) or add `atexit.register(_fallback_tmdb_executor.shutdown)` to clean up threads.

---

### Improvement 5 (Hard): Integration tests for async code paths

Create a test suite that unsets `LAN_STREAMER_TESTING` and exercises the actual async paths. This would catch event-loop-specific issues like missing yields, coroutine never awaited, or `CancelledError` not being handled. Even 3-4 integration tests would significantly improve confidence.

---

### Improvement 6 (Easy): Avoid `from lan_streamer.system.async_utils import run_in_executor` inside closures

**Location:** `src/lan_streamer/ui_views/controller.py:1516, 1680`

The `run_in_executor` import is repeated inside two closures. Move it to the top-level imports (or at least to the function scope).
