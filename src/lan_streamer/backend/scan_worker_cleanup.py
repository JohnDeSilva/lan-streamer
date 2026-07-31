import asyncio
import logging

from PySide6.QtCore import QObject, Signal

from lan_streamer import db
from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger("lan_streamer.backend")


class CleanupWorker(AsyncWorkerBase):
    """Removes missing series/seasons/episodes from the database."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        library_name: str,
        root_directories: list[str],
        async_task_manager: AsyncTaskManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.library_name: str = library_name
        self.root_directories: list[str] = root_directories

    async def run_async(self) -> dict:
        logger.info(f"CleanupWorker starting for library {self.library_name}")
        results = await asyncio.to_thread(
            db.cleanup_library, self.library_name, self.root_directories
        )
        logger.info(f"CleanupWorker finished with results: {results}")
        return results
