"""Tests for AsyncWorkerBase."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest
from PySide6.QtCore import QObject

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_task_manager import AsyncTaskManager


# ---------------------------------------------------------------------------
# Stub worker for testing
# ---------------------------------------------------------------------------


class _StubAsyncWorker(AsyncWorkerBase):
    """Minimal concrete worker that returns a fixed value."""

    def __init__(
        self,
        async_task_manager: AsyncTaskManager,
        return_value: Any = "done",
        raise_error: Optional[Exception] = None,
        parent: Optional[QObject] = None,
        sleep_duration: float = 0.0,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self._return_value = return_value
        self._raise_error = raise_error
        self._sleep_duration = sleep_duration

    async def run_async(self) -> Any:
        if self._sleep_duration > 0:
            await asyncio.sleep(self._sleep_duration)
        if self._raise_error:
            raise self._raise_error
        return self._return_value


class _StubParent(QObject):
    """Minimal QObject parent for tests."""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_parent() -> _StubParent:
    return _StubParent()


@pytest.fixture
def task_manager(stub_parent: _StubParent) -> AsyncTaskManager:
    return AsyncTaskManager(parent=stub_parent)


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.run_until_complete(
        asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True)
    )
    loop.close()


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    return event_loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAsyncWorkerBase:
    def test_worker_properties(self, task_manager: AsyncTaskManager) -> None:
        worker = _StubAsyncWorker(async_task_manager=task_manager)
        assert worker._is_async_worker is True
        assert worker._cancelled is False

    def test_start_schedules_task(
        self,
        event_loop: asyncio.AbstractEventLoop,
        task_manager: AsyncTaskManager,
    ) -> None:
        """Verify start() creates a named async task."""
        worker = _StubAsyncWorker(async_task_manager=task_manager, sleep_duration=0.5)

        async def run() -> None:
            assert task_manager.task_names() == []
            worker.start()
            await asyncio.sleep(0.01)
            assert len(task_manager.task_names()) >= 1
            worker.stop()
            await asyncio.sleep(0.01)

        _run(run(), event_loop)

    def test_is_running_after_start(
        self, event_loop: asyncio.AbstractEventLoop, task_manager: AsyncTaskManager
    ) -> None:
        """Verify is_running is True after starting and False after stopping."""
        worker = _StubAsyncWorker(async_task_manager=task_manager, sleep_duration=0.5)

        async def run() -> None:
            assert worker.is_running is False
            worker.start()
            await asyncio.sleep(0.01)
            assert worker.is_running is True
            worker.stop()
            await asyncio.sleep(0.05)
            assert worker.is_running is False

        _run(run(), event_loop)

    def test_stop_cancels_task(
        self, event_loop: asyncio.AbstractEventLoop, task_manager: AsyncTaskManager
    ) -> None:
        """Verify stop() cancels the running task."""
        worker = _StubAsyncWorker(async_task_manager=task_manager, sleep_duration=0.5)

        async def run() -> None:
            worker.start()
            await asyncio.sleep(0.01)
            assert worker.is_running is True
            worker.stop()
            await asyncio.sleep(0.05)
            assert worker.is_running is False

        _run(run(), event_loop)

    def test_stop_without_start_does_not_raise(
        self, task_manager: AsyncTaskManager
    ) -> None:
        worker = _StubAsyncWorker(async_task_manager=task_manager)
        worker.stop()

    def test_is_async_worker_marker(self, task_manager: AsyncTaskManager) -> None:
        worker = _StubAsyncWorker(async_task_manager=task_manager)
        assert worker._is_async_worker is True

    def test_task_name_includes_class_name(
        self,
        event_loop: asyncio.AbstractEventLoop,
        task_manager: AsyncTaskManager,
    ) -> None:
        worker = _StubAsyncWorker(async_task_manager=task_manager, sleep_duration=0.5)

        async def run() -> None:
            worker.start()
            await asyncio.sleep(0.01)
            task_names = task_manager.task_names()
            assert any("_StubAsyncWorker" in name for name in task_names)
            worker.stop()
            await asyncio.sleep(0.01)

        _run(run(), event_loop)

    def test_cancelled_flag(
        self,
        event_loop: asyncio.AbstractEventLoop,
        task_manager: AsyncTaskManager,
    ) -> None:
        worker = _StubAsyncWorker(async_task_manager=task_manager, sleep_duration=0.5)

        async def run() -> None:
            assert worker._cancelled is False
            worker.start()
            await asyncio.sleep(0.01)
            assert worker._cancelled is False
            worker.stop()
            assert worker._cancelled is True

        _run(run(), event_loop)

    def test_finished_signal(
        self,
        event_loop: asyncio.AbstractEventLoop,
        task_manager: AsyncTaskManager,
    ) -> None:
        """Verify finished signal fires with the result."""
        worker = _StubAsyncWorker(
            async_task_manager=task_manager, return_value="test_result"
        )
        results: list[Any] = []

        async def run() -> None:
            worker.finished.connect(results.append)
            worker.start()
            await asyncio.sleep(0.1)
            worker.stop()

        _run(run(), event_loop)
        assert results == ["test_result"]

    def test_error_signal(
        self,
        event_loop: asyncio.AbstractEventLoop,
        task_manager: AsyncTaskManager,
    ) -> None:
        """Verify error signal fires when run_async raises."""
        worker = _StubAsyncWorker(
            async_task_manager=task_manager,
            raise_error=ValueError("worker error"),
        )
        errors: list[str] = []

        async def run() -> None:
            worker.error.connect(errors.append)
            worker.start()
            await asyncio.sleep(0.1)
            worker.stop()

        _run(run(), event_loop)
        assert len(errors) >= 1
        assert "worker error" in errors[0]
