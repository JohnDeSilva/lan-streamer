import contextlib
import copy
import html
import logging
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent, QFont, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lan_streamer import __version__
from lan_streamer.system.config import config, split_multi_root_libraries
from lan_streamer.system.updater import UpdateCheckWorker
from lan_streamer.ui_views.dialogs.update_dialog import UpdateDialog
from lan_streamer.ui_views.progress_widgets import (
    ScanProgressTree,
    SegmentedProgressBar,
)
from lan_streamer.ui_views.proxy import QFileDialog, QMessageBox

if TYPE_CHECKING:
    from lan_streamer.ui_views.controller import Controller

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """
    Configuration modal encapsulating system directory management and operational behaviors.
    """

    def __init__(
        self,
        controller_instance: Controller | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        logger.info("Initializing SettingsDialog")
        self.controller: Controller | None = controller_instance
        self.setWindowTitle("Application Configuration")
        self.resize(800, 700)

        self._init_scanning_widgets()
        self._init_integration_widgets()
        self._init_library_widgets()
        self._init_tab_widgets()
        self._init_remote_agent_widgets()
        self._init_playback_widgets()
        self._init_system_widgets()
        self._init_combined_view_widgets()

        self._setup_ui()
        self._load_config()

    def _init_tab_widgets(self) -> None:
        self.staged_tabs: list[dict[str, Any]] = []
        self.tabs_list_widget: QListWidget = QListWidget()
        self.tab_libraries_list_widget: QListWidget = QListWidget()
        self.add_tab_button: QPushButton = QPushButton("Add Tab")
        self.rename_tab_button: QPushButton = QPushButton("Rename Tab")
        self.remove_tab_button: QPushButton = QPushButton("Remove Tab")
        self.move_tab_up_button: QPushButton = QPushButton("Move Up")
        self.move_tab_down_button: QPushButton = QPushButton("Move Down")

    def _init_library_widgets(self) -> None:
        self.staged_libraries: dict[str, dict[str, Any]] = {}
        self.staged_scan_agents: dict[str, dict[str, Any]] = {}
        self.library_name_input: QLineEdit = QLineEdit()
        self.library_type_input: QComboBox = QComboBox()
        self.library_management_type_input: QComboBox = QComboBox()
        self.library_selector: QComboBox = QComboBox()
        self.local_library_scan_button: QPushButton = QPushButton("Scan Library")
        self.remote_library_scan_button: QPushButton = QPushButton(
            "Sync / Scan Library"
        )
        self.scan_target_library_combobox: QComboBox = QComboBox()
        self.library_management_mode_label: QLabel = QLabel("Management: Local")
        self.show_future_episodes_checkbox: QCheckBox = QCheckBox()
        self.anime_library_checkbox: QCheckBox = QCheckBox()
        self.directory_list_label: QLabel = QLabel("Root Directory:")
        self.directory_list_widget: QListWidget = QListWidget()
        self.library_order_list_widget: QListWidget = QListWidget()

    def _init_scanning_widgets(self) -> None:
        self.auto_scan_checkbox: QCheckBox = QCheckBox(
            "Enable automatic background scanning"
        )
        self.scan_interval_spinbox: QSpinBox = QSpinBox()
        self.scan_interval_spinbox.setRange(1, 168)
        self.scan_interval_spinbox.setSuffix(" hours")
        self.scan_concurrency_spinbox: QSpinBox = QSpinBox()
        self.scan_concurrency_spinbox.setRange(1, 16)
        self.scan_concurrency_spinbox.setSuffix(" threads")
        self.scan_concurrency_spinbox.setToolTip(
            "Number of concurrent worker threads used during library scanning.\n\n"
            "• Too high (8+): Causes severe mechanical hard drive thrashing and saturates network share (SMB/NFS) queues, leading to timeouts.\n"
            "• Too low (1): Significantly increases scan duration by processing everything sequentially.\n"
            "• Recommended: 2-4 threads for network drives (NAS/SMB/NFS) and mechanical HDDs; 4-8 threads for fast local SSDs."
        )
        self.scan_concurrency_warning_label: QLabel = QLabel(
            "⚠️ Concurrency Advice: Setting too high (8+) can cause severe mechanical HDD thrashing "
            "and saturate network share (SMB/NFS) request queues. Setting too low (1) results in slower sequential scans. "
            "2-4 threads recommended for network drives/HDDs; 4-8 threads for fast local SSDs."
        )
        self.scan_concurrency_warning_label.setWordWrap(True)
        self.scan_concurrency_warning_label.setStyleSheet(
            "font-size: 11px; color: #94a3b8; border: none; padding-top: 2px;"
        )

        self.force_refresh_checkbox: QCheckBox = QCheckBox(
            "Force refresh metadata (update/search TMDB)"
        )
        self.global_progress_bar: SegmentedProgressBar = SegmentedProgressBar()
        self.global_progress_bar.setVisible(False)
        self.scan_progress_tree: ScanProgressTree = ScanProgressTree()
        self.scan_progress_tree.setVisible(False)
        self.scan_report_display: QTextEdit = QTextEdit()
        self.scan_report_display.setReadOnly(True)
        self.scan_report_display.setFont(QFont("Courier New", 10))
        self.scan_report_display.setVisible(False)
        self._scan_running: bool = False
        self.current_scan_logs: list[str] = []

        if self.controller is not None:
            self.controller.global_progress_updated.connect(self._on_global_progress)
            self.controller.detail_progress_updated.connect(self._on_detail_progress)
            self.controller.scan_completed.connect(self._on_scan_completed)

    def _init_integration_widgets(self) -> None:
        self.jellyfin_url_input: QLineEdit = QLineEdit()
        self.jellyfin_key_input: QLineEdit = QLineEdit()
        self.sync_history_on_start_checkbox: QCheckBox = QCheckBox(
            "Sync watch history from Jellyfin on startup"
        )
        self.check_updates_startup_checkbox: QCheckBox = QCheckBox(
            "Automatically check for updates on startup"
        )
        self.update_release_channel_selector: QComboBox = QComboBox()
        self.update_release_channel_selector.addItems(
            ["Main Releases", "Release Candidates"]
        )
        self.tmdb_key_input: QLineEdit = QLineEdit()
        self.opensubtitles_username_input: QLineEdit = QLineEdit()
        self.opensubtitles_password_input: QLineEdit = QLineEdit()
        self.opensubtitles_api_key_input: QLineEdit = QLineEdit()

    def _init_remote_agent_widgets(self) -> None:
        # Dedicated Remote Libraries Setup widgets
        self.remote_agent_url_input: QLineEdit = QLineEdit()
        self.connect_agent_button: QPushButton = QPushButton("Connect to Agent")
        self.remote_agents_tree_widget: QTreeWidget = QTreeWidget()
        self.map_local_mount_button: QPushButton = QPushButton("Map Local Mount...")
        self.remove_remote_agent_button: QPushButton = QPushButton("Remove Agent")
        self.refresh_remote_agents_button: QPushButton = QPushButton("Refresh Agents")

        # Scan Agents widgets (backward compatibility aliases)
        self.scan_agent_name_input: QLineEdit = QLineEdit()
        self.scan_agent_url_input: QLineEdit = self.remote_agent_url_input
        self.scan_agent_selector: QComboBox = QComboBox()
        self.scan_agent_status_label: QLabel = QLabel("Status: Ready")

        # Remote library legacy mapping widgets
        self.remote_agent_selector: QComboBox = QComboBox()
        self.remote_library_selector: QComboBox = QComboBox()
        self.remote_root_path_label: QLabel = QLabel("Remote Path: None")
        self.remote_library_container: QWidget = QWidget()

    def _init_playback_widgets(self) -> None:
        self.use_embedded_checkbox: QCheckBox = QCheckBox(
            "Use Embedded Video Player (uncheck for Standalone VLC)"
        )
        self.enable_caching_checkbox: QCheckBox = QCheckBox(
            "Copy Files to local Cache before Streaming"
        )
        self.enable_hw_accel_checkbox: QCheckBox = QCheckBox(
            "Enable Hardware Acceleration Decoding"
        )
        self.enable_next_episode_popup_checkbox: QCheckBox = QCheckBox(
            "Enable Next Episode Autoplay Popup"
        )
        self.watched_threshold_input: QLineEdit = QLineEdit()
        self.max_cache_size_input: QLineEdit = QLineEdit()
        self.vlc_buffer_input: QLineEdit = QLineEdit()
        self.fullscreen_control_bar_position_selector: QComboBox = QComboBox()
        self.subtitle_position_selector: QComboBox = QComboBox()
        self.default_aspect_mode_selector: QComboBox = QComboBox()

    def _init_system_widgets(self) -> None:
        self.db_path_input: QLineEdit = QLineEdit()
        self.log_dir_input: QLineEdit = QLineEdit()
        self.log_retention_input: QLineEdit = QLineEdit()
        self.log_saving_mode_selector: QComboBox = QComboBox()
        self.log_level_selector: QComboBox = QComboBox()

        self.backup_directory_input: QLineEdit = QLineEdit()
        self.config_backup_frequency_input: QLineEdit = QLineEdit()
        self.database_backup_frequency_input: QLineEdit = QLineEdit()
        self.config_backup_retention_input: QLineEdit = QLineEdit()
        self.database_backup_retention_input: QLineEdit = QLineEdit()

        self.log_level_filter: QComboBox = QComboBox()
        self.log_search_input: QLineEdit = QLineEdit()
        self.log_autoscroll_checkbox: QCheckBox = QCheckBox()
        self.log_display: QPlainTextEdit = QPlainTextEdit()
        self.all_log_records: list[tuple[str, str]] = []
        self._logging_connected: bool = False

    def _init_combined_view_widgets(self) -> None:
        self.staged_combined_views: list[dict[str, Any]] = []
        self.enable_combined_view_checkbox: QCheckBox = QCheckBox(
            "Enable Combined Library View"
        )
        self.combined_views_list_widget: QListWidget = QListWidget()
        self.row_properties_group: QGroupBox = QGroupBox("Row Properties")
        self.row_name_input: QLineEdit = QLineEdit()
        self.row_enabled_checkbox: QCheckBox = QCheckBox("Enabled")
        self.row_sort_selector: QComboBox = QComboBox()
        self.row_filter_selector: QComboBox = QComboBox()
        self.row_max_items_spinbox: QSpinBox = QSpinBox()
        self.row_libraries_container: QScrollArea = QScrollArea()
        self.row_libraries_layout: QVBoxLayout = QVBoxLayout()

    def _create_header_with_info(self, text: str, info_text: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        header = QLabel(f"<b>{text}</b>")
        header.setStyleSheet("font-size: 14px;")
        layout.addWidget(header)

        info_btn = QPushButton("?")
        info_btn.setFixedSize(20, 20)
        info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        info_btn.setToolTip("Click for details on how to get these credentials")
        info_btn.setFlat(True)
        info_btn.setStyleSheet(
            """
            QPushButton {
                color: #3498db;
                font-weight: bold;
                font-size: 16px;
                border: none;
                background: none;
                padding: 0;
            }
            QPushButton:hover {
                text-decoration: underline;
                color: #2980b9;
            }
        """
        )
        info_btn.clicked.connect(
            lambda: QMessageBox.information(self, f"About {text}", info_text)
        )
        layout.addWidget(info_btn)
        layout.addStretch()

        return container

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        tab_container: QTabWidget = QTabWidget()

        # Connectivity Configuration Pane
        connectivity_tab: QWidget = self._build_connectivity_tab()

        # Library Management Pane
        management_tab: QWidget = self._build_management_tab()

        # Dedicated Library Tabs Setup Pane
        tabs_tab: QWidget = self._build_tabs_tab()

        # Local Libraries Management Pane
        local_libraries_tab: QWidget = self._build_libraries_tab()

        # Dedicated Remote Libraries Management Pane
        remote_libraries_tab: QWidget = self._build_remote_libraries_tab()

        # Combined View Setup Pane
        combined_tab: QWidget = self._build_combined_view_tab()

        # Video Player Settings Pane
        player_tab: QWidget = self._build_player_tab()

        # Advanced Settings Pane
        advanced_tab: QWidget = self._build_advanced_tab()

        # Running Logs Tab
        logs_tab: QWidget = self._build_logs_tab()

        # Add tabs in the requested order
        tab_container.addTab(management_tab, "Library Management")
        tab_container.addTab(tabs_tab, "Library Tabs")
        tab_container.addTab(local_libraries_tab, "Local Libraries Setup")
        tab_container.addTab(remote_libraries_tab, "Remote Libraries Setup")
        tab_container.addTab(combined_tab, "Combined View")
        tab_container.addTab(player_tab, "Video Player")
        tab_container.addTab(connectivity_tab, "Remote API's")
        tab_container.addTab(advanced_tab, "Advanced")
        tab_container.addTab(logs_tab, "Logs")

        main_layout.addWidget(tab_container)

        # Dialog Standard Action Buttons
        buttons_layout: QHBoxLayout = QHBoxLayout()
        buttons_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Discard")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)

        save_button: QPushButton = QPushButton("Save Settings")
        save_button.setObjectName("accentButton")
        save_button.clicked.connect(self.save_config)
        buttons_layout.addWidget(save_button)

        main_layout.addLayout(buttons_layout)

    def _build_connectivity_tab(self) -> QWidget:
        connectivity_tab: QWidget = QWidget()
        connectivity_layout: QGridLayout = QGridLayout(connectivity_tab)
        connectivity_layout.setSpacing(12)
        connectivity_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Jellyfin Section
        jelly_header = self._create_header_with_info(
            "Jellyfin Server",
            "Jellyfin credentials allow Lan Streamer to sync your watch history.\n\n"
            "- Server URL: The address of your Jellyfin server (e.g. http://192.168.1.50:8096)\n"
            "- API Token: Create this in Jellyfin Dashboard -> Dashboard -> API Keys.",
        )
        connectivity_layout.addWidget(jelly_header, 0, 0, 1, 2)
        connectivity_layout.addWidget(QLabel("Server URL:"), 1, 0)
        connectivity_layout.addWidget(self.jellyfin_url_input, 1, 1)
        connectivity_layout.addWidget(QLabel("API Token:"), 2, 0)
        self.jellyfin_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.jellyfin_key_input, 2, 1)
        connectivity_layout.addWidget(self.sync_history_on_start_checkbox, 3, 0, 1, 2)

        # TMDB Section
        tmdb_header = self._create_header_with_info(
            "The Movie Database (TMDB)",
            "TMDB is used to fetch posters, descriptions, and episode metadata.\n\n"
            "- API Key: Create a free key at https://www.themoviedb.org/settings/api",
        )
        connectivity_layout.addWidget(tmdb_header, 4, 0, 1, 2)
        connectivity_layout.addWidget(QLabel("API Key:"), 5, 0)
        self.tmdb_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.tmdb_key_input, 5, 1)

        # OpenSubtitles Section
        osub_header = self._create_header_with_info(
            "OpenSubtitles.com",
            "Allows searching and downloading subtitles directly.\n\n"
            "- Username/Password: Your personal OpenSubtitles.com account.\n"
            "- API Key: MANDATORY for the app to connect. Create a free 'Consumer Key' "
            "at https://www.opensubtitles.com/en/consumers",
        )
        connectivity_layout.addWidget(osub_header, 6, 0, 1, 2)
        connectivity_layout.addWidget(QLabel("Username:"), 7, 0)
        connectivity_layout.addWidget(self.opensubtitles_username_input, 7, 1)
        connectivity_layout.addWidget(QLabel("Password:"), 8, 0)
        self.opensubtitles_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.opensubtitles_password_input, 8, 1)
        connectivity_layout.addWidget(QLabel("API Key:"), 9, 0)
        self.opensubtitles_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.opensubtitles_api_key_input, 9, 1)

        # MyAnimeList Section
        mal_header = self._create_header_with_info(
            "MyAnimeList",
            "MyAnimeList integration allows Lan Streamer to push your watch history.\n\n"
            "To get a Client ID and Client Secret, register an application on MyAnimeList at:\n"
            "https://myanimelist.net/apiconfig/create\n\n"
            "Important: Configure the Redirect URI on MyAnimeList to exactly:\n"
            "http://localhost/\n"
            "(with a trailing slash - omitting the slash will cause a login redirect loop on MyAnimeList).",
        )
        connectivity_layout.addWidget(mal_header, 10, 0, 1, 2)
        connectivity_layout.addWidget(QLabel("Client ID:"), 11, 0)
        self.myanimelist_client_id_input: QLineEdit = QLineEdit()
        connectivity_layout.addWidget(self.myanimelist_client_id_input, 11, 1)

        connectivity_layout.addWidget(QLabel("Client Secret:"), 12, 0)
        self.myanimelist_client_secret_input: QLineEdit = QLineEdit()
        self.myanimelist_client_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.myanimelist_client_secret_input, 12, 1)

        mal_buttons_layout = QHBoxLayout()
        self.myanimelist_status_label = QLabel("Status: Not connected")
        self.myanimelist_status_label.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self.myanimelist_status_label.setStyleSheet("color: #e53935;")
        mal_buttons_layout.addWidget(self.myanimelist_status_label)

        self.myanimelist_link_button = QPushButton("Link MAL Account...")
        self.myanimelist_link_button.clicked.connect(self.link_myanimelist_account)
        mal_buttons_layout.addWidget(self.myanimelist_link_button)

        self.myanimelist_unlink_button = QPushButton("Remove MAL Connection")
        self.myanimelist_unlink_button.clicked.connect(self.unlink_myanimelist_account)
        self.myanimelist_unlink_button.setVisible(False)
        mal_buttons_layout.addWidget(self.myanimelist_unlink_button)

        connectivity_layout.addLayout(mal_buttons_layout, 13, 0, 1, 2)

        connectivity_layout.setRowStretch(14, 1)
        return connectivity_tab

    def _build_libraries_tab(self) -> QWidget:
        libraries_tab: QWidget = QWidget()
        libraries_main_layout: QHBoxLayout = QHBoxLayout(libraries_tab)
        libraries_main_layout.setSpacing(15)
        libraries_main_layout.setContentsMargins(10, 10, 10, 10)

        # Left Column: Existing Library Setup
        left_column = QWidget()
        libraries_layout: QVBoxLayout = QVBoxLayout(left_column)
        libraries_layout.setContentsMargins(0, 0, 0, 0)
        libraries_layout.setSpacing(12)

        # Create Library Group
        create_layout: QHBoxLayout = QHBoxLayout()
        create_layout.addWidget(QLabel("New Library Name:"))
        self.library_name_input.setPlaceholderText("e.g. Movies, Documentaries")
        create_layout.addWidget(self.library_name_input)

        create_layout.addWidget(QLabel("Type:"))
        self.library_type_input.clear()
        self.library_type_input.addItems(["TV Shows", "Movies", "Anime"])
        create_layout.addWidget(self.library_type_input)

        add_library_button: QPushButton = QPushButton("Create Library")
        add_library_button.clicked.connect(self.add_staged_library)
        create_layout.addWidget(add_library_button)
        libraries_layout.addLayout(create_layout)

        # Divider
        divider_frame: QFrame = QFrame()
        divider_frame.setFrameShape(QFrame.Shape.HLine)
        divider_frame.setFrameShadow(QFrame.Shadow.Sunken)
        libraries_layout.addWidget(divider_frame)

        # Select Library Group
        select_layout: QHBoxLayout = QHBoxLayout()
        select_layout.addWidget(QLabel("Configure Library:"))
        self.library_selector.setMinimumWidth(200)
        self.library_selector.currentTextChanged.connect(self._on_library_selected)
        select_layout.addWidget(self.library_selector)

        self.local_library_scan_button.setText("Scan Library")
        self.local_library_scan_button.clicked.connect(self.scan_selected_local_library)
        select_layout.addWidget(self.local_library_scan_button)

        delete_library_button: QPushButton = QPushButton("Remove Library")
        delete_library_button.clicked.connect(self.remove_staged_library)
        select_layout.addWidget(delete_library_button)
        select_layout.addStretch()
        libraries_layout.addLayout(select_layout)

        self.show_future_episodes_checkbox.setText("Show future episodes")
        self.show_future_episodes_checkbox.stateChanged.connect(
            self._on_show_future_episodes_toggled
        )
        libraries_layout.addWidget(self.show_future_episodes_checkbox)

        self.anime_library_checkbox.setText("Anime Library")
        self.anime_library_checkbox.setToolTip(
            "Enable Anime Mode for MyAnimeList integration and better metadata matching."
        )
        self.anime_library_checkbox.stateChanged.connect(self._on_anime_library_toggled)
        libraries_layout.addWidget(self.anime_library_checkbox)

        # Mapped Directories List
        self.directory_list_label.setText("Root Directory:")
        libraries_layout.addWidget(self.directory_list_label)
        libraries_layout.addWidget(self.directory_list_widget)

        # Directory Operations
        dir_buttons_layout: QHBoxLayout = QHBoxLayout()
        add_dir_button: QPushButton = QPushButton("Add Directory...")
        add_dir_button.clicked.connect(self.add_staged_directory)
        dir_buttons_layout.addWidget(add_dir_button)

        toggle_archive_button: QPushButton = QPushButton("Toggle Active / Archive")
        toggle_archive_button.setToolTip(
            "Toggle between Active (frequently scanned) and Archive (rarely changing / skipped during periodic scans) mode."
        )
        toggle_archive_button.clicked.connect(self.toggle_staged_directory_archive_mode)
        dir_buttons_layout.addWidget(toggle_archive_button)

        remove_dir_button: QPushButton = QPushButton("Remove Selected Directory")
        remove_dir_button.clicked.connect(self.remove_staged_directory)
        dir_buttons_layout.addWidget(remove_dir_button)
        dir_buttons_layout.addStretch()
        libraries_layout.addLayout(dir_buttons_layout)

        libraries_main_layout.addWidget(left_column, 2)

        # Right Column: Scan Order Setup
        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        right_layout.addWidget(QLabel("Library Scan Order (Left to Right):"))
        right_layout.addWidget(self.library_order_list_widget)

        order_btns_layout = QHBoxLayout()
        move_up_order_btn = QPushButton("Move Up")
        move_up_order_btn.clicked.connect(self.move_library_order_up)
        move_down_order_btn = QPushButton("Move Down")
        move_down_order_btn.clicked.connect(self.move_library_order_down)
        order_btns_layout.addWidget(move_up_order_btn)
        order_btns_layout.addWidget(move_down_order_btn)
        right_layout.addLayout(order_btns_layout)

        libraries_main_layout.addWidget(right_column, 1)
        return libraries_tab

    def _build_remote_libraries_tab(self) -> QWidget:
        """Builds the dedicated Remote Libraries Setup tab."""
        remote_tab: QWidget = QWidget()
        remote_main_layout: QVBoxLayout = QVBoxLayout(remote_tab)
        remote_main_layout.setSpacing(12)
        remote_main_layout.setContentsMargins(10, 10, 10, 10)

        # Instructions banner
        instructions_label = QLabel(
            "Connect to a remote Scan Agent running on your network (e.g. Docker / NAS server).\n"
            "Once connected, check the libraries you want to enable and map their remote directories to local mounts for playback."
        )
        instructions_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
        instructions_label.setWordWrap(True)
        remote_main_layout.addWidget(instructions_label)

        # Connection Header
        connection_group = QGroupBox("Scan Agent Connection")
        connection_layout = QHBoxLayout(connection_group)
        connection_layout.addWidget(QLabel("Agent URL:"))
        self.remote_agent_url_input.setPlaceholderText("e.g. http://192.168.1.100:8800")
        self.remote_agent_url_input.returnPressed.connect(self.connect_to_agent)
        connection_layout.addWidget(self.remote_agent_url_input, 1)

        self.connect_agent_button.setText("Connect to Agent")
        self.connect_agent_button.clicked.connect(self.connect_to_agent)
        connection_layout.addWidget(self.connect_agent_button)
        remote_main_layout.addWidget(connection_group)

        # Tree Widget Section
        tree_group = QGroupBox("Scan Agents & Tracked Remote Libraries")
        tree_layout = QVBoxLayout(tree_group)
        tree_layout.setSpacing(8)

        self.remote_agents_tree_widget.setHeaderLabels(
            ["Remote Media Source", "Local Mount Point"]
        )
        self.remote_agents_tree_widget.setColumnCount(2)
        if self.remote_agents_tree_widget.header() is not None:
            self.remote_agents_tree_widget.header().setStretchLastSection(True)
        self.remote_agents_tree_widget.setColumnWidth(0, 380)
        self.remote_agents_tree_widget.itemDoubleClicked.connect(
            self._on_remote_tree_item_double_clicked
        )
        self.remote_agents_tree_widget.itemChanged.connect(
            self._on_remote_tree_item_changed
        )
        tree_layout.addWidget(self.remote_agents_tree_widget, 1)

        # Tree Action Buttons
        actions_layout = QHBoxLayout()
        self.map_local_mount_button.setText("Map Local Mount...")
        self.map_local_mount_button.setToolTip(
            "Select the local SMB/NFS directory mount point for the selected remote directory."
        )
        self.map_local_mount_button.clicked.connect(
            self.map_local_mount_for_selected_item
        )
        actions_layout.addWidget(self.map_local_mount_button)

        self.remove_remote_agent_button.setText("Remove Agent")
        self.remove_remote_agent_button.setToolTip(
            "Remove the selected scan agent and its remote libraries."
        )
        self.remove_remote_agent_button.clicked.connect(
            self.remove_selected_remote_agent
        )
        actions_layout.addWidget(self.remove_remote_agent_button)

        self.refresh_remote_agents_button.setText("Refresh Status")
        self.refresh_remote_agents_button.setToolTip(
            "Re-check reachability and fetch library updates for all configured agents."
        )
        self.refresh_remote_agents_button.clicked.connect(self.refresh_remote_agents)
        actions_layout.addWidget(self.refresh_remote_agents_button)

        self.remote_library_scan_button.setText("Sync / Scan Library")
        self.remote_library_scan_button.setToolTip(
            "Trigger synchronization and scanning for the selected remote library."
        )
        self.remote_library_scan_button.clicked.connect(
            self.scan_selected_remote_library
        )
        actions_layout.addWidget(self.remote_library_scan_button)

        actions_layout.addStretch()
        tree_layout.addLayout(actions_layout)

        remote_main_layout.addWidget(tree_group, 1)
        return remote_tab

    def _build_tabs_tab(self) -> QWidget:
        """Builds the dedicated Library Tabs setup pane."""
        tabs_tab: QWidget = QWidget()
        tabs_main_layout: QHBoxLayout = QHBoxLayout(tabs_tab)
        tabs_main_layout.setSpacing(15)
        tabs_main_layout.setContentsMargins(10, 10, 10, 10)

        # Left Column: Tabs list and controls
        left_column: QWidget = QWidget()
        left_layout: QVBoxLayout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        left_layout.addWidget(QLabel("Configured Library Tabs:"))
        self.tabs_list_widget.currentRowChanged.connect(self._on_tab_selected)
        left_layout.addWidget(self.tabs_list_widget)

        buttons_layout: QHBoxLayout = QHBoxLayout()
        self.add_tab_button.clicked.connect(self.add_tab)
        buttons_layout.addWidget(self.add_tab_button)

        self.rename_tab_button.clicked.connect(self.rename_tab)
        buttons_layout.addWidget(self.rename_tab_button)

        self.remove_tab_button.clicked.connect(self.remove_tab)
        buttons_layout.addWidget(self.remove_tab_button)

        self.move_tab_up_button.clicked.connect(self.move_tab_up)
        buttons_layout.addWidget(self.move_tab_up_button)

        self.move_tab_down_button.clicked.connect(self.move_tab_down)
        buttons_layout.addWidget(self.move_tab_down_button)

        left_layout.addLayout(buttons_layout)
        tabs_main_layout.addWidget(left_column, 1)

        # Right Column: Checkable libraries in selected tab
        right_column: QWidget = QWidget()
        right_layout: QVBoxLayout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        right_layout.addWidget(QLabel("Libraries included in selected tab:"))
        self.tab_libraries_list_widget.itemChanged.connect(
            self._on_tab_library_item_changed
        )
        right_layout.addWidget(self.tab_libraries_list_widget)

        tabs_main_layout.addWidget(right_column, 1)
        return tabs_tab

    def _refresh_tabs_list(self) -> None:
        self.tabs_list_widget.blockSignals(True)
        current_index: int = self.tabs_list_widget.currentRow()
        self.tabs_list_widget.clear()
        for tab_dict in self.staged_tabs:
            tab_name: str = tab_dict.get("name", "")
            libraries_count: int = len(tab_dict.get("libraries", []))
            self.tabs_list_widget.addItem(f"{tab_name} ({libraries_count} libraries)")
        if 0 <= current_index < len(self.staged_tabs):
            self.tabs_list_widget.setCurrentRow(current_index)
        elif self.staged_tabs:
            self.tabs_list_widget.setCurrentRow(0)
        self.tabs_list_widget.blockSignals(False)
        self._on_tab_selected(self.tabs_list_widget.currentRow())

    @Slot(int)
    def _on_tab_selected(self, index: int) -> None:
        if index < 0 or index >= len(self.staged_tabs):
            self.tab_libraries_list_widget.clear()
            self.tab_libraries_list_widget.setEnabled(False)
            return

        self.tab_libraries_list_widget.setEnabled(True)
        self.tab_libraries_list_widget.blockSignals(True)
        self.tab_libraries_list_widget.clear()

        selected_tab: dict[str, Any] = self.staged_tabs[index]
        selected_libraries: set[str] = set(selected_tab.get("libraries", []))

        all_library_names: list[str] = sorted(self.staged_libraries.keys())
        for library_name in all_library_names:
            item = QListWidgetItem(library_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if library_name in selected_libraries
                else Qt.CheckState.Unchecked
            )
            self.tab_libraries_list_widget.addItem(item)

        self.tab_libraries_list_widget.blockSignals(False)

    @Slot(QListWidgetItem)
    def _on_tab_library_item_changed(self, item: QListWidgetItem) -> None:
        index: int = self.tabs_list_widget.currentRow()
        if index < 0 or index >= len(self.staged_tabs):
            return

        selected_tab: dict[str, Any] = self.staged_tabs[index]
        library_name: str = item.text()
        libraries_list: list[str] = selected_tab.setdefault("libraries", [])

        if item.checkState() == Qt.CheckState.Checked:
            if library_name not in libraries_list:
                libraries_list.append(library_name)
        elif library_name in libraries_list:
            libraries_list.remove(library_name)

        self.tabs_list_widget.blockSignals(True)
        current_item = self.tabs_list_widget.item(index)
        if current_item is not None:
            current_item.setText(
                f"{selected_tab.get('name', '')} ({len(libraries_list)} libraries)"
            )
        self.tabs_list_widget.blockSignals(False)

    @Slot()
    def add_tab(self) -> None:
        tab_name, confirmed = QInputDialog.getText(
            self, "Add Tab", "Enter new tab name:"
        )
        tab_name = tab_name.strip()
        if not confirmed or not tab_name:
            return
        if any(tab.get("name") == tab_name for tab in self.staged_tabs):
            QMessageBox.warning(
                self, "Tab Exists", f"A tab named '{tab_name}' already exists."
            )
            return

        self.staged_tabs.append({"name": tab_name, "libraries": []})
        self._refresh_tabs_list()
        self.tabs_list_widget.setCurrentRow(len(self.staged_tabs) - 1)

    @Slot()
    def rename_tab(self) -> None:
        index: int = self.tabs_list_widget.currentRow()
        if index < 0 or index >= len(self.staged_tabs):
            return

        current_tab_name: str = self.staged_tabs[index].get("name", "")
        new_tab_name, confirmed = QInputDialog.getText(
            self, "Rename Tab", "Enter new tab name:", text=current_tab_name
        )
        new_tab_name = new_tab_name.strip()
        if not confirmed or not new_tab_name or new_tab_name == current_tab_name:
            return

        if any(
            item_index != index and tab.get("name") == new_tab_name
            for item_index, tab in enumerate(self.staged_tabs)
        ):
            QMessageBox.warning(
                self, "Tab Exists", f"A tab named '{new_tab_name}' already exists."
            )
            return

        self.staged_tabs[index]["name"] = new_tab_name
        self._refresh_tabs_list()
        self.tabs_list_widget.setCurrentRow(index)

    @Slot()
    def remove_tab(self) -> None:
        index: int = self.tabs_list_widget.currentRow()
        if index < 0 or index >= len(self.staged_tabs):
            return

        del self.staged_tabs[index]
        self._refresh_tabs_list()

    @Slot()
    def move_tab_up(self) -> None:
        index: int = self.tabs_list_widget.currentRow()
        if index <= 0 or index >= len(self.staged_tabs):
            return

        self.staged_tabs[index - 1], self.staged_tabs[index] = (
            self.staged_tabs[index],
            self.staged_tabs[index - 1],
        )
        self._refresh_tabs_list()
        self.tabs_list_widget.setCurrentRow(index - 1)

    @Slot()
    def move_tab_down(self) -> None:
        index: int = self.tabs_list_widget.currentRow()
        if index < 0 or index >= len(self.staged_tabs) - 1:
            return

        self.staged_tabs[index + 1], self.staged_tabs[index] = (
            self.staged_tabs[index],
            self.staged_tabs[index + 1],
        )
        self._refresh_tabs_list()
        self.tabs_list_widget.setCurrentRow(index + 1)

    @Slot()
    def scan_selected_local_library(self) -> None:
        selected_library: str = self.library_selector.currentText().strip()
        if not selected_library or self.controller is None:
            return
        self._show_scan_progress_widgets()
        self.controller.trigger_scan(
            force_refresh=False,
            library_name=selected_library,
            run_pass1=True,
            run_pass2=True,
            chain_pass3=True,
            chain_cleanup=True,
        )

    @Slot()
    def scan_selected_remote_library(self) -> None:
        selected_item = self.remote_agents_tree_widget.currentItem()
        if not selected_item or self.controller is None:
            QMessageBox.information(
                self,
                "Select Remote Library",
                "Please select a remote library from the tree to sync or scan.",
            )
            return
        item_data = selected_item.data(0, Qt.ItemDataRole.UserRole)
        library_name = ""
        if isinstance(item_data, dict) and item_data.get("item_type") in (
            "library",
            "root_directory",
        ):
            library_name = item_data.get("library_name", "")
        if not library_name:
            library_name = selected_item.data(
                0, Qt.ItemDataRole.UserRole + 1
            ) or selected_item.text(0)
        if library_name and library_name in self.staged_libraries:
            self.controller._config.libraries[library_name] = dict(
                self.staged_libraries[library_name]
            )
            self._show_scan_progress_widgets()
            self.controller.trigger_scan(
                force_refresh=False,
                library_name=library_name,
                run_pass1=True,
                run_pass2=True,
                chain_pass3=True,
                chain_cleanup=True,
            )
        else:
            QMessageBox.information(
                self,
                "Select Remote Library",
                "Please select a valid tracked remote library.",
            )

    def _build_combined_view_tab(self) -> QWidget:
        combined_tab: QWidget = QWidget()
        combined_tab_main_layout: QVBoxLayout = QVBoxLayout(combined_tab)
        combined_tab_main_layout.setContentsMargins(10, 10, 10, 10)
        combined_tab_main_layout.setSpacing(10)

        # Checkbox to enable/disable combined view
        combined_tab_main_layout.addWidget(self.enable_combined_view_checkbox)

        # Content container
        combined_content_widget = QWidget()
        combined_layout: QHBoxLayout = QHBoxLayout(combined_content_widget)
        combined_layout.setContentsMargins(0, 0, 0, 0)
        combined_layout.setSpacing(15)
        combined_tab_main_layout.addWidget(combined_content_widget)

        # Connect enable checkbox to setEnabled of the content container
        self.enable_combined_view_checkbox.toggled.connect(
            combined_content_widget.setEnabled
        )

        # Left Column: List and List Controls
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Configure rows for Combined Library View:"))
        left_layout.addWidget(self.combined_views_list_widget)

        list_btn_layout = QHBoxLayout()
        move_up_btn = QPushButton("Move Up")
        move_up_btn.clicked.connect(self.move_combined_view_row_up)
        move_down_btn = QPushButton("Move Down")
        move_down_btn.clicked.connect(self.move_combined_view_row_down)
        remove_btn = QPushButton("Remove Row")
        remove_btn.clicked.connect(self.delete_combined_view_row)

        list_btn_layout.addWidget(move_up_btn)
        list_btn_layout.addWidget(move_down_btn)
        list_btn_layout.addWidget(remove_btn)
        left_layout.addLayout(list_btn_layout)

        add_row_btn = QPushButton("Add New Row")
        add_row_btn.clicked.connect(self.add_combined_view_row)
        left_layout.addWidget(add_row_btn)

        combined_layout.addWidget(left_column, 2)

        # Right Column: Properties Group
        properties_layout = QVBoxLayout(self.row_properties_group)
        properties_layout.setSpacing(10)

        properties_layout.addWidget(QLabel("Row Display Name:"))
        properties_layout.addWidget(self.row_name_input)
        self.row_name_input.textChanged.connect(self._on_row_property_changed)

        properties_layout.addWidget(self.row_enabled_checkbox)
        self.row_enabled_checkbox.stateChanged.connect(self._on_row_property_changed)

        # Sort and filter settings (all rows are now configured similarly to smart rows)
        properties_layout.addWidget(QLabel("Sort By:"))
        self.row_sort_selector.addItems(
            ["Alphabetical", "Recently Added", "Recently Aired", "Next Up"]
        )
        self.row_sort_selector.currentTextChanged.connect(self._on_row_property_changed)
        properties_layout.addWidget(self.row_sort_selector)

        properties_layout.addWidget(QLabel("Filter Mode:"))
        self.row_filter_selector.addItems(["All", "Watched", "Unwatched"])
        self.row_filter_selector.currentTextChanged.connect(
            self._on_row_property_changed
        )
        properties_layout.addWidget(self.row_filter_selector)

        # Max items setting
        properties_layout.addWidget(QLabel("Max Items:"))
        self.row_max_items_spinbox.setRange(1, 1000)
        self.row_max_items_spinbox.setValue(20)
        self.row_max_items_spinbox.valueChanged.connect(self._on_row_property_changed)
        properties_layout.addWidget(self.row_max_items_spinbox)

        # Libraries Checklist
        properties_layout.addWidget(
            QLabel("Aggregated Libraries (none checked = all):")
        )
        libs_widget = QWidget()
        libs_widget.setLayout(self.row_libraries_layout)
        self.row_libraries_container.setWidget(libs_widget)
        self.row_libraries_container.setWidgetResizable(True)
        self.row_libraries_container.setMinimumHeight(150)
        properties_layout.addWidget(self.row_libraries_container)

        properties_layout.addStretch()
        combined_layout.addWidget(self.row_properties_group, 3)

        self.combined_views_list_widget.currentRowChanged.connect(
            self._on_combined_view_selected
        )
        return combined_tab

    def _build_player_tab(self) -> QWidget:
        player_tab: QWidget = QWidget()
        player_layout: QVBoxLayout = QVBoxLayout(player_tab)
        player_layout.setSpacing(15)

        player_layout.addWidget(self.use_embedded_checkbox)
        player_layout.addWidget(self.enable_caching_checkbox)
        player_layout.addWidget(self.enable_hw_accel_checkbox)
        player_layout.addWidget(self.enable_next_episode_popup_checkbox)

        threshold_layout: QHBoxLayout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("Watched Threshold (% of video length):"))
        self.watched_threshold_input.setFixedWidth(80)
        threshold_layout.addWidget(self.watched_threshold_input)
        threshold_layout.addStretch()
        player_layout.addLayout(threshold_layout)

        cache_size_layout: QHBoxLayout = QHBoxLayout()
        cache_size_layout.addWidget(QLabel("Max Local File Cache Size (GB):"))
        self.max_cache_size_input.setFixedWidth(80)
        cache_size_layout.addWidget(self.max_cache_size_input)
        cache_size_layout.addStretch()
        player_layout.addLayout(cache_size_layout)

        vlc_buffer_layout: QHBoxLayout = QHBoxLayout()
        vlc_buffer_layout.addWidget(QLabel("VLC Buffer Size (ms):"))
        self.vlc_buffer_input.setFixedWidth(80)
        vlc_buffer_layout.addWidget(self.vlc_buffer_input)
        vlc_buffer_layout.addStretch()
        player_layout.addLayout(vlc_buffer_layout)

        self.fullscreen_control_bar_position_selector.addItems(
            ["Bottom", "Top", "Left", "Right"]
        )
        position_layout: QHBoxLayout = QHBoxLayout()
        position_layout.addWidget(QLabel("Fullscreen Control Bar Position:"))
        self.fullscreen_control_bar_position_selector.setFixedWidth(120)
        position_layout.addWidget(self.fullscreen_control_bar_position_selector)
        position_layout.addStretch()
        player_layout.addLayout(position_layout)

        self.subtitle_position_selector.addItems(["Bottom", "Top"])
        subtitle_position_layout: QHBoxLayout = QHBoxLayout()
        subtitle_position_layout.addWidget(QLabel("Subtitle Position:"))
        self.subtitle_position_selector.setFixedWidth(120)
        subtitle_position_layout.addWidget(self.subtitle_position_selector)
        subtitle_position_layout.addStretch()
        player_layout.addLayout(subtitle_position_layout)

        self.default_aspect_mode_selector.addItem("Fit (Original / Letterbox)", "fit")
        self.default_aspect_mode_selector.addItem(
            "Fill Screen (Crop to Fit / Zoom)", "fill"
        )
        self.default_aspect_mode_selector.addItem("Stretch to Fit", "stretch")
        self.default_aspect_mode_selector.addItem("16:9 (Widescreen)", "16:9")
        self.default_aspect_mode_selector.addItem("21:9 (Ultrawide)", "21:9")
        self.default_aspect_mode_selector.addItem("4:3 (Standard)", "4:3")
        self.default_aspect_mode_selector.addItem("16:10", "16:10")
        self.default_aspect_mode_selector.addItem("2.35:1 (Cinemascope)", "2.35:1")

        aspect_mode_layout: QHBoxLayout = QHBoxLayout()
        aspect_mode_layout.addWidget(QLabel("Default Aspect Ratio / Zoom:"))
        self.default_aspect_mode_selector.setFixedWidth(240)
        aspect_mode_layout.addWidget(self.default_aspect_mode_selector)
        aspect_mode_layout.addStretch()
        player_layout.addLayout(aspect_mode_layout)

        player_layout.addStretch()
        return player_tab

    def _build_advanced_tab(self) -> QWidget:
        advanced_tab: QWidget = QWidget()
        advanced_layout: QVBoxLayout = QVBoxLayout(advanced_tab)
        advanced_layout.setSpacing(15)
        advanced_layout.setContentsMargins(10, 10, 10, 10)

        advanced_layout.addWidget(self._build_database_group())
        advanced_layout.addWidget(self._build_log_group())
        advanced_layout.addWidget(self._build_config_group())
        advanced_layout.addWidget(self._build_updates_group())
        advanced_layout.addStretch()
        return advanced_tab

    def _build_database_group(self) -> QFrame:
        db_frame: QFrame = QFrame()
        db_frame.setObjectName("dbGroupFrame")
        db_frame.setStyleSheet(
            "QFrame#dbGroupFrame { background-color: #222222; border: 1px solid #333333; border-radius: 8px; }"
        )
        db_group_layout: QGridLayout = QGridLayout(db_frame)
        db_group_layout.setContentsMargins(15, 15, 15, 15)
        db_group_layout.setSpacing(10)
        db_group_layout.setColumnStretch(1, 1)

        db_title: QLabel = QLabel("Database Settings")
        db_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #2a82da;")
        db_group_layout.addWidget(db_title, 0, 0, 1, 3)

        db_path_label: QLabel = QLabel("Database File Path:")
        db_group_layout.addWidget(db_path_label, 1, 0)
        db_group_layout.addWidget(self.db_path_input, 1, 1)
        browse_db_button: QPushButton = QPushButton("Browse File...")
        browse_db_button.clicked.connect(self.browse_database_path)
        db_group_layout.addWidget(browse_db_button, 1, 2)

        db_freq_label: QLabel = QLabel("Database Backup Freq (Days):")
        db_group_layout.addWidget(db_freq_label, 2, 0)
        self.database_backup_frequency_input.setToolTip(
            "Setting this to 0 backs up every time the application starts"
        )
        db_group_layout.addWidget(self.database_backup_frequency_input, 2, 1)

        db_ret_label: QLabel = QLabel("Database Backup Retention (Days):")
        db_group_layout.addWidget(db_ret_label, 3, 0)
        db_group_layout.addWidget(self.database_backup_retention_input, 3, 1)

        restore_database_button: QPushButton = QPushButton("Restore Database...")
        restore_database_button.clicked.connect(self.trigger_restore_database)
        db_group_layout.addWidget(restore_database_button, 4, 1)

        return db_frame

    def _build_log_group(self) -> QFrame:
        logs_frame: QFrame = QFrame()
        logs_frame.setObjectName("logsGroupFrame")
        logs_frame.setStyleSheet(
            "QFrame#logsGroupFrame { background-color: #222222; border: 1px solid #333333; border-radius: 8px; }"
        )
        logs_group_layout: QGridLayout = QGridLayout(logs_frame)
        logs_group_layout.setContentsMargins(15, 15, 15, 15)
        logs_group_layout.setSpacing(10)
        logs_group_layout.setColumnStretch(1, 1)

        logs_title: QLabel = QLabel("Log Settings")
        logs_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #2a82da;")
        logs_group_layout.addWidget(logs_title, 0, 0, 1, 3)

        log_dir_label: QLabel = QLabel("Logs Directory:")
        logs_group_layout.addWidget(log_dir_label, 1, 0)
        logs_group_layout.addWidget(self.log_dir_input, 1, 1)
        browse_log_button: QPushButton = QPushButton("Browse Folder...")
        browse_log_button.clicked.connect(self.browse_log_directory)
        logs_group_layout.addWidget(browse_log_button, 1, 2)

        log_level_label: QLabel = QLabel("Log Level:")
        logs_group_layout.addWidget(log_level_label, 2, 0)
        self.log_level_selector.addItems(
            ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        )
        logs_group_layout.addWidget(self.log_level_selector, 2, 1)

        log_saving_label: QLabel = QLabel("Log Saving Mode (Restart Required):")
        logs_group_layout.addWidget(log_saving_label, 3, 0)
        self.log_saving_mode_selector.addItems(
            ["Single Global File", "Divided Service Logs"]
        )
        logs_group_layout.addWidget(self.log_saving_mode_selector, 3, 1)

        log_ret_label: QLabel = QLabel("Max Log Retention Days:")
        logs_group_layout.addWidget(log_ret_label, 4, 0)
        logs_group_layout.addWidget(self.log_retention_input, 4, 1)

        return logs_frame

    def _build_config_group(self) -> QFrame:
        config_frame: QFrame = QFrame()
        config_frame.setObjectName("configGroupFrame")
        config_frame.setStyleSheet(
            "QFrame#configGroupFrame { background-color: #222222; border: 1px solid #333333; border-radius: 8px; }"
        )
        config_group_layout: QGridLayout = QGridLayout(config_frame)
        config_group_layout.setContentsMargins(15, 15, 15, 15)
        config_group_layout.setSpacing(10)
        config_group_layout.setColumnStretch(1, 1)

        config_title: QLabel = QLabel("Configuration & System Backup Settings")
        config_title.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #2a82da;"
        )
        config_group_layout.addWidget(config_title, 0, 0, 1, 3)

        backup_dir_label: QLabel = QLabel("Backup Directory:")
        config_group_layout.addWidget(backup_dir_label, 1, 0)
        config_group_layout.addWidget(self.backup_directory_input, 1, 1)
        browse_backup_button: QPushButton = QPushButton("Browse Folder...")
        browse_backup_button.clicked.connect(self.browse_backup_directory)
        config_group_layout.addWidget(browse_backup_button, 1, 2)

        config_freq_label: QLabel = QLabel("Config Backup Freq (Days):")
        config_group_layout.addWidget(config_freq_label, 2, 0)
        self.config_backup_frequency_input.setToolTip(
            "Setting this to 0 backs up every time the application starts"
        )
        config_group_layout.addWidget(self.config_backup_frequency_input, 2, 1)

        config_ret_label: QLabel = QLabel("Config Backup Retention (Days):")
        config_group_layout.addWidget(config_ret_label, 3, 0)
        config_group_layout.addWidget(self.config_backup_retention_input, 3, 1)

        restore_config_button: QPushButton = QPushButton("Restore Config...")
        restore_config_button.clicked.connect(self.trigger_restore_config)
        config_group_layout.addWidget(restore_config_button, 4, 1)

        return config_frame

    def _build_updates_group(self) -> QFrame:
        updates_frame: QFrame = QFrame()
        updates_frame.setObjectName("updatesGroupFrame")
        updates_frame.setStyleSheet(
            "QFrame#updatesGroupFrame { background-color: #222222; border: 1px solid #333333; border-radius: 8px; }"
        )
        updates_group_layout: QGridLayout = QGridLayout(updates_frame)
        updates_group_layout.setContentsMargins(15, 15, 15, 15)
        updates_group_layout.setSpacing(10)
        updates_group_layout.setColumnStretch(1, 1)

        updates_title: QLabel = QLabel("Application Updates")
        updates_title.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #2a82da;"
        )
        updates_group_layout.addWidget(updates_title, 0, 0, 1, 3)

        updates_group_layout.addWidget(self.check_updates_startup_checkbox, 1, 0, 1, 3)

        updates_channel_label: QLabel = QLabel("Update Channel:")
        updates_group_layout.addWidget(updates_channel_label, 2, 0, 1, 1)
        updates_group_layout.addWidget(self.update_release_channel_selector, 2, 1, 1, 1)

        self.check_updates_now_button: QPushButton = QPushButton(
            "Check for Updates Now"
        )
        self.check_updates_now_button.clicked.connect(self.trigger_manual_update_check)
        updates_group_layout.addWidget(self.check_updates_now_button, 3, 0, 1, 1)

        return updates_frame

    def _build_management_tab(self) -> QWidget:
        management_tab: QWidget = QWidget()
        management_layout: QVBoxLayout = QVBoxLayout(management_tab)
        management_layout.setSpacing(15)

        target_layout: QHBoxLayout = QHBoxLayout()
        target_layout.addWidget(QLabel("Target Library for Scanning:"))
        self.scan_target_library_combobox.setMinimumWidth(220)
        target_layout.addWidget(self.scan_target_library_combobox)
        target_layout.addStretch()
        management_layout.addLayout(target_layout)

        self.scan_files_button: QPushButton = QPushButton("Scan Files")
        self.scan_files_button.setStyleSheet(
            "QPushButton {"
            "    background-color: #2a82da;"
            "    color: #ffffff;"
            "    font-size: 16px;"
            "    font-weight: bold;"
            "    padding: 12px 24px;"
            "    border: none;"
            "    border-radius: 6px;"
            "}"
            "QPushButton:hover {"
            "    background-color: #3592ea;"
            "}"
            "QPushButton:pressed {"
            "    background-color: #1a62ba;"
            "}"
            "QPushButton:disabled {"
            "    background-color: #3a3a3a;"
            "    color: #888888;"
            "}"
        )
        self.scan_files_button.clicked.connect(self.trigger_full_scan_files)
        management_layout.addWidget(self.scan_files_button)

        # Individual scan passes group
        self.passes_frame: QFrame = QFrame()
        self.passes_frame.setStyleSheet(
            "QFrame { background-color: #222222; border: 1px solid #333333; border-radius: 6px; }"
        )
        passes_layout: QVBoxLayout = QVBoxLayout(self.passes_frame)
        passes_layout.setSpacing(10)

        passes_title = QLabel("Individual Scan Passes")
        passes_title.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #e2e8f0; border: none;"
        )
        passes_layout.addWidget(passes_title)

        pass1_row: QHBoxLayout = QHBoxLayout()
        self.pass1_button: QPushButton = QPushButton("File Scan")
        self.pass1_button.clicked.connect(self.trigger_pass1_scan)
        pass1_row.addWidget(self.pass1_button)
        self.force_file_scan_checkbox: QCheckBox = QCheckBox("Force re-scan")
        pass1_row.addWidget(self.force_file_scan_checkbox)
        passes_layout.addLayout(pass1_row)

        pass2_row: QHBoxLayout = QHBoxLayout()
        self.pass2_button: QPushButton = QPushButton("Metadata Resolution")
        self.pass2_button.clicked.connect(self.trigger_pass2_scan)
        pass2_row.addWidget(self.pass2_button)
        self.force_metadata_checkbox: QCheckBox = QCheckBox("Force re-fetch ")
        pass2_row.addWidget(self.force_metadata_checkbox)
        passes_layout.addLayout(pass2_row)

        pass3_row: QHBoxLayout = QHBoxLayout()
        self.pass3_button: QPushButton = QPushButton("Runtime Extraction")
        self.pass3_button.clicked.connect(self.trigger_pass3_scan)
        pass3_row.addWidget(self.pass3_button)
        self.force_runtime_checkbox: QCheckBox = QCheckBox("Force re-extract")
        pass3_row.addWidget(self.force_runtime_checkbox)
        passes_layout.addLayout(pass3_row)

        self.cleanup_button: QPushButton = QPushButton("Garbage Cleanup")
        self.cleanup_button.clicked.connect(self.trigger_garbage_cleanup)
        passes_layout.addWidget(self.cleanup_button)

        management_layout.addWidget(self.passes_frame)

        # Scheduled scanning group
        self.scheduled_scan_frame: QFrame = QFrame()
        self.scheduled_scan_frame.setStyleSheet(
            "QFrame { background-color: #222222; border: 1px solid #333333; border-radius: 6px; }"
        )
        scheduled_scan_layout: QVBoxLayout = QVBoxLayout(self.scheduled_scan_frame)
        scheduled_scan_layout.setSpacing(10)

        scheduled_scan_title = QLabel("Scheduled Background Scanning")
        scheduled_scan_title.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #e2e8f0; border: none;"
        )
        scheduled_scan_layout.addWidget(scheduled_scan_title)

        scheduled_scan_layout.addWidget(self.auto_scan_checkbox)

        interval_row: QHBoxLayout = QHBoxLayout()
        interval_row.addWidget(QLabel("Scan interval:"))
        interval_row.addWidget(self.scan_interval_spinbox)
        interval_row.addStretch()
        scheduled_scan_layout.addLayout(interval_row)

        concurrency_row: QHBoxLayout = QHBoxLayout()
        concurrency_row.addWidget(QLabel("Scanner concurrency:"))
        concurrency_row.addWidget(self.scan_concurrency_spinbox)
        concurrency_row.addStretch()
        scheduled_scan_layout.addLayout(concurrency_row)
        scheduled_scan_layout.addWidget(self.scan_concurrency_warning_label)

        management_layout.addWidget(self.scheduled_scan_frame)

        # Watch history sync buttons
        self.pull_watch_history_button: QPushButton = QPushButton("Pull Watch History")
        self.pull_watch_history_button.clicked.connect(
            self.trigger_global_jellyfin_pull
        )
        management_layout.addWidget(self.pull_watch_history_button)

        self.push_watch_history_button: QPushButton = QPushButton("Push Watch History")
        self.push_watch_history_button.clicked.connect(
            self.trigger_global_jellyfin_push
        )
        management_layout.addWidget(self.push_watch_history_button)

        management_layout.addSpacing(10)
        management_layout.addWidget(QLabel("Global Operation Progress:"))
        management_layout.addWidget(self.global_progress_bar)
        management_layout.addSpacing(4)
        self.scan_detail_label: QLabel = QLabel("Scan Detail:")
        management_layout.addWidget(self.scan_detail_label)
        management_layout.addWidget(self.scan_progress_tree)
        management_layout.addWidget(self.scan_report_display, 1)

        management_layout.addStretch()
        return management_tab

    def _build_logs_tab(self) -> QWidget:
        logs_tab: QWidget = QWidget()
        logs_layout: QVBoxLayout = QVBoxLayout(logs_tab)
        logs_layout.setSpacing(10)
        logs_layout.setContentsMargins(10, 10, 10, 10)

        # Control panel layout
        control_layout: QHBoxLayout = QHBoxLayout()
        control_layout.setSpacing(10)

        control_layout.addWidget(QLabel("Min Level:"))
        self.log_level_filter.clear()
        self.log_level_filter.addItems(
            ["All", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        )
        self.log_level_filter.setCurrentText("INFO")
        self.log_level_filter.currentTextChanged.connect(self._on_log_filter_changed)
        control_layout.addWidget(self.log_level_filter)

        control_layout.addWidget(QLabel("Filter Text:"))
        self.log_search_input.setPlaceholderText("Search logs...")
        self.log_search_input.textChanged.connect(self._on_log_filter_changed)
        control_layout.addWidget(self.log_search_input)

        self.log_autoscroll_checkbox.setText("Auto-scroll")
        self.log_autoscroll_checkbox.setChecked(True)
        control_layout.addWidget(self.log_autoscroll_checkbox)

        clear_logs_button: QPushButton = QPushButton("Clear View")
        clear_logs_button.clicked.connect(self._clear_log_view)
        control_layout.addWidget(clear_logs_button)

        copy_logs_button: QPushButton = QPushButton("Copy All")
        copy_logs_button.clicked.connect(self._copy_logs_to_clipboard)
        control_layout.addWidget(copy_logs_button)

        export_logs_button: QPushButton = QPushButton("Export Logs")
        export_logs_button.clicked.connect(self._export_logs)
        control_layout.addWidget(export_logs_button)

        logs_layout.addLayout(control_layout)

        # PlainTextEdit display configuration
        self.log_display.setReadOnly(True)
        log_font: QFont = QFont("Courier New", 10)
        log_font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_display.setFont(log_font)
        self.log_display.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #121212;
                color: #dcdcdc;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 10px;
            }
            """
        )
        logs_layout.addWidget(self.log_display)
        return logs_tab

    def _load_config(self) -> None:
        self.jellyfin_url_input.setText(config.jellyfin_url)
        self.jellyfin_key_input.setText(config.jellyfin_api_key)
        self.sync_history_on_start_checkbox.setChecked(config.sync_history_on_start)
        self.check_updates_startup_checkbox.setChecked(
            config.check_for_updates_on_startup
        )
        channel_index = self.update_release_channel_selector.findText(
            "Release Candidates"
            if config.update_release_channel == "rc"
            else "Main Releases"
        )
        if channel_index >= 0:
            self.update_release_channel_selector.setCurrentIndex(channel_index)
        self.tmdb_key_input.setText(config.tmdb_api_key)
        self.opensubtitles_username_input.setText(config.opensubtitles_username)
        self.opensubtitles_password_input.setText(config.opensubtitles_password)
        self.opensubtitles_api_key_input.setText(config.opensubtitles_api_key)
        self.myanimelist_client_id_input.setText(config.myanimelist_client_id)
        self.myanimelist_client_secret_input.setText(config.myanimelist_client_secret)
        self._update_mal_status_ui()

        self.use_embedded_checkbox.setChecked(config.use_embedded_player)
        self.enable_caching_checkbox.setChecked(config.enable_caching)
        self.enable_hw_accel_checkbox.setChecked(config.enable_hw_accel)
        self.enable_next_episode_popup_checkbox.setChecked(
            config.enable_next_episode_popup
        )
        self.watched_threshold_input.setText(str(int(config.watched_threshold * 100)))
        self.max_cache_size_input.setText(str(config.max_cache_size_gb))
        self.vlc_buffer_input.setText(str(config.vlc_buffer_ms))
        self.fullscreen_control_bar_position_selector.setCurrentText(
            config.fullscreen_control_bar_position
        )
        self.subtitle_position_selector.setCurrentText(config.subtitle_position)
        aspect_mode_index = self.default_aspect_mode_selector.findData(
            getattr(config, "default_video_aspect_mode", "fit")
        )
        if aspect_mode_index >= 0:
            self.default_aspect_mode_selector.setCurrentIndex(aspect_mode_index)

        self.db_path_input.setText(config.database_path)
        self.log_dir_input.setText(config.log_directory)
        self.log_retention_input.setText(str(config.max_log_retention_days))
        self.log_saving_mode_selector.setCurrentText(
            "Divided Service Logs"
            if config.divide_logs_by_service
            else "Single Global File"
        )
        self.log_level_selector.setCurrentText(config.log_level.upper())

        self.backup_directory_input.setText(config.backup_directory)
        self.config_backup_frequency_input.setText(str(config.config_backup_frequency))
        self.database_backup_frequency_input.setText(
            str(config.database_backup_frequency)
        )
        self.config_backup_retention_input.setText(str(config.config_backup_retention))
        self.database_backup_retention_input.setText(
            str(config.database_backup_retention)
        )

        self.auto_scan_checkbox.setChecked(config.auto_scan_enabled)
        self.scan_interval_spinbox.setValue(config.scan_interval_hours)
        self.scan_concurrency_spinbox.setValue(
            getattr(config, "scan_concurrency", 4) or 4
        )

        self.staged_libraries = {
            library_name: {
                "type": library_config.get("type", "tv"),
                "management_type": library_config.get("management_type", "local"),
                "paths": list(library_config.get("paths", [])),
                "archive_paths": list(library_config.get("archive_paths", [])),
                "show_future_episodes": library_config.get(
                    "show_future_episodes", True
                ),
                "agent_url": library_config.get("agent_url", ""),
                "remote_library_id": library_config.get("remote_library_id", ""),
                "remote_root_path": library_config.get("remote_root_path", ""),
                "remote_root_paths": list(library_config.get("remote_root_paths", [])),
                "mount_mappings": dict(library_config.get("mount_mappings", {})),
            }
            for library_name, library_config in config.libraries.items()
        }
        self.staged_scan_agents = copy.deepcopy(getattr(config, "scan_agents", {}))
        self._populate_remote_agents_tree()
        self._refresh_scan_agent_selectors()
        self._refresh_library_selector()

        self.enable_combined_view_checkbox.setChecked(config.enable_combined_view)
        self.staged_combined_views = [dict(row) for row in config.combined_views]
        self._refresh_combined_views_list()

        if config.tabs:
            self.staged_tabs = [
                {
                    "name": tab.get("name", ""),
                    "libraries": list(tab.get("libraries", [])),
                }
                for tab in config.tabs
            ]
        else:
            self.staged_tabs = [
                {"name": library_name, "libraries": [library_name]}
                for library_name in self.staged_libraries
            ]
        self._refresh_tabs_list()

        # Populate initial logs from the buffer
        from lan_streamer.system.logging_handler import qt_log_handler

        self.all_log_records = list(qt_log_handler.buffer)
        self._refresh_log_display()

        # Connect live log signals
        qt_log_handler.emitter.log_emitted.connect(self._on_log_emitted)
        self._logging_connected = True

    def _refresh_combined_views_list(self) -> None:
        self.combined_views_list_widget.blockSignals(True)
        current_idx = self.combined_views_list_widget.currentRow()
        self.combined_views_list_widget.clear()
        for _idx, row in enumerate(self.staged_combined_views):
            status = "Enabled" if row.get("enabled", True) else "Disabled"
            self.combined_views_list_widget.addItem(
                f"{row.get('name', 'Unnamed')} - {status}"
            )
        if current_idx >= 0 and current_idx < len(self.staged_combined_views):
            self.combined_views_list_widget.setCurrentRow(current_idx)
        elif self.staged_combined_views:
            self.combined_views_list_widget.setCurrentRow(0)
        self.combined_views_list_widget.blockSignals(False)
        self._on_combined_view_selected()

    def _get_default_row_name(self, row: dict[str, Any]) -> str:
        libs = row.get("libraries", [])
        lib_str = ", ".join(libs) if libs else "All Libraries"
        sort_str = row.get("sort_by", "Alphabetical")
        filter_str = row.get("filter_mode", "All")
        return f"{lib_str} - {sort_str} - {filter_str}"

    @Slot()
    def _on_combined_view_selected(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_combined_views):
            self.row_properties_group.setEnabled(False)
            return

        self.row_properties_group.setEnabled(True)
        row = self.staged_combined_views[row_idx]

        self.row_name_input.blockSignals(True)
        self.row_enabled_checkbox.blockSignals(True)
        self.row_sort_selector.blockSignals(True)
        self.row_filter_selector.blockSignals(True)
        self.row_max_items_spinbox.blockSignals(True)

        self.row_name_input.setText(row.get("name", ""))
        self.row_enabled_checkbox.setChecked(row.get("enabled", True))

        self.row_sort_selector.setCurrentText(row.get("sort_by", "Alphabetical"))
        self.row_filter_selector.setCurrentText(row.get("filter_mode", "All"))
        self.row_max_items_spinbox.setValue(row.get("max_items", 20))

        self.row_name_input.blockSignals(False)
        self.row_enabled_checkbox.blockSignals(False)
        self.row_sort_selector.blockSignals(False)
        self.row_filter_selector.blockSignals(False)
        self.row_max_items_spinbox.blockSignals(False)

        # Clear libraries list layout
        while self.row_libraries_layout.count():
            layout_item = self.row_libraries_layout.takeAt(0)
            if layout_item is not None:
                w = layout_item.widget()
                if w is not None:
                    w.deleteLater()

        selected_libs = row.get("libraries", [])
        for lib_name in sorted(self.staged_libraries.keys()):
            cb = QCheckBox(lib_name)
            cb.setChecked(lib_name in selected_libs)
            cb.stateChanged.connect(self._on_row_library_toggled)
            self.row_libraries_layout.addWidget(cb)

    @Slot()
    def _on_row_property_changed(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_combined_views):
            return

        row = self.staged_combined_views[row_idx]
        old_default = self._get_default_row_name(row)
        current_name = self.row_name_input.text().strip()

        row["enabled"] = self.row_enabled_checkbox.isChecked()
        row["sort_by"] = self.row_sort_selector.currentText()
        row["filter_mode"] = self.row_filter_selector.currentText()
        row["max_items"] = self.row_max_items_spinbox.value()

        new_default = self._get_default_row_name(row)
        if current_name in {"", old_default, "New Smart Row"}:
            row["name"] = new_default
            self.row_name_input.blockSignals(True)
            self.row_name_input.setText(new_default)
            self.row_name_input.blockSignals(False)
        else:
            row["name"] = current_name

        status = "Enabled" if row["enabled"] else "Disabled"
        item = self.combined_views_list_widget.item(row_idx)
        if item:
            item.setText(f"{row['name']} - {status}")

    @Slot()
    def _on_row_library_toggled(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_combined_views):
            return
        row = self.staged_combined_views[row_idx]
        old_default = self._get_default_row_name(row)
        current_name = self.row_name_input.text().strip()

        selected_libs = []
        for i in range(self.row_libraries_layout.count()):
            layout_item = self.row_libraries_layout.itemAt(i)
            if layout_item is not None:
                widget = layout_item.widget()
                if isinstance(widget, QCheckBox) and widget.isChecked():
                    selected_libs.append(widget.text())
        row["libraries"] = selected_libs

        new_default = self._get_default_row_name(row)
        if current_name in {"", old_default, "New Smart Row"}:
            row["name"] = new_default
            self.row_name_input.blockSignals(True)
            self.row_name_input.setText(new_default)
            self.row_name_input.blockSignals(False)

            # Update item list text
            status = "Enabled" if row.get("enabled", True) else "Disabled"
            item = self.combined_views_list_widget.item(row_idx)
            if item:
                item.setText(f"{row['name']} - {status}")

    @Slot()
    def add_combined_view_row(self) -> None:
        new_row = {
            "enabled": True,
            "libraries": [],
            "sort_by": "Alphabetical",
            "filter_mode": "All",
            "max_items": 20,
        }
        new_row["name"] = self._get_default_row_name(new_row)
        self.staged_combined_views.append(new_row)
        logger.debug(f"Added combined view row: '{new_row['name']}'")
        self._refresh_combined_views_list()
        self.combined_views_list_widget.setCurrentRow(
            len(self.staged_combined_views) - 1
        )

    @Slot()
    def delete_combined_view_row(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_combined_views):
            return
        deleted_name: str = self.staged_combined_views[row_idx].get("name", "Unnamed")
        del self.staged_combined_views[row_idx]
        logger.debug(f"Deleted combined view row at index {row_idx}: '{deleted_name}'")
        self._refresh_combined_views_list()

    @Slot()
    def move_combined_view_row_up(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx <= 0 or row_idx >= len(self.staged_combined_views):
            return
        self.staged_combined_views[row_idx], self.staged_combined_views[row_idx - 1] = (
            self.staged_combined_views[row_idx - 1],
            self.staged_combined_views[row_idx],
        )
        logger.debug(f"Moved combined view row from index {row_idx} to {row_idx - 1}")
        self._refresh_combined_views_list()
        self.combined_views_list_widget.setCurrentRow(row_idx - 1)

    @Slot()
    def move_combined_view_row_down(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_combined_views) - 1:
            return
        self.staged_combined_views[row_idx], self.staged_combined_views[row_idx + 1] = (
            self.staged_combined_views[row_idx + 1],
            self.staged_combined_views[row_idx],
        )
        logger.debug(f"Moved combined view row from index {row_idx} to {row_idx + 1}")
        self._refresh_combined_views_list()
        self.combined_views_list_widget.setCurrentRow(row_idx + 1)

    def _refresh_library_order_list(self) -> None:
        self.library_order_list_widget.blockSignals(True)
        current_idx = self.library_order_list_widget.currentRow()
        self.library_order_list_widget.clear()
        for lib_name in self.staged_libraries:
            self.library_order_list_widget.addItem(lib_name)
        if current_idx >= 0 and current_idx < len(self.staged_libraries):
            self.library_order_list_widget.setCurrentRow(current_idx)
        elif self.staged_libraries:
            self.library_order_list_widget.setCurrentRow(0)
        self.library_order_list_widget.blockSignals(False)

    @Slot()
    def move_library_order_up(self) -> None:
        row_idx = self.library_order_list_widget.currentRow()
        if row_idx <= 0 or row_idx >= len(self.staged_libraries):
            return

        keys = list(self.staged_libraries.keys())
        keys[row_idx], keys[row_idx - 1] = keys[row_idx - 1], keys[row_idx]

        new_staged = {}
        for key in keys:
            new_staged[key] = self.staged_libraries[key]
        self.staged_libraries = new_staged

        self._refresh_library_order_list()
        self.library_order_list_widget.setCurrentRow(row_idx - 1)

    @Slot()
    def move_library_order_down(self) -> None:
        row_idx = self.library_order_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_libraries) - 1:
            return

        keys = list(self.staged_libraries.keys())
        keys[row_idx], keys[row_idx + 1] = keys[row_idx + 1], keys[row_idx]

        new_staged = {}
        for key in keys:
            new_staged[key] = self.staged_libraries[key]
        self.staged_libraries = new_staged

        self._refresh_library_order_list()
        self.library_order_list_widget.setCurrentRow(row_idx + 1)

    def _refresh_library_selector(self) -> None:
        self.library_selector.blockSignals(True)
        self.library_selector.clear()
        local_libraries = [
            name
            for name, lib in self.staged_libraries.items()
            if lib.get("management_type", "local") != "remote"
        ]
        self.library_selector.addItems(sorted(local_libraries))
        self.library_selector.blockSignals(False)

        if hasattr(self, "scan_target_library_combobox"):
            self.scan_target_library_combobox.blockSignals(True)
            current_target = self.scan_target_library_combobox.currentText()
            self.scan_target_library_combobox.clear()
            all_libraries = sorted(self.staged_libraries.keys())
            self.scan_target_library_combobox.addItems(all_libraries)
            if current_target in all_libraries:
                self.scan_target_library_combobox.setCurrentText(current_target)
            self.scan_target_library_combobox.blockSignals(False)

        self._refresh_directory_list()
        self._refresh_library_options()
        self._refresh_library_order_list()
        if hasattr(self, "tabs_list_widget"):
            self._refresh_tabs_list()

    @Slot(str)
    def _on_library_selected(self, library_name: str) -> None:
        self._refresh_directory_list()
        self._refresh_library_options()

    def _refresh_library_options(self) -> None:
        selected_library: str = self.library_selector.currentText()
        if selected_library in self.staged_libraries:
            lib_config = self.staged_libraries[selected_library]
            lib_type = lib_config.get("type", "tv")
            self.directory_list_label.setText("Root Directory:")

            if lib_type in ("tv", "anime"):
                self.show_future_episodes_checkbox.setVisible(True)
                self.show_future_episodes_checkbox.blockSignals(True)
                self.show_future_episodes_checkbox.setChecked(
                    lib_config.get("show_future_episodes", True)
                )
                self.show_future_episodes_checkbox.blockSignals(False)
                self.anime_library_checkbox.setVisible(True)
                self.anime_library_checkbox.blockSignals(True)
                self.anime_library_checkbox.setChecked(lib_type == "anime")
                self.anime_library_checkbox.blockSignals(False)
            else:
                self.show_future_episodes_checkbox.setVisible(False)
                self.anime_library_checkbox.setVisible(False)
        else:
            self.show_future_episodes_checkbox.setVisible(False)
            self.anime_library_checkbox.setVisible(False)

    @Slot(int)
    def _on_show_future_episodes_toggled(self, state: int) -> None:
        selected_library: str = self.library_selector.currentText()
        if selected_library in self.staged_libraries:
            self.staged_libraries[selected_library]["show_future_episodes"] = (
                self.show_future_episodes_checkbox.isChecked()
            )

    def _refresh_directory_list(self) -> None:
        self.directory_list_widget.clear()
        selected_library: str = self.library_selector.currentText()
        if selected_library in self.staged_libraries:
            paths: list[str] = self.staged_libraries[selected_library].get("paths", [])
            archive_paths: list[str] = self.staged_libraries[selected_library].get(
                "archive_paths", []
            )
            for directory_path in paths:
                mode_label = (
                    "[Archive]" if directory_path in archive_paths else "[Active]"
                )
                item = QListWidgetItem(f"{mode_label}  {directory_path}")
                item.setData(Qt.ItemDataRole.UserRole, directory_path)
                self.directory_list_widget.addItem(item)

    @Slot()
    def toggle_staged_directory_archive_mode(self) -> None:
        selected_library: str = self.library_selector.currentText()
        selected_item: QListWidgetItem | None = self.directory_list_widget.currentItem()
        if not selected_library or selected_item is None:
            return

        directory_path: str = selected_item.data(Qt.ItemDataRole.UserRole) or (
            selected_item.text().split("  ", 1)[-1]
            if "  " in selected_item.text()
            else selected_item.text()
        )
        library_configuration = self.staged_libraries[selected_library]
        archive_paths: list[str] = library_configuration.setdefault("archive_paths", [])
        if directory_path in archive_paths:
            archive_paths.remove(directory_path)
        else:
            archive_paths.append(directory_path)

        current_row = self.directory_list_widget.currentRow()
        self._refresh_directory_list()
        if 0 <= current_row < self.directory_list_widget.count():
            self.directory_list_widget.setCurrentRow(current_row)

    @Slot()
    def add_staged_library(self) -> None:
        """Adds a local media library to the staged configuration."""
        new_library_name: str = self.library_name_input.text().strip()
        new_library_type: str = "tv"
        if self.library_type_input.currentText() == "Movies":
            new_library_type = "movie"
        elif self.library_type_input.currentText() == "Anime":
            new_library_type = "anime"

        new_management_type: str = "local"
        if (
            hasattr(self, "library_management_type_input")
            and self.library_management_type_input.count() > 0
            and "Remote" in self.library_management_type_input.currentText()
        ):
            new_management_type = "remote"

        if not new_library_name:
            return
        if new_library_name in self.staged_libraries:
            QMessageBox.warning(
                self,
                "Duplicate Library",
                f"Library '{new_library_name}' already exists.",
            )
            return

        self.staged_libraries[new_library_name] = {
            "type": new_library_type,
            "management_type": new_management_type,
            "paths": [],
            "archive_paths": [],
            "show_future_episodes": True,
            "agent_url": "",
            "remote_library_id": "",
            "remote_root_path": "",
            "mount_mappings": {},
        }
        self.library_name_input.clear()
        self._refresh_library_selector()
        self._refresh_tabs_list()
        if new_management_type == "local":
            self.library_selector.setCurrentText(new_library_name)
        else:
            self._populate_remote_agents_tree()
        logger.info(
            "Added %s library '%s' (type: %s) to staged configuration",
            new_management_type,
            new_library_name,
            new_library_type,
        )

    @Slot()
    def connect_to_agent(self) -> None:
        """Connect to a remote scan agent via URL, verify reachability, and fetch its libraries."""
        raw_agent_url: str = self.remote_agent_url_input.text().strip()
        if not raw_agent_url:
            QMessageBox.warning(self, "Invalid URL", "Please enter an Agent URL.")
            return

        from lan_streamer.services.scan_agent_client import (
            ScanAgentConnectionError,
            normalize_agent_url,
            scan_agent_client,
        )

        try:
            normalized_agent_url = normalize_agent_url(raw_agent_url)
        except ValueError as validation_error:
            QMessageBox.warning(self, "Invalid URL", str(validation_error))
            return

        is_reachable = False
        agent_name = f"Scan Agent ({normalized_agent_url})"
        discovered_libraries: list[dict[str, Any]] = []

        try:
            health_data = scan_agent_client.check_agent_health(
                normalized_agent_url, timeout=4.0
            )
            is_reachable = True
            service_name = health_data.get("service")
            if service_name:
                agent_name = service_name
        except (
            ScanAgentConnectionError,
            OSError,
            ValueError,
            RuntimeError,
        ) as connection_error:
            logger.warning(
                "Could not connect to scan agent at %s: %s",
                normalized_agent_url,
                connection_error,
            )

        if is_reachable:
            try:
                discovered_libraries = scan_agent_client.fetch_agent_libraries(
                    normalized_agent_url, timeout=5.0
                )
            except (
                ScanAgentConnectionError,
                OSError,
                ValueError,
                RuntimeError,
            ) as library_fetch_error:
                logger.warning(
                    "Failed to fetch libraries from agent %s: %s",
                    normalized_agent_url,
                    library_fetch_error,
                )

        existing_agent_data = self.staged_scan_agents.get(normalized_agent_url, {})
        merged_libraries = list(discovered_libraries)
        if not merged_libraries and existing_agent_data.get("discovered_libraries"):
            merged_libraries = existing_agent_data["discovered_libraries"]

        self.staged_scan_agents[normalized_agent_url] = {
            "name": agent_name,
            "url": normalized_agent_url,
            "api_key": existing_agent_data.get("api_key", ""),
            "reachable": is_reachable,
            "discovered_libraries": merged_libraries,
        }

        self.remote_agent_url_input.clear()
        self._populate_remote_agents_tree()
        self._refresh_scan_agent_selectors()

        if not is_reachable:
            QMessageBox.warning(
                self,
                "Scan Agent Unreachable",
                f"Could not connect to Scan Agent at:\n{normalized_agent_url}\n\n"
                "The agent has been added, but is currently marked unreachable.",
            )
        else:
            logger.info(
                "Successfully connected to scan agent '%s' at %s with %d libraries",
                agent_name,
                normalized_agent_url,
                len(discovered_libraries),
            )

    def _populate_remote_agents_tree(self) -> None:
        """Populates the tree widget with configured agents, their libraries, and root directory mappings."""
        self.remote_agents_tree_widget.blockSignals(True)
        self.remote_agents_tree_widget.clear()

        for agent_url, agent_data in sorted(self.staged_scan_agents.items()):
            agent_name = agent_data.get("name") or "Scan Agent"
            is_reachable = bool(agent_data.get("reachable", True))
            status_icon = "🟢" if is_reachable else "🔴"
            status_text = "Reachable" if is_reachable else "Unreachable"

            agent_item = QTreeWidgetItem(self.remote_agents_tree_widget)
            agent_item.setText(0, f"{status_icon}  {agent_name} ({agent_url})")
            agent_item.setText(1, f"Status: {status_text}")
            agent_item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {"item_type": "agent", "agent_url": agent_url},
            )
            agent_item.setExpanded(True)

            discovered_libraries: list[dict[str, Any]] = list(
                agent_data.get("discovered_libraries", [])
            )

            # Ensure any staged remote libraries belonging to this agent are included
            seen_library_names = {
                library_dict.get("name")
                for library_dict in discovered_libraries
                if isinstance(library_dict, dict) and library_dict.get("name")
            }
            for (
                staged_library_name,
                staged_library_config,
            ) in self.staged_libraries.items():
                if (
                    staged_library_config.get("management_type") == "remote"
                    and staged_library_config.get("agent_url") == agent_url
                    and staged_library_name not in seen_library_names
                ):
                    discovered_libraries.append(
                        {
                            "id": staged_library_config.get("remote_library_id", ""),
                            "name": staged_library_name,
                            "type": staged_library_config.get("type", "tv"),
                            "root_path": staged_library_config.get(
                                "remote_root_path", ""
                            ),
                            "root_paths": list(
                                staged_library_config.get("mount_mappings", {})
                            )
                            or list(staged_library_config.get("remote_root_paths", []))
                            or [staged_library_config.get("remote_root_path", "")],
                        }
                    )
                    seen_library_names.add(staged_library_name)

            for library_info in discovered_libraries:
                if not isinstance(library_info, dict):
                    continue
                library_name = library_info.get("name") or "Unnamed Library"
                library_type = (
                    library_info.get("media_type") or library_info.get("type") or "tv"
                )
                library_identifier = library_info.get("id") or ""

                is_enabled = (
                    library_name in self.staged_libraries
                    and self.staged_libraries[library_name].get("management_type")
                    == "remote"
                    and self.staged_libraries[library_name].get("agent_url")
                    == agent_url
                )

                root_paths: list[str] = []
                if library_info.get("root_paths"):
                    root_paths = [
                        str(path) for path in library_info["root_paths"] if path
                    ]
                elif library_info.get("root_path"):
                    root_paths = [str(library_info["root_path"])]

                mount_mappings: dict[str, str] = {}
                if is_enabled:
                    mount_mappings = dict(
                        self.staged_libraries[library_name].get("mount_mappings", {})
                    )
                    for root_key in mount_mappings:
                        if root_key and root_key not in root_paths:
                            root_paths.append(root_key)

                library_item = QTreeWidgetItem(agent_item)
                library_item.setText(0, f"{library_name} [{library_type.upper()}]")
                library_item.setText(1, "Enabled" if is_enabled else "Disabled")
                library_item.setFlags(
                    library_item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                library_item.setCheckState(
                    0,
                    Qt.CheckState.Checked if is_enabled else Qt.CheckState.Unchecked,
                )
                library_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {
                        "item_type": "library",
                        "agent_url": agent_url,
                        "library_id": library_identifier,
                        "library_name": library_name,
                        "library_type": library_type,
                        "root_paths": root_paths,
                    },
                )
                library_item.setExpanded(True)

                for remote_root in root_paths:
                    if not remote_root:
                        continue
                    root_item = QTreeWidgetItem(library_item)
                    root_item.setText(0, f"📁 {remote_root}")
                    local_mount = mount_mappings.get(remote_root, "")
                    root_item.setText(
                        1,
                        local_mount or "[Not Mapped - Select to Map]",
                    )
                    root_item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {
                            "item_type": "root_directory",
                            "agent_url": agent_url,
                            "library_name": library_name,
                            "remote_root": remote_root,
                        },
                    )

        self.remote_agents_tree_widget.blockSignals(False)

    @Slot(QTreeWidgetItem, int)
    def _on_remote_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Handles enabling or disabling a remote library when its check state changes."""
        if column != 0:
            return
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(item_data, dict) or item_data.get("item_type") != "library":
            return

        is_checked = item.checkState(0) == Qt.CheckState.Checked
        library_name: str = item_data["library_name"]
        agent_url: str = item_data["agent_url"]
        library_type: str = item_data["library_type"]
        library_identifier: str = item_data["library_id"]
        root_paths: list[str] = item_data.get("root_paths", [])

        if is_checked:
            item.setText(1, "Enabled")
            mount_mappings: dict[str, str] = {}
            for child_index in range(item.childCount()):
                child_item = item.child(child_index)
                if child_item is None:
                    continue
                child_data = child_item.data(0, Qt.ItemDataRole.UserRole) or {}
                remote_root = child_data.get("remote_root", "")
                mapped_local = child_item.text(1)
                if mapped_local and not mapped_local.startswith("[Not Mapped"):
                    mount_mappings[remote_root] = mapped_local

            if library_name not in self.staged_libraries:
                self.staged_libraries[library_name] = {
                    "type": library_type,
                    "management_type": "remote",
                    "agent_url": agent_url,
                    "remote_library_id": library_identifier,
                    "remote_root_path": root_paths[0] if root_paths else "",
                    "remote_root_paths": list(root_paths),
                    "mount_mappings": mount_mappings,
                    "paths": [
                        local_path
                        for local_path in mount_mappings.values()
                        if local_path
                    ],
                    "archive_paths": [],
                    "show_future_episodes": True,
                }
                logger.info(
                    "Enabled remote library '%s' from agent %s",
                    library_name,
                    agent_url,
                )
            else:
                self.staged_libraries[library_name]["management_type"] = "remote"
                self.staged_libraries[library_name]["agent_url"] = agent_url
                if "mount_mappings" not in self.staged_libraries[library_name]:
                    self.staged_libraries[library_name]["mount_mappings"] = (
                        mount_mappings
                    )
        else:
            item.setText(1, "Disabled")
            if (
                library_name in self.staged_libraries
                and self.staged_libraries[library_name].get("management_type")
                == "remote"
            ):
                del self.staged_libraries[library_name]
                logger.info(
                    "Disabled remote library '%s' from agent %s",
                    library_name,
                    agent_url,
                )

        self._refresh_library_order_list()
        self._refresh_tabs_list()
        self._refresh_library_selector()

    def map_local_mount_for_item(
        self, item: QTreeWidgetItem, local_mount_directory: str
    ) -> None:
        """Assigns a local directory mount point to a remote root directory item."""
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if (
            not isinstance(item_data, dict)
            or item_data.get("item_type") != "root_directory"
        ):
            return
        remote_root: str = item_data.get("remote_root", "")
        library_name: str = item_data.get("library_name", "")

        item.setText(1, local_mount_directory)
        logger.info(
            "Mapped remote root '%s' for library '%s' to local mount '%s'",
            remote_root,
            library_name,
            local_mount_directory,
        )

        if library_name in self.staged_libraries:
            mount_mappings = self.staged_libraries[library_name].setdefault(
                "mount_mappings", {}
            )
            mount_mappings[remote_root] = local_mount_directory
            paths = self.staged_libraries[library_name].setdefault("paths", [])
            if local_mount_directory not in paths:
                paths.append(local_mount_directory)

    @Slot()
    def map_local_mount_for_selected_item(self) -> None:
        """Opens directory browser to assign a local mount point to the selected remote root."""
        current_item = self.remote_agents_tree_widget.currentItem()
        if not current_item:
            QMessageBox.information(
                self,
                "Select Directory",
                "Please select a remote root directory under a library to map its local mount point.",
            )
            return
        item_data = current_item.data(0, Qt.ItemDataRole.UserRole)
        if (
            not isinstance(item_data, dict)
            or item_data.get("item_type") != "root_directory"
        ):
            QMessageBox.information(
                self,
                "Select Directory",
                "Please select a remote root directory under a library to map its local mount point.",
            )
            return

        remote_root = item_data.get("remote_root", "")
        local_directory = QFileDialog.getExistingDirectory(
            self, f"Select Local Mount Point for '{remote_root}'"
        )
        if local_directory:
            self.map_local_mount_for_item(current_item, local_directory)

    @Slot(QTreeWidgetItem, int)
    def _on_remote_tree_item_double_clicked(
        self, item: QTreeWidgetItem, column: int
    ) -> None:
        """Double clicking a root directory item opens the local mount directory picker."""
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if (
            isinstance(item_data, dict)
            and item_data.get("item_type") == "root_directory"
        ):
            remote_root = item_data.get("remote_root", "")
            local_directory = QFileDialog.getExistingDirectory(
                self, f"Select Local Mount Point for '{remote_root}'"
            )
            if local_directory:
                self.map_local_mount_for_item(item, local_directory)

    @Slot()
    def remove_selected_remote_agent(self) -> None:
        """Removes the selected scan agent and its remote libraries."""
        current_item = self.remote_agents_tree_widget.currentItem()
        if not current_item:
            return

        target_item: QTreeWidgetItem | None = current_item
        agent_url: str = ""
        while target_item is not None:
            item_data = target_item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(item_data, dict) and "agent_url" in item_data:
                agent_url = item_data["agent_url"]
                break
            target_item = target_item.parent()

        if not agent_url or agent_url not in self.staged_scan_agents:
            return

        del self.staged_scan_agents[agent_url]
        logger.info("Removed scan agent %s", agent_url)

        libraries_to_remove = [
            library_name
            for library_name, library_config in self.staged_libraries.items()
            if library_config.get("management_type") == "remote"
            and library_config.get("agent_url") == agent_url
        ]
        for library_name in libraries_to_remove:
            del self.staged_libraries[library_name]
            logger.info("Removed remote library '%s'", library_name)

        self._populate_remote_agents_tree()
        self._refresh_scan_agent_selectors()
        self._refresh_library_order_list()

    @Slot()
    def refresh_remote_agents(self) -> None:
        """Pings all configured scan agents and re-queries their library listings."""
        from lan_streamer.services.scan_agent_client import (
            ScanAgentConnectionError,
            scan_agent_client,
        )

        logger.info(
            "Refreshing reachability and libraries for all configured scan agents"
        )
        for agent_url, agent_data in list(self.staged_scan_agents.items()):
            try:
                health_data = scan_agent_client.check_agent_health(
                    agent_url, timeout=3.0
                )
                agent_data["reachable"] = True
                service_name = health_data.get("service")
                if service_name:
                    agent_data["name"] = service_name
                agent_data["discovered_libraries"] = (
                    scan_agent_client.fetch_agent_libraries(agent_url, timeout=4.0)
                )
            except (
                ScanAgentConnectionError,
                OSError,
                ValueError,
                RuntimeError,
            ):
                agent_data["reachable"] = False

        self._populate_remote_agents_tree()
        self._refresh_scan_agent_selectors()

    @Slot()
    def add_staged_scan_agent(self) -> None:
        """Legacy helper / test wrapper to add scan agent."""
        if not self.remote_agent_url_input.text() and hasattr(
            self, "scan_agent_url_input"
        ):
            self.remote_agent_url_input.setText(self.scan_agent_url_input.text())
        self.connect_to_agent()

    @Slot()
    def remove_staged_scan_agent(self) -> None:
        """Legacy helper / test wrapper to remove scan agent."""
        selected_agent = self.scan_agent_selector.currentData()
        if not selected_agent or selected_agent not in self.staged_scan_agents:
            selected_text = self.scan_agent_selector.currentText()
            for url, agent_dict in list(self.staged_scan_agents.items()):
                agent_name = str(agent_dict.get("name") or "")
                if url in selected_text or (agent_name and agent_name in selected_text):
                    selected_agent = url
                    break
        if selected_agent and selected_agent in self.staged_scan_agents:
            del self.staged_scan_agents[selected_agent]
            self._populate_remote_agents_tree()
            self._refresh_scan_agent_selectors()

    @Slot()
    def test_staged_scan_agent_connection(self) -> None:
        """Legacy helper / test wrapper to test connection."""
        self.refresh_remote_agents()

    def _refresh_scan_agent_selectors(self) -> None:
        """Refreshes legacy agent selectors for compatibility."""
        self.scan_agent_selector.blockSignals(True)
        self.scan_agent_selector.clear()
        self.remote_agent_selector.blockSignals(True)
        self.remote_agent_selector.clear()

        for url, agent_dict in sorted(self.staged_scan_agents.items()):
            display_text = f"{agent_dict.get('name', 'Agent')} ({url})"
            self.scan_agent_selector.addItem(display_text, url)
            self.remote_agent_selector.addItem(display_text, url)

        self.scan_agent_selector.blockSignals(False)
        self.remote_agent_selector.blockSignals(False)

    @Slot(str)
    def _on_remote_agent_changed(self, text: str) -> None:
        selected_library: str = self.library_selector.currentText()
        if selected_library in self.staged_libraries:
            agent_url = self.remote_agent_selector.currentData() or text
            self.staged_libraries[selected_library]["agent_url"] = agent_url

    @Slot()
    def fetch_remote_agent_libraries(self) -> None:
        self.refresh_remote_agents()

    @Slot(int)
    def _on_remote_library_selected(self, index: int) -> None:
        pass

    @Slot()
    def remove_staged_library(self) -> None:
        selected_library: str = self.library_selector.currentText()
        if not selected_library:
            return

        del self.staged_libraries[selected_library]
        self._refresh_library_selector()

    @Slot()
    def add_staged_directory(self) -> None:
        selected_library: str = self.library_selector.currentText()
        if not selected_library:
            QMessageBox.warning(
                self, "No Library Selected", "Please select or create a library first."
            )
            return

        chosen_directory: str = QFileDialog.getExistingDirectory(
            self, "Select Root Directory"
        )
        if not chosen_directory:
            return

        existing_paths: list[str] = self.staged_libraries[selected_library].get(
            "paths", []
        )
        if existing_paths:
            if chosen_directory in existing_paths:
                return
            confirmation_result = QMessageBox.question(
                self,
                "Replace Root Directory?",
                f"This library already has a root directory configured:\n\n{existing_paths[0]}\n\n"
                f"Libraries only support a single root directory. Would you like to replace it with:\n\n{chosen_directory}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmation_result != QMessageBox.StandardButton.Yes:
                return
            self.staged_libraries[selected_library]["archive_paths"] = []

        self.staged_libraries[selected_library]["paths"] = [chosen_directory]
        self._refresh_directory_list()

    @Slot()
    def remove_staged_directory(self) -> None:
        selected_library: str = self.library_selector.currentText()
        selected_item: QListWidgetItem | None = self.directory_list_widget.currentItem()
        if not selected_library or selected_item is None:
            return

        directory_path: str = selected_item.data(Qt.ItemDataRole.UserRole) or (
            selected_item.text().split("  ", 1)[-1]
            if "  " in selected_item.text()
            else selected_item.text()
        )
        configured_paths: list[str] = self.staged_libraries[selected_library].get(
            "paths", []
        )
        if directory_path in configured_paths:
            configured_paths.remove(directory_path)
            self.staged_libraries[selected_library]["paths"] = configured_paths
        else:
            self.staged_libraries[selected_library]["paths"] = []

        archive_paths: list[str] = self.staged_libraries[selected_library].get(
            "archive_paths", []
        )
        if directory_path in archive_paths:
            archive_paths.remove(directory_path)
            self.staged_libraries[selected_library]["archive_paths"] = archive_paths
        else:
            self.staged_libraries[selected_library]["archive_paths"] = []

        self._refresh_directory_list()

    @Slot()
    def browse_database_path(self) -> None:
        chosen_file, _ = QFileDialog.getSaveFileName(
            self,
            "Select Database File",
            self.db_path_input.text(),
            "Database Files (*.db);;All Files (*)",
        )
        if chosen_file:
            self.db_path_input.setText(chosen_file)

    @Slot()
    def browse_log_directory(self) -> None:
        chosen_dir: str = QFileDialog.getExistingDirectory(
            self, "Select Log Directory", self.log_dir_input.text()
        )
        if chosen_dir:
            self.log_dir_input.setText(chosen_dir)

    @Slot()
    def save_config(self) -> None:
        logger.info(
            "SettingsDialog save_config called to persist configuration settings"
        )
        db_freq = 0
        db_ret = 0
        with contextlib.suppress(ValueError):
            db_freq = int(self.database_backup_frequency_input.text().strip())
        with contextlib.suppress(ValueError):
            db_ret = int(self.database_backup_retention_input.text().strip())

        cfg_freq = 0
        cfg_ret = 0
        with contextlib.suppress(ValueError):
            cfg_freq = int(self.config_backup_frequency_input.text().strip())
        with contextlib.suppress(ValueError):
            cfg_ret = int(self.config_backup_retention_input.text().strip())

        warnings: list[str] = []
        if db_freq > 0 and db_ret < db_freq:
            warnings.append(
                f"- Database Backup Retention ({db_ret} days) is less than its backup frequency ({db_freq} days)."
            )
        if cfg_freq > 0 and cfg_ret < cfg_freq:
            warnings.append(
                f"- Config Backup Retention ({cfg_ret} days) is less than its backup frequency ({cfg_freq} days)."
            )

        if warnings:
            warning_text = (
                "The following backup settings have retention times less than their backup frequencies:\n\n"
                + "\n".join(warnings)
                + "\n\nThis may result in backup files being cleaned up before a new backup is created.\n\nDo you want to save these settings anyway?"
            )
            confirm = QMessageBox.question(
                self,
                "Backup Retention Warning",
                warning_text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm == QMessageBox.StandardButton.No:
                return

        config.jellyfin_url = self.jellyfin_url_input.text().strip()
        config.jellyfin_api_key = self.jellyfin_key_input.text().strip()
        config.tmdb_api_key = self.tmdb_key_input.text().strip()
        config.opensubtitles_username = self.opensubtitles_username_input.text().strip()
        config.opensubtitles_password = self.opensubtitles_password_input.text().strip()
        config.opensubtitles_api_key = self.opensubtitles_api_key_input.text().strip()
        config.myanimelist_client_id = self.myanimelist_client_id_input.text().strip()
        config.myanimelist_client_secret = (
            self.myanimelist_client_secret_input.text().strip()
        )
        config.sync_history_on_start = self.sync_history_on_start_checkbox.isChecked()
        config.check_for_updates_on_startup = (
            self.check_updates_startup_checkbox.isChecked()
        )
        config.update_release_channel = (
            "rc"
            if self.update_release_channel_selector.currentText()
            == "Release Candidates"
            else "stable"
        )

        config.use_embedded_player = self.use_embedded_checkbox.isChecked()
        config.enable_caching = self.enable_caching_checkbox.isChecked()
        config.enable_hw_accel = self.enable_hw_accel_checkbox.isChecked()
        config.enable_next_episode_popup = (
            self.enable_next_episode_popup_checkbox.isChecked()
        )
        try:
            parsed_threshold = float(self.watched_threshold_input.text().strip())
            if parsed_threshold > 1.0:
                config.watched_threshold = parsed_threshold / 100.0
            else:
                config.watched_threshold = parsed_threshold
        except ValueError:
            pass

        with contextlib.suppress(ValueError):
            config.max_cache_size_gb = float(self.max_cache_size_input.text().strip())

        with contextlib.suppress(ValueError):
            config.vlc_buffer_ms = int(self.vlc_buffer_input.text().strip())
        config.fullscreen_control_bar_position = (
            self.fullscreen_control_bar_position_selector.currentText()
        )
        config.subtitle_position = self.subtitle_position_selector.currentText()
        config.default_video_aspect_mode = (
            self.default_aspect_mode_selector.currentData() or "fit"
        )

        if self.db_path_input.text().strip():
            config.database_path = self.db_path_input.text().strip()
        if self.log_dir_input.text().strip():
            config.log_directory = self.log_dir_input.text().strip()

        config.log_level = self.log_level_selector.currentText()
        with contextlib.suppress(ValueError):
            config.max_log_retention_days = int(self.log_retention_input.text().strip())

        config.divide_logs_by_service = (
            self.log_saving_mode_selector.currentText() == "Divided Service Logs"
        )

        if self.backup_directory_input.text().strip():
            config.backup_directory = self.backup_directory_input.text().strip()

        with contextlib.suppress(ValueError):
            config.config_backup_frequency = int(
                self.config_backup_frequency_input.text().strip()
            )

        with contextlib.suppress(ValueError):
            config.database_backup_frequency = int(
                self.database_backup_frequency_input.text().strip()
            )

        with contextlib.suppress(ValueError):
            config.config_backup_retention = int(
                self.config_backup_retention_input.text().strip()
            )

        with contextlib.suppress(ValueError):
            config.database_backup_retention = int(
                self.database_backup_retention_input.text().strip()
            )

        config.auto_scan_enabled = self.auto_scan_checkbox.isChecked()
        config.scan_interval_hours = self.scan_interval_spinbox.value()
        config.scan_concurrency = self.scan_concurrency_spinbox.value()

        normalized_libraries, _ = split_multi_root_libraries(self.staged_libraries)
        config.libraries = normalized_libraries
        config.scan_agents = self.staged_scan_agents
        config.enable_combined_view = self.enable_combined_view_checkbox.isChecked()
        config.combined_views = self.staged_combined_views
        config.tabs = self.staged_tabs
        config.save()  # Persist startup-critical keys to config file
        config.save_to_db()  # Persist all DB-backed keys to database

        # Restart the scheduled scan service with the new settings
        if self.controller is not None:
            self.controller.scheduled_scan_service.stop()
            self.controller.scheduled_scan_service.interval_seconds = (
                float(config.scan_interval_hours) * 3600.0
            )
            if config.auto_scan_enabled:
                self.controller.start_scheduled_scans()

        from lan_streamer.system.logging_handler import set_application_log_level

        set_application_log_level(config.log_level)
        self.accept()

    @Slot()
    def link_myanimelist_account(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        from lan_streamer.ui_views.proxy import myanimelist_client

        client_id = self.myanimelist_client_id_input.text().strip()
        client_secret = self.myanimelist_client_secret_input.text().strip()
        if not client_id:
            QMessageBox.warning(
                self, "MyAnimeList Configuration", "Please enter a Client ID."
            )
            return

        config.myanimelist_client_id = client_id
        config.myanimelist_client_secret = client_secret
        config.save_to_db()

        import secrets
        import string

        chars = string.ascii_letters + string.digits
        code_verifier = "".join(secrets.choice(chars) for _ in range(128))

        auth_url = myanimelist_client.generate_auth_url(code_verifier)

        import webbrowser

        webbrowser.open(auth_url)

        text, ok = QInputDialog.getText(
            self,
            "Link MyAnimeList Account",
            "An authorization page has been opened in your browser.\n\n"
            "1. Sign in to MyAnimeList and click 'Allow' to authorize the app.\n"
            "2. The browser will then redirect to a blank page starting with 'http://localhost/?code=...'.\n"
            "   (Make sure your App Redirect URL in MyAnimeList is exactly 'http://localhost/')\n"
            "3. Copy that final redirected URL from your browser's address bar and paste it below:\n\n"
            "(Do NOT copy the initial MyAnimeList sign-in page URL)",
        )
        if not ok or not text.strip():
            return

        from urllib.parse import parse_qs, urlparse

        if (
            "myanimelist.net/v1/oauth2/authorize" in text
            or "response_type=code" in text
        ):
            QMessageBox.warning(
                self,
                "Link MyAnimeList Account",
                "It looks like you copied the initial authorization URL by mistake.\n\n"
                "You must sign in and approve the application in the browser first, "
                "then copy the final redirect URL (starting with http://localhost/?code=...) "
                "and paste it here.",
            )
            return

        query = urlparse(text).query
        params = parse_qs(query)
        code_list = params.get("code")
        code = code_list[0].strip() if code_list else text.strip()

        if not code or code.startswith("http"):
            QMessageBox.warning(
                self,
                "Link MyAnimeList Account",
                "Could not find authorization code in the provided URL/text.\n\n"
                "Make sure you copy the final redirect URL starting with 'http://localhost/?code=' after authorizing.",
            )
            return

        success, msg = myanimelist_client.exchange_auth_code(code, code_verifier)
        if success:
            QMessageBox.information(self, "Link MyAnimeList Account", msg)
        else:
            QMessageBox.critical(self, "Link MyAnimeList Account", msg)

        self._update_mal_status_ui()

    @Slot()
    def unlink_myanimelist_account(self) -> None:
        from lan_streamer.ui_views.proxy import myanimelist_client

        confirm = QMessageBox.question(
            self,
            "Remove MyAnimeList Connection",
            "Are you sure you want to disconnect MyAnimeList? This will clear your authentication credentials.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            myanimelist_client.remove_connection()
            self._update_mal_status_ui()

    def _update_mal_status_ui(self) -> None:
        from lan_streamer.ui_views.proxy import myanimelist_client

        if myanimelist_client.is_authenticated():
            self.myanimelist_status_label.setText("Status: Connected")
            self.myanimelist_status_label.setStyleSheet("color: #4caf50;")
            self.myanimelist_unlink_button.setVisible(True)
        else:
            self.myanimelist_status_label.setText("Status: Not connected")
            self.myanimelist_status_label.setStyleSheet("color: #e53935;")
            self.myanimelist_unlink_button.setVisible(False)

    @Slot(int)
    def _on_anime_library_toggled(self, state: int) -> None:
        selected_library: str = self.library_selector.currentText()
        if selected_library in self.staged_libraries:
            lib_config = self.staged_libraries[selected_library]
            is_anime = self.anime_library_checkbox.isChecked()
            lib_config["type"] = "anime" if is_anime else "tv"
            self._refresh_library_options()

    @Slot()
    def browse_backup_directory(self) -> None:
        chosen_directory: str = QFileDialog.getExistingDirectory(
            self, "Select Backup Directory", self.backup_directory_input.text()
        )
        if chosen_directory:
            self.backup_directory_input.setText(chosen_directory)

    @Slot()
    def trigger_restore_config(self) -> None:
        chosen_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Configuration Backup to Restore",
            self.backup_directory_input.text(),
            "JSON Files (*.json);;All Files (*)",
        )
        if chosen_file:
            from lan_streamer.system.backup import restore_config_backup

            success: bool = restore_config_backup(chosen_file)
            if success:
                QMessageBox.information(
                    self,
                    "Restore Successful",
                    "Configuration successfully restored and reloaded.",
                )
                self._load_config()
            else:
                QMessageBox.critical(
                    self,
                    "Restore Failed",
                    "Failed to restore configuration. Ensure the file is valid.",
                )

    @Slot()
    def trigger_restore_database(self) -> None:
        chosen_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Database Backup to Restore",
            self.backup_directory_input.text(),
            "Database Files (*.db);;All Files (*)",
        )
        if chosen_file:
            from lan_streamer.system.backup import restore_database_backup

            success: bool = restore_database_backup(chosen_file)
            if success:
                QMessageBox.information(
                    self,
                    "Restore Successful",
                    "Database successfully restored from backup.",
                )
            else:
                QMessageBox.critical(
                    self,
                    "Restore Failed",
                    "Failed to restore database. Ensure the file is uncorrupted.",
                )

    @Slot(str, int, int)
    def _on_global_progress(
        self, library_name: str, completed_count: int, total_count: int
    ) -> None:
        self.global_progress_bar.setVisible(True)
        self.global_progress_bar.mark_library_done(library_name)

    @Slot(str, dict)
    def _on_detail_progress(self, event: str, payload: dict[str, Any]) -> None:
        """Routes granular scan events to the SegmentedProgressBar and ScanProgressTree."""
        library = payload.get("library", "")
        root = payload.get("root", "")
        folder = payload.get("folder", "")
        season = payload.get("season", "")
        file_path = payload.get("file", "")

        if event == "init_tree":
            tree = payload.get("tree", {})
            library_order = payload.get("library_order") or list(
                self.staged_libraries.keys()
            )
            self.global_progress_bar.init_from_tree(
                tree, library_order, self.staged_libraries
            )
            self.scan_progress_tree.init_from_tree(
                tree, library_order, self.staged_libraries
            )
            self.global_progress_bar.setVisible(True)
            if self._scan_running:
                self.scan_progress_tree.setVisible(False)
                self.scan_report_display.setVisible(True)
            else:
                self.scan_progress_tree.setVisible(True)
                self.scan_report_display.setVisible(False)

        elif event == "start_library":
            self.global_progress_bar.mark_library_active(library)
            self.scan_progress_tree.mark_library_active(library)

        elif event == "finish_library":
            self.global_progress_bar.mark_library_done(library)
            self.scan_progress_tree.mark_library_done(library)

        elif event == "fail_library":
            self.global_progress_bar.mark_library_failed(library)
            self.scan_progress_tree.mark_library_failed(library)

        elif event == "start_folder":
            self.global_progress_bar.advance_root(root)
            self.scan_progress_tree.mark_folder_active(library, root, folder)

        elif event == "finish_folder":
            skipped = payload.get("skipped", False)
            self.scan_progress_tree.mark_folder_done(
                library, root, folder, skipped=skipped
            )

        elif event == "start_season":
            self.scan_progress_tree.mark_season_active(library, folder, season)

        elif event == "finish_season":
            self.scan_progress_tree.mark_season_done(library, folder, season)

        elif event == "start_file":
            self.scan_progress_tree.mark_file_active(file_path, library, folder, season)

        elif event == "finish_file":
            self.scan_progress_tree.mark_file_done(file_path)

        elif event == "start_offline_scan":
            self.global_progress_bar.set_current_pass(1)

        elif event == "start_metadata_resolution":
            self.global_progress_bar.set_current_pass(2)

        elif event == "runtime_extraction_progress":
            completed = payload.get("completed", 0)
            total = payload.get("total", 0)
            self.global_progress_bar.set_pass3_progress(completed, total)

    @Slot()
    def _on_scan_completed(self) -> None:
        self._scan_running = False
        self.scan_report_display.moveCursor(QTextCursor.MoveOperation.End)
        self.scan_report_display.insertPlainText("\n*** SCAN COMPLETED ***\n")
        self.scan_files_button.setVisible(True)
        self.passes_frame.setVisible(True)
        self.pull_watch_history_button.setVisible(True)
        self.push_watch_history_button.setVisible(True)
        self.scan_detail_label.setText("Scan Detail:")

    def _show_scan_progress_widgets(self) -> None:
        self.scan_progress_tree.reset()
        self.scan_progress_tree.setVisible(False)
        self.scan_report_display.clear()
        self.scan_report_display.setVisible(True)
        self.global_progress_bar.setVisible(True)
        self._scan_running = True
        self.current_scan_logs = []
        self._appended_report_lines = set()
        self.scan_files_button.setVisible(False)
        self.passes_frame.setVisible(False)
        self.pull_watch_history_button.setVisible(False)
        self.push_watch_history_button.setVisible(False)
        self.scan_detail_label.setText("Scan Report:")

    @Slot()
    def trigger_full_scan_files(self) -> None:
        if self.controller is not None:
            target_library: str = (
                self.scan_target_library_combobox.currentText().strip()
            )
            self._show_scan_progress_widgets()
            if target_library:
                self.controller.trigger_scan(
                    force_refresh=False,
                    library_name=target_library,
                    run_pass1=True,
                    run_pass2=True,
                    chain_pass3=True,
                    chain_cleanup=True,
                )
            else:
                self.controller.trigger_scan_all(
                    force_refresh=False,
                    run_pass1=True,
                    run_pass2=True,
                    chain_pass3=True,
                    chain_cleanup=True,
                )

    @Slot()
    def trigger_pass1_scan(self) -> None:
        if self.controller is not None:
            target_library: str = (
                self.scan_target_library_combobox.currentText().strip()
            )
            self._show_scan_progress_widgets()
            force_refresh = self.force_file_scan_checkbox.isChecked()
            if target_library:
                self.controller.trigger_scan(
                    force_refresh=force_refresh,
                    library_name=target_library,
                    run_pass1=True,
                    run_pass2=False,
                    chain_pass3=False,
                    chain_cleanup=False,
                )
            else:
                self.controller.trigger_scan_all(
                    force_refresh=force_refresh,
                    run_pass1=True,
                    run_pass2=False,
                    chain_pass3=False,
                    chain_cleanup=False,
                )

    @Slot()
    def trigger_pass2_scan(self) -> None:
        if self.controller is not None:
            target_library: str = (
                self.scan_target_library_combobox.currentText().strip()
            )
            self._show_scan_progress_widgets()
            force_refresh = self.force_metadata_checkbox.isChecked()
            if target_library:
                self.controller.trigger_scan(
                    force_refresh=force_refresh,
                    library_name=target_library,
                    run_pass1=False,
                    run_pass2=True,
                    chain_pass3=False,
                    chain_cleanup=False,
                )
            else:
                self.controller.trigger_scan_all(
                    force_refresh=force_refresh,
                    run_pass1=False,
                    run_pass2=True,
                    chain_pass3=False,
                    chain_cleanup=False,
                )

    @Slot()
    def trigger_pass3_scan(self) -> None:
        if self.controller is not None:
            self._show_scan_progress_widgets()
            force_refresh = self.force_runtime_checkbox.isChecked()
            self.controller.trigger_runtime_extraction(force_refresh=force_refresh)

    @Slot()
    def trigger_garbage_cleanup(self) -> None:
        if self.controller is not None:
            target_library: str = (
                self.scan_target_library_combobox.currentText().strip()
            )
            self._show_scan_progress_widgets()
            if target_library:
                self.controller.trigger_cleanup(library_name=target_library)
            else:
                self.controller.trigger_global_cleanup()

    @Slot()
    def trigger_global_jellyfin_pull(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.controller.trigger_jellyfin_pull()
            QTimer.singleShot(
                2000,
                lambda: self._complete_jellyfin_progress("Jellyfin pull completed."),
            )

    @Slot()
    def trigger_global_jellyfin_push(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.controller.trigger_jellyfin_push()
            QTimer.singleShot(
                2000,
                lambda: self._complete_jellyfin_progress("Jellyfin push completed."),
            )

    def _complete_jellyfin_progress(self, message_text: str) -> None:
        pass  # Segmented bar has no text format; completion is driven by mark_library_done

    @Slot()
    def trigger_manual_update_check(self) -> None:
        logger.info("Manual update check triggered")
        self.check_updates_now_button.setEnabled(False)
        self.check_updates_now_button.setText("Checking...")

        self.update_check_worker = UpdateCheckWorker(
            release_channel=config.update_release_channel
        )

        def on_check_finished(
            success: bool, release_info: dict, error_msg: str
        ) -> None:
            self.check_updates_now_button.setEnabled(True)
            self.check_updates_now_button.setText("Check for Updates Now")

            if success:
                if release_info:
                    dialog = UpdateDialog(
                        current_version=__version__,
                        new_version=release_info["version"],
                        release_notes=release_info["release_notes"],
                        download_url=release_info["download_url"],
                        parent=self,
                    )
                    dialog.exec()
                else:
                    QMessageBox.information(
                        self,
                        "No Updates",
                        "You are running the latest version of LAN Streamer.",
                    )
            else:
                QMessageBox.warning(
                    self,
                    "Update Check Failed",
                    f"Could not check for updates:\n{error_msg}",
                )

        self.update_check_worker.finished.connect(on_check_finished)
        self.update_check_worker.start()

    @Slot(str)
    def _on_log_filter_changed(self, text: str) -> None:
        self._refresh_log_display()

    @Slot()
    def _clear_log_view(self) -> None:
        self.all_log_records.clear()
        self._refresh_log_display()

    @Slot()
    def _copy_logs_to_clipboard(self) -> None:
        from PySide6.QtWidgets import QApplication

        log_text: str = "\n".join(
            [formatted_message for formatted_message, _ in self.all_log_records]
        )
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(log_text)

    @Slot()
    def _export_logs(self) -> None:
        log_dir = Path(config.log_directory)
        if not log_dir.is_dir():
            QMessageBox.warning(
                self,
                "Export Failed",
                f"Log directory does not exist or is not a directory: {log_dir}",
            )
            return

        log_files = [f for f in log_dir.glob("*.log*") if f.is_file()]
        if not log_files:
            QMessageBox.warning(
                self,
                "Export Failed",
                f"No log files found in the log directory: {log_dir}",
            )
            return

        try:
            home_dir = Path.home()
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            zip_filename = f"lan_streamer_logs_{timestamp}.zip"
            zip_filepath = home_dir / zip_filename

            with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for file_path in log_files:
                    zip_file.write(file_path, arcname=file_path.name)

            QMessageBox.information(
                self,
                "Export Successful",
                f"Logs successfully exported to:\n{zip_filepath}",
            )
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred while exporting logs:\n{e}",
            )

    def _refresh_log_display(self) -> None:
        self.log_display.clear()
        search_term: str = self.log_search_input.text().strip().lower()
        selected_level: str = self.log_level_filter.currentText()
        level_threshold: int = self._get_level_value(selected_level)
        matching_lines: list[str] = []
        for formatted_message, level_name in self.all_log_records:
            record_level_val: int = self._get_level_value(level_name)
            if record_level_val < level_threshold:
                continue
            if search_term and search_term not in formatted_message.lower():
                continue
            html_line: str = self._format_log_to_html(formatted_message, level_name)
            matching_lines.append(html_line)
        self.log_display.appendHtml("<br>".join(matching_lines))
        if self.log_autoscroll_checkbox.isChecked():
            self._scroll_to_bottom()

    def _get_level_value(self, level_name: str) -> int:
        levels: dict[str, int] = {
            "DEBUG": 10,
            "INFO": 20,
            "WARNING": 30,
            "ERROR": 40,
            "CRITICAL": 50,
        }
        return levels.get(level_name.upper(), 0)

    def _format_log_to_html(self, message: str, level_name: str) -> str:
        escaped_message: str = html.escape(message)
        colors: dict[str, str] = {
            "DEBUG": "#7f8c8d",
            "INFO": "#2ecc71",
            "WARNING": "#f1c40f",
            "ERROR": "#e74c3c",
            "CRITICAL": "#e74c3c; font-weight: bold; background-color: #2c3e50;",
        }
        color: str = colors.get(level_name.upper(), "#ffffff")
        level_tag: str = f"[{level_name}]"
        colored_tag: str = (
            f'<span style="color: {color}; font-weight: bold;">{level_tag}</span>'
        )
        return escaped_message.replace(level_tag, colored_tag, 1)

    @Slot(str, str)
    def _on_log_emitted(self, formatted_message: str, level_name: str) -> None:
        self.all_log_records.append((formatted_message, level_name))
        if len(self.all_log_records) > 1000:
            self.all_log_records.pop(0)

        if self._scan_running:

            def is_separator(text: str) -> bool:
                stripped = text.strip()
                if not stripped:
                    return True
                return all(c in "=-*_" for c in stripped)

            if "[SCAN_REPORT]" in formatted_message:
                idx = formatted_message.index("[SCAN_REPORT]")
                content = formatted_message[idx + len("[SCAN_REPORT]") :]
                content = content.removeprefix(" ")
                if is_separator(content) or content not in self._appended_report_lines:
                    if not is_separator(content):
                        self._appended_report_lines.add(content)
                    self.scan_report_display.moveCursor(QTextCursor.MoveOperation.End)
                    self.scan_report_display.insertPlainText(content + "\n")
                    self.current_scan_logs.append(formatted_message)
                else:
                    # Repeated content (e.g. same stats value in multiple
                    # sections) — still show it but don't add to dedup set
                    # so identical values in PASS 2 or TOTAL are not hidden.
                    self.scan_report_display.moveCursor(QTextCursor.MoveOperation.End)
                    self.scan_report_display.insertPlainText(content + "\n")
            elif "[SCAN_ISSUE]" in formatted_message:
                idx = formatted_message.index("[SCAN_ISSUE]")
                content = (
                    "ISSUE: " + formatted_message[idx + len("[SCAN_ISSUE]") :].strip()
                )
                if is_separator(content) or content not in self._appended_report_lines:
                    if not is_separator(content):
                        self._appended_report_lines.add(content)
                    self.scan_report_display.moveCursor(QTextCursor.MoveOperation.End)
                    self.scan_report_display.insertPlainText(content + "\n")
                    self.current_scan_logs.append(formatted_message)

        search_term: str = self.log_search_input.text().strip().lower()
        selected_level: str = self.log_level_filter.currentText()
        level_threshold: int = self._get_level_value(selected_level)
        record_level_val: int = self._get_level_value(level_name)
        if record_level_val >= level_threshold and (
            not search_term or search_term in formatted_message.lower()
        ):
            html_line: str = self._format_log_to_html(formatted_message, level_name)
            self.log_display.appendHtml(html_line)
            if self.log_autoscroll_checkbox.isChecked():
                self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        self.log_display.moveCursor(QTextCursor.MoveOperation.End)

    def _disconnect_signals(self) -> None:
        """Disconnect all controller and log signals to prevent use-after-free."""
        if self.controller is not None:
            with contextlib.suppress(Exception):
                self.controller.global_progress_updated.disconnect(
                    self._on_global_progress
                )
            with contextlib.suppress(Exception):
                self.controller.detail_progress_updated.disconnect(
                    self._on_detail_progress
                )
            with contextlib.suppress(Exception):
                self.controller.scan_completed.disconnect(self._on_scan_completed)
        if getattr(self, "_logging_connected", False):
            try:
                from lan_streamer.system.logging_handler import qt_log_handler

                qt_log_handler.emitter.log_emitted.disconnect(self._on_log_emitted)
            except RuntimeError, ImportError, SystemError:
                pass
            self._logging_connected = False

    def closeEvent(self, event: QCloseEvent) -> None:
        self._disconnect_signals()
        super().closeEvent(event)

    def accept(self) -> None:
        self._disconnect_signals()
        super().accept()

    def reject(self) -> None:
        self._disconnect_signals()
        super().reject()
