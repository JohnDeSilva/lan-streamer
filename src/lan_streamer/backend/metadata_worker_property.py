import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Set
from PySide6.QtCore import Signal, QThread

from lan_streamer import db
from lan_streamer.scanner.file_property_scanner import get_detailed_file_info

logger = logging.getLogger("lan_streamer.backend")


def _produce_item_update(
    item: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Probe a single item and return its update dict, or ``None`` if no
    new data was extracted."""
    file_path = item["path"]
    info = get_detailed_file_info(file_path)
    extracted_runtime = info.get("runtime")
    runtime_val = extracted_runtime if extracted_runtime is not None else 0

    has_tech_info = (
        (info.get("video_codec") and info.get("video_codec") != "Unknown")
        or (info.get("resolution") and info.get("resolution") != "Unknown")
        or ((info.get("bit_rate") or 0) > 0)
    )

    if not (runtime_val > 0 or has_tech_info):
        return None

    return {
        "item_identifier": item["id"],
        "item_type": item["type"],
        "runtime_minutes": extracted_runtime,
        "video_codec": info.get("video_codec"),
        "resolution": info.get("resolution"),
        "audio_tracks": info.get("audio_tracks"),
        "subtitle_tracks": info.get("subtitle_tracks"),
        "bit_rate": info.get("bit_rate"),
        "size_bytes": info.get("size_bytes"),
    }


class FilePropertyExtractionWorker(QThread):
    """Processes videos in parallel (by library) to extract missing runtimes
    and technical metadata.

    Libraries are processed concurrently with a ``ThreadPoolExecutor``.
    Within each library, items are processed sequentially (season-by-season
    for episodes, one-by-one for movies).
    """

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
        self._lock: threading.Lock = threading.Lock()
        self._total_count: int = 0
        self._completed_count: int = 0

    def run(self) -> None:
        try:
            logger.info("FilePropertyExtractionWorker starting run")
            logger.info(
                "Starting Pass 3 (Technical Metadata Extraction) for candidates..."
            )

            items_list: List[Dict[str, Any]] = db.get_items_missing_runtime()

            # Filter out items that already have complete metadata
            candidates: List[Dict[str, Any]] = []
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

                candidates.append(item)

            self._total_count = len(candidates)
            logger.info(
                f"Found {self._total_count} candidates "
                "for background technical extraction"
            )
            self._completed_count = 0
            updated_count: int = 0

            # Group candidates by library so each library is processed in its
            # own thread.
            items_by_library: Dict[str, List[Dict[str, Any]]] = {}
            for item in candidates:
                library = item.get("library_name") or "_unknown"
                items_by_library.setdefault(library, []).append(item)

            max_workers: int = max(
                1,
                min(
                    len(items_by_library),
                    (os.cpu_count() or 4) * 2,
                ),
            )

            def _process_library(
                library_items: List[Dict[str, Any]],
            ) -> int:
                """Process one library's items. Returns count of updates."""
                local_updated: int = 0

                # Group episodes by season within this library.
                episodes_by_season: Dict[Optional[str], List[Dict[str, Any]]] = {}
                movies: List[Dict[str, Any]] = []
                for item in library_items:
                    if item["type"] == "episode":
                        season_id = item.get("season_id")
                        episodes_by_season.setdefault(season_id, []).append(item)
                    else:
                        movies.append(item)

                # Process episodes by season (sequential within library).
                for season_id, season_episodes in episodes_by_season.items():
                    season_updates: List[Dict[str, Any]] = []
                    for ep in season_episodes:
                        update = _produce_item_update(ep)
                        if update:
                            season_updates.append(update)
                            local_updated += 1

                        with self._lock:
                            self._completed_count += 1
                            self.progress_updated.emit(
                                self._completed_count, self._total_count
                            )

                    if season_updates:
                        logger.info(
                            f"Committing batch write for season "
                            f"{season_id} ({len(season_updates)} episodes)"
                        )
                        with self._lock:
                            db.update_items_runtime_batch(season_updates)

                # Process movies individually.
                for movie in movies:
                    update = _produce_item_update(movie)
                    if update:
                        logger.info(f"Committing write for movie {movie['path']}")
                        with self._lock:
                            db.update_items_runtime_batch([update])
                        local_updated += 1

                    with self._lock:
                        self._completed_count += 1
                        self.progress_updated.emit(
                            self._completed_count, self._total_count
                        )

                return local_updated

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_library: Dict[Any, str] = {}
                for library_name, items in items_by_library.items():
                    future = executor.submit(_process_library, items)
                    future_to_library[future] = library_name

                for future in as_completed(future_to_library):
                    library_name = future_to_library[future]
                    try:
                        updated_count += future.result()
                    except Exception:
                        logger.exception(
                            f"FilePropertyExtractionWorker library "
                            f"'{library_name}' failed"
                        )

            logger.info(
                f"FilePropertyExtractionWorker finished, updated "
                f"{updated_count} of {self._total_count} items"
            )
            logger.info("Finished Pass 3 (Technical Metadata Extraction)")
            self.finished.emit(updated_count)
        except Exception as exception_instance:
            logger.exception("FilePropertyExtractionWorker failed")
            self.error.emit(str(exception_instance))
