import asyncio
import logging
from typing import Any, Callable, Dict, Optional
from PySide6.QtCore import QObject, Signal

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger("lan_streamer.backend")


class GenericSearchWorker(AsyncWorkerBase):
    """Runs an arbitrary callable in a background thread and emits its result.

    Signals:
        search_finished: Emitted with the callable's return value on success.
        error: Emitted with an error message string on failure.
    """

    search_finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        target: Callable[..., Any],
        async_task_manager: Optional[AsyncTaskManager] = None,
        args: Optional[tuple] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        description: str = "search",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self._target: Callable[..., Any] = target
        self._args: tuple = args or ()
        self._kwargs: Dict[str, Any] = kwargs or {}
        self._description: str = description

    async def run_async(self) -> Any:
        logger.info(f"GenericSearchWorker running {self._description} in background...")
        result = await asyncio.to_thread(self._target, *self._args, **self._kwargs)
        logger.info(f"GenericSearchWorker {self._description} completed successfully")
        self.search_finished.emit(result)
        return result
