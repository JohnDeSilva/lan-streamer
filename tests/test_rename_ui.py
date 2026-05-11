import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from lan_streamer.ui import RenameDialog


@pytest.fixture
def series_data():
    return {
        "metadata": {"tmdb_name": "Test Show", "name": "Test Show"},
        "seasons": {
            "Season 1": {
                "episodes": [
                    {
                        "name": "Episode 1",
                        "path": "/data/Test Show/Season 1/ep1.mkv",
                        "tmdb_number": 1,
                        "tmdb_name": "The Beginning",
                    }
                ]
            }
        },
    }


def test_rename_dialog_init(qtbot, series_data):
    dialog = RenameDialog("Test Show", series_data)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Rename Files - Test Show"
    assert dialog.table.rowCount() == 1
    # Default template should produce a new name
    assert dialog.table.item(0, 2).text() == "Test Show - S01E01 - The Beginning.mkv"


def test_rename_dialog_template_change(qtbot, series_data):
    dialog = RenameDialog("Test Show", series_data)
    qtbot.addWidget(dialog)

    # Change template
    qtbot.keyClicks(dialog.template_input, " - {OriginalTitle}")
    # Wait for preview update (it's connected to textChanged)

    expected = "Test Show - S01E01 - The Beginning - ep1.mkv"
    assert dialog.table.item(0, 2).text() == expected


def test_rename_dialog_cancel(qtbot, series_data):
    dialog = RenameDialog("Test Show", series_data)
    qtbot.addWidget(dialog)

    qtbot.mouseClick(
        dialog.button_box.button(dialog.button_box.StandardButton.Cancel),
        Qt.MouseButton.LeftButton,
    )
    assert not dialog.isVisible()


def test_rename_dialog_no_changes(qtbot, series_data):
    # If the template produces the same name, OK button should be disabled
    dialog = RenameDialog("Test Show", series_data)
    qtbot.addWidget(dialog)

    # Set template to just original name
    dialog.template_input.setText("{OriginalTitle}")
    assert not dialog.ok_button.isEnabled()


def test_rename_dialog_run_rename(qtbot, series_data, tmp_path, monkeypatch):

    # Setup files
    old_file = tmp_path / "ep1.mkv"
    old_file.touch()
    series_data["seasons"]["Season 1"]["episodes"][0]["path"] = str(old_file)

    dialog = RenameDialog("Test Show", series_data)
    qtbot.addWidget(dialog)

    # Mock QMessageBox.question to return Yes
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    # Mock QMessageBox.information to do nothing
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)

    dialog.run_rename()

    assert not old_file.exists()
    # Check if new file exists
    new_name = "Test Show - S01E01 - The Beginning.mkv"
    assert (tmp_path / new_name).exists()


def test_rename_dialog_run_rename_fail(qtbot, series_data, tmp_path, monkeypatch):
    # Setup files - but dest already exists
    old_file = tmp_path / "ep1.mkv"
    old_file.touch()
    dest_file = tmp_path / "Test Show - S01E01 - The Beginning.mkv"
    dest_file.touch()

    series_data["seasons"]["Season 1"]["episodes"][0]["path"] = str(old_file)

    dialog = RenameDialog("Test Show", series_data)
    qtbot.addWidget(dialog)

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)

    dialog.run_rename()

    # old_file should still exist because rename failed
    assert old_file.exists()


def test_rename_dialog_update_preview_colors(qtbot, series_data):
    from PySide6.QtCore import Qt

    dialog = RenameDialog("Test Show", series_data)
    qtbot.addWidget(dialog)

    # Check green color for change (default template vs original ep1.mkv)
    assert dialog.table.item(0, 2).foreground().color() == Qt.GlobalColor.green

    # Change template to match original (no change)
    dialog.template_input.setText("{OriginalTitle}")
    assert dialog.table.item(0, 2).foreground().color() == Qt.GlobalColor.gray


def test_rename_dialog_run_rename_no_change(qtbot, series_data):
    dialog = RenameDialog("Test Show", series_data)
    qtbot.addWidget(dialog)

    # Manually clear previews or set same name
    dialog.template_input.setText("{OriginalTitle}")
    dialog.previews = []  # Force empty previews to hit that branch

    # run_rename should just accept and close
    dialog.run_rename()
    assert not dialog.isVisible()
