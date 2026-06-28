"""Async worker base class for migrating QThread workers to async patterns.

Provides a QObject-based worker with async lifecycle, compatible with
:class:`~lan_streamer.system.threading_manager.WorkerSlot`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger(__name__)


class AsyncWorkerBase(QObject):
    """Base class for async workers managed by :class:`WorkerSlot`.

    Subclasses must implement :meth:`run_async` — a coroutine that performs
    the background work.

    Signals
    -------
    started : Signal()
        Emitted when the background coroutine begins.
    finished : Signal(object)
        Emitted when the background coroutine completes (payload depends on
        the subclass).
    error : Signal(str)
        Emitted when an unhandled exception occurs in ``run_async``.
    """

    started = Signal()
    finished = Signal(object)
    error = Signal(str)

    # Marker for WorkerSlot to detect async workers.
    _is_async_worker: bool = True

    def __init__(
        self,
        async_task_manager: Optional[AsyncTaskManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._async_task_manager: Optional[AsyncTaskManager] = async_task_manager
        self._task_name: str = f"{self.__class__.__name__}_{id(self)}"
        self._cancelled: bool = False

    async def run_async(self) -> Any:
        """Coroutine that performs the background work.

        Subclasses MUST override this method.
        """
        raise NotImplementedError

    def start(self) -> None:
        """Schedule ``run_async`` via the async task manager.

        This is the entry point called by :class:`WorkerSlot`.
        """
        if self._async_task_manager is None:
            raise RuntimeError(
                f"Cannot start {self.__class__.__name__} without an AsyncTaskManager"
            )
        self._cancelled = False
        self._async_task_manager.create_task(
            coroutine=self._run_wrapper(),
            name=self._task_name,
            on_done_callback=self._on_task_done,
        )

    def stop(self) -> None:
        """Request cooperative cancellation of the background coroutine."""
        self._cancelled = True
        if self._async_task_manager is not None:
            self._async_task_manager.cancel_task(self._task_name)

    def isInterruptionRequested(self) -> bool:
        """Check if cooperative cancellation has been requested."""
        return self._cancelled

    @property
    def is_running(self) -> bool:
        if self._async_task_manager is None:
            return False
        return self._async_task_manager.is_task_running(self._task_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_wrapper(self) -> None:
        """Wrap ``run_async`` with lifecycle signal emission."""
        try:
            self.started.emit()
            result = await self.run_async()
            if not self._cancelled:
                self.finished.emit(result)
        except asyncio.CancelledError:
            logger.info("%s was cancelled.", self.__class__.__name__)
        except Exception as exception:
            logger.exception("%s failed with error.", self.__class__.__name__)
            if not self._cancelled:
                self.error.emit(str(exception))

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        """Called when the asyncio task completes for any reason."""
        # Task completion is already handled by _run_wrapper.
        # This callback exists so AsyncTaskManager cleans up its tracking.
