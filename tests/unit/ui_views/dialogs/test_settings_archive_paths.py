"""Unit tests for active vs archive path configuration in SettingsDialog."""

from __future__ import annotations

from unittest.mock import patch

from lan_streamer.system.config import config
from lan_streamer.ui_views.dialogs.settings import SettingsDialog


def test_settings_dialog_displays_and_toggles_archive_mode(qtbot) -> None:
    """Verify that mapped directories show Active/Archive tags and can be toggled."""
    initial_libraries = {
        "TV Shows": {
            "type": "tv",
            "paths": ["/media/current_tv"],
            "archive_paths": [],
            "show_future_episodes": True,
        },
        "Archive TV": {
            "type": "tv",
            "paths": ["/media/archive_tv"],
            "archive_paths": ["/media/archive_tv"],
            "show_future_episodes": True,
        },
    }

    with patch.dict(config.libraries, initial_libraries, clear=True):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)

        # Select the TV Shows library
        dialog.library_selector.setCurrentText("TV Shows")

        list_widget = dialog.directory_list_widget
        assert list_widget.count() == 1

        # TV Shows is Active
        item0 = list_widget.item(0)
        assert "[Active]" in item0.text()
        assert "/media/current_tv" in item0.text()

        # Switch to Archive TV
        dialog.library_selector.setCurrentText("Archive TV")
        assert list_widget.count() == 1
        archive_item = list_widget.item(0)
        assert "[Archive]" in archive_item.text()
        assert "/media/archive_tv" in archive_item.text()

        # Switch back to TV Shows, select item 0 and toggle to Archive
        dialog.library_selector.setCurrentText("TV Shows")
        list_widget.setCurrentRow(0)
        dialog.toggle_staged_directory_archive_mode()

        assert "[Archive]" in list_widget.item(0).text()
        assert (
            "/media/current_tv" in dialog.staged_libraries["TV Shows"]["archive_paths"]
        )

        # Toggle item 0 back to Active
        list_widget.setCurrentRow(0)
        dialog.toggle_staged_directory_archive_mode()

        assert "[Active]" in list_widget.item(0).text()
        assert (
            "/media/current_tv"
            not in dialog.staged_libraries["TV Shows"]["archive_paths"]
        )

        # Toggle back to Archive and verify save_config persists archive_paths
        dialog.toggle_staged_directory_archive_mode()
        with (
            patch.object(config, "save"),
            patch.object(config, "save_to_db"),
        ):
            dialog.save_config()
            assert config.libraries["TV Shows"]["archive_paths"] == [
                "/media/current_tv"
            ]

        dialog.reject()


def test_settings_dialog_remove_directory_cleans_archive_paths(qtbot) -> None:
    """Verify removing a directory also removes it from archive_paths."""
    initial_libraries = {
        "Archive TV": {
            "type": "tv",
            "paths": ["/media/archive_tv"],
            "archive_paths": ["/media/archive_tv"],
            "show_future_episodes": True,
        }
    }

    with patch.dict(config.libraries, initial_libraries, clear=True):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)

        dialog.library_selector.setCurrentText("Archive TV")
        list_widget = dialog.directory_list_widget
        assert list_widget.count() == 1

        # Select archive_tv and remove it
        list_widget.setCurrentRow(0)
        dialog.remove_staged_directory()

        assert list_widget.count() == 0
        assert "/media/archive_tv" not in dialog.staged_libraries["Archive TV"]["paths"]
        assert (
            "/media/archive_tv"
            not in dialog.staged_libraries["Archive TV"]["archive_paths"]
        )

        dialog.reject()
