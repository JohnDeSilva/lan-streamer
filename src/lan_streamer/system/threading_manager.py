import logging
from typing import Callable, List, Optional, TypeVar

from PySide6.QtCore import QObject, QThread

logger = logging.getLogger(__name__)

W = TypeVar("W", bound=QThread)


class WorkerSlot(QObject):
    """
    Manages lifecycle of a single worker slot (one worker at a time).

    Provides start/stop/is_running semantics with proper signal management.
    Avoids bare QObject.disconnect() calls which are invalid in PySide6
    when no specific connection is given.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._instance: Optional[QThread] = None
        self._timeout_ms: int = 5000

    @property
    def is_running(self) -> bool:
        return self._instance is not None and self._instance.isRunning()

    @property
    def instance(self) -> Optional[QThread]:
        return self._instance

    def start(
        self,
        factory: Callable[[], W],
        **signal_slots: Optional[Callable],
    ) -> W:
        """
        Stop any existing worker, create a new one via *factory*, connect
        the given signal→slot mappings, and start the thread.

        Keyword arguments map **signal names** to **slots**, for example::

            slot.start(
                lambda: MyWorker(...),
                finished=self._on_finished,
                error=self._on_error,
            )

        Only signals that are provided as keyword arguments are connected.
        """
        self.stop()

        worker: W = factory()
        self._instance = worker

        for signal_name, slot in signal_slots.items():
            if slot is not None:
                signal = getattr(worker, signal_name, None)
                if signal is not None:
                    signal.connect(slot)

        worker.start()
        logger.debug(
            "WorkerSlot started %s (slot=%s)",
            worker.__class__.__name__,
            self._instance is not None,
        )
        return worker

    def stop(self) -> None:
        """Stop the current worker if one exists and it is still alive."""
        worker = self._instance
        if worker is None:
            return

        try:
            worker.requestInterruption()
            worker.quit()

            if not worker.wait(self._timeout_ms):
                logger.warning(
                    "WorkerSlot: %s did not finish within %d ms",
                    worker.__class__.__name__,
                    self._timeout_ms,
                )

            worker.deleteLater()
        except RuntimeError as error:
            logger.debug(
                "WorkerSlot: RuntimeError while stopping %s: %s",
                worker.__class__.__name__,
                error,
            )

        self._instance = None

    def start_if_not_running(
        self,
        factory: Callable[[], W],
        **signal_slots: Optional[Callable],
    ) -> Optional[W]:
        """
        Like :meth:`start` but returns ``None`` without creating a new worker
        when a worker is already running.
        """
        if self.is_running:
            logger.info(
                "WorkerSlot: %s already running, skipping.",
                self._instance.__class__.__name__ if self._instance else "unknown",
            )
            return None
        return self.start(factory, **signal_slots)


class WorkerManager(QObject):
    """
    Centralized manager for all background workers used by the application.
    Creates named :class:`WorkerSlot` instances for each distinct worker role.

    Usage from a controller or other QObject::

        self.worker_manager = WorkerManager(parent=self)
        self.worker_manager.scan.start(
            lambda: ScanWorker(...),
            finished=self._on_scan_finished,
            error=self._on_worker_error,
        )
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.scan: WorkerSlot = WorkerSlot(self)
        self.scan_all: WorkerSlot = WorkerSlot(self)
        self.cleanup: WorkerSlot = WorkerSlot(self)
        self.jellyfin_pull: WorkerSlot = WorkerSlot(self)
        self.jellyfin_push: WorkerSlot = WorkerSlot(self)
        self.file_property: WorkerSlot = WorkerSlot(self)
        self.subtitle_merge: WorkerSlot = WorkerSlot(self)
        self.metadata_embed: WorkerSlot = WorkerSlot(self)
        self.metadata_apply: WorkerSlot = WorkerSlot(self)
        self.refresh: WorkerSlot = WorkerSlot(self)
        self.scan_series: WorkerSlot = WorkerSlot(self)

    def stop_all(self) -> None:
        """Stop every managed worker. Useful during application shutdown."""
        logger.info("WorkerManager: stopping all workers.")
        for slot in self._slots():
            slot.stop()

    def _slots(self) -> List[WorkerSlot]:
        result: List[WorkerSlot] = []
        for attr_name in dir(self):
            attr = getattr(self, attr_name, None)
            if isinstance(attr, WorkerSlot):
                result.append(attr)
        return result
