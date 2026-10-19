"""Background worker that listens for Server-Sent Events from a remote scan agent.

Maintains a long-lived HTTP connection to the scan agent's ``/api/v1/events``
stream and publishes structured Qt signals whenever playback watch state,
metadata, or scanning status updates occur on the remote agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TYPE_CHECKING

import aiohttp
from PySide6.QtCore import QObject, Signal

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.services.scan_agent_client import normalize_agent_url

if TYPE_CHECKING:
    from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger(__name__)

_SOCK_CONNECT_TIMEOUT_SECONDS: float = 10.0
_SOCK_READ_TIMEOUT_SECONDS: float = 45.0
_MAX_RECONNECT_INTERVAL_SECONDS: float = 30.0
_RECONNECT_SLEEP_STEP_SECONDS: float = 0.2
_BACKOFF_JITTER_FACTOR_MINIMUM: float = 0.8
_BACKOFF_JITTER_FACTOR_MAXIMUM: float = 1.2


class AgentEventListenerWorker(AsyncWorkerBase):
    """Asynchronous worker listening to remote scan agent Server-Sent Events.

    The worker opens a long-lived SSE connection to ``/api/v1/events``. The
    first request uses the ``live=1`` handshake so the agent streams only new
    events instead of replaying its buffered history. Every subsequent
    reconnect sends a ``Last-Event-ID`` header derived from the last parsed
    ``id:`` field so missed events are resumed exactly once. Reconnection
    uses exponential backoff with jitter, capped at 30 seconds, and reset to
    the base interval after every successful connection. Socket connect and
    read timeouts detect half-open connections.

    Signals
    -------
    event_received : Signal(str, dict)
        Emitted for any SSE event received with event name and parsed payload.
    watch_updated : Signal(dict)
        Emitted when a ``watch.updated`` event is received from the agent.
    metadata_updated : Signal(dict)
        Emitted when a ``metadata.updated`` event is received from the agent.
    scan_finished : Signal(dict)
        Emitted when a ``scan.finished`` event is received from the agent.
    connection_status_changed : Signal(str, bool)
        Emitted with the agent URL and boolean connection status (True when connected,
        False when disconnected or reconnecting).
    """

    event_received = Signal(str, dict)
    watch_updated = Signal(dict)
    metadata_updated = Signal(dict)
    scan_finished = Signal(dict)
    connection_status_changed = Signal(str, bool)

    def __init__(
        self,
        agent_url: str,
        async_task_manager: AsyncTaskManager | None = None,
        parent: QObject | None = None,
        reconnect_interval_seconds: float = 3.0,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.agent_url: str = agent_url
        self.reconnect_interval_seconds: float = max(0.01, reconnect_interval_seconds)
        self._is_connected: bool | None = None
        self._last_sequence: int | None = None
        self._current_backoff_seconds: float = self.reconnect_interval_seconds

    def start(self) -> None:
        """Start the listener only when an asyncio loop is running.

        ``AsyncTaskManager.create_task`` falls back to running a coroutine
        synchronously when no loop exists. For this infinite SSE worker that
        fallback would block the caller forever, so refuse to start instead.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "Cannot start agent event listener for '%s': no running event loop.",
                self.agent_url,
            )
            return
        super().start()

    async def run_async(self) -> None:
        """Continuously stream SSE events with cooperative reconnection."""
        try:
            normalized_url = normalize_agent_url(self.agent_url)
        except ValueError as url_error:
            logger.warning(
                "Invalid agent URL '%s' for SSE event listener: %s",
                self.agent_url,
                url_error,
            )
            return

        events_endpoint = f"{normalized_url}/api/v1/events"
        logger.info(
            "Starting agent event listener worker for '%s' at %s",
            self.agent_url,
            events_endpoint,
        )

        while not self.isInterruptionRequested():
            try:
                await self._listen_stream(events_endpoint)
            except asyncio.CancelledError:
                logger.info("Agent event listener for '%s' cancelled", self.agent_url)
                break
            except (
                aiohttp.ClientError,
                OSError,
                TimeoutError,
                RuntimeError,
            ) as stream_error:
                if self.isInterruptionRequested():
                    break
                backoff_seconds = self._compute_backoff_delay()
                logger.warning(
                    "Agent event listener connection to '%s' failed: %s. Reconnecting in %.1fs...",
                    self.agent_url,
                    stream_error,
                    backoff_seconds,
                )
                self._update_connection_status(False)
                self._advance_backoff()
                await self._sleep_cooperatively(backoff_seconds)
            except Exception:
                if self.isInterruptionRequested():
                    break
                backoff_seconds = self._compute_backoff_delay()
                logger.exception(
                    "Unexpected error in agent event listener for '%s'",
                    self.agent_url,
                )
                self._update_connection_status(False)
                self._advance_backoff()
                await self._sleep_cooperatively(backoff_seconds)
            else:
                if self.isInterruptionRequested():
                    break
                # The server closed the stream cleanly; reconnect after a
                # short backoff (reset to base by the successful connection).
                self._update_connection_status(False)
                backoff_seconds = self._compute_backoff_delay()
                logger.info(
                    "Agent SSE event stream from '%s' closed. Reconnecting in %.1fs...",
                    self.agent_url,
                    backoff_seconds,
                )
                self._advance_backoff()
                await self._sleep_cooperatively(backoff_seconds)

        self._update_connection_status(False)
        logger.info("Agent event listener worker for '%s' terminated", self.agent_url)

    async def _listen_stream(self, events_endpoint: str) -> None:
        """Connect to the SSE stream and process incoming event frames."""
        client_timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=_SOCK_CONNECT_TIMEOUT_SECONDS,
            sock_read=_SOCK_READ_TIMEOUT_SECONDS,
        )
        request_headers = {
            "Accept": "text/event-stream",
            "User-Agent": "LanStreamer-Desktop/1.0",
        }
        if self._last_sequence is None:
            # Live-tail handshake: only stream events published after the
            # connection is established instead of replaying buffered history.
            request_url = f"{events_endpoint}?live=1"
        else:
            request_url = events_endpoint
            request_headers["Last-Event-ID"] = str(self._last_sequence)

        async with (
            aiohttp.ClientSession(timeout=client_timeout) as client_session,
            client_session.get(request_url, headers=request_headers) as response_stream,
        ):
            if response_stream.status != 200:
                raise aiohttp.ClientResponseError(
                    request_info=response_stream.request_info,
                    history=response_stream.history,
                    status=response_stream.status,
                    message=f"Agent returned HTTP {response_stream.status}",
                )

            self._reset_backoff()
            self._update_connection_status(True)
            logger.info(
                "Connected to agent SSE event stream at '%s' (resuming after sequence %s)",
                request_url,
                self._last_sequence,
            )

            current_event_name = "message"
            current_data_lines: list[str] = []
            current_sequence: int | None = None

            async for raw_line_bytes in response_stream.content:
                if self.isInterruptionRequested():
                    break

                decoded_line = raw_line_bytes.decode("utf-8", errors="replace").rstrip(
                    "\r\n"
                )

                if decoded_line.startswith(":"):
                    # SSE comment / heartbeat ping
                    continue

                if not decoded_line:
                    # Empty line marks end of an event frame. Commit the id
                    # only once the frame is complete so a connection dropped
                    # mid-frame resumes from the previous id and re-delivers
                    # the interrupted event instead of silently skipping it.
                    if current_data_lines:
                        data_string = "\n".join(current_data_lines)
                        self._dispatch_event(current_event_name, data_string)
                    if current_sequence is not None:
                        self._last_sequence = current_sequence
                    current_event_name = "message"
                    current_data_lines = []
                    current_sequence = None
                    continue

                if decoded_line.startswith("event:"):
                    current_event_name = decoded_line.split(":", 1)[1].strip()
                elif decoded_line.startswith("data:"):
                    data_content = decoded_line.split(":", 1)[1].strip()
                    current_data_lines.append(data_content)
                elif decoded_line.startswith("id:"):
                    current_sequence = self._parse_sequence(
                        decoded_line.split(":", 1)[1].strip()
                    )

    def _parse_sequence(self, raw_sequence: str) -> int | None:
        """Parse an SSE ``id:`` value, returning None for non-numeric ids."""
        try:
            return int(raw_sequence)
        except ValueError:
            logger.debug(
                "Ignoring non-numeric SSE id '%s' received from '%s'",
                raw_sequence,
                self.agent_url,
            )
            return None

    def _compute_backoff_delay(self) -> float:
        """Return the next reconnect delay scaled by a random jitter factor."""
        jitter_factor = random.uniform(
            _BACKOFF_JITTER_FACTOR_MINIMUM,
            _BACKOFF_JITTER_FACTOR_MAXIMUM,
        )
        return max(0.0, self._current_backoff_seconds * jitter_factor)

    def _advance_backoff(self) -> None:
        """Double the current backoff interval, capped at the maximum."""
        self._current_backoff_seconds = min(
            self._current_backoff_seconds * 2.0,
            _MAX_RECONNECT_INTERVAL_SECONDS,
        )

    def _reset_backoff(self) -> None:
        """Reset the backoff interval to the configured base value."""
        self._current_backoff_seconds = self.reconnect_interval_seconds

    async def _sleep_cooperatively(self, total_seconds: float) -> None:
        """Sleep for *total_seconds* in short steps, aborting on interruption."""
        elapsed_seconds = 0.0
        step_seconds = min(_RECONNECT_SLEEP_STEP_SECONDS, total_seconds)
        while (
            step_seconds > 0
            and elapsed_seconds < total_seconds
            and not self.isInterruptionRequested()
        ):
            await asyncio.sleep(step_seconds)
            elapsed_seconds += step_seconds

    def _dispatch_event(self, event_name: str, raw_data_string: str) -> None:
        """Parse JSON payload and emit targeted signals."""
        try:
            payload = json.loads(raw_data_string)
        except json.JSONDecodeError as decode_error:
            logger.debug(
                "Could not decode JSON payload for event '%s' from '%s': %s",
                event_name,
                self.agent_url,
                decode_error,
            )
            return

        if not isinstance(payload, dict):
            return

        logger.debug(
            "Agent '%s' dispatched event '%s': %s",
            self.agent_url,
            event_name,
            payload,
        )
        self.event_received.emit(event_name, payload)

        if event_name == "watch.updated":
            self.watch_updated.emit(payload)
        elif event_name == "metadata.updated":
            self.metadata_updated.emit(payload)
        elif event_name == "scan.finished":
            self.scan_finished.emit(payload)

    def _update_connection_status(self, is_connected: bool) -> None:
        """Update internal connection state and emit signal if changed."""
        if self._is_connected != is_connected:
            self._is_connected = is_connected
            self.connection_status_changed.emit(self.agent_url, is_connected)
