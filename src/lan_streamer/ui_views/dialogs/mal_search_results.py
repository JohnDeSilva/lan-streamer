"""Dialog for selecting a MyAnimeList entry from search results."""

import logging
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

logger = logging.getLogger(__name__)

THUMBNAIL_SIZE = 96


def _status_label(status: str) -> str:
    mapping = {
        "finished_airing": "Finished",
        "currently_airing": "Airing",
        "not_yet_aired": "Upcoming",
    }
    return mapping.get(status, status.replace("_", " ").title() if status else "")


def _build_alt_titles_text(item: Dict[str, Any]) -> str:
    parts: list[str] = []
    en = item.get("english_title") or ""
    if en:
        parts.append(f"English: {en}")
    synonyms = item.get("alternative_titles") or []
    if synonyms:
        parts.append(f"Also known as: {', '.join(synonyms[:3])}")
    genres = item.get("genres") or []
    if genres:
        parts.append(f"Genres: {', '.join(genres)}")
    return "  |  ".join(parts)


class MalSearchResultsDialog(QDialog):
    """Modal dialog that displays MyAnimeList search results in a table.

    Columns: poster thumbnail, title, air date, episodes, status, synopsis,
    alternate titles. Poster thumbnails are fetched asynchronously from the MAL CDN.

    After :meth:`exec` returns ``Accepted``, call :meth:`selected_id` and
    :meth:`selected_title` to retrieve the chosen entry.
    """

    def __init__(
        self,
        results: List[Dict[str, Any]],
        parent: Optional[QWidget] = None,
        existing_mapped_ids: Optional[Set[int]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MyAnimeList Search Results")
        self.resize(900, 520)

        self._selected_id: Optional[int] = None
        self._selected_title: Optional[str] = None
        self._cached_thumbnails: Dict[str, QIcon] = {}
        self._pending_thumbnails: List[tuple[int, str]] = []
        self._existing_mapped_ids: Set[int] = existing_mapped_ids or set()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        header = QLabel("Select a MyAnimeList entry:")
        layout.addWidget(header)

        self._results_table = QTableWidget()
        self._results_table.setColumnCount(7)
        self._results_table.setHorizontalHeaderLabels(
            [
                "",
                "Title",
                "Air Date",
                "Episodes",
                "Status",
                "Synopsis",
                "Alternate Titles",
            ]
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.Stretch
        )
        self._results_table.setColumnWidth(0, THUMBNAIL_SIZE + 16)
        self._results_table.setColumnWidth(2, 100)
        self._results_table.setColumnWidth(3, 70)
        self._results_table.setColumnWidth(4, 80)
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
            anime_id: Optional[int] = item.get("id")
            title: str = item.get("title") or "Unknown"
            start_date: str = item.get("start_date") or ""
            num_episodes: int = item.get("num_episodes") or 0
            status: str = item.get("status") or ""
            synopsis: str = item.get("synopsis") or ""
            alternate_titles_text = _build_alt_titles_text(item)

            poster_url: str = item.get("poster_path") or ""

            # Column 0: poster thumbnail (placeholder until async load)
            thumb_item = QTableWidgetItem()
            thumb_item.setData(Qt.ItemDataRole.UserRole, anime_id)
            thumb_item.setData(Qt.ItemDataRole.UserRole + 1, title)
            if poster_url:
                self._pending_thumbnails.append((row_index, poster_url))
            self._results_table.setItem(row_index, 0, thumb_item)

            # Column 1: Title
            is_mapped = anime_id is not None and anime_id in self._existing_mapped_ids
            title_text = f"● {title}" if is_mapped else title
            title_item = QTableWidgetItem(title_text)
            if is_mapped:
                title_item.setForeground(QBrush(QColor("#4caf50")))
            if alternate_titles_text:
                title_item.setToolTip(alternate_titles_text)
            self._results_table.setItem(row_index, 1, title_item)

            # Column 2: Air Date
            date_item = QTableWidgetItem(start_date)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_table.setItem(row_index, 2, date_item)

            # Column 3: Episodes
            ep_item = QTableWidgetItem(str(num_episodes) if num_episodes else "?")
            ep_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_table.setItem(row_index, 3, ep_item)

            # Column 4: Status
            status_item = QTableWidgetItem(_status_label(status))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_table.setItem(row_index, 4, status_item)

            # Column 5: Synopsis
            synopsis_item = QTableWidgetItem(
                synopsis[:200] + ("..." if len(synopsis) > 200 else "")
            )
            synopsis_item.setToolTip(synopsis)
            self._results_table.setItem(row_index, 5, synopsis_item)

            # Column 6: Alternate Titles
            alt_item = QTableWidgetItem(alternate_titles_text)
            alt_item.setToolTip(alternate_titles_text)
            self._results_table.setItem(row_index, 6, alt_item)

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
                logger.debug("Failed to load MAL poster thumbnail: %s", poster_url)
                return
        item = self._results_table.item(row_index, 0)
        if item is not None:
            item.setIcon(icon)

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
            logger.info("No MAL entry selected in dialog")

    def _capture_selection(self, item: QTableWidgetItem) -> None:
        self._selected_id = item.data(Qt.ItemDataRole.UserRole)
        self._selected_title = item.data(Qt.ItemDataRole.UserRole + 1)
        logger.info(
            "MAL entry selected in dialog: '%s' (ID: %s)",
            self._selected_title,
            self._selected_id,
        )

    def selected_id(self) -> Optional[int]:
        """Return the MAL anime ID chosen by the user, or ``None``."""
        return self._selected_id

    def selected_title(self) -> Optional[str]:
        """Return the title of the chosen MAL entry, or ``None``."""
        return self._selected_title
