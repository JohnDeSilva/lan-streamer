import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QDialog,
    QLineEdit,
    QMessageBox,
    QFileDialog,
    QFrame,
    QSizePolicy,
    QProgressBar,
)
from PySide6.QtCore import (
    Qt,
    Signal,
    Slot,
    QObject,
    QSize,
    QFileSystemWatcher,
    QTimer,
)

from PySide6.QtGui import QPixmap, QIcon, QFont, QColor

from .config import config
from . import db
from .jellyfin import jellyfin_client
from .tmdb import tmdb_client
from .backend import (
    ScanWorker,
    CleanupWorker,
    JellyfinPullWorker,
    JellyfinPushWorker,
    ScanAllLibrariesWorker,
    CleanupAllLibrariesWorker,
)

logger = logging.getLogger(__name__)


def get_application_stylesheet() -> str:
    """Returns a premium, rich dark mode stylesheet implementing modern aesthetic standards."""
    return """
    QWidget {
        background-color: #191919;
        color: #FFFFFF;
        font-family: 'Inter', 'Roboto', sans-serif;
        font-size: 14px;
    }
    QPushButton {
        background-color: #2a2a2a;
        border: 1px solid #444444;
        border-radius: 6px;
        padding: 6px 12px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #3a3a3a;
        border-color: #2a82da;
        color: #2a82da;
    }
    QPushButton:pressed {
        background-color: #202020;
    }
    QPushButton:disabled {
        background-color: #151515;
        color: #666666;
        border-color: #222222;
    }
    QPushButton#accentButton {
        background-color: #2a82da;
        color: #ffffff;
        border: none;
    }
    QPushButton#accentButton:hover {
        background-color: #3592ea;
    }
    QLineEdit, QComboBox {
        background-color: #222222;
        border: 1px solid #444444;
        border-radius: 6px;
        padding: 5px 10px;
        color: #ffffff;
    }
    QLineEdit:focus, QComboBox:focus {
        border-color: #2a82da;
    }
    QListWidget, QTableWidget {
        background-color: #1e1e1e;
        border: 1px solid #333333;
        border-radius: 8px;
    }
    QListWidget::item:hover, QTableWidget::item:hover {
        background-color: #282828;
        border-radius: 4px;
    }
    QListWidget::item:selected, QTableWidget::item:selected {
        background-color: #2a82da;
        color: #ffffff;
        border-radius: 4px;
    }
    QHeaderView::section {
        background-color: #222222;
        color: #aaaaaa;
        padding: 5px;
        border: none;
        border-bottom: 1px solid #444444;
        font-weight: bold;
    }
    QTabWidget::pane {
        border: 1px solid #333333;
        border-radius: 6px;
        background-color: #1e1e1e;
    }
    QTabBar::tab {
        background-color: #222222;
        color: #888888;
        padding: 8px 16px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #1e1e1e;
        color: #ffffff;
        border-bottom: 2px solid #2a82da;
        font-weight: bold;
    }
    QTabBar::tab:hover {
        background-color: #2a2a2a;
        color: #ffffff;
    }
    QScrollBar:vertical {
        border: none;
        background-color: #191919;
        width: 10px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background-color: #444444;
        border-radius: 5px;
        min-height: 20px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: #555555;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    """


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
    global_progress_updated = Signal(str, int, int)

    file_system_watcher: QFileSystemWatcher
    debounce_timer: QTimer

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.current_library_name: str = ""
        self.cached_library_data: Dict[str, Any] = {}
        self.selected_series_name: str = ""
        self.sort_mode: str = config.sort_mode
        self.filter_out_watched: bool = config.filter_out_watched
        self.scan_worker_instance: Optional[ScanWorker] = None
        self.cleanup_worker_instance: Optional[CleanupWorker] = None
        self.pull_worker_instance: Optional[JellyfinPullWorker] = None
        self.push_worker_instance: Optional[JellyfinPushWorker] = None
        self.scan_all_worker_instance: Optional[ScanAllLibrariesWorker] = None
        self.cleanup_all_worker_instance: Optional[CleanupAllLibrariesWorker] = None

        self.debounce_timer = QTimer(self)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(2000)
        self.debounce_timer.timeout.connect(self._on_debounce_timeout)

        self.file_system_watcher = QFileSystemWatcher(self)
        self.file_system_watcher.directoryChanged.connect(self._on_directory_changed)

    def select_library(self, library_name: str) -> None:
        logger.info(f"Controller loading library: {library_name}")
        self.current_library_name = library_name
        self.status_changed.emit(f"Loading library: {library_name}...")

        library_config = config.libraries.get(library_name, {})

        existing_directories = self.file_system_watcher.directories()
        if existing_directories:
            self.file_system_watcher.removePaths(existing_directories)

        root_directories: List[str] = library_config.get("paths", [])
        for directory_path in root_directories:
            if Path(directory_path).is_dir():
                self.file_system_watcher.addPath(directory_path)

        if library_config.get("type", "tv") == "movie":
            self.cached_library_data = db.load_movie_library(library_name)
        else:
            self.cached_library_data = db.load_library(library_name)
        self._cache_series_metrics()
        self.selected_series_name = ""

        self.status_changed.emit("Library loaded successfully.")
        self.library_loaded.emit()

    def _on_directory_changed(self, path_string: str) -> None:
        logger.info(
            f"Directory modification detected on '{path_string}'. Automated background scanning disabled."
        )

    def _on_debounce_timeout(self) -> None:
        pass

    def _cache_series_metrics(self) -> None:
        for series_name, series_data in self.cached_library_data.items():
            if "seasons" not in series_data:
                is_watched = bool(series_data.get("watched"))
                series_data["metrics"] = {
                    "total_episodes": 1,
                    "watched_episodes": 1 if is_watched else 0,
                    "max_date_added": series_data.get("date_added") or 0,
                    "max_air_date": str(series_data.get("year") or ""),
                }
            else:
                total_episodes: int = 0
                watched_episodes: int = 0
                max_date_added: int = 0
                max_air_date: str = ""

                for season_data in series_data.get("seasons", {}).values():
                    for episode_record in season_data.get("episodes", []):
                        total_episodes += 1
                        if episode_record.get("watched"):
                            watched_episodes += 1
                        added_timestamp: int = episode_record.get("date_added") or 0
                        if added_timestamp > max_date_added:
                            max_date_added = added_timestamp
                        air_date_string: str = episode_record.get("air_date") or ""
                        if air_date_string > max_air_date:
                            max_air_date = air_date_string

                series_data["metrics"] = {
                    "total_episodes": total_episodes,
                    "watched_episodes": watched_episodes,
                    "max_date_added": max_date_added,
                    "max_air_date": max_air_date,
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
            self.sort_mode = mode
            config.sort_mode = mode
            config.save()
            self.library_loaded.emit()

    def set_filter_out_watched(self, enabled: bool) -> None:
        if self.filter_out_watched != enabled:
            self.filter_out_watched = enabled
            config.filter_out_watched = enabled
            config.save()
            self.library_loaded.emit()

    def mark_episode_watched(self, absolute_path: str, watched: bool) -> None:
        logger.info(
            f"Controller marking episode watched={watched} for path: {absolute_path}"
        )
        db.update_episode_watched_status(absolute_path, watched)

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

        if self.selected_series_name:
            target_record = self.cached_library_data.get(self.selected_series_name, {})
            if "seasons" not in target_record:
                self.movie_selected.emit(self.selected_series_name)
            else:
                self.series_selected.emit(self.selected_series_name)
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

        library_config = config.libraries.get(self.current_library_name, {})
        root_directories: List[str] = library_config.get("paths", [])
        library_type: str = library_config.get("type", "tv")
        self.status_changed.emit(
            f"Scanning library '{self.current_library_name}' (force={force_refresh})..."
        )

        self.scan_worker_instance = ScanWorker(
            root_directories=root_directories,
            library_type=library_type,
            existing_library=self.cached_library_data,
            force_refresh=force_refresh,
            cleanup=False,
        )
        self.scan_worker_instance.finished.connect(self._on_scan_finished)
        self.scan_worker_instance.partial_result.connect(self._on_scan_partial)
        self.scan_worker_instance.error.connect(self._on_worker_error)
        self.scan_worker_instance.start()

    def _on_scan_partial(self, partial_library: Dict[str, Any]) -> None:
        if self.current_library_name:
            # We create a shallow copy/update of cached data to not lose references while UI re-renders
            self.cached_library_data = partial_library
            self._cache_series_metrics()
            self.library_loaded.emit()

    def _on_scan_finished(self, updated_library: Dict[str, Any]) -> None:
        if self.current_library_name:
            library_config = config.libraries.get(self.current_library_name, {})
            if library_config.get("type", "tv") == "movie":
                db.save_movie_library(self.current_library_name, updated_library)
            else:
                db.save_library(self.current_library_name, updated_library)
            self.cached_library_data = updated_library
            self._cache_series_metrics()
            self.status_changed.emit("Library scan completed successfully.")
            self.library_loaded.emit()
            if self.selected_series_name:
                if library_config.get("type", "tv") == "movie":
                    self.movie_selected.emit(self.selected_series_name)
                else:
                    self.series_selected.emit(self.selected_series_name)

    def trigger_cleanup(self) -> None:
        if not self.current_library_name:
            self.status_changed.emit("Select a library first.")
            return

        library_config = config.libraries.get(self.current_library_name, {})
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
        self.select_library(self.current_library_name)
        series_removed: int = statistics.get("series", 0)
        seasons_removed: int = statistics.get("seasons", 0)
        episodes_removed: int = statistics.get("episodes", 0)
        self.status_changed.emit(
            f"Cleanup finished: removed {series_removed} series, {seasons_removed} seasons, {episodes_removed} episodes."
        )

    def trigger_jellyfin_pull(self) -> None:
        if not jellyfin_client.is_configured():
            self.status_changed.emit("Jellyfin is not configured.")
            return

        self.status_changed.emit("Pulling watch history from Jellyfin...")
        self.pull_worker_instance = JellyfinPullWorker()
        self.pull_worker_instance.finished.connect(self._on_pull_finished)
        self.pull_worker_instance.error.connect(self._on_worker_error)
        self.pull_worker_instance.start()

    def _on_pull_finished(self, updated_count: int) -> None:
        if self.current_library_name:
            self.select_library(self.current_library_name)
        self.status_changed.emit(
            f"Watch history pulled successfully: updated {updated_count} episodes."
        )

    def trigger_jellyfin_push(self) -> None:
        if not jellyfin_client.is_configured():
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

    def trigger_scan_all(self, force_refresh: bool = False) -> None:
        if (
            self.scan_all_worker_instance is not None
            and self.scan_all_worker_instance.isRunning()
        ):
            logger.info("ScanAllLibrariesWorker is already running.")
            return

        self.status_changed.emit("Scanning all libraries...")
        self.scan_all_worker_instance = ScanAllLibrariesWorker(
            force_refresh=force_refresh
        )
        self.scan_all_worker_instance.library_progress.connect(
            self.global_progress_updated.emit
        )
        self.scan_all_worker_instance.finished.connect(self._on_scan_all_finished)
        self.scan_all_worker_instance.error.connect(self._on_worker_error)
        self.scan_all_worker_instance.start()

    def _on_scan_all_finished(self) -> None:
        self.status_changed.emit("Global multi-library scan completed successfully.")
        if self.current_library_name:
            self.select_library(self.current_library_name)

    def trigger_cleanup_all(self) -> None:
        if (
            self.cleanup_all_worker_instance is not None
            and self.cleanup_all_worker_instance.isRunning()
        ):
            logger.info("CleanupAllLibrariesWorker is already running.")
            return

        self.status_changed.emit("Cleaning up all libraries...")
        self.cleanup_all_worker_instance = CleanupAllLibrariesWorker()
        self.cleanup_all_worker_instance.library_progress.connect(
            self.global_progress_updated.emit
        )
        self.cleanup_all_worker_instance.finished.connect(self._on_cleanup_all_finished)
        self.cleanup_all_worker_instance.error.connect(self._on_worker_error)
        self.cleanup_all_worker_instance.start()

    def _on_cleanup_all_finished(self) -> None:
        self.status_changed.emit("Global multi-library cleanup completed successfully.")
        if self.current_library_name:
            self.select_library(self.current_library_name)

    def _on_worker_error(self, error_message: str) -> None:
        self.status_changed.emit(f"Worker Error: {error_message}")
        logger.error(f"Background execution fault: {error_message}")

    def apply_metadata_match(
        self, series_name: str, match_dictionary: Dict[str, Any]
    ) -> None:
        logger.info(
            f"Controller applying metadata match for '{series_name}': {match_dictionary}"
        )
        if series_name not in self.cached_library_data:
            return

        library_config = config.libraries.get(self.current_library_name, {})
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

        if match_dictionary.get("poster_path"):
            raw_poster_path: str = match_dictionary.get("poster_path", "")
            tmdb_identifier_value: str = target_dict.get("tmdb_identifier", "")
            if raw_poster_path and tmdb_identifier_value:
                prefix = "tmdb_movie_" if is_movie else "tmdb_series_"
                cached_image_path: Optional[str] = tmdb_client.download_image(
                    raw_poster_path, f"{prefix}{tmdb_identifier_value}"
                )
                target_dict["poster_path"] = cached_image_path or raw_poster_path
            else:
                target_dict["poster_path"] = raw_poster_path

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

        if self.current_library_name:
            if is_movie:
                db.save_movie_library(
                    self.current_library_name, self.cached_library_data
                )
            else:
                db.save_library(self.current_library_name, self.cached_library_data)

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

        library_config = config.libraries.get(self.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        target_dict: Dict[str, Any] = (
            series_record if is_movie else series_record.get("metadata", {})
        )

        target_identifier: str = match_dictionary.get("id", "")
        target_dict["jellyfin_id"] = target_identifier

        if self.current_library_name:
            if is_movie:
                db.save_movie_library(
                    self.current_library_name, self.cached_library_data
                )
            else:
                db.save_library(self.current_library_name, self.cached_library_data)

        self.status_changed.emit(
            f"Successfully linked Jellyfin watch history for '{series_name}'."
        )
        self.library_loaded.emit()
        if self.selected_series_name == series_name:
            if is_movie:
                self.movie_selected.emit(series_name)
            else:
                self.series_selected.emit(series_name)

    def apply_rename_batch(self, preview_results: List[Dict[str, Any]]) -> None:
        logger.info(
            f"Controller executing batch renames for {len(preview_results)} files."
        )
        from .renamer import perform_rename

        def on_rename_success(old_path_string: str, new_path_string: str) -> None:
            db.update_episode_path(old_path_string, new_path_string)
            for series_dictionary in self.cached_library_data.values():
                for season_dictionary in series_dictionary.get("seasons", {}).values():
                    for episode_dictionary in season_dictionary.get("episodes", []):
                        if episode_dictionary.get("path") == old_path_string:
                            episode_dictionary["path"] = new_path_string
                            path_instance = Path(new_path_string)
                            episode_dictionary["name"] = path_instance.name
                            break

        perform_rename(preview_results, on_rename_success)

        if self.current_library_name:
            db.save_library(self.current_library_name, self.cached_library_data)

        self.status_changed.emit("Batch renaming completed successfully.")
        self.library_loaded.emit()
        if self.selected_series_name:
            self.series_selected.emit(self.selected_series_name)


class LibraryGridView(QWidget):
    """
    Responsive Grid View displaying series items using custom layout sizing.
    Conforms strictly to zero-abbreviation variable naming and strict typing requirements.
    """

    def __init__(
        self, controller_instance: Controller, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.controller: Controller = controller_instance
        self.series_list_widget: QListWidget = QListWidget()
        self.library_selector: QComboBox = QComboBox()
        self.sort_selector: QComboBox = QComboBox()
        self.filter_watched_checkbox: QCheckBox = QCheckBox("Hide Watched")
        self.cached_icons: Dict[str, QIcon] = {}

        self._setup_ui()
        self._wire_signals()

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Top Filters Row
        top_toolbar_layout: QHBoxLayout = QHBoxLayout()
        top_toolbar_layout.setSpacing(10)

        top_toolbar_layout.addWidget(QLabel("Library:"))
        self.library_selector.setMinimumWidth(150)
        top_toolbar_layout.addWidget(self.library_selector)

        top_toolbar_layout.addSpacing(15)
        top_toolbar_layout.addWidget(QLabel("Sort By:"))
        self.sort_selector.addItems(
            ["Alphabetical", "Recently Added", "Recently Aired"]
        )
        self.sort_selector.setCurrentText(self.controller.sort_mode)
        top_toolbar_layout.addWidget(self.sort_selector)

        top_toolbar_layout.addSpacing(15)
        self.filter_watched_checkbox.setChecked(self.controller.filter_out_watched)
        top_toolbar_layout.addWidget(self.filter_watched_checkbox)

        top_toolbar_layout.addStretch()

        settings_button: QPushButton = QPushButton("Settings...")
        settings_button.setObjectName("openSettingsButton")
        settings_button.clicked.connect(self.open_settings_dialog)
        top_toolbar_layout.addWidget(settings_button)

        main_layout.addLayout(top_toolbar_layout)

        # Bottom Actions Row
        actions_toolbar_layout: QHBoxLayout = QHBoxLayout()
        actions_toolbar_layout.setSpacing(10)

        scan_button: QPushButton = QPushButton("Scan New Files")
        scan_button.clicked.connect(lambda: self.controller.trigger_scan(False))
        actions_toolbar_layout.addWidget(scan_button)

        refresh_all_button: QPushButton = QPushButton("Refresh Metadata")
        refresh_all_button.clicked.connect(lambda: self.controller.trigger_scan(True))
        actions_toolbar_layout.addWidget(refresh_all_button)

        pull_history_button: QPushButton = QPushButton("Pull Watch History")
        pull_history_button.clicked.connect(self.controller.trigger_jellyfin_pull)
        actions_toolbar_layout.addWidget(pull_history_button)

        push_history_button: QPushButton = QPushButton("Push Watch History")
        push_history_button.clicked.connect(self.controller.trigger_jellyfin_push)
        actions_toolbar_layout.addWidget(push_history_button)

        cleanup_button: QPushButton = QPushButton("Cleanup")
        cleanup_button.clicked.connect(self.controller.trigger_cleanup)
        actions_toolbar_layout.addWidget(cleanup_button)

        actions_toolbar_layout.addStretch()
        main_layout.addLayout(actions_toolbar_layout)

        # Series Responsive List/Grid Widget
        self.series_list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.series_list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.series_list_widget.setSpacing(15)
        self.series_list_widget.setIconSize(QSize(160, 220))
        self.series_list_widget.setGridSize(QSize(190, 280))
        self.series_list_widget.setMovement(QListWidget.Movement.Static)

        main_layout.addWidget(self.series_list_widget)

    def _wire_signals(self) -> None:
        self.controller.library_loaded.connect(self.populate_grid)
        self.library_selector.currentTextChanged.connect(self.on_library_changed)
        self.sort_selector.currentTextChanged.connect(self.controller.set_sort_mode)
        self.filter_watched_checkbox.toggled.connect(
            self.controller.set_filter_out_watched
        )
        self.series_list_widget.itemClicked.connect(self.on_item_clicked)

    def populate_libraries(self, library_names: List[str]) -> None:
        self.library_selector.blockSignals(True)
        self.library_selector.clear()
        self.library_selector.addItems(library_names)
        if (
            self.controller.current_library_name
            and self.controller.current_library_name in library_names
        ):
            self.library_selector.setCurrentText(self.controller.current_library_name)
            self.controller.select_library(self.controller.current_library_name)
        elif library_names:
            self.controller.select_library(library_names[0])
            self.library_selector.setCurrentText(library_names[0])
        self.library_selector.blockSignals(False)

    @Slot()
    def open_settings_dialog(self) -> None:
        dialog_instance = SettingsDialog(self.controller, self)
        dialog_instance.exec()
        self.populate_libraries(sorted(config.libraries.keys()))

    @Slot(str)
    def on_library_changed(self, library_name: str) -> None:
        if library_name:
            self.controller.select_library(library_name)

    @Slot()
    def populate_grid(self) -> None:
        # Build list of displayable series structured records
        series_entries: List[Dict[str, Any]] = []
        for series_name, series_data in self.controller.cached_library_data.items():
            metrics_dictionary: Dict[str, Any] = series_data.get("metrics", {})
            is_movie: bool = "seasons" not in series_data
            metadata_dictionary: Dict[str, Any] = (
                series_data if is_movie else series_data.get("metadata", {})
            )

            total_episodes: int = metrics_dictionary.get("total_episodes", 0)
            watched_episodes: int = metrics_dictionary.get("watched_episodes", 0)
            max_date_added: int = metrics_dictionary.get("max_date_added", 0)
            max_air_date: str = metrics_dictionary.get("max_air_date", "")

            is_fully_watched: bool = (
                total_episodes > 0 and watched_episodes == total_episodes
            )
            if self.controller.filter_out_watched and is_fully_watched:
                continue

            first_air_date: str = (
                str(metadata_dictionary.get("year", ""))
                if is_movie
                else metadata_dictionary.get("first_air_date", "")
            )
            effective_air_date: str = max(max_air_date, first_air_date)
            poster_path_string: str = metadata_dictionary.get("poster_path", "")

            series_entries.append(
                {
                    "name": series_name,
                    "poster_path": poster_path_string,
                    "date_added": max_date_added,
                    "effective_air_date": effective_air_date,
                    "watched_count": watched_episodes,
                    "total_count": total_episodes,
                    "is_movie": is_movie,
                }
            )

        # Apply sorting logic
        sort_mode_value: str = self.controller.sort_mode
        if sort_mode_value == "Recently Added":
            series_entries.sort(key=lambda entry: entry["date_added"], reverse=True)
        elif sort_mode_value == "Recently Aired":
            series_entries.sort(
                key=lambda entry: entry["effective_air_date"], reverse=True
            )
        else:
            series_entries.sort(key=lambda entry: entry["name"].lower())

        current_item_count: int = self.series_list_widget.count()
        target_item_count: int = len(series_entries)
        poster_role: int = int(Qt.ItemDataRole.UserRole) + 1

        # Render items into the responsive icon grid via delta in-place synchronization
        for row_index, entry_record in enumerate(series_entries):
            series_title: str = entry_record["name"]
            watched_count: int = entry_record["watched_count"]
            total_count: int = entry_record["total_count"]
            is_movie: bool = entry_record["is_movie"]
            poster_path_value: str = entry_record["poster_path"]

            if is_movie:
                status_string: str = "Watched" if watched_count > 0 else "Unwatched"
                display_label: str = f"{series_title}\n({status_string})"
            else:
                display_label: str = f"{series_title}\n({watched_count}/{total_count})"

            list_item: Optional[QListWidgetItem] = None
            if row_index < current_item_count:
                list_item = self.series_list_widget.item(row_index)

            if list_item is not None:
                if list_item.text() != display_label:
                    list_item.setText(display_label)
                if list_item.data(Qt.ItemDataRole.UserRole) != series_title:
                    list_item.setData(Qt.ItemDataRole.UserRole, series_title)
                    list_item.setToolTip(series_title)

                stored_poster: Any = list_item.data(poster_role)
                if stored_poster != poster_path_value:
                    list_item.setData(poster_role, poster_path_value)
                    self._assign_item_icon(list_item, poster_path_value)
            else:
                new_item: QListWidgetItem = QListWidgetItem(display_label)
                new_item.setData(Qt.ItemDataRole.UserRole, series_title)
                new_item.setData(poster_role, poster_path_value)
                new_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                new_item.setToolTip(series_title)
                self._assign_item_icon(new_item, poster_path_value)
                self.series_list_widget.addItem(new_item)

        while self.series_list_widget.count() > target_item_count:
            last_row_index: int = self.series_list_widget.count() - 1
            self.series_list_widget.takeItem(last_row_index)

    def _assign_item_icon(
        self, item_target: QListWidgetItem, poster_path_value: str
    ) -> None:
        if poster_path_value in self.cached_icons:
            item_target.setIcon(self.cached_icons[poster_path_value])
            return

        icon_assigned: bool = False
        if poster_path_value:
            poster_path_object = Path(poster_path_value)
            if poster_path_object.is_file():
                pixmap_instance = QPixmap(str(poster_path_object))
                if not pixmap_instance.isNull():
                    scaled_pixmap = pixmap_instance.scaled(
                        160,
                        220,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    loaded_icon = QIcon(scaled_pixmap)
                    self.cached_icons[poster_path_value] = loaded_icon
                    item_target.setIcon(loaded_icon)
                    icon_assigned = True

        if not icon_assigned:
            if "" not in self.cached_icons:
                fallback_pixmap = QPixmap(160, 220)
                fallback_pixmap.fill(QColor(40, 40, 40))
                self.cached_icons[""] = QIcon(fallback_pixmap)
            item_target.setIcon(self.cached_icons[""])

    @Slot(QListWidgetItem)
    def on_item_clicked(self, item_target: QListWidgetItem) -> None:
        title: str = item_target.data(Qt.ItemDataRole.UserRole)
        if title:
            library_config = config.libraries.get(
                self.controller.current_library_name, {}
            )
            if library_config.get("type") == "movie":
                self.controller.select_movie(title)
            else:
                self.controller.select_series(title)


class SeriesDetailView(QWidget):
    """
    Presents exhaustive series structure tabs, season tables, and direct execution actions.
    Enforces strict typing and zero-abbreviation naming standard.
    """

    back_requested = Signal()

    def __init__(
        self, controller_instance: Controller, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.controller: Controller = controller_instance
        self.title_label: QLabel = QLabel()
        self.jellyfin_status_label: QLabel = QLabel()
        self.overview_label: QLabel = QLabel()
        self.poster_label: QLabel = QLabel()
        self.seasons_tab_widget: QTabWidget = QTabWidget()
        self.match_jellyfin_button: QPushButton = QPushButton(
            "Match Jellyfin Watch History..."
        )

        self._setup_ui()
        self.controller.series_selected.connect(self.populate_series_details)

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Header Panel
        header_layout: QHBoxLayout = QHBoxLayout()
        header_layout.setSpacing(20)

        back_button: QPushButton = QPushButton("← Back to Library")
        back_button.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(back_button, 0, Qt.AlignmentFlag.AlignTop)

        self.poster_label.setFixedSize(180, 260)
        self.poster_label.setStyleSheet(
            "background-color: #222222; border: 1px solid #444444; border-radius: 6px;"
        )
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.poster_label, 0, Qt.AlignmentFlag.AlignTop)

        info_layout: QVBoxLayout = QVBoxLayout()
        info_layout.setSpacing(10)

        self.title_label.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        self.jellyfin_status_label.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        info_layout.addWidget(self.jellyfin_status_label)

        self.overview_label.setFont(QFont("Inter", 13))
        self.overview_label.setWordWrap(True)
        self.overview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        info_layout.addWidget(self.overview_label)

        # Action Buttons Row
        actions_row_layout: QHBoxLayout = QHBoxLayout()
        actions_row_layout.setSpacing(10)

        match_metadata_button: QPushButton = QPushButton("Match Series Metadata...")
        match_metadata_button.setObjectName("matchMetadataButton")
        match_metadata_button.clicked.connect(
            lambda: self.controller.metadata_dialog_requested.emit(
                self.controller.selected_series_name
            )
        )
        actions_row_layout.addWidget(match_metadata_button)

        self.match_jellyfin_button.setObjectName("matchJellyfinButton")
        self.match_jellyfin_button.clicked.connect(
            lambda: self.controller.jellyfin_dialog_requested.emit(
                self.controller.selected_series_name
            )
        )
        actions_row_layout.addWidget(self.match_jellyfin_button)

        rename_files_button: QPushButton = QPushButton("Rename Files...")
        rename_files_button.setObjectName("renameFilesButton")
        rename_files_button.clicked.connect(
            lambda: self.controller.rename_dialog_requested.emit(
                self.controller.selected_series_name
            )
        )
        actions_row_layout.addWidget(rename_files_button)

        actions_row_layout.addStretch()
        info_layout.addLayout(actions_row_layout)

        header_layout.addLayout(info_layout)
        main_layout.addLayout(header_layout)

        # Horizontal Divider Line
        divider_line: QFrame = QFrame()
        divider_line.setFrameShape(QFrame.Shape.HLine)
        divider_line.setFrameShadow(QFrame.Shadow.Sunken)
        divider_line.setStyleSheet("border-color: #333333;")
        main_layout.addWidget(divider_line)

        # Seasons Table Container Tabs
        main_layout.addWidget(self.seasons_tab_widget)

    @Slot(str)
    def populate_series_details(self, series_name: str) -> None:
        series_record: Dict[str, Any] = self.controller.cached_library_data.get(
            series_name, {}
        )
        metadata_dictionary: Dict[str, Any] = series_record.get("metadata", {})

        series_display_title: str = metadata_dictionary.get("tmdb_name") or series_name
        self.title_label.setText(series_display_title)
        self.overview_label.setText(
            metadata_dictionary.get("overview") or "No overview available."
        )

        jellyfin_identifier_value: str = metadata_dictionary.get("jellyfin_id", "")
        if jellyfin_client.is_configured():
            self.match_jellyfin_button.setVisible(True)
            self.jellyfin_status_label.setVisible(True)
            if jellyfin_identifier_value:
                self.jellyfin_status_label.setText("Jellyfin Sync: Matched")
                self.jellyfin_status_label.setStyleSheet("color: #43a047;")
            else:
                self.jellyfin_status_label.setText("⚠️ Jellyfin Sync: Not Matched")
                self.jellyfin_status_label.setStyleSheet("color: #e53935;")
        else:
            self.match_jellyfin_button.setVisible(False)
            self.jellyfin_status_label.setVisible(False)

        # Load dynamic poster fragment
        poster_path_string: str = metadata_dictionary.get("poster_path", "")
        pixmap_assigned: bool = False
        if poster_path_string:
            poster_path_object = Path(poster_path_string)
            if poster_path_object.is_file():
                pixmap_instance = QPixmap(str(poster_path_object))
                if not pixmap_instance.isNull():
                    self.poster_label.setPixmap(
                        pixmap_instance.scaled(
                            180,
                            260,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    pixmap_assigned = True

        if not pixmap_assigned:
            self.poster_label.clear()
            self.poster_label.setText("No Poster")

        # Clear and repopulate Season Tabs
        self.seasons_tab_widget.clear()
        seasons_dictionary: Dict[str, Any] = series_record.get("seasons", {})

        try:
            sorted_season_names: List[str] = sorted(
                seasons_dictionary.keys(), key=db.natural_sort_key
            )
        except AttributeError:
            sorted_season_names = sorted(seasons_dictionary.keys())

        for season_name in sorted_season_names:
            season_data: Dict[str, Any] = seasons_dictionary.get(season_name, {})
            episodes_list: List[Dict[str, Any]] = season_data.get("episodes", [])

            # Create an explicit QTableWidget layout for absolute robust item targeting under automated tests
            episode_table: QTableWidget = QTableWidget()
            episode_table.setColumnCount(5)
            episode_table.setHorizontalHeaderLabels(
                ["#", "Episode Title", "Air Date", "Runtime", "Watched"]
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.Stretch
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                2, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                3, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                4, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.setSelectionBehavior(
                QTableWidget.SelectionBehavior.SelectRows
            )
            episode_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            episode_table.verticalHeader().setVisible(False)
            episode_table.setShowGrid(False)

            episode_table.setRowCount(len(episodes_list))

            def make_cell_clicked_slot(
                ep_list: List[Dict[str, Any]],
            ) -> Callable[[int, int], None]:
                def slot(row: int, col: int) -> None:
                    if col == 1:
                        target_path = ep_list[row].get("path", "")
                        if target_path:
                            self.controller.playback_requested.emit(target_path)

                return slot

            episode_table.cellClicked.connect(make_cell_clicked_slot(episodes_list))

            for row_index, episode_record in enumerate(episodes_list):
                tmdb_number_value: Optional[int] = episode_record.get("tmdb_number")
                number_string: str = (
                    str(tmdb_number_value)
                    if tmdb_number_value is not None
                    else str(row_index + 1)
                )

                tmdb_name_value: Optional[str] = episode_record.get("tmdb_name")
                title_string: str = (
                    tmdb_name_value
                    if tmdb_name_value
                    else episode_record.get("name", "Unknown")
                )

                absolute_path: str = episode_record.get("path", "")
                is_watched: bool = bool(episode_record.get("watched", False))
                air_date_string: str = episode_record.get("air_date") or ""
                runtime_value: int = episode_record.get("runtime", 0)
                runtime_string: str = f"{runtime_value} min" if runtime_value else ""

                # Render table item entities cleanly
                number_item: QTableWidgetItem = QTableWidgetItem(number_string)
                number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                episode_table.setItem(row_index, 0, number_item)

                title_item: QTableWidgetItem = QTableWidgetItem(title_string)
                title_item.setToolTip("Click to play episode")
                episode_table.setItem(row_index, 1, title_item)

                air_date_item: QTableWidgetItem = QTableWidgetItem(air_date_string)
                air_date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                episode_table.setItem(row_index, 2, air_date_item)

                runtime_item: QTableWidgetItem = QTableWidgetItem(runtime_string)
                runtime_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                episode_table.setItem(row_index, 3, runtime_item)

                # Custom interactive widget wrapper for Checkbox column to bind perfectly under pytest-qt
                checkbox_container: QWidget = QWidget()
                checkbox_layout: QHBoxLayout = QHBoxLayout(checkbox_container)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)
                checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

                watched_checkbox: QCheckBox = QCheckBox()
                watched_checkbox.setChecked(is_watched)
                watched_checkbox.setObjectName(
                    f"watchedCheckbox_{row_index}_{absolute_path}"
                )

                # Capture closure scope cleanly
                def make_toggle_slot(path_target: str) -> Callable[[bool], None]:
                    return lambda checked: self.controller.mark_episode_watched(
                        path_target, checked
                    )

                watched_checkbox.toggled.connect(make_toggle_slot(absolute_path))
                checkbox_layout.addWidget(watched_checkbox)
                episode_table.setCellWidget(row_index, 4, checkbox_container)

            self.seasons_tab_widget.addTab(episode_table, season_name)

    def trigger_episode_playback_by_row(
        self, season_tab_index: int, row_index: int
    ) -> None:
        """Test Helper triggering playback by simulating a click on the episode title cell."""
        target_widget: Optional[QWidget] = self.seasons_tab_widget.widget(
            season_tab_index
        )
        if isinstance(target_widget, QTableWidget):
            target_widget.cellClicked.emit(row_index, 1)


class MetadataMatchDialog(QDialog):
    """
    Search modal to retrieve metadata from external matching provider APIs.
    Strictly typesafe with zero abbreviations.
    """

    def __init__(
        self,
        series_name: str,
        controller_instance: Controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.controller: Controller = controller_instance
        self.search_input: QLineEdit = QLineEdit()
        self.results_table: QTableWidget = QTableWidget()
        self.search_results_list: List[Dict[str, Any]] = []

        self.setWindowTitle(f"Match Metadata: {series_name}")
        self.resize(800, 500)
        self._setup_ui()
        self.search_input.setText(series_name)

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Top Form Filters Row
        top_row_layout: QHBoxLayout = QHBoxLayout()
        top_row_layout.setSpacing(10)

        top_row_layout.addWidget(QLabel("Search Query:"))
        self.search_input.setMinimumWidth(250)
        top_row_layout.addWidget(self.search_input)

        search_button: QPushButton = QPushButton("Search")
        search_button.setObjectName("metadataSearchTriggerButton")
        search_button.clicked.connect(self.execute_search)
        top_row_layout.addWidget(search_button)

        main_layout.addLayout(top_row_layout)

        # Search Results Matrix Table
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(
            ["Provider ID", "Series Title", "First Air Date", "Overview"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)

        main_layout.addWidget(self.results_table)

        # Bottom Form Actions Buttons
        bottom_buttons_layout: QHBoxLayout = QHBoxLayout()
        bottom_buttons_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Cancel")
        cancel_button.setObjectName("closeMetadataMatchDialogButton")
        cancel_button.clicked.connect(self.reject)
        bottom_buttons_layout.addWidget(cancel_button)

        apply_button: QPushButton = QPushButton("Apply Selected Match")
        apply_button.setObjectName("accentButton")
        apply_button.clicked.connect(self.apply_selected)
        bottom_buttons_layout.addWidget(apply_button)

        main_layout.addLayout(bottom_buttons_layout)

    @Slot()
    def execute_search(self) -> None:
        query_string: str = self.search_input.text().strip()
        if not query_string:
            return

        self.results_table.clearContents()
        self.results_table.setRowCount(0)
        self.search_results_list = []

        library_config = config.libraries.get(self.controller.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        if is_movie:
            raw_results = tmdb_client.search_movie_full(query_string)
            for item_data in raw_results:
                self.search_results_list.append(
                    {
                        "id": str(item_data.get("id", "")),
                        "tmdb_id": str(item_data.get("id", "")),
                        "name": item_data.get("title", ""),
                        "first_air_date": item_data.get("release_date", ""),
                        "overview": item_data.get("overview", ""),
                        "poster_path": item_data.get("poster_path", ""),
                        "provider": "TMDB",
                    }
                )
        else:
            raw_results = tmdb_client.search_series_full(query_string)
            for item_data in raw_results:
                self.search_results_list.append(
                    {
                        "id": str(item_data.get("id", "")),
                        "tmdb_id": str(item_data.get("id", "")),
                        "name": item_data.get("name", ""),
                        "first_air_date": item_data.get("first_air_date", ""),
                        "overview": item_data.get("overview", ""),
                        "poster_path": item_data.get("poster_path", ""),
                        "provider": "TMDB",
                    }
                )

        self.results_table.setRowCount(len(self.search_results_list))
        for row_index, result_dictionary in enumerate(self.search_results_list):
            id_item: QTableWidgetItem = QTableWidgetItem(result_dictionary["id"])
            self.results_table.setItem(row_index, 0, id_item)

            name_item: QTableWidgetItem = QTableWidgetItem(result_dictionary["name"])
            self.results_table.setItem(row_index, 1, name_item)

            date_item: QTableWidgetItem = QTableWidgetItem(
                result_dictionary["first_air_date"]
            )
            self.results_table.setItem(row_index, 2, date_item)

            overview_item: QTableWidgetItem = QTableWidgetItem(
                result_dictionary["overview"]
            )
            self.results_table.setItem(row_index, 3, overview_item)

    @Slot()
    def apply_selected(self) -> None:
        selected_rows: List[int] = [
            item.row() for item in self.results_table.selectedItems()
        ]
        if not selected_rows:
            QMessageBox.warning(
                self, "Selection Required", "Please select a match result first."
            )
            return

        target_row_index: int = selected_rows[0]
        match_record: Dict[str, Any] = self.search_results_list[target_row_index]
        self.controller.apply_metadata_match(self.series_name, match_record)
        self.accept()


class JellyfinMatchDialog(QDialog):
    """
    Search modal to retrieve series or movie IDs specifically from Jellyfin for watch history correlation.
    Strictly typesafe with zero abbreviations.
    """

    def __init__(
        self,
        series_name: str,
        controller_instance: Controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.controller: Controller = controller_instance
        self.search_input: QLineEdit = QLineEdit()
        self.results_table: QTableWidget = QTableWidget()
        self.search_results_list: List[Dict[str, Any]] = []

        self.setWindowTitle(f"Match Jellyfin Watch History: {series_name}")
        self.resize(800, 500)
        self._setup_ui()
        self.search_input.setText(series_name)

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Top Form Filters Row
        top_row_layout: QHBoxLayout = QHBoxLayout()
        top_row_layout.setSpacing(10)

        top_row_layout.addWidget(QLabel("Search Query:"))
        self.search_input.setMinimumWidth(250)
        top_row_layout.addWidget(self.search_input)

        search_button: QPushButton = QPushButton("Search Jellyfin")
        search_button.setObjectName("jellyfinSearchTriggerButton")
        search_button.clicked.connect(self.execute_search)
        top_row_layout.addWidget(search_button)

        main_layout.addLayout(top_row_layout)

        # Search Results Matrix Table
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(
            ["Jellyfin ID", "Series Title", "Production Year", "Overview"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)

        main_layout.addWidget(self.results_table)

        # Bottom Form Actions Buttons
        bottom_buttons_layout: QHBoxLayout = QHBoxLayout()
        bottom_buttons_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Cancel")
        cancel_button.setObjectName("closeJellyfinMatchDialogButton")
        cancel_button.clicked.connect(self.reject)
        bottom_buttons_layout.addWidget(cancel_button)

        apply_button: QPushButton = QPushButton("Link Selected Match")
        apply_button.setObjectName("accentButton")
        apply_button.clicked.connect(self.apply_selected)
        bottom_buttons_layout.addWidget(apply_button)

        main_layout.addLayout(bottom_buttons_layout)

    @Slot()
    def execute_search(self) -> None:
        query_string: str = self.search_input.text().strip()
        if not query_string:
            return

        self.results_table.clearContents()
        self.results_table.setRowCount(0)
        self.search_results_list = []

        library_config = config.libraries.get(self.controller.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        if is_movie:
            raw_results: List[Dict[str, Any]] = jellyfin_client.search_movie(
                query_string
            )
        else:
            raw_results = jellyfin_client.search_series(query_string)

        for item_data in raw_results:
            production_year_value: str = str(item_data.get("ProductionYear", ""))
            first_air_date_value: str = (
                production_year_value if production_year_value else ""
            )

            self.search_results_list.append(
                {
                    "id": str(item_data.get("Id", "")),
                    "name": item_data.get("Name", ""),
                    "first_air_date": first_air_date_value,
                    "overview": item_data.get("Overview", ""),
                    "provider": "Jellyfin",
                }
            )

        self.results_table.setRowCount(len(self.search_results_list))
        for row_index, result_dictionary in enumerate(self.search_results_list):
            id_item: QTableWidgetItem = QTableWidgetItem(result_dictionary["id"])
            self.results_table.setItem(row_index, 0, id_item)

            name_item: QTableWidgetItem = QTableWidgetItem(result_dictionary["name"])
            self.results_table.setItem(row_index, 1, name_item)

            date_item: QTableWidgetItem = QTableWidgetItem(
                result_dictionary["first_air_date"]
            )
            self.results_table.setItem(row_index, 2, date_item)

            overview_item: QTableWidgetItem = QTableWidgetItem(
                result_dictionary["overview"]
            )
            self.results_table.setItem(row_index, 3, overview_item)

    @Slot()
    def apply_selected(self) -> None:
        selected_rows: List[int] = [
            item.row() for item in self.results_table.selectedItems()
        ]
        if not selected_rows:
            QMessageBox.warning(
                self, "Selection Required", "Please select a match result first."
            )
            return

        target_row_index: int = selected_rows[0]
        match_record: Dict[str, Any] = self.search_results_list[target_row_index]
        self.controller.apply_jellyfin_watch_match(self.series_name, match_record)
        self.accept()


class RenamePreviewDialog(QDialog):
    """
    Dialog displaying generated file renaming mapping previews for consistent file hygiene.
    Conforms strictly to standard static typing and naming constraints.
    """

    def __init__(
        self,
        series_name: str,
        controller_instance: Controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.controller: Controller = controller_instance
        self.template_input: QLineEdit = QLineEdit()
        self.preview_table: QTableWidget = QTableWidget()
        self.preview_results_list: List[Dict[str, Any]] = []

        self.setWindowTitle(f"Rename Preview: {series_name}")
        self.resize(900, 600)
        self._setup_ui()
        self.template_input.setText(
            "{SeriesTitle} S{SeasonNumber:02}E{EpisodeNumber:02} - {EpisodeTitle}"
        )
        self.generate_preview()

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Template Header Box
        template_layout: QHBoxLayout = QHBoxLayout()
        template_layout.setSpacing(10)

        template_layout.addWidget(QLabel("Naming Template:"))
        self.template_input.setMinimumWidth(400)
        template_layout.addWidget(self.template_input)

        preview_trigger_button: QPushButton = QPushButton("Update Preview")
        preview_trigger_button.setObjectName("renamePreviewTriggerButton")
        preview_trigger_button.clicked.connect(self.generate_preview)
        template_layout.addWidget(preview_trigger_button)

        main_layout.addLayout(template_layout)

        # Preview Data Table
        self.preview_table.setColumnCount(2)
        self.preview_table.setHorizontalHeaderLabels(
            ["Original Target Filename", "New Standardized Filename"]
        )
        self.preview_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.preview_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.verticalHeader().setVisible(False)

        main_layout.addWidget(self.preview_table)

        # Action Execution Toolbar
        actions_layout: QHBoxLayout = QHBoxLayout()
        actions_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Cancel")
        cancel_button.setObjectName("closeRenameFilesDialogButton")
        cancel_button.clicked.connect(self.reject)
        actions_layout.addWidget(cancel_button)

        apply_renames_button: QPushButton = QPushButton("Apply Renames")
        apply_renames_button.setObjectName("accentButton")
        apply_renames_button.clicked.connect(self.apply_renames)
        actions_layout.addWidget(apply_renames_button)

        main_layout.addLayout(actions_layout)

    @Slot()
    def generate_preview(self) -> None:
        template_string: str = self.template_input.text().strip()
        if (
            not template_string
            or self.series_name not in self.controller.cached_library_data
        ):
            return

        series_dictionary: Dict[str, Any] = self.controller.cached_library_data[
            self.series_name
        ]
        from .renamer import get_rename_preview

        self.preview_results_list = get_rename_preview(
            series_dictionary, template_string
        )

        self.preview_table.setRowCount(len(self.preview_results_list))
        for row_index, preview_dictionary in enumerate(self.preview_results_list):
            old_name_str: str = preview_dictionary.get("old_name", "")
            if not old_name_str and "old_path" in preview_dictionary:
                old_name_str = Path(preview_dictionary["old_path"]).name

            old_item: QTableWidgetItem = QTableWidgetItem(old_name_str)
            self.preview_table.setItem(row_index, 0, old_item)

            new_item: QTableWidgetItem = QTableWidgetItem(
                preview_dictionary.get("new_name", "")
            )
            self.preview_table.setItem(row_index, 1, new_item)

    @Slot()
    def apply_renames(self) -> None:
        if not self.preview_results_list:
            return

        self.controller.apply_rename_batch(self.preview_results_list)
        self.accept()


class SettingsDialog(QDialog):
    """
    Configuration modal encapsulating system directory management and operational behaviors.
    """

    def __init__(
        self,
        controller_instance: Optional[Controller] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.controller: Optional[Controller] = controller_instance
        self.setWindowTitle("Application Configuration")
        self.resize(800, 700)

        self.force_refresh_checkbox: QCheckBox = QCheckBox(
            "Force refresh metadata (update/search TMDB)"
        )
        self.global_progress_bar: QProgressBar = QProgressBar()
        self.global_progress_bar.setVisible(False)
        if self.controller is not None:
            self.controller.global_progress_updated.connect(self._on_global_progress)

        self.jellyfin_url_input: QLineEdit = QLineEdit()
        self.jellyfin_key_input: QLineEdit = QLineEdit()
        self.tmdb_key_input: QLineEdit = QLineEdit()

        self.staged_libraries: Dict[str, Dict[str, Any]] = {}
        self.library_name_input: QLineEdit = QLineEdit()
        self.library_type_input: QComboBox = QComboBox()
        self.library_selector: QComboBox = QComboBox()
        self.directory_list_widget: QListWidget = QListWidget()

        self.use_embedded_checkbox: QCheckBox = QCheckBox(
            "Use Embedded Video Player (uncheck for Standalone VLC)"
        )
        self.enable_caching_checkbox: QCheckBox = QCheckBox(
            "Enable Media Stream Caching"
        )
        self.enable_hw_accel_checkbox: QCheckBox = QCheckBox(
            "Enable Hardware Acceleration Decoding"
        )
        self.watched_threshold_input: QLineEdit = QLineEdit()

        self.db_path_input: QLineEdit = QLineEdit()
        self.log_dir_input: QLineEdit = QLineEdit()
        self.log_retention_input: QLineEdit = QLineEdit()
        self.log_saving_mode_selector: QComboBox = QComboBox()
        self.log_level_selector: QComboBox = QComboBox()

        self.backup_directory_input: QLineEdit = QLineEdit()
        self.config_backup_frequency_input: QLineEdit = QLineEdit()
        self.database_backup_frequency_input: QLineEdit = QLineEdit()
        self.config_backup_retention_input: QLineEdit = QLineEdit()
        self.database_backup_retention_input: QLineEdit = QLineEdit()

        self._setup_ui()
        self._load_config()

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        tab_container: QTabWidget = QTabWidget()

        # Connectivity Configuration Pane
        connectivity_tab: QWidget = QWidget()
        connectivity_layout: QGridLayout = QGridLayout(connectivity_tab)
        connectivity_layout.setSpacing(12)

        connectivity_layout.addWidget(QLabel("Jellyfin Server URL:"), 0, 0)
        connectivity_layout.addWidget(self.jellyfin_url_input, 0, 1)

        connectivity_layout.addWidget(QLabel("Jellyfin API Token:"), 1, 0)
        self.jellyfin_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.jellyfin_key_input, 1, 1)

        connectivity_layout.addWidget(QLabel("TMDB API Key:"), 2, 0)
        self.tmdb_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.tmdb_key_input, 2, 1)

        connectivity_layout.setRowStretch(4, 1)
        tab_container.addTab(connectivity_tab, "Remote APIs")

        # Libraries Management Pane
        libraries_tab: QWidget = QWidget()
        libraries_layout: QVBoxLayout = QVBoxLayout(libraries_tab)
        libraries_layout.setSpacing(12)

        # Create Library Group
        create_layout: QHBoxLayout = QHBoxLayout()
        create_layout.addWidget(QLabel("New Library Name:"))
        self.library_name_input.setPlaceholderText("e.g. Movies, Documentaries")
        create_layout.addWidget(self.library_name_input)

        create_layout.addWidget(QLabel("Type:"))
        self.library_type_input.addItems(["TV Shows", "Movies"])
        create_layout.addWidget(self.library_type_input)

        add_library_button: QPushButton = QPushButton("Create Library")
        add_library_button.clicked.connect(self.add_staged_library)
        create_layout.addWidget(add_library_button)
        libraries_layout.addLayout(create_layout)

        # Divider
        divider_frame: QFrame = QFrame()
        divider_frame.setFrameShape(QFrame.Shape.HLine)
        divider_frame.setFrameShadow(QFrame.Shadow.Sunken)
        libraries_layout.addWidget(divider_frame)

        # Select Library Group
        select_layout: QHBoxLayout = QHBoxLayout()
        select_layout.addWidget(QLabel("Configure Library:"))
        self.library_selector.setMinimumWidth(200)
        self.library_selector.currentTextChanged.connect(self._on_library_selected)
        select_layout.addWidget(self.library_selector)

        delete_library_button: QPushButton = QPushButton("Remove Library")
        delete_library_button.clicked.connect(self.remove_staged_library)
        select_layout.addWidget(delete_library_button)
        select_layout.addStretch()
        libraries_layout.addLayout(select_layout)

        # Mapped Directories List
        libraries_layout.addWidget(QLabel("Mapped Root Directories:"))
        libraries_layout.addWidget(self.directory_list_widget)

        # Directory Operations
        dir_buttons_layout: QHBoxLayout = QHBoxLayout()
        add_dir_button: QPushButton = QPushButton("Add Directory...")
        add_dir_button.clicked.connect(self.add_staged_directory)
        dir_buttons_layout.addWidget(add_dir_button)

        remove_dir_button: QPushButton = QPushButton("Remove Selected Directory")
        remove_dir_button.clicked.connect(self.remove_staged_directory)
        dir_buttons_layout.addWidget(remove_dir_button)
        dir_buttons_layout.addStretch()
        libraries_layout.addLayout(dir_buttons_layout)

        tab_container.addTab(libraries_tab, "Libraries Setup")

        # Video Player Settings Pane
        player_tab: QWidget = QWidget()
        player_layout: QVBoxLayout = QVBoxLayout(player_tab)
        player_layout.setSpacing(15)

        player_layout.addWidget(self.use_embedded_checkbox)
        player_layout.addWidget(self.enable_caching_checkbox)
        player_layout.addWidget(self.enable_hw_accel_checkbox)

        threshold_layout: QHBoxLayout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("Watched Threshold (% of video length):"))
        self.watched_threshold_input.setFixedWidth(80)
        threshold_layout.addWidget(self.watched_threshold_input)
        threshold_layout.addStretch()
        player_layout.addLayout(threshold_layout)

        player_layout.addStretch()

        tab_container.addTab(player_tab, "Video Player")

        # Advanced Settings Pane
        advanced_tab: QWidget = QWidget()
        advanced_layout: QGridLayout = QGridLayout(advanced_tab)
        advanced_layout.setSpacing(12)

        advanced_layout.addWidget(QLabel("Database File Path:"), 0, 0)
        advanced_layout.addWidget(self.db_path_input, 0, 1)
        browse_db_button: QPushButton = QPushButton("Browse File...")
        browse_db_button.clicked.connect(self.browse_database_path)
        advanced_layout.addWidget(browse_db_button, 0, 2)

        advanced_layout.addWidget(QLabel("Logs Directory:"), 1, 0)
        advanced_layout.addWidget(self.log_dir_input, 1, 1)
        browse_log_button: QPushButton = QPushButton("Browse Folder...")
        browse_log_button.clicked.connect(self.browse_log_directory)
        advanced_layout.addWidget(browse_log_button, 1, 2)

        advanced_layout.addWidget(QLabel("Max Log Retention Days:"), 2, 0)
        advanced_layout.addWidget(self.log_retention_input, 2, 1)

        advanced_layout.addWidget(QLabel("Log Saving Mode:"), 3, 0)
        self.log_saving_mode_selector.addItems(
            ["Single Global File", "Divided Service Logs"]
        )
        advanced_layout.addWidget(self.log_saving_mode_selector, 3, 1)

        advanced_layout.addWidget(QLabel("Log Level:"), 4, 0)
        self.log_level_selector.addItems(
            ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        )
        advanced_layout.addWidget(self.log_level_selector, 4, 1)

        advanced_layout.addWidget(QLabel("Backup Directory:"), 5, 0)
        advanced_layout.addWidget(self.backup_directory_input, 5, 1)
        browse_backup_button: QPushButton = QPushButton("Browse Folder...")
        browse_backup_button.clicked.connect(self.browse_backup_directory)
        advanced_layout.addWidget(browse_backup_button, 5, 2)

        advanced_layout.addWidget(QLabel("Config Backup Freq (Days):"), 6, 0)
        advanced_layout.addWidget(self.config_backup_frequency_input, 6, 1)

        advanced_layout.addWidget(QLabel("Database Backup Freq (Days):"), 7, 0)
        advanced_layout.addWidget(self.database_backup_frequency_input, 7, 1)

        advanced_layout.addWidget(QLabel("Config Backup Retention:"), 8, 0)
        advanced_layout.addWidget(self.config_backup_retention_input, 8, 1)

        advanced_layout.addWidget(QLabel("Database Backup Retention:"), 9, 0)
        advanced_layout.addWidget(self.database_backup_retention_input, 9, 1)

        restore_config_button: QPushButton = QPushButton("Restore Config...")
        restore_config_button.clicked.connect(self.trigger_restore_config)
        advanced_layout.addWidget(restore_config_button, 10, 0)

        restore_database_button: QPushButton = QPushButton("Restore Database...")
        restore_database_button.clicked.connect(self.trigger_restore_database)
        advanced_layout.addWidget(restore_database_button, 10, 1)

        advanced_layout.setRowStretch(11, 1)
        tab_container.addTab(advanced_tab, "Advanced")

        # Library Management Pane
        management_tab: QWidget = QWidget()
        management_layout: QVBoxLayout = QVBoxLayout(management_tab)
        management_layout.setSpacing(15)

        scan_all_button: QPushButton = QPushButton("Scan New Files (All Libraries)")
        scan_all_button.setObjectName("accentButton")
        scan_all_button.clicked.connect(self.trigger_global_scan_files)
        management_layout.addWidget(scan_all_button)

        cleanup_all_button: QPushButton = QPushButton("Cleanup All Libraries")
        cleanup_all_button.clicked.connect(self.trigger_global_cleanup)
        management_layout.addWidget(cleanup_all_button)

        # Refresh Metadata Group
        refresh_frame: QFrame = QFrame()
        refresh_frame.setStyleSheet(
            "QFrame { background-color: #222222; border: 1px solid #333333; border-radius: 6px; }"
        )
        refresh_layout: QVBoxLayout = QVBoxLayout(refresh_frame)
        refresh_layout.setSpacing(10)

        refresh_all_button: QPushButton = QPushButton(
            "Refresh Metadata (All Libraries)"
        )
        refresh_all_button.clicked.connect(self.trigger_global_refresh_metadata)
        refresh_layout.addWidget(refresh_all_button)

        refresh_layout.addWidget(self.force_refresh_checkbox)
        management_layout.addWidget(refresh_frame)

        # Jellyfin Sync Group
        jellyfin_frame: QFrame = QFrame()
        jellyfin_frame.setStyleSheet(
            "QFrame { background-color: #222222; border: 1px solid #333333; border-radius: 6px; }"
        )
        jellyfin_layout: QVBoxLayout = QVBoxLayout(jellyfin_frame)
        jellyfin_layout.setSpacing(10)

        pull_all_button: QPushButton = QPushButton(
            "Pull Watch History from Jellyfin (All Libraries)"
        )
        pull_all_button.clicked.connect(self.trigger_global_jellyfin_pull)
        jellyfin_layout.addWidget(pull_all_button)

        push_all_button: QPushButton = QPushButton(
            "Push Watch History to Jellyfin (All Libraries)"
        )
        push_all_button.clicked.connect(self.trigger_global_jellyfin_push)
        jellyfin_layout.addWidget(push_all_button)
        management_layout.addWidget(jellyfin_frame)

        management_layout.addSpacing(10)
        management_layout.addWidget(QLabel("Global Operation Progress:"))
        self.global_progress_bar.setMinimum(0)
        self.global_progress_bar.setMaximum(100)
        self.global_progress_bar.setValue(0)
        management_layout.addWidget(self.global_progress_bar)

        management_layout.addStretch()
        tab_container.addTab(management_tab, "Library Management")

        main_layout.addWidget(tab_container)

        # Dialog Standard Action Buttons
        buttons_layout: QHBoxLayout = QHBoxLayout()
        buttons_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Discard")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)

        save_button: QPushButton = QPushButton("Save Settings")
        save_button.setObjectName("accentButton")
        save_button.clicked.connect(self.save_config)
        buttons_layout.addWidget(save_button)

        main_layout.addLayout(buttons_layout)

    def _load_config(self) -> None:
        self.jellyfin_url_input.setText(config.jellyfin_url)
        self.jellyfin_key_input.setText(config.jellyfin_api_key)
        self.tmdb_key_input.setText(config.tmdb_api_key)

        self.use_embedded_checkbox.setChecked(config.use_embedded_player)
        self.enable_caching_checkbox.setChecked(config.enable_caching)
        self.enable_hw_accel_checkbox.setChecked(config.enable_hw_accel)
        self.watched_threshold_input.setText(str(int(config.watched_threshold * 100)))

        self.db_path_input.setText(config.database_path)
        self.log_dir_input.setText(config.log_directory)
        self.log_retention_input.setText(str(config.max_log_retention_days))
        self.log_saving_mode_selector.setCurrentText(
            "Divided Service Logs"
            if config.divide_logs_by_service
            else "Single Global File"
        )
        self.log_level_selector.setCurrentText(config.log_level.upper())

        self.backup_directory_input.setText(config.backup_directory)
        self.config_backup_frequency_input.setText(str(config.config_backup_frequency))
        self.database_backup_frequency_input.setText(
            str(config.database_backup_frequency)
        )
        self.config_backup_retention_input.setText(str(config.config_backup_retention))
        self.database_backup_retention_input.setText(
            str(config.database_backup_retention)
        )

        self.staged_libraries = {
            library_name: {
                "type": library_config.get("type", "tv"),
                "paths": list(library_config.get("paths", [])),
            }
            for library_name, library_config in config.libraries.items()
        }
        self._refresh_library_selector()

    def _refresh_library_selector(self) -> None:
        self.library_selector.blockSignals(True)
        self.library_selector.clear()
        self.library_selector.addItems(sorted(self.staged_libraries.keys()))
        self.library_selector.blockSignals(False)
        self._refresh_directory_list()

    @Slot(str)
    def _on_library_selected(self, library_name: str) -> None:
        self._refresh_directory_list()

    def _refresh_directory_list(self) -> None:
        self.directory_list_widget.clear()
        selected_library: str = self.library_selector.currentText()
        if selected_library in self.staged_libraries:
            self.directory_list_widget.addItems(
                self.staged_libraries[selected_library].get("paths", [])
            )

    @Slot()
    def add_staged_library(self) -> None:
        new_library_name: str = self.library_name_input.text().strip()
        new_library_type: str = (
            "movie" if self.library_type_input.currentText() == "Movies" else "tv"
        )
        if not new_library_name:
            return
        if new_library_name in self.staged_libraries:
            QMessageBox.warning(
                self,
                "Duplicate Library",
                f"Library '{new_library_name}' already exists.",
            )
            return

        self.staged_libraries[new_library_name] = {
            "type": new_library_type,
            "paths": [],
        }
        self.library_name_input.clear()
        self._refresh_library_selector()
        self.library_selector.setCurrentText(new_library_name)

    @Slot()
    def remove_staged_library(self) -> None:
        selected_library: str = self.library_selector.currentText()
        if not selected_library:
            return

        del self.staged_libraries[selected_library]
        self._refresh_library_selector()

    @Slot()
    def add_staged_directory(self) -> None:
        selected_library: str = self.library_selector.currentText()
        if not selected_library:
            QMessageBox.warning(
                self, "No Library Selected", "Please select or create a library first."
            )
            return

        chosen_directory: str = QFileDialog.getExistingDirectory(
            self, "Select Root Directory"
        )
        if chosen_directory:
            paths: List[str] = self.staged_libraries[selected_library].get("paths", [])
            if chosen_directory not in paths:
                paths.append(chosen_directory)
                self.staged_libraries[selected_library]["paths"] = paths
                self._refresh_directory_list()

    @Slot()
    def remove_staged_directory(self) -> None:
        selected_library: str = self.library_selector.currentText()
        selected_item: Optional[QListWidgetItem] = (
            self.directory_list_widget.currentItem()
        )
        if not selected_library or selected_item is None:
            return

        directory_path: str = selected_item.text()
        paths: List[str] = self.staged_libraries[selected_library].get("paths", [])
        if directory_path in paths:
            paths.remove(directory_path)
            self.staged_libraries[selected_library]["paths"] = paths
            self._refresh_directory_list()

    @Slot()
    def browse_database_path(self) -> None:
        chosen_file, _ = QFileDialog.getSaveFileName(
            self,
            "Select Database File",
            self.db_path_input.text(),
            "Database Files (*.db);;All Files (*)",
        )
        if chosen_file:
            self.db_path_input.setText(chosen_file)

    @Slot()
    def browse_log_directory(self) -> None:
        chosen_dir: str = QFileDialog.getExistingDirectory(
            self, "Select Log Directory", self.log_dir_input.text()
        )
        if chosen_dir:
            self.log_dir_input.setText(chosen_dir)

    @Slot()
    def save_config(self) -> None:
        config.jellyfin_url = self.jellyfin_url_input.text().strip()
        config.jellyfin_api_key = self.jellyfin_key_input.text().strip()
        config.tmdb_api_key = self.tmdb_key_input.text().strip()
        config.sync_history_on_start = False

        config.use_embedded_player = self.use_embedded_checkbox.isChecked()
        config.enable_caching = self.enable_caching_checkbox.isChecked()
        config.enable_hw_accel = self.enable_hw_accel_checkbox.isChecked()
        try:
            parsed_threshold = float(self.watched_threshold_input.text().strip())
            if parsed_threshold > 1.0:
                config.watched_threshold = parsed_threshold / 100.0
            else:
                config.watched_threshold = parsed_threshold
        except ValueError:
            pass

        if self.db_path_input.text().strip():
            config.database_path = self.db_path_input.text().strip()
        if self.log_dir_input.text().strip():
            config.log_directory = self.log_dir_input.text().strip()

        config.log_level = self.log_level_selector.currentText()
        try:
            config.max_log_retention_days = int(self.log_retention_input.text().strip())
        except ValueError:
            pass

        config.divide_logs_by_service = (
            self.log_saving_mode_selector.currentText() == "Divided Service Logs"
        )

        if self.backup_directory_input.text().strip():
            config.backup_directory = self.backup_directory_input.text().strip()

        try:
            config.config_backup_frequency = int(
                self.config_backup_frequency_input.text().strip()
            )
        except ValueError:
            pass

        try:
            config.database_backup_frequency = int(
                self.database_backup_frequency_input.text().strip()
            )
        except ValueError:
            pass

        try:
            config.config_backup_retention = int(
                self.config_backup_retention_input.text().strip()
            )
        except ValueError:
            pass

        try:
            config.database_backup_retention = int(
                self.database_backup_retention_input.text().strip()
            )
        except ValueError:
            pass

        config.libraries = self.staged_libraries
        config.save()
        self.accept()

    @Slot()
    def browse_backup_directory(self) -> None:
        chosen_directory: str = QFileDialog.getExistingDirectory(
            self, "Select Backup Directory", self.backup_directory_input.text()
        )
        if chosen_directory:
            self.backup_directory_input.setText(chosen_directory)

    @Slot()
    def trigger_restore_config(self) -> None:
        chosen_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Configuration Backup to Restore",
            self.backup_directory_input.text(),
            "JSON Files (*.json);;All Files (*)",
        )
        if chosen_file:
            from .backup import restore_config_backup

            success: bool = restore_config_backup(chosen_file)
            if success:
                QMessageBox.information(
                    self,
                    "Restore Successful",
                    "Configuration successfully restored and reloaded.",
                )
                self._load_config()
            else:
                QMessageBox.critical(
                    self,
                    "Restore Failed",
                    "Failed to restore configuration. Ensure the file is valid.",
                )

    @Slot()
    def trigger_restore_database(self) -> None:
        chosen_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Database Backup to Restore",
            self.backup_directory_input.text(),
            "Database Files (*.db);;All Files (*)",
        )
        if chosen_file:
            from .backup import restore_database_backup

            success: bool = restore_database_backup(chosen_file)
            if success:
                QMessageBox.information(
                    self,
                    "Restore Successful",
                    "Database successfully restored from backup.",
                )
            else:
                QMessageBox.critical(
                    self,
                    "Restore Failed",
                    "Failed to restore database. Ensure the file is uncorrupted.",
                )

    @Slot(str, int, int)
    def _on_global_progress(
        self, library_name: str, completed_count: int, total_count: int
    ) -> None:
        self.global_progress_bar.setVisible(True)
        self.global_progress_bar.setMaximum(total_count)
        self.global_progress_bar.setValue(completed_count)
        self.global_progress_bar.setFormat(
            f"Processing '{library_name}' ({completed_count}/{total_count})"
        )

    @Slot()
    def trigger_global_scan_files(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.global_progress_bar.setMaximum(100)
            self.global_progress_bar.setValue(0)
            self.global_progress_bar.setFormat("Starting global file scan...")
            self.controller.trigger_scan_all(False)

    @Slot()
    def trigger_global_cleanup(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.global_progress_bar.setMaximum(100)
            self.global_progress_bar.setValue(0)
            self.global_progress_bar.setFormat("Starting global cleanup...")
            self.controller.trigger_cleanup_all()

    @Slot()
    def trigger_global_refresh_metadata(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.global_progress_bar.setMaximum(100)
            self.global_progress_bar.setValue(0)
            self.global_progress_bar.setFormat("Starting global metadata refresh...")
            self.controller.trigger_scan_all(self.force_refresh_checkbox.isChecked())

    @Slot()
    def trigger_global_jellyfin_pull(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.global_progress_bar.setMaximum(100)
            self.global_progress_bar.setValue(50)
            self.global_progress_bar.setFormat("Pulling history from Jellyfin...")
            self.controller.trigger_jellyfin_pull()
            QTimer.singleShot(
                2000,
                lambda: self._complete_jellyfin_progress("Jellyfin pull completed."),
            )

    @Slot()
    def trigger_global_jellyfin_push(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.global_progress_bar.setMaximum(100)
            self.global_progress_bar.setValue(50)
            self.global_progress_bar.setFormat("Pushing history to Jellyfin...")
            self.controller.trigger_jellyfin_push()
            QTimer.singleShot(
                2000,
                lambda: self._complete_jellyfin_progress("Jellyfin push completed."),
            )

    def _complete_jellyfin_progress(self, message_text: str) -> None:
        self.global_progress_bar.setMaximum(100)
        self.global_progress_bar.setValue(100)
        self.global_progress_bar.setFormat(message_text)


class MovieDetailView(QWidget):
    """
    Presents exhaustive movie structure, overview, and direct execution actions.
    Enforces strict typing and zero-abbreviation naming standard.
    """

    back_requested = Signal()

    def __init__(
        self, controller_instance: Controller, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.controller: Controller = controller_instance
        self.title_label: QLabel = QLabel()
        self.overview_label: QLabel = QLabel()
        self.poster_label: QLabel = QLabel()
        self.metadata_label: QLabel = QLabel()
        self.play_button: QPushButton = QPushButton("▶ Play Movie")

        self._setup_ui()
        self.controller.movie_selected.connect(self.populate_movie_details)
        self._current_movie_path: str = ""

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Header Panel
        header_layout: QHBoxLayout = QHBoxLayout()
        header_layout.setSpacing(20)

        back_button: QPushButton = QPushButton("← Back to Library")
        back_button.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(back_button, 0, Qt.AlignmentFlag.AlignTop)

        self.poster_label.setFixedSize(180, 260)
        self.poster_label.setStyleSheet(
            "background-color: #222222; border: 1px solid #444444; border-radius: 6px;"
        )
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.poster_label, 0, Qt.AlignmentFlag.AlignTop)

        info_layout: QVBoxLayout = QVBoxLayout()
        info_layout.setSpacing(10)

        self.title_label.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        self.metadata_label.setFont(QFont("Inter", 12))
        self.metadata_label.setStyleSheet("color: #aaaaaa;")
        info_layout.addWidget(self.metadata_label)

        self.overview_label.setFont(QFont("Inter", 13))
        self.overview_label.setWordWrap(True)
        self.overview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        info_layout.addWidget(self.overview_label)

        # Action Buttons Row
        actions_row_layout: QHBoxLayout = QHBoxLayout()
        actions_row_layout.setSpacing(10)

        self.play_button.setObjectName("accentButton")
        self.play_button.clicked.connect(self._on_play_clicked)
        actions_row_layout.addWidget(self.play_button)

        match_metadata_button: QPushButton = QPushButton("Match Movie Metadata...")
        match_metadata_button.setObjectName("matchMetadataButton")
        match_metadata_button.clicked.connect(
            lambda: self.controller.metadata_dialog_requested.emit(
                self.controller.selected_series_name
            )
        )
        actions_row_layout.addWidget(match_metadata_button)

        actions_row_layout.addStretch()
        info_layout.addLayout(actions_row_layout)

        header_layout.addLayout(info_layout)
        main_layout.addLayout(header_layout)

        # Horizontal Divider Line
        divider_line: QFrame = QFrame()
        divider_line.setFrameShape(QFrame.Shape.HLine)
        divider_line.setFrameShadow(QFrame.Shadow.Sunken)
        divider_line.setStyleSheet("border-color: #333333;")
        main_layout.addWidget(divider_line)

        main_layout.addStretch()

    @Slot(str)
    def populate_movie_details(self, movie_name: str) -> None:
        movie_record: Dict[str, Any] = self.controller.cached_library_data.get(
            movie_name, {}
        )
        self._current_movie_path = movie_record.get("path", "")

        movie_display_title: str = movie_record.get("tmdb_name") or movie_name
        self.title_label.setText(movie_display_title)
        self.overview_label.setText(
            movie_record.get("overview") or "No overview available."
        )

        year: int = movie_record.get("year", 0)
        runtime: int = movie_record.get("runtime", 0)
        rating: str = movie_record.get("rating", "")
        genre: str = movie_record.get("genre", "")

        metadata_parts = []
        if year:
            metadata_parts.append(str(year))
        if runtime:
            metadata_parts.append(f"{runtime} min")
        if rating:
            metadata_parts.append(f"★ {rating}")
        if genre:
            metadata_parts.append(genre)

        self.metadata_label.setText(" • ".join(metadata_parts))

        poster_path_string: str = movie_record.get("poster_path", "")
        pixmap_assigned: bool = False
        if poster_path_string:
            poster_path_object = Path(poster_path_string)
            if poster_path_object.is_file():
                pixmap_instance = QPixmap(str(poster_path_object))
                if not pixmap_instance.isNull():
                    self.poster_label.setPixmap(
                        pixmap_instance.scaled(
                            180,
                            260,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    pixmap_assigned = True

        if not pixmap_assigned:
            self.poster_label.clear()
            self.poster_label.setText("No Poster")

    @Slot()
    def _on_play_clicked(self) -> None:
        if self._current_movie_path:
            self.controller.playback_requested.emit(self._current_movie_path)
