import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from sqlalchemy import select

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Slot, QPoint, Signal
from PySide6.QtGui import QFont, QIcon, QPainter, QPolygon, QColor, QAction
from lan_streamer.ui_views.proxy import QPixmap
from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Movie
from lan_streamer.db.queries_cast import get_cast_for_movie
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
        self._current_movie_db_id: Optional[str] = None

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
        self.poster_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.poster_label.customContextMenuRequested.connect(
            self._on_poster_context_menu
        )
        self.poster_label.setToolTip("Right-click to change poster")
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

        info_layout.addLayout(actions_layout)

        self.trailers_button: QPushButton = QPushButton("Trailers")
        self.trailers_button.setObjectName("trailersButton")
        self.trailers_button.setIcon(self._create_youtube_icon())
        self.trailers_button.clicked.connect(self._on_trailers_clicked)
        actions_layout.addWidget(self.trailers_button)

        actions_layout.addStretch()

        header_layout.addLayout(info_layout)
        main_layout.addLayout(header_layout)

        # Horizontal Divider Line
        divider_line: QFrame = QFrame()
        divider_line.setFrameShape(QFrame.Shape.HLine)
        divider_line.setFrameShadow(QFrame.Shadow.Sunken)
        divider_line.setStyleSheet("border-color: #333333;")
        main_layout.addWidget(divider_line)

        # Cast section
        cast_header: QLabel = QLabel("Cast")
        cast_header.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        main_layout.addWidget(cast_header)

        self._cast_scroll = QScrollArea()
        self._cast_scroll.setWidgetResizable(True)
        self._cast_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cast_scroll.setMaximumHeight(220)
        self._cast_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        cast_scroll_content = QWidget()
        self._cast_grid = QHBoxLayout(cast_scroll_content)
        self._cast_grid.setSpacing(10)
        self._cast_grid.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._cast_scroll.setWidget(cast_scroll_content)
        main_layout.addWidget(self._cast_scroll)

        # Bottom stretch to keep layout compact at top
        main_layout.addStretch()

    def populate_movie_details(self, movie_name: str) -> None:
        if getattr(self.controller, "is_video_playing", False):
            return

        logger.info(f"Populating movie details for: '{movie_name}'")
        self._current_movie_name = movie_name
        self._current_movie_db_id = None
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

        self._display_cast_section()

    def _on_poster_context_menu(self, position: QPoint) -> None:
        """Show context menu when the user right-clicks the movie poster."""
        menu = QMenu(self)
        change_poster_action = QAction("\U0001f5bc  Change Poster\u2026", self)
        change_poster_action.triggered.connect(self._open_poster_selector)
        menu.addAction(change_poster_action)
        menu.exec(self.poster_label.mapToGlobal(position))

    def _open_poster_selector(self) -> None:
        """Open PosterSelectorDialog for the current movie."""
        if not self._current_movie_name:
            return
        from lan_streamer.ui_views.dialogs.poster_selector import PosterSelectorDialog

        logger.info(
            "Opening PosterSelectorDialog for movie '%s'",
            self._current_movie_name,
        )
        dialog = PosterSelectorDialog(
            media_name=self._current_movie_name,
            media_kind="movie",
            parent=self,
        )
        dialog.poster_updated.connect(
            lambda new_path: self.populate_movie_details(self._current_movie_name)
        )
        dialog.exec()

    def _lookup_movie_id(self) -> Optional[str]:
        """Query the database for the Movie UUID matching the current movie name."""
        if not self._current_movie_name:
            return None
        if self._current_movie_db_id is not None:
            return self._current_movie_db_id
        with get_session() as session:
            statement = select(Movie).where(
                Movie.library_name == self.controller.current_library_name,
                Movie.name == self._current_movie_name,
            )
            movie = session.execute(statement).unique().scalar_one_or_none()
            if movie is not None:
                self._current_movie_db_id = movie.id
                return movie.id
        return None

    def _make_person_click_handler(self, person_id: str) -> Any:
        """Create a mouse press event handler for a cast member card."""

        def handler(event: object) -> None:
            self._on_cast_member_clicked(person_id)

        return handler

    def _on_cast_member_clicked(self, person_id: str) -> None:
        """Handle cast member card click."""
        logger.info("Cast member clicked in movie detail: %s", person_id)
        self.controller.select_cast_member(person_id)

    def _display_cast_section(self) -> None:
        """Populate the cast grid for the current movie."""
        while self._cast_grid.count():
            item = self._cast_grid.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        movie_id = self._lookup_movie_id()
        if not movie_id:
            return

        cast_entries = get_cast_for_movie(movie_id)
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
                    from lan_streamer.ui_views.image_masking import get_circular_pixmap

                    circular_pixmap = get_circular_pixmap(pixmap, 60)
                    photo.setPixmap(circular_pixmap)
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

            if cast_entry.character:
                character_label = QLabel(cast_entry.character)
                character_label.setWordWrap(True)
                character_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                character_label.setStyleSheet("color: #aaa; font-size: 9px;")
                card_layout.addWidget(character_label)

            card.mousePressEvent = self._make_person_click_handler(person.id)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            self._cast_grid.addWidget(card)

    def _create_youtube_icon(self) -> QIcon:
        """Generates a custom YouTube icon using QPainter."""
        from PySide6.QtGui import QPixmap

        youtube_pixmap: QPixmap = QPixmap(24, 24)
        youtube_pixmap.fill(Qt.GlobalColor.transparent)

        painter_instance: QPainter = QPainter(youtube_pixmap)
        painter_instance.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Red YouTube background rounded rect
        painter_instance.setBrush(QColor("#FF0000"))
        painter_instance.setPen(Qt.PenStyle.NoPen)
        painter_instance.drawRoundedRect(2, 5, 20, 14, 4, 4)

        # White play button triangle
        painter_instance.setBrush(QColor("#FFFFFF"))
        triangle_polygon: QPolygon = QPolygon(
            [QPoint(10, 9), QPoint(10, 15), QPoint(15, 12)]
        )
        painter_instance.drawPolygon(triangle_polygon)
        painter_instance.end()

        return QIcon(youtube_pixmap)

    @Slot()
    def _on_trailers_clicked(self) -> None:
        display_title = self.title_label.text()
        if not display_title:
            return
        import urllib.parse
        import webbrowser

        search_query: str = f"{display_title} trailer"
        trailer_url: str = f"https://www.youtube.com/results?search_query={urllib.parse.quote(search_query)}"
        logger.info(f"Opening YouTube search for trailer: '{search_query}'")
        webbrowser.open(trailer_url)

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
