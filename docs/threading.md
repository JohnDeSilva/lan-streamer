# Threading Architecture

## Overview

LAN Streamer uses `PySide6.QtCore.QThread` for all background work to keep the UI responsive. This document describes the threading architecture, the `WorkerManager` lifecycle manager, the worker taxonomy, and the threading patterns used throughout the codebase.

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        Controller (QObject)                       │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                   WorkerManager (QObject)                  │    │
│  │                                                           │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │    │
│  │  │ scan     │  │ cleanup  │  │ pull     │  │ push     │ │    │
│  │  │ (Worker  │  │ (Worker  │  │ (Worker  │  │ (Worker  │ │    │
│  │  │  Slot)   │  │  Slot)   │  │  Slot)   │  │  Slot)   │ │    │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘ │    │
│  │       │              │              │              │       │    │
│  │  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐ │    │
│  │  │ file_    │  │ subtitle │  │ metadata │  │ refresh  │ │    │
│  │  │ property │  │ _merge   │  │ _embed   │  │          │ │    │
│  │  │ (Worker  │  │ (Worker  │  │ (Worker  │  │ (Worker  │ │    │
│  │  │  Slot)   │  │  Slot)   │  │  Slot)   │  │  Slot)   │ │    │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘ │    │
│  │       │              │              │              │       │    │
│  │  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐ │    │
│  │  │ scan_    │  │ metadata │  │ scan_all │  │ jellyfin │ │    │
│  │  │ series   │  │ _apply   │  │          │  │ _pull/   │ │    │
│  │  │          │  │          │  │          │  │ _push    │ │    │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  trigger_*() methods → worker_manager.<slot>.start(factory, ...)  │
│  _on_*_finished()   → result handlers                             │
│  _on_worker_error() → shared error handler                        │
└──────────────────────────┬───────────────────────────────────────┘
                           │ QThread signals (finished, error, progress)
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Backend Workers (QThread)                    │
│                                                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │
│  │  Simple Workers  │  │  Complex Workers  │  │  Database/Thread │  │
│  │  (no DB writer)  │  │  (with DB writer) │  │  Pool Workers   │  │
│  ├─────────────────┤  ├─────────────────┤  ├──────────────────┤  │
│  │ CleanupWorker   │  │ ScanWorker       │  │ ScanAllLibraries │  │
│  │ JellyfinPull    │  │ FileProperty     │  │  (w/ ThreadPool) │  │
│  │ JellyfinPush    │  │ ExtractionWorker │  │                  │  │
│  │ SubtitleMerge   │  │                  │  │                  │  │
│  │ MetadataEmbed   │  │                  │  │                  │  │
│  │ SeriesMetaEmbed │  │                  │  │                  │  │
│  │ RefreshSeries   │  │                  │  │                  │  │
│  │ MetadataApply   │  │                  │  │                  │  │
│  │ ScanSingleSeries│  │                  │  │                  │  │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘  │
└──────────────────────────┬───────────────────────────────────────┘
                           │ queue.Queue
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                  DatabaseWriterThread (threading.Thread)          │
│  Sequential consumer: executes DB write tasks from a queue       │
│  Actions: save_season, save_movie, save_library,                 │
│           save_movie_library, save_directory_mtime,              │
│           update_items_runtime_batch                              │
└──────────────────────────────────────────────────────────────────┘
```

---

## WorkerManager & WorkerSlot

### Problem Statement (Before)

Before this refactoring, the `Controller` managed worker lifecycles manually with:

- 11 separate `_*_worker_instance` attributes (`Optional[X]` types)
- A `_stop_worker()` method using `getattr`/`setattr` on string attribute names
- Duplicated 5-step lifecycle in 14 trigger methods
- A bare `worker.disconnect()` call (invalid in PySide6 — caused `TypeError`)
- Inconsistent concurrency guards (some methods had them, some didn't)

### Solution: WorkerManager + WorkerSlot

`WorkerManager` is a `QObject` at `src/lan_streamer/system/threading_manager.py` that owns a set of named `WorkerSlot` instances, one per distinct worker role.

Each `WorkerSlot` provides:

```
start(factory: Callable[[], W], **signal_slots) -> W
    Stop any existing worker, create new one, connect signals, start.

stop() -> None
    requestInterruption → quit → wait(timeout) → deleteLater

is_running: bool (property)
    Returns True if a worker exists and isRunning().

start_if_not_running(factory, **signal_slots) -> Optional[W]
    Like start() but returns None if a worker is already running.

instance: Optional[QThread] (property)
    Returns the current worker instance (or None).
```

### Lifecycle of a WorkerSlot

```
start() called
    │
    ├── stop() existing worker (if any)
    │     ├── requestInterruption()
    │     ├── quit()
    │     ├── wait(5000ms) — blocks until thread finishes
    │     └── deleteLater() — Qt event loop disconnects + frees
    │
    ├── factory() → new worker instance
    ├── connect signal_slots (only those specified)
    └── worker.start() — QThread begins execution

worker finishes
    │
    ├── finished signal emitted → connected slot runs
    ├── instance still accessible via .instance property
    └── next start() call will stop() first
```

### Signal Connection Strategy

`WorkerSlot.start()` accepts keyword arguments mapping signal names to slots:

```python
self.worker_manager.scan.start(
    lambda: ScanWorker(...),
    finished=self._on_scan_finished,
    error=self._on_worker_error,
    partial_result=self._on_scan_partial,
)
```

Only the signals explicitly provided as kwargs are connected. This means:
- No bare `disconnect()` calls (the PySide6 bug is fixed)
- No signal leaks — when the worker is replaced, the old worker's `deleteLater()` handles cleanup
- No unnecessary connections

---

## Worker Taxonomy

### Simple Workers (no sub-threads)

| Class | File | Signals |
|---|---|---|
| `CleanupWorker` | `scan_worker_cleanup.py` | `finished(dict)`, `error(str)` |
| `JellyfinPullWorker` | `jellyfin_workers.py` | `finished(int)`, `error(str)` |
| `JellyfinPushWorker` | `jellyfin_workers.py` | `finished(int)`, `error(str)` |
| `SubtitleMergeWorker` | `metadata_worker_subtitle.py` | `finished(str)`, `error(str)` |
| `MetadataEmbedWorker` | `metadata_worker_embed.py` | `finished(str)`, `error(str)` |
| `SeriesMetadataEmbedWorker` | `metadata_worker_embed.py` | `finished()`, `progress_updated(str,int,int)`, `error(str)` |
| `RefreshSeriesWorker` | `metadata_worker_refresh.py` | `finished(dict)`, `error(str)` |
| `MetadataApplyWorker` | `metadata_worker_apply.py` | `finished(dict,str)`, `error(str)` |
| `GenericSearchWorker` | `metadata_worker_search.py` | `search_finished(object)`, `error(str)` |
| `ScanSingleSeriesWorker` | `scan_series_worker.py` | `finished(dict)`, `error(str)` |

### Complex Workers (manage sub-threads)

| Class | File | Signals | Sub-threads |
|---|---|---|---|
| `ScanWorker` | `scan_worker_single.py` | `finished(dict)`, `partial_result(dict)`, `error(str)`, `detail_progress_batch(list)` | `DatabaseWriterThread` |
| `ScanAllLibrariesWorker` | `scan_worker_all.py` | `finished()`, `library_progress(str,int,int)`, `error(str)`, `detail_progress_batch(list)` | `DatabaseWriterThread`, `ThreadPoolExecutor` |
| `FilePropertyExtractionWorker` | `metadata_worker_property.py` | `finished(int)`, `progress_updated(int,int)`, `error(str)` | `DatabaseWriterThread`, `ThreadPoolExecutor` |

### Supporting Infrastructure

| Class | File | Base Class | Role |
|---|---|---|---|
| `DatabaseWriterThread` | `database_writer.py` | `threading.Thread` (daemon) | Sequential queue consumer for DB writes |
| `DatabaseWriteTask` | `database_writer.py` | (plain object) | Encapsulates a single DB write request with `threading.Event` |

---

## Patterns & Best Practices

### Pattern 1: Starting a Worker

```python
# Controller method
def trigger_cleanup(self) -> None:
    self.worker_manager.cleanup.start(
        lambda: CleanupWorker(
            library_name=self.current_library_name,
            root_directories=root_directories,
        ),
        finished=self._on_cleanup_finished,
        error=self._on_worker_error,
    )
```

### Pattern 2: Concurrency Guard

```python
# Before (old)
if self.scan_worker_instance is not None and self.scan_worker_instance.isRunning():
    return

# After (new)
if self.worker_manager.scan.is_running:
    return
```

### Pattern 3: Accessing Worker Attributes After Completion

```python
# Before (old)
changed_seasons = getattr(self.scan_worker_instance, "changed_season_ids", None)

# After (new)
scan_worker = self.worker_manager.scan.instance
changed_seasons = getattr(scan_worker, "changed_season_ids", None)
```

### Pattern 4: Adding a New Worker Type

1. Add a `WorkerSlot` to `WorkerManager.__init__`:
   ```python
   class WorkerManager(QObject):
       def __init__(self, parent=None):
           super().__init__(parent)
           ...
           self.my_new_worker: WorkerSlot = WorkerSlot(self)
   ```
2. In the controller, start it via:
   ```python
   self.worker_manager.my_new_worker.start(
       lambda: MyNewWorker(...),
       finished=self._on_my_new_worker_finished,
       error=self._on_worker_error,
   )
   ```

---

## Thread Safety Considerations

1. **Qt Signals are thread-safe** across `QThread` boundaries. Emitting a signal from a worker thread delivers it to the main thread's event loop (queued connection is automatic for cross-thread signals).

2. **No shared mutable state**. Workers receive their input via constructor arguments and return results via signals. The controller never shares mutable references with workers.

3. **Worker interruption**. Workers should periodically check `self.isInterruptionRequested()` in their `run()` method to support graceful shutdown.

4. **DatabaseWriterThread**. DB writes are serialized through a `queue.Queue` to avoid concurrent database access. Each `DatabaseWriteTask` carries its own `threading.Event` for completion notification.

---

## Bug Fix: `disconnect()` Error

### The Bug

In the original `_stop_worker()` method:

```python
def _stop_worker(self, worker_attr, timeout_ms=5000):
    worker = getattr(self, worker_attr, None)
    if worker is None:
        return
    try:
        worker.requestInterruption()
        worker.quit()
        worker.disconnect()  # <-- TypeError in PySide6
        worker.wait(timeout_ms)
        worker.deleteLater()
    except RuntimeError:
        pass
```

`QObject.disconnect()` with no arguments is invalid in PySide6 unless there are no connections. The error message was:
> `TypeError: PySide6.QtCore.QObject.disconnect(): not enough arguments`

### The Fix

The `_stop_worker` method was removed entirely. Worker lifecycle is now managed by `WorkerSlot.stop()`:

```python
def stop(self) -> None:
    worker = self._instance
    if worker is None:
        return
    try:
        worker.requestInterruption()
        worker.quit()
        if not worker.wait(self._timeout_ms):
            logger.warning(...)
        worker.deleteLater()
    except RuntimeError:
        pass
    self._instance = None
```

Key differences:
- No `disconnect()` call — `deleteLater()` handles signal cleanup
- No `getattr`/`setattr` on string attribute names — direct property access
- Each `WorkerSlot` owns exactly one worker, eliminating confusion about which worker is being stopped

---

## Duplicated Code Removed

| Pattern | Removed From | Lines Saved |
|---|---|---|
| Worker lifecycle boilerplate | 14 controller methods | ~120 lines |
| Concurrency guard boilerplate | 9 controller methods | ~30 lines |
| `_stop_worker` method | controller.py | 16 lines |
| Worker instance attributes | controller.py `__init__` | 11 lines |
| **Total** | | **~177 lines** |
