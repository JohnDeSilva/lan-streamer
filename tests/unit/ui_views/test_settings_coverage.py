"""Targeted tests for SettingsDialog uncovered lines."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox

from lan_streamer.ui_views.dialogs.settings import SettingsDialog
from lan_streamer.system.config import config


@pytest.fixture
def make_dialog(qtbot: Any) -> SettingsDialog:
    """Create a fresh SettingsDialog with controller mocked, for fast tests."""
    controller = MagicMock()
    controller.scheduled_scan_service = MagicMock()
    with (
        patch("lan_streamer.ui_views.dialogs.settings.config", config),
        patch("lan_streamer.system.logging_handler.qt_log_handler") as mock_log_handler,
    ):
        mock_log_handler.buffer = []
        mock_log_handler.emitter = MagicMock()
        dialog = SettingsDialog(controller_instance=controller)
        qtbot.addWidget(dialog)
    return dialog


# ── _on_row_property_changed ────────────────────────────────────────


class TestOnRowPropertyChanged:
    def test_returns_early_when_no_row_selected(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Line 1071: early return when currentRow() == -1."""
        dialog = make_dialog
        dialog.combined_views_list_widget.setCurrentRow(-1)
        dialog._on_row_property_changed()

    def test_returns_early_when_index_out_of_bounds(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Line 1071: early return when index >= len(staged_combined_views)."""
        dialog = make_dialog
        dialog.staged_combined_views = []
        dialog.combined_views_list_widget.setCurrentRow(0)
        dialog._on_row_property_changed()

    def test_auto_updates_name_when_name_matches_old_default(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1088-1091: name auto-updates when current matches old default."""
        dialog = make_dialog
        row = {
            "enabled": True,
            "libraries": [],
            "sort_by": "Alphabetical",
            "filter_mode": "All",
            "max_items": 20,
            "name": "",
        }
        dialog.staged_combined_views = [row]
        dialog.combined_views_list_widget.addItem("test")
        dialog.combined_views_list_widget.setCurrentRow(0)
        dialog.row_name_input.setText("")
        dialog._on_row_property_changed()
        assert row["name"] == dialog._get_default_row_name(row)

    def test_auto_updates_name_when_name_is_new_smart_row(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1088-1091: name auto-updates when current is 'New Smart Row'."""
        dialog = make_dialog
        row = {
            "enabled": True,
            "libraries": [],
            "sort_by": "Alphabetical",
            "filter_mode": "All",
            "max_items": 20,
            "name": "New Smart Row",
        }
        dialog.staged_combined_views = [row]
        dialog.combined_views_list_widget.addItem("test")
        dialog.combined_views_list_widget.setCurrentRow(0)
        dialog.row_name_input.setText("New Smart Row")
        dialog._on_row_property_changed()
        assert row["name"] == dialog._get_default_row_name(row)

    def test_preserves_custom_name(self, make_dialog: SettingsDialog) -> None:
        """Lines 1092-1093: custom name is preserved."""
        dialog = make_dialog
        row = {
            "enabled": True,
            "libraries": [],
            "sort_by": "Alphabetical",
            "filter_mode": "All",
            "max_items": 20,
            "name": "Old Default",
        }
        dialog.staged_combined_views = [row]
        dialog.combined_views_list_widget.addItem("test")
        dialog.combined_views_list_widget.setCurrentRow(0)
        dialog.row_name_input.setText("My Custom Row")
        dialog._on_row_property_changed()
        assert row["name"] == "My Custom Row"


# ── _on_row_library_toggled ─────────────────────────────────────────


class TestOnRowLibraryToggled:
    def test_returns_early_when_no_row_selected(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Line 1104: early return when no row selected."""
        dialog = make_dialog
        dialog.combined_views_list_widget.setCurrentRow(-1)
        dialog._on_row_library_toggled()


# ── move_library_order_up / down ────────────────────────────────────


class TestMoveLibraryOrder:
    def test_move_up_returns_early_at_top(self, make_dialog: SettingsDialog) -> None:
        """Line 1205: early return when row_idx <= 0."""
        dialog = make_dialog
        dialog.staged_libraries = {"Lib A": {}, "Lib B": {}}
        dialog.library_order_list_widget.addItem("Lib A")
        dialog.library_order_list_widget.addItem("Lib B")
        dialog.library_order_list_widget.setCurrentRow(0)
        dialog.move_library_order_up()
        keys = list(dialog.staged_libraries.keys())
        assert keys[0] == "Lib A"

    def test_move_up_returns_early_when_empty(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Line 1205: early return when no libraries."""
        dialog = make_dialog
        dialog.staged_libraries = {}
        dialog.library_order_list_widget.setCurrentRow(-1)
        dialog.move_library_order_up()

    def test_move_down_returns_early_at_bottom(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Line 1222: early return when row_idx >= len - 1."""
        dialog = make_dialog
        dialog.staged_libraries = {"Lib A": {}, "Lib B": {}}
        dialog.library_order_list_widget.addItem("Lib A")
        dialog.library_order_list_widget.addItem("Lib B")
        dialog.library_order_list_widget.setCurrentRow(1)
        dialog.move_library_order_down()
        keys = list(dialog.staged_libraries.keys())
        assert keys[1] == "Lib B"

    def test_move_down_returns_early_when_empty(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Line 1222: early return when no libraries."""
        dialog = make_dialog
        dialog.staged_libraries = {}
        dialog.library_order_list_widget.setCurrentRow(-1)
        dialog.move_library_order_down()


# ── save_config — ValueError fallback paths ─────────────────────────


def _save_config_no_warning(dialog: SettingsDialog) -> None:
    """Call save_config with all backup inputs set to safe values to avoid warning dialog."""
    dialog.database_backup_frequency_input.setText("0")
    dialog.database_backup_retention_input.setText("0")
    dialog.config_backup_frequency_input.setText("0")
    dialog.config_backup_retention_input.setText("0")
    with (
        patch.object(config, "save"),
        patch.object(config, "save_to_db"),
        patch("lan_streamer.system.logging_handler.set_application_log_level"),
    ):
        dialog.save_config()


class TestSaveConfigParsing:
    def test_backup_freq_value_error_keeps_original(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1506-1510: non-integer db backup freq preserves existing value."""
        dialog = make_dialog
        original_frequency = config.database_backup_frequency
        dialog.database_backup_frequency_input.setText("not_a_number")
        dialog.database_backup_retention_input.setText("0")
        dialog.config_backup_frequency_input.setText("0")
        dialog.config_backup_retention_input.setText("0")
        with (
            patch.object(config, "save"),
            patch.object(config, "save_to_db"),
            patch("lan_streamer.system.logging_handler.set_application_log_level"),
        ):
            dialog.save_config()
        assert config.database_backup_frequency == original_frequency

    def test_backup_retention_value_error_keeps_zero(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1391-1392: non-integer db backup retention defaults to 0."""
        dialog = make_dialog
        original_retention = config.database_backup_retention
        dialog.database_backup_frequency_input.setText("0")
        dialog.config_backup_frequency_input.setText("0")
        dialog.config_backup_retention_input.setText("0")
        with (
            patch.object(config, "save"),
            patch.object(config, "save_to_db"),
            patch("lan_streamer.system.logging_handler.set_application_log_level"),
            patch.object(
                dialog.database_backup_retention_input,
                "text",
                return_value="xyz",
            ),
        ):
            dialog.save_config()
        assert config.database_backup_retention == original_retention

    def test_config_backup_freq_value_error_keeps_zero(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1398-1399: non-integer config backup freq defaults to 0."""
        dialog = make_dialog
        original_freq = config.config_backup_frequency
        dialog.config_backup_retention_input.setText("0")
        dialog.database_backup_frequency_input.setText("0")
        dialog.database_backup_retention_input.setText("0")
        with (
            patch.object(config, "save"),
            patch.object(config, "save_to_db"),
            patch("lan_streamer.system.logging_handler.set_application_log_level"),
            patch.object(
                dialog.config_backup_frequency_input,
                "text",
                return_value="abc",
            ),
        ):
            dialog.save_config()
        assert config.config_backup_frequency == original_freq

    def test_config_backup_retention_value_error_keeps_zero(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1402-1403: non-integer config backup retention defaults to 0."""
        dialog = make_dialog
        original_retention = config.config_backup_retention
        dialog.config_backup_frequency_input.setText("0")
        dialog.database_backup_frequency_input.setText("0")
        dialog.database_backup_retention_input.setText("0")
        with (
            patch.object(config, "save"),
            patch.object(config, "save_to_db"),
            patch("lan_streamer.system.logging_handler.set_application_log_level"),
            patch.object(
                dialog.config_backup_retention_input,
                "text",
                return_value="bad",
            ),
        ):
            dialog.save_config()
        assert config.config_backup_retention == original_retention

    def test_backup_warning_shown_and_user_declines(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1406-1429: backup warning when retention < freq, user clicks No."""
        dialog = make_dialog
        dialog.database_backup_frequency_input.setText("10")
        dialog.database_backup_retention_input.setText("5")
        dialog.config_backup_frequency_input.setText("0")
        dialog.config_backup_retention_input.setText("0")
        with (
            patch.object(config, "save") as mock_save,
            patch.object(config, "save_to_db"),
            patch(
                "lan_streamer.ui_views.dialogs.settings.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ),
        ):
            dialog.save_config()
        mock_save.assert_not_called()

    def test_backup_warning_user_accepts(self, make_dialog: SettingsDialog) -> None:
        """Lines 1406-1429: backup warning shown, user clicks Yes."""
        dialog = make_dialog
        dialog.database_backup_frequency_input.setText("10")
        dialog.database_backup_retention_input.setText("5")
        dialog.config_backup_frequency_input.setText("0")
        dialog.config_backup_retention_input.setText("0")
        with (
            patch.object(config, "save"),
            patch.object(config, "save_to_db"),
            patch(
                "lan_streamer.ui_views.dialogs.settings.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch("lan_streamer.system.logging_handler.set_application_log_level"),
        ):
            dialog.save_config()

    def test_watched_threshold_over_100_converts(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1460-1463: threshold > 1.0 is divided by 100."""
        dialog = make_dialog
        dialog.watched_threshold_input.setText("85")
        _save_config_no_warning(dialog)
        assert abs(config.watched_threshold - 0.85) < 0.001

    def test_watched_threshold_value_error_keeps_default(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1464-1465: non-float threshold keeps old value."""
        dialog = make_dialog
        original = config.watched_threshold
        dialog.watched_threshold_input.setText("bad")
        _save_config_no_warning(dialog)
        assert config.watched_threshold == original

    def test_max_cache_size_value_error(self, make_dialog: SettingsDialog) -> None:
        """Lines 1469-1470: non-float cache size keeps old value."""
        dialog = make_dialog
        original = config.max_cache_size_gb
        dialog.max_cache_size_input.setText("bad")
        _save_config_no_warning(dialog)
        assert config.max_cache_size_gb == original

    def test_vlc_buffer_value_error(self, make_dialog: SettingsDialog) -> None:
        """Lines 1474-1475: non-int VLC buffer keeps old value."""
        dialog = make_dialog
        original = config.vlc_buffer_ms
        dialog.vlc_buffer_input.setText("abc")
        _save_config_no_warning(dialog)
        assert config.vlc_buffer_ms == original

    def test_config_backup_freq_value_error_on_save(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1502-1503: non-int config backup freq."""
        dialog = make_dialog
        dialog.config_backup_frequency_input.setText("NaN")
        dialog.config_backup_retention_input.setText("0")
        dialog.database_backup_frequency_input.setText("0")
        dialog.database_backup_retention_input.setText("0")
        with (
            patch.object(config, "save"),
            patch.object(config, "save_to_db"),
            patch("lan_streamer.system.logging_handler.set_application_log_level"),
        ):
            dialog.save_config()

    def test_db_backup_freq_value_error_on_save(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1509-1510: non-int db backup freq."""
        dialog = make_dialog
        dialog.database_backup_frequency_input.setText("NaN")
        dialog.database_backup_retention_input.setText("0")
        dialog.config_backup_frequency_input.setText("0")
        dialog.config_backup_retention_input.setText("0")
        with (
            patch.object(config, "save"),
            patch.object(config, "save_to_db"),
            patch("lan_streamer.system.logging_handler.set_application_log_level"),
        ):
            dialog.save_config()

    def test_config_backup_retention_value_error_on_save(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1516-1517: non-int config backup retention."""
        dialog = make_dialog
        dialog.config_backup_retention_input.setText("NaN")
        dialog.config_backup_frequency_input.setText("0")
        dialog.database_backup_frequency_input.setText("0")
        dialog.database_backup_retention_input.setText("0")
        with (
            patch.object(config, "save"),
            patch.object(config, "save_to_db"),
            patch("lan_streamer.system.logging_handler.set_application_log_level"),
        ):
            dialog.save_config()

    def test_db_backup_retention_value_error_on_save(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1523-1524: non-int db backup retention."""
        dialog = make_dialog
        dialog.database_backup_retention_input.setText("NaN")
        dialog.database_backup_frequency_input.setText("0")
        dialog.config_backup_frequency_input.setText("0")
        dialog.config_backup_retention_input.setText("0")
        with (
            patch.object(config, "save"),
            patch.object(config, "save_to_db"),
            patch("lan_streamer.system.logging_handler.set_application_log_level"),
        ):
            dialog.save_config()

    def test_add_staged_library_anime_type(self, make_dialog: SettingsDialog) -> None:
        """Line 1293: library type = 'anime'."""
        dialog = make_dialog
        dialog.library_name_input.setText("AnimeLib")
        dialog.library_type_input.setCurrentText("Anime")
        dialog.add_staged_library()
        assert "AnimeLib" in dialog.staged_libraries
        assert dialog.staged_libraries["AnimeLib"]["type"] == "anime"

    def test_save_config_watched_threshold_below_one(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Line 1463: threshold <= 1.0 is stored directly."""
        dialog = make_dialog
        dialog.watched_threshold_input.setText("0.5")
        _save_config_no_warning(dialog)
        assert abs(config.watched_threshold - 0.5) < 0.001


# ── MAL OAuth flow ──────────────────────────────────────────────────


class TestMALOAuthFlow:
    def test_link_mal_no_client_id(self, make_dialog: SettingsDialog) -> None:
        """Lines 1556-1560: warning shown when Client ID empty."""
        dialog = make_dialog
        dialog.myanimelist_client_id_input.setText("")
        with patch(
            "lan_streamer.ui_views.dialogs.settings.QMessageBox.warning"
        ) as mock_warn:
            dialog.link_myanimelist_account()
        mock_warn.assert_called_once()

    def test_link_mal_user_cancels_input_dialog(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1588-1589: early return when user cancels QInputDialog."""
        dialog = make_dialog
        dialog.myanimelist_client_id_input.setText("test_id")
        dialog.myanimelist_client_secret_input.setText("test_secret")
        with (
            patch("lan_streamer.ui_views.dialogs.settings.QMessageBox.warning"),
            patch("webbrowser.open"),
            patch(
                "PySide6.QtWidgets.QInputDialog.getText",
                return_value=("", False),
            ),
            patch("lan_streamer.ui_views.proxy.myanimelist_client") as mock_mal,
            patch.object(config, "save_to_db"),
        ):
            mock_mal.generate_auth_url.return_value = "http://example.invalid/auth"
            dialog.link_myanimelist_account()

    def test_link_mal_wrong_url_authorize_page(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 1593-1605: warning when user pastes the authorize page URL."""
        dialog = make_dialog
        dialog.myanimelist_client_id_input.setText("test_id")
        dialog.myanimelist_client_secret_input.setText("test_secret")
        authorize_url = "https://example.invalid/v1/oauth2/authorize?response_type=code"
        with (
            patch(
                "lan_streamer.ui_views.dialogs.settings.QMessageBox.warning"
            ) as mock_warn,
            patch("webbrowser.open"),
            patch(
                "PySide6.QtWidgets.QInputDialog.getText",
                return_value=(authorize_url, True),
            ),
            patch("lan_streamer.ui_views.proxy.myanimelist_client") as mock_mal,
            patch.object(config, "save_to_db"),
        ):
            mock_mal.generate_auth_url.return_value = "http://example.invalid/auth"
            dialog.link_myanimelist_account()
        mock_warn.assert_called_once()

    def test_link_mal_no_code_in_pasted_text(self, make_dialog: SettingsDialog) -> None:
        """Lines 1612-1619: warning when no code found in pasted URL."""
        dialog = make_dialog
        dialog.myanimelist_client_id_input.setText("test_id")
        dialog.myanimelist_client_secret_input.setText("test_secret")
        with (
            patch(
                "lan_streamer.ui_views.dialogs.settings.QMessageBox.warning"
            ) as mock_warn,
            patch("webbrowser.open"),
            patch(
                "PySide6.QtWidgets.QInputDialog.getText",
                return_value=("http://example.invalid/bad_url", True),
            ),
            patch("lan_streamer.ui_views.proxy.myanimelist_client") as mock_mal,
            patch.object(config, "save_to_db"),
        ):
            mock_mal.generate_auth_url.return_value = "http://example.invalid/auth"
            dialog.link_myanimelist_account()
        mock_warn.assert_called_once()

    def test_link_mal_exchange_success(self, make_dialog: SettingsDialog) -> None:
        """Lines 1621-1623: success path after valid code exchange."""
        dialog = make_dialog
        dialog.myanimelist_client_id_input.setText("test_id")
        dialog.myanimelist_client_secret_input.setText("test_secret")
        redirect_url = "http://localhost/?code=abc123"
        with (
            patch(
                "lan_streamer.ui_views.dialogs.settings.QMessageBox.information"
            ) as mock_info,
            patch("webbrowser.open"),
            patch(
                "PySide6.QtWidgets.QInputDialog.getText",
                return_value=(redirect_url, True),
            ),
            patch("lan_streamer.ui_views.proxy.myanimelist_client") as mock_mal,
            patch.object(config, "save_to_db"),
        ):
            mock_mal.generate_auth_url.return_value = "http://example.invalid/auth"
            mock_mal.exchange_auth_code.return_value = (True, "Linked successfully")
            dialog.link_myanimelist_account()
        mock_info.assert_called_once()

    def test_link_mal_exchange_failure(self, make_dialog: SettingsDialog) -> None:
        """Lines 1624-1625: error shown on failed code exchange."""
        dialog = make_dialog
        dialog.myanimelist_client_id_input.setText("test_id")
        dialog.myanimelist_client_secret_input.setText("test_secret")
        redirect_url = "http://localhost/?code=bad_code"
        with (
            patch(
                "lan_streamer.ui_views.dialogs.settings.QMessageBox.critical"
            ) as mock_crit,
            patch("webbrowser.open"),
            patch(
                "PySide6.QtWidgets.QInputDialog.getText",
                return_value=(redirect_url, True),
            ),
            patch("lan_streamer.ui_views.proxy.myanimelist_client") as mock_mal,
            patch.object(config, "save_to_db"),
        ):
            mock_mal.generate_auth_url.return_value = "http://example.invalid/auth"
            mock_mal.exchange_auth_code.return_value = (False, "Exchange failed")
            dialog.link_myanimelist_account()
        mock_crit.assert_called_once()


# ── _update_mal_status_ui ───────────────────────────────────────────


class TestMALStatusUI:
    def test_connected_status(self, make_dialog: SettingsDialog) -> None:
        """Lines 1648-1650: when authenticated, shows Connected."""
        dialog = make_dialog
        with patch("lan_streamer.ui_views.proxy.myanimelist_client") as mock_mal:
            mock_mal.is_authenticated.return_value = True
            dialog._update_mal_status_ui()
        assert "Connected" in dialog.myanimelist_status_label.text()
        assert not dialog.myanimelist_unlink_button.isHidden()

    def test_not_connected_status(self, make_dialog: SettingsDialog) -> None:
        """Lines 1651-1654: when not authenticated, shows Not connected."""
        dialog = make_dialog
        with patch("lan_streamer.ui_views.proxy.myanimelist_client") as mock_mal:
            mock_mal.is_authenticated.return_value = False
            dialog._update_mal_status_ui()
        assert "Not connected" in dialog.myanimelist_status_label.text()


# ── trigger_restore_config failure ──────────────────────────────────


class TestRestoreConfig:
    def test_restore_config_failure_shows_critical(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Line 1693: restore_config returns False."""
        dialog = make_dialog
        with (
            patch(
                "lan_streamer.ui_views.dialogs.settings.QFileDialog.getOpenFileName",
                return_value=("test.json", ""),
            ),
            patch(
                "lan_streamer.system.backup.restore_config_backup",
                return_value=False,
            ),
            patch(
                "lan_streamer.ui_views.dialogs.settings.QMessageBox.critical"
            ) as mock_crit,
        ):
            dialog.trigger_restore_config()
        mock_crit.assert_called_once()

    def test_restore_database_failure_shows_critical(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Line 1718: restore_database returns False."""
        dialog = make_dialog
        with (
            patch(
                "lan_streamer.ui_views.dialogs.settings.QFileDialog.getOpenFileName",
                return_value=("test.db", ""),
            ),
            patch(
                "lan_streamer.system.backup.restore_database_backup",
                return_value=False,
            ),
            patch(
                "lan_streamer.ui_views.dialogs.settings.QMessageBox.critical"
            ) as mock_crit,
        ):
            dialog.trigger_restore_database()
        mock_crit.assert_called_once()


# ── _on_detail_progress scan events ─────────────────────────────────


class TestOnDetailProgress:
    def _make_dialog(self, qtbot: Any) -> SettingsDialog:
        controller = MagicMock()
        controller.scheduled_scan_service = MagicMock()
        with (
            patch("lan_streamer.ui_views.dialogs.settings.config", config),
            patch(
                "lan_streamer.system.logging_handler.qt_log_handler"
            ) as mock_log_handler,
        ):
            mock_log_handler.buffer = []
            mock_log_handler.emitter = MagicMock()
            dialog = SettingsDialog(controller_instance=controller)
            qtbot.addWidget(dialog)
        return dialog

    def test_init_tree_event(self, qtbot: Any) -> None:
        """Lines 1741-1757: init_tree event."""
        dialog = self._make_dialog(qtbot)
        dialog.show()
        qtbot.waitUntil(lambda: dialog.isVisible())
        dialog._scan_running = False
        payload = {
            "tree": {"TV": {"root1": 10}},
            "library_order": ["TV"],
        }
        dialog._on_detail_progress("init_tree", payload)
        assert dialog.global_progress_bar.isVisible()

    def test_init_tree_when_scan_running(self, qtbot: Any) -> None:
        """Lines 1752-1754: scan_progress_tree hidden when _scan_running."""
        dialog = self._make_dialog(qtbot)
        dialog.show()
        qtbot.waitUntil(lambda: dialog.isVisible())
        dialog._scan_running = True
        payload = {
            "tree": {"TV": {"root1": 10}},
            "library_order": ["TV"],
        }
        dialog._on_detail_progress("init_tree", payload)
        assert dialog.scan_report_display.isVisible()

    def test_start_library(self, qtbot: Any) -> None:
        """Lines 1759-1761: start_library event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress("start_library", {"library": "TV"})

    def test_finish_library(self, qtbot: Any) -> None:
        """Lines 1763-1765: finish_library event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress("finish_library", {"library": "TV"})

    def test_fail_library(self, qtbot: Any) -> None:
        """Lines 1767-1769: fail_library event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress("fail_library", {"library": "TV"})

    def test_start_folder(self, qtbot: Any) -> None:
        """Lines 1771-1773: start_folder event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress(
            "start_folder",
            {"library": "TV", "root": "/tv", "folder": "/tv/shows"},
        )

    def test_finish_folder(self, qtbot: Any) -> None:
        """Lines 1775-1779: finish_folder event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress(
            "finish_folder",
            {"library": "TV", "root": "/tv", "folder": "/tv/shows", "skipped": True},
        )

    def test_start_season(self, qtbot: Any) -> None:
        """Lines 1781-1782: start_season event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress(
            "start_season",
            {"library": "TV", "folder": "/tv/shows", "season": "Season 1"},
        )

    def test_finish_season(self, qtbot: Any) -> None:
        """Lines 1784-1785: finish_season event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress(
            "finish_season",
            {"library": "TV", "folder": "/tv/shows", "season": "Season 1"},
        )

    def test_start_file(self, qtbot: Any) -> None:
        """Lines 1787-1788: start_file event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress(
            "start_file",
            {"library": "TV", "folder": "/tv", "season": "S01", "file": "/tv/ep.mkv"},
        )

    def test_finish_file(self, qtbot: Any) -> None:
        """Lines 1790-1791: finish_file event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress("finish_file", {"file": "/tv/ep.mkv"})

    def test_start_offline_scan(self, qtbot: Any) -> None:
        """Lines 1793-1794: start_offline_scan event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress("start_offline_scan", {})

    def test_start_metadata_resolution(self, qtbot: Any) -> None:
        """Lines 1796-1797: start_metadata_resolution event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress("start_metadata_resolution", {})

    def test_runtime_extraction_progress(self, qtbot: Any) -> None:
        """Lines 1799-1802: runtime_extraction_progress event."""
        dialog = self._make_dialog(qtbot)
        dialog._on_detail_progress(
            "runtime_extraction_progress", {"completed": 5, "total": 10}
        )


# ── _export_logs exception ──────────────────────────────────────────


class TestExportLogs:
    def test_export_logs_exception_shows_critical(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 2001-2002: exception during export (inside try block)."""
        dialog = make_dialog
        fake_file = MagicMock()
        fake_file.is_file.return_value = True
        fake_file.name = "test.log"
        with (
            patch("lan_streamer.ui_views.dialogs.settings.Path") as mock_path_cls,
            patch(
                "lan_streamer.ui_views.dialogs.settings.QMessageBox.critical"
            ) as mock_crit,
            patch("lan_streamer.ui_views.dialogs.settings.zipfile") as mock_zipfile,
        ):
            mock_path_cls.return_value.is_dir.return_value = True
            mock_path_cls.return_value.glob.return_value = [fake_file]
            mock_path_cls.home.return_value = Path("/tmp")
            mock_zipfile.ZipFile.side_effect = OSError("disk full")
            mock_zipfile.ZIP_DEFLATED = 8
            dialog._export_logs()
        mock_crit.assert_called_once()


# ── _on_log_emitted ─────────────────────────────────────────────────


class TestOnLogEmitted:
    def test_buffer_overflow_pops_oldest(self, make_dialog: SettingsDialog) -> None:
        """Lines 2055-2056: when >1000 records, oldest is dropped."""
        dialog = make_dialog
        dialog.all_log_records = [("msg", "INFO")] * 1000
        dialog._on_log_emitted("new message", "INFO")
        assert len(dialog.all_log_records) == 1000
        assert dialog.all_log_records[-1] == ("new message", "INFO")

    def test_scan_report_separator_detection(self, make_dialog: SettingsDialog) -> None:
        """Lines 2060-2063: is_separator check within scan report."""
        dialog = make_dialog
        dialog._scan_running = True
        separator_line = "[SCAN_REPORT] ----"
        dialog._on_log_emitted(separator_line, "INFO")
        assert separator_line in [msg for msg, _ in dialog.all_log_records]

    def test_non_scan_log_no_report_insert(self, make_dialog: SettingsDialog) -> None:
        """Lines 2082+: regular log lines are displayed (not inserted to report)."""
        dialog = make_dialog
        dialog._scan_running = True
        dialog._on_log_emitted("Regular log line", "INFO")
        assert len(dialog.all_log_records) == 1


# ── _disconnect_signals ─────────────────────────────────────────────


class TestDisconnectSignals:
    def test_disconnect_when_connected(self, make_dialog: SettingsDialog) -> None:
        """Lines 2109-2135: disconnects all signals."""
        dialog = make_dialog
        dialog._logging_connected = True
        with patch(
            "lan_streamer.system.logging_handler.qt_log_handler"
        ) as mock_log_handler:
            mock_log_handler.emitter = MagicMock()
            dialog._disconnect_signals()
        assert not dialog._logging_connected

    def test_disconnect_with_no_controller(self, make_dialog: SettingsDialog) -> None:
        """Lines 2109-2134: when controller is None."""
        dialog = make_dialog
        dialog.controller = None
        dialog._logging_connected = False
        dialog._disconnect_signals()

    def test_disconnect_exception_does_not_raise(
        self, make_dialog: SettingsDialog
    ) -> None:
        """Lines 2112-2134: exception paths are swallowed."""
        dialog = make_dialog
        dialog.controller = MagicMock()
        dialog.controller.global_progress_updated.disconnect.side_effect = RuntimeError
        dialog.controller.detail_progress_updated.disconnect.side_effect = RuntimeError
        dialog.controller.scan_completed.disconnect.side_effect = RuntimeError
        dialog._logging_connected = False
        dialog._disconnect_signals()

    def test_close_event_calls_disconnect(self, make_dialog: SettingsDialog) -> None:
        """Lines 2137-2139: closeEvent calls _disconnect_signals."""
        dialog = make_dialog
        with patch.object(dialog, "_disconnect_signals") as mock_disconnect:
            from PySide6.QtGui import QCloseEvent

            event = QCloseEvent()
            dialog.closeEvent(event)
            mock_disconnect.assert_called_once()
