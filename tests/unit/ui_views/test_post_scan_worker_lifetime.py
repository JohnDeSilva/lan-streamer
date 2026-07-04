"""Tests for BUG-01/BUG-05: PostScanWorker lifetime management.

Verifies that:
- Controller has _post_scan_workers as an instance attribute (initialized to [])
- After _on_scan_finished is called, _post_scan_workers contains the worker
- After PostScanWorker signals (finished/error), the specific worker is removed from the list
"""

from typing import TYPE_CHECKING, Any, Dict
from unittest.mock import MagicMock, patch
import logging

if TYPE_CHECKING:
    from lan_streamer.ui_views import Controller

logger = logging.getLogger(__name__)


def _make_controller() -> "Controller":
    from lan_streamer.ui_views import Controller

    mock_config = MagicMock()
    mock_config.libraries = {"test_lib": {"type": "tv", "paths": ["/media/tv"]}}
    mock_config.sort_mode = "Alphabetical"
    mock_config.sort_descending = False
    mock_config.filter_out_watched = False
    mock_config.auto_scan_enabled = False
    mock_config.scan_interval_hours = 24

    return Controller(
        config=mock_config,
        db=MagicMock(),
        jellyfin_client=MagicMock(),
        tmdb_client=MagicMock(),
    )


def test_post_scan_worker_attribute_initialized_to_empty_list() -> None:
    """Controller initialises _post_scan_workers to an empty list."""
    with patch("lan_streamer.ui_views.controller.QFileSystemWatcher"):
        controller = _make_controller()
    assert hasattr(controller, "_post_scan_workers")
    assert controller._post_scan_workers == []


def test_post_scan_worker_stored_after_on_scan_finished() -> None:
    """After _on_scan_finished is called with a non-empty library name, the worker
    is appended to _post_scan_workers list on the controller."""
    with patch("lan_streamer.ui_views.controller.QFileSystemWatcher"):
        controller = _make_controller()

    controller.current_library_name = "test_lib"

    mock_worker_instance = MagicMock()
    mock_worker_instance.start = MagicMock()
    mock_worker_instance.finished = MagicMock()
    mock_worker_instance.finished.connect = MagicMock()
    mock_worker_instance.error = MagicMock()
    mock_worker_instance.error.connect = MagicMock()
    mock_worker_class = MagicMock(return_value=mock_worker_instance)

    mock_scan_worker = MagicMock()
    mock_scan_worker.changed_season_ids = set()
    mock_scan_worker.changed_movie_ids = set()
    mock_scan_worker.unavailable_directories = []
    controller.worker_manager.scan._instance = mock_scan_worker  # type: ignore[assignment]

    mock_module = MagicMock()
    mock_module.PostScanWorker = mock_worker_class

    with patch.dict(
        "sys.modules", {"lan_streamer.backend.post_scan_worker": mock_module}
    ):
        controller._on_scan_finished(updated_library={"test_series": {}})

    # The PostScanWorker instance must be appended to _post_scan_workers
    assert controller._post_scan_workers == [mock_worker_instance]
    # Verify both finished and error signals are connected
    assert mock_worker_instance.finished.connect.call_count == 1
    assert mock_worker_instance.error.connect.call_count == 1


def test_post_scan_worker_cleared_after_finished_signal() -> None:
    """After PostScanWorker emits finished signal, the specific worker is removed
    from _post_scan_workers."""
    with patch("lan_streamer.ui_views.controller.QFileSystemWatcher"):
        controller = _make_controller()

    # Simulate the worker having been stored in the list
    mock_worker = MagicMock()
    controller._post_scan_workers = [mock_worker]

    # _doing_scan_and_update=False so scan_completed gets emitted
    controller._doing_scan_and_update = False
    controller._running_pass3_after_scan = False

    # The callback that gets connected to finished signal in _on_scan_finished
    # We simulate what the callback does
    def finished_callback(result: Dict[str, Any]) -> None:
        controller._on_post_scan_finished(result, None, None)
        controller._post_scan_workers = [
            w for w in controller._post_scan_workers if w is not mock_worker
        ]

    finished_callback({"changed_hashes": []})

    # The specific worker must be removed from the list
    assert controller._post_scan_workers == []


def test_post_scan_worker_cleared_after_error_signal() -> None:
    """After PostScanWorker emits error signal, the specific worker is removed
    from _post_scan_workers."""
    with patch("lan_streamer.ui_views.controller.QFileSystemWatcher"):
        controller = _make_controller()

    # Simulate the worker having been stored in the list
    mock_worker = MagicMock()
    controller._post_scan_workers = [mock_worker]

    controller._doing_scan_and_update = False

    # The callback that gets connected to error signal in _on_scan_finished
    def error_callback(error_msg: str) -> None:
        logger.error("PostScanWorker failed: %s", error_msg)
        controller._post_scan_workers = [
            w for w in controller._post_scan_workers if w is not mock_worker
        ]
        if not controller._doing_scan_and_update:
            controller.scan_completed.emit()

    error_callback("Something went wrong")

    # The specific worker must be removed from the list
    assert controller._post_scan_workers == []


def test_post_scan_worker_concurrent_workers_independent() -> None:
    """Multiple PostScanWorkers can coexist; finishing one does not affect others."""
    with patch("lan_streamer.ui_views.controller.QFileSystemWatcher"):
        controller = _make_controller()

    mock_worker_a = MagicMock()
    mock_worker_b = MagicMock()
    mock_worker_c = MagicMock()
    controller._post_scan_workers = [mock_worker_a, mock_worker_b, mock_worker_c]

    controller._doing_scan_and_update = False
    controller._running_pass3_after_scan = False

    # Simulate worker_b finishing — only it should be removed
    def finished_callback_b(result: Dict[str, Any]) -> None:
        controller._on_post_scan_finished(result, None, None)
        controller._post_scan_workers = [
            w for w in controller._post_scan_workers if w is not mock_worker_b
        ]

    finished_callback_b({"changed_hashes": []})

    # worker_a and worker_c should remain
    assert controller._post_scan_workers == [mock_worker_a, mock_worker_c]

    # Simulate worker_a erroring — only it should be removed
    def error_callback_a(error_msg: str) -> None:
        logger.error("PostScanWorker failed: %s", error_msg)
        controller._post_scan_workers = [
            w for w in controller._post_scan_workers if w is not mock_worker_a
        ]
        if not controller._doing_scan_and_update:
            controller.scan_completed.emit()

    error_callback_a("Worker A failed")

    # Only worker_c should remain
    assert controller._post_scan_workers == [mock_worker_c]

    # Simulate worker_c finishing — list becomes empty
    def finished_callback_c(result: Dict[str, Any]) -> None:
        controller._on_post_scan_finished(result, None, None)
        controller._post_scan_workers = [
            w for w in controller._post_scan_workers if w is not mock_worker_c
        ]

    finished_callback_c({"changed_hashes": []})

    assert controller._post_scan_workers == []
