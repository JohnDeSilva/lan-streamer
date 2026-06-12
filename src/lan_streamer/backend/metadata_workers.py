import logging
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer.backend.proxy import (
    db,
    config,
    jellyfin_client,
    get_detailed_file_info,
    scan_series,
    scan_movie,
    clean_series_data,
)

logger = logging.getLogger("lan_streamer.backend")


class RuntimeExtractionWorker(QThread):
    """Processes videos sequentially in the background to extract missing runtimes and technical metadata."""

    progress_updated = Signal(int, int)
    finished = Signal(int)
    error = Signal(str)

    def run(self) -> None:
        try:
            logger.info("RuntimeExtractionWorker starting run")

            items_list: List[Dict[str, Any]] = db.get_items_missing_runtime()
            total_count: int = len(items_list)
            logger.info(
                f"Found {total_count} items missing runtime metadata in database"
            )
            completed_count: int = 0
            updated_count: int = 0

            for item_dictionary in items_list:
                file_path: str = item_dictionary["path"]
                logger.info(
                    f"Looking at file [{completed_count + 1}/{total_count}]: {file_path} (Type: {item_dictionary['type']})"
                )

                info = get_detailed_file_info(file_path)
                extracted_runtime = info.get("runtime")
                runtime_val = extracted_runtime if extracted_runtime is not None else 0

                logger.info(
                    f"Extraction results for {file_path}: runtime={extracted_runtime} mins, "
                    f"codec={info.get('video_codec')}, resolution={info.get('resolution')}, "
                    f"bit_rate={info.get('bit_rate')}"
                )

                has_tech_info = (
                    (info.get("video_codec") and info.get("video_codec") != "Unknown")
                    or (info.get("resolution") and info.get("resolution") != "Unknown")
                    or ((info.get("bit_rate") or 0) > 0)
                )

                if runtime_val > 0 or has_tech_info:
                    logger.info(
                        f"Updating database for {file_path} with extracted runtime and technical info"
                    )
                    db.update_item_runtime(
                        item_identifier=item_dictionary["id"],
                        item_type=item_dictionary["type"],
                        runtime_minutes=extracted_runtime,
                        video_codec=info.get("video_codec"),
                        resolution=info.get("resolution"),
                        audio_tracks=info.get("audio_tracks"),
                        subtitle_tracks=info.get("subtitle_tracks"),
                        bit_rate=info.get("bit_rate"),
                        size_bytes=info.get("size_bytes"),
                    )
                    updated_count += 1
                else:
                    logger.warning(
                        f"Bypassing database update for {file_path}: no valid runtime or technical metadata extracted"
                    )

                completed_count += 1
                self.progress_updated.emit(completed_count, total_count)

            logger.info(
                f"RuntimeExtractionWorker finished, updated {updated_count} of {total_count} items"
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


class RefreshSeriesWorker(QThread):
    """Refreshes metadata for a single series or movie by scanning its folder directly."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        library_name: str,
        item_name: str,
        library_type: str,
        root_directories: List[str],
        existing_library: Dict[str, Any],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.library_name: str = library_name
        self.item_name: str = item_name
        self.library_type: str = library_type
        self.root_directories: List[str] = root_directories
        self.existing_library: Dict[str, Any] = existing_library

    def run(self) -> None:
        try:
            logger.info(
                f"RefreshSeriesWorker starting for item: {self.item_name} in library {self.library_name}"
            )
            # Find the path of the specific series/movie directory within the root directories
            target_dir: Optional[Path] = None
            for root_dir in self.root_directories:
                potential_dir = Path(root_dir) / self.item_name
                if potential_dir.exists() and potential_dir.is_dir():
                    target_dir = potential_dir
                    break

            if not target_dir:
                raise ValueError(f"Could not find directory for '{self.item_name}'")

            # Fetch Jellyfin correlation data if configured
            jellyfin_data: Optional[Dict[str, Any]] = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            existing_item = self.existing_library.get(self.item_name)
            # We want to refresh this item from TMDB, bypassing lock.
            # So we pass tmdb_series/tmdb_movie = None, and single_item_refresh = True.
            if self.library_type == "movie":
                item_data = scan_movie(
                    target_dir,
                    tmdb_movie=None,
                    jellyfin_data=jellyfin_data,
                    manual_jellyfin_id=None,
                    existing_movie_data=existing_item,
                    force_refresh=True,
                    cleanup=False,
                    single_item_refresh=True,
                )
            else:
                show_future = config.libraries.get(self.library_name, {}).get(
                    "show_future_episodes", True
                )
                item_data = scan_series(
                    target_dir,
                    tmdb_series=None,
                    jellyfin_data=jellyfin_data,
                    manual_jellyfin_id=None,
                    existing_series_data=existing_item,
                    force_refresh=True,
                    cleanup=False,
                    single_item_refresh=True,
                    show_future_episodes=show_future,
                )

            if not item_data:
                raise ValueError(f"Scan failed for '{self.item_name}'")

            # Update the existing library dictionary with the new item data
            updated_library = self.existing_library.copy()
            if self.library_type != "movie":
                item_data = clean_series_data(item_data)
            updated_library[self.item_name] = item_data

            # Persist back to DB
            db.save_library(self.library_name, updated_library)

            logger.info("RefreshSeriesWorker finished successfully")
            self.finished.emit(updated_library)
        except Exception as exc:
            logger.exception("RefreshSeriesWorker failed")
            self.error.emit(str(exc))
