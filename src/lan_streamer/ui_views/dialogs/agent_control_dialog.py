"""Desktop dialog for configuring and controlling remote Scan Agents."""

from __future__ import annotations

import logging
from typing import Any

import requests
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lan_streamer.services.scan_agent_client import (
    ScanAgentConnectionError,
    scan_agent_client,
)

logger = logging.getLogger(__name__)

AGENT_CLIENT_EXCEPTIONS = (
    ScanAgentConnectionError,
    requests.RequestException,
    OSError,
    ValueError,
    KeyError,
    TypeError,
)


# ----------------------------------------------------------------------
# Background Workers for Non-Blocking HTTP Operations
# ----------------------------------------------------------------------


class AgentDataFetchWorker(QThread):
    """Fetches configuration, scan status, and libraries off the main UI thread."""

    fetch_completed = Signal(dict, dict, list)
    fetch_failed = Signal(str)

    def __init__(self, agent_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.agent_url = agent_url

    def run(self) -> None:
        try:
            configuration = scan_agent_client.fetch_agent_config(self.agent_url)
            status_data = scan_agent_client.fetch_scan_status(self.agent_url)
            libraries_list = scan_agent_client.fetch_agent_libraries(self.agent_url)
            if not self.isInterruptionRequested():
                self.fetch_completed.emit(configuration, status_data, libraries_list)
        except AGENT_CLIENT_EXCEPTIONS as error:
            logger.warning(
                "Failed fetching data from agent %s: %s", self.agent_url, error
            )
            if not self.isInterruptionRequested():
                self.fetch_failed.emit(str(error))


class AgentConfigSaveWorker(QThread):
    """Persists updated configuration to the remote scan agent off-thread."""

    save_completed = Signal(dict)
    save_failed = Signal(str)

    def __init__(
        self,
        agent_url: str,
        configuration_payload: dict[str, Any],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.agent_url = agent_url
        self.configuration_payload = configuration_payload

    def run(self) -> None:
        try:
            result = scan_agent_client.update_agent_config(
                self.agent_url, self.configuration_payload
            )
            if not self.isInterruptionRequested():
                self.save_completed.emit(result)
        except AGENT_CLIENT_EXCEPTIONS as error:
            logger.warning(
                "Failed saving config on agent %s: %s", self.agent_url, error
            )
            if not self.isInterruptionRequested():
                self.save_failed.emit(str(error))


class AgentScanTriggerWorker(QThread):
    """Triggers a scan on the remote agent off-thread."""

    trigger_completed = Signal(dict)
    trigger_failed = Signal(str)

    def __init__(
        self,
        agent_url: str,
        library_identifier: str | None,
        pass_number: int,
        force_refresh: bool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.agent_url = agent_url
        self.library_identifier = library_identifier
        self.pass_number = pass_number
        self.force_refresh = force_refresh

    def run(self) -> None:
        try:
            result = scan_agent_client.trigger_agent_scan(
                self.agent_url,
                library_identifier=self.library_identifier,
                pass_number=self.pass_number,
                force_refresh=self.force_refresh,
            )
            if not self.isInterruptionRequested():
                self.trigger_completed.emit(result)
        except AGENT_CLIENT_EXCEPTIONS as error:
            logger.warning(
                "Failed triggering scan on agent %s: %s", self.agent_url, error
            )
            if not self.isInterruptionRequested():
                self.trigger_failed.emit(str(error))


class AgentScanCancelWorker(QThread):
    """Cancels an active scan on the remote agent off-thread."""

    cancel_completed = Signal(dict)
    cancel_failed = Signal(str)

    def __init__(self, agent_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.agent_url = agent_url

    def run(self) -> None:
        try:
            result = scan_agent_client.cancel_agent_scan(self.agent_url)
            if not self.isInterruptionRequested():
                self.cancel_completed.emit(result)
        except AGENT_CLIENT_EXCEPTIONS as error:
            logger.warning(
                "Failed cancelling scan on agent %s: %s", self.agent_url, error
            )
            if not self.isInterruptionRequested():
                self.cancel_failed.emit(str(error))


class AgentLibraryCreateWorker(QThread):
    """Registers a new library on the agent off-thread."""

    create_completed = Signal(dict)
    create_failed = Signal(str)

    def __init__(
        self,
        agent_url: str,
        name: str,
        media_type: str,
        root_path: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.agent_url = agent_url
        self.name = name
        self.media_type = media_type
        self.root_path = root_path

    def run(self) -> None:
        try:
            result = scan_agent_client.create_agent_library(
                self.agent_url, self.name, self.media_type, self.root_path
            )
            if not self.isInterruptionRequested():
                self.create_completed.emit(result)
        except AGENT_CLIENT_EXCEPTIONS as error:
            logger.warning(
                "Failed creating library on agent %s: %s", self.agent_url, error
            )
            if not self.isInterruptionRequested():
                self.create_failed.emit(str(error))


class AgentLibraryDeleteWorker(QThread):
    """Deletes a library from the agent off-thread."""

    delete_completed = Signal(str)
    delete_failed = Signal(str)

    def __init__(
        self,
        agent_url: str,
        library_identifier: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.agent_url = agent_url
        self.library_identifier = library_identifier

    def run(self) -> None:
        try:
            scan_agent_client.delete_agent_library(
                self.agent_url, self.library_identifier
            )
            if not self.isInterruptionRequested():
                self.delete_completed.emit(self.library_identifier)
        except AGENT_CLIENT_EXCEPTIONS as error:
            logger.warning(
                "Failed deleting library from agent %s: %s", self.agent_url, error
            )
            if not self.isInterruptionRequested():
                self.delete_failed.emit(str(error))


# ----------------------------------------------------------------------
# Modal Dialog to Add a New Library on the Agent
# ----------------------------------------------------------------------


class AddRemoteLibraryDialog(QDialog):
    """Sub-dialog to define a new library directly on the remote agent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Library on Remote Agent")
        self.resize(440, 200)

        main_layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. TV Shows, Movies, Anime")
        form_layout.addRow("Library Name:", self.name_input)

        self.media_type_combobox = QComboBox()
        self.media_type_combobox.addItems(["tv", "movie", "anime"])
        form_layout.addRow("Media Type:", self.media_type_combobox)

        self.root_path_input = QLineEdit()
        self.root_path_input.setPlaceholderText("e.g. /media/tv or /data/movies")
        form_layout.addRow("Remote Root Path:", self.root_path_input)

        main_layout.addLayout(form_layout)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._validate_and_accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def _validate_and_accept(self) -> None:
        if not self.name_input.text().strip():
            QMessageBox.warning(
                self, "Validation Error", "Library name cannot be empty."
            )
            return
        if not self.root_path_input.text().strip():
            QMessageBox.warning(
                self, "Validation Error", "Remote root path cannot be empty."
            )
            return
        self.accept()

    def get_library_values(self) -> dict[str, str]:
        return {
            "name": self.name_input.text().strip(),
            "media_type": self.media_type_combobox.currentText().strip(),
            "root_path": self.root_path_input.text().strip(),
        }


# ----------------------------------------------------------------------
# Main Agent Control Dialog
# ----------------------------------------------------------------------


class AgentControlDialog(QDialog):
    """Dialog allowing users to control and configure all remote scan agent settings and actions."""

    def __init__(
        self,
        agent_url: str,
        controller: Any | None = None,
        parent: QWidget | None = None,
        auto_fetch: bool = True,
    ) -> None:
        super().__init__(parent)
        self.agent_url = agent_url
        self.controller = controller
        self.setWindowTitle(f"Remote Scan Agent — {agent_url}")
        self.resize(740, 600)

        self._active_workers: list[QThread] = []
        self._cached_libraries: list[dict[str, Any]] = []
        self._scan_triggered_during_session: bool = False

        self._init_ui()
        if auto_fetch:
            self.refresh_all_data()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # Header bar
        header_layout = QHBoxLayout()
        title_label = QLabel(f"<b>Agent URL:</b> {self.agent_url}")
        self.connection_status_label = QLabel("Connecting...")
        self.connection_status_label.setStyleSheet("color: #888888;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.connection_status_label)
        main_layout.addLayout(header_layout)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_configuration_tab(), "Configuration")
        self.tabs.addTab(self._build_scan_actions_tab(), "Scan Actions & Status")
        self.tabs.addTab(self._build_libraries_tab(), "Libraries Management")
        main_layout.addWidget(self.tabs, 1)

        # Bottom Close Button
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        bottom_layout.addWidget(close_button)
        main_layout.addLayout(bottom_layout)

    # ------------------------------------------------------------------
    # Tab 1: Configuration
    # ------------------------------------------------------------------

    def _build_configuration_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        form_layout = QFormLayout()

        self.tmdb_api_key_input = QLineEdit()
        self.tmdb_api_key_input.setPlaceholderText("Enter TMDB API Key")
        form_layout.addRow("TMDB API Key:", self.tmdb_api_key_input)

        self.scan_concurrency_spinbox = QSpinBox()
        self.scan_concurrency_spinbox.setRange(1, 32)
        self.scan_concurrency_spinbox.setValue(4)
        form_layout.addRow("Scan Concurrency (Threads):", self.scan_concurrency_spinbox)

        layout.addLayout(form_layout)

        # Scheduled Scans Group
        scheduled_group = QGroupBox("Automated Scheduled Scanning")
        scheduled_layout = QFormLayout(scheduled_group)

        self.scheduled_scans_enabled_checkbox = QCheckBox(
            "Enable Periodic Scheduled Scans"
        )
        self.scheduled_scans_enabled_checkbox.setChecked(True)
        scheduled_layout.addRow(self.scheduled_scans_enabled_checkbox)

        self.scheduled_scan_interval_spinbox = QSpinBox()
        self.scheduled_scan_interval_spinbox.setRange(1, 168)
        self.scheduled_scan_interval_spinbox.setValue(4)
        self.scheduled_scan_interval_spinbox.setSuffix(" hours")
        scheduled_layout.addRow("Scan Interval:", self.scheduled_scan_interval_spinbox)

        layout.addWidget(scheduled_group)

        # Filesystem Watcher Group
        watcher_group = QGroupBox("Real-Time Filesystem Watching")
        watcher_layout = QFormLayout(watcher_group)

        self.filesystem_watching_enabled_checkbox = QCheckBox(
            "Enable Real-Time Filesystem Event Watching"
        )
        self.filesystem_watching_enabled_checkbox.setChecked(True)
        watcher_layout.addRow(self.filesystem_watching_enabled_checkbox)

        self.filesystem_watching_debounce_spinbox = QSpinBox()
        self.filesystem_watching_debounce_spinbox.setRange(1, 3600)
        self.filesystem_watching_debounce_spinbox.setValue(30)
        self.filesystem_watching_debounce_spinbox.setSuffix(" seconds")
        watcher_layout.addRow(
            "Settle Debounce Window:", self.filesystem_watching_debounce_spinbox
        )

        layout.addWidget(watcher_group)

        # OpenSubtitles Group
        subtitles_group = QGroupBox("OpenSubtitles Integration")
        subtitles_layout = QFormLayout(subtitles_group)

        self.opensubtitles_username_input = QLineEdit()
        subtitles_layout.addRow("Username:", self.opensubtitles_username_input)

        self.opensubtitles_password_input = QLineEdit()
        self.opensubtitles_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.opensubtitles_password_input.setPlaceholderText(
            "Leave blank to keep unchanged"
        )
        password_layout = QHBoxLayout()
        password_layout.addWidget(self.opensubtitles_password_input, 1)
        self.clear_opensubtitles_password_checkbox = QCheckBox("Clear Password")
        self.clear_opensubtitles_password_checkbox.toggled.connect(
            self._on_clear_password_toggled
        )
        password_layout.addWidget(self.clear_opensubtitles_password_checkbox)
        subtitles_layout.addRow("Password:", password_layout)

        self.opensubtitles_api_key_input = QLineEdit()
        subtitles_layout.addRow("API Key (Optional):", self.opensubtitles_api_key_input)

        layout.addWidget(subtitles_group)

        # Logging Group
        logging_group = QGroupBox("Agent Logging & Storage")
        logging_layout = QFormLayout(logging_group)

        self.log_level_combobox = QComboBox()
        self.log_level_combobox.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combobox.setCurrentText("INFO")
        logging_layout.addRow("Log Level:", self.log_level_combobox)

        layout.addWidget(logging_group)

        # Action Buttons
        button_layout = QHBoxLayout()
        self.save_configuration_button = QPushButton("Save Configuration to Agent")
        self.save_configuration_button.clicked.connect(self.save_configuration)
        button_layout.addWidget(self.save_configuration_button)

        self.reload_configuration_button = QPushButton("Reload Configuration")
        self.reload_configuration_button.clicked.connect(self.refresh_all_data)
        button_layout.addWidget(self.reload_configuration_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)
        layout.addStretch()

        return widget

    # ------------------------------------------------------------------
    # Tab 2: Scan Actions & Status
    # ------------------------------------------------------------------

    def _build_scan_actions_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        # Status Display Group
        status_group = QGroupBox("Current Scan Activity")
        status_layout = QVBoxLayout(status_group)

        self.scan_state_label = QLabel("<b>Status:</b> Idle")
        status_layout.addWidget(self.scan_state_label)

        self.scan_job_details_label = QLabel("No active scan job.")
        self.scan_job_details_label.setWordWrap(True)
        status_layout.addWidget(self.scan_job_details_label)

        refresh_status_button = QPushButton("Refresh Status")
        refresh_status_button.clicked.connect(self.refresh_scan_status)
        status_layout.addWidget(refresh_status_button)

        layout.addWidget(status_group)

        # Scan Controls Group
        controls_group = QGroupBox("Trigger Scan on Agent")
        controls_layout = QFormLayout(controls_group)

        self.target_library_combobox = QComboBox()
        self.target_library_combobox.addItem("All Libraries", userData=None)
        controls_layout.addRow("Target Library:", self.target_library_combobox)

        self.scan_pass_combobox = QComboBox()
        self.scan_pass_combobox.addItem("Full Scan (Passes 1-3)", userData=0)
        self.scan_pass_combobox.addItem("Pass 1: File Discovery Only", userData=1)
        self.scan_pass_combobox.addItem("Pass 2: Metadata Resolution Only", userData=2)
        self.scan_pass_combobox.addItem("Pass 3: Technical Probing Only", userData=3)
        controls_layout.addRow("Scan Pass:", self.scan_pass_combobox)

        self.force_refresh_checkbox = QCheckBox(
            "Force refresh (ignore directory modification times)"
        )
        controls_layout.addRow(self.force_refresh_checkbox)

        buttons_layout = QHBoxLayout()
        self.start_scan_button = QPushButton("Start Scan on Agent")
        self.start_scan_button.clicked.connect(self.start_scan_on_agent)
        buttons_layout.addWidget(self.start_scan_button)

        self.cancel_scan_button = QPushButton("Cancel Active Scan")
        self.cancel_scan_button.clicked.connect(self.cancel_scan_on_agent)
        buttons_layout.addWidget(self.cancel_scan_button)

        controls_layout.addRow(buttons_layout)
        layout.addWidget(controls_group)
        layout.addStretch()

        return widget

    # ------------------------------------------------------------------
    # Tab 3: Libraries Management
    # ------------------------------------------------------------------

    def _build_libraries_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        self.libraries_table = QTableWidget()
        self.libraries_table.setColumnCount(4)
        self.libraries_table.setHorizontalHeaderLabels(
            ["Identifier", "Name", "Media Type", "Remote Root Path"]
        )
        if self.libraries_table.horizontalHeader() is not None:
            self.libraries_table.horizontalHeader().setSectionResizeMode(
                3, QHeaderView.ResizeMode.Stretch
            )
        layout.addWidget(self.libraries_table, 1)

        buttons_layout = QHBoxLayout()
        self.add_library_button = QPushButton("Add Library on Agent...")
        self.add_library_button.clicked.connect(self.prompt_add_library)
        buttons_layout.addWidget(self.add_library_button)

        self.delete_library_button = QPushButton("Delete Selected Library")
        self.delete_library_button.clicked.connect(self.delete_selected_library)
        buttons_layout.addWidget(self.delete_library_button)

        refresh_libraries_button = QPushButton("Refresh Libraries")
        refresh_libraries_button.clicked.connect(self.refresh_all_data)
        buttons_layout.addWidget(refresh_libraries_button)

        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)

        return widget

    # ------------------------------------------------------------------
    # Data Loading & Populating
    # ------------------------------------------------------------------

    @Slot()
    def refresh_all_data(self) -> None:
        """Fetch fresh configuration, status, and libraries from the agent."""
        self.connection_status_label.setText("Fetching data...")
        self.connection_status_label.setStyleSheet("color: #e6a23c;")

        worker = AgentDataFetchWorker(self.agent_url, parent=self)
        worker.fetch_completed.connect(self._on_data_fetch_completed)
        worker.fetch_failed.connect(self._on_data_fetch_failed)
        worker.finished.connect(lambda: self._remove_worker(worker))
        self._active_workers.append(worker)
        worker.start()

    def _on_data_fetch_completed(
        self,
        configuration: dict[str, Any],
        status_data: dict[str, Any],
        libraries_list: list[dict[str, Any]],
    ) -> None:
        self.connection_status_label.setText("Connected")
        self.connection_status_label.setStyleSheet("color: #67c23a; font-weight: bold;")

        # Populate Configuration
        self.tmdb_api_key_input.setText(configuration.get("tmdb_api_key") or "")
        self.scan_concurrency_spinbox.setValue(
            int(configuration.get("scan_concurrency") or 4)
        )
        self.scheduled_scans_enabled_checkbox.setChecked(
            bool(configuration.get("scheduled_scan_enabled", True))
        )
        self.scheduled_scan_interval_spinbox.setValue(
            int(configuration.get("scheduled_scan_interval_hours") or 4)
        )
        self.filesystem_watching_enabled_checkbox.setChecked(
            bool(configuration.get("filesystem_watching_enabled", True))
        )
        self.filesystem_watching_debounce_spinbox.setValue(
            int(configuration.get("filesystem_watching_debounce_seconds") or 30)
        )
        self.opensubtitles_username_input.setText(
            configuration.get("opensubtitles_username") or ""
        )
        self.opensubtitles_api_key_input.setText(
            configuration.get("opensubtitles_api_key") or ""
        )
        self.log_level_combobox.setCurrentText(configuration.get("log_level") or "INFO")

        # Populate Status
        self._update_status_display(status_data)

        # Populate Libraries
        self._cached_libraries = libraries_list
        self._populate_libraries_table(libraries_list)
        self._populate_target_library_combobox(libraries_list)

    def _on_data_fetch_failed(self, error_message: str) -> None:
        self.connection_status_label.setText("Connection Failed")
        self.connection_status_label.setStyleSheet("color: #f56c6c; font-weight: bold;")
        if self.isVisible():
            QMessageBox.warning(
                self,
                "Agent Connection Error",
                f"Could not load data from scan agent at:\n{self.agent_url}\n\nError: {error_message}",
            )

    def _update_status_display(self, status_data: dict[str, Any]) -> None:
        running_job = status_data.get("running")
        last_job = status_data.get("last_job")

        if running_job:
            job_id = running_job.get("id")
            pass_number = running_job.get("pass_number", 0)
            self.scan_state_label.setText(
                f"<b style='color: #409eff;'>Status: Active Scan (Job #{job_id})</b>"
            )
            self.scan_job_details_label.setText(
                f"Pass Number: {pass_number}\nStarted: {running_job.get('started_at', 'unknown')}"
            )
        else:
            self.scan_state_label.setText("<b style='color: #67c23a;'>Status: Idle</b>")
            if last_job:
                self.scan_job_details_label.setText(
                    f"Last Completed Job: #{last_job.get('id')} — "
                    f"Status: {last_job.get('status')}\n"
                    f"Finished: {last_job.get('finished_at', 'unknown')}"
                )
            else:
                self.scan_job_details_label.setText("No recent scan jobs.")

    def _populate_libraries_table(self, libraries_list: list[dict[str, Any]]) -> None:
        self.libraries_table.setRowCount(0)
        for library_entry in libraries_list:
            row_index = self.libraries_table.rowCount()
            self.libraries_table.insertRow(row_index)

            library_id = str(library_entry.get("id") or "")
            name = str(library_entry.get("name") or "")
            media_type = str(library_entry.get("media_type") or "")
            root_path = str(library_entry.get("root_path") or "")

            self.libraries_table.setItem(row_index, 0, QTableWidgetItem(library_id))
            self.libraries_table.setItem(row_index, 1, QTableWidgetItem(name))
            self.libraries_table.setItem(row_index, 2, QTableWidgetItem(media_type))
            self.libraries_table.setItem(row_index, 3, QTableWidgetItem(root_path))

    def _populate_target_library_combobox(
        self, libraries_list: list[dict[str, Any]]
    ) -> None:
        current_selection = self.target_library_combobox.currentData()
        self.target_library_combobox.clear()
        self.target_library_combobox.addItem("All Libraries", userData=None)

        for library_entry in libraries_list:
            library_id = str(library_entry.get("id") or "")
            name = str(library_entry.get("name") or library_id)
            self.target_library_combobox.addItem(name, userData=library_id)

        # Restore selection if still present
        if current_selection is not None:
            index = self.target_library_combobox.findData(current_selection)
            if index != -1:
                self.target_library_combobox.setCurrentIndex(index)

    # ------------------------------------------------------------------
    # Form configuration handlers
    # ------------------------------------------------------------------

    @Slot(bool)
    def _on_clear_password_toggled(self, checked: bool) -> None:
        self.opensubtitles_password_input.setEnabled(not checked)
        if checked:
            self.opensubtitles_password_input.clear()

    @Slot()
    def save_configuration(self) -> None:
        """Collect form values and send PUT /config to agent off-thread."""
        payload: dict[str, Any] = {
            "tmdb_api_key": self.tmdb_api_key_input.text().strip(),
            "scan_concurrency": self.scan_concurrency_spinbox.value(),
            "scheduled_scan_enabled": self.scheduled_scans_enabled_checkbox.isChecked(),
            "scheduled_scan_interval_hours": self.scheduled_scan_interval_spinbox.value(),
            "filesystem_watching_enabled": self.filesystem_watching_enabled_checkbox.isChecked(),
            "filesystem_watching_debounce_seconds": self.filesystem_watching_debounce_spinbox.value(),
            "opensubtitles_username": self.opensubtitles_username_input.text().strip(),
            "opensubtitles_api_key": self.opensubtitles_api_key_input.text().strip(),
            "log_level": self.log_level_combobox.currentText(),
        }

        if self.clear_opensubtitles_password_checkbox.isChecked():
            payload["clear_opensubtitles_password"] = True
        else:
            password = self.opensubtitles_password_input.text()
            if password:
                payload["opensubtitles_password"] = password

        self.save_configuration_button.setEnabled(False)
        worker = AgentConfigSaveWorker(self.agent_url, payload, parent=self)
        worker.save_completed.connect(self._on_config_save_completed)
        worker.save_failed.connect(self._on_config_save_failed)
        worker.finished.connect(lambda: self._remove_worker(worker))
        self._active_workers.append(worker)
        worker.start()

    def _on_config_save_completed(self, result: dict[str, Any]) -> None:
        self.save_configuration_button.setEnabled(True)
        self.clear_opensubtitles_password_checkbox.setChecked(False)
        self.opensubtitles_password_input.setEnabled(True)
        self.opensubtitles_password_input.clear()
        QMessageBox.information(
            self, "Configuration Saved", "Agent configuration updated successfully."
        )

    def _on_config_save_failed(self, error_message: str) -> None:
        self.save_configuration_button.setEnabled(True)
        QMessageBox.warning(
            self,
            "Save Failed",
            f"Failed to update agent configuration:\n{error_message}",
        )

    # ------------------------------------------------------------------
    # Scan management handlers
    # ------------------------------------------------------------------

    @Slot()
    def refresh_scan_status(self) -> None:
        """Query agent scan status and update status label."""
        try:
            status_data = scan_agent_client.fetch_scan_status(self.agent_url)
            self._update_status_display(status_data)
        except AGENT_CLIENT_EXCEPTIONS as error:
            logger.warning("Could not refresh scan status: %s", error)

    @Slot()
    def start_scan_on_agent(self) -> None:
        """Trigger scan on the remote agent."""
        target_library_id = self.target_library_combobox.currentData()
        pass_number = self.scan_pass_combobox.currentData() or 0
        force_refresh = self.force_refresh_checkbox.isChecked()

        self.start_scan_button.setEnabled(False)
        worker = AgentScanTriggerWorker(
            self.agent_url,
            target_library_id,
            pass_number,
            force_refresh,
            parent=self,
        )
        worker.trigger_completed.connect(self._on_scan_trigger_completed)
        worker.trigger_failed.connect(self._on_scan_trigger_failed)
        worker.finished.connect(lambda: self._remove_worker(worker))
        self._active_workers.append(worker)
        worker.start()

    def _on_scan_trigger_completed(self, result: dict[str, Any]) -> None:
        self.start_scan_button.setEnabled(True)
        self._scan_triggered_during_session = True
        job_id = result.get("id")
        QMessageBox.information(
            self, "Scan Started", f"Scan Job #{job_id} initiated on agent."
        )
        self.refresh_scan_status()

    def _on_scan_trigger_failed(self, error_message: str) -> None:
        self.start_scan_button.setEnabled(True)
        QMessageBox.warning(
            self,
            "Scan Trigger Failed",
            f"Could not initiate scan on agent:\n{error_message}",
        )

    @Slot()
    def cancel_scan_on_agent(self) -> None:
        """Request scan cancellation on the agent."""
        self.cancel_scan_button.setEnabled(False)
        worker = AgentScanCancelWorker(self.agent_url, parent=self)
        worker.cancel_completed.connect(self._on_scan_cancel_completed)
        worker.cancel_failed.connect(self._on_scan_cancel_failed)
        worker.finished.connect(lambda: self._remove_worker(worker))
        self._active_workers.append(worker)
        worker.start()

    def _on_scan_cancel_completed(self, result: dict[str, Any]) -> None:
        self.cancel_scan_button.setEnabled(True)
        QMessageBox.information(
            self, "Scan Cancelled", "Scan cancellation requested on agent."
        )
        self.refresh_scan_status()

    def _on_scan_cancel_failed(self, error_message: str) -> None:
        self.cancel_scan_button.setEnabled(True)
        QMessageBox.warning(
            self, "Cancel Failed", f"Could not cancel scan on agent:\n{error_message}"
        )

    # ------------------------------------------------------------------
    # Library management handlers
    # ------------------------------------------------------------------

    @Slot()
    def prompt_add_library(self) -> None:
        dialog = AddRemoteLibraryDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.get_library_values()
            worker = AgentLibraryCreateWorker(
                self.agent_url,
                values["name"],
                values["media_type"],
                values["root_path"],
                parent=self,
            )
            worker.create_completed.connect(self._on_library_created)
            worker.create_failed.connect(self._on_library_action_failed)
            worker.finished.connect(lambda: self._remove_worker(worker))
            self._active_workers.append(worker)
            worker.start()

    def _on_library_created(self, result: dict[str, Any]) -> None:
        QMessageBox.information(
            self, "Library Added", f"Library '{result.get('name')}' created on agent."
        )
        self.refresh_all_data()

    @Slot()
    def delete_selected_library(self) -> None:
        selected_row = self.libraries_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(
                self, "No Selection", "Please select a library to delete."
            )
            return

        library_id_item = self.libraries_table.item(selected_row, 0)
        library_name_item = self.libraries_table.item(selected_row, 1)
        if not library_id_item:
            return

        library_id = library_id_item.text()
        library_name = library_name_item.text() if library_name_item else library_id

        confirmation = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete remote library '{library_name}' ({library_id}) from the agent?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return

        worker = AgentLibraryDeleteWorker(self.agent_url, library_id, parent=self)
        worker.delete_completed.connect(self._on_library_deleted)
        worker.delete_failed.connect(self._on_library_action_failed)
        worker.finished.connect(lambda: self._remove_worker(worker))
        self._active_workers.append(worker)
        worker.start()

    def _on_library_deleted(self, library_id: str) -> None:
        QMessageBox.information(
            self,
            "Library Deleted",
            f"Library '{library_id}' was removed from the agent.",
        )
        self.refresh_all_data()

    def _on_library_action_failed(self, error_message: str) -> None:
        QMessageBox.warning(
            self, "Library Operation Failed", f"Operation failed:\n{error_message}"
        )

    def _remove_worker(self, worker: QThread) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        worker.deleteLater()

    def _queue_matching_remote_syncs(self) -> None:
        """Trigger background remote sync on desktop for libraries hosted by this agent."""
        if self.controller is None or not hasattr(self.controller, "_config"):
            return
        configured_libraries = getattr(self.controller._config, "libraries", {})
        for library_name, library_data in configured_libraries.items():
            if not isinstance(library_data, dict):
                continue
            if library_data.get("management_type") == "remote":
                remote_url = str(library_data.get("agent_url", "")).rstrip("/")
                if remote_url == self.agent_url and hasattr(
                    self.controller, "_queue_remote_sync"
                ):
                    logger.info(
                        "Triggering desktop remote sync for '%s' following agent scan",
                        library_name,
                    )
                    self.controller._queue_remote_sync(library_name)

    def closeEvent(self, event: Any) -> None:
        """Interrupt active background workers and trigger remote sync when dialog closes."""
        for worker in list(self._active_workers):
            worker.requestInterruption()
            worker.wait(500)
        if self._scan_triggered_during_session:
            self._queue_matching_remote_syncs()
        super().closeEvent(event)
