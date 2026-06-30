"""Async utilities for migrating from QThread-based threading to asyncio.

This module provides helpers for running synchronous I/O operations
asynchronously, decorating sync callables as async functions, limiting
concurrency with semaphores, and safely managing task lifecycle.

Stage 0 of the migration toward qasync-based asyncio integration.
"""

import asyncio
import atexit
import functools
import logging
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List, Optional, TypeVar

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type variables
# ---------------------------------------------------------------------------

F = TypeVar("F", bound=Callable[..., Any])
T = TypeVar("T")


# ---------------------------------------------------------------------------
# Default thread-pool executor helpers
# ---------------------------------------------------------------------------


async def run_in_executor(
    callable: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Run a synchronous callable in the default thread pool executor.

    Wraps ``asyncio.get_event_loop().run_in_executor()`` with the default
    ``ThreadPoolExecutor`` so that blocking I/O (filesystem, subprocess,
    database writes) does not block the asyncio event loop.

    Args:
        callable: A synchronous callable to execute in a thread pool worker.
        *args: Positional arguments forwarded to *callable*.
        **kwargs: Keyword arguments forwarded to *callable*.

    Returns:
        The return value of *callable*.

    Example:
        .. code-block:: python

            result = await run_in_executor(os.listdir, "/some/path")
    """
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        functools.partial(callable, *args, **kwargs),
    )


# ---------------------------------------------------------------------------
# Dedicated filesystem executor (Stage 5)
# ---------------------------------------------------------------------------
# A size-constrained ThreadPoolExecutor (max_workers=3) dedicated to
# filesystem I/O — directory walks, stat calls, mtime checks.  This
# prevents runaway scan threads from saturating the CPU and avoids
# overloading network filesystems with concurrent I/O requests.

_FS_EXECUTOR_LOCK: threading.Lock = threading.Lock()
_FS_EXECUTOR: Optional[ThreadPoolExecutor] = None


def get_fs_executor() -> ThreadPoolExecutor:
    """Return the process-lifetime filesystem executor singleton.

    The executor is created with ``max_workers=3`` on first call and
    automatically shut down at interpreter exit via ``atexit``.  Call
    :func:`shutdown_fs_executor` to shut it down earlier.

    Returns:
        A :class:`concurrent.futures.ThreadPoolExecutor` with at most 3
        worker threads.
    """
    global _FS_EXECUTOR
    if _FS_EXECUTOR is None:
        with _FS_EXECUTOR_LOCK:
            if _FS_EXECUTOR is None:
                _FS_EXECUTOR = ThreadPoolExecutor(
                    max_workers=3,
                    thread_name_prefix="fs_executor",
                )
    return _FS_EXECUTOR


def shutdown_fs_executor() -> None:
    """Shut down the filesystem executor, cancelling queued futures.

    Safe to call multiple times.  After this call a new executor will be
    created on the next :func:`get_fs_executor` call.
    """
    global _FS_EXECUTOR
    with _FS_EXECUTOR_LOCK:
        executor = _FS_EXECUTOR
        if executor is not None:
            logger.info("Shutting down filesystem executor...")
            executor.shutdown(wait=False, cancel_futures=True)
            _FS_EXECUTOR = None
            logger.info("Filesystem executor shut down.")


atexit.register(shutdown_fs_executor)


async def run_in_fs_executor(
    callable: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Run a synchronous callable in the dedicated filesystem executor.

    Uses :meth:`asyncio.AbstractEventLoop.run_in_executor` with the
    size-constrained (``max_workers=3``) :func:`get_fs_executor` pool.
    Prefer this over :func:`run_in_executor` for all filesystem I/O
    (``os.scandir``, ``os.stat``, ``Path.iterdir``, ``Path.stat``,
    directory walks).

    Args:
        callable: A synchronous callable to execute.
        *args: Positional arguments forwarded to *callable*.
        **kwargs: Keyword arguments forwarded to *callable*.

    Returns:
        The return value of *callable*.
    """
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        get_fs_executor(),
        functools.partial(callable, *args, **kwargs),
    )


# ---------------------------------------------------------------------------
# Semaphore and concurrency control
# ---------------------------------------------------------------------------


class AsyncSemaphore:
    """A context-manager wrapper around :class:`asyncio.Semaphore`.

    Provides an idiomatic async context manager interface for controlling
    access to a limited resource.  Use it in ``async with`` blocks to
    limit the number of concurrent operations.

    Args:
        value: The initial capacity of the semaphore (number of concurrent
            entries allowed).  Must be a positive integer.

    Example:
        .. code-block:: python

            semaphore = AsyncSemaphore(5)
            async with semaphore:
                await some_io_bound_work()
    """

    def __init__(self, value: int) -> None:
        if value < 1:
            raise ValueError(f"Semaphore value must be >= 1, got {value}")
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(value)

    async def __aenter__(self) -> None:
        """Acquire the semaphore, blocking if the capacity is exhausted."""
        await self._semaphore.acquire()

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_value: Optional[BaseException],
        traceback: Optional[object],
    ) -> None:
        """Release the semaphore, allowing another waiter to proceed."""
        self._semaphore.release()


# ---------------------------------------------------------------------------
# Global concurrency semaphores (Stage 6)
# ---------------------------------------------------------------------------

_NETWORK_SEMAPHORE: Optional[asyncio.Semaphore] = None
_SUBPROCESS_SEMAPHORE: Optional[asyncio.Semaphore] = None
_SEMAPHORE_LOCK: threading.Lock = threading.Lock()
_NETWORK_SEMAPHORE_VALUE: int = 10
_SUBPROCESS_SEMAPHORE_VALUE: int = 3


def get_network_semaphore() -> asyncio.Semaphore:
    """Return the process-lifetime network concurrency semaphore singleton.

    Limits the number of **concurrent in-flight** API requests (TMDB,
    Jellyfin, etc.) to ``max_concurrent=10``.  Complements the token-bucket
    rate limiter in :class:`~lan_streamer.providers.http_client.AsyncHTTPClient`
    by capping peak parallelism.

    Returns:
        An :class:`asyncio.Semaphore` with value 10.
    """
    global _NETWORK_SEMAPHORE
    if _NETWORK_SEMAPHORE is None:
        with _SEMAPHORE_LOCK:
            if _NETWORK_SEMAPHORE is None:
                _NETWORK_SEMAPHORE = asyncio.Semaphore(_NETWORK_SEMAPHORE_VALUE)
    return _NETWORK_SEMAPHORE


def get_subprocess_semaphore() -> asyncio.Semaphore:
    """Return the process-lifetime subprocess concurrency semaphore singleton.

    Limits the number of **concurrent** FFmpeg / FFprobe subprocesses to
    ``max_concurrent=3``, preventing disk thrashing and CPU exhaustion
    during large metadata scans on network storage.

    Returns:
        An :class:`asyncio.Semaphore` with value 3.
    """
    global _SUBPROCESS_SEMAPHORE
    if _SUBPROCESS_SEMAPHORE is None:
        with _SEMAPHORE_LOCK:
            if _SUBPROCESS_SEMAPHORE is None:
                _SUBPROCESS_SEMAPHORE = asyncio.Semaphore(_SUBPROCESS_SEMAPHORE_VALUE)
    return _SUBPROCESS_SEMAPHORE


async def async_run_subprocess(
    command: List[str],
    stdin: Optional[bytes] = None,
    timeout: Optional[float] = None,
) -> "subprocess.CompletedProcess[str]":
    """Run a subprocess asynchronously via ``asyncio.create_subprocess_exec``.

    Acquires :func:`get_subprocess_semaphore` before spawning the process,
    reads stdout/stderr incrementally via ``communicate()``, and returns a
    :class:`subprocess.CompletedProcess` with ``stdout`` / ``stderr`` as
    decoded strings.

    Args:
        command: The executable and its arguments (e.g. ``["ffmpeg", "-y",
            "-i", "input.mp4", ...]``).
        stdin: Optional bytes to send to the process's stdin.
        timeout: Optional timeout in seconds for ``communicate()``.

    Returns:
        A :class:`subprocess.CompletedProcess[str]` with ``stdout`` and
        ``stderr`` as strings.

    Raises:
        asyncio.TimeoutError: If the subprocess does not complete within
            *timeout* seconds.
    """
    semaphore = get_subprocess_semaphore()
    async with semaphore:
        logger.debug("Spawning subprocess: %s", " ".join(command))
        process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=stdin),
                timeout=timeout,
            )
        except BaseException as exception_instance:
            if isinstance(exception_instance, asyncio.TimeoutError):
                logger.warning(
                    "Subprocess timed out after %ss: %s", timeout, " ".join(command)
                )
            elif isinstance(exception_instance, asyncio.CancelledError):
                logger.warning("Subprocess was cancelled: %s", " ".join(command))
            else:
                logger.warning(
                    "Exception during subprocess execution: %s", exception_instance
                )
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
            raise

        return subprocess.CompletedProcess(
            args=command,
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=stdout_bytes.decode("utf-8", errors="replace")
            if stdout_bytes
            else "",
            stderr=stderr_bytes.decode("utf-8", errors="replace")
            if stderr_bytes
            else "",
        )
