"""Post-scan worker — persists library data and rebuilds smart row cache.

Runs ``save_library`` / ``save_movie_library`` and smart row cache rebuild
in a background thread so the UI thread is not blocked after a scan completes.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject

from lan_streamer import db
from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.services.smart_row_service import SmartRowService
from lan_streamer.system.async_task_manager import AsyncTaskManager
from lan_streamer.system.async_utils import run_in_executor

logger = logging.getLogger("lan_streamer.backend")


class PostScanWorker(AsyncWorkerBase):
    """Persists scanned library data and rebuilds smart row cache.

    Accepts the library name, updated library data, and library type from the
    completed scan worker. Runs the synchronous DB save and cache rebuild in a
    thread pool to avoid blocking the UI thread.

    Signals
    -------
    finished : signal(object)
        Emitted with ``(library_name, changed_hashes)`` on successful
        completion.
    """

    def __init__(
        self,
        library_name: str,
        library_data: Dict[str, Any],
        library_type: str,
        smart_row_service: Optional[SmartRowService] = None,
        async_task_manager: Optional[AsyncTaskManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.library_name: str = library_name
        self.library_data: Dict[str, Any] = library_data
        self.library_type: str = library_type
        self.smart_row_service: Optional[SmartRowService] = smart_row_service

    def start(self) -> None:
        """Start the worker, falling back to synchronous execution if no event loop is running."""
        try:
            asyncio.get_running_loop()
            super().start()
        except RuntimeError:
            logger.info("PostScanWorker: no running event loop, running synchronously")
            result = self._run_sync()
            self.finished.emit(result)

    def _run_sync(self) -> Dict[str, Any]:
        """Execute post-scan operations synchronously."""
        if self.library_type == "movie":
            db.save_movie_library(self.library_name, self.library_data)
        else:
            db.save_library(self.library_name, self.library_data)
        logger.info(
            "PostScanWorker: saved library '%s' (%s) to database",
            self.library_name,
            self.library_type,
        )
        changed_hashes: List[str] = []
        if self.smart_row_service is not None:
            changed_hashes = self.smart_row_service.rebuild_for_libraries(
                [self.library_name]
            )
            if changed_hashes:
                logger.info(
                    "PostScanWorker: rebuilt smart row cache for library "
                    "'%s' (%d config hashes changed)",
                    self.library_name,
                    len(changed_hashes),
                )
        return {
            "library_name": self.library_name,
            "changed_hashes": changed_hashes,
        }

    async def run_async(self) -> Dict[str, Any]:
        """Persist library data and rebuild smart row cache."""
        if self.library_type == "movie":
            await run_in_executor(
                db.save_movie_library, self.library_name, self.library_data
            )
        else:
            await run_in_executor(db.save_library, self.library_name, self.library_data)
        logger.info(
            "PostScanWorker: saved library '%s' (%s) to database",
            self.library_name,
            self.library_type,
        )

        changed_hashes: List[str] = []
        if self.smart_row_service is not None:
            changed_hashes = await run_in_executor(
                self.smart_row_service.rebuild_for_libraries,
                [self.library_name],
            )
            if changed_hashes:
                logger.info(
                    "PostScanWorker: rebuilt smart row cache for library "
                    "'%s' (%d config hashes changed)",
                    self.library_name,
                    len(changed_hashes),
                )

        return {
            "library_name": self.library_name,
            "changed_hashes": changed_hashes,
        }
