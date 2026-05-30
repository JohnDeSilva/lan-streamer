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

        from lan_streamer.scanner.renamer import get_rename_preview

        self.preview_results_list = get_rename_preview(
            series_dictionary, template_string
        )

        # Filter out subtitle entries for preview display
        filtered_results = [
            p for p in self.preview_results_list if not p.get("is_subtitle", False)
        ]
        self.preview_table.setRowCount(len(filtered_results))
        self.preview_results_list = filtered_results
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
