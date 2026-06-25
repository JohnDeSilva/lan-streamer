# 🔍 Code Review: `parallelization_2` Branch

**Baseline Commit**: `6a324a6691d119cf3ad9040aaf806564be90df91`
**Review Target**: pre-merge review of parallel scanning, database writer thread, and signal batching architecture.

---

## 🛠️ Threading Architecture Analysis

The `parallelization_2` branch introduces parallelization across three levels:
1. **Library-level concurrency** via local `ThreadPoolExecutor` instances in `ScanAllLibrariesWorker` and `FilePropertyExtractionWorker`.
2. **Folder-level concurrency** via a shared global `ThreadPoolExecutor` instance in `scanner/core.py`.
3. **Dedicated Database Writer Thread** (`DatabaseWriterThread`) to serialize all database mutations behind a FIFO `queue.Queue`.

### ⚖️ Pros and Cons

#### Pros
- **SQLite Thread Safety**: Consolidating all database writes into a single-threaded queue eliminates SQLite `database is locked` errors and concurrency conflicts without requiring complex database-level locks.
- **UI Responsiveness**: Buffering detail-progress events in a thread-safe list and flushing them via Qt signals periodically (or at the end of the loop) prevents the Qt GUI thread from being flooded by signals from concurrent pool workers.
- **Deadlock Mitigation**: Using separate executor instances for library scanning and folder scanning ensures that library workers (which block waiting for folder scans) do not starve the executor threads needed by folder tasks.
- **Reduced Disk IO (Pre-Scan)**: Reusing existing library metadata loaded from the database to build the pre-scan tree structure (in Pass 2) saves significant disk walks on network shares.

#### Cons / Risks
- **High Concurrency Disk IO**: Removing the worker limit on the global folder executor can result in up to 32 parallel folder scans running concurrently on high-core systems. On traditional HDDs or slow network shares (SMB/NFS), this causes extreme disk head thrashing and network congestion, degrading scan speed compared to a capped worker pool (e.g., 8–12 workers).
- **SQLite Write Bottlenecks**: Because all DB writes must go through the single `DatabaseWriterThread` and wait for completion, a slow drive or long-running query can cause all parallel folder scans to block waiting on `task.event.wait()`, negating the benefits of parallel file discovery.
- **Complexity**: Coordinating nested callbacks (`_season_callback`, `_movie_callback`) across different threads increases the risk of race conditions, memory leaks, and unhandled exceptions.

---

## 🚨 Bugs & Issues (Pre-Merge Review)

### 🔴 Critical Issues

#### 1. Double Counting in Single Library Scanner (`ScanWorker`)
* **File**: [scan_worker_single.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/scan_worker_single.py)
* **Problem**: Unlike `ScanAllLibrariesWorker`, the single-library `ScanWorker` does not track scanned series and movies using unique ID sets. In the callbacks (`_season_callback` and `_movie_callback`), it increments `self.stats["series_scanned"]` and `self.stats["movies_scanned"]` in both Pass 1 and Pass 2. Consequently, the global `self.stats` double-counts every entity processed when both passes run.
* **Impact**: Total summary stats in the log and UI show twice the actual count of series and movies.

#### 2. Missing Skipped Stats in All-Library Scanner (`ScanAllLibrariesWorker`)
* **File**: [scan_worker_all.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/scan_worker_all.py)
* **Problem**: In `run()`, when merging `local_stats` into `self.stats`, the keys ending with `_skipped` (like `series_skipped`, `seasons_skipped`, etc.) are explicitly filtered out to avoid double-counting. However, there is no global unique tracking set for skipped entities.
* **Impact**: The combined `TOTAL ACCUMULATED RUN STATS` logged at the end of the scan will always display `Skipped=0` for series, seasons, episodes, and movies, even if items were skipped.

#### 3. Double Counting in Per-Library Accumulated Reports
* **File**: [scan_worker_all.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/scan_worker_all.py)
* **Problem**: The helper method `_log_scan_summary` computes `accumulated_stats` for each library by calling `merge_stats_dicts_for_report(pass1_stats, pass2_stats)`. This helper simply sums the values. Since scanned and skipped series/movies are incremented in both passes, the per-library report output still double-counts these metrics.
* **Impact**: Logs show incorrect per-library accumulated reports (e.g., 20 scanned series instead of 10).

---

### 🟠 High Severity Issues

#### 4. Progress Bar Ignores Library Name (Premature Updates)
* **File**: [progress_widgets.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/progress_widgets.py)
* **Problem**: The methods `mark_library_done(library_name)` and `mark_library_failed(library_name)` in `LibraryScanProgressBar` iterate over all roots and mark them as `DONE` or `FAILED` regardless of the `library_name` argument:
  ```python
  def mark_library_done(self, library_name: str) -> None:
      for root_dir, root_data in self._roots.items(): # Iterates ALL roots
          root_data["state"] = self.STATE_DONE
  ```
* **Impact**: In a multi-library setup, marking one library as done or failed prematurely updates the visual progress state of sibling libraries.

---

### 🟡 Medium Severity Issues

#### 5. Redundant Per-Item `detail_progress` Signals
* **Files**: [scan_worker_all.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/scan_worker_all.py), [scan_worker_single.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/scan_worker_single.py)
* **Problem**: On every progress flush, both workers emit `detail_progress_batch` (correct) and then loop over the batch to emit the legacy single-item `detail_progress` signal for each item. The controller has already migrated to `detail_progress_batch`.
* **Impact**: Emitting hundreds of redundant Qt signals across threads adds unnecessary performance overhead and CPU load on the main UI thread.

#### 6. Orphaned Dead Code in Controller
* **File**: [controller.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/controller.py)
* **Problem**: The method `_on_scan_all_detail_progress` is no longer wired to any signal since the controller connected to `detail_progress_batch` instead.
* **Impact**: Dead code left in the codebase increases maintenance friction.

---

## 🛠️ Step-by-Step Resolution Plans

### Plan for Issue 1: Fix Double Counting in `ScanWorker` (Single Scanner)
1. In `src/lan_streamer/backend/scan_worker_single.py#L49`, add `self._scanned_series_ids: Set[str] = set()` and `self._scanned_movie_ids: Set[str] = set()` to the constructor.
2. In `run()`, clear these sets.
3. In `_season_callback`, resolve the `series_id` (defaulting to `series_name`) and check if it is in `self._scanned_series_ids`. Only increment `self.stats["series_scanned"]` if it has not been counted yet.
4. Apply the same logic in `_movie_callback` for `self.stats["movies_scanned"]`.
5. Ensure `pass1_stats` and `pass2_stats` continue to track per-pass numbers correctly.

### Plan for Issue 2: Fix Missing Skipped Stats in `ScanAllLibrariesWorker`
1. Add `self._skipped_series_ids: Set[str] = set()` and `self._skipped_movie_ids: Set[str] = set()` to `ScanAllLibrariesWorker.__init__`.
2. In `_season_callback`, when `any_changed` is False, resolve `series_id` and check `self._skipped_series_ids` under lock before incrementing `self.stats["series_skipped"]`.
3. In `run()`, modify the stats-merging logic to skip `_scanned` and `_skipped` keys ONLY if they are not tracked via sets, or ensure that they are correctly merged from the per-library results using a unique tracking scheme.
4. Ensure `self.stats` has correct values for all keys at the end.

### Plan for Issue 3: Fix Double Counting in Per-Library Accumulated Reports
1. Update `_log_scan_summary` in `scan_worker_all.py`.
2. Instead of calling `merge_stats_dicts_for_report` directly on `pass1_stats` and `pass2_stats`, compute the accumulated counts for `series_scanned`, `movies_scanned`, `series_skipped`, and `movies_skipped` by using unique sets or correcting the summation logic.
3. Ensure that it does not double-count metrics when both passes run.

### Plan for Issue 4: Fix Progress Bar Ignoring Library Name
1. Modify `LibraryScanProgressBar` in `src/lan_streamer/ui_views/progress_widgets.py`.
2. Ensure that `_roots` values store a reference or name of the library they belong to (e.g., `root_data["library_name"]`).
3. Update `mark_library_done` and `mark_library_failed` to filter the root directories and folder states matching the target `library_name`:
   ```python
   def mark_library_done(self, library_name: str) -> None:
       for root_dir, root_data in self._roots.items():
           if root_data.get("library_name") == library_name:
               root_data["state"] = self.STATE_DONE
               for f in root_data["folder_states"]:
                   root_data["folder_states"][f] = self.STATE_DONE
       self.update()
   ```

### Plan for Issue 5: Deprecate / Remove Redundant Per-Item Signals
1. Remove the single-event `detail_progress` signal and its emission loop inside `flush_detail_progress()` in both `scan_worker_all.py` and `scan_worker_single.py`.
2. Update the class definitions to remove `detail_progress` from the Qt `Signal` lists.
3. In the UI controller and tests, ensure only `detail_progress_batch` is connected.

### Plan for Issue 6: Clean Up Dead Code in Controller
1. Open `src/lan_streamer/ui_views/controller.py`.
2. Locate the unused method `_on_scan_all_detail_progress` and safely delete it.

### Plan for Issue 7: Cap Folder-Level Concurrency to Sensible Bounds
1. In `src/lan_streamer/scanner/core.py#L42`, restore a sensible limit to `max_workers` in the global `ThreadPoolExecutor` (e.g., `max_workers = min(12, (os.cpu_count() or 4) * 2)`).
2. This avoids disk head thrashing and excessive I/O bottlenecks while maintaining high parallel performance.

---

## 🧪 Recommended Test Improvements

### T1: Test Unique Counting and Skipped Counts
Write a unit test that verifies `ScanWorker` and `ScanAllLibrariesWorker` aggregate unique scanned and skipped metrics correctly without double counting and without zeroing out skipped counts when both passes run.

### T2: Test Progress Bar Library Isolation
Add integration tests using multiple libraries to verify that `LibraryScanProgressBar`'s `mark_library_done` and `mark_library_failed` correctly isolate the target library rather than updating all roots.

### T3: Test Bounded Executor and Teardown
Write a test verifying that the global scan executor respects its thread cap, does not deadlock, and is cleaned up correctly during application teardown.
