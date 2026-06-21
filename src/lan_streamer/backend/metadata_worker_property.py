import logging
from typing import List, Dict, Any, Optional, Set
from PySide6.QtCore import Signal, QThread

from lan_streamer import db
from lan_streamer.scanner.file_property_scanner import get_detailed_file_info

logger = logging.getLogger("lan_streamer.backend")


class FilePropertyExtractionWorker(QThread):
    """Processes videos sequentially in the background to extract missing runtimes and technical metadata."""

    progress_updated = Signal(int, int)
    finished = Signal(int)
    error = Signal(str)

    def __init__(
        self,
        changed_season_ids: Optional[Set[str]] = None,
        changed_movie_ids: Optional[Set[str]] = None,
        parent: Optional[QThread] = None,
    ) -> None:
        super().__init__(parent)
        self.changed_season_ids = changed_season_ids
        self.changed_movie_ids = changed_movie_ids

    def run(self) -> None:
        try:
            logger.info("FilePropertyExtractionWorker starting run")
            logger.info(
                "Starting Pass 3 (Technical Metadata Extraction) for candidates..."
            )

            items_list: List[Dict[str, Any]] = db.get_items_missing_runtime()

            # Filter out any files that already have both complete technical and creative metadata
            candidates = []
            for item in items_list:
                if item["type"] == "episode":
                    if (
                        self.changed_season_ids is not None
                        and item.get("season_id") not in self.changed_season_ids
                    ):
                        continue
                else:
                    if (
                        self.changed_movie_ids is not None
                        and item.get("id") not in self.changed_movie_ids
                    ):
                        continue

                if db.has_tech_and_metadata(item["id"], item["type"]):
                    logger.info(
                        f"Skipping {item['path']} as it already has technical and creative metadata"
                    )
                else:
                    candidates.append(item)

            total_count: int = len(candidates)
            logger.info(
                f"Found {total_count} candidates for background technical extraction"
            )
            completed_count: int = 0
            updated_count: int = 0

            # Group candidates by season_id for episodes. Movies are processed as single items.
            episodes_by_season: Dict[Optional[str], List[Dict[str, Any]]] = {}
            movies: List[Dict[str, Any]] = []

            for item in candidates:
                if item["type"] == "episode":
                    season_id = item.get("season_id")
                    if season_id not in episodes_by_season:
                        episodes_by_season[season_id] = []
                    episodes_by_season[season_id].append(item)
                else:
                    movies.append(item)

            # Process episodes by season
            for season_id, season_episodes in episodes_by_season.items():
                season_updates = []
                for ep in season_episodes:
                    file_path = ep["path"]
                    logger.info(
                        f"Probing episode [{completed_count + 1}/{total_count}]: {file_path}"
                    )
                    info = get_detailed_file_info(file_path)
                    extracted_runtime = info.get("runtime")
                    runtime_val = (
                        extracted_runtime if extracted_runtime is not None else 0
                    )

                    has_tech_info = (
                        (
                            info.get("video_codec")
                            and info.get("video_codec") != "Unknown"
                        )
                        or (
                            info.get("resolution")
                            and info.get("resolution") != "Unknown"
                        )
                        or ((info.get("bit_rate") or 0) > 0)
                    )

                    if runtime_val > 0 or has_tech_info:
                        season_updates.append(
                            {
                                "item_identifier": ep["id"],
                                "item_type": "episode",
                                "runtime_minutes": extracted_runtime,
                                "video_codec": info.get("video_codec"),
                                "resolution": info.get("resolution"),
                                "audio_tracks": info.get("audio_tracks"),
                                "subtitle_tracks": info.get("subtitle_tracks"),
                                "bit_rate": info.get("bit_rate"),
                                "size_bytes": info.get("size_bytes"),
                            }
                        )
                        updated_count += 1
                    completed_count += 1
                    self.progress_updated.emit(completed_count, total_count)

                if season_updates:
                    logger.info(
                        f"Committing batch write for season {season_id} ({len(season_updates)} episodes)"
                    )
                    db.update_items_runtime_batch(season_updates)

            # Process movies individually
            for movie in movies:
                file_path = movie["path"]
                logger.info(
                    f"Probing movie [{completed_count + 1}/{total_count}]: {file_path}"
                )
                info = get_detailed_file_info(file_path)
                extracted_runtime = info.get("runtime")
                runtime_val = extracted_runtime if extracted_runtime is not None else 0

                has_tech_info = (
                    (info.get("video_codec") and info.get("video_codec") != "Unknown")
                    or (info.get("resolution") and info.get("resolution") != "Unknown")
                    or ((info.get("bit_rate") or 0) > 0)
                )

                if runtime_val > 0 or has_tech_info:
                    logger.info(f"Committing write for movie {file_path}")
                    db.update_items_runtime_batch(
                        [
                            {
                                "item_identifier": movie["id"],
                                "item_type": "movie",
                                "runtime_minutes": extracted_runtime,
                                "video_codec": info.get("video_codec"),
                                "resolution": info.get("resolution"),
                                "audio_tracks": info.get("audio_tracks"),
                                "subtitle_tracks": info.get("subtitle_tracks"),
                                "bit_rate": info.get("bit_rate"),
                                "size_bytes": info.get("size_bytes"),
                            }
                        ]
                    )
                    updated_count += 1
                completed_count += 1
                self.progress_updated.emit(completed_count, total_count)

            logger.info(
                f"FilePropertyExtractionWorker finished, updated {updated_count} of {total_count} items"
            )
            logger.info("Finished Pass 3 (Technical Metadata Extraction)")
            self.finished.emit(updated_count)
        except Exception as exception_instance:
            logger.exception("FilePropertyExtractionWorker failed")
            self.error.emit(str(exception_instance))
