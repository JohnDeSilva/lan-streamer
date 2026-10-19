"""Unit tests for Controller scan-agent SSE event handling and reactivity."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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
