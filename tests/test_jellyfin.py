import pytest
from unittest.mock import MagicMock, patch
from lan_streamer.jellyfin import JellyfinClient
from lan_streamer.config import config


@pytest.fixture
def jf_client(monkeypatch):
    monkeypatch.setattr(config, "jellyfin_url", "http://test-jf")
    monkeypatch.setattr(config, "jellyfin_api_key", "test-key")
    client = JellyfinClient()
    return client


def test_jellyfin_is_configured(jf_client):
    assert jf_client.is_configured() is True


def test_jellyfin_not_configured():
    client = JellyfinClient()
    client.session = MagicMock()
    # Assuming config is empty from other tests, if not let's set it
    config.jellyfin_url = ""
    config.jellyfin_api_key = ""
    assert client.is_configured() is False
    assert client.search_series("Test") is None
    assert client.get_seasons("1") == []
    assert client.get_episodes("1", "1") == []
    assert client.download_image("1") == ""
    assert client.get_current_user_id() is None
    # set_watched_status should just return
    client.set_watched_status("1", True)


def test_get_current_user_id(jf_client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"Id": "user123"}]
    jf_client.session.get = MagicMock(return_value=mock_resp)

    assert jf_client.get_current_user_id() == "user123"

    # Second call should use cache
    jf_client.session.get.reset_mock()
    assert jf_client.get_current_user_id() == "user123"
    jf_client.session.get.assert_not_called()


def test_search_series(jf_client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Items": [{"Id": "series123", "Name": "Test Show"}]}
    jf_client.session.get = MagicMock(return_value=mock_resp)

    res = jf_client.search_series("Test Show")
    assert res["Id"] == "series123"


def test_get_seasons(jf_client):
    jf_client._cached_user_id = "user123"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Items": [{"Id": "s1", "Name": "Season 1"}]}
    jf_client.session.get = MagicMock(return_value=mock_resp)

    res = jf_client.get_seasons("series123")
    assert len(res) == 1
    assert res[0]["Id"] == "s1"


def test_get_episodes(jf_client):
    jf_client._cached_user_id = "user123"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Items": [{"Id": "ep1", "Name": "Episode 1"}]}
    jf_client.session.get = MagicMock(return_value=mock_resp)

    res = jf_client.get_episodes("series123", "s1")
    assert len(res) == 1
    assert res[0]["Id"] == "ep1"


def test_download_image(jf_client, tmp_path, monkeypatch):
    import lan_streamer.jellyfin

    monkeypatch.setattr(lan_streamer.jellyfin, "CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake-image-data"
    jf_client.session.get = MagicMock(return_value=mock_resp)

    path = jf_client.download_image("item123")
    assert path == str(tmp_path / "item123.jpg")
    assert (tmp_path / "item123.jpg").read_bytes() == b"fake-image-data"

    # Verify headers were included
    args, kwargs = jf_client.session.get.call_args
    assert "Authorization" in kwargs.get("headers", {})

    # Second call should return cached path without downloading
    jf_client.session.get.reset_mock()
    path2 = jf_client.download_image("item123")
    assert path2 == str(tmp_path / "item123.jpg")
    jf_client.session.get.assert_not_called()


def test_set_watched_status(jf_client):
    jf_client._cached_user_id = "user123"
    jf_client.session.post = MagicMock()
    jf_client.session.delete = MagicMock()

    jf_client.set_watched_status("item123", True)
    jf_client.session.post.assert_called_once()

    jf_client.set_watched_status("item123", False)
    jf_client.session.delete.assert_called_once()


def test_jellyfin_error_handling(jf_client):
    jf_client.session.get = MagicMock(side_effect=Exception("Mocked error"))
    jf_client.session.post = MagicMock(side_effect=Exception("Mocked error"))

    assert jf_client.get_current_user_id() is None
    assert jf_client.search_series("Test") is None
    assert jf_client.get_seasons("1") == []
    assert jf_client.get_episodes("1", "1") == []
    assert jf_client.download_image("1") == ""
    # Shouldn't raise
    jf_client._cached_user_id = "u1"
    jf_client.set_watched_status("1", True)


def test_jellyfin_validate_credentials(jf_client, monkeypatch):
    import requests

    # Success
    import socket

    monkeypatch.setattr(socket, "create_connection", MagicMock())
    jf_client.session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    jf_client.session.get.return_value = mock_resp
    success, msg = jf_client.validate_credentials("http://test", "key")
    assert success is True
    assert "successful" in msg

    # Empty inputs
    assert jf_client.validate_credentials("", "key")[0] is False
    assert jf_client.validate_credentials("http://test", "")[0] is False

    # Connection Error
    jf_client.session.get.side_effect = requests.exceptions.ConnectionError("Failed")
    success, msg = jf_client.validate_credentials("http://test", "key")
    assert success is False
    assert "HTTP connection failed" in msg

    # HTTP Error 401
    mock_err_resp = MagicMock()
    mock_err_resp.status_code = 401
    jf_client.session.get.side_effect = requests.exceptions.HTTPError(
        response=mock_err_resp
    )
    success, msg = jf_client.validate_credentials("http://test", "key")
    assert success is False
    assert "Unauthorized" in msg

    # Unexpected Error
    jf_client.session.get.side_effect = Exception("Boom")
    success, msg = jf_client.validate_credentials("http://test", "key")
    assert success is False
    assert "Unexpected error" in msg


def test_get_base_url_logic(jf_client):
    config.jellyfin_url = "jellyfin.local"
    assert jf_client._get_base_url() == "https://jellyfin.local"

    config.jellyfin_url = "localhost"
    assert jf_client._get_base_url() == "http://localhost"

    config.jellyfin_url = "192.168.1.10"
    assert jf_client._get_base_url() == "http://192.168.1.10"

    config.jellyfin_url = ""
    assert jf_client._get_base_url() == ""


def test_get_current_user_id_https_retry(jf_client, monkeypatch):
    import requests

    monkeypatch.setattr(
        config, "jellyfin_url", "test.com"
    )  # Will result in https://test.com
    monkeypatch.setattr(config, "jellyfin_api_key", "key")

    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"Id": "u1"}]

    def side_effect(url, **kwargs):
        if url.startswith("https://"):
            raise requests.exceptions.ConnectionError("Force retry")
        return mock_resp

    jf_client.session.get = MagicMock(side_effect=side_effect)

    user_id = jf_client.get_current_user_id()
    assert user_id == "u1"
    assert jf_client.session.get.call_count == 2
    assert jf_client.session.get.call_args_list[0][0][0].startswith("https://")
    assert jf_client.session.get.call_args_list[1][0][0].startswith("http://")


def test_clean_name(jf_client):
    assert jf_client._clean_name("The.Office.S01.720p") == "The Office"
    assert jf_client._clean_name("Breaking Bad (2008)") == "Breaking Bad"
    assert jf_client._clean_name("Show.Name.2024.1080p.HEVC") == "Show Name"
    assert jf_client._clean_name("Anime_Show_Dual-Audio") == "Anime Show"
    assert jf_client._clean_name("Test [2024] (4K)") == "Test"
    assert jf_client._clean_name("Series Name Season 2") == "Series Name"


def test_validate_credentials_failure(jf_client):
    # Mock socket connection error
    with patch("socket.create_connection", side_effect=Exception("Connection error")):
        success, msg = jf_client.validate_credentials("http://bad", "key")
        assert success is False
        assert "System-level connection failed" in msg

    # Mock 401
    with patch("socket.create_connection"):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        from requests.exceptions import HTTPError

        mock_resp.raise_for_status.side_effect = HTTPError(response=mock_resp)
        jf_client.session.get = MagicMock(return_value=mock_resp)
        success, msg = jf_client.validate_credentials("http://bad", "key")
        assert success is False
        assert "401" in msg or "Unauthorized" in msg


def test_get_headers_no_config(jf_client):
    from lan_streamer.config import config

    old_key = config.jellyfin_api_key
    config.jellyfin_api_key = ""
    try:
        headers = jf_client._get_headers()
        assert "X-Emby-Token" not in headers
    finally:
        config.jellyfin_api_key = old_key


def test_download_image_cached(jf_client, tmp_path):
    # Mock cache dir
    with patch("lan_streamer.jellyfin.CACHE_DIR", tmp_path):
        image_file = tmp_path / "test_id.jpg"
        image_file.write_text("dummy image data")

        # Should return existing path without network call
        jf_client.session.get = MagicMock()
        path = jf_client.download_image("test_id")
        assert path == str(image_file)
        jf_client.session.get.assert_not_called()


def test_search_series_strategies(jf_client):
    mock_resp_empty = MagicMock()
    mock_resp_empty.json.return_value = {"Items": []}
    mock_resp_empty.status_code = 200

    mock_resp_success = MagicMock()
    mock_resp_success.json.return_value = {
        "Items": [{"Id": "match123", "Name": "Star Trek: Discovery"}]
    }
    mock_resp_success.status_code = 200

    # Test Colon Strategy
    jf_client.session.get = MagicMock(side_effect=[mock_resp_empty, mock_resp_success])
    res = jf_client.search_series("Star Trek - Discovery")
    assert res["Id"] == "match123"
    assert jf_client.session.get.call_count == 2

    # Test Fuzzy Strategy
    mock_resp_fuzzy = MagicMock()
    mock_resp_fuzzy.json.return_value = {
        "Items": [{"Id": "fuzzy123", "Name": "The Office"}]
    }
    mock_resp_fuzzy.status_code = 200

    # The.Office.S01.720p has no hyphens, so Strategy 2 (Colon) is skipped.
    jf_client.session.get = MagicMock(side_effect=[mock_resp_empty, mock_resp_fuzzy])
    res = jf_client.search_series("The.Office.S01.720p")
    assert res["Id"] == "fuzzy123"
    assert jf_client.session.get.call_count == 2


def test_search_series_full(jf_client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "Items": [{"Id": "1", "Name": "Show A"}, {"Id": "2", "Name": "Show B"}]
    }
    mock_resp.status_code = 200
    jf_client.session.get = MagicMock(return_value=mock_resp)

    results = jf_client.search_series_full("Show")
    assert len(results) == 2
    assert results[0]["Name"] == "Show A"


def test_is_similar(jf_client):
    assert jf_client._is_similar("Marvel's She-Hulk", "She-Hulk") is True
    assert jf_client._is_similar("Marvel's She-Hulk", "Marvel's Daredevil") is False
    assert jf_client._is_similar("The Office", "The Office (US)") is True
    assert jf_client._is_similar("Breaking Bad", "Better Call Saul") is False


def test_search_series_fallback_similarity(jf_client):
    mock_resp_empty = MagicMock()
    mock_resp_empty.json.return_value = {"Items": []}
    mock_resp_empty.status_code = 200

    # Bad match (low similarity)
    mock_resp_bad = MagicMock()
    mock_resp_bad.json.return_value = {
        "Items": [{"Id": "bad", "Name": "Something Completely Different"}]
    }
    mock_resp_bad.status_code = 200

    # Good match
    mock_resp_good = MagicMock()
    mock_resp_good.json.return_value = {
        "Items": [{"Id": "good", "Name": "Matched Show"}]
    }
    mock_resp_good.status_code = 200

    # Strategy 1-3 fail, Strategy 4 returns bad match (should be rejected), Strategy 5 returns good match
    # Matched Show S01 Extra Noise has no hyphens, so Strategy 2 (Colon) is skipped.
    # Strategies called: 1 (Exact), 3 (Fuzzy), 4 (Two words), 5 (First word)
    jf_client.session.get = MagicMock(
        side_effect=[
            mock_resp_empty,
            mock_resp_empty,
            mock_resp_bad,
            mock_resp_good,
        ]
    )

    res = jf_client.search_series("Matched Show S01 Extra Noise")
    assert res["Id"] == "good"


def test_validate_credentials_ip(jf_client):
    with patch("socket.create_connection"):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        jf_client.session.get = MagicMock(return_value=mock_resp)

        # Test IP address
        success, _ = jf_client.validate_credentials("192.168.1.10:8096", "key")
        assert success is True
        assert jf_client.session.get.call_args[0][0] == "http://192.168.1.10:8096/Users"


def test_download_image_error(jf_client, tmp_path):
    with patch("lan_streamer.jellyfin.CACHE_DIR", tmp_path):
        jf_client.session.get = MagicMock(side_effect=Exception("Download failed"))
        path = jf_client.download_image("error_id")
        assert path == ""


def test_search_series_full_error(jf_client):
    jf_client.session.get = MagicMock(side_effect=Exception("Search failed"))
    results = jf_client.search_series_full("anything")
    assert results == []


def test_preload_library(jf_client):
    jf_client._cached_user_id = "user123"

    mock_resp_series = MagicMock()
    mock_resp_series.json.return_value = {
        "Items": [{"Id": "series1", "Name": "Cached Show"}]
    }
    mock_resp_series.status_code = 200

    mock_resp_empty = MagicMock()
    mock_resp_empty.json.return_value = {"Items": []}
    mock_resp_empty.status_code = 200

    # _fetch_all_items_paginated will call session.get until it returns < 5000 items.
    # It will make 1 call for Series, 1 for Season, 1 for Episode.
    jf_client.session.get = MagicMock(
        side_effect=[
            mock_resp_series,  # Series items (1 item, < 5000, breaks loop)
            mock_resp_empty,  # Season items (0 items, < 5000, breaks loop)
            mock_resp_empty,  # Episode items (0 items, < 5000, breaks loop)
        ]
    )

    jf_client.preload_library()

    assert jf_client._cache is not None
    assert len(jf_client._cache["series"]) == 1
    assert jf_client._cache["series"][0]["Name"] == "Cached Show"

    # Verify search uses cache
    jf_client.session.get.reset_mock()
    res = jf_client.search_series("Cached Show")
    assert res["Id"] == "series1"
    jf_client.session.get.assert_not_called()

    jf_client.clear_cache()
    assert jf_client._cache is None
