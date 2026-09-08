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
    assert root_item is not None
    assert "📁 /storage/tv" in root_item.text(0)

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
            "lan_streamer.ui_views.dialogs.settings.QMessageBox.warning"
        ) as mock_warn,
    ):
        dialog.remote_agent_url_input.setText("http://127.0.0.1:8800")
        dialog.connect_to_agent()
        mock_warn.assert_called_once()

    tree = dialog.remote_agents_tree_widget
    assert tree.topLevelItemCount() == 1
    agent_item = tree.topLevelItem(0)
    assert agent_item is not None
    assert "🔴" in agent_item.text(0)
    assert agent_item.text(1) == "Status: Unreachable"

    dialog.reject()
