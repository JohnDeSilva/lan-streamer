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
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QHeaderView,
)
from PySide6.QtCore import QTimer, Slot, Qt
from PySide6.QtGui import QFont

from lan_streamer import db
from lan_streamer.backend import GenericSearchWorker
from lan_streamer.system.config import config
from lan_streamer.ui_views.proxy import (
    QMessageBox,
    jellyfin_client,
    tmdb_client,
    myanimelist_client,
)

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

        # MyAnimeList status for each season (only for anime libraries)
        self.mal_status_labels = {}
        library_config = config.libraries.get(self.controller.current_library_name, {})
        lib_type = library_config.get("type", "tv")
        if lib_type == "anime":
            seasons = self.series_record.get("seasons", {})
            sorted_season_names = sorted(seasons.keys(), key=db.natural_sort_key)
            for season_name in sorted_season_names:
                season_data = seasons[season_name]
                mal_id = season_data.get("metadata", {}).get("myanimelist_id")
                status_label = QLabel()
                status_label.setFont(QFont("Inter", 11, QFont.Weight.Bold))
                if mal_id:
                    status_label.setText(f"Mapped (MAL ID: {mal_id})")
                    status_label.setStyleSheet("color: #43a047;")
                else:
                    status_label.setText("Not Mapped")
                    status_label.setStyleSheet("color: #e53935;")
                self.mal_status_labels[season_name] = status_label
                info_form.addRow(f"{season_name} MAL Match:", status_label)

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

        # Mapper tab widget
        self.mapper_widget = QWidget()
        self._setup_mapper_ui()
        self.tab_widget.addTab(self.mapper_widget, "Manual Metadata Mapper")

        # MyAnimeList tab (only for anime libraries)
        library_config = config.libraries.get(self.controller.current_library_name, {})
        lib_type = library_config.get("type", "tv")
        if lib_type == "anime":
            self.mal_mapper_widget = QWidget()
            self._setup_mal_mapper_ui()
            self.tab_widget.addTab(self.mal_mapper_widget, "MyAnimeList Mapper")

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

    def _setup_mapper_ui(self) -> None:
        layout = QVBoxLayout(self.mapper_widget)
        layout.setSpacing(10)

        # Dropdowns layout
        combo_layout = QHBoxLayout()
        combo_layout.addWidget(QLabel("TMDB Group:"))
        self.group_combo = QComboBox()
        combo_layout.addWidget(self.group_combo)

        combo_layout.addWidget(QLabel("Subgroup (Arc/Season):"))
        self.subgroup_combo = QComboBox()
        combo_layout.addWidget(self.subgroup_combo)
        layout.addLayout(combo_layout)

        self.set_default_group_checkbox = QCheckBox(
            "Save selected TMDB Group as default group for future metadata updates"
        )
        layout.addWidget(self.set_default_group_checkbox)

        # Table
        self.mapper_table = QTableWidget()
        self.mapper_table.setColumnCount(3)
        self.mapper_table.setHorizontalHeaderLabels(
            ["TMDB Episode", "Air Date", "Mapped Local File"]
        )
        self.mapper_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.mapper_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.mapper_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.mapper_table.verticalHeader().setDefaultSectionSize(40)
        self.mapper_table.verticalHeader().setVisible(False)
        layout.addWidget(self.mapper_table)

        # Button to save
        self.apply_mapping_btn = QPushButton("Apply Manual Mappings")
        self.apply_mapping_btn.setObjectName("accentButton")
        self.apply_mapping_btn.clicked.connect(self._on_apply_mappings_clicked)
        layout.addWidget(self.apply_mapping_btn)

        # Defer TMDB data loading to after the dialog is visible
        QTimer.singleShot(0, self._deferred_load_mapper_data)

    def _deferred_load_mapper_data(self) -> None:
        # Collect local files (fast, no I/O)
        self.local_episodes = []
        for season in self.series_record.get("seasons", {}).values():
            for ep in season.get("episodes", []):
                if ep.get("path"):
                    self.local_episodes.append(ep)
        self.local_episodes.sort(
            key=lambda x: db.natural_sort_key(x.get("name") or Path(x["path"]).name)
        )

        # Populate group combo with static items immediately,
        # then fetch TMDB groups in background.
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem("Loading...", userData=None)
        self.group_combo.blockSignals(False)

        tmdb_id = self.series_record.get("metadata", {}).get("tmdb_identifier")
        saved_group_id = self.series_record.get("metadata", {}).get(
            "tmdb_episode_group_id"
        )
        self.set_default_group_checkbox.setChecked(bool(saved_group_id))

        if tmdb_id:
            self._fetch_episode_groups(tmdb_id, saved_group_id)
        else:
            self._populate_group_combo([], saved_group_id)

    def _fetch_episode_groups(
        self, tmdb_id: str, saved_group_id: Optional[str]
    ) -> None:
        """Fetch episode groups from TMDB in a background worker."""
        self._episode_groups_worker: Optional[GenericSearchWorker] = None

        worker = GenericSearchWorker(
            target=tmdb_client.get_episode_groups,
            args=(tmdb_id,),
            description="fetch episode groups",
            parent=self,
        )
        worker.finished.connect(
            lambda groups: self._populate_group_combo(groups or [], saved_group_id)
        )
        worker.error.connect(
            lambda msg: self._populate_group_combo([], saved_group_id, msg)
        )
        self._episode_groups_worker = worker
        worker.start()

    def _populate_group_combo(
        self,
        groups_list: list,
        saved_group_id: Optional[str],
        error_msg: Optional[str] = None,
    ) -> None:
        """Populate the group combo from fetched TMDB data."""
        self.groups_list = groups_list

        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem("Select Group...", userData=None)
        self.group_combo.addItem("Default TV Order", userData="default")
        selected_idx = 0
        if saved_group_id == "default" or (
            not saved_group_id
            and self.series_record.get("metadata", {}).get("tmdb_identifier")
        ):
            selected_idx = 1
        for idx, g in enumerate(groups_list):
            g_id = g.get("id")
            self.group_combo.addItem(
                str(g.get("name") or "Unknown Group"), userData=g_id
            )
            if saved_group_id and str(g_id) == str(saved_group_id):
                selected_idx = idx + 2

        self.group_combo.setCurrentIndex(selected_idx)
        self.group_combo.blockSignals(False)
        if selected_idx > 0:
            self._on_group_changed()

        # Connect signals
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        self.subgroup_combo.currentIndexChanged.connect(self._on_subgroup_changed)

    def _on_group_changed(self) -> None:
        self.subgroup_combo.blockSignals(True)
        self.subgroup_combo.clear()
        self.subgroup_combo.addItem("Loading...", userData=None)
        self.subgroup_combo.blockSignals(False)

        group_id = self.group_combo.currentData()
        group_name = self.group_combo.currentText()
        logger.info(
            f"SeriesDetailsDialog TMDB group changed to: '{group_name}' (ID: {group_id})"
        )

        if not group_id:
            self.set_default_group_checkbox.setChecked(False)
            self.set_default_group_checkbox.setEnabled(False)
            self.subgroup_combo.blockSignals(True)
            self.subgroup_combo.clear()
            self.subgroup_combo.addItem("Select Subgroup...", userData=None)
            self.subgroup_combo.blockSignals(False)
            return

        self.set_default_group_checkbox.setEnabled(True)

        if group_id == "default":
            tmdb_id = self.series_record.get("metadata", {}).get("tmdb_identifier")
            if tmdb_id:
                self._fetch_seasons(tmdb_id)
        else:
            self._fetch_group_details(group_id)

    def _fetch_seasons(self, tmdb_id: str) -> None:
        """Fetch seasons from TMDB in a background worker."""
        self._seasons_worker: Optional[GenericSearchWorker] = None
        worker = GenericSearchWorker(
            target=tmdb_client.get_seasons,
            args=(tmdb_id,),
            description="fetch seasons",
            parent=self,
        )
        worker.finished.connect(self._populate_seasons)
        worker.error.connect(lambda msg: self._populate_seasons([]))
        self._seasons_worker = worker
        worker.start()

    def _populate_seasons(self, seasons: list) -> None:
        self.subgroup_combo.blockSignals(True)
        self.subgroup_combo.clear()
        self.subgroup_combo.addItem("Select Subgroup...", userData=None)
        for season in seasons:
            season_number = season.get("season_number")
            if season_number is not None:
                self.subgroup_combo.addItem(
                    str(season.get("name") or f"Season {season_number}"),
                    userData={
                        "is_season": True,
                        "season_number": season_number,
                    },
                )
        self.subgroup_combo.blockSignals(False)
        self._on_subgroup_changed()

    def _fetch_group_details(self, group_id: str) -> None:
        """Fetch episode group details from TMDB in a background worker."""
        self._group_details_worker: Optional[GenericSearchWorker] = None
        worker = GenericSearchWorker(
            target=tmdb_client.get_episode_group_details,
            args=(group_id,),
            description="fetch group details",
            parent=self,
        )
        worker.finished.connect(self._populate_group_details)
        worker.error.connect(lambda msg: self._populate_group_details(None))
        self._group_details_worker = worker
        worker.start()

    def _populate_group_details(self, group_details: Optional[dict]) -> None:
        self.subgroup_combo.blockSignals(True)
        self.subgroup_combo.clear()
        self.subgroup_combo.addItem("Select Subgroup...", userData=None)
        if group_details and "groups" in group_details:
            for subgroup in group_details.get("groups", []):
                self.subgroup_combo.addItem(
                    str(subgroup.get("name") or "Unknown Subgroup"),
                    userData=subgroup,
                )
        self.subgroup_combo.blockSignals(False)
        self._on_subgroup_changed()

    def _on_subgroup_changed(self) -> None:
        self.mapper_table.setRowCount(0)
        subgroup_data = self.subgroup_combo.currentData()
        subgroup_name = self.subgroup_combo.currentText()
        logger.info(f"SeriesDetailsDialog subgroup changed to: '{subgroup_name}'")
        if not subgroup_data:
            return

        if isinstance(subgroup_data, dict) and subgroup_data.get("is_season"):
            season_number = subgroup_data.get("season_number")
            tmdb_id = self.series_record.get("metadata", {}).get("tmdb_identifier")
            if tmdb_id and season_number is not None:
                self._fetch_episodes(tmdb_id, season_number)
            return

        # Non-season subgroup data (from episode group) — populate directly
        episodes = (
            subgroup_data.get("episodes", []) if isinstance(subgroup_data, dict) else []
        )
        self._populate_mapper_episodes(episodes)

    def _fetch_episodes(self, tmdb_id: str, season_number: int) -> None:
        """Fetch episodes from TMDB in a background worker."""
        self._episodes_worker: Optional[GenericSearchWorker] = None
        worker = GenericSearchWorker(
            target=tmdb_client.get_episodes,
            args=(tmdb_id, season_number),
            description="fetch episodes",
            parent=self,
        )
        worker.finished.connect(self._populate_episodes)
        worker.error.connect(lambda msg: self._populate_episodes([]))
        self._episodes_worker = worker
        worker.start()

    def _populate_episodes(self, episodes_data: list) -> None:
        episodes = [
            {
                "id": ep.get("id"),
                "name": ep.get("name"),
                "episode_number": ep.get("episode_number"),
                "order": ep.get("episode_number", 1) - 1,
                "air_date": ep.get("air_date"),
                "runtime": ep.get("runtime"),
            }
            for ep in episodes_data
        ]
        self._populate_mapper_episodes(episodes)

    def _populate_mapper_episodes(self, episodes: list) -> None:
        self.mapper_table.setRowCount(len(episodes))
        self.row_group_episodes = episodes

        for row_idx, group_ep in enumerate(episodes):
            ep_order = group_ep.get("order", 0) + 1
            ep_title = group_ep.get("name") or "TBA"
            air_date = group_ep.get("air_date") or "Unknown"

            # Column 0: Name
            name_item = QTableWidgetItem(f"E{ep_order:02d} - {ep_title}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.mapper_table.setItem(row_idx, 0, name_item)

            # Column 1: Air Date
            date_item = QTableWidgetItem(air_date)
            date_item.setFlags(date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.mapper_table.setItem(row_idx, 1, date_item)

            # Column 2: ComboBox for local file
            combo = QComboBox()
            combo.addItem("Unmapped / None", userData=None)

            selected_idx = 0
            for idx, local_ep in enumerate(self.local_episodes):
                filename = Path(local_ep["path"]).name
                combo.addItem(filename, userData=local_ep["path"])

                # Check if this local ep is currently mapped to this TMDB episode ID
                cur_id = local_ep.get("tmdb_episode_identifier") or local_ep.get(
                    "tmdb_identifier"
                )
                if cur_id and str(cur_id) == str(group_ep.get("id")):
                    selected_idx = idx + 1

            combo.setCurrentIndex(selected_idx)
            self.mapper_table.setCellWidget(row_idx, 2, combo)

    def _on_apply_mappings_clicked(self) -> None:
        subgroup_data = self.subgroup_combo.currentData()
        if not subgroup_data:
            QMessageBox.warning(
                self, "No Subgroup Selected", "Please select a subgroup first."
            )
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Mapping",
            "Are you sure you want to apply these manual mappings? This will overwrite existing metadata for these files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        group_id = self.group_combo.currentData()
        group_name = self.group_combo.currentText()
        subgroup_name = self.subgroup_combo.currentText()
        logger.info(
            f"Manual Map: Applying mappings for series '{self.series_name}' using TMDB Group '{group_name}' (ID: {group_id}), Subgroup '{subgroup_name}'"
        )

        # Gather selections
        updates = {}
        for row_idx in range(self.mapper_table.rowCount()):
            combo = self.mapper_table.cellWidget(row_idx, 2)
            if isinstance(combo, QComboBox):
                selected_path = combo.currentData()
                if selected_path:
                    group_ep = self.row_group_episodes[row_idx]
                    ep_order = group_ep.get("order", 0) + 1
                    ep_name = group_ep.get("name", "")

                    logger.info(
                        f"Manual Map: Mapping file '{Path(selected_path).name}' to TMDB episode E{ep_order:02d} - '{ep_name}' (ID: {group_ep['id']})"
                    )

                    updates[selected_path] = {
                        "tmdb_identifier": str(group_ep["id"]),
                        "tmdb_episode_identifier": str(group_ep["id"]),
                        "tmdb_name": ep_name,
                        "tmdb_number": group_ep.get("episode_number")
                        or (group_ep.get("order", 0) + 1),
                        "air_date": group_ep.get("air_date") or "",
                        "runtime": group_ep.get("runtime") or 0,
                    }

        subgroup_ep_ids = {str(ep["id"]) for ep in self.row_group_episodes}

        # Apply in-place
        modified_count = 0
        for season_name, season_data in self.series_record.get("seasons", {}).items():
            for ep in season_data.get("episodes", []):
                p = ep.get("path")
                if p:
                    if p in updates:
                        for k, v in updates[p].items():
                            ep[k] = v
                        modified_count += 1
                    elif str(ep.get("tmdb_episode_identifier")) in subgroup_ep_ids:
                        old_id = ep.get("tmdb_episode_identifier")
                        logger.info(
                            f"Manual Map: Clearing mapping for file '{Path(p).name}' (was mapped to TMDB ID: {old_id})"
                        )
                        ep["tmdb_identifier"] = ""
                        ep["tmdb_episode_identifier"] = ""
                        ep["tmdb_name"] = ""
                        ep["tmdb_number"] = None
                        modified_count += 1

        # Save default group ID if checked
        saved_group_id = None
        if self.set_default_group_checkbox.isChecked():
            saved_group_id = self.group_combo.currentData()
            logger.info(
                f"Manual Map: Setting default group ID '{saved_group_id}' for series '{self.series_name}'"
            )
        else:
            logger.info(
                f"Manual Map: Default group ID not set or cleared for series '{self.series_name}'"
            )

        if "metadata" not in self.series_record:
            self.series_record["metadata"] = {}
        self.series_record["metadata"]["tmdb_episode_group_id"] = saved_group_id

        # Save once
        db.save_library(
            self.controller.current_library_name, self.controller.cached_library_data
        )
        self.controller.library_loaded.emit()
        self.controller.series_selected.emit(self.series_name)

        QMessageBox.information(
            self,
            "Success",
            f"Successfully applied manual mappings for {modified_count} episode file(s).",
        )

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

        saved_group_id = None
        if self.set_default_group_checkbox.isChecked():
            saved_group_id = self.group_combo.currentData()

        if "metadata" not in self.series_record:
            self.series_record["metadata"] = {}
        self.series_record["metadata"]["tmdb_episode_group_id"] = saved_group_id

        if new_name != self.series_name:
            self.controller.update_series_name(self.series_name, new_name)
        self.controller.toggle_series_lock(
            new_name if new_name != self.series_name else self.series_name, locked
        )

        db.save_library(
            self.controller.current_library_name, self.controller.cached_library_data
        )
        self.accept()

    def _setup_mal_mapper_ui(self) -> None:
        layout = QVBoxLayout(self.mal_mapper_widget)
        layout.setSpacing(10)

        # Local season selector
        season_layout = QHBoxLayout()
        season_layout.addWidget(QLabel("Local Season:"))
        self.mal_season_combo = QComboBox()
        for s_name in sorted(
            self.series_record.get("seasons", {}).keys(), key=db.natural_sort_key
        ):
            self.mal_season_combo.addItem(s_name)
        season_layout.addWidget(self.mal_season_combo)
        layout.addLayout(season_layout)

        # MAL Search Layout
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search MyAnimeList:"))
        self.mal_search_input = QLineEdit()
        self.mal_search_input.setText(self.series_name)
        search_layout.addWidget(self.mal_search_input)

        self.mal_search_btn = QPushButton("Search")
        self.mal_search_btn.clicked.connect(self._on_mal_search_clicked)
        search_layout.addWidget(self.mal_search_btn)
        layout.addLayout(search_layout)

        # Search Results
        results_layout = QHBoxLayout()
        results_layout.addWidget(QLabel("MAL Entry:"))
        self.mal_search_results_combo = QComboBox()
        self.mal_search_results_combo.addItem("Select MAL Entry...", userData=None)
        self.mal_search_results_combo.currentIndexChanged.connect(
            self._on_mal_entry_selected
        )
        results_layout.addWidget(self.mal_search_results_combo)
        layout.addLayout(results_layout)

        # Table
        self.mal_mapper_table = QTableWidget()
        self.mal_mapper_table.setColumnCount(2)
        self.mal_mapper_table.setHorizontalHeaderLabels(
            ["MAL Episode", "Mapped Local File"]
        )
        self.mal_mapper_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.mal_mapper_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.mal_mapper_table.verticalHeader().setDefaultSectionSize(40)
        self.mal_mapper_table.verticalHeader().setVisible(False)
        layout.addWidget(self.mal_mapper_table)

        # Apply Button
        self.mal_apply_btn = QPushButton("Apply MyAnimeList Mappings")
        self.mal_apply_btn.setObjectName("accentButton")
        self.mal_apply_btn.clicked.connect(self._on_mal_apply_mappings_clicked)
        layout.addWidget(self.mal_apply_btn)

        # Connect Season Change signal
        self.mal_season_combo.currentIndexChanged.connect(self._on_mal_season_changed)

        # Initialize
        self._on_mal_season_changed()

    @Slot(int)
    def _on_mal_season_changed(self) -> None:
        self.mal_local_episodes = []
        season_name = self.mal_season_combo.currentText()
        logger.info(f"SeriesDetailsDialog MAL season changed to: '{season_name}'")
        if not season_name:
            return

        season_data = self.series_record.get("seasons", {}).get(season_name, {})
        for ep in season_data.get("episodes", []):
            if ep.get("path"):
                self.mal_local_episodes.append(ep)

        self.mal_local_episodes.sort(
            key=lambda x: db.natural_sort_key(x.get("name") or Path(x["path"]).name)
        )

        saved_mal_id = season_data.get("metadata", {}).get("myanimelist_id")

        self.mal_search_results_combo.blockSignals(True)
        self.mal_search_results_combo.clear()
        self.mal_search_results_combo.addItem("Select MAL Entry...", userData=None)

        self.mal_mapper_table.setRowCount(0)

        if not myanimelist_client.is_configured():
            self.mal_search_results_combo.addItem(
                "MyAnimeList API Client ID not configured in settings", userData=None
            )
            self.mal_search_results_combo.blockSignals(False)
            return

        search_text = self.series_name
        if season_name and season_name.lower() not in ("season 1", "specials"):
            search_text += f" {season_name}"
        self.mal_search_input.setText(search_text)

        if saved_mal_id:
            details = myanimelist_client.get_anime_details(saved_mal_id)
            if details:
                title = details.get("title") or f"ID: {saved_mal_id}"
                self.mal_search_results_combo.addItem(title, userData=saved_mal_id)
                self.mal_search_results_combo.setCurrentIndex(1)
                self.mal_search_results_combo.blockSignals(False)
                self._populate_mal_episodes(details)
                return

        self.mal_search_results_combo.blockSignals(False)
        self._on_mal_search_clicked()

    @Slot()
    def _on_mal_search_clicked(self) -> None:
        query = self.mal_search_input.text().strip()
        logger.info(f"SeriesDetailsDialog MAL searching for: '{query}'")
        if not query:
            return

        try:
            results = myanimelist_client.search_anime(query)
        except Exception as e:
            logger.exception(f"Failed to search MyAnimeList: {e}")
            QMessageBox.warning(
                self,
                "Search Failed",
                f"Could not search MyAnimeList: {e}",
            )
            results = []

        self.mal_search_results_combo.blockSignals(True)
        self.mal_search_results_combo.clear()
        self.mal_search_results_combo.addItem("Select MAL Entry...", userData=None)

        for item in results:
            label = f"{item.get('title')} ({item.get('start_date', 'Unknown')}) - ID: {item.get('id')}"
            self.mal_search_results_combo.addItem(label, userData=item.get("id"))

        self.mal_search_results_combo.blockSignals(False)

    @Slot(int)
    def _on_mal_entry_selected(self) -> None:
        anime_id = self.mal_search_results_combo.currentData()
        self.mal_mapper_table.setRowCount(0)
        logger.info(f"SeriesDetailsDialog MAL entry selected ID: {anime_id}")
        if not anime_id:
            return

        try:
            details = myanimelist_client.get_anime_details(anime_id)
        except Exception as e:
            logger.exception(f"Failed to fetch MyAnimeList details: {e}")
            QMessageBox.warning(
                self,
                "Fetch Failed",
                f"Could not fetch MyAnimeList details: {e}",
            )
            details = None
        if details:
            self._populate_mal_episodes(details)

    def _populate_mal_episodes(self, details: Dict[str, Any]) -> None:
        num_episodes = details.get("num_episodes") or 0
        if num_episodes == 0:
            num_episodes = max(12, len(self.mal_local_episodes) + 5)

        self.mal_mapper_table.setRowCount(num_episodes)
        self.mal_row_episodes = list(range(1, num_episodes + 1))

        anime_id = details.get("id")

        for row_idx, mal_ep_num in enumerate(self.mal_row_episodes):
            ep_item = QTableWidgetItem(f"Episode {mal_ep_num}")
            ep_item.setFlags(ep_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.mal_mapper_table.setItem(row_idx, 0, ep_item)

            combo = QComboBox()
            combo.addItem("Unmapped / None", userData=None)

            selected_idx = 0
            for idx, local_ep in enumerate(self.mal_local_episodes):
                filename = Path(local_ep["path"]).name
                combo.addItem(filename, userData=local_ep["path"])

                cur_anime_id = local_ep.get("myanimelist_anime_id")
                cur_ep_num = local_ep.get("myanimelist_episode_number")
                if cur_anime_id == anime_id and cur_ep_num == mal_ep_num:
                    selected_idx = idx + 1

            if selected_idx == 0 and row_idx < len(self.mal_local_episodes):
                has_any_mapping = any(
                    ep.get("myanimelist_anime_id") == anime_id
                    for ep in self.mal_local_episodes
                )
                if not has_any_mapping:
                    selected_idx = row_idx + 1

            combo.setCurrentIndex(selected_idx)
            self.mal_mapper_table.setCellWidget(row_idx, 1, combo)

    @Slot()
    def _on_mal_apply_mappings_clicked(self) -> None:
        anime_id = self.mal_search_results_combo.currentData()
        season_name = self.mal_season_combo.currentText()
        if not season_name:
            return

        if not anime_id:
            QMessageBox.warning(
                self,
                "No MAL Entry Selected",
                "Please select a MyAnimeList entry first.",
            )
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Mapping",
            "Are you sure you want to apply these MyAnimeList mappings? This will link this season's episodes to this MAL entry.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        updates = {}
        for row_idx in range(self.mal_mapper_table.rowCount()):
            combo = self.mal_mapper_table.cellWidget(row_idx, 1)
            if isinstance(combo, QComboBox):
                selected_path = combo.currentData()
                if selected_path:
                    mal_ep_num = self.mal_row_episodes[row_idx]
                    updates[selected_path] = {
                        "myanimelist_anime_id": anime_id,
                        "myanimelist_episode_number": mal_ep_num,
                    }

        season_data = self.series_record.get("seasons", {}).get(season_name, {})
        if "metadata" not in season_data:
            season_data["metadata"] = {}
        season_data["metadata"]["myanimelist_id"] = anime_id

        # Update MAL status label in Series Info tab
        if hasattr(self, "mal_status_labels") and season_name in self.mal_status_labels:
            lbl = self.mal_status_labels[season_name]
            if anime_id:
                lbl.setText(f"Mapped (MAL ID: {anime_id})")
                lbl.setStyleSheet("color: #43a047;")
            else:
                lbl.setText("Not Mapped")
                lbl.setStyleSheet("color: #e53935;")

        modified_count = 0
        for ep in season_data.get("episodes", []):
            p = ep.get("path")
            if p:
                if p in updates:
                    ep["myanimelist_anime_id"] = updates[p]["myanimelist_anime_id"]
                    ep["myanimelist_episode_number"] = updates[p][
                        "myanimelist_episode_number"
                    ]
                    modified_count += 1
                else:
                    if ep.get("myanimelist_anime_id") == anime_id:
                        ep["myanimelist_anime_id"] = None
                        ep["myanimelist_episode_number"] = None
                        modified_count += 1

        db.save_library(
            self.controller.current_library_name, self.controller.cached_library_data
        )
        self.controller.library_loaded.emit()
        self.controller.series_selected.emit(self.series_name)

        QMessageBox.information(
            self,
            "Mappings Applied",
            f"Successfully applied MyAnimeList mappings to {modified_count} episodes.",
        )
        self._on_mal_season_changed()
