import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from lan_streamer import ui
from lan_streamer.config import config
from lan_streamer.ui import MainWindow, LibrarySettingsDialog, JellyfinSettingsDialog


@pytest.fixture
def app(qtbot):
    if not QApplication.instance():
        app = QApplication([])
    else:
        app = QApplication.instance()
    return app


@pytest.fixture
def mock_dependencies(monkeypatch):
    monkeypatch.setattr(ui, "db", MagicMock())
    monkeypatch.setattr(ui, "config", config)
    monkeypatch.setattr(ui, "jellyfin_client", MagicMock())
    monkeypatch.setattr(ui, "play_video", MagicMock())
    monkeypatch.setattr(ui, "scan_directories", MagicMock())

    # Globally mock ScanWorker to prevent thread issues in tests
    ui.OriginalScanWorker = ui.ScanWorker
    mock_worker_class = MagicMock()
    mock_worker = MagicMock()
    mock_worker_class.return_value = mock_worker
    monkeypatch.setattr(ui, "ScanWorker", mock_worker_class)

    config.libraries = {"TestLib": ["/path1"]}
    config.jellyfin_url = ""
    config.jellyfin_api_key = ""

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


def test_library_settings_dialog(qtbot, mock_dependencies, monkeypatch):
    dialog = LibrarySettingsDialog()
    qtbot.addWidget(dialog)

    assert dialog.library_combo.count() == 1
    assert dialog.library_combo.currentText() == "TestLib"

    # Add new library
    monkeypatch.setattr(ui.QInputDialog, "getText", lambda *args: ("NewLib", True))
    dialog.add_library()
    assert dialog.library_combo.count() == 2
    assert "NewLib" in config.libraries

    # Try adding existing
    mock_warning = MagicMock()
    monkeypatch.setattr(ui.QMessageBox, "warning", mock_warning)
    dialog.add_library()

    # Add dir
    monkeypatch.setattr(ui.QFileDialog, "getExistingDirectory", lambda *args: "/tmp")
    dialog.add_dir()
    assert "/tmp" in config.libraries["NewLib"]

    # Remove dir
    dialog.list_widget.setCurrentRow(0)
    dialog.remove_dir()
    assert "/tmp" not in config.libraries["NewLib"]

    # Remove library
    monkeypatch.setattr(
        ui.QMessageBox, "question", lambda *args: ui.QMessageBox.StandardButton.Yes
    )
    dialog.remove_library()
    assert "NewLib" not in config.libraries


def test_mainwindow_load(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.main_library_combo.currentText() == "TestLib"
    assert window.series_model.rowCount() == 1

    # Select series
    index = window.series_model.index(0, 0)
    window.on_series_selected(index)
    assert window.tree_model.rowCount() == 1

    season_item = window.tree_model.item(0, 0)
    assert season_item.rowCount() == 1

    ep_item = season_item.child(0, 0)
    assert ep_item.text() == "[ ] Ep1"


def test_mainwindow_play_video(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    window.on_series_selected(window.series_model.index(0, 0))

    season_item = window.tree_model.item(0, 0)
    ep_item = season_item.child(0, 0)
    index = window.tree_model.indexFromItem(ep_item)

    window.on_tree_double_clicked(index)

    ui.play_video.assert_called_once_with("/path1")
    ui.db.update_episode_watched_status.assert_called_once_with("/path1", True)
    assert ep_item.text() == "[✓] Ep1"


def test_mainwindow_force_scan(qtbot, mock_dependencies, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)

    window.force_scan_library()
    ui.ScanWorker.return_value.start.assert_called_once()

    # Manually trigger the slot to test UI updates
    window.on_scan_finished({})

    ui.db.save_library.assert_called_once_with("TestLib", {})


def test_mainwindow_force_scan_error(qtbot, mock_dependencies, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)

    mock_crit = MagicMock()
    monkeypatch.setattr(ui.QMessageBox, "critical", mock_crit)

    window.force_scan_library()
    ui.ScanWorker.return_value.start.assert_called_once()

    # Manually trigger error slot
    window.on_scan_error("Mocked scan error")

    mock_crit.assert_called_once()
    assert window.refresh_action.isEnabled() is True


def test_scan_worker_logic(mock_dependencies, monkeypatch):
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

    # Call run() directly (synchronous) to test the internal logic
    # without spinning up a real C++ thread which causes instability in tests.
    worker.run()

    ui_mod.jellyfin_client.preload_library.assert_called_once()
    ui_mod.scan_directories.assert_called_once_with(
        ["/path1"], existing_library={"Old Data": {}}
    )
    ui_mod.jellyfin_client.clear_cache.assert_called()
    mock_finished.assert_called_once_with({"New Data": {}})
    mock_error.assert_not_called()


def test_scan_worker_error_logic(mock_dependencies, monkeypatch):
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
    ui_mod.jellyfin_client.clear_cache.assert_called()


def test_toggle_watched_status(qtbot, mock_dependencies):
    window = MainWindow()
    qtbot.addWidget(window)

    window.on_series_selected(window.series_model.index(0, 0))

    season_item = window.tree_model.item(0, 0)
    ep_item = season_item.child(0, 0)
    window.toggle_watched_status(ep_item, force_status=True)

    assert ep_item.text() == "[✓] Ep1"
    ui.db.update_episode_watched_status.assert_called_with("/path1", True)
    ui.jellyfin_client.set_watched_status.assert_called_with("3", True)


def test_ui_save_jellyfin_settings(qtbot, mock_dependencies, monkeypatch):
    dialog = JellyfinSettingsDialog()
    qtbot.addWidget(dialog)
    dialog.jellyfin_url_input.setText("http://new-url")
    dialog.jellyfin_api_key_input.setText("new-key")

    mock_info = MagicMock()
    monkeypatch.setattr(ui.QMessageBox, "information", mock_info)
    dialog.save_jellyfin_settings()

    assert config.jellyfin_url == "http://new-url"
    assert config.jellyfin_api_key == "new-key"


def test_ui_add_dir_errors(qtbot, mock_dependencies, monkeypatch):
    dialog = LibrarySettingsDialog()
    qtbot.addWidget(dialog)

    # Empty library
    dialog.library_combo.clear()
    mock_warning = MagicMock()
    monkeypatch.setattr(ui.QMessageBox, "warning", mock_warning)
    monkeypatch.setattr(ui.QFileDialog, "getExistingDirectory", lambda *args: "")
    dialog.add_dir()
    mock_warning.assert_called()


def test_jellyfin_settings_dialog_full(qtbot, mock_dependencies, monkeypatch):
    dialog = JellyfinSettingsDialog()
    qtbot.addWidget(dialog)

    # Mock QMessageBox
    mock_info = MagicMock()
    monkeypatch.setattr(ui.QMessageBox, "information", mock_info)

    # Jellyfin settings
    dialog.jellyfin_url_input.setText("http://newurl")
    dialog.jellyfin_api_key_input.setText("newkey")
    dialog.save_jellyfin_settings()

    assert config.jellyfin_url == "http://newurl"
    assert config.jellyfin_api_key == "newkey"
    mock_info.assert_called_once()


def test_jellyfin_settings_test_connection(qtbot, mock_dependencies, monkeypatch):
    dialog = JellyfinSettingsDialog()
    qtbot.addWidget(dialog)

    # Mock QMessageBox
    mock_info = MagicMock()
    mock_warn = MagicMock()
    monkeypatch.setattr(ui.QMessageBox, "information", mock_info)
    monkeypatch.setattr(ui.QMessageBox, "warning", mock_warn)

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
    window.on_tree_double_clicked(window.tree_model.index(99, 99))


def test_mainwindow_context_menu(qtbot, mock_dependencies, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)

    window.on_series_selected(window.series_model.index(0, 0))

    # Mock QMenu exec to return the first action
    def mock_exec(pos):
        return mock_menu.actions()[0]

    mock_menu = ui.QMenu()
    monkeypatch.setattr(ui, "QMenu", lambda: mock_menu)
    monkeypatch.setattr(mock_menu, "exec", mock_exec)

    season_item = window.tree_model.item(0, 0)
    ep_item = season_item.child(0, 0)
    ep_index = window.tree_model.indexFromItem(ep_item)

    window.show_tree_context_menu(window.tree_view.visualRect(ep_index).center())
    # The action toggles watched status
    assert ep_item.text() == "[✓] Ep1"


def test_mainwindow_play_video_error(qtbot, mock_dependencies, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)

    window.on_series_selected(window.series_model.index(0, 0))
    season_item = window.tree_model.item(0, 0)
    ep_item = season_item.child(0, 0)
    index = window.tree_model.indexFromItem(ep_item)

    ui.play_video.side_effect = Exception("Mocked playback error")
    mock_crit = MagicMock()
    monkeypatch.setattr(ui.QMessageBox, "critical", mock_crit)

    window.on_tree_double_clicked(index)
    mock_crit.assert_called_once()


def test_mainwindow_sorting_and_filtering(qtbot, mock_dependencies, monkeypatch):
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


def test_series_match_dialog(qtbot, mock_dependencies, monkeypatch):
    from lan_streamer.ui import SeriesMatchDialog

    ui.jellyfin_client.search_series_full.return_value = [
        {"Id": "match1", "Name": "Found Show", "ProductionYear": 2024}
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
    assert selected["Id"] == "match1"

    # Click match
    monkeypatch.setattr(dialog, "accept", lambda: None)
    qtbot.mouseClick(dialog.ok_button, Qt.MouseButton.LeftButton)


def test_mainwindow_manual_match(qtbot, mock_dependencies, monkeypatch, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)

    series_name = "Series A"
    # Setup local directory for matching
    series_dir = tmp_path / series_name
    series_dir.mkdir()
    config.libraries["TestLib"] = [str(tmp_path)]

    # Mock dialog success
    mock_selected = {"Id": "new_id", "Name": "New Match"}

    class MockDialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return ui.QDialog.DialogCode.Accepted

        def get_selected_series(self):
            return mock_selected

    monkeypatch.setattr(ui, "SeriesMatchDialog", MockDialog)

    # Mock scanner and cleaner
    mock_new_data = {"metadata": {"jellyfin_id": "new_id"}, "seasons": {}}
    monkeypatch.setattr(ui, "scan_series", lambda *args, **kwargs: mock_new_data)
    monkeypatch.setattr(ui, "clean_series_data", lambda d: d)

    # Mock QMessageBox to prevent popups during tests
    monkeypatch.setattr(ui, "QMessageBox", MagicMock())

    # Trigger manual match
    window.match_series_manually(series_name)

    assert window.library[series_name]["metadata"]["jellyfin_id"] == "new_id"
    ui.db.save_library.assert_called()
