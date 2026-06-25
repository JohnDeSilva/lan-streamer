import logging
from typing import Any, Callable, Dict, Optional
from PySide6.QtCore import QObject, Signal, QThread

logger = logging.getLogger("lan_streamer.backend")


class GenericSearchWorker(QThread):
    """Runs an arbitrary callable in a background thread and emits its result.

    Signals:
        finished: Emitted with the callable's return value on success.
        error: Emitted with an error message string on failure.
    """

    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        target: Callable[..., Any],
        args: Optional[tuple] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        description: str = "search",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._target: Callable[..., Any] = target
        self._args: tuple = args or ()
        self._kwargs: Dict[str, Any] = kwargs or {}
        self._description: str = description

    def run(self) -> None:
        try:
            logger.info(
                f"GenericSearchWorker running {self._description} in background..."
            )
            result = self._target(*self._args, **self._kwargs)
            logger.info(
                f"GenericSearchWorker {self._description} completed successfully"
            )
            self.finished.emit(result)
        except Exception as exc:
            logger.exception(f"GenericSearchWorker {self._description} failed: {exc}")
            self.error.emit(str(exc))
