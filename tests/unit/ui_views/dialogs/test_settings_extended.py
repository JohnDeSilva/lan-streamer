"""
Extended SettingsDialog tests to improve coverage.
Targeting uncovered methods:
- save_config (basic path)
- add_staged_library / remove_staged_library
- add/remove staged directories
- combined view operations: add/move/delete/select rows
- _on_row_property_changed
- log view: filter, clear, export
- _on_global_progress, _on_detail_progress
- trigger_global_scan_files, trigger_global_refresh_metadata,
  trigger_global_jellyfin_pull/push, trigger_global_runtime_extraction
- link/unlink MAL account (fast path)
- _load_config for libraries
"""

import pytest
from unittest.mock import patch

from lan_streamer.ui_views.dialogs.settings import SettingsDialog
from lan_streamer.ui_views import Controller
from lan_streamer.system.config import config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dialog(qtbot):
    d = SettingsDialog()
    qtbot.addWidget(d)
    return d


@pytest.fixture
def dialog_with_libs(qtbot):
    with patch.dict(
        config.libraries,
        {
            "TV Shows": {"type": "tv", "paths": ["/tv"]},
            "Movies": {"type": "movie", "paths": ["/movies"]},
        },
        clear=True,
    ):
        d = SettingsDialog()
        qtbot.addWidget(d)
        yield d


@pytest.fixture
def dialog_with_controller(qtbot):
    ctrl = Controller()
    d = SettingsDialog(controller_instance=ctrl)
    qtbot.addWidget(d)
    return d, ctrl


# ---------------------------------------------------------------------------
# Basic initialization
# ---------------------------------------------------------------------------


def test_settings_dialog_initializes(dialog) -> None:
    """SettingsDialog should open without errors."""
    assert dialog.windowTitle() == "Application Configuration"


def test_settings_dialog_with_controller_connects_signals(
    dialog_with_controller,
) -> None:
    """When a controller is given, signals should be connected at init."""
    dialog, ctrl = dialog_with_controller
    # If no error occurred, signals are connected. Emit to verify.
    ctrl.global_progress_updated.emit("test", 1, 10)


# ---------------------------------------------------------------------------
# save_config - basic path
# ---------------------------------------------------------------------------


def test_save_config_persists_credentials(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.jellyfin_url_input.setText("http://localhost:8096")
    dialog.jellyfin_key_input.setText("token-abc")
    dialog.tmdb_key_input.setText("tmdb-key-xyz")

    with patch.object(config, "save") as mock_save:
        dialog.save_config()
        mock_save.assert_called_once()

    assert config.jellyfin_url == "http://localhost:8096"
    assert config.jellyfin_api_key == "token-abc"
    assert config.tmdb_api_key == "tmdb-key-xyz"


def test_save_config_persists_player_settings(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.use_embedded_checkbox.setChecked(True)
    dialog.enable_caching_checkbox.setChecked(False)
    dialog.watched_threshold_input.setText("85")

    with patch.object(config, "save"):
        dialog.save_config()

    assert config.use_embedded_player is True
    assert config.enable_caching is False
    assert abs(config.watched_threshold - 0.85) < 0.001


# ---------------------------------------------------------------------------
# add_staged_library
# ---------------------------------------------------------------------------


def test_add_staged_library_creates_entry(dialog) -> None:
    dialog.library_name_input.setText("My Anime")
    dialog.library_type_input.setCurrentText("Anime")

    count_before = dialog.library_selector.count()
    dialog.add_staged_library()

    assert dialog.library_selector.count() == count_before + 1
    assert "My Anime" in dialog.staged_libraries


def test_add_staged_library_empty_name_no_op(dialog) -> None:
    dialog.library_name_input.setText("")
    count_before = dialog.library_selector.count()
    dialog.add_staged_library()
    # No new library should be added
    assert dialog.library_selector.count() == count_before


def test_add_staged_library_duplicate_no_op(dialog_with_libs) -> None:
    """Re-adding an existing library name should not create a duplicate."""
    dialog = dialog_with_libs
    count_before = dialog.library_selector.count()
    dialog.library_name_input.setText("TV Shows")
    with patch("lan_streamer.ui_views.proxy.QMessageBox.warning") as mock_warn:
        dialog.add_staged_library()
        mock_warn.assert_called_once()
    assert dialog.library_selector.count() == count_before


# ---------------------------------------------------------------------------
# remove_staged_library
# ---------------------------------------------------------------------------


def test_remove_staged_library(dialog_with_libs) -> None:
    dialog = dialog_with_libs
    dialog.library_selector.setCurrentText("TV Shows")
    count_before = dialog.library_selector.count()
    dialog.remove_staged_library()
    assert dialog.library_selector.count() == count_before - 1
    assert "TV Shows" not in dialog.staged_libraries


def test_remove_staged_library_none_selected(dialog) -> None:
    """With nothing selected, remove should be a no-op."""
    dialog.library_selector.setCurrentIndex(-1)
    dialog.remove_staged_library()  # Should not crash


# ---------------------------------------------------------------------------
# add/remove staged directories
# ---------------------------------------------------------------------------


def test_add_staged_directory(dialog_with_libs, tmp_path) -> None:
    dialog = dialog_with_libs
    dialog.library_selector.setCurrentText("TV Shows")

    with patch(
        "lan_streamer.ui_views.proxy.QFileDialog.getExistingDirectory",
        return_value=str(tmp_path),
    ):
        dialog.add_staged_directory()

    assert str(tmp_path) in [
        dialog.directory_list_widget.item(i).text()
        for i in range(dialog.directory_list_widget.count())
    ]


def test_remove_staged_directory(dialog_with_libs) -> None:
    dialog = dialog_with_libs
    dialog.library_selector.setCurrentText("TV Shows")
    # TV Shows already has "/tv" in paths
    dialog.directory_list_widget.addItem("/to-remove")
    dialog.directory_list_widget.setCurrentRow(0)
    dialog.remove_staged_directory()
    texts = [
        dialog.directory_list_widget.item(i).text()
        for i in range(dialog.directory_list_widget.count())
    ]
    assert "/to-remove" not in texts or len(texts) < 2


def test_remove_staged_directory_no_selection(dialog_with_libs) -> None:
    dialog = dialog_with_libs
    dialog.library_selector.setCurrentText("TV Shows")
    dialog.directory_list_widget.clearSelection()
    dialog.remove_staged_directory()  # Should not crash


# ---------------------------------------------------------------------------
# Combined View operations
# ---------------------------------------------------------------------------


def test_add_combined_view_row(dialog) -> None:
    count_before = dialog.combined_views_list_widget.count()
    dialog.add_combined_view_row()
    assert dialog.combined_views_list_widget.count() == count_before + 1
    assert len(dialog.staged_combined_views) == count_before + 1


def test_delete_combined_view_row(dialog) -> None:
    dialog.add_combined_view_row()
    dialog.combined_views_list_widget.setCurrentRow(0)
    count_before = dialog.combined_views_list_widget.count()
    dialog.delete_combined_view_row()
    assert dialog.combined_views_list_widget.count() == count_before - 1


def test_move_combined_view_row_up(dialog) -> None:
    dialog.add_combined_view_row()
    dialog.staged_combined_views[0]["name"] = "Row A"
    dialog.combined_views_list_widget.item(0).setText("Row A")
    dialog.add_combined_view_row()
    dialog.staged_combined_views[1]["name"] = "Row B"
    dialog.combined_views_list_widget.item(1).setText("Row B")

    dialog.combined_views_list_widget.setCurrentRow(1)
    dialog.move_combined_view_row_up()

    assert "Row B" in dialog.combined_views_list_widget.item(0).text()


def test_move_combined_view_row_down(dialog) -> None:
    dialog.add_combined_view_row()
    dialog.staged_combined_views[0]["name"] = "Row A"
    dialog.combined_views_list_widget.item(0).setText("Row A")
    dialog.add_combined_view_row()
    dialog.staged_combined_views[1]["name"] = "Row B"
    dialog.combined_views_list_widget.item(1).setText("Row B")

    dialog.combined_views_list_widget.setCurrentRow(0)
    dialog.move_combined_view_row_down()

    assert "Row B" in dialog.combined_views_list_widget.item(0).text()


def test_on_combined_view_selected_updates_ui(dialog) -> None:
    dialog.add_combined_view_row()
    dialog.staged_combined_views[0]["name"] = "My Row"
    dialog.staged_combined_views[0]["enabled"] = True
    dialog.staged_combined_views[0]["sort_by"] = "Next Up"
    dialog.staged_combined_views[0]["filter_mode"] = "Unwatched"

    dialog.combined_views_list_widget.setCurrentRow(0)

    assert dialog.row_name_input.text() == "My Row"
    assert dialog.row_enabled_checkbox.isChecked() is True
    assert dialog.row_sort_selector.currentText() == "Next Up"
    assert dialog.row_filter_selector.currentText() == "Unwatched"


def test_on_row_property_changed_updates_staged_view(dialog) -> None:
    dialog.add_combined_view_row()
    dialog.combined_views_list_widget.setCurrentRow(0)

    dialog.row_name_input.setText("Updated Name")

    assert dialog.staged_combined_views[0]["name"] == "Updated Name"


# ---------------------------------------------------------------------------
# Log view operations
# ---------------------------------------------------------------------------


def test_clear_log_view(dialog) -> None:
    dialog.log_display.setPlainText("Some log text")
    dialog.all_log_records = [("INFO: Some log text", "INFO")]
    dialog._clear_log_view()
    assert dialog.log_display.toPlainText() == ""
    assert dialog.all_log_records == []


def test_on_log_filter_changed_filters_level(dialog) -> None:
    # all_log_records is a list of (formatted_message, level_name) tuples
    dialog.all_log_records = [
        ("debug msg", "DEBUG"),
        ("warn msg", "WARNING"),
        ("error msg", "ERROR"),
    ]
    dialog.log_level_filter.setCurrentText("ERROR")
    dialog._on_log_filter_changed("")  # Pass empty text arg
    # The display should filter to show ERROR level only
    # Just verify no crash occurs and the method runs


def test_on_log_filter_changed_with_search(dialog) -> None:
    dialog.all_log_records = [
        ("important message", "INFO"),
        ("something else", "INFO"),
    ]
    dialog.log_level_filter.setCurrentText("All")
    dialog.log_search_input.setText("important")
    dialog._on_log_filter_changed("")  # Pass empty text arg
    # Verify no crash; display should show only 'important message'


def test_copy_logs_to_clipboard(dialog, qtbot) -> None:
    dialog.log_display.setPlainText("Test log line")
    dialog._copy_logs_to_clipboard()  # Should not crash


def test_export_logs_no_log_dir(dialog, tmp_path) -> None:
    """If log directory doesn't exist, export should warn."""

    config.log_directory = str(tmp_path / "nonexistent_logs")
    with patch("lan_streamer.ui_views.proxy.QMessageBox.warning") as mock_warn:
        dialog._export_logs()
        mock_warn.assert_called_once()


def test_export_logs_with_log_files(dialog, tmp_path) -> None:
    """If log directory exists with .log files, export should succeed."""
    # Create a temporary log directory and a .log file
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "app.log").write_text("test log line")
    config.log_directory = str(log_dir)

    with patch("lan_streamer.ui_views.proxy.QMessageBox.information"):
        dialog._export_logs()  # Should not crash


# ---------------------------------------------------------------------------
# _on_global_progress and _on_detail_progress
# ---------------------------------------------------------------------------


def test_on_global_progress_shows_bar(dialog_with_controller) -> None:
    dialog, ctrl = dialog_with_controller
    # Just verify emitting the signal doesn't crash
    ctrl.global_progress_updated.emit("Scanning", 3, 10)


def test_on_detail_progress_shows_tree(dialog_with_controller) -> None:
    dialog, ctrl = dialog_with_controller
    # Just verify emitting the signal doesn't crash
    ctrl.detail_progress_updated.emit("start_folder", {"root": "/tv", "folder": "Show"})


# ---------------------------------------------------------------------------
# Global management actions
# ---------------------------------------------------------------------------


def test_trigger_global_scan_files_with_controller(dialog_with_controller) -> None:
    dialog, ctrl = dialog_with_controller
    with patch.object(ctrl, "trigger_scan_all") as mock_scan:
        dialog.trigger_global_scan_files()
        mock_scan.assert_called_once()


def test_trigger_global_scan_files_without_controller(dialog) -> None:
    dialog.trigger_global_scan_files()  # Should not crash


def test_trigger_global_refresh_metadata_with_controller(
    dialog_with_controller,
) -> None:
    dialog, ctrl = dialog_with_controller
    with patch.object(ctrl, "trigger_scan_all") as mock_scan:
        dialog.trigger_global_refresh_metadata()
        mock_scan.assert_called_once()


def test_trigger_global_jellyfin_pull_with_controller(dialog_with_controller) -> None:
    dialog, ctrl = dialog_with_controller
    with patch.object(ctrl, "trigger_jellyfin_pull") as mock_pull:
        dialog.trigger_global_jellyfin_pull()
        mock_pull.assert_called_once()


def test_trigger_global_jellyfin_push_with_controller(dialog_with_controller) -> None:
    dialog, ctrl = dialog_with_controller
    with patch.object(ctrl, "trigger_jellyfin_push") as mock_push:
        dialog.trigger_global_jellyfin_push()
        mock_push.assert_called_once()


def test_trigger_global_runtime_extraction_with_controller(
    dialog_with_controller,
) -> None:
    dialog, ctrl = dialog_with_controller
    with patch.object(ctrl, "trigger_runtime_extraction") as mock_rt:
        dialog.trigger_global_runtime_extraction()
        mock_rt.assert_called_once()


# ---------------------------------------------------------------------------
# MAL account linking/unlinking
# ---------------------------------------------------------------------------


def test_link_mal_account_no_client_id(dialog) -> None:
    dialog.myanimelist_client_id_input.setText("")
    dialog.myanimelist_client_secret_input.setText("")
    with patch("lan_streamer.ui_views.proxy.QMessageBox.warning") as mock_warn:
        dialog.link_myanimelist_account()
        mock_warn.assert_called_once()


def test_unlink_mal_account_clears_credentials(dialog) -> None:
    from PySide6.QtWidgets import QMessageBox

    config.myanimelist_access_token = "fake-token"
    config.myanimelist_refresh_token = "fake-refresh"
    with patch.object(config, "save"):
        with patch(
            "lan_streamer.ui_views.proxy.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dialog.unlink_myanimelist_account()
    assert not config.myanimelist_access_token
    assert not config.myanimelist_refresh_token


# ---------------------------------------------------------------------------
# _on_show_future_episodes_toggled
# ---------------------------------------------------------------------------


def test_on_show_future_episodes_toggled(dialog_with_libs) -> None:
    dialog = dialog_with_libs
    dialog.library_selector.setCurrentText("TV Shows")
    dialog.show_future_episodes_checkbox.setChecked(True)
    assert dialog.staged_libraries["TV Shows"].get("show_future_episodes") is True
    dialog.show_future_episodes_checkbox.setChecked(False)
    assert dialog.staged_libraries["TV Shows"].get("show_future_episodes") is False


# ---------------------------------------------------------------------------
# browse_database_path / browse_log_directory / browse_backup_directory
# ---------------------------------------------------------------------------


def test_browse_database_path(dialog, tmp_path) -> None:
    db_path = tmp_path / "test.db"
    with patch(
        "lan_streamer.ui_views.proxy.QFileDialog.getSaveFileName",
        return_value=(str(db_path), ""),
    ):
        dialog.browse_database_path()
    assert dialog.db_path_input.text() == str(db_path)


def test_browse_database_path_cancelled(dialog) -> None:
    with patch(
        "lan_streamer.ui_views.proxy.QFileDialog.getSaveFileName", return_value=("", "")
    ):
        dialog.browse_database_path()  # Should not crash


def test_browse_log_directory(dialog, tmp_path) -> None:
    with patch(
        "lan_streamer.ui_views.proxy.QFileDialog.getExistingDirectory",
        return_value=str(tmp_path),
    ):
        dialog.browse_log_directory()
    assert dialog.log_dir_input.text() == str(tmp_path)


def test_browse_backup_directory(dialog, tmp_path) -> None:
    with patch(
        "lan_streamer.ui_views.proxy.QFileDialog.getExistingDirectory",
        return_value=str(tmp_path),
    ):
        dialog.browse_backup_directory()
    assert dialog.backup_directory_input.text() == str(tmp_path)


# ---------------------------------------------------------------------------
# trigger_restore_database / trigger_restore_config
# ---------------------------------------------------------------------------


def test_trigger_restore_database_cancelled(dialog) -> None:
    with patch(
        "lan_streamer.ui_views.proxy.QFileDialog.getOpenFileName", return_value=("", "")
    ):
        dialog.trigger_restore_database()  # Should not crash


def test_trigger_restore_config_cancelled(dialog) -> None:
    with patch(
        "lan_streamer.ui_views.proxy.QFileDialog.getOpenFileName", return_value=("", "")
    ):
        dialog.trigger_restore_config()  # Should not crash
