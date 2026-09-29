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


def test_fetch_library_items_success() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "Test Show": {
            "name": "Test Show",
            "seasons": {},
        }
    }

    with patch("requests.get", return_value=mock_response) as mock_get:
        items = client.fetch_library_items("http://127.0.0.1:8800", "lib-tv-01")
        assert "Test Show" in items
        mock_get.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/libraries/lib-tv-01/items",
            timeout=30.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )


def test_fetch_library_items_connection_error() -> None:
    client = ScanAgentClient()
    with (
        patch("requests.get", side_effect=requests.RequestException("boom")),
        pytest.raises(ScanAgentConnectionError, match="Could not fetch library items"),
    ):
        client.fetch_library_items("http://127.0.0.1:8800", "lib-tv-01")


def test_fetch_library_items_bad_status_code() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"

    with (
        patch("requests.get", return_value=mock_response),
        pytest.raises(ScanAgentConnectionError, match="returned HTTP 404"),
    ):
        client.fetch_library_items("http://127.0.0.1:8800", "lib-tv-01")


def test_fetch_library_items_invalid_payload() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = ["not", "a", "dict"]

    with (
        patch("requests.get", return_value=mock_response),
        pytest.raises(ScanAgentConnectionError, match="Expected dictionary"),
    ):
        client.fetch_library_items("http://127.0.0.1:8800", "lib-tv-01")


def test_download_poster_empty() -> None:
    client = ScanAgentClient()
    assert client.download_poster("http://127.0.0.1:8800", "") == ""
    assert client.download_poster("http://127.0.0.1:8800", "   ") == ""


def test_download_poster_local_file_exists(tmp_path) -> None:
    client = ScanAgentClient()
    local_image = tmp_path / "poster.jpg"
    local_image.write_bytes(b"existing_bytes")

    with patch("requests.get") as mock_get:
        result_path = client.download_poster(
            "http://127.0.0.1:8800", str(local_image), str(tmp_path)
        )
        assert result_path == str(local_image)
        mock_get.assert_not_called()


def test_download_poster_success(tmp_path) -> None:
    client = ScanAgentClient()
    destination_dir = tmp_path / "cache_images"
    destination_dir.mkdir()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"fake_image_bytes"

    with patch("requests.get", return_value=mock_response) as mock_get:
        result_path = client.download_poster(
            "http://127.0.0.1:8800",
            "/agent/cache/images/tmdb_series_42.jpg",
            local_destination_directory=str(destination_dir),
        )
        expected_saved_file = destination_dir / "tmdb_series_42.jpg"
        assert result_path == str(expected_saved_file)
        assert expected_saved_file.read_bytes() == b"fake_image_bytes"
        assert mock_get.called


def test_download_poster_failure(tmp_path) -> None:
    client = ScanAgentClient()
    destination_dir = tmp_path / "cache_images"
    destination_dir.mkdir()

    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("requests.get", return_value=mock_response):
        result_path = client.download_poster(
            "http://127.0.0.1:8800",
            "/agent/cache/images/missing.jpg",
            local_destination_directory=str(destination_dir),
        )
        assert result_path == ""


def test_fetch_library_items_quotes_identifier() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}

    with patch("requests.get", return_value=mock_response) as mock_get:
        client.fetch_library_items("http://127.0.0.1:8800", "Anime & Cartoons")
        mock_get.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/libraries/Anime%20%26%20Cartoons/items",
            timeout=30.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )


def test_fetch_agent_config_success() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "scheduled_scan_interval_hours": 4,
        "scheduled_scan_enabled": True,
        "filesystem_watching_enabled": True,
        "filesystem_watching_debounce_seconds": 30,
    }

    with patch("requests.get", return_value=mock_response) as mock_get:
        payload = client.fetch_agent_config("http://127.0.0.1:8800")
        assert payload["scheduled_scan_interval_hours"] == 4
        mock_get.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/config",
            timeout=10.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )


def test_update_agent_config_success() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"scheduled_scan_interval_hours": 8}

    with patch("requests.put", return_value=mock_response) as mock_put:
        result = client.update_agent_config(
            "http://127.0.0.1:8800", {"scheduled_scan_interval_hours": 8}
        )
        assert result["scheduled_scan_interval_hours"] == 8
        mock_put.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/config",
            json={"scheduled_scan_interval_hours": 8},
            timeout=10.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )


def test_fetch_scan_status_success() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"running": None, "last_job": {"id": 1}}

    with patch("requests.get", return_value=mock_response) as mock_get:
        status_payload = client.fetch_scan_status("http://127.0.0.1:8800")
        assert status_payload["running"] is None
        mock_get.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/scan/status",
            timeout=10.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )


def test_trigger_agent_scan_success() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": 12, "status": "pending"}

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = client.trigger_agent_scan(
            "http://127.0.0.1:8800",
            library_identifier="tv",
            pass_number=2,
            force_refresh=True,
        )
        assert result["id"] == 12
        mock_post.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/scan",
            json={
                "library_id": "tv",
                "pass_number": 2,
                "force_refresh": True,
            },
            timeout=10.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )


def test_cancel_agent_scan_success() -> None:
    client = ScanAgentClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "cancelled"}

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = client.cancel_agent_scan("http://127.0.0.1:8800")
        assert result["status"] == "cancelled"
        mock_post.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/scan/cancel",
            timeout=10.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )


def test_create_and_delete_agent_library() -> None:
    client = ScanAgentClient()
    post_response = MagicMock()
    post_response.status_code = 200
    post_response.json.return_value = {
        "id": "anime",
        "name": "Anime",
        "media_type": "anime",
        "root_path": "/media/anime",
    }

    with patch("requests.post", return_value=post_response) as mock_post:
        create_result = client.create_agent_library(
            "http://127.0.0.1:8800",
            name="Anime",
            media_type="anime",
            root_path="/media/anime",
        )
        assert create_result["id"] == "anime"
        mock_post.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/libraries",
            json={
                "name": "Anime",
                "media_type": "anime",
                "root_path": "/media/anime",
            },
            timeout=10.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )

    delete_response = MagicMock()
    delete_response.status_code = 200
    delete_response.json.return_value = {"status": "deleted"}

    with patch("requests.delete", return_value=delete_response) as mock_delete:
        delete_result = client.delete_agent_library("http://127.0.0.1:8800", "anime")
        assert delete_result["status"] == "deleted"
        mock_delete.assert_called_once_with(
            "http://127.0.0.1:8800/api/v1/libraries/anime",
            timeout=10.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "LanStreamer-Desktop/1.0",
            },
        )
