import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import Qt
from lan_streamer import ui
from lan_streamer.config import config
from lan_streamer.ui import (
    MainWindow,
    LibrarySettingsDialog,
    JellyfinSettingsDialog,
    GeneralSettingsDialog,
)


@pytest.fixture
def app(qtbot):
    if not QApplication.instance():
        app = QApplication([])
    else:
        app = QApplication.instance()
    return app


@pytest.fixture
def mock_dependencies():
    mock_db = MagicMock()
    mock_db.natural_sort_key = ui.db.natural_sort_key

    mock_worker_class = MagicMock()
    mock_worker = MagicMock()
    mock_worker_class.return_value = mock_worker

    mock_sync_worker_class = MagicMock()
    mock_sync_worker = MagicMock()
    mock_sync_worker_class.return_value = mock_sync_worker

    mock_pull_worker_class = MagicMock()
    mock_pull_worker = MagicMock()
    mock_pull_worker_class.return_value = mock_pull_worker

    mock_push_worker_class = MagicMock()
    mock_push_worker = MagicMock()
    mock_push_worker_class.return_value = mock_push_worker

    mock_cleanup_worker_class = MagicMock()
    mock_cleanup_worker = MagicMock()
    mock_cleanup_worker_class.return_value = mock_cleanup_worker

    # Globally save original workers BEFORE patching them
    ui.OriginalScanWorker = ui.ScanWorker
    ui.OriginalSyncAllWorker = ui.SyncAllWorker
    ui.OriginalCleanupWorker = ui.CleanupWorker

    with (
        patch.object(ui, "db", mock_db),
        patch.object(ui, "config", config),
        patch.object(ui, "jellyfin_client", MagicMock()),
        patch.object(ui, "tmdb_client", MagicMock()),
        patch.object(ui, "play_video", MagicMock()),
        patch.object(ui, "scan_directories", MagicMock()),
        patch.object(ui, "ScanWorker", mock_worker_class),
        patch.object(ui, "SyncAllWorker", mock_sync_worker_class),
        patch.object(ui, "JellyfinPullWorker", mock_pull_worker_class),
        patch.object(ui, "JellyfinPushWorker", mock_push_worker_class),
        patch.object(ui, "CleanupWorker", mock_cleanup_worker_class),
    ):
        config.libraries = {"TestLib": ["/path1"]}
        config.jellyfin_url = ""
        config.jellyfin_api_key = ""
        config.tmdb_api_key = ""
        # Don't auto-run history pull on start in tests
        config.sync_history_on_start = False
        config.sort_mode = "Alphabetical"
        config.filter_unwatched = False

        # Mock DB response
        ui.db.load_library.return_value = {
            "Series A": {
                "metadata": {"jellyfin_id": "1", "poster_path": ""},
                "seasons": {
                    "Season 1": {
                        "metadata": {"jellyfin_id": "2", "poster_path": ""},
                        "episodes": [
                            {
                                "name": "Ep1",
                                "path": "/path1",
                                "jellyfin_id": "3",
                                "watched": False,
                            }
                        ],
                    }
                },
            }
        }
        yield


def test_library_settings_dialog(qtbot, mock_dependencies):
    dialog = LibrarySettingsDialog()
    qtbot.addWidget(dialog)

    assert dialog.library_combo.count() == 1
    assert dialog.library_combo.currentText() == "TestLib"

    # Add new library
    with patch("lan_streamer.ui.QInputDialog.getText", return_value=("NewLib", True)):
        dialog.add_library()
    assert dialog.library_combo.count() == 2
    assert "NewLib" in config.libraries

    # Try adding existing
    mock_warning = MagicMock()
    with (
        patch("lan_streamer.ui.QInputDialog.getText", return_value=("TestLib", True)),
        patch("lan_streamer.ui.QMessageBox.warning", mock_warning),
    ):
        dialog.add_library()

    # Add dir
    with patch("lan_streamer.ui.QFileDialog.getExistingDirectory", return_value="/tmp"):
        dialog.add_dir()
    assert "/tmp" in config.libraries["NewLib"]

    # Remove dir
    dialog.list_widget.setCurrentRow(0)
    dialog.remove_dir()
    assert "/tmp" not in config.libraries["NewLib"]

    # Remove library
    mock_msgbox = MagicMock()
    mock_msgbox.StandardButton.Yes = ui.QMessageBox.StandardButton.Yes
    mock_msgbox.question.return_value = ui.QMessageBox.StandardButton.Yes
    with patch("lan_streamer.ui.QMessageBox", mock_msgbox):
        dialog.remove_library()
    assert "NewLib" not in config.libraries

    # Test sync history on startup checkbox in GeneralSettingsDialog
    config.sync_history_on_start = True
    gen_dialog = GeneralSettingsDialog()
    qtbot.addWidget(gen_dialog)
    assert gen_dialog.sync_checkbox.isChecked() is True
    gen_dialog.sync_checkbox.setChecked(False)

    with patch("lan_streamer.ui.QMessageBox.information"):
        # We need to call accept() or manually update config in test if we want to check persistence via dialog
        gen_dialog.accept()
        assert config.sync_history_on_start is False

        gen_dialog.sync_checkbox.setChecked(True)
        gen_dialog.accept()
        assert config.sync_history_on_start is True

        # Test global log file checkbox
        assert gen_dialog.log_file_checkbox.isChecked() is False
        gen_dialog.log_file_checkbox.setChecked(True)
        gen_dialog.accept()
        assert config.enable_global_file_logging is True


def test_mainwindow_load(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.main_library_combo.currentText() == "TestLib"
    assert window.series_model.rowCount() == 1

    # Select series
    index = window.series_model.index(0, 0)
    window.on_series_selected(index)
    assert window.season_model.rowCount() == 1
    assert window.episode_model.rowCount() == 1

    ep_item = window.episode_model.item(0, 0)
    assert ep_item.text() == "[ ] Ep1"


def test_mainwindow_play_video(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    window.on_series_selected(window.series_model.index(0, 0))

    ep_item = window.episode_model.item(0, 0)
    index = window.episode_model.indexFromItem(ep_item)

    window.on_episode_double_clicked(index)

    ui.play_video.assert_called_once_with("/path1")
    ui.db.update_episode_watched_status.assert_called_once_with("/path1", True)
    assert ep_item.text() == "[✓] Ep1"


def test_mainwindow_force_scan(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    window.force_scan_library()
    ui.ScanWorker.return_value.start.assert_called_once()

    # Manually trigger the slot to test UI updates
    window.on_scan_finished({})

    ui.db.save_library.assert_called_once_with("TestLib", {})


def test_mainwindow_force_scan_error(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    mock_crit = MagicMock()
    with patch("lan_streamer.ui.QMessageBox.critical", mock_crit):
        window.force_scan_library()
        ui.ScanWorker.return_value.start.assert_called_once()

        # Manually trigger error slot
        window.on_scan_error("Mocked scan error")

        mock_crit.assert_called_once()
    assert window.refresh_action.isEnabled() is True


def test_scan_worker_logic(mock_dependencies):
    import lan_streamer.ui as ui_mod

    # Use the original class saved in the fixture
    ScanWorker = ui_mod.OriginalScanWorker

    # Ensure scan_directories returns something
    ui_mod.scan_directories.return_value = {"New Data": {}}

    worker = ScanWorker(["/path1"], {"Old Data": {}})

    mock_finished = MagicMock()
    mock_error = MagicMock()
    worker.finished.connect(mock_finished)
    worker.error.connect(mock_error)

    # Call run() directly (synchronous)
    worker.run()

    from unittest.mock import ANY

    ui_mod.scan_directories.assert_called_once_with(
        ["/path1"], existing_library={"Old Data": {}}, jellyfin_data=ANY, callback=ANY
    )
    mock_finished.assert_called_once_with({"New Data": {}})
    mock_error.assert_not_called()


def test_scan_worker_error_logic(mock_dependencies):
    import lan_streamer.ui as ui_mod

    ScanWorker = ui_mod.OriginalScanWorker

    ui_mod.scan_directories.side_effect = Exception("Logic Error")

    worker = ScanWorker(["/path1"], {})
    mock_finished = MagicMock()
    mock_error = MagicMock()
    worker.finished.connect(mock_finished)
    worker.error.connect(mock_error)

    worker.run()

    mock_finished.assert_not_called()
    mock_error.assert_called_once_with("Logic Error")
    # ScanWorker no longer calls clear_cache


def test_toggle_watched_status(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    window.on_series_selected(window.series_model.index(0, 0))

    episode_item = window.episode_model.item(0, 0)
    window.toggle_watched_status(episode_item, force_status=True)

    assert episode_item.text() == "[✓] Ep1"
    ui.db.update_episode_watched_status.assert_called_with("/path1", True)
    ui.jellyfin_client.set_watched_status.assert_called_with("3", True)


def test_ui_save_jellyfin_settings(qtbot, mock_dependencies):
    dialog = JellyfinSettingsDialog()
    qtbot.addWidget(dialog)
    dialog.jellyfin_url_input.setText("http://new-url")
    dialog.jellyfin_api_key_input.setText("new-key")

    mock_info = MagicMock()
    with patch("lan_streamer.ui.QMessageBox.information", mock_info):
        dialog.save_jellyfin_settings()

    assert config.jellyfin_url == "http://new-url"
    assert config.jellyfin_api_key == "new-key"


def test_ui_add_dir_errors(qtbot, mock_dependencies):
    dialog = LibrarySettingsDialog()
    qtbot.addWidget(dialog)

    # Empty library
    dialog.library_combo.clear()
    mock_warning = MagicMock()
    with (
        patch("lan_streamer.ui.QMessageBox.warning", mock_warning),
        patch("lan_streamer.ui.QFileDialog.getExistingDirectory", return_value=""),
    ):
        dialog.add_dir()
    mock_warning.assert_called()


def test_jellyfin_settings_dialog_full(qtbot, mock_dependencies):
    dialog = JellyfinSettingsDialog()
    qtbot.addWidget(dialog)

    # Mock QMessageBox
    mock_info = MagicMock()
    with patch("lan_streamer.ui.QMessageBox.information", mock_info):
        # Jellyfin settings
        dialog.jellyfin_url_input.setText("http://newurl")
        dialog.jellyfin_api_key_input.setText("newkey")
        dialog.save_jellyfin_settings()

    assert config.jellyfin_url == "http://newurl"
    assert config.jellyfin_api_key == "newkey"
    mock_info.assert_called_once()


def test_jellyfin_settings_test_connection(qtbot, mock_dependencies):
    dialog = JellyfinSettingsDialog()
    qtbot.addWidget(dialog)

    # Mock QMessageBox
    mock_info = MagicMock()
    mock_warn = MagicMock()
    with (
        patch("lan_streamer.ui.QMessageBox.information", mock_info),
        patch("lan_streamer.ui.QMessageBox.warning", mock_warn),
    ):
        # Mock validate_credentials
        ui.jellyfin_client.validate_credentials.return_value = (True, "Success")
        dialog.test_connection()
        mock_info.assert_called_once_with(dialog, "Success", "Success")

        ui.jellyfin_client.validate_credentials.return_value = (False, "Failed")
        dialog.test_connection()
        mock_warn.assert_called_once_with(dialog, "Connection Failed", "Failed")


def test_mainwindow_force_scan_empty(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    window.main_library_combo.setCurrentText("")
    window.force_scan_library()  # Should return early

    config.libraries["TestLib"] = []
    window.main_library_combo.setCurrentText("TestLib")
    window.force_scan_library()  # Should return early


def test_mainwindow_selection_errors(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    # Invalid index
    window.on_series_selected(window.series_model.index(99, 99))
    window.on_episode_double_clicked(window.episode_model.index(99, 99))


def test_mainwindow_context_menu(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    window.on_series_selected(window.series_model.index(0, 0))

    # Mock QMenu exec to return the first action
    def mock_exec(pos):
        return mock_menu.actions()[0]

    mock_menu = ui.QMenu()
    with (
        patch("lan_streamer.ui.QMenu", return_value=mock_menu),
        patch.object(mock_menu, "exec", mock_exec),
    ):
        ep_item = window.episode_model.item(0, 0)
        ep_index = window.episode_model.indexFromItem(ep_item)

        window.show_episode_context_menu(
            window.episode_view.visualRect(ep_index).center()
        )
        # The action toggles watched status
        assert ep_item.text() == "[✓] Ep1"


def test_mainwindow_play_video_error(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    window.on_series_selected(window.series_model.index(0, 0))
    ep_item = window.episode_model.item(0, 0)
    index = window.episode_model.indexFromItem(ep_item)

    ui.play_video.side_effect = Exception("Mocked playback error")
    mock_crit = MagicMock()
    with patch("lan_streamer.ui.QMessageBox.critical", mock_crit):
        window.on_episode_double_clicked(index)
        mock_crit.assert_called_once()


def test_mainwindow_sorting_and_filtering(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    # Mock library data
    window.library = {
        "A Series": {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Ep1",
                            "path": "/path/a",
                            "watched": True,
                            "date_added": 100,
                        }
                    ]
                }
            }
        },
        "B Series": {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Ep1",
                            "path": "/path/b",
                            "watched": False,
                            "date_added": 300,
                        }
                    ]
                }
            }
        },
        "C Series": {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Ep1",
                            "path": "/path/c",
                            "watched": True,
                            "date_added": 200,
                        }
                    ]
                }
            }
        },
    }

    # Initial state: Alphabetical, show all
    window.update_series_view()
    assert window.series_model.rowCount() == 3
    assert window.series_model.item(0).text() == "A Series"
    assert window.series_model.item(1).text() == "B Series"
    assert window.series_model.item(2).text() == "C Series"

    # Filter Unwatched
    window.unwatched_checkbox.setChecked(True)
    assert window.series_model.rowCount() == 1
    assert window.series_model.item(0).text() == "B Series"

    # Turn off filter
    window.unwatched_checkbox.setChecked(False)

    # Sort Date Added (Newest)
    window.sort_combo.setCurrentText("Date Added (Newest)")
    assert window.series_model.rowCount() == 3
    assert window.series_model.item(0).text() == "B Series"  # 300
    assert window.series_model.item(1).text() == "C Series"  # 200
    assert window.series_model.item(2).text() == "A Series"  # 100

    # Sort Date Added (Oldest)
    window.sort_combo.setCurrentText("Date Added (Oldest)")
    assert window.series_model.rowCount() == 3
    assert window.series_model.item(0).text() == "A Series"  # 100
    assert window.series_model.item(1).text() == "C Series"  # 200
    assert window.series_model.item(2).text() == "B Series"  # 300


def test_mainwindow_persistence(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    # Change filter
    window.unwatched_checkbox.setChecked(True)
    assert config.filter_unwatched is True

    # Change sort
    window.sort_combo.setCurrentText("Date Added (Newest)")
    assert config.sort_mode == "Date Added (Newest)"

    # Change back
    window.unwatched_checkbox.setChecked(False)
    assert config.filter_unwatched is False
    window.sort_combo.setCurrentText("Alphabetical")
    assert config.sort_mode == "Alphabetical"


def test_poster_delegate(qtbot):
    from lan_streamer.delegates import PosterDelegate
    from PySide6.QtWidgets import QListView, QStyleOptionViewItem, QStyle
    from PySide6.QtGui import QPainter, QPixmap, QStandardItemModel, QStandardItem
    from PySide6.QtCore import Qt

    view = QListView()
    delegate = PosterDelegate(view)

    option = QStyleOptionViewItem()
    option.rect = view.rect()
    option.state = QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver

    model = QStandardItemModel()
    item = QStandardItem("Test Series")
    # Simulate an actual image for coverage
    img = QPixmap(100, 100)
    img.fill(Qt.GlobalColor.black)

    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        img.save(tf.name)
        item.setData(tf.name, Qt.ItemDataRole.UserRole + 1)

    model.appendRow(item)
    index = model.index(0, 0)

    pixmap = QPixmap(200, 300)
    painter = QPainter(pixmap)
    delegate.paint(painter, option, index)
    painter.end()

    os.unlink(tf.name)

    size = delegate.sizeHint(option, index)
    assert size.width() > 0


def test_series_match_dialog(qtbot, mock_dependencies):
    from lan_streamer.ui import SeriesMatchDialog

    # TMDB search_series_full returns dicts with 'name'/'year'/'id' (not Jellyfin's Name/ProductionYear)
    ui.tmdb_client.search_series_full.return_value = [
        {"id": "match1", "name": "Found Show", "first_air_date": "2024-01-01"}
    ]

    dialog = SeriesMatchDialog("Original Show")
    qtbot.addWidget(dialog)

    assert dialog.search_input.text() == "Original Show"
    # Search is triggered on init
    assert dialog.results_list.count() == 1
    assert "Found Show (2024)" in dialog.results_list.item(0).text()

    # Select result
    dialog.results_list.setCurrentRow(0)
    selected = dialog.get_selected_series()
    assert selected["id"] == "match1"

    # Click match
    with patch.object(dialog, "accept"):
        qtbot.mouseClick(dialog.ok_button, Qt.MouseButton.LeftButton)


def test_mainwindow_manual_match(qtbot, mock_dependencies, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)

    series_name = "Series A"
    # Setup local directory for matching
    series_dir = tmp_path / series_name
    series_dir.mkdir()
    config.libraries["TestLib"] = [str(tmp_path)]

    # Mock dialog success
    mock_selected = {"id": "new_tmdb_identifier", "name": "New Match"}

    class MockDialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return ui.QDialog.DialogCode.Accepted

        def get_selected_series(self):
            return mock_selected

    # Mock scanner and cleaner
    mock_new_data = {
        "metadata": {"tmdb_identifier": "new_tmdb_identifier"},
        "seasons": {},
    }

    with (
        patch("lan_streamer.ui.SeriesMatchDialog", MockDialog),
        patch("lan_streamer.ui.scan_series", return_value=mock_new_data),
        patch("lan_streamer.ui.clean_series_data", side_effect=lambda d: d),
        patch("lan_streamer.ui.QMessageBox", MagicMock()),
    ):
        # Trigger manual match
        window.match_series_manually(series_name)

        assert (
            window.library[series_name]["metadata"]["tmdb_identifier"]
            == "new_tmdb_identifier"
        )
        ui.db.save_library.assert_called()


def test_poster_delegate_mouseover(qtbot):
    # Test line 31-32 of delegates.py
    from lan_streamer.delegates import PosterDelegate
    from PySide6.QtWidgets import QListView, QStyleOptionViewItem, QStyle
    from PySide6.QtGui import QPainter, QPixmap, QStandardItemModel, QStandardItem

    view = QListView()
    delegate = PosterDelegate(view)

    option = QStyleOptionViewItem()
    option.rect = view.rect()
    # MouseOver ONLY (no Selected)
    option.state = QStyle.StateFlag.State_MouseOver

    model = QStandardItemModel()
    item = QStandardItem("Test")
    model.appendRow(item)
    index = model.index(0, 0)

    pixmap = QPixmap(100, 100)
    painter = QPainter(pixmap)
    delegate.paint(painter, option, index)
    painter.end()


def test_mainwindow_load_empty(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    # Pre-set some data
    window.library = {"Series A": {}}
    # Trigger load with empty name
    window.main_library_combo.clear()
    window.load_library_ui()
    assert window.library == {}


def test_ui_on_sync_all_finished(qtbot, mock_dependencies):
    # Test on_sync_all_finished branch in ui.py
    window = MainWindow()
    qtbot.addWidget(window)
    window.on_sync_all_finished()
    assert window.refresh_action.isEnabled()


def test_tmdb_settings_dialog(qtbot, mock_dependencies):
    from lan_streamer.ui import TMDBSettingsDialog

    # Mock validate_credentials
    ui.tmdb_client.validate_credentials.return_value = (True, "Success")

    dialog = TMDBSettingsDialog()
    qtbot.addWidget(dialog)

    dialog.api_key_input.setText("new-key")

    # Mock QMessageBox
    mock_info = MagicMock()
    with patch("lan_streamer.ui.QMessageBox.information", mock_info):
        # Test connection
        test_btn = [
            b for b in dialog.findChildren(QPushButton) if b.text() == "Test Connection"
        ][0]
        qtbot.mouseClick(test_btn, Qt.MouseButton.LeftButton)
        ui.tmdb_client.validate_credentials.assert_called_with("new-key")

        # Save
        save_btn = [b for b in dialog.findChildren(QPushButton) if b.text() == "Save"][
            0
        ]
        qtbot.mouseClick(save_btn, Qt.MouseButton.LeftButton)
        assert config.tmdb_api_key == "new-key"


def test_mainwindow_sync_all(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    # Mock SyncAllWorker
    mock_worker = MagicMock()
    with patch("lan_streamer.ui.SyncAllWorker", return_value=mock_worker):
        window.sync_all_libraries()
        assert window.sync_worker == mock_worker
        mock_worker.start.assert_called_once()
        assert not window.refresh_action.isEnabled()

    # Simulate finish
    window.on_sync_all_finished()
    assert window.refresh_action.isEnabled()


def test_format_episode_display(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    # Case 1: TMDB match
    ep_data_match = {
        "name": "S01E01.mkv",
        "tmdb_number": 1,
        "tmdb_name": "Pilot",
        "watched": False,
    }
    assert window._format_episode_display(ep_data_match) == "[ ] 1. Pilot"

    # Case 2: No match fallback
    ep_data_no_match = {
        "name": "S01E01.mkv",
        "tmdb_number": None,
        "tmdb_name": None,
        "watched": True,
    }
    assert window._format_episode_display(ep_data_no_match) == "[✓] S01E01.mkv"


def test_mainwindow_partial_scan_update(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    partial_data = {"New Series": {"metadata": {}, "seasons": {}}}
    window.on_scan_partial_update(partial_data)

    assert "New Series" in window.library
    ui.db.save_library.assert_called()


def test_mainwindow_refresh_detail_view_restore(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    # Setup some data
    window.library = {
        "Series A": {
            "metadata": {"tmdb_name": "Series A"},
            "seasons": {
                "Season 1": {"episodes": []},
                "Season 2": {"episodes": []},
            },
        }
    }
    window.update_series_view()

    # Select Series A
    index = window.series_model.index(0, 0)
    window.on_series_selected(index)

    # Select Season 2
    season2_index = window.season_model.index(1, 0)
    window.season_view.setCurrentIndex(season2_index)
    window.on_season_selected(season2_index)
    assert window.season_view.currentIndex().row() == 1

    # Update library data (e.g. from scan)
    window.library["Series A"]["seasons"]["Season 3"] = {"episodes": []}

    # Refresh detail view
    window._refresh_detail_view()

    # Check if Season 2 is still selected
    assert window.season_view.currentIndex().row() == 1
    assert window.season_model.item(1).text() == "Season 2"


def test_mainwindow_season_watched_status(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    # Navigate to Series A
    window.on_series_selected(window.series_model.index(0, 0))

    # Toggle Season 1 to watched
    window.toggle_season_watched_status("Season 1", True)

    # Verify DB call
    ui.db.update_season_watched_status.assert_called_with(
        "TestLib", "Series A", "Season 1", True
    )

    # Verify UI refresh
    assert ui.db.load_library.call_count > 1


def test_mainwindow_season_context_menu(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)
    window.on_series_selected(window.series_model.index(0, 0))

    # Mock QMenu
    mock_menu = MagicMock()
    mock_action = MagicMock()
    mock_menu.addAction.return_value = mock_action
    mock_menu.exec.return_value = mock_action

    with patch("lan_streamer.ui.QMenu", return_value=mock_menu):
        # Trigger context menu
        season_index = window.season_model.index(0, 0)
        window.season_view.indexAt = MagicMock(return_value=season_index)

        # Mock toggle_season_watched_status to verify it's called
        with patch.object(window, "toggle_season_watched_status") as mock_toggle:
            window.show_season_context_menu(
                window.season_view.viewport().rect().center()
            )
            mock_toggle.assert_called()


def test_jellyfin_match_dialog(qtbot, mock_dependencies):
    from lan_streamer.ui import JellyfinMatchDialog

    ui.jellyfin_client.search_series.return_value = [
        {"Id": "jf1", "Name": "Jellyfin Show", "ProductionYear": 2024}
    ]

    dialog = JellyfinMatchDialog("Local Show")
    qtbot.addWidget(dialog)

    assert dialog.search_input.text() == "Local Show"
    assert dialog.results_list.count() == 1
    assert "Jellyfin Show (2024)" in dialog.results_list.item(0).text()

    dialog.results_list.setCurrentRow(0)
    selected = dialog.get_selected_series()
    assert selected["Id"] == "jf1"


def test_mainwindow_match_jellyfin_manually(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    mock_selected = {"Id": "jf_new_id", "Name": "Matched JF"}

    class MockDialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return ui.QDialog.DialogCode.Accepted

        def get_selected_series(self):
            return mock_selected

    with (
        patch("lan_streamer.ui.JellyfinMatchDialog", MockDialog),
        patch.object(window, "load_library_ui"),
    ):
        ui.jellyfin_client.get_series_episodes.return_value = [
            {
                "Id": "jf_ep1",
                "Name": "Ep1",
                "IndexNumber": 1,
                "ParentIndexNumber": 1,
                "UserData": {"Played": True},
            }
        ]
        window.match_jellyfin_manually("Series A")
        assert window.library["Series A"]["metadata"]["jellyfin_id"] == "jf_new_id"

        # Check that episode was correlated and updated
        ep = window.library["Series A"]["seasons"]["Season 1"]["episodes"][0]
        assert ep["jellyfin_id"] == "jf_ep1"
        assert ep["watched"] is True

        ui.db.save_library.assert_called()
        window.load_library_ui.assert_called_once()


def test_mainwindow_cleanup(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    mock_msgbox = MagicMock()
    mock_msgbox.StandardButton.Yes = ui.QMessageBox.StandardButton.Yes
    mock_msgbox.StandardButton.No = ui.QMessageBox.StandardButton.No
    mock_msgbox.question.return_value = ui.QMessageBox.StandardButton.Yes

    with patch("lan_streamer.ui.QMessageBox", mock_msgbox):
        window.cleanup_current_library()
        ui.CleanupWorker.return_value.start.assert_called_once()

        # Simulate finish
        stats = {"series": 1, "seasons": 1, "episodes": 1}
        with patch("lan_streamer.ui.QMessageBox.information"):
            window.on_cleanup_finished(stats)
            ui.db.load_library.assert_called()


def test_mainwindow_cleanup_error(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    mock_msgbox = MagicMock()
    mock_msgbox.StandardButton.Yes = ui.QMessageBox.StandardButton.Yes
    mock_msgbox.StandardButton.No = ui.QMessageBox.StandardButton.No
    mock_msgbox.question.return_value = ui.QMessageBox.StandardButton.Yes

    with patch("lan_streamer.ui.QMessageBox", mock_msgbox):
        window.cleanup_current_library()

        # Simulate error
        mock_crit = MagicMock()
        with patch("lan_streamer.ui.QMessageBox.critical", mock_crit):
            window.on_cleanup_error("Mocked cleanup error")
            mock_crit.assert_called_once()


def test_cleanup_worker_logic(mock_dependencies):
    import lan_streamer.ui as ui_mod

    CleanupWorker = ui_mod.OriginalCleanupWorker

    # Mock db.cleanup_library
    ui_mod.db.cleanup_library.return_value = {"series": 1, "seasons": 0, "episodes": 0}

    worker = CleanupWorker("TestLib", ["/path1"])

    mock_finished = MagicMock()
    mock_error = MagicMock()
    worker.finished.connect(mock_finished)
    worker.error.connect(mock_error)

    worker.run()

    ui_mod.db.cleanup_library.assert_called_once_with("TestLib", ["/path1"])
    mock_finished.assert_called_once_with({"series": 1, "seasons": 0, "episodes": 0})
    mock_error.assert_not_called()


def test_cleanup_worker_error_logic(mock_dependencies):
    import lan_streamer.ui as ui_mod

    CleanupWorker = ui_mod.OriginalCleanupWorker

    ui_mod.db.cleanup_library.side_effect = Exception("Cleanup Logic Error")

    worker = CleanupWorker("TestLib", ["/path1"])
    mock_finished = MagicMock()
    mock_error = MagicMock()
    worker.finished.connect(mock_finished)
    worker.error.connect(mock_error)

    worker.run()

    mock_finished.assert_not_called()
    mock_error.assert_called_once_with("Cleanup Logic Error")
