"""Full-page season detail view with poster, overview, and episode table."""

import datetime
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QFont, QPixmap, QColor, QAction
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lan_streamer import db
from lan_streamer.system.config import config
from lan_streamer.ui_views.controller import Controller

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMenu
    from lan_streamer.providers.tmdb import tmdb_client
    from lan_streamer.providers.myanimelist import myanimelist_client
else:
    from lan_streamer.ui_views.proxy import QMenu, tmdb_client, myanimelist_client

logger = logging.getLogger(__name__)


class SeasonDetailView(QWidget):
    """Full-page season detail with poster, overview, episode table,
    TMDB metadata mapper, and MyAnimeList mapper tabs.

    Reads data from ``controller.cached_library_data`` and supports TMDB
    display group re-ordering.
    """

    back_requested = Signal()

    def __init__(
        self, controller_instance: Controller, parent: Optional[QWidget] = None
    ) -> None:
        """Initialize the season detail view.

        Args:
            controller_instance: Application controller for data access.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.controller: Controller = controller_instance
        self._current_series_name: Optional[str] = None
        self._current_season_name: Optional[str] = None

        # State for mapper tabs
        self._current_series_data: Dict[str, Any] = {}
        self._current_season_data: Dict[str, Any] = {}
        self._current_season_episodes: List[Dict[str, Any]] = []

        # TMDB mapper state
        self._tmdb_mapper_episodes: List[Dict[str, Any]] = []

        # MAL mapper state
        self._mal_selected_anime_id: Optional[int] = None
        self._mal_local_episodes: List[Dict[str, Any]] = []
        self._mal_row_episodes: List[int] = []
        self._mal_entries: List[
            Dict[str, Any]
        ] = []  # list of {id, title} for tracked entries

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        back_button = QPushButton("\u2190 Back")
        back_button.clicked.connect(self.back_requested.emit)
        main_layout.addWidget(back_button)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setSpacing(15)
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        top_row = QHBoxLayout()
        top_row.setSpacing(20)

        # Left column: poster, title, overview
        left_container = QWidget()
        left_container.setMaximumWidth(200)
        left_column = QVBoxLayout(left_container)
        left_column.setSpacing(12)
        left_column.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._setup_left_column(left_column)
        top_row.addWidget(left_container)

        # Right column: QTabWidget with Episodes, Metadata Mapper, and MAL Mapper tabs
        self._tab_widget = QTabWidget()

        # --- Tab 0: Episodes ---
        self._episodes_tab = QWidget()
        episodes_tab_layout = QVBoxLayout(self._episodes_tab)
        episodes_tab_layout.setSpacing(10)

        episode_header = QLabel("Episodes")
        episode_header_font = QFont()
        episode_header_font.setPointSize(14)
        episode_header_font.setBold(True)
        episode_header.setFont(episode_header_font)
        episodes_tab_layout.addWidget(episode_header)

        self._episode_table = QTableWidget()
        self._episode_table.setColumnCount(6)
        self._episode_table.setHorizontalHeaderLabels(
            ["#", "Episode Title", "Air Date", "Runtime", "Progress", "Details"]
        )
        for col_index, resize_mode in enumerate(
            [
                QHeaderView.ResizeMode.ResizeToContents,
                QHeaderView.ResizeMode.Stretch,
                QHeaderView.ResizeMode.ResizeToContents,
                QHeaderView.ResizeMode.ResizeToContents,
                QHeaderView.ResizeMode.ResizeToContents,
                QHeaderView.ResizeMode.Interactive,
            ]
        ):
            self._episode_table.horizontalHeader().setSectionResizeMode(
                col_index, resize_mode
            )
        self._episode_table.setColumnWidth(5, 90)
        self._episode_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._episode_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._episode_table.verticalHeader().setVisible(False)
        self._episode_table.verticalHeader().setDefaultSectionSize(32)
        self._episode_table.setShowGrid(False)
        self._episode_table.cellClicked.connect(self._on_episode_cell_clicked)
        episodes_tab_layout.addWidget(self._episode_table, 1)

        # Season action row (inside episodes tab)
        self._season_actions_layout = QHBoxLayout()
        self._season_actions_layout.setSpacing(10)
        self._mark_season_button = QPushButton()
        self._mark_season_button.setObjectName("markSeasonWatchedButton")
        self._mark_season_button.clicked.connect(self._on_mark_season_watched)
        self._season_actions_layout.addWidget(self._mark_season_button)
        self._season_actions_layout.addStretch()
        episodes_tab_layout.addLayout(self._season_actions_layout)

        self._tab_widget.addTab(self._episodes_tab, "Episodes")

        # --- Tab 1: Manual Metadata Mapper ---
        self._metadata_mapper_tab = QWidget()
        self._setup_metadata_mapper_tab()
        self._tab_widget.addTab(self._metadata_mapper_tab, "Manual Metadata Mapper")

        # --- Tab 2: MyAnimeList Mapper ---
        self._mal_mapper_tab = QWidget()
        self._setup_mal_mapper_tab()
        self._tab_widget.addTab(self._mal_mapper_tab, "MyAnimeList Mapper")
        # Visibility will be updated in display_season() based on library type.

        top_row.addWidget(self._tab_widget, 1)
        self._content_layout.addLayout(top_row)

    def _setup_left_column(self, layout: QVBoxLayout) -> None:
        """Build the poster, title, and overview widgets in the left column."""
        self._poster_label = QLabel()
        self._poster_label.setFixedSize(200, 300)
        self._poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster_label.setStyleSheet(
            "background-color: #1a1a1f; border: 1px solid #2d2d35; border-radius: 8px;"
        )
        self._poster_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._poster_label.customContextMenuRequested.connect(
            self._on_poster_context_menu
        )
        self._poster_label.setToolTip("Right-click to change poster")
        layout.addWidget(self._poster_label)

        self._title_label = QLabel()
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setWordWrap(True)
        self._title_label.setMaximumWidth(200)
        layout.addWidget(self._title_label)

        self._overview_label = QLabel()
        overview_font = QFont()
        overview_font.setPointSize(12)
        self._overview_label.setFont(overview_font)
        self._overview_label.setWordWrap(True)
        self._overview_label.setMaximumWidth(200)
        self._overview_label.setStyleSheet("color: #94A3B8;")
        layout.addWidget(self._overview_label)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def display_season(self, series_name: str, season_name: str) -> None:
        """Populate the view with series and season data from cached library.

        Applies TMDB display group re-ordering if configured.
        """
        self._current_series_name = series_name
        self._current_season_name = season_name
        logger.info("Displaying season '%s' of series '%s'", season_name, series_name)

        series_record: Dict[str, Any] = self.controller.cached_library_data.get(
            series_name, {}
        )
        if not series_record:
            logger.warning("Series '%s' not found in cached data", series_name)
            self._title_label.setText(f"Series '{series_name}' not found")
            return

        self._current_series_data = series_record

        metadata_dict: Dict[str, Any] = series_record.get("metadata", {})
        seasons_dict: Dict[str, Any] = series_record.get("seasons", {})
        library_name = self.controller.current_library_name
        saved_group_id = config.get_series_preference(
            library_name, series_name, "display_group_id", "default"
        )

        # When a display group is configured, regroup seasons_dict so that
        # season_name (which may be a group name like "Arc 1") can be found
        # and episodes appear in the group-defined order.
        if saved_group_id != "default":
            tmdb_id = metadata_dict.get("tmdb_identifier")
            if tmdb_id:
                group_details = tmdb_client.get_episode_group_details(saved_group_id)
                if group_details and "groups" in group_details:
                    # Build episode lookup maps from original seasons
                    db_episodes_by_id: Dict[str, Dict[str, Any]] = {}
                    db_episodes_by_number: Dict[tuple, Dict[str, Any]] = {}
                    for s_name, s_data in seasons_dict.items():
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

                    # Re-group using the configured display group
                    regrouped_seasons: Dict[str, Dict[str, Any]] = {}
                    for group in group_details["groups"]:
                        group_name = (
                            group.get("name") or f"Group {group.get('order', '')}"
                        )
                        episodes_list: List[Dict[str, Any]] = []
                        for group_ep in group.get("episodes", []):
                            ep_id = str(group_ep.get("id", ""))
                            db_ep = db_episodes_by_id.get(ep_id)
                            if not db_ep:
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
                                group_order = group_ep.get("order") + 1
                                ep_name = group_ep.get("name") or "TBA"
                                formatted_name = (
                                    f"{group_name} E{group_order:02d} - {ep_name}"
                                )
                                episodes_list.append(
                                    {
                                        "name": formatted_name,
                                        "path": None,
                                        "tmdb_episode_identifier": ep_id,
                                        "tmdb_identifier": ep_id,
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
                    seasons_dict = regrouped_seasons

        season_data: Dict[str, Any] = seasons_dict.get(season_name, {})
        if not season_data:
            logger.warning(
                "Season '%s' not found for series '%s'", season_name, series_name
            )
            self._title_label.setText(f"Season '{season_name}' not found")
            return

        self._current_season_data = season_data

        # Poster
        season_meta: Dict[str, Any] = season_data.get("metadata", {})
        poster_path: str = season_meta.get("poster_path") or metadata_dict.get(
            "poster_path", ""
        )
        pixmap_assigned = False
        if poster_path and Path(poster_path).is_file():
            pixmap = QPixmap(poster_path)
            if not pixmap.isNull():
                self._poster_label.setPixmap(
                    pixmap.scaled(
                        200,
                        300,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                pixmap_assigned = True
        if not pixmap_assigned:
            self._poster_label.clear()
            self._poster_label.setText("No Poster")

        self._title_label.setText(season_name)

        season_overview = season_meta.get("overview") or ""
        if not season_overview:
            tmdb_id = metadata_dict.get("tmdb_identifier")
            if tmdb_id:
                season_number = self._parse_season_number(season_name)
                if season_number is not None:
                    season_details = tmdb_client.get_season_details(
                        tmdb_id, season_number
                    )
                    if season_details and season_details.get("overview"):
                        season_overview = season_details["overview"]
                        season_meta["overview"] = season_overview
        if not season_overview:
            season_overview = metadata_dict.get("overview", "")
        self._overview_label.setText(season_overview or "No overview available.")

        # Episodes — already in display group order when a group was applied above
        episodes: List[Dict[str, Any]] = list(season_data.get("episodes", []))

        if saved_group_id == "default":

            def _episode_sort_key(episode: Dict[str, Any]) -> int:
                number = episode.get("tmdb_number")
                if isinstance(number, (int, float)):
                    return int(number)
                return 999999

            episodes.sort(key=_episode_sort_key)

        self._current_season_episodes = episodes
        self._build_episode_table(episodes, series_name, season_name)

        local_eps = [ep for ep in episodes if ep.get("path")]
        all_watched = len(local_eps) > 0 and all(
            ep.get("watched", False) for ep in local_eps
        )
        self._mark_season_button.setText(
            "Mark season as unwatched" if all_watched else "Mark season as watched"
        )

        # Update MAL tab visibility based on library type
        library_config = config.libraries.get(library_name, {})
        lib_type = library_config.get("type", "tv")
        mal_tab_index = self._tab_widget.indexOf(self._mal_mapper_tab)
        self._tab_widget.setTabVisible(mal_tab_index, lib_type == "anime")

        # Load TMDB and MAL mapper data for the current page context
        self._load_tmdb_mapper_data()
        self._load_mal_mapper_data()

    # ------------------------------------------------------------------
    # Episode table
    # ------------------------------------------------------------------

    def _on_episode_cell_clicked(self, row: int, column: int) -> None:
        """Play episode when the title column (index 1) is clicked."""
        if column != 1:
            return
        item = self._episode_table.item(row, 0)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole) or ""
        if path:
            self.controller.playback_requested.emit(path)

    def _build_episode_table(
        self, episodes: List[Dict[str, Any]], series_name: str, season_name: str
    ) -> None:
        """Populate the 6-column episode table with progress bars and context menu."""
        table = self._episode_table
        table.setRowCount(0)
        table.setRowCount(len(episodes))
        today_str = datetime.date.today().isoformat()

        # Compute which file paths are shared by multiple episodes
        path_counts: Dict[str, int] = {}
        for ep in episodes:
            p = ep.get("path")
            if p:
                path_counts[p] = path_counts.get(p, 0) + 1
        shared_paths: set[str] = {p for p, c in path_counts.items() if c > 1}

        for row_index, episode in enumerate(episodes):
            self._fill_episode_row(
                table, row_index, episode, series_name, today_str, shared_paths
            )

        # Context menu
        def make_context_menu(
            ep_list: List[Dict[str, Any]],
        ) -> Callable[[QPoint], None]:
            def show_menu(position: QPoint) -> None:
                item = table.itemAt(position)
                if not item:
                    return
                row = item.row()
                ep = ep_list[row]
                if not ep.get("path"):
                    return
                menu = QMenu(table)
                is_watched = bool(ep.get("watched", False))
                text = "Mark as Unwatched" if is_watched else "Mark as Watched"
                toggle = QAction(text, table)

                def on_toggle() -> None:
                    p = ep.get("path", "")
                    if p:
                        self.controller.mark_episode_watched(p, not is_watched)
                        self.display_season(series_name, season_name)

                toggle.triggered.connect(on_toggle)
                menu.addAction(toggle)

                remove = QAction("Remove Episode", table)

                def on_remove() -> None:
                    p = ep.get("path", "")
                    if not p:
                        return
                    from PySide6.QtWidgets import QMessageBox

                    confirm = QMessageBox.question(
                        self,
                        "Remove Episode",
                        f"Remove '{Path(p).name}' from the database? "
                        "Files will be re-discovered on the next scan.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if confirm == QMessageBox.StandardButton.Yes:
                        self.controller.delete_episode(p)
                        self.display_season(series_name, season_name)

                remove.triggered.connect(on_remove)
                menu.addAction(remove)
                menu.exec(table.viewport().mapToGlobal(position))

            return show_menu

        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(make_context_menu(episodes))

    def _fill_episode_row(
        self,
        table: QTableWidget,
        row: int,
        episode: Dict[str, Any],
        series_name: str,
        today_str: str,
        shared_paths: Optional[set[str]] = None,
    ) -> None:
        """Render a single episode row with icon, color, progress bar, and details button."""
        number = str(episode.get("tmdb_number") or (row + 1))
        title = episode.get("tmdb_name") or episode.get("name", "Unknown")
        path = episode.get("path") or ""
        watched = bool(episode.get("watched", False))
        air_date = episode.get("air_date") or ""
        runtime = episode.get("file_runtime") or episode.get("runtime") or 0
        runtime_str = f"{runtime} min" if runtime else ""
        is_shared = bool(path and shared_paths and path in shared_paths)

        # Icon and color
        if is_shared:
            color = QColor("#d97706")  # amber — shared file
            icon = "\u29c9  "
        elif path:
            if watched:
                color = QColor("#888888")
                icon = "\u2713  "
            else:
                color = QColor("#0e5296")
                icon = "\u25cf  "
        else:
            missing = False
            if air_date:
                try:
                    if datetime.date.fromisoformat(air_date) < datetime.date.today():
                        missing = True
                except ValueError:
                    if air_date < today_str:
                        missing = True
            if missing:
                color = QColor("#ef4444")
                icon = "\u2715  "
            else:
                color = QColor("#a78bfa")
                icon = "\u25ca  "

        display_title = f"{icon}{title}"

        # Column 0: #
        num_item = QTableWidgetItem(number)
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        num_item.setForeground(color)
        num_item.setData(Qt.ItemDataRole.UserRole, path)
        table.setItem(row, 0, num_item)

        # Column 1: Title
        tooltip = "Click to play" if path else ""
        if is_shared and self._current_season_episodes:
            shared_numbers = [
                str(i + 1)
                for i, e in enumerate(self._current_season_episodes)
                if e.get("path") == path and e is not episode
            ]
            if shared_numbers:
                tooltip = f"Shared file with episode(s): {', '.join(shared_numbers)}"
        title_item = QTableWidgetItem(display_title)
        title_item.setToolTip(tooltip)
        title_item.setForeground(color)
        table.setItem(row, 1, title_item)

        # Column 2: Air Date
        date_item = QTableWidgetItem(air_date)
        date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        date_item.setForeground(color)
        table.setItem(row, 2, date_item)

        # Column 3: Runtime
        rt_item = QTableWidgetItem(runtime_str)
        rt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        rt_item.setForeground(color)
        table.setItem(row, 3, rt_item)

        # Column 4: Progress bar
        progress = 100 if watched else 0
        if not watched and path:
            pos = episode.get("last_played_position", 0)
            if pos and pos > 0:
                total = (
                    episode.get("file_runtime") or episode.get("runtime") or 0
                ) * 60
                if total > 0:
                    progress = min(int(pos / total * 100), 99)
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(progress)
        progress_bar.setTextVisible(True)
        progress_bar.setFixedHeight(18)
        progress_bar.setStyleSheet(
            "QProgressBar {"
            "  background-color: #1e1e24;"
            "  border: 1px solid #3d3d47;"
            "  border-radius: 4px;"
            "  text-align: center;"
            "  color: #E2E8F0;"
            "  font-size: 11px;"
            "}"
            "QProgressBar::chunk {"
            "  background-color: #2a82da;"
            "  border-radius: 3px;"
            "}"
        )
        pc = QWidget()
        pc.setStyleSheet("background-color: transparent;")
        pl = QHBoxLayout(pc)
        pl.setContentsMargins(4, 2, 4, 2)
        pl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(progress_bar)
        table.setCellWidget(row, 4, pc)

        # Column 5: Details button
        details = QPushButton("...")
        details.setToolTip("Details")
        details.setObjectName(f"detailsEpisodeButton_{row}")
        details.setStyleSheet("padding: 2px 8px; font-weight: bold;")
        if path:

            def make_details_slot(
                target_series: str, target_path: str
            ) -> Callable[[], None]:
                return lambda: self.controller.episode_details_requested.emit(
                    target_series, target_path
                )

            details.clicked.connect(make_details_slot(series_name, path))
        else:
            details.setEnabled(False)
        dc = QWidget()
        dc.setStyleSheet("background-color: transparent;")
        dl = QHBoxLayout(dc)
        dl.setContentsMargins(2, 2, 2, 2)
        dl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(details)
        table.setCellWidget(row, 5, dc)

    # ------------------------------------------------------------------
    # Display group re-ordering
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_season_number(season_name: str) -> Optional[int]:
        """Extract season number from a season name like 'Season 1' or 'S01'."""
        match = re.search(r"(\d+)", season_name)
        if match:
            return int(match.group(1))
        return None

    # ------------------------------------------------------------------
    # Mark season watched
    # ------------------------------------------------------------------

    def _on_mark_season_watched(self) -> None:
        """Toggle watched state for all local episodes in the current season."""
        if not self._current_series_name or not self._current_season_name:
            return
        series = self.controller.cached_library_data.get(self._current_series_name, {})
        season = series.get("seasons", {}).get(self._current_season_name, {})
        eps = season.get("episodes", [])
        local = [e for e in eps if e.get("path")]
        all_watched = len(local) > 0 and all(e.get("watched", False) for e in local)

        self.controller.mark_season_watched(
            self._current_series_name, self._current_season_name, not all_watched
        )
        self.display_season(self._current_series_name, self._current_season_name)

    # ------------------------------------------------------------------
    # Poster context menu
    # ------------------------------------------------------------------

    def _on_poster_context_menu(self, position: QPoint) -> None:
        """Show context menu for changing the season poster."""
        menu = QMenu(self)
        action = QAction("\U0001f5bc  Change Poster\u2026", self)
        action.triggered.connect(self._open_poster_selector)
        menu.addAction(action)
        menu.exec(self._poster_label.mapToGlobal(position))

    def _open_poster_selector(self) -> None:
        """Open PosterSelectorDialog for the current season."""
        if not self._current_season_name:
            return
        from lan_streamer.ui_views.dialogs.poster_selector import PosterSelectorDialog

        logger.info(
            "Opening PosterSelectorDialog for season '%s'", self._current_season_name
        )
        dialog = PosterSelectorDialog(
            media_name=self._current_season_name,
            media_kind="season",
            series_name=self._current_series_name or "",
            parent=self,
        )
        dialog.poster_updated.connect(self._on_poster_updated)
        dialog.exec()

    def _on_poster_updated(self, new_poster_path: str) -> None:
        """Refresh the poster label after a poster change."""
        pixmap = QPixmap(new_poster_path)
        if not pixmap.isNull():
            self._poster_label.setPixmap(
                pixmap.scaled(
                    200,
                    300,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    # ------------------------------------------------------------------
    # Tab 1 — Manual Metadata Mapper (TMDB)
    # ------------------------------------------------------------------

    def _setup_metadata_mapper_tab(self) -> None:
        layout = QVBoxLayout(self._metadata_mapper_tab)
        layout.setSpacing(10)

        info_label = QLabel(
            "Manual metadata mapper — matches TMDB episodes to local files.\n"
            "Uses the series display group and current season automatically."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self._tmdb_mapper_table = QTableWidget()
        self._tmdb_mapper_table.setColumnCount(3)
        self._tmdb_mapper_table.setHorizontalHeaderLabels(
            ["TMDB Episode", "Air Date", "Mapped Local File"]
        )
        self._tmdb_mapper_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._tmdb_mapper_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._tmdb_mapper_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._tmdb_mapper_table.verticalHeader().setDefaultSectionSize(40)
        self._tmdb_mapper_table.verticalHeader().setVisible(False)
        layout.addWidget(self._tmdb_mapper_table)

        self._tmdb_apply_button = QPushButton("Apply Manual Mappings")
        self._tmdb_apply_button.setObjectName("accentButton")
        self._tmdb_apply_button.clicked.connect(self._on_apply_metadata_mappings)
        layout.addWidget(self._tmdb_apply_button)

    def _load_tmdb_mapper_data(self) -> None:
        seasons_dict = self._current_series_data.get("seasons", {})
        self._tmdb_local_episodes = []
        for season_data in seasons_dict.values():
            for ep in season_data.get("episodes", []):
                if ep.get("path"):
                    self._tmdb_local_episodes.append(ep)
        self._tmdb_local_episodes.sort(
            key=lambda x: db.natural_sort_key(Path(x["path"]).name)
        )

        tmdb_id = self._current_series_data.get("metadata", {}).get("tmdb_identifier")
        if not tmdb_id:
            self._tmdb_mapper_table.setRowCount(0)
            return

        saved_group_id = self._current_series_data.get("metadata", {}).get(
            "tmdb_episode_group_id"
        )

        episodes: List[Dict[str, Any]] = []
        current_season = self._current_season_name or ""
        if saved_group_id and saved_group_id != "default":
            group_details = tmdb_client.get_episode_group_details(saved_group_id)
            if group_details and "groups" in group_details:
                season_number = self._parse_season_number(current_season)
                matched_subgroup = None
                for subgroup in group_details.get("groups", []):
                    sg_episodes = subgroup.get("episodes", [])
                    sg_season_numbers = {
                        e.get("season_number")
                        for e in sg_episodes
                        if e.get("season_number")
                    }
                    if season_number is not None and season_number in sg_season_numbers:
                        matched_subgroup = subgroup
                        break
                if not matched_subgroup:
                    for subgroup in group_details.get("groups", []):
                        sg_name = (subgroup.get("name") or "").lower()
                        if (
                            current_season.lower() in sg_name
                            or sg_name in current_season.lower()
                        ):
                            matched_subgroup = subgroup
                            break
                if matched_subgroup:
                    raw = matched_subgroup.get("episodes", [])
                    for ep in raw:
                        episodes.append(
                            {
                                "id": ep.get("id"),
                                "name": ep.get("name"),
                                "episode_number": ep.get("episode_number"),
                                "order": ep.get(
                                    "order", (ep.get("episode_number") or 1) - 1
                                ),
                                "air_date": ep.get("air_date"),
                                "runtime": ep.get("runtime"),
                            }
                        )
        else:
            season_number = self._parse_season_number(current_season)
            if season_number is not None:
                try:
                    raw = tmdb_client.get_episodes(tmdb_id, season_number)
                    for ep in raw:
                        episodes.append(
                            {
                                "id": ep.get("id"),
                                "name": ep.get("name"),
                                "episode_number": ep.get("episode_number"),
                                "order": ep.get("episode_number", 1) - 1,
                                "air_date": ep.get("air_date"),
                                "runtime": ep.get("runtime"),
                            }
                        )
                except Exception as exc:
                    logger.exception("Failed to fetch season episodes: %s", exc)

        self._tmdb_mapper_episodes = episodes
        self._tmdb_mapper_table.setRowCount(len(episodes))

        for row_idx, group_ep in enumerate(episodes):
            ep_order = group_ep.get("order", 0) + 1
            ep_title = group_ep.get("name") or "TBA"
            air_date = group_ep.get("air_date") or "Unknown"

            name_item = QTableWidgetItem(f"E{ep_order:02d} - {ep_title}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tmdb_mapper_table.setItem(row_idx, 0, name_item)

            date_item = QTableWidgetItem(air_date)
            date_item.setFlags(date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tmdb_mapper_table.setItem(row_idx, 1, date_item)

            combo = QComboBox()
            combo.addItem("Unmapped / None", userData=None)
            selected_idx = 0
            for idx, local_ep in enumerate(self._tmdb_local_episodes):
                filename = Path(local_ep["path"]).name
                combo.addItem(filename, userData=local_ep["path"])
                cur_id = local_ep.get("tmdb_episode_identifier") or local_ep.get(
                    "tmdb_identifier"
                )
                if cur_id and str(cur_id) == str(group_ep.get("id")):
                    selected_idx = idx + 1
            combo.setCurrentIndex(selected_idx)
            self._tmdb_mapper_table.setCellWidget(row_idx, 2, combo)

    def _on_apply_metadata_mappings(self) -> None:
        if not self._tmdb_mapper_episodes:
            QMessageBox.warning(
                self, "No TMDB Data", "No TMDB episode data loaded to map against."
            )
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Mapping",
            "Are you sure you want to apply these manual mappings? "
            "This will overwrite existing metadata for these files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        logger.info(
            "Manual Map: Applying mappings for series '%s', season '%s'",
            self._current_series_name,
            self._current_season_name,
        )

        updates = {}
        for row_idx in range(self._tmdb_mapper_table.rowCount()):
            combo = self._tmdb_mapper_table.cellWidget(row_idx, 2)
            if isinstance(combo, QComboBox):
                selected_path = combo.currentData()
                if selected_path:
                    group_ep = self._tmdb_mapper_episodes[row_idx]
                    updates[selected_path] = {
                        "tmdb_identifier": str(group_ep["id"]),
                        "tmdb_episode_identifier": str(group_ep["id"]),
                        "tmdb_name": group_ep.get("name", ""),
                        "tmdb_number": group_ep.get("episode_number")
                        or (group_ep.get("order", 0) + 1),
                        "air_date": group_ep.get("air_date") or "",
                        "runtime": group_ep.get("runtime") or 0,
                    }

        subgroup_ep_ids = {str(ep["id"]) for ep in self._tmdb_mapper_episodes}
        modified_count = 0
        for season_data in self._current_series_data.get("seasons", {}).values():
            for ep in season_data.get("episodes", []):
                p = ep.get("path")
                if p:
                    if p in updates:
                        for k, v in updates[p].items():
                            ep[k] = v
                        modified_count += 1
                    elif str(ep.get("tmdb_episode_identifier")) in subgroup_ep_ids:
                        ep["tmdb_identifier"] = ""
                        ep["tmdb_episode_identifier"] = ""
                        ep["tmdb_name"] = ""
                        ep["tmdb_number"] = None
                        modified_count += 1

        library_name = self.controller.current_library_name
        db.save_library(library_name, self.controller.cached_library_data)
        self.controller.library_loaded.emit()

        QMessageBox.information(
            self,
            "Success",
            f"Successfully applied manual mappings for {modified_count} "
            f"episode file(s).",
        )

        if self._current_series_name and self._current_season_name:
            self.display_season(self._current_series_name, self._current_season_name)

    # ------------------------------------------------------------------
    # Tab 2 — MyAnimeList Mapper
    # ------------------------------------------------------------------

    def _setup_mal_mapper_tab(self) -> None:
        layout = QVBoxLayout(self._mal_mapper_tab)
        layout.setSpacing(10)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search MyAnimeList:"))
        self._mal_search_input = QLineEdit()
        search_layout.addWidget(self._mal_search_input)
        self._mal_search_button = QPushButton("Search")
        self._mal_search_button.clicked.connect(self._on_search_mal)
        search_layout.addWidget(self._mal_search_button)
        layout.addLayout(search_layout)

        # macOS QComboBox popup rendering issues — use a label + dialog instead
        self._mal_selected_label = QLabel("No MAL entries loaded")
        self._mal_selected_label.setStyleSheet(
            "padding: 6px 10px; background-color: #1e1e24; "
            "border: 1px solid #3d3d47; border-radius: 4px; color: #E2E8F0;"
        )
        layout.addWidget(self._mal_selected_label)

        add_another_layout = QHBoxLayout()
        self._mal_add_entry_button = QPushButton("Add Another MAL Entry")
        self._mal_add_entry_button.setObjectName("accentButton")
        self._mal_add_entry_button.clicked.connect(self._on_add_mal_entry)
        add_another_layout.addWidget(self._mal_add_entry_button)
        add_another_layout.addStretch()
        layout.addLayout(add_another_layout)

        self._mal_mapper_table = QTableWidget()
        self._mal_mapper_table.setColumnCount(3)
        self._mal_mapper_table.setHorizontalHeaderLabels(
            ["MAL Entry", "Episode #", "Mapped Local File"]
        )
        self._mal_mapper_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._mal_mapper_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._mal_mapper_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._mal_mapper_table.setColumnWidth(1, 100)
        self._mal_mapper_table.verticalHeader().setDefaultSectionSize(40)
        self._mal_mapper_table.verticalHeader().setVisible(False)
        layout.addWidget(self._mal_mapper_table)

        self._mal_apply_button = QPushButton("Apply MyAnimeList Mappings")
        self._mal_apply_button.setObjectName("accentButton")
        self._mal_apply_button.clicked.connect(self._on_apply_mal_mappings)
        layout.addWidget(self._mal_apply_button)

    def _load_mal_mapper_data(self) -> None:
        season_name = self._current_season_name or ""
        self._mal_local_episodes = []
        self._mal_entries = []
        logger.info("Loading MAL mapper data for season: '%s'", season_name)
        if not season_name:
            return

        season_data = self._current_series_data.get("seasons", {}).get(season_name, {})
        for ep in season_data.get("episodes", []):
            if ep.get("path"):
                self._mal_local_episodes.append(ep)
        self._mal_local_episodes.sort(
            key=lambda x: db.natural_sort_key(Path(x["path"]).name)
        )

        self._mal_mapper_table.setRowCount(0)
        self._mal_selected_anime_id = None
        self._mal_row_episodes = []
        self._mal_selected_label.setText("No MAL entries loaded")

        if not myanimelist_client.is_configured():
            self._mal_selected_label.setText(
                "MyAnimeList API Client ID not configured in settings"
            )
            return

        # Collect unique MAL anime IDs from per-episode saved data
        episode_mal_ids: Dict[int, list[str]] = {}
        for ep in self._mal_local_episodes:
            aid = ep.get("myanimelist_anime_id")
            if aid is not None:
                episode_mal_ids.setdefault(aid, []).append(ep.get("path", ""))

        if episode_mal_ids:
            loaded_count = 0
            for aid in episode_mal_ids:
                details = myanimelist_client.get_anime_details(aid)
                if details:
                    title = details.get("title") or f"ID: {aid}"
                    self._mal_entries.append({"id": aid, "title": title})
                    self._populate_mal_episodes(details, append=loaded_count > 0)
                    loaded_count += 1
            if loaded_count > 0:
                if loaded_count == 1:
                    self._mal_selected_label.setText(
                        f"1 MAL entry loaded ({self._mal_entries[0]['title']})"
                    )
                else:
                    self._mal_selected_label.setText(
                        f"{loaded_count} MAL entries loaded"
                    )
                return

        # Fall back to season-level myanimelist_id
        saved_mal_id = season_data.get("metadata", {}).get("myanimelist_id")
        if saved_mal_id:
            details = myanimelist_client.get_anime_details(saved_mal_id)
            if details:
                title = details.get("title") or f"ID: {saved_mal_id}"
                self._mal_selected_anime_id = saved_mal_id
                self._mal_entries.append({"id": saved_mal_id, "title": title})
                self._mal_selected_label.setText(f"1 MAL entry loaded ({title})")
                self._populate_mal_episodes(details, append=False)
                return

        # Auto-search when no saved MAL entry exists
        search_text = self._current_series_name or ""
        if search_text:
            try:
                results = myanimelist_client.search_anime(search_text)
            except Exception:
                results = []
            if results:
                anime_id = results[0].get("id")
                if anime_id:
                    self._on_mal_entry_selected(anime_id)
                    return
        self._mal_search_input.setText(search_text)

    def _on_search_mal(self) -> None:
        """Search MAL and replace the mapper table with the chosen entry."""
        query = self._mal_search_input.text().strip()
        logger.info("Search MyAnimeList: '%s'", query)
        if not query:
            return

        try:
            results = myanimelist_client.search_anime(query)
        except Exception as exc:
            logger.exception("Failed to search MyAnimeList: %s", exc)
            QMessageBox.warning(
                self,
                "Search Failed",
                f"Could not search MyAnimeList: {exc}",
            )
            return

        if not results:
            QMessageBox.information(
                self,
                "No Results",
                "No MyAnimeList entries found for your query.",
            )
            return

        from lan_streamer.ui_views.dialogs.mal_search_results import (
            MalSearchResultsDialog,
        )

        dialog = MalSearchResultsDialog(results, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            anime_id = dialog.selected_id()
            if anime_id:
                self._on_mal_entry_selected(anime_id)

    def _on_add_mal_entry(self) -> None:
        """Open MAL search and append the chosen entry to the existing table."""
        query = self._mal_search_input.text().strip()
        if not query:
            QMessageBox.information(
                self,
                "Search Required",
                "Enter a search term first, then click Add Another MAL Entry.",
            )
            return

        try:
            results = myanimelist_client.search_anime(query)
        except Exception as exc:
            logger.exception("Failed to search MyAnimeList: %s", exc)
            QMessageBox.warning(
                self, "Search Failed", f"Could not search MyAnimeList: {exc}"
            )
            return

        if not results:
            QMessageBox.information(
                self,
                "No Results",
                "No MyAnimeList entries found for your query.",
            )
            return

        from lan_streamer.ui_views.dialogs.mal_search_results import (
            MalSearchResultsDialog,
        )

        dialog = MalSearchResultsDialog(results, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            anime_id = dialog.selected_id()
            title = dialog.selected_title()
            if anime_id:
                self._append_mal_entry(anime_id, title or f"ID: {anime_id}")

    def _on_mal_entry_selected(self, anime_id: int) -> None:
        """Replace the entire mapper table with a single MAL entry."""
        self._mal_selected_anime_id = anime_id
        self._mal_entries = []
        self._mal_mapper_table.setRowCount(0)
        self._mal_row_episodes = []
        logger.info("MAL entry selected ID: %s", anime_id)
        if not anime_id:
            return

        try:
            details = myanimelist_client.get_anime_details(anime_id)
        except Exception as exc:
            logger.exception("Failed to fetch MAL details for ID %s: %s", anime_id, exc)
            QMessageBox.warning(
                self, "Fetch Failed", f"Could not fetch MyAnimeList details: {exc}"
            )
            return
        if details:
            title = details.get("title") or f"ID: {anime_id}"
            self._mal_entries.append({"id": anime_id, "title": title})
            self._mal_selected_label.setText(f"1 MAL entry loaded ({title})")
            self._populate_mal_episodes(details, append=False)

    def _append_mal_entry(self, anime_id: int, title: str) -> None:
        """Append a new MAL entry's episodes to the existing mapper table."""
        logger.info("Appending MAL entry ID: %s (%s)", anime_id, title)
        try:
            details = myanimelist_client.get_anime_details(anime_id)
        except Exception as exc:
            logger.exception("Failed to fetch MAL details for ID %s: %s", anime_id, exc)
            QMessageBox.warning(
                self, "Fetch Failed", f"Could not fetch MyAnimeList details: {exc}"
            )
            return
        if details:
            self._mal_entries.append({"id": anime_id, "title": title})
            self._mal_selected_label.setText(
                f"{len(self._mal_entries)} MAL entries loaded"
            )
            self._populate_mal_episodes(details, append=True, filter_used_paths=True)

    def _populate_mal_episodes(
        self,
        details: Dict[str, Any],
        append: bool = False,
        filter_used_paths: bool = False,
    ) -> None:
        num_episodes = details.get("num_episodes") or 0
        if num_episodes == 0:
            num_episodes = max(12, len(self._mal_local_episodes) + 5)

        anime_id: Optional[int] = details.get("id")
        anime_title: str = details.get("title") or f"ID: {anime_id}"

        start_row = self._mal_mapper_table.rowCount() if append else 0
        if not append:
            self._mal_mapper_table.setRowCount(0)
            self._mal_row_episodes = []

        new_ep_numbers = list(range(1, num_episodes + 1))
        total_rows = start_row + num_episodes
        self._mal_mapper_table.setRowCount(total_rows)
        self._mal_row_episodes.extend(new_ep_numbers)

        # Determine whether this is the first entry — for auto-matching
        is_first_entry = start_row == 0 and not any(
            ep.get("myanimelist_anime_id") for ep in self._mal_local_episodes
        )

        # Collect local file paths already used in existing rows
        used_paths: set[str] = set()
        for check_row in range(start_row):
            combo = self._mal_mapper_table.cellWidget(check_row, 2)
            if isinstance(combo, QComboBox) and combo.currentData():
                used_paths.add(combo.currentData())

        for offset, mal_ep_num in enumerate(new_ep_numbers):
            row_idx = start_row + offset

            # Column 0: MAL Entry (anime title)
            entry_item = QTableWidgetItem(anime_title)
            entry_item.setData(Qt.ItemDataRole.UserRole, anime_id)
            entry_item.setFlags(entry_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._mal_mapper_table.setItem(row_idx, 0, entry_item)

            # Column 1: Episode #
            ep_item = QTableWidgetItem(f"Episode {mal_ep_num}")
            ep_item.setFlags(ep_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._mal_mapper_table.setItem(row_idx, 1, ep_item)

            # Column 2: Mapped Local File
            combo = QComboBox()
            combo.addItem("Unmapped / None", userData=None)
            selected_idx = 0
            for idx, local_ep in enumerate(self._mal_local_episodes):
                local_path = local_ep["path"]
                if filter_used_paths and local_path in used_paths:
                    continue
                filename = Path(local_path).name
                combo.addItem(filename, userData=local_path)
                cur_anime_id = local_ep.get("myanimelist_anime_id")
                cur_ep_num = local_ep.get("myanimelist_episode_number")
                if cur_anime_id == anime_id and cur_ep_num == mal_ep_num:
                    selected_idx = combo.count() - 1

            # Auto-match sequentially only for the first entry
            if (
                selected_idx == 0
                and is_first_entry
                and offset < len(self._mal_local_episodes)
            ):
                candidate_path = self._mal_local_episodes[offset]["path"]
                for combo_idx in range(1, combo.count()):
                    if combo.itemData(combo_idx) == candidate_path:
                        selected_idx = combo_idx
                        break

            combo.setCurrentIndex(selected_idx)
            self._mal_mapper_table.setCellWidget(row_idx, 2, combo)

    def _on_apply_mal_mappings(self) -> None:
        season_name = self._current_season_name
        if not season_name:
            return

        if not self._mal_entries:
            QMessageBox.warning(
                self,
                "No MAL Entry Selected",
                "Please select at least one MyAnimeList entry first.",
            )
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Mapping",
            "Are you sure you want to apply these MyAnimeList mappings?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Collect active anime IDs from the table rows
        active_ids: set[int] = set()
        updates = {}
        for row_idx in range(self._mal_mapper_table.rowCount()):
            entry_item = self._mal_mapper_table.item(row_idx, 0)
            if entry_item is None:
                continue
            row_anime_id: Optional[int] = entry_item.data(Qt.ItemDataRole.UserRole)
            if row_anime_id is None:
                continue
            active_ids.add(row_anime_id)

            combo = self._mal_mapper_table.cellWidget(row_idx, 2)
            if isinstance(combo, QComboBox):
                selected_path = combo.currentData()
                if selected_path:
                    mal_ep_num = self._mal_row_episodes[row_idx]
                    updates[selected_path] = {
                        "myanimelist_anime_id": row_anime_id,
                        "myanimelist_episode_number": mal_ep_num,
                    }

        season_data = self._current_series_data.get("seasons", {}).get(season_name, {})
        if "metadata" not in season_data:
            season_data["metadata"] = {}

        # Set season-level MAL ID only when there's exactly one entry
        if len(self._mal_entries) == 1:
            season_data["metadata"]["myanimelist_id"] = self._mal_entries[0]["id"]
        else:
            season_data["metadata"]["myanimelist_id"] = None

        modified_count = 0
        for ep in season_data.get("episodes", []):
            p = ep.get("path")
            if p:
                if p in updates:
                    ep["myanimelist_anime_id"] = updates[p]["myanimelist_anime_id"]
                    ep["myanimelist_episode_number"] = updates[p][
                        "myanimelist_episode_number"
                    ]
                    modified_count += 1
                elif ep.get("myanimelist_anime_id") in active_ids:
                    ep["myanimelist_anime_id"] = None
                    ep["myanimelist_episode_number"] = None
                    modified_count += 1

        logger.info(
            "Applied MAL mappings to %d episode(s) in season '%s'",
            modified_count,
            season_name,
        )

        db.save_library(
            self.controller.current_library_name, self.controller.cached_library_data
        )
        self.controller.library_loaded.emit()

        QMessageBox.information(
            self,
            "Mappings Applied",
            f"Successfully applied MyAnimeList mappings to {modified_count} "
            f"episode(s).",
        )

        if self._current_series_name and self._current_season_name:
            self.display_season(self._current_series_name, self._current_season_name)
