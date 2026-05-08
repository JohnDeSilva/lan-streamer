from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QLabel,
    QPushButton,
    QInputDialog,
    QMessageBox,
    QDialog,
    QComboBox,
    QLineEdit,
    QFormLayout,
    QListView,
    QMenu,
    QStackedWidget,
    QCheckBox,
    QFileDialog,
)
from PySide6.QtGui import QAction, QStandardItemModel, QStandardItem
from PySide6.QtCore import Qt, QThread, Signal
from pathlib import Path
import logging

from .config import config
from .scanner import (
    scan_directories,
    scan_series,
    clean_series_data,
    _parse_episode_number,
)
from .player import play_video
from .jellyfin import jellyfin_client
from .tmdb import tmdb_client
from . import db
from .delegates import PosterDelegate

logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    """Scans a single library directory using TMDB for metadata."""

    finished = Signal(dict)
    partial_result = Signal(dict)
    error = Signal(str)

    def __init__(self, root_directories, existing_library, parent=None):
        super().__init__(parent)
        self.root_directories = root_directories
        self.existing_library = existing_library

    def run(self):
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
            )
            self.finished.emit(library)
        except Exception as e:
            self.error.emit(str(e))


class SyncAllWorker(QThread):
    """Rescans all libraries using TMDB for metadata (manual action only)."""

    finished = Signal()
    progress = Signal(str)
    error = Signal(str)

    def run(self):
        try:
            # Fetch Jellyfin correlation data if configured
            jellyfin_data = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            for library_name, root_dirs in config.libraries.items():
                self.progress.emit(f"Scanning library '{library_name}'...")
                existing_data = db.load_library(library_name)
                library = scan_directories(
                    root_dirs,
                    existing_library=existing_data,
                    jellyfin_data=jellyfin_data,
                )
                db.save_library(library_name, library)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class JellyfinPullWorker(QThread):
    """Pulls watch history from Jellyfin and syncs it to the local DB."""

    finished = Signal(int)  # number of episodes updated
    error = Signal(str)

    def run(self):
        try:
            watched_ids, watched_paths, watched_names = (
                jellyfin_client.fetch_watched_episodes()
            )
            updated = db.sync_watched_from_jellyfin_data(
                watched_ids, watched_paths, watched_names
            )
            self.finished.emit(updated)
        except Exception as e:
            self.error.emit(str(e))


class JellyfinPushWorker(QThread):
    """Pushes all local watched state to Jellyfin."""

    finished = Signal(int)  # number of episodes pushed
    error = Signal(str)

    def run(self):
        try:
            episodes = db.get_all_episodes_with_jellyfin_id()
            count = 0
            for ep in episodes:
                # We push whatever our local state is
                jellyfin_client.set_watched_status(
                    ep["jellyfin_id"], bool(ep["watched"])
                )
                count += 1
            self.finished.emit(count)
        except Exception as e:
            self.error.emit(str(e))


class SeriesMatchDialog(QDialog):
    """Manual match dialog — searches TMDB."""

    def __init__(self, series_name, parent=None):
        super().__init__(parent)
        self.series_name = series_name
        self.selected_series = None
        self.setWindowTitle(f"Match Series: {series_name}")
        self.setMinimumSize(500, 400)

        layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit(series_name)
        self.search_button = QPushButton("Search TMDB")
        self.search_button.clicked.connect(self.do_search)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_button)
        layout.addLayout(search_layout)

        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.results_list)

        buttons = QHBoxLayout()
        self.ok_button = QPushButton("Match Selected")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self.do_search()

    def do_search(self):
        self.results_list.clear()
        query = self.search_input.text().strip()
        if not query:
            return

        results = tmdb_client.search_series_full(query)
        for item in results:
            display_name = item.get("name", "Unknown")
            year = item.get("first_air_date", "")[:4]  # TMDB uses first_air_date
            if year:
                display_name += f" ({year})"

            from PySide6.QtWidgets import QListWidgetItem

            list_item = QListWidgetItem(display_name)
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self.results_list.addItem(list_item)

    def get_selected_series(self):
        current = self.results_list.currentItem()
        if current:
            return current.data(Qt.ItemDataRole.UserRole)
        return None


class JellyfinMatchDialog(QDialog):
    """Manual match dialog for Jellyfin — searches Jellyfin."""

    def __init__(self, series_name, parent=None):
        super().__init__(parent)
        self.series_name = series_name
        self.selected_series = None
        self.setWindowTitle(f"Match Jellyfin: {series_name}")
        self.setMinimumSize(500, 400)

        layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit(series_name)
        self.search_button = QPushButton("Search Jellyfin")
        self.search_button.clicked.connect(self.do_search)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_button)
        layout.addLayout(search_layout)

        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.results_list)

        buttons = QHBoxLayout()
        self.ok_button = QPushButton("Match Selected")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self.do_search()

    def do_search(self):
        self.results_list.clear()
        query = self.search_input.text().strip()
        if not query:
            return

        results = jellyfin_client.search_series(query)
        from PySide6.QtWidgets import QListWidgetItem

        for item in results:
            display_name = item.get("Name", "Unknown")
            year = item.get("ProductionYear", "")
            if year:
                display_name += f" ({year})"

            list_item = QListWidgetItem(display_name)
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self.results_list.addItem(list_item)

    def get_selected_series(self):
        current = self.results_list.currentItem()
        if current:
            return current.data(Qt.ItemDataRole.UserRole)
        return None


class TMDBSettingsDialog(QDialog):
    """Settings dialog for TMDB API key."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TMDB Settings")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # TMDB logo
        from pathlib import Path as _Path

        logo_path = _Path(__file__).parent / "assets" / "tmdb_logo.svg"
        if logo_path.exists():
            try:
                from PySide6.QtSvgWidgets import QSvgWidget

                logo = QSvgWidget(str(logo_path))
                logo.setFixedSize(120, 42)
                logo_row = QHBoxLayout()
                logo_row.addStretch()
                logo_row.addWidget(logo)
                logo_row.addStretch()
                layout.addLayout(logo_row)
            except Exception:
                pass  # SVG widget not available — skip logo silently

        desc = QLabel(
            'Get a free API key at <a href="https://www.themoviedb.org/settings/api">themoviedb.org/settings/api</a>'
        )
        desc.setOpenExternalLinks(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        form = QFormLayout()
        self.api_key_input = QLineEdit(config.tmdb_api_key)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Paste your TMDB API key here")
        form.addRow("TMDB API Key:", self.api_key_input)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self.test_connection)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_settings)
        button_row.addWidget(test_btn)
        button_row.addWidget(save_btn)
        layout.addLayout(button_row)

    def test_connection(self):
        key = self.api_key_input.text().strip()
        success, message = tmdb_client.validate_credentials(key)
        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.warning(self, "Connection Failed", message)

    def save_settings(self):
        config.tmdb_api_key = self.api_key_input.text().strip()
        config.save()
        QMessageBox.information(self, "Saved", "TMDB settings saved.")


class JellyfinSettingsDialog(QDialog):
    """Settings dialog for Jellyfin watch-history sync credentials."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jellyfin Settings (Watch History Sync)")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Used only for syncing watch history — not for metadata.")
        )

        jellyfin_layout = QFormLayout()
        self.jellyfin_url_input = QLineEdit(config.jellyfin_url)
        self.jellyfin_api_key_input = QLineEdit(config.jellyfin_api_key)
        self.jellyfin_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        jellyfin_layout.addRow("Jellyfin URL:", self.jellyfin_url_input)
        jellyfin_layout.addRow("API Key:", self.jellyfin_api_key_input)

        save_jellyfin_button = QPushButton("Save Jellyfin Settings")
        save_jellyfin_button.clicked.connect(self.save_jellyfin_settings)

        test_connection_button = QPushButton("Test Connection")
        test_connection_button.clicked.connect(self.test_connection)

        button_row = QHBoxLayout()
        button_row.addWidget(test_connection_button)
        button_row.addWidget(save_jellyfin_button)
        jellyfin_layout.addRow(button_row)

        layout.addLayout(jellyfin_layout)

    def test_connection(self):
        url = self.jellyfin_url_input.text().strip()
        api_key = self.jellyfin_api_key_input.text().strip()

        success, message = jellyfin_client.validate_credentials(url, api_key)
        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.warning(self, "Connection Failed", message)

    def save_jellyfin_settings(self):
        config.jellyfin_url = self.jellyfin_url_input.text().strip()
        config.jellyfin_api_key = self.jellyfin_api_key_input.text().strip()
        config.save()
        jellyfin_client._cached_user_id = None
        QMessageBox.information(self, "Saved", "Jellyfin settings saved.")


class LibrarySettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Library Settings")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        # Libraries Management
        library_layout = QHBoxLayout()
        self.library_combo = QComboBox()
        self.library_combo.addItems(list(config.libraries.keys()))
        self.library_combo.currentTextChanged.connect(self.on_library_changed)

        self.new_library_button = QPushButton("New Lib")
        self.new_library_button.clicked.connect(self.add_library)
        self.delete_library_button = QPushButton("Del Lib")
        self.delete_library_button.clicked.connect(self.remove_library)

        library_layout.addWidget(QLabel("Library:"))
        library_layout.addWidget(self.library_combo, 1)
        library_layout.addWidget(self.new_library_button)
        library_layout.addWidget(self.delete_library_button)
        layout.addLayout(library_layout)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        button_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Directory")
        self.add_button.clicked.connect(self.add_dir)
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.remove_dir)

        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        layout.addLayout(button_layout)

        self.sync_checkbox = QCheckBox("Sync Jellyfin watch history on startup")
        self.sync_checkbox.setChecked(config.sync_history_on_start)
        self.sync_checkbox.stateChanged.connect(self.on_sync_on_start_changed)
        layout.addWidget(self.sync_checkbox)

        self.on_library_changed(self.library_combo.currentText())

    def on_sync_on_start_changed(self, state):
        config.sync_history_on_start = self.sync_checkbox.isChecked()
        config.save()

    def on_library_changed(self, library_name):
        self.list_widget.clear()
        if library_name and library_name in config.libraries:
            for path in config.libraries[library_name]:
                self.list_widget.addItem(path)

    def add_library(self):
        name, ok = QInputDialog.getText(self, "New Library", "Enter library name:")
        if ok and name:
            if name in config.libraries:
                QMessageBox.warning(self, "Error", f"Library '{name}' already exists.")
            else:
                config.add_library(name)
                self.library_combo.addItem(name)
                self.library_combo.setCurrentText(name)

    def remove_library(self):
        name = self.library_combo.currentText()
        if name:
            reply = QMessageBox.question(self, "Confirm", f"Delete library '{name}'?")
            if reply == QMessageBox.StandardButton.Yes:
                config.remove_library(name)
                self.library_combo.removeItem(self.library_combo.findText(name))

    def add_dir(self):
        library_name = self.library_combo.currentText()
        if not library_name:
            QMessageBox.warning(self, "Error", "Create or select a library first.")
            return

        path = QFileDialog.getExistingDirectory(
            self, "Select Directory", "", QFileDialog.Option.ShowDirsOnly
        )
        if path:
            p = Path(path)
            if not p.exists() or not p.is_dir():
                QMessageBox.warning(self, "Error", f"Invalid directory:\n{path}")
            else:
                config.add_root_dir(library_name, path)
                self.list_widget.addItem(path)

    def remove_dir(self):
        library_name = self.library_combo.currentText()
        current_item = self.list_widget.currentItem()
        if current_item and library_name:
            path = current_item.text()
            config.remove_root_dir(library_name, path)
            self.list_widget.takeItem(self.list_widget.row(current_item))


class MainWindow(QMainWindow):
    def __init__(self, recreated_db=False):
        super().__init__()
        self.setWindowTitle("LAN Streamer")
        self.setMinimumSize(1000, 700)
        self.library = {}
        self.current_series = None

        self._setup_ui()
        self._setup_menu()
        self.refresh_libraries_combo()

        # Always pull Jellyfin watch history on startup (if configured)
        if config.sync_history_on_start and jellyfin_client.is_configured():
            self.pull_jellyfin_history()

    def _setup_menu(self):
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("Settings")

        manage_dirs_action = QAction("Manage Libraries...", self)
        manage_dirs_action.setMenuRole(QAction.MenuRole.NoRole)
        manage_dirs_action.triggered.connect(self.open_library_settings)
        settings_menu.addAction(manage_dirs_action)

        external_menu = settings_menu.addMenu("External Sources")

        manage_tmdb_action = QAction("TMDB Settings...", self)
        manage_tmdb_action.setMenuRole(QAction.MenuRole.NoRole)
        manage_tmdb_action.triggered.connect(self.open_tmdb_settings)
        external_menu.addAction(manage_tmdb_action)

        manage_jellyfin_action = QAction("Jellyfin Settings...", self)
        manage_jellyfin_action.setMenuRole(QAction.MenuRole.NoRole)
        manage_jellyfin_action.triggered.connect(self.open_jellyfin_settings)
        external_menu.addAction(manage_jellyfin_action)

        settings_menu.addSeparator()

        self.refresh_action = QAction("Check for New Files and Fetch Metadata", self)
        self.refresh_action.triggered.connect(self.force_scan_library)
        settings_menu.addAction(self.refresh_action)

        self.pull_action = QAction("Pull Watch History from Jellyfin", self)
        self.pull_action.triggered.connect(self.pull_jellyfin_history)
        settings_menu.addAction(self.pull_action)

        self.push_action = QAction("Push Watch History to Jellyfin", self)
        self.push_action.triggered.connect(self.push_jellyfin_history)
        settings_menu.addAction(self.push_action)

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)

        # Library Selector
        lib_selector_layout = QHBoxLayout()
        lib_selector_layout.addWidget(QLabel("Current Library:"))
        self.main_library_combo = QComboBox()
        self.main_library_combo.currentTextChanged.connect(self.on_main_library_changed)
        lib_selector_layout.addWidget(self.main_library_combo, 1)

        self.unwatched_checkbox = QCheckBox("Unwatched Only")
        self.unwatched_checkbox.setChecked(config.filter_unwatched)
        self.unwatched_checkbox.stateChanged.connect(self.update_series_view)
        lib_selector_layout.addWidget(self.unwatched_checkbox)

        lib_selector_layout.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(
            ["Alphabetical", "Date Added (Newest)", "Date Added (Oldest)"]
        )
        self.sort_combo.setCurrentText(config.sort_mode)
        self.sort_combo.currentTextChanged.connect(self.update_series_view)
        lib_selector_layout.addWidget(self.sort_combo)

        main_layout.addLayout(lib_selector_layout)

        # Stacked Widget
        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)

        # ---- VIEW 0: Series Grid ----
        self.home_view = QWidget()
        home_layout = QVBoxLayout(self.home_view)
        home_layout.setContentsMargins(0, 0, 0, 0)

        self.series_view = QListView()
        self.series_view.setViewMode(QListView.ViewMode.IconMode)
        self.series_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.series_view.setSpacing(20)
        self.series_view.setUniformItemSizes(True)
        self.series_view.setItemDelegate(PosterDelegate(self.series_view))

        self.series_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.series_view.customContextMenuRequested.connect(
            self.show_series_context_menu
        )

        self.series_model = QStandardItemModel()
        self.series_view.setModel(self.series_model)
        self.series_view.clicked.connect(self.on_series_selected)

        home_layout.addWidget(self.series_view)
        self.stacked_widget.addWidget(self.home_view)

        # ---- VIEW 1: Series Details ----
        self.detail_view = QWidget()
        detail_layout = QVBoxLayout(self.detail_view)
        detail_layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QHBoxLayout()
        self.back_button = QPushButton("← Back to Library")
        self.back_button.clicked.connect(self.go_back)
        self.detail_title = QLabel("")
        self.detail_title.setStyleSheet("font-size: 24px; font-weight: bold;")

        self.locked_checkbox = QCheckBox("Lock Metadata")
        self.locked_checkbox.setToolTip(
            "Prevent automatic metadata updates for this series"
        )
        self.locked_checkbox.stateChanged.connect(self.on_locked_metadata_changed)

        top_bar.addWidget(self.back_button)
        top_bar.addWidget(self.detail_title, 1)
        top_bar.addWidget(self.locked_checkbox)
        detail_layout.addLayout(top_bar)

        # Column View for Details
        column_layout = QHBoxLayout()
        detail_layout.addLayout(column_layout)

        # Seasons Column
        self.season_view = QListView()
        self.season_view.setFixedWidth(200)
        self.season_model = QStandardItemModel()
        self.season_view.setModel(self.season_model)
        self.season_view.clicked.connect(self.on_season_selected)
        self.season_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.season_view.customContextMenuRequested.connect(
            self.show_season_context_menu
        )
        column_layout.addWidget(self.season_view)

        # Episodes Column
        self.episode_view = QListView()
        self.episode_model = QStandardItemModel()
        self.episode_view.setModel(self.episode_model)
        self.episode_view.doubleClicked.connect(self.on_episode_double_clicked)
        self.episode_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.episode_view.customContextMenuRequested.connect(
            self.show_episode_context_menu
        )
        column_layout.addWidget(self.episode_view)
        self.stacked_widget.addWidget(self.detail_view)

    def refresh_libraries_combo(self):
        current = self.main_library_combo.currentText()
        self.main_library_combo.blockSignals(True)
        self.main_library_combo.clear()
        self.main_library_combo.addItems(list(config.libraries.keys()))
        if current in config.libraries:
            self.main_library_combo.setCurrentText(current)
        elif config.libraries:
            self.main_library_combo.setCurrentIndex(0)
        self.main_library_combo.blockSignals(False)
        self.on_main_library_changed(self.main_library_combo.currentText())

    def on_main_library_changed(self, library_name):
        self.load_library_ui()

    def open_library_settings(self):
        dialog = LibrarySettingsDialog(self)
        dialog.exec()
        self.refresh_libraries_combo()

    def open_tmdb_settings(self):
        dialog = TMDBSettingsDialog(self)
        dialog.exec()

    def open_jellyfin_settings(self):
        dialog = JellyfinSettingsDialog(self)
        dialog.exec()

    def load_library_ui(self, stay_on_current=False):
        if not stay_on_current:
            self.go_back()

        library_name = self.main_library_combo.currentText()
        if not library_name:
            self.library = {}
            return

        self.library = db.load_library(library_name)

        self.update_series_view()
        if stay_on_current and self.current_series:
            self._refresh_detail_view()

    def update_series_view(self):

        self.series_model.clear()

        filter_unwatched = self.unwatched_checkbox.isChecked()
        sort_mode = self.sort_combo.currentText()

        # Update persistence
        if config.filter_unwatched != filter_unwatched or config.sort_mode != sort_mode:
            config.filter_unwatched = filter_unwatched
            config.sort_mode = sort_mode
            config.save()

        series_list = []
        for series_name, series_data in self.library.items():
            has_unwatched = False

            for season_data in series_data.get("seasons", {}).values():
                for episode in season_data.get("episodes", []):
                    if not episode.get("watched"):
                        has_unwatched = True
                        break
                if has_unwatched:
                    break

            if filter_unwatched and not has_unwatched:
                continue

            if "max_ctime" not in series_data:
                max_ctime = 0
                for season_data in series_data.get("seasons", {}).values():
                    for episode in season_data.get("episodes", []):
                        ctime = episode.get("date_added", 0)
                        if ctime > max_ctime:
                            max_ctime = ctime
                series_data["max_ctime"] = max_ctime

            series_list.append((series_name, series_data, series_data["max_ctime"]))

        if sort_mode == "Alphabetical":
            series_list.sort(key=lambda x: x[0])
        elif sort_mode == "Date Added (Newest)":
            series_list.sort(key=lambda x: x[2], reverse=True)
        elif sort_mode == "Date Added (Oldest)":
            series_list.sort(key=lambda x: x[2])

        for series_name, series_data, _ in series_list:
            display_name = (
                series_data.get("metadata", {}).get("tmdb_name") or series_name
            )
            item = QStandardItem(display_name)
            poster_path = series_data.get("metadata", {}).get("poster_path")
            if poster_path:
                item.setData(poster_path, Qt.ItemDataRole.UserRole + 1)
            item.setData(series_name, Qt.ItemDataRole.UserRole)
            self.series_model.appendRow(item)

    def force_scan_library(self):
        library_name = self.main_library_combo.currentText()
        if not library_name:
            return

        root_directories = config.libraries.get(library_name, [])
        if not root_directories:
            return

        # Disable UI elements that shouldn't be clicked during scan
        self.statusBar().showMessage(
            f"Scanning library '{library_name}'... Please wait."
        )
        self.refresh_action.setEnabled(False)

        # Start the background worker
        worker = ScanWorker(root_directories, self.library)
        worker.partial_result.connect(self.on_scan_partial_update)
        worker.finished.connect(self.on_scan_finished)
        worker.error.connect(self.on_scan_error)
        # Ensure the worker is deleted when it's done
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.start()
        self.scan_worker = worker

    def on_scan_partial_update(self, partial_library_data):
        library_name = self.main_library_combo.currentText()
        if not library_name:
            return

        # Merge partial data into current library
        self.library.update(partial_library_data)
        db.save_library(library_name, self.library)

        # Refresh UI but stay on current view
        self.update_series_view()
        if self.current_series:
            self._refresh_detail_view()

    def on_scan_finished(self, new_library_data):
        library_name = self.main_library_combo.currentText()
        self.library = new_library_data
        db.save_library(library_name, self.library)
        self.load_library_ui(stay_on_current=True)

        self.statusBar().showMessage(f"Scan complete for '{library_name}'.", 5000)
        self.refresh_action.setEnabled(True)

        # Trigger history pull after scan to catch new episodes
        if jellyfin_client.is_configured():
            self.statusBar().showMessage("Pulling watch history from Jellyfin...")
            self.pull_worker = JellyfinPullWorker()
            self.pull_worker.finished.connect(
                lambda updated: self.statusBar().showMessage(
                    f"History pull complete: {updated} updated.", 5000
                )
            )
            self.pull_worker.finished.connect(
                lambda: self.load_library_ui(stay_on_current=True)
            )
            self.pull_worker.finished.connect(self.pull_worker.deleteLater)
            self.pull_worker.start()

    def sync_all_libraries(self):
        self.statusBar().showMessage("Scanning all libraries (TMDB)... Please wait.")
        self.refresh_action.setEnabled(False)

        self.sync_worker = SyncAllWorker()
        self.sync_worker.progress.connect(lambda msg: self.statusBar().showMessage(msg))
        self.sync_worker.finished.connect(self.on_sync_all_finished)
        self.sync_worker.error.connect(self.on_scan_error)
        self.sync_worker.finished.connect(self.sync_worker.deleteLater)
        self.sync_worker.error.connect(self.sync_worker.deleteLater)
        self.sync_worker.start()

    def on_sync_all_finished(self):
        self.load_library_ui(stay_on_current=True)
        self.statusBar().showMessage("Library scan complete.", 5000)
        self.refresh_action.setEnabled(True)

        # Trigger history pull after scan to catch new episodes
        if jellyfin_client.is_configured():
            self.statusBar().showMessage("Pulling watch history from Jellyfin...")
            self.pull_worker = JellyfinPullWorker()
            self.pull_worker.finished.connect(
                lambda updated: self.statusBar().showMessage(
                    f"History pull complete: {updated} updated.", 5000
                )
            )
            self.pull_worker.finished.connect(
                lambda: self.load_library_ui(stay_on_current=True)
            )
            self.pull_worker.finished.connect(self.pull_worker.deleteLater)
            self.pull_worker.start()

    def pull_jellyfin_history(self):
        """Pulls Jellyfin watch history and updates local DB watched flags."""
        self.statusBar().showMessage("Pulling watch history from Jellyfin...")
        if hasattr(self, "pull_action"):
            self.pull_action.setEnabled(False)

        self.pull_worker = JellyfinPullWorker()
        self.pull_worker.finished.connect(self.on_pull_finished)
        self.pull_worker.error.connect(self.on_scan_error)
        self.pull_worker.finished.connect(self.pull_worker.deleteLater)
        self.pull_worker.error.connect(self.pull_worker.deleteLater)
        self.pull_worker.start()

    def on_pull_finished(self, updated_count):
        self.load_library_ui(stay_on_current=True)
        msg = f"Jellyfin history pull complete. {updated_count} episodes updated."
        self.statusBar().showMessage(msg, 5000)
        logger.info(msg)
        if hasattr(self, "pull_action"):
            self.pull_action.setEnabled(True)

    def push_jellyfin_history(self):
        """Pushes local watched flags to Jellyfin."""
        self.statusBar().showMessage("Pushing watch history to Jellyfin...")
        if hasattr(self, "push_action"):
            self.push_action.setEnabled(False)

        self.push_worker = JellyfinPushWorker()
        self.push_worker.finished.connect(self.on_push_finished)
        self.push_worker.error.connect(self.on_scan_error)
        self.push_worker.finished.connect(self.push_worker.deleteLater)
        self.push_worker.error.connect(self.push_worker.deleteLater)
        self.push_worker.start()

    def on_push_finished(self, count):
        msg = f"Jellyfin history push complete. {count} items processed."
        self.statusBar().showMessage(msg, 5000)
        logger.info(msg)
        if hasattr(self, "push_action"):
            self.push_action.setEnabled(True)

    def on_history_sync_error(self, error_msg: str):
        self.statusBar().showMessage(f"History sync failed: {error_msg}", 5000)
        if hasattr(self, "history_sync_action"):
            self.history_sync_action.setEnabled(True)

    def on_scan_error(self, error_msg):
        self.statusBar().showMessage(f"Scan failed: {error_msg}", 5000)
        self.refresh_action.setEnabled(True)
        QMessageBox.critical(
            self, "Scan Error", f"An error occurred during scanning:\n{error_msg}"
        )

    def show_series_context_menu(self, position):
        index = self.series_view.indexAt(position)
        if not index.isValid():
            return
        item = self.series_model.itemFromIndex(index)
        series_name = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu()
        match_action = menu.addAction("Match Series (TMDB)...")
        jellyfin_action = menu.addAction("Match Jellyfin (Watch History)...")

        action = menu.exec(self.series_view.viewport().mapToGlobal(position))
        if action == match_action:
            self.match_series_manually(series_name)
        elif action == jellyfin_action:
            self.match_jellyfin_manually(series_name)

    def match_jellyfin_manually(self, series_name):
        dialog = JellyfinMatchDialog(series_name, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.get_selected_series()
            if not selected:
                return

            library_name = self.main_library_combo.currentText()
            if not library_name:
                return

            jellyfin_id = selected.get("Id")
            if not jellyfin_id:
                return

            # Update local library cache and database
            if series_name in self.library:
                self.library[series_name]["metadata"]["jellyfin_id"] = jellyfin_id

                # Fetch episodes for this series from Jellyfin to sync watch history immediately
                self.statusBar().showMessage(
                    f"Syncing watch history for '{series_name}'..."
                )
                logger.info(
                    f"Manual Jellyfin match for '{series_name}' (ID: {jellyfin_id}). Fetching episodes for correlation..."
                )
                jf_episodes = jellyfin_client.get_series_episodes(jellyfin_id)
                logger.info(
                    f"Fetched {len(jf_episodes)} episodes from Jellyfin for '{series_name}'."
                )

                # Build maps for correlation (Season/Episode and Name)
                jf_map = {}
                jf_name_map = {}
                for item in jf_episodes:
                    s_num = item.get("ParentIndexNumber")
                    e_num = item.get("IndexNumber")
                    if s_num is not None and e_num is not None:
                        jf_map[(s_num, e_num)] = item

                    name = item.get("Name", "").lower()
                    if name:
                        jf_name_map[name] = item

                # Update episodes in local library
                updated_count = 0
                for season_name, season_data in (
                    self.library[series_name].get("seasons", {}).items()
                ):
                    for episode in season_data.get("episodes", []):
                        # Try to correlate
                        parsed = _parse_episode_number(episode["name"])
                        jf_item = None
                        if parsed:
                            jf_item = jf_map.get(parsed)

                        if not jf_item:
                            # Try by name (without extension)
                            stem = Path(episode["name"]).stem.lower()
                            jf_item = jf_name_map.get(stem)

                        if jf_item:
                            episode["jellyfin_id"] = jf_item.get("Id", "")
                            # Sync watched status
                            is_played = jf_item.get("UserData", {}).get("Played", False)
                            logger.debug(
                                f"Correlated '{episode['name']}' -> Jellyfin ID {episode['jellyfin_id']} (Watched: {is_played})"
                            )
                            if episode.get("watched") != is_played:
                                episode["watched"] = is_played
                                db.update_episode_watched_status(
                                    episode["path"], is_played
                                )
                                updated_count += 1

                db.save_library(library_name, self.library)
                self.statusBar().showMessage(
                    f"Series '{series_name}' linked. {updated_count} episodes updated.",
                    5000,
                )
                self.load_library_ui(stay_on_current=True)

    def match_series_manually(self, series_name):
        dialog = SeriesMatchDialog(series_name, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.get_selected_series()
            if not selected:
                return

            library_name = self.main_library_combo.currentText()
            if not library_name:
                return

            # Find the path of the series directory
            series_path = None
            root_dirs = config.libraries.get(library_name, [])
            for root in root_dirs:
                potential_path = Path(root) / series_name
                if potential_path.exists() and potential_path.is_dir():
                    series_path = potential_path
                    break

            if not series_path:
                QMessageBox.warning(
                    self, "Error", f"Could not find local directory for '{series_name}'"
                )
                return

            # Re-scan with the selected TMDB series
            new_data = scan_series(series_path, tmdb_series=selected)
            cleaned_data = clean_series_data(new_data)

            if cleaned_data:
                cleaned_data["metadata"]["is_manual_match"] = True
                self.library[series_name] = cleaned_data
                db.save_library(library_name, self.library)
                self.update_series_view()
                QMessageBox.information(
                    self,
                    "Success",
                    f"Series '{series_name}' matched to '{selected.get('name')}'",
                )

    def go_back(self):
        self.stacked_widget.setCurrentIndex(0)
        self.current_series = None

    def on_series_selected(self, index):
        item = self.series_model.itemFromIndex(index)
        if not item:
            return

        series_name = item.data(Qt.ItemDataRole.UserRole)
        self.current_series = series_name
        self._refresh_detail_view()
        self.stacked_widget.setCurrentIndex(1)

    def _refresh_detail_view(self):
        if not self.current_series:
            return

        series_name = self.current_series
        series_data = self.library.get(series_name, {})
        display_name = series_data.get("metadata", {}).get("tmdb_name") or series_name
        self.detail_title.setText(display_name)

        # Store currently selected season to restore it if possible
        selected_season_name = None
        current_season_index = self.season_view.currentIndex()
        if current_season_index.isValid():
            selected_season_name = self.season_model.itemFromIndex(
                current_season_index
            ).text()

        self.season_model.clear()
        self.episode_model.clear()

        seasons = series_data.get("seasons", {})
        sorted_season_names = sorted(seasons.keys(), key=db.natural_sort_key)

        restore_index = None
        for i, season_name in enumerate(sorted_season_names):
            season_item = QStandardItem(season_name)
            season_item.setEditable(False)
            season_item.setData(seasons[season_name], Qt.ItemDataRole.UserRole)
            self.season_model.appendRow(season_item)
            if selected_season_name == season_name:
                restore_index = self.season_model.index(i, 0)

        # Update locked metadata checkbox
        series_metadata = series_data.get("metadata", {})
        self.locked_checkbox.blockSignals(True)
        self.locked_checkbox.setChecked(series_metadata.get("locked_metadata", False))
        self.locked_checkbox.blockSignals(False)

        # Restore season selection or select first
        if restore_index:
            self.season_view.setCurrentIndex(restore_index)
            self.on_season_selected(restore_index)
        elif self.season_model.rowCount() > 0:
            first_index = self.season_model.index(0, 0)
            self.season_view.setCurrentIndex(first_index)
            self.on_season_selected(first_index)

    def show_season_context_menu(self, position):
        index = self.season_view.indexAt(position)
        if not index.isValid():
            return
        item = self.season_model.itemFromIndex(index)
        season_name = item.text()
        season_data = item.data(Qt.ItemDataRole.UserRole)

        # Check if all episodes are watched to determine the primary action
        all_watched = all(
            ep.get("watched", False) for ep in season_data.get("episodes", [])
        )

        menu = QMenu()
        action_text = "Mark all as Unwatched" if all_watched else "Mark all as Watched"
        toggle_action = menu.addAction(action_text)

        action = menu.exec(self.season_view.viewport().mapToGlobal(position))
        if action == toggle_action:
            self.toggle_season_watched_status(season_name, not all_watched)

    def toggle_season_watched_status(self, season_name, watched):
        if not self.current_series:
            return

        library_name = self.main_library_combo.currentText()
        if not library_name:
            return

        # Update database
        db.update_season_watched_status(
            library_name, self.current_series, season_name, watched
        )

        # Update Jellyfin if configured
        series_data = self.library.get(self.current_series, {})
        season_data = series_data.get("seasons", {}).get(season_name, {})
        season_jellyfin_id = season_data.get("metadata", {}).get("jellyfin_id")

        if season_jellyfin_id and jellyfin_client.is_configured():
            jellyfin_client.set_watched_status(season_jellyfin_id, watched)

        # Refresh local cache and UI
        self.load_library_ui(stay_on_current=True)

    def on_season_selected(self, index):
        item = self.season_model.itemFromIndex(index)
        if not item or not self.current_series:
            return

        season_name = item.text()
        self.episode_model.clear()

        seasons = self.library.get(self.current_series, {}).get("seasons", {})
        season_data = seasons.get(season_name, {})
        episodes = sorted(
            season_data.get("episodes", []),
            key=lambda x: db.natural_sort_key(x["name"]),
        )

        for episode in episodes:
            display_text = self._format_episode_display(episode)
            episode_item = QStandardItem(display_text)
            episode_item.setEditable(False)
            episode_item.setData(episode, Qt.ItemDataRole.UserRole)
            self.episode_model.appendRow(episode_item)

    def on_locked_metadata_changed(self, state):
        if not self.current_series:
            return

        is_locked = state == Qt.CheckState.Checked.value
        library_name = self.main_library_combo.currentText()
        if not library_name:
            return

        if self.current_series in self.library:
            self.library[self.current_series]["metadata"]["locked_metadata"] = is_locked
            db.save_library(library_name, self.library)
            logger.info(
                f"Updated locked_metadata for '{self.current_series}' to {is_locked}"
            )

    def _format_episode_display(self, episode_data: dict) -> str:
        watched_indicator = "[✓] " if episode_data.get("watched") else "[ ] "
        tmdb_num = episode_data.get("tmdb_number")
        tmdb_name = episode_data.get("tmdb_name")

        if tmdb_num is not None and tmdb_name:
            return f"{watched_indicator}{tmdb_num}. {tmdb_name}"
        return f"{watched_indicator}{episode_data['name']}"

    def on_episode_double_clicked(self, index):
        item = self.episode_model.itemFromIndex(index)
        if not item:
            return
        episode_data = item.data(Qt.ItemDataRole.UserRole)
        if episode_data and episode_data.get("path"):
            try:
                play_video(episode_data["path"])
                self.toggle_watched_status(item, force_status=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not play video:\n{e}")

    def show_episode_context_menu(self, position):
        index = self.episode_view.indexAt(position)
        if not index.isValid():
            return
        item = self.episode_model.itemFromIndex(index)

        episode_data = item.data(Qt.ItemDataRole.UserRole)
        if not episode_data:
            return

        is_watched = episode_data.get("watched", False)
        menu = QMenu()
        action_text = "Mark as Unwatched" if is_watched else "Mark as Watched"
        toggle_action = menu.addAction(action_text)

        action = menu.exec(self.episode_view.viewport().mapToGlobal(position))
        if action == toggle_action:
            self.toggle_watched_status(item, force_status=not is_watched)

    def toggle_watched_status(self, item: QStandardItem, force_status: bool = None):
        episode_data = item.data(Qt.ItemDataRole.UserRole)
        if not episode_data:
            return

        new_status = (
            force_status
            if force_status is not None
            else not episode_data.get("watched", False)
        )

        episode_data["watched"] = new_status
        db.update_episode_watched_status(episode_data["path"], new_status)

        if episode_data.get("jellyfin_id"):
            jellyfin_client.set_watched_status(episode_data["jellyfin_id"], new_status)

        display_text = self._format_episode_display(episode_data)
        item.setText(display_text)
        item.setData(episode_data, Qt.ItemDataRole.UserRole)
