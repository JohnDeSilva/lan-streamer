"""Client service for communicating with remote Scan Agents from the desktop."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

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


scan_agent_client = ScanAgentClient()
