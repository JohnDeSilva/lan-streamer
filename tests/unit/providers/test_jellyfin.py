import pytest
import requests
from unittest.mock import MagicMock, patch
from lan_streamer.providers.jellyfin import JellyfinClient


@pytest.fixture
def jf_client(mock_session) -> JellyfinClient:
    client = JellyfinClient(
        session=mock_session,
        jellyfin_url="http://test-jf",
        jellyfin_api_key="test-key",
    )
    return client


def test_jellyfin_is_configured(jf_client) -> None:
    assert jf_client.is_configured() is True


def test_jellyfin_not_configured() -> None:
    client = JellyfinClient(jellyfin_url="", jellyfin_api_key="")
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


def test_get_base_url_logic(jf_client) -> None:
    original_url = jf_client._jellyfin_url
    jf_client._jellyfin_url = "jellyfin.local"
    assert jf_client._get_base_url() == "https://jellyfin.local"

    jf_client._jellyfin_url = "localhost"
    assert jf_client._get_base_url() == "http://localhost"

    jf_client._jellyfin_url = "192.168.1.10"
    assert jf_client._get_base_url() == "http://192.168.1.10"

    jf_client._jellyfin_url = ""
    assert jf_client._get_base_url() == ""
    jf_client._jellyfin_url = original_url


def test_get_current_user_id_https_retry(mock_session) -> None:
    client = JellyfinClient(
        session=mock_session,
        jellyfin_url="test.com",
        jellyfin_api_key="key",
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"Id": "u1"}]

    def side_effect(url, **kwargs) -> None:
        if url.startswith("https://"):
            raise requests.exceptions.ConnectionError("Force retry")
        return mock_resp

    client.session.get = MagicMock(side_effect=side_effect)

    user_id = client.get_current_user_id()
    assert user_id == "u1"
    assert client.session.get.call_count == 2
    assert client.session.get.call_args_list[0][0][0].startswith("https://")
    assert client.session.get.call_args_list[1][0][0].startswith("http://")


def test_get_current_user_id_https_retry_failure(mock_session) -> None:
    client = JellyfinClient(
        session=mock_session,
        jellyfin_url="test.com",
        jellyfin_api_key="key",
    )
    client.session.get = MagicMock(side_effect=Exception("Both failed"))
    assert client.get_current_user_id() is None


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


def test_search_series(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Items": [{"Id": "s1", "Name": "Series One"}]}
    jf_client.session.get = MagicMock(return_value=mock_resp)

    results = jf_client.search_series("Series One")
    assert len(results) == 1
    assert results[0]["Id"] == "s1"


def test_search_series_not_configured(mock_session) -> None:
    client = JellyfinClient(
        session=mock_session,
        jellyfin_url="",
        jellyfin_api_key="",
    )
    assert client.search_series("Test") == []


def test_search_series_error(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    jf_client.session.get = MagicMock(side_effect=Exception("API Error"))
    assert jf_client.search_series("Test") == []


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


def test_search_movie(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Items": [{"Id": "m1", "Name": "Movie One"}]}
    jf_client.session.get = MagicMock(return_value=mock_resp)

    results = jf_client.search_movie("Movie One")
    assert len(results) == 1
    assert results[0]["Id"] == "m1"


def test_search_movie_not_configured(mock_session) -> None:
    client = JellyfinClient(
        session=mock_session,
        jellyfin_url="",
        jellyfin_api_key="",
    )
    assert client.search_movie("Test") == []


def test_search_movie_error(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    jf_client.session.get = MagicMock(side_effect=Exception("API Error"))
    assert jf_client.search_movie("Test") == []


def test_jellyfin_get_current_user_id_unconfigured(mock_session) -> None:
    client = JellyfinClient(
        session=mock_session,
        jellyfin_url="http://test",
        jellyfin_api_key="key",
    )
    client.session.get = MagicMock()
    client.session.get.return_value.json.return_value = []
    assert client.get_current_user_id() is None


def test_get_current_user_id_https_retry_error(mock_session) -> None:
    client = JellyfinClient(
        session=mock_session,
        jellyfin_url="test.com",
        jellyfin_api_key="key",
    )
    from requests.exceptions import ConnectionError

    client.session.get = MagicMock(
        side_effect=[ConnectionError("HTTPS fail"), Exception("HTTP fail")]
    )
    assert client.get_current_user_id() is None


def test_jellyfin_get_correlation_data_unconfigured(mock_session) -> None:
    client = JellyfinClient(
        session=mock_session,
        jellyfin_url="",
        jellyfin_api_key="",
    )
    assert client.get_jellyfin_correlation_data() == {}

    # 2. No user_id
    client.get_current_user_id = MagicMock(return_value=None)
    assert client.get_jellyfin_correlation_data() == {}


def test_jellyfin_correlation_data_pagination_and_exceptions(jf_client) -> None:
    jf_client._cached_user_id = "user123"

    # Mock 1st page: Episode/Movie search (5000 items)
    page1 = MagicMock()
    page1.json.return_value = {
        "Items": [
            {
                "Id": f"ep{i}",
                "Path": f"/path{i}",
                "SeriesId": "s1",
                "Name": f"Ep{i}",
                "ProviderIds": {"Tmdb": f"tmdb{i}"},
            }
            for i in range(5000)
        ]
    }

    # Mock 2nd page: Episode/Movie search (1 item)
    page2 = MagicMock()
    page2.json.return_value = {
        "Items": [
            {
                "Id": "ep_last",
                "Path": "/path_last",
                "SeriesId": "s1",
                "Name": "EpLast",
                "ProviderIds": {"Tmdb": "tmdb_last"},
            }
        ]
    }

    # Mock 3rd page: Series/Movie search (5000 items)
    page3 = MagicMock()
    page3.json.return_value = {
        "Items": [{"Id": "s1", "ProviderIds": {"Tmdb": "tmdb_series_1"}}] * 5000
    }

    # Mock 4th page: Series/Movie search (0 items)
    page4 = MagicMock()
    page4.json.return_value = {"Items": []}

    jf_client.session.get = MagicMock(side_effect=[page1, page2, page3, page4])

    data = jf_client.get_jellyfin_correlation_data()
    assert len(data["path_map"]) == 5001
    assert data["tmdb_series_map"]["tmdb_series_1"] == "s1"


def test_jellyfin_correlation_data_exceptions(jf_client) -> None:
    jf_client._cached_user_id = "user123"
    # Exception during Episode fetch
    jf_client.session.get = MagicMock(side_effect=Exception("Episode API down"))
    data = jf_client.get_jellyfin_correlation_data()
    assert data == {
        "path_map": {},
        "tmdb_episode_map": {},
        "tmdb_series_map": {},
        "name_map": {},
        "series_id_map": {},
    }


def test_jellyfin_played_status_edge_cases(jf_client, mock_session) -> None:
    # 1. Unconfigured
    unconfigured = JellyfinClient(
        session=mock_session,
        jellyfin_url="",
        jellyfin_api_key="",
    )
    unconfigured.set_watched_status("item1", True)  # Should return immediately

    # 2. No user_id
    jf_client.get_current_user_id = MagicMock(return_value=None)
    assert jf_client.search_series("Test") == []
    assert jf_client.search_movie("Test") == []
    jf_client.set_watched_status("item1", True)


def test_jellyfin_fetch_watched_episodes_edge_cases(jf_client) -> None:
    # No user_id
    jf_client.get_current_user_id = MagicMock(return_value=None)
    assert jf_client.fetch_watched_episodes() == (set(), set(), set())

    # Names list population
    jf_client.get_current_user_id = MagicMock(return_value="user123")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "Items": [
            {
                "Id": "ep1",
                "Path": "/path1",
                "SeriesName": "CoolShow",
                "Name": "EpisodeOne",
            }
        ]
    }
    jf_client.session.get = MagicMock(return_value=mock_resp)
    ids, paths, names = jf_client.fetch_watched_episodes()
    assert ("coolshow", "episodeone") in names


# ------------------------------------------------------------------
# Constructor fallback tests
# ------------------------------------------------------------------


def test_jellyfin_fallback_to_config_url() -> None:
    """When jellyfin_url is None, _effective_url reads from config."""
    with patch(
        "lan_streamer.providers.jellyfin.config.jellyfin_url", "http://fallback"
    ):
        with patch(
            "lan_streamer.providers.jellyfin.config.jellyfin_api_key", "fallback-key"
        ):
            client = JellyfinClient(jellyfin_url=None, jellyfin_api_key=None)
            assert client._effective_url == "http://fallback"
            assert client._effective_api_key == "fallback-key"
            assert client.is_configured() is True
