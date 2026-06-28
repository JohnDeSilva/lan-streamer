import asyncio
import logging
from pathlib import Path
from typing import Any, Optional
from PySide6.QtCore import QObject, Signal

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger("lan_streamer.player_widget")


class CacheWorker(AsyncWorkerBase):
    """Worker for copying media files to local cache asynchronously."""

    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        src_path: str,
        dest_path: str,
        async_task_manager: Optional[AsyncTaskManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.src_path: Path = Path(src_path)
        self.dest_path: Path = Path(dest_path)

    async def run_async(self) -> str:
        logger.info(f"Starting cache of {self.src_path} to {self.dest_path}")
        await asyncio.to_thread(
            self.dest_path.parent.mkdir, parents=True, exist_ok=True
        )

        total_size = await asyncio.to_thread(lambda: self.src_path.stat().st_size)
        copied = 0
        chunk_size = 1024 * 1024  # 1MB

        def copy_chunk(fsrc: Any, fdst: Any) -> bytes:
            buf = fsrc.read(chunk_size)
            if buf:
                fdst.write(buf)
            return buf

        with open(self.src_path, "rb") as fsrc:
            with open(self.dest_path, "wb") as fdst:
                while True:
                    if self._cancelled:
                        logger.info("CacheWorker cancelled.")
                        break
                    buf = await asyncio.to_thread(copy_chunk, fsrc, fdst)
                    if not buf:
                        break
                    copied += len(buf)
                    if total_size > 0:
                        self.progress.emit(int((copied / total_size) * 100))

        logger.info(f"Caching finished: {self.dest_path}")
        return str(self.dest_path)

    def run(self) -> None:
        """Synchronous compatibility fallback for tests."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_wrapper())
        finally:
            loop.close()
