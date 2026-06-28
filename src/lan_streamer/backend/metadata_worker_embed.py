import logging
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QThread

logger = logging.getLogger("lan_streamer.backend")


class MetadataEmbedWorker(QThread):
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
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.video_path: str = video_path
        self.metadata: Dict[str, str] = metadata

    def run(self) -> None:
        try:
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
            process_result = subprocess.run(
                command, capture_output=True, text=True, timeout=300
            )
            logger.debug(f"ffmpeg stdout: {process_result.stdout}")
            logger.debug(f"ffmpeg stderr: {process_result.stderr}")

            if process_result.returncode != 0:
                error_message = process_result.stderr or "Unknown ffmpeg error"
                raise Exception(f"ffmpeg execution failed: {error_message}")

            # Atomically replace
            os.replace(output_path, self.video_path)

            logger.info(
                f"MetadataEmbedWorker finished successfully for {self.video_path}"
            )
            self.finished.emit(self.video_path)
        except Exception as exception_instance:
            logger.exception("MetadataEmbedWorker failed")
            self.error.emit(str(exception_instance))


class SeriesMetadataEmbedWorker(QThread):
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
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.episodes: List[Dict[str, Any]] = episodes

    def run(self) -> None:
        try:
            total_episodes = len(self.episodes)
            logger.info(
                f"SeriesMetadataEmbedWorker starting for series '{self.series_name}', processing {total_episodes} episodes"
            )
            for index, episode_record in enumerate(self.episodes):
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
                process_result = subprocess.run(
                    command, capture_output=True, text=True, timeout=300
                )
                logger.debug(f"ffmpeg stdout: {process_result.stdout}")
                logger.debug(f"ffmpeg stderr: {process_result.stderr}")

                if process_result.returncode == 0:
                    os.replace(output_path, video_path)
                    logger.info(f"Successfully embedded metadata for: '{video_path}'")
                else:
                    logger.error(
                        f"Failed to embed metadata for '{video_path}': {process_result.stderr}"
                    )

            logger.info(
                f"SeriesMetadataEmbedWorker finished successfully for series: '{self.series_name}'"
            )
            self.finished.emit()
        except Exception as exception_instance:
            logger.exception("SeriesMetadataEmbedWorker failed")
            self.error.emit(str(exception_instance))
