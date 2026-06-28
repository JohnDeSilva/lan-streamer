import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer import db
from lan_streamer.system.config import config
from lan_streamer.providers.jellyfin import jellyfin_client
from lan_streamer.scanner import scan_movie, scan_series
from lan_streamer.services.metadata_updates import clean_series_data

logger = logging.getLogger("lan_streamer.backend")


class ScanSingleSeriesWorker(QThread):
    """
    Background worker that scans all directories corresponding to a specific series
    or movie in the library, bypassing mtime caching to re-scan files.
    """

    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        library_name: str,
        series_name: str,
        library_type: str,
        root_directories: List[str],
        existing_library: Dict[str, Any],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.library_name: str = library_name
        self.series_name: str = series_name
        self.library_type: str = library_type
        self.root_directories: List[str] = root_directories
        self.existing_library: Dict[str, Any] = existing_library

    def run(self) -> None:
        try:
            logger.info(
                f"ScanSingleSeriesWorker starting for item: '{self.series_name}' in library '{self.library_name}'"
            )

            # Find all matching series directories in all root directories
            target_directories: List[Path] = []
            for root_directory in self.root_directories:
                potential_directory = Path(root_directory) / self.series_name
                if potential_directory.exists() and potential_directory.is_dir():
                    target_directories.append(potential_directory)

            if not target_directories:
                raise ValueError(
                    f"Could not find any directory for '{self.series_name}' across root directories."
                )

            # Fetch Jellyfin correlation data if configured
            jellyfin_data: Optional[Dict[str, Any]] = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            existing_item = self.existing_library.get(self.series_name)

            item_data: Optional[Dict[str, Any]] = existing_item

            for target_directory in target_directories:
                if self.library_type == "movie":
                    item_data = scan_movie(
                        target_directory,
                        tmdb_movie=None,
                        jellyfin_data=jellyfin_data,
                        manual_jellyfin_id=None,
                        existing_movie_data=item_data,
                        force_refresh=False,
                        cleanup=False,
                        single_item_refresh=True,
                        disregard_mtimes=True,
                    )
                else:
                    show_future_episodes = config.libraries.get(
                        self.library_name, {}
                    ).get("show_future_episodes", True)
                    item_data = scan_series(
                        target_directory,
                        tmdb_series=None,
                        jellyfin_data=jellyfin_data,
                        manual_jellyfin_id=None,
                        existing_series_data=item_data,
                        force_refresh=False,
                        cleanup=False,
                        single_item_refresh=True,
                        show_future_episodes=show_future_episodes,
                        disregard_mtimes=True,
                    )

            if not item_data:
                raise ValueError(f"Scan failed for '{self.series_name}'")

            # Update the existing library dictionary with the new item data
            updated_library = self.existing_library.copy()
            if self.library_type != "movie":
                item_data = clean_series_data(item_data)
            updated_library[self.series_name] = item_data

            # Persist back to database
            db.save_library(self.library_name, updated_library)

            logger.info("ScanSingleSeriesWorker finished successfully")
            self.finished.emit(updated_library)
        except Exception as exception:
            logger.exception("ScanSingleSeriesWorker failed")
            self.error.emit(str(exception))
