import logging
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QThread

from . import db
from .config import config
from .jellyfin import jellyfin_client
from .scanner import scan_directories

logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    """Scans a single library directory using TMDB for metadata."""

    finished = Signal(dict)
    partial_result = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        root_directories: List[str],
        library_type: str,
        existing_library: Dict[str, Any],
        force_refresh: bool = False,
        cleanup: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.root_directories: List[str] = root_directories
        self.library_type: str = library_type
        self.existing_library: Dict[str, Any] = existing_library
        self.force_refresh: bool = force_refresh
        self.cleanup: bool = cleanup

    def run(self) -> None:
        try:
            logger.info(
                f"ScanWorker starting run for directories: {self.root_directories}"
            )
            # Fetch Jellyfin correlation data if configured
            jellyfin_data: Optional[Dict[str, Any]] = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            library: Dict[str, Any] = scan_directories(
                self.root_directories,
                library_type=self.library_type,
                existing_library=self.existing_library,
                jellyfin_data=jellyfin_data,
                callback=self.partial_result.emit,
                force_refresh=self.force_refresh,
                cleanup=self.cleanup,
            )
            logger.info("ScanWorker finished successfully")
            self.finished.emit(library)
        except Exception as exc:
            logger.exception("ScanWorker failed")
            self.error.emit(str(exc))


class CleanupWorker(QThread):
    """Removes missing series/seasons/episodes from the database."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        library_name: str,
        root_directories: List[str],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.library_name: str = library_name
        self.root_directories: List[str] = root_directories

    def run(self) -> None:
        try:
            logger.info(f"CleanupWorker starting for library {self.library_name}")
            results: Dict[str, Any] = db.cleanup_library(
                self.library_name, self.root_directories
            )
            logger.info(f"CleanupWorker finished with results: {results}")
            self.finished.emit(results)
        except Exception as exc:
            logger.exception("CleanupWorker failed")
            self.error.emit(str(exc))


class JellyfinPullWorker(QThread):
    """Pulls watch history from Jellyfin and syncs it to the local DB."""

    finished = Signal(int)  # number of episodes updated
    error = Signal(str)

    def run(self) -> None:
        try:
            logger.info("JellyfinPullWorker starting run")
            watched_identifiers, watched_paths, watched_names = (
                jellyfin_client.fetch_watched_episodes()
            )
            updated_count: int = db.sync_watched_from_jellyfin_data(
                watched_identifiers, watched_paths, watched_names
            )
            logger.info(
                f"JellyfinPullWorker finished, updated {updated_count} episodes"
            )
            self.finished.emit(updated_count)
        except Exception as exc:
            logger.exception("JellyfinPullWorker failed")
            self.error.emit(str(exc))


class JellyfinPushWorker(QThread):
    """Pushes all local watched state to Jellyfin."""

    finished = Signal(int)  # number of episodes pushed
    error = Signal(str)

    def run(self) -> None:
        try:
            logger.info("JellyfinPushWorker starting run")
            episodes_list: List[Dict[str, Any]] = db.get_all_episodes_with_jellyfin_id()
            pushed_count: int = 0
            for episode_record in episodes_list:
                jellyfin_client.set_watched_status(
                    episode_record["jellyfin_id"], bool(episode_record["watched"])
                )
                pushed_count += 1
            logger.info(f"JellyfinPushWorker finished, pushed {pushed_count} episodes")
            self.finished.emit(pushed_count)
        except Exception as exc:
            logger.exception("JellyfinPushWorker failed")
            self.error.emit(str(exc))


class ScanAllLibrariesWorker(QThread):
    """Scans all configured libraries sequentially using TMDB for metadata."""

    library_progress = Signal(str, int, int)
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        force_refresh: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.force_refresh: bool = force_refresh

    def run(self) -> None:
        try:
            logger.info("ScanAllLibrariesWorker starting global scan run")
            libraries_dictionary = config.libraries
            total_count: int = len(libraries_dictionary)
            completed_count: int = 0

            jellyfin_data: Optional[Dict[str, Any]] = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            for library_name, library_configuration in libraries_dictionary.items():
                logger.info(f"ScanAllLibrariesWorker scanning library: {library_name}")
                root_directories: List[str] = list(
                    library_configuration.get("paths", [])
                )
                library_type: str = library_configuration.get("type", "tv")

                existing_library_data: Dict[str, Any] = {}
                if library_type == "movie":
                    existing_library_data = db.load_movie_library(library_name)
                else:
                    existing_library_data = db.load_library(library_name)

                updated_library_data: Dict[str, Any] = scan_directories(
                    root_directories,
                    library_type=library_type,
                    existing_library=existing_library_data,
                    jellyfin_data=jellyfin_data,
                    callback=None,
                    force_refresh=self.force_refresh,
                    cleanup=False,
                )

                if library_type == "movie":
                    db.save_movie_library(library_name, updated_library_data)
                else:
                    db.save_library(library_name, updated_library_data)

                completed_count += 1
                self.library_progress.emit(library_name, completed_count, total_count)

            logger.info("ScanAllLibrariesWorker finished successfully")
            self.finished.emit()
        except Exception as exception_instance:
            logger.exception("ScanAllLibrariesWorker failed")
            self.error.emit(str(exception_instance))


class CleanupAllLibrariesWorker(QThread):
    """Removes missing items from the database across all configured libraries sequentially."""

    library_progress = Signal(str, int, int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        try:
            logger.info("CleanupAllLibrariesWorker starting global cleanup run")
            libraries_dictionary = config.libraries
            total_count: int = len(libraries_dictionary)
            completed_count: int = 0

            for library_name, library_configuration in libraries_dictionary.items():
                logger.info(
                    f"CleanupAllLibrariesWorker cleaning library: {library_name}"
                )
                root_directories: List[str] = list(
                    library_configuration.get("paths", [])
                )
                db.cleanup_library(library_name, root_directories)

                completed_count += 1
                self.library_progress.emit(library_name, completed_count, total_count)

            logger.info("CleanupAllLibrariesWorker finished successfully")
            self.finished.emit()
        except Exception as exception_instance:
            logger.exception("CleanupAllLibrariesWorker failed")
            self.error.emit(str(exception_instance))


class RuntimeExtractionWorker(QThread):
    """Processes videos sequentially in the background to extract missing runtimes."""

    progress_updated = Signal(int, int)
    finished = Signal(int)
    error = Signal(str)

    def run(self) -> None:
        try:
            logger.info("RuntimeExtractionWorker starting run")
            from .scanner import _extract_video_runtime

            items_list: List[Dict[str, Any]] = db.get_items_missing_runtime()
            total_count: int = len(items_list)
            completed_count: int = 0
            updated_count: int = 0

            for item_dictionary in items_list:
                file_path: str = item_dictionary["path"]
                extracted_runtime: int = _extract_video_runtime(file_path)
                if extracted_runtime > 0:
                    db.update_item_runtime(
                        item_dictionary["id"],
                        item_dictionary["type"],
                        extracted_runtime,
                    )
                    updated_count += 1

                completed_count += 1
                self.progress_updated.emit(completed_count, total_count)

            logger.info(
                f"RuntimeExtractionWorker finished, updated {updated_count} items"
            )
            self.finished.emit(updated_count)
        except Exception as exception_instance:
            logger.exception("RuntimeExtractionWorker failed")
            self.error.emit(str(exception_instance))


class SubtitleMergeWorker(QThread):
    """Merges external subtitle files into a video container using ffmpeg."""

    finished = Signal(str)  # resulting file path
    error = Signal(str)

    def __init__(
        self,
        video_path: str,
        subtitle_paths: List[str],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.video_path: str = video_path
        self.subtitle_paths: List[str] = subtitle_paths

    def run(self) -> None:
        try:
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
            process_result = subprocess.run(
                command, capture_output=True, text=True, timeout=300
            )
            logger.debug(f"ffmpeg stdout: {process_result.stdout}")
            logger.debug(f"ffmpeg stderr: {process_result.stderr}")

            if process_result.returncode != 0:
                error_message = process_result.stderr or "Unknown ffmpeg error"
                raise Exception(f"ffmpeg execution failed: {error_message}")

            # Atomically replace the original file with the merged Matroska container
            os.replace(output_path, self.video_path)

            # Cleanup external subtitle files after successful merge
            for subtitle_file_path in self.subtitle_paths:
                try:
                    os.remove(subtitle_file_path)
                except OSError as error_instance:
                    logger.warning(
                        f"Could not remove merged subtitle file {subtitle_file_path}: {error_instance}"
                    )

            logger.info(
                f"SubtitleMergeWorker finished successfully for {self.video_path}"
            )
            self.finished.emit(self.video_path)
        except Exception as exception_instance:
            logger.exception("SubtitleMergeWorker failed")
            self.error.emit(str(exception_instance))


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
            for index, ep_record in enumerate(self.episodes):
                video_path = ep_record.get("path", "")
                if not video_path:
                    continue

                self.progress_updated.emit(
                    f"Embedding: {Path(video_path).name}", index + 1, total_episodes
                )

                metadata = {
                    "title": ep_record.get("tmdb_name") or ep_record.get("name", ""),
                    "show": self.series_name,
                    "episode_id": str(ep_record.get("tmdb_number") or ""),
                    "date": ep_record.get("air_date") or "",
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
                    f"Embedding metadata for series episode {index + 1}/{total_episodes}: {video_path}"
                )
                logger.debug(f"Running ffmpeg command: {' '.join(command)}")
                process_result = subprocess.run(
                    command, capture_output=True, text=True, timeout=300
                )
                logger.debug(f"ffmpeg stdout: {process_result.stdout}")
                logger.debug(f"ffmpeg stderr: {process_result.stderr}")

                if process_result.returncode == 0:
                    os.replace(output_path, video_path)
                    logger.info(f"Successfully embedded metadata for {video_path}")
                else:
                    logger.error(
                        f"Failed to embed metadata for {video_path}: {process_result.stderr}"
                    )

            logger.info(
                f"SeriesMetadataEmbedWorker finished successfully for series: {self.series_name}"
            )
            self.finished.emit()
        except Exception as exception_instance:
            logger.exception("SeriesMetadataEmbedWorker failed")
            self.error.emit(str(exception_instance))
