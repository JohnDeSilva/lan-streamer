from unittest.mock import patch, MagicMock

from lan_streamer.ui_views import Controller
from lan_streamer.ui_views.progress_widgets import (
    SegmentedProgressBar,
    LibraryScanProgressBar,
)
from lan_streamer.ui_views.dialogs.settings import SettingsDialog
from lan_streamer.ui_views.library_grid import LibraryGridView
from lan_streamer.backend.scan_worker_all import ScanAllLibrariesWorker


def test_segmented_progress_bar_passes(qtbot) -> None:
    bar = SegmentedProgressBar()
    bar._library_order = ["LibA"]
    bar._libraries = {
        "LibA": {
            "roots": ["/path"],
            "root_totals": {"/path": 10},
            "root_done": {"/path": 0},
            "state": 0,
        }
    }
    bar._root_states = {"/path": 0}

    assert bar._current_pass == 1

    bar.set_current_pass(2)
    assert bar._current_pass == 2

    bar.set_pass3_progress(3, 10)
    assert bar._current_pass == 3
    assert bar._pass3_fraction == 0.3


def test_library_scan_progress_bar_passes(qtbot) -> None:
    bar = LibraryScanProgressBar()
    bar.init_from_roots({"/path": ["FolderA"]}, ["/path"])

    assert bar._current_pass == 1

    bar.set_current_pass(2)
    assert bar._current_pass == 2

    bar.set_pass3_progress(7, 10)
    assert bar._current_pass == 3
    assert bar._pass3_fraction == 0.7


def test_settings_dialog_scan_layout_toggles(qtbot) -> None:
    controller = Controller()
    dialog = SettingsDialog(controller)
    qtbot.addWidget(dialog)

    # Initial state
    assert not dialog.scan_files_button.isHidden()
    assert not dialog.passes_frame.isHidden()
    assert not dialog.pull_watch_history_button.isHidden()
    assert not dialog.push_watch_history_button.isHidden()

    # During scan
    dialog._show_scan_progress_widgets()
    assert dialog.scan_files_button.isHidden()
    assert dialog.passes_frame.isHidden()
    assert dialog.pull_watch_history_button.isHidden()
    assert dialog.push_watch_history_button.isHidden()
    assert dialog.scan_detail_label.text() == "Scan Report:"

    # After scan
    dialog._on_scan_completed()
    assert not dialog.scan_files_button.isHidden()
    assert not dialog.passes_frame.isHidden()
    assert not dialog.pull_watch_history_button.isHidden()
    assert not dialog.push_watch_history_button.isHidden()
    assert dialog.scan_detail_label.text() == "Scan Detail:"


def test_settings_dialog_log_all_lines_shown(qtbot) -> None:
    controller = Controller()
    dialog = SettingsDialog(controller)
    qtbot.addWidget(dialog)

    dialog._show_scan_progress_widgets()
    dialog._scan_running = True

    # Emit two identical logs
    dialog._on_log_emitted("[SCAN_REPORT] Episode Added: Show A", "INFO")
    dialog._on_log_emitted("[SCAN_REPORT] Episode Added: Show A", "INFO")

    # Emit a separator log
    dialog._on_log_emitted("[SCAN_REPORT] =====================", "INFO")
    dialog._on_log_emitted("[SCAN_REPORT] =====================", "INFO")

    text = dialog.scan_report_display.toPlainText()
    assert text.count("Episode Added: Show A") == 2
    assert text.count("=====================") == 2


def test_library_grid_progress_routing(qtbot) -> None:
    controller = Controller()
    grid = LibraryGridView(controller)
    qtbot.addWidget(grid)

    grid._on_detail_progress("start_offline_scan", {})
    assert grid.scan_progress_bar._current_pass == 1
    assert "offline scan" in grid.scan_status_label.text()

    grid._on_detail_progress("start_metadata_resolution", {})
    assert grid.scan_progress_bar._current_pass == 2
    assert "metadata resolution" in grid.scan_status_label.text()

    grid._on_detail_progress(
        "runtime_extraction_progress", {"completed": 4, "total": 10}
    )
    assert grid.scan_progress_bar._current_pass == 3
    assert grid.scan_progress_bar._pass3_fraction == 0.4
    assert "Extracting video runtimes: 4/10" in grid.scan_status_label.text()


def test_controller_chains_pass3() -> None:
    controller = Controller()

    with patch.object(controller, "trigger_runtime_extraction") as mock_extraction:
        mock_emit = MagicMock()
        controller.scan_completed.connect(mock_emit)

        # 1. trigger_scan chains to trigger_runtime_extraction
        controller._running_pass3_after_scan = True
        controller._doing_scan_and_update = False
        controller._on_scan_finished({})
        mock_extraction.assert_called_once()
        mock_emit.assert_not_called()

        mock_extraction.reset_mock()
        mock_emit.reset_mock()

        # 2. scan_and_update chains to trigger_runtime_extraction
        controller._running_pass3_after_scan = True
        controller._doing_scan_and_update = True
        controller._on_scan_and_update_cleanup_finished({})
        mock_extraction.assert_called_once()
        mock_emit.assert_not_called()

        mock_extraction.reset_mock()
        mock_emit.reset_mock()

        # 3. trigger_scan_all chains to trigger_runtime_extraction
        controller._running_pass3_after_scan = True
        controller._on_scan_all_finished()
        mock_extraction.assert_called_once()
        mock_emit.assert_not_called()

        mock_extraction.reset_mock()
        mock_emit.reset_mock()

        # 4. runtime finished clears flags and emits scan_completed
        controller._on_runtime_finished(5)
        assert not controller._running_pass3_after_scan
        mock_emit.assert_called_once()


@patch("lan_streamer.backend.scan_worker_all.scan_directories")
@patch("lan_streamer.backend.scan_worker_all.db")
def test_scan_all_libraries_worker_passes_sequencing(mock_db, mock_scan_dirs) -> None:
    from lan_streamer.system.config import config

    config.libraries = {
        "Lib1": {"type": "tv", "paths": ["/path1"]},
        "Lib2": {"type": "movie", "paths": ["/path2"]},
    }

    mock_db.load_library.return_value = {"old": "tv"}
    mock_db.load_movie_library.return_value = {"old": "movie"}

    def dummy_scan_dirs(paths, **kwargs):
        from lan_streamer.scanner import LibraryDict

        res = LibraryDict()
        res.unavailable_directories = []
        return res

    mock_scan_dirs.side_effect = dummy_scan_dirs

    worker = ScanAllLibrariesWorker()

    passes_called = []

    def detail_batch_emit(batch):
        for event_dict in batch:
            event = event_dict.get("event")
            if event in ("start_offline_scan", "start_metadata_resolution"):
                passes_called.append(event)

    worker.detail_progress_batch.connect(detail_batch_emit)
    worker.run()

    assert passes_called == ["start_offline_scan", "start_metadata_resolution"]
    # Check that scan_directories was called 4 times total:
    # Pass 1 for Lib1, Pass 1 for Lib2, then Pass 2 for Lib1, Pass 2 for Lib2.
    assert mock_scan_dirs.call_count == 4
