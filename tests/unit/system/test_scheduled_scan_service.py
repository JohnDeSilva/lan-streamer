"""
Tests for ScheduledScanService — the periodic background scan service.

Uses a real asyncio event loop and a stub controller to verify scheduling,
locking, cancellation, and signal propagation.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal

from lan_streamer.system.async_task_manager import AsyncTaskManager
from lan_streamer.system.scheduled_scan_service import ScheduledScanService


# ---------------------------------------------------------------------------
# Stub controller
# ---------------------------------------------------------------------------


class _StubController(QObject):
    """Minimal controller stub with the interface ScheduledScanService needs."""

    scan_completed = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.task_manager = AsyncTaskManager(parent=self)
        self.trigger_scan_all = MagicMock()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    """Provide a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.run_until_complete(
        asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True)
    )
    loop.close()


@pytest.fixture
def controller() -> _StubController:
    """Return a fresh stub controller."""
    return _StubController()


@pytest.fixture
def service(
    event_loop: asyncio.AbstractEventLoop,
    controller: _StubController,
) -> ScheduledScanService:
    """Return a ScheduledScanService wired to a stub controller."""
    svc = ScheduledScanService(
        controller=controller,
        interval_seconds=0.05,
        parent=controller,
    )
    return svc


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    """Run a coroutine synchronously with the given event loop."""
    return event_loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConstruction:
    """Construction and property tests."""

    def test_constructor_sets_interval(self, controller: _StubController) -> None:
        svc = ScheduledScanService(controller=controller, interval_seconds=7200.0)
        assert svc.interval_seconds == 7200.0

    def test_scan_in_progress_defaults_false(
        self, service: ScheduledScanService
    ) -> None:
        assert service.scan_in_progress is False

    def test_interval_seconds_property(self, service: ScheduledScanService) -> None:
        service.interval_seconds = 1234.0
        assert service.interval_seconds == 1234.0


class TestStartStop:
    """Schedule and deschedule the periodic task."""

    def test_start_registers_task(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        async def run() -> None:
            task_manager = service._controller.task_manager
            assert task_manager.get_task("scheduled_scan") is None
            service.start()
            task = task_manager.get_task("scheduled_scan")
            assert task is not None
            assert task.get_name() == "scheduled_scan"
            service.stop()

        _run(run(), event_loop)

    def test_stop_cancels_task(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        async def run() -> None:
            service.start()
            tm = service._controller.task_manager
            task = tm.get_task("scheduled_scan")
            assert task is not None
            service.stop()
            # The task may still be in the dict in 'cancelling' state;
            # verify it is eventually marked cancelled.
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.CancelledError:
                pass
            assert task.cancelled()

        _run(run(), event_loop)

    def test_start_with_non_positive_interval_logs_warning(
        self,
        controller: _StubController,
        event_loop: asyncio.AbstractEventLoop,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        svc = ScheduledScanService(controller=controller, interval_seconds=0)

        async def run() -> None:
            with caplog.at_level("WARNING"):
                svc.start()
            assert "Scan interval must be positive" in caplog.text
            tm = controller.task_manager
            assert tm.get_task("scheduled_scan") is None

        _run(run(), event_loop)

    def test_stop_when_not_started(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        async def run() -> None:
            service.stop()

        _run(run(), event_loop)


class TestScanNow:
    """Manual scan_now triggering."""

    def test_scan_now_starts_scan(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        _run(service.scan_now(), event_loop)
        service._controller.trigger_scan_all.assert_called_once_with(
            force_refresh=False,
            run_pass1=True,
            run_pass2=True,
            chain_pass3=True,
            chain_cleanup=False,
        )
        assert service.scan_in_progress is True
        service._controller.scan_completed.emit()

    def test_scan_now_skipped_when_in_progress(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        service._scan_in_progress = True
        with caplog.at_level("WARNING"):
            _run(service.scan_now(), event_loop)
        assert "scan already in progress" in caplog.text
        service._controller.trigger_scan_all.assert_not_called()

    def test_scan_now_force_refresh(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        _run(service.scan_now(force_refresh=True), event_loop)
        service._controller.trigger_scan_all.assert_called_once_with(
            force_refresh=True,
            run_pass1=True,
            run_pass2=True,
            chain_pass3=True,
            chain_cleanup=False,
        )
        service._controller.scan_completed.emit()


class TestScheduledScan:
    """Tests for the periodic scheduled scan behaviour."""

    def test_scheduled_scan_triggers_scan_all(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        _run(service._run_scheduled_scan(), event_loop)
        service._controller.trigger_scan_all.assert_called_once_with(
            force_refresh=False,
            run_pass1=True,
            run_pass2=True,
            chain_pass3=True,
            chain_cleanup=False,
        )

    def test_scheduled_scan_sets_flag(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        assert service.scan_in_progress is False
        _run(service._run_scheduled_scan(), event_loop)
        assert service.scan_in_progress is True
        service._controller.scan_completed.emit()

    def test_scheduled_scan_skipped_when_in_progress(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        service._scan_in_progress = True
        with caplog.at_level("INFO"):
            _run(service._run_scheduled_scan(), event_loop)
        assert "Scheduled scan skipped" in caplog.text
        service._controller.trigger_scan_all.assert_not_called()


class TestSignalHandling:
    """Signal-based reset of the in-progress flag."""

    def test_on_scan_completed_resets_flag(
        self,
        service: ScheduledScanService,
    ) -> None:
        service._scan_in_progress = True
        service._controller.scan_completed.emit()
        assert service.scan_in_progress is False

    def test_on_scan_completed_emits_own_signal(
        self,
        service: ScheduledScanService,
    ) -> None:
        received = []

        def record() -> None:
            received.append(True)

        service.scan_completed.connect(record)
        service._controller.scan_completed.emit()
        assert len(received) == 1


class TestErrorHandling:
    """Error handling when trigger_scan_all raises."""

    def test_scan_now_error_resets_flag(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        service._controller.trigger_scan_all.side_effect = RuntimeError("boom")
        _run(service.scan_now(), event_loop)
        assert service.scan_in_progress is False

    def test_scan_now_error_emits_scan_error(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        service._controller.trigger_scan_all.side_effect = RuntimeError("boom")
        received = []

        def record(message: str) -> None:
            received.append(message)

        service.scan_error.connect(record)
        _run(service.scan_now(), event_loop)
        assert len(received) == 1
        assert "boom" in received[0]

    def test_scheduled_scan_error_resets_flag(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        service._controller.trigger_scan_all.side_effect = RuntimeError("boom")
        _run(service._run_scheduled_scan(), event_loop)
        assert service.scan_in_progress is False

    def test_scheduled_scan_error_emits_scan_error(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
    ) -> None:
        service._controller.trigger_scan_all.side_effect = RuntimeError("boom")
        received = []

        def record(message: str) -> None:
            received.append(message)

        service.scan_error.connect(record)
        _run(service._run_scheduled_scan(), event_loop)
        assert len(received) == 1


class TestFullCycle:
    """Integration-style cycle tests."""

    def test_start_runs_periodic_scan(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
        controller: _StubController,
    ) -> None:
        controller.trigger_scan_all.reset_mock()

        async def run() -> None:
            service.start()
            assert controller.task_manager.get_task("scheduled_scan") is not None
            await asyncio.sleep(0.1)

        _run(run(), event_loop)

        controller.trigger_scan_all.assert_called()

        async def cleanup() -> None:
            service.stop()
            controller.scan_completed.emit()

        _run(cleanup(), event_loop)

    def test_periodic_scan_does_not_overlap(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
        controller: _StubController,
    ) -> None:
        async def run() -> None:
            service.start()
            await asyncio.sleep(0.1)
            # scan is still in progress (signal not emitted)
            await asyncio.sleep(0.1)

        _run(run(), event_loop)

        controller.trigger_scan_all.assert_called_once()
        service._scan_in_progress = False
        service.stop()

    def test_multiple_scan_now_respects_lock(
        self,
        event_loop: asyncio.AbstractEventLoop,
        service: ScheduledScanService,
        controller: _StubController,
    ) -> None:
        controller.trigger_scan_all.reset_mock()
        _run(service.scan_now(), event_loop)
        _run(service.scan_now(), event_loop)
        controller.trigger_scan_all.assert_called_once()
        controller.scan_completed.emit()
