"""Full-page season detail view with poster, cast, and episode table."""

import logging
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QFont, QPixmap, QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Season, Series
from lan_streamer.db.queries_cast import get_cast_for_series

logger = logging.getLogger(__name__)


class SeasonDetailView(QWidget):
    """Full-page view for displaying season details with cast and episode list."""

    back_requested = Signal()
    episode_details_requested = Signal(str, str)  # series_name, episode_path
    cast_member_clicked = Signal(str)  # person_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_series_name: Optional[str] = None
        self._current_season_name: Optional[str] = None
        self._season_id: Optional[str] = None
        self._series_id: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        back_button = QPushButton("← Back")
        back_button.clicked.connect(self.back_requested.emit)
        layout.addWidget(back_button)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll)

        top_row = QHBoxLayout()
        top_row.setSpacing(20)

        left_column = QVBoxLayout()
        self._poster_label = QLabel()
        self._poster_label.setFixedSize(200, 300)
        self._poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster_label.setStyleSheet("background-color: #1a1a2e; color: #666;")
        self._poster_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._poster_label.customContextMenuRequested.connect(
            self._on_poster_context_menu
        )
        self._poster_label.setToolTip("Right-click to change poster")
        left_column.addWidget(self._poster_label)

        self._title_label = QLabel()
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        left_column.addWidget(self._title_label)

        self._series_label = QLabel()
        series_font = QFont()
        series_font.setPointSize(12)
        self._series_label.setFont(series_font)
        self._series_label.setStyleSheet("color: #94A3B8;")
        left_column.addWidget(self._series_label)

        self._episode_count_label = QLabel()
        self._episode_count_label.setStyleSheet("color: #94A3B8;")
        left_column.addWidget(self._episode_count_label)

        left_column.addStretch()
        top_row.addLayout(left_column)

        right_column = QVBoxLayout()
        episodes_header = QLabel("Episodes")
        episodes_header_font = QFont()
        episodes_header_font.setPointSize(14)
        episodes_header_font.setBold(True)
        episodes_header.setFont(episodes_header_font)
        right_column.addWidget(episodes_header)

        self._episode_table = QTableWidget()
        self._episode_table.setColumnCount(4)
        self._episode_table.setHorizontalHeaderLabels(
            ["#", "Title", "Air Date", "Runtime"]
        )
        self._episode_table.horizontalHeader().setStretchLastSection(True)
        self._episode_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._episode_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._episode_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._episode_table.verticalHeader().setVisible(False)
        right_column.addWidget(self._episode_table, 1)
        top_row.addLayout(right_column, 1)

        self._content_layout.addLayout(top_row)

        # Cast section
        cast_header = QLabel("Cast")
        cast_header_font = QFont()
        cast_header_font.setPointSize(14)
        cast_header_font.setBold(True)
        cast_header.setFont(cast_header_font)
        self._content_layout.addWidget(cast_header)

        self._cast_scroll = QScrollArea()
        self._cast_scroll.setWidgetResizable(True)
        self._cast_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cast_scroll.setMaximumHeight(300)
        self._cast_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        cast_scroll_content = QWidget()
        self._cast_grid = QHBoxLayout(cast_scroll_content)
        self._cast_grid.setSpacing(10)
        self._cast_grid.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._cast_scroll.setWidget(cast_scroll_content)
        self._content_layout.addWidget(self._cast_scroll)

    def display_season(self, series_name: str, season_name: str) -> None:
        self._current_series_name = series_name
        self._current_season_name = season_name
        self._title_label.setText(season_name)
        self._series_label.setText(f"Series: {series_name}")

        with get_session() as session:
            series = session.scalars(
                select(Series).where(Series.name == series_name)
            ).first()
            if series is None:
                self._title_label.setText(f"Series '{series_name}' not found")
                return

            season = session.scalars(
                select(Season).where(
                    Season.series_id == series.id,
                    Season.name == season_name,
                )
            ).first()
            if season is None:
                self._title_label.setText(f"Season '{season_name}' not found")
                return

            self._season_id = season.id
            self._series_id = series.id

            poster_path = season.poster_path or series.poster_path
            if poster_path:
                pixmap = QPixmap(poster_path)
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(
                        200,
                        300,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self._poster_label.setPixmap(pixmap)

            episodes = list(season.episodes)
            self._episode_count_label.setText(f"{len(episodes)} episodes")
            self._episode_table.setRowCount(len(episodes))
            for episode_index, episode in enumerate(episodes):
                self._episode_table.setItem(
                    episode_index,
                    0,
                    QTableWidgetItem(str(episode.tmdb_number or "")),
                )
                self._episode_table.setItem(
                    episode_index,
                    1,
                    QTableWidgetItem(episode.tmdb_name or episode.name or ""),
                )
                self._episode_table.setItem(
                    episode_index,
                    2,
                    QTableWidgetItem(episode.air_date or ""),
                )
                self._episode_table.setItem(
                    episode_index,
                    3,
                    QTableWidgetItem(f"{episode.runtime or 0} min"),
                )

        self._display_cast()

    def _on_poster_context_menu(self, position: QPoint) -> None:
        """Show context menu when the user right-clicks the season poster."""
        menu = QMenu(self)
        change_poster_action = QAction("\U0001f5bc  Change Poster\u2026", self)
        change_poster_action.triggered.connect(self._open_poster_selector)
        menu.addAction(change_poster_action)
        menu.exec(self._poster_label.mapToGlobal(position))

    def _open_poster_selector(self) -> None:
        """Open PosterSelectorDialog for the current season."""
        if not self._current_season_name:
            return
        from lan_streamer.ui_views.dialogs.poster_selector import PosterSelectorDialog

        logger.info(
            "Opening PosterSelectorDialog for season '%s' of series '%s'",
            self._current_season_name,
            self._current_series_name,
        )
        dialog = PosterSelectorDialog(
            media_name=self._current_season_name,
            media_kind="season",
            series_name=self._current_series_name,
            parent=self,
        )
        dialog.poster_updated.connect(self._on_poster_updated)
        dialog.exec()

    def _on_poster_updated(self, new_poster_path: str) -> None:
        """Reload the poster label after a successful update."""
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
            logger.info("Season poster label refreshed with '%s'", new_poster_path)

    def _display_cast(self) -> None:
        while self._cast_grid.count():
            item = self._cast_grid.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        if not self._series_id:
            return

        cast_entries = get_cast_for_series(self._series_id)
        if not cast_entries:
            return

        for cast_entry in cast_entries[:20]:
            person = cast_entry.person
            if not person:
                continue

            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setFixedSize(100, 150)
            card.setStyleSheet(
                "background-color: #16213e; border-radius: 8px; padding: 6px;"
            )

            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(4)
            card_layout.setContentsMargins(4, 4, 4, 4)

            photo = QLabel()
            photo.setFixedSize(60, 60)
            photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if person.profile_path:
                pixmap = QPixmap(person.profile_path)
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(
                        60,
                        60,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    photo.setPixmap(pixmap)
                else:
                    photo.setText("🎭")
            else:
                photo.setText("🎭")
            photo.setStyleSheet("background-color: #0f3460; border-radius: 30px;")
            card_layout.addWidget(photo, 0, Qt.AlignmentFlag.AlignCenter)

            name_label = QLabel(person.name or "Unknown")
            name_label.setWordWrap(True)
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_label.setStyleSheet(
                "color: #e0e0e0; font-weight: bold; font-size: 10px;"
            )
            card_layout.addWidget(name_label)

            card.mousePressEvent = self._make_person_click_handler(person.id)
            self._cast_grid.addWidget(card)

    def _make_person_click_handler(self, person_id: str) -> Any:
        def handler(event: object) -> None:
            self._on_cast_clicked(person_id)

        return handler

    def _on_cast_clicked(self, person_id: str) -> None:
        logger.info("Cast member clicked: %s", person_id)
        self.cast_member_clicked.emit(person_id)
