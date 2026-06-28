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
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, List, Optional, TypeVar

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


def to_async(
    callable: F,
) -> Callable[..., Awaitable[Any]]:
    """Decorate a synchronous callable as an async function.

    The returned wrapper submits *callable* to :func:`run_in_executor` on
    every invocation.

    Args:
        callable: A synchronous callable to wrap.

    Returns:
        An async function that, when awaited, runs *callable* in the
        default thread pool executor.

    Example:
        .. code-block:: python

            @to_async
            def read_file(path: str) -> str:
                with open(path) as handle:
                    return handle.read()

            contents = await read_file("/tmp/data.txt")
    """

    @functools.wraps(callable)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await run_in_executor(callable, *args, **kwargs)

    return wrapper


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


async def gather_with_concurrency(
    n: int,
    *coroutines: Awaitable[T],
) -> List[T]:
    """Run coroutines with a limited concurrency level.

    Uses an :class:`asyncio.Semaphore` internally to ensure that no more
    than *n* coroutines are executing concurrently at any given time.
    Results are returned in the same order as the input coroutines.

    Args:
        n: Maximum number of coroutines to run concurrently.  Must be a
            positive integer.
        *coroutines: One or more awaitables to execute.

    Returns:
        A list of return values in the same order as *coroutines*.

    Raises:
        ValueError: If *n* is less than 1.

    Example:
        .. code-block:: python

            results = await gather_with_concurrency(
                3,
                fetch_item("a"),
                fetch_item("b"),
                fetch_item("c"),
                fetch_item("d"),
            )
    """
    if n < 1:
        raise ValueError(f"Concurrency limit must be >= 1, got {n}")

    semaphore: AsyncSemaphore = AsyncSemaphore(n)

    async def _semaphore_wrapper(coroutine: Awaitable[T]) -> T:
        async with semaphore:
            return await coroutine

    return await asyncio.gather(
        *(_semaphore_wrapper(coroutine) for coroutine in coroutines)
    )


# ---------------------------------------------------------------------------
# Task lifecycle helpers
# ---------------------------------------------------------------------------


def cancel_task_safely(task: Optional["asyncio.Task[Any]"]) -> None:
    """Cancel an asyncio task and suppress ``CancelledError``.

    Logs at DEBUG level when a task is cancelled.  Does nothing if *task*
    is ``None``, already cancelled, or already finished.

    Args:
        task: The :class:`asyncio.Task` to cancel, or ``None``.

    Example:
        .. code-block:: python

            current_task = asyncio.current_task()
            cancel_task_safely(current_task)
    """
    if task is None:
        return

    if task.done():
        logger.debug(
            "Task %s is already done, skipping cancellation.",
            task.get_name() if hasattr(task, "get_name") else task,
        )
        return

    if task.cancelled():
        logger.debug(
            "Task %s is already cancelled, skipping.",
            task.get_name() if hasattr(task, "get_name") else task,
        )
        return

    task.cancel()
    logger.debug(
        "Task %s cancelled.",
        task.get_name() if hasattr(task, "get_name") else task,
    )


# ---------------------------------------------------------------------------
# Event loop helpers
# ---------------------------------------------------------------------------


def get_event_loop_safe() -> asyncio.AbstractEventLoop:
    """Return the running event loop, or create a new one if none exists.

    Attempts to retrieve the currently running event loop via
    :func:`asyncio.get_running_loop`.  If no loop is running, it falls
    back to :func:`asyncio.get_event_loop` (which may create a new loop
    on Python >= 3.10 when no loop is set).

    A warning is logged when a new loop has to be created, because under
    normal operation with ``qasync`` a running loop should always be
    available.

    Returns:
        An :class:`asyncio.AbstractEventLoop` instance.

    Example:
        .. code-block:: python

            loop = get_event_loop_safe()
            loop.call_soon(some_callback)
    """
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "No running event loop found. Creating a new event loop. "
            "This may indicate that qasync is not properly initialised "
            "or that this function was called from a non-async context.",
        )
        loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop
