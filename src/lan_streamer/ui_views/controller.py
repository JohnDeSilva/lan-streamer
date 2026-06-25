import logging
import re
from pathlib import Path
from typing import (
    List,
    Dict,
    Any,
    Optional,
    Set,
    Protocol,
    TYPE_CHECKING,
)

from PySide6.QtCore import QObject, Signal, QFileSystemWatcher

from lan_streamer.system.config import config as _config_default
from lan_streamer import db as _db_default


if TYPE_CHECKING:
    from lan_streamer.providers.jellyfin import (
        jellyfin_client as _jellyfin_default,
    )
    from lan_streamer.providers.tmdb import tmdb_client as _tmdb_default
    from lan_streamer.backend import (
        ScanWorker,
        CleanupWorker,
        JellyfinPullWorker,
        JellyfinPushWorker,
        ScanAllLibrariesWorker,
        FilePropertyExtractionWorker,
    )
else:
    from lan_streamer.ui_views.proxy import (
        jellyfin_client as _jellyfin_default,
        tmdb_client as _tmdb_default,
        ScanWorker,
        CleanupWorker,
        JellyfinPullWorker,
        JellyfinPushWorker,
        ScanAllLibrariesWorker,
        FilePropertyExtractionWorker,
    )

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Protocols for dependency injection interfaces
# ------------------------------------------------------------------


class JellyfinClientProtocol(Protocol):
    """Interface abstracting methods of JellyfinClient used by Controller."""

    def is_configured(self) -> bool: ...


class TMDBClientProtocol(Protocol):
    """Interface abstracting methods of TMDBClient used by Controller."""

    def download_image(self, poster_path: str, cache_key: str) -> str | None: ...
    def get_episode_group_details(self, group_id: str) -> dict | None: ...
    def get_season_based_episode_group(
        self, tmdb_identifier: str | int
    ) -> dict | None: ...
    def get_episodes(self, tmdb_identifier: str | int, season_num: int) -> list: ...


# Backward-compatible aliases for tests that patch module-level names
jellyfin_client: JellyfinClientProtocol = _jellyfin_default
tmdb_client: TMDBClientProtocol = _tmdb_default


class Controller(QObject):
    """
    Core Application Logic Controller managing native UI synchronization and persistence layer interactions.
    Enforces strict zero-abbreviation variable naming standard.
    """

    library_loaded = Signal()
    series_selected = Signal(str)
    movie_selected = Signal(str)
    status_changed = Signal(str)
    playback_requested = Signal(str)
    metadata_dialog_requested = Signal(str)
    rename_dialog_requested = Signal(str)
    jellyfin_dialog_requested = Signal(str)
    series_details_requested = Signal(str)
    episode_details_requested = Signal(str, str)
    movie_details_requested = Signal(str, str)
    episode_metadata_dialog_requested = Signal(str, str)
    global_progress_updated = Signal(str, int, int)
    detail_progress_updated = Signal(str, dict)
    scan_completed = Signal()

    file_system_watcher: QFileSystemWatcher

    def __init__(
        self,
        parent: Optional[QObject] = None,
        config: Any = None,
        db: Any = None,
        jellyfin_client: Optional[JellyfinClientProtocol] = None,
        tmdb_client: Optional[TMDBClientProtocol] = None,
    ) -> None:
        super().__init__(parent)
        self._config = config if config is not None else _config_default
        self._db = db if db is not None else _db_default
        self._jellyfin_client = (
            jellyfin_client if jellyfin_client is not None else _jellyfin_default
        )
        self._tmdb_client = tmdb_client if tmdb_client is not None else _tmdb_default
        self.current_library_name: str = ""
        self.cached_library_data: Dict[str, Any] = {}
        self.selected_series_name: str = ""
        self.sort_mode: str = self._config.sort_mode
        self.sort_descending: bool = self._config.sort_descending
        self.filter_out_watched: bool = self._config.filter_out_watched
        self.scan_worker_instance: Optional[ScanWorker] = None
        self.cleanup_worker_instance: Optional[CleanupWorker] = None
        self.pull_worker_instance: Optional[JellyfinPullWorker] = None
        self.push_worker_instance: Optional[JellyfinPushWorker] = None
        self.scan_all_worker_instance: Optional[ScanAllLibrariesWorker] = None
        self.file_property_worker_instance: Optional[FilePropertyExtractionWorker] = (
            None
        )
        self.merge_subtitle_worker_instance: Optional[Any] = None
        self.embed_metadata_worker_instance: Optional[Any] = None
        self.is_video_playing: bool = False
        self._running_pass3_after_scan: bool = False
        self._running_cleanup_after_scan: bool = False
        self._doing_scan_and_update: bool = False
        self._cleanup_queue: List[str] = []

        self.file_system_watcher = QFileSystemWatcher(self)

        self.file_system_watcher.directoryChanged.connect(self._on_directory_changed)

    def select_library(self, library_name: str, reset_selection: bool = True) -> None:
        logger.info(f"Controller loading library: {library_name}")
        self._config.load()
        self.current_library_name = library_name
        self.status_changed.emit(f"Loading library: {library_name}...")

        library_config = self._config.libraries.get(library_name, {})

        existing_directories = self.file_system_watcher.directories()
        if existing_directories:
            self.file_system_watcher.removePaths(existing_directories)

        root_directories: List[str] = library_config.get("paths", [])
        for directory_path in root_directories:
            if Path(directory_path).is_dir():
                self.file_system_watcher.addPath(directory_path)

        if library_config.get("type", "tv") == "movie":
            self.cached_library_data = self._db.load_movie_library(library_name)
        else:
            self.cached_library_data = self._db.load_library(library_name)
        self._cache_series_metrics()

        if reset_selection:
            self.selected_series_name = ""

        self.status_changed.emit("Library loaded successfully.")
        self.library_loaded.emit()

    def _on_directory_changed(self, path_string: str) -> None:
        logger.info(
            f"Directory modification detected on '{path_string}'. Automated background scanning disabled."
        )

    def _cache_series_metrics(self) -> None:
        for series_name, series_data in self.cached_library_data.items():
            if "seasons" not in series_data:
                is_watched = bool(series_data.get("watched"))
                series_data["metrics"] = {
                    "total_episodes": 1,
                    "watched_episodes": 1 if is_watched else 0,
                    "max_date_added": series_data.get("date_added") or 0,
                    "max_air_date": str(series_data.get("year") or ""),
                    "last_played_at": series_data.get("last_played_at") or 0,
                }
            else:
                total_episodes: int = 0
                watched_episodes: int = 0
                max_date_added: int = 0
                max_air_date: str = ""
                last_played_at: int = 0

                for season_data in series_data.get("seasons", {}).values():
                    for episode_record in season_data.get("episodes", []):
                        # Only count episodes that have a local file path.
                        # Placeholder/missing episodes (path=None) are stored in the
                        # DB for display purposes but do not contribute to progress.
                        if not episode_record.get("path"):
                            continue
                        total_episodes += 1
                        if episode_record.get("watched"):
                            watched_episodes += 1
                        added_timestamp: int = episode_record.get("date_added") or 0
                        if added_timestamp > max_date_added:
                            max_date_added = added_timestamp
                        air_date_string: str = episode_record.get("air_date") or ""
                        if air_date_string > max_air_date:
                            max_air_date = air_date_string
                        lp: int = episode_record.get("last_played_at") or 0
                        if lp > last_played_at:
                            last_played_at = lp

                series_data["metrics"] = {
                    "total_episodes": total_episodes,
                    "watched_episodes": watched_episodes,
                    "max_date_added": max_date_added,
                    "max_air_date": max_air_date,
                    "last_played_at": last_played_at,
                }

    def select_series(self, series_name: str) -> None:
        if series_name in self.cached_library_data:
            self.selected_series_name = series_name
            self.series_selected.emit(series_name)

    def select_movie(self, movie_name: str) -> None:
        if movie_name in self.cached_library_data:
            self.selected_series_name = movie_name
            self.movie_selected.emit(movie_name)

    def set_sort_mode(self, mode: str) -> None:
        if self.sort_mode != mode:
            logger.info(f"Sort mode changed from '{self.sort_mode}' to '{mode}'")
            self.sort_mode = mode
            self._config.sort_mode = mode
            self._config.save_to_db()
            self.library_loaded.emit()

    def set_sort_descending(self, descending: bool) -> None:
        if self.sort_descending != descending:
            logger.info(
                f"Sort direction changed to {'descending' if descending else 'ascending'}"
            )
            self.sort_descending = descending
            self._config.sort_descending = descending
            self._config.save_to_db()
            self.library_loaded.emit()

    def set_filter_out_watched(self, enabled: bool) -> None:
        if self.filter_out_watched != enabled:
            self.filter_out_watched = enabled
            self._config.filter_out_watched = enabled
            self._config.save_to_db()
            self.library_loaded.emit()

    def mark_episode_watched(self, absolute_path: str, watched: bool) -> None:
        logger.info(
            f"Controller marking episode watched={watched} for path: {absolute_path}"
        )
        self._db.update_episode_watched_status(absolute_path, watched)

        # Update cached state in memory
        for series_data in self.cached_library_data.values():
            if "seasons" not in series_data:
                if series_data.get("path") == absolute_path:
                    series_data["watched"] = watched
                    break
            else:
                for season_data in series_data.get("seasons", {}).values():
                    for episode_record in season_data.get("episodes", []):
                        if episode_record.get("path") == absolute_path:
                            episode_record["watched"] = watched
                            break

        self._cache_series_metrics()

        if not self.is_video_playing:
            self.library_loaded.emit()

    def mark_season_watched(self, series_name: str, season_name: str) -> None:
        logger.info(
            f"Controller marking season watched for series '{series_name}', season '{season_name}'"
        )
        self._db.update_season_watched_status(
            self.current_library_name, series_name, season_name, True
        )

        series_data: Dict[str, Any] = self.cached_library_data.get(series_name, {})
        season_data: Dict[str, Any] = series_data.get("seasons", {}).get(
            season_name, {}
        )
        for episode_record in season_data.get("episodes", []):
            episode_record["watched"] = True

        self._cache_series_metrics()
        if not self.is_video_playing:
            self.library_loaded.emit()

    def mark_series_watched(self, series_name: str) -> None:
        logger.info(f"Controller marking entire series watched: '{series_name}'")
        self._db.update_series_watched_status(
            self.current_library_name, series_name, True
        )

        series_data: Dict[str, Any] = self.cached_library_data.get(series_name, {})
        for season_data in series_data.get("seasons", {}).values():
            for episode_record in season_data.get("episodes", []):
                episode_record["watched"] = True

        self._cache_series_metrics()
        if not self.is_video_playing:
            self.library_loaded.emit()

    def trigger_scan(self, force_refresh: bool = False) -> None:
        if not self.current_library_name:
            self.status_changed.emit("Select a library first.")
            return

        if (
            self.scan_worker_instance is not None
            and self.scan_worker_instance.isRunning()
        ):
            logger.info(
                "ScanWorker is already actively running. Skipping redundant automatic scan trigger."
            )
            return

        self._config.load()
        library_config = self._config.libraries.get(self.current_library_name, {})
        root_directories: List[str] = library_config.get("paths", [])
        library_type: str = library_config.get("type", "tv")
        self.status_changed.emit(
            f"Scanning library '{self.current_library_name}' (force={force_refresh})...."
        )

        self._running_pass3_after_scan = True
        self._doing_scan_and_update = False

        self.scan_worker_instance = ScanWorker(
            root_directories=root_directories,
            library_type=library_type,
            existing_library=self.cached_library_data,
            force_refresh=force_refresh,
            cleanup=False,
            library_name=self.current_library_name,
        )
        self.scan_worker_instance.finished.connect(self._on_scan_finished)
        self.scan_worker_instance.partial_result.connect(self._on_scan_partial)
        self.scan_worker_instance.error.connect(self._on_worker_error)
        self.scan_worker_instance.detail_progress_batch.connect(
            self._on_detail_progress_batch
        )
        self.scan_worker_instance.start()

    def _on_scan_partial(self, partial_library: Dict[str, Any]) -> None:
        if self.current_library_name:
            # We create a shallow copy/update of cached data to not lose references while UI re-renders
            self.cached_library_data = partial_library
            self._cache_series_metrics()
            if not self.is_video_playing:
                self.library_loaded.emit()

    def _on_scan_finished(self, updated_library: Dict[str, Any]) -> None:
        scanned_library_name = (
            self.scan_worker_instance.library_name
            if self.scan_worker_instance
            else self.current_library_name
        )
        if scanned_library_name:
            library_config = self._config.libraries.get(scanned_library_name, {})
            if library_config.get("type", "tv") == "movie":
                self._db.save_movie_library(scanned_library_name, updated_library)
            else:
                self._db.save_library(scanned_library_name, updated_library)

            if self.current_library_name == scanned_library_name:
                self.cached_library_data = updated_library
                self._cache_series_metrics()

            if (
                self.scan_worker_instance
                and self.scan_worker_instance.unavailable_directories
            ):
                for directory_name in self.scan_worker_instance.unavailable_directories:
                    self.status_changed.emit(
                        f"root directory {directory_name} is unavailable check connection to {directory_name}"
                    )
            else:
                self.status_changed.emit(
                    f"Library scan for '{scanned_library_name}' completed successfully."
                )

            if (
                self.current_library_name == scanned_library_name
                and not self.is_video_playing
            ):
                self.library_loaded.emit()
        if self._running_pass3_after_scan and not self._doing_scan_and_update:
            changed_seasons = getattr(
                self.scan_worker_instance, "changed_season_ids", None
            )
            changed_movies = getattr(
                self.scan_worker_instance, "changed_movie_ids", None
            )
            self.trigger_runtime_extraction(changed_seasons, changed_movies)
        elif not self._doing_scan_and_update:
            self.scan_completed.emit()

    def trigger_cleanup(self) -> None:
        if not self.current_library_name:
            self.status_changed.emit("Select a library first.")
            return

        library_config = self._config.libraries.get(self.current_library_name, {})
        root_directories: List[str] = library_config.get("paths", [])
        self.status_changed.emit(
            f"Cleaning up missing files in '{self.current_library_name}'..."
        )

        self.cleanup_worker_instance = CleanupWorker(
            library_name=self.current_library_name, root_directories=root_directories
        )
        self.cleanup_worker_instance.finished.connect(self._on_cleanup_finished)
        self.cleanup_worker_instance.error.connect(self._on_worker_error)
        self.cleanup_worker_instance.start()

    def _on_cleanup_finished(self, statistics: Dict[str, Any]) -> None:
        self.select_library(self.current_library_name, reset_selection=False)
        series_removed: int = statistics.get("series", 0)
        seasons_removed: int = statistics.get("seasons", 0)
        episodes_removed: int = statistics.get("episodes", 0)
        self.status_changed.emit(
            f"Cleanup finished: removed {series_removed} series, {seasons_removed} seasons, {episodes_removed} episodes."
        )

    def trigger_global_cleanup(self) -> None:
        self._config.load()
        self._cleanup_queue = list(self._config.libraries.keys())
        self.status_changed.emit("Starting global library cleanup...")
        self._run_next_global_cleanup()

    def _run_next_global_cleanup(self) -> None:
        if not self._cleanup_queue:
            self.status_changed.emit("Global library cleanup completed.")
            self.scan_completed.emit()
            return

        lib_name = self._cleanup_queue.pop(0)
        library_config = self._config.libraries.get(lib_name, {})
        root_directories: List[str] = library_config.get("paths", [])
        self.status_changed.emit(f"Cleaning up missing files in '{lib_name}'...")

        self.cleanup_worker_instance = CleanupWorker(
            library_name=lib_name, root_directories=root_directories
        )
        self.cleanup_worker_instance.finished.connect(
            self._on_global_cleanup_step_finished
        )
        self.cleanup_worker_instance.error.connect(self._on_global_cleanup_step_error)
        self.cleanup_worker_instance.start()

    def _on_global_cleanup_step_finished(self, statistics: Dict[str, Any]) -> None:
        if self.current_library_name:
            self.select_library(self.current_library_name, reset_selection=False)
        series_removed: int = statistics.get("series", 0)
        seasons_removed: int = statistics.get("seasons", 0)
        episodes_removed: int = statistics.get("episodes", 0)
        logger.info(
            f"Cleanup finished for library step: removed {series_removed} series, {seasons_removed} seasons, {episodes_removed} episodes."
        )
        self._run_next_global_cleanup()

    def _on_global_cleanup_step_error(self, error_message: str) -> None:
        logger.error(f"Global cleanup step worker error: {error_message}")
        self._run_next_global_cleanup()

    def trigger_scan_and_update(self, force_refresh: bool = False) -> None:
        """
        Combines a library scan (discovers new files, updates paths) with a
        cleanup pass (nulls paths for files that have gone missing).
        The cleanup runs automatically once the scan has completed.
        """
        if not self.current_library_name:
            self.status_changed.emit("Select a library first.")
            return

        if (
            self.scan_worker_instance is not None
            and self.scan_worker_instance.isRunning()
        ):
            logger.info(
                "ScanWorker is already actively running. Skipping redundant scan trigger."
            )
            return

        self._config.load()
        library_config = self._config.libraries.get(self.current_library_name, {})
        root_directories: List[str] = library_config.get("paths", [])
        library_type: str = library_config.get("type", "tv")
        self.status_changed.emit(
            f"Scanning & updating library '{self.current_library_name}'..."
        )

        self._running_pass3_after_scan = True
        self._doing_scan_and_update = True

        self.scan_worker_instance = ScanWorker(
            root_directories=root_directories,
            library_type=library_type,
            existing_library=self.cached_library_data,
            force_refresh=force_refresh,
            cleanup=False,
            library_name=self.current_library_name,
        )
        self.scan_worker_instance.finished.connect(
            self._on_scan_and_update_scan_finished
        )
        self.scan_worker_instance.partial_result.connect(self._on_scan_partial)
        self.scan_worker_instance.error.connect(self._on_worker_error)
        self.scan_worker_instance.detail_progress_batch.connect(
            self._on_detail_progress_batch
        )
        self.scan_worker_instance.start()

    def _on_scan_and_update_scan_finished(
        self, updated_library: Dict[str, Any]
    ) -> None:
        """Called when the scan phase of scan_and_update completes. Saves results then runs cleanup."""
        self._on_scan_finished(updated_library)

        # Now chain into cleanup
        if not self.current_library_name:
            return
        library_config = self._config.libraries.get(self.current_library_name, {})
        root_directories: List[str] = library_config.get("paths", [])
        self.status_changed.emit(
            f"Scan complete. Updating paths in '{self.current_library_name}'..."
        )
        self.cleanup_worker_instance = CleanupWorker(
            library_name=self.current_library_name, root_directories=root_directories
        )
        self.cleanup_worker_instance.finished.connect(
            self._on_scan_and_update_cleanup_finished
        )
        self.cleanup_worker_instance.error.connect(self._on_worker_error)
        self.cleanup_worker_instance.start()

    def _on_scan_and_update_cleanup_finished(self, statistics: Dict[str, Any]) -> None:
        """Called when the cleanup phase of scan_and_update completes."""
        self.select_library(self.current_library_name, reset_selection=False)
        series_removed: int = statistics.get("series", 0)
        episodes_nulled: int = statistics.get("episodes", 0)
        self.status_changed.emit(
            f"Scan Library complete. "
            f"{series_removed} series removed, {episodes_nulled} episode paths updated."
        )
        if self._running_pass3_after_scan:
            changed_seasons = getattr(
                self.scan_worker_instance, "changed_season_ids", None
            )
            changed_movies = getattr(
                self.scan_worker_instance, "changed_movie_ids", None
            )
            self.trigger_runtime_extraction(changed_seasons, changed_movies)
        else:
            self.scan_completed.emit()

    def trigger_jellyfin_pull(self) -> None:
        if not self._jellyfin_client.is_configured():
            self.status_changed.emit("Jellyfin is not configured.")
            return

        self.status_changed.emit("Pulling watch history from Jellyfin...")
        self.pull_worker_instance = JellyfinPullWorker()
        self.pull_worker_instance.finished.connect(self._on_pull_finished)
        self.pull_worker_instance.error.connect(self._on_worker_error)
        self.pull_worker_instance.start()

    def _on_pull_finished(self, updated_count: int) -> None:
        if self.current_library_name:
            self.select_library(self.current_library_name, reset_selection=False)
        self.status_changed.emit(
            f"Watch history pulled successfully: updated {updated_count} episodes."
        )

    def trigger_jellyfin_push(self) -> None:
        if not self._jellyfin_client.is_configured():
            self.status_changed.emit("Jellyfin is not configured.")
            return

        self.status_changed.emit("Pushing local watch history to Jellyfin...")
        self.push_worker_instance = JellyfinPushWorker()
        self.push_worker_instance.finished.connect(self._on_push_finished)
        self.push_worker_instance.error.connect(self._on_worker_error)
        self.push_worker_instance.start()

    def _on_push_finished(self, pushed_count: int) -> None:
        self.status_changed.emit(
            f"Watch history pushed successfully: synchronized {pushed_count} episodes."
        )

    def trigger_scan_all(
        self,
        force_refresh: bool = False,
        run_pass1: bool = True,
        run_pass2: bool = True,
        chain_pass3: bool = True,
        chain_cleanup: bool = False,
    ) -> None:
        if (
            self.scan_all_worker_instance is not None
            and self.scan_all_worker_instance.isRunning()
        ):
            logger.info("ScanAllLibrariesWorker is already running.")
            return

        self._config.load()
        self.status_changed.emit("Scanning all libraries...")
        self._running_pass3_after_scan = chain_pass3
        self._running_cleanup_after_scan = chain_cleanup
        self.scan_all_worker_instance = ScanAllLibrariesWorker(
            force_refresh=force_refresh,
            run_pass1=run_pass1,
            run_pass2=run_pass2,
        )
        self.scan_all_worker_instance.library_progress.connect(
            self.global_progress_updated.emit
        )
        self.scan_all_worker_instance.detail_progress_batch.connect(
            self._on_scan_all_detail_progress_batch
        )
        self.scan_all_worker_instance.finished.connect(self._on_scan_all_finished)
        self.scan_all_worker_instance.error.connect(self._on_worker_error)
        self.scan_all_worker_instance.start()

    def _on_detail_progress_batch(self, events: List[Dict[str, Any]]) -> None:
        for event_dict in events:
            self.detail_progress_updated.emit(
                event_dict.get("event", ""), event_dict.get("payload", {})
            )

    def _on_scan_all_detail_progress_batch(self, events: List[Dict[str, Any]]) -> None:
        for event_dict in events:
            event = event_dict.get("event", "")
            payload = event_dict.get("payload", {})
            self.detail_progress_updated.emit(event, payload)

            if event == "finish_root":
                scanned_library = payload.get("library")
                if scanned_library and (
                    self.current_library_name == scanned_library
                    or self.current_library_name == "Combined View"
                ):
                    if self.current_library_name == "Combined View":
                        self.library_loaded.emit()
                    else:
                        library_config = self._config.libraries.get(
                            self.current_library_name, {}
                        )
                        if library_config.get("type", "tv") == "movie":
                            self.cached_library_data = self._db.load_movie_library(
                                self.current_library_name
                            )
                        else:
                            self.cached_library_data = self._db.load_library(
                                self.current_library_name
                            )
                        self._cache_series_metrics()
                        self.library_loaded.emit()

    def _on_scan_all_finished(self) -> None:
        if (
            self.scan_all_worker_instance
            and self.scan_all_worker_instance.unavailable_directories
        ):
            for directory_name in self.scan_all_worker_instance.unavailable_directories:
                self.status_changed.emit(
                    f"root directory {directory_name} is unavailable check connection to {directory_name}"
                )
        else:
            self.status_changed.emit(
                "Global multi-library scan completed successfully."
            )
        if self.current_library_name:
            if self.current_library_name == "Combined View":
                self.library_loaded.emit()
            else:
                self.select_library(self.current_library_name, reset_selection=False)
        if self._running_pass3_after_scan:
            changed_seasons = getattr(
                self.scan_all_worker_instance, "changed_season_ids", None
            )
            changed_movies = getattr(
                self.scan_all_worker_instance, "changed_movie_ids", None
            )
            self.trigger_runtime_extraction(changed_seasons, changed_movies)
        elif self._running_cleanup_after_scan:
            self.trigger_global_cleanup()
        else:
            self.scan_completed.emit()

    def trigger_runtime_extraction(
        self,
        changed_season_ids: Optional[Set[str]] = None,
        changed_movie_ids: Optional[Set[str]] = None,
    ) -> None:
        if (
            self.file_property_worker_instance is not None
            and self.file_property_worker_instance.isRunning()
        ):
            logger.info("FilePropertyExtractionWorker is already running.")
            return

        self.status_changed.emit("Extracting missing video runtimes in background...")
        self.file_property_worker_instance = FilePropertyExtractionWorker(
            changed_season_ids=changed_season_ids,
            changed_movie_ids=changed_movie_ids,
        )
        self.file_property_worker_instance.progress_updated.connect(
            self._on_runtime_progress
        )
        self.file_property_worker_instance.finished.connect(self._on_runtime_finished)
        self.file_property_worker_instance.error.connect(self._on_worker_error)
        self.file_property_worker_instance.start()

    def _on_runtime_progress(self, completed_count: int, total_count: int) -> None:
        self.global_progress_updated.emit(
            "Extracting Runtimes", completed_count, total_count
        )
        self.detail_progress_updated.emit(
            "runtime_extraction_progress",
            {"completed": completed_count, "total": total_count},
        )

    def _on_runtime_finished(self, updated_count: int) -> None:
        self.status_changed.emit(
            f"Runtime extraction completed: updated {updated_count} videos."
        )
        if self.current_library_name:
            self.select_library(self.current_library_name, reset_selection=False)
        self._running_pass3_after_scan = False

        # Show green (Pass 3 = 100%) before hiding, even if no items were processed.
        self.detail_progress_updated.emit(
            "runtime_extraction_progress",
            {"completed": 0, "total": 0},
        )

        if self._running_cleanup_after_scan:
            self._running_cleanup_after_scan = False
            self.trigger_global_cleanup()
        else:
            self.scan_completed.emit()

    def _on_worker_error(self, error_message: str) -> None:
        self.status_changed.emit(f"Worker Error: {error_message}")
        logger.error(f"Background execution fault: {error_message}")
        self.scan_completed.emit()

    def _download_provider_artwork(
        self,
        target_dict: Dict[str, Any],
        match_dictionary: Dict[str, Any],
        is_movie: bool,
    ) -> None:
        if match_dictionary.get("poster_path"):
            raw_poster_path: str = match_dictionary.get("poster_path", "")
            tmdb_identifier_value: str = target_dict.get("tmdb_identifier", "")
            if raw_poster_path and tmdb_identifier_value:
                prefix = "tmdb_movie_" if is_movie else "tmdb_series_"
                cached_image_path: Optional[str] = self._tmdb_client.download_image(
                    raw_poster_path, f"{prefix}{tmdb_identifier_value}"
                )
                target_dict["poster_path"] = cached_image_path or raw_poster_path
            else:
                target_dict["poster_path"] = raw_poster_path

    def _sync_tmdb_episodes_for_series(
        self, series_record: Dict[str, Any], new_tmdb_identifier: str
    ) -> None:
        episode_group_details = None
        saved_group_id = series_record.get("metadata", {}).get("tmdb_episode_group_id")
        if saved_group_id and saved_group_id != "default":
            try:
                episode_group_details = self._tmdb_client.get_episode_group_details(
                    saved_group_id
                )
            except Exception as e:
                logger.exception(
                    f"Failed to fetch saved group details {saved_group_id}: {e}"
                )
        if not episode_group_details:
            episode_group_details = self._tmdb_client.get_season_based_episode_group(
                new_tmdb_identifier
            )
        group_seasons = {}
        if (
            episode_group_details
            and isinstance(episode_group_details, dict)
            and "groups" in episode_group_details
        ):
            for group in episode_group_details.get("groups", []):
                group_name = group.get("name") or ""
                season_num_match = re.search(r"\d+", group_name)
                season_num = (
                    int(season_num_match.group())
                    if season_num_match
                    else group.get("order", -1)
                )
                if group_name.lower() == "specials":
                    season_num = 0
                if season_num >= 0:
                    group_seasons[season_num] = group.get("episodes", [])
        else:
            episode_group_details = None

        for season_folder_name, season_data_dict in series_record.get(
            "seasons", {}
        ).items():
            if season_folder_name.lower() == "specials":
                target_season_number: int = 0
            else:
                parsed_season_match = re.search(r"\d+", season_folder_name)
                target_season_number = (
                    int(parsed_season_match.group()) if parsed_season_match else -1
                )

            if target_season_number >= 0:
                if (
                    episode_group_details
                    and isinstance(episode_group_details, dict)
                    and "groups" in episode_group_details
                ):
                    fetched_episodes_list = []
                    for group_ep in group_seasons.get(target_season_number, []):
                        fetched_episodes_list.append(
                            {
                                "id": group_ep.get("id"),
                                "name": group_ep.get("name"),
                                "episode_number": group_ep.get("order")
                                + 1,  # Using order + 1 as the 1-indexed episode number
                                "air_date": group_ep.get("air_date") or "",
                                "runtime": group_ep.get("runtime") or 0,
                            }
                        )
                else:
                    fetched_episodes_list = self._tmdb_client.get_episodes(
                        new_tmdb_identifier, target_season_number
                    )
                for episode_item_dict in season_data_dict.get("episodes", []):
                    episode_filename: str = str(
                        episode_item_dict.get("name")
                        or Path(str(episode_item_dict.get("path", ""))).name
                    )
                    matched_tmdb_episode: Optional[Dict[str, Any]] = None

                    episode_number_match = re.search(
                        r"[Ss]\d+[Ee](\d+)", episode_filename
                    )
                    if episode_number_match:
                        target_episode_number: int = int(episode_number_match.group(1))
                        for candidate_episode in fetched_episodes_list:
                            if (
                                candidate_episode.get("episode_number")
                                == target_episode_number
                            ):
                                matched_tmdb_episode = candidate_episode
                                break
                    else:
                        stem_lower: str = Path(episode_filename).stem.lower()
                        for candidate_episode in fetched_episodes_list:
                            candidate_name: str = str(
                                candidate_episode.get("name") or ""
                            ).lower()
                            if candidate_name and candidate_name in stem_lower:
                                matched_tmdb_episode = candidate_episode
                                break

                    if matched_tmdb_episode:
                        matched_id_str: str = str(matched_tmdb_episode.get("id", ""))
                        episode_item_dict["tmdb_identifier"] = matched_id_str
                        episode_item_dict["tmdb_episode_identifier"] = matched_id_str
                        if matched_tmdb_episode.get("name"):
                            episode_item_dict["tmdb_name"] = matched_tmdb_episode.get(
                                "name", ""
                            )
                        if matched_tmdb_episode.get("episode_number") is not None:
                            episode_item_dict["tmdb_number"] = matched_tmdb_episode.get(
                                "episode_number"
                            )
                        if matched_tmdb_episode.get("air_date"):
                            episode_item_dict["air_date"] = matched_tmdb_episode.get(
                                "air_date", ""
                            )
                        if matched_tmdb_episode.get("runtime"):
                            episode_item_dict["runtime"] = matched_tmdb_episode.get(
                                "runtime", 0
                            )

                # Add TMDB placeholders if show_future_episodes is enabled
                show_future = self._config.libraries.get(
                    self.current_library_name, {}
                ).get("show_future_episodes", True)
                if show_future:
                    from lan_streamer.scanner.scan_tv import (
                        _create_tmdb_placeholder_episodes,
                    )

                    season_metadata = season_data_dict.get("metadata", {})
                    placeholders = _create_tmdb_placeholder_episodes(
                        fetched_episodes_list,
                        season_data_dict.get("episodes", []),
                        season_folder_name,
                        season_metadata,
                        show_future_episodes=show_future,
                    )
                    season_data_dict["episodes"].extend(placeholders)

    def apply_metadata_match(
        self, series_name: str, match_dictionary: Dict[str, Any]
    ) -> None:
        logger.info(
            f"Controller applying metadata match for '{series_name}': {match_dictionary}"
        )
        if series_name not in self.cached_library_data:
            return

        library_config = self._config.libraries.get(self.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        target_dict: Dict[str, Any] = (
            series_record if is_movie else series_record.get("metadata", {})
        )

        provider_name: str = match_dictionary.get("provider", "TMDB")
        target_identifier: str = match_dictionary.get("id", "")

        if provider_name == "Jellyfin":
            target_dict["jellyfin_id"] = target_identifier
            tmdb_id_mapped: str = match_dictionary.get("tmdb_id", "")
            if tmdb_id_mapped:
                target_dict["tmdb_identifier"] = tmdb_id_mapped
        else:
            target_dict["tmdb_identifier"] = target_identifier

        if match_dictionary.get("name"):
            target_dict["tmdb_name"] = match_dictionary.get("name", "")
        if match_dictionary.get("overview"):
            target_dict["overview"] = match_dictionary.get("overview", "")

        self._download_provider_artwork(target_dict, match_dictionary, is_movie)

        if not is_movie and match_dictionary.get("first_air_date"):
            target_dict["first_air_date"] = match_dictionary.get("first_air_date", "")
        elif is_movie and match_dictionary.get("first_air_date"):
            air_date_str = match_dictionary.get("first_air_date", "")
            if air_date_str:
                try:
                    target_dict["year"] = int(air_date_str.split("-")[0])
                except ValueError:
                    pass

        target_dict["locked_metadata"] = True
        if not is_movie:
            series_record["metadata"] = target_dict

            new_tmdb_identifier: str = target_dict.get("tmdb_identifier", "")
            if new_tmdb_identifier:
                # Remove any previous metadata records (placeholders with path=None)
                # and clear old TMDB fields from remaining episodes before redownloading
                total_placeholders_removed = 0
                total_episodes_cleared = 0
                for season_name, season_data in list(
                    series_record.get("seasons", {}).items()
                ):
                    filtered_episodes = []
                    for ep in season_data.get("episodes", []):
                        if ep.get("path"):
                            # Clear old metadata fields
                            for key in [
                                "tmdb_name",
                                "tmdb_identifier",
                                "tmdb_episode_identifier",
                                "tmdb_number",
                                "air_date",
                                "runtime",
                            ]:
                                ep.pop(key, None)
                            filtered_episodes.append(ep)
                            total_episodes_cleared += 1
                        else:
                            total_placeholders_removed += 1
                    season_data["episodes"] = filtered_episodes

                logger.info(
                    f"Cleared manual match metadata for '{series_name}': "
                    f"removed {total_placeholders_removed} placeholder episode(s), "
                    f"cleared old TMDB metadata from {total_episodes_cleared} local episode(s)."
                )

                self._sync_tmdb_episodes_for_series(series_record, new_tmdb_identifier)

        if self.current_library_name:
            if is_movie:
                self._db.save_movie_library(
                    self.current_library_name, self.cached_library_data
                )
            else:
                self._db.save_library(
                    self.current_library_name, self.cached_library_data
                )

        self.status_changed.emit(
            f"Successfully applied metadata match to '{series_name}'."
        )
        self.library_loaded.emit()
        if self.selected_series_name == series_name:
            if is_movie:
                self.movie_selected.emit(series_name)
            else:
                self.series_selected.emit(series_name)

    def apply_jellyfin_watch_match(
        self, series_name: str, match_dictionary: Dict[str, Any]
    ) -> None:
        logger.info(
            f"Controller applying Jellyfin watch history match for '{series_name}': {match_dictionary}"
        )
        if series_name not in self.cached_library_data:
            return

        library_config = self._config.libraries.get(self.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        target_dict: Dict[str, Any] = (
            series_record if is_movie else series_record.get("metadata", {})
        )

        target_identifier: str = match_dictionary.get("id", "")
        target_dict["jellyfin_id"] = target_identifier

        if self.current_library_name:
            if is_movie:
                self._db.save_movie_library(
                    self.current_library_name, self.cached_library_data
                )
            else:
                self._db.save_library(
                    self.current_library_name, self.cached_library_data
                )

        self.status_changed.emit(
            f"Successfully linked Jellyfin watch history for '{series_name}'."
        )
        self.library_loaded.emit()
        if self.selected_series_name == series_name:
            if is_movie:
                self.movie_selected.emit(series_name)
            else:
                self.series_selected.emit(series_name)

    def apply_episode_metadata_match(
        self, series_name: str, episode_path: str, match_dictionary: Dict[str, Any]
    ) -> None:
        logger.info(
            f"Controller applying episode metadata match for '{series_name}' at '{episode_path}': {match_dictionary}"
        )
        if series_name not in self.cached_library_data:
            return

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        episode_found: bool = False

        for season_data in series_record.get("seasons", {}).values():
            for episode_record in season_data.get("episodes", []):
                if episode_record.get("path") == episode_path:
                    target_identifier: str = str(match_dictionary.get("id", ""))
                    episode_record["tmdb_identifier"] = target_identifier
                    episode_record["tmdb_episode_identifier"] = target_identifier
                    if match_dictionary.get("name"):
                        episode_record["tmdb_name"] = match_dictionary.get("name", "")
                    if match_dictionary.get("episode_number") is not None:
                        episode_record["tmdb_number"] = match_dictionary.get(
                            "episode_number"
                        )
                    if match_dictionary.get("air_date"):
                        episode_record["air_date"] = match_dictionary.get(
                            "air_date", ""
                        )
                    if match_dictionary.get("runtime"):
                        episode_record["runtime"] = match_dictionary.get("runtime", 0)
                    episode_found = True
                    break
            if episode_found:
                break

        if episode_found:
            if self.current_library_name:
                self._db.save_library(
                    self.current_library_name, self.cached_library_data
                )

            self.status_changed.emit(
                f"Successfully applied episode metadata match to '{series_name}'."
            )
            self.library_loaded.emit()
            if self.selected_series_name == series_name:
                self.series_selected.emit(series_name)

    def update_episode_metadata(
        self, series_name: str, episode_path: str, metadata_dictionary: Dict[str, Any]
    ) -> None:
        """Persists manual metadata overrides for a specific episode."""
        logger.info(
            f"Controller updating episode metadata for '{series_name}' at '{episode_path}'"
        )
        if series_name not in self.cached_library_data:
            return

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        episode_found: bool = False

        for season_data in series_record.get("seasons", {}).values():
            for episode_record in season_data.get("episodes", []):
                if episode_record.get("path") == episode_path:
                    for key, value in metadata_dictionary.items():
                        episode_record[key] = value
                    episode_found = True
                    break
            if episode_found:
                break

        if episode_found:
            if self.current_library_name:
                self._db.save_library(
                    self.current_library_name, self.cached_library_data
                )
            self.library_loaded.emit()
            if self.selected_series_name == series_name:
                self.series_selected.emit(series_name)

    def toggle_series_lock(self, series_name: str, locked: bool) -> None:
        """
        Updates the locked_metadata flag for a series or movie and persists it to the database.
        """
        logger.info(f"Controller toggling lock for '{series_name}' to {locked}")
        if series_name not in self.cached_library_data:
            return

        library_config = self._config.libraries.get(self.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        if is_movie:
            series_record["locked_metadata"] = locked
            if self.current_library_name:
                self._db.save_movie_library(
                    self.current_library_name, self.cached_library_data
                )
            self.movie_selected.emit(series_name)
        else:
            if "metadata" not in series_record:
                series_record["metadata"] = {}
            series_record["metadata"]["locked_metadata"] = locked
            if self.current_library_name:
                self._db.save_library(
                    self.current_library_name, self.cached_library_data
                )
            self.series_selected.emit(series_name)

        self.library_loaded.emit()

    def trigger_series_refresh(self, series_name: str) -> None:
        """Triggers a background RefreshSeriesWorker for the specified series or movie."""
        if not self.current_library_name:
            self.status_changed.emit("Select a library first.")
            return

        if self.scan_worker_instance and self.scan_worker_instance.isRunning():
            self.status_changed.emit("A scan is already in progress.")
            return

        library_config = self._config.libraries.get(self.current_library_name, {})
        library_type = library_config.get("type", "tv")
        root_directories = library_config.get("paths", [])

        self.status_changed.emit(f"Refreshing metadata for '{series_name}'...")

        from lan_streamer.backend import RefreshSeriesWorker

        self.refresh_worker_instance = RefreshSeriesWorker(
            library_name=self.current_library_name,
            item_name=series_name,
            library_type=library_type,
            root_directories=root_directories,
            existing_library=self.cached_library_data,
        )
        self.refresh_worker_instance.finished.connect(self._on_refresh_finished)
        self.refresh_worker_instance.error.connect(self._on_worker_error)
        self.refresh_worker_instance.start()

    def _on_refresh_finished(self, updated_library: Dict[str, Any]) -> None:
        scanned_library_name = (
            self.refresh_worker_instance.library_name
            if self.refresh_worker_instance
            else self.current_library_name
        )
        if scanned_library_name:
            if self.current_library_name == scanned_library_name:
                self.cached_library_data = updated_library
                self._cache_series_metrics()
                self.status_changed.emit("Metadata refresh completed successfully.")
                if not self.is_video_playing:
                    self.library_loaded.emit()
            else:
                item_name = (
                    self.refresh_worker_instance.item_name
                    if self.refresh_worker_instance
                    else "item"
                )
                self.status_changed.emit(
                    f"Background refresh for '{item_name}' completed successfully."
                )

    def refresh_episode_metadata(self, series_name: str, episode_path: str) -> None:
        """
        Queries TMDB directly for the specific episode's metadata and updates it,
        bypassing lock status (since targeted).
        """
        logger.info(
            f"Controller refreshing episode metadata for '{series_name}' at '{episode_path}'"
        )
        if series_name not in self.cached_library_data:
            return

        series_record = self.cached_library_data[series_name]
        series_tmdb_id = series_record.get("metadata", {}).get("tmdb_identifier")
        if not series_tmdb_id:
            logger.warning(
                "Cannot refresh episode metadata because series has no TMDB identifier"
            )
            return

        target_episode: Optional[Dict[str, Any]] = None
        target_season_name: Optional[str] = None
        for season_name, season_data in series_record.get("seasons", {}).items():
            for ep in season_data.get("episodes", []):
                if ep.get("path") == episode_path:
                    target_episode = ep
                    target_season_name = season_name
                    break
            if target_episode:
                break

        if not target_episode or target_season_name is None:
            logger.warning("Episode not found in cache")
            return

        if target_season_name.lower() == "specials":
            season_index = 0
        else:
            m = re.search(r"\d+", target_season_name)
            season_index = int(m.group()) if m else 1

        episode_num = target_episode.get("episode_number") or target_episode.get(
            "tmdb_number"
        )
        if episode_num is None:
            logger.warning("Episode has no episode number")
            return

        try:
            tmdb_episodes = self._tmdb_client.get_episodes(series_tmdb_id, season_index)
            matched_ep = None
            for ep in tmdb_episodes:
                if ep.get("episode_number") == episode_num:
                    matched_ep = ep
                    break

            if matched_ep:
                target_episode["tmdb_name"] = matched_ep.get("name", "")
                target_episode["name"] = matched_ep.get("name", "")
                target_episode["overview"] = matched_ep.get("overview", "")
                target_episode["air_date"] = matched_ep.get("air_date", "")
                target_episode["runtime"] = matched_ep.get("runtime", 0)

                self._db.save_library(
                    self.current_library_name, self.cached_library_data
                )
                self.library_loaded.emit()
                if self.selected_series_name == series_name:
                    self.series_selected.emit(series_name)
                logger.info("Successfully refreshed episode metadata from TMDB")
            else:
                logger.warning(
                    f"Could not find episode {episode_num} in TMDB season {season_index}"
                )
        except Exception:
            logger.exception("Failed to refresh episode metadata from TMDB")

    def update_movie_metadata(
        self, movie_name: str, movie_path: str, metadata: Dict[str, Any]
    ) -> None:
        """
        Updates movie metadata in the database and refreshes local cache.
        Strictly typed with no abbreviations.
        """
        if movie_name not in self.cached_library_data:
            return

        movie_data = self.cached_library_data[movie_name]
        movie_data.update(metadata)

        # Persistence
        self._db.save_library(self.current_library_name, self.cached_library_data)
        self._cache_series_metrics()
        self.library_loaded.emit()

    def merge_subtitles(self, video_path: str, subtitle_paths: List[str]) -> None:
        """Triggers background ffmpeg worker to merge external subtitles into video file."""
        if (
            self.merge_subtitle_worker_instance
            and self.merge_subtitle_worker_instance.isRunning()
        ):
            self.status_changed.emit("Subtitle merge already in progress.")
            return

        from lan_streamer.backend import SubtitleMergeWorker

        self.status_changed.emit("Merging external subtitles into video file...")
        self.merge_subtitle_worker_instance = SubtitleMergeWorker(
            video_path, subtitle_paths
        )
        self.merge_subtitle_worker_instance.finished.connect(
            self._on_subtitle_merge_finished
        )
        self.merge_subtitle_worker_instance.error.connect(self._on_worker_error)
        self.merge_subtitle_worker_instance.start()

    def _on_subtitle_merge_finished(self, final_path: str) -> None:
        self.status_changed.emit("Subtitles merged successfully.")
        # Trigger scan to update metadata/details if needed
        self.trigger_scan(force_refresh=False)

    def embed_metadata(self, video_path: str, metadata: Dict[str, str]) -> None:
        """Triggers background ffmpeg worker to embed metadata into video file."""
        if (
            self.embed_metadata_worker_instance
            and self.embed_metadata_worker_instance.isRunning()
        ):
            self.status_changed.emit("Metadata embedding already in progress.")
            return

        from lan_streamer.backend import MetadataEmbedWorker

        self.status_changed.emit("Embedding metadata into video file...")
        self.embed_metadata_worker_instance = MetadataEmbedWorker(video_path, metadata)
        self.embed_metadata_worker_instance.finished.connect(
            self._on_metadata_embed_finished
        )
        self.embed_metadata_worker_instance.error.connect(self._on_worker_error)
        self.embed_metadata_worker_instance.start()

    def _on_metadata_embed_finished(self, final_path: str) -> None:
        self.status_changed.emit("Metadata embedded successfully.")
        self.trigger_scan(force_refresh=False)

    def embed_metadata_series(self, series_name: str) -> None:
        """Triggers background worker to embed metadata for all episodes in a series."""
        if (
            self.embed_metadata_worker_instance
            and self.embed_metadata_worker_instance.isRunning()
        ):
            self.status_changed.emit("Metadata embedding already in progress.")
            return

        if series_name not in self.cached_library_data:
            return

        series_record = self.cached_library_data[series_name]
        all_episodes = []
        for season in series_record.get("seasons", {}).values():
            for ep in season.get("episodes", []):
                all_episodes.append(ep)

        if not all_episodes:
            self.status_changed.emit("No episodes found in series.")
            return

        from lan_streamer.backend import SeriesMetadataEmbedWorker

        self.status_changed.emit(f"Embedding metadata for series '{series_name}'...")
        self.embed_metadata_worker_instance = SeriesMetadataEmbedWorker(
            series_name, all_episodes
        )
        self.embed_metadata_worker_instance.progress_updated.connect(
            self.global_progress_updated.emit
        )
        self.embed_metadata_worker_instance.finished.connect(
            lambda: self.status_changed.emit("Series metadata embedding finished.")
        )
        self.embed_metadata_worker_instance.error.connect(self._on_worker_error)
        self.embed_metadata_worker_instance.start()

    def update_series_name(self, old_name: str, new_name: str) -> None:
        """Renames a series in the database and updates cache."""
        if old_name not in self.cached_library_data or not new_name:
            return

        series_data = self.cached_library_data.pop(old_name)
        self.cached_library_data[new_name] = series_data

        self._db.save_library(self.current_library_name, self.cached_library_data)
        self._cache_series_metrics()
        self.library_loaded.emit()
        # Trigger re-selection to update UI
        self.selected_series_name = new_name
        self.series_selected.emit(new_name)

    def apply_rename_batch(self, preview_results: List[Dict[str, Any]]) -> None:
        logger.info(
            f"Controller executing batch renames for {len(preview_results)} files."
        )
        from lan_streamer.scanner.renamer import perform_rename

        def on_rename_success(old_path_string: str, new_path_string: str) -> None:
            self._db.update_episode_path(old_path_string, new_path_string)
            for series_dictionary in self.cached_library_data.values():
                for season_dictionary in series_dictionary.get("seasons", {}).values():
                    for episode_dictionary in season_dictionary.get("episodes", []):
                        if episode_dictionary.get("default_path") == old_path_string:
                            episode_dictionary["default_path"] = new_path_string
                        if episode_dictionary.get("path") == old_path_string:
                            episode_dictionary["path"] = new_path_string
                        versions = episode_dictionary.get("versions") or []
                        for v in versions:
                            if v.get("path") == old_path_string:
                                v["path"] = new_path_string

        perform_rename(preview_results, on_rename_success)

        if self.current_library_name:
            self._db.save_library(self.current_library_name, self.cached_library_data)

        self.status_changed.emit("Batch renaming completed successfully.")
        self.library_loaded.emit()
        if self.selected_series_name:
            self.series_selected.emit(self.selected_series_name)

    def set_video_playing(self, is_playing: bool) -> None:
        logger.info(f"Controller setting video playing state: {is_playing}")
        self.is_video_playing = is_playing
        if not is_playing:
            self.library_loaded.emit()
            if self.selected_series_name:
                library_config = self._config.libraries.get(
                    self.current_library_name, {}
                )
                if library_config.get("type", "tv") == "movie":
                    self.movie_selected.emit(self.selected_series_name)
                else:
                    self.series_selected.emit(self.selected_series_name)

    def delete_series(self, series_name: str) -> None:
        """Deletes a series record from database."""
        logger.info(f"Controller deleting series: {series_name}")
        if not self.current_library_name:
            return

        try:
            self._db.delete_series_record(self.current_library_name, series_name)
        except Exception as e:
            logger.exception(f"Failed to delete series record for {series_name}: {e}")

        self.select_library(self.current_library_name, reset_selection=True)

    def delete_episode(self, absolute_path: str) -> None:
        """Deletes an episode record from database."""
        logger.info(f"Controller deleting episode: {absolute_path}")
        try:
            self._db.delete_episode_record(absolute_path)
        except Exception as e:
            logger.exception(
                f"Failed to delete episode record for {absolute_path}: {e}"
            )

        if self.current_library_name:
            self.select_library(self.current_library_name, reset_selection=False)
