# Code Review: Parallelization & Mtime Caching Changes (Commit Range)

**Review Date**: 2026-06-25
**Reviewer**: Senior Software Engineer
**Base Commit**: `6a324a6691d119cf3ad9040aaf806564be90df91`
**Head Commit**: `88e158b`
**Files Changed**: 51 files, +4602/-1492 lines

---

## 🔴 Critical Issues (Must Fix Before Merge)

### C1. `scan_worker_single.py` — QTimer silently never fires (lines 117–120)

```python
self._flush_timer = QTimer(self)
self._flush_timer.setInterval(50)
self._flush_timer.timeout.connect(self.flush_detail_progress)
self._flush_timer.start()
```

`ScanWorker.run()` overrides `QThread.run()` **without calling `self.exec()`**. Per Qt docs, without `exec()`, no Qt event loop runs in the thread. A `QTimer` cannot fire without an active event loop. The timer's `timeout` signal is **never** delivered.

**Impact**: `flush_detail_progress()` is never called during the scan. Progress events accumulate in `_detail_progress_buffer` for the entire duration (potentially minutes). The UI appears frozen. Only the `finally` block at line 451 flushes at the very end.

**Fix**:
- Option A: Add `self.flush_detail_progress()` calls at strategic points (after Pass 1, after each root directory in Pass 2), mimicking `scan_worker_all.py`.
- Option B: Call `self.exec()` in `run()` and restructure scan as event-driven.
- Option C: Remove the timer entirely and use explicit flush calls only (simplest).

### C2. `ui_views/dialogs/settings.py` — Logging handler runs GUI ops on background thread (lines 1967–1995)

`_on_log_emitted` is connected to the Python `logging` system's handler, which runs on **whatever thread emitted the log message**. The method calls `self.log_display.appendHtml(...)` — a Qt GUI operation — from potentially any background thread (scanner, TMDB, DB writer).

**Impact**: Crash, data corruption, or undefined behavior. Qt GUI operations from non-GUI threads are explicitly undefined behavior.

**Fix**: Use `QMetaObject.invokeMethod(self.log_display, "appendHtml", Qt.QueuedConnection, Q_ARG(str, html))` or emit a custom signal from the logging handler and connect it with `Qt.QueuedConnection` to the slot.

### C3. `ui_views/dialogs/settings.py` — Controller signal leak on dialog close (lines 79–81)

`SettingsDialog.__init__` connects to `controller.global_progress_updated`, `detail_progress_updated`, and `scan_completed` but **never disconnects** these signals when the dialog is closed/rejected/accepted. `closeEvent`, `accept`, and `reject` only call `_disconnect_logging` (log handler removal) — not signal disconnections.

**Impact**: After the dialog closes, controller signals continue invoking slots on a deleted `QObject`. This causes "warnings: QObject::connect: Cannot queue arguments of type '...'" and potential use-after-free crashes.

**Fix**: Call `disconnect()` for each connected signal in `closeEvent`, `accept`, and `reject`.

### C4. `db/library_tv.py` and `db/library_movie.py` — Silent data loss: exceptions swallowed in `save_library()` (lines 647–655, 300–308)

Both `save_library()` (TV) and `save_movie_library()` catch `Exception`, log it, append to `stats["issues"]`, then **return normally** without re-raising. The caller has no reliable way to detect the write failed.

**Contrast**: `save_season_data()` (line 855–858) and `save_movie_data()` (line 443–445) correctly re-raise `raise e`.

**Impact**: Silent data loss on disk-full, constraint violation, or transient DB errors. Data the caller assumes is persisted is silently rolled back.

**Fix**: Re-raise after logging (consistent with per-item saves), or return a clear success/failure indicator that the caller checks.

### C5. `services/file_discovery.py` — False-positive re-scan when `size_bytes` is None (lines 117–131)

When `size_bytes` is `None` for all existing version entries, the list becomes empty after the `None` filter (line 123). `any()` on an empty list returns `False`, so `not any([]) == True` — every file is reported as "changed".

**Impact**: Nullifies mtime-caching optimization for any library where technical metadata hasn't been extracted yet. Every scan pass re-detects every season as "changed".

**Fix**: If `sizes` is empty after filtering, return `False` (unchanged). The mtime-based check at the higher level catches real changes.

---

## 🔴 Critical Thread Safety Issues

### C6. `scan_worker_all.py` — Stats modified without lock in `as_completed` loop (lines 936–940)

```python
for key, value in local_stats.items():
    if not (key.endswith("_scanned") or key.endswith("_skipped")):
        self.stats[key] += value
```

This runs in the **sequential** `as_completed` loop (after all executor threads have completed), so there's no concurrent access from multiple threads here. However, the `self.stats` dict is concurrently updated by callbacks running in executor threads **for the `_scanned` and `_skipped` keys** under `self._lock`. The differentiation between lock-protected and non-lock-protected key sets is fragile.

**Risk**: Future refactoring that adds a counter to both paths creates a silent data race. Currently safe under GIL + disjoint key convention, but brittle.

**Fix**: Hold `self._lock` during this merge (negligible perf cost in the already-sequential loop), or clearly document the convention.

### C7. `scan_worker_single.py` — `partial_result.emit` passed as callback to thread pool (line 372)

```python
callback=self.partial_result.emit,
```

`partial_result` is a `Signal` on `ScanWorker(QThread)`. This passes `emit` as a callable to `scan_directories`, which calls it from `ThreadPoolExecutor` threads. This works because `Qt.AutoConnection` queues the signal, but:

- If `scan_directories` ever calls this synchronously (from same thread), the slot runs in the main thread (via queued connection), creating a re-entrancy hole.
- The slot might run after `ScanWorker` transitions between passes.

---

## 🔴 Critical Performance / Memory Issues

### C8. `metadata_worker_property.py` — Per-item signal emission floods Qt event queue (lines 158–162, 194–196)

Progress signal emitted from `ThreadPoolExecutor` thread **for every single item**:

```python
with self._lock:
    self._completed_count += 1
    self.progress_updated.emit(self._completed_count, self._total_count)
```

For 10,000 items, this posts 10,000 `QMetaCallEvent` objects to the main thread. The lock is held during `emit()`, which is unnecessary.

**Fix**: Batch progress updates — emit every N items (e.g., 100) or at a fixed interval via timer. Or use atomic counter and batch flush.

### C9. `progress_widgets.py` — ScanProgressTree creates QTreeWidgetItem per episode upfront (lines 352–455, 547–580)

Creates `QTreeWidgetItem` for every episode file in the library. For 10k+ episodes, this is a massive widget tree consuming significant memory and slowing initial paint.

**Risk**: Out-of-memory on large libraries, UI freezes during population.

**Fix**: Virtualized tree (QTreeView with model) or lazy loading of items.

### C10. `library_grid.py` — Synchronous image loading on UI thread (lines 598–631, 770–805)

`_assign_item_icon` and `_assign_item_icon_with_size` load `QPixmap` from disk synchronously on the UI thread during `populate_grid`/`populate_combined_view`.

**Impact**: Blocks UI for seconds on large libraries with many posters.

**Fix**: Async image loading in a background thread with placeholder display.

---

## 🟡 High Priority Issues

### H1. `controller.py` — DB writes on UI thread (lines 361–405)

`_on_scan_finished` calls `self._db.save_library()` synchronously on the UI thread. Database writes block the UI.

### H2. `controller.py` — Network I/O on UI thread (lines 878–915, 1000)

`_sync_tmdb_episodes_for_series` calls `self._tmdb_client.get_episodes()` and `get_episode_group_details()` synchronously on the UI thread.

### H3. `db/library_tv.py` — `save_library()` does not persist directory mtimes (lines 522–663)

`save_library()` saves Series/Season/Episode records but **never writes `ScannedDirectory` rows** for series or season directory mtimes. `save_season_data()` and `save_movie_data()` do, but the batch path doesn't.

**Impact**: If the per-item callback path is bypassed, mtimes are lost. Subsequent scans force full re-scan.

### H4. `db/library_tv.py` / `library_movie.py` — Missing explicit `session.commit()` (lines 647, 300)

Rely on `get_session()` context manager implicit commit. Inconsistent with `save_season_data()` and `save_movie_data()` which call explicit `session.commit()`. Works today but fragile — any change to context manager behavior breaks data persistence.

### H5. `db/scanned_directories` — Read-only query opens write transaction (library_shared.py:131–139)

`get_directory_mtime()` uses `get_session()` which calls `session.commit()` on exit. For a read-only query, this acquires a SQLite WAL write-lock unnecessarily. Under concurrent scan threads, this causes needless `SQLITE_BUSY` retries.

### H6. `db/queries_technical_extraction.py` — Silent `except: pass` hides DB errors (lines 265–266)

`has_tech_and_metadata()` catches all exceptions and returns `False`. The caller interprets `False` as "needs extraction" and re-submits, which also fails silently. Creates an infinite retry loop.

**Fix**: Log the exception before `pass`.

### H7. `db/library_shared.py` — `_sync_media_files()` relies on `session.new` internals (lines 46–49, 98–106)

Iterates `session.new` to find in-flight `MediaFile` objects by path. This is a fragile SQLAlchemy internal API dependency. Future SQLAlchemy versions could change the behavior of `session.new`.

**Fix**: Use a local `dict[path, MediaFile]` to track transient objects.

### H8. `metadata_worker_property.py` — `stop()` not called before `join()` on database writer (lines 227–229)

```python
if self.database_writer is not None:
    self.database_queue.put(None)
    self.database_writer.join()
```

The `stop()` method sets `_stop_event`, which the writer thread checks after `queue.get(timeout=0.5)` timeouts. Without `stop()`, `join()` may block up to 500ms waiting for the timeout. Both `scan_worker_all.py` and `scan_worker_single.py` correctly call `stop()` + `put(None)` + `join()`. This is inconsistent.

### H9. `scan_worker_base.py` — `unittest.mock.Mock` imported at runtime on hot path (lines 262–263)

```python
from unittest.mock import Mock
```

Executed **on every single database write wait** (every season, every movie). For 10,000 items, that's 10,000 imports. While cached by `sys.modules`, the name resolution overhead is non-zero.

**Fix**: Move to module level, or use a sentinel pattern.

### H10. `tmdb.py` — TOCTOU race in `download_image` (lines 552–560)

```python
if image_path.exists():
    return str(image_path)
# race: another thread could download same file
with open(image_path, "wb") as f:
    f.write(resp.content)
```

Two threads downloading the same image simultaneously can corrupt the cached file.

**Fix**: Use temporary file + `os.replace()` for atomic writes.

### H11. `database_writer.py` — Unbounded queue (lines 45, 55–77)

`queue.Queue()` has no `maxsize`. Fire-and-forget `save_directory_mtime` tasks can accumulate while the writer processes synchronous tasks. With 10,000 series × 1 mtime task each, the queue can grow large.

**Fix**: Add `maxsize` (e.g., 1000) or log a warning at queue depth thresholds.

### H12. Test flakiness — timing-dependent thread tests

- `test_database_writer.py` — `writer.join(timeout=2.0)` and `task.event.wait(timeout=2.0)` are timeout-based and flaky in CI.
- `test_tmdb.py` — `test_concurrent_requests_are_serialised_by_throttle` and `test_rate_limit_lock_not_held_during_sleep` use `time.sleep(0.02)` for thread coordination (lines 730–830).

### H13. Worker tests don't test QThread behavior

All backend worker tests call `.run()` directly instead of `.start()` + waiting for signals. This misses:
- Signal/slot thread affinity issues
- Race conditions in shared state
- Actual QThread lifecycle
- Event loop integration

Files: `test_scan_workers.py`, `test_scan_worker_all_extended.py`, `test_scan_worker_all_failed.py`, `test_metadata_workers.py`, `test_progress_passes.py`.

---

## 🟡 UI-Specific Issues

### H14. `controller.py` — Worker instances not cleaned up (lines 119–128)

`scan_worker_instance`, `cleanup_worker_instance`, etc. are stored as instance attributes but never explicitly `deleteLater()`ed. If `Controller` is recreated, old workers may linger.

### H15. `controller.py` — Signal congestion (lines 345–359, 634–638)

`detail_progress_batch` signal connects to `_on_detail_progress_batch` which then re-emits `detail_progress_updated` for **each event** in the batch — defeating the batching purpose. High-frequency progress updates can flood the Qt event loop.

### H16. `library_grid.py` — Full rebuild on every library change (lines 544–588, 646–768)

`populate_grid` and `populate_combined_view` destroy and recreate all widget items on every library load. No incremental update.

### H17. `progress_widgets.py` — `paintEvent` performance (lines 155–275, 726–855)

Complex paint operations with O(n) and O(n log n) loops on every frame. No cached layout calculations.

### H18. `controller.py` — Race condition in `trigger_series_refresh` (lines 1173–1185)

There's a check for `self.scan_worker_instance` being running, but between the check and the assignment, the check is not atomic with the worker creation.

---

## 🟡 Database Issues

### H19. `db/queries_technical_extraction.py` — No null guard on `item_identifier` (line 133)

If caller passes `"item_identifier": None`, the `where(Episode.id == None)` becomes `WHERE episodes.id IS NULL` — a no-op but silently skips the update.

**Fix**: Add explicit guard: `if not item_identifier: continue`.

### H20. Inconsistent exception handling across save functions

| Function | Behavior |
|---|---|
| `save_season_data()` | Re-raises after logging |
| `save_movie_data()` | Re-raises after logging |
| `save_library()` | **Swallows** exception |
| `save_movie_library()` | **Swallows** exception |

This inconsistency makes caller-side error handling unpredictable.

---

## 🟢 Low Priority / Observations

### L1. Migration naming — `add_last_scanned_mtime_columns.py` actually creates a new table, not columns

### L2. Old mtime data in JSON metadata blobs not migrated to `scanned_directories` table; first post-upgrade scan does a full scan. Acceptable.

### L3. `scanner/core.py` — Global executor singleton uses double-checked locking. Safe under GIL.

### L4. Nested thread pool architecture: outer pool (library-level) + inner pool (folder-level). With 4 libraries on 8-core CPU: 48 threads max. Acceptable but should be monitored.

### L5. `scan_worker_all.py` — `self.problems = []` reset at line 819. Safe due to Python reference semantics.

### L6. `metadata_worker_property.py` — Double queue creation in `__init__` (line 75) and `run()` (line 80). The first queue is abandoned.

### L7. `scan_worker_all.py` — 4 closures per `_scan_library_pass` capture entire stack frame. ~10,000 closures for 10 libraries × 1000 seasons. Temporary memory pressure, not a leak.

### L8. Test isolation: `test_controller_extended.py` mutates `config.libraries` globally (lines 30–66). Can pollute other tests.

### L9. Tests call private methods directly (`test_progress_passes.py` lines 50–117). Brittle to refactoring.

### L10. `test_directory_mtime_persistence.py` uses hardcoded `/tmp/test_series_commit_regression` paths (line 15–16). Not isolated; can conflict with parallel test runs.

---

## 🔧 Resolution Plan

### Immediate (Pre-Merge)

1. **C1**: Fix QTimer in `scan_worker_single.py` — add explicit `flush_detail_progress()` calls or remove timer
2. **C2**: Fix `settings.py` log handler — marshal GUI operations to UI thread
3. **C3**: Fix `settings.py` — disconnect controller signals on dialog close
4. **C4/C5**: Fix exception swallowing in `save_library()` / `save_movie_library()`
5. **C4 (cont)**: Fix `file_discovery.py` empty `sizes` false-positive
6. **C8**: Batch progress signals in `metadata_worker_property.py`
7. **H3**: Fix `save_library()` to persist directory mtimes
8. **H8**: Add `stop()` call before `join()` in `metadata_worker_property.py`
9. **H9**: Move mock import to module level

### Short-Term (This Sprint)

10. **H1/H2**: Move DB writes and network I/O off UI thread in `controller.py`
11. **H6**: Log the silent `except: pass` in `has_tech_and_metadata()`
12. **H7**: Replace `session.new` iteration with local dict tracking
13. **H10**: Fix TOCTOU race in `download_image`
14. **H11**: Add queue size monitoring / maxsize
15. **H12/H13**: Fix flaky tests — replace timeouts with deterministic synchronization, test actual QThread behavior
16. **H14**: Clean up worker instances in controller
17. **H17**: Fix `has_tech_and_metadata()` silent except

### Medium-Term

18. **C9/C10**: Virtualize tree/grid views for large libraries
19. **H15**: Reduce signal congestion — don't un-batch in `_on_detail_progress_batch`
20. **H16**: Incremental library grid updates instead of full rebuild
21. **H5**: Add read-only session context for queries
22. **H18**: Fix race condition in `trigger_series_refresh`
23. **L8-L10**: Improve test isolation

---

## ✅ Items Reviewed & Verified Clean

| Area | Status |
|---|---|
| Lock ordering | ✅ No deadlocks found (lock hierarchy is clean) |
| TMDB rate limiter | ✅ Correctly implemented (token-bucket, sleep outside lock) |
| SQLAlchemy 2.0 compliance | ✅ No `session.query()` calls anywhere |
| N+1 query patterns | ✅ None found — proper `selectinload`/`joinedload` usage |
| Migration safety | ✅ Clean additive DDL, no data migration risks |
| `save_library()` data paths | ✅ Series/Season/Episode records properly persisted (mtimes missing) |
| `ScannedDirectory` model | ✅ Properly defined with TEXT PK path and FLOAT mtime |
| Global executor singleton | ✅ Thread-safe double-checked locking |
| `_global_scan_executor_lock` usage | ✅ Correct |
| Detailed logging compliance | ✅ Background lifecycle, DB writes, and progress all logged |

---

## 📊 Summary

| Severity | Count |
|---|---|
| 🔴 Critical | 10 |
| 🟡 High | 20 |
| 🟢 Low | 10 |
| **Total** | **40** |

The architectural design (queue-based DB writer, pass-based scanning, lock separation, mtime caching) is fundamentally sound. The most critical defect is the silent loss of UI progress updates in `ScanWorker` due to the absent Qt event loop (C1). The SettingsDialog thread-safety issue (C2) is a potential crash bug. On the database side, the swallowed exceptions (C4) and false-positive re-scan (C5) are the primary data integrity concerns.

Most issues are in the MEDIUM-HIGH range and relate to performance edge cases (unbounded queues, signal flooding, synchronous I/O on UI thread) rather than correctness. The test suite is comprehensive in coverage but many tests don't actually test threading behavior, calling `.run()` directly instead of testing through QThread `.start()`.
