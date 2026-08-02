import asyncio
import datetime
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPolygon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from lan_streamer import db
from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Series
from lan_streamer.system.config import config
from lan_streamer.ui_views.proxy import QPixmap

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QMenu

    from lan_streamer.providers.tmdb import tmdb_client
    from lan_streamer.ui_views.controller import Controller
else:
    from lan_streamer.ui_views.proxy import QMenu, tmdb_client

logger = logging.getLogger(__name__)


def _episode_sort_key(episode_item: dict[str, Any]) -> tuple[int, str]:
    num = episode_item.get("tmdb_number")
    if num is not None:
        try:
            return (int(num), episode_item.get("name", ""))
        except TypeError, ValueError:
            pass
    name_str = episode_item.get("name", "")
    parsed = re.search(r"[Ee](\d+)", name_str)
    if parsed:
        return (int(parsed.group(1)), name_str)
    return (999999, name_str)


class SeriesDetailView(QWidget):
    """
    Presents exhaustive series structure tabs, season tables, and direct execution actions.
    Enforces strict typing and zero-abbreviation naming standard.
    """

    back_requested = Signal()

    def __init__(
        self, controller_instance: Controller, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.controller: Controller = controller_instance
        self.title_label: QLabel = QLabel()
        self.overview_label: QLabel = QLabel()
        self.poster_label: QLabel = QLabel()
        self.play_next_button: QPushButton = QPushButton()
        self._next_episode_path: str = ""
        self.seasons_tab_widget: QTabWidget = QTabWidget()
        self._current_series_name: str = ""
        self._current_series_db_id: str | None = None
        self._season_tables: dict[str, QTableWidget] = {}
        self.episode_groups_cache: dict[str, list[dict[str, Any]]] = {}
        self.episode_group_details_cache: dict[str, dict[str, Any]] = {}
        self._cached_series_data_copy: dict[str, Any] | None = None
        self._loading_task_name: str | None = None

        self._setup_ui()
        self.controller.series_selected.connect(self.populate_series_details)
        self.controller.library_loaded.connect(self.on_library_loaded)

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        top_row: QHBoxLayout = QHBoxLayout()
        top_row.setSpacing(20)

        left_container: QWidget = QWidget()
        left_container.setMaximumWidth(240)
        left_layout: QVBoxLayout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(15)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        back_button: QPushButton = QPushButton("← Back to Library")
        back_button.clicked.connect(self.back_requested.emit)
        left_layout.addWidget(back_button)

        self.poster_label.setFixedSize(240, 350)
        self.poster_label.setStyleSheet(
            "background-color: #1a1a1f; border: 1px solid #2d2d35; border-radius: 8px;"
        )
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.poster_label.customContextMenuRequested.connect(
            self._on_poster_context_menu
        )
        self.poster_label.setToolTip("Right-click to change poster")
        left_layout.addWidget(self.poster_label)

        self.trailers_button: QPushButton = QPushButton("Trailers")
        self.trailers_button.setObjectName("trailersButton")
        self.trailers_button.setIcon(self._create_youtube_icon())
        self.trailers_button.setMaximumWidth(240)
        self.trailers_button.clicked.connect(self._on_trailers_clicked)
        left_layout.addWidget(self.trailers_button)

        self.play_next_button.setObjectName("playEpisodeButton")
        self.play_next_button.setMaximumWidth(240)
        self.play_next_button.clicked.connect(self._on_play_next_clicked)
        left_layout.addWidget(self.play_next_button)

        self.title_label.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumWidth(240)
        left_layout.addWidget(self.title_label)

        self.overview_label.setFont(QFont("Inter", 13))
        self.overview_label.setWordWrap(True)
        self.overview_label.setMaximumWidth(240)
        self.overview_label.setStyleSheet("color: #94A3B8;")
        left_layout.addWidget(self.overview_label)

        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(8)

        series_details_button: QPushButton = QPushButton("Series Details")
        series_details_button.setObjectName("seriesDetailsButton")
        series_details_button.clicked.connect(
            lambda: self.controller.series_details_requested.emit(
                self.controller.selected_series_name
            )
        )
        actions_layout.addWidget(series_details_button)

        display_group_row = QHBoxLayout()
        display_group_row.setSpacing(6)
        display_group_row.addWidget(QLabel("Display Group:"))
        self.order_combo = QComboBox()
        self.order_combo.setObjectName("orderComboBox")
        self.order_combo.currentIndexChanged.connect(self._on_order_changed)
        display_group_row.addWidget(self.order_combo, 1)
        actions_layout.addLayout(display_group_row)

        left_layout.addLayout(actions_layout)

        top_row.addWidget(left_container)

        right_container: QWidget = QWidget()
        right_layout: QVBoxLayout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        self.seasons_tab_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        right_layout.addWidget(self.seasons_tab_widget, 1)
        top_row.addWidget(right_container, 1)

        main_layout.addLayout(top_row, 1)

        cast_header: QLabel = QLabel("Cast")
        cast_header.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        main_layout.addWidget(cast_header)

        self._cast_scroll = QScrollArea()
        self._cast_scroll.setWidgetResizable(True)
        self._cast_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cast_scroll.setFixedHeight(190)
        self._cast_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        cast_scroll_content = QWidget()
        self._cast_grid = QHBoxLayout(cast_scroll_content)
        self._cast_grid.setSpacing(10)
        self._cast_grid.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._cast_scroll.setWidget(cast_scroll_content)
        main_layout.addWidget(self._cast_scroll)

    def _on_poster_context_menu(self, position: QPoint) -> None:
        """Show context menu when the user right-clicks the series poster."""
        menu: QMenu = QMenu(self)
        change_poster_action = QAction("🖼  Change Poster…", self)
        change_poster_action.triggered.connect(self._open_poster_selector)
        menu.addAction(change_poster_action)
        menu.exec(self.poster_label.mapToGlobal(position))

    def _open_poster_selector(self) -> None:
        """Open the PosterSelectorDialog for the current series."""
        if not self._current_series_name:
            return
        from lan_streamer.ui_views.dialogs.poster_selector import PosterSelectorDialog

        logger.info(
            "Opening PosterSelectorDialog for series '%s'",
            self._current_series_name,
        )
        dialog = PosterSelectorDialog(
            media_name=self._current_series_name,
            media_kind="series",
            parent=self,
        )
        dialog.poster_updated.connect(
            lambda new_path: self.populate_series_details(self._current_series_name)
        )
        dialog.exec()

    def _lookup_series_id(self) -> str | None:
        """Query the database for the Series UUID matching the current series name."""
        if not self._current_series_name:
            return None
        if self._current_series_db_id is not None:
            return self._current_series_db_id
        with get_session() as session:
            statement = select(Series).where(
                Series.library_name == self.controller.current_library_name,
                Series.name == self._current_series_name,
            )
            series = session.execute(statement).unique().scalar_one_or_none()
            if series is not None:
                self._current_series_db_id = series.id
                return series.id
        return None

    def _make_person_click_handler(self, person_id: str) -> Any:
        """Create a mouse press event handler for a cast member card."""

        def handler(event: object) -> None:
            self._on_cast_member_clicked(person_id)

        return handler

    def _on_cast_member_clicked(self, person_id: str) -> None:
        """Handle cast member card click."""
        logger.info("Cast member clicked in series detail: %s", person_id)
        self.controller.select_cast_member(person_id)

    def _fetch_series_db_and_cast(
        self, series_name: str
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Fetch series DB ID and cast list (to be run in a background thread)."""
        from sqlalchemy.orm import joinedload

        from lan_streamer.db.models_cast import MediaCast

        series_database_identifier = None
        serialized_cast = []
        with get_session() as session:
            statement = (
                select(Series)
                .where(
                    Series.library_name == self.controller.current_library_name,
                    Series.name == series_name,
                )
                .options(joinedload(Series.media_cast).joinedload(MediaCast.person))
            )
            series = session.execute(statement).unique().scalar_one_or_none()
            if series is not None:
                series_database_identifier = series.id
                sorted_cast = sorted(series.media_cast, key=lambda c: c.sort_order or 0)
                for cast_entry in sorted_cast[:20]:
                    person = cast_entry.person
                    if person:
                        serialized_cast.append(
                            {
                                "person_id": person.id,
                                "name": person.name,
                                "profile_path": person.profile_path,
                                "character": cast_entry.character,
                            }
                        )
        return series_database_identifier, serialized_cast

    def _make_person_click_handler(self, person_id: str) -> Any:
        """Create a mouse press event handler for a cast member card."""

        def handler(event: object) -> None:
            self._on_cast_member_clicked(person_id)

        return handler

    def _on_cast_member_clicked(self, person_id: str) -> None:
        """Handle cast member card click."""
        logger.info("Cast member clicked in series detail: %s", person_id)
        self.controller.select_cast_member(person_id)

    def _display_cast_section(self, cast_entries: list[dict[str, Any]]) -> None:
        """Populate the cast grid for the current series."""
        # Clear existing cast cards
        while self._cast_grid.count():
            item = self._cast_grid.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        if not cast_entries:
            return

        for cast_entry in cast_entries:
            person_database_identifier = cast_entry["person_id"]
            person_name = cast_entry["name"]
            profile_path = cast_entry["profile_path"]
            character = cast_entry["character"]

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
            if profile_path:
                pixmap = QPixmap(profile_path)
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(
                        60,
                        60,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    photo.setPixmap(scaled_pixmap)
                else:
                    photo.setText("🎭")
            else:
                photo.setText("🎭")
            photo.setStyleSheet("background-color: #0f3460; border-radius: 4px;")
            card_layout.addWidget(photo, 0, Qt.AlignmentFlag.AlignCenter)

            name_label = QLabel(person_name or "Unknown")
            name_label.setWordWrap(True)
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_label.setStyleSheet(
                "color: #e0e0e0; font-weight: bold; font-size: 10px;"
            )
            card_layout.addWidget(name_label)

            if character:
                character_label = QLabel(character)
                character_label.setWordWrap(True)
                character_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                character_label.setStyleSheet("color: #aaa; font-size: 9px;")
                card_layout.addWidget(character_label)

            card.mousePressEvent = self._make_person_click_handler(
                person_database_identifier
            )
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            self._cast_grid.addWidget(card)

    @Slot()
    def on_library_loaded(self) -> None:
        if (
            self._current_series_name
            and self._current_series_name in self.controller.cached_library_data
        ):
            new_data = self.controller.cached_library_data.get(
                self._current_series_name
            )
            is_scanning = False
            if hasattr(self.controller, "worker_manager") and hasattr(
                self.controller.worker_manager, "scan"
            ):
                is_scanning = self.controller.worker_manager.scan.is_running

            if is_scanning and (
                hasattr(self, "_cached_series_data_copy")
                and self._cached_series_data_copy == new_data
            ):
                return
            import copy

            self._cached_series_data_copy = (
                copy.deepcopy(new_data) if new_data else None
            )
            self.populate_series_details(self._current_series_name)

    @Slot(int)
    def _on_order_changed(self, index: int) -> None:
        if index < 0 or not self._current_series_name:
            return
        selected_group_id = self.order_combo.itemData(index)
        config.set_series_preference(
            self.controller.current_library_name,
            self._current_series_name,
            "display_group_id",
            selected_group_id,
        )
        self.populate_series_details(self._current_series_name)

    @Slot(str, bool)
    def _on_mark_season_watched(self, season_name: str, watched: bool = True) -> None:
        if not self.controller.selected_series_name:
            return
        self.controller.mark_season_watched(
            self.controller.selected_series_name, season_name, watched
        )
        self.populate_series_details(self._current_series_name)

    @Slot()
    def _on_play_next_clicked(self) -> None:
        if self._next_episode_path:
            logger.info(
                f"Play Next clicked for: '{self._current_series_name}' (Next Episode Path: {self._next_episode_path})"
            )
            self.controller.playback_requested.emit(self._next_episode_path)

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

    @Slot(str)
    def populate_series_details(self, series_name: str) -> None:
        if getattr(self.controller, "is_video_playing", False):
            return

        logger.info(f"Populating series details for: '{series_name}'")

        series_record: dict[str, Any] = self.controller.cached_library_data.get(
            series_name, {}
        )
        metadata_dictionary: dict[str, Any] = series_record.get("metadata", {})

        series_display_title: str = metadata_dictionary.get("tmdb_name") or series_name
        self.title_label.setText(series_display_title)
        self.overview_label.setText(
            metadata_dictionary.get("overview") or "No overview available."
        )

        # Load dynamic poster fragment
        poster_path_string: str = metadata_dictionary.get("poster_path", "")
        pixmap_assigned: bool = False
        if poster_path_string:
            poster_path_object = Path(poster_path_string)
            if poster_path_object.is_file():
                pixmap_instance = QPixmap(str(poster_path_object))
                if not pixmap_instance.isNull():
                    self.poster_label.setPixmap(
                        pixmap_instance.scaled(
                            240,
                            350,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    pixmap_assigned = True

        if not pixmap_assigned:
            self.poster_label.clear()
            self.poster_label.setText("No Poster")

        # Track the active series data copy to prevent redundant updates
        import copy

        self._cached_series_data_copy = (
            copy.deepcopy(series_record) if series_record else None
        )

        # Check if an asyncio event loop is running
        try:
            import asyncio

            asyncio.get_running_loop()
            has_event_loop = True
        except RuntimeError:
            has_event_loop = False

        if has_event_loop:
            # Start loading TMDB and database details asynchronously
            if hasattr(self, "_loading_task_name") and self._loading_task_name:
                self.controller.async_task_manager.cancel_task(self._loading_task_name)
            self._loading_task_name = f"load_series_details_{series_name}"
            self.controller.async_task_manager.create_task(
                self._load_details_async(series_name), name=self._loading_task_name
            )
        else:
            # Run synchronously (e.g. during synchronous unit tests)
            logger.debug("No running event loop. Loading series details synchronously.")
            series_database_identifier, cast_entries = self._fetch_series_db_and_cast(
                series_name
            )
            available_groups = [{"id": "default", "name": "TV Order (Default)"}]
            tmdb_identifier = metadata_dictionary.get("tmdb_identifier")
            if tmdb_identifier:
                if tmdb_identifier not in self.episode_groups_cache:
                    self.episode_groups_cache[tmdb_identifier] = (
                        tmdb_client.get_episode_groups(tmdb_identifier)
                    )
                groups_list = self.episode_groups_cache[tmdb_identifier]
                for group in groups_list:
                    available_groups.append(
                        {
                            "id": str(group.get("id") or ""),
                            "name": str(group.get("name") or "Unknown Order"),
                        }
                    )
            saved_group_identifier = config.get_series_preference(
                self.controller.current_library_name,
                series_name,
                "display_group_id",
                "default",
            )
            if not any(
                group["id"] == saved_group_identifier for group in available_groups
            ):
                saved_group_identifier = "default"

            group_details = None
            if saved_group_identifier != "default":
                if saved_group_identifier not in self.episode_group_details_cache:
                    self.episode_group_details_cache[saved_group_identifier] = (
                        tmdb_client.get_episode_group_details(saved_group_identifier)
                        or {}
                    )
                group_details = self.episode_group_details_cache.get(
                    saved_group_identifier
                )

            self._update_series_ui(
                series_name=series_name,
                series_database_identifier=series_database_identifier,
                cast_entries=cast_entries,
                available_groups=available_groups,
                group_details=group_details,
                saved_group_identifier=saved_group_identifier,
            )

    async def _load_details_async(self, series_name: str) -> None:
        # Debounce: wait for 50ms to see if user keeps scrolling/clicking.
        # If cancelled during this sleep, the thread pool task will never be spawned!

        await asyncio.sleep(0.05)

        # 1. Fetch DB ID and Cast Entries (serialized) in a background thread
        series_database_identifier, cast_entries = await asyncio.to_thread(
            self._fetch_series_db_and_cast, series_name
        )

        # 2. Get metadata dictionary
        series_record: dict[str, Any] = self.controller.cached_library_data.get(
            series_name, {}
        )
        metadata_dictionary: dict[str, Any] = series_record.get("metadata", {})

        # 3. Fetch TMDB episode groups
        available_groups: list[dict[str, str]] = [
            {"id": "default", "name": "TV Order (Default)"}
        ]
        tmdb_identifier = metadata_dictionary.get("tmdb_identifier")
        if tmdb_identifier:
            if tmdb_identifier not in self.episode_groups_cache:
                fetched_groups = await asyncio.to_thread(
                    tmdb_client.get_episode_groups, tmdb_identifier
                )
                self.episode_groups_cache[tmdb_identifier] = fetched_groups
            groups_list = self.episode_groups_cache[tmdb_identifier]
            for group in groups_list:
                available_groups.append(
                    {
                        "id": str(group.get("id") or ""),
                        "name": str(group.get("name") or "Unknown Order"),
                    }
                )

        # 4. Get the saved group ID
        saved_group_identifier = config.get_series_preference(
            self.controller.current_library_name,
            series_name,
            "display_group_id",
            "default",
        )
        if not any(group["id"] == saved_group_identifier for group in available_groups):
            saved_group_identifier = "default"

        # 5. Fetch group details
        group_details = None
        if saved_group_identifier != "default":
            if saved_group_identifier not in self.episode_group_details_cache:
                fetched_details = await asyncio.to_thread(
                    tmdb_client.get_episode_group_details, saved_group_identifier
                )
                self.episode_group_details_cache[saved_group_identifier] = (
                    fetched_details or {}
                )
            group_details = self.episode_group_details_cache.get(saved_group_identifier)

        # 6. Update UI on the main thread
        self._update_series_ui(
            series_name=series_name,
            series_database_identifier=series_database_identifier,
            cast_entries=cast_entries,
            available_groups=available_groups,
            group_details=group_details,
            saved_group_identifier=saved_group_identifier,
        )

    def _update_series_ui(
        self,
        series_name: str,
        series_database_identifier: str | None,
        cast_entries: list[dict[str, Any]],
        available_groups: list[dict[str, str]],
        group_details: dict[str, Any] | None,
        saved_group_identifier: str,
    ) -> None:
        if getattr(self.controller, "is_video_playing", False):
            return

        self._current_series_db_id = series_database_identifier
        series_record: dict[str, Any] = self.controller.cached_library_data.get(
            series_name, {}
        )
        is_opening: bool = self._current_series_name != series_name
        self._current_series_name = series_name
        self._season_tables = {}

        current_tab_name: str | None = None
        if self.seasons_tab_widget.count() > 0:
            current_tab_name = self.seasons_tab_widget.tabText(
                self.seasons_tab_widget.currentIndex()
            )
        self.seasons_tab_widget.clear()

        today_str = datetime.datetime.now(datetime.UTC).date().isoformat()
        library_config = config.libraries.get(self.controller.current_library_name, {})
        show_future_episodes = library_config.get("show_future_episodes", True)
        hide_missing_future = config.get_series_preference(
            self.controller.current_library_name,
            series_name,
            "hide_missing_future",
            False,
        )

        seasons_dictionary, group_order_map = self._build_grouped_seasons(
            series_record.get("seasons", {}), group_details
        )
        self._populate_order_combo(available_groups, saved_group_identifier)
        sorted_season_names = self._sort_and_filter_seasons(
            seasons_dictionary, group_order_map
        )

        (
            next_episode_path,
            next_episode_season_text,
            next_episode_number_text,
        ) = self._find_next_unwatched_episode(
            seasons_dictionary,
            sorted_season_names,
            hide_missing_future,
            show_future_episodes,
            today_str,
        )
        self._update_play_next_button(
            next_episode_path, next_episode_season_text, next_episode_number_text
        )

        for season_name in sorted_season_names:
            season_data = seasons_dictionary.get(season_name, {})
            self._build_season_tab(
                season_name,
                season_data,
                hide_missing_future,
                show_future_episodes,
                today_str,
                series_name,
            )

        self._restore_or_select_season_tab(
            is_opening, current_tab_name, sorted_season_names, seasons_dictionary
        )
        self._display_cast_section(cast_entries)

    def _build_grouped_seasons(
        self,
        seasons_dictionary: dict[str, Any],
        group_details: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        group_order_map: dict[str, int] = {}
        if not group_details or "groups" not in group_details:
            return seasons_dictionary, group_order_map

        db_episodes_by_id: dict[str, dict[str, Any]] = {}
        db_episodes_by_number: dict[tuple[int, int], dict[str, Any]] = {}
        for season_name, season_data in seasons_dictionary.items():
            season_number_match = re.search(r"\d+", season_name)
            season_number = (
                int(season_number_match.group()) if season_number_match else 0
            )
            for episode in season_data.get("episodes", []):
                episode_identifier = episode.get(
                    "tmdb_episode_identifier"
                ) or episode.get("tmdb_identifier")
                if episode_identifier:
                    db_episodes_by_id[str(episode_identifier)] = episode
                episode_number = episode.get("tmdb_number")
                if episode_number is not None:
                    db_episodes_by_number[(season_number, episode_number)] = episode

        regrouped_seasons: dict[str, Any] = {}
        for index, group in enumerate(group_details["groups"]):
            group_name = group.get("name") or f"Group {group.get('order', '')}"
            group_order_map[group_name] = index
            episodes_list: list[dict[str, Any]] = []
            for group_episode in group.get("episodes", []):
                episode_identifier = str(group_episode.get("id", ""))
                db_episode = db_episodes_by_id.get(episode_identifier)
                if not db_episode:
                    db_episode = db_episodes_by_number.get(
                        (
                            group_episode.get("season_number"),
                            group_episode.get("episode_number"),
                        )
                    )

                if db_episode:
                    new_episode = db_episode.copy()
                    new_episode["tmdb_number"] = group_episode.get("order") + 1
                    if group_episode.get("name"):
                        new_episode["tmdb_name"] = group_episode.get("name")
                    episodes_list.append(new_episode)
                else:
                    episode_name = group_episode.get("name") or "TBA"
                    group_order = group_episode.get("order") + 1
                    formatted_name = f"{group_name} E{group_order:02d} - {episode_name}"
                    episodes_list.append(
                        {
                            "name": formatted_name,
                            "path": None,
                            "tmdb_identifier": episode_identifier,
                            "tmdb_episode_identifier": episode_identifier,
                            "tmdb_name": episode_name,
                            "tmdb_number": group_order,
                            "air_date": group_episode.get("air_date") or "",
                            "runtime": group_episode.get("runtime") or 0,
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
        return regrouped_seasons, group_order_map

    def _populate_order_combo(
        self,
        available_groups: list[dict[str, str]],
        saved_group_identifier: str,
    ) -> None:
        self.order_combo.blockSignals(True)
        self.order_combo.clear()
        for index, group in enumerate(available_groups):
            self.order_combo.addItem(group["name"], userData=group["id"])
            if group["id"] == saved_group_identifier:
                self.order_combo.setCurrentIndex(index)
        self.order_combo.blockSignals(False)

    def _sort_and_filter_seasons(
        self,
        seasons_dictionary: dict[str, Any],
        group_order_map: dict[str, int],
    ) -> list[str]:
        if group_order_map:
            sorted_season_names = sorted(
                seasons_dictionary.keys(), key=lambda k: group_order_map.get(k, 999)
            )
        else:
            try:
                sorted_season_names = sorted(
                    seasons_dictionary.keys(), key=db.natural_sort_key
                )
            except AttributeError, NameError:
                sorted_season_names = sorted(seasons_dictionary.keys())

        return [
            season_name
            for season_name in sorted_season_names
            if any(
                episode.get("path")
                for episode in seasons_dictionary.get(season_name, {}).get(
                    "episodes", []
                )
            )
        ]

    def _filter_episodes_for_display(
        self,
        episodes_list: list[dict[str, Any]],
        hide_missing_future: bool,
        show_future_episodes: bool,
        today_str: str,
    ) -> list[dict[str, Any]]:
        if hide_missing_future:
            return [
                episode_item
                for episode_item in episodes_list
                if episode_item.get("path")
            ]
        if not show_future_episodes:
            return [
                episode_item
                for episode_item in episodes_list
                if not (
                    episode_item.get("path") is None
                    and (
                        not (air_date_value := episode_item.get("air_date"))
                        or air_date_value > today_str
                    )
                )
            ]
        return episodes_list

    def _sort_episodes_by_number(
        self, episodes_list: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        try:
            return sorted(episodes_list, key=_episode_sort_key)
        except TypeError, ValueError:
            return episodes_list

    def _find_next_unwatched_episode(
        self,
        seasons_dictionary: dict[str, Any],
        sorted_season_names: list[str],
        hide_missing_future: bool,
        show_future_episodes: bool,
        today_str: str,
    ) -> tuple[str | None, str | None, str | None]:
        next_episode_path: str | None = None
        next_episode_season_text: str | None = None
        next_episode_number_text: str | None = None

        for season_name in sorted_season_names:
            season_data = seasons_dictionary.get(season_name, {})
            episodes_list = self._filter_episodes_for_display(
                season_data.get("episodes", []),
                hide_missing_future,
                show_future_episodes,
                today_str,
            )
            sorted_episodes = self._sort_episodes_by_number(episodes_list)

            for index, episode_record in enumerate(sorted_episodes):
                if not episode_record.get("watched", False) and episode_record.get(
                    "path"
                ):
                    next_episode_path = episode_record.get("path", "")

                    season_num_match = re.search(r"\d+", season_name)
                    if season_num_match:
                        next_episode_season_text = f"S{int(season_num_match.group())}"
                    else:
                        next_episode_season_text = season_name

                    tmdb_number_value = episode_record.get("tmdb_number")
                    next_episode_number_text = (
                        str(tmdb_number_value)
                        if tmdb_number_value is not None
                        else str(index + 1)
                    )
                    break
            if next_episode_path:
                break

        return next_episode_path, next_episode_season_text, next_episode_number_text

    def _update_play_next_button(
        self,
        next_episode_path: str | None,
        next_episode_season_text: str | None,
        next_episode_number_text: str | None,
    ) -> None:
        if next_episode_path:
            self._next_episode_path = next_episode_path
            self.play_next_button.setText(
                f"▶ PLAY {next_episode_season_text}:E{next_episode_number_text}"
            )
            self.play_next_button.setVisible(True)
        else:
            self._next_episode_path = ""
            self.play_next_button.setVisible(False)

    def _build_season_tab(
        self,
        season_name: str,
        season_data: dict[str, Any],
        hide_missing_future: bool,
        show_future_episodes: bool,
        today_str: str,
        series_name: str,
    ) -> None:
        episodes_list = self._filter_episodes_for_display(
            season_data.get("episodes", []),
            hide_missing_future,
            show_future_episodes,
            today_str,
        )
        sorted_episodes = self._sort_episodes_by_number(episodes_list)

        season_page = QWidget()
        season_layout = QVBoxLayout(season_page)
        season_layout.setContentsMargins(0, 5, 0, 0)
        season_layout.setSpacing(10)

        episode_table = QTableWidget()
        self._season_tables[season_name] = episode_table
        season_layout.addWidget(episode_table)

        episode_table.setColumnCount(6)
        episode_table.setHorizontalHeaderLabels(
            ["#", "Episode Title", "Air Date", "Runtime", "Progress", "Details"]
        )
        episode_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        episode_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        episode_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        episode_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        episode_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        episode_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Interactive
        )
        episode_table.setColumnWidth(5, 90)
        episode_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        episode_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        episode_table.verticalHeader().setVisible(False)
        episode_table.verticalHeader().setDefaultSectionSize(32)
        episode_table.setShowGrid(False)

        episode_table.cellClicked.connect(self._make_cell_clicked_slot(sorted_episodes))

        self._populate_episode_table(
            episode_table, sorted_episodes, today_str, series_name
        )
        self._setup_context_menu(episode_table, sorted_episodes)

        season_actions_layout = self._build_season_actions(
            season_name, sorted_episodes, series_name
        )
        season_layout.addLayout(season_actions_layout)

        self._season_tables[season_name] = episode_table
        season_layout.addWidget(episode_table)

        self.seasons_tab_widget.addTab(season_page, season_name)

    def _make_cell_clicked_slot(
        self, episode_list: list[dict[str, Any]]
    ) -> Callable[[int, int], None]:
        def slot(row: int, col: int) -> None:
            if col == 1:  # Title column
                target_path = episode_list[row].get("path", "")
                if target_path:
                    logger.info(
                        f"Episode table row clicked to play: '{episode_list[row].get('name')}' (Path: {target_path})"
                    )
                    self.controller.playback_requested.emit(target_path)

        return slot

    def _populate_episode_table(
        self,
        episode_table: QTableWidget,
        sorted_episodes: list[dict[str, Any]],
        today_str: str,
        series_name: str,
    ) -> None:
        episode_table.setRowCount(len(sorted_episodes))

        for row_index, episode_record in enumerate(sorted_episodes):
            tmdb_number_value: int | None = episode_record.get("tmdb_number")
            number_string: str = (
                str(tmdb_number_value)
                if tmdb_number_value is not None
                else str(row_index + 1)
            )

            tmdb_name_value: str | None = episode_record.get("tmdb_name")
            title_string: str = tmdb_name_value or episode_record.get("name", "Unknown")

            absolute_path: str = episode_record.get("path") or ""
            is_watched: bool = bool(episode_record.get("watched", False))
            air_date_string: str = episode_record.get("air_date") or ""
            runtime_value: int = (
                episode_record.get("file_runtime") or episode_record.get("runtime") or 0
            )
            runtime_string: str = f"{runtime_value} min" if runtime_value else ""

            if absolute_path:
                if is_watched:
                    text_color = QColor("#888888")
                    icon_str = "✓  "
                else:
                    text_color = QColor("#0e5296")
                    icon_str = "●  "
            else:
                is_missing = False
                if air_date_string:
                    try:
                        air_date_obj = datetime.date.fromisoformat(air_date_string)
                        today_obj = datetime.datetime.now(datetime.UTC).date()
                        if air_date_obj < today_obj:
                            is_missing = True
                    except ValueError:
                        if air_date_string < today_str:
                            is_missing = True

                if is_missing:
                    text_color = QColor("#ef4444")  # Bright Red
                    icon_str = "✕  "
                else:
                    text_color = QColor("#a78bfa")  # Lavender/purple
                    icon_str = "◊  "

            display_title = f"{icon_str}{title_string}"

            details_button: QPushButton = QPushButton("...")
            details_button.setToolTip("Details")
            details_button.setObjectName(f"detailsEpisodeButton_{row_index}")
            details_button.setStyleSheet("padding: 2px 8px; font-weight: bold;")

            if absolute_path:
                details_button.clicked.connect(
                    self._make_details_slot(series_name, absolute_path)
                )
            else:
                details_button.setEnabled(False)

            details_container: QWidget = QWidget()
            details_container.setStyleSheet("background-color: transparent;")
            details_layout: QHBoxLayout = QHBoxLayout(details_container)
            details_layout.setContentsMargins(2, 2, 2, 2)
            details_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            details_layout.addWidget(details_button)
            episode_table.setCellWidget(row_index, 5, details_container)

            number_item: QTableWidgetItem = QTableWidgetItem(number_string)
            number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            number_item.setForeground(text_color)
            episode_table.setItem(row_index, 0, number_item)

            title_item: QTableWidgetItem = QTableWidgetItem(display_title)
            title_item.setToolTip("Click to play episode" if absolute_path else "")
            title_item.setForeground(text_color)
            episode_table.setItem(row_index, 1, title_item)

            air_date_item: QTableWidgetItem = QTableWidgetItem(air_date_string)
            air_date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            air_date_item.setForeground(text_color)
            episode_table.setItem(row_index, 2, air_date_item)

            runtime_item: QTableWidgetItem = QTableWidgetItem(runtime_string)
            runtime_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            runtime_item.setForeground(text_color)
            episode_table.setItem(row_index, 3, runtime_item)

            progress_value: int = 0
            if is_watched:
                progress_value = 100
            elif absolute_path:
                position = episode_record.get("last_played_position", 0)
                if position and position > 0:
                    runtime_minutes = episode_record.get("runtime") or 0
                    file_runtime_minutes = episode_record.get("file_runtime") or 0
                    total_minutes = file_runtime_minutes or runtime_minutes
                    if total_minutes > 0:
                        total_seconds = total_minutes * 60
                        progress_value = min(int(position / total_seconds * 100), 99)

            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(progress_value)
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
            progress_container = QWidget()
            progress_container.setStyleSheet("background-color: transparent;")
            progress_layout = QHBoxLayout(progress_container)
            progress_layout.setContentsMargins(4, 2, 4, 2)
            progress_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            progress_layout.addWidget(progress_bar)
            episode_table.setCellWidget(row_index, 4, progress_container)

    def _make_details_slot(
        self, target_series: str, target_path: str
    ) -> Callable[[], None]:
        return lambda: self.controller.episode_details_requested.emit(
            target_series, target_path
        )

    def _setup_context_menu(
        self,
        episode_table: QTableWidget,
        sorted_episodes: list[dict[str, Any]],
    ) -> None:
        episode_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        episode_table.customContextMenuRequested.connect(
            self._show_episode_context_menu(episode_table, sorted_episodes)
        )

    def _show_episode_context_menu(
        self,
        table: QTableWidget,
        episode_list: list[dict[str, Any]],
    ) -> Callable[[QPoint], None]:
        def show_context_menu(menu_position: QPoint) -> None:
            item: QTableWidgetItem | None = table.itemAt(menu_position)
            if not item:
                return
            row: int = item.row()
            episode: dict[str, Any] = episode_list[row]
            if not episode.get("path"):
                return

            menu: QMenu = QMenu(table)

            is_watched: bool = bool(episode.get("watched", False))
            action_text: str = "Mark as Unwatched" if is_watched else "Mark as Watched"
            toggle_action: QAction = QAction(action_text, table)

            def handle_toggle() -> None:
                target_path: str = episode.get("path", "")
                if target_path:
                    new_status: bool = not is_watched
                    logger.info(
                        f"Context menu toggle watched status for episode '{episode.get('name')}' to {new_status} (Path: {target_path})"
                    )
                    self.controller.mark_episode_watched(target_path, new_status)
                    self.populate_series_details(self._current_series_name)

            toggle_action.triggered.connect(handle_toggle)
            menu.addAction(toggle_action)

            remove_action: QAction = QAction("Remove Episode", table)

            def handle_delete() -> None:
                target_path: str = episode.get("path", "")
                if target_path:
                    from PySide6.QtWidgets import QMessageBox

                    confirm = QMessageBox.question(
                        self,
                        "Remove Episode",
                        f"Are you sure you want to remove the episode '{Path(target_path).name}' from the library database? This is a nondestructive operation that only affects the database, and files will be picked up on the next scan.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if confirm == QMessageBox.StandardButton.Yes:
                        logger.info(
                            f"User confirmed removal of episode: '{episode.get('name')}' (Path: {target_path})"
                        )
                        self.controller.delete_episode(target_path)
                        self.populate_series_details(self._current_series_name)

            remove_action.triggered.connect(handle_delete)
            menu.addAction(remove_action)

            menu.exec(table.viewport().mapToGlobal(menu_position))

        return show_context_menu

    def _build_season_actions(
        self,
        season_name: str,
        sorted_episodes: list[dict[str, Any]],
        series_name: str,
    ) -> QHBoxLayout:
        season_actions_layout: QHBoxLayout = QHBoxLayout()
        local_episodes = [ep for ep in sorted_episodes if ep.get("path")]
        is_season_watched = len(local_episodes) > 0 and all(
            ep.get("watched", False) for ep in local_episodes
        )
        button_text = (
            "Mark season as unwatched"
            if is_season_watched
            else "Mark season as watched"
        )
        mark_season_button: QPushButton = QPushButton(button_text)
        mark_season_button.setObjectName(f"markSeasonWatchedButton_{season_name}")
        mark_season_button.clicked.connect(
            self._make_season_watched_slot(season_name, not is_season_watched)
        )
        season_actions_layout.addWidget(mark_season_button)

        season_detail_button: QPushButton = QPushButton("View Details")
        season_detail_button.setObjectName(f"seasonDetailButton_{season_name}")
        season_detail_button.clicked.connect(
            self._make_season_detail_slot(series_name, season_name)
        )
        season_actions_layout.addWidget(season_detail_button)

        season_actions_layout.addStretch()
        return season_actions_layout

    def _make_season_watched_slot(
        self,
        target_season: str,
        target_watched_state: bool,
    ) -> Callable[[], None]:
        return lambda: self._on_mark_season_watched(target_season, target_watched_state)

    def _make_season_detail_slot(
        self, target_series: str, target_season: str
    ) -> Callable[[], None]:
        return lambda: self.controller.season_detail_requested.emit(
            target_series, target_season
        )

    def _restore_or_select_season_tab(
        self,
        is_opening: bool,
        current_tab_name: str | None,
        sorted_season_names: list[str],
        seasons_dictionary: dict[str, Any],
    ) -> None:
        restored_tab = False
        if not is_opening and current_tab_name:
            for idx in range(self.seasons_tab_widget.count()):
                if self.seasons_tab_widget.tabText(idx) == current_tab_name:
                    self.seasons_tab_widget.setCurrentIndex(idx)
                    restored_tab = True
                    break

        if not restored_tab and sorted_season_names:
            target_tab_index: int = 0
            for index_position, season_name in enumerate(sorted_season_names):
                season_data_record = seasons_dictionary.get(season_name, {})
                has_unwatched: bool = False
                for ep in season_data_record.get("episodes", []):
                    if not ep.get("watched"):
                        has_unwatched = True
                        break
                if has_unwatched:
                    target_tab_index = index_position
                    break
            self.seasons_tab_widget.setCurrentIndex(target_tab_index)

    def trigger_episode_playback_by_row(
        self, season_tab_index: int, row_index: int
    ) -> None:
        """Test Helper triggering playback by simulating a click on the episode title cell."""
        target_widget: QWidget | None = self.seasons_tab_widget.widget(season_tab_index)
        if target_widget:
            table_target = target_widget.findChild(QTableWidget)
            if table_target:
                table_target.cellClicked.emit(row_index, 1)
