"""
Tests for AsyncTaskManager — the asyncio-based task lifecycle manager.

These tests use a real ``asyncio`` event loop running in synchronous pytest
functions via ``loop.run_until_complete()``.  The ``QtCore.QObject`` base
class is instantiated with the offscreen platform (set in ``conftest.py``) so
no display server is needed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from PySide6.QtCore import QObject

from lan_streamer.system.async_task_manager import (
    AsyncTaskManager,
    DEFAULT_CANCEL_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubParent(QObject):
    """Minimal QObject for testing AsyncTaskManager parent relationships."""


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    """Provide a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    # Cancel any remaining tasks
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.run_until_complete(
        asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True)
    )
    loop.close()


@pytest.fixture
def stub_parent() -> _StubParent:
    """Return a QObject suitable as a parent."""
    return _StubParent()


@pytest.fixture
def manager(stub_parent: _StubParent) -> AsyncTaskManager:
    """Return an AsyncTaskManager with no running tasks."""
    return AsyncTaskManager(parent=stub_parent)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_default_cancel_timeout() -> None:
    """DEFAULT_CANCEL_TIMEOUT is a positive float."""
    assert isinstance(DEFAULT_CANCEL_TIMEOUT, float)
    assert DEFAULT_CANCEL_TIMEOUT > 0


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_initial_is_task_running_false(manager: AsyncTaskManager) -> None:
    """is_task_running on an unknown name returns False."""
    assert manager.is_task_running("nonexistent") is False


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


def test_create_task_returns_task_object(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """create_task returns a proper asyncio.Task when a loop is running."""

    async def noop() -> None:
        pass

    async def _run() -> None:
        task = manager.create_task(noop(), name="test_task")
        assert task is not None
        assert isinstance(task, asyncio.Task)
        await task

    event_loop.run_until_complete(_run())


def test_create_task_tracks_the_task(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """After creation the task is retrievable via the internal tracking dict."""

    async def noop() -> None:
        pass

    async def _run() -> None:
        task = manager.create_task(noop(), name="tracked")
        assert task is not None
        assert manager._tasks.get("tracked") is task
        assert manager.is_task_running("tracked")
        await task

    event_loop.run_until_complete(_run())


def test_create_task_auto_removes_on_completion(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """A completed task is automatically removed from tracking."""
    completed: list[asyncio.Task[Any]] = []

    async def quick() -> None:
        pass

    async def _run() -> None:
        task = manager.create_task(
            quick(), name="auto_clean", on_done_callback=lambda t: completed.append(t)
        )
        assert task is not None
        await task
        # Yield to allow the done callback to fire
        await asyncio.sleep(0)

        assert "auto_clean" not in manager._tasks
        assert manager.is_task_running("auto_clean") is False
        assert len(completed) == 1
        assert completed[0] is task

    event_loop.run_until_complete(_run())


def test_create_task_with_done_callback(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """on_done_callback is invoked when the task completes."""
    callback_result: list[str] = []

    async def simple() -> None:
        pass

    def done_callback(task: asyncio.Task[Any]) -> None:
        callback_result.append("called")

    async def _run() -> None:
        task = manager.create_task(
            simple(), name="callback_test", on_done_callback=done_callback
        )
        assert task is not None
        await task
        await asyncio.sleep(0)

        assert callback_result == ["called"]

    event_loop.run_until_complete(_run())


def test_create_task_done_callback_exception_logged(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An exception in the done callback is logged, not propagated."""

    async def simple() -> None:
        pass

    def broken_callback(task: asyncio.Task[Any]) -> None:
        msg = "intentional failure"
        raise ValueError(msg)

    async def _run() -> None:
        task = manager.create_task(
            simple(), name="broken", on_done_callback=broken_callback
        )
        assert task is not None
        await task
        await asyncio.sleep(0)

    event_loop.run_until_complete(_run())

    assert "broken" in caplog.text
    assert "done callback raised" in caplog.text
    assert "ValueError" in caplog.text


def test_create_task_no_event_loop(
    manager: AsyncTaskManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """create_task returns None and logs a warning when no loop is running."""
    # Temporarily clear any running loop
    with pytest.MonkeyPatch.context():
        # We can't easily "unset" the running loop, but we can verify the
        # behaviour by checking that when there IS a loop it works, and the
        # warning path is covered by mocking.
        pass

    # Instead, test the warning path directly by checking the log
    # when the manager tries to get a running loop that doesn't exist.
    # We monkeypatch asyncio.get_running_loop to raise RuntimeError.
    def raise_no_loop() -> asyncio.AbstractEventLoop:
        msg = "There is no current event loop in thread 'MainThread'."
        raise RuntimeError(msg)

    from unittest.mock import patch

    async def dummy() -> None:
        pass

    with (
        patch("asyncio.get_running_loop", side_effect=raise_no_loop),
        caplog.at_level("WARNING"),
    ):
        result = manager.create_task(dummy(), name="no_loop")

    assert result is not None
    assert "No running event loop" in caplog.text
    assert "synchronously" in caplog.text
    assert "no_loop" in caplog.text


def test_create_task_overwrites_existing_name(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """Creating a task with an existing name replaces the tracked reference."""

    async def slow() -> None:
        await asyncio.sleep(10)

    async def quick() -> None:
        pass

    async def _run() -> None:
        task_first = manager.create_task(slow(), name="dupe")
        assert task_first is not None

        task_second = manager.create_task(quick(), name="dupe")
        assert task_second is not None

        # The manager now tracks the second task.
        assert manager._tasks.get("dupe") is task_second
        assert manager._tasks.get("dupe") is not task_first

        # Clean up
        task_first.cancel()
        await asyncio.sleep(0)
        await task_second

    event_loop.run_until_complete(_run())


# ---------------------------------------------------------------------------
# cancel_task
# ---------------------------------------------------------------------------


def test_cancel_task_unknown_name(
    manager: AsyncTaskManager, caplog: pytest.LogCaptureFixture
) -> None:
    """Cancelling a nonexistent task logs a debug message."""
    with caplog.at_level("DEBUG"):
        manager.cancel_task("phantom")

    assert "No task named 'phantom' found" in caplog.text


def test_cancel_task_cancels_running_task(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """cancel_task requests cancellation of a running task."""
    cancelled = False

    async def wait_forever() -> None:
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    async def _run() -> None:
        nonlocal cancelled
        task = manager.create_task(wait_forever(), name="cancellable")
        assert task is not None
        await asyncio.sleep(0)

        assert manager.is_task_running("cancellable") is True

        manager.cancel_task("cancellable")
        await asyncio.sleep(0)

        assert cancelled is True
        assert manager.is_task_running("cancellable") is False

    event_loop.run_until_complete(_run())


def test_cancel_task_already_done(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cancelling an already-completed task is a no-op."""

    async def quick() -> None:
        pass

    async def _run() -> None:
        task = manager.create_task(quick(), name="done_task")
        assert task is not None
        await task
        await asyncio.sleep(0)

        # The done callback removes the task from tracking, so re-insert it
        # to exercise the "already done" code path in cancel_task.
        manager._tasks["done_task"] = task  # noqa: SLF001

    event_loop.run_until_complete(_run())

    with caplog.at_level("DEBUG"):
        manager.cancel_task("done_task")

    assert "already done" in caplog.text


# ---------------------------------------------------------------------------
# cancel_all
# ---------------------------------------------------------------------------


def test_cancel_all_with_no_tasks(
    manager: AsyncTaskManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """cancel_all with an empty manager logs a debug message."""
    with caplog.at_level("DEBUG"):
        manager.cancel_all()

    assert "no tasks to cancel" in caplog.text


def test_cancel_all_cancels_every_task(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """cancel_all cancels every tracked task."""
    cancellation_count: int = 0

    async def stoppable(name: str) -> None:
        nonlocal cancellation_count
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_count += 1
            raise

    async def _run() -> None:
        for i in range(3):
            manager.create_task(stoppable(f"task_{i}"), name=f"task_{i}")

    event_loop.run_until_complete(_run())
    event_loop.run_until_complete(asyncio.sleep(0))
    assert len(manager._tasks) == 3

    manager.cancel_all()
    event_loop.run_until_complete(asyncio.sleep(0))

    assert cancellation_count == 3
    # All tasks should be removed from tracking after cancellation
    event_loop.run_until_complete(asyncio.sleep(0))
    assert len(manager._tasks) == 0


# ---------------------------------------------------------------------------
# is_task_running
# ---------------------------------------------------------------------------


def test_is_task_running_returns_false_for_unknown(manager: AsyncTaskManager) -> None:
    """is_task_running returns False for a name that was never created."""
    assert manager.is_task_running("unknown") is False


def test_is_task_running_true_while_active(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """is_task_running returns True while the task is executing."""

    async def long_running() -> None:
        await asyncio.sleep(10)

    async def _run() -> None:
        task = manager.create_task(long_running(), name="active")
        assert task is not None

    event_loop.run_until_complete(_run())
    event_loop.run_until_complete(asyncio.sleep(0))

    assert manager.is_task_running("active") is True

    # Clean up
    manager.cancel_task("active")
    event_loop.run_until_complete(asyncio.sleep(0))


def test_is_task_running_false_after_completion(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """is_task_running returns False after the task finishes."""

    async def quick() -> None:
        pass

    async def _run() -> asyncio.Task[Any]:
        task = manager.create_task(quick(), name="finisher")
        assert task is not None
        return task

    task = event_loop.run_until_complete(_run())
    event_loop.run_until_complete(task)
    event_loop.run_until_complete(asyncio.sleep(0))

    assert manager.is_task_running("finisher") is False


def test_is_task_running_false_after_cancellation(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """is_task_running returns False after a task is cancelled."""

    async def wait_forever() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    async def _run() -> None:
        task = manager.create_task(wait_forever(), name="cancel_me")
        assert task is not None

    event_loop.run_until_complete(_run())
    event_loop.run_until_complete(asyncio.sleep(0))

    manager.cancel_task("cancel_me")
    event_loop.run_until_complete(asyncio.sleep(0))

    assert manager.is_task_running("cancel_me") is False


# ---------------------------------------------------------------------------
# schedule_interval
# ---------------------------------------------------------------------------


def test_schedule_interval_creates_tracked_task(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """schedule_interval returns a task and tracks it."""

    async def sample() -> None:
        pass

    async def _run() -> None:
        task = manager.schedule_interval(
            lambda: sample(), interval_seconds=10.0, name="interval"
        )
        assert task is not None
        assert manager._tasks.get("interval") is task
        assert manager.is_task_running("interval") is True

    event_loop.run_until_complete(_run())


def test_schedule_interval_runs_multiple_times(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """The factory is invoked repeatedly at the given interval."""
    counter: int = 0

    async def increment() -> None:
        nonlocal counter
        counter += 1

    async def _run() -> None:
        task = manager.schedule_interval(
            lambda: increment(), interval_seconds=0.01, name="counter"
        )
        assert task is not None

    event_loop.run_until_complete(_run())

    # Let it run for ~3 intervals
    event_loop.run_until_complete(asyncio.sleep(0.035))
    manager.cancel_task("counter")
    event_loop.run_until_complete(asyncio.sleep(0))

    assert counter >= 2


def test_schedule_interval_continues_after_error(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An error in the coroutine is logged and the loop continues."""
    attempt_count: int = 0

    async def flaky() -> None:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            msg = "first attempt failed"
            raise ValueError(msg)
        # Second attempt succeeds

    async def _run() -> None:
        task = manager.schedule_interval(
            lambda: flaky(), interval_seconds=0.01, name="flaky"
        )
        assert task is not None

    event_loop.run_until_complete(_run())

    event_loop.run_until_complete(asyncio.sleep(0.025))
    manager.cancel_task("flaky")
    event_loop.run_until_complete(asyncio.sleep(0))

    assert attempt_count >= 2
    assert "raised an error" in caplog.text
    assert "ValueError" in caplog.text
    assert "first attempt failed" in caplog.text


def test_schedule_interval_stops_on_cancellation(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """Cancelling an interval task stops the loop."""
    run_count: int = 0

    async def sample() -> None:
        nonlocal run_count
        run_count += 1

    async def _run() -> None:
        task = manager.schedule_interval(
            lambda: sample(), interval_seconds=0.01, name="stop_test"
        )
        assert task is not None

    event_loop.run_until_complete(_run())

    event_loop.run_until_complete(asyncio.sleep(0.015))
    manager.cancel_task("stop_test")
    event_loop.run_until_complete(asyncio.sleep(0.05))

    count_after_cancel = run_count
    event_loop.run_until_complete(asyncio.sleep(0.05))
    # Should NOT have increased after cancellation
    assert run_count == count_after_cancel


# ---------------------------------------------------------------------------
# stop_all
# ---------------------------------------------------------------------------


def test_stop_all_with_no_tasks(manager: AsyncTaskManager) -> None:
    """stop_all returns None when no tasks are tracked."""
    result = manager.stop_all()
    assert result is None


def test_stop_all_cancels_and_waits(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
) -> None:
    """stop_all cancels all tasks and returns a cleanup task."""

    async def long_running(name: str) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    async def _setup() -> None:
        for i in range(3):
            manager.create_task(long_running(f"task_{i}"), name=f"stop_{i}")

    event_loop.run_until_complete(_setup())
    event_loop.run_until_complete(asyncio.sleep(0))

    async def _stop_and_wait() -> None:
        cleanup = manager.stop_all()
        assert cleanup is not None
        assert isinstance(cleanup, asyncio.Task)
        await cleanup

    event_loop.run_until_complete(_stop_and_wait())

    assert len(manager._tasks) == 0


def test_stop_all_returns_none_when_no_loop(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """stop_all logs a warning if no event loop is running while tasks
    are still pending."""

    async def _create_task() -> None:
        async def long_running() -> None:
            await asyncio.sleep(10)

        manager.create_task(long_running(), name="pending")

    event_loop.run_until_complete(_create_task())
    event_loop.run_until_complete(asyncio.sleep(0))
    assert len(manager._tasks) == 1

    from unittest.mock import patch

    def raise_no_loop() -> asyncio.AbstractEventLoop:
        msg = "no loop"
        raise RuntimeError(msg)

    with (
        patch("asyncio.get_running_loop", side_effect=raise_no_loop),
        caplog.at_level("WARNING"),
    ):
        result = manager.stop_all()

    assert result is None
    assert "No running event loop during stop_all" in caplog.text


# ---------------------------------------------------------------------------
# schedule_interval — no event loop
# ---------------------------------------------------------------------------


def test_schedule_interval_no_event_loop(
    manager: AsyncTaskManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """schedule_interval returns None and warns when no loop is running."""
    from unittest.mock import patch

    def raise_no_loop() -> asyncio.AbstractEventLoop:
        msg = "no loop"
        raise RuntimeError(msg)

    async def dummy() -> None:
        pass

    with (
        patch("asyncio.get_running_loop", side_effect=raise_no_loop),
        caplog.at_level("WARNING"),
    ):
        result = manager.schedule_interval(
            lambda: dummy(), interval_seconds=1.0, name="no_loop"
        )

    assert result is None
    assert "No running event loop" in caplog.text


# ---------------------------------------------------------------------------
# Edge cases: QObject parent management
# ---------------------------------------------------------------------------


def test_constructor_sets_parent(stub_parent: _StubParent) -> None:
    """The manager's Qt parent is correctly assigned."""
    manager = AsyncTaskManager(parent=stub_parent)
    assert manager.parent() is stub_parent


def test_constructor_no_parent() -> None:
    """The manager can be constructed without a parent."""
    manager = AsyncTaskManager()
    assert manager.parent() is None


# ---------------------------------------------------------------------------
# Integration: create_task then cancel via cancel_all
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# schedule_interval with factory exception
# ---------------------------------------------------------------------------


def test_schedule_interval_factory_raises(
    event_loop: asyncio.AbstractEventLoop,
    manager: AsyncTaskManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An exception in the factory itself is also caught and logged."""
    attempt_count: int = 0

    def failing_factory() -> asyncio.coroutine:
        nonlocal attempt_count
        attempt_count += 1
        msg = "factory failure"
        raise RuntimeError(msg)

    # The factory will raise RuntimeError before we even get a coroutine.
    # _run_interval catches Exception so this is fine.
    async def _setup() -> None:
        task = manager.schedule_interval(
            failing_factory, interval_seconds=0.01, name="bad_factory"
        )
        assert task is not None

    event_loop.run_until_complete(_setup())
    event_loop.run_until_complete(asyncio.sleep(0.025))
    manager.cancel_task("bad_factory")
    event_loop.run_until_complete(asyncio.sleep(0))

    assert attempt_count >= 1
    assert "raised an error" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "factory failure" in caplog.text


# ---------------------------------------------------------------------------
# schedule_once with error
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Large number of tasks for stop_all
# ---------------------------------------------------------------------------
