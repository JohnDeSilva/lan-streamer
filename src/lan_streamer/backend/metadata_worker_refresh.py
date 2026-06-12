import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer.backend.proxy import (
    db,
    config,
    jellyfin_client,
    scan_movie,
    scan_series,
    clean_series_data,
)

logger = logging.getLogger("lan_streamer.backend")


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
