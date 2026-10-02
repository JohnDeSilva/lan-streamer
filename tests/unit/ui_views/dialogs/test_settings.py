from unittest.mock import patch

from lan_streamer.system.config import config
from lan_streamer.ui_views import SettingsDialog


def test_settings_dialog_library_scan_order(qtbot) -> None:
    # Set up staged_libraries with initial order
    initial_libraries = {
        "Movies": {"type": "movie", "paths": ["/movies"]},
        "TV Shows": {"type": "tv", "paths": ["/tv"]},
        "Anime": {"type": "tv", "paths": ["/anime"]},
    }

    with patch.dict(config.libraries, initial_libraries, clear=True):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)

        # Verify initial order in list widget
        list_widget = dialog.library_order_list_widget
        assert list_widget.count() == 3
        assert list_widget.item(0).text() == "Movies"
        assert list_widget.item(1).text() == "TV Shows"
        assert list_widget.item(2).text() == "Anime"

        # Select "TV Shows" (index 1) and move it up
        list_widget.setCurrentRow(1)
        dialog.move_library_order_up()

        # Verify new order in list widget
        assert list_widget.item(0).text() == "TV Shows"
        assert list_widget.item(1).text() == "Movies"
        assert list_widget.item(2).text() == "Anime"

        # Verify self.staged_libraries has keys in the new order
        staged_keys = list(dialog.staged_libraries.keys())
        assert staged_keys == ["TV Shows", "Movies", "Anime"]

        # Move "Movies" (index 1) down
        list_widget.setCurrentRow(1)
        dialog.move_library_order_down()

        # Verify new order
        assert list_widget.item(0).text() == "TV Shows"
        assert list_widget.item(1).text() == "Anime"
        assert list_widget.item(2).text() == "Movies"

        staged_keys = list(dialog.staged_libraries.keys())
        assert staged_keys == ["TV Shows", "Anime", "Movies"]

        # Call save_config and check that config.libraries gets updated
        with patch.object(config, "save") as mock_save:
            dialog.save_config()
            assert list(config.libraries.keys()) == ["TV Shows", "Anime", "Movies"]
            mock_save.assert_called_once()

        dialog.reject()


def test_settings_dialog_combined_view_comboboxes(qtbot) -> None:
    from lan_streamer.ui_views.dialogs.settings import SettingsDialog

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    # Verify "Next Up" is present in Sort By options
    sort_items = [
        dialog.row_sort_selector.itemText(i)
        for i in range(dialog.row_sort_selector.count())
    ]
    assert "Next Up" in sort_items

    # Verify "Next Up" is NOT present in Filter Mode options
    filter_items = [
        dialog.row_filter_selector.itemText(i)
        for i in range(dialog.row_filter_selector.count())
    ]
    assert "Next Up" not in filter_items

    dialog.reject()


def test_settings_dialog_vlc_buffer(qtbot) -> None:
    from lan_streamer.system.config import config
    from lan_streamer.ui_views.dialogs.settings import SettingsDialog

    config.vlc_buffer_ms = 4000
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    # Check that the input box has the correct initial value
    assert dialog.vlc_buffer_input.text() == "4000"

    # Modify value
    dialog.vlc_buffer_input.setText("8000")

    # Save and verify
    with patch.object(config, "save") as mock_save:
        dialog.save_config()
        assert config.vlc_buffer_ms == 8000
        mock_save.assert_called_once()

    dialog.reject()


def test_settings_dialog_sync_history_on_start(qtbot) -> None:
    from lan_streamer.system.config import config
    from lan_streamer.ui_views.dialogs.settings import SettingsDialog

    config.sync_history_on_start = True
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    # Check that the checkbox has the correct initial value
    assert dialog.sync_history_on_start_checkbox.isChecked() is True

    # Modify value
    dialog.sync_history_on_start_checkbox.setChecked(False)

    # Save and verify
    with patch.object(config, "save") as mock_save:
        dialog.save_config()
        assert config.sync_history_on_start is False
        mock_save.assert_called_once()

    dialog.reject()


def test_settings_dialog_anime_library_toggle(qtbot) -> None:
    from lan_streamer.system.config import config
    from lan_streamer.ui_views.dialogs.settings import SettingsDialog

    initial_libraries = {
        "TV Shows": {"type": "tv", "paths": ["/tv"]},
        "Movies": {"type": "movie", "paths": ["/movies"]},
    }

    with patch.dict(config.libraries, initial_libraries, clear=True):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)

        # Select "TV Shows" (type "tv")
        dialog.library_selector.setCurrentText("TV Shows")
        assert not dialog.anime_library_checkbox.isHidden()
        assert dialog.anime_library_checkbox.isChecked() is False

        # Toggle it on (turns TV Show to Anime)
        dialog.anime_library_checkbox.setChecked(True)
        assert dialog.staged_libraries["TV Shows"]["type"] == "anime"
        assert dialog.anime_library_checkbox.isChecked() is True

        # Toggle it off (turns Anime to TV Show)
        dialog.anime_library_checkbox.setChecked(False)
        assert dialog.staged_libraries["TV Shows"]["type"] == "tv"
        assert dialog.anime_library_checkbox.isChecked() is False

        # Select "Movies" (type "movie") - should hide the checkbox
        dialog.library_selector.setCurrentText("Movies")
        assert dialog.anime_library_checkbox.isHidden()

        dialog.reject()


def test_settings_dialog_scan_report_view(qtbot) -> None:
    from lan_streamer.ui_views.dialogs.settings import SettingsDialog

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    # Initially hidden
    assert dialog.scan_report_display is not None
    assert dialog.scan_report_display.isReadOnly()
    assert dialog.scan_report_display.isHidden()

    # Trigger scan view transition
    dialog._show_scan_progress_widgets()
    assert dialog._scan_running is True
    assert dialog.scan_progress_tree.isHidden()
    assert not dialog.scan_report_display.isHidden()

    # Simulate logs emitted
    dialog._on_log_emitted(
        "2026-06-12 11:09:44,123 [INFO] lan_streamer.backend: [SCAN_REPORT] Series Added: 5",
        "INFO",
    )
    dialog._on_log_emitted(
        "2026-06-12 11:09:44,123 [WARNING] lan_streamer.backend: [SCAN_ISSUE] Type=Database Write Failure | Item=Season 'Season 1' | Error=DB lock",
        "WARNING",
    )

    report_text = dialog.scan_report_display.toPlainText()
    assert "Series Added: 5" in report_text
    assert (
        "ISSUE: Type=Database Write Failure | Item=Season 'Season 1' | Error=DB lock"
        in report_text
    )

    # Complete scan
    dialog._on_scan_completed()
    assert dialog._scan_running is False
    assert "*** SCAN COMPLETED ***" in dialog.scan_report_display.toPlainText()

    dialog.reject()


def test_settings_dialog_add_local_library(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    # 1. Create a local library
    dialog.library_name_input.setText("Local Anime")
    dialog.library_type_input.setCurrentText("Anime")
    dialog.add_staged_library()

    assert "Local Anime" in dialog.staged_libraries
    assert dialog.staged_libraries["Local Anime"]["type"] == "anime"
    assert dialog.staged_libraries["Local Anime"]["management_type"] == "local"

    # Verify it is listed in the local library selector
    selector_items = [
        dialog.library_selector.itemText(i)
        for i in range(dialog.library_selector.count())
    ]
    assert "Local Anime" in selector_items

    dialog.reject()


def test_settings_dialog_remote_libraries_tab_flow(qtbot) -> None:
    from PySide6.QtCore import Qt

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    mock_health = {"status": "ok", "service": "Storage NAS Agent", "libraries": 1}
    mock_libraries = [
        {
            "id": "lib-nas-1",
            "name": "NAS TV",
            "type": "tv",
            "root_path": "/storage/tv",
            "root_paths": ["/storage/tv"],
        }
    ]

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.check_agent_health",
            return_value=mock_health,
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_libraries",
            return_value=mock_libraries,
        ),
    ):
        dialog.remote_agent_url_input.setText("http://127.0.0.1:8800")
        dialog.connect_to_agent()
        qtbot.waitUntil(
            lambda: "http://127.0.0.1:8800" in dialog.staged_scan_agents,
            timeout=5000,
        )

    # Agent node assertions
    tree = dialog.remote_agents_tree_widget
    assert tree.topLevelItemCount() == 1
    agent_item = tree.topLevelItem(0)
    assert agent_item is not None
    assert "🟢" in agent_item.text(0)
    assert "Storage NAS Agent" in agent_item.text(0)
    assert agent_item.text(1) == "Status: Reachable"

    # Library node assertions
    assert agent_item.childCount() == 1
    library_item = agent_item.child(0)
    assert library_item is not None
    assert "NAS TV" in library_item.text(0)
    assert library_item.text(1) == "Disabled"
    assert library_item.checkState(0) == Qt.CheckState.Unchecked

    # Root directory node assertions
    assert library_item.childCount() == 1
    root_item = library_item.child(0)
    assert "📁 /storage/tv" in root_item.text(0)

    # Manage agent dialog opening
    with patch.object(dialog, "open_agent_management_dialog") as mock_dialog_open:
        dialog.remote_agents_tree_widget.setCurrentItem(agent_item)
        dialog.open_selected_agent_management_dialog()
        mock_dialog_open.assert_called_once_with("http://127.0.0.1:8800")

    # Enable library via checkbox
    library_item.setCheckState(0, Qt.CheckState.Checked)
    assert "NAS TV" in dialog.staged_libraries
    assert dialog.staged_libraries["NAS TV"]["management_type"] == "remote"
    assert library_item.text(1) == "Enabled"

    # Map local mount
    dialog.map_local_mount_for_item(root_item, "/mnt/nas/tv")
    assert root_item.text(1) == "/mnt/nas/tv"
    assert dialog.staged_libraries["NAS TV"]["mount_mappings"] == {
        "/storage/tv": "/mnt/nas/tv"
    }

    # Disable library via checkbox
    library_item.setCheckState(0, Qt.CheckState.Unchecked)
    assert "NAS TV" not in dialog.staged_libraries
    assert library_item.text(1) == "Disabled"

    # Re-enable library
    library_item.setCheckState(0, Qt.CheckState.Checked)
    assert "NAS TV" in dialog.staged_libraries

    # Remove agent
    tree.setCurrentItem(agent_item)
    dialog.remove_selected_remote_agent()
    assert tree.topLevelItemCount() == 0
    assert "http://127.0.0.1:8800" not in dialog.staged_scan_agents
    assert "NAS TV" not in dialog.staged_libraries

    dialog.reject()


def test_settings_dialog_remote_agent_unreachable(qtbot) -> None:
    from lan_streamer.services.scan_agent_client import ScanAgentConnectionError

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.check_agent_health",
            side_effect=ScanAgentConnectionError("Connection refused"),
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_libraries",
            return_value=[],
        ),
        patch(
            "lan_streamer.ui_views.dialogs.settings.QMessageBox.warning"
        ) as mock_warn,
    ):
        dialog.remote_agent_url_input.setText("http://127.0.0.1:8800")
        dialog.connect_to_agent()
        qtbot.waitUntil(
            lambda: "http://127.0.0.1:8800" in dialog.staged_scan_agents,
            timeout=5000,
        )
        mock_warn.assert_called_once()

    tree = dialog.remote_agents_tree_widget
    assert tree.topLevelItemCount() == 1
    agent_item = tree.topLevelItem(0)
    assert agent_item is not None
    assert "🔴" in agent_item.text(0)
    dialog.reject()


def test_settings_dialog_add_multiple_root_directories(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.library_name_input.setText("MultiRootLib")
    dialog.add_staged_library()

    assert "MultiRootLib" in dialog.staged_libraries
    assert dialog.staged_libraries["MultiRootLib"]["paths"] == []

    # 1. Add first directory
    with patch(
        "lan_streamer.ui_views.dialogs.settings.QFileDialog.getExistingDirectory",
        return_value="/root/one",
    ):
        dialog.add_staged_directory()

    assert dialog.staged_libraries["MultiRootLib"]["paths"] == ["/root/one"]

    # 2. Add second directory (no replace dialog; appends to multi-root list)
    with patch(
        "lan_streamer.ui_views.dialogs.settings.QFileDialog.getExistingDirectory",
        return_value="/root/two",
    ):
        dialog.add_staged_directory()

    assert dialog.staged_libraries["MultiRootLib"]["paths"] == [
        "/root/one",
        "/root/two",
    ]

    # 3. Remove the first directory
    dialog.directory_list_widget.setCurrentRow(0)
    dialog.remove_staged_directory()
    assert dialog.staged_libraries["MultiRootLib"]["paths"] == ["/root/two"]

    dialog.reject()


def test_settings_dialog_library_selector_includes_remote_and_local(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.staged_libraries = {
        "Local TV": {"type": "tv", "management_type": "local", "paths": ["/local/tv"]},
        "Remote Movies": {
            "type": "movie",
            "management_type": "remote",
            "paths": [],
            "agent_url": "http://127.0.0.1:8800",
        },
    }
    dialog._refresh_library_selector()

    combo_items = [
        dialog.library_selector.itemText(index)
        for index in range(dialog.library_selector.count())
    ]
    assert "Local TV" in combo_items
    assert "Remote Movies" in combo_items


def test_settings_dialog_library_order_list_syncs_with_selector(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.staged_libraries = {
        "Library A": {"type": "tv", "management_type": "local", "paths": ["/path/a"]},
        "Library B": {
            "type": "movie",
            "management_type": "local",
            "paths": ["/path/b"],
        },
    }
    dialog._refresh_library_selector()

    # Selecting item in library_order_list_widget should update library_selector
    dialog.library_order_list_widget.setCurrentRow(1)
    assert dialog.library_selector.currentText() == "Library B"

    # Selecting item in library_selector should update library_order_list_widget
    dialog.library_selector.setCurrentText("Library A")
    assert dialog.library_order_list_widget.currentItem() is not None
    assert dialog.library_order_list_widget.currentItem().text() == "Library A"


def test_settings_dialog_rename_library(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.staged_libraries = {
        "Original Name": {
            "type": "tv",
            "management_type": "local",
            "paths": ["/path/tv"],
        },
    }
    dialog._refresh_library_selector()
    dialog.library_selector.setCurrentText("Original Name")

    with patch(
        "lan_streamer.ui_views.dialogs.settings.QInputDialog.getText",
        return_value=("Renamed Name", True),
    ):
        dialog.rename_staged_library()

    assert "Original Name" not in dialog.staged_libraries
    assert "Renamed Name" in dialog.staged_libraries
    assert dialog.library_selector.currentText() == "Renamed Name"
    assert dialog.renamed_libraries.get("Original Name") == "Renamed Name"


def test_settings_dialog_change_library_type(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.staged_libraries = {
        "My Media": {
            "type": "tv",
            "management_type": "local",
            "paths": ["/path/media"],
        },
    }
    dialog._refresh_library_selector()
    dialog.library_selector.setCurrentText("My Media")

    assert dialog.selected_library_type_combobox.currentText() == "TV Shows"

    dialog.selected_library_type_combobox.setCurrentText("Movies")
    assert dialog.staged_libraries["My Media"]["type"] == "movie"

    dialog.selected_library_type_combobox.setCurrentText("Anime")
    assert dialog.staged_libraries["My Media"]["type"] == "anime"


def test_settings_dialog_delete_library_destructive(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.staged_libraries = {
        "Delete Me": {
            "type": "tv",
            "management_type": "local",
            "paths": ["/path/delete"],
        },
        "Keep Me": {
            "type": "movie",
            "management_type": "local",
            "paths": ["/path/keep"],
        },
    }
    dialog._refresh_library_selector()
    dialog.library_selector.setCurrentText("Delete Me")

    dialog.remove_staged_library()

    assert "Delete Me" not in dialog.staged_libraries
    assert "Delete Me" in dialog.deleted_libraries
    assert "Keep Me" in dialog.staged_libraries

    with (
        patch("lan_streamer.db.library.delete_library_records") as mock_delete_records,
        patch("lan_streamer.system.config.config.save"),
        patch("lan_streamer.system.config.config.save_to_db"),
        patch("lan_streamer.system.logging_handler.set_application_log_level"),
    ):
        dialog.save_config()
        mock_delete_records.assert_called_once_with("Delete Me")


def test_settings_dialog_save_config_preserves_multi_root(qtbot, monkeypatch) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    # Manually stage a multi-root library
    dialog.staged_libraries = {
        "Combined": {
            "paths": ["/media/shows", "/media/cartoons"],
            "type": "tv",
            "archive_paths": [],
            "management_type": "local",
        }
    }

    with (
        patch("lan_streamer.system.config.config.save"),
        patch("lan_streamer.system.config.config.save_to_db"),
        patch("lan_streamer.system.logging_handler.set_application_log_level"),
    ):
        dialog.save_config()

    from lan_streamer.system.config import config

    assert "Combined" in config.libraries
    assert config.libraries["Combined"]["paths"] == ["/media/shows", "/media/cartoons"]
    assert "Combined (cartoons)" not in config.libraries


def test_settings_dialog_has_no_library_tabs_pane(qtbot) -> None:
    from unittest.mock import MagicMock, patch

    from PySide6.QtWidgets import QTabWidget

    from lan_streamer.system.config import config

    controller_mock = MagicMock()
    dialog_instance = SettingsDialog(controller_instance=controller_mock)
    qtbot.addWidget(dialog_instance)

    tab_widget = dialog_instance.findChild(QTabWidget)
    assert tab_widget is not None
    tabs_titles = [tab_widget.tabText(index) for index in range(tab_widget.count())]

    assert "Library Tabs" not in tabs_titles
    assert tabs_titles == [
        "Library Management",
        "Libraries",
        "Remote Sources",
        "Combined View",
        "Video Player",
        "Remote API's",
        "Advanced",
        "Logs",
    ]

    dialog_instance.staged_libraries = {
        "Anime": {"type": "tv", "paths": ["/anime"], "management_type": "local"},
        "Movies": {"type": "movie", "paths": ["/movies"], "management_type": "local"},
    }

    with (
        patch("lan_streamer.system.config.config.save"),
        patch("lan_streamer.system.config.config.save_to_db"),
        patch("lan_streamer.system.logging_handler.set_application_log_level"),
    ):
        dialog_instance.save_config()

    assert "Anime" in config.libraries
    assert "Movies" in config.libraries
    assert config.get_tab_names() == ["Anime", "Movies"]


def test_settings_dialog_per_library_scanning_controls(qtbot) -> None:
    from unittest.mock import MagicMock

    controller_mock = MagicMock()
    dialog_instance = SettingsDialog(controller_instance=controller_mock)
    qtbot.addWidget(dialog_instance)

    dialog_instance.staged_libraries = {
        "Anime": {"type": "tv", "paths": ["/anime"], "management_type": "local"},
        "Movies": {"type": "movie", "paths": ["/movies"], "management_type": "local"},
    }
    dialog_instance._refresh_library_selector()

    # Libraries: Scan Library button
    dialog_instance.library_selector.setCurrentText("Anime")
    dialog_instance.scan_selected_local_library()
    controller_mock.trigger_scan.assert_called_with(
        force_refresh=False,
        library_name="Anime",
        run_pass1=True,
        run_pass2=True,
        chain_pass3=True,
        chain_cleanup=True,
    )

    # Management tab: Target Library combobox
    dialog_instance.scan_target_library_combobox.setCurrentText("Movies")

    dialog_instance.trigger_full_scan_files()
    controller_mock.trigger_scan.assert_called_with(
        force_refresh=False,
        library_name="Movies",
        run_pass1=True,
        run_pass2=True,
        chain_pass3=True,
        chain_cleanup=True,
    )

    dialog_instance.trigger_pass1_scan()
    controller_mock.trigger_scan.assert_called_with(
        force_refresh=False,
        library_name="Movies",
        run_pass1=True,
        run_pass2=False,
        chain_pass3=False,
        chain_cleanup=False,
    )

    dialog_instance.trigger_pass2_scan()
    controller_mock.trigger_scan.assert_called_with(
        force_refresh=False,
        library_name="Movies",
        run_pass1=False,
        run_pass2=True,
        chain_pass3=False,
        chain_cleanup=False,
    )

    dialog_instance.trigger_garbage_cleanup()
    controller_mock.trigger_cleanup.assert_called_with(library_name="Movies")


def test_settings_dialog_remote_library_uses_media_type(qtbot) -> None:
    from PySide6.QtCore import Qt

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.staged_scan_agents = {
        "http://127.0.0.1:8800": {
            "name": "Scan Agent",
            "url": "http://127.0.0.1:8800",
            "reachable": True,
            "discovered_libraries": [
                {
                    "id": "remote-cinema",
                    "name": "Remote Cinema",
                    "media_type": "movie",
                    "root_path": "/remote/movies",
                }
            ],
        }
    }

    dialog._populate_remote_agents_tree()

    # Find the library item in the tree
    agent_item = dialog.remote_agents_tree_widget.topLevelItem(0)
    assert agent_item is not None
    assert agent_item.childCount() == 1
    library_item = agent_item.child(0)
    assert library_item is not None
    assert "Remote Cinema [MOVIE]" in library_item.text(0)

    # Check the item to enable it
    library_item.setCheckState(0, Qt.CheckState.Checked)
    dialog._on_remote_tree_item_changed(library_item, 0)

    assert "Remote Cinema" in dialog.staged_libraries
    staged_config = dialog.staged_libraries["Remote Cinema"]
    assert staged_config["type"] == "movie"
    assert staged_config["management_type"] == "remote"
    assert staged_config["remote_library_id"] == "remote-cinema"

    dialog.reject()


def test_settings_dialog_scan_selected_remote_library(qtbot) -> None:
    from unittest.mock import MagicMock

    controller_mock = MagicMock()
    controller_mock._config = config
    dialog = SettingsDialog(controller_instance=controller_mock)
    qtbot.addWidget(dialog)

    dialog.staged_libraries["Remote TV"] = {
        "type": "tv",
        "management_type": "remote",
        "agent_url": "http://127.0.0.1:8800",
        "remote_library_id": "remote-tv-1",
        "paths": [],
        "archive_paths": [],
        "show_future_episodes": True,
    }

    dialog.staged_scan_agents = {
        "http://127.0.0.1:8800": {
            "name": "Scan Agent",
            "url": "http://127.0.0.1:8800",
            "reachable": True,
            "discovered_libraries": [
                {
                    "id": "remote-tv-1",
                    "name": "Remote TV",
                    "media_type": "tv",
                    "root_path": "/remote/tv",
                }
            ],
        }
    }

    dialog._populate_remote_agents_tree()
    agent_item = dialog.remote_agents_tree_widget.topLevelItem(0)
    assert agent_item is not None
    library_item = agent_item.child(0)
    assert library_item is not None

    dialog.remote_agents_tree_widget.setCurrentItem(library_item)
    dialog.scan_selected_remote_library()

    controller_mock.trigger_scan.assert_called_once_with(
        force_refresh=False,
        library_name="Remote TV",
        run_pass1=True,
        run_pass2=True,
        chain_pass3=True,
        chain_cleanup=True,
    )

    dialog.reject()


def test_settings_dialog_add_and_remove_staged_remote_source(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.staged_libraries = {
        "Anime_Unified": {
            "type": "tv",
            "management_type": "local",
            "paths": ["/media/local/anime"],
            "archive_paths": [],
            "show_future_episodes": True,
            "sources": [
                {"type": "local", "path": "/media/local/anime", "is_archive": False}
            ],
        }
    }
    dialog.staged_scan_agents = {
        "http://127.0.0.1:8800": {
            "name": "NAS Agent",
            "discovered_libraries": [
                {
                    "id": "nas-anime-source",
                    "name": "NAS Anime",
                    "media_type": "tv",
                    "root_paths": ["/nas/anime"],
                }
            ],
        }
    }

    dialog._refresh_library_selector()
    dialog.library_selector.setCurrentText("Anime_Unified")

    with patch(
        "lan_streamer.ui_views.dialogs.settings.QInputDialog.getItem",
        return_value=("NAS Agent : NAS Anime [TV] (http://127.0.0.1:8800)", True),
    ):
        dialog.add_staged_remote_source()

    library_config = dialog.staged_libraries["Anime_Unified"]
    assert library_config["management_type"] == "hybrid"
    assert len(library_config["sources"]) == 2
    agent_sources = [
        source for source in library_config["sources"] if source.get("type") == "agent"
    ]
    assert len(agent_sources) == 1
    assert agent_sources[0]["source_identifier"] == "nas-anime-source"

    # Verify widget displayed both local and remote source
    assert dialog.directory_list_widget.count() == 2
    remote_item = dialog.directory_list_widget.item(1)
    assert "[Remote Source]" in remote_item.text()
    assert "NAS Anime" in remote_item.text()

    # Now remove the remote source
    dialog.directory_list_widget.setCurrentRow(1)
    dialog.remove_staged_directory()

    assert len(dialog.staged_libraries["Anime_Unified"]["sources"]) == 1
    assert dialog.directory_list_widget.count() == 1
    assert "[Active]" in dialog.directory_list_widget.item(0).text()

    dialog.reject()


def test_settings_dialog_add_remote_source_no_agents_shows_info(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.staged_libraries = {
        "Test Lib": {
            "type": "tv",
            "management_type": "local",
            "paths": ["/media/test"],
            "archive_paths": [],
            "show_future_episodes": True,
        }
    }
    dialog.staged_scan_agents = {}
    dialog._refresh_library_selector()
    dialog.library_selector.setCurrentText("Test Lib")

    with patch(
        "lan_streamer.ui_views.dialogs.settings.QMessageBox.information"
    ) as mock_info:
        dialog.add_staged_remote_source()
        mock_info.assert_called_once()

    dialog.reject()
