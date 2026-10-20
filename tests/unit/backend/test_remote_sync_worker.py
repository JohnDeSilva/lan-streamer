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


def test_remote_sync_worker_does_not_resurrect_deleted_series() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)

    async def run_test() -> None:
        library_configuration = {
            "management_type": "remote",
            "type": "tv",
            "agent_url": "http://127.0.0.1:8800",
        }
        database = MagicMock()
        # Existing database state has an old show that was removed on the remote agent
        database.load_library.return_value = {
            "Deleted Show": {"name": "Deleted Show", "seasons": {}},
            "Existing Show": {"name": "Existing Show", "seasons": {}},
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
            return_value={"Existing Show": {"name": "Existing Show", "seasons": {}}},
        ):
            result = await worker.run_async()

        assert result["success"] is True
        assert result["items"] == 1
        database.save_library.assert_called_once()
        saved_items = database.save_library.call_args[0][1]
        assert "Existing Show" in saved_items
        assert "Deleted Show" not in saved_items
        database.cleanup_removed_library_items.assert_called_once_with(
            "Anime", "tv", {"Existing Show"}
        )

    _run(run_test())


def test_remote_sync_worker_hybrid_purges_remote_items_missing_from_agent() -> None:
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
        # "Local Show" has files under /local/anime, "Old Remote Show" has files outside /local/anime
        database.load_library.return_value = {
            "Local Show": {
                "name": "Local Show",
                "seasons": {
                    "Season 1": {
                        "episodes": [
                            {"name": "E1", "path": "/local/anime/Local Show/e1.mkv"}
                        ]
                    }
                },
            },
            "Old Remote Show": {
                "name": "Old Remote Show",
                "seasons": {
                    "Season 1": {
                        "episodes": [
                            {"name": "E1", "path": "/mnt/remote/Old Remote Show/e1.mkv"}
                        ]
                    }
                },
            },
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
            return_value={
                "Active Remote Show": {"name": "Active Remote Show", "seasons": {}}
            },
        ):
            result = await worker.run_async()

        assert result["success"] is True
        database.save_library.assert_called_once()
        saved_items = database.save_library.call_args[0][1]
        assert "Local Show" in saved_items
        assert "Active Remote Show" in saved_items
        assert "Old Remote Show" not in saved_items
        database.cleanup_removed_library_items.assert_called_once_with(
            "Anime", "tv", {"Local Show", "Active Remote Show"}
        )

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


def test_remote_sync_worker_serializes_save_with_database_lock() -> None:
    """The snapshot save must hold the shared watch-state write lock."""
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    database_lock = MagicMock()

    async def run_test() -> None:
        database = MagicMock()
        database.load_library.return_value = {}
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
            database_lock=database_lock,
        )

        with patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
            return_value={"Show A": {"name": "Show A", "seasons": {}}},
        ):
            result = await worker.run_async()

        assert result["success"] is True
        assert worker._database_lock is database_lock
        database_lock.__enter__.assert_called_once()
        database_lock.__exit__.assert_called_once()
        database.save_library.assert_called_once()

    _run(run_test())


def test_remote_sync_worker_deduplicates_series_across_agent_sources() -> None:
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
                    "source_id": "remote-tv-01",
                },
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8801",
                    "source_id": "remote-tv-02",
                },
            ],
        }
        database = MagicMock()
        database.load_library.return_value = {}
        worker = RemoteSyncWorker(
            library_name="TV Shows",
            library_configuration=library_configuration,
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )

        source_1_items = {
            "Breaking Bad": {
                "name": "Breaking Bad",
                "metadata": {
                    "tmdb_identifier": "1396",
                    "tmdb_name": "Breaking Bad",
                    "overview": "Teacher becomes kingpin.",
                },
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "name": "Pilot",
                                "episode_number": 1,
                                "path": "/agent1/tv/Breaking Bad/S01E01.mkv",
                                "versions": [
                                    {"path": "/agent1/tv/Breaking Bad/S01E01.mkv"}
                                ],
                            },
                            {
                                "name": "Cat's in the Bag...",
                                "episode_number": 2,
                                "path": "/agent1/tv/Breaking Bad/S01E02.mkv",
                                "versions": [
                                    {"path": "/agent1/tv/Breaking Bad/S01E02.mkv"}
                                ],
                            },
                        ],
                    }
                },
            }
        }

        source_2_items = {
            "Breaking Bad (2008)": {
                "name": "Breaking Bad (2008)",
                "metadata": {
                    "tmdb_identifier": "1396",
                    "tmdb_name": "Breaking Bad",
                    "overview": "Teacher becomes kingpin.",
                },
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "name": "Pilot",
                                "episode_number": 1,
                                "path": "/agent2/tv/Breaking Bad (2008)/S01E01.4k.mkv",
                                "versions": [
                                    {
                                        "path": "/agent2/tv/Breaking Bad (2008)/S01E01.4k.mkv"
                                    }
                                ],
                            }
                        ],
                    },
                    "Season 2": {
                        "metadata": {},
                        "episodes": [
                            {
                                "name": "Seven Thirty-Seven",
                                "episode_number": 1,
                                "path": "/agent2/tv/Breaking Bad (2008)/S02E01.mkv",
                                "versions": [
                                    {
                                        "path": "/agent2/tv/Breaking Bad (2008)/S02E01.mkv"
                                    }
                                ],
                            }
                        ],
                    },
                },
            }
        }

        def mock_fetch(agent_url: str, source_id: str, **kwargs: Any) -> dict[str, Any]:
            if source_id == "remote-tv-01":
                return source_1_items
            return source_2_items

        with patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
            side_effect=mock_fetch,
        ):
            result = await worker.run_async()

        assert result["success"] is True
        assert result["items"] == 1
        database.save_library.assert_called_once()
        saved_library = database.save_library.call_args[0][1]
        assert len(saved_library) == 1
        series_key = next(iter(saved_library.keys()))
        merged_series = saved_library[series_key]

        # Both seasons must be present
        assert "Season 1" in merged_series["seasons"]
        assert "Season 2" in merged_series["seasons"]

        # Season 1 Episode 1 must have both versions preserved
        s1_episodes = merged_series["seasons"]["Season 1"]["episodes"]
        ep1 = next(ep for ep in s1_episodes if ep.get("episode_number") == 1)
        ep1_paths = [v["path"] for v in ep1["versions"]]
        assert "/agent1/tv/Breaking Bad/S01E01.mkv" in ep1_paths
        assert "/agent2/tv/Breaking Bad (2008)/S01E01.4k.mkv" in ep1_paths

        # Season 1 Episode 2 must be present
        assert any(ep.get("episode_number") == 2 for ep in s1_episodes)

        # Season 2 Episode 1 must be present
        s2_episodes = merged_series["seasons"]["Season 2"]["episodes"]
        assert any(ep.get("episode_number") == 1 for ep in s2_episodes)

    _run(run_test())


def test_remote_sync_worker_deduplicates_movies_across_agent_sources() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)

    async def run_test() -> None:
        library_configuration = {
            "management_type": "remote",
            "type": "movie",
            "sources": [
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8800",
                    "source_id": "remote-movies-01",
                },
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8801",
                    "source_id": "remote-movies-02",
                },
            ],
        }
        database = MagicMock()
        database.load_movie_library.return_value = {}
        worker = RemoteSyncWorker(
            library_name="Movies",
            library_configuration=library_configuration,
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )

        source_1_items = {
            "Inception": {
                "name": "Inception",
                "tmdb_identifier": "27205",
                "path": "/agent1/movies/Inception (2010)/Inception.mkv",
                "versions": [{"path": "/agent1/movies/Inception (2010)/Inception.mkv"}],
            }
        }

        source_2_items = {
            "Inception (2010)": {
                "name": "Inception (2010)",
                "tmdb_identifier": "27205",
                "path": "/agent2/movies/Inception (2010)/Inception.4k.mkv",
                "versions": [
                    {"path": "/agent2/movies/Inception (2010)/Inception.4k.mkv"}
                ],
            }
        }

        def mock_fetch(agent_url: str, source_id: str, **kwargs: Any) -> dict[str, Any]:
            if source_id == "remote-movies-01":
                return source_1_items
            return source_2_items

        with patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
            side_effect=mock_fetch,
        ):
            result = await worker.run_async()

        assert result["success"] is True
        assert result["items"] == 1
        database.save_movie_library.assert_called_once()
        saved_library = database.save_movie_library.call_args[0][1]
        assert len(saved_library) == 1
        movie_key = next(iter(saved_library.keys()))
        merged_movie = saved_library[movie_key]

        paths = [version["path"] for version in merged_movie["versions"]]
        assert "/agent1/movies/Inception (2010)/Inception.mkv" in paths
        assert "/agent2/movies/Inception (2010)/Inception.4k.mkv" in paths

    _run(run_test())


def test_remote_sync_worker_deduplicates_series_by_normalized_title() -> None:
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
                    "source_id": "remote-tv-01",
                },
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8801",
                    "source_id": "remote-tv-02",
                },
            ],
        }
        database = MagicMock()
        database.load_library.return_value = {}
        worker = RemoteSyncWorker(
            library_name="TV Shows",
            library_configuration=library_configuration,
            database=database,
            async_task_manager=task_manager,
            parent=parent,
        )

        source_1_items = {
            "Steins;Gate": {
                "name": "Steins;Gate",
                "metadata": {},
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "name": "Episode 1",
                                "episode_number": 1,
                                "path": "/agent1/tv/Steins Gate/S01E01.mkv",
                                "versions": [
                                    {"path": "/agent1/tv/Steins Gate/S01E01.mkv"}
                                ],
                            }
                        ],
                    }
                },
            }
        }

        source_2_items = {
            "steins.gate": {
                "name": "steins.gate",
                "metadata": {},
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "name": "Episode 1",
                                "episode_number": 1,
                                "path": "/agent2/tv/steins.gate/S01E01.720p.mkv",
                                "versions": [
                                    {"path": "/agent2/tv/steins.gate/S01E01.720p.mkv"}
                                ],
                            }
                        ],
                    }
                },
            }
        }

        def mock_fetch(agent_url: str, source_id: str, **kwargs: Any) -> dict[str, Any]:
            if source_id == "remote-tv-01":
                return source_1_items
            return source_2_items

        with patch(
            "lan_streamer.services.scan_agent_client.scan_agent_client.fetch_library_items",
            side_effect=mock_fetch,
        ):
            result = await worker.run_async()

        assert result["success"] is True
        assert result["items"] == 1
        database.save_library.assert_called_once()
        saved_library = database.save_library.call_args[0][1]
        assert len(saved_library) == 1
        series_key = next(iter(saved_library.keys()))
        merged_series = saved_library[series_key]

        episode_one = merged_series["seasons"]["Season 1"]["episodes"][0]
        episode_one_paths = [version["path"] for version in episode_one["versions"]]
        assert "/agent1/tv/Steins Gate/S01E01.mkv" in episode_one_paths
        assert "/agent2/tv/steins.gate/S01E01.720p.mkv" in episode_one_paths

    _run(run_test())
