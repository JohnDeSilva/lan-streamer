import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional
from PySide6.QtCore import QObject, Signal

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger("lan_streamer.backend")


class SubtitleMergeWorker(AsyncWorkerBase):
    """Merges external subtitle files into a video container using ffmpeg."""

    finished = Signal(str)  # resulting file path
    error = Signal(str)

    def __init__(
        self,
        video_path: str,
        subtitle_paths: List[str],
        async_task_manager: Optional[AsyncTaskManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.video_path: str = video_path
        self.subtitle_paths: List[str] = subtitle_paths

    async def run_async(self) -> str:
        logger.info(f"SubtitleMergeWorker starting for {self.video_path}")

        video_path_obj = Path(self.video_path)
        output_path = str(video_path_obj.with_suffix(".merged.mkv"))

        # ffmpeg -i video.mp4 -i sub1.srt -i sub2.ass -c copy -map 0 -map 1 -map 2 output.mkv
        command = ["ffmpeg", "-y", "-i", self.video_path]
        for subtitle_file_path in self.subtitle_paths:
            command.extend(["-i", subtitle_file_path])

        command.extend(["-c", "copy", "-map", "0"])
        for index_offset in range(len(self.subtitle_paths)):
            command.extend(["-map", str(index_offset + 1)])

        # Attempt to set subtitle language metadata from filename conventions (e.g., .en.srt)
        for index_offset, subtitle_file_path in enumerate(self.subtitle_paths):
            suffixes_list = Path(subtitle_file_path).suffixes
            if len(suffixes_list) >= 2:
                language_code = suffixes_list[-2].replace(".", "")
                # Basic check for ISO-639 codes (usually 2 or 3 chars)
                if 2 <= len(language_code) <= 3:
                    command.extend(
                        [
                            f"-metadata:s:s:{index_offset}",
                            f"language={language_code}",
                        ]
                    )

        command.append(output_path)

        logger.info(
            f"Starting subtitle merge for {self.video_path} with {len(self.subtitle_paths)} subtitle files"
        )
        logger.debug(f"Running ffmpeg command: {' '.join(command)}")
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
        )
        stdout_str = result.stdout.strip()
        stderr_str = result.stderr.strip()

        logger.debug(f"ffmpeg stdout: {stdout_str}")
        logger.debug(f"ffmpeg stderr: {stderr_str}")

        if result.returncode != 0:
            error_message = stderr_str or "Unknown ffmpeg error"
            raise Exception(f"ffmpeg execution failed: {error_message}")

        # Atomically replace the original file with the merged Matroska container
        await asyncio.to_thread(os.replace, output_path, self.video_path)

        # Cleanup external subtitle files after successful merge
        for subtitle_file_path in self.subtitle_paths:
            try:
                await asyncio.to_thread(os.remove, subtitle_file_path)
            except OSError as error_instance:
                logger.warning(
                    f"Could not remove merged subtitle file {subtitle_file_path}: {error_instance}"
                )

        logger.info(f"SubtitleMergeWorker finished successfully for {self.video_path}")
        return self.video_path

    def run(self) -> None:
        """Synchronous compatibility fallback for tests."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_wrapper())
        finally:
            loop.close()
