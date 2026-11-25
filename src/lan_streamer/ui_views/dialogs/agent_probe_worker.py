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


def auto_detect_agent_mounts(
    agent_url: str,
    libraries: list[dict[str, Any]],
    max_depth: int = 5,
    existing_mappings: dict[str, str] | None = None,
) -> dict[str, str]:
    """Auto-detect local mount points for unmapped root paths reported by *agent_url*."""
    import os

    from lan_streamer.services.mount_discovery_service import (
        auto_detect_mount_mappings_for_items,
    )
    from lan_streamer.services.scan_agent_client import (
        ScanAgentConnectionError,
        scan_agent_client,
    )

    existing = existing_mappings or {}
    detected_mounts: dict[str, str] = {}
    for library_entry in libraries:
        if not isinstance(library_entry, dict):
            continue
        source_identifier = str(
            library_entry.get("id") or library_entry.get("name") or ""
        )
        if not source_identifier:
            continue
        root_paths: list[str] = []
        if library_entry.get("root_paths"):
            root_paths = [str(path) for path in library_entry["root_paths"] if path]
        elif library_entry.get("root_path"):
            root_paths = [str(library_entry["root_path"])]
        if not root_paths:
            continue

        unmapped_roots = [
            root
            for root in root_paths
            if not (existing.get(root) and os.path.isdir(existing[root]))
        ]
        if not unmapped_roots:
            continue

        library_type = str(
            library_entry.get("media_type") or library_entry.get("type") or "tv"
        )
        try:
            items_dictionary = scan_agent_client.fetch_source_items(
                agent_url, source_identifier, timeout=15.0
            )
        except (
            ScanAgentConnectionError,
            requests.RequestException,
            ValueError,
            TypeError,
            OSError,
        ) as error_instance:
            logger.debug(
                "Could not fetch items from %s (%s) for mount detection: %s",
                agent_url,
                source_identifier,
                error_instance,
            )
            continue

        detected_for_source = auto_detect_mount_mappings_for_items(
            remote_roots=unmapped_roots,
            items_dictionary=items_dictionary,
            library_type=library_type,
            existing_mappings=existing,
            max_depth=max_depth,
        )
        detected_mounts.update(detected_for_source)

    return detected_mounts


class AutoDetectMountsWorker(QThread):
    """Non-blocking QThread that auto-detects local network mounts for an agent.

    Signals
    -------
    mounts_detected : Signal(str, dict)
        Emitted with ``(agent_url, detected_mounts)`` when detection completes.
    """

    mounts_detected = Signal(str, dict)

    def __init__(
        self,
        agent_url: str,
        libraries: list[dict[str, Any]],
        max_depth: int = 5,
        existing_mappings: dict[str, str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.agent_url: str = agent_url
        self.libraries: list[dict[str, Any]] = list(libraries)
        self.max_depth: int = max_depth
        self.existing_mappings: dict[str, str] = dict(existing_mappings or {})

    def run(self) -> None:
        detected = auto_detect_agent_mounts(
            self.agent_url,
            self.libraries,
            max_depth=self.max_depth,
            existing_mappings=self.existing_mappings,
        )
        if not self.isInterruptionRequested():
            self.mounts_detected.emit(self.agent_url, detected)


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
