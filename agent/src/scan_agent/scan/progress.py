"""Thread-safe progress/log broker bridging scan threads to SSE consumers."""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Iterator
from typing import Any

logger = logging.getLogger(__name__)

ProgressSubscriber = Callable[[dict[str, Any]], None]


class ProgressBroker:
    """Fan-out broker for scan progress and log events.

    Producers (the background scan thread) call :meth:`publish` /
    :meth:`publish_log`; consumers (FastAPI SSE handlers) register callbacks
    via :meth:`subscribe` or catch up on missed events with
    :meth:`pending_since`. Every event carries a monotonically increasing
    ``sequence`` number and the ``event`` name plus a ``payload`` dict.
    """

    def __init__(self, max_history: int = 1000) -> None:
        """Initialise the broker with a bounded event history."""
        self._lock = threading.Lock()
        self._subscribers: dict[int, ProgressSubscriber] = {}
        self._next_subscription_id = 0
        self._sequence = 0
        self._history: deque[dict[str, Any]] = deque(maxlen=max_history)

    def publish(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Publish an event to all subscribers and the bounded history.

        Returns the fully-formed event dict (including its sequence number).
        """
        with self._lock:
            self._sequence += 1
            message = {
                "sequence": self._sequence,
                "event": event,
                "payload": payload,
            }
            self._history.append(message)
            subscribers = list(self._subscribers.values())
        for subscriber in subscribers:
            try:
                subscriber(message)
            except Exception:
                logger.exception("Progress subscriber raised for event '%s'", event)
        return message

    def publish_log(self, line: str, level: str = "INFO") -> dict[str, Any]:
        """Publish a single log line as a ``scan.log`` event."""
        resolved_level = level
        if level == "INFO":
            upper_line = line.upper()
            if upper_line.startswith("ERROR:") or " ERROR " in upper_line:
                resolved_level = "ERROR"
            elif upper_line.startswith("WARNING:") or " WARNING " in upper_line:
                resolved_level = "WARNING"
            elif upper_line.startswith("DEBUG:") or " DEBUG " in upper_line:
                resolved_level = "DEBUG"
        return self.publish(
            "scan.log", {"line": line, "message": line, "level": resolved_level}
        )

    def subscribe(self, subscriber: ProgressSubscriber) -> int:
        """Register *subscriber* and return a subscription handle."""
        with self._lock:
            self._next_subscription_id += 1
            handle = self._next_subscription_id
            self._subscribers[handle] = subscriber
            return handle

    def unsubscribe(self, handle: int) -> None:
        """Remove the subscriber identified by *handle*."""
        with self._lock:
            self._subscribers.pop(handle, None)

    def pending_since(self, sequence: int) -> Iterator[dict[str, Any]]:
        """Yield events with a sequence number greater than *sequence*.

        Used by SSE handlers to catch up on events published while a client
        was disconnected.
        """
        with self._lock:
            snapshot = list(self._history)
        for message in snapshot:
            if message["sequence"] > sequence:
                yield message

    @property
    def latest_sequence(self) -> int:
        """Return the highest sequence number published so far."""
        with self._lock:
            return self._sequence

    def attach_to_logger(self, target_logger: logging.Logger) -> BrokerLogHandler:
        """Attach a BrokerLogHandler to target_logger if not already attached."""
        for existing_handler in target_logger.handlers:
            if (
                isinstance(existing_handler, BrokerLogHandler)
                and existing_handler._broker is self
            ):
                return existing_handler
        handler = BrokerLogHandler(self)
        target_logger.addHandler(handler)
        return handler


class BrokerLogHandler(logging.Handler):
    """Forward formatted log records from python logging to the progress broker."""

    def __init__(self, broker: ProgressBroker) -> None:
        """Initialise the handler at NOTSET level with a compact formatter."""
        super().__init__(level=logging.NOTSET)
        self._broker = broker
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Publish the formatted record as a scan.log event."""
        try:
            self._broker.publish_log(self.format(record), level=record.levelname)
        except ValueError, TypeError, RuntimeError:
            self.handleError(record)
