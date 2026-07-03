# Scan Process Architecture Analysis & Improvement Proposals

> **Status:** Analysis phase — proposals pending user selection
> **Last Updated:** 2026-07-02

## Table of Contents

1. [Scan Flow Overview](#1-scan-flow-overview)
2. [Trigger Points](#2-trigger-points)
3. [Current Architecture Deep-Dive](#3-current-architecture-deep-dive)
4. [Bottleneck Analysis](#4-bottleneck-analysis)
5. [Improvement Proposals](#5-improvement-proposals)

---

## 1. Scan Flow Overview

The scan process has **three trigger granularities** and a **two-pass architecture**:

### Trigger Granularities

| Type | Worker Class | File | Description |
|------|-------------|------|-------------|
| **Single Library** | `AsyncScanWorker` | `backend/scan_worker_async.py` | Scan one library (both passes) |
| **All Libraries** | `ScanAllLibrariesWorker` | `backend/scan_worker_all.py` | Parallel multi-library scan |
| **Single Series/Movie** | `ScanSingleSeriesWorker` | `backend/scan_series_worker.py` | Targeted rescan of one item |

### Two-Pass Architecture

```
PASS 1 (Offline)                      PASS 2 (Online)
┌─────────────────────┐               ┌─────────────────────┐
│ Filesystem crawl    │               │ TMDB metadata fetch │
│ File discovery      │    ─────►     │ Episode resolution  │
│ mtime checks        │               │ Poster downloads    │
│ FFprobe extraction  │               │ Jellyfin matching   │
│ DB writes (callbk)  │               │ DB writes (callbk)  │
└─────────────────────┘               └─────────────────────┘
```

---

## 2. Trigger Points

### UI Triggers

```
library_grid.py                          settings.py
┌──────────────────┐                    ┌──────────────────────┐
│ "Scan Library"   │──► trigger_scan_and_update(False)
│ "Refresh Meta"   │──► trigger_scan(True)
│ "Combined Scan"  │──► trigger_scan_all(False)                 │
└──────────────────┘                    │ "Scan Files"          │──► trigger_full_scan_files()
                                         │ "File Scan" (P1)     │──► trigger_pass1_scan()
                                         │ "Metadata" (P2)      │──► trigger_pass2_scan()
                                         │ "Runtime" (P3)       │──► trigger_pass3_scan()
                                         └──────────────────────┘
                                                        ▲
scheduled_scan_service.py                                │
┌──────────────────────┐                                │
│ Timer-based auto-scan│────────────────────────────────┘
└──────────────────────┘
```

### Controller Dispatch

All triggers converge at `controller.py` which dispatches via `WorkerManager` slots:

```
controller.py
  ├─ trigger_scan()           → worker_manager.scan.start(AsyncScanWorker)
  ├─ trigger_scan_and_update()→ worker_manager.scan.start(AsyncScanWorker)
  └─ trigger_scan_all()       → worker_manager.scan_all.start(ScanAllLibrariesWorker)
```

### Post-Scan Chain (UI Thread — Critical Path)

```
Worker finished
  │
  ▼
_on_scan_finished() / _on_scan_all_finished()
  │
  ├─ [UI] db.save_library() / db.save_movie_library()    ← BLOCKING
  ├─ [UI] _cache_series_metrics()                        ← CPU
  ├─ [UI] SmartRowService.rebuild_for_libraries()        ← BLOCKING SQL
  │   └─ db.rebuild_cache_for_config()
  │       └─ queries_ui.get_combined_smart_row()          ← Full library scan
  ├─ [UI] smart_rows_updated.emit() → widget rebuild
  ├─ [BG] trigger_runtime_extraction()                   ← ffprobe
  └─ [BG] trigger_global_cleanup()                       ← DB cleanup
```

---

## 3. Current Architecture Deep-Dive

### 3.1 Threading Model

The system uses **four thread pools**:

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 1: asyncio Event Loop (Qt Main Thread via qasync)     │
│                                                              │
│  AsyncTaskManager                                           │
│    ├─ ScanAllLibrariesWorker.run_async()                    │
│    ├─ AsyncScanWorker.run_async()                           │
│    └─ AsyncDatabaseWriter._run()  [async consumer queue]    │
└────────────────┬─────────────────────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────────────────────┐
│  Layer 2: Default ThreadPoolExecutor (asyncio.to_thread)     │
│  _scan_library_pass() dispatched here — one per library      │
└────────────────┬─────────────────────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────────────────────┐
│  Layer 3: Global Scan Executor (get_scan_executor())         │
│  max_workers = min(12, cpu_count * 2)                       │
│  scan_series() / scan_movie() dispatched here (per dir)      │
└────────────────┬─────────────────────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────────────────────┐
│  Layer 4: Filesystem Executor (run_in_fs_executor)            │
│  max_workers = 3  — for tree discovery only                   │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Database Writer Architecture

`AsyncDatabaseWriter` uses an `asyncio.Queue` to serialize ALL DB writes:

```
Scanner Thread Pool (Layer 3)
         │
         ▼
  sync_submit("save_season", {...})
         │
         ├─ run_coroutine_threadsafe(queue.put(...))
         ├─ threading.Event.wait(timeout=60)  ← BLOCKS scanner thread
         │
         ▼  ┌─────────────────────────────────────┐
  asyncio   │ AsyncDatabaseWriter._run()           │
  Queue ───►│   Processes ONE task at a time       │
            │   └─ asyncio.to_thread(_execute)     │
            └─────────────────────────────────────┘
```

**Key issue:** All scanner threads (Layer 3) block on DB writes, serializing through a single consumer.

### 3.3 Progress Reporting

```
scanner thread → _detail_callback() → buffer (under lock) → flush at 20 items
                                                              │
                                                              ▼
                                              detail_progress_batch.emit()
                                                              │
                                                              ▼
                                              UI thread → update progress bar
```

---

## 4. Bottleneck Analysis

### 4.1 Critical Bottlenecks

| # | Issue | Severity | Location | Impact |
|---|-------|----------|----------|--------|
| C1 | **Sequential DB writes serialize all scanner threads** | 🔴 Critical | `database_writer.py` (`sync_submit` blocks scanner threads) | Scanner threads spend 60%+ of time waiting on DB writes |
| C2 | **Post-scan cache rebuild runs on UI thread** | 🔴 Critical | `controller.py` (`_on_scan_finished` lines 494–499, 802) | UI freezes for seconds during `rebuild_all_cache()` |
| C3 | **ffprobe subprocess spawned without concurrency limit** | 🟠 High | `file_property_scanner.py` (subprocess.run per file) | Can spawn 24+ simultaneous ffprobe processes, thrashing CPU/IO |
| C4 | **Libraries scanned sequentially despite concurrent submission** | 🟠 High | `scan_worker_all.py` (lines 949–1004 — sequential await) | Faster libraries wait for slower libraries |
| C5 | **Post-scan DB save serializes entire library** | 🟠 High | `controller.py` (lines 470–472) | UI blocks saving potentially massive dict |

### 4.2 Moderate Bottlenecks

| # | Issue | Severity | Location | Impact |
|---|-------|----------|----------|--------|
| M1 | **TMDB season/episode fetches are sequential per series** | 🟡 Medium | `metadata_episode.py` (`_process_season_metadata`) | N seasons → N sequential API calls |
| M2 | **TMDB search fallbacks are sequential** | 🟡 Medium | `tmdb.py` (search_series, 4–5 attempts) | Up to 5 sequential HTTP calls per lookup |
| M3 | **Jellyfin correlation fetches are sequential** | 🟡 Medium | `jellyfin.py` (two sequential full-library scans) | 2x latency for correlation data |
| M4 | **Cast/image fetch inside scan callback blocks** | 🟡 Medium | `scan_worker_all.py` (lines 431, 538 — `db.get_cast_for_series`) | Synchronous DB + network in scanner thread |
| M5 | **N+1 playback state queries** | 🟡 Medium | `queries_playback.py` (lazy-loaded relationships) | 100+ queries for single watched update |

### 4.3 Minor Bottlenecks

| # | Issue | Severity | Location | Impact |
|---|-------|----------|----------|--------|
| N1 | **Redundant `has_video_files()` in tree discovery** | 🟢 Low | `scan_worker_base.py` (recursive walk per top-level dir) | Extra I/O on network shares |
| N2 | **Full library dict iteration in `_cache_series_metrics`** | 🟢 Low | `controller.py` (line 476) | CPU O(n) per scan completion |
| N3 | **Settings dialog `_scan_running` flag never explicitly cleared** | 🟢 Low | `settings.py` (line 85—relies on signal) | Fragile state management |

---

## 5. Improvement Proposals

Below are concrete improvement proposals organized by impact level. Each proposal includes estimated effort, risk level, and implementation approach.

---

### Proposal A: Parallelize AsyncDatabaseWriter (🔴 Critical)

**Goal:** Eliminate the serial bottleneck where all scanner threads block on `sync_submit()`.

**Current behavior:** Single `asyncio.Queue` consumer processes DB writes one-at-a-time. Scanner threads submit writes and block via `threading.Event.wait()`.

**Proposed change:** Replace the single-consumer queue with a **batching + concurrent consumer model**:

```
Current:
  Writer Queue ──► Consumer (1) ──► asyncio.to_thread(write)

Proposed:
  Writer Queue ──► Batcher ──► Batch Consumer (1) ──► asyncio.to_thread(batch_write)
                     │
                     └──► stats tracked per-batch
```

**Implementation options:**

| Option | Approach | Complexity | Risk | Benefit |
|--------|----------|------------|------|---------|
| A1 | Batch DB writes: collect N writes into a single SQL transaction | Low | Low | 5-10x write throughput |
| A2 | Concurrent consumers: 2-3 consumers with SQLite WAL mode | Medium | Medium | Scales with write volume |
| A3 | Remove sync_submit entirely: pass DB session to scanner threads | High | High | Maximum throughput but complex |

**Recommended: A1** — Batch writes into transactions. The scanner naturally produces writes in bursts (one season at a time). Batching those into a single transaction reduces SQLite overhead and frees scanner threads faster.

**Files to modify:**
- `backend/database_writer.py` — modify `_run()` to batch-consume queue
- `tests/test_database_writer.py` — update tests for batching behavior

---

### Proposal B: Offload Post-Scan Processing to Background (🔴 Critical)

**Goal:** Move all post-scan CPU/DB work off the UI thread.

**Current behavior:** `_on_scan_finished()` runs on UI thread and calls:
1. `db.save_library()` — serializes full library dict to DB
2. `_cache_series_metrics()` — iterates all episodes
3. `SmartRowService.rebuild_for_libraries()` — runs SQL + cache writes

**Proposed change:** Run post-scan work in a background worker:

```
Current:
  Worker finished ──► UI thread ──► save_library + rebuild_cache + emit signals

Proposed:
  Worker finished ──► UI thread (light) ──► BackgroundPostScanWorker
        │                                        │
        │  (1) cache_library_data = result       │  (2) db.save_library()
        │  (3) emit fast signals                 │  (4) rebuild_cache()
        │                                        │  (5) emit finished
        └────────────────────────────────────────┘
                        │
                        ▼
                 UI thread: on_post_scan_finished()
                   ├─ library_loaded.emit()
                   └─ smart_rows_updated.emit()
```

**Implementation:**
1. Create `backend/post_scan_worker.py` — `PostScanWorker(AsyncWorkerBase)`
2. Controller starts it in `_on_scan_finished()` instead of doing work inline
3. On completion, emit signals for UI update

**Files to modify:**
- `backend/post_scan_worker.py` — new file
- `ui_views/controller.py` — `_on_scan_finished()`, `_on_scan_all_finished()`
- `system/threading_manager.py` — add `post_scan` slot
- `tests/test_controller.py` — update for async post-scan

---

### Proposal C: Throttle FFprobe Subprocess Spawns (🟠 High)

**Goal:** Limit concurrent ffprobe processes to prevent CPU thrashing.

**Current behavior:** `file_property_scanner.py` calls `subprocess.run(ffprobe, timeout=10)` directly. The `asyncio.Semaphore` in `async_utils.py` (`_SUBPROCESS_SEMAPHORE = 3`) is **not enforced** because these calls run in thread-pool workers, not in async context.

**Proposed change:** Introduce a `threading.Semaphore` (or `BoundedSemaphore`) in `get_detailed_file_info()` to limit concurrent ffprobe invocations:

```python
_ffprobe_semaphore = threading.BoundedSemaphore(3)

def get_detailed_file_info(file_path: str) -> dict:
    with _ffprobe_semaphore:
        result = subprocess.run([ffprobe, file_path], ...)
```

**Options:**

| Option | Approach | Complexity | Benefit |
|--------|----------|------------|---------|
| C1 | Threading semaphore in `get_detailed_file_info` | Very Low | Prevents CPU thrashing |
| C2 | Configurable max_ffprobe_workers in config | Low | User-tunable |
| C3 | Priority-based scheduling (known-new files first) | Medium | Feels faster to user |

**Recommended: C1 + C2** — Simple semaphore with configurable limit.

**Files to modify:**
- `scanner/file_property_scanner.py` — add semaphore
- `system/config.py` — add `max_ffprobe_workers` config key
- `tests/test_file_property_scanner.py` — test concurrency limit

---

### Proposal D: True Parallel Library Scanning (🟠 High)

**Goal:** Allow libraries that finish Pass 1 early to proceed to Pass 2 without waiting.

**Current behavior:** In `ScanAllLibrariesWorker.run_async()`, libraries are submitted concurrently to the executor but results are awaited sequentially:

```python
tasks = [run_in_executor(lib) for lib in libraries]
for task, lib_name in tasks:                   # ← sequential await
    result = await task
    merge(result, lib_name)
```

**Proposed change:** Process results as they complete using `asyncio.as_completed()`:

```python
tasks = {run_in_executor(lib): lib_name for lib in libraries}
for done_task in asyncio.as_completed(tasks):  # ← as-completed
    result = await done_task
    lib_name = tasks[done_task]
    merge(result, lib_name)
```

**Same for Pass 2:** Allow libraries to start Pass 2 as soon as they finish Pass 1, rather than waiting for all libraries to finish Pass 1.

**Files to modify:**
- `backend/scan_worker_all.py` — Pass 1 and Pass 2 loops (lines 949–1004, 1037–1097)
- `tests/test_scan_worker_all.py` — verify parallel completion

---

### Proposal E: Batch TMDB Season Fetches (🟡 Medium)

**Goal:** Reduce sequential API calls by parallelizing TMDB season/episode fetches within a series.

**Current behavior:** `_process_season_metadata()` calls `tmdb_client.get_episodes()` once per season sequentially within `scan_tv.py`'s per-season loop.

**Proposed change:** Pre-fetch all season episode lists concurrently before the per-season processing loop:

```
Current:                                      Proposed:
  For each season:                              tmdb_episodes = await asyncio.gather(
    episodes = tmdb.get_episodes(id, n)  (N×)      [tmdb.get_episodes(id, n) for n in 1..N]
    process(season, episodes)                    )
                                                For each season:
                                                  process(season, tmdb_episodes[n])
```

**Options:**

| Option | Approach | Complexity | Benefit |
|--------|----------|------------|---------|
| E1 | Pre-fetch all seasons before processing loop | Low | N serial → 1 parallel batch |
| E2 | Async gather within scan_tv.py using asyncio.to_thread | Medium | Doesn't require full async migration |
| E3 | Use the async TMDB client (tmdb_async.py) instead of sync | High | Full async benefits |

**Recommended: E1** — Simple restructuring of the season loop to pre-fetch.

**Files to modify:**
- `services/metadata_episode.py` — `_process_season_metadata()` return structure
- `scanner/scan_tv.py` — call structure for season processing

---

### Proposal F: Async Jellyfin Data Fetching (🟡 Medium)

**Goal:** Parallelize the two full-library Jellyfin fetches in `get_jellyfin_correlation_data()`.

**Current behavior:** Two sequential paginated requests (episodes + series/movies).

**Proposed change:** Use threads or the async client to fetch both in parallel:

```python
# Current:
episodes_data = jellyfin._fetch_all_items(endpoint="Items", ..., fields=...)
series_data = jellyfin._fetch_all_items(endpoint="Items", ..., include_item_types="Series,Movies")

# Proposed:
import concurrent.futures
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    episodes_future = pool.submit(jellyfin._fetch_all_items, ...)
    series_future = pool.submit(jellyfin._fetch_all_items, ...)
    episodes_data = episodes_future.result()
    series_data = series_future.result()
```

**Files to modify:**
- `providers/jellyfin.py` — `get_jellyfin_correlation_data()`
- `tests/test_jellyfin.py` — verify parallel fetch

---

### Proposal G: Eliminate N+1 Playback Queries (🟡 Medium)

**Goal:** Fix lazy-loaded relationship queries in playback state updates.

**Current behavior:** `queries_playback.py` functions (e.g., `update_episode_watched_status`) lazy-load `episodes`, `playback_state`, `media_files` one-by-one.

**Proposed change:** Use eager loading (`selectinload` / `joinedload`) to fetch all needed data in a single query:

```python
# Before:
mf = session.execute(select(MediaFile).where(MediaFile.path == path)).scalar_one_or_none()
for ep in mf.episodes:  # lazy load — N+1
    state = ep.playback_state  # lazy load — N+1

# After:
stmt = (
    select(MediaFile)
    .options(
        selectinload(MediaFile.episodes).selectinload(Episode.playback_state)
    )
    .where(MediaFile.path == path)
)
```

**Files to modify:**
- `db/queries_playback.py` — add eager loading options
- `tests/test_queries_playback.py` — verify query count

---

### Proposal H: Incremental Cache Rebuild (🟡 Medium)

**Goal:** Avoid full cache rebuild when only specific items change.

**Current behavior:** After scan-all completes, `SmartRowService.on_scan_completed(None)` calls `rebuild_all_cache()` which recomputes ALL enabled smart row configurations.

**Proposed change:** Pass the list of changed libraries/items and rebuild only affected configs. This already works for single-library scans but scan-all uses `None` (triggers full rebuild). The fix is to pass the actual list of changed libraries.

**Implementation:** Simple change in `_on_scan_all_finished()` — convert `None` to the actual list of affected libraries.

**Files to modify:**
- `ui_views/controller.py` — `_on_scan_all_finished()` (line 802)
- `services/smart_row_service.py` — verify `rebuild_for_libraries()` works correctly

---

### Proposal I: Optimize Tree Discovery (🟢 Low)

**Goal:** Reduce redundant filesystem walks during tree discovery.

**Current behavior:** `discover_single_library_tree_impl()` calls `has_video_files()` for every top-level directory, which does a recursive walk.

**Proposed change:** Use `os.scandir()` depth-first search that stops at first video file found, and cache results for the main scan pass:

1. Inline `has_video_files` check into the tree discovery walk
2. Reuse the discovered directory structure in the main scan pass
3. Avoid double-walking the same directories

**Files to modify:**
- `backend/scan_worker_base.py` — `discover_single_library_tree_impl()`
- `scanner/parser.py` — `has_video_files()`

---

## Summary Decision Matrix

| Prop | Title | Severity | Effort | Risk | UI Impact | Speed Gain |
|------|-------|----------|--------|------|-----------|------------|
| **A** | Parallelize DB Writer | 🔴 Critical | Low | Low | ✅ Eliminates UI freeze | 20-40% scan time reduction |
| **B** | Offload Post-Scan Processing | 🔴 Critical | Medium | Low | ✅ Eliminates UI freeze | 1-5s UI responsiveness |
| **C** | Throttle FFprobe | 🟠 High | Very Low | None | None | 10-20% CPU reduction |
| **D** | True Parallel Library Scan | 🟠 High | Low | Low | None | 15-30% (multi-lib) |
| **E** | Batch TMDB Season Fetches | 🟡 Medium | Low | Low | None | 10-30% per series |
| **F** | Async Jellyfin Fetch | 🟡 Medium | Low | Low | None | 1-3s faster startup |
| **G** | N+1 Playback Queries | 🟡 Medium | Low | Low | None | Unlocks bulk ops |
| **H** | Incremental Cache Rebuild | 🟡 Medium | Very Low | None | ✅ Faster post-scan | 0.5-2s per scan |
| **I** | Optimize Tree Discovery | 🟢 Low | Low | Low | None | 5-10% first-scan |

---

## Implementation Order (Recommended)

### Phase 1 — Quick Wins (1-2 days)
1. **C**: Throttle FFprobe — threading semaphore (very low risk)
2. **H**: Incremental cache rebuild — pass library list instead of None
3. **I**: Optimize tree discovery — cache walk results
4. **F**: Async Jellyfin fetch — parallelize two fetches

### Phase 2 — Architecture Improvements (3-5 days)
5. **A**: Parallelize DB Writer — batch writes into transactions
6. **B**: Offload post-scan processing — background worker
7. **D**: True parallel library scanning — as_completed pattern

### Phase 3 — Network Optimization (2-3 days)
8. **E**: Batch TMDB season fetches — parallel season fetch
9. **G**: Eliminate N+1 playback queries — eager loading

---

## Diagrams

### Current Scan Worker Threading Model

```
Legend: ─── sync call   ~~~ async queue   ═══ thread boundary

┌──────────────────────────────────────────────────────────────────┐
│  MAIN THREAD (qasync event loop)                                 │
│                                                                  │
│  ScanAllLibrariesWorker.run_async()                              │
│    ├─ load_library() ───────────────────────────────── sync DB  │
│    ├─ _discover_tree() ──► FS Executor ──► await                 │
│    ├─ Pass 1: submit N library tasks         │                  │
│    │   └─ await results (sequential)          │                  │
│    ├─ Pass 2: submit N library tasks          │                  │
│    │   └─ await results (sequential)          │                  │
│    └─ _log_scan_summary()                     │                  │
│                                                │                  │
│  AsyncDatabaseWriter._run()                    │                  │
│    └─ queue.get() → asyncio.to_thread(write)  │                  │
└──────────┬═════════════════════════════════════╪══════════════════┘
           │ Pass 1/2 tasks (run_in_executor)     │
           │                                     │
┌──────────▼═════════════════════════════════════▼══════════════════┐
│  EXECUTOR THREAD: _scan_library_pass()          │                │
│                                                  │                │
│  scan_directories() ──► Global Scan Executor     │                │
│    └─ Per-series:                                │                │
│         scan_series() / scan_movie()             │                │
│           ├─ os.scandir() / stat()              │                │
│           ├─ ffprobe subprocess (unlimited)     │                │
│           ├─ TMDB API call (unlimited)          │                │
│           └─ season_callback() ──► sync_submit()│                │
│               └─ blocks until DB write done ◄═══╪══ await queue │
└──────────────────────────────────────────────────┘               │
```

### Proposed Post-Phase-2 Threading Model

```
┌──────────────────────────────────────────────────────────────────┐
│  MAIN THREAD (qasync event loop)                                 │
│                                                                  │
│  ScanAllLibrariesWorker.run_async()                              │
│    ├─ load_library() ─────────────────────────── sync DB         │
│    ├─ _discover_tree() ──► FS Executor ──► await                │
│    ├─ Pass 1: submit + as_completed() ◄══ as they finish        │
│    ├─ Pass 2: submit + as_completed() ◄══ as they finish        │
│    ├─ Start PostScanWorker (background)                         │
│    │   └─ emit scan_completed immediately                       │
│    └─ _log_scan_summary()                                       │
│                                                                  │
│  AsyncDatabaseWriter._run() (batched)                            │
│    └─ batch_get() → asyncio.to_thread(batch_write)              │
└══════════════════════════════════════════════════════════════════┘

┌──────────────────────────────────────────────────────────────────┐
│  POST-SCAN WORKER THREAD (background)                           │
│                                                                  │
│  PostScanWorker.run_async()                                     │
│    ├─ db.save_library()                                         │
│    ├─ SmartRowService.rebuild_for_libraries()                   │
│    └─ emit finished → UI: library_loaded, smart_rows_updated    │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  EXECUTOR THREADS                                                │
│                                                                  │
│  scan_series() / scan_movie()                                    │
│    ├─ os.scandir() / stat()                                      │
│    ├─ ffprobe (SEMAPHORE=3) ← throttled                         │
│    ├─ TMDB API call (SEMAPHORE=10) ← throttled                  │
│    └─ season_callback() ──► sync_submit()                       │
│         └─ (batched, returns faster)                            │
└──────────────────────────────────────────────────────────────────┘
```
