"""Client service for communicating with remote Scan Agents from the desktop."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

logger = logging.getLogger(__name__)


class ScanAgentConnectionError(Exception):
    """Raised when an error occurs communicating with a remote Scan Agent."""


def normalize_agent_url(agent_url: str) -> str:
    """Normalize agent URL by ensuring scheme and stripping trailing slash."""
    cleaned_url = agent_url.strip()
    if not cleaned_url:
        raise ValueError("Invalid agent URL: empty string")

    if not cleaned_url.startswith(("http://", "https://")):
        cleaned_url = f"http://{cleaned_url}"

    parsed = urlparse(cleaned_url)
    if not parsed.netloc:
        raise ValueError(f"Invalid agent URL: '{agent_url}'")

    return cleaned_url.rstrip("/")


class ScanAgentClient:
    """Synchronous HTTP client for interacting with remote Scan Agent endpoints."""

    def __init__(self, default_timeout: float = 10.0) -> None:
        self.default_timeout = default_timeout
        self._headers = {
            "Accept": "application/json",
            "User-Agent": "LanStreamer-Desktop/1.0",
        }

    def check_agent_health(
        self, agent_url: str, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Check whether the remote agent is reachable and healthy."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/health"

        try:
            response = requests.get(
                target_endpoint,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(f"Health check failed for scan agent '{agent_url}': {error}")
            raise ScanAgentConnectionError(
                f"Could not connect to scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code != 200:
            logger.warning(
                f"Scan agent '{agent_url}' health check returned HTTP {response.status_code}"
            )
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            return response.json()
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid JSON response from scan agent at '{agent_url}': {error}"
            ) from error

    def fetch_media_sources(
        self, agent_url: str, timeout: float = 10.0
    ) -> list[dict[str, Any]]:
        """Fetch all media sources registered with the specified remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/sources"

        try:
            response = requests.get(
                target_endpoint,
                headers=self._headers,
                timeout=timeout,
            )
            if response.status_code == 404:
                target_endpoint = f"{normalized_url}/api/v1/libraries"
                response = requests.get(
                    target_endpoint,
                    headers=self._headers,
                    timeout=timeout,
                )
        except requests.RequestException as error:
            logger.warning(
                f"Failed fetching media sources from scan agent '{agent_url}': {error}"
            )
            raise ScanAgentConnectionError(
                f"Could not fetch media sources from scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code != 200:
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
            if isinstance(payload, list):
                return payload
            raise ValueError("Expected list of media sources from agent")
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid media sources response from scan agent at '{agent_url}': {error}"
            ) from error

    def fetch_agent_libraries(
        self, agent_url: str, timeout: float = 10.0
    ) -> list[dict[str, Any]]:
        """Fetch all libraries registered with the specified remote scan agent (legacy alias)."""
        return self.fetch_media_sources(agent_url, timeout=timeout)

    def fetch_source_items(
        self,
        agent_url: str,
        source_identifier: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Fetch full media source scanner items dictionary from the remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        quoted_identifier = quote(str(source_identifier), safe="")
        target_endpoint = f"{normalized_url}/api/v1/sources/{quoted_identifier}/items"

        try:
            response = requests.get(
                target_endpoint,
                headers=self._headers,
                timeout=timeout,
            )
            if response.status_code == 404:
                target_endpoint = (
                    f"{normalized_url}/api/v1/libraries/{quoted_identifier}/items"
                )
                response = requests.get(
                    target_endpoint,
                    headers=self._headers,
                    timeout=timeout,
                )
        except requests.RequestException as error:
            logger.warning(
                f"Failed fetching source items from scan agent '{agent_url}': {error}"
            )
            raise ScanAgentConnectionError(
                f"Could not fetch source items from scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code != 200:
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ValueError("Expected dictionary of items from agent")
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid items response from scan agent at '{agent_url}': {error}"
            ) from error

    def fetch_library_items(
        self,
        agent_url: str,
        library_identifier: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Fetch full library scanner items dictionary from the remote scan agent (legacy alias)."""
        return self.fetch_source_items(agent_url, library_identifier, timeout=timeout)

    def download_poster(
        self,
        agent_url: str,
        remote_poster_path: str,
        local_destination_directory: str | None = None,
        timeout: float = 15.0,
    ) -> str:
        """Download a poster image from the remote scan agent into local cache.

        Args:
            agent_url: Base URL of the remote scan agent.
            remote_poster_path: File path or TMDB path on the remote agent.
            local_destination_directory: Optional local directory where the image
                should be saved. Defaults to ``config.cache_directory / 'images'``.
            timeout: Network request timeout in seconds.

        Returns:
            Absolute local file path string to the downloaded image, or existing
            local path, or empty string on failure.
        """
        cleaned_remote_path = remote_poster_path.strip()
        if not cleaned_remote_path:
            return ""

        # If already a valid local file on disk, preserve it
        local_candidate = Path(cleaned_remote_path)
        if local_candidate.is_file():
            return str(local_candidate)

        if local_destination_directory is not None:
            destination_folder = Path(local_destination_directory)
        else:
            from lan_streamer.system.config import config

            destination_folder = Path(config.cache_directory) / "images"

        destination_folder.mkdir(parents=True, exist_ok=True)
        filename = local_candidate.name or "poster.jpg"
        local_target_file = destination_folder / filename

        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = (
            f"{normalized_url}/api/v1/images/poster?path={quote(cleaned_remote_path)}"
        )

        try:
            response = requests.get(
                target_endpoint,
                headers=self._headers,
                timeout=timeout,
            )
            if response.status_code == 200 and response.content:
                local_target_file.write_bytes(response.content)
                logger.info(
                    "Downloaded remote poster from agent to '%s'", local_target_file
                )
                return str(local_target_file)
            logger.warning(
                "Failed downloading poster '%s' from agent '%s': HTTP %d",
                cleaned_remote_path,
                agent_url,
                response.status_code,
            )
        except (requests.RequestException, OSError) as error:
            logger.warning(
                "Could not download poster '%s' from agent '%s': %s",
                cleaned_remote_path,
                agent_url,
                error,
            )

        return ""

    def fetch_agent_config(
        self, agent_url: str, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Fetch the full agent configuration from the remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/config"

        try:
            response = requests.get(
                target_endpoint,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                "Failed fetching configuration from scan agent '%s': %s",
                agent_url,
                error,
            )
            raise ScanAgentConnectionError(
                f"Could not fetch configuration from scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code != 200:
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ValueError("Expected dictionary of configuration from agent")
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid configuration response from scan agent at '{agent_url}': {error}"
            ) from error

    def update_agent_config(
        self,
        agent_url: str,
        configuration_payload: dict[str, Any],
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Update configuration settings on the remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/config"

        try:
            response = requests.put(
                target_endpoint,
                json=configuration_payload,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                "Failed updating configuration on scan agent '%s': %s",
                agent_url,
                error,
            )
            raise ScanAgentConnectionError(
                f"Could not update configuration on scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code != 200:
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ValueError("Expected dictionary response from agent config update")
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid response from scan agent at '{agent_url}': {error}"
            ) from error

    def fetch_scan_status(
        self, agent_url: str, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Fetch current scan status and last completed job details from the agent."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/scan/status"

        try:
            response = requests.get(
                target_endpoint,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                "Failed fetching scan status from scan agent '%s': %s",
                agent_url,
                error,
            )
            raise ScanAgentConnectionError(
                f"Could not fetch scan status from scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code != 200:
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ValueError("Expected dictionary response from agent scan status")
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid scan status response from scan agent at '{agent_url}': {error}"
            ) from error

    def trigger_agent_scan(
        self,
        agent_url: str,
        library_identifier: str | None = None,
        pass_number: int = 0,
        force_refresh: bool = False,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Initiate a background scan on the remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/scan"
        request_body: dict[str, Any] = {
            "library_id": library_identifier,
            "pass_number": pass_number,
            "force_refresh": force_refresh,
        }

        try:
            response = requests.post(
                target_endpoint,
                json=request_body,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                "Failed triggering scan on scan agent '%s': %s", agent_url, error
            )
            raise ScanAgentConnectionError(
                f"Could not trigger scan on scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code not in (200, 201, 202):
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ValueError("Expected dictionary response from trigger scan")
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid response from scan agent at '{agent_url}': {error}"
            ) from error

    def cancel_agent_scan(
        self, agent_url: str, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Cancel a running scan on the remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/scan/cancel"

        try:
            response = requests.post(
                target_endpoint,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                "Failed cancelling scan on scan agent '%s': %s", agent_url, error
            )
            raise ScanAgentConnectionError(
                f"Could not cancel scan on scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code not in (200, 202):
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ValueError("Expected dictionary response from cancel scan")
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid response from scan agent at '{agent_url}': {error}"
            ) from error

    def create_agent_library(
        self,
        agent_url: str,
        name: str,
        media_type: str,
        root_path: str,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Register a new library on the remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/libraries"
        payload = {
            "name": name,
            "media_type": media_type,
            "root_path": root_path,
        }

        try:
            response = requests.post(
                target_endpoint,
                json=payload,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                "Failed creating library '%s' on agent '%s': %s",
                name,
                agent_url,
                error,
            )
            raise ScanAgentConnectionError(
                f"Could not create library on scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code not in (200, 201):
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            response_json = response.json()
            if isinstance(response_json, dict):
                return response_json
            raise ValueError("Expected dictionary response from create library")
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid response from scan agent at '{agent_url}': {error}"
            ) from error

    def delete_agent_library(
        self,
        agent_url: str,
        library_identifier: str,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Delete a library from the remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        quoted_identifier = quote(str(library_identifier), safe="")
        target_endpoint = f"{normalized_url}/api/v1/libraries/{quoted_identifier}"

        try:
            response = requests.delete(
                target_endpoint,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                "Failed deleting library '%s' from agent '%s': %s",
                library_identifier,
                agent_url,
                error,
            )
            raise ScanAgentConnectionError(
                f"Could not delete library from scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code not in (200, 204):
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            response_json = response.json()
            if isinstance(response_json, dict):
                return response_json
            return {"status": "deleted"}
        except ValueError:
            return {"status": "deleted"}

    def record_watch_event(
        self,
        agent_url: str,
        media_type: str = "episode",
        media_identifier: int | None = None,
        path: str | None = None,
        event: str = "complete",
        position_seconds: float | None = None,
        watched: bool | None = None,
        client_identifier: str = "desktop",
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Record a watch event or sync watch state to a remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/watch/events"
        payload: dict[str, Any] = {
            "media_type": media_type,
            "event": event,
            "client_id": client_identifier,
        }
        if media_identifier is not None:
            payload["media_id"] = media_identifier
        if path is not None:
            payload["path"] = path
        if position_seconds is not None:
            payload["position_seconds"] = position_seconds
        if watched is not None:
            payload["watched"] = watched

        try:
            response = requests.post(
                target_endpoint,
                json=payload,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                "Failed recording watch event on agent '%s': %s", agent_url, error
            )
            raise ScanAgentConnectionError(
                f"Could not record watch event on scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code not in (200, 201):
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            response_json = response.json()
            if isinstance(response_json, dict):
                return response_json
            return {"status": "recorded"}
        except ValueError:
            return {"status": "recorded"}

    def sync_watch_events(
        self,
        agent_url: str,
        events: list[dict[str, Any]],
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Bulk synchronize multiple watch events to a remote scan agent."""
        if not events:
            return {"status": "synced", "updated_count": 0}

        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/watch/sync"

        try:
            response = requests.post(
                target_endpoint,
                json=events,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                "Failed syncing watch events to agent '%s': %s", agent_url, error
            )
            raise ScanAgentConnectionError(
                f"Could not sync watch events to scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code != 200:
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            response_json = response.json()
            if isinstance(response_json, dict):
                return response_json
            return {"status": "synced"}
        except ValueError:
            return {"status": "synced"}

    def apply_manual_metadata_mappings(
        self,
        agent_url: str,
        episode_mappings: list[dict[str, Any]],
        series_identifier: int | None = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Apply manual episode metadata mappings to a remote scan agent."""
        if not episode_mappings:
            return {"status": "applied", "modified_count": 0}

        normalized_url = normalize_agent_url(agent_url)
        if series_identifier is not None:
            target_endpoint = (
                f"{normalized_url}/api/v1/services/metadata/series/"
                f"{series_identifier}/manual-map"
            )
        else:
            target_endpoint = (
                f"{normalized_url}/api/v1/services/metadata/episodes/manual-map"
            )

        payload = {"episode_mappings": episode_mappings}

        try:
            response = requests.post(
                target_endpoint,
                json=payload,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                "Failed applying metadata mappings to agent '%s': %s",
                agent_url,
                error,
            )
            raise ScanAgentConnectionError(
                f"Could not apply metadata mappings to scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code != 200:
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            response_json = response.json()
            if isinstance(response_json, dict):
                return response_json
            return {"status": "applied"}
        except ValueError:
            return {"status": "applied"}


scan_agent_client = ScanAgentClient()
