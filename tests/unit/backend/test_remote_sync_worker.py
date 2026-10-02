"""Tests for the remote-library synchronization worker."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QObject

from lan_streamer.backend.remote_sync_worker import RemoteSyncWorker
from lan_streamer.system.async_task_manager import AsyncTaskManager


def _run(coro: Any) -> None:
    asyncio.run(coro)


def test_remote_sync_worker_runs_sync_off_ui_thread() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)

    async def run_test() -> None:
        library_configuration = {
            "management_type": "remote",
            "type": "tv",
            "agent_url": "http://127.0.0.1:8800",
        }
        database = MagicMock()
        worker = RemoteSyncWorker(
            library_name="Remote TV",
            library_configuration=library_configuration,
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )
        assert worker.library_name == "Remote TV"
        assert worker._is_async_worker is True

        with patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
            return_value={"Show A": {"name": "Show A", "seasons": {}}},
        ):
            result = await worker.run_async()

        assert result["success"] is True
        assert result["items"] == 1
        database.save_library.assert_called_once()
        assert result["library_name"] == "Remote TV"

    _run(run_test())


def test_remote_sync_worker_returns_error_result_on_failure() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)

    async def run_test() -> None:
        from lan_streamer.services.scan_agent_client import ScanAgentConnectionError

        database = MagicMock()
        worker = RemoteSyncWorker(
            library_name="Remote TV",
            library_configuration={
                "management_type": "remote",
                "type": "tv",
                "agent_url": "http://127.0.0.1:8800",
            },
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )
        with patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
            side_effect=ScanAgentConnectionError("unreachable"),
        ):
            result = await worker.run_async()
        assert result["success"] is False
        assert "unreachable" in result["error"]

    _run(run_test())


def test_remote_sync_worker_multi_agent_sources() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)

    async def run_test() -> None:
        library_configuration = {
            "management_type": "remote",
            "type": "tv",
            "sources": [
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8800",
                    "source_id": "src-tv-01",
                },
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8800",
                    "source_id": "src-tv-02",
                },
            ],
        }
        database = MagicMock()
        database.load_library.return_value = {}
        worker = RemoteSyncWorker(
            library_name="Combined Remote TV",
            library_configuration=library_configuration,
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )

        def mock_fetch_source_items(
            agent_url: str, source_id: str, **kwargs: Any
        ) -> dict[str, Any]:
            if source_id == "src-tv-01":
                return {"Show A": {"name": "Show A", "seasons": {}}}
            return {"Show B": {"name": "Show B", "seasons": {}}}

        with patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
            side_effect=mock_fetch_source_items,
        ):
            result = await worker.run_async()

        assert result["success"] is True
        assert result["items"] == 2
        database.save_library.assert_called_once()
        saved_items = database.save_library.call_args[0][1]
        assert "Show A" in saved_items
        assert "Show B" in saved_items

    _run(run_test())


def test_remote_sync_worker_hybrid_preserves_local_items() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)

    async def run_test() -> None:
        library_configuration = {
            "management_type": "hybrid",
            "type": "tv",
            "sources": [
                {"type": "local", "path": "/local/anime"},
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8800",
                    "source_id": "src-agent-anime",
                },
            ],
        }
        database = MagicMock()
        # Existing database state has a locally-scanned show
        database.load_library.return_value = {
            "Local Show": {"name": "Local Show", "seasons": {}}
        }
        worker = RemoteSyncWorker(
            library_name="Anime",
            library_configuration=library_configuration,
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )

        with patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
            return_value={"Remote Show": {"name": "Remote Show", "seasons": {}}},
        ):
            result = await worker.run_async()

        assert result["success"] is True
        database.save_library.assert_called_once()
        saved_items = database.save_library.call_args[0][1]
        assert "Local Show" in saved_items
        assert "Remote Show" in saved_items

    _run(run_test())


def test_remote_sync_worker_back_syncs_watch_and_metadata() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)

    async def run_test() -> None:
        library_configuration = {
            "management_type": "remote",
            "type": "tv",
            "agent_url": "http://127.0.0.1:8800",
            "mount_mappings": {"/mnt/share": "/Volumes/share"},
        }
        local_desktop_items = {
            "Anime Series": {
                "name": "Anime Series",
                "seasons": {
                    "Season 1": {
                        "metadata": {"myanimelist_id": 9999},
                        "episodes": [
                            {
                                "path": "/Volumes/share/Anime/S01E01.mkv",
                                "episode_number": 1,
                                "watched": True,
                                "last_played_position": 350,
                                "tmdb_episode_identifier": "tmdb-ep-99",
                                "myanimelist_anime_id": 9999,
                                "myanimelist_episode_number": 1,
                            }
                        ],
                    }
                },
            }
        }
        database = MagicMock()
        database.load_library.return_value = local_desktop_items
        worker = RemoteSyncWorker(
            library_name="Anime Remote",
            library_configuration=library_configuration,
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )

        mock_agent_items = {
            "Anime Series": {
                "name": "Anime Series",
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "path": "/mnt/share/Anime/S01E01.mkv",
                                "episode_number": 1,
                                "watched": False,
                            }
                        ],
                    }
                },
            }
        }

        with (
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
                return_value=mock_agent_items,
            ),
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.sync_watch_events"
            ) as mock_sync_watch,
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.apply_manual_metadata_mappings"
            ) as mock_sync_mappings,
        ):
            result = await worker.run_async()

        assert result["success"] is True
        database.save_library.assert_called_once()

        mock_sync_watch.assert_called_once()
        agent_url, watch_events = mock_sync_watch.call_args[0]
        assert agent_url == "http://127.0.0.1:8800"
        assert len(watch_events) == 1
        assert watch_events[0]["path"] == "/mnt/share/Anime/S01E01.mkv"
        assert watch_events[0]["watched"] is True
        assert watch_events[0]["position_seconds"] == 350

        mock_sync_mappings.assert_called_once()
        agent_url, mappings = mock_sync_mappings.call_args[0]
        assert agent_url == "http://127.0.0.1:8800"
        assert len(mappings) == 1
        assert mappings[0]["path"] == "/mnt/share/Anime/S01E01.mkv"
        assert mappings[0]["tmdb_episode_identifier"] == "tmdb-ep-99"
        assert mappings[0]["myanimelist_id"] == 9999
        assert mappings[0]["myanimelist_anime_id"] == 9999
        assert mappings[0]["myanimelist_episode_number"] == 1

    _run(run_test())


def test_remote_sync_worker_skips_back_sync_when_already_in_sync() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)

    async def run_test() -> None:
        library_configuration = {
            "management_type": "remote",
            "type": "tv",
            "agent_url": "http://127.0.0.1:8800",
            "mount_mappings": {"/mnt/share": "/Volumes/share"},
        }
        identical_items = {
            "Anime Series": {
                "name": "Anime Series",
                "seasons": {
                    "Season 1": {
                        "metadata": {"myanimelist_id": 9999},
                        "episodes": [
                            {
                                "path": "/Volumes/share/Anime/S01E01.mkv",
                                "episode_number": 1,
                                "watched": True,
                                "last_played_position": 350,
                                "tmdb_episode_identifier": "tmdb-ep-99",
                                "myanimelist_anime_id": 9999,
                                "myanimelist_episode_number": 1,
                            }
                        ],
                    }
                },
            }
        }
        database = MagicMock()
        database.load_library.return_value = identical_items
        worker = RemoteSyncWorker(
            library_name="Anime Remote",
            library_configuration=library_configuration,
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )

        with (
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
                return_value=identical_items,
            ),
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.sync_watch_events"
            ) as mock_sync_watch,
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.apply_manual_metadata_mappings"
            ) as mock_sync_mappings,
        ):
            result = await worker.run_async()

        assert result["success"] is True
        database.save_library.assert_called_once()
        # When desktop and agent are already in sync, no redundant network calls are made
        mock_sync_watch.assert_not_called()
        mock_sync_mappings.assert_not_called()

    _run(run_test())


def test_remote_sync_worker_back_syncs_in_progress_position_delta() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)

    async def run_test() -> None:
        library_configuration = {
            "management_type": "remote",
            "type": "tv",
            "agent_url": "http://127.0.0.1:8800",
            "mount_mappings": {"/mnt/share": "/Volumes/share"},
        }
        local_desktop_items = {
            "Anime Series": {
                "name": "Anime Series",
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "path": "/Volumes/share/Anime/S01E01.mkv",
                                "episode_number": 1,
                                "watched": False,
                                "last_played_position": 420,
                                "last_played_at": 1000,
                            }
                        ],
                    }
                },
            }
        }
        database = MagicMock()
        database.load_library.return_value = local_desktop_items
        worker = RemoteSyncWorker(
            library_name="Anime Remote",
            library_configuration=library_configuration,
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )

        mock_agent_items = {
            "Anime Series": {
                "name": "Anime Series",
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "path": "/mnt/share/Anime/S01E01.mkv",
                                "episode_number": 1,
                                "watched": False,
                                "last_played_position": 0,
                                "last_played_at": 500,
                            }
                        ],
                    }
                },
            }
        }

        with (
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
                return_value=mock_agent_items,
            ),
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.sync_watch_events"
            ) as mock_sync_watch,
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.apply_manual_metadata_mappings"
            ),
        ):
            result = await worker.run_async()

        assert result["success"] is True
        mock_sync_watch.assert_called_once()
        agent_url, watch_events = mock_sync_watch.call_args[0]
        assert agent_url == "http://127.0.0.1:8800"
        assert len(watch_events) == 1
        assert watch_events[0]["path"] == "/mnt/share/Anime/S01E01.mkv"
        assert watch_events[0]["watched"] is False
        assert watch_events[0]["event"] == "stop"
        assert watch_events[0]["position_seconds"] == 420.0

    _run(run_test())


def test_remote_sync_worker_does_not_overwrite_newer_agent_progress() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)

    async def run_test() -> None:
        library_configuration = {
            "type": "tv",
            "sources": [
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8800",
                    "mount_mappings": {"/mnt/share": "/Volumes/share"},
                }
            ],
        }

        database = MagicMock()
        database.load_library.return_value = {
            "Anime Series": {
                "name": "Anime Series",
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "path": "/Volumes/share/Anime/S01E01.mkv",
                                "episode_number": 1,
                                "watched": False,
                                "last_played_position": 100,
                                "last_played_at": 1000,
                            }
                        ],
                    }
                },
            }
        }

        worker = RemoteSyncWorker(
            library_name="Anime",
            library_configuration=library_configuration,
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )

        # Agent has played further and more recently
        mock_agent_items = {
            "Anime Series": {
                "name": "Anime Series",
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "path": "/mnt/share/Anime/S01E01.mkv",
                                "episode_number": 1,
                                "watched": False,
                                "last_played_position": 500,
                                "last_played_at": 2000,
                            }
                        ],
                    }
                },
            }
        }

        with (
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
                return_value=mock_agent_items,
            ),
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.sync_watch_events"
            ) as mock_sync_watch,
            patch(
                "lan_streamer.services.scan_agent_client.scan_agent_client.apply_manual_metadata_mappings"
            ),
        ):
            result = await worker.run_async()

        assert result["success"] is True
        mock_sync_watch.assert_not_called()

    _run(run_test())
