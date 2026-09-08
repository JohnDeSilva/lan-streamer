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
        database.save_library.assert_not_called()

    _run(run_test())
