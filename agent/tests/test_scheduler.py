"""Unit tests for the scan scheduler."""

from __future__ import annotations

from unittest.mock import MagicMock

from scan_agent.scan.scheduler import ScanScheduler


def test_scheduler_initialization(agent_config) -> None:
    orchestrator = MagicMock()
    scheduler = ScanScheduler(agent_config, orchestrator)
    assert scheduler.is_running is False
    assert scheduler.interval_seconds == 4 * 3600


def test_scheduler_triggers_scan_on_tick(agent_config) -> None:
    orchestrator = MagicMock()
    agent_config.scheduled_scan_interval_hours = 1
    scheduler = ScanScheduler(agent_config, orchestrator)

    # Directly invoke tick
    scheduler._trigger_scheduled_scan()
    orchestrator.start_scan.assert_called_once_with(
        library_identifier=None,
        pass_number=0,
        force_refresh=False,
    )


def test_scheduler_skips_when_disabled(agent_config) -> None:
    orchestrator = MagicMock()
    agent_config.scheduled_scan_enabled = False
    scheduler = ScanScheduler(agent_config, orchestrator)

    scheduler._trigger_scheduled_scan()
    orchestrator.start_scan.assert_not_called()


def test_scheduler_handles_orchestrator_busy(agent_config) -> None:
    orchestrator = MagicMock()
    orchestrator.start_scan.side_effect = RuntimeError("A scan is already running")
    scheduler = ScanScheduler(agent_config, orchestrator)

    # Should not raise exception
    scheduler._trigger_scheduled_scan()
    orchestrator.start_scan.assert_called_once()


def test_scheduler_lifecycle_start_and_stop(agent_config) -> None:
    orchestrator = MagicMock()
    agent_config.scheduled_scan_interval_hours = 1
    scheduler = ScanScheduler(agent_config, orchestrator)

    scheduler.start()
    assert scheduler.is_running is True

    # Calling start again is idempotent
    scheduler.start()
    assert scheduler.is_running is True

    scheduler.stop()
    assert scheduler.is_running is False

    # Calling stop again is idempotent
    scheduler.stop()
    assert scheduler.is_running is False


def test_scheduler_busy_retry_window(agent_config) -> None:
    orchestrator = MagicMock()
    orchestrator.start_scan.side_effect = RuntimeError("A scan is already running")
    agent_config.scheduled_scan_interval_hours = 4
    scheduler = ScanScheduler(agent_config, orchestrator)

    # When trigger is called and orchestrator is busy, it should record that it's busy
    success = scheduler._trigger_scheduled_scan()
    assert success is False
