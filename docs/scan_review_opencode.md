# Code Review: Scan Improvements Branch

**Branch:** `scan_improvements`
**Base:** `origin/scan_improvements`
**Review Date:** 2026-07-03
**Reviewer:** Code Review Agent

---

## Executive Summary

This branch implements several performance improvements from the `scan.md` proposals:
- **Proposal C**: Throttle FFprobe (via shallow scan optimization in parser.py)
- **Proposal D**: True Parallel Library Scanning (via `asyncio.wait` with `FIRST_COMPLETED` and inverted task map)
- **Proposal E**: Batch TMDB Season Fetches (via shared `ThreadPoolExecutor` for pre-fetch)
- **Proposal B (partial)**: Offload Post-Scan Processing (via `PostScanWorker`)
- **Proposal H**: Incremental Cache Rebuild (passing affected libraries)

The changes are generally well-structured and address real bottlenecks. However, several **bugs, race conditions, and design issues** were identified that must be fixed before merge.

---

## Bugs & Issues (Organized by Severity)

### 🔴 CRITICAL — Must Fix Before Merge

#### BUG-01: PostScanWorker Reference Leak on Exception Path
**File:** `src/lan_streamer/ui_views/controller.py` (lines 527-569)
**Danger:** Memory leak, worker thread orphaned, subsequent scans may fail
**Likelihood:** Medium (any exception in PostScanWorker or interruption)
**Fix Complexity:** Low

**Issue:** `self._post_scan_worker` is set in `_on_scan_finished` but only cleared in `_on_post_scan_finished`. If:
- PostScanWorker crashes with unhandled exception
- Application shuts down during post-scan
- Signal connection fails silently

The reference is never cleared, leaking the worker and its QThread. Subsequent scans overwrite the reference without cleanup.

**Fix:** Use try/finally or connect to `destroyed` signal, or store in a list and clean up all on new scan start.

```python
# In _on_scan_finished:
self._post_scan_worker = PostScanWorker(...)
self._post_scan_worker.finished.connect(
    lambda result: self._on_post_scan_finished(...)
)
self._post_scan_worker.finished.connect(
    lambda _: setattr(self, '_post_scan_worker', None)  # Always clear
)
self._post_scan_worker.start()
```

---

#### BUG-02: TMDB Prefetch Executor Not Shut Down on Exception
**File:** `src/lan_streamer/backend/scan_worker_all.py` (lines 908-913, 1181-1187)
**Danger:** Thread leak (4 threads per scan run), resource exhaustion on repeated scans
**Likelihood:** High (any exception in `run_async` before finally block)
**Fix Complexity:** Low

**Issue:** The `tmdb_prefetch_executor` is created at line 908 but only shut down in the `finally` block at line 1181. If an exception occurs before the `try` block completes (e.g., in `await self._database_writer.start()` at line 916), the executor is never shut down.

**Fix:** Move executor creation inside the `try` block, or use `try/finally` around just the executor lifecycle.

```python
tmdb_prefetch_executor = None
try:
    tmdb_prefetch_executor = concurrent.futures.ThreadPoolExecutor(...)
    await self._database_writer.start()
    # ... rest of run_async
finally:
    if tmdb_prefetch_executor:
        tmdb_prefetch_executor.shutdown(wait=False)
```

---

#### BUG-03: Shallow Scan Misses Valid Season Folders
**File:** `src/lan_streamer/scanner/parser.py` (lines 108-147)
**Danger:** Data loss — series not discovered, episodes missing from library
**Likelihood:** Medium (common naming conventions not matched)
**Fix Complexity:** Medium

**Issue:** The `has_video_files_shallow` function was optimized by removing the subdirectory file check and adding only `\bs\d+\b` regex. This breaks detection for common naming patterns:

| Folder Name | Matched Before? | Matched Now? |
|-------------|----------------|--------------|
| `Season 1` | ✅ (subdir check) | ✅ (`season` keyword) |
| `S01` | ✅ (subdir check) | ✅ (`\bs\d+\b`) |
| `Season01` | ✅ (subdir check) | ✅ (`season` keyword) |
| `S1` | ✅ (subdir check) | ❌ (no word boundary match) |
| `Season 01` | ✅ | ✅ |
| `series-name-season-1` | ❌ | ✅ (`season` keyword) |
| `Season One` | ❌ | ❌ (no digit) |
| `Specials` | ✅ | ✅ |
| `Extras` | ✅ | ✅ |

**The `\bs\d+\b` pattern fails for:**
- `S1` (no word boundary after `s`)
- `S01E01` style folders
- Any single-digit season without zero-padding

**Fix:** Restore the subdirectory check OR improve the regex:
```python
# Option A: Keep subdir check (safest)
if entry.is_dir(follow_symlinks=True):
    name_lower = entry.name.lower()
    if (season_keywords OR re.search(r"\bs\d+\b", name_lower)
        OR re.search(r"^s\d+$", name_lower)):  # Match S1, S01 at boundaries
        return True
    # Fallback: check immediate children for video files
    try:
        with os.scandir(entry.path) as sub_scanner:
            for sub_entry in sub_scanner:
                if sub_entry.is_file(follow_symlinks=True):
                    _, ext = os.path.splitext(sub_entry.name)
                    if ext.lower() in VIDEO_EXTENSIONS:
                        return True
    except OSError:
        pass

# Option B: Better regex
re.search(r"(?:^|[^a-z])s\d+(?:[^a-z]|$)", name_lower)  # S1, S01, Season 1
```

---

#### BUG-04: `_on_scan_all_finished` Rebuilds ALL Configs, Not Just Affected
**File:** `src/lan_streamer/ui_views/controller.py` (line 866)
**Danger:** Defeats incremental cache rebuild (Proposal H), causes UI lag on large libraries
**Likelihood:** Certain (every global scan)
**Fix Complexity:** Trivial

**Issue:**
```python
affected_libraries = list(self._config.libraries.keys())  # ALL libraries!
```
This passes ALL libraries to `rebuild_for_libraries`, triggering full cache rebuild instead of incremental. The scan worker already tracks `unavailable_directories` and per-library stats — it knows which libraries actually changed.

**Fix:** Pass only libraries that were scanned and had changes:
```python
# In ScanAllLibrariesWorker, expose changed libraries
self.changed_libraries: Set[str] = set()

# In _scan_library_pass result handling:
if result["pass_stats"].get("series_added", 0) > 0 or \
   result["pass_stats"].get("movies_added", 0) > 0 or \
   result["pass_stats"].get("series_updated", 0) > 0 or \
   result["pass_stats"].get("movies_updated", 0) > 0:
    self.changed_libraries.add(library_name)

# In controller:
affected_libraries = list(scan_all_worker.changed_libraries)
```

---

#### BUG-05: Race Condition — Concurrent Scans Overwrite `_post_scan_worker`
**File:** `src/lan_streamer/ui_views/controller.py` (lines 132, 527, 569)
**Danger:** Lost cache rebuild, stale data in UI, worker thread leak
**Likelihood:** Low-Medium (user triggers scan while previous post-scan running)
**Fix Complexity:** Medium

**Issue:** If a new scan starts before the previous `PostScanWorker` finishes:
1. `_on_scan_finished` overwrites `self._post_scan_worker` with new worker
2. Old worker's `finished` signal fires, calls `_on_post_scan_finished`
3. `_on_post_scan_finished` sets `self._post_scan_worker = None`
4. New worker's reference is lost — its `finished` signal never handled

**Fix:** Track workers in a list, or disallow new scans while post-scan is running:
```python
def _on_scan_finished(self, updated_library):
    # ...
    if hasattr(self, '_post_scan_workers'):
        self._post_scan_workers.append(worker)
    else:
        self._post_scan_workers = [worker]

    def on_finished(result):
        self._on_post_scan_finished(result, ...)
        # Remove this specific worker
        self._post_scan_workers = [w for w in self._post_scan_workers if w is not worker]

    worker.finished.connect(on_finished)
```

---

### 🟠 HIGH — Should Fix Before Merge

#### BUG-06: `pytest` Module Check is Fragile
**Files:** `src/lan_streamer/ui_views/controller.py` (lines 363, 871)
**Danger:** Test/production behavior divergence, false positives in CI
**Likelihood:** Medium (any test importing pytest or using pytest fixtures)
**Fix Complexity:** Low

**Issue:** `"pytest" in sys.modules` returns True if pytest was ever imported, not just when running tests. This happens in:
- CI environments with pytest pre-loaded
- IDEs that import pytest for discovery
- Any code that does `import pytest` at module level

**Fix:** Use environment variable or explicit test flag:
```python
# In conftest.py or test setup:
os.environ["LAN_STREAMER_TESTING"] = "1"

# In controller:
is_testing = os.environ.get("LAN_STREAMER_TESTING") == "1"
```

---

#### BUG-07: Task Name Collision Risk (UUID Truncation)
**Files:** `src/lan_streamer/ui_views/controller.py` (lines 381, 902)
**Danger:** Task manager collisions, tasks overwritten/cancelled incorrectly
**Likelihood:** Very Low (8 hex chars = 32 bits, birthday paradox at ~65k tasks)
**Fix Complexity:** Trivial

**Issue:** `uuid.uuid4().hex[:8]` gives only 32 bits of entropy. Use full UUID or add timestamp:
```python
task_name = f"watched_update_{uuid.uuid4().hex}"  # 32 chars
# or
task_name = f"watched_update_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
```

---

#### BUG-08: Inverted Task Map — KeyError If Task Not In Map
**File:** `src/lan_streamer/backend/scan_worker_all.py` (lines 993, 1099)
**Danger:** Crash on task lookup if map/task desync
**Likelihood:** Low (tasks added to map before pending set)
**Fix Complexity:** Low

**Issue:** `library_name = library_task_map[task]` assumes task is in map. If a task is cancelled before being added to map, or added twice, KeyError occurs.

**Fix:** Use `.get()` with fallback:
```python
library_name = library_task_map.get(task)
if library_name is None:
    logger.error(f"Task {task} not found in library_task_map!")
    continue
```

---

#### BUG-09: `run_in_executor` Fallback Creates Unbounded Executors
**File:** `src/lan_streamer/scanner/scan_tv.py` (lines 696-708)
**Danger:** Thread explosion if many series scanned standalone
**Likelihood:** Medium (single-series scans, tests)
**Fix Complexity:** Low

**Issue:** When `tmdb_prefetch_executor` is None, a new `ThreadPoolExecutor(max_workers=4)` is created **per series** via context manager. For a library with 100 series, this creates 100 executors (400 threads) sequentially — not concurrently, but still heavy overhead.

**Fix:** Reuse a module-level executor for fallback, or require caller to provide one:
```python
# Module-level fallback executor (lazy init)
_fallback_tmdb_executor = None
_fallback_lock = threading.Lock()

def _get_fallback_executor():
    global _fallback_tmdb_executor
    if _fallback_tmdb_executor is None:
        with _fallback_lock:
            if _fallback_tmdb_executor is None:
                _fallback_tmdb_executor = ThreadPoolExecutor(
                    max_workers=4, thread_name_prefix="tmdb_prefetch_fallback"
                )
    return _fallback_tmdb_executor

# In scan_series:
if tmdb_prefetch_executor is not None:
    executor = tmdb_prefetch_executor
    should_shutdown = False
else:
    executor = _get_fallback_executor()
    should_shutdown = False  # Don't shutdown shared fallback
```

---

#### BUG-10: SmartRowService Dead Code Removal May Break Callers
**File:** `src/lan_streamer/services/smart_row_service.py` (removed `on_scan_completed`, `_rebuild`, `background_runner`)
**Danger:** Runtime AttributeError if external code calls removed methods
**Likelihood:** Low (internal codebase only)
**Fix Complexity:** Trivial (verify no callers)

**Issue:** The removed methods were public API. Need to verify no external callers exist (grep shows only tests called them, which were updated).

**Fix:** Confirm with `grep -r "on_scan_completed\|_rebuild" --include="*.py" src/` — only tests should appear.

---

### 🟡 MEDIUM — Should Fix Before Merge

#### BUG-11: Missing Type Annotation for `tmdb_prefetch_executor` in `scan_directories`
**File:** `src/lan_streamer/scanner/core.py` (line 101)
**Danger:** Type checker (mypy) may miss issues
**Likelihood:** Certain (mypy will flag)
**Fix Complexity:** Trivial

**Fix:** Add import and type:
```python
from concurrent.futures import ThreadPoolExecutor
# ...
tmdb_prefetch_executor: Optional[ThreadPoolExecutor] = None,
```

---

#### BUG-12: `scan_tv.py` Removed `threading` Import But May Still Be Used
**File:** `src/lan_streamer/scanner/scan_tv.py` (line 6 removed)
**Danger:** If any code in module uses `threading`, runtime ImportError
**Likelihood:** Low (grep shows no remaining uses)
**Fix Complexity:** Trivial (verify)

---

#### BUG-13: `controller.py` Missing Import for `Optional`, `Set`, `List` in Type Hints
**File:** `src/lan_streamer/ui_views/controller.py` (lines 553, 555, 568 use `Optional[Set[str]]`, `List[str]`)
**Danger:** mypy errors if not imported
**Likelihood:** Certain
**Fix Complexity:** Trivial

---

### 🟢 LOW — Can Address in Follow-up

#### BUG-14: `season_callback`/`movie_callback` Not Passed in Metadata-Only Path
**File:** `src/lan_streamer/scanner/core.py` (lines 243-260, 530-546)
**Danger:** Incomplete data persistence if callbacks needed
**Likelihood:** Low (metadata-only path may not need callbacks)
**Fix Complexity:** Low

---

## Improvements (Not Bug Fixes)

### Trivial (Quick Wins)

| ID | Improvement | File | Effort |
|---|---|---|---|
| IMP-01 | Use full UUID for task names | `controller.py:381,902` | 1 min |
| IMP-02 | Add `LAN_STREAMER_TESTING` env var for test detection | `controller.py`, `conftest.py` | 5 min |
| IMP-03 | Add type annotation for `tmdb_prefetch_executor` | `core.py:101` | 1 min |
| IMP-04 | Use `.get()` with fallback for task map lookup | `scan_worker_all.py:993,1099` | 2 min |
| IMP-05 | Document `\bs\d+\b` regex limitation in `has_video_files_shallow` | `parser.py:140` | 2 min |

### Low Complexity

| ID | Improvement | File | Effort |
|---|---|---|---|
| IMP-06 | Pass only changed libraries to cache rebuild in `_on_scan_all_finished` | `controller.py:866` | 10 min |
| IMP-07 | Track PostScanWorkers in list to handle concurrent scans | `controller.py:132,527,569` | 15 min |
| IMP-08 | Move TMDB executor creation inside try block | `scan_worker_all.py:908` | 5 min |
| IMP-09 | Add fallback executor reuse in `scan_tv.py` | `scan_tv.py:696-708` | 10 min |
| IMP-10 | Improve season folder regex in `has_video_files_shallow` | `parser.py:140` | 15 min |

### Medium Complexity

| ID | Improvement | File | Effort |
|---|---|---|---|
| IMP-11 | Extract `run_watched_update` and `run_rebuild_and_finalize` to private methods | `controller.py:369,875` | 20 min |
| IMP-12 | Add integration test for shallow scan with various folder names | `tests/unit/scanner/test_parser.py` | 30 min |
| IMP-13 | Add test for concurrent scan + post-scan race | `tests/unit/ui_views/test_controller.py` | 30 min |

### High Complexity (Architectural)

| ID | Improvement | File | Effort |
|---|---|---|---|
| IMP-14 | True incremental cache rebuild: track changed libraries in ScanAllLibrariesWorker | `scan_worker_all.py`, `controller.py` | 1-2 hrs |
| IMP-15 | Batch DB writes in AsyncDatabaseWriter (Proposal A) | `database_writer.py` | 2-4 hrs |

---

## Mapping to scan.md Proposals

| Proposal | Status | Notes |
|---|---|---|
| **A: Parallelize DB Writer** | ❌ Not implemented | Critical bottleneck remains |
| **B: Offload Post-Scan Processing** | ✅ Partial | `PostScanWorker` created but has ref leak (BUG-01, BUG-05) |
| **C: Throttle FFprobe** | ⚠️ Indirect | Shallow scan optimization helps tree discovery, but ffprobe itself not throttled |
| **D: True Parallel Library Scan** | ✅ Implemented | `asyncio.wait(FIRST_COMPLETED)` + inverted task map |
| **E: Batch TMDB Season Fetches** | ✅ Implemented | Shared executor + `_fetch_tmdb_episodes_parallel` |
| **F: Async Jellyfin Fetch** | ❌ Not implemented | |
| **G: Eliminate N+1 Playback Queries** | ❌ Not implemented | |
| **H: Incremental Cache Rebuild** | ⚠️ Partial | Logic exists but `_on_scan_all_finished` passes ALL libraries (BUG-04) |
| **I: Optimize Tree Discovery** | ✅ Implemented | `has_video_files_shallow` optimization (but BUG-03 regresses detection) |

---

## Test Coverage Assessment

### New Tests Added (Good)
- `test_task_map_lookup.py` — Tests inverted task map (BUG-08 area)
- `test_tmdb_executor_lifetime.py` — Tests executor lifecycle (BUG-02 area)
- `test_post_scan_worker_lifetime.py` — Tests PostScanWorker reference (BUG-01 area)
- Strengthened `test_database_writer.py` assertions

### Missing Tests (Gaps)
1. **Shallow scan folder detection** — No tests for `S1`, `Season01`, `Season One` patterns
2. **Concurrent scan + post-scan race** — No test for BUG-05
3. **Incremental cache rebuild with changed libraries only** — No test for BUG-04 fix
4. **TMDB executor cleanup on exception** — No test for BUG-02
5. **PostScanWorker exception handling** — No test for BUG-01

---

## Recommendation

**DO NOT MERGE** until CRITICAL and HIGH issues are fixed:
1. BUG-01 (PostScanWorker ref leak)
2. BUG-02 (TMDB executor leak on exception)
3. BUG-03 (Shallow scan misses folders)
4. BUG-04 (Full cache rebuild on global scan)
5. BUG-05 (Concurrent scan race)
6. BUG-06 (Fragile pytest detection)

**Can merge after fixes** with MEDIUM issues as follow-up tickets.

---

## Files Modified Summary

| File | Change Type | Risk |
|---|---|---|
| `scan_worker_all.py` | Major refactor (parallel, task map, TMDB executor) | 🔴 High |
| `scan_tv.py` | Feature (TMDB pre-fetch executor param) | 🟠 Medium |
| `parser.py` | Optimization (shallow scan) | 🔴 High (BUG-03) |
| `core.py` | Plumbing (pass through executor) | 🟢 Low |
| `smart_row_service.py` | Cleanup (removed dead code) | 🟢 Low |
| `controller.py` | Feature (PostScanWorker, async watched update) | 🔴 High (BUG-01, 04, 05, 06) |
| `post_scan_worker.py` | New file | 🟠 Medium |
| Tests (6 files) | New/updated tests | 🟢 Low |
