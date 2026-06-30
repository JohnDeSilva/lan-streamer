from unittest.mock import patch, MagicMock
from PySide6.QtWidgets import QDialog
from lan_streamer.ui_views import Controller
from lan_streamer.ui_views.library_grid import LibraryGridView
from lan_streamer.system.config import config


def test_controller_reloads_config_on_actions(mock_db_save) -> None:
    """Verify that config.load() is called prior to loading libraries or triggering scans."""
    controller = Controller()
    controller.current_library_name = "TestLib"

    with patch.object(config, "load") as mock_load:
        # 1. select_library
        controller.select_library("TestLib")
        mock_load.assert_called_once()
        mock_load.reset_mock()

        # 2. trigger_scan
        with patch(
            "lan_streamer.ui_views.controller.AsyncScanWorker"
        ) as mock_scan_worker:
            mock_worker_instance = MagicMock()
            mock_scan_worker.return_value = mock_worker_instance

            controller.trigger_scan()
            mock_load.assert_called_once()
            mock_load.reset_mock()

        # 3. trigger_scan_and_update
        with patch(
            "lan_streamer.ui_views.controller.AsyncScanWorker"
        ) as mock_scan_worker:
            mock_worker_instance = MagicMock()
            mock_scan_worker.return_value = mock_worker_instance

            controller.trigger_scan_and_update()
            mock_load.assert_called_once()
            mock_load.reset_mock()

        # 4. trigger_scan_all
        with patch(
            "lan_streamer.ui_views.controller.ScanAllLibrariesWorker"
        ) as mock_scan_all_worker:
            mock_worker_instance = MagicMock()
            mock_worker_instance._is_async_worker = True
            mock_worker_instance.is_running = False
            mock_scan_all_worker.return_value = mock_worker_instance

            controller.trigger_scan_all()
            mock_load.assert_called_once()
            mock_load.reset_mock()


def test_library_grid_autoscan_on_settings_save(qtbot, mock_db_save) -> None:
    """Verify that adding new paths in SettingsDialog triggers appropriate scan."""
    controller = Controller()
    controller.current_library_name = "MyLib"

    # Pre-populate config
    config.libraries = {
        "MyLib": {"type": "tv", "paths": ["/tv/path1"]},
        "OtherLib": {"type": "tv", "paths": ["/tv/other1"]},
    }

    grid_view = LibraryGridView(controller)
    qtbot.addWidget(grid_view)

    # Mock SettingsDialog to execute and modify config.libraries to simulate user action
    with (
        patch(
            "lan_streamer.ui_views.library_grid.SettingsDialog"
        ) as MockSettingsDialog,
        patch.object(
            controller, "trigger_scan_and_update"
        ) as mock_trigger_scan_and_update,
        patch.object(controller, "trigger_scan_all") as mock_trigger_scan_all,
        patch.object(config, "load") as mock_config_load,
    ):
        mock_dialog_instance = MagicMock()
        MockSettingsDialog.return_value = mock_dialog_instance

        # Scenario 1: User adds a path to the CURRENT library ("MyLib")
        def mock_exec_accept_current():
            config.libraries["MyLib"]["paths"].append("/tv/path2")
            return QDialog.DialogCode.Accepted

        mock_dialog_instance.exec.side_effect = mock_exec_accept_current

        grid_view.open_settings_dialog()

        mock_trigger_scan_and_update.assert_called_once_with(False)
        mock_trigger_scan_all.assert_not_called()

        # Reset config and mocks
        config.libraries = {
            "MyLib": {"type": "tv", "paths": ["/tv/path1"]},
            "OtherLib": {"type": "tv", "paths": ["/tv/other1"]},
        }
        mock_trigger_scan_and_update.reset_mock()
        mock_trigger_scan_all.reset_mock()

        # Scenario 2: User adds a path to a DIFFERENT library ("OtherLib")
        def mock_exec_accept_other():
            config.libraries["OtherLib"]["paths"].append("/tv/other2")
            return QDialog.DialogCode.Accepted

        mock_dialog_instance.exec.side_effect = mock_exec_accept_other

        grid_view.open_settings_dialog()

        mock_trigger_scan_and_update.assert_not_called()
        mock_trigger_scan_all.assert_called_once_with(False)

        # Reset config and mocks
        config.libraries = {
            "MyLib": {"type": "tv", "paths": ["/tv/path1"]},
            "OtherLib": {"type": "tv", "paths": ["/tv/other1"]},
        }
        mock_trigger_scan_and_update.reset_mock()
        mock_trigger_scan_all.reset_mock()

        # Scenario 3: Dialog rejected (cancel clicked) -> Should reload config, no scan
        mock_dialog_instance.exec.side_effect = lambda: QDialog.DialogCode.Rejected
        mock_config_load.reset_mock()

        grid_view.open_settings_dialog()

        mock_config_load.assert_called()  # It loads at start, and loads on reject.
        mock_trigger_scan_and_update.assert_not_called()
        mock_trigger_scan_all.assert_not_called()
