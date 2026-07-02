"""Full-page cast detail view with biography and filmography."""

import logging
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lan_streamer.db.queries_cast import get_filmography, get_person_by_id

logger = logging.getLogger(__name__)


class CastDetailView(QWidget):
    """Full-page view for displaying a cast member's details and filmography."""

    back_requested = Signal()
    media_item_clicked = Signal(str, str)  # media_type, media_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the cast detail view.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._current_person_id: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Back button
        back_button = QPushButton("← Back")
        back_button.clicked.connect(self.back_requested.emit)
        layout.addWidget(back_button)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Header (photo + info)
        header_layout = QVBoxLayout()

        self._photo_label = QLabel()
        self._photo_label.setFixedSize(200, 200)
        self._photo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._photo_label.setStyleSheet(
            "background-color: #1a1a2e; border-radius: 100px; color: #666;"
        )
        header_layout.addWidget(self._photo_label)

        self._name_label = QLabel()
        name_font = QFont()
        name_font.setPointSize(20)
        name_font.setBold(True)
        self._name_label.setFont(name_font)
        header_layout.addWidget(self._name_label)

        self._birth_label = QLabel()
        self._birth_label.setStyleSheet("color: #94A3B8;")
        header_layout.addWidget(self._birth_label)

        self._death_label = QLabel()
        self._death_label.setStyleSheet("color: #94A3B8;")
        header_layout.addWidget(self._death_label)

        self._place_label = QLabel()
        self._place_label.setStyleSheet("color: #94A3B8;")
        header_layout.addWidget(self._place_label)

        self._content_layout.addLayout(header_layout)

        # Biography
        bio_header = QLabel("Biography")
        bio_header_font = QFont()
        bio_header_font.setPointSize(14)
        bio_header_font.setBold(True)
        bio_header.setFont(bio_header_font)
        self._content_layout.addWidget(bio_header)

        self._biography_label = QLabel()
        self._biography_label.setWordWrap(True)
        self._biography_label.setStyleSheet("color: #ccc; line-height: 1.5;")
        self._content_layout.addWidget(self._biography_label)

        # Filmography
        film_header = QLabel("Filmography")
        film_header_font = QFont()
        film_header_font.setPointSize(14)
        film_header_font.setBold(True)
        film_header.setFont(film_header_font)
        self._content_layout.addWidget(film_header)

        self._filmography_layout = QVBoxLayout()
        self._content_layout.addLayout(self._filmography_layout)

        self._content_layout.addStretch()

    def display_person(self, person_id: str) -> None:
        """Load and display person details.

        Args:
            person_id: The UUID of the person to display.
        """
        self._current_person_id = person_id
        person = get_person_by_id(person_id)
        if person is None:
            self._name_label.setText("Person not found")
            return

        self._name_label.setText(person.name or "Unknown")

        if person.profile_path:
            pixmap = QPixmap(person.profile_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    200,
                    200,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._photo_label.setPixmap(pixmap)

        bio_parts = []
        if person.birth_date:
            bio_parts.append(f"Born: {person.birth_date}")
        if person.death_date:
            bio_parts.append(f"Died: {person.death_date}")
        if person.place_of_birth:
            bio_parts.append(f"Place of birth: {person.place_of_birth}")

        self._birth_label.setText(bio_parts[0] if len(bio_parts) > 0 else "")
        self._death_label.setText(bio_parts[1] if len(bio_parts) > 1 else "")
        self._place_label.setText(bio_parts[2] if len(bio_parts) > 2 else "")

        self._biography_label.setText(person.biography or "No biography available.")

        # Load filmography
        self._display_filmography(person_id)

    def _display_filmography(self, person_id: str) -> None:
        """Display filmography entries for a person.

        Args:
            person_id: The UUID of the person.
        """
        # Clear existing
        while self._filmography_layout.count():
            item = self._filmography_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        filmography = get_filmography(person_id)
        if not filmography:
            no_film_label = QLabel("No filmography data available.")
            no_film_label.setStyleSheet("color: #888;")
            self._filmography_layout.addWidget(no_film_label)
            return

        for cast_entry in filmography:
            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setStyleSheet(
                "background-color: #16213e; border-radius: 8px;"
                " padding: 8px; margin: 4px 0;"
            )
            card_layout = QHBoxLayout(card)
            card_layout.setSpacing(12)

            # Determine what media this entry is for
            if cast_entry.series:
                title = cast_entry.series.name or "Unknown Series"
                media_type = "series"
                media_id = cast_entry.series.id
                poster_path = cast_entry.series.poster_path
                role_parts = [f"Role: {cast_entry.role}"]
                if cast_entry.character:
                    role_parts.append(f"as {cast_entry.character}")
                subtitle = " ".join(role_parts)
            elif cast_entry.movie:
                title = cast_entry.movie.name or "Unknown Movie"
                media_type = "movie"
                media_id = cast_entry.movie.id
                poster_path = cast_entry.movie.poster_path
                role_parts = [f"Role: {cast_entry.role}"]
                if cast_entry.character:
                    role_parts.append(f"as {cast_entry.character}")
                subtitle = " ".join(role_parts)
            else:
                continue

            # Poster thumbnail – fixed width, stretches to full row height
            poster_label = QLabel()
            poster_label.setFixedWidth(50)
            poster_label.setStyleSheet(
                "background-color: #1a1a2e; border-radius: 4px; color: #555;"
            )
            poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if poster_path:
                pixmap = QPixmap(poster_path)
                if not pixmap.isNull():
                    pixmap = pixmap.scaledToWidth(
                        50,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    poster_label.setPixmap(pixmap)
            else:
                poster_label.setText("N/A")
            card_layout.addWidget(poster_label)

            # Text info
            text_layout = QVBoxLayout()
            text_layout.setSpacing(2)

            title_label = QLabel(title)
            title_label.setStyleSheet(
                "color: #e0e0e0; font-weight: bold; font-size: 13px;"
            )
            text_layout.addWidget(title_label)

            role_label = QLabel(subtitle)
            role_label.setStyleSheet("color: #aaa; font-size: 11px;")
            text_layout.addWidget(role_label)

            text_layout.addStretch()
            card_layout.addLayout(text_layout, 1)

            card.mousePressEvent = self._make_media_click_handler(media_type, media_id)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            self._filmography_layout.addWidget(card)

    def _make_media_click_handler(self, media_type: str, media_id: str) -> Any:
        """Create a mouse press event handler for a filmography card."""

        def handler(event: object) -> None:
            self._on_media_clicked(media_type, media_id)

        return handler

    def _on_media_clicked(self, media_type: str, media_id: str) -> None:
        """Handle filmography item click.

        Args:
            media_type: 'series' or 'movie'.
            media_id: The UUID of the media item.
        """
        logger.info(
            "Filmography item clicked: type=%s, id=%s",
            media_type,
            media_id,
        )
        self.media_item_clicked.emit(media_type, media_id)
