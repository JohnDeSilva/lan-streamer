"""Dialog for selecting posters and backdrops for series and movies."""

import logging
from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Movie, Series
from lan_streamer.db.queries_cast import (
    get_images_for_media,
    set_selected_image,
)

logger = logging.getLogger(__name__)


class PosterSelectorDialog(QDialog):
    """Dialog for browsing and selecting posters/backdrops for media."""

    def __init__(
        self,
        media_name: str,
        is_movie: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize the poster selector dialog.

        Args:
            media_name: Name of the series or movie.
            is_movie: Whether the media is a movie (False for series).
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._media_name = media_name
        self._is_movie = is_movie
        self._media_id: Optional[str] = None

        self.setWindowTitle(f"Select Poster — {media_name}")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        # Resolve media ID
        with get_session() as session:
            model_record: Any = None
            if is_movie:
                model_record = session.scalars(
                    select(Movie).where(Movie.name == media_name)
                ).first()
            else:
                model_record = session.scalars(
                    select(Series).where(Series.name == media_name)
                ).first()
            if model_record:
                self._media_id = model_record.id

        if not self._media_id:
            layout.addWidget(QLabel(f"Media '{media_name}' not found in database."))
            close_button = QPushButton("Close")
            close_button.clicked.connect(self.accept)
            layout.addWidget(close_button)
            return

        # Tab widget for poster/backdrop
        self._tab_widget = QTabWidget()
        layout.addWidget(self._tab_widget)

        # Posters tab
        posters_widget = self._create_image_tab("poster")
        self._tab_widget.addTab(posters_widget, "Posters")

        # Backdrops tab
        backdrops_widget = self._create_image_tab("backdrop")
        self._tab_widget.addTab(backdrops_widget, "Backdrops")

        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

    def _create_image_tab(self, image_type: str) -> QWidget:
        """Create a tab with image grid.

        Args:
            image_type: Type of images to display ('poster' or 'backdrop').

        Returns:
            A widget containing the image grid.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        scroll.setWidget(grid_widget)
        layout.addWidget(scroll)

        images = get_images_for_media(
            series_id=self._media_id if not self._is_movie else None,
            movie_id=self._media_id if self._is_movie else None,
            image_type=image_type,
        )

        if not images:
            no_images_label = QLabel(f"No {image_type} images available.")
            no_images_label.setStyleSheet("color: #888;")
            grid_layout.addWidget(no_images_label, 0, 0)
        else:
            row_index, col_index = 0, 0
            max_columns = 3
            for image in images:
                card = QFrame()
                card.setFrameShape(QFrame.Shape.StyledPanel)
                card.setFixedSize(200, 300)
                card.setStyleSheet(
                    "background-color: #16213e; border-radius: 8px; padding: 4px;"
                )
                card_layout = QVBoxLayout(card)

                image_label = QLabel()
                image_label.setFixedSize(180, 250)
                image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if image.local_path:
                    pixmap = QPixmap(image.local_path)
                    if not pixmap.isNull():
                        pixmap = pixmap.scaled(
                            180,
                            250,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        image_label.setPixmap(pixmap)

                select_button = QPushButton(
                    "✓ Selected" if image.is_selected else "Select"
                )
                if image.is_selected:
                    select_button.setStyleSheet(
                        "background-color: #27ae60; color: white;"
                    )
                else:
                    select_button.clicked.connect(
                        lambda checked, img_id=image.id, btn=select_button: (
                            self._select_image(  # noqa: E501
                                img_id, btn
                            )
                        )
                    )
                card_layout.addWidget(image_label)
                card_layout.addWidget(select_button)

                grid_layout.addWidget(card, row_index, col_index)
                col_index += 1
                if col_index >= max_columns:
                    col_index = 0
                    row_index += 1

        return widget

    def _select_image(self, image_id: str, button: QPushButton) -> None:
        """Set an image as selected and update UI.

        Args:
            image_id: The UUID of the image to select.
            button: The button widget to update.
        """
        set_selected_image(image_id)
        button.setText("✓ Selected")
        button.setStyleSheet("background-color: #27ae60; color: white;")
        QMessageBox.information(self, "Updated", "Poster selection updated.")
        self.accept()
