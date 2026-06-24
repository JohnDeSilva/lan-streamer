# Parallel Scan Architecture

## Overview

The scan worker system consists of two production workers sharing a common base module:

| File | Role |
|---|---|
| `src/lan_streamer/backend/scan_worker_base.py` | Shared static helpers and `discover_single_library_tree_impl` |
| `src/lan_streamer/backend/scan_worker_all.py` | `ScanAllLibrariesWorker` — scans multiple libraries in parallel |
| `src/lan_streamer/backend/scan_worker_single.py` | `ScanSingleLibraryWorker` — scans one library at a time |

## Threading Model

- **ScanAllLibrariesWorker**: Uses `concurrent.futures.ThreadPoolExecutor` with `max_workers = max(1, min(len(libraries), cpu_count or 4))`.
- **ScanSingleLibraryWorker**: Runs inline in its QThread (single library, no parallelism needed).
- **main.py controller**: Instantiates `ScanAllLibrariesWorker` and connects signals.
- **Signal emission**: Works from pool threads because Qt's signal-slot mechanism queues signals to the receiving thread's event loop.

## Per-Library Two-Pass Structure

Each library goes through two passes:

1. **Pass 1 — File Discovery (offline)**: Crawls the filesystem for new/changed/removed files. No network calls.
2. **Pass 2 — Metadata Resolution (online)**: Enriches discovered items with TMDB/Jellyfin metadata. Network-bound.

Pass 1 and Pass 2 each have their own local stats accumulator dictionaries. Stats are merged after both passes complete.

## Scan Worker Base (`scan_worker_base.py`)

Shared functions:

| Function | Purpose |
|---|---|
| `create_empty_stats()` | Returns a zero-initialized stats dictionary |
| `merge_stats_dicts(base, delta)` | Accumulates delta into base in-place |
| `merge_stats_dicts_for_report(*dicts)` | Combines multiple dicts for aggregate report |
| `log_stats_breakdown(label, stats_dict, log_target)` | Logs a stats section with formatted counters |
| `log_issues_report(problems, log_target)` | Groups and logs scan issues by type/error |
| `discover_single_library_tree_impl(...)` | Discovers files for a single library path |

### Logger Pattern

These functions accept an optional `log_target` parameter (defaulting to the base module's logger). Callers pass their own module-level logger so test patches on per-module loggers continue to work:

```python
log_stats_breakdown("PASS 1 BREAKDOWN", stats, logger)
log_issues_report(problems, logger)
```

## Stats Dictionary Shape

```python
{
    "series_scanned": int, "series_added": int,
    "series_updated": int, "series_removed": int,
    "series_skipped": int,
    "seasons_scanned": int, "seasons_added": int,
    "seasons_updated": int, "seasons_removed": int,
    "seasons_skipped": int,
    "episodes_scanned": int, "episodes_added": int,
    "episodes_updated": int, "episodes_removed": int,
    "episodes_skipped": int,
    "movies_scanned": int, "movies_added": int,
    "movies_updated": int, "movies_removed": int,
    "movies_skipped": int,
}
```

## Per-Library Accumulation

Each `_scan_library_pass` maintains its own `local_stats` dict. After both passes complete, results are merged into per-library accumulators (`pass1_stats`, `pass2_stats`, `stats`). The combined `problems` and `unavailable_directories` lists are protected by a threading lock since multiple library threads may append simultaneously.

## Scan Report Layout

```
[SCAN_REPORT] ===== Library: /path/to/library =====
[SCAN_REPORT]   Paths: [lib_id]
[SCAN_REPORT] PASS 1: OFFLINE FILE DISCOVERY BREAKDOWN (PASS 1)
[SCAN_REPORT]   Series: Scanned=... | Added=... | ...
[SCAN_REPORT]   ...
[SCAN_REPORT] ---------------------------------------------------
[SCAN_REPORT] PASS 2: ONLINE METADATA RESOLUTION BREAKDOWN (PASS 2)
[SCAN_REPORT]   ...
[SCAN_REPORT] ---------------------------------------------------
[SCAN_REPORT] TOTAL ACCUMULATED RUN STATS
[SCAN_REPORT]   ...
[SCAN_REPORT] ===================================================
[SCAN_REPORT]               SCAN RUN ISSUES REPORT
[SCAN_REPORT] ===================================================
[SCAN_REPORT] Type: ...
[SCAN_REPORT] ===================================================
[SCAN_REPORT]               *** SCAN COMPLETED ***
[SCAN_REPORT] ===================================================
```

## Testing Strategy

- **`tests/unit/backend/test_scan_workers.py`** — Primary test file (820+ lines). Covers both `ScanSingleLibraryWorker` and `ScanAllLibrariesWorker` with mocked `scan_directories`, `os.scandir`, `shutil.disk_usage`.
- **`tests/unit/backend/test_scan_worker_all_extended.py`** — Extended parallel-specific tests (library error signals, partial failures).
- **`tests/unit/test_additional_coverage.py`** / **`test_extended_coverage.py`** — Additional edge-case coverage.

### Key Testing Patterns

- **DirectConnection**: All signal assertions use `Qt.DirectConnection` because workers execute synchronously in tests (no event loop).
- **Logger Patches**: Patches target per-module loggers (`scan_worker_single.logger`, `scan_worker_all.logger`). The shared base functions accept a `log_target` parameter so the patched per-module logger is used.
- **Ordering**: Parallel execution is non-deterministic, so tests use `sorted()` or `set()` comparisons for multi-library results.

### Thread Safety in Tests

Tests run `ScanAllLibrariesWorker.run()` directly (blocking). The `ThreadPoolExecutor` submits tasks, waits for completion via `executor.shutdown(wait=True)`, then merges results — all within the calling thread's stack. No real threading races occur in test mode.

## DB Thread Safety

- SQLite `WAL` mode with `check_same_thread=False` and `busy_timeout=5000`
- Each `_scan_library_pass` opens its own DB session via `get_session()`
- `save_season_data` and `save_movie_data` manage their own session lifecycle
