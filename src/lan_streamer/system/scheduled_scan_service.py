"""
Background scheduled scan service for periodic library scanning.

Provides :class:`ScheduledScanService`, a :class:`QObject` that uses
:class:`AsyncTaskManager` to periodically trigger full library scans
on a configurable interval.  A simple flag prevents concurrent scans.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class ScheduledScanService(QObject):
    """Periodically triggers a full multi-library scan on a configurable interval.

    Connects to the controller's ``scan_completed`` signal to learn when a
    scan finishes so it can reset the in-progress flag.  Scans are skipped
    if a previous scan is still running.

    Signals
    -------
    scan_started:
        Emitted when a scheduled or ad-hoc scan begins.
    scan_completed:
        Emitted when a scan finishes (successfully or not).
    scan_error:
        Emitted when starting a scan raises an unexpected exception.
    """

    scan_started = Signal()
    scan_completed = Signal()
    scan_error = Signal(str)

    def __init__(
        self,
        controller: Any,
        interval_seconds: float = 3600.0,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._interval_seconds = interval_seconds
        self._scan_in_progress: bool = False

        self._controller.scan_completed.connect(self._on_scan_completed)

    def _on_scan_completed(self) -> None:
        """Reset the in-progress flag when any scan finishes."""
        self._scan_in_progress = False
        self.scan_completed.emit()

    @property
    def scan_in_progress(self) -> bool:
        """Whether a scan is currently running."""
        return self._scan_in_progress

    @property
    def interval_seconds(self) -> float:
        """The interval between scheduled scans, in seconds."""
        return self._interval_seconds

    @interval_seconds.setter
    def interval_seconds(self, value: float) -> None:
        self._interval_seconds = value

    def start(self) -> None:
        """Register the periodic scan task with AsyncTaskManager."""
        if self._interval_seconds <= 0:
            logger.warning(
                "Scan interval must be positive; not starting scheduled scans."
            )
            return

        self._controller.task_manager.schedule_interval(
            self._run_scheduled_scan,
            interval_seconds=self._interval_seconds,
            name="scheduled_scan",
        )
        logger.info(
            "ScheduledScanService started (interval=%ss).", self._interval_seconds
        )

    def stop(self) -> None:
        """Cancel the periodic scan task."""
        self._controller.task_manager.cancel_task("scheduled_scan")
        logger.info("ScheduledScanService stopped.")

    async def scan_now(self, force_refresh: bool = False) -> None:
        """Manually trigger an immediate scan."""
        if self._scan_in_progress:
            logger.warning("scan_now skipped: scan already in progress.")
            return

        self._scan_in_progress = True
        self.scan_started.emit()
        try:
            self._controller.trigger_scan_all(
                force_refresh=force_refresh,
                run_pass1=True,
                run_pass2=True,
                chain_pass3=True,
                chain_cleanup=False,
            )
        except Exception as error:
            self._scan_in_progress = False
            logger.exception("Failed to start ad-hoc scan: %s", error)
            self.scan_error.emit(str(error))

    async def _run_scheduled_scan(self) -> None:
        """Coroutine called by the periodic timer."""
        if self._scan_in_progress:
            logger.info("Scheduled scan skipped: previous scan still running.")
            return

        self._scan_in_progress = True
        self.scan_started.emit()
        try:
            self._controller.trigger_scan_all(
                force_refresh=False,
                run_pass1=True,
                run_pass2=True,
                chain_pass3=True,
                chain_cleanup=False,
            )
        except Exception as error:
            self._scan_in_progress = False
            logger.exception("Failed to start scheduled scan: %s", error)
            self.scan_error.emit(str(error))
