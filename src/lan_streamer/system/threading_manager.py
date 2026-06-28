import logging
import traceback
from typing import Any, Callable, List, Optional

from PySide6.QtCore import QObject

logger = logging.getLogger(__name__)

AnyWorker = QObject


class WorkerSlot(QObject):
    """
    Manages lifecycle of a single async worker slot (one worker at a time).

    Supports async QObject workers (marked with ``_is_async_worker = True``,
    e.g. :class:`AsyncWorkerBase`).

    Provides start/stop/is_running semantics with proper signal management.
    Avoids bare ``QObject.disconnect()`` calls which are invalid in PySide6
    when no specific connection is given.

    Key design decisions:

    * **Cooperative stop**. Cancellation is delegated to ``AsyncTaskManager``.
    * **Guard on start**. If a worker is already running when ``start()``
      is called, a warning is logged (with stack trace) to help catch
      re-entrant callers.  The old worker is still stopped.
    * **``start_if_not_running``** for call sites that want to silently
      skip when a worker is active.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._instance: Optional[QObject] = None
        self._connected_signal_slots: List[tuple[Any, Callable]] = []

    @property
    def is_running(self) -> bool:
        if self._instance is None:
            return False
        if self._is_async(self._instance):
            return bool(getattr(self._instance, "is_running", False))
        return False

    @property
    def instance(self) -> Optional[AnyWorker]:
        return self._instance

    @staticmethod
    def _is_async(worker: QObject) -> bool:
        marker = getattr(worker, "_is_async_worker", False)
        return marker is True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        factory: Callable[[], AnyWorker],
        **signal_slots: Optional[Callable],
    ) -> AnyWorker:
        """
        Stop any existing worker, create a new one via *factory*, connect
        the given signal→slot mappings, and start the worker.

        Keyword arguments map **signal names** to **slots**, for example::

            slot.start(
                lambda: MyWorker(...),
                finished=self._on_finished,
                error=self._on_error,
            )

        Only signals that are provided as keyword arguments are connected.
        """
        if self.is_running:
            caller = "".join(traceback.format_stack(limit=4)[:-1])
            logger.warning(
                "WorkerSlot: replacing running %s with new worker. Call stack:\n%s",
                self._instance.__class__.__name__ if self._instance else "worker",
                caller,
            )

        self.stop()

        worker: AnyWorker = factory()
        self._instance = worker

        for signal_name, slot in signal_slots.items():
            if slot is not None:
                signal = getattr(worker, signal_name, None)
                if signal is not None:
                    signal.connect(slot)
                    self._connected_signal_slots.append((signal, slot))
                else:
                    logger.warning(
                        "WorkerSlot.start(): worker %s has no signal '%s' — slot not connected",
                        worker.__class__.__name__,
                        signal_name,
                    )

        start_method = getattr(worker, "start", None)
        if start_method is not None:
            start_method()
        logger.debug(
            "WorkerSlot started %s",
            worker.__class__.__name__,
        )
        return worker

    def start_if_not_running(
        self,
        factory: Callable[[], AnyWorker],
        **signal_slots: Optional[Callable],
    ) -> Optional[AnyWorker]:
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

    def stop(self) -> None:
        """
        Stop the current async worker if one exists.

        Delegates to ``worker.stop()`` (cooperative cancellation via
        ``AsyncTaskManager``).
        """
        worker = self._instance
        if worker is None:
            return

        try:
            self._disconnect_signal_slots()

            stop_method = getattr(worker, "stop", None)
            if stop_method is not None:
                stop_method()
            logger.debug(
                "WorkerSlot: async worker %s stopped.",
                worker.__class__.__name__,
            )
        except RuntimeError as error:
            if self._is_deleted_qobject_error(error):
                logger.debug(
                    "WorkerSlot: RuntimeError while stopping %s: %s",
                    worker.__class__.__name__,
                    error,
                )
            else:
                raise
        finally:
            self._instance = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _disconnect_signal_slots(self) -> None:
        """Disconnect controller callbacks from the current worker."""
        for signal, connected_slot in self._connected_signal_slots:
            try:
                signal.disconnect(connected_slot)
            except (RuntimeError, TypeError) as error:
                if not self._is_deleted_qobject_error(error):
                    logger.debug(
                        "WorkerSlot: signal disconnect failed for %s: %s",
                        connected_slot,
                        error,
                    )
        self._connected_signal_slots.clear()

    def _is_deleted_qobject_error(self, error: Exception) -> bool:
        message = str(error).lower()
        return (
            "c++ object" in message
            or "already deleted" in message
            or "internal c++ object" in message
            or "wrapped c/c++ object" in message
            or "destroyed" in message
        )

    def __repr__(self) -> str:
        cls = self._instance.__class__.__name__ if self._instance else "empty"
        return f"<WorkerSlot: {cls} running={self.is_running}>"


class WorkerManager(QObject):
    """
    Centralized manager for all background workers used by the application.
    Creates named :class:`WorkerSlot` instances for each distinct worker role.

    Usage from a controller or other QObject::

        self.worker_manager = WorkerManager(parent=self)
        self.worker_manager.scan.start(
            lambda: AsyncScanWorker(...),
            finished=self._on_scan_finished,
            error=self._on_worker_error,
        )
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.scan: WorkerSlot = WorkerSlot(self)
        self.scan_all: WorkerSlot = WorkerSlot(self)
        self.cleanup: WorkerSlot = WorkerSlot(self)
        self.cleanup_global: WorkerSlot = WorkerSlot(self)
        self.cleanup_scan_update: WorkerSlot = WorkerSlot(self)
        self.jellyfin_pull: WorkerSlot = WorkerSlot(self)
        self.jellyfin_push: WorkerSlot = WorkerSlot(self)
        self.file_property: WorkerSlot = WorkerSlot(self)
        self.subtitle_merge: WorkerSlot = WorkerSlot(self)
        self.metadata_embed: WorkerSlot = WorkerSlot(self)
        self.metadata_apply: WorkerSlot = WorkerSlot(self)
        self.refresh: WorkerSlot = WorkerSlot(self)
        self.scan_series: WorkerSlot = WorkerSlot(self)

        self._all_slots: List[WorkerSlot] = [
            self.scan,
            self.scan_all,
            self.cleanup,
            self.cleanup_global,
            self.cleanup_scan_update,
            self.jellyfin_pull,
            self.jellyfin_push,
            self.file_property,
            self.subtitle_merge,
            self.metadata_embed,
            self.metadata_apply,
            self.refresh,
            self.scan_series,
        ]

    def stop_all(self) -> None:
        """Stop every managed worker. Useful during application shutdown."""
        logger.info("WorkerManager: stopping all workers.")
        for slot in self._all_slots:
            slot.stop()

    def _slots(self) -> List[WorkerSlot]:
        return self._all_slots
