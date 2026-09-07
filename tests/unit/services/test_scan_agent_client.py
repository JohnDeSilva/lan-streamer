"""Unit tests for desktop client's ScanAgentClient service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from lan_streamer.services.scan_agent_client import (
    ScanAgentClient,
    ScanAgentConnectionError,
    normalize_agent_url,
)


def test_normalize_agent_url() -> None:
    assert normalize_agent_url("http://127.0.0.1:8800/") == "http://127.0.0.1:8800"
    assert normalize_agent_url("https://127.0.0.1:8800") == "https://127.0.0.1:8800"
    assert normalize_agent_url("127.0.0.1:8800") == "http://127.0.0.1:8800"
    assert (
        normalize_agent_url("   http://127.0.0.1:8800/   ") == "http://127.0.0.1:8800"
    )

    with pytest.raises(ValueError, match="Invalid agent URL"):
        normalize_agent_url("")


def test_check_agent_health_success() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "tmdb_configured": True,
        "libraries": 3,
    }

    with patch("requests.get", return_value=mock_response) as mock_get:
        health_payload = client.check_agent_health("http://127.0.0.1:8800")
        assert health_payload["status"] == "ok"
        assert health_payload["libraries"] == 3
        mock_get.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/health",
            timeout=5.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )


def test_check_agent_health_connection_error() -> None:
    client = ScanAgentClient()
    with (
        patch(
            "requests.get", side_effect=requests.RequestException("Connection refused")
        ),
        pytest.raises(
            ScanAgentConnectionError, match="Could not connect to scan agent"
        ),
    ):
        client.check_agent_health("http://127.0.0.1:8800")


def test_check_agent_health_bad_status_code() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    with (
        patch("requests.get", return_value=mock_response),
        pytest.raises(ScanAgentConnectionError, match="returned HTTP 500"),
    ):
        client.check_agent_health("http://127.0.0.1:8800")


def test_fetch_agent_libraries_success() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "id": "lib-tv-01",
            "name": "TV Shows",
            "media_type": "series",
            "root_path": "/media/tv",
            "enabled": True,
        }
    ]

    with patch("requests.get", return_value=mock_response) as mock_get:
        libraries_list = client.fetch_agent_libraries("http://127.0.0.1:8800")
        assert len(libraries_list) == 1
        assert libraries_list[0]["name"] == "TV Shows"
        assert libraries_list[0]["root_path"] == "/media/tv"
        mock_get.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/libraries",
            timeout=10.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )
