"""Tests for BUG-01: PostScanWorker lifetime management.

Verifies that:
- Controller has _post_scan_worker as an instance attribute (initialized to None)
- After _on_scan_finished is called, _post_scan_worker is set (not None)
- After _on_post_scan_finished completes, _post_scan_worker is None (reference cleared)
"""

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from lan_streamer.ui_views import Controller


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


def test_post_scan_worker_attribute_initialized_to_none() -> None:
    """Controller initialises _post_scan_worker to None."""
    with patch("lan_streamer.ui_views.controller.QFileSystemWatcher"):
        controller = _make_controller()
    assert hasattr(controller, "_post_scan_worker")
    assert controller._post_scan_worker is None


def test_post_scan_worker_stored_after_on_scan_finished() -> None:
    """After _on_scan_finished is called with a non-empty library name, _post_scan_worker
    is stored as an instance attribute on the controller (not just a local variable)."""
    with patch("lan_streamer.ui_views.controller.QFileSystemWatcher"):
        controller = _make_controller()

    controller.current_library_name = "test_lib"

    mock_worker_instance = MagicMock()
    mock_worker_instance.start = MagicMock()
    mock_worker_instance.finished = MagicMock()
    mock_worker_instance.finished.connect = MagicMock()
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

    # The PostScanWorker instance must be retained on self._post_scan_worker
    assert controller._post_scan_worker is mock_worker_instance


def test_post_scan_worker_cleared_after_on_post_scan_finished() -> None:
    """After _on_post_scan_finished completes, _post_scan_worker is set back to None."""
    with patch("lan_streamer.ui_views.controller.QFileSystemWatcher"):
        controller = _make_controller()

    # Simulate the worker having been stored
    controller._post_scan_worker = MagicMock()  # type: ignore[assignment]

    # _doing_scan_and_update=False so scan_completed gets emitted
    controller._doing_scan_and_update = False
    controller._running_pass3_after_scan = False

    controller._on_post_scan_finished(
        result={"changed_hashes": []},
        changed_season_ids=None,
        changed_movie_ids=None,
    )

    # Reference must be released
    assert controller._post_scan_worker is None
