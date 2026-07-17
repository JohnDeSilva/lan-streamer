"""Dialog for selecting a TMDB series entry from search results."""

import logging
import re
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lan_streamer.ui_views.proxy import tmdb_client

logger = logging.getLogger(__name__)

THUMBNAIL_SIZE = 96


def _parse_season_number(season_name: str) -> Optional[int]:
    match = re.search(r"(\d+)", season_name)
    return int(match.group(1)) if match else None


class TmdbSearchResultsDialog(QDialog):
    """Modal dialog that displays TMDB series search results in a table.

    Columns: poster thumbnail, title, seasons, first air date, overview.

    After :meth:`exec` returns ``Accepted``, call :meth:`selected_id`,
    :meth:`selected_title`, and :meth:`selected_season_number` to
    retrieve the chosen entry.
    """

    def __init__(
        self,
        results: List[Dict[str, Any]],
        current_season_name: str = "",
        parent: Optional[QWidget] = None,
        existing_mapped_ids: Optional[Set[int]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("TMDB Series Search Results")
        self.resize(900, 520)

        self._selected_id: Optional[int] = None
        self._selected_title: Optional[str] = None
        self._selected_season_number: int = 1
        self._current_season_name = current_season_name
        self._cached_thumbnails: Dict[str, QIcon] = {}
        self._pending_thumbnails: List[tuple[int, str]] = []
        self._existing_mapped_ids: Set[int] = existing_mapped_ids or set()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        header = QLabel("Select a TMDB series entry:")
        layout.addWidget(header)

        self._results_table = QTableWidget()
        self._results_table.setColumnCount(5)
        self._results_table.setHorizontalHeaderLabels(
            ["", "Title", "Seasons", "First Air Date", "Overview"]
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self._results_table.setColumnWidth(0, THUMBNAIL_SIZE + 16)
        self._results_table.setColumnWidth(2, 70)
        self._results_table.setColumnWidth(3, 100)
        self._results_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._results_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._results_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self._results_table.verticalHeader().setDefaultSectionSize(THUMBNAIL_SIZE + 10)
        self._results_table.setStyleSheet(
            """
            QTableWidget {
                background-color: #222222;
                border: 1px solid #444444;
                border-radius: 6px;
                font-size: 13px;
                gridline-color: #333333;
            }
            QTableWidget::item {
                padding: 6px 10px;
                color: #f3f4f6;
            }
            QTableWidget::item:selected {
                background-color: #1a6bb5;
                color: #ffffff;
            }
            """
        )
        self._results_table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._results_table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._results_table)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._populate_table(results)

        if self._results_table.rowCount() > 0:
            self._results_table.selectRow(0)

    def _populate_table(self, results: List[Dict[str, Any]]) -> None:
        self._results_table.setRowCount(len(results))
        self._pending_thumbnails = []

        for row_index, item in enumerate(results):
            series_id: Optional[int] = item.get("id")
            title: str = item.get("name") or item.get("title") or "Unknown"
            first_air_date: str = item.get("first_air_date") or ""
            overview: str = item.get("overview") or ""
            season_count: int = 0
            poster_path: str = item.get("poster_path") or ""

            thumb_item = QTableWidgetItem()
            thumb_item.setData(Qt.ItemDataRole.UserRole, series_id)
            thumb_item.setData(Qt.ItemDataRole.UserRole + 1, title)
            if poster_path:
                poster_url = f"https://image.tmdb.org/t/p/w185{poster_path}"
                self._pending_thumbnails.append((row_index, poster_url))
            self._results_table.setItem(row_index, 0, thumb_item)

            is_mapped = series_id is not None and series_id in self._existing_mapped_ids
            title_text = f"● {title}" if is_mapped else title
            title_item = QTableWidgetItem(title_text)
            if is_mapped:
                title_item.setForeground(QBrush(QColor("#4caf50")))
            self._results_table.setItem(row_index, 1, title_item)

            seasons_item = QTableWidgetItem(str(season_count) if season_count else "?")
            seasons_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_table.setItem(row_index, 2, seasons_item)

            date_item = QTableWidgetItem(first_air_date)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_table.setItem(row_index, 3, date_item)

            overview_item = QTableWidgetItem(
                overview[:200] + ("..." if len(overview) > 200 else "")
            )
            overview_item.setToolTip(overview)
            self._results_table.setItem(row_index, 4, overview_item)

        if self._pending_thumbnails:
            QTimer.singleShot(0, self._process_thumbnail_batch)

    def _process_thumbnail_batch(self) -> None:
        batch = self._pending_thumbnails[:3]
        self._pending_thumbnails = self._pending_thumbnails[3:]
        for row_index, poster_url in batch:
            self._assign_thumbnail_icon(row_index, poster_url)
        if self._pending_thumbnails:
            QTimer.singleShot(0, self._process_thumbnail_batch)

    def _assign_thumbnail_icon(self, row_index: int, poster_url: str) -> None:
        if poster_url in self._cached_thumbnails:
            icon = self._cached_thumbnails[poster_url]
        else:
            try:
                import requests as http_requests

                response = http_requests.get(poster_url, timeout=5)
                response.raise_for_status()
                pixmap = QPixmap()
                if pixmap.loadFromData(response.content):
                    scaled = pixmap.scaled(
                        THUMBNAIL_SIZE,
                        THUMBNAIL_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    icon = QIcon(scaled)
                    self._cached_thumbnails[poster_url] = icon
                else:
                    return
            except Exception:
                logger.debug("Failed to load TMDB poster thumbnail: %s", poster_url)
                return
        item = self._results_table.item(row_index, 0)
        if item is not None:
            item.setIcon(icon)

    def _resolve_season_number(self, series_id: int) -> int:
        """Auto-match the best season for the current season name."""
        try:
            seasons = tmdb_client.get_seasons(series_id)
        except Exception:
            seasons = []
        if not seasons:
            return 1

        season_number = _parse_season_number(self._current_season_name)
        if season_number is not None:
            for season in seasons:
                sn = season.get("season_number")
                if sn == season_number:
                    return sn
            for season in seasons:
                sn = season.get("season_number")
                sname = (season.get("name") or "").lower()
                cur_lower = self._current_season_name.lower()
                if cur_lower in sname or sname in cur_lower:
                    return sn or 1
            # Fall back to the parsed number
            if any(s.get("season_number") == season_number for s in seasons):
                return season_number

        # Default to first non-special season
        for season in seasons:
            sn = season.get("season_number")
            if sn and sn > 0:
                return sn
        return 1

    def _capture_selection(self, item: QTableWidgetItem) -> None:
        series_id = item.data(Qt.ItemDataRole.UserRole)
        title = item.data(Qt.ItemDataRole.UserRole + 1)
        if series_id:
            self._selected_id = int(series_id)
            self._selected_title = title
            self._selected_season_number = self._resolve_season_number(
                self._selected_id
            )
            logger.info(
                "TMDB entry selected: '%s' (ID: %s, Season: %s)",
                title,
                self._selected_id,
                self._selected_season_number,
            )

    def _on_cell_double_clicked(self, row: int, _column: int) -> None:
        item = self._results_table.item(row, 0)
        if item:
            self._capture_selection(item)
            self.accept()

    def _on_cell_clicked(self, row: int, _column: int) -> None:
        item = self._results_table.item(row, 0)
        if item:
            self._capture_selection(item)

    def _on_accept(self) -> None:
        selected = self._results_table.selectedItems()
        if selected:
            row = selected[0].row()
            item = self._results_table.item(row, 0)
            if item:
                self._capture_selection(item)
                self.accept()
        else:
            logger.info("No TMDB entry selected in dialog")

    def selected_id(self) -> Optional[int]:
        """Return the TMDB series ID chosen by the user, or ``None``."""
        return self._selected_id

    def selected_title(self) -> Optional[str]:
        """Return the title of the chosen TMDB entry, or ``None``."""
        return self._selected_title

    def selected_season_number(self) -> int:
        """Return the season number resolved for the chosen entry."""
        return self._selected_season_number
