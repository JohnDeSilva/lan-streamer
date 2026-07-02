"""Full-page season detail view with cast, poster, and episode table."""

import logging
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHeaderView,
    QLabel,
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
from lan_streamer.db.queries_cast import get_cast_for_season

logger = logging.getLogger(__name__)


class SeasonDetailView(QWidget):
    """Full-page view for displaying season details with cast and episode list."""

    back_requested = Signal()
    episode_details_requested = Signal(str, str)  # series_name, episode_path
    cast_member_clicked = Signal(str)  # person_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the season detail view.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._current_series_name: Optional[str] = None
        self._current_season_name: Optional[str] = None
        self._season_id: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Back button
        back_button = QPushButton("← Back")
        back_button.clicked.connect(self.back_requested.emit)
        layout.addWidget(back_button)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Header section (poster + info)
        header_layout = QVBoxLayout()

        # Poster row
        poster_row = QVBoxLayout()
        self._poster_label = QLabel()
        self._poster_label.setFixedSize(200, 300)
        self._poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster_label.setStyleSheet("background-color: #1a1a2e; color: #666;")
        poster_row.addWidget(self._poster_label)
        header_layout.addLayout(poster_row)

        # Info section
        self._title_label = QLabel()
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        header_layout.addWidget(self._title_label)

        self._series_label = QLabel()
        series_font = QFont()
        series_font.setPointSize(12)
        self._series_label.setFont(series_font)
        self._series_label.setStyleSheet("color: #94A3B8;")
        header_layout.addWidget(self._series_label)

        self._episode_count_label = QLabel()
        self._episode_count_label.setStyleSheet("color: #94A3B8;")
        header_layout.addWidget(self._episode_count_label)

        self._content_layout.addLayout(header_layout)

        # Cast section
        cast_header = QLabel("Cast")
        cast_header_font = QFont()
        cast_header_font.setPointSize(14)
        cast_header_font.setBold(True)
        cast_header.setFont(cast_header_font)
        self._content_layout.addWidget(cast_header)

        self._cast_grid = QGridLayout()
        self._cast_grid.setSpacing(10)
        self._content_layout.addLayout(self._cast_grid)

        # Episode table
        episodes_header = QLabel("Episodes")
        episodes_header_font = QFont()
        episodes_header_font.setPointSize(14)
        episodes_header_font.setBold(True)
        episodes_header.setFont(episodes_header_font)
        self._content_layout.addWidget(episodes_header)

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
        self._content_layout.addWidget(self._episode_table)

    def display_season(self, series_name: str, season_name: str) -> None:
        """Load and display season data.

        Args:
            series_name: Name of the parent series.
            season_name: Name of the season to display.
        """
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

            # Load poster
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

            # Load episodes
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

        # Load cast
        self._display_cast()

    def _display_cast(self) -> None:
        """Display cast members in the cast grid."""
        # Clear existing cast widgets
        while self._cast_grid.count():
            item = self._cast_grid.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        if not self._season_id:
            return

        cast_entries = get_cast_for_season(self._season_id)
        if not cast_entries:
            no_cast = QLabel("No cast information available")
            no_cast.setStyleSheet("color: #888;")
            self._cast_grid.addWidget(no_cast, 0, 0)
            return

        row_index, col_index = 0, 0
        max_columns = 6
        for cast_entry in cast_entries:
            person = cast_entry.person
            if not person:
                continue

            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setFixedSize(140, 200)
            card.setStyleSheet(
                "background-color: #16213e; border-radius: 8px; padding: 8px;"
            )

            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(4)

            # Profile photo
            photo = QLabel()
            photo.setFixedSize(80, 80)
            photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if person.profile_path:
                pixmap = QPixmap(person.profile_path)
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(
                        80,
                        80,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    photo.setPixmap(pixmap)
                else:
                    photo.setText("📷")
            else:
                photo.setText("📷")
            photo.setStyleSheet("background-color: #0f3460; border-radius: 40px;")
            card_layout.addWidget(photo, 0, Qt.AlignmentFlag.AlignCenter)

            name_label = QLabel(person.name or "Unknown")
            name_label.setWordWrap(True)
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_label.setStyleSheet(
                "color: #e0e0e0; font-weight: bold; font-size: 11px;"
            )
            card_layout.addWidget(name_label)

            if cast_entry.character:
                character_label = QLabel(cast_entry.character)
                character_label.setWordWrap(True)
                character_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                character_label.setStyleSheet("color: #aaa; font-size: 10px;")
                card_layout.addWidget(character_label)

            # Make card clickable
            card.mousePressEvent = self._make_person_click_handler(person.id)

            self._cast_grid.addWidget(card, row_index, col_index)
            col_index += 1
            if col_index >= max_columns:
                col_index = 0
                row_index += 1

    def _make_person_click_handler(self, person_id: str) -> Any:
        """Create a mouse press event handler for a cast member card."""

        def handler(event: object) -> None:
            self._on_cast_clicked(person_id)

        return handler

    def _on_cast_clicked(self, person_id: str) -> None:
        """Handle cast member click.

        Args:
            person_id: The UUID of the person to navigate to.
        """
        logger.info("Cast member clicked: %s", person_id)
        self.cast_member_clicked.emit(person_id)
