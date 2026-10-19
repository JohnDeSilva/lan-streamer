"""Unit tests for Controller scan-agent SSE event handling and reactivity."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lan_streamer.ui_views.controller import Controller


@pytest.fixture
def test_controller(qapp: Any) -> Controller:
    """Provide an isolated Controller instance with mocked database and config."""
    mock_config = MagicMock()
    mock_config.libraries = {
        "Remote TV": {
            "management_type": "remote",
            "type": "tv",
            "agent_url": "http://127.0.0.1:8000",
            "mount_mappings": {"/remote/media/tv": "/local/mount/tv"},
            "sources": [
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8000",
                    "source_id": "Remote TV",
                    "mount_mappings": {"/remote/media/tv": "/local/mount/tv"},
                }
            ],
        }
    }
    mock_config.scan_agents = {"http://127.0.0.1:8000": {"enabled": True}}
    mock_config.scan_interval_hours = 4
    mock_config.auto_scan_enabled = False

    mock_database = MagicMock()

    with (
        patch("lan_streamer.ui_views.controller._config_default", mock_config),
        patch("lan_streamer.ui_views.controller._db_default", mock_database),
    ):
        controller = Controller(config=mock_config, db=mock_database)
        yield controller
        controller.stop_agent_event_listeners()


def test_controller_start_and_stop_agent_event_listeners(
    test_controller: Controller,
) -> None:
    """Listeners are created for configured agent URLs and stopped on shutdown."""
    with patch(
        "lan_streamer.backend.agent_event_worker.AgentEventListenerWorker.start"
    ) as mock_worker_start:
        test_controller.start_agent_event_listeners()
        assert "http://127.0.0.1:8000" in test_controller.agent_event_listeners
        mock_worker_start.assert_called_once()

    worker = test_controller.agent_event_listeners["http://127.0.0.1:8000"]
    with patch.object(worker, "stop") as mock_worker_stop:
        test_controller.stop_agent_event_listeners()
        mock_worker_stop.assert_called_once()
        assert len(test_controller.agent_event_listeners) == 0


def test_controller_handles_agent_watch_updated_event(
    test_controller: Controller,
) -> None:
    """watch.updated events from an agent update local memory, database, and smart rows."""
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": "/local/mount/tv/Show Alpha/S01E01.mkv",
                            "watched": False,
                            "last_played_position": 0,
                            "versions": [
                                {"path": "/local/mount/tv/Show Alpha/S01E01.mkv"}
                            ],
                        }
                    ]
                }
            },
        }
    }

    loaded_emitted = []
    test_controller.library_loaded.connect(lambda: loaded_emitted.append(True))

    mock_smart_row_service = MagicMock()
    mock_smart_row_service.on_episode_watched.return_value = ["hash_abc"]
    test_controller._smart_row_service = mock_smart_row_service

    smart_rows_emitted = []
    test_controller.smart_rows_updated.connect(smart_rows_emitted.append)

    test_payload = {
        "media_type": "episode",
        "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
        "watched": True,
        "position_seconds": 1250,
        "last_played_at": 1729355555,
    }

    test_controller._on_agent_watch_updated(test_payload, "http://127.0.0.1:8000")

    # 1. In-memory episode updated
    episode_record = test_controller.cached_library_data["Show Alpha"]["seasons"][
        "Season 1"
    ]["episodes"][0]
    assert episode_record["watched"] is True
    assert episode_record["last_played_position"] == 1250

    # 2. Local database cache updated
    test_controller._db.update_episode_watched_status.assert_called_with(
        "/local/mount/tv/Show Alpha/S01E01.mkv", True
    )
    test_controller._db.update_playback_position.assert_called_with(
        "/local/mount/tv/Show Alpha/S01E01.mkv", 1250
    )

    # 3. Signals emitted
    assert len(loaded_emitted) >= 1


def test_controller_handles_agent_scan_finished_event(
    test_controller: Controller,
) -> None:
    """scan.finished event queues synchronization for affected remote libraries."""
    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller._on_agent_scan_finished(
            {"job_id": 1, "libraries": ["Remote TV"]},
            "http://127.0.0.1:8000",
        )
        mock_queue_sync.assert_called_once_with("Remote TV", emit_signal=True)


def test_controller_handles_agent_scan_finished_all_libraries(
    test_controller: Controller,
) -> None:
    """When scan.finished has no library list specified, all agent libraries are synced."""
    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller._on_agent_scan_finished(
            {"job_id": 1, "libraries": []},
            "http://127.0.0.1:8000",
        )
        mock_queue_sync.assert_called_once_with("Remote TV", emit_signal=True)


def test_controller_handles_agent_metadata_updated_event(
    test_controller: Controller,
) -> None:
    """metadata.updated event emits status message on the controller."""
    status_messages = []
    test_controller.status_changed.connect(status_messages.append)

    test_controller._on_agent_metadata_updated(
        {"media_type": "series", "series_name": "Show Alpha"},
        "http://127.0.0.1:8000",
    )
    assert any(
        "Metadata updated on remote agent" in message for message in status_messages
    )


def test_controller_handles_agent_watch_updated_movie(
    test_controller: Controller,
) -> None:
    """watch.updated updates movie records in in-memory cache and database."""
    test_controller.cached_library_data = {
        "Movie Alpha": {
            "name": "Movie Alpha",
            "type": "movie",
            "path": "/local/mount/tv/Movie Alpha/Movie Alpha.mkv",
            "watched": False,
            "last_played_position": 0,
            "versions": [{"path": "/local/mount/tv/Movie Alpha/Movie Alpha.mkv"}],
        }
    }

    test_controller._on_agent_watch_updated(
        {
            "media_type": "movie",
            "path": "/remote/media/tv/Movie Alpha/Movie Alpha.mkv",
            "watched": True,
            "position_seconds": 3600,
            "last_played_at": 1729356000,
        },
        "http://127.0.0.1:8000",
    )

    movie_record = test_controller.cached_library_data["Movie Alpha"]
    assert movie_record["watched"] is True
    assert movie_record["last_played_position"] == 3600


def test_controller_handles_agent_watch_updated_empty_path(
    test_controller: Controller,
) -> None:
    """watch.updated ignores payloads with empty or missing path."""
    test_controller.cached_library_data = {}
    test_controller._on_agent_watch_updated({}, "http://127.0.0.1:8000")
    test_controller._db.update_episode_watched_status.assert_not_called()
