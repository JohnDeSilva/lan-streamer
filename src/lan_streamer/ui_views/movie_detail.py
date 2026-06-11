import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QFont
from lan_streamer.ui_views.proxy import QPixmap
from lan_streamer.system.config import config
from lan_streamer.ui_views.controller import Controller

logger = logging.getLogger(__name__)


class MovieDetailView(QWidget):
    """
    Presents movie details, overview, artwork, and direct playback controls.
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
        self.metadata_label: QLabel = QLabel()
        self._current_movie_name: str = ""
        self._current_movie_path: str = ""

        self._setup_ui()
        self.controller.movie_selected.connect(self.populate_movie_details)
        self.controller.library_loaded.connect(self.on_library_loaded)

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Header Panel
        header_layout: QHBoxLayout = QHBoxLayout()
        header_layout.setSpacing(20)

        back_button: QPushButton = QPushButton("← Back to Library")
        back_button.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(back_button, 0, Qt.AlignmentFlag.AlignTop)

        self.poster_label.setFixedSize(180, 260)
        self.poster_label.setStyleSheet(
            "background-color: #222222; border: 1px solid #444444; border-radius: 6px;"
        )
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.poster_label, 0, Qt.AlignmentFlag.AlignTop)

        info_layout: QVBoxLayout = QVBoxLayout()
        info_layout.setSpacing(10)

        self.title_label.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        self.metadata_label.setFont(QFont("Inter", 12))
        self.metadata_label.setStyleSheet("color: #888888;")
        self.metadata_label.setWordWrap(True)
        info_layout.addWidget(self.metadata_label)

        self.overview_label.setFont(QFont("Inter", 13))
        self.overview_label.setWordWrap(True)
        self.overview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        info_layout.addWidget(self.overview_label)

        # Actions Panel
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)

        self.play_button: QPushButton = QPushButton("Play Movie")
        self.play_button.setObjectName("accentButton")
        self.play_button.clicked.connect(self._on_play_clicked)
        actions_layout.addWidget(self.play_button)

        movie_details_button: QPushButton = QPushButton("Movie Details")
        movie_details_button.setObjectName("movieDetailsButton")
        movie_details_button.clicked.connect(
            lambda: self.controller.movie_details_requested.emit(
                self._current_movie_name, self._current_movie_path
            )
        )
        actions_layout.addWidget(movie_details_button)

        actions_layout.addStretch()
        info_layout.addLayout(actions_layout)

        header_layout.addLayout(info_layout)
        main_layout.addLayout(header_layout)

        # Horizontal Divider Line
        divider_line: QFrame = QFrame()
        divider_line.setFrameShape(QFrame.Shape.HLine)
        divider_line.setFrameShadow(QFrame.Shadow.Sunken)
        divider_line.setStyleSheet("border-color: #333333;")
        main_layout.addWidget(divider_line)

        # Bottom stretch to keep layout compact at top
        main_layout.addStretch()

    def populate_movie_details(self, movie_name: str) -> None:
        if getattr(self.controller, "is_video_playing", False):
            return

        logger.info(f"Populating movie details for: '{movie_name}'")
        self._current_movie_name = movie_name
        movie_record: Dict[str, Any] = self.controller.cached_library_data.get(
            movie_name, {}
        )
        self._current_movie_path = movie_record.get("path", "")

        movie_display_title: str = movie_record.get("tmdb_name") or movie_name
        self.title_label.setText(movie_display_title)
        self.overview_label.setText(
            movie_record.get("overview") or "No overview available."
        )

        # Build metadata label details
        year: Optional[int] = movie_record.get("year")
        runtime: Optional[int] = movie_record.get("file_runtime") or movie_record.get(
            "runtime"
        )
        rating: Optional[str] = movie_record.get("rating")
        genre: Optional[str] = movie_record.get("genre")

        metadata_parts: List[str] = []
        if year:
            metadata_parts.append(str(year))
        if runtime:
            metadata_parts.append(f"{runtime} min")
        if rating:
            metadata_parts.append(f"★ {rating}")
        if genre:
            metadata_parts.append(genre)

        self.metadata_label.setText(" • ".join(metadata_parts))

        poster_path_string: str = movie_record.get("poster_path", "")
        pixmap_assigned: bool = False
        if poster_path_string:
            poster_path_object = Path(poster_path_string)
            if poster_path_object.is_file():
                pixmap_instance = QPixmap(str(poster_path_object))
                if not pixmap_instance.isNull():
                    self.poster_label.setPixmap(
                        pixmap_instance.scaled(
                            180,
                            260,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    pixmap_assigned = True

        if not pixmap_assigned:
            logger.info(
                f"No poster loaded or file missing for movie: '{movie_name}', showing fallback"
            )
            self.poster_label.clear()
            self.poster_label.setText("No Poster")

    @Slot()
    def on_library_loaded(self) -> None:
        library_config = config.libraries.get(self.controller.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"
        if (
            is_movie
            and self.controller.selected_series_name
            and self.controller.selected_series_name
            in self.controller.cached_library_data
        ):
            self.populate_movie_details(self.controller.selected_series_name)

    @Slot()
    def _on_play_clicked(self) -> None:
        if self._current_movie_path:
            logger.info(
                f"Play Movie clicked for: '{self._current_movie_name}' (Path: {self._current_movie_path})"
            )
            self.controller.playback_requested.emit(self._current_movie_path)
