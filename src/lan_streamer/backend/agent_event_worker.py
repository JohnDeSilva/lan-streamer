"""Background worker that listens for Server-Sent Events from a remote scan agent.

Maintains a long-lived HTTP connection to the scan agent's ``/api/v1/events``
stream and publishes structured Qt signals whenever playback watch state,
metadata, or scanning status updates occur on the remote agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import aiohttp
from PySide6.QtCore import QObject, Signal

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.services.scan_agent_client import normalize_agent_url

if TYPE_CHECKING:
    from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger(__name__)


class AgentEventListenerWorker(AsyncWorkerBase):
    """Asynchronous worker listening to remote scan agent Server-Sent Events.

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
                logger.warning(
                    "Agent event listener connection to '%s' failed: %s. Reconnecting in %.1fs...",
                    self.agent_url,
                    stream_error,
                    self.reconnect_interval_seconds,
                )
                self._update_connection_status(False)

                # Cooperatively wait before reconnecting
                elapsed_sleep = 0.0
                step_interval = min(0.2, self.reconnect_interval_seconds)
                while (
                    elapsed_sleep < self.reconnect_interval_seconds
                    and not self.isInterruptionRequested()
                ):
                    await asyncio.sleep(step_interval)
                    elapsed_sleep += step_interval
            except Exception:
                if self.isInterruptionRequested():
                    break
                logger.exception(
                    "Unexpected error in agent event listener for '%s'",
                    self.agent_url,
                )
                self._update_connection_status(False)

        self._update_connection_status(False)
        logger.info("Agent event listener worker for '%s' terminated", self.agent_url)

    async def _listen_stream(self, events_endpoint: str) -> None:
        """Connect to the SSE stream and process incoming event frames."""
        client_timeout = aiohttp.ClientTimeout(total=None, sock_read=None)
        headers = {
            "Accept": "text/event-stream",
            "User-Agent": "LanStreamer-Desktop/1.0",
        }

        async with (
            aiohttp.ClientSession(timeout=client_timeout) as client_session,
            client_session.get(events_endpoint, headers=headers) as response_stream,
        ):
            if response_stream.status != 200:
                raise aiohttp.ClientResponseError(
                    request_info=response_stream.request_info,
                    history=response_stream.history,
                    status=response_stream.status,
                    message=f"Agent returned HTTP {response_stream.status}",
                )

            self._update_connection_status(True)
            logger.info(
                "Connected to agent SSE event stream at '%s'",
                events_endpoint,
            )

            current_event_name = "message"
            current_data_lines: list[str] = []

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
                    # Empty line marks end of an event frame
                    if current_data_lines:
                        data_string = "\n".join(current_data_lines)
                        self._dispatch_event(current_event_name, data_string)
                    current_event_name = "message"
                    current_data_lines = []
                    continue

                if decoded_line.startswith("event:"):
                    current_event_name = decoded_line.split(":", 1)[1].strip()
                elif decoded_line.startswith("data:"):
                    data_content = decoded_line.split(":", 1)[1].strip()
                    current_data_lines.append(data_content)

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
