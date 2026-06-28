# Async and Threading Hybrid Refactor Review & Improvements

This document evaluates the hybrid `asyncio` and `threading` architecture of the `lan-streamer` application. It assesses how well the refactor utilizes the strengths of both models, identifies potential issues and anti-patterns, and outlines a comprehensive plan for further refactoring.

---

## 1. Executive Summary & Hybrid Strategy Assessment

The current refactor successfully implements a **hybrid execution model** where:
*   **`asyncio` (via `qasync`)** orchestrates the application event loop, network clients (`aiohttp` with rate limiting), background timers, and Qt UI event coordination.
*   **`ThreadPoolExecutor` / Threads** handle blocking OS-level operations (such as recursive directory crawling, file stat checks, and subtitle renaming) and native C-level tasks (VLC playback).

This is a **highly effective division of labor**. Network drives (NAS/SMB/NFS mounts) introduce significant, unpredictable I/O latency. Blocking operations on these mounts cannot be executed directly on the main async event loop without freezing the Qt user interface. Offloading them to isolated worker threads keeps the UI fully responsive.

However, the current implementation still exhibits several architectural risks, nested threading overhead, and resource management inefficiencies.

---

## 2. Review of the Current Architecture (Pros and Cons)

### Pros
*   **WAL Mode Concurrency**: Transitioning to SQLite Write-Ahead Logging (WAL) mode enables concurrent reads while the serialized `AsyncDatabaseWriter` executes database writes sequentially.
*   **UI Thread Safeguard**: Filesystem scans and API calls are offloaded from the Qt GUI thread, ensuring 100% UI responsiveness.
*   **Cooperative Cancellation**: Replaced polling-based cancellation in workers with clean coroutine cancellation and safe task tracking.

### Cons
*   **Nested Executor Overhead**: A library-level `ThreadPoolExecutor` spawns jobs that call `scan_directories`, which in turn submits sub-tasks to the global `_global_scan_executor`. This nested threading causes GIL contention and high context-switching overhead.
*   **Ad-Hoc Executors**: Components like `_discover_tree` spin up local, unmanaged thread pools rather than routing work through the centralized, size-limited `FileSystemExecutor`.
*   **Unthrottled Subprocesses**: Spawning concurrent `ffprobe` processes without strict semaphore limits can saturate CPU and Disk I/O on network mounts.

---

## 3. Organization of Possible Bugs & Issues

### Issue A: Nested Thread Pool Saturation & GIL Lockups
*   **Description**: `ScanAllLibrariesWorker` spawns a local `ThreadPoolExecutor` to run `_scan_library_pass` for each library in parallel. Inside that thread, it calls `scan_directories`, which spawns more threads via `get_scan_executor()` to scan individual series/movies.
*   **Danger to Application**: **High**. Creating nested thread pools can lead to CPU starvation, high memory overhead (each thread carries an 8MB stack allocation), and potential pool exhaustion/lockups if threads wait on each other.
*   **Likelihood of Occurrence**: **Medium** (primarily when scanning multiple large libraries simultaneously on low-spec hardware or slow network mounts).
*   **Complexity of Fix**: **Medium**. Unify all directory crawling and scanning tasks into a single managed queue that routes I/O tasks to the centralized `FileSystemExecutor`.

### Issue B: Orphaned Subprocesses on Task Cancellation
*   **Description**: When a scanning worker is cancelled (e.g., via `cancel_task_safely` or when the application is closed), pending subprocesses (like `ffprobe`) may continue running as orphaned zombie processes because the cancellation does not cleanly propagate to the process handle.
*   **Danger to Application**: **Medium**. Orphaned processes leak memory and CPU, leading to degraded system performance over time.
*   **Likelihood of Occurrence**: **Medium** (whenever a scan is manually cancelled mid-run).
*   **Complexity of Fix**: **Medium**. Ensure `async_run_subprocess` registers a clean-up handler to explicitly call `process.terminate()` or `kill()` in a `finally` block when cancelled.

### Issue C: SQLite Write Queue Saturation under High Parallelism
*   **Description**: High concurrency in the scanner threads submitting write tasks to `AsyncDatabaseWriter` can lead to queue growth and transaction lockups if connection limits are exceeded.
*   **Danger to Application**: **Medium** (can cause database timeouts or delayed UI updates).
*   **Likelihood of Occurrence**: **Low** (due to WAL mode concurrency, but possible during massive initial imports).
*   **Complexity of Fix**: **Low**. Implement batching inside the write queue handler to flush multiple records in a single transaction.

### Issue D: Ad-Hoc Thread Pool Leaks
*   **Description**: Ad-hoc thread pools spun up via `with ThreadPoolExecutor()` in functions like `_discover_tree` do not share process-lifetime cleanup constraints, potentially leaking threads if an exception occurs before the context manager block completes.
*   **Danger to Application**: **Low** (minor resource leak).
*   **Likelihood of Occurrence**: **Low**.
*   **Complexity of Fix**: **Low**. Replace all ad-hoc executors with calls to the global `FileSystemExecutor`.

---

## 4. Proposed Improvements (Organized by Complexity)

### Low Complexity

#### 1. Add Daemon Flag to Global Thread Pools
*   **Improvement**: Explicitly configure all global executors (like `_FS_EXECUTOR` and `_global_scan_executor`) to use daemon threads by subclassing or configuring the worker initialization. This guarantees that background worker threads do not block application exit.
*   **Rationale**: Simplifies process teardown and avoids hangs on exit if `atexit` handlers fail.

#### 2. Centralize Concurrency Semaphores
*   **Improvement**: Expose the network and subprocess semaphores in `async_utils.py` so that all HTTP clients and technical probe utilities share the same limits.
*   **Rationale**: Prevents different modules from exceeding API rate limits or disk I/O caps independently.

---

### Medium Complexity

#### 1. Unify Filesystem Operations under `FileSystemExecutor`
*   **Improvement**: Replace local thread pools in `scan_worker_all.py` (such as `_discover_tree`) with `run_in_fs_executor` calls.
*   **Rationale**: Enforces a single bottleneck (`max_workers=3`) for all filesystem-touching operations, protecting network drives from saturation.

#### 2. Clean Up Subprocess Termination
*   **Improvement**: Enhance `async_run_subprocess` to handle `asyncio.CancelledError` explicitly:
    ```python
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(...)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    ```
*   **Rationale**: Prevents orphaned zombie processes upon scan cancellation.

---

### High Complexity

#### 1. Decompose Scanner into an Async Queue Pipeline
*   **Improvement**: Fully rewrite `scanner/core.py` to replace synchronous scanning loops with a pipeline of async tasks cooperating over queues:
    ```
    Dir Crawler (Thread Pool) ➔ Delta Queue ➔ TMDB API Task (Async Loop) ➔ Metadata Queue ➔ DB Writer
    ```
*   **Rationale**: Eliminates nested executors entirely. The GIL is released during network calls, and Disk I/O is cleanly isolated to the size-constrained thread pool.

---

## 5. Summary of Bug Likelihood & Danger

| Potential Bug / Risk | Danger Level | Likelihood | Fix Complexity | Mitigation Plan |
|---|---|---|---|---|
| **Nested Executor Saturation** | **High** (CPU/IO locks) | **Medium** | Medium | Consolidate library and folder scans into a single queue routed to `FileSystemExecutor`. |
| **Orphaned Subprocesses** | **Medium** (Resource leak) | **Medium** | Medium | Implement explicit `process.kill()` on `CancelledError` in `async_run_subprocess`. |
| **SQLite Queue Saturation** | **Medium** (DB lag) | **Low** | Low | Implement write batching for bulk operations. |
| **Thread Pools Exit Hangs** | **Low** (Hang on exit) | **Low** | Low | Ensure all background workers are created as daemon threads. |
