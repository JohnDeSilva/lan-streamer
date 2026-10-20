"""Unit tests for Controller scan-agent SSE event handling and reactivity."""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lan_streamer import db as database_module
from lan_streamer.services.scan_agent_client import DESKTOP_CLIENT_IDENTIFIER
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

    mock_database = MagicMock(spec=database_module)

    with (
        patch("lan_streamer.ui_views.controller._config_default", mock_config),
        patch("lan_streamer.ui_views.controller._db_default", mock_database),
    ):
        controller = Controller(config=mock_config, db=mock_database)
        yield controller
        controller.stop_agent_event_listeners()


def _flush_remote_watch_events(test_controller: Controller) -> None:
    """Flush coalesced remote watch events and drain background tasks."""
    test_controller._flush_pending_remote_watch_events()
    test_controller.async_task_manager.stop_all()


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
    _flush_remote_watch_events(test_controller)

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
    test_controller._db.update_episode_playback_position.assert_called_with(
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


def test_controller_handles_agent_scan_finished_event_with_sources(
    test_controller: Controller,
) -> None:
    """scan.finished event with sources and source_ids queues synchronization."""
    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller._on_agent_scan_finished(
            {"job_id": 1, "sources": ["Remote TV"], "source_ids": [101]},
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
    """metadata.updated event emits status message and queues remote sync."""
    status_messages = []
    test_controller.status_changed.connect(status_messages.append)

    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller._on_agent_metadata_updated(
            {"media_type": "series", "series_name": "Show Alpha"},
            "http://127.0.0.1:8000",
        )
        assert any(
            "Metadata updated on remote agent" in message for message in status_messages
        )
        mock_queue_sync.assert_called_once_with("Remote TV", emit_signal=True)


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
    _flush_remote_watch_events(test_controller)

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


def test_sync_watched_to_agents_batches_multiple_episodes(
    test_controller: Controller,
) -> None:
    """When multiple episode paths are synced, sync_watch_events is called with the batch."""
    paths = [
        "/local/mount/tv/Show Alpha/S01E01.mkv",
        "/local/mount/tv/Show Alpha/S01E02.mkv",
    ]
    with patch(
        "lan_streamer.services.scan_agent_client.scan_agent_client.sync_watch_events"
    ) as mock_sync_batch:
        test_controller._sync_watched_to_agents(paths, watched=True)
        test_controller.async_task_manager.stop_all()
        mock_sync_batch.assert_called_once()
        agent_url, events = mock_sync_batch.call_args[0]
        assert agent_url == "http://127.0.0.1:8000"
        assert len(events) == 2
        assert events[0]["path"] == "/remote/media/tv/Show Alpha/S01E01.mkv"
        assert events[0]["watched"] is True


def test_mark_series_unwatched(test_controller: Controller) -> None:
    """mark_series_watched with watched=False marks all episodes unwatched and syncs False to agent."""
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "_origin_libraries": ["Remote TV"],
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": "/local/mount/tv/Show Alpha/S01E01.mkv",
                            "watched": True,
                        }
                    ]
                }
            },
        }
    }
    with patch.object(test_controller, "_sync_watched_to_agents") as mock_sync:
        test_controller.mark_series_watched("Show Alpha", watched=False)
        assert (
            test_controller.cached_library_data["Show Alpha"]["seasons"]["Season 1"][
                "episodes"
            ][0]["watched"]
            is False
        )
        mock_sync.assert_called_once_with(
            ["/local/mount/tv/Show Alpha/S01E01.mkv"], False, ["Remote TV"]
        )


def test_apply_metadata_match_remote_library_dispatches_to_agent(
    test_controller: Controller,
) -> None:
    """apply_metadata_match on a remote library dispatches to agent and does not spawn MetadataApplyWorker."""
    test_controller.current_library_name = "Remote TV"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "path": "/local/mount/tv/Show Alpha",
            "metadata": {
                "locked_metadata": False,
                "tmdb_identifier": "111",
            },
            "seasons": {},
        }
    }

    with (
        patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.match_metadata"
        ) as mock_agent_match,
        patch.object(
            test_controller.worker_manager.metadata_apply, "start"
        ) as mock_worker_start,
        patch.object(test_controller, "_finish_metadata_match") as mock_finish,
    ):
        test_controller.apply_metadata_match(
            "Show Alpha",
            {"provider": "TMDB", "id": "999", "name": "Show Alpha TMDB"},
        )
        test_controller.async_task_manager.stop_all()

        # MetadataApplyWorker should NOT be started for remote library
        mock_worker_start.assert_not_called()
        mock_finish.assert_called_once_with("Show Alpha")

        # scan_agent_client.match_metadata should be called
        mock_agent_match.assert_called_once()
        call_kwargs = mock_agent_match.call_args[1]
        assert call_kwargs["agent_url"] == "http://127.0.0.1:8000"
        assert call_kwargs["media_type"] == "series"
        assert call_kwargs["tmdb_identifier"] == "999"
        assert call_kwargs["name"] == "Show Alpha"
        assert call_kwargs["path"] == "/remote/media/tv/Show Alpha"


def test_select_tab_triggers_freshness_check_for_stale_remote_libraries(
    test_controller: Controller,
) -> None:
    """select_tab queues remote sync if the library has not been synced recently, even if data exists."""
    test_controller._db.load_library.return_value = {
        "Show Alpha": {"name": "Show Alpha"}
    }
    test_controller._remote_library_last_synced["Remote TV"] = 0.0

    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller.select_tab("Remote TV")
        mock_queue_sync.assert_called_once_with("Remote TV", emit_signal=True)


def test_select_tab_skips_freshness_sync_if_recently_synced(
    test_controller: Controller,
) -> None:
    """select_tab does not queue remote sync if the library was synced within 60 seconds."""
    test_controller._db.load_library.return_value = {
        "Show Alpha": {"name": "Show Alpha"}
    }
    test_controller._remote_library_last_synced["Remote TV"] = 1000.0

    with (
        patch("time.time", return_value=1030.0),
        patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync,
    ):
        test_controller.select_tab("Remote TV")
        mock_queue_sync.assert_not_called()


def test_check_combined_view_freshness_queues_sync_for_remote_libraries(
    test_controller: Controller,
) -> None:
    """check_combined_view_freshness queues background sync with emit_signal=False for stale remote libraries."""
    test_controller._config.combined_views = [
        {"name": "Next Up", "enabled": True, "libraries": ["Remote TV"]}
    ]
    test_controller._remote_library_last_synced["Remote TV"] = 0.0

    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller.check_combined_view_freshness()
        mock_queue_sync.assert_called_once_with("Remote TV", emit_signal=False)


def test_remote_sync_finished_rebuilds_smart_row_cache(
    test_controller: Controller,
) -> None:
    """_on_remote_sync_finished rebuilds smart rows and emits smart_rows_updated on success."""
    mock_smart_row_service = MagicMock()
    mock_smart_row_service.rebuild_for_libraries.return_value = ["hash_123"]
    test_controller._smart_row_service = mock_smart_row_service

    emitted_hashes = []
    test_controller.smart_rows_updated.connect(emitted_hashes.append)

    test_controller._remote_sync_scheduled.add("Remote TV")
    test_controller._remote_sync_emit_signal["Remote TV"] = False

    with patch.object(test_controller, "_drain_remote_sync_queue"):
        test_controller._on_remote_sync_finished(
            {"success": True, "items": 5}, "Remote TV"
        )

    mock_smart_row_service.rebuild_for_libraries.assert_called_once_with(["Remote TV"])
    assert emitted_hashes == [["hash_123"]]
    assert "Remote TV" in test_controller._remote_library_last_synced


def test_echoed_watch_event_is_ignored(test_controller: Controller) -> None:
    """A watch event this desktop originated must not echo into DB/cache work."""
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
                        }
                    ]
                }
            },
        }
    }

    with (
        patch.object(
            test_controller, "_record_recent_remote_watch_event"
        ) as mock_record,
        patch.object(
            test_controller, "_apply_remote_watch_event_to_database"
        ) as mock_apply,
        patch.object(
            test_controller._smart_row_service, "on_episode_watched"
        ) as mock_rows,
    ):
        test_controller._on_agent_watch_updated(
            {
                "client_id": DESKTOP_CLIENT_IDENTIFIER,
                "media_type": "episode",
                "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
                "watched": True,
                "position_seconds": 999,
            },
            "http://127.0.0.1:8000",
        )
        test_controller.async_task_manager.stop_all()

        mock_record.assert_not_called()
        mock_apply.assert_not_called()
        mock_rows.assert_not_called()

    episode_record = test_controller.cached_library_data["Show Alpha"]["seasons"][
        "Season 1"
    ]["episodes"][0]
    assert episode_record["watched"] is False
    assert episode_record["last_played_position"] == 0


def test_recent_watch_events_are_reapplied_after_sync(
    test_controller: Controller,
) -> None:
    """Events received during a sync are re-applied so a stale snapshot cannot win."""
    test_controller._recent_remote_watch_events = {
        "/local/mount/tv/Show Alpha/S01E01.mkv": {
            "watched": True,
            "position_seconds": 321,
            "received_at": time.time(),
        }
    }

    test_controller._reapply_recent_remote_watch_events()

    test_controller._db.update_episode_watched_status.assert_called_once_with(
        "/local/mount/tv/Show Alpha/S01E01.mkv", True
    )
    test_controller._db.update_episode_playback_position.assert_called_once_with(
        "/local/mount/tv/Show Alpha/S01E01.mkv", 321
    )


def test_remote_sync_finalization_runs_off_the_signal_handler(
    test_controller: Controller,
) -> None:
    """Smart-row rebuild and watch reconciliation happen on a background task."""
    mock_smart_row_service = MagicMock()
    mock_smart_row_service.rebuild_for_libraries.return_value = ["hash_123"]
    test_controller._smart_row_service = mock_smart_row_service
    emitted_hashes: list[list[str]] = []
    test_controller.smart_rows_updated.connect(emitted_hashes.append)

    test_controller._remote_sync_scheduled.add("Remote TV")
    test_controller._remote_sync_emit_signal["Remote TV"] = False

    with (
        patch.object(
            test_controller, "_reapply_recent_remote_watch_events"
        ) as mock_reapply,
        patch.object(test_controller, "_drain_remote_sync_queue"),
    ):
        test_controller._on_remote_sync_finished(
            {"success": True, "items": 5}, "Remote TV"
        )
        test_controller.async_task_manager.stop_all()

    mock_reapply.assert_called_once()
    mock_smart_row_service.rebuild_for_libraries.assert_called_once_with(["Remote TV"])
    assert emitted_hashes == [["hash_123"]]


def test_remote_sync_finished_drains_queue_when_finalization_raises(
    test_controller: Controller,
) -> None:
    """The queue must always be drained, even if post-sync finalization fails."""
    test_controller._remote_sync_scheduled.add("Remote TV")
    test_controller._remote_sync_emit_signal["Remote TV"] = False

    with (
        patch.object(
            test_controller,
            "_finalize_remote_sync_in_background",
            side_effect=RuntimeError("boom"),
        ),
        patch("lan_streamer.ui_views.controller.QTimer.singleShot") as mock_single_shot,
        pytest.raises(RuntimeError),
    ):
        test_controller._on_remote_sync_finished({"success": True}, "Remote TV")

    mock_single_shot.assert_called_once_with(
        0, test_controller._drain_remote_sync_queue
    )


def test_local_metadata_match_defers_agent_dispatch_until_worker_finishes(
    test_controller: Controller,
) -> None:
    """Local apply and remote match must not run concurrently."""
    test_controller._config.libraries["Local TV"] = {
        "management_type": "local",
        "type": "tv",
        "paths": [],
    }
    test_controller.current_library_name = "Local TV"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "metadata": {"locked_metadata": False, "tmdb_identifier": "111"},
            "seasons": {},
        }
    }

    with (
        patch.object(
            test_controller, "_sync_metadata_match_to_agents"
        ) as mock_agent_sync,
        patch.object(
            test_controller.worker_manager.metadata_apply, "start"
        ) as mock_worker_start,
        patch.object(test_controller, "_download_provider_artwork"),
    ):
        test_controller.apply_metadata_match(
            "Show Alpha",
            {"provider": "TMDB", "id": "999", "name": "Show Alpha TMDB"},
        )
        mock_worker_start.assert_called_once()
        mock_agent_sync.assert_not_called()
        assert "Show Alpha" in test_controller._pending_agent_metadata_matches

        test_controller._on_metadata_apply_finished(
            "Show Alpha", test_controller.cached_library_data["Show Alpha"], ""
        )

    mock_agent_sync.assert_called_once()
    assert "Show Alpha" not in test_controller._pending_agent_metadata_matches


def test_metadata_apply_error_discards_pending_agent_dispatch(
    test_controller: Controller,
) -> None:
    """A failed local match must not be pushed to the agent."""
    test_controller._pending_agent_metadata_matches["Show Alpha"] = (
        {"id": "999"},
        False,
    )
    with (
        patch.object(test_controller, "_finish_metadata_match"),
        patch.object(
            test_controller, "_sync_metadata_match_to_agents"
        ) as mock_agent_sync,
    ):
        test_controller._on_metadata_apply_error("Show Alpha", "failed")
        mock_agent_sync.assert_not_called()
    assert "Show Alpha" not in test_controller._pending_agent_metadata_matches


def test_metadata_dispatch_uses_unscoped_match_and_episode_parent_path(
    test_controller: Controller,
) -> None:
    """Never send a local row id; derive the series directory from its episodes."""
    test_controller.current_library_name = "Remote TV"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "metadata": {"tmdb_identifier": "111"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"path": ("/local/mount/tv/Show Alpha/Season 1/S01E01.mkv")}
                    ]
                }
            },
        }
    }

    with patch(
        "lan_streamer.services.scan_agent_client.scan_agent_client.match_metadata"
    ) as mock_agent_match:
        test_controller._dispatch_metadata_match_to_agents(
            "Show Alpha", {"provider": "TMDB", "id": "999"}, False
        )

    call_kwargs = mock_agent_match.call_args[1]
    assert "media_identifier" not in call_kwargs
    assert call_kwargs["path"] == "/remote/media/tv/Show Alpha"


def test_scan_finished_matches_remote_library_id(test_controller: Controller) -> None:
    """A renamed library is still matched by the persisted agent library id."""
    test_controller._config.libraries["Remote TV"]["remote_library_id"] = 42

    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller._on_agent_scan_finished(
            {"job_id": 1, "library_ids": [42], "libraries": ["Different Name"]},
            "http://127.0.0.1:8000",
        )
        mock_queue_sync.assert_called_once_with("Remote TV", emit_signal=True)

    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller._on_agent_scan_finished(
            {"job_id": 2, "library_ids": [99], "libraries": ["Different Name"]},
            "http://127.0.0.1:8000",
        )
        mock_queue_sync.assert_not_called()


def test_reload_combined_view_preserves_cache_without_rows(
    test_controller: Controller,
) -> None:
    """An empty Combined View must not wipe the in-memory library cache."""
    test_controller.current_tab_name = "Combined View"
    test_controller._config.combined_views = []
    existing_data = {"Show Alpha": {"name": "Show Alpha"}}
    test_controller.cached_library_data = existing_data
    loaded_emitted: list[bool] = []
    test_controller.library_loaded.connect(lambda: loaded_emitted.append(True))

    with (
        patch.object(test_controller, "_load_tab_library_data") as mock_load,
        patch.object(test_controller, "_cache_series_metrics"),
    ):
        test_controller._reload_current_tab_data()

    mock_load.assert_not_called()
    assert test_controller.cached_library_data is existing_data
    assert loaded_emitted == [True]


def test_reload_combined_view_loads_configured_libraries(
    test_controller: Controller,
) -> None:
    """Combined View reloads the union of enabled row libraries."""
    test_controller.current_tab_name = "Combined View"
    test_controller._config.combined_views = [
        {"enabled": True, "libraries": ["Remote TV"]},
        {"enabled": False, "libraries": ["Ignored"]},
    ]
    reloaded_data = {"Show Alpha": {"name": "Show Alpha"}}

    with (
        patch.object(
            test_controller, "_load_tab_library_data", return_value=reloaded_data
        ) as mock_load,
        patch.object(test_controller, "_cache_series_metrics"),
    ):
        test_controller._reload_current_tab_data()

    mock_load.assert_called_once_with(["Remote TV"], trigger_remote_sync=False)
    assert test_controller.cached_library_data is reloaded_data


def test_hybrid_library_without_agent_is_not_refreshed(
    test_controller: Controller,
) -> None:
    """A hybrid library with no agent source must not retry a guaranteed failure."""
    test_controller._config.libraries["Hybrid TV"] = {
        "management_type": "hybrid",
        "type": "tv",
        "paths": [],
    }
    test_controller._db.load_library.return_value = {
        "Show Alpha": {"name": "Show Alpha"}
    }

    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller.select_tab("Hybrid TV")

    mock_queue_sync.assert_not_called()
    assert test_controller._should_refresh_remote_library("Hybrid TV") is False


def test_failed_sync_attempt_backs_off_freshness_checks(
    test_controller: Controller,
) -> None:
    """A recent failed attempt suppresses repeated tab-triggered syncs."""
    test_controller._db.load_library.return_value = {
        "Show Alpha": {"name": "Show Alpha"}
    }
    test_controller._remote_library_last_sync_attempt["Remote TV"] = 1000.0

    with (
        patch("time.time", return_value=1030.0),
        patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync,
    ):
        test_controller.select_tab("Remote TV")

    mock_queue_sync.assert_not_called()


def test_start_agent_event_listeners_normalizes_urls(
    test_controller: Controller,
) -> None:
    """Trailing-slash variants must not create duplicate SSE listeners."""
    test_controller._config.scan_agents = {"http://127.0.0.1:8000/": {"enabled": True}}

    with patch(
        "lan_streamer.backend.agent_event_worker.AgentEventListenerWorker.start"
    ):
        test_controller.start_agent_event_listeners()

    assert list(test_controller.agent_event_listeners.keys()) == [
        "http://127.0.0.1:8000"
    ]


def test_bulk_watch_events_coalesce_into_one_library_reload(
    test_controller: Controller,
) -> None:
    """N distinct watch events must produce one reload and persist every path."""
    first_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    second_path = "/local/mount/tv/Show Alpha/S01E02.mkv"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": first_path,
                            "watched": False,
                            "last_played_position": 0,
                        },
                        {
                            "name": "Episode 2",
                            "path": second_path,
                            "watched": False,
                            "last_played_position": 0,
                        },
                    ]
                }
            },
        }
    }

    mock_smart_row_service = MagicMock()
    mock_smart_row_service.on_episode_watched.side_effect = lambda media_path: (
        ["hash_alpha"] if media_path.endswith("E01.mkv") else ["hash_beta"]
    )
    test_controller._smart_row_service = mock_smart_row_service

    loaded_emitted: list[bool] = []
    test_controller.library_loaded.connect(lambda: loaded_emitted.append(True))
    smart_rows_emitted: list[list[str]] = []
    test_controller.smart_rows_updated.connect(smart_rows_emitted.append)

    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
            "watched": True,
            "position_seconds": 100,
            "last_played_at": 1729355000,
        },
        "http://127.0.0.1:8000",
    )
    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E02.mkv",
            "watched": True,
            "position_seconds": 200,
            "last_played_at": 1729355001,
        },
        "http://127.0.0.1:8000",
    )

    assert loaded_emitted == []
    assert test_controller._db.update_episode_watched_status.call_count == 0

    _flush_remote_watch_events(test_controller)

    assert loaded_emitted == [True]
    watched_paths = [
        call.args[0]
        for call in test_controller._db.update_episode_watched_status.call_args_list
    ]
    assert watched_paths == [first_path, second_path]
    assert smart_rows_emitted == [["hash_alpha", "hash_beta"]]


def test_same_path_watch_events_keep_only_latest_state(
    test_controller: Controller,
) -> None:
    """Two events for one path persist the latest position and watched state once."""
    episode_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": episode_path,
                            "watched": False,
                            "last_played_position": 0,
                        }
                    ]
                }
            },
        }
    }

    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
            "watched": False,
            "position_seconds": 10,
            "last_played_at": 1729355000,
        },
        "http://127.0.0.1:8000",
    )
    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
            "watched": True,
            "position_seconds": 99,
            "last_played_at": 1729355001,
        },
        "http://127.0.0.1:8000",
    )
    _flush_remote_watch_events(test_controller)

    episode_record = test_controller.cached_library_data["Show Alpha"]["seasons"][
        "Season 1"
    ]["episodes"][0]
    assert episode_record["watched"] is True
    assert episode_record["last_played_position"] == 99
    test_controller._db.update_episode_watched_status.assert_called_once_with(
        episode_path, True
    )
    test_controller._db.update_episode_playback_position.assert_called_once_with(
        episode_path, 99
    )


def test_out_of_order_watch_event_does_not_overwrite_newer_state(
    test_controller: Controller,
) -> None:
    """An older last_played_at must not clobber newer in-memory or DB state."""
    episode_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": episode_path,
                            "watched": False,
                            "last_played_position": 0,
                        }
                    ]
                }
            },
        }
    }

    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
            "watched": True,
            "position_seconds": 500,
            "last_played_at": 1729356000,
        },
        "http://127.0.0.1:8000",
    )
    _flush_remote_watch_events(test_controller)

    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
            "watched": False,
            "position_seconds": 10,
            "last_played_at": 1729355000,
        },
        "http://127.0.0.1:8000",
    )
    _flush_remote_watch_events(test_controller)

    episode_record = test_controller.cached_library_data["Show Alpha"]["seasons"][
        "Season 1"
    ]["episodes"][0]
    assert episode_record["watched"] is True
    assert episode_record["last_played_position"] == 500
    test_controller._db.update_episode_watched_status.assert_called_once_with(
        episode_path, True
    )


def test_flush_skips_event_older_than_cached_playback_state(
    test_controller: Controller,
) -> None:
    """A cached item last_played_at newer than the event must be preserved."""
    episode_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": episode_path,
                            "watched": True,
                            "last_played_position": 500,
                            "last_played_at": 1729356000,
                        }
                    ]
                }
            },
        }
    }

    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
            "watched": False,
            "position_seconds": 10,
            "last_played_at": 1729355000,
        },
        "http://127.0.0.1:8000",
    )
    _flush_remote_watch_events(test_controller)

    episode_record = test_controller.cached_library_data["Show Alpha"]["seasons"][
        "Season 1"
    ]["episodes"][0]
    assert episode_record["watched"] is True
    assert episode_record["last_played_position"] == 500
    assert episode_record["last_played_at"] == 1729356000


def test_off_tab_watch_event_persists_without_library_reload(
    test_controller: Controller,
) -> None:
    """Events for paths outside the current tab still persist to DB/smart rows."""
    off_tab_path = "/local/mount/tv/Other Show/S01E01.mkv"
    test_controller.cached_library_data = {}

    mock_smart_row_service = MagicMock()
    mock_smart_row_service.on_episode_watched.return_value = ["hash_off_tab"]
    test_controller._smart_row_service = mock_smart_row_service

    loaded_emitted: list[bool] = []
    test_controller.library_loaded.connect(lambda: loaded_emitted.append(True))
    smart_rows_emitted: list[list[str]] = []
    test_controller.smart_rows_updated.connect(smart_rows_emitted.append)

    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Other Show/S01E01.mkv",
            "watched": True,
            "position_seconds": 42,
            "last_played_at": 1729355000,
        },
        "http://127.0.0.1:8000",
    )
    _flush_remote_watch_events(test_controller)

    assert loaded_emitted == []
    test_controller._db.update_episode_watched_status.assert_called_once_with(
        off_tab_path, True
    )
    test_controller._db.update_episode_playback_position.assert_called_once_with(
        off_tab_path, 42
    )
    mock_smart_row_service.on_episode_watched.assert_called_once_with(off_tab_path)
    assert smart_rows_emitted == [["hash_off_tab"]]


def test_watch_event_handler_defers_work_until_flush(
    test_controller: Controller,
) -> None:
    """The Qt-thread handler must not scan, write, or recompute before flushing."""
    episode_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": episode_path,
                            "watched": False,
                            "last_played_position": 0,
                        }
                    ]
                }
            },
        }
    }

    with (
        patch.object(
            test_controller, "_apply_remote_watch_events_batch_to_database"
        ) as mock_batch_database,
        patch.object(
            test_controller,
            "_apply_remote_watch_events_batch_to_smart_rows",
            return_value=["hash_abc"],
        ) as mock_batch_smart_rows,
        patch.object(test_controller, "_cache_series_metrics") as mock_cache_metrics,
        patch.object(
            test_controller._smart_row_service, "on_episode_watched"
        ) as mock_single_smart_row,
    ):
        test_controller._on_agent_watch_updated(
            {
                "media_type": "episode",
                "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
                "watched": True,
                "position_seconds": 321,
                "last_played_at": 1729355000,
            },
            "http://127.0.0.1:8000",
        )

        mock_batch_database.assert_not_called()
        mock_batch_smart_rows.assert_not_called()
        mock_cache_metrics.assert_not_called()
        mock_single_smart_row.assert_not_called()
        test_controller._db.update_episode_watched_status.assert_not_called()

        _flush_remote_watch_events(test_controller)

        mock_batch_database.assert_called_once()
        mock_batch_smart_rows.assert_called_once()
        mock_cache_metrics.assert_called_once()
        mock_single_smart_row.assert_not_called()


def test_watch_event_matches_episode_version_path(
    test_controller: Controller,
) -> None:
    """A version file path must update its episode even when the primary differs."""
    primary_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    version_path = "/local/mount/tv/Show Alpha/S01E01.alt.mkv"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": primary_path,
                            "watched": False,
                            "last_played_position": 0,
                            "versions": [
                                {"path": primary_path},
                                {"path": version_path},
                            ],
                        }
                    ]
                }
            },
        }
    }

    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E01.alt.mkv",
            "watched": True,
            "position_seconds": 50,
            "last_played_at": 1729355000,
        },
        "http://127.0.0.1:8000",
    )
    _flush_remote_watch_events(test_controller)

    episode_record = test_controller.cached_library_data["Show Alpha"]["seasons"][
        "Season 1"
    ]["episodes"][0]
    assert episode_record["watched"] is True
    assert episode_record["last_played_position"] == 50


def test_watch_event_timestamp_falls_back_to_timestamp_field(
    test_controller: Controller,
) -> None:
    """The explicit 'timestamp' field is used when last_played_at is absent."""
    episode_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": episode_path,
                            "watched": False,
                            "last_played_position": 0,
                        }
                    ]
                }
            },
        }
    }

    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
            "watched": True,
            "position_seconds": 50,
            "timestamp": 1729355999,
        },
        "http://127.0.0.1:8000",
    )
    _flush_remote_watch_events(test_controller)

    episode_record = test_controller.cached_library_data["Show Alpha"]["seasons"][
        "Season 1"
    ]["episodes"][0]
    assert episode_record["last_played_at"] == 1729355999.0


def test_watch_event_without_timestamp_uses_current_time(
    test_controller: Controller,
) -> None:
    """A payload without any timestamp uses the local clock as a fallback."""
    episode_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": episode_path,
                            "watched": False,
                            "last_played_position": 0,
                        }
                    ]
                }
            },
        }
    }

    with patch("lan_streamer.ui_views.controller.time.time", return_value=1234567890.0):
        test_controller._on_agent_watch_updated(
            {
                "media_type": "episode",
                "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
                "watched": True,
                "position_seconds": 50,
            },
            "http://127.0.0.1:8000",
        )
        _flush_remote_watch_events(test_controller)

    episode_record = test_controller.cached_library_data["Show Alpha"]["seasons"][
        "Season 1"
    ]["episodes"][0]
    assert episode_record["last_played_at"] == 1234567890.0


def test_smart_row_rebuild_falls_back_to_remote_path(
    test_controller: Controller,
) -> None:
    """When the local path yields no hashes, the remote path is tried."""
    local_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    remote_path = "/remote/media/tv/Show Alpha/S01E01.mkv"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": local_path,
                            "watched": False,
                            "last_played_position": 0,
                        }
                    ]
                }
            },
        }
    }

    mock_smart_row_service = MagicMock()
    mock_smart_row_service.on_episode_watched.side_effect = lambda media_path: (
        [] if media_path == local_path else ["hash_remote"]
    )
    test_controller._smart_row_service = mock_smart_row_service
    smart_rows_emitted: list[list[str]] = []
    test_controller.smart_rows_updated.connect(smart_rows_emitted.append)

    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": remote_path,
            "watched": True,
            "position_seconds": 50,
            "last_played_at": 1729355000,
        },
        "http://127.0.0.1:8000",
    )
    _flush_remote_watch_events(test_controller)

    assert (
        mock_smart_row_service.on_episode_watched.call_args_list[0].args[0]
        == local_path
    )
    assert (
        mock_smart_row_service.on_episode_watched.call_args_list[1].args[0]
        == remote_path
    )
    assert smart_rows_emitted == [["hash_remote"]]


def test_batch_database_write_continues_after_one_path_fails(
    test_controller: Controller,
) -> None:
    """A failure for one path must not stop the rest of the batch."""
    first_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    second_path = "/local/mount/tv/Show Alpha/S01E02.mkv"
    test_controller.cached_library_data = {}

    test_controller._db.update_episode_watched_status.side_effect = [
        RuntimeError("database locked"),
        None,
    ]

    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
            "watched": True,
            "position_seconds": 10,
            "last_played_at": 1729355000,
        },
        "http://127.0.0.1:8000",
    )
    test_controller._on_agent_watch_updated(
        {
            "media_type": "episode",
            "path": "/remote/media/tv/Show Alpha/S01E02.mkv",
            "watched": True,
            "position_seconds": 20,
            "last_played_at": 1729355001,
        },
        "http://127.0.0.1:8000",
    )
    _flush_remote_watch_events(test_controller)

    watched_paths = [
        call.args[0]
        for call in test_controller._db.update_episode_watched_status.call_args_list
    ]
    assert watched_paths == [first_path, second_path]


def test_watch_event_with_unparseable_timestamp_uses_current_time(
    test_controller: Controller,
) -> None:
    """An unparseable timestamp falls back to the local clock and still applies."""
    episode_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    test_controller.cached_library_data = {
        "Show Alpha": {
            "name": "Show Alpha",
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": episode_path,
                            "watched": False,
                            "last_played_position": 0,
                        }
                    ]
                }
            },
        }
    }

    with patch("lan_streamer.ui_views.controller.time.time", return_value=1234567890.0):
        test_controller._on_agent_watch_updated(
            {
                "media_type": "episode",
                "path": "/remote/media/tv/Show Alpha/S01E01.mkv",
                "watched": True,
                "position_seconds": 50,
                "last_played_at": "not-a-timestamp",
            },
            "http://127.0.0.1:8000",
        )
        _flush_remote_watch_events(test_controller)

    episode_record = test_controller.cached_library_data["Show Alpha"]["seasons"][
        "Season 1"
    ]["episodes"][0]
    assert episode_record["watched"] is True
    assert episode_record["last_played_at"] == 1234567890.0


def test_recent_watch_event_pruning_also_clears_timestamp_guard(
    test_controller: Controller,
) -> None:
    """Expired recent-event entries must also release their monotonic timestamp."""
    expired_path = "/local/mount/tv/Show Alpha/S01E01.mkv"
    test_controller._recent_remote_watch_events = {
        expired_path: {
            "watched": True,
            "position_seconds": 1,
            "received_at": 0.0,
        }
    }
    test_controller._remote_watch_event_timestamps = {expired_path: 1.0}

    test_controller._record_recent_remote_watch_event(
        "/local/mount/tv/Show Alpha/S01E02.mkv", {"watched": False}
    )

    assert expired_path not in test_controller._recent_remote_watch_events
    assert expired_path not in test_controller._remote_watch_event_timestamps


def test_remote_watch_persistence_uses_exported_database_api() -> None:
    """Remote watch events must target the real playback-position API.

    The original P0 called ``update_playback_position``, which does not exist
    in the database module. Asserting the database contract here prevents a
    MagicMock from hiding that mistake again.
    """
    assert callable(database_module.update_episode_playback_position)
    assert not hasattr(database_module, "update_playback_position")


def test_stream_gap_queues_sync_for_agent_libraries(
    test_controller: Controller,
) -> None:
    """A dropped agent history resynchronizes every library sourced from it."""
    test_controller.current_tab_name = "Remote TV"
    test_controller._remote_library_last_synced["Remote TV"] = 1000.0
    test_controller._remote_library_last_sync_attempt["Remote TV"] = 1000.0
    status_messages: list[str] = []
    test_controller.status_changed.connect(status_messages.append)

    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller._on_agent_stream_gap(
            {"oldest_sequence": 10, "latest_sequence": 20},
            "http://127.0.0.1:8000",
        )

    mock_queue_sync.assert_called_once_with("Remote TV", emit_signal=True)
    assert "Remote TV" not in test_controller._remote_library_last_synced
    assert "Remote TV" not in test_controller._remote_library_last_sync_attempt
    assert any("history was truncated" in message for message in status_messages)


def test_stream_gap_signal_is_connected_to_handler(
    test_controller: Controller,
) -> None:
    """The worker's stream_gap signal must reach the controller resync handler."""
    with (
        patch("lan_streamer.backend.agent_event_worker.AgentEventListenerWorker.start"),
        patch.object(test_controller, "_on_agent_stream_gap") as mock_handler,
    ):
        test_controller.start_agent_event_listeners()
        worker = test_controller.agent_event_listeners["http://127.0.0.1:8000"]
        worker.stream_gap.emit({"oldest_sequence": 5})

    mock_handler.assert_called_once_with(
        {"oldest_sequence": 5}, "http://127.0.0.1:8000"
    )


def test_remote_sync_finalization_rebuilds_off_the_main_thread(
    test_controller: Controller,
) -> None:
    """Smart-row rebuild must not run on the Qt/main thread."""
    main_thread_identifier = threading.get_ident()
    rebuild_thread_identifiers: list[int] = []

    def record_rebuild_thread(library_names: list[str]) -> list[str]:
        rebuild_thread_identifiers.append(threading.get_ident())
        return []

    test_controller._smart_row_service = MagicMock()
    test_controller._smart_row_service.rebuild_for_libraries.side_effect = (
        record_rebuild_thread
    )
    test_controller._remote_sync_scheduled.add("Remote TV")
    test_controller._remote_sync_emit_signal["Remote TV"] = False

    with patch.object(test_controller, "_drain_remote_sync_queue"):
        test_controller._on_remote_sync_finished(
            {"success": True, "items": 1}, "Remote TV"
        )
        test_controller.async_task_manager.stop_all()

    assert rebuild_thread_identifiers
    assert rebuild_thread_identifiers[0] != main_thread_identifier


def test_agent_scan_finished_triggers_sync_and_removes_deleted_series(
    test_controller: Controller,
) -> None:
    """When scan.finished is received from agent, remote sync is queued and deleted series are pruned."""
    test_controller.current_tab_name = "Remote TV"
    test_controller.cached_library_data = {
        "Old Series": {"name": "Old Series", "seasons": {}},
        "Surviving Series": {"name": "Surviving Series", "seasons": {}},
    }

    with patch.object(test_controller, "_queue_remote_sync") as mock_queue_sync:
        test_controller._on_agent_scan_finished(
            {"job_id": 101, "libraries": ["Remote TV"]},
            "http://127.0.0.1:8000",
        )
        mock_queue_sync.assert_called_once_with("Remote TV", emit_signal=True)

    # Now simulate the remote sync completion where agent returned only "Surviving Series"
    with (
        patch.object(
            test_controller, "_resolve_tab_library_names", return_value=["Remote TV"]
        ),
        patch.object(
            test_controller,
            "_load_tab_library_data",
            return_value={
                "Surviving Series": {"name": "Surviving Series", "seasons": {}}
            },
        ),
        patch.object(test_controller, "_drain_remote_sync_queue"),
    ):
        test_controller._remote_sync_scheduled.add("Remote TV")
        test_controller._remote_sync_emit_signal["Remote TV"] = True
        test_controller._on_remote_sync_finished(
            {"success": True, "items": 1}, "Remote TV"
        )
        test_controller.async_task_manager.stop_all()

    assert "Old Series" not in test_controller.cached_library_data
    assert "Surviving Series" in test_controller.cached_library_data
