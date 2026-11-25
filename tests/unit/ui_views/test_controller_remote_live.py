"""Unit tests for live-only remote library features in Controller."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from lan_streamer.ui_views.controller import Controller

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def live_controller() -> Controller:
    mock_config = MagicMock()
    mock_config.libraries = {
        "Remote TV": {
            "management_type": "remote",
            "type": "tv",
            "agent_url": "http://127.0.0.1:8800",
            "sources": [
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8800",
                    "source_id": "src-tv",
                }
            ],
        }
    }
    mock_config.scan_agents = {"http://127.0.0.1:8800": {"mount_mappings": {}}}
    mock_config.sort_mode = "Alphabetical"
    mock_config.sort_descending = False
    mock_config.filter_out_watched = False
    mock_config.combined_views = []
    mock_config.get_tab_libraries.side_effect = lambda tab: [tab]
    mock_db = MagicMock()
    controller = Controller(config=mock_config, db=mock_db)
    controller.current_library_name = "Remote TV"
    controller._remote_library_memory_cache["Remote TV"] = {
        "Show One": {
            "name": "Show One",
            "metadata": {"poster_path": "/posters/show1.jpg"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "episode_number": 1,
                            "path": "/media/tv/Show One/S01E01.mkv",
                            "last_played_position": 120,
                            "watched": True,
                            "date_added": 100,
                        },
                        {
                            "name": "Ep 2",
                            "episode_number": 2,
                            "path": "/media/tv/Show One/S01E02.mkv",
                            "last_played_position": 0,
                            "watched": False,
                            "date_added": 200,
                        },
                    ]
                }
            },
        }
    }
    controller.cached_library_data = controller._remote_library_memory_cache[
        "Remote TV"
    ]
    return controller


def test_get_next_episode_and_playback_position_from_memory(
    live_controller: Controller,
) -> None:
    pos = live_controller.get_playback_position("/media/tv/Show One/S01E01.mkv")
    assert pos == 120
    live_controller._db.get_episode_playback_position.assert_not_called()

    next_ep = live_controller.get_next_episode("/media/tv/Show One/S01E01.mkv")
    assert next_ep is not None
    assert next_ep["path"] == "/media/tv/Show One/S01E02.mkv"
    assert next_ep["episode_number"] == 2
    assert next_ep["season"] == "Season 1"
    live_controller._db.get_next_episode.assert_not_called()

    assert live_controller.get_next_episode("/media/tv/Show One/S01E02.mkv") is None


def test_get_smart_row_items_and_purge_stale_remote_db(
    live_controller: Controller,
) -> None:
    items = live_controller.get_smart_row_items(["Remote TV"], "Alphabetical", "All")
    assert len(items) == 1
    assert items[0]["name"] == "Show One"

    live_controller._db.delete_library_records.return_value = {"series_deleted": 1}
    live_controller.purge_stale_remote_database_records()
    live_controller._db.delete_library_records.assert_called_once_with("Remote TV")


def test_apply_detected_mount_mappings_and_auto_detect_agent_mounts(
    live_controller: Controller, tmp_path: Path
) -> None:
    local_dir = str(tmp_path / "Volumes" / "tv")
    live_controller._apply_detected_mount_mappings(
        "Remote TV", {"/media/tv": local_dir}
    )
    assert (
        live_controller._config.libraries["Remote TV"]["mount_mappings"]["/media/tv"]
        == local_dir
    )
    live_controller._config.save_config.assert_called_once()

    from lan_streamer.ui_views.dialogs.agent_probe_worker import (
        auto_detect_agent_mounts,
    )

    with patch(
        "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_source_items"
    ) as mock_fetch:
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()
        result = auto_detect_agent_mounts(
            "http://127.0.0.1:8800",
            [{"id": "s1", "name": "TV", "root_paths": ["/media/tv"]}],
            existing_mappings={"/media/tv": str(existing_dir)},
        )
        assert result == {}
        mock_fetch.assert_not_called()
