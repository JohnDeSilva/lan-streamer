import logging
from pathlib import Path
from typing import Dict, Any, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QLineEdit,
    QCheckBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QTabWidget,
)
from PySide6.QtGui import QFont

from lan_streamer import db
from lan_streamer.system.config import config
from lan_streamer.ui_views.proxy import QMessageBox, jellyfin_client

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from lan_streamer.ui_views.controller import Controller


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
        logger.info(f"Initializing SeriesDetailsDialog for series '{series_name}'")
        self.series_name: str = series_name
        self.controller: "Controller" = controller_instance
        self.series_record: Dict[str, Any] = self.controller.cached_library_data.get(
            series_name, {}
        )

        self.setWindowTitle(f"Series Details: {series_name}")
        self.resize(900, 650)
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # Tab widget
        self.tab_widget = QTabWidget(self)

        # Series Info tab widget
        info_tab = QWidget()
        info_layout = QVBoxLayout(info_tab)
        info_layout.setSpacing(15)

        info_form = QFormLayout()
        self.name_edit = QLineEdit(self.series_name)
        info_form.addRow("Series Name:", self.name_edit)

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
        info_form.addRow("Series Path(s):", paths_label)

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
        info_form.addRow("Sync Status:", self.jellyfin_status_label)

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
        # hide_missing preference is saved in _on_save_clicked, so no per-toggle
        # config write needed here to avoid blocking the UI thread.
        info_form.addRow("Episode View:", self.hide_missing_checkbox)

        info_layout.addLayout(info_form)

        # Buttons on Info Tab
        scan_series_btn = QPushButton("Scan Series")
        scan_series_btn.clicked.connect(self._on_scan_series_clicked)
        info_layout.addWidget(scan_series_btn)

        mark_watched_btn = QPushButton("Mark Series as Watched")
        mark_watched_btn.clicked.connect(self._on_mark_watched_clicked)
        info_layout.addWidget(mark_watched_btn)

        remove_series_btn = QPushButton("Remove Series...")
        remove_series_btn.setObjectName("dangerButton")
        remove_series_btn.clicked.connect(self._on_remove_series_clicked)
        info_layout.addWidget(remove_series_btn)

        info_layout.addStretch()

        self.tab_widget.addTab(info_tab, "Series Info")

        # Series Metadata tab widget
        metadata_tab = QWidget()
        metadata_layout = QVBoxLayout(metadata_tab)
        metadata_layout.setSpacing(15)

        metadata_form = QFormLayout()
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
        metadata_form.addRow("Metadata Lock:", self.locked_checkbox)

        metadata_layout.addLayout(metadata_form)

        # Buttons on Metadata Tab
        match_meta_btn = QPushButton("Match Series Metadata...")
        match_meta_btn.clicked.connect(self._on_match_meta_clicked)
        metadata_layout.addWidget(match_meta_btn)

        refresh_btn = QPushButton("Refresh Series Metadata")
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        metadata_layout.addWidget(refresh_btn)

        match_jellyfin_btn = QPushButton("Match Jellyfin Watch History...")
        match_jellyfin_btn.clicked.connect(self._on_match_jellyfin_clicked)
        if not jellyfin_client.is_configured():
            match_jellyfin_btn.setEnabled(False)
        metadata_layout.addWidget(match_jellyfin_btn)

        rename_btn = QPushButton("Rename Files...")
        rename_btn.clicked.connect(self._on_rename_clicked)
        metadata_layout.addWidget(rename_btn)

        embed_btn = QPushButton("Embed Metadata into All Video Files")
        embed_btn.setObjectName("accentButton")
        embed_btn.clicked.connect(self._on_embed_clicked)
        metadata_layout.addWidget(embed_btn)

        metadata_layout.addStretch()

        self.tab_widget.addTab(metadata_tab, "Series Metadata")

        main_layout.addWidget(self.tab_widget)

        # Bottom Close/Save buttons
        buttons = QHBoxLayout()
        buttons.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save_clicked)
        buttons.addWidget(close_btn)
        buttons.addWidget(save_btn)
        main_layout.addLayout(buttons)

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
        if not jellyfin_client.is_configured():
            QMessageBox.information(
                self,
                "Jellyfin Sync",
                "Jellyfin is not configured. Please configure it in Settings first.",
            )
            return
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

    def _on_scan_series_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Confirm Scan",
            f"Are you sure you want to scan all folders for '{self.series_name}'? This will check for new/modified files, disregarding cached modification times.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.trigger_series_scan(self.series_name)
            self.accept()

    def _on_mark_watched_clicked(self) -> None:
        self.controller.mark_series_watched(self.series_name)
        self.accept()

    def _on_remove_series_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Remove Series",
            f"Are you sure you want to remove the series '{self.series_name}' from the library database? This is a nondestructive operation that only affects the database, and files will be picked up on the next scan.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.delete_series(self.series_name)
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

        db.save_library(
            self.controller.current_library_name, self.controller.cached_library_data
        )
        self.accept()
