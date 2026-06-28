import asyncio
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_task_manager import AsyncTaskManager
from lan_streamer.system.async_utils import async_run_subprocess

logger = logging.getLogger("lan_streamer.backend")


class MetadataEmbedWorker(AsyncWorkerBase):
    """
    Background worker that uses ffmpeg to embed metadata into a video container.
    Strictly typesafe with zero abbreviations.
    """

    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        video_path: str,
        metadata: Dict[str, str],
        async_task_manager: Optional[AsyncTaskManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.video_path: str = video_path
        self.metadata: Dict[str, str] = metadata

    async def run_async(self) -> str:
        logger.info(f"Starting metadata embedding for {self.video_path}")
        video_path_obj = Path(self.video_path)
        tmp_suffix = f".meta_tmp{video_path_obj.suffix}"
        output_path = str(video_path_obj.with_suffix(tmp_suffix))

        command = ["ffmpeg", "-y", "-i", self.video_path, "-c", "copy", "-map", "0"]
        for key, value in self.metadata.items():
            if value:
                command.extend(["-metadata", f"{key}={value}"])
        command.append(output_path)

        logger.debug(f"Running ffmpeg command: {' '.join(command)}")
        result = await async_run_subprocess(command)
        stdout_str = result.stdout.strip()
        stderr_str = result.stderr.strip()

        logger.debug(f"ffmpeg stdout: {stdout_str}")
        logger.debug(f"ffmpeg stderr: {stderr_str}")

        if result.returncode != 0:
            error_message = stderr_str or "Unknown ffmpeg error"
            raise Exception(f"ffmpeg execution failed: {error_message}")

        # Atomically replace
        await asyncio.to_thread(os.replace, output_path, self.video_path)

        logger.info(f"MetadataEmbedWorker finished successfully for {self.video_path}")
        return self.video_path


class SeriesMetadataEmbedWorker(AsyncWorkerBase):
    """
    Background worker that embeds metadata for all episodes in a series.
    Strictly typesafe with zero abbreviations.
    """

    progress_updated = Signal(str, int, int)
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        series_name: str,
        episodes: List[Dict[str, Any]],
        async_task_manager: Optional[AsyncTaskManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.series_name: str = series_name
        self.episodes: List[Dict[str, Any]] = episodes

    async def run_async(self) -> None:
        total_episodes = len(self.episodes)
        logger.info(
            f"SeriesMetadataEmbedWorker starting for series '{self.series_name}', processing {total_episodes} episodes"
        )
        for index, episode_record in enumerate(self.episodes):
            if self._cancelled:
                logger.info("SeriesMetadataEmbedWorker cancelled.")
                break

            video_path = episode_record.get("path", "")
            if not video_path:
                logger.debug(f"Skipping episode at index {index}: missing path")
                continue

            self.progress_updated.emit(
                f"Embedding: {Path(video_path).name}", index + 1, total_episodes
            )

            metadata = {
                "title": episode_record.get("tmdb_name")
                or episode_record.get("name", ""),
                "show": self.series_name,
                "episode_id": str(episode_record.get("tmdb_number") or ""),
                "date": episode_record.get("air_date") or "",
            }

            video_path_obj = Path(video_path)
            tmp_suffix = f".meta_tmp{video_path_obj.suffix}"
            output_path = str(video_path_obj.with_suffix(tmp_suffix))

            command = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", "-map", "0"]
            for key, value in metadata.items():
                if value:
                    command.extend(["-metadata", f"{key}={value}"])
            command.append(output_path)

            logger.info(
                f"Embedding metadata for series episode {index + 1}/{total_episodes}: '{video_path}'"
            )
            logger.debug(f"Running ffmpeg command: {' '.join(command)}")
            result = await async_run_subprocess(command)
            stdout_str = result.stdout.strip()
            stderr_str = result.stderr.strip()

            logger.debug(f"ffmpeg stdout: {stdout_str}")
            logger.debug(f"ffmpeg stderr: {stderr_str}")

            if result.returncode == 0:
                await asyncio.to_thread(os.replace, output_path, video_path)
                logger.info(f"Successfully embedded metadata for: '{video_path}'")
            else:
                logger.error(
                    f"Failed to embed metadata for '{video_path}': {stderr_str}"
                )

        logger.info(
            f"SeriesMetadataEmbedWorker finished successfully for series: '{self.series_name}'"
        )

    async def _run_wrapper(self) -> None:
        """Override to emit finished with no arguments."""
        try:
            self.started.emit()
            await self.run_async()
            if not self._cancelled:
                self.finished.emit()
        except asyncio.CancelledError:
            logger.info("%s was cancelled.", self.__class__.__name__)
        except Exception as exception:
            logger.exception("%s failed with error.", self.__class__.__name__)
            if not self._cancelled:
                self.error.emit(str(exception))
