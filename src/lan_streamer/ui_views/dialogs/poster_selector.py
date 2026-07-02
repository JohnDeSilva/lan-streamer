"""Dialog for selecting and changing posters for series, seasons, and movies.

Supports three sources:
- TMDB: Fetches alternate poster/backdrop images from TMDB API.
- ThePosterDB: Opens the ThePosterDB website in a browser for manual download,
  then provides a local file upload path.
- Local Upload: Browse the filesystem to pick any local image file.
"""

import logging
import shutil
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select, update

from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Movie, Season, Series
from lan_streamer.providers.tmdb import tmdb_client, TMDB_IMAGE_BASE_ORIGINAL

logger = logging.getLogger(__name__)

# Cache directory for locally-managed poster overrides
_POSTER_OVERRIDE_CACHE = (
    Path.home() / ".config" / "lan-streamer" / "cache" / "poster_overrides"
)


class _TmdbImageFetchWorker(QObject):
    """Background worker that fetches TMDB image lists and downloads thumbnails."""

    images_ready = Signal(list)  # list[dict] of image metadata
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(
        self,
        tmdb_identifier: int,
        media_kind: str,
        parent: Optional[QObject] = None,
    ) -> None:
        """Initialise the worker.

        Args:
            tmdb_identifier: TMDB numeric ID for the series or movie.
            media_kind: Either ``"series"`` or ``"movie"``.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._tmdb_identifier = tmdb_identifier
        self._media_kind = media_kind

    def run(self) -> None:
        """Fetch image list from TMDB and emit result."""
        try:
            if self._media_kind == "series":
                raw_data = tmdb_client.get_series_images(self._tmdb_identifier)
            else:
                raw_data = tmdb_client.get_movie_images(self._tmdb_identifier)

            poster_entries: List[Dict[str, Any]] = raw_data.get("posters", [])
            backdrop_entries: List[Dict[str, Any]] = raw_data.get("backdrops", [])
            all_entries = [
                {"image_type": "poster", **entry} for entry in poster_entries
            ] + [{"image_type": "backdrop", **entry} for entry in backdrop_entries]

            logger.info(
                "TMDB image fetch for %s %s: %d posters, %d backdrops",
                self._media_kind,
                self._tmdb_identifier,
                len(poster_entries),
                len(backdrop_entries),
            )
            self.images_ready.emit(all_entries)
        except Exception as fetch_error:
            logger.exception(
                "TMDB image fetch failed for %s %s",
                self._media_kind,
                self._tmdb_identifier,
            )
            self.error_occurred.emit(str(fetch_error))
        finally:
            self.finished.emit()


class _ThumbnailDownloader(QObject):
    """Asynchronous worker to download thumbnail images."""

    downloaded = Signal(bytes, object)  # content, label

    def __init__(
        self, image_url: str, label: QLabel, parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)
        self.image_url = image_url
        self.label = label

    def start_download(self) -> None:
        import threading

        def worker() -> None:
            try:
                import requests as http_requests

                response = http_requests.get(self.image_url, timeout=8)
                if response.status_code == 200:
                    self.downloaded.emit(response.content, self.label)
            except Exception:
                logger.debug("Thumbnail fetch failed for %s", self.image_url)

        threading.Thread(target=worker, daemon=True).start()


class PosterSelectorDialog(QDialog):
    """Dialog for browsing and selecting posters/backdrops for media.

    Supports series, season, and movie poster selection via TMDB image
    search, local file upload, and a link to ThePosterDB for browsing.

    Args:
        media_name: Display name of the media item.
        media_kind: One of ``"series"``, ``"season"``, or ``"movie"``.
        series_name: For seasons, the parent series name (used to resolve the DB record).
        parent: Optional parent widget.
    """

    poster_updated = Signal(str)  # Emitted with the new local image path

    def __init__(
        self,
        media_name: str,
        media_kind: str = "series",
        series_name: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._media_name = media_name
        self._media_kind = media_kind  # "series", "season", or "movie"
        self._series_name = series_name  # only used when media_kind == "season"

        self._series_db_id: Optional[str] = None
        self._movie_db_id: Optional[str] = None
        self._season_db_id: Optional[str] = None
        self._tmdb_numeric_id: Optional[int] = None

        self._fetch_thread: Optional[QThread] = None
        self._fetch_worker: Optional[_TmdbImageFetchWorker] = None

        self.setWindowTitle(f"Change Poster — {media_name}")
        self.setMinimumSize(800, 580)
        self.resize(900, 620)

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(12, 12, 12, 12)
        self._root_layout.setSpacing(10)

        self._resolve_media_ids()
        self._build_ui()

    # ------------------------------------------------------------------
    # DB resolution
    # ------------------------------------------------------------------

    def _resolve_media_ids(self) -> None:
        """Resolve database primary-key IDs and TMDB numeric ID from the DB."""
        with get_session() as session:
            if self._media_kind == "movie":
                movie_record = session.scalars(
                    select(Movie).where(Movie.name == self._media_name)
                ).first()
                if movie_record is not None:
                    self._movie_db_id = movie_record.id
                    raw_tmdb_id = movie_record.tmdb_identifier
                    if raw_tmdb_id is not None:
                        try:
                            self._tmdb_numeric_id = int(raw_tmdb_id)
                        except ValueError, TypeError:
                            logger.warning(
                                "Cannot parse TMDB numeric ID '%s' for movie '%s'",
                                raw_tmdb_id,
                                self._media_name,
                            )

            elif self._media_kind == "season":
                parent_series_name = self._series_name or self._media_name
                series_record = session.scalars(
                    select(Series).where(Series.name == parent_series_name)
                ).first()
                if series_record is not None:
                    self._series_db_id = series_record.id
                    raw_tmdb_id = series_record.tmdb_identifier
                    if raw_tmdb_id is not None:
                        try:
                            self._tmdb_numeric_id = int(raw_tmdb_id)
                        except ValueError, TypeError:
                            pass
                    # Resolve season
                    season_record = session.scalars(
                        select(Season).where(
                            Season.series_id == series_record.id,
                            Season.name == self._media_name,
                        )
                    ).first()
                    if season_record is not None:
                        self._season_db_id = season_record.id

            else:  # series
                series_record = session.scalars(
                    select(Series).where(Series.name == self._media_name)
                ).first()
                if series_record is not None:
                    self._series_db_id = series_record.id
                    raw_tmdb_id = series_record.tmdb_identifier
                    if raw_tmdb_id is not None:
                        try:
                            self._tmdb_numeric_id = int(raw_tmdb_id)
                        except ValueError, TypeError:
                            pass

        logger.info(
            "PosterSelectorDialog resolved IDs: series=%s movie=%s season=%s tmdb=%s",
            self._series_db_id,
            self._movie_db_id,
            self._season_db_id,
            self._tmdb_numeric_id,
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build the full dialog UI."""
        # Header
        header_label = QLabel(f"🖼  Change Poster: <b>{self._media_name}</b>")
        header_label.setStyleSheet(
            "font-size: 15px; color: #E2E8F0; padding-bottom: 4px;"
        )
        self._root_layout.addWidget(header_label)

        # Tab widget
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(
            """
            QTabWidget::pane { border: 1px solid #2d2d3e; border-radius: 6px; }
            QTabBar::tab { padding: 8px 16px; color: #94A3B8; background: #1a1a2e; }
            QTabBar::tab:selected { color: #E2E8F0; background: #16213e;
                                    border-bottom: 2px solid #6366f1; }
            """
        )
        self._root_layout.addWidget(self._tab_widget, 1)

        # Build tabs
        self._tab_widget.addTab(self._build_tmdb_tab(), "🎬 TMDB Images")
        self._tab_widget.addTab(self._build_posterdb_tab(), "🌐 ThePosterDB")
        self._tab_widget.addTab(self._build_local_upload_tab(), "📁 Local File")

        # Close button row
        button_row = QHBoxLayout()
        button_row.addStretch()
        close_button = QPushButton("Close")
        close_button.setFixedWidth(100)
        close_button.setStyleSheet(
            "background: #2d2d3e; color: #E2E8F0; border-radius: 5px; padding: 6px 14px;"
        )
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        self._root_layout.addLayout(button_row)

    def _build_tmdb_tab(self) -> QWidget:
        """Build the TMDB image browsing tab."""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(8, 8, 8, 8)
        container_layout.setSpacing(8)

        if self._tmdb_numeric_id is None:
            notice = QLabel(
                "⚠ No TMDB identifier linked to this media item.\n"
                "Run a library scan with TMDB configured to fetch metadata first."
            )
            notice.setStyleSheet("color: #f59e0b; padding: 20px;")
            notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
            container_layout.addWidget(notice)
            return container

        action_row = QHBoxLayout()
        self._tmdb_fetch_button = QPushButton("⬇  Fetch Images from TMDB")
        self._tmdb_fetch_button.setStyleSheet(
            "background: #6366f1; color: white; border-radius: 5px; "
            "padding: 7px 18px; font-weight: bold;"
        )
        self._tmdb_fetch_button.clicked.connect(self._on_fetch_tmdb_images)
        action_row.addWidget(self._tmdb_fetch_button)
        action_row.addStretch()

        self._tmdb_status_label = QLabel("")
        self._tmdb_status_label.setStyleSheet("color: #94A3B8;")
        action_row.addWidget(self._tmdb_status_label)
        container_layout.addLayout(action_row)

        # Scroll area for image grid
        self._tmdb_scroll = QScrollArea()
        self._tmdb_scroll.setWidgetResizable(True)
        self._tmdb_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tmdb_scroll.setStyleSheet("background: transparent;")
        self._tmdb_grid_host = QWidget()
        self._tmdb_grid_layout = QGridLayout(self._tmdb_grid_host)
        self._tmdb_grid_layout.setSpacing(10)
        self._tmdb_scroll.setWidget(self._tmdb_grid_host)
        container_layout.addWidget(self._tmdb_scroll, 1)

        placeholder = QLabel(
            "Click 'Fetch Images from TMDB' to load available posters."
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #475569; font-size: 13px;")
        self._tmdb_grid_layout.addWidget(placeholder, 0, 0)
        self._tmdb_placeholder_label = placeholder

        return container

    def _build_posterdb_tab(self) -> QWidget:
        """Build the ThePosterDB information and navigation tab."""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(16)

        info_label = QLabel(
            "<b>ThePosterDB</b> is a community poster art site that does not provide "
            "a public API. You can browse it in your browser, download posters "
            "manually, then use the <i>Local File</i> tab to apply them."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #94A3B8; font-size: 13px; line-height: 1.5;")
        container_layout.addWidget(info_label)

        # Build search URL
        safe_name = self._media_name.replace(" ", "+")
        posterdb_search_url = f"https://theposterdb.com/search?term={safe_name}"
        posterdb_home_url = "https://theposterdb.com"

        search_button = QPushButton(f'🔍  Search ThePosterDB for "{self._media_name}"')
        search_button.setStyleSheet(
            "background: #0891b2; color: white; border-radius: 5px; "
            "padding: 9px 20px; font-weight: bold; font-size: 13px;"
        )
        search_button.clicked.connect(lambda: webbrowser.open(posterdb_search_url))
        container_layout.addWidget(search_button)

        home_button = QPushButton("🌐  Open ThePosterDB Home")
        home_button.setStyleSheet(
            "background: #1e293b; color: #94A3B8; border: 1px solid #334155; "
            "border-radius: 5px; padding: 7px 16px;"
        )
        home_button.clicked.connect(lambda: webbrowser.open(posterdb_home_url))
        container_layout.addWidget(home_button)

        instruction_label = QLabel(
            "💡 After downloading a poster from ThePosterDB, switch to the "
            "<b>Local File</b> tab to apply it to this media item."
        )
        instruction_label.setWordWrap(True)
        instruction_label.setStyleSheet(
            "color: #64748B; font-size: 12px; margin-top: 10px;"
        )
        container_layout.addWidget(instruction_label)
        container_layout.addStretch()
        return container

    def _build_local_upload_tab(self) -> QWidget:
        """Build the local file upload tab."""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(14)

        info_label = QLabel(
            "Select an image file from your computer to use as the poster. "
            "Supported formats: JPEG, PNG, WebP, BMP."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #94A3B8; font-size: 13px;")
        container_layout.addWidget(info_label)

        browse_row = QHBoxLayout()
        self._local_path_label = QLabel("No file selected")
        self._local_path_label.setStyleSheet(
            "color: #475569; font-size: 12px; font-style: italic;"
        )
        self._local_path_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        browse_row.addWidget(self._local_path_label)

        browse_button = QPushButton("Browse…")
        browse_button.setStyleSheet(
            "background: #1e293b; color: #E2E8F0; border: 1px solid #334155; "
            "border-radius: 5px; padding: 7px 16px;"
        )
        browse_button.clicked.connect(self._on_browse_local_file)
        browse_row.addWidget(browse_button)
        container_layout.addLayout(browse_row)

        # Preview area
        preview_frame = QFrame()
        preview_frame.setFrameShape(QFrame.Shape.StyledPanel)
        preview_frame.setStyleSheet(
            "background: #0f172a; border: 1px solid #1e293b; border-radius: 8px;"
        )
        preview_frame.setFixedHeight(320)
        preview_layout = QVBoxLayout(preview_frame)
        self._local_preview_label = QLabel("Preview will appear here")
        self._local_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._local_preview_label.setStyleSheet("color: #475569;")
        preview_layout.addWidget(self._local_preview_label)
        container_layout.addWidget(preview_frame)

        self._local_apply_button = QPushButton("✓  Apply This Poster")
        self._local_apply_button.setEnabled(False)
        self._local_apply_button.setStyleSheet(
            "background: #22c55e; color: white; border-radius: 5px; "
            "padding: 9px 22px; font-weight: bold; font-size: 13px;"
        )
        self._local_apply_button.clicked.connect(self._on_apply_local_poster)
        container_layout.addWidget(self._local_apply_button)

        self._local_selected_path: Optional[str] = None
        container_layout.addStretch()
        return container

    # ------------------------------------------------------------------
    # TMDB fetching
    # ------------------------------------------------------------------

    def _on_fetch_tmdb_images(self) -> None:
        """Launch background thread to fetch TMDB images."""
        if self._tmdb_numeric_id is None:
            return

        self._tmdb_fetch_button.setEnabled(False)
        self._tmdb_status_label.setText("⏳  Fetching from TMDB…")

        # Clear existing grid contents
        while self._tmdb_grid_layout.count():
            item = self._tmdb_grid_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        # Determine whether this is a series or movie for the API call
        tmdb_media_kind = "movie" if self._media_kind == "movie" else "series"

        self._fetch_thread = QThread()
        self._fetch_worker = _TmdbImageFetchWorker(
            tmdb_identifier=self._tmdb_numeric_id,
            media_kind=tmdb_media_kind,
        )
        self._fetch_worker.moveToThread(self._fetch_thread)
        self._fetch_thread.started.connect(self._fetch_worker.run)
        self._fetch_worker.images_ready.connect(self._on_tmdb_images_ready)
        self._fetch_worker.error_occurred.connect(self._on_tmdb_fetch_error)
        self._fetch_worker.finished.connect(self._fetch_thread.quit)
        self._fetch_worker.finished.connect(self._fetch_worker.deleteLater)
        self._fetch_thread.finished.connect(self._fetch_thread.deleteLater)
        self._fetch_thread.start()

        logger.info(
            "Launched TMDB image fetch thread for %s %s",
            tmdb_media_kind,
            self._tmdb_numeric_id,
        )

    def _on_tmdb_images_ready(self, image_list: List[Dict[str, Any]]) -> None:
        """Populate TMDB image grid once images are fetched."""
        self._tmdb_fetch_button.setEnabled(True)

        poster_entries = [
            entry for entry in image_list if entry.get("image_type") == "poster"
        ]
        backdrop_entries = [
            entry for entry in image_list if entry.get("image_type") == "backdrop"
        ]

        self._tmdb_status_label.setText(
            f"✓  {len(poster_entries)} posters, {len(backdrop_entries)} backdrops found"
        )

        if not image_list:
            no_results_label = QLabel("No images found on TMDB for this title.")
            no_results_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_results_label.setStyleSheet("color: #f59e0b; padding: 20px;")
            self._tmdb_grid_layout.addWidget(no_results_label, 0, 0)
            return

        max_columns = 4
        row_index = 0
        column_index = 0

        for image_entry in image_list[:24]:  # cap at 24 for UI performance
            card = self._build_tmdb_image_card(image_entry)
            self._tmdb_grid_layout.addWidget(card, row_index, column_index)
            column_index += 1
            if column_index >= max_columns:
                column_index = 0
                row_index += 1

        logger.info("Rendered %d TMDB image cards in grid", min(len(image_list), 24))

    def _on_tmdb_fetch_error(self, error_message: str) -> None:
        """Handle TMDB fetch error."""
        self._tmdb_fetch_button.setEnabled(True)
        self._tmdb_status_label.setText("✗  Fetch failed")
        error_label = QLabel(f"Failed to fetch images from TMDB:\n{error_message}")
        error_label.setStyleSheet("color: #ef4444; padding: 12px;")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tmdb_grid_layout.addWidget(error_label, 0, 0)
        logger.error("TMDB image fetch error: %s", error_message)

    def _build_tmdb_image_card(self, image_entry: Dict[str, Any]) -> QFrame:
        """Build a single image card widget for the TMDB grid.

        Args:
            image_entry: Dictionary from TMDB image API response with
                         ``file_path``, ``width``, ``height``, ``image_type``.

        Returns:
            A styled QFrame card widget.
        """
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setFixedSize(185, 310)
        card.setStyleSheet(
            "background: #0f172a; border: 1px solid #1e293b; border-radius: 8px;"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 6, 6, 6)
        card_layout.setSpacing(4)

        image_label = QLabel()
        image_label.setFixedSize(170, 255)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setStyleSheet("background: #1e293b; border-radius: 4px;")
        image_label.setText("⏳")
        card_layout.addWidget(image_label)

        file_path = image_entry.get("file_path", "")
        image_type = image_entry.get("image_type", "poster")
        width_value = image_entry.get("width", 0)
        height_value = image_entry.get("height", 0)

        meta_label = QLabel(f"{image_type.capitalize()} • {width_value}×{height_value}")
        meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        meta_label.setStyleSheet("color: #475569; font-size: 10px;")
        card_layout.addWidget(meta_label)

        select_button = QPushButton("Select")
        select_button.setStyleSheet(
            "background: #6366f1; color: white; border-radius: 4px; padding: 5px;"
        )
        select_button.clicked.connect(
            lambda checked=False, fp=file_path, it=image_type: (
                self._on_select_tmdb_image(fp, it)
            )
        )
        card_layout.addWidget(select_button)

        # Load thumbnail lazily via a short URL fetch (uses w185 size)
        if file_path:
            thumbnail_url = f"https://image.tmdb.org/t/p/w185{file_path}"
            self._load_thumbnail_into_label(thumbnail_url, image_label)

        return card

    def _load_thumbnail_into_label(self, image_url: str, label: QLabel) -> None:
        """Download and display a thumbnail image in the given label.

        Runs asynchronously in a background thread and updates the UI on completion.

        Args:
            image_url: Full URL for the thumbnail image.
            label: QLabel widget to display the pixmap in.
        """
        downloader = _ThumbnailDownloader(image_url, label, parent=self)
        label.setProperty("_downloader", downloader)
        downloader.downloaded.connect(self._on_thumbnail_downloaded)
        downloader.start_download()

    @Slot(bytes, object)
    def _on_thumbnail_downloaded(self, content: bytes, label: object) -> None:
        """Process downloaded thumbnail bytes on the main GUI thread."""
        if not isinstance(label, QLabel):
            return
        pixmap = QPixmap()
        pixmap.loadFromData(content)
        if not pixmap.isNull():
            label.setPixmap(
                pixmap.scaled(
                    170,
                    255,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            label.setText("📷")
        label.setProperty("_downloader", None)

    def _on_select_tmdb_image(self, tmdb_file_path: str, image_type: str) -> None:
        """Download the selected TMDB image and apply it as the active poster.

        Args:
            tmdb_file_path: TMDB relative file path (e.g. ``/abc123.jpg``).
            image_type: Either ``"poster"`` or ``"backdrop"``.
        """
        if not tmdb_file_path:
            return

        image_url = f"{TMDB_IMAGE_BASE_ORIGINAL}{tmdb_file_path}"

        logger.info("Downloading TMDB %s image: %s", image_type, image_url)

        local_path = tmdb_client.download_and_cache_image(
            tmdb_file_path, size="original"
        )

        if not local_path:
            QMessageBox.warning(
                self,
                "Download Failed",
                f"Could not download the image from TMDB.\n\nURL: {image_url}",
            )
            return

        self._apply_poster_path(local_path, image_type)

    # ------------------------------------------------------------------
    # Local file upload
    # ------------------------------------------------------------------

    def _on_browse_local_file(self) -> None:
        """Open a file dialog and set the selected image for preview."""
        selected_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Poster Image",
            str(Path.home()),
            "Image Files (*.jpg *.jpeg *.png *.webp *.bmp *.tiff);;All Files (*)",
        )
        if not selected_file:
            return

        self._local_selected_path = selected_file
        self._local_path_label.setText(selected_file)

        pixmap = QPixmap(selected_file)
        if not pixmap.isNull():
            self._local_preview_label.setPixmap(
                pixmap.scaled(
                    280,
                    300,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self._local_apply_button.setEnabled(True)
            logger.info("Local poster file selected: %s", selected_file)
        else:
            self._local_preview_label.setText("⚠ Cannot read selected file as image")
            self._local_apply_button.setEnabled(False)
            logger.warning("Selected file is not a valid image: %s", selected_file)

    def _on_apply_local_poster(self) -> None:
        """Copy the selected local file into the override cache and apply it."""
        if not self._local_selected_path:
            return

        source_path = Path(self._local_selected_path)
        if not source_path.is_file():
            QMessageBox.warning(
                self,
                "File Not Found",
                f"The selected file no longer exists:\n{self._local_selected_path}",
            )
            return

        # Copy to override cache so the original can be moved/deleted freely
        _POSTER_OVERRIDE_CACHE.mkdir(parents=True, exist_ok=True)
        safe_name = self._media_name.replace(" ", "_").replace("/", "_")
        destination_path = _POSTER_OVERRIDE_CACHE / f"{safe_name}{source_path.suffix}"
        try:
            shutil.copy2(source_path, destination_path)
        except OSError as copy_error:
            QMessageBox.critical(
                self,
                "Copy Failed",
                f"Could not copy image to cache:\n{copy_error}",
            )
            logger.exception("Failed to copy local poster file")
            return

        logger.info(
            "Copied local poster from '%s' to '%s'", source_path, destination_path
        )
        self._apply_poster_path(str(destination_path), "poster")

    # ------------------------------------------------------------------
    # Poster application
    # ------------------------------------------------------------------

    def _apply_poster_path(self, local_image_path: str, image_type: str) -> None:
        """Write the chosen poster path back to the database and emit update signal.

        For series and movies this updates the ``poster_path`` column on the
        primary record.  For seasons it updates ``Season.poster_path``.

        Args:
            local_image_path: Absolute path to the local image file.
            image_type: Image type label (``"poster"`` or ``"backdrop"``).
        """
        logger.info(
            "Applying %s image path '%s' to %s '%s'",
            image_type,
            local_image_path,
            self._media_kind,
            self._media_name,
        )

        with get_session() as session:
            if self._media_kind == "series" and self._series_db_id is not None:
                session.execute(
                    update(Series)
                    .where(Series.id == self._series_db_id)
                    .values(poster_path=local_image_path)
                )
                logger.info(
                    "Updated series '%s' poster_path to '%s'",
                    self._media_name,
                    local_image_path,
                )

            elif self._media_kind == "season" and self._season_db_id is not None:
                session.execute(
                    update(Season)
                    .where(Season.id == self._season_db_id)
                    .values(poster_path=local_image_path)
                )
                logger.info(
                    "Updated season '%s' poster_path to '%s'",
                    self._media_name,
                    local_image_path,
                )

            elif self._media_kind == "movie" and self._movie_db_id is not None:
                session.execute(
                    update(Movie)
                    .where(Movie.id == self._movie_db_id)
                    .values(poster_path=local_image_path)
                )
                logger.info(
                    "Updated movie '%s' poster_path to '%s'",
                    self._media_name,
                    local_image_path,
                )

            else:
                QMessageBox.warning(
                    self,
                    "Cannot Apply Poster",
                    "Could not find the media record in the database. "
                    "Please run a library scan first.",
                )
                logger.warning(
                    "Cannot apply poster: no DB record resolved for %s '%s'",
                    self._media_kind,
                    self._media_name,
                )
                return

        QMessageBox.information(
            self,
            "Poster Updated",
            f"The poster for '{self._media_name}' has been updated successfully.",
        )
        self.poster_updated.emit(local_image_path)
        self.accept()
