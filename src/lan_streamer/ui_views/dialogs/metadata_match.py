import logging
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
)
from PySide6.QtCore import Slot

from lan_streamer.system.config import config
from lan_streamer.ui_views.proxy import tmdb_client, jellyfin_client, QMessageBox

if TYPE_CHECKING:
    from lan_streamer.ui_views.controller import Controller

logger = logging.getLogger(__name__)


class MetadataMatchDialog(QDialog):
    """
    Search modal to retrieve metadata from external matching provider APIs.
    Strictly typesafe with zero abbreviations.
    """

    def __init__(
        self,
        series_name: str,
        controller_instance: "Controller",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        logger.info(f"Initializing MetadataMatchDialog for series '{series_name}'")
        self.series_name: str = series_name
        self.controller: "Controller" = controller_instance
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
        logger.info(f"MetadataMatchDialog executing search for: '{query_string}'")
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
                        "id": str(item_data.get("id") or ""),
                        "tmdb_id": str(item_data.get("id") or ""),
                        "name": item_data.get("title") or "",
                        "first_air_date": item_data.get("release_date") or "",
                        "overview": item_data.get("overview") or "",
                        "poster_path": item_data.get("poster_path") or "",
                        "provider": "TMDB",
                    }
                )
        else:
            raw_results = tmdb_client.search_series_full(query_string)
            for item_data in raw_results:
                self.search_results_list.append(
                    {
                        "id": str(item_data.get("id") or ""),
                        "tmdb_id": str(item_data.get("id") or ""),
                        "name": item_data.get("name") or "",
                        "first_air_date": item_data.get("first_air_date") or "",
                        "overview": item_data.get("overview") or "",
                        "poster_path": item_data.get("poster_path") or "",
                        "provider": "TMDB",
                    }
                )

        logger.info(
            f"MetadataMatchDialog search found {len(self.search_results_list)} results for '{query_string}'"
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
            logger.warning("MetadataMatchDialog apply clicked with no selection")
            QMessageBox.warning(
                self, "Selection Required", "Please select a match result first."
            )
            return

        target_row_index: int = selected_rows[0]
        match_record: Dict[str, Any] = self.search_results_list[target_row_index]
        logger.info(
            f"MetadataMatchDialog applying match for '{self.series_name}': {match_record}"
        )
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
        controller_instance: "Controller",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        logger.info(f"Initializing JellyfinMatchDialog for series '{series_name}'")
        self.series_name: str = series_name
        self.controller: "Controller" = controller_instance
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
        logger.info(f"JellyfinMatchDialog executing search for: '{query_string}'")
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
            production_year = item_data.get("ProductionYear")
            production_year_value: str = (
                str(production_year) if production_year is not None else ""
            )
            first_air_date_value: str = (
                production_year_value if production_year_value else ""
            )

            self.search_results_list.append(
                {
                    "id": str(item_data.get("Id") or ""),
                    "name": item_data.get("Name") or "",
                    "first_air_date": first_air_date_value,
                    "overview": item_data.get("Overview") or "",
                    "provider": "Jellyfin",
                }
            )

        logger.info(
            f"JellyfinMatchDialog search found {len(self.search_results_list)} results for '{query_string}'"
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
            logger.warning("JellyfinMatchDialog link clicked with no selection")
            QMessageBox.warning(
                self, "Selection Required", "Please select a match result first."
            )
            return

        target_row_index: int = selected_rows[0]
        match_record: Dict[str, Any] = self.search_results_list[target_row_index]
        logger.info(
            f"JellyfinMatchDialog linking watch match for '{self.series_name}': {match_record}"
        )
        self.controller.apply_jellyfin_watch_match(self.series_name, match_record)
        self.accept()
