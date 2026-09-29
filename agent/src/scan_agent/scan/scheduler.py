"""Scheduled background scan runner."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scan_agent.config import AgentConfig
    from scan_agent.scan.orchestrator import ScanOrchestrator

logger = logging.getLogger(__name__)


class ScanScheduler:
    """Periodically triggers library scans at a configured interval.

    Runs a lightweight background thread that sleeps until the next scheduled
    interval, then requests a scan from the :class:`ScanOrchestrator`.
    """

    def __init__(
        self,
        agent_config: AgentConfig,
        scan_orchestrator: ScanOrchestrator,
    ) -> None:
        self._agent_config = agent_config
        self._orchestrator = scan_orchestrator
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_scan_timestamp: float = time.monotonic()

    @property
    def is_running(self) -> bool:
        """Return True if the background scheduler thread is active."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def interval_seconds(self) -> float:
        """Return the configured scan interval converted to seconds."""
        interval_hours = max(1, self._agent_config.scheduled_scan_interval_hours)
        return float(interval_hours * 3600)

    def start(self) -> None:
        """Start the scheduler background thread if not already active."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._last_scan_timestamp = time.monotonic()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="scan-agent-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Scheduled scan runner started (interval: %d hours)",
            self._agent_config.scheduled_scan_interval_hours,
        )

    def stop(self) -> None:
        """Signal the background scheduler thread to exit and join it."""
        if not self.is_running or self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        self._thread = None
        logger.info("Scheduled scan runner stopped")

    def _trigger_scheduled_scan(self) -> None:
        """Trigger a full pass scan across all configured libraries if enabled."""
        if not self._agent_config.scheduled_scan_enabled:
            logger.debug(
                "Scheduled scan skipped because scheduled scanning is disabled"
            )
            return
        if not self._agent_config.libraries:
            logger.debug("Scheduled scan skipped because no libraries are configured")
            return

        logger.info("Triggering scheduled scan across all configured libraries")
        try:
            self._orchestrator.start_scan(
                library_identifier=None,
                pass_number=0,
                force_refresh=False,
            )
            logger.info("Scheduled scan successfully initiated")
        except RuntimeError as runtime_error:
            logger.info(
                "Scheduled scan skipped (already in progress): %s", runtime_error
            )
        except ValueError, OSError:
            logger.exception("Failed to start scheduled scan")

    def _run_loop(self) -> None:
        """Background loop sleeping in small increments until interval elapses."""
        while not self._stop_event.is_set():
            current_time = time.monotonic()
            interval = self.interval_seconds
            elapsed = current_time - self._last_scan_timestamp

            if elapsed >= interval:
                self._trigger_scheduled_scan()
                self._last_scan_timestamp = time.monotonic()

            self._stop_event.wait(timeout=1.0)
