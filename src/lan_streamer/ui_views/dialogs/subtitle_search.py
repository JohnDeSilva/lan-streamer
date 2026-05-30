from pathlib import Path
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QHeaderView,
)

from lan_streamer.ui_views.proxy import QMessageBox
from lan_streamer.providers.opensubtitles import opensubtitles_client

if TYPE_CHECKING:
    from lan_streamer.ui_views.controller import Controller


class SubtitleSearchDialog(QDialog):
    """
    Search and download subtitles from OpenSubtitles.com.
    """

    def __init__(
        self,
        media_name: str,
        media_record: Dict[str, Any],
        controller_instance: "Controller",
        is_movie: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.media_name = media_name
        self.media_record = media_record
        self.controller = controller_instance
        self.is_movie = is_movie
        self.results: List[Dict[str, Any]] = []

        self.setWindowTitle(f"Search Subtitles: {media_name}")
        self.resize(800, 500)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        self.query_edit = QLineEdit()

        if self.is_movie:
            tmdb_name = self.media_record.get("tmdb_name") or self.media_name
            year = self.media_record.get("year", "")
            default_query = f"{tmdb_name} {year}".strip()
        else:
            series_record = self.controller.cached_library_data.get(self.media_name, {})
            tmdb_name = (
                series_record.get("metadata", {}).get("tmdb_name") or self.media_name
            )
            season_num = self.media_record.get("season_number", 1)
            episode_num = self.media_record.get("tmdb_number", 1)
            default_query = f"{tmdb_name} S{season_num:02d}E{episode_num:02d}"

        self.query_edit.setText(default_query)
        search_layout.addWidget(QLabel("Query:"))
        search_layout.addWidget(self.query_edit)

        self.lang_edit = QLineEdit("en")
        self.lang_edit.setFixedWidth(50)
        search_layout.addWidget(QLabel("Languages:"))
        search_layout.addWidget(self.lang_edit)

        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._on_search_clicked)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)

        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(
            ["Language", "Filename", "Rating", "Downloads"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.results_table)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.download_btn = QPushButton("Download Selected")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._on_download_clicked)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        buttons.addWidget(self.download_btn)
        layout.addLayout(buttons)

        self.results_table.itemSelectionChanged.connect(
            lambda: self.download_btn.setEnabled(
                len(self.results_table.selectedItems()) > 0
            )
        )

    def _on_search_clicked(self) -> None:
        query = self.query_edit.text().strip()
        langs = self.lang_edit.text().strip()

        tmdb_id = None
        season_num = None
        episode_num = None

        if self.is_movie:
            tmdb_id_str = self.media_record.get("tmdb_id")
            tmdb_id = (
                int(tmdb_id_str) if tmdb_id_str and str(tmdb_id_str).isdigit() else None
            )
        else:
            series_record = self.controller.cached_library_data.get(self.media_name, {})
            tmdb_id_str = series_record.get("metadata", {}).get("tmdb_id")
            tmdb_id = (
                int(tmdb_id_str) if tmdb_id_str and str(tmdb_id_str).isdigit() else None
            )
            season_num = self.media_record.get("season_number")
            episode_num = self.media_record.get("tmdb_number")

        self.results = opensubtitles_client.search_subtitles(
            query=query if not tmdb_id else None,
            tmdb_id=tmdb_id,
            season_number=season_num,
            episode_number=episode_num,
            languages=langs,
        )

        self.results_table.setRowCount(0)
        for res in self.results:
            attr = res.get("attributes", {})
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)

            self.results_table.setItem(
                row, 0, QTableWidgetItem(attr.get("language", ""))
            )
            self.results_table.setItem(
                row, 1, QTableWidgetItem(attr.get("release", ""))
            )
            self.results_table.setItem(
                row, 2, QTableWidgetItem(str(attr.get("ratings", 0)))
            )
            self.results_table.setItem(
                row, 3, QTableWidgetItem(str(attr.get("download_count", 0)))
            )

        if not self.results:
            QMessageBox.information(self, "Search", "No subtitles found.")

    def _on_download_clicked(self) -> None:
        selected_row = self.results_table.currentRow()
        if selected_row < 0 or selected_row >= len(self.results):
            return

        subtitle_data = self.results[selected_row]
        file_id = (
            subtitle_data.get("attributes", {}).get("files", [{}])[0].get("file_id")
        )
        if not file_id:
            QMessageBox.warning(self, "Download", "No file ID found for this subtitle.")
            return

        download_url = opensubtitles_client.get_download_link(file_id)
        if not download_url:
            QMessageBox.warning(
                self,
                "Download",
                "Could not get download link. Check your credentials in Settings.",
            )
            return

        content = opensubtitles_client.download_subtitle(download_url)
        if not content:
            QMessageBox.warning(
                self, "Download", "Failed to download subtitle content."
            )
            return

        # Save next to video file
        video_path = Path(self.media_record.get("path", ""))
        if not video_path.exists():
            QMessageBox.warning(self, "Download", "Video file not found on disk.")
            return

        lang = subtitle_data.get("attributes", {}).get("language", "en")
        sub_path = video_path.with_suffix(f".{lang}.srt")

        try:
            with open(sub_path, "wb") as f:
                f.write(content)
            QMessageBox.information(self, "Download", f"Subtitle saved to:\n{sub_path}")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Download", f"Error saving subtitle: {e}")
