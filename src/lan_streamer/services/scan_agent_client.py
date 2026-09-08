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

    def fetch_agent_libraries(
        self, agent_url: str, timeout: float = 10.0
    ) -> list[dict[str, Any]]:
        """Fetch all libraries registered with the specified remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = f"{normalized_url}/api/v1/libraries"

        try:
            response = requests.get(
                target_endpoint,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                f"Failed fetching libraries from scan agent '{agent_url}': {error}"
            )
            raise ScanAgentConnectionError(
                f"Could not fetch libraries from scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code != 200:
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
            if isinstance(payload, list):
                return payload
            raise ValueError("Expected list of libraries from agent")
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid libraries response from scan agent at '{agent_url}': {error}"
            ) from error

    def fetch_library_items(
        self,
        agent_url: str,
        library_identifier: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Fetch full library scanner items dictionary from the remote scan agent."""
        normalized_url = normalize_agent_url(agent_url)
        target_endpoint = (
            f"{normalized_url}/api/v1/libraries/{library_identifier}/items"
        )

        try:
            response = requests.get(
                target_endpoint,
                headers=self._headers,
                timeout=timeout,
            )
        except requests.RequestException as error:
            logger.warning(
                f"Failed fetching library items from scan agent '{agent_url}': {error}"
            )
            raise ScanAgentConnectionError(
                f"Could not fetch library items from scan agent at '{agent_url}': {error}"
            ) from error

        if response.status_code != 200:
            raise ScanAgentConnectionError(
                f"Scan agent at '{agent_url}' returned HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ValueError("Expected dictionary of library items from agent")
        except ValueError as error:
            raise ScanAgentConnectionError(
                f"Invalid library items response from scan agent at '{agent_url}': {error}"
            ) from error

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


scan_agent_client = ScanAgentClient()
