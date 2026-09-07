"""Tests for remote library handling in ScanAllLibrariesWorker."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from PySide6.QtCore import QObject

from lan_streamer.backend.scan_worker_all import ScanAllLibrariesWorker
from lan_streamer.system.async_task_manager import AsyncTaskManager
from lan_streamer.system.config import config


def test_scan_worker_all_skips_remote_library() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = ScanAllLibrariesWorker(async_task_manager=task_manager)

    test_libraries = {
        "LocalLib": {
            "type": "tv",
            "management_type": "local",
            "paths": ["/local/tv"],
        },
        "RemoteLib": {
            "type": "tv",
            "management_type": "remote",
            "agent_url": "http://127.0.0.1:8800",
            "paths": ["/mnt/nas/tv"],
        },
    }

    mock_discovered_tree = {"type": "tv", "roots": {}}

    async def _run_test() -> None:
        with (
            patch.dict(config.libraries, test_libraries, clear=True),
            patch.object(
                worker,
                "_discover_single_library_tree",
                return_value=mock_discovered_tree,
            ) as mock_discover,
        ):
            tree = await worker._discover_tree(library_data_by_name={})

            assert mock_discover.call_count == 1
            assert mock_discover.call_args[0][0] == "LocalLib"
            assert "RemoteLib" in tree
            assert "LocalLib" in tree

    asyncio.run(_run_test())
