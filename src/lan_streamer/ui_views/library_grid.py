import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QComboBox,
    QCheckBox,
    QScrollArea,
    QFrame,
    QTabBar,
    QDialog,
)
from PySide6.QtCore import Qt, Slot, QSize
from PySide6.QtGui import QIcon, QColor
from lan_streamer.ui_views.proxy import QPixmap

from lan_streamer.system.config import config
from lan_streamer import db
from lan_streamer.ui_views.progress_widgets import LibraryScanProgressBar
from lan_streamer.ui_views.dialogs import SettingsDialog, SearchDialog
from lan_streamer.ui_views.controller import Controller

logger = logging.getLogger(__name__)


class LibraryGridView(QWidget):
    """
    Responsive Grid View displaying series items using custom layout sizing.
    Conforms strictly to zero-abbreviation variable naming and typing requirements.
    """

    def __init__(
        self, controller_instance: Controller, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.controller: Controller = controller_instance
        self.series_list_widget: QListWidget = QListWidget()
        self.library_tab_bar: QTabBar = QTabBar()
        self.library_selector: QComboBox = QComboBox(self)
        self.library_selector.hide()
        self.library_names_list: List[str] = []
        self.sort_label: QLabel = QLabel("Sort By:")
        self.sort_selector: QComboBox = QComboBox()
        self.order_label: QLabel = QLabel("Order:")
        self.order_selector: QComboBox = QComboBox()
        self.sort_order_container: QWidget = QWidget()
        self.filter_watched_checkbox: QCheckBox = QCheckBox("Hide Watched")
        self.cached_icons: Dict[str, QIcon] = {}
        self._last_order_mode: Optional[str] = None
        self.scan_progress_bar: LibraryScanProgressBar = LibraryScanProgressBar()
        self.scan_status_label: QLabel = QLabel()
        self._smart_row_widgets: Dict[str, QWidget] = {}

        self._setup_ui()
        self._wire_signals()

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Top Filters Row
        top_toolbar_layout: QHBoxLayout = QHBoxLayout()
        top_toolbar_layout.setSpacing(10)

        self.library_tab_bar.setDrawBase(False)
        top_toolbar_layout.addWidget(self.library_tab_bar)

        # Sort & Order Container to easily hide them in Combined View
        sort_order_layout: QHBoxLayout = QHBoxLayout(self.sort_order_container)
        sort_order_layout.setContentsMargins(15, 0, 15, 0)
        sort_order_layout.setSpacing(10)

        sort_order_layout.addWidget(self.sort_label)
        self.sort_selector.addItems(
            ["Alphabetical", "Recently Added", "Recently Aired", "Next Up"]
        )
        self.sort_selector.setCurrentText(self.controller.sort_mode)
        sort_order_layout.addWidget(self.sort_selector)

        sort_order_layout.addWidget(self.order_label)
        sort_order_layout.addWidget(self.order_selector)

        top_toolbar_layout.addWidget(self.sort_order_container)

        self.filter_watched_checkbox.setChecked(self.controller.filter_out_watched)
        top_toolbar_layout.addWidget(self.filter_watched_checkbox)

        top_toolbar_layout.addStretch()

        search_button: QPushButton = QPushButton("Search")
        search_button.setObjectName("searchSeriesButton")
        search_button.clicked.connect(self._open_search_dialog)
        top_toolbar_layout.addWidget(search_button)

        settings_button: QPushButton = QPushButton("Settings...")
        settings_button.setObjectName("openSettingsButton")
        settings_button.clicked.connect(self.open_settings_dialog)
        top_toolbar_layout.addWidget(settings_button)

        main_layout.addLayout(top_toolbar_layout)

        # Bottom Actions Row
        self.actions_toolbar_widget = QWidget()
        actions_toolbar_layout: QHBoxLayout = QHBoxLayout(self.actions_toolbar_widget)
        actions_toolbar_layout.setContentsMargins(0, 0, 0, 0)
        actions_toolbar_layout.setSpacing(10)

        scan_button: QPushButton = QPushButton("Scan Library")
        scan_button.setToolTip(
            "Scan for new files and update paths for moved or deleted episodes"
        )
        scan_button.clicked.connect(
            lambda: self.controller.trigger_scan_and_update(False)
        )
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

        actions_toolbar_layout.addStretch()
        main_layout.addWidget(self.actions_toolbar_widget)

        # Combined Actions Row
        self.combined_actions_toolbar_widget: QWidget = QWidget()
        combined_actions_toolbar_layout: QHBoxLayout = QHBoxLayout(
            self.combined_actions_toolbar_widget
        )
        combined_actions_toolbar_layout.setContentsMargins(0, 0, 0, 0)
        combined_actions_toolbar_layout.setSpacing(10)

        combined_scan_button: QPushButton = QPushButton("Scan Library")
        combined_scan_button.setToolTip(
            "Scan for new files and update paths for moved or deleted episodes"
        )
        combined_scan_button.clicked.connect(self.trigger_combined_scan)
        combined_actions_toolbar_layout.addWidget(combined_scan_button)

        combined_actions_toolbar_layout.addStretch()
        self.combined_actions_toolbar_widget.setVisible(False)
        main_layout.addWidget(self.combined_actions_toolbar_widget)

        # Series Responsive List/Grid Widget
        self.series_list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.series_list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.series_list_widget.setSpacing(15)
        self.series_list_widget.setIconSize(QSize(160, 220))
        self.series_list_widget.setGridSize(QSize(190, 280))
        self.series_list_widget.setMovement(QListWidget.Movement.Static)

        main_layout.addWidget(self.series_list_widget)

        # Combined View Scroll Area
        self.combined_scroll_area: QScrollArea = QScrollArea()
        self.combined_scroll_area.setWidgetResizable(True)
        self.combined_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.combined_scroll_area.setVisible(False)
        self.combined_scroll_content = QWidget()
        self.combined_scroll_layout = QVBoxLayout(self.combined_scroll_content)
        self.combined_scroll_layout.setSpacing(25)
        self.combined_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.combined_scroll_area.setWidget(self.combined_scroll_content)
        main_layout.addWidget(self.combined_scroll_area)

        # Add status label and progress bar at the very bottom
        self.scan_status_label.setStyleSheet(
            "font-weight: bold; color: #f3f4f6; font-size: 13px;"
        )
        self.scan_status_label.setVisible(False)
        main_layout.addWidget(self.scan_status_label)

        self.scan_progress_bar.setVisible(False)
        main_layout.addWidget(self.scan_progress_bar)

    def _wire_signals(self) -> None:
        self.controller.library_loaded.connect(self.populate_grid)
        self.library_tab_bar.currentChanged.connect(self.on_library_tab_changed)
        self.library_selector.currentTextChanged.connect(self._on_selector_text_changed)
        self.sort_selector.currentTextChanged.connect(self.controller.set_sort_mode)
        self.order_selector.currentTextChanged.connect(self.on_order_changed)
        self.filter_watched_checkbox.toggled.connect(
            self.controller.set_filter_out_watched
        )
        self.series_list_widget.itemClicked.connect(self.on_item_clicked)
        self.controller.detail_progress_updated.connect(self._on_detail_progress)
        self.controller.scan_completed.connect(self._on_scan_completed)
        self.controller.smart_rows_updated.connect(self._on_smart_rows_updated)

    @Slot(str, dict)
    def _on_detail_progress(self, event: str, payload: Dict[str, Any]) -> None:
        root = payload.get("root", "")
        folder = payload.get("folder", "")
        if event == "init_library_scan":
            roots = payload.get("roots", {})
            roots_order = payload.get("roots_order", [])
            self.scan_progress_bar.init_from_roots(roots, roots_order)
            self.scan_progress_bar.setVisible(True)
            self.scan_status_label.setText("Starting library scan...")
            self.scan_status_label.setVisible(True)
        elif event == "init_tree":
            roots_dict: Dict[str, List[str]] = {}
            roots_order: List[str] = []
            tree = payload.get("tree", {})
            library_order = payload.get("library_order") or list(
                config.libraries.keys()
            )
            for lib_name in library_order:
                if lib_name in tree:
                    lib_data = tree[lib_name]
                    raw_roots = lib_data.get("roots", {})
                    config_paths = config.libraries.get(lib_name, {}).get("paths", [])
                    ordered_roots = []
                    for path in config_paths:
                        if path in raw_roots:
                            ordered_roots.append(path)
                    for path in raw_roots.keys():
                        if path not in ordered_roots:
                            ordered_roots.append(path)

                    for root_dir in ordered_roots:
                        folders_dict = raw_roots[root_dir]
                        roots_order.append(root_dir)
                        roots_dict[root_dir] = list(folders_dict.keys())
            self.scan_progress_bar.init_from_roots(roots_dict, roots_order)
            self.scan_progress_bar.setVisible(True)
            self.scan_status_label.setText("Starting global library scan...")
            self.scan_status_label.setVisible(True)
        elif event == "start_folder":
            self.scan_progress_bar.mark_folder_active(root, folder)
            library_name: str = payload.get("library", "")
            library_prefix: str = f" [{library_name}]" if library_name else ""
            self.scan_status_label.setText(
                f"Scanning{library_prefix}: {root} > {folder}"
            )
            self.scan_status_label.setVisible(True)
        elif event == "finish_folder":
            self.scan_progress_bar.mark_folder_done(root, folder)

        elif event == "finish_library":
            library_name: str = payload.get("library", "")
            self.scan_progress_bar.mark_library_done(library_name)

        elif event == "fail_library":
            library_name: str = payload.get("library", "")
            self.scan_progress_bar.mark_library_failed(library_name)

        elif event == "start_offline_scan":
            self.scan_progress_bar.set_current_pass(1)
            self.scan_status_label.setText("Starting offline scan (Pass 1 of 3)...")
            self.scan_status_label.setVisible(True)

        elif event == "start_metadata_resolution":
            self.scan_progress_bar.set_current_pass(2)
            self.scan_status_label.setText(
                "Starting metadata resolution (Pass 2 of 3)..."
            )
            self.scan_status_label.setVisible(True)

        elif event == "runtime_extraction_progress":
            completed = payload.get("completed", 0)
            total = payload.get("total", 0)
            self.scan_progress_bar.set_pass3_progress(completed, total)
            self.scan_status_label.setText(
                f"Extracting video runtimes: {completed}/{total} (Pass 3 of 3)..."
            )
            self.scan_status_label.setVisible(True)
            self.scan_progress_bar.setVisible(True)

    @Slot()
    def _on_scan_completed(self) -> None:
        self.scan_progress_bar.setVisible(False)
        self.scan_status_label.setVisible(False)

    def _on_selector_text_changed(self, text: str) -> None:
        if text in self.library_names_list:
            idx = self.library_names_list.index(text)
            self.library_tab_bar.blockSignals(True)
            self.library_tab_bar.setCurrentIndex(idx)
            self.library_tab_bar.blockSignals(False)
            self.on_library_changed(text)

    @Slot(int)
    def on_library_tab_changed(self, index: int) -> None:
        if 0 <= index < len(self.library_names_list):
            library_name = self.library_names_list[index]
            self.library_selector.blockSignals(True)
            self.library_selector.setCurrentText(library_name)
            self.library_selector.blockSignals(False)
            self.on_library_changed(library_name)

    def populate_libraries(self, library_names: List[str]) -> None:
        self.library_selector.blockSignals(True)
        self.library_selector.clear()
        self.library_tab_bar.blockSignals(True)
        while self.library_tab_bar.count() > 0:
            self.library_tab_bar.removeTab(0)

        self.library_names_list = []
        if config.enable_combined_view:
            self.library_names_list.append("Combined View")
        self.library_names_list.extend(library_names)

        for name in self.library_names_list:
            self.library_tab_bar.addTab(name)
            self.library_selector.addItem(name)

        current = self.controller.current_library_name
        if current and current in self.library_names_list:
            idx = self.library_names_list.index(current)
            self.library_tab_bar.setCurrentIndex(idx)
            self.library_selector.setCurrentText(current)
            self.on_library_changed(current)
        else:
            if self.library_names_list:
                self.library_tab_bar.setCurrentIndex(0)
                self.library_selector.setCurrentText(self.library_names_list[0])
                self.on_library_changed(self.library_names_list[0])
        self.library_tab_bar.blockSignals(False)
        self.library_selector.blockSignals(False)

    @Slot()
    def open_settings_dialog(self) -> None:
        config.load()
        old_library_paths = {
            lib_name: list(lib_info.get("paths", []))
            for lib_name, lib_info in config.libraries.items()
        }
        dialog_instance = SettingsDialog(self.controller, self)
        if dialog_instance.exec() == QDialog.DialogCode.Accepted:
            new_library_paths = {
                lib_name: list(lib_info.get("paths", []))
                for lib_name, lib_info in config.libraries.items()
            }
            new_paths_added = False
            current_library_paths_added = False
            current_library = self.controller.current_library_name

            for lib_name, new_paths in new_library_paths.items():
                old_paths = old_library_paths.get(lib_name, [])
                added_for_this_lib = any(path not in old_paths for path in new_paths)
                if added_for_this_lib:
                    new_paths_added = True
                    if lib_name == current_library:
                        current_library_paths_added = True

            self.populate_libraries(list(config.libraries.keys()))

            if new_paths_added:
                if current_library_paths_added and current_library != "Combined View":
                    logger.info(
                        f"New path added to current library '{current_library}'. Triggering auto-scan..."
                    )
                    self.controller.trigger_scan_and_update(False)
                else:
                    logger.info(
                        "New path added to a library. Triggering scan all libraries..."
                    )
                    self.controller.trigger_scan_all(False)
        else:
            config.load()
            self.populate_libraries(list(config.libraries.keys()))

    @Slot(str)
    def on_library_changed(self, library_name: str) -> None:
        if library_name == "Combined View":
            self.controller.current_library_name = "Combined View"
            self.series_list_widget.setVisible(False)
            if hasattr(self, "actions_toolbar_widget"):
                self.actions_toolbar_widget.setVisible(False)
            if hasattr(self, "combined_actions_toolbar_widget"):
                self.combined_actions_toolbar_widget.setVisible(True)
            self.sort_order_container.setVisible(False)
            self.filter_watched_checkbox.setVisible(False)
            self.combined_scroll_area.setVisible(True)
            self.populate_combined_view()
        else:
            self.series_list_widget.setVisible(True)
            if hasattr(self, "actions_toolbar_widget"):
                self.actions_toolbar_widget.setVisible(True)
            if hasattr(self, "combined_actions_toolbar_widget"):
                self.combined_actions_toolbar_widget.setVisible(False)
            self.sort_order_container.setVisible(True)
            self.filter_watched_checkbox.setVisible(True)
            self.combined_scroll_area.setVisible(False)
            if library_name:
                self.controller.select_library(library_name)

    @Slot()
    def trigger_combined_scan(self) -> None:
        self.controller.trigger_scan_all(False)

    @Slot(str)
    def on_order_changed(self, text: str) -> None:
        if not text:
            return
        if self.controller.sort_mode == "Alphabetical":
            descending = text == "Z-A"
        else:
            descending = text == "Oldest to Newest"
        logger.debug(
            f"Order dropdown changed to '{text}', sort_descending={descending}"
        )
        self.controller.set_sort_descending(descending)

    @Slot()
    def populate_grid(self) -> None:
        if getattr(self.controller, "is_video_playing", False):
            return
        if self.controller.current_library_name == "Combined View":
            self.populate_combined_view()
            return
        self.order_selector.blockSignals(True)
        current_sort_mode: str = self.controller.sort_mode
        logger.info(
            f"Populating library grid for '{self.controller.current_library_name}' "
            f"(Sort: {current_sort_mode}, Descending: {self.controller.sort_descending}, "
            f"Hide Watched: {self.controller.filter_out_watched})"
        )
        show_order: bool = current_sort_mode != "Next Up"
        self.order_label.setVisible(show_order)
        self.order_selector.setVisible(show_order)
        if show_order:
            if current_sort_mode != self._last_order_mode:
                self.order_selector.clear()
                if current_sort_mode == "Alphabetical":
                    self.order_selector.addItems(["A-Z", "Z-A"])
                else:
                    self.order_selector.addItems(
                        ["Newest to Oldest", "Oldest to Newest"]
                    )
                self._last_order_mode = current_sort_mode
            if current_sort_mode == "Alphabetical":
                self.order_selector.setCurrentText(
                    "Z-A" if self.controller.sort_descending else "A-Z"
                )
            else:
                self.order_selector.setCurrentText(
                    "Oldest to Newest"
                    if self.controller.sort_descending
                    else "Newest to Oldest"
                )
        else:
            self._last_order_mode = None
        self.order_selector.blockSignals(False)
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

            if not is_movie and total_episodes == 0:
                continue

            first_air_date: str = (
                str(metadata_dictionary.get("year", ""))
                if is_movie
                else metadata_dictionary.get("first_air_date", "")
            )
            effective_air_date: str = max(max_air_date, first_air_date)
            poster_path_string: str = metadata_dictionary.get("poster_path", "")

            last_played_at = metrics_dictionary.get("last_played_at", 0)
            is_next_up_candidate = False
            if total_episodes > 0 and not is_fully_watched:
                if watched_episodes > 0 or last_played_at > 0:
                    is_next_up_candidate = True

            series_entries.append(
                {
                    "name": series_name,
                    "poster_path": poster_path_string,
                    "date_added": max_date_added,
                    "effective_air_date": effective_air_date,
                    "watched_count": watched_episodes,
                    "total_count": total_episodes,
                    "is_movie": is_movie,
                    "last_played_at": last_played_at,
                    "is_fully_watched": is_fully_watched,
                    "is_next_up_candidate": is_next_up_candidate,
                }
            )

        # Apply sorting logic
        sort_mode_value: str = self.controller.sort_mode
        sort_descending: bool = self.controller.sort_descending
        logger.debug(
            f"Sorting {len(series_entries)} entries by '{sort_mode_value}' "
            f"(descending={sort_descending})"
        )
        if sort_mode_value == "Recently Added":
            series_entries.sort(
                key=lambda entry: entry["date_added"], reverse=not sort_descending
            )
        elif sort_mode_value == "Recently Aired":
            series_entries.sort(
                key=lambda entry: entry["effective_air_date"],
                reverse=not sort_descending,
            )
        elif sort_mode_value == "Next Up":
            if not sort_descending:
                series_entries.sort(
                    key=lambda entry: (
                        not entry["is_next_up_candidate"],
                        -entry["last_played_at"],
                        entry["name"].lower(),
                    )
                )
            else:
                series_entries.sort(
                    key=lambda entry: (
                        not entry["is_next_up_candidate"],
                        entry["last_played_at"],
                        entry["name"].lower(),
                    )
                )
        else:
            series_entries.sort(
                key=lambda entry: entry["name"].lower(), reverse=sort_descending
            )

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
        logger.info(f"Populated library grid with {target_item_count} items.")

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
                else:
                    logger.warning(
                        f"Could not load poster pixmap (invalid format): {poster_path_value}"
                    )
            else:
                logger.warning(
                    f"Poster path does not exist on disk: {poster_path_value}"
                )

        if not icon_assigned:
            logger.debug(
                f"Assigning fallback default icon for item text: '{item_target.text().splitlines()[0]}'"
            )
            if "" not in self.cached_icons:
                fallback_pixmap = QPixmap(160, 220)
                fallback_pixmap.fill(QColor(40, 40, 40))
                self.cached_icons[""] = QIcon(fallback_pixmap)
            item_target.setIcon(self.cached_icons[""])

    @Slot(QListWidgetItem)
    def on_item_clicked(self, item_target: QListWidgetItem) -> None:
        title: str = item_target.data(Qt.ItemDataRole.UserRole)
        if title:
            logger.info(f"Library item clicked: '{title}'")
            library_config = config.libraries.get(
                self.controller.current_library_name, {}
            )
            if library_config.get("type") == "movie":
                self.controller.select_movie(title)
            else:
                self.controller.select_series(title)

    @Slot()
    def _open_search_dialog(self) -> None:
        """Open the search dialog, scoped to current library (or all if combined view)."""
        library_name: Optional[str] = None
        if self.controller.current_library_name != "Combined View":
            library_name = self.controller.current_library_name

        logger.info(
            f"Opening search dialog for library: {library_name or 'All Libraries'}"
        )
        dialog = SearchDialog(library_name=library_name, parent=self)
        dialog.item_selected.connect(self._on_search_result_selected)
        dialog.exec()

    @Slot(str, str, str)
    def _on_search_result_selected(
        self, item_name: str, library_name: str, item_type: str
    ) -> None:
        """Navigate to the series or movie selected from search results."""
        logger.info(
            f"Search result navigation: '{item_name}' (Type: {item_type}) "
            f"in library '{library_name}'"
        )
        if library_name:
            # Remember previous view for correct back navigation
            previous_view = self.controller.current_library_name
            self._navigate_back_to_combined = previous_view == "Combined View"

            self.controller.current_library_name = library_name
            self.controller.select_library(library_name)
            if item_type == "movie":
                self.controller.select_movie(item_name)
            else:
                self.controller.select_series(item_name)

    def _build_smart_row_widget(self, row_config: Dict[str, Any]) -> Optional[QWidget]:
        """Build a single smart row widget from a row configuration dict.

        Returns None if the row has no items.
        """
        libraries = row_config.get("libraries", [])
        row_name = row_config.get("name", "Row")
        sort_by = row_config.get("sort_by", "Alphabetical")
        filter_mode = row_config.get("filter_mode", "All")

        config_hash = db.compute_config_hash(libraries, sort_by, filter_mode)

        logger.debug(
            f"Building smart row widget for '{row_name}' (config_hash={config_hash})"
        )
        items = db.get_cached_smart_rows(libraries, sort_by, filter_mode)
        max_items = row_config.get("max_items", 20)
        items = items[:max_items]

        if not items:
            logger.debug(f"Skipping row '{row_name}' because it contains 0 items")
            return None

        # Create a row container
        row_container = QWidget()
        row_container.setObjectName(f"smart_row_{config_hash}")
        row_layout = QVBoxLayout(row_container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        # Header
        header_label = QLabel(f"<b>{row_name}</b>")
        header_label.setStyleSheet("font-size: 18px; color: #2a82da;")
        row_layout.addWidget(header_label)

        # Horizontal List Widget
        h_list = QListWidget()
        h_list.setFlow(QListWidget.Flow.LeftToRight)
        h_list.setWrapping(False)
        h_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        h_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        h_list.setViewMode(QListWidget.ViewMode.IconMode)
        h_list.setIconSize(QSize(120, 165))
        h_list.setGridSize(QSize(145, 210))
        h_list.setMovement(QListWidget.Movement.Static)
        h_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        h_list.setFixedHeight(225)
        h_list.setStyleSheet(
            """
            QListWidget {
                background-color: transparent;
                border: none;
            }
            QListWidget::item {
                border: 1px solid #333333;
                border-radius: 6px;
                background-color: #222222;
                margin-right: 10px;
            }
            QListWidget::item:hover {
                background-color: #333333;
                border: 1px solid #2a82da;
            }
            """
        )

        for media_item in items:
            item_type = media_item.get("type")
            name = media_item.get("name") or media_item.get("series_name") or ""
            poster_path = media_item.get("poster_path") or ""
            watched_count = media_item.get("watched_count", 0)
            total_count = media_item.get("total_count", 0)

            if item_type == "season":
                season_name = media_item.get("season_name") or ""
                display_label = f"{name}\n{season_name} ({watched_count}/{total_count})"
            elif item_type == "series":
                display_label = f"{name}\n({watched_count}/{total_count})"
            else:
                status_string = "Watched" if watched_count > 0 else "Unwatched"
                display_label = f"{name}\n({status_string})"

            list_item = QListWidgetItem(display_label)
            list_item.setData(Qt.ItemDataRole.UserRole, media_item)
            list_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            list_item.setToolTip(display_label)

            self._assign_item_icon_with_size(list_item, poster_path, 120, 165)
            h_list.addItem(list_item)

        h_list.itemClicked.connect(self.on_combined_item_clicked)
        row_layout.addWidget(h_list)

        return row_container

    def _clear_combined_view(self) -> None:
        """Remove all widgets from the combined scroll layout."""
        while self.combined_scroll_layout.count():
            layout_item = self.combined_scroll_layout.takeAt(0)
            if layout_item is not None:
                w = layout_item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
        self._smart_row_widgets.clear()

    def populate_combined_view(self) -> None:
        logger.info("populate_combined_view: started populating combined layout")
        self._clear_combined_view()

        enabled_rows = [
            row for row in config.combined_views if row.get("enabled", True)
        ]
        logger.info(
            f"populate_combined_view: found {len(enabled_rows)} enabled smart rows"
        )
        if not enabled_rows:
            empty_label = QLabel(
                "No rows configured or enabled in Combined View settings."
            )
            empty_label.setStyleSheet("font-size: 16px; color: #888888; padding: 20px;")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.combined_scroll_layout.addWidget(empty_label)
            return

        for row in enabled_rows:
            libraries = row.get("libraries", [])
            config_hash = db.compute_config_hash(
                libraries,
                row.get("sort_by", "Alphabetical"),
                row.get("filter_mode", "All"),
            )

            row_container = self._build_smart_row_widget(row)
            if row_container is not None:
                self._smart_row_widgets[config_hash] = row_container
                self.combined_scroll_layout.addWidget(row_container)

        self.combined_scroll_layout.addStretch()

    @Slot(list)
    def _on_smart_rows_updated(self, changed_config_hashes: List[str]) -> None:
        """Handle targeted smart row updates from the controller.

        Always processes updates even when the combined view is hidden,
        so that when the user navigates back, the widgets reflect fresh
        cache data without requiring an explicit populate_combined_view call.
        """
        logger.debug(
            f"Smart rows updated for {len(changed_config_hashes)} configs "
            f"(combined_view_visible={self.combined_scroll_area.isVisible()})"
        )
        for config_hash in changed_config_hashes:
            # Find the row config that matches this hash
            for row in config.combined_views:
                if not row.get("enabled", True):
                    continue
                libraries = row.get("libraries", [])
                row_hash = db.compute_config_hash(
                    libraries,
                    row.get("sort_by", "Alphabetical"),
                    row.get("filter_mode", "All"),
                )
                if row_hash != config_hash:
                    continue

                old_widget = self._smart_row_widgets.pop(config_hash, None)
                new_widget = self._build_smart_row_widget(row)

                if new_widget is not None:
                    self._smart_row_widgets[config_hash] = new_widget
                    if old_widget is not None:
                        # Replace old widget
                        index = self.combined_scroll_layout.indexOf(old_widget)
                        old_widget.setParent(None)
                        old_widget.deleteLater()
                        if index >= 0:
                            self.combined_scroll_layout.insertWidget(index, new_widget)
                        else:
                            self.combined_scroll_layout.addWidget(new_widget)
                    else:
                        self.combined_scroll_layout.addWidget(new_widget)
                elif old_widget is not None:
                    old_widget.setParent(None)
                    old_widget.deleteLater()
                break

    def _sync_library_selector(self, library_name: str) -> None:
        """Sync the library selector and tab bar to the given library name.

        Called when navigating from the combined view to a library item detail,
        so the selector reflects the actual library being viewed rather than
        showing 'Combined View' while displaying library content.
        """
        if library_name in self.library_names_list:
            idx = self.library_names_list.index(library_name)
            self.library_selector.blockSignals(True)
            self.library_selector.setCurrentText(library_name)
            self.library_selector.blockSignals(False)
            self.library_tab_bar.blockSignals(True)
            self.library_tab_bar.setCurrentIndex(idx)
            self.library_tab_bar.blockSignals(False)

    def _assign_item_icon_with_size(
        self,
        item_target: QListWidgetItem,
        poster_path_value: str,
        width: int,
        height: int,
    ) -> None:
        cache_key = f"{poster_path_value}_{width}_{height}"
        if cache_key in self.cached_icons:
            item_target.setIcon(self.cached_icons[cache_key])
            return

        icon_assigned: bool = False
        if poster_path_value:
            poster_path_object = Path(poster_path_value)
            if poster_path_object.is_file():
                pixmap_instance = QPixmap(str(poster_path_object))
                if not pixmap_instance.isNull():
                    scaled_pixmap = pixmap_instance.scaled(
                        width,
                        height,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    loaded_icon = QIcon(scaled_pixmap)
                    self.cached_icons[cache_key] = loaded_icon
                    item_target.setIcon(loaded_icon)
                    icon_assigned = True

        if not icon_assigned:
            fallback_key = f"fallback_{width}_{height}"
            if fallback_key not in self.cached_icons:
                fallback_pixmap = QPixmap(width, height)
                fallback_pixmap.fill(QColor(40, 40, 40))
                self.cached_icons[fallback_key] = QIcon(fallback_pixmap)
            item_target.setIcon(self.cached_icons[fallback_key])

    @Slot(QListWidgetItem)
    def on_combined_item_clicked(self, item_target: QListWidgetItem) -> None:
        item_data = item_target.data(Qt.ItemDataRole.UserRole)
        if not item_data:
            return

        item_type = item_data.get("type")  # "season", "series", "movie"
        library_name = item_data.get("library_name")
        name = item_data.get("name") or item_data.get("series_name") or ""
        logger.info(
            f"Combined view item clicked: '{name}' (Type: {item_type}, Library: {library_name})"
        )

        # Remember the previous view before changing current_library_name
        previous_view = self.controller.current_library_name
        self._navigate_back_to_combined = previous_view == "Combined View"

        if library_name:
            self.controller.current_library_name = library_name

        if item_type == "movie":
            movie_name = item_data.get("name")
            if movie_name:
                self.controller.select_library(library_name)
                self.controller.select_movie(movie_name)
        else:
            series_name = item_data.get("name") or item_data.get("series_name")
            if series_name:
                self.controller.select_library(library_name)
                self.controller.select_series(series_name)
