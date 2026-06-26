# Threading Improvements Review and Plan

This document details the code review of the changes introduced in the `threading_improvements` branch compared to `origin/main`. It identifies potential bugs, reference cycle issues, and antipatterns, lists pros and cons, outlines a plan to resolve them, and details the likelihood and impact of each issue.

---

## 🐛 Identified Bugs & Issues

Below is a detailed list of potential bugs and safety issues found in the current branch.

### 1. Re-entrant Deadlock in `BaseScanWorker.emit_detail_progress`
* **Severity**: 🔴 Critical / High
* **Likelihood**: 🟢 Very High in production, but undetected by current unit tests due to test libraries containing fewer than 20 items.
* **Fix Complexity**: 🟢 Low

#### Description
In `src/lan_streamer/backend/scan_worker_base.py`, `self._lock` is initialized as a standard non-reentrant `threading.Lock()`.
When `emit_detail_progress` is called, it acquires `self._lock` and appends a progress event to the buffer. If the buffer size reaches or exceeds 20 items, it calls `self.flush_detail_progress()` from within the `with self._lock:` block.
However, `flush_detail_progress()` also attempts to acquire `self._lock` using `with self._lock:`. Since standard locks are non-reentrant, this leads to an immediate thread deadlock, freezing the scanning thread.

#### Pros and Cons of Current Implementation
* **Pros**: Batching detail progress reduces signal emission frequency and GUI thread overhead.
* **Cons**: Guarantees a deadlock and thread hang as soon as any scanning library contains 20 or more files/subdirectories.

#### Plan to Resolve
Modify `emit_detail_progress` to determine if a flush is needed, release the lock, and then call `flush_detail_progress()` without holding the lock. This keeps signal emission and the nested call out of the locked block, completely avoiding the deadlock.

---

### 2. Database Corruption & UI Inconsistency on Cooperative Cancellation
* **Severity**: 🟠 High (Data integrity and cache pollution)
* **Likelihood**: 🟡 Medium (Occurs whenever a scan is cancelled by the user midway)
* **Fix Complexity**: 🟡 Medium

#### Description
When cooperative cancellation is triggered (e.g., via `self.isInterruptionRequested()`), `scan_directories` returns early with an incomplete library dictionary containing only the subset of directories processed before interruption.
However, both `ScanWorker` and `ScanAllLibrariesWorker` continue to process this partial result:
* `ScanWorker` emits `finished(library)` with the incomplete dictionary. The `Controller` receives this and calls `_save_library_data` which invokes `save_library(..., library)`. This updates the database and sets the in-memory cache `self.cached_library_data` to the partial results, truncating the media items shown in the UI.
* In `ScanAllLibrariesWorker`, the individual thread tasks write the incomplete directories list back to the database, marking the directories' mtimes as updated. In subsequent scans, these directories will be skipped due to matching mtimes, causing items to be permanently missing from the catalog.

#### Pros and Cons of Current Implementation
* **Pros**: Cooperative cancellation successfully halts scanning loops.
* **Cons**: Writes corrupted/partial states to the database and UI caches, causing catalog pollution, data loss, and UI truncation.

#### Plan to Resolve
Modify the workers (`ScanWorker` and `ScanAllLibrariesWorker`) to check `self.isInterruptionRequested()` immediately after directory scans. If cancelled, they must discard the partial library dictionary, skip writing to the database, and emit a cancellation status instead of calling `finished.emit(library)`.

---

### 3. Reference Cycle / Memory Leak in `WorkerSlot.stop` cleanup
* **Severity**: 🟡 Medium / Low (Resource Leak)
* **Likelihood**: 🟡 Medium (Occurs when stopping/re-starting workers or when controller is destroyed)
* **Fix Complexity**: 🟢 Low

#### Description
In `src/lan_streamer/system/threading_manager.py`, the nested `cleanup` closure in `make_cleanup` captures `w` (the worker thread instance) and `self` (the `WorkerSlot` instance) as strong references. Since `self._stopping_workers` also holds a strong reference to `worker`, a reference cycle is formed:
`WorkerSlot` ➔ `self._stopping_workers` ➔ `worker` ➔ Qt signal connection ➔ `cleanup` closure ➔ `WorkerSlot` / `worker`.
If a worker thread is terminated or fails to emit the `finished` signal, or if the `WorkerSlot` is cleared, these objects will never be garbage collected.

#### Pros and Cons of Current Implementation
* **Pros**: Keeps the `QThread` instance alive during deferred deletion to prevent PySide6 crash on thread exit.
* **Cons**: Creates a strong reference cycle that leaks memory and Qt objects if signals are not emitted.

#### Plan to Resolve
Use `weakref` to capture weak references to `self` and `w` inside the `make_cleanup` closure.

---

## 📈 Non-Bug Improvements

These improvements enhance codebase quality, readability, type safety, and test coverage but do not resolve active bugs.

### 🟢 Low Complexity
1. **Restore Type Annotations in Controller**: Re-add the removed type annotations (e.g. `_running_pass3_after_scan: bool = False`) in `src/lan_streamer/ui_views/controller.py` to prevent static typing warnings and maintain strict `mypy` compliance.
2. **Explicit Log on Cancel**: Add distinct logging output when cooperative cancellation is triggered so that logs clearly show when and where a scan was aborted.

### 🟡 Medium Complexity
1. **Explicit Cancellation Signal**: Add a `cancelled = Signal()` signal to `BaseScanWorker` so the controller can listen to it and update the status bar (e.g., "Scan cancelled by user") instead of receiving a successful `finished` signal.
2. **Cancellation Unit & Integration Tests**: Implement dedicated tests simulating interruption requests on `ScanWorker` and `ScanAllLibrariesWorker` to verify that they do not save partial library states to the database and cancel outstanding futures correctly.

---

## 🔍 Likelihood and Risk Analysis

After completing the fixes, we evaluate the likelihood and risk of running into each of the identified issues:

| Issue | Danger / Impact | Original Likelihood | Post-Fix Likelihood | Risk Description |
| :--- | :--- | :--- | :--- | :--- |
| **Deadlock in emit_detail_progress** | 🔴 High | 🔴 Very High | 🟢 Extremely Low | Will freeze the scan process on any directory with >20 items. Post-fix, the lock is released before flushing. |
| **Data Loss on Cancel** | 🔴 High | 🟡 Medium | 🟢 Extremely Low | Partial scan writes lead to database data loss and cache pollution. Post-fix, partial saves are aborted. |
| **Reference Cycle Leak** | 🟡 Medium | 🟡 Medium | 🟢 Extremely Low | Leaks workers and WorkerSlot instances. Post-fix, weak references prevent cycles. |
