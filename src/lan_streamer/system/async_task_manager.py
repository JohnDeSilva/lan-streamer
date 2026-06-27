"""
Asynchronous task manager bridging asyncio with a PySide6/Qt application lifecycle.

This module provides :class:`AsyncTaskManager`, a :class:`QObject` subclass that
wraps ``asyncio`` task management for use inside a ``qasync``-driven Qt
application.  It is Stage 0 of a migration from ``QThread``-based background
workers to ``asyncio``-based coroutines.

All task operations execute on the main thread because ``qasync`` runs the
asyncio event loop on the Qt main event loop.  No threading locks are needed.

Usage::

    manager = AsyncTaskManager(parent=some_qobject)

    async def do_work() -> None:
        ...

    manager.create_task(do_work(), name="my_task")

    # Recurring task
    manager.schedule_interval(
        lambda: do_work(), interval_seconds=300.0, name="scheduled_scan"
    )

    # Later
    manager.cancel_task("my_task")
    manager.stop_all()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

from PySide6.QtCore import QObject

logger = logging.getLogger(__name__)

DEFAULT_CANCEL_TIMEOUT: float = 5.0
"""Default number of seconds to wait for tasks to respond to cancellation."""

# Type alias for a factory that returns a coroutine.
CoroutineFactory = Callable[[], Coroutine[Any, Any, Any]]


class AsyncTaskManager(QObject):
    """
    Manages the lifecycle of ``asyncio`` tasks in a ``qasync``-based Qt application.

    Every created task is tracked by a unique name in an internal dictionary.
    Done-callbacks are supported and the internal dictionary is automatically
    cleaned up when a task completes.

    All public methods are safe to call from the Qt main thread.  If no asyncio
    event loop is running at the time of a call, a warning is logged and the
    operation is skipped gracefully.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """
        Initialise the task manager.

        Args:
            parent: Optional Qt parent :class:`QObject` for proper memory
                management.
        """
        super().__init__(parent)
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def create_task(
        self,
        coroutine: Coroutine[Any, Any, Any],
        name: str,
        on_done_callback: Optional[Callable[[asyncio.Task[Any]], Any]] = None,
    ) -> Optional[asyncio.Task[Any]]:
        """
        Schedule *coroutine* as a named asyncio task.

        The task is stored in an internal dictionary keyed by *name*.  When the
        task finishes (success, exception, or cancellation) it is automatically
        removed from tracking.  An optional *on_done_callback* is invoked with
        the completed task just before removal.

        Args:
            coroutine: The coroutine to run.
            name: A unique name for the task.  If a task with this name
                already exists it will be overwritten (the old task is **not**
                cancelled automatically).
            on_done_callback: Optional callable invoked with the completed
                :class:`asyncio.Task` when it finishes.

        Returns:
            The :class:`asyncio.Task` instance, or ``None`` if no event loop
            is currently running.

        Note:
            If a task with the same name already exists in the tracking
            dictionary, the old reference is silently replaced.  The old task
            continues running but is no longer tracked by this manager.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("No running event loop -- cannot create task '%s'.", name)
            try:
                coroutine.close()
            except Exception:
                pass
            return None

        task = asyncio.create_task(coroutine, name=name)
        self._tasks[name] = task

        def _on_task_done(completed_task: asyncio.Task[Any]) -> None:
            """Internal done-callback: clean up dict, then fire user callback."""
            # Only clean up if this task is still the one we track.
            if self._tasks.get(name) is completed_task:
                del self._tasks[name]
                logger.debug("Task '%s' completed and removed from tracking.", name)

            if on_done_callback is not None:
                try:
                    on_done_callback(completed_task)
                except Exception as error:
                    logger.error(
                        "Task '%s' done callback raised: %s",
                        name,
                        error,
                        exc_info=True,
                    )

        task.add_done_callback(_on_task_done)

        logger.info("Created task '%s' (id=%s).", name, id(task))
        return task

    def cancel_task(self, name: str) -> None:
        """
        Cancel a named task gracefully.

        If the task does not exist or has already completed this is a no-op
        (logged at DEBUG level).

        Args:
            name: The name of the task to cancel.
        """
        task = self._tasks.get(name)
        if task is None:
            logger.debug("No task named '%s' found to cancel.", name)
            return

        if task.done():
            logger.debug("Task '%s' is already done -- skipping cancellation.", name)
            return

        task.cancel()
        logger.info("Cancellation requested for task '%s'.", name)

    def cancel_all(self) -> None:
        """
        Cancel every currently tracked task.

        Tasks that have already finished are skipped.  This method iterates
        over a snapshot of the tracked names so it is safe even if tasks
        complete during iteration.
        """
        names = list(self._tasks.keys())
        if not names:
            logger.debug("cancel_all: no tasks to cancel.")
            return

        logger.info("Cancelling all %d tracked task(s).", len(names))
        for name in names:
            self.cancel_task(name)

    def get_task(self, name: str) -> Optional[asyncio.Task[Any]]:
        """
        Return the tracked task for *name*, or ``None`` if unknown.

        Args:
            name: The name of the task.

        Returns:
            The :class:`asyncio.Task` instance if it is still tracked, else
            ``None``.
        """
        return self._tasks.get(name)

    def task_names(self) -> list[str]:
        """
        Return a list of all currently tracked task names.

        Returns:
            A new list of task name strings.
        """
        return list(self._tasks.keys())

    def is_task_running(self, name: str) -> bool:
        """
        Return ``True`` if a task with *name* exists and has not completed.

        A task that has finished, been cancelled, or raised an exception is
        considered "not running".

        Args:
            name: The name of the task.

        Returns:
            ``True`` if the task exists and is not done, ``False`` otherwise.
        """
        task = self._tasks.get(name)
        if task is None:
            return False
        return not task.done()

    # ------------------------------------------------------------------
    # Scheduling helpers
    # ------------------------------------------------------------------

    async def _run_interval(
        self,
        coroutine_factory: CoroutineFactory,
        interval_seconds: float,
        name: str,
    ) -> None:
        """
        Coroutine body for :meth:`schedule_interval`.

        Calls the factory, awaits the returned coroutine, sleeps for the
        interval, then repeats.  If the coroutine or the factory raises, the
        error is logged and the loop continues.  If the task is cancelled the
        loop exits cleanly.
        """
        logger.debug(
            "Interval task '%s' starting (interval=%.1f s).",
            name,
            interval_seconds,
        )
        while True:
            try:
                coroutine = coroutine_factory()
                await coroutine
            except asyncio.CancelledError:
                logger.debug("Interval task '%s' cancelled -- stopping loop.", name)
                break
            except Exception as error:
                logger.error(
                    "Interval task '%s' raised an error: %s",
                    name,
                    error,
                    exc_info=True,
                )

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                logger.debug(
                    "Interval task '%s' cancelled during sleep -- stopping loop.",
                    name,
                )
                break

        logger.debug("Interval task '%s' has exited.", name)

    async def _run_once(
        self,
        coroutine_factory: CoroutineFactory,
        delay_seconds: float,
        name: str,
    ) -> None:
        """
        Coroutine body for :meth:`schedule_once`.

        Waits for *delay_seconds*, then calls the factory and awaits the
        returned coroutine.  If the task is cancelled during the delay the
        coroutine is never executed.
        """
        logger.debug(
            "Scheduled task '%s' waiting %.1f s before execution.",
            name,
            delay_seconds,
        )
        try:
            await asyncio.sleep(delay_seconds)
            coroutine = coroutine_factory()
            await coroutine
        except asyncio.CancelledError:
            logger.debug("Scheduled task '%s' cancelled.", name)
        except Exception as error:
            logger.error(
                "Scheduled task '%s' raised an error: %s",
                name,
                error,
                exc_info=True,
            )

        logger.debug("Scheduled task '%s' finished.", name)

    def schedule_interval(
        self,
        coroutine_factory: CoroutineFactory,
        interval_seconds: float,
        name: str,
    ) -> Optional[asyncio.Task[Any]]:
        """
        Create a recurring task that runs *coroutine_factory* every
        *interval_seconds*.

        The factory is a zero-argument callable that returns a coroutine.
        After each invocation the manager sleeps for *interval_seconds*, so
        the effective period is ``execution_time + interval_seconds``.

        If the coroutine (or the factory) raises, the error is logged and the
        loop continues.  Cancelling the task stops the loop.

        Args:
            coroutine_factory: A callable that returns a coroutine to await.
            interval_seconds: Sleep duration between iterations, in seconds.
            name: A unique name for the recurring task.

        Returns:
            The :class:`asyncio.Task` instance, or ``None`` if no event loop
            is running.
        """
        # Check for a running loop *before* creating the _run_interval
        # coroutine object so we never leave an orphan unawaited coroutine
        # when no loop is available.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No running event loop -- cannot schedule interval task '%s'.",
                name,
            )
            return None

        coroutine = self._run_interval(coroutine_factory, interval_seconds, name)
        return self.create_task(coroutine, name=name)

    def schedule_once(
        self,
        coroutine_factory: CoroutineFactory,
        delay_seconds: float,
        name: str,
    ) -> Optional[asyncio.Task[Any]]:
        """
        Schedule a one-shot task that runs *coroutine_factory* after
        *delay_seconds*.

        The factory is a zero-argument callable that returns a coroutine.
        The manager waits for the delay, then calls the factory and awaits the
        coroutine.  If the task is cancelled during the delay the coroutine is
        not executed.

        Args:
            coroutine_factory: A callable that returns a coroutine to await.
            delay_seconds: Number of seconds to wait before execution.
            name: A unique name for the scheduled task.

        Returns:
            The :class:`asyncio.Task` instance, or ``None`` if no event loop
            is running.
        """
        # Check for a running loop *before* creating the _run_once coroutine
        # object so we never leave an orphan unawaited coroutine when no
        # loop is available.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No running event loop -- cannot schedule task '%s'.",
                name,
            )
            return None

        coroutine = self._run_once(coroutine_factory, delay_seconds, name)
        return self.create_task(coroutine, name=name)

    # ------------------------------------------------------------------
    # Bulk stop
    # ------------------------------------------------------------------

    def stop_all(self) -> Optional[asyncio.Task[None]]:
        """
        Cancel all tracked tasks and wait briefly for cancellation.

        This method:
        1. Cancels every tracked task via :meth:`cancel_all`.
        2. Creates a short-lived task that awaits the cancelled tasks (up to
           :data:`DEFAULT_CANCEL_TIMEOUT` seconds each).
        3. Returns that cleanup task for optional awaiting by the caller.

        The returned :class:`asyncio.Task` can be safely ignored if you do
        not need to wait for cleanup (e.g. during application shutdown).
        If no tasks need waiting or no event loop is running, ``None`` is
        returned.

        Returns:
            An :class:`asyncio.Task` that waits for all cancellations, or
            ``None`` if there is nothing to wait for or no loop is running.
        """
        self.cancel_all()

        # Snapshot tasks that are still pending after cancel_all().
        pending = [task for task in list(self._tasks.values()) if not task.done()]
        if not pending:
            logger.debug("stop_all: no pending tasks to wait for.")
            return None

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No running event loop during stop_all -- "
                "cancellation requests issued but cannot await completion."
            )
            return None

        async def _await_pending() -> None:
            """Wait for all pending tasks to finish after cancellation."""
            for index, task in enumerate(pending):
                try:
                    await asyncio.wait_for(task, timeout=DEFAULT_CANCEL_TIMEOUT)
                except asyncio.CancelledError, asyncio.TimeoutError:
                    logger.debug(
                        "stop_all: task %d/%d finished after cancellation "
                        "(CancelledError/TimeoutError).",
                        index + 1,
                        len(pending),
                    )
                except Exception as error:
                    logger.error(
                        "stop_all: task %d/%d raised during cancellation wait: %s",
                        index + 1,
                        len(pending),
                        error,
                        exc_info=True,
                    )

        cleanup_task: asyncio.Task[None] = loop.create_task(
            _await_pending(), name="async_task_manager_stop_all_cleanup"
        )
        logger.info(
            "stop_all: created cleanup task to await %d pending cancellation(s).",
            len(pending),
        )
        return cleanup_task
