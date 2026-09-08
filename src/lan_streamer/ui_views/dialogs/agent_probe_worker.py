"""Background worker that probes a remote scan agent for health and library list.

The probe performs two blocking HTTP calls (agent health + library listing).
Moving the work off the Qt main thread keeps the settings dialog responsive
while the agent URL is being validated.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)

_AGENT_HEALTH_TIMEOUT: float = 4.0
_AGENT_LIBRARIES_TIMEOUT: float = 5.0


def probe_scan_agent(
    agent_url: str,
    health_timeout: float = _AGENT_HEALTH_TIMEOUT,
    libraries_timeout: float = _AGENT_LIBRARIES_TIMEOUT,
) -> dict[str, Any]:
    """Fetch agent health and library list.

    This function does all blocking network work and must run on a background
    thread.

    Arguments:
        agent_url: Base URL of the scan agent (e.g. ``http://192.168.1.50:8081``).
        health_timeout: Seconds before the health check times out.
        libraries_timeout: Seconds before the library listing times out.

    Returns:
        A dictionary with ``health`` and ``libraries`` keys.  ``health``
        contains the parsed health payload, or ``None`` if the request failed.
        ``libraries`` is a dict mapping library name → configuration.
    """
    from lan_streamer.services.scan_agent_client import (
        ScanAgentConnectionError,
        scan_agent_client,
    )

    health = None
    libraries: dict[str, Any] = {}
    try:
        health = scan_agent_client.check_agent_health(agent_url, timeout=health_timeout)
    except (
        ScanAgentConnectionError,
        requests.RequestException,
        ValueError,
        TypeError,
        OSError,
    ) as error_instance:
        logger.debug("Agent health probe failed for %s: %s", agent_url, error_instance)
    try:
        remote_library_list = scan_agent_client.fetch_agent_libraries(
            agent_url, timeout=libraries_timeout
        )
        libraries = {
            str(library_entry.get("name")): dict(library_entry)
            for library_entry in remote_library_list
            if isinstance(library_entry, dict)
        }
    except (
        ScanAgentConnectionError,
        requests.RequestException,
        ValueError,
        TypeError,
        OSError,
    ) as error_instance:
        logger.debug("Agent library list failed for %s: %s", agent_url, error_instance)
    return {"health": health, "libraries": libraries}


class AgentProbeWorker(QThread):
    """Non-blocking QThread that probes a scan agent.

    Signals
    -------
    probe_finished : Signal(str, dict)
        Emitted with ``(agent_url, result)`` when the probe completes.
    """

    probe_finished = Signal(str, dict)

    def __init__(self, agent_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.agent_url: str = agent_url

    def run(self) -> None:
        result = probe_scan_agent(self.agent_url)
        if not self.isInterruptionRequested():
            self.probe_finished.emit(self.agent_url, result)
