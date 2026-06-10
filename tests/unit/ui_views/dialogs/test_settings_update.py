import pytest
from unittest.mock import patch, MagicMock

from lan_streamer.ui_views.dialogs.settings import SettingsDialog
from lan_streamer.system.config import config


@pytest.fixture
def dialog(qtbot) -> SettingsDialog:
    d = SettingsDialog()
    qtbot.addWidget(d)
    return d


def test_settings_dialog_updates_ui_initialization(dialog) -> None:
    # Verify widgets exist
    assert dialog.check_updates_startup_checkbox is not None
    assert dialog.check_updates_now_button is not None
    assert not dialog.check_updates_startup_checkbox.isHidden()
    assert not dialog.check_updates_now_button.isHidden()


def test_settings_dialog_updates_load_and_save(qtbot) -> None:
    config.check_for_updates_on_startup = True
    d1 = SettingsDialog()
    qtbot.addWidget(d1)
    assert d1.check_updates_startup_checkbox.isChecked() is True

    # Modify value
    d1.check_updates_startup_checkbox.setChecked(False)

    with patch.object(config, "save") as mock_save:
        d1.save_config()
        assert config.check_for_updates_on_startup is False
        mock_save.assert_called_once()

    d1.reject()

    # Load again with new value
    config.check_for_updates_on_startup = False
    d2 = SettingsDialog()
    qtbot.addWidget(d2)
    assert d2.check_updates_startup_checkbox.isChecked() is False
    d2.reject()


def test_settings_dialog_manual_check_no_updates(dialog, qtbot) -> None:
    mock_worker = MagicMock()

    with (
        patch(
            "lan_streamer.ui_views.dialogs.settings.UpdateCheckWorker",
            return_value=mock_worker,
        ) as mock_worker_class,
        patch(
            "lan_streamer.ui_views.dialogs.settings.QMessageBox.information"
        ) as mock_info,
    ):
        dialog.trigger_manual_update_check()

        mock_worker_class.assert_called_once()
        mock_worker.start.assert_called_once()
        assert dialog.check_updates_now_button.text() == "Checking..."
        assert dialog.check_updates_now_button.isEnabled() is False

        # Mock signal finish with no update
        mock_worker.finished.connect.call_args[0][0](True, {}, "")

        mock_info.assert_called_once()
        assert "latest version" in mock_info.call_args[0][2]
        assert dialog.check_updates_now_button.text() == "Check for Updates Now"
        assert dialog.check_updates_now_button.isEnabled() is True


def test_settings_dialog_manual_check_has_updates(dialog, qtbot) -> None:
    mock_worker = MagicMock()
    release_info = {
        "version": "v0.27.0",
        "release_notes": "Added updates",
        "download_url": "http://download.url/app",
    }

    with (
        patch(
            "lan_streamer.ui_views.dialogs.settings.UpdateCheckWorker",
            return_value=mock_worker,
        ),
        patch(
            "lan_streamer.ui_views.dialogs.settings.UpdateDialog"
        ) as mock_update_dialog_class,
    ):
        dialog.trigger_manual_update_check()

        mock_dialog_instance = MagicMock()
        mock_update_dialog_class.return_value = mock_dialog_instance

        # Mock signal finish with update found
        mock_worker.finished.connect.call_args[0][0](True, release_info, "")

        mock_update_dialog_class.assert_called_once()
        mock_dialog_instance.exec.assert_called_once()


def test_settings_dialog_manual_check_failed(dialog, qtbot) -> None:
    mock_worker = MagicMock()

    with (
        patch(
            "lan_streamer.ui_views.dialogs.settings.UpdateCheckWorker",
            return_value=mock_worker,
        ),
        patch(
            "lan_streamer.ui_views.dialogs.settings.QMessageBox.warning"
        ) as mock_warn,
    ):
        dialog.trigger_manual_update_check()

        # Mock signal finish with error
        mock_worker.finished.connect.call_args[0][0](False, {}, "Timeout error")

        mock_warn.assert_called_once()
        assert "Timeout error" in mock_warn.call_args[0][2]
