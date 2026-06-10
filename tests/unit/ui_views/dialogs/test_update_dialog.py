import os
import sys
import pytest
from unittest.mock import patch, MagicMock

from PySide6.QtWidgets import QMessageBox

from lan_streamer.ui_views.dialogs.update_dialog import UpdateDialog


@pytest.fixture
def dialog(qtbot) -> UpdateDialog:
    dlg = UpdateDialog(
        current_version="0.26.0",
        new_version="0.27.0",
        release_notes="## Enhancements\n- Added cool update feature",
        download_url="https://github.com/JohnDeSilva/lan-streamer/releases/download/v0.27.0/lan-streamer-ubuntu",
    )
    qtbot.addWidget(dlg)
    return dlg


def test_update_dialog_init(dialog) -> None:
    assert dialog.windowTitle() == "Update Available"
    assert "0.26.0" in dialog.version_label.text()
    assert "0.27.0" in dialog.version_label.text()
    assert not dialog.download_button.isHidden()
    assert not dialog.ignore_button.isHidden()
    assert dialog.progress_container.isHidden()


def test_update_dialog_start_download(dialog, qtbot) -> None:
    mock_worker = MagicMock()
    mock_worker.isRunning.return_value = False
    with patch(
        "lan_streamer.ui_views.dialogs.update_dialog.DownloadWorker",
        return_value=mock_worker,
    ) as mock_worker_class:
        dialog.start_download()

        mock_worker_class.assert_called_once_with(
            "https://github.com/JohnDeSilva/lan-streamer/releases/download/v0.27.0/lan-streamer-ubuntu",
            str(
                os.path.expanduser("~/.config/lan-streamer/updates/lan-streamer-ubuntu")
            ),
        )
        mock_worker.start.assert_called_once()
        assert dialog.download_button.isHidden()
        assert dialog.ignore_button.isHidden()
        assert not dialog.progress_container.isHidden()


def test_update_dialog_progress(dialog) -> None:
    # Trigger progress update
    dialog.on_progress(1048576, 2097152)  # 1MB of 2MB
    assert dialog.progress_bar.value() == 50
    assert "1.0 MB / 2.0 MB (50%)" in dialog.progress_label.text()

    # Indeterminate progress
    dialog.on_progress(0, 0)
    assert dialog.progress_bar.minimum() == 0
    assert dialog.progress_bar.maximum() == 0


def test_update_dialog_finished_success(dialog, qtbot) -> None:
    with (
        patch("PySide6.QtCore.QProcess.startDetached") as mock_start,
        patch("os.chmod") as mock_chmod,
        patch(
            "lan_streamer.ui_views.dialogs.update_dialog.QApplication.quit"
        ) as mock_quit,
    ):
        dialog.on_finished(True, "/path/to/downloaded/update")
        if sys.platform != "win32":
            from pathlib import Path

            mock_chmod.assert_called_once_with(
                Path("/path/to/downloaded/update"), 0o755
            )  # chmod called on path
        mock_start.assert_called_once_with("/path/to/downloaded/update")
        mock_quit.assert_called_once()


def test_update_dialog_finished_error(dialog, qtbot) -> None:
    with patch(
        "lan_streamer.ui_views.dialogs.update_dialog.QMessageBox.critical"
    ) as mock_msg:
        dialog.ignore_button.setVisible(False)
        dialog.download_button.setVisible(False)
        dialog.progress_container.setVisible(True)

        dialog.on_finished(False, "Connection reset by peer")

        mock_msg.assert_called_once()
        assert not dialog.ignore_button.isHidden()
        assert not dialog.download_button.isHidden()
        assert dialog.progress_container.isHidden()


def test_update_dialog_close_event_not_downloading(dialog) -> None:
    # Closing when not downloading should accept directly
    mock_event = MagicMock()
    dialog.closeEvent(mock_event)
    mock_event.accept.assert_called_once()


def test_update_dialog_close_event_downloading_cancel(dialog) -> None:
    mock_worker = MagicMock()
    mock_worker.isRunning.return_value = True
    dialog.worker = mock_worker

    mock_event = MagicMock()
    with patch(
        "lan_streamer.ui_views.dialogs.update_dialog.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        dialog.closeEvent(mock_event)
        mock_worker.cancel.assert_called_once()
        mock_worker.wait.assert_called_once()
        mock_event.accept.assert_called_once()
        dialog.worker = None


def test_update_dialog_close_event_downloading_ignore(dialog) -> None:
    mock_worker = MagicMock()
    mock_worker.isRunning.return_value = True
    dialog.worker = mock_worker

    mock_event = MagicMock()
    with patch(
        "lan_streamer.ui_views.dialogs.update_dialog.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ):
        dialog.closeEvent(mock_event)
        mock_worker.cancel.assert_not_called()
        mock_event.ignore.assert_called_once()
        dialog.worker = None
