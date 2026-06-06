import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSizePolicy,
    QComboBox,
)
from PySide6.QtCore import Qt, Slot, QPoint, Signal
from PySide6.QtGui import QFont, QColor, QAction
from lan_streamer.ui_views.proxy import QPixmap

from lan_streamer import db
from lan_streamer.system.config import config

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMenu
    from lan_streamer.providers.tmdb import tmdb_client
else:
    from lan_streamer.ui_views.proxy import QMenu, tmdb_client
from lan_streamer.ui_views.controller import Controller

logger = logging.getLogger(__name__)


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
        self.overview_label: QLabel = QLabel()
        self.poster_label: QLabel = QLabel()
        self.play_next_button: QPushButton = QPushButton()
        self._next_episode_path: str = ""
        self.seasons_tab_widget: QTabWidget = QTabWidget()
        self._current_series_name: str = ""
        self._season_tables: Dict[str, QTableWidget] = {}
        self.episode_groups_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.episode_group_details_cache: Dict[str, Dict[str, Any]] = {}

        self._setup_ui()
        self.controller.series_selected.connect(self.populate_series_details)
        self.controller.library_loaded.connect(self.on_library_loaded)

    def _setup_ui(self) -> None:
        main_layout: QHBoxLayout = QHBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(20)

        # Left Column (1/4 width stretch)
        left_container: QWidget = QWidget()
        left_layout: QVBoxLayout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(15)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        back_button: QPushButton = QPushButton("← Back to Library")
        back_button.clicked.connect(self.back_requested.emit)
        left_layout.addWidget(back_button)

        self.poster_label.setFixedSize(240, 350)
        self.poster_label.setStyleSheet(
            "background-color: #1a1a1f; border: 1px solid #2d2d35; border-radius: 8px;"
        )
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.poster_label)

        self.play_next_button.setObjectName("playEpisodeButton")
        self.play_next_button.clicked.connect(self._on_play_next_clicked)
        left_layout.addWidget(self.play_next_button)

        self.title_label.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        self.title_label.setWordWrap(True)
        left_layout.addWidget(self.title_label)

        self.overview_label.setFont(QFont("Inter", 13))
        self.overview_label.setWordWrap(True)
        self.overview_label.setStyleSheet("color: #94A3B8;")
        left_layout.addWidget(self.overview_label)

        # Actions Panel
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)

        series_details_button: QPushButton = QPushButton("Series Details")
        series_details_button.setObjectName("seriesDetailsButton")
        series_details_button.clicked.connect(
            lambda: self.controller.series_details_requested.emit(
                self.controller.selected_series_name
            )
        )
        actions_layout.addWidget(series_details_button)

        actions_layout.addWidget(QLabel("Display Group:"))
        self.order_combo = QComboBox()
        self.order_combo.setObjectName("orderComboBox")
        self.order_combo.currentIndexChanged.connect(self._on_order_changed)
        actions_layout.addWidget(self.order_combo)

        actions_layout.addStretch()
        left_layout.addLayout(actions_layout)

        main_layout.addWidget(left_container, 1)  # 1/4 stretch

        # Right Column (3/4 width stretch)
        self.seasons_tab_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        main_layout.addWidget(self.seasons_tab_widget, 3)  # 3/4 stretch

    @Slot()
    def on_library_loaded(self) -> None:
        if (
            self._current_series_name
            and self._current_series_name in self.controller.cached_library_data
        ):
            self.populate_series_details(self._current_series_name)

    @Slot(int)
    def _on_order_changed(self, index: int) -> None:
        if index < 0 or not self._current_series_name:
            return
        selected_group_id = self.order_combo.itemData(index)
        config.set_series_preference(
            self.controller.current_library_name,
            self._current_series_name,
            "display_group_id",
            selected_group_id,
        )
        self.populate_series_details(self._current_series_name)

    @Slot()
    def _on_mark_series_watched(self) -> None:
        if not self.controller.selected_series_name:
            return
        self.controller.mark_series_watched(self.controller.selected_series_name)
        self.populate_series_details(self._current_series_name)

    @Slot(str)
    def _on_mark_season_watched(self, season_name: str) -> None:
        if not self.controller.selected_series_name:
            return
        self.controller.mark_season_watched(
            self.controller.selected_series_name, season_name
        )
        self.populate_series_details(self._current_series_name)

    @Slot()
    def _on_play_next_clicked(self) -> None:
        if self._next_episode_path:
            self.controller.playback_requested.emit(self._next_episode_path)

    @Slot(str)
    def populate_series_details(self, series_name: str) -> None:
        if getattr(self.controller, "is_video_playing", False):
            return

        import datetime

        today_str = datetime.date.today().isoformat()
        library_config = config.libraries.get(self.controller.current_library_name, {})
        show_future_episodes = library_config.get("show_future_episodes", True)

        hide_missing_future = config.get_series_preference(
            self.controller.current_library_name,
            series_name,
            "hide_missing_future",
            False,
        )
        is_opening: bool = self._current_series_name != series_name
        self._current_series_name = series_name
        self._season_tables = {}

        series_record: Dict[str, Any] = self.controller.cached_library_data.get(
            series_name, {}
        )
        metadata_dictionary: Dict[str, Any] = series_record.get("metadata", {})

        series_display_title: str = metadata_dictionary.get("tmdb_name") or series_name
        self.title_label.setText(series_display_title)
        self.overview_label.setText(
            metadata_dictionary.get("overview") or "No overview available."
        )

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
                            240,
                            350,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    pixmap_assigned = True

        if not pixmap_assigned:
            self.poster_label.clear()
            self.poster_label.setText("No Poster")

        # Save active tab text to restore it later and prevent tab jumping
        current_tab_name: Optional[str] = None
        if self.seasons_tab_widget.count() > 0:
            current_tab_name = self.seasons_tab_widget.tabText(
                self.seasons_tab_widget.currentIndex()
            )

        # Clear and repopulate Season Tabs
        self.seasons_tab_widget.clear()

        # Get the selected group ID from configuration preference
        saved_group_id = config.get_series_preference(
            self.controller.current_library_name,
            series_name,
            "display_group_id",
            "default",
        )

        available_groups: List[Dict[str, str]] = [
            {"id": "default", "name": "TV Order (Default)"}
        ]
        tmdb_id = metadata_dictionary.get("tmdb_identifier")
        if tmdb_id:
            if tmdb_id not in self.episode_groups_cache:
                self.episode_groups_cache[tmdb_id] = tmdb_client.get_episode_groups(
                    tmdb_id
                )
            groups_list = self.episode_groups_cache[tmdb_id]
            for g in groups_list:
                available_groups.append(
                    {
                        "id": str(g.get("id") or ""),
                        "name": str(g.get("name") or "Unknown Order"),
                    }
                )

        if not any(g["id"] == saved_group_id for g in available_groups):
            saved_group_id = "default"

        group_details = None
        if saved_group_id != "default":
            if saved_group_id not in self.episode_group_details_cache:
                details = tmdb_client.get_episode_group_details(saved_group_id)
                self.episode_group_details_cache[saved_group_id] = details or {}
            group_details = self.episode_group_details_cache.get(saved_group_id)

        group_order_map = {}
        seasons_dictionary: Dict[str, Any] = series_record.get("seasons", {})
        if group_details and "groups" in group_details:
            # Re-group episodes from database seasons by matching on tmdb_episode_identifier
            db_episodes_by_id = {}
            db_episodes_by_number = {}
            for s_name, s_data in seasons_dictionary.items():
                s_num_match = re.search(r"\d+", s_name)
                s_num = int(s_num_match.group()) if s_num_match else 0
                for ep in s_data.get("episodes", []):
                    ep_id = ep.get("tmdb_episode_identifier") or ep.get(
                        "tmdb_identifier"
                    )
                    if ep_id:
                        db_episodes_by_id[str(ep_id)] = ep
                    ep_num = ep.get("tmdb_number")
                    if ep_num is not None:
                        db_episodes_by_number[(s_num, ep_num)] = ep

            regrouped_seasons = {}
            for idx, group in enumerate(group_details["groups"]):
                group_name = group.get("name") or f"Group {group.get('order', '')}"
                group_order_map[group_name] = idx
                episodes_list = []
                for group_ep in group.get("episodes", []):
                    ep_id = str(group_ep.get("id", ""))
                    db_ep = db_episodes_by_id.get(ep_id)
                    if not db_ep:
                        # Try matching by standard season/episode number
                        db_ep = db_episodes_by_number.get(
                            (
                                group_ep.get("season_number"),
                                group_ep.get("episode_number"),
                            )
                        )

                    if db_ep:
                        new_ep = db_ep.copy()
                        new_ep["tmdb_number"] = group_ep.get("order") + 1
                        if group_ep.get("name"):
                            new_ep["tmdb_name"] = group_ep.get("name")
                        episodes_list.append(new_ep)
                    else:
                        ep_name = group_ep.get("name") or "TBA"
                        group_order = group_ep.get("order") + 1
                        formatted_name = f"{group_name} E{group_order:02d} - {ep_name}"
                        episodes_list.append(
                            {
                                "name": formatted_name,
                                "path": None,
                                "tmdb_identifier": ep_id,
                                "tmdb_episode_identifier": ep_id,
                                "tmdb_name": ep_name,
                                "tmdb_number": group_order,
                                "air_date": group_ep.get("air_date") or "",
                                "runtime": group_ep.get("runtime") or 0,
                                "jellyfin_id": "",
                                "watched": False,
                                "date_added": 0,
                            }
                        )
                if episodes_list:
                    regrouped_seasons[group_name] = {
                        "metadata": {
                            "jellyfin_id": "",
                            "poster_path": "",
                        },
                        "episodes": episodes_list,
                    }
            seasons_dictionary = regrouped_seasons

        # Populate order combobox
        self.order_combo.blockSignals(True)
        self.order_combo.clear()
        for idx, g in enumerate(available_groups):
            self.order_combo.addItem(g["name"], userData=g["id"])
            if g["id"] == saved_group_id:
                self.order_combo.setCurrentIndex(idx)
        self.order_combo.blockSignals(False)

        if group_order_map:
            sorted_season_names = sorted(
                seasons_dictionary.keys(), key=lambda k: group_order_map.get(k, 999)
            )
        else:
            try:
                sorted_season_names: List[str] = sorted(
                    seasons_dictionary.keys(), key=db.natural_sort_key
                )
            except AttributeError:
                sorted_season_names = sorted(seasons_dictionary.keys())

        # Filter seasons to only those having 1 or more episodes (at least one local episode)
        filtered_season_names = []
        for season_name in sorted_season_names:
            season_data = seasons_dictionary.get(season_name, {})
            episodes_list = season_data.get("episodes", [])
            if any(ep.get("path") for ep in episodes_list):
                filtered_season_names.append(season_name)
        sorted_season_names = filtered_season_names

        # Determine next unwatched episode in natural order
        next_episode_path: Optional[str] = None
        next_episode_season_num: Optional[str] = None
        next_episode_num: Optional[str] = None

        def episode_sort_key(ep: Dict[str, Any]) -> tuple:
            num = ep.get("tmdb_number")
            if num is not None:
                try:
                    return (int(num), ep.get("name", ""))
                except ValueError, TypeError:
                    pass
            name_str = ep.get("name", "")
            parsed = re.search(r"[Ee](\d+)", name_str)
            if parsed:
                return (int(parsed.group(1)), name_str)
            return (999999, name_str)

        for season_name in sorted_season_names:
            season_data = seasons_dictionary.get(season_name, {})
            episodes_list = season_data.get("episodes", [])
            if hide_missing_future:
                episodes_list = [ep for ep in episodes_list if ep.get("path")]
            elif not show_future_episodes:
                episodes_list = [
                    ep
                    for ep in episodes_list
                    if not (
                        ep.get("path") is None
                        and (not ep.get("air_date") or ep.get("air_date") > today_str)
                    )
                ]
            try:
                sorted_episodes = sorted(episodes_list, key=episode_sort_key)
            except Exception:
                sorted_episodes = episodes_list

            for index, episode_record in enumerate(sorted_episodes):
                if not episode_record.get("watched", False) and episode_record.get(
                    "path"
                ):
                    next_episode_path = episode_record.get("path", "")

                    season_num_match = re.search(r"\d+", season_name)
                    if season_num_match:
                        next_episode_season_num = f"S{int(season_num_match.group())}"
                    else:
                        next_episode_season_num = season_name

                    tmdb_number_value = episode_record.get("tmdb_number")
                    next_episode_num = (
                        str(tmdb_number_value)
                        if tmdb_number_value is not None
                        else str(index + 1)
                    )
                    break
            if next_episode_path:
                break

        if next_episode_path:
            self._next_episode_path = next_episode_path
            self.play_next_button.setText(
                f"▶ PLAY {next_episode_season_num}:E{next_episode_num}"
            )
            self.play_next_button.setVisible(True)
        else:
            self._next_episode_path = ""
            self.play_next_button.setVisible(False)

        for season_name in sorted_season_names:
            season_data: Dict[str, Any] = seasons_dictionary.get(season_name, {})
            episodes_list: List[Dict[str, Any]] = season_data.get("episodes", [])
            if hide_missing_future:
                episodes_list = [ep for ep in episodes_list if ep.get("path")]
            elif not show_future_episodes:
                episodes_list = [
                    ep
                    for ep in episodes_list
                    if not (
                        ep.get("path") is None
                        and (not ep.get("air_date") or ep.get("air_date") > today_str)
                    )
                ]

            try:
                sorted_episodes = sorted(episodes_list, key=episode_sort_key)
            except Exception:
                sorted_episodes = episodes_list

            # Create an explicit QTableWidget layout for absolute robust item targeting under automated tests
            episode_table: QTableWidget = QTableWidget()
            episode_table.setColumnCount(5)
            episode_table.setHorizontalHeaderLabels(
                ["#", "Episode Title", "Air Date", "Runtime", "Details"]
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.Stretch
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                2, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                3, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                4, QHeaderView.ResizeMode.Interactive
            )
            episode_table.setColumnWidth(4, 90)
            episode_table.setSelectionBehavior(
                QTableWidget.SelectionBehavior.SelectRows
            )
            episode_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            episode_table.verticalHeader().setVisible(False)
            episode_table.verticalHeader().setDefaultSectionSize(32)
            episode_table.setShowGrid(False)

            episode_table.setRowCount(len(sorted_episodes))

            def make_cell_clicked_slot(
                episode_list: List[Dict[str, Any]],
            ) -> Callable[[int, int], None]:
                def slot(row: int, col: int) -> None:
                    if col == 1:  # Title column
                        target_path = episode_list[row].get("path", "")
                        if target_path:
                            self.controller.playback_requested.emit(target_path)

                return slot

            episode_table.cellClicked.connect(make_cell_clicked_slot(sorted_episodes))

            for row_index, episode_record in enumerate(sorted_episodes):
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

                absolute_path: str = episode_record.get("path") or ""
                is_watched: bool = bool(episode_record.get("watched", False))
                air_date_string: str = episode_record.get("air_date") or ""
                runtime_value: int = episode_record.get("runtime", 0)
                runtime_string: str = f"{runtime_value} min" if runtime_value else ""

                # Determine styling and icons based on state
                if absolute_path:
                    if is_watched:
                        text_color = QColor("#888888")
                        icon_str = "✓  "
                    else:
                        text_color = QColor("#0e5296")
                        icon_str = "●  "
                else:
                    is_missing = False
                    if air_date_string:
                        try:
                            air_date_obj = datetime.date.fromisoformat(air_date_string)
                            today_obj = datetime.date.today()
                            if air_date_obj < today_obj:
                                is_missing = True
                        except ValueError:
                            if air_date_string < today_str:
                                is_missing = True

                    if is_missing:
                        text_color = QColor("#ef4444")  # Bright Red
                        icon_str = "✕  "
                    else:
                        text_color = QColor("#a78bfa")  # Lavender/purple
                        icon_str = "◊  "

                display_title = f"{icon_str}{title_string}"

                # Column 0: Details Button
                details_button: QPushButton = QPushButton("...")
                details_button.setToolTip("Details")
                details_button.setObjectName(f"detailsEpisodeButton_{row_index}")
                details_button.setStyleSheet("padding: 2px 8px; font-weight: bold;")

                if absolute_path:

                    def make_details_slot(
                        target_series: str, target_path: str
                    ) -> Callable[[], None]:
                        return lambda: self.controller.episode_details_requested.emit(
                            target_series, target_path
                        )

                    details_button.clicked.connect(
                        make_details_slot(series_name, absolute_path)
                    )
                else:
                    details_button.setEnabled(False)

                details_container: QWidget = QWidget()
                details_container.setStyleSheet("background-color: transparent;")
                details_layout: QHBoxLayout = QHBoxLayout(details_container)
                details_layout.setContentsMargins(2, 2, 2, 2)
                details_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                details_layout.addWidget(details_button)
                episode_table.setCellWidget(row_index, 4, details_container)

                # Render table item entities cleanly
                number_item: QTableWidgetItem = QTableWidgetItem(number_string)
                number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                number_item.setForeground(text_color)
                episode_table.setItem(row_index, 0, number_item)

                title_item: QTableWidgetItem = QTableWidgetItem(display_title)
                title_item.setToolTip("Click to play episode" if absolute_path else "")
                title_item.setForeground(text_color)
                episode_table.setItem(row_index, 1, title_item)

                air_date_item: QTableWidgetItem = QTableWidgetItem(air_date_string)
                air_date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                air_date_item.setForeground(text_color)
                episode_table.setItem(row_index, 2, air_date_item)

                runtime_item: QTableWidgetItem = QTableWidgetItem(runtime_string)
                runtime_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                runtime_item.setForeground(text_color)
                episode_table.setItem(row_index, 3, runtime_item)

            def make_context_menu_slot(
                table: QTableWidget, season: str, episode_list: List[Dict[str, Any]]
            ) -> Callable[[QPoint], None]:
                def show_context_menu(position: QPoint) -> None:
                    item: Optional[QTableWidgetItem] = table.itemAt(position)
                    if not item:
                        return
                    row: int = item.row()
                    episode: Dict[str, Any] = episode_list[row]
                    if not episode.get("path"):
                        return

                    menu: QMenu = QMenu(table)

                    is_watched: bool = bool(episode.get("watched", False))
                    action_text: str = (
                        "Mark as Unwatched" if is_watched else "Mark as Watched"
                    )
                    toggle_action: QAction = QAction(action_text, table)

                    def handle_toggle() -> None:
                        target_path: str = episode.get("path", "")
                        if target_path:
                            new_status: bool = not is_watched
                            self.controller.mark_episode_watched(
                                target_path, new_status
                            )
                            self.populate_series_details(self._current_series_name)

                    toggle_action.triggered.connect(handle_toggle)
                    menu.addAction(toggle_action)

                    delete_action: QAction = QAction("Delete Episode", table)

                    def handle_delete() -> None:
                        target_path: str = episode.get("path", "")
                        if target_path:
                            from PySide6.QtWidgets import QMessageBox

                            confirm = QMessageBox.question(
                                self,
                                "Delete Episode",
                                f"Are you sure you want to delete the episode '{Path(target_path).name}' from the library database? This action cannot be undone.",
                                QMessageBox.StandardButton.Yes
                                | QMessageBox.StandardButton.No,
                            )
                            if confirm == QMessageBox.StandardButton.Yes:
                                self.controller.delete_episode(target_path)
                                self.populate_series_details(self._current_series_name)

                    delete_action.triggered.connect(handle_delete)
                    menu.addAction(delete_action)

                    menu.exec(table.viewport().mapToGlobal(position))

                return show_context_menu

            episode_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            episode_table.customContextMenuRequested.connect(
                make_context_menu_slot(episode_table, season_name, sorted_episodes)
            )

            # Create season_page container to house the table and mark season watched button cleanly
            season_page: QWidget = QWidget()
            season_layout: QVBoxLayout = QVBoxLayout(season_page)
            season_layout.setContentsMargins(0, 5, 0, 0)
            season_layout.setSpacing(10)

            season_actions_layout: QHBoxLayout = QHBoxLayout()
            mark_season_button: QPushButton = QPushButton("Mark season as watched")
            mark_season_button.setObjectName(f"markSeasonWatchedButton_{season_name}")

            def make_season_watched_slot(
                target_season: str,
            ) -> Callable[[], None]:
                return lambda: self._on_mark_season_watched(target_season)

            mark_season_button.clicked.connect(make_season_watched_slot(season_name))
            season_actions_layout.addWidget(mark_season_button)
            season_actions_layout.addStretch()
            season_layout.addLayout(season_actions_layout)

            self._season_tables[season_name] = episode_table
            season_layout.addWidget(episode_table)

            self.seasons_tab_widget.addTab(season_page, season_name)

        # Restore previous tab if it exists, otherwise select first unwatched tab on first load
        restored_tab = False
        if not is_opening and current_tab_name:
            for idx in range(self.seasons_tab_widget.count()):
                if self.seasons_tab_widget.tabText(idx) == current_tab_name:
                    self.seasons_tab_widget.setCurrentIndex(idx)
                    restored_tab = True
                    break

        if not restored_tab and sorted_season_names:
            target_tab_index: int = 0
            for index_position, season_name in enumerate(sorted_season_names):
                season_data_record = seasons_dictionary.get(season_name, {})
                has_unwatched: bool = False
                for ep in season_data_record.get("episodes", []):
                    if not ep.get("watched"):
                        has_unwatched = True
                        break
                if has_unwatched:
                    target_tab_index = index_position
                    break
            self.seasons_tab_widget.setCurrentIndex(target_tab_index)

    def trigger_episode_playback_by_row(
        self, season_tab_index: int, row_index: int
    ) -> None:
        """Test Helper triggering playback by simulating a click on the episode title cell."""
        target_widget: Optional[QWidget] = self.seasons_tab_widget.widget(
            season_tab_index
        )
        if target_widget:
            table_target = target_widget.findChild(QTableWidget)
            if table_target:
                table_target.cellClicked.emit(row_index, 1)
