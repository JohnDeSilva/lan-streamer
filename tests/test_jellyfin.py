import pytest
import requests
from unittest.mock import MagicMock, patch
from lan_streamer.jellyfin import JellyfinClient
from lan_streamer.config import config


@pytest.fixture
def jf_client() -> None:
    with (
        patch.object(config, "jellyfin_url", "http://test-jf"),
        patch.object(config, "jellyfin_api_key", "test-key"),
    ):
        client = JellyfinClient()
        yield client


def test_jellyfin_is_configured(jf_client) -> None:
    assert jf_client.is_configured() is True


def test_jellyfin_not_configured() -> None:
    client = JellyfinClient()
    config.jellyfin_url = ""
    config.jellyfin_api_key = ""
    assert client.is_configured() is False
    assert client.get_current_user_id() is None
    # set_watched_status should just return silently
    client.set_watched_status("1", True)
    # fetch_watched_episodes should return empty sets
    assert client.fetch_watched_episodes() == (set(), set(), set())


def test_get_current_user_id(jf_client) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"Id": "user123"}]
    jf_client.session.get = MagicMock(return_value=mock_resp)

    assert jf_client.get_current_user_id() == "user123"

    # Second call should use cache
    jf_client.session.get.reset_mock()
    assert jf_client.get_current_user_id() == "user123"
    jf_client.session.get.assert_not_called()


def test_set_watched_status(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    jf_client.session.post = MagicMock()
    jf_client.session.delete = MagicMock()

    jf_client.set_watched_status("item123", True)
    jf_client.session.post.assert_called_once()

    jf_client.set_watched_status("item123", False)
    jf_client.session.delete.assert_called_once()


def test_set_watched_status_error(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    jf_client.session.post = MagicMock(side_effect=Exception("network error"))
    # Should not raise
    jf_client.set_watched_status("item123", True)


def test_fetch_watched_episodes(jf_client) -> None:
    jf_client._cached_user_id = "user123"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "Items": [
            {"Id": "ep1", "Path": "/movies/show/s01e01.mkv"},
            {"Id": "ep2", "Path": "/movies/show/s01e02.mkv"},
            {"Id": "ep3"},  # no Path — should be skipped
        ]
    }
    jf_client.session.get = MagicMock(return_value=mock_resp)

    ids, paths, names = jf_client.fetch_watched_episodes()
    assert paths == {"/movies/show/s01e01.mkv", "/movies/show/s01e02.mkv"}
    assert ids == {"ep1", "ep2", "ep3"}


def test_fetch_watched_episodes_pagination(jf_client) -> None:
    """Verify pagination: stops when fewer than limit items are returned."""
    jf_client._cached_user_id = "user123"

    # First page: 5000 items
    page1 = MagicMock()
    page1.json.return_value = {"Items": [{"Path": f"/ep{i}.mkv"} for i in range(5000)]}

    # Second page: 3 items (< 5000 → last page)
    page2 = MagicMock()
    page2.json.return_value = {"Items": [{"Path": "/ep_last.mkv"}]}

    jf_client.session.get = MagicMock(side_effect=[page1, page2])

    ids, paths, names = jf_client.fetch_watched_episodes()
    assert len(paths) == 5001
    assert jf_client.session.get.call_count == 2


def test_fetch_watched_episodes_error(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    jf_client.session.get = MagicMock(side_effect=Exception("network down"))

    ids, paths, names = jf_client.fetch_watched_episodes()
    assert paths == set()
    assert ids == set()
    assert names == set()


def test_jellyfin_error_handling(jf_client) -> None:
    jf_client.session.get = MagicMock(side_effect=Exception("Mocked error"))
    jf_client.session.post = MagicMock(side_effect=Exception("Mocked error"))

    assert jf_client.get_current_user_id() is None
    # Shouldn't raise
    jf_client._cached_user_id = "u1"
    jf_client.set_watched_status("1", True)


def test_jellyfin_validate_credentials(jf_client) -> None:

    with patch("socket.create_connection", MagicMock()):
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
        jf_client.session.get.side_effect = requests.exceptions.ConnectionError(
            "Failed"
        )
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


def test_validate_credentials_socket_failure(jf_client) -> None:
    with patch("socket.create_connection", side_effect=Exception("Connection error")):
        success, msg = jf_client.validate_credentials("http://bad", "key")
        assert success is False
        assert "System-level connection failed" in msg


def test_validate_credentials_401(jf_client) -> None:
    with patch("socket.create_connection"):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        from requests.exceptions import HTTPError

        mock_resp.raise_for_status.side_effect = HTTPError(response=mock_resp)
        jf_client.session.get = MagicMock(return_value=mock_resp)
        success, msg = jf_client.validate_credentials("http://bad", "key")
        assert success is False
        assert "401" in msg or "Unauthorized" in msg


def test_validate_credentials_ip(jf_client) -> None:
    with patch("socket.create_connection"):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        jf_client.session.get = MagicMock(return_value=mock_resp)

        success, _ = jf_client.validate_credentials("192.168.1.10:8096", "key")
        assert success is True
        assert jf_client.session.get.call_args[0][0] == "http://192.168.1.10:8096/Users"


def test_get_base_url_logic(jf_client) -> None:
    config.jellyfin_url = "jellyfin.local"
    assert jf_client._get_base_url() == "https://jellyfin.local"

    config.jellyfin_url = "localhost"
    assert jf_client._get_base_url() == "http://localhost"

    config.jellyfin_url = "192.168.1.10"
    assert jf_client._get_base_url() == "http://192.168.1.10"

    config.jellyfin_url = ""
    assert jf_client._get_base_url() == ""


def test_get_current_user_id_https_retry(jf_client) -> None:
    with (
        patch.object(config, "jellyfin_url", "test.com"),
        patch.object(config, "jellyfin_api_key", "key"),
    ):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"Id": "u1"}]

        def side_effect(url, **kwargs) -> None:
            if url.startswith("https://"):
                raise requests.exceptions.ConnectionError("Force retry")
            return mock_resp

        jf_client.session.get = MagicMock(side_effect=side_effect)

        user_id = jf_client.get_current_user_id()
        assert user_id == "u1"
        assert jf_client.session.get.call_count == 2
        assert jf_client.session.get.call_args_list[0][0][0].startswith("https://")
        assert jf_client.session.get.call_args_list[1][0][0].startswith("http://")


def test_get_current_user_id_https_retry_failure(jf_client) -> None:
    with patch.object(config, "jellyfin_url", "test.com"):
        jf_client.session.get = MagicMock(side_effect=Exception("Both failed"))
        assert jf_client.get_current_user_id() is None


def test_get_headers(jf_client) -> None:
    headers = jf_client._get_headers()
    assert "Authorization" in headers
    assert "test-key" in headers["Authorization"]


def test_get_jellyfin_correlation_data(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "Items": [
            {
                "Id": "ep1",
                "Path": "/path1",
                "ProviderIds": {"Tmdb": "tmdb1"},
                "Name": "Ep1",
                "SeriesName": "Show",
            }
        ]
    }
    jf_client.session.get = MagicMock(return_value=mock_resp)

    data = jf_client.get_jellyfin_correlation_data()
    assert "/path1" in data["path_map"]
    assert "tmdb1" in data["tmdb_episode_map"]
    assert ("show", "ep1") in data["name_map"]
    assert "series_id_map" in data


def test_mark_as_played(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    jf_client.session.post = MagicMock()
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    jf_client.session.post.return_value = mock_resp

    success = jf_client.mark_as_played("item123")
    assert success is True
    jf_client.session.post.assert_called_once()


def test_unmark_as_played(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    jf_client.session.delete = MagicMock()
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    jf_client.session.delete.return_value = mock_resp

    success = jf_client.unmark_as_played("item123")
    assert success is True
    jf_client.session.delete.assert_called_once()


def test_unmark_as_played_error(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    jf_client.session.delete = MagicMock(side_effect=Exception("API Error"))
    assert jf_client.unmark_as_played("item123") is False


def test_search_series(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Items": [{"Id": "s1", "Name": "Series One"}]}
    jf_client.session.get = MagicMock(return_value=mock_resp)

    results = jf_client.search_series("Series One")
    assert len(results) == 1
    assert results[0]["Id"] == "s1"


def test_search_series_not_configured(jf_client) -> None:
    with patch.object(config, "jellyfin_url", ""):
        assert jf_client.search_series("Test") == []


def test_search_series_error(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    jf_client.session.get = MagicMock(side_effect=Exception("API Error"))
    assert jf_client.search_series("Test") == []


def test_get_series_episodes(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Items": [{"Id": "e1", "Path": "/p1"}]}
    jf_client.session.get = MagicMock(return_value=mock_resp)

    results = jf_client.get_series_episodes("s1")
    assert len(results) == 1
    assert results[0]["Id"] == "e1"


def test_get_series_episodes_error(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    jf_client.session.get = MagicMock(side_effect=Exception("API Error"))
    assert jf_client.get_series_episodes("s1") == []


def test_get_jellyfin_correlation_data_series_id_map(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "Items": [
            {
                "Id": "ep1",
                "Path": "/path1",
                "SeriesId": "s1",
                "Name": "Episode 1",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
            }
        ]
    }
    jf_client.session.get = MagicMock(return_value=mock_resp)

    data = jf_client.get_jellyfin_correlation_data()
    assert "s1" in data["series_id_map"]
    assert (1, 1) in data["series_id_map"]["s1"]["episodes"]
    assert data["series_id_map"]["s1"]["episodes"][(1, 1)] == "ep1"
    assert "episode 1" in data["series_id_map"]["s1"]["names"]
