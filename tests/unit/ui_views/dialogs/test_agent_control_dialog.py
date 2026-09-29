"""Unit tests for the desktop AgentControlDialog."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from lan_streamer.ui_views.dialogs.agent_control_dialog import (
    AddRemoteLibraryDialog,
    AgentControlDialog,
)


@pytest.fixture
def mock_agent_data() -> dict:
    return {
        "config": {
            "tmdb_api_key": "test_tmdb_key",
            "scan_concurrency": 4,
            "scheduled_scan_enabled": True,
            "scheduled_scan_interval_hours": 4,
            "filesystem_watching_enabled": True,
            "filesystem_watching_debounce_seconds": 30,
            "opensubtitles_username": "user1",
            "opensubtitles_password": "*****",
            "opensubtitles_api_key": "os_key",
            "log_level": "INFO",
        },
        "status": {
            "running": None,
            "last_job": {"id": 1, "status": "done"},
            "is_interrupted": False,
        },
        "libraries": [
            {
                "id": "tv",
                "name": "TV Shows",
                "media_type": "tv",
                "root_path": "/media/tv",
                "enabled": True,
            }
        ],
    }


def test_agent_control_dialog_loads_data(qtbot, mock_agent_data) -> None:
    agent_url = "http://127.0.0.1:8800"

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_config",
            return_value=mock_agent_data["config"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_scan_status",
            return_value=mock_agent_data["status"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_libraries",
            return_value=mock_agent_data["libraries"],
        ),
        patch("lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.warning"),
    ):
        dialog = AgentControlDialog(agent_url=agent_url)
        qtbot.addWidget(dialog)

        # Wait for data fetch worker to finish and populate UI
        qtbot.waitUntil(
            lambda: dialog.tmdb_api_key_input.text() == "test_tmdb_key",
            timeout=10000,
        )

        assert dialog.scan_concurrency_spinbox.value() == 4
        assert dialog.scheduled_scans_enabled_checkbox.isChecked() is True
        assert dialog.scheduled_scan_interval_spinbox.value() == 4
        assert dialog.filesystem_watching_enabled_checkbox.isChecked() is True
        assert dialog.filesystem_watching_debounce_spinbox.value() == 30
        assert dialog.opensubtitles_username_input.text() == "user1"
        assert dialog.log_level_combobox.currentText() == "INFO"
        assert dialog.libraries_table.rowCount() == 1
        dialog.close()


def test_agent_control_dialog_saves_config(qtbot, mock_agent_data) -> None:
    agent_url = "http://127.0.0.1:8800"

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_config",
            return_value=mock_agent_data["config"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_scan_status",
            return_value=mock_agent_data["status"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_libraries",
            return_value=mock_agent_data["libraries"],
        ),
        patch("lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.warning"),
    ):
        dialog = AgentControlDialog(agent_url=agent_url)
        qtbot.addWidget(dialog)
        qtbot.waitUntil(
            lambda: dialog.tmdb_api_key_input.text() == "test_tmdb_key",
            timeout=10000,
        )

    # Modify values
    dialog.scheduled_scan_interval_spinbox.setValue(8)
    dialog.filesystem_watching_debounce_spinbox.setValue(60)
    dialog.clear_opensubtitles_password_checkbox.setChecked(True)

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.update_agent_config",
            return_value={"scheduled_scan_interval_hours": 8},
        ) as mock_update,
        patch(
            "lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.information"
        ),
        patch("lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.warning"),
    ):
        dialog.save_configuration()
        qtbot.waitUntil(lambda: mock_update.called, timeout=10000)

        saved_payload = mock_update.call_args[0][1]
        assert saved_payload["scheduled_scan_interval_hours"] == 8
        assert saved_payload["filesystem_watching_debounce_seconds"] == 60
        assert saved_payload["clear_opensubtitles_password"] is True
        dialog.close()


def test_agent_control_dialog_trigger_and_cancel_scan(qtbot, mock_agent_data) -> None:
    from unittest.mock import MagicMock

    agent_url = "http://127.0.0.1:8800"
    mock_controller = MagicMock()
    mock_controller._config.libraries = {
        "TV Shows": {"management_type": "remote", "agent_url": agent_url}
    }

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_config",
            return_value=mock_agent_data["config"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_scan_status",
            return_value=mock_agent_data["status"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_libraries",
            return_value=mock_agent_data["libraries"],
        ),
        patch("lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.warning"),
    ):
        dialog = AgentControlDialog(agent_url=agent_url, controller=mock_controller)
        qtbot.addWidget(dialog)
        qtbot.waitUntil(
            lambda: dialog.libraries_table.rowCount() == 1,
            timeout=10000,
        )

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.trigger_agent_scan",
            return_value={"id": 1, "status": "pending"},
        ) as mock_trigger,
        patch(
            "lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.information"
        ),
        patch("lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.warning"),
    ):
        dialog.start_scan_on_agent()
        qtbot.waitUntil(lambda: mock_trigger.called, timeout=10000)
        assert mock_trigger.call_args[0][0] == agent_url

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.cancel_agent_scan",
            return_value={"status": "cancelled"},
        ) as mock_cancel,
        patch(
            "lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.information"
        ),
        patch("lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.warning"),
    ):
        dialog.cancel_scan_on_agent()
        qtbot.waitUntil(lambda: mock_cancel.called, timeout=10000)
        assert mock_cancel.call_args[0][0] == agent_url
        dialog.close()

    mock_controller._queue_remote_sync.assert_called_once_with("TV Shows")


def test_add_remote_library_dialog(qtbot) -> None:
    dialog = AddRemoteLibraryDialog()
    qtbot.addWidget(dialog)
    dialog.name_input.setText("Anime Series")
    dialog.media_type_combobox.setCurrentText("anime")
    dialog.root_path_input.setText("/media/anime")

    values = dialog.get_library_values()
    assert values == {
        "name": "Anime Series",
        "media_type": "anime",
        "root_path": "/media/anime",
    }


def test_agent_control_dialog_button_states_reflect_running_job(
    qtbot, mock_agent_data
) -> None:
    agent_url = "http://127.0.0.1:8800"
    mock_agent_data["status"]["running"] = {
        "id": 42,
        "pass_number": 0,
        "started_at": "now",
    }

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_config",
            return_value=mock_agent_data["config"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_scan_status",
            return_value=mock_agent_data["status"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_libraries",
            return_value=mock_agent_data["libraries"],
        ),
        patch("lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.warning"),
    ):
        dialog = AgentControlDialog(agent_url=agent_url)
        qtbot.addWidget(dialog)
        qtbot.waitUntil(
            lambda: dialog.libraries_table.rowCount() == 1,
            timeout=10000,
        )

        # When a scan is running, start button must be disabled and cancel button enabled
        assert dialog.start_scan_button.isEnabled() is False
        assert dialog.cancel_scan_button.isEnabled() is True

        # Now simulate idle status
        idle_status = {"running": None, "last_job": {"id": 42, "status": "done"}}
        dialog._update_status_display(idle_status)

        assert dialog.start_scan_button.isEnabled() is True
        assert dialog.cancel_scan_button.isEnabled() is False
        dialog.close()


def test_agent_control_dialog_accept_triggers_remote_sync_and_cleans_up(
    qtbot, mock_agent_data
) -> None:
    from unittest.mock import MagicMock

    agent_url = "http://127.0.0.1:8800/"
    mock_controller = MagicMock()
    mock_controller._config.libraries = {
        "TV Shows": {"management_type": "remote", "agent_url": "http://127.0.0.1:8800"}
    }

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_config",
            return_value=mock_agent_data["config"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_scan_status",
            return_value=mock_agent_data["status"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_libraries",
            return_value=mock_agent_data["libraries"],
        ),
        patch("lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.warning"),
    ):
        # Dialog initialized with trailing slash; should normalize
        dialog = AgentControlDialog(agent_url=agent_url, controller=mock_controller)
        qtbot.addWidget(dialog)
        qtbot.waitUntil(
            lambda: dialog.libraries_table.rowCount() == 1,
            timeout=10000,
        )
        assert dialog.agent_url == "http://127.0.0.1:8800"

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.trigger_agent_scan",
            return_value={"id": 1, "status": "pending"},
        ),
        patch(
            "lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.information"
        ),
        patch("lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.warning"),
    ):
        dialog.start_scan_on_agent()
        qtbot.waitUntil(lambda: dialog._scan_triggered_during_session, timeout=10000)

    # User closes dialog using accept() (e.g. clicking Close button)
    dialog.accept()

    # Ensure remote sync is triggered and timer is stopped
    mock_controller._queue_remote_sync.assert_called_once_with("TV Shows")
    assert dialog._status_timer.isActive() is False


def test_agent_control_dialog_refresh_scan_status_is_non_blocking(
    qtbot, mock_agent_data
) -> None:
    agent_url = "http://127.0.0.1:8800"

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_config",
            return_value=mock_agent_data["config"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_scan_status",
            return_value=mock_agent_data["status"],
        ),
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_agent_libraries",
            return_value=mock_agent_data["libraries"],
        ),
        patch("lan_streamer.ui_views.dialogs.agent_control_dialog.QMessageBox.warning"),
    ):
        dialog = AgentControlDialog(agent_url=agent_url)
        qtbot.addWidget(dialog)
        qtbot.waitUntil(
            lambda: dialog.libraries_table.rowCount() == 1,
            timeout=10000,
        )

    updated_status = {"running": {"id": 99, "pass_number": 0, "started_at": "just now"}}
    with patch(
        "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_scan_status",
        return_value=updated_status,
    ) as mock_fetch:
        dialog.refresh_scan_status()
        qtbot.waitUntil(
            lambda: dialog.start_scan_button.isEnabled() is False,
            timeout=10000,
        )
        assert mock_fetch.called
        dialog.close()
