# Code Review: Parallelization & mtime Skip Optimization
**Base commit:** `6a324a6691d119cf3ad9040aaf806564be90df91`
**Branch:** `parallelization_2`
**Reviewer:** Senior Software Engineer
**Date:** 2026-06-25

---

## Executive Summary

These changes introduce four major features:
1. **Parallel library scanning** via `ThreadPoolExecutor` inside `ScanAllLibrariesWorker`
2. **Serialized database writes** via a dedicated `DatabaseWriterThread` queue
3. **TMDB rate-limiting** via a class-level lock with exponential backoff
4. **mtime-based directory skip optimization** at the series, season, and movie directory levels

The work is well-structured and test coverage is solid (93%+). However, there are several threading correctness issues, a subtle mtime correctness hole, potential deadlock paths, and test gaps that should be resolved before merging.

---

## 1. Threading & Deadlock Issues

### 1.1 `time.sleep()` called while holding `_class_rate_limit_lock` — HIGH SEVERITY

**File:** `src/lan_streamer/providers/tmdb.py`, lines 92–98

```python
with TMDBClient._class_rate_limit_lock:
    current_time = time.time()
    elapsed = current_time - TMDBClient._class_last_request_time
    delay = 0.1 - elapsed
    if delay > 0:
        time.sleep(delay)            # ← HOLDS LOCK WHILE SLEEPING
    TMDBClient._class_last_request_time = time.time()
```

**Problem:** The rate-limit lock is held for the entire sleep duration. Every other scan thread that calls `_make_request` is blocked during this sleep, effectively serializing **all** TMDB calls rather than just throttling them to 10 req/s. With a library of 100 series, this sleep propagates to every parallel worker, defeating the purpose of parallelization.

**Correct approach:** Record the timestamp, release the lock, *then* sleep:
```python
with TMDBClient._class_rate_limit_lock:
    elapsed = time.time() - TMDBClient._class_last_request_time
    delay = max(0.0, 0.1 - elapsed)
    TMDBClient._class_last_request_time = time.time() + delay  # reserve the slot
# Lock released — sleep outside
if delay > 0:
    time.sleep(delay)
```
This is the standard "token bucket" pattern. The lock only protects the timestamp update, not the sleep.

---

### 1.2 `DatabaseWriterThread` — 60-second blocking wait per season on scan threads — MEDIUM SEVERITY

**File:** `src/lan_streamer/backend/scan_worker_single.py`, `_season_callback`

```python
task = DatabaseWriteTask(...)
self.database_queue.put(task)
if not task.event.wait(timeout=60):
    raise TimeoutError(...)
```

The scan thread — already running inside the global `ThreadPoolExecutor` — blocks for up to 60 seconds waiting for the DB write to complete. If the DB writer is briefly stalled (e.g., another slow write, disk flush, WAL checkpoint), all `ThreadPoolExecutor` threads pile up here.

**Concern:** The timeout value of 60 seconds is arbitrary. A legitimate WAL checkpoint on a large library could exceed this, causing spurious `TimeoutError` exceptions that surface as scan failures — data loss from the user's perspective.

**Recommendation:**
- Increase the timeout or make it configurable via `config`.
- Log a warning at a partial threshold (e.g., 10s), not just on failure.
- Consider fire-and-forget for non-correctness-critical writes (mtime persistence) vs. confirmed writes for season data.

---

### 1.3 `ScanAllLibrariesWorker` — shared `problems` list may be mutated from multiple threads without consistent locking — MEDIUM

**File:** `src/lan_streamer/backend/scan_worker_all.py`

The `self.problems` list is appended from multiple library scan threads inside their respective callbacks. The lock used is `self._lock` in some places. **Verify** that every `self.problems.append(...)` path in `scan_worker_all.py` is consistently guarded by `with self._lock:` — a single unguarded append from a concurrent thread is a data race.

---

### 1.4 `flush_detail_progress()` emits Qt signals after lock release — GOOD (document it) — INFO

```python
with self._detail_progress_lock:
    batch = list(self._detail_progress_buffer)
    self._detail_progress_buffer.clear()
# Lock released here — correct
self.detail_progress_batch.emit(batch)
```

Intentional and correct — Qt signal emission must not happen under a Python lock to avoid priority inversion with the UI thread. Add a comment documenting this invariant for future maintainers.

---

## 2. mtime Correctness Issues

### 2.1 Series mtime skip in `core.py` is dead code for the production scan path — HIGH SEVERITY

**File:** `src/lan_streamer/scanner/core.py`, lines 427–433

```python
if (
    library_type != "movie"
    and not series_force_refresh
    and not offline          # ← only fires when offline=False
    and existing_series
    and has_meta
):
```

In the standard two-pass `ScanWorker` flow:
- **Pass 1:** `offline=True, metadata_only=False` → `not offline` is False → check **never fires**
- **Pass 2:** `offline=False, metadata_only=True` → the **metadata_only branch** at the top of `scan_directories` is taken → this non-metadata_only code block is **never reached**

**Consequence:** This optimization is dead code for `ScanWorker` (the only production scan entry point). It only fires when `scan_directories` is called directly with `offline=False, metadata_only=False` — which has no current production call site.

**Fix:** Move the check into `_discover_seasons_to_process` (which already has `_check_series_directory_mtime_unchanged`) so it fires in Pass 1 where it would have real impact, OR add an explicit check at the top of `scan_series` for the pass 1 path.

---

### 2.2 Float mtime equality comparison — platform correctness risk — LOW/MEDIUM

**Files:** `scan_tv.py`, `scan_movie.py`, `core.py`

```python
if cached_mtime is not None and current_mtime == cached_mtime:
```

**Risk:** On FAT32/exFAT (external USB drives) `st_mtime` has 2-second resolution. On some NFS server configurations, mtime resolution may be 1 second. A sub-second write to a season could update the mtime but round to the same integer, causing the optimization to **incorrectly skip a changed directory**.

**Recommendation:** Store and compare as `int(mtime)` on known low-resolution filesystems, or add a file-size fallback when `abs(current_mtime - cached_mtime) < 2.0`.

---

### 2.3 Deleted season not detected when series directory mtime unchanged — EDGE CASE

**File:** `src/lan_streamer/scanner/scan_tv.py`, `_check_series_directory_mtime_unchanged` fast path

When series mtime matches, `iterdir()` is skipped and season list comes from `existing_series_data`. If a season folder is deleted but the parent series directory mtime did not update (possible on some non-POSIX NFS configurations), the deleted season remains in the UI indefinitely.

**Note:** On POSIX-conformant filesystems (ext4, xfs, btrfs), deleting a subdirectory always updates the parent mtime — this is a non-issue for local Linux filesystems. Document as a known limitation for non-POSIX NFS mounts.

---

### 2.4 `save_directory_mtime()` bypasses `DatabaseWriterThread` — concurrent writer antipattern — MEDIUM

**File:** `src/lan_streamer/db/library_shared.py`, `save_directory_mtime()`

`save_directory_mtime` opens its own SQLite session and writes directly from scan threads (inside `ThreadPoolExecutor`), bypassing the `DatabaseWriterThread` queue. This means multiple scan threads can write to SQLite simultaneously with the DB writer thread.

SQLite WAL mode allows only **one writer at a time** — others will block until the busy-timeout. This adds latency to scan threads and is an architectural antipattern given the explicit single-writer design.

**Fix:** Add `action="save_directory_mtime"` to `DatabaseWriteTask` and route all mtime saves through the queue.

---

### 2.5 `get_directory_mtime()` opens N+1 DB connections during scan — MEDIUM PERFORMANCE

**File:** `src/lan_streamer/db/library_shared.py`

During a scan with 50 series × 5 seasons = 250 `get_directory_mtime` calls, each opens its own SQLite session. While SQLite sessions are cheap on local disk, on a system where `lan_streamer.db` is on a network mount this causes 250 sequential DB round-trips on scan threads.

**Recommendation:** Pre-load all `ScannedDirectory` records for a root into an in-memory `dict[str, float]` at the start of each scan, pass it through as a parameter, and avoid per-directory DB calls in the hot path entirely.

---

## 3. Design & Architecture Issues

### 3.1 Global `ThreadPoolExecutor` is unbounded — NAS saturation risk — MEDIUM

**File:** `src/lan_streamer/scanner/core.py`, `get_scan_executor()`

```python
_global_scan_executor = ThreadPoolExecutor(
    thread_name_prefix="scan_worker",
)
```

No `max_workers` limit. Python's default caps at `min(32, os.cpu_count() + 4)`. On a 4-core system this is 8 concurrent scan threads, each doing `iterdir()` and `stat()` calls over SMB. 8 concurrent network filesystem operations can saturate the NAS's connection queue and make all of them slow — worse than sequential scanning.

**Recommendation:** Make `max_workers` configurable (e.g., in `config.json`), defaulting to `4` for network shares. A user scanning a local NVMe drive can raise this; a user on a slow NAS should lower it.

---

### 3.2 `_series_belongs_to_root` imported with private prefix — API design smell — LOW

**File:** `scan_worker_all.py` imports `_series_belongs_to_root` from `scan_worker_base.py`.

The leading underscore signals "private to module" but it's cross-imported. Remove the underscore or move it to a public shared utilities module.

---

### 3.3 `DatabaseWriteTask.callback` is defined but never used — dead code — LOW

**File:** `database_writer.py`, line 18.

No call site passes a `callback`. The `callback` parameter and the branch `if task.callback and task.result: task.callback(task.result)` are dead code. Remove to reduce cognitive overhead.

---

### 3.4 Unbounded `database_queue` — memory pressure risk for large libraries — LOW/MEDIUM

If scan threads produce work faster than the DB writer can process it, `database_queue` grows unboundedly. Each queued `DatabaseWriteTask` holds full season/episode data dicts — for a 10,000-episode library this could be several hundred MB of in-flight state.

**Recommendation:** Use `queue.Queue(maxsize=N)` (e.g., `maxsize=len(libraries) * 4`) to apply back-pressure, causing scan threads to block rather than accumulate unbounded state.

---

### 3.5 Deferred `from lan_streamer import db` imports in hot-path functions — style — LOW

**Files:** `scan_tv.py`, `scan_movie.py`, `core.py`

```python
from lan_streamer import db as _db   # inside function called thousands of times
```

Python caches module imports so this is effectively free at runtime. But it's nonstandard and confusing. Add a comment at each site:
```python
# Deferred import to break circular dependency: scanner → db → scanner/__init__
from lan_streamer import db as _db
```

---

## 4. Code Quality & Antipatterns

### 4.1 `detect_movie_file_changes` hand-rolled DFS vs `os.walk` — LOW

```python
stack = [str(movie_dir)]
while stack:
    curr_dir = stack.pop()
    with os.scandir(curr_dir) as it: ...
```

Functionally equivalent to `os.walk(movie_dir, followlinks=True)` but more verbose. `os.walk` also uses `scandir` internally. Consider using `os.walk` for readability.

---

### 4.2 `merge_stats_dicts` vs `merge_stats_dicts_for_report` — naming confusion — LOW

Two nearly identical functions in `scan_worker_base.py`. One mutates in-place, one returns a new dict. The naming doesn't convey the distinction. Rename for clarity: `accumulate_stats_inplace` / `merge_stats_snapshot`.

---

### 4.3 Missing docstring on `_check_series_directory_mtime_unchanged` explaining the filesystem semantics — INFO

The docstring explains *what* the function does but not *why* the series mtime is sufficient to skip `iterdir()`. Adding one sentence: "On POSIX filesystems, adding or removing a subdirectory atomically updates the parent directory's mtime" would prevent future maintainers from questioning the optimization.

---

## 5. Test Coverage Gaps

### 5.1 No test for rate-limit lock-while-sleeping regression — HIGH

The bug in §1.1 has no test. A regression test:

```python
def test_tmdb_rate_limit_releases_lock_before_sleep():
    # Two threads must both complete within ~0.3s, not serialize to 0.2s+
    import concurrent.futures, time
    client = TMDBClient(...)
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client._make_request, "GET", url) for _ in range(2)]
        [f.result() for f in futures]
    assert time.time() - start < 0.3  # would be ~0.2s with serialized sleep
```

---

### 5.2 No test for `DatabaseWriteTask` timeout path — MEDIUM

The `task.event.wait(timeout=60)` branch has no test. Should test that a stalled `DatabaseWriterThread` causes `TimeoutError` and it is properly logged/recorded in `problems`.

---

### 5.3 Series mtime skip test does not cover the Pass 1 production path — MEDIUM

`test_series_mtime_skip_scanning` calls `scan_directories(offline=False, metadata_only=False)`. This is the dead-code path (§2.1). Tests should verify the optimization fires during simulated Pass 1 (`offline=True`) via `_discover_seasons_to_process`.

---

### 5.4 No migration correctness test — MEDIUM (required by AGENTS.md)

`0def24d4a3b4` creates `scanned_directories` and removes `last_scanned_mtime` from `seasons`/`movies`. No test verifies:
- Upgrading a DB with existing `last_scanned_mtime` data preserves season/movie records
- Downgrading correctly recreates the removed columns

Per `AGENTS.md`: *"Implement and write test cases verifying that database migrations handle existing data correctly without data loss."*

---

### 5.5 No test for `detect_movie_file_changes` with symlinked video files — LOW

The `entry.is_file(follow_symlinks=True)` path is not tested. On setups using symlinks to organize movies across drives, this could silently miss files.

---

## 6. Prioritized Remediation Table

| # | Area | Severity | Must fix? | Action |
|---|------|----------|-----------|--------|
| 1.1 | TMDB sleep inside lock | HIGH | ✅ Yes | Release lock before sleeping |
| 2.1 | Series mtime check dead code | HIGH | ✅ Yes | Move into `_discover_seasons_to_process` / Pass 1 path |
| 2.4 | `save_directory_mtime` bypasses DB writer | MEDIUM | ✅ Yes | Route through `DatabaseWriteTask` |
| 5.1 | No test for rate-limit regression | HIGH | ✅ Yes | Add concurrency test |
| 5.4 | No migration correctness test | MEDIUM | ✅ Yes | Required by AGENTS.md |
| 1.2 | 60s arbitrary DB write timeout | MEDIUM | 🟡 Should | Make configurable; add partial timeout warning |
| 1.3 | `problems` list locking audit | MEDIUM | 🟡 Should | Audit all append sites in worker_all |
| 2.3 | N+1 DB reads for mtime | MEDIUM | 🟡 Should | Pre-load `ScannedDirectory` per root |
| 3.1 | Unbounded thread pool | MEDIUM | 🟡 Should | Configurable `max_workers` (default 4) |
| 3.4 | Unbounded DB queue | LOW | 🔵 Nice | `queue.Queue(maxsize=N)` |
| 2.2 | Float mtime equality on low-res FS | LOW | 🔵 Nice | Tolerance or int cast |
| 4.3 | `DatabaseWriteTask.callback` dead | LOW | 🔵 Nice | Remove |
| 3.2 | `_series_belongs_to_root` prefix | LOW | 🔵 Nice | Remove underscore |

---

## 7. What Is Done Well

- **`DatabaseWriterThread` single-writer design** is correct and eliminates SQLite `SQLITE_BUSY` for the primary write path.
- **Signal batching** (`_detail_progress_buffer` + lock, emit outside lock) correctly prevents calling Qt signals from non-QThread threads.
- **`os.scandir` migration** in `detect_tv_file_changes` and `detect_movie_file_changes` is a genuine I/O improvement — `DirEntry.stat()` reuses the `readdir` result, avoiding a separate `stat(2)` syscall per entry on Linux.
- **`_check_single_season_changed` early-return fix** (mtime match → unconditional `return False`) correctly prevents the `_changed` flag from overriding a confirmed-unchanged state.
- **`create_empty_stats()` extraction** eliminates 80+ lines of repeated dict literal boilerplate.
- **Conventional commits** are used consistently throughout all 30+ commits.
- **Test coverage at 93.45%** is well above the 90% threshold.
- **TMDB retry/backoff logic** (§1.1's intent) is the right approach — 429 handling with exponential backoff is correct. Only the lock scope needs fixing.

---

## Addendum: Critical Finding — `save_directory_mtime()` Never Commits

**File:** `src/lan_streamer/db/library_shared.py`, `save_directory_mtime()`

```python
def save_directory_mtime(path: str, mtime: float) -> None:
    with get_session() as session:
        record = session.scalars(
            select(ScannedDirectory).where(ScannedDirectory.path == path)
        ).first()
        if record:
            record.last_scanned_mtime = mtime
        else:
            record = ScannedDirectory(path=path, last_scanned_mtime=mtime)
            session.add(record)
        # ← NO session.commit() call here
```

**Problem:** `save_directory_mtime()` modifies/adds a `ScannedDirectory` record but never calls `session.commit()`. The write is silently rolled back when the `with` block exits unless the `get_session()` context manager auto-commits, which it does NOT (SQLAlchemy's `Session` context manager calls `session.close()` on exit, not `session.commit()`).

**Impact:** This is a **HIGH severity data loss bug** for the `save_series_mtime` path called from `scan_series` Phase 6 in `scan_tv.py`:

```python
# scan_tv.py Phase 6 — series mtime save
_db.save_directory_mtime(str(series_directory.absolute()), series_directory_mtime)
```

The series mtime is **never actually persisted to the database**. This means the series-level `_check_series_directory_mtime_unchanged()` will always return `False` (no cached mtime), so the `iterdir()` call is never skipped — the entire series mtime optimization at the `_discover_seasons_to_process` level is silently broken.

**Contrast with season/movie mtime saves:** The mtime upsert logic is duplicated (copy-pasted) inside `save_season_data()` and `save_movie_data()`, and those copies **do** call `session.commit()` at the end. So season and movie mtimes are persisted correctly, but series mtimes are not.

**Fix:**
```python
def save_directory_mtime(path: str, mtime: float) -> None:
    with get_session() as session:
        record = session.scalars(
            select(ScannedDirectory).where(ScannedDirectory.path == path)
        ).first()
        if record:
            record.last_scanned_mtime = mtime
        else:
            record = ScannedDirectory(path=path, last_scanned_mtime=mtime)
            session.add(record)
        session.commit()  # ← Add this
```

**Updated Prioritization Table Row:**

| # | Area | Severity | Must fix? | Action |
|---|------|----------|-----------|--------|
| A1 | `save_directory_mtime` missing `session.commit()` | **CRITICAL** | ✅ Yes | Add `session.commit()` |

---

## Addendum: Nested Lock Ordering in `ScanAllLibrariesWorker` — Potential Deadlock

**File:** `src/lan_streamer/backend/scan_worker_all.py`, `_season_callback` and `_movie_callback`

```python
with local_lock:              # Acquire local lock first
    ...
    with self._lock:          # Then acquire global lock — nested!
        if series_id not in self._scanned_series_ids:
            ...
```

Nested lock acquisition creates deadlock risk if any other code path acquires `self._lock` first and then tries to acquire `local_lock`. Even if this is currently safe (because `local_lock` is unique per library task), it is a fragile pattern. The two lock levels (`local_lock`, `self._lock`) should always be acquired in the same order, and this should be documented explicitly.

**Recommendation:** Separate the global stats update into a post-pass merge step (outside the hot callback path) to eliminate nested locking entirely, or use a thread-safe atomic counter rather than a lock-protected dict for the global IDs sets.

---

## Final Complete Prioritization Table

| # | Area | Severity | Must fix? |
|---|------|----------|-----------|
| A1 | `save_directory_mtime` missing `session.commit()` | **CRITICAL** | ✅ Yes |
| 1.1 | TMDB sleep inside rate-limit lock | HIGH | ✅ Yes |
| 2.1 | Series mtime skip dead code path in core.py | HIGH | ✅ Yes |
| 2.4 | `save_directory_mtime` called from scan thread bypassing DB writer | MEDIUM | ✅ Yes |
| 5.1 | No test for rate-limit regression | HIGH | ✅ Yes |
| 5.4 | No migration correctness test | MEDIUM | ✅ Yes |
| A2 | Nested lock ordering in `_season_callback` | MEDIUM | ✅ Yes |
| 1.2 | 60s arbitrary DB write timeout | MEDIUM | 🟡 Should |
| 1.3 | `problems` list locking audit | MEDIUM | 🟡 Should |
| 2.3 | N+1 DB reads for mtime | MEDIUM | 🟡 Should |
| 3.1 | Unbounded thread pool | MEDIUM | 🟡 Should |
| 3.4 | Unbounded DB queue | LOW | 🔵 Nice |
| 2.2 | Float mtime equality on low-res FS | LOW | 🔵 Nice |
| 4.3 | `DatabaseWriteTask.callback` dead | LOW | 🔵 Nice |
| 3.2 | `_series_belongs_to_root` private prefix | LOW | 🔵 Nice |
