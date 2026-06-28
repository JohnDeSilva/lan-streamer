# Async Migration Plan: Threading → Asyncio

## Overview

This plan outlines the staged migration from the existing `QThread`-based threading model to an `asyncio`-native architecture. The primary driver is enabling a **scheduled background scan service** that periodically checks for new/changed media files using mtime tracking, without blocking the UI or requiring always-on background threads.

**Key constraint**: This is a PySide6 (Qt) application. We will use the [`qasync`](https://github.com/CabbageDevelopment/qasync) library to bridge the Qt event loop with `asyncio`, allowing both systems to coexist on the main thread while asyncio manages concurrent I/O.

---

## Current Architecture (Baseline)

- **17 QThread subclasses** across the codebase (scanning, Jellyfin, metadata, FFmpeg, updates, caching)
- **1 threading.Thread** (`DatabaseWriterThread`) for serialized DB writes
- **4 ThreadPoolExecutors** for parallelism within QThreads
- **Zero `async`/`await` usage**
- **No scheduled/periodic scanning** — scans are always user-initiated
- **mtime tracking exists** but is directory-level only, used for early-exit optimization
- **Signal chain**: Worker → Controller signals → UI slots (Qt's cross-thread signal mechanism)

### Threading Pain Points

| Issue | Location |
|---|---|
| Nested threads (QThread → ThreadPoolExecutor) | `scan_worker_all.py`, `metadata_worker_property.py` |
| QThread timeout stop issues | `threading_manager.py:WorkerSlot.stop()` — weakref deferred cleanup |
| No structured cancellation | `isInterruptionRequested()` polling |
| Synchronous network calls in threads | `providers/tmdb.py`, `providers/jellyfin.py` |
| Blocking subprocess (ffprobe) | `scanner/file_property_scanner.py` |
| Serialized DB writes as bottleneck | `backend/database_writer.py` |
| No periodic scheduling | Entirely user-triggered scans |

---

## Target Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Qt Event Loop                      │
│  ┌──────────────────────────────────────────────┐   │
│  │              qasync Integration                │   │
│  │  ┌──────────────────┐  ┌──────────────────┐  │   │
│  │  │   UI Components  │  │  asyncio Tasks   │  │   │
│  │  │ (QWidgets, etc.) │◄─┤  (Scan, Meta,   │  │   │
│  │  │                  │  │   Network, Sub-  │  │   │
│  │  │  Controller      │  │   process)       │  │   │
│  │  │  (Signals/Slots)  │  │                  │  │   │
│  │  └──────────────────┘  └──────────────────┘  │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### Key Design Goals

1. **Single event loop** — Qt and asyncio share the main thread via `qasync`
2. **Cooperative concurrency** — asyncio tasks yield at I/O boundaries (network, subprocess, DB)
3. **Scheduled scan service** — asyncio task that runs on configurable interval, checks mtimes, triggers metadata resolution
4. **Gradual migration** — each stage is backward-compatible, deployable, and testable
5. **Preserve signal interface** — UI components remain Qt signals/slots; asyncio tasks feed results back through Controller signals

---

## Stage 0: Foundation — Dependencies & Event Loop Setup

**Goal**: Install `qasync`, set up the asyncio event loop integration, and provide utilities without changing any business logic.

### Changes

#### 0.1 Dependency Addition
- Add `qasync` to `pyproject.toml`
- Add `aiohttp` as the async HTTP client (replacement for `requests` over multiple stages)
- Add `aiofiles` if needed for async file I/O
- Run `uv lock`

#### 0.2 Event Loop Bootstrap
- Modify `src/lan_streamer/main.py`:
  - Import `qasync` and wrap `QApplication.exec_()` in `qasync.run()`:
    ```python
    async def main():
        loop = asyncio.get_event_loop()
        # Initialize application
        ...
        await qasync.run(app.exec_())

    if __name__ == "__main__":
        asyncio.run(main())
    ```
- Add an `async_task_manager.py` at `src/lan_streamer/system/`:
  - `AsyncTaskManager(QObject)` — owns the event loop reference
  - `create_task(coroutine, name, on_done_callback)` — wraps `asyncio.ensure_future`
  - `cancel_task(name)` — cancels a named task
  - `cancel_all()` — cancels all tasks (called on shutdown)
  - `get_task(name)` — returns the task handle for status checks
  - `schedule_interval(coroutine_factory, interval_seconds, name)` — periodically creates/runs a task

#### 0.3 Async Utilities Module
- Create `src/lan_streamer/system/async_utils.py`:
  - `run_in_executor(callable, *args)` — runs a sync callable in the default thread pool executor
  - `to_async(callable)` — decorator wrapping sync → async conversion
  - `async_lock` / `async_semaphore` — asyncio synchronization primitives
  - `AsyncDatabaseSession` — context manager for async DB access (placeholder, wired in Stage 3)

#### 0.4 Wire Shutdown
- Modify `controller.worker_manager.stop_all` to also call `async_task_manager.cancel_all()`
- Connect `application_instance.aboutToQuit` to async shutdown sequence

### Tests
- Add tests verifying `qasync` integration doesn't break app startup/shutdown
- Unit tests for `AsyncTaskManager` scheduling, cancellation, lifecycle
- Unit tests for `async_utils` helpers

### Commit
`feat(async): add qasync integration and AsyncTaskManager foundation`

---

## Stage 1: Scheduled Scan Service

**Goal**: Implement a background scheduled scanner that periodically checks for new/changed files using a hierarchical modification-time (mtime) delta check, executing fine-grained async metadata resolution tasks without blocking the user interface.

### Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                     ScheduledScanService                          │
│                                                                   │
│  ┌──────────────┐       ┌─────────────────┐                       │
│  │ Hourly Timer │ ────▶ │ Scan Lock Check │                       │
│  └──────────────┘       └─────────┬───────┘                       │
│                                   │ (Acquire)                     │
│                                   ▼                               │
│                          ┌─────────────────┐                      │
│                          │ Directory delta │                      │
│                          │  check (mtime)  │                      │
│                          └────────┬────────┘                      │
│                                   │ (Deltas Found)                │
│                                   ▼                               │
│                          ┌─────────────────┐                      │
│                          │  Async Task     │                      │
│                          │  Dispatcher     │                      │
│                          └────────┬────────┘                      │
│                                   │                               │
│         ┌─────────────────────────┼────────────────────────┐      │
│         ▼                         ▼                        ▼      │
│  ┌──────────────┐         ┌──────────────┐         ┌──────────────┐ │
│  │ Filename     │         │ FFprobe      │         │ TMDB lookup  │ │
│  │ parsing task │         │ metadata     │         │ (Semaphore)  │ │
│  └──────┬───────┘         └──────┬───────┘         └──────┬───────┘ │
│         │                        │                        │       │
│         └────────────────────────┼────────────────────────┘       │
│                                  ▼                                │
│                        ┌──────────────────┐                       │
│                        │ Database Writer  │                       │
│                        │ Queue (serialize)│                       │
│                        └──────────────────┘                       │
└───────────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────┐
  │ Controller Signal │
  │ scan_completed    │
  │ progress events   │
  └──────────────────┘
```

### Changes

#### 1.1 Create `src/lan_streamer/system/scheduled_scan_service.py`
- `ScheduledScanService(QObject)`:
  - **Configuration**: Reads scan interval from config (default 3600s = 1 hour).
  - **`start()`**: Registers a periodic asyncio task via `AsyncTaskManager.schedule_interval()`.
  - **`stop()`**: Cancels the periodic task.
  - **`scan_now(force_refresh=False)`**: Manually triggers an immediate scan.
  - **`_run_scheduled_scan()`**: Core async method:
    1. Check if a global scan lock is already acquired (via `asyncio.Lock` or a status flag). If locked, log a warning and skip execution to prevent concurrent scan collisions.
    2. Read library configurations from the database configuration.
    3. Perform hierarchical, filesystem-aware modification time checks across libraries.
    4. Collect the list of newly added or updated files.
    5. For each file, dispatch a fine-grained async metadata resolution task.
    6. Emit progress and completion signals to the controller.

#### 1.2 Hierarchical Modification-Time (mtime) Delta Check
Directories are scanned using a two-tiered check to account for the fact that filesystem modification times do not propagate recursively (i.e., modifying a file in a subdirectory does not update the parent folder's modification time):
- **Series Folder Check**: Fetch the cached modification time for the series directory from the database. Perform `os.stat` on the directory.
  - **If Changed**: Perform an `os.scandir` on the series directory to identify if any season folders were added or removed, updating the internal lists.
  - **If Unchanged**: Bypass listing the series directory. Retrieve the known season folders for this series directly from the database cache.
- **Season Folder Check**: For each season folder, check its filesystem modification time against the database.
  - **If Unchanged**: Skip walking the files in this season directory entirely.
  - **If Changed**: Walk the files in that season directory to detect new, modified, or deleted files.
- **Movie Folder Check**: Similarly, inspect movie folders. If a movie folder's modification time is unchanged, skip walking its contents.

#### 1.3 Fine-Grained Async Metadata Resolution Pipeline
Instead of wrapping massive synchronous scan operations in a thread pool executor, rewrite the resolution process into lightweight, parallel asyncio tasks. For each new or updated file discovered:
- **Parser Task**: Parse the filename to extract episode, season, or movie metadata.
- **FFprobe Subprocess Task**: Spawn an asynchronous subprocess via `asyncio.create_subprocess_exec` to fetch video duration, codecs, and resolution. Protect this with `subprocess_semaphore = asyncio.Semaphore(4)` to prevent high disk and CPU utilization.
- **External Metadata Provider Task**: Use the async provider client (`aiohttp`) to lookup missing TMDB details. Protect this with `network_semaphore = asyncio.Semaphore(10)` to prevent API rate-limiting blocks.
- **Database Write Serialization**: Enqueue metadata records to the `AsyncDatabaseWriter` queue.

#### 1.4 Wire into Controller
- Add `scheduled_scan_service` to `Controller.__init__()`
- Connect `scheduled_scan_service` signals to existing Controller slots (`_on_detail_progress_batch`, `_on_scan_completed`, etc.)
- Add `Controller.start_scheduled_scans()` and `Controller.stop_scheduled_scans()` methods
- Add `Controller.trigger_scan_now()` for manual ad-hoc scans (this leverages the same async pipeline with a `force_scan` parameter)
- Settings UI: Add scan interval configuration in General Settings or Library Setup tab

#### 1.5 Completion Chaining
When the scheduled scan discovers changed files and resolves their metadata:
- Emit `scan_completed` signal (reuse existing slot)
- Optionally chain into `trigger_runtime_extraction()` (Pass 3) if files changed
- Optionally chain into `trigger_global_cleanup()` if stale records found

### Tests
- Unit tests for `ScheduledScanService` scheduling, lock acquisition, and cancellation.
- Unit tests for hierarchical modification time check (verifying file edits in subdirectories trigger delta updates).
- Integration test: verify that background scanning does not block the main user interface event loop.
- Existing scanner tests must still pass (no regressions).

### Commit
`feat(scanner): add ScheduledScanService with mtime-aware periodic scanning`

---

## Stage 2: Async Network Providers

**Goal**: Convert TMDB, Jellyfin, OpenSubtitles, and MyAnimeList providers from synchronous `requests` to `aiohttp` for non-blocking HTTP I/O.

### Changes

#### 2.1 Create Async HTTP Client
- `src/lan_streamer/providers/http_client.py`:
  - `AsyncHTTPClient` singleton — owns `aiohttp.ClientSession`
  - `get(url, headers, params)`, `post(url, json, headers)` — async methods
  - Token bucket rate limiting (async version of existing TMDB rate limiter)
  - Retry with exponential backoff
  - Request/response logging at DEBUG level
  - Connection pool management (limits, timeouts)

#### 2.2 Async TMDB Client
- Create `src/lan_streamer/providers/tmdb_async.py`:
  - `AsyncTMDBClient` — mirror of existing `TMDBClient` but fully async
  - Same methods: `search_series`, `search_movie`, `get_series_by_id`, `get_movie_by_id`, `get_episodes`, `get_episode_groups`, `get_episode_group_details`, `download_image`
  - Uses `AsyncHTTPClient` internally
  - Preserves existing caching logic (image caching to disk, response caching)
  - Token bucket rate limiter explicitly async (uses `asyncio.Semaphore` + timestamps)

#### 2.3 Async Jellyfin Client
- Create `src/lan_streamer/providers/jellyfin_async.py`:
  - `AsyncJellyfinClient` — async version of `JellyfinClient`
  - Methods: `get_jellyfin_correlation_data`, `fetch_watched_episodes`, `mark_as_watched`, `mark_as_unwatched`
  - Pagination uses async iteration

#### 2.4 Async OpenSubtitles & MyAnimeList
- Create `src/lan_streamer/providers/opensubtitles_async.py` and `myanimelist_async.py`:
  - Async versions of existing clients
  - Used by metadata workers and background tasks

#### 2.5 Dual-Provider Pattern
- Keep existing sync providers for backward compatibility
- Expose factory functions: `get_tmdb_client(async=False)` → returns sync or async client based on flag
- Update `__init__.py` in `providers/` to re-export both versions

#### 2.6 Wire Async Providers into Scheduled Scan
- When `ScheduledScanService._run_scheduled_scan()` needs TMDB metadata, use `AsyncTMDBClient` instead of wrapping sync `TMDBClient`
- This eliminates the need for `run_in_executor` for network calls
- Parallel metadata requests use `asyncio.gather()` instead of `ThreadPoolExecutor`

**Visual: Parallel Metadata Resolution**

```python
# Before (sync wrapped in executor):
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(tmdb_client.get_episodes, series_identifier, season_number)
               for series_identifier, season_number in season_identifiers]
    for future in as_completed(futures):
        result = future.result()

# After (native async):
async with AsyncTMDBClient() as tmdb_client:
    tasks = [tmdb_client.get_episodes(series_identifier, season_number) for series_identifier, season_number in season_identifiers]
    results = await asyncio.gather(*tasks)
```

### Tests
- Unit tests for `AsyncHTTPClient` (mocked aiohttp responses)
- Unit tests for `AsyncTMDBClient` search, details, episode groups
- Integration test: verify async client produces identical results to sync client for same inputs
- Existing provider tests must still pass (sync clients unchanged)

### Commit
`feat(providers): add async HTTP providers with aiohttp`

---

## Stage 3: Async Database Operations

**Goal**: Move database reads off the main thread and into async context, configuring SQLite for Write-Ahead Logging (WAL) mode to permit concurrent read operations while serialization writes are managed by an async queue.

### Changes

#### 3.1 Async Database Session Manager
- Create `src/lan_streamer/db/async_session.py`:
  - `AsyncDatabaseSession` — wraps SQLAlchemy's `AsyncSession` (using `sqlalchemy.ext.asyncio`)
  - `async with database_session() as session:` — async context manager
  - **Important**: SQLite + asyncio requires `aiosqlite` and `sqlalchemy[asyncio]`

#### 3.2 Migration to `sqlalchemy[asyncio]` + `aiosqlite`
- Add `aiosqlite` and `sqlalchemy[asyncio]` dependencies
- Update database initialization in `src/lan_streamer/db/`:
  - Create both sync `Engine` (for existing code) and async `AsyncEngine`
  - Configure the database connection string with WAL parameters: `journal_mode=WAL`
  - `get_async_session()` — returns `AsyncSession`
  - `get_sync_session()` — returns `Session` (existing behavior)
- **Critical**: SQLAlchemy async session with SQLite requires `pysqlite` >= 3.x and the `aiosqlite` driver. Must verify compatibility.

#### 3.3 Async Read Operations
- Replace ad-hoc `get_directory_mtime()` calls with async versions
- Create async equivalents of key read functions:
  - `async_get_directory_mtime(path)` → `AsyncSession.get()`
  - `async_load_library(name)` → async version of `load_library()`
  - `async_load_movie_library(name)` → async version of `load_movie_library()`
- These are used by `ScheduledScanService` for mtime pre-checks and library data loading

#### 3.4 Async Write Queue
- Replace `DatabaseWriterThread` (threading.Thread + queue.Queue) with asyncio-based write queue:
  - `AsyncDatabaseWriter` — `asyncio.Queue` of write tasks
  - `async write(task)` — puts task on queue
  - Background coroutine that drains the queue sequentially
  - Same serialization guarantee as current system (single writer)
  - Replace `DatabaseWriteTask` with typed dataclasses + callbacks

#### 3.5 Remove `wait_for_database_write_task()`
- Current pattern: scan worker submits a task and blocks on `threading.Event`
- New pattern: scan worker `await`s the write completion directly
- This allows the scanner to yield control of the event loop rather than blocking a thread

### Compatibility Strategy
- All existing sync DB operations continue working unchanged
- New async operations use the same underlying tables/ORM models
- Both engines (sync + async) are initialized from the same configuration
- Migration happens incrementally: callers switch to async versions when convenient

### Tests
- Unit tests for `AsyncDatabaseSession` CRUD operations
- Unit tests for async write queue ordering and error handling
- Integration test: concurrent async writes maintain consistency
- Existing database tests run against both sync and async engines

### Commit
`feat(db): add async database sessions and async write queue`

---

## Stage 4: Incremental Worker Migration

**Goal**: Migrate individual backend workers from QThread to asyncio tasks, starting with the simplest and most self-contained, building up to the complex scan workers.

### Migration Priority Order

1. **CacheWorker** (`playback/cache.py`) — simple file copy, no network
2. **GenericSearchWorker** (`metadata_worker_search.py`) — wrapper around a callable
3. **MetadataApplyWorker** (`metadata_worker_apply.py`) — TMDB image download + DB sync
4. **MetadataEmbedWorker** / **SeriesMetadataEmbedWorker** (`metadata_worker_embed.py`) — FFmpeg subprocess
5. **SubtitleMergeWorker** (`metadata_worker_subtitle.py`) — FFmpeg subprocess
6. **RefreshSeriesWorker** (`metadata_worker_refresh.py`) — series re-scan
7. **ScanSingleSeriesWorker** (`scan_series_worker.py`) — single series scan
8. **FilePropertyExtractionWorker** (`metadata_worker_property.py`) — FFprobe + DB writes
9. **JellyfinPullWorker** / **JellyfinPushWorker** — async API calls
10. **CleanupWorker** — DB operations
11. **ScanWorker** (single library) — the main scan worker
12. **ScanAllLibrariesWorker** — the most complex worker

### Migration Pattern for Each Worker

For each worker, the pattern is:
1. Keep existing `QThread` subclass but add an `async_run()` method
2. `AsyncTaskManager` manages the coroutine lifecycle
3. Signals remain connected to Controller slots
4. The `QThread.run()` method delegates to a sync wrapper if needed
5. When all callers have switched to async, remove the QThread subclass

```python
# Before:
class CacheWorker(QThread):
    finished = Signal(str)

    def run(self):
        result = self._do_cache(self.source, self.dest)
        self.finished.emit(result)

# After (transitional):
class CacheWorker(QThread):
    finished = Signal(str)

    async def async_run(self):
        result = await self._do_cache_async(self.source, self.dest)
        self.finished.emit(result)

    def run(self):
        # Backward compat: run sync in thread pool
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.async_run())
```

For workers that are fully migrated:
```python
# After (final):
class AsyncCacheTask:
    """No longer a QThread — pure asyncio task."""
    async def run(self, source, dest, progress_callback):
        result = await async_copy_file(source, dest, progress_callback)
        return result
```

### WorkerSlot Updates
- Modify `WorkerSlot.start()` to optionally accept a coroutine factory instead of a QThread factory
- When given a coroutine factory, it uses `AsyncTaskManager.create_task()` instead of QThread.start()
- Signal-to-slot connections are preserved (callbacks are called when the async task completes)

### Tests
- For each migrated worker: verify `async_run()` produces identical results to `run()`
- Verify signals are emitted correctly from async context
- Verify cancellation works (task cancellation vs thread interruption)
- Existing worker tests remain passing

### Commits
One commit per worker migration (12+ commits), each following the same pattern:

```
refactor(backend): migrate CacheWorker to asyncio
refactor(backend): migrate GenericSearchWorker to asyncio
refactor(backend): migrate MetadataApplyWorker to asyncio
...
refactor(backend): migrate ScanAllLibrariesWorker to asyncio
```

---

## Stage 5: Hybrid Thread Pool Setup and Filesystem Traversal

**Goal**: Implement the custom, size-constrained `ThreadPoolExecutor` and offload all directory walks, `mtime` delta checks, and blocking filesystem checks to this executor. This isolates network share latency (SMB/NFS/NAS) from the PySide6 event loop, preventing UI freezes when network storage becomes slow or unreachable.

### Specific Changes
- **Thread Pool Setup**: Define a dedicated filesystem executor (`FileSystemExecutor`) with `max_workers = 3` (or configurable based on network/local drive types) in `src/lan_streamer/system/async_utils.py`.
- **Crawler Offloading**: Rewrite all `os.scandir`, `os.stat`, and directory walks in `scanner/core.py` to execute in this pool via `asyncio.to_thread` or `loop.run_in_executor(fs_executor, ...)`.
- **Concurrency Separation**: The event loop (on the Qt main thread) coordinates high-level scheduling, while worker threads perform the raw directory scans.

### Tests
- Verify simulated network drive connection hangs (inducing multi-second delays on mock scanning operations) do not degrade Qt user interface responsiveness or frame rates.

### Commit
`feat(scanner): offload filesystem traversal to custom ThreadPoolExecutor`

---

## Stage 6: Concurrency Control and Subprocess Throttling

**Goal**: Implement semaphores and concurrency limits to safeguard CPU, memory, and network resources from starvation during large metadata scans on network drives.

### Specific Changes
- **API Call Limits**: Protect all TMDB and Jellyfin client operations using `network_semaphore = asyncio.Semaphore(10)` to prevent API rate-limiting blocks or connection timeouts.
- **Subprocess Throttling**: Restrict concurrent `FFprobe` and `FFmpeg` subprocesses using `subprocess_semaphore = asyncio.Semaphore(3)` to prevent disk thrashing and CPU exhaustion on network storage.
- **Incremental Output Reading**: Configure `asyncio.subprocess` to read stdout/stderr incrementally via `communicate()` or stream readers to avoid memory accumulation.

### Tests
- Validate that scanning 100+ files simultaneously results in at most 3 parallel `ffprobe` subprocesses and 10 parallel API requests.
- Verify cancellation of long-running subprocesses (FFmpeg) halts execution cleanly without leaving zombie processes.

### Commit
`feat(scanner): apply concurrency semaphores to network and subprocesses`

---

## Stage 7: QThread Consolidation & Legacy Cleanup

**Goal**: Clean up obsolete `QThread` workers that have been fully replaced by async-managed tasks, while retaining select threads (such as VLC playback or the backup updater) for native platform isolation.

### Specific Changes
- **Clean up QThreads**: Remove legacy `QThread`-based worker classes (e.g., `MetadataEmbedWorker`, `SubtitleMergeWorker`, etc.) that are now managed as asyncio tasks.
- **Serialized Database Writer**: Retain the serialized `AsyncDatabaseWriter` write queue draining tasks sequentially, configured with Write-Ahead Logging (WAL) mode for simultaneous non-blocking read access.
- **Simplify WorkerManager**: Update `WorkerSlot` to support both native thread handles and asyncio task handles cleanly, unifying status monitoring.

### Tests
- Execute full regression and integration test suites to verify that concurrent database reads during serialized writes run without lock collisions.

### Commit
`refactor(core): consolidate QThread workers and finalize hybrid model`

---

## Post-Migration Benefits

| Metric | Before | After |
|---|---|---|
| Thread count (idle) | ~15 (QThreads + pools) | ~4 (event loop + size-limited pools) |
| Thread count (scanning) | ~30+ (QThread + nested pools) | ~8 (asyncio tasks + managed pools) |
| Memory per idle thread | ~8MB per QThread stack | ~1KB per coroutine |
| Cancellation | Polling `isInterruptionRequested()` | `task.cancel()` with `CancelledError` |
| Parallel network calls | `ThreadPoolExecutor` (synchronous) | `asyncio.gather()` (truly async) |
| Subprocess (ffprobe) | `subprocess.run()` (blocking thread) | Managed `asyncio` subprocesses |
| DB write bottleneck | `threading.Thread` + `queue.Queue` | Serialized async queue / WAL concurrency |
| Periodic scheduling | None (manual only) | Configurable async timer |

---

## Rollback Strategy

Each stage is designed to be independently deployable and revertible:

- **Stage 0**: Can be reverted by removing qasync import and using `app.exec_()` directly
- **Stage 1**: Can be disabled by not starting `ScheduledScanService`; manual scans continue working
- **Stage 2**: Sync providers remain alongside async; switch back via config flag
- **Stage 3**: Async engine optional; sync engine remains default
- **Stage 4**: Each worker can be individually reverted to QThread form
- **Stage 5**: The hybrid file system thread pool can be disabled, falling back to synchronous execution
- **Stage 6**: Semaphores can be bypassed by increasing limits
- **Stage 7**: Threading barriers for C-based engines (VLC) remain permanently isolated

A **feature flag** (`config.enable_async_scan`) controls whether the async `ScheduledScanService` or legacy QThread workers are used. This flag defaults to `false` until Stage 7.

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| `aiosqlite` compatibility with SQLAlchemy | Extensive testing; fallback to sync engine if async init fails |
| `qasync` version compatibility with Qt6 | Pin tested version; maintain fallback to native `app.exec_()` |
| Performance regression in async DB writes | Benchmark read/write latency; batch writes if needed |
| FFmpeg subprocess deadlock with asyncio | Use `asyncio.create_subprocess_exec()` with proper `communicate()` handling |
| Third-party TMDB API rate limits | Async token bucket preserves existing behavior exactly |

---

## Excluded from Async Migration

The following components are intentionally **not** targeted for async migration:

| Component | Reason |
|---|---|
| `playback/player.py` (VLC) | VLC has its own threading model; wrapping in asyncio adds complexity without benefit |
| `playback/wakelock.py` | Simple platform calls, not I/O bound |
| `playback/widget.py` UI timers | Qt timers are fine for UI update intervals (seek bar, OSD) |
| `system/config.py` | Synchronous config reads are fast (JSON file or memory); no benefit to async |
| `system/logging_handler.py` | Logging is already async-safe via QueueHandler |
| `system/backup.py` | Runs at startup, not on timer; no benefit |
| `system/updater.py` | Low frequency; `QThread` is acceptable for occasional use |
| Renamer `scanner/renamer.py` | User-initiated, low frequency |
