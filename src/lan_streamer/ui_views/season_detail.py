"""Full-page season detail view with poster, overview, and episode table."""

import datetime
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QFont, QPixmap, QColor, QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lan_streamer.system.config import config
from lan_streamer.ui_views.controller import Controller

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMenu
    from lan_streamer.providers.tmdb import tmdb_client
else:
    from lan_streamer.ui_views.proxy import QMenu, tmdb_client

logger = logging.getLogger(__name__)


class SeasonDetailView(QWidget):
    """Full-page season detail with poster, overview, and episode table.

    Reads data from ``controller.cached_library_data`` and supports TMDB
    display group re-ordering.
    """

    back_requested = Signal()
    episode_details_requested = Signal(str, str)  # series_name, episode_path

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
        left_column = QVBoxLayout()
        left_column.setSpacing(12)
        left_column.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._setup_left_column(left_column)
        top_row.addLayout(left_column)

        # Right column: episode table
        right_column = QVBoxLayout()
        right_column.setSpacing(10)
        episode_header = QLabel("Episodes")
        episode_header_font = QFont()
        episode_header_font.setPointSize(14)
        episode_header_font.setBold(True)
        episode_header.setFont(episode_header_font)
        right_column.addWidget(episode_header)

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
        right_column.addWidget(self._episode_table, 1)
        top_row.addLayout(right_column, 1)
        self._content_layout.addLayout(top_row)

        # Season action row
        self._season_actions_layout = QHBoxLayout()
        self._season_actions_layout.setSpacing(10)
        self._mark_season_button = QPushButton()
        self._mark_season_button.setObjectName("markSeasonWatchedButton")
        self._mark_season_button.clicked.connect(self._on_mark_season_watched)
        self._season_actions_layout.addWidget(self._mark_season_button)
        self._season_actions_layout.addStretch()
        self._content_layout.addLayout(self._season_actions_layout)

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
        layout.addWidget(self._title_label)

        self._overview_label = QLabel()
        overview_font = QFont()
        overview_font.setPointSize(12)
        self._overview_label.setFont(overview_font)
        self._overview_label.setWordWrap(True)
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

        metadata_dict: Dict[str, Any] = series_record.get("metadata", {})
        seasons_dict: Dict[str, Any] = series_record.get("seasons", {})
        season_data: Dict[str, Any] = seasons_dict.get(season_name, {})
        if not season_data:
            logger.warning(
                "Season '%s' not found for series '%s'", season_name, series_name
            )
            self._title_label.setText(f"Season '{season_name}' not found")
            return

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

        # Episodes with optional display-group re-ordering
        episodes: List[Dict[str, Any]] = list(season_data.get("episodes", []))
        library_name = self.controller.current_library_name
        saved_group_id = config.get_series_preference(
            library_name, series_name, "display_group_id", "default"
        )

        if saved_group_id != "default":
            tmdb_id = metadata_dict.get("tmdb_identifier")
            if tmdb_id:
                group_details = tmdb_client.get_episode_group_details(saved_group_id)
                if group_details and "groups" in group_details:
                    order_map = self._build_order_map(episodes, group_details)
                    if order_map:
                        episodes.sort(
                            key=lambda ep: order_map.get(episodes.index(ep), 999999)
                        )

        if saved_group_id == "default":

            def _episode_sort_key(episode: Dict[str, Any]) -> int:
                number = episode.get("tmdb_number")
                if isinstance(number, (int, float)):
                    return int(number)
                return 999999

            episodes.sort(key=_episode_sort_key)

        self._build_episode_table(episodes, series_name, season_name)

        local_eps = [ep for ep in episodes if ep.get("path")]
        all_watched = len(local_eps) > 0 and all(
            ep.get("watched", False) for ep in local_eps
        )
        self._mark_season_button.setText(
            "Mark season as unwatched" if all_watched else "Mark season as watched"
        )

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

        for row_index, episode in enumerate(episodes):
            self._fill_episode_row(table, row_index, episode, series_name, today_str)

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
    ) -> None:
        """Render a single episode row with icon, color, progress bar, and details button."""
        number = str(episode.get("tmdb_number") or (row + 1))
        title = episode.get("tmdb_name") or episode.get("name", "Unknown")
        path = episode.get("path") or ""
        watched = bool(episode.get("watched", False))
        air_date = episode.get("air_date") or ""
        runtime = episode.get("file_runtime") or episode.get("runtime") or 0
        runtime_str = f"{runtime} min" if runtime else ""

        # Icon and color
        if path:
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
        title_item = QTableWidgetItem(display_title)
        title_item.setToolTip("Click to play" if path else "")
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

            def make_ds(ts: str, tp: str) -> Callable[[], None]:
                return lambda: self.episode_details_requested.emit(ts, tp)

            details.clicked.connect(make_ds(series_name, path))
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

    @staticmethod
    def _build_order_map(
        episodes: List[Dict[str, Any]], group_details: Dict[str, Any]
    ) -> Dict[int, int]:
        """Map episode index to display group order, matching by TMDB identifier or number."""
        order_map: Dict[int, int] = {}
        for group in group_details.get("groups", []):
            for gep in group.get("episodes", []):
                gid = str(gep.get("id", ""))
                gorder = gep.get("order", 0)
                gnum = gep.get("episode_number")
                for ep_index, ep in enumerate(episodes):
                    eid = str(ep.get("tmdb_episode_identifier") or "")
                    if eid and eid == gid:
                        order_map[ep_index] = gorder
                        break
                    en = ep.get("tmdb_number")
                    if en is not None and en == gnum:
                        order_map[ep_index] = gorder
                        break
        return order_map

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
