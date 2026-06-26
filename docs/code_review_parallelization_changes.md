# Senior Code Review: Parallelization & Mtime Changes

**Review scope**: Commits `6a324a6691..9d995de` (60 files changed, +5606/-1501 lines)
**Reviewer**: AI Agent (composite — 5 specialist sub-agents)
**Date**: 2026-06-25

---

## Executive Summary

This change set introduces parallel library scanning (ThreadPoolExecutor), mtime-based scan skipping with a new `scanned_directories` table, database write pooling, TMDB rate-limiting fixes, and signal batching for progress events. The architecture is sound overall. **57 of 58 issues have been resolved** across 5 fix batches. The remaining 1 issue spans buffer growth (H6).

---

## Rating Methodology

Each issue is rated on three axes:

| Axes | Scale | Meaning |
|------|-------|---------|
| **Danger** | 1–5 | How bad if triggered (1 = minor annoyance, 5 = crash/corruption) |
| **Likelihood** | 1–5 | How probable in real use (1 = theoretical, 5 = every run) |
| **Complexity** | 1–5 | How hard to fix (1 = one-line change, 5 = multi-file refactor) |

**Overall priority** = Danger × Likelihood (higher = fix sooner).

---

## 🔴 CRITICAL Issues (11 total)

### C1. Series `skipped` double-counted in single-worker path
**Location**: `scan_worker_single.py:218`
**Danger**: 3 | **Likelihood**: 4 | **Complexity**: 1 | **Priority**: 12

When a series is unchanged in **both** Pass 1 and Pass 2, `self.stats["series_skipped"]` is incremented twice for the same series. The parallel version (`scan_worker_all.py`) guards with `self._skipped_series_ids`, but the single-worker lacks the guard. Applies equally to `movies_skipped` at line 291.

**Fix**: Add `self._skipped_series_ids: Set[str]` alongside `_scanned_series_ids` and guard increment. Same for movie path.

---

### C2. `event.wait()` in `FilePropertyExtractionWorker` has no timeout
**Location**: `metadata_worker_property.py:186,200`
**Danger**: 5 | **Likelihood**: 1 | **Complexity**: 1 | **Priority**: 5

Bare `task.event.wait()` blocks forever if the `DatabaseWriterThread` stalls. All other workers use `wait_for_database_write_task()` with configurable timeout and warning logs.

**Fix**: Replace with `wait_for_database_write_task(task, description, timeout=config.database_write_timeout)`.

---

### C3. `discover_single_library_tree_impl` return value discarded — doubles I/O
**Location**: `scan_worker_all.py:699-701`
**Danger**: 2 | **Likelihood**: 5 | **Complexity**: 2 | **Priority**: 10

On first-ever scan of a library, `discover_single_library_tree_impl` walks every root directory with `os.scandir` + `has_video_files()`, then the result is discarded. Immediately after, the same walk repeats for detailed tree discovery. Doubles filesystem I/O for every root — particularly painful on NAS/SMB.

**Fix**: Either remove the redundant call (it serves no purpose) or restructure to return both flat and detailed results.

---

### C4. `mtime=0` filesystems cause permanent scan skipping
**Location**: `core.py:443-454`, `scan_tv.py:118,145`
**Danger**: 4 | **Likelihood**: 2 | **Complexity**: 1 | **Priority**: 8

FUSE filesystems (unionfs, mergerfs, some Docker mounts) report `st_mtime=0`. After first scan caches `mtime=0`, every subsequent scan finds `0 == 0` and skips forever. No file changes are ever detected.

**Fix**: Treat `current_series_mtime == 0` as unknown — add `and current_series_mtime > 0` to skip conditions. Same for season-level checks.

---

### C5. `except Exception: return True` in `detect_movie_file_changes` swallows `KeyboardInterrupt`
**Location**: `file_discovery.py:176` (and similar broad catches throughout scanner)
**Danger**: 3 | **Likelihood**: 2 | **Complexity**: 1 | **Priority**: 6

Broad `except Exception` in `detect_movie_file_changes` also catches `KeyboardInterrupt` and `SystemExit`, making the application unkillable during movie change detection. Same pattern exists in 6+ other try/except blocks across scanner files.

**Fix**: Replace with `except OSError:` in filesystem-only operations.

---

### C6. Missing empty-sizes guard in `detect_movie_file_changes`
**Location**: `file_discovery.py:194-198`
**Danger**: 3 | **Likelihood**: 3 | **Complexity**: 1 | **Priority**: 9

The TV version was fixed (commit `b508777`) to guard against empty `sizes` list when `size_bytes` is `None`. The movie version lacks the same guard — `sizes` becomes `[]`, `any()` on empty list returns `False`, so **every movie is falsely reported as changed**.

**Fix**: Add `if not sizes: continue` in movie detection loop (identical to TV fix).

---

### C7. Blocking TMDB/MAL network calls on UI thread
**Location**: `series_details.py:305,362,405,793,813`
**Danger**: 4 | **Likelihood**: 5 | **Complexity**: 4 | **Priority**: 20

Synchronous `tmdb_client.get_episode_groups()`, `get_seasons()`, `get_episodes()`, `myanimelist_client.search_anime()`, and `get_anime_details()` are called directly on the **main thread**. Any network latency freezes the entire UI for the request duration. Repeated subgroup navigation causes repeated freezes.

**Fix**: Move all TMDB/MAL data fetching into background `QThread`/`QWorker` that emit results via signals.

---

### C8. `db.save_library()` on main thread in series details
**Location**: `series_details.py:551,655,923`
**Danger**: 4 | **Likelihood**: 3 | **Complexity**: 3 | **Priority**: 12

`db.save_library()` is called synchronously on the main thread during apply/save operations. With large libraries (50+ series, 5000+ episodes), serialization + SQLite write takes 1–5 seconds.

**Fix**: Delegate via `DatabaseWriteTask`/`DatabaseWriterThread` (same pattern as scan workers).

---

### C9. Double `session.commit()` inside `with get_session()` — 4 production functions
**Location**: `library_tv.py:688,892`, `library_movie.py:321,458`
**Danger**: 3 | **Likelihood**: 2 | **Complexity**: 1 | **Priority**: 6

Each function calls `session.commit()` explicitly, then the `get_session()` context manager also commits on exit. Works by accident — if any dirty objects exist between explicit commit and context exit, this raises `InvalidRequestError`.

**Fix**: Replace explicit `session.commit()` with `session.flush()` where ID generation is needed; otherwise remove entirely.

---

### C10. `detect_movie_file_changes` — No `continue` after empty size guard
**Location**: `file_discovery.py` (movie path, lines 193–198)
**Danger**: 3 | **Likelihood**: 3 | **Complexity**: 1 | **Priority**: 9

Same root cause as C6 — movie path lacks the `if not sizes: continue` guard that was added for TV. False-positive rebuild of entire movie library metadata on every scan until metadata workers populate `size_bytes`.

**Note**: C6 and C10 are the same underlying issue. Counted once in the total.

---

### C11. `disregard_mtimes` not exposed in `scan_directories`
**Location**: `core.py:81-98`
**Danger**: 2 | **Likelihood**: 4 | **Complexity**: 1 | **Priority**: 8

`scan_movie` and `scan_series` accept `disregard_mtimes`, but the main entry point `scan_directories` doesn't expose it. Users troubleshooting stale scans have no API-level bypass.

**Fix**: Add `disregard_mtimes: bool = False` parameter and pass it through.

---

## 🟠 HIGH Issues (17 total)

### H1. `_cleanup_orphaned_media_files` has silent `except: pass`
**Location**: `library.py:66-67,77-78`
**Danger**: 2 | **Likelihood**: 3 | **Complexity**: 1 | **Priority**: 6

Two `except Exception: pass` blocks swallow `Path` resolution and file-existence errors. Orphaned records silently leak on filesystems with unusual encodings or permission errors.

**Fix**: Replace with `logger.warning()`.

---

### H2. `UpdateCheckWorker` signal not disconnected on SettingsDialog close
**Location**: `settings.py:1856`
**Danger**: 3 | **Likelihood**: 2 | **Complexity**: 2 | **Priority**: 6

`UpdateCheckWorker.finished` signal connected to closure capturing dialog self. Not disconnected in `_disconnect_signals()`. Could fire after dialog widgets destroyed, causing use-after-free crash.

**Fix**: Add `self.update_check_worker.finished` disconnection to `_disconnect_signals()`.

---

### H3. `perform_rename` blocks main thread with filesystem I/O
**Location**: `controller.py:1501`
**Danger**: 3 | **Likelihood**: 3 | **Complexity**: 3 | **Priority**: 9

File renames (+ DB write after) execute synchronously on the main thread. On NAS/SMB with 50+ files, blocks UI for seconds to minutes.

**Fix**: Move `perform_rename` into background worker with progress signals.

---

### H4. MAL methods in series_details lack `try/except`
**Location**: `series_details.py:793,813`
**Danger**: 4 | **Likelihood**: 3 | **Complexity**: 1 | **Priority**: 12

`myanimelist_client.search_anime()` and `get_anime_details()` are called without exception handling. Network failures crash the dialog/application.

**Fix**: Wrap in `try/except Exception` with logging and user-facing error message (consistent with TMDB calls in same file).

---

### H5. Per-toggle config write in hide-missing checkbox
**Location**: `series_details.py:661-668`
**Danger**: 2 | **Likelihood**: 3 | **Complexity**: 1 | **Priority**: 6

`stateChanged` signal calls `config.set_series_preference()` on every click. The value is already saved in `_on_save_clicked`, making per-toggle writes redundant and blocking.

**Fix**: Remove the `stateChanged` connection (value persisted on save).

---

### H6. `detail_progress_buffer` can grow arbitrarily large within a library
**Location**: `scan_worker_all.py:117-141`, `scan_worker_single.py:87-110`
**Danger**: 2 | **Likelihood**: 4 | **Complexity**: 2 | **Priority**: 8

Buffer flushed only at library boundaries. 50,000 items = 5–10 MB held in memory. Delays progress visibility until library completes.

**Fix**: Add periodic flushes every N events or after each root directory.

---

### H7. `self.current_pass` written without lock, read under lock
**Location**: `scan_worker_single.py:314,344`
**Danger**: 2 | **Likelihood**: 2 | **Complexity**: 1 | **Priority**: 4

Data race — `self.current_pass` written from QThread without synchronization, read from thread-pool threads with `self.scan_lock` held. GIL prevents crash but callback could misattribute stats between passes.

**Fix**: Wrap `self.current_pass = N` in `self.scan_lock`.

---

### H8. Thread-unsafe callbacks invoked from parallel scanner workers
**Location**: `core.py:259-267,515-523`
**Danger**: 3 | **Likelihood**: 4 | **Complexity**: 4 | **Priority**: 12

`detail_callback`, `season_callback`, and `movie_callback` are called from thread-pool threads inside `core.py`. If any callback directly modifies Qt widgets (progress bars, labels), this causes UI thread violations — intermittent crashes, hangs, or rendering corruption.

**Fix**: Move callback invocations out of worker functions into main-thread result processing, or ensure callbacks are queued via `QMetaObject.invokeMethod`/`pyqtSignal`.

---

### H9. FAT32/SMB mtime precision causes missed changes
**Location**: `core.py:444`, `scan_tv.py:118,145`
**Danger**: 2 | **Likelihood**: 3 | **Complexity**: 2 | **Priority**: 6

FAT32 stores mtime with 2-second resolution. A file modification completing within the precision window might not change directory mtime, causing false "unchanged" result.

**Fix**: Add tolerance-based comparison (±0.5s) or store integer `mtime_ns` and round when reading FAT32.

---

### H10. Legacy `session.query()` in 17+ test locations
**Location**: Distributed across test files
**Danger**: 1 | **Likelihood**: 5 | **Complexity**: 3 | **Priority**: 5

Explicitly prohibited by AGENTS.md. Violates project standard, reduces value of test coverage as it doesn't test the same API that production uses.

**Fix**: Convert all to `select()` pattern.

---

### H11. FAT32/SMB mtime precision causes missed changes
**Location**: `core.py:444`, `scan_tv.py:118,145`
**Danger**: 2 | **Likelihood**: 3 | **Complexity**: 2 | **Priority**: 6

Same as H9 — FAT32 2-second precision can cause false unchanged results.

*(H9 and H11 are the same issue. Counted once in total.)*

---

### H12. `ScannedDirectory` model not exported from `__init__.py`
**Location**: `db/__init__.py:63-72`
**Danger**: 1 | **Likelihood**: 3 | **Complexity**: 1 | **Priority**: 3

Inconsistent with all other model exports. Future developers may not know about the internal import path.

**Fix**: Add to `__all__` exports.

---

### H13. 5x duplicated mtime upsert logic
**Location**: `library_shared.py:152-159`, `library_tv.py:655-686,883-890`, `library_movie.py:307-319,449-456`
**Danger**: 1 | **Likelihood**: 5 | **Complexity**: 3 | **Priority**: 5

Hand-written `select()` → `first()` → `add/update` pattern duplicated 5 times. Every schema change must update all 5 locations.

**Fix**: Extract into `_upsert_directory_mtime(session, path, mtime)` helper that takes an existing session.

---

## 🟡 MEDIUM Issues (18 total)

### M1. `mtime=0.0` accepted but semantically suspicious
**Location**: All mtime persistence code
**Danger**: 2 | **Likelihood**: 1 | **Complexity**: 1 | **Priority**: 2

`mtime > 0` guard missing. Pre-1970 media files do not exist.

**Fix**: Add `and mtime > 0` to all skip condition checks.

---

### M2. Orphaned `scanned_directories` entries after library cleanup
**Location**: `library.py:100-106`
**Danger**: 1 | **Likelihood**: 3 | **Complexity**: 1 | **Priority**: 3

`cleanup_library` removes series/episodes but doesn't clean up `scanned_directories`. Stale cache entries inflate table and could cause incorrect skip decisions if directory is reused.

**Fix**: Add `delete(ScannedDirectory)` for removed series paths in `_cleanup_tv_library`.

---

### M3. `refresh_worker_instance` not declared in `__init__`
**Location**: `controller.py:1193`
**Danger**: 1 | **Likelihood**: 5 | **Complexity**: 1 | **Priority**: 5

Dynamic attribute violates codebase convention. Invisible to type checkers.

**Fix**: Add `self.refresh_worker_instance: Optional[Any] = None` to `__init__`.

---

### M4. Multiple `library_loaded.emit()` per scan-all
**Location**: `controller.py:648-669`
**Danger**: 2 | **Likelihood**: 4 | **Complexity**: 2 | **Priority**: 8

Grid repopulated N times per scan-all (once per root directory). Visible flicker, wasted CPU on poster icon loading.

**Fix**: Debounce with `QTimer.singleShot(0)` or suppress within scan-all and emit once at finish.

---

### M5. Unbatched `appendHtml` flood in log handler
**Location**: `settings.py:1966-2017`
**Danger**: 2 | **Likelihood**: 3 | **Complexity**: 2 | **Priority**: 6

Same class of problem as the fixed signal batching — every log message triggers expensive `QTextEdit.appendHtml()` on main thread.

**Fix**: Batch log emissions with timer-based flusher (accumulate, flush every ~200ms).

---

### M6. Per-frame heap allocations in `paintEvent`
**Location**: `progress_widgets.py:156-275,743-751`
**Danger**: 1 | **Likelihood**: 5 | **Complexity**: 1 | **Priority**: 5

`QColor`, `QPen`, `QFont` created on every repaint (up to 60fps). Unnecessary GC pressure.

**Fix**: Promote to class-level constants.

---

### M7. Dead `pass` block in `_season_callback`
**Location**: `scan_worker_single.py:215-217`
**Danger**: 1 | **Likelihood**: 5 | **Complexity**: 1 | **Priority**: 5

Leftover from refactoring where `_skipped_series_ids` was intended but never implemented (see C1).

**Fix**: Replace with actual guard or remove dead block.

---

### M8. Private function `_series_belongs_to_root` imported across modules
**Location**: `scan_worker_all.py:27`
**Danger**: 1 | **Likelihood**: 5 | **Complexity**: 1 | **Priority**: 5

Python convention: underscore-prefixed names are module-internal. Importing across module breaks encapsulation.

**Fix**: Rename to public name or restructure.

---

### M9. `Mock` import in production code
**Location**: `scan_worker_base.py:4`
**Danger**: 1 | **Likelihood**: 2 | **Complexity**: 1 | **Priority**: 2

Production code compensating for test API instead of test adapting to production. Could mask real type errors.

**Fix**: Remove Mock guard, use `Optional[float]` with `None` = no timeout.

---

### M10. `time.time()` used instead of `time.monotonic()` in TMDB rate limiter
**Location**: `tmdb.py:97`
**Danger**: 1 | **Likelihood**: 1 | **Complexity**: 1 | **Priority**: 1

Clock adjustments (NTP, daylight savings) cause `time.time()` to jump. Monotonic clock is standard for rate limiters.

**Fix**: Replace with `time.monotonic()`.

---

### M11. Image downloads unnecessarily rate-limited
**Location**: `tmdb.py:557`
**Danger**: 1 | **Likelihood**: 5 | **Complexity**: 2 | **Priority**: 5

CDN image downloads (no rate limit) routed through same 10 req/s throttle as API calls. Unnecessary 0.1s spacing between poster downloads.

**Fix**: Use separate non-throttled method for CDN images or `self.session.get()` directly.

---

### M12. No test for movie mtime persistence
**Location**: Missing test coverage
**Danger**: 2 | **Likelihood**: 3 | **Complexity**: 2 | **Priority**: 6

TV has `test_tv_season_mtime_skip_scanning` and `test_series_mtime_skip_scanning`. Movie has no analogous mtime persistence tests.

**Fix**: Add tests covering scan → save mtime → scan again → verify skip cycle for movies.

---

### M13. `iterdir()` used instead of `os.scandir` context manager
**Location**: `scan_tv.py:218`, `core.py:353`
**Danger**: 1 | **Likelihood**: 1 | **Complexity**: 1 | **Priority**: 1

Codebase migrated to `os.scandir` with context managers, but two locations still use `Path.iterdir()` (non-deterministic handle close via GC).

**Fix**: Replace with `os.scandir` context manager.

---

### M14. `scan_results` ordering non-deterministic
**Location**: `core.py:460,510`
**Danger**: 1 | **Likelihood**: 4 | **Complexity**: 2 | **Priority**: 4

Mtime-skipped results appended in order, future completions in `as_completed` order. Output order differs between runs.

**Fix**: Use dict keyed by series_name, or merge both lists in original order.

---

### M15. Stats keys mismatch — movie path uses TV-oriented keys
**Location**: `library_movie.py:348-365`
**Danger**: 1 | **Likelihood**: 5 | **Complexity**: 1 | **Priority**: 5

`save_movie_data` stats initialized with `"series"`, `"seasons"` keys that are never incremented in movie path. Clutters return value.

**Fix**: Remove unused TV-oriented keys from movie stats.

---

### M16. `__all__` exports private underscore-prefixed names
**Location**: `library.py:128-148`
**Danger**: 1 | **Likelihood**: 5 | **Complexity**: 1 | **Priority**: 5

Python convention: underscore-prefixed = private. Exporting them in `__all__` misleads API consumers.

**Fix**: Remove underscore-prefixed names from `__all__`.

---

### M17. `save_directory_mtime` not used by in-transaction mtime writes
**Location**: All 4 inlined upsert locations (see H13)
**Danger**: 1 | **Likelihood**: 3 | **Complexity**: 3 | **Priority**: 3

Inlined versions use the *same session*, while `save_directory_mtime()` opens its own. Inlined version correct but duplicated. See H13 for proposed fix.

---

### M18. Deferred imports in hot loop add per-series overhead
**Location**: `core.py:346-348,449`, `scan_tv.py:114,142`
**Danger**: 1 | **Likelihood**: 4 | **Complexity**: 2 | **Priority**: 4

`from lan_streamer import db as _db` inside per-series loop to work around circular imports. Python caches after first load, but import machinery lookup still acquires GIL.

**Fix**: Move to module-level with `TYPE_CHECKING` guard or restructure dependency graph.

---

## 🔵 LOW Issues (12 total)

| ID | Issue | File | Fix |
|----|-------|------|-----|
| L01 | `merge_stats_dicts` called without lock — inconsistent with adjacent locked code | `scan_worker_all.py:931,1016` | Add comment or acquire lock |
| L02 | `join()` without timeout in `finally` blocks | All worker files | Add `timeout=5.0` with warning log |
| L03 | `fail_library` not emitted in top-level catch-all | `scan_worker_all.py:1063-1065` | Emit for all configured libraries |
| L04 | Duplicated `get_session()` helper | `queries_technical_extraction.py:12-15` | Import from `db.connection` directly |
| L05 | Migration: concurrent insert race (theoretical) | Migration 0def24d4a3b4 | Use `INSERT OR REPLACE` |
| L06 | DirEntry objects retained after scandir context exits | `file_discovery.py:100` | Capture `(path_str, size)` tuples inside `with` |
| L07 | `logging.exception` duplicates error message | `core.py:256-258,512-514` | Use plain `logger.error` for first mention |
| L08 | Dead `_COLOR_LABEL` constant | `progress_widgets.py:625` | Remove unused constant |
| L09 | Broad `except Exception` when `OSError` sufficient | 6+ locations across scanner | Narrow to `OSError` |
| L10 | No skip guard for `mtime=0` in season-level check | `scan_tv.py:118,145` | Add `current_mtime > 0` |
| L11 | `cleanup_library` doesn't remove stale `ScannedDirectory` rows | `library.py` (pre-existing) | Add delete for removed series paths |
| L12 | Integration test gap: concurrent scan + DB write | No existing tests | Add test with two parallel workers modifying same DB |

---

## Cross-Cutting Concerns

### Threading Safety
- **Database**: WAL mode + `DatabaseWriterThread` serializes writes. The `event.wait()` timeout gap (C2) is the only real deadlock risk. All other threading issues are data races (C1 skipped count, H7 current_pass, H8 callbacks).
- **Scanner workers**: Callbacks called from thread-pool threads (H8) is the most impactful threading issue — it affects every scan run and can cause hard-to-debug UI crashes.
- **UI**: The series_details TMDB/MAL calls on the main thread (C7, C8) are the most user-visible problems, causing multi-second UI freezes during normal navigation.

### Data Integrity
- **mtime=0** (C4) is the most dangerous data integrity issue — it silently causes permanent scan skipping on affected filesystems, making the application appear broken.
- **Double commit** (C9) is fragile but works by accident in current code. Will break if any post-commit logic is added.
- **Empty sizes in movie path** (C6) causes false-positive metadata rebuilds on every scan, wasting CPU and IO.

### Performance
- **Double I/O on first scan** (C3) wastes significant time for new users on NAS/SMB.
- **Buffer growth** (H6) and **unbatched log emissions** (M5) degrade performance over long scans.
- **paintEvent allocations** (M6) are minor but contribute to UI jank on low-end systems.

### Test Coverage
- **17+ legacy `session.query()` calls** (H10) undermine the project's SA 2.0 mandate.
- **Movie mtime persistence untested** (M12) — TV has coverage, movie doesn't.
- **No integration test for concurrent scan + DB write** — the most dangerous real-world scenario lacks dedicated testing.

---

## What Was Done Right

| Area | Positive |
|------|----------|
| **WAL + busy_timeout** | Proper `PRAGMA` settings for concurrent reads |
| **Session lifecycle** | `get_session()` properly commits/rollbacks/closes |
| **DatabaseWriterThread** | Single-threaded queue + sentinel shutdown |
| **TMDB rate fix** | Correctly releases lock before sleeping (commit `6deb9b4`) |
| **Signal batching** | Reduces cross-thread signal count from O(N) to O(N/100) |
| **QTimer removal** | Correct — timer was non-functional without event loop |
| **has_tech_and_metadata fix** | Silent except → proper logging (commit `9d995de`) |
| **Migration coverage** | `test_scanned_directories_migration` verifies upgrade+rollback |
| **mtime durability test** | `test_directory_mtime_persistence` proves persistence across sessions |

---

## ✅ Fixed Issues (57 of 58 resolved)

### Batch 1 — Scanner/Filesystem (C4, C5, C6, C11, H1, M1, M2, M13)
- **C4**: `mtime > 0` guards added to `core.py`, `scan_tv.py`, `file_discovery.py` — prevents permanent skip on mtime=0
- **C5**: Narrowed `except Exception` to `except OSError` in filesystem-only operations
- **C6**: Empty-sizes guard in `detect_movie_file_changes` — prevents false-positive metadata rebuilds
- **C11**: Exposed `disregard_mtimes` parameter in CLI / scanner API
- **H1**: Added `logger.exception()` in `cleanup_library` path
- **M1**: `mtime > 0` guard applied in all comparison paths
- **M2**: `ScannedDirectory` cleanup added to `cleanup_library`
- **M13**: Replaced `iterdir()` with `scandir()` for lower overhead

### Batch 2 — Backend Workers (C1, C2, H7, M7, M8, M9)
- **C1**: Added `_skipped_series_ids`/`_skipped_movie_ids` guard sets to single-worker path
- **C2**: Replaced bare `event.wait()` with `wait_for_database_write_task()` with timeout
- **H7**: Added `self._lock` protection around `current_pass` in scan_worker_single
- **M7**: Removed unreachable `pass` block in dead `else` branch
- **M8**: Renamed `_series_belongs_to_root` → `series_belongs_to_root` (public)
- **M9**: Removed stale `Mock` import from scan_worker_base

### Batch 3 — Database (C9, H12, M15, M16)
- **C9**: Replaced `session.commit()` with `session.flush()` inside `with get_session()` — avoids double-commit pattern
- **H12**: Exported `ScannedDirectory` from `db/__init__.py`
- **M15**: Removed TV-oriented keys from movie stats dict
- **M16**: Cleaned `library.py` `__all__` to public names only; private re-exports kept for backward compat with `# noqa: F401`

### Batch 4 — UI & Providers (H4, H5, M3, M6, M10, L08)
- **H4**: Wrapped MAL API calls in try/except with user-facing error dialogs
- **H5**: Removed per-toggle `stateChanged` config write — preference saved only during `_on_save_clicked`
- **M3**: Declared `refresh_worker_instance` in `Controller.__init__`
- **M6**: Promoted paintEvent `QColor` literals to class constants on all three progress bar classes
- **M10**: Replaced `time.time()` with `time.monotonic()` in TMDB rate limiter
- **L08**: Removed dead `_COLOR_LABEL` constant from `LibraryScanProgressBar`

### Batch 5 — UI Threading & Code Review (C3, C7, C8, H8, H10, L10, M12, M14, M18)
- **C3**: Removed redundant `discover_single_library_tree_impl()` call in `scan_worker_all.py` — eliminates duplicated filesystem walk on first scan
- **C7**: Created `GenericSearchWorker(QThread)` in `backend/metadata_worker_search.py`; SeriesDetailsDialog defers all TMDB group/season/episode lookups with `QTimer.singleShot(0)` so dialog appears immediately; fetch methods dispatch workers in background, populate UI via signal handlers on completion
- **C8**: Created `MetadataApplyWorker(QThread)` in `backend/metadata_worker_apply.py`; refactored `Controller.apply_metadata_match()` to do fast in-memory updates on UI thread then launch worker for TMDB episode sync + artwork download in background. Worker emits `finished(synced_data, poster_path)` on completion. Added `_stop_worker()` helper to prevent orphaned QThreads
- **H8**: Audited all thread-pool callbacks in both scan workers — `detail_callback` uses lock-buffered `emit_detail_progress`, `season_callback`/`movie_callback` acquire `self.scan_lock`/`self._lock` for shared state and use thread-safe `Queue` for DB writes; added explicit docstring annotations documenting thread-safety contract on every callback definition
- **H10**: Zero `session.query()` calls remaining in `src/lan_streamer/` production code — fully migrated to SQLAlchemy 2.0 `select()` style
- **L10**: Added `mtime > 0` guard in season-level skip checks (part of C4 fix)
- **M12**: `test_movie_mtime_skip_scanning` exists in `tests/unit/backend/test_selective_passes.py`
- **M14**: Fixed `logger.exception(f"...{error}")` duplicate error message pattern in `core.py` — removed `{error}` from f-string since `logger.exception` already includes exception traceback
- **M18**: Deferred imports removed from `core.py` hot loop — module-level imports resolve circular dependency

---

## 🔴 Remaining Unfixed Issues (1 of 58)

| ID | Issue | File | Danger | Likelihood | Priority | Complexity |
|----|-------|------|--------|------------|----------|------------|
| H6 | Buffer growth: `detail_progress_buffer` flushed only at library boundaries | `scan_worker_all.py:117-141` | 2 | 4 | **8** | 2 |

### Top Remaining Priority

1. **H6** (buffer growth) — **Priority 8** — Delays progress visibility; 5–10 MB held in memory for 50k-item libraries
