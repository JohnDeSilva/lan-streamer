import logging
from pathlib import Path
from typing import List, Any
from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QThread, QByteArray
from PySide6.QtGui import QStandardItemModel, QStandardItem

from .config import config
from . import db
from .jellyfin import jellyfin_client
from .tmdb import tmdb_client
from .scanner import scan_directories

logger = logging.getLogger(__name__)


class BackendBridge(QObject):
    """
    QML Declarative Backend Bridge managing data models and multi-select Action Toolbar operations.
    Conforms strictly to zero-abbreviation variable naming standards.
    """

    availableLibrariesChanged = Signal()
    statusMessageChanged = Signal()
    seriesModelChanged = Signal()
    seasonModelChanged = Signal()
    episodeModelChanged = Signal()
    seriesSortOptionChanged = Signal()
    filterOutWatchedChanged = Signal()
    jellyfinEnabledChanged = Signal()
    configChanged = Signal()
    playbackRequested = Signal(
        str
    )  # Emits target file path to trigger embedded video surface
    openMetadataMatchDialog = Signal(str)
    selectedSeriesOverviewChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._status_message = "Ready"
        self._available_libraries: List[str] = list(config.libraries.keys())
        self._current_library_name: str = ""
        self._series_sort_option: str = config.sort_mode
        self._filter_out_watched: bool = config.filter_out_watched

        # Initialize native QStandardItemModel instances for QML consumption
        self._series_model = QStandardItemModel()
        self._season_model = QStandardItemModel()
        self._episode_model = QStandardItemModel()

        # Define custom roles for QML delegate access
        self.watched_role = Qt.ItemDataRole.UserRole + 1
        self.path_role = Qt.ItemDataRole.UserRole + 2
        self.jellyfin_identifier_role = Qt.ItemDataRole.UserRole + 3
        self.poster_role = Qt.ItemDataRole.UserRole + 4

        # Configure custom QML role names mapping across all models
        unified_role_names: dict[int, QByteArray] = {
            Qt.ItemDataRole.DisplayRole: QByteArray(b"modelDisplay"),
            self.watched_role: QByteArray(b"watched"),
            self.path_role: QByteArray(b"path"),
            self.jellyfin_identifier_role: QByteArray(b"jellyfinIdentifier"),
            self.poster_role: QByteArray(b"posterPath"),
        }
        self._series_model.setItemRoleNames(unified_role_names)
        self._season_model.setItemRoleNames(unified_role_names)
        self._episode_model.setItemRoleNames(unified_role_names)

        self._cached_library_data: dict[str, Any] = {}
        self._selected_series_name: str = ""
        self._selected_series_overview: str = ""
        self._selected_season_name: str = ""

        if self._available_libraries:
            self.selectLibrary(self._available_libraries[0])

    # --- Reactive Properties Exposed to QML ---

    @Property(str, notify=selectedSeriesOverviewChanged)
    def selectedSeriesOverview(self) -> str:
        return self._selected_series_overview

    @Property(list, notify=availableLibrariesChanged)
    def availableLibraries(self) -> List[str]:
        return self._available_libraries

    @Property(str, notify=statusMessageChanged)
    def statusMessage(self) -> str:
        return self._status_message

    @statusMessage.setter  # type: ignore
    def statusMessage(self, value: str) -> None:
        if self._status_message != value:
            self._status_message = value
            self.statusMessageChanged.emit()

    @Property(QObject, notify=seriesModelChanged)
    def seriesModel(self) -> QStandardItemModel:
        return self._series_model

    @Property(QObject, notify=seasonModelChanged)
    def seasonModel(self) -> QStandardItemModel:
        return self._season_model

    @Property(QObject, notify=episodeModelChanged)
    def episodeModel(self) -> QStandardItemModel:
        return self._episode_model

    @Property(str, notify=seriesSortOptionChanged)
    def seriesSortOption(self) -> str:
        return self._series_sort_option

    @seriesSortOption.setter  # type: ignore
    def seriesSortOption(self, value: str) -> None:
        if self._series_sort_option != value:
            self._series_sort_option = value
            config.sort_mode = value
            config.save()
            self.seriesSortOptionChanged.emit()
            self._refresh_series_model()

    @Property(bool, notify=filterOutWatchedChanged)
    def filterOutWatched(self) -> bool:
        return self._filter_out_watched

    @filterOutWatched.setter  # type: ignore
    def filterOutWatched(self, value: bool) -> None:
        if self._filter_out_watched != value:
            self._filter_out_watched = value
            config.filter_out_watched = value
            config.save()
            self.filterOutWatchedChanged.emit()
            self._refresh_series_model()

    @Property(bool, notify=jellyfinEnabledChanged)
    def jellyfinEnabled(self) -> bool:
        return jellyfin_client.is_configured()

    @Property(str, notify=configChanged)
    def configJellyfinUrl(self) -> str:
        return config.jellyfin_url

    @configJellyfinUrl.setter  # type: ignore
    def configJellyfinUrl(self, value: str) -> None:
        val = value.strip()
        if config.jellyfin_url != val:
            config.jellyfin_url = val
            config.save()
            self.jellyfinEnabledChanged.emit()
            self.configChanged.emit()

    @Property(str, notify=configChanged)
    def configJellyfinApiKey(self) -> str:
        return config.jellyfin_api_key

    @configJellyfinApiKey.setter  # type: ignore
    def configJellyfinApiKey(self, value: str) -> None:
        val = value.strip()
        if config.jellyfin_api_key != val:
            config.jellyfin_api_key = val
            config.save()
            self.jellyfinEnabledChanged.emit()
            self.configChanged.emit()

    @Property(str, notify=configChanged)
    def configTmdbApiKey(self) -> str:
        return config.tmdb_api_key

    @configTmdbApiKey.setter  # type: ignore
    def configTmdbApiKey(self, value: str) -> None:
        val = value.strip()
        if config.tmdb_api_key != val:
            config.tmdb_api_key = val
            config.save()
            self.configChanged.emit()

    @Property(bool, notify=configChanged)
    def configSyncHistoryOnStart(self) -> bool:
        return config.sync_history_on_start

    @configSyncHistoryOnStart.setter  # type: ignore
    def configSyncHistoryOnStart(self, value: bool) -> None:
        if config.sync_history_on_start != value:
            config.sync_history_on_start = value
            config.save()
            self.configChanged.emit()

    @Property(bool, notify=configChanged)
    def configUseEmbeddedPlayer(self) -> bool:
        return config.use_embedded_player

    @configUseEmbeddedPlayer.setter  # type: ignore
    def configUseEmbeddedPlayer(self, value: bool) -> None:
        if config.use_embedded_player != value:
            config.use_embedded_player = value
            config.save()
            self.configChanged.emit()

    @Property(bool, notify=configChanged)
    def configEnableHardwareAcceleration(self) -> bool:
        return config.enable_hw_accel

    @configEnableHardwareAcceleration.setter  # type: ignore
    def configEnableHardwareAcceleration(self, value: bool) -> None:
        if config.enable_hw_accel != value:
            config.enable_hw_accel = value
            config.save()
            self.configChanged.emit()

    @Property(bool, notify=configChanged)
    def configEnableGlobalFileLogging(self) -> bool:
        return config.enable_global_file_logging

    @configEnableGlobalFileLogging.setter  # type: ignore
    def configEnableGlobalFileLogging(self, value: bool) -> None:
        if config.enable_global_file_logging != value:
            config.enable_global_file_logging = value
            config.save()
            self.configChanged.emit()

    @Property(str, notify=configChanged)
    def configDatabasePath(self) -> str:
        return config.database_path

    @configDatabasePath.setter  # type: ignore
    def configDatabasePath(self, value: str) -> None:
        val = value.strip()
        if config.database_path != val:
            config.database_path = val
            config.save()
            self.configChanged.emit()

    @Property(str, notify=configChanged)
    def configLogDirectory(self) -> str:
        return config.log_directory

    @configLogDirectory.setter  # type: ignore
    def configLogDirectory(self, value: str) -> None:
        val = value.strip()
        if config.log_directory != val:
            config.log_directory = val
            config.save()
            self.configChanged.emit()

    # --- Action Slots Invoked from QML ---

    @Slot(str)
    def selectLibrary(self, library_name: str) -> None:
        logger.info(f"Loading library into QML backend: {library_name}")
        self._current_library_name = library_name
        self.statusMessage = f"Loading library: {library_name}"

        self._cached_library_data = db.load_library(library_name)
        self._cache_series_metrics()
        self._season_model.clear()
        self._episode_model.clear()

        self._refresh_series_model()
        self.statusMessage = "Loaded library series successfully"

    def _cache_series_metrics(self) -> None:
        if not getattr(self, "_cached_library_data", None):
            return

        for series_name, series_data in self._cached_library_data.items():
            total_episodes = 0
            watched_episodes = 0
            max_date_added = 0
            max_air_date = ""
            for season in series_data.get("seasons", {}).values():
                for episode_record in season.get("episodes", []):
                    total_episodes += 1
                    if episode_record.get("watched"):
                        watched_episodes += 1
                    added_timestamp = episode_record.get("date_added") or 0
                    if added_timestamp > max_date_added:
                        max_date_added = added_timestamp
                    ep_air_date = episode_record.get("air_date") or ""
                    if ep_air_date > max_air_date:
                        max_air_date = ep_air_date

            series_data["metrics"] = {
                "total_episodes": total_episodes,
                "watched_episodes": watched_episodes,
                "max_date_added": max_date_added,
                "max_air_date": max_air_date,
            }

    def _refresh_series_model(self) -> None:
        if not getattr(self, "_cached_library_data", None):
            return

        self._series_model.clear()

        series_entries = []
        for series_name, series_data in self._cached_library_data.items():
            metadata_dict = series_data.get("metadata", {})
            metrics = series_data.get("metrics", {})

            total_episodes = metrics.get("total_episodes", 0)
            watched_episodes = metrics.get("watched_episodes", 0)
            max_date_added = metrics.get("max_date_added", 0)
            max_air_date = metrics.get("max_air_date", "")

            is_series_watched = (
                total_episodes > 0 and watched_episodes == total_episodes
            )
            if self._filter_out_watched and is_series_watched:
                continue

            first_air_date = metadata_dict.get("first_air_date", "")
            effective_air_date = max(max_air_date, first_air_date)
            poster_path = metadata_dict.get("poster_path", "")

            series_entries.append(
                {
                    "name": series_name,
                    "poster_path": poster_path,
                    "date_added": max_date_added,
                    "effective_air_date": effective_air_date,
                }
            )

        if self._series_sort_option == "Recently Added":
            series_entries.sort(key=lambda entry: entry["date_added"], reverse=True)
        elif self._series_sort_option == "Recently Aired":
            series_entries.sort(
                key=lambda entry: entry["effective_air_date"], reverse=True
            )
        else:
            series_entries.sort(key=lambda entry: entry["name"].lower())

        for entry in series_entries:
            item = QStandardItem(entry["name"])
            item.setData(entry["name"], Qt.ItemDataRole.DisplayRole)
            item.setData(entry["poster_path"], self.poster_role)
            self._series_model.appendRow(item)

        self.seriesModelChanged.emit()

    @Slot(int)
    def selectSeries(self, index: int) -> None:
        self._season_model.clear()
        self._episode_model.clear()
        self._selected_series_name = ""
        self._selected_series_overview = ""
        self.selectedSeriesOverviewChanged.emit()
        self._selected_season_name = ""

        item = self._series_model.item(index)
        if not item:
            return

        self._selected_series_name = item.text()
        series_content = self._cached_library_data.get(self._selected_series_name, {})
        series_metadata = series_content.get("metadata", {})
        self._selected_series_overview = series_metadata.get("overview", "")
        self.selectedSeriesOverviewChanged.emit()
        seasons = series_content.get("seasons", {})

        # Use natural sort key if available from database module
        try:
            sorted_season_names = sorted(seasons.keys(), key=db.natural_sort_key)
        except AttributeError:
            sorted_season_names = sorted(seasons.keys())

        for season_name in sorted_season_names:
            season_data = seasons.get(season_name, {})
            metadata_dict = season_data.get("metadata", {})
            poster_path = metadata_dict.get("poster_path", "")

            season_item = QStandardItem(season_name)
            season_item.setData(season_name, Qt.ItemDataRole.DisplayRole)
            season_item.setData(poster_path, self.poster_role)
            self._season_model.appendRow(season_item)

        self.seasonModelChanged.emit()

    @Slot(int)
    def selectSeason(self, index: int) -> None:
        self._episode_model.clear()
        self._selected_season_name = ""

        item = self._season_model.item(index)
        if not item:
            return

        self._selected_season_name = item.text()
        series_content = self._cached_library_data.get(self._selected_series_name, {})
        seasons = series_content.get("seasons", {})
        season_content = seasons.get(self._selected_season_name, {})
        episodes_list = season_content.get("episodes", [])

        for episode_data in episodes_list:
            tmdb_title = episode_data.get("tmdb_name")
            tmdb_number = episode_data.get("tmdb_number")
            if tmdb_title and tmdb_number is not None:
                display_name = f"Episode {tmdb_number}: {tmdb_title}"
            elif tmdb_title:
                display_name = tmdb_title
            else:
                display_name = episode_data.get("name", "Unknown Episode")

            is_watched = bool(episode_data.get("watched", False))
            file_path = episode_data.get("path", "")
            jellyfin_identifier = episode_data.get("jellyfin_id", "")

            episode_item = QStandardItem(display_name)
            episode_item.setData(display_name, Qt.ItemDataRole.DisplayRole)
            episode_item.setData(is_watched, self.watched_role)
            episode_item.setData(file_path, self.path_role)
            episode_item.setData(jellyfin_identifier, self.jellyfin_identifier_role)

            self._episode_model.appendRow(episode_item)

        self.episodeModelChanged.emit()

    @Slot(list)
    def markEpisodesWatched(self, selected_rows: List[int]) -> None:
        """Bulk update selected episode indexes to watched status."""
        logger.info(f"Bulk marking rows as watched: {selected_rows}")
        updated_count = 0
        for row_index in selected_rows:
            item = self._episode_model.item(row_index)
            if item:
                file_path = item.data(self.path_role)
                jellyfin_identifier = item.data(self.jellyfin_identifier_role)

                # Update underlying database record without abbreviations
                if file_path:
                    db.update_episode_watched_status(file_path, True)
                    item.setData(True, self.watched_role)
                    updated_count += 1

                # Synchronize to remote Jellyfin server if available
                if jellyfin_identifier and jellyfin_client.is_configured():
                    jellyfin_client.set_watched_status(jellyfin_identifier, True)

        # Refresh cached model state
        self._refresh_cached_episode_watched_state(selected_rows, True)
        self.statusMessage = f"Marked {updated_count} episodes as watched"

    @Slot(list)
    def markEpisodesUnwatched(self, selected_rows: List[int]) -> None:
        """Bulk update selected episode indexes to unwatched status."""
        logger.info(f"Bulk marking rows as unwatched: {selected_rows}")
        updated_count = 0
        for row_index in selected_rows:
            item = self._episode_model.item(row_index)
            if item:
                file_path = item.data(self.path_role)
                jellyfin_identifier = item.data(self.jellyfin_identifier_role)

                if file_path:
                    db.update_episode_watched_status(file_path, False)
                    item.setData(False, self.watched_role)
                    updated_count += 1

                if jellyfin_identifier and jellyfin_client.is_configured():
                    jellyfin_client.set_watched_status(jellyfin_identifier, False)

        self._refresh_cached_episode_watched_state(selected_rows, False)
        self.statusMessage = f"Marked {updated_count} episodes as unwatched"

    def _refresh_cached_episode_watched_state(
        self, rows: List[int], state: bool
    ) -> None:
        """Helper to ensure in-memory cached structure stays synced with local database updates."""
        series_content = self._cached_library_data.get(self._selected_series_name, {})
        seasons = series_content.get("seasons", {})
        season_content = seasons.get(self._selected_season_name, {})
        episodes_list = season_content.get("episodes", [])

        for row_index in rows:
            if 0 <= row_index < len(episodes_list):
                if episodes_list[row_index]["watched"] != state:
                    episodes_list[row_index]["watched"] = state
                    if "metrics" in series_content:
                        series_content["metrics"]["watched_episodes"] += (
                            1 if state else -1
                        )

    @Slot(int)
    def matchMetadataForSeries(self, index: int) -> None:
        item = self._series_model.item(index)
        if item:
            series_target_name = item.text()
            self.statusMessage = f"Matching metadata for: {series_target_name}"
            logger.info(
                f"Triggered metadata match slot for series: {series_target_name}"
            )
            self.openMetadataMatchDialog.emit(series_target_name)

    @Slot(str, str, result="QVariantList")
    def searchSeriesMetadata(self, query: str, provider_name: str) -> list:
        logger.info(
            f"Searching metadata for query: '{query}' via provider: '{provider_name}'"
        )
        formatted_results = []
        if provider_name.lower() == "jellyfin":
            search_results = jellyfin_client.search_series(query)
            for result_item in search_results:
                production_year = result_item.get("ProductionYear", "")
                first_air_date = f"{production_year}-01-01" if production_year else ""
                item_identifier = str(result_item.get("Id", ""))
                provider_dictionary = result_item.get("ProviderIds", {})
                tmdb_identifier = str(provider_dictionary.get("Tmdb", ""))
                formatted_results.append(
                    {
                        "id": item_identifier,
                        "tmdb_id": tmdb_identifier,
                        "name": result_item.get("Name", ""),
                        "first_air_date": first_air_date,
                        "overview": result_item.get("Overview", ""),
                        "poster_path": "",
                        "provider": "Jellyfin",
                    }
                )
        else:
            search_results = tmdb_client.search_series_full(query)
            for result_item in search_results:
                formatted_results.append(
                    {
                        "id": str(result_item.get("id", "")),
                        "tmdb_id": str(result_item.get("id", "")),
                        "name": result_item.get("name", ""),
                        "first_air_date": result_item.get("first_air_date", ""),
                        "overview": result_item.get("overview", ""),
                        "poster_path": result_item.get("poster_path", ""),
                        "provider": "TMDB",
                    }
                )
        return formatted_results

    @Slot(str, "QVariantMap")
    def applySeriesMetadataMatch(self, series_name: str, match_data: dict) -> None:
        if not getattr(self, "_cached_library_data", None):
            return
        if series_name in self._cached_library_data:
            target_series_data = self._cached_library_data[series_name]
            metadata_dictionary = target_series_data.get("metadata", {})

            provider_type = match_data.get("provider", "TMDB")
            if provider_type == "Jellyfin":
                metadata_dictionary["jellyfin_id"] = match_data.get("id", "")
                if match_data.get("tmdb_id"):
                    metadata_dictionary["tmdb_identifier"] = match_data.get(
                        "tmdb_id", ""
                    )
            else:
                metadata_dictionary["tmdb_identifier"] = match_data.get("id", "")

            if match_data.get("name"):
                metadata_dictionary["tmdb_name"] = match_data.get("name", "")
            if match_data.get("overview"):
                metadata_dictionary["overview"] = match_data.get("overview", "")
            if match_data.get("poster_path"):
                metadata_dictionary["poster_path"] = match_data.get("poster_path", "")
            if match_data.get("first_air_date"):
                metadata_dictionary["first_air_date"] = match_data.get(
                    "first_air_date", ""
                )

            target_series_data["metadata"] = metadata_dictionary

            # Save persistence layer
            db.save_library(self._current_library_name, self._cached_library_data)
            self.statusMessage = (
                f"Successfully applied metadata match for: {series_name}"
            )
            logger.info(
                f"Updated metadata match for series '{series_name}' via provider '{provider_type}' with ID '{match_data.get('id')}'"
            )
            self._refresh_series_model()
            # If the currently selected series matches, refresh detail view models too
            if getattr(self, "_selected_series_name", "") == series_name:
                for row_index in range(self._series_model.rowCount()):
                    if self._series_model.item(row_index).text() == series_name:
                        self.selectSeries(row_index)
                        break

    @Slot(int, str, result="QVariantList")
    def getRenamePreviews(self, series_index: int, file_template: str) -> list:
        item = self._series_model.item(series_index)
        if not item:
            return []
        series_target_name = item.text()
        series_content = self._cached_library_data.get(series_target_name, {})
        from .renamer import get_rename_preview

        return get_rename_preview(series_content, file_template)

    @Slot(list, result="QVariantList")
    def applyRenames(self, preview_items: list) -> list:
        from .renamer import perform_rename

        def on_rename_success(old_path_string: str, new_path_string: str) -> None:
            db.update_episode_path(old_path_string, new_path_string)
            # Update cached library in memory by removing old references and adding new ones/updating existing
            for series_dictionary in self._cached_library_data.values():
                for season_dictionary in series_dictionary.get("seasons", {}).values():
                    episodes_list = season_dictionary.get("episodes", [])
                    for episode_dictionary in episodes_list:
                        if episode_dictionary.get("path") == old_path_string:
                            episode_dictionary["path"] = new_path_string
                            new_path_object = Path(new_path_string)
                            episode_dictionary["name"] = new_path_object.name
                            break

        rename_results = perform_rename(preview_items, on_rename_success)

        # Resave persistent database layer to ensure complete sync
        if getattr(self, "_current_library_name", ""):
            db.save_library(self._current_library_name, self._cached_library_data)

        # Refresh currently selected series detail models if active
        if getattr(self, "_selected_series_name", ""):
            for row_index in range(self._series_model.rowCount()):
                if (
                    self._series_model.item(row_index).text()
                    == self._selected_series_name
                ):
                    self.selectSeries(row_index)
                    break

        return rename_results

    @Slot(int)
    def playEpisode(self, index: int) -> None:
        item = self._episode_model.item(index)
        if item:
            target_path = item.data(self.path_role)
            if target_path:
                self.statusMessage = f"Playing media: {item.text()}"
                logger.info(
                    f"Requesting media playback sink for target path: {target_path}"
                )
                self.playbackRequested.emit(target_path)

    @Slot()
    def scanForNewFiles(self) -> None:
        """Searches root directories for new files and retrieves metadata only for new files found."""
        if not getattr(self, "_current_library_name", ""):
            self.statusMessage = "Select a library first"
            return

        root_directories = config.libraries.get(self._current_library_name, [])
        self.statusMessage = (
            f"Scanning for new files in '{self._current_library_name}'..."
        )
        logger.info(
            f"Triggering ScanWorker with force_refresh=False for library: {self._current_library_name}"
        )

        self._scan_worker = ScanWorker(
            root_directories=root_directories,
            existing_library=self._cached_library_data,
            force_refresh=False,
            cleanup=False,
        )
        self._scan_worker.finished.connect(self._on_scan_worker_finished)
        self._scan_worker.error.connect(self._on_worker_error)
        self._scan_worker.start()

    @Slot()
    def refreshEntireLibrary(self) -> None:
        """Searches all files in library folders and updates/fetches metadata for all of them."""
        if not getattr(self, "_current_library_name", ""):
            self.statusMessage = "Select a library first"
            return

        root_directories = config.libraries.get(self._current_library_name, [])
        self.statusMessage = (
            f"Full refresh triggered for '{self._current_library_name}'..."
        )
        logger.info(
            f"Triggering ScanWorker with force_refresh=True for library: {self._current_library_name}"
        )

        self._scan_worker = ScanWorker(
            root_directories=root_directories,
            existing_library=self._cached_library_data,
            force_refresh=True,
            cleanup=False,
        )
        self._scan_worker.finished.connect(self._on_scan_worker_finished)
        self._scan_worker.error.connect(self._on_worker_error)
        self._scan_worker.start()

    @Slot()
    def cleanupLibrary(self) -> None:
        """Removes series and episodes that are no longer present in the library folders."""
        if not getattr(self, "_current_library_name", ""):
            self.statusMessage = "Select a library first"
            return

        root_directories = config.libraries.get(self._current_library_name, [])
        self.statusMessage = (
            f"Cleaning up missing files in '{self._current_library_name}'..."
        )
        logger.info(
            f"Executing database library cleanup for: {self._current_library_name}"
        )

        try:
            stats = db.cleanup_library(self._current_library_name, root_directories)
            self.selectLibrary(self._current_library_name)
            self.statusMessage = (
                f"Cleanup finished: removed {stats.get('series', 0)} series, "
                f"{stats.get('seasons', 0)} seasons, {stats.get('episodes', 0)} episodes"
            )
        except Exception as exc:
            self.statusMessage = f"Cleanup error: {exc}"
            logger.error(f"Library cleanup failed: {exc}")

    @Slot()
    def pullWatchHistoryFromJellyfin(self) -> None:
        if not jellyfin_client.is_configured():
            self.statusMessage = "Jellyfin is not configured"
            return
        self.statusMessage = "Pulling watch history from Jellyfin..."
        logger.info("Triggering JellyfinPullWorker")
        self._jellyfin_pull_worker = JellyfinPullWorker()
        self._jellyfin_pull_worker.finished.connect(self._on_jellyfin_pull_finished)
        self._jellyfin_pull_worker.error.connect(self._on_worker_error)
        self._jellyfin_pull_worker.start()

    @Slot()
    def pushWatchHistoryToJellyfin(self) -> None:
        if not jellyfin_client.is_configured():
            self.statusMessage = "Jellyfin is not configured"
            return
        self.statusMessage = "Pushing watch history to Jellyfin..."
        logger.info("Triggering JellyfinPushWorker")
        self._jellyfin_push_worker = JellyfinPushWorker()
        self._jellyfin_push_worker.finished.connect(self._on_jellyfin_push_finished)
        self._jellyfin_push_worker.error.connect(self._on_worker_error)
        self._jellyfin_push_worker.start()

    def _on_jellyfin_pull_finished(self, updated_count: int) -> None:
        if getattr(self, "_current_library_name", ""):
            self.selectLibrary(self._current_library_name)
        self.statusMessage = f"Pulled watch history: updated {updated_count} episodes"

    def _on_jellyfin_push_finished(self, pushed_count: int) -> None:
        self.statusMessage = f"Pushed watch history: synced {pushed_count} episodes"

    def _on_scan_worker_finished(self, updated_library: dict) -> None:
        if getattr(self, "_current_library_name", ""):
            db.save_library(self._current_library_name, updated_library)
            self._cached_library_data = updated_library
            self._cache_series_metrics()
            self.selectLibrary(self._current_library_name)
            self.statusMessage = "New files scanned successfully"

    def _on_worker_error(self, error_text: str) -> None:
        self.statusMessage = f"Scan error: {error_text}"
        logger.error(f"Background scan worker failed: {error_text}")

    @Slot(str)
    def addNewLibrary(self, library_name: str) -> None:
        library_name = library_name.strip()
        if library_name and library_name not in config.libraries:
            config.add_library(library_name)
            self._available_libraries = list(config.libraries.keys())
            self.availableLibrariesChanged.emit()
            self.statusMessage = f"Added library: {library_name}"
            if not getattr(self, "_current_library_name", ""):
                self.selectLibrary(library_name)

    @Slot(str)
    def removeSelectedLibrary(self, library_name: str) -> None:
        if library_name in config.libraries:
            config.remove_library(library_name)
            self._available_libraries = list(config.libraries.keys())
            self.availableLibrariesChanged.emit()
            self.statusMessage = f"Removed library: {library_name}"
            if getattr(self, "_current_library_name", "") == library_name:
                if self._available_libraries:
                    self.selectLibrary(self._available_libraries[0])
                else:
                    self._current_library_name = ""
                    self._cached_library_data = {}
                    self._series_model.clear()
                    self._season_model.clear()
                    self._episode_model.clear()

    @Slot(str, str)
    def addRootDirectoryToLibrary(self, library_name: str, directory_path: str) -> None:
        directory_path = directory_path.strip()
        if library_name in config.libraries and directory_path:
            config.add_root_dir(library_name, directory_path)
            self.statusMessage = f"Added path to {library_name}"
            self.availableLibrariesChanged.emit()

    @Slot(str, str)
    def removeRootDirectoryFromLibrary(
        self, library_name: str, directory_path: str
    ) -> None:
        if library_name in config.libraries:
            config.remove_root_dir(library_name, directory_path)
            self.statusMessage = f"Removed path from {library_name}"
            self.availableLibrariesChanged.emit()

    @Slot(str, result=list)
    def getRootDirectoriesForLibrary(self, library_name: str) -> List[str]:
        return config.libraries.get(library_name, [])


class ScanWorker(QThread):
    """Scans a single library directory using TMDB for metadata."""

    finished = Signal(dict)
    partial_result = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        root_directories: List[str],
        existing_library: dict,
        force_refresh: bool = False,
        cleanup: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.root_directories = root_directories
        self.existing_library = existing_library
        self.force_refresh = force_refresh
        self.cleanup = cleanup

    def run(self) -> None:
        try:
            # Fetch Jellyfin correlation data if configured
            jellyfin_data = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            library = scan_directories(
                self.root_directories,
                existing_library=self.existing_library,
                jellyfin_data=jellyfin_data,
                callback=self.partial_result.emit,
                force_refresh=self.force_refresh,
                cleanup=self.cleanup,
            )
            self.finished.emit(library)
        except Exception as exc:
            self.error.emit(str(exc))


class SyncAllWorker(QThread):
    """Rescans all libraries using TMDB for metadata (manual action only)."""

    finished = Signal()
    progress = Signal(str)
    error = Signal(str)

    def run(self) -> None:
        try:
            jellyfin_data = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            for library_name, root_directories in config.libraries.items():
                self.progress.emit(f"Scanning library '{library_name}'...")
                existing_library_data = db.load_library(library_name)
                library = scan_directories(
                    root_directories,
                    existing_library=existing_library_data,
                    jellyfin_data=jellyfin_data,
                )
                db.save_library(library_name, library)
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class CleanupWorker(QThread):
    """Removes missing series/seasons/episodes from the database."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        library_name: str,
        root_directories: List[str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.library_name = library_name
        self.root_directories = root_directories

    def run(self) -> None:
        try:
            results = db.cleanup_library(self.library_name, self.root_directories)
            self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class JellyfinPullWorker(QThread):
    """Pulls watch history from Jellyfin and syncs it to the local DB."""

    finished = Signal(int)  # number of episodes updated
    error = Signal(str)

    def run(self) -> None:
        try:
            watched_identifiers, watched_paths, watched_names = (
                jellyfin_client.fetch_watched_episodes()
            )
            updated_count = db.sync_watched_from_jellyfin_data(
                watched_identifiers, watched_paths, watched_names
            )
            self.finished.emit(updated_count)
        except Exception as exc:
            self.error.emit(str(exc))


class JellyfinPushWorker(QThread):
    """Pushes all local watched state to Jellyfin."""

    finished = Signal(int)  # number of episodes pushed
    error = Signal(str)

    def run(self) -> None:
        try:
            episodes_list = db.get_all_episodes_with_jellyfin_id()
            pushed_count = 0
            for episode_record in episodes_list:
                jellyfin_client.set_watched_status(
                    episode_record["jellyfin_id"], bool(episode_record["watched"])
                )
                pushed_count += 1
            self.finished.emit(pushed_count)
        except Exception as exc:
            self.error.emit(str(exc))
