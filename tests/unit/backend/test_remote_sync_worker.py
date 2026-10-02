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
