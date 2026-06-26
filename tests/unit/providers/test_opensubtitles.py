"""Tests for the OpenSubtitles client module utilizing dependency injection."""

import pytest
from unittest.mock import MagicMock, patch

from lan_streamer.providers.opensubtitles import (
    OpenSubtitlesClient,
    OPENSUBTITLES_API_BASE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config() -> MagicMock:
    """Fixture that returns a mock configuration."""
    cfg = MagicMock()
    cfg.opensubtitles_api_key = "test_api_key"
    cfg.opensubtitles_username = "user"
    cfg.opensubtitles_password = "pass"
    return cfg


@pytest.fixture
def client(mock_session, mock_config) -> OpenSubtitlesClient:
    """Fixture returning an OpenSubtitlesClient with injected mock session and patched config."""
    with patch("lan_streamer.providers.opensubtitles.config", mock_config):
        yield OpenSubtitlesClient(session=mock_session)


# ---------------------------------------------------------------------------
# _get_headers
# ---------------------------------------------------------------------------


def test_get_headers_without_token(client) -> None:
    headers = client._get_headers()
    assert headers["Api-Key"] == "test_api_key"
    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"


def test_get_headers_with_token(client) -> None:
    client.token = "my_jwt_token"
    headers = client._get_headers()
    assert headers["Authorization"] == "Bearer my_jwt_token"


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "username,password",
    [
        ("", ""),
        ("", "pass"),
        ("user", ""),
    ],
)
def test_login_missing_credentials_returns_false(
    client, mock_config, username, password
) -> None:
    mock_config.opensubtitles_username = username
    mock_config.opensubtitles_password = password
    result = client.login()
    assert result is False
    assert client.token is None


def test_login_success(client, mock_session) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "jwt_abc123"}
    mock_session.post.return_value = mock_response

    result = client.login()

    assert result is True
    assert client.token == "jwt_abc123"
    mock_session.post.assert_called_once()
    args, kwargs = mock_session.post.call_args
    assert args[0] == f"{OPENSUBTITLES_API_BASE}login"
    assert kwargs["json"] == {"username": "user", "password": "pass"}


@pytest.mark.parametrize(
    "status_code, text, side_effect, expected_result",
    [
        (401, "Unauthorized", None, False),
        (500, "Internal Error", None, False),
        (200, "", ConnectionError("Connection dropped"), False),
    ],
)
def test_login_failures(
    client, mock_session, status_code, text, side_effect, expected_result
) -> None:
    if side_effect:
        mock_session.post.side_effect = side_effect
    else:
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.text = text
        mock_session.post.return_value = mock_response

    assert client.login() == expected_result
    assert client.token is None


# ---------------------------------------------------------------------------
# search_subtitles
# ---------------------------------------------------------------------------


def test_search_subtitles_missing_api_key_returns_empty(client, mock_config) -> None:
    mock_config.opensubtitles_api_key = ""
    results = client.search_subtitles(query="The Matrix")
    assert results == []


def test_search_subtitles_by_tmdb_id_success(client, mock_session) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"id": "sub1"}, {"id": "sub2"}]}
    mock_session.get.return_value = mock_response

    results = client.search_subtitles(tmdb_id=603, season_number=1, episode_number=2)

    assert len(results) == 2
    assert results[0]["id"] == "sub1"
    mock_session.get.assert_called_once()
    kwargs = mock_session.get.call_args.kwargs
    assert kwargs["params"]["tmdb_id"] == 603
    assert kwargs["params"]["season_number"] == 1
    assert kwargs["params"]["episode_number"] == 2
    assert kwargs["params"]["languages"] == "en"


def test_search_subtitles_by_tmdb_id_no_season_episode(client, mock_session) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_session.get.return_value = mock_response

    client.search_subtitles(tmdb_id=603)

    mock_session.get.assert_called_once()
    params = mock_session.get.call_args.kwargs["params"]
    assert params["tmdb_id"] == 603
    assert "season_number" not in params
    assert "episode_number" not in params


def test_search_subtitles_by_query_success(client, mock_session) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"id": "sub99"}]}
    mock_session.get.return_value = mock_response

    results = client.search_subtitles(query="some movie")

    assert len(results) == 1
    params = mock_session.get.call_args.kwargs["params"]
    assert params["query"] == "some movie"


@pytest.mark.parametrize(
    "status_code, text, side_effect",
    [
        (429, "Too Many Requests", None),
        (500, "Internal Server Error", None),
        (200, "", TimeoutError("timed out")),
    ],
)
def test_search_subtitles_failures(
    client, mock_session, status_code, text, side_effect
) -> None:
    if side_effect:
        mock_session.get.side_effect = side_effect
    else:
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.text = text
        mock_session.get.return_value = mock_response

    results = client.search_subtitles(query="test")
    assert results == []


# ---------------------------------------------------------------------------
# get_download_link
# ---------------------------------------------------------------------------


def test_get_download_link_already_authenticated(client, mock_session) -> None:
    client.token = "existing_token"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"link": "https://cdn.example.invalid/sub.srt"}
    mock_session.post.return_value = mock_response

    link = client.get_download_link(file_id=98765)

    assert link == "https://cdn.example.invalid/sub.srt"
    mock_session.post.assert_called_once()
    args, kwargs = mock_session.post.call_args
    assert args[0] == f"{OPENSUBTITLES_API_BASE}download"
    assert kwargs["json"] == {"file_id": 98765}


def test_get_download_link_triggers_login_when_no_token(client, mock_session) -> None:
    client.token = None

    login_response = MagicMock()
    login_response.status_code = 200
    login_response.json.return_value = {"token": "new_token"}

    download_response = MagicMock()
    download_response.status_code = 200
    download_response.json.return_value = {"link": "https://example.invalid/file.srt"}

    mock_session.post.side_effect = [login_response, download_response]

    link = client.get_download_link(file_id=111)

    assert link == "https://example.invalid/file.srt"
    assert client.token == "new_token"
    assert mock_session.post.call_count == 2


def test_get_download_link_login_fails_returns_none(
    client, mock_config, mock_session
) -> None:
    client.token = None
    mock_config.opensubtitles_username = ""
    mock_config.opensubtitles_password = ""

    link = client.get_download_link(file_id=222)

    assert link is None
    mock_session.post.assert_not_called()


@pytest.mark.parametrize(
    "status_code, text, side_effect",
    [
        (406, "Download quota exceeded", None),
        (500, "Internal error", None),
        (200, "", RuntimeError("network dead")),
    ],
)
def test_get_download_link_failures(
    client, mock_session, status_code, text, side_effect
) -> None:
    client.token = "tok"
    if side_effect:
        mock_session.post.side_effect = side_effect
    else:
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.text = text
        mock_session.post.return_value = mock_response

    link = client.get_download_link(file_id=333)
    assert link is None


# ---------------------------------------------------------------------------
# download_subtitle
# ---------------------------------------------------------------------------


def test_download_subtitle_success(client, mock_session) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"
    mock_session.get.return_value = mock_response

    content = client.download_subtitle("https://example.invalid/sub.srt")

    assert content == b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"
    mock_session.get.assert_called_once_with(
        "https://example.invalid/sub.srt", timeout=30
    )


@pytest.mark.parametrize(
    "status_code, text, side_effect",
    [
        (403, "Forbidden", None),
        (500, "Server Error", None),
        (200, "", ConnectionError("dropped")),
    ],
)
def test_download_subtitle_failures(
    client, mock_session, status_code, text, side_effect
) -> None:
    if side_effect:
        mock_session.get.side_effect = side_effect
    else:
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.text = text
        mock_session.get.return_value = mock_response

    content = client.download_subtitle("https://example.invalid/sub.srt")
    assert content is None
