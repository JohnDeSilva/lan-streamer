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
    assert worker._last_sequence == 3


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


def test_agent_event_worker_first_connection_uses_live_tail_and_timeouts() -> None:
    """The first connection must not replay history and must use socket timeouts."""
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="http://127.0.0.1:8000",
        async_task_manager=task_manager,
        parent=parent,
    )

    recorded: dict[str, Any] = {}

    class EmptyContent:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class MockResponse:
        status = 200
        content = EmptyContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockSession:
        def __init__(self, **kwargs: Any) -> None:
            recorded["session_kwargs"] = kwargs

        def get(self, url: str, **kwargs: Any):
            recorded["url"] = url
            recorded["headers"] = kwargs.get("headers", {})
            worker.stop()
            return MockResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    async def run_test() -> None:
        with patch("aiohttp.ClientSession", MockSession):
            await worker.run_async()

    _run_coroutine(run_test())

    assert recorded["url"].endswith("/api/v1/events?live=1")
    assert "Last-Event-ID" not in recorded["headers"]
    client_timeout = recorded["session_kwargs"]["timeout"]
    assert client_timeout.sock_connect == 10.0
    assert client_timeout.sock_read == 45.0


def test_agent_event_worker_reconnect_resumes_with_last_event_id() -> None:
    """Reconnects must resume from the last parsed SSE id instead of replaying."""
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="http://127.0.0.1:8000",
        async_task_manager=task_manager,
        parent=parent,
        reconnect_interval_seconds=0.01,
    )

    requests: list[tuple[str, dict[str, str]]] = []
    call_count = 0

    class LineContent:
        def __init__(self, lines: list[bytes]) -> None:
            self._lines = lines

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._lines:
                raise StopAsyncIteration
            return self._lines.pop(0)

    class MockResponse:
        status = 200

        def __init__(self, lines: list[bytes]) -> None:
            self.content = LineContent(lines)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get(self, url: str, **kwargs: Any):
            nonlocal call_count
            call_count += 1
            requests.append((url, kwargs.get("headers", {})))
            if call_count == 1:
                return MockResponse(
                    [
                        b"id: 7\n",
                        b"event: test.event\n",
                        b'data: {"value": 1}\n',
                        b"\n",
                    ]
                )
            worker.stop()
            return MockResponse([])

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    async def run_test() -> None:
        with (
            patch("aiohttp.ClientSession", MockSession),
            patch(
                "lan_streamer.backend.agent_event_worker.random.uniform",
                return_value=1.0,
            ),
        ):
            await worker.run_async()

    _run_coroutine(run_test())

    assert call_count >= 2
    assert requests[0][0].endswith("?live=1")
    assert "Last-Event-ID" not in requests[0][1]
    assert not requests[1][0].endswith("?live=1")
    assert requests[1][1]["Last-Event-ID"] == "7"
    assert worker._last_sequence == 7


def test_agent_event_worker_backoff_grows_and_caps() -> None:
    """Exponential backoff must double, cap at 30 s, and reset after connecting."""
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="http://127.0.0.1:8000",
        async_task_manager=task_manager,
        parent=parent,
        reconnect_interval_seconds=3.0,
    )

    with patch(
        "lan_streamer.backend.agent_event_worker.random.uniform", return_value=1.0
    ):
        assert worker._compute_backoff_delay() == 3.0
        worker._advance_backoff()
        assert worker._compute_backoff_delay() == 6.0
        worker._advance_backoff()
        assert worker._compute_backoff_delay() == 12.0
        while worker._current_backoff_seconds < 30.0:
            worker._advance_backoff()
        assert worker._compute_backoff_delay() == 30.0
        worker._reset_backoff()
        assert worker._compute_backoff_delay() == 3.0


def test_agent_event_worker_ignores_non_numeric_sequence_ids() -> None:
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="http://127.0.0.1:8000",
        async_task_manager=task_manager,
        parent=parent,
    )

    assert worker._parse_sequence("not-a-number") is None
    assert worker._parse_sequence("12") == 12


def test_agent_event_worker_start_without_event_loop_is_refused() -> None:
    """The infinite listener must not be executed synchronously without a loop."""
    parent = QObject()
    task_manager = AsyncTaskManager(parent=parent)
    worker = AgentEventListenerWorker(
        agent_url="http://127.0.0.1:8000",
        async_task_manager=task_manager,
        parent=parent,
    )

    worker.start()
    assert worker.is_running is False
