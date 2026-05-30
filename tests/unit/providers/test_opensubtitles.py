"""Tests for the OpenSubtitles client module (0% → ~95% coverage)."""

from unittest.mock import patch, MagicMock
from typing import Optional

from lan_streamer.providers.opensubtitles import OpenSubtitlesClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    api_key: str = "test_api_key",
    username: str = "user",
    password: str = "pass",
    token: Optional[str] = None,
) -> OpenSubtitlesClient:
    """Return a freshly instantiated client with config stubbed."""
    client = OpenSubtitlesClient()
    client.token = token
    return client


def _mock_config(
    api_key: str = "test_api_key",
    username: str = "user",
    password: str = "pass",
) -> MagicMock:
    mock = MagicMock()
    mock.opensubtitles_api_key = api_key
    mock.opensubtitles_username = username
    mock.opensubtitles_password = password
    return mock


# ---------------------------------------------------------------------------
# _get_headers
# ---------------------------------------------------------------------------


def test_get_headers_without_token() -> None:
    client = _make_client()
    with patch("lan_streamer.providers.opensubtitles.config", _mock_config()):
        headers = client._get_headers()

    assert headers["Api-Key"] == "test_api_key"
    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"


def test_get_headers_with_token() -> None:
    client = _make_client(token="my_jwt_token")
    with patch("lan_streamer.providers.opensubtitles.config", _mock_config()):
        headers = client._get_headers()

    assert headers["Authorization"] == "Bearer my_jwt_token"


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def test_login_missing_credentials_returns_false() -> None:
    client = _make_client()
    mock_cfg = _mock_config(username="", password="")
    with patch("lan_streamer.providers.opensubtitles.config", mock_cfg):
        result = client.login()

    assert result is False
    assert client.token is None


def test_login_missing_username_only() -> None:
    client = _make_client()
    mock_cfg = _mock_config(username="", password="secret")
    with patch("lan_streamer.providers.opensubtitles.config", mock_cfg):
        result = client.login()
    assert result is False


def test_login_success() -> None:
    client = _make_client()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "jwt_abc123"}

    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.post", return_value=mock_response) as mock_post,
    ):
        result = client.login()

    assert result is True
    assert client.token == "jwt_abc123"
    mock_post.assert_called_once()


def test_login_http_error_returns_false() -> None:
    client = _make_client()
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.post", return_value=mock_response),
    ):
        result = client.login()

    assert result is False
    assert client.token is None


def test_login_network_exception_returns_false() -> None:
    client = _make_client()
    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.post", side_effect=ConnectionError("Network failure")),
    ):
        result = client.login()

    assert result is False
    assert client.token is None


# ---------------------------------------------------------------------------
# search_subtitles
# ---------------------------------------------------------------------------


def test_search_subtitles_missing_api_key_returns_empty() -> None:
    client = _make_client()
    mock_cfg = _mock_config(api_key="")
    with patch("lan_streamer.providers.opensubtitles.config", mock_cfg):
        results = client.search_subtitles(query="The Matrix")

    assert results == []


def test_search_subtitles_by_tmdb_id_success() -> None:
    client = _make_client()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"id": "sub1"}, {"id": "sub2"}]}

    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.get", return_value=mock_response) as mock_get,
    ):
        results = client.search_subtitles(
            tmdb_id=603, season_number=1, episode_number=2
        )

    assert len(results) == 2
    assert results[0]["id"] == "sub1"
    # Check params were built correctly
    call_kwargs = mock_get.call_args
    assert call_kwargs.kwargs["params"]["tmdb_id"] == 603
    assert call_kwargs.kwargs["params"]["season_number"] == 1
    assert call_kwargs.kwargs["params"]["episode_number"] == 2


def test_search_subtitles_by_tmdb_id_no_season_episode() -> None:
    """tmdb_id present but season/episode omitted should not include those keys."""
    client = _make_client()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}

    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.get", return_value=mock_response) as mock_get,
    ):
        client.search_subtitles(tmdb_id=603)

    params = mock_get.call_args.kwargs["params"]
    assert "season_number" not in params
    assert "episode_number" not in params


def test_search_subtitles_by_query_success() -> None:
    client = _make_client()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"id": "sub99"}]}

    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.get", return_value=mock_response) as mock_get,
    ):
        results = client.search_subtitles(query="some movie")

    assert len(results) == 1
    params = mock_get.call_args.kwargs["params"]
    assert params["query"] == "some movie"


def test_search_subtitles_http_error_returns_empty() -> None:
    client = _make_client()
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.text = "Too Many Requests"

    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.get", return_value=mock_response),
    ):
        results = client.search_subtitles(query="test")

    assert results == []


def test_search_subtitles_network_exception_returns_empty() -> None:
    client = _make_client()
    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.get", side_effect=TimeoutError("timed out")),
    ):
        results = client.search_subtitles(query="test")

    assert results == []


# ---------------------------------------------------------------------------
# get_download_link
# ---------------------------------------------------------------------------


def test_get_download_link_already_authenticated() -> None:
    client = _make_client(token="existing_token")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"link": "https://cdn.example.com/sub.srt"}

    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.post", return_value=mock_response),
    ):
        link = client.get_download_link(file_id=98765)

    assert link == "https://cdn.example.com/sub.srt"


def test_get_download_link_triggers_login_when_no_token() -> None:
    """When no token present, get_download_link should call login first."""
    client = _make_client(token=None)

    login_response = MagicMock()
    login_response.status_code = 200
    login_response.json.return_value = {"token": "new_token"}

    download_response = MagicMock()
    download_response.status_code = 200
    download_response.json.return_value = {"link": "https://example.com/file.srt"}

    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.post", side_effect=[login_response, download_response]),
    ):
        link = client.get_download_link(file_id=111)

    assert link == "https://example.com/file.srt"
    assert client.token == "new_token"


def test_get_download_link_login_fails_returns_none() -> None:
    """If login fails and token is still None, returns None."""
    client = _make_client(token=None)

    with (
        patch(
            "lan_streamer.providers.opensubtitles.config",
            _mock_config(username="", password=""),
        ),
    ):
        link = client.get_download_link(file_id=222)

    assert link is None


def test_get_download_link_http_error_returns_none() -> None:
    client = _make_client(token="tok")
    mock_response = MagicMock()
    mock_response.status_code = 406
    mock_response.text = "Download quota exceeded"

    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.post", return_value=mock_response),
    ):
        link = client.get_download_link(file_id=333)

    assert link is None


def test_get_download_link_network_exception_returns_none() -> None:
    client = _make_client(token="tok")
    with (
        patch("lan_streamer.providers.opensubtitles.config", _mock_config()),
        patch("requests.post", side_effect=RuntimeError("network dead")),
    ):
        link = client.get_download_link(file_id=444)

    assert link is None


# ---------------------------------------------------------------------------
# download_subtitle
# ---------------------------------------------------------------------------


def test_download_subtitle_success() -> None:
    client = _make_client()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"

    with patch("requests.get", return_value=mock_response):
        content = client.download_subtitle("https://example.com/sub.srt")

    assert content == b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"


def test_download_subtitle_http_error_returns_none() -> None:
    client = _make_client()
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden"

    with patch("requests.get", return_value=mock_response):
        content = client.download_subtitle("https://example.com/sub.srt")

    assert content is None


def test_download_subtitle_network_exception_returns_none() -> None:
    client = _make_client()
    with patch("requests.get", side_effect=ConnectionError("dropped")):
        content = client.download_subtitle("https://example.com/sub.srt")

    assert content is None
