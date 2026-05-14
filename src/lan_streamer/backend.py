import logging
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QThread

from . import db
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
