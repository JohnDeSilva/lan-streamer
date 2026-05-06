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
    QTreeView,
    QCheckBox,
    QFileDialog,
)
from PySide6.QtGui import QAction, QStandardItemModel, QStandardItem
from PySide6.QtCore import Qt
from pathlib import Path

from .config import config
from .scanner import scan_directories, scan_series, clean_series_data
from .player import play_video
from .jellyfin import jellyfin_client
from . import db
from .delegates import PosterDelegate


class SeriesMatchDialog(QDialog):
    def __init__(self, series_name, parent=None):
        super().__init__(parent)
        self.series_name = series_name
        self.selected_series = None
        self.setWindowTitle(f"Match Series: {series_name}")
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

        # Initial search
        self.do_search()

    def do_search(self):
        self.results_list.clear()
        query = self.search_input.text().strip()
        if not query:
            return

        results = jellyfin_client.search_series_full(query)
        for item in results:
            display_name = item.get("Name", "Unknown")
            year = item.get("ProductionYear")
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


class JellyfinSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jellyfin Settings")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

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
        # Reset cached user ID so it's re-fetched with new credentials
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

        self.on_library_changed(self.library_combo.currentText())

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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lan Streamer")
        self.setMinimumSize(1000, 700)
        self.library = {}
        self.current_series = None

        self._setup_ui()
        self._setup_menu()
        self.refresh_libraries_combo()

    def _setup_menu(self):
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("Settings")

        manage_dirs_action = QAction("Manage Libraries...", self)
        manage_dirs_action.setMenuRole(QAction.MenuRole.NoRole)
        manage_dirs_action.triggered.connect(self.open_library_settings)
        settings_menu.addAction(manage_dirs_action)

        manage_jf_action = QAction("Jellyfin Settings...", self)
        manage_jf_action.setMenuRole(QAction.MenuRole.NoRole)
        manage_jf_action.triggered.connect(self.open_jellyfin_settings)
        settings_menu.addAction(manage_jf_action)

        refresh_action = QAction("Refresh Library (Scan Network)", self)
        refresh_action.triggered.connect(self.force_scan_library)
        settings_menu.addAction(refresh_action)

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
        self.unwatched_checkbox.stateChanged.connect(self.update_series_view)
        lib_selector_layout.addWidget(self.unwatched_checkbox)

        lib_selector_layout.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(
            ["Alphabetical", "Date Added (Newest)", "Date Added (Oldest)"]
        )
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

        top_bar.addWidget(self.back_button)
        top_bar.addWidget(self.detail_title, 1)
        detail_layout.addLayout(top_bar)

        self.tree_view = QTreeView()
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_model = QStandardItemModel()
        self.tree_view.setModel(self.tree_model)

        self.tree_view.doubleClicked.connect(self.on_tree_double_clicked)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.show_tree_context_menu)

        detail_layout.addWidget(self.tree_view)
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

    def open_jellyfin_settings(self):
        dialog = JellyfinSettingsDialog(self)
        dialog.exec()

    def load_library_ui(self):
        self.series_model.clear()
        self.go_back()

        library_name = self.main_library_combo.currentText()
        if not library_name:
            self.library = {}
            return

        self.library = db.load_library(library_name)

        self.update_series_view()

    def update_series_view(self):

        self.series_model.clear()

        filter_unwatched = self.unwatched_checkbox.isChecked()
        sort_mode = self.sort_combo.currentText()

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
            item = QStandardItem(series_name)
            poster_path = series_data.get("metadata", {}).get("poster_path")
            if poster_path:
                item.setData(poster_path, Qt.ItemDataRole.UserRole + 1)
            item.setData(series_name, Qt.ItemDataRole.UserRole)
            self.series_model.appendRow(item)

    def force_scan_library(self):
        library_name = self.main_library_combo.currentText()
        if not library_name:
            return

        root_dirs = config.libraries.get(library_name, [])
        if not root_dirs:
            return

        self.library = scan_directories(root_dirs)
        db.save_library(library_name, self.library)
        self.load_library_ui()

    def show_series_context_menu(self, position):
        index = self.series_view.indexAt(position)
        if not index.isValid():
            return
        item = self.series_model.itemFromIndex(index)
        series_name = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu()
        match_action = menu.addAction("Match Series...")

        action = menu.exec(self.series_view.viewport().mapToGlobal(position))
        if action == match_action:
            self.match_series_manually(series_name)

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

            # Re-scan this series with the selected Jellyfin metadata
            new_data = scan_series(series_path, jellyfin_series=selected)
            cleaned_data = clean_series_data(new_data)

            if cleaned_data:
                self.library[series_name] = cleaned_data
                db.save_library(library_name, self.library)
                self.update_series_view()
                QMessageBox.information(
                    self,
                    "Success",
                    f"Series '{series_name}' successfully matched to '{selected.get('Name')}'",
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
        self.detail_title.setText(series_name)

        self.tree_model.clear()

        seasons = self.library.get(series_name, {}).get("seasons", {})
        for season_name, season_data in sorted(seasons.items()):
            season_item = QStandardItem(season_name)
            season_item.setEditable(False)

            font = season_item.font()
            font.setBold(True)
            font.setPointSize(14)
            season_item.setFont(font)

            episodes = season_data.get("episodes", [])
            for episode in episodes:
                watched_indicator = "[✓] " if episode.get("watched") else "[ ] "
                episode_item = QStandardItem(f"{watched_indicator}{episode['name']}")
                episode_item.setEditable(False)
                episode_item.setData(episode, Qt.ItemDataRole.UserRole)
                season_item.appendRow(episode_item)

            self.tree_model.appendRow(season_item)

        self.tree_view.expandAll()
        self.stacked_widget.setCurrentIndex(1)

    def on_tree_double_clicked(self, index):
        item = self.tree_model.itemFromIndex(index)
        if not item:
            return
        episode_data = item.data(Qt.ItemDataRole.UserRole)
        if episode_data and episode_data.get("path"):
            try:
                play_video(episode_data["path"])
                self.toggle_watched_status(item, force_status=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not play video:\n{e}")

    def show_tree_context_menu(self, position):
        index = self.tree_view.indexAt(position)
        if not index.isValid():
            return
        item = self.tree_model.itemFromIndex(index)

        episode_data = item.data(Qt.ItemDataRole.UserRole)
        if not episode_data:
            return  # Probably a season row

        is_watched = episode_data.get("watched", False)
        menu = QMenu()
        action_text = "Mark as Unwatched" if is_watched else "Mark as Watched"
        toggle_action = menu.addAction(action_text)

        action = menu.exec(self.tree_view.viewport().mapToGlobal(position))
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

        watched_indicator = "[✓] " if new_status else "[ ] "
        item.setText(f"{watched_indicator}{episode_data['name']}")
        item.setData(episode_data, Qt.ItemDataRole.UserRole)
