"""Unit tests for the remote scan-agent SSE event listener worker."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QObject

from lan_streamer.backend.agent_event_worker import AgentEventListenerWorker
from lan_streamer.system.async_task_manager import AsyncTaskManager


def _run_coroutine(coroutine: Any) -> None:
    asyncio.run(coroutine)


def test_agent_event_worker_initialization() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="http://127.0.0.1:8800",
        async_task_manager=task_manager,
        parent=parent,
        reconnect_interval_seconds=1.0,
    )
    assert worker.agent_url == "http://127.0.0.1:8800"
    assert worker._is_async_worker is True
    assert worker.reconnect_interval_seconds == 1.0


def test_agent_event_worker_processes_sse_events() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="http://127.0.0.1:8000",
        async_task_manager=task_manager,
        parent=parent,
    )

    received_events: list[tuple[str, dict[str, Any]]] = []
    received_watch_updates: list[dict[str, Any]] = []
    received_metadata_updates: list[dict[str, Any]] = []
    received_scan_finished: list[dict[str, Any]] = []

    worker.event_received.connect(
        lambda event_name, payload: received_events.append((event_name, payload))
    )
    worker.watch_updated.connect(received_watch_updates.append)
    worker.metadata_updated.connect(received_metadata_updates.append)
    worker.scan_finished.connect(received_scan_finished.append)

    sample_lines = [
        b"id: 1\n",
        b"event: watch.updated\n",
        b'data: {"media_type": "episode", "path": "/media/tv/S01E01.mkv", "watched": true}\n',
        b"\n",
        b"id: 2\n",
        b"event: metadata.updated\n",
        b'data: {"media_type": "series", "media_identifier": 42, "tmdb_identifier": "12345"}\n',
        b"\n",
        b"id: 3\n",
        b"event: scan.finished\n",
        b'data: {"job_id": 10, "libraries": ["TV Shows"]}\n',
        b"\n",
    ]

    async def mock_line_generator():
        for line in sample_lines:
            yield line
        # After yielding, request interruption so the worker terminates cleanly
        worker.stop()

    class MockContent:
        def __aiter__(self):
            return mock_line_generator()

    class MockResponse:
        status = 200
        content = MockContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockSession:
        def get(self, url: str, **kwargs: Any):
            return MockResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    async def run_test() -> None:
        with patch("aiohttp.ClientSession", return_value=MockSession()):
            await worker.run_async()

    _run_coroutine(run_test())

    assert len(received_events) == 3
    assert len(received_watch_updates) == 1
    assert received_watch_updates[0]["media_type"] == "episode"
    assert received_watch_updates[0]["watched"] is True
    assert received_watch_updates[0]["path"] == "/media/tv/S01E01.mkv"

    assert len(received_metadata_updates) == 1
    assert received_metadata_updates[0]["media_identifier"] == 42
    assert received_metadata_updates[0]["tmdb_identifier"] == "12345"

    assert len(received_scan_finished) == 1
    assert received_scan_finished[0]["job_id"] == 10
    assert received_scan_finished[0]["libraries"] == ["TV Shows"]


def test_agent_event_worker_handles_connection_error_and_cancellation() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="http://127.0.0.1:8000",
        async_task_manager=task_manager,
        parent=parent,
        reconnect_interval_seconds=0.01,
    )

    connection_statuses: list[bool] = []
    worker.connection_status_changed.connect(
        lambda agent_url, is_connected: connection_statuses.append(is_connected)
    )

    import aiohttp

    call_count = 0

    class FailingSession:
        def get(self, url: str, **kwargs: Any):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                worker.stop()
            raise aiohttp.ClientConnectionError("Connection refused")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    async def run_test() -> None:
        with patch("aiohttp.ClientSession", return_value=FailingSession()):
            await worker.run_async()

    _run_coroutine(run_test())
    assert call_count >= 2
    assert False in connection_statuses


def test_agent_event_worker_handles_invalid_url() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="",
        async_task_manager=task_manager,
        parent=parent,
    )

    async def run_test() -> None:
        await worker.run_async()

    _run_coroutine(run_test())
    assert worker.is_running is False


def test_agent_event_worker_handles_non_200_response() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="http://127.0.0.1:8000",
        async_task_manager=task_manager,
        parent=parent,
        reconnect_interval_seconds=0.01,
    )

    class MockResponse500:
        status = 500
        request_info = MagicMock()
        history = ()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    call_count = 0

    class MockSession500:
        def get(self, url: str, **kwargs: Any):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                worker.stop()
            return MockResponse500()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    async def run_test() -> None:
        with patch("aiohttp.ClientSession", return_value=MockSession500()):
            await worker.run_async()

    _run_coroutine(run_test())
    assert call_count >= 2


def test_agent_event_worker_handles_comments_and_malformed_json() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="http://127.0.0.1:8000",
        async_task_manager=task_manager,
        parent=parent,
    )

    received_events: list[tuple[str, dict[str, Any]]] = []
    worker.event_received.connect(
        lambda event_name, payload: received_events.append((event_name, payload))
    )

    sample_lines = [
        b": ping comment\n",
        b"event: test.event\n",
        b"data: {not valid json}\n",
        b"\n",
        b"event: test.non_dict\n",
        b"data: [1, 2, 3]\n",
        b"\n",
        b"event: valid.event\n",
        b'data: {"valid": true}\n',
        b"\n",
    ]

    async def mock_line_generator():
        for line in sample_lines:
            yield line
        worker.stop()

    class MockContent:
        def __aiter__(self):
            return mock_line_generator()

    class MockResponse:
        status = 200
        content = MockContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockSession:
        def get(self, url: str, **kwargs: Any):
            return MockResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    async def run_test() -> None:
        with patch("aiohttp.ClientSession", return_value=MockSession()):
            await worker.run_async()

    _run_coroutine(run_test())
    assert len(received_events) == 1
    assert received_events[0] == ("valid.event", {"valid": True})
