from pathlib import Path
from typing import Dict, Any, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QLineEdit,
    QCheckBox,
    QListWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QTabWidget,
)
from PySide6.QtCore import Slot
from PySide6.QtGui import QFont

from lan_streamer.system.config import config
from lan_streamer.ui_views.proxy import QMessageBox, jellyfin_client
from lan_streamer.ui_views.dialogs.subtitle_search import SubtitleSearchDialog

if TYPE_CHECKING:
    from lan_streamer.ui_views.controller import Controller


class EpisodeDetailsDialog(QDialog):
    """
    Comprehensive multi-tab interface for viewing/editing episode metadata
    and inspecting technical file characteristics.
    """

    def __init__(
        self,
        series_name: str,
        episode_path: str,
        controller_instance: "Controller",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.episode_path: str = episode_path
        self.controller: "Controller" = controller_instance
        self.episode_record: Dict[str, Any] = {}

        # UI Elements for Tab 1 (Metadata)
        self.title_edit: QLineEdit = QLineEdit()
        self.runtime_edit: QLineEdit = QLineEdit()
        self.air_date_edit: QLineEdit = QLineEdit()
        self.locked_checkbox: QCheckBox = QCheckBox("Locked Metadata")

        # UI Elements for Tab 2 (File Info)
        self.path_label: QLabel = QLabel()
        self.size_label: QLabel = QLabel()
        self.type_label: QLabel = QLabel()
        self.codec_label: QLabel = QLabel()
        self.resolution_label: QLabel = QLabel()
        self.audio_list: QListWidget = QListWidget()
        self.subtitle_list: QListWidget = QListWidget()
        self.external_sub_list: QListWidget = QListWidget()
        self.merge_button: QPushButton = QPushButton(
            "Combine Subtitles into Video File"
        )

        self.setWindowTitle(f"Episode Details: {Path(episode_path).name}")
        self.resize(700, 600)
        self._load_data()
        self._setup_ui()
        self._refresh_file_info()

    def _load_data(self) -> None:
        series_data = self.controller.cached_library_data.get(self.series_name, {})
        for season in series_data.get("seasons", {}).values():
            for ep in season.get("episodes", []):
                if ep.get("path") == self.episode_path:
                    self.episode_record = ep
                    break
            if self.episode_record:
                break

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._create_metadata_tab(), "Metadata")
        tabs.addTab(self._create_file_info_tab(), "File Information")
        main_layout.addWidget(tabs)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        cancel_btn = QPushButton("Close")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save Changes")
        save_btn.setObjectName("accentButton")
        save_btn.clicked.connect(self._on_save_clicked)
        buttons_layout.addWidget(cancel_btn)
        buttons_layout.addWidget(save_btn)
        main_layout.addLayout(buttons_layout)

    def _create_metadata_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)

        form = QGridLayout()
        form.addWidget(QLabel("Title:"), 0, 0)
        form.addWidget(self.title_edit, 0, 1)

        form.addWidget(QLabel("Runtime (min):"), 1, 0)
        form.addWidget(self.runtime_edit, 1, 1)

        form.addWidget(QLabel("Air Date:"), 2, 0)
        form.addWidget(self.air_date_edit, 2, 1)

        layout.addLayout(form)
        layout.addWidget(self.locked_checkbox)

        refresh_btn = QPushButton("Refresh Metadata")
        refresh_btn.setObjectName("refreshMetadataButton")
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(refresh_btn)

        search_btn = QPushButton("Search TMDB for this Episode...")
        search_btn.clicked.connect(self._on_search_tmdb_clicked)
        layout.addWidget(search_btn)

        embed_btn = QPushButton("Embed Metadata into Video File")
        embed_btn.clicked.connect(self._on_embed_clicked)
        layout.addWidget(embed_btn)

        layout.addStretch()

        # Populate
        self.title_edit.setText(
            self.episode_record.get("tmdb_name")
            or self.episode_record.get("name")
            or ""
        )
        self.runtime_edit.setText(str(self.episode_record.get("runtime") or ""))
        self.air_date_edit.setText(self.episode_record.get("air_date") or "")
        self.locked_checkbox.setChecked(
            bool(self.episode_record.get("locked_metadata", False))
        )

        return widget

    def _create_file_info_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Path:</b>"), 0, 0)
        self.path_label.setWordWrap(True)
        grid.addWidget(self.path_label, 0, 1)

        grid.addWidget(QLabel("<b>Size:</b>"), 1, 0)
        grid.addWidget(self.size_label, 1, 1)

        grid.addWidget(QLabel("<b>Type:</b>"), 2, 0)
        grid.addWidget(self.type_label, 2, 1)

        grid.addWidget(QLabel("<b>Codec:</b>"), 3, 0)
        grid.addWidget(self.codec_label, 3, 1)

        grid.addWidget(QLabel("<b>Resolution:</b>"), 4, 0)
        grid.addWidget(self.resolution_label, 4, 1)

        layout.addLayout(grid)

        layout.addWidget(QLabel("<b>Internal Audio Tracks:</b>"))
        self.audio_list.setMaximumHeight(100)
        layout.addWidget(self.audio_list)

        layout.addWidget(QLabel("<b>Internal Subtitle Tracks:</b>"))
        self.subtitle_list.setMaximumHeight(100)
        layout.addWidget(self.subtitle_list)

        layout.addWidget(QLabel("<b>Detected External Subtitles:</b>"))
        self.external_sub_list.setMaximumHeight(100)
        layout.addWidget(self.external_sub_list)

        self.merge_button.setObjectName("accentButton")
        self.merge_button.clicked.connect(self._on_merge_clicked)
        layout.addWidget(self.merge_button)

        osub_btn = QPushButton("Search OpenSubtitles.com for Subtitles...")
        osub_btn.clicked.connect(self._on_search_osub_clicked)
        layout.addWidget(osub_btn)

        layout.addStretch()

        return widget

    def _refresh_file_info(self) -> None:
        from lan_streamer.scanner import get_detailed_file_info, SUBTITLE_EXTENSIONS

        # Check if we have cached technical metadata in the episode record
        info: Dict[str, Any]
        has_db_info = bool(self.episode_record.get("video_codec"))
        if has_db_info:
            info = {
                "path": self.episode_path,
                "video_codec": self.episode_record.get("video_codec"),
                "resolution": self.episode_record.get("resolution") or "Unknown",
                "audio_tracks": self.episode_record.get("audio_tracks") or [],
                "subtitle_tracks": self.episode_record.get("subtitle_tracks") or [],
            }
            try:
                info["size_bytes"] = Path(self.episode_path).stat().st_size
            except Exception:
                info["size_bytes"] = 0
            info["video_type"] = Path(self.episode_path).suffix.upper().replace(".", "")
        else:
            info = get_detailed_file_info(self.episode_path)

        self.path_label.setText(self.episode_path)
        size_mb = info["size_bytes"] / (1024 * 1024)
        self.size_label.setText(f"{size_mb:.2f} MB")
        self.type_label.setText(info["video_type"])
        self.codec_label.setText(info.get("video_codec", "Unknown"))
        self.resolution_label.setText(info["resolution"])

        self.audio_list.clear()
        for track in info["audio_tracks"]:
            self.audio_list.addItem(
                f"Track {track['index']}: {track['codec']} ({track['language']}) {track['title']}"
            )

        self.subtitle_list.clear()
        for track in info["subtitle_tracks"]:
            self.subtitle_list.addItem(
                f"Track {track['index']}: {track['codec']} ({track['language']}) {track['title']}"
            )

        # Detect external subtitles
        self.external_sub_list.clear()
        ext_subs = []
        parent_dir = Path(self.episode_path).parent
        stem = Path(self.episode_path).stem
        if parent_dir.exists():
            for f in parent_dir.iterdir():
                if f.suffix.lower() in SUBTITLE_EXTENSIONS and f.stem.startswith(stem):
                    ext_subs.append(str(f.absolute()))
                    self.external_sub_list.addItem(f.name)

        self.merge_button.setEnabled(len(ext_subs) > 0)
        self._ext_subs = ext_subs

    @Slot()
    def _on_save_clicked(self) -> None:
        metadata = {
            "tmdb_name": self.title_edit.text(),
            "air_date": self.air_date_edit.text(),
            "locked_metadata": self.locked_checkbox.isChecked(),
        }
        try:
            metadata["runtime"] = (
                int(self.runtime_edit.text()) if self.runtime_edit.text() else 0
            )
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Runtime must be a number.")
            return

        self.controller.update_episode_metadata(
            self.series_name, self.episode_path, metadata
        )
        self.accept()

    @Slot()
    def _on_search_tmdb_clicked(self) -> None:
        # Trigger the existing EpisodeMatchDialog
        self.controller.episode_metadata_dialog_requested.emit(
            self.series_name, self.episode_path
        )
        # Close this one as the metadata might change
        self.reject()

    @Slot()
    def _on_refresh_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Confirm Refresh",
            "Are you sure you want to refresh metadata for this episode from TMDB?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.refresh_episode_metadata(
                self.series_name, self.episode_path
            )
            # Reload data and update UI fields
            self._load_data()
            self.title_edit.setText(
                self.episode_record.get("tmdb_name")
                or self.episode_record.get("name")
                or ""
            )
            self.runtime_edit.setText(str(self.episode_record.get("runtime") or ""))
            self.air_date_edit.setText(self.episode_record.get("air_date") or "")
            self.locked_checkbox.setChecked(
                bool(self.episode_record.get("locked_metadata", False))
            )

    @Slot()
    def _on_embed_clicked(self) -> None:
        """Collects current UI metadata and triggers embedding."""
        metadata = {
            "title": self.title_edit.text(),
            "show": self.series_name,
            "episode_id": str(self.episode_record.get("tmdb_number") or ""),
            "date": self.air_date_edit.text(),
        }

        confirm = QMessageBox.question(
            self,
            "Confirm Embedding",
            "This will rewrite the video container to embed the metadata. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.embed_metadata(self.episode_path, metadata)
            self.accept()

    @Slot()
    def _on_merge_clicked(self) -> None:
        if not self._ext_subs:
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Merge",
            f"This will merge {len(self._ext_subs)} subtitle files into the video container. "
            "The original video file will be replaced. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.merge_subtitles(self.episode_path, self._ext_subs)
            self.accept()

    @Slot()
    def _on_search_osub_clicked(self) -> None:
        dialog = SubtitleSearchDialog(
            self.series_name,
            self.episode_record,
            self.controller,
            is_movie=False,
            parent=self,
        )
        if dialog.exec():
            self._refresh_file_info()


class MovieDetailsDialog(QDialog):
    """
    Comprehensive multi-tab interface for viewing/editing movie metadata
    and inspecting technical file characteristics.
    """

    def __init__(
        self,
        movie_name: str,
        movie_path: str,
        controller_instance: "Controller",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.movie_name: str = movie_name
        self.movie_path: str = movie_path
        self.controller: "Controller" = controller_instance
        self.movie_record: Dict[str, Any] = self.controller.cached_library_data.get(
            movie_name, {}
        )

        # UI Elements for Tab 1 (Metadata)
        self.title_edit: QLineEdit = QLineEdit()
        self.runtime_edit: QLineEdit = QLineEdit()
        self.year_edit: QLineEdit = QLineEdit()
        self.rating_edit: QLineEdit = QLineEdit()
        self.genre_edit: QLineEdit = QLineEdit()
        self.locked_checkbox: QCheckBox = QCheckBox(
            "Lock Metadata (Prevents automatic updates during scans)"
        )
        self.locked_checkbox.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self.locked_checkbox.setStyleSheet("color: #ff9800;")

        # UI Elements for Tab 2 (File Info)
        self.path_label: QLabel = QLabel()
        self.size_label: QLabel = QLabel()
        self.type_label: QLabel = QLabel()
        self.codec_label: QLabel = QLabel()
        self.resolution_label: QLabel = QLabel()
        self.audio_list: QListWidget = QListWidget()
        self.subtitle_list: QListWidget = QListWidget()
        self.external_sub_list: QListWidget = QListWidget()
        self.merge_button: QPushButton = QPushButton(
            "Combine Subtitles into Video File"
        )

        self.setWindowTitle(f"Movie Details: {Path(movie_path).name}")
        self.resize(700, 650)
        self._setup_ui()
        self._refresh_file_info()

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._create_metadata_tab(), "Metadata")
        tabs.addTab(self._create_file_info_tab(), "File Information")
        main_layout.addWidget(tabs)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        cancel_btn = QPushButton("Close")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save Changes")
        save_btn.setObjectName("accentButton")
        save_btn.clicked.connect(self._on_save_clicked)
        buttons_layout.addWidget(cancel_btn)
        buttons_layout.addWidget(save_btn)
        main_layout.addLayout(buttons_layout)

    def _create_metadata_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)

        form = QGridLayout()
        form.addWidget(QLabel("Title:"), 0, 0)
        form.addWidget(self.title_edit, 0, 1)

        form.addWidget(QLabel("Runtime (min):"), 1, 0)
        form.addWidget(self.runtime_edit, 1, 1)

        form.addWidget(QLabel("Release Year:"), 2, 0)
        form.addWidget(self.year_edit, 2, 1)

        form.addWidget(QLabel("Rating:"), 3, 0)
        form.addWidget(self.rating_edit, 3, 1)

        form.addWidget(QLabel("Genre:"), 4, 0)
        form.addWidget(self.genre_edit, 4, 1)

        layout.addLayout(form)
        layout.addWidget(self.locked_checkbox)

        search_btn = QPushButton("Search TMDB for this Movie...")
        search_btn.clicked.connect(self._on_search_tmdb_clicked)
        layout.addWidget(search_btn)

        refresh_btn = QPushButton("Refresh Movie Metadata")
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(refresh_btn)

        embed_btn = QPushButton("Embed Metadata into Video File")
        embed_btn.clicked.connect(self._on_embed_clicked)
        layout.addWidget(embed_btn)

        layout.addStretch()

        # Populate
        self.title_edit.setText(
            self.movie_record.get("tmdb_name") or self.movie_record.get("name") or ""
        )
        self.runtime_edit.setText(str(self.movie_record.get("runtime") or ""))
        self.year_edit.setText(str(self.movie_record.get("year") or ""))
        self.rating_edit.setText(self.movie_record.get("rating") or "")
        self.genre_edit.setText(self.movie_record.get("genre") or "")
        self.locked_checkbox.setChecked(
            bool(self.movie_record.get("locked_metadata", False))
        )

        return widget

    def _create_file_info_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Path:</b>"), 0, 0)
        self.path_label.setWordWrap(True)
        grid.addWidget(self.path_label, 0, 1)

        grid.addWidget(QLabel("<b>Size:</b>"), 1, 0)
        grid.addWidget(self.size_label, 1, 1)

        grid.addWidget(QLabel("<b>Type:</b>"), 2, 0)
        grid.addWidget(self.type_label, 2, 1)

        grid.addWidget(QLabel("<b>Codec:</b>"), 3, 0)
        grid.addWidget(self.codec_label, 3, 1)

        grid.addWidget(QLabel("<b>Resolution:</b>"), 4, 0)
        grid.addWidget(self.resolution_label, 4, 1)

        layout.addLayout(grid)

        layout.addWidget(QLabel("<b>Internal Audio Tracks:</b>"))
        self.audio_list.setMaximumHeight(100)
        layout.addWidget(self.audio_list)

        layout.addWidget(QLabel("<b>Internal Subtitle Tracks:</b>"))
        self.subtitle_list.setMaximumHeight(100)
        layout.addWidget(self.subtitle_list)

        layout.addWidget(QLabel("<b>Detected External Subtitles:</b>"))
        self.external_sub_list.setMaximumHeight(100)
        layout.addWidget(self.external_sub_list)

        self.merge_button.setObjectName("accentButton")
        self.merge_button.clicked.connect(self._on_merge_clicked)
        layout.addWidget(self.merge_button)

        osub_btn = QPushButton("Search OpenSubtitles.com for Subtitles...")
        osub_btn.clicked.connect(self._on_search_osub_clicked)
        layout.addWidget(osub_btn)

        layout.addStretch()

        return widget

    def _refresh_file_info(self) -> None:
        from lan_streamer.scanner import get_detailed_file_info, SUBTITLE_EXTENSIONS

        # Check if we have cached technical metadata in the movie record
        info: Dict[str, Any]
        has_db_info = bool(self.movie_record.get("video_codec"))
        if has_db_info:
            info = {
                "path": self.movie_path,
                "video_codec": self.movie_record.get("video_codec"),
                "resolution": self.movie_record.get("resolution") or "Unknown",
                "audio_tracks": self.movie_record.get("audio_tracks") or [],
                "subtitle_tracks": self.movie_record.get("subtitle_tracks") or [],
            }
            try:
                info["size_bytes"] = Path(self.movie_path).stat().st_size
            except Exception:
                info["size_bytes"] = 0
            info["video_type"] = Path(self.movie_path).suffix.upper().replace(".", "")
        else:
            info = get_detailed_file_info(self.movie_path)

        self.path_label.setText(self.movie_path)
        size_mb = info["size_bytes"] / (1024 * 1024)
        self.size_label.setText(f"{size_mb:.2f} MB")
        self.type_label.setText(info["video_type"])
        self.codec_label.setText(info.get("video_codec", "Unknown"))
        self.resolution_label.setText(info["resolution"])

        self.audio_list.clear()
        for track in info["audio_tracks"]:
            self.audio_list.addItem(
                f"Track {track['index']}: {track['codec']} ({track['language']}) {track['title']}"
            )

        self.subtitle_list.clear()
        for track in info["subtitle_tracks"]:
            self.subtitle_list.addItem(
                f"Track {track['index']}: {track['codec']} ({track['language']}) {track['title']}"
            )

        # Detect external subtitles
        self.external_sub_list.clear()
        ext_subs = []
        parent_dir = Path(self.movie_path).parent
        stem = Path(self.movie_path).stem
        if parent_dir.exists():
            for f in parent_dir.iterdir():
                if f.suffix.lower() in SUBTITLE_EXTENSIONS and f.stem.startswith(stem):
                    ext_subs.append(str(f.absolute()))
                    self.external_sub_list.addItem(f.name)

        self.merge_button.setEnabled(len(ext_subs) > 0)
        self._ext_subs = ext_subs

    @Slot()
    def _on_save_clicked(self) -> None:
        metadata = {
            "tmdb_name": self.title_edit.text(),
            "rating": self.rating_edit.text(),
            "genre": self.genre_edit.text(),
            "locked_metadata": self.locked_checkbox.isChecked(),
        }
        try:
            metadata["runtime"] = (
                int(self.runtime_edit.text()) if self.runtime_edit.text() else 0
            )
            metadata["year"] = (
                int(self.year_edit.text()) if self.year_edit.text() else 0
            )
        except ValueError:
            QMessageBox.warning(
                self, "Invalid Input", "Runtime and Year must be numbers."
            )
            return

        self.controller.update_movie_metadata(
            self.movie_name, self.movie_path, metadata
        )
        self.accept()

    @Slot()
    def _on_search_tmdb_clicked(self) -> None:
        # Trigger the existing EpisodeMatchDialog (which handles movies too)
        self.controller.episode_metadata_dialog_requested.emit(
            self.movie_name, self.movie_path
        )
        self.reject()

    @Slot()
    def _on_refresh_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Confirm Refresh",
            f"Are you sure you want to refresh metadata for '{self.movie_name}' from TMDB?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.trigger_series_refresh(self.movie_name)
            self.accept()

    @Slot()
    def _on_embed_clicked(self) -> None:
        """Collects current UI metadata and triggers embedding."""
        metadata = {
            "title": self.title_edit.text(),
            "date": self.year_edit.text(),
            "genre": self.genre_edit.text(),
        }

        confirm = QMessageBox.question(
            self,
            "Confirm Embedding",
            "This will rewrite the video container to embed the metadata. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.embed_metadata(self.movie_path, metadata)
            self.accept()

    @Slot()
    def _on_merge_clicked(self) -> None:
        if not self._ext_subs:
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Merge",
            f"This will merge {len(self._ext_subs)} subtitle files into the video container. "
            "The original video file will be replaced. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.merge_subtitles(self.movie_path, self._ext_subs)
            self.accept()

    @Slot()
    def _on_search_osub_clicked(self) -> None:
        dialog = SubtitleSearchDialog(
            self.movie_name,
            self.movie_record,
            self.controller,
            is_movie=True,
            parent=self,
        )
        if dialog.exec():
            self._refresh_file_info()


class SeriesDetailsDialog(QDialog):
    """
    Comprehensive dialog for managing series-level metadata and bulk actions.
    """

    def __init__(
        self,
        series_name: str,
        controller_instance: "Controller",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.controller: "Controller" = controller_instance
        self.series_record: Dict[str, Any] = self.controller.cached_library_data.get(
            series_name, {}
        )

        self.setWindowTitle(f"Series Details: {series_name}")
        self.resize(700, 550)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        form = QFormLayout()
        self.name_edit = QLineEdit(self.series_name)
        form.addRow("Series Name:", self.name_edit)

        # Paths
        paths = set()
        for season in self.series_record.get("seasons", {}).values():
            for ep in season.get("episodes", []):
                p = ep.get("path", "")
                if p:
                    # Attempt to find the series folder (2 levels up from episode file)
                    try:
                        paths.add(str(Path(p).parent.parent))
                    except Exception:
                        paths.add(str(Path(p).parent))

        paths_label = QLabel("\n".join(sorted(list(paths))))
        paths_label.setWordWrap(True)
        form.addRow("Series Path(s):", paths_label)

        # Jellyfin Status
        metadata = self.series_record.get("metadata", {})
        jellyfin_id = metadata.get("jellyfin_id", "")
        self.jellyfin_status_label = QLabel()
        self.jellyfin_status_label.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        if jellyfin_client.is_configured():
            if jellyfin_id:
                self.jellyfin_status_label.setText("Jellyfin Sync: Matched")
                self.jellyfin_status_label.setStyleSheet("color: #43a047;")
            else:
                self.jellyfin_status_label.setText("⚠️ Jellyfin Sync: Not Matched")
                self.jellyfin_status_label.setStyleSheet("color: #e53935;")
        else:
            self.jellyfin_status_label.setVisible(False)
        form.addRow("Sync Status:", self.jellyfin_status_label)

        self.locked_checkbox = QCheckBox(
            "Lock Metadata (Prevents automatic updates during scans)"
        )
        self.locked_checkbox.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self.locked_checkbox.setStyleSheet("color: #ff9800;")
        library_config = config.libraries.get(self.controller.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"
        if is_movie:
            is_locked = bool(self.series_record.get("locked_metadata", False))
        else:
            is_locked = bool(metadata.get("locked_metadata", False))
        self.locked_checkbox.setChecked(is_locked)
        form.addRow("Metadata Lock:", self.locked_checkbox)

        self.hide_missing_checkbox = QCheckBox("Hide missing/future episodes")
        self.hide_missing_checkbox.setObjectName("hideMissingCheckbox")
        self.hide_missing_checkbox.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        hide_missing_val = config.get_series_preference(
            self.controller.current_library_name,
            self.series_name,
            "hide_missing_future",
            False,
        )
        self.hide_missing_checkbox.setChecked(hide_missing_val)
        form.addRow("Episode View:", self.hide_missing_checkbox)

        layout.addLayout(form)

        # Buttons
        match_meta_btn = QPushButton("Match Series Metadata...")
        match_meta_btn.clicked.connect(self._on_match_meta_clicked)
        layout.addWidget(match_meta_btn)

        refresh_btn = QPushButton("Refresh Series Metadata")
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(refresh_btn)

        match_jellyfin_btn = QPushButton("Match Jellyfin Watch History...")
        match_jellyfin_btn.clicked.connect(self._on_match_jellyfin_clicked)
        if not jellyfin_client.is_configured():
            match_jellyfin_btn.setEnabled(False)
        layout.addWidget(match_jellyfin_btn)

        rename_btn = QPushButton("Rename Files...")
        rename_btn.clicked.connect(self._on_rename_clicked)
        layout.addWidget(rename_btn)

        embed_btn = QPushButton("Embed Metadata into All Video Files")
        embed_btn.setObjectName("accentButton")
        embed_btn.clicked.connect(self._on_embed_clicked)
        layout.addWidget(embed_btn)

        mark_watched_btn = QPushButton("Mark Series as Watched")
        mark_watched_btn.clicked.connect(self._on_mark_watched_clicked)
        layout.addWidget(mark_watched_btn)

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save_clicked)
        buttons.addWidget(close_btn)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

    def _on_match_meta_clicked(self) -> None:
        self.controller.metadata_dialog_requested.emit(self.series_name)
        self.accept()

    def _on_refresh_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Confirm Refresh",
            f"Are you sure you want to refresh metadata for '{self.series_name}' from TMDB?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.trigger_series_refresh(self.series_name)
            self.accept()

    def _on_match_jellyfin_clicked(self) -> None:
        self.controller.jellyfin_dialog_requested.emit(self.series_name)
        self.accept()

    def _on_rename_clicked(self) -> None:
        self.controller.rename_dialog_requested.emit(self.series_name)
        self.accept()

    def _on_embed_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Confirm Bulk Embedding",
            "This will rewrite the video containers for ALL episodes in this series. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.embed_metadata_series(self.series_name)
            self.accept()

    def _on_mark_watched_clicked(self) -> None:
        self.controller.mark_series_watched(self.series_name)
        self.accept()

    def _on_save_clicked(self) -> None:
        new_name = self.name_edit.text()
        locked = self.locked_checkbox.isChecked()
        hide_missing = self.hide_missing_checkbox.isChecked()
        config.set_series_preference(
            self.controller.current_library_name,
            self.series_name,
            "hide_missing_future",
            hide_missing,
        )
        if new_name != self.series_name:
            self.controller.update_series_name(self.series_name, new_name)
        self.controller.toggle_series_lock(
            new_name if new_name != self.series_name else self.series_name, locked
        )
        self.accept()
