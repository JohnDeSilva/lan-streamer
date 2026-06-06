from pathlib import Path
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QHeaderView,
    QComboBox,
    QTreeWidget,
    QTreeWidgetItem,
)
from PySide6.QtCore import Slot, Qt

from lan_streamer.ui_views.proxy import QMessageBox, tmdb_client

if TYPE_CHECKING:
    from lan_streamer.ui_views.controller import Controller


class EpisodeMatchDialog(QDialog):
    """
    Modal dialog allowing users to match metadata on TMDB for an individual episode of a show.
    Conforms strictly to zero-abbreviation variable naming and static typing standards.
    """

    def __init__(
        self,
        series_name: str,
        episode_path: str,
        controller_instance: "Controller",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.episode_path: str = episode_path
        self.controller: "Controller" = controller_instance
        self.season_selector: QComboBox = QComboBox()
        self.results_table: QTableWidget = QTableWidget()
        self.search_results_list: List[Dict[str, Any]] = []

        series_record: Dict[str, Any] = self.controller.cached_library_data.get(
            self.series_name, {}
        )
        metadata_dictionary: Dict[str, Any] = series_record.get("metadata", {})
        self.tmdb_identifier: str = metadata_dictionary.get("tmdb_identifier", "")

        if not self.tmdb_identifier:
            matched_series = tmdb_client.search_series(self.series_name)
            if matched_series:
                self.tmdb_identifier = str(matched_series.get("id", ""))

        self.setWindowTitle(f"Match Episode Metadata: {series_name}")
        self.resize(900, 500)
        self._setup_ui()
        self._populate_seasons()

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        top_row_layout: QHBoxLayout = QHBoxLayout()
        top_row_layout.setSpacing(10)
        top_row_layout.addWidget(QLabel("TMDB Season:"))
        self.season_selector.setMinimumWidth(200)
        self.season_selector.currentTextChanged.connect(self.on_season_changed)
        top_row_layout.addWidget(self.season_selector)
        top_row_layout.addStretch()
        main_layout.addLayout(top_row_layout)

        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(
            ["Episode #", "Episode Title", "Air Date", "Overview"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)
        main_layout.addWidget(self.results_table)

        bottom_buttons_layout: QHBoxLayout = QHBoxLayout()
        bottom_buttons_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Cancel")
        cancel_button.setObjectName("closeEpisodeMatchDialogButton")
        cancel_button.clicked.connect(self.reject)
        bottom_buttons_layout.addWidget(cancel_button)

        apply_button: QPushButton = QPushButton("Apply Selected Match")
        apply_button.setObjectName("accentButton")
        apply_button.clicked.connect(self.apply_selected)
        bottom_buttons_layout.addWidget(apply_button)

        main_layout.addLayout(bottom_buttons_layout)

    def _populate_seasons(self) -> None:
        seasons_list: List[Dict[str, Any]] = []
        if self.tmdb_identifier:
            seasons_list = tmdb_client.get_seasons(self.tmdb_identifier)

        self.season_selector.blockSignals(True)
        for season_dictionary in seasons_list:
            season_number_value: int = season_dictionary.get("season_number", 0)
            season_name_value: str = (
                season_dictionary.get("name") or f"Season {season_number_value}"
            )
            self.season_selector.addItem(season_name_value, season_number_value)
        self.season_selector.blockSignals(False)

        if self.season_selector.count() > 0:
            self.on_season_changed(self.season_selector.currentText())

    @Slot(str)
    def on_season_changed(self, season_text: str) -> None:
        if not self.tmdb_identifier or self.season_selector.count() == 0:
            return

        season_number_value: Any = self.season_selector.currentData()
        if season_number_value is None:
            return

        season_number_int: int = int(season_number_value)
        self.results_table.clearContents()
        self.results_table.setRowCount(0)
        self.search_results_list = []

        episodes_data: List[Dict[str, Any]] = tmdb_client.get_episodes(
            self.tmdb_identifier, season_number_int
        )

        for episode_dictionary in episodes_data:
            episode_identifier_str: str = str(episode_dictionary.get("id", ""))
            episode_number_int: int = episode_dictionary.get("episode_number", 0)
            episode_name_str: str = episode_dictionary.get("name", "")
            air_date_str: str = episode_dictionary.get("air_date", "")
            overview_str: str = episode_dictionary.get("overview", "")
            runtime_int: int = episode_dictionary.get("runtime", 0)

            self.search_results_list.append(
                {
                    "id": episode_identifier_str,
                    "episode_number": episode_number_int,
                    "name": episode_name_str,
                    "air_date": air_date_str,
                    "overview": overview_str,
                    "runtime": runtime_int,
                }
            )

        self.results_table.setRowCount(len(self.search_results_list))
        for row_index, record_dictionary in enumerate(self.search_results_list):
            number_item: QTableWidgetItem = QTableWidgetItem(
                str(record_dictionary["episode_number"])
            )
            number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.results_table.setItem(row_index, 0, number_item)

            name_item: QTableWidgetItem = QTableWidgetItem(record_dictionary["name"])
            self.results_table.setItem(row_index, 1, name_item)

            date_item: QTableWidgetItem = QTableWidgetItem(
                record_dictionary["air_date"]
            )
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.results_table.setItem(row_index, 2, date_item)

            overview_item: QTableWidgetItem = QTableWidgetItem(
                record_dictionary["overview"]
            )
            self.results_table.setItem(row_index, 3, overview_item)

    @Slot()
    def apply_selected(self) -> None:
        selected_rows: List[int] = [
            item.row() for item in self.results_table.selectedItems()
        ]
        if not selected_rows:
            QMessageBox.warning(
                self,
                "Selection Required",
                "Please select an episode match result first.",
            )
            return

        target_row_index: int = selected_rows[0]
        match_record: Dict[str, Any] = self.search_results_list[target_row_index]
        self.controller.apply_episode_metadata_match(
            self.series_name, self.episode_path, match_record
        )
        self.accept()


class RenamePreviewDialog(QDialog):
    """
    Dialog displaying generated file renaming mapping previews for consistent file hygiene.
    Conforms strictly to standard static typing and naming constraints.
    """

    def __init__(
        self,
        series_name: str,
        controller_instance: "Controller",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.controller: "Controller" = controller_instance
        self.template_input: QLineEdit = QLineEdit()
        self.preview_tree: QTreeWidget = QTreeWidget()
        self.preview_results_list: List[Dict[str, Any]] = []
        self.all_previews_list: List[Dict[str, Any]] = []

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

        # Preview Data Tree
        self.preview_tree.setColumnCount(2)
        self.preview_tree.setHeaderLabels(
            ["Original Target Filename", "New Standardized Filename"]
        )
        self.preview_tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        self.preview_tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.preview_tree.setColumnWidth(0, 400)
        self.preview_tree.itemChanged.connect(self.on_tree_item_changed)

        main_layout.addWidget(self.preview_tree)

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

    @Slot(QTreeWidgetItem, int)
    def on_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return

        self.preview_tree.blockSignals(True)
        try:
            # If a parent item (Season) checkstate changes, sync all its child items
            if item.parent() is None:
                state = item.checkState(0)
                for i in range(item.childCount()):
                    item.child(i).setCheckState(0, state)
            else:
                # If a child item (Episode) checkstate changes, update the parent's checkstate
                parent = item.parent()
                if parent:
                    checked_count = 0
                    unchecked_count = 0
                    child_count = parent.childCount()
                    for i in range(child_count):
                        child_state = parent.child(i).checkState(0)
                        if child_state == Qt.CheckState.Checked:
                            checked_count += 1
                        elif child_state == Qt.CheckState.Unchecked:
                            unchecked_count += 1

                    if checked_count == child_count:
                        parent.setCheckState(0, Qt.CheckState.Checked)
                    elif unchecked_count == child_count:
                        parent.setCheckState(0, Qt.CheckState.Unchecked)
                    else:
                        parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
        finally:
            self.preview_tree.blockSignals(False)

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

        from lan_streamer.scanner.renamer import get_rename_preview
        from lan_streamer.db import natural_sort_key

        self.all_previews_list = get_rename_preview(series_dictionary, template_string)

        # Filter out subtitle entries for preview display
        filtered_results = [
            p for p in self.all_previews_list if not p.get("is_subtitle", False)
        ]

        # Group preview entries by season
        from collections import defaultdict

        grouped_by_season = defaultdict(list)
        for p in filtered_results:
            grouped_by_season[p.get("season", "Unknown Season")].append(p)

        self.preview_tree.blockSignals(True)
        self.preview_tree.clear()

        # Naturally sort the season keys
        sorted_seasons = sorted(grouped_by_season.keys(), key=natural_sort_key)

        for season_name in sorted_seasons:
            season_item = QTreeWidgetItem(self.preview_tree)
            season_item.setText(0, season_name)
            season_item.setFlags(season_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            season_item.setCheckState(0, Qt.CheckState.Checked)

            for preview_dictionary in grouped_by_season[season_name]:
                old_name_str: str = preview_dictionary.get("old_name", "")
                if not old_name_str and "old_path" in preview_dictionary:
                    old_name_str = Path(preview_dictionary["old_path"]).name

                child_item = QTreeWidgetItem(season_item)
                child_item.setText(0, old_name_str)
                child_item.setText(1, preview_dictionary.get("new_name", ""))
                child_item.setFlags(
                    child_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                )
                child_item.setCheckState(0, Qt.CheckState.Checked)
                child_item.setData(0, Qt.ItemDataRole.UserRole, preview_dictionary)

        self.preview_tree.expandAll()
        self.preview_tree.blockSignals(False)

    @Slot()
    def apply_renames(self) -> None:
        # Collect checked video paths from the tree view
        checked_video_paths = set()
        root = self.preview_tree.invisibleRootItem()
        for i in range(root.childCount()):
            season_item = root.child(i)
            for j in range(season_item.childCount()):
                child_item = season_item.child(j)
                if child_item.checkState(0) == Qt.CheckState.Checked:
                    video_dict = child_item.data(0, Qt.ItemDataRole.UserRole)
                    if video_dict and "old_path" in video_dict:
                        checked_video_paths.add(video_dict["old_path"])

        if not checked_video_paths:
            QMessageBox.warning(
                self,
                "Selection Required",
                "Please select at least one episode to rename.",
            )
            return

        # Build list of previews to apply, including associated subtitles
        to_apply = []
        for p in self.all_previews_list:
            if not p.get("is_subtitle", False):
                if p["old_path"] in checked_video_paths:
                    to_apply.append(p)
            else:
                # Subtitle files are matched to their corresponding video files
                is_checked = False
                for v_path in checked_video_paths:
                    sub = Path(p["old_path"])
                    vid = Path(v_path)
                    if sub.parent == vid.parent and sub.name.startswith(vid.stem):
                        is_checked = True
                        break
                if is_checked:
                    to_apply.append(p)

        self.preview_results_list = to_apply
        self.controller.apply_rename_batch(self.preview_results_list)
        self.accept()
