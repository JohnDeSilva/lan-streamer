import pytest
import time
from unittest.mock import MagicMock, patch
from lan_streamer.providers.myanimelist import MyAnimeListClient
from lan_streamer.system.config import config


@pytest.fixture
def mal() -> None:
    with (
        patch.object(config, "myanimelist_client_id", "test-client-id"),
        patch.object(config, "myanimelist_client_secret", "test-client-secret"),
        patch.object(config, "myanimelist_access_token", "test-access-token"),
        patch.object(config, "myanimelist_refresh_token", "test-refresh-token"),
        patch.object(config, "myanimelist_token_expires_at", time.time() + 3600),
    ):
        client = MyAnimeListClient()
        yield client


def test_mal_is_configured(mal) -> None:
    assert mal.is_configured() is True
    config.myanimelist_client_id = ""
    assert mal.is_configured() is False


def test_mal_is_authenticated(mal) -> None:
    assert mal.is_authenticated() is True
    config.myanimelist_access_token = ""
    assert mal.is_authenticated() is False


def test_mal_get_auth_headers_authenticated(mal) -> None:
    headers = mal.get_auth_headers()
    assert headers["Authorization"] == "Bearer test-access-token"


def test_mal_get_auth_headers_unauthenticated() -> None:
    with (
        patch.object(config, "myanimelist_client_id", "test-client-id"),
        patch.object(config, "myanimelist_access_token", ""),
    ):
        client = MyAnimeListClient()
        headers = client.get_auth_headers()
        assert headers["X-MAL-CLIENT-ID"] == "test-client-id"


def test_mal_get_auth_headers_refreshes_token(mal) -> None:
    config.myanimelist_token_expires_at = time.time() - 100
    with patch.object(mal, "refresh_access_token", return_value=True) as mock_refresh:
        headers = mal.get_auth_headers()
        mock_refresh.assert_called_once()
        assert headers["Authorization"] == "Bearer test-access-token"


def test_mal_generate_auth_url(mal) -> None:
    url = mal.generate_auth_url("my_verifier")
    assert "client_id=test-client-id" in url
    assert "code_challenge=my_verifier" in url
    assert "code_challenge_method=plain" in url


def test_mal_exchange_auth_code_success(mal) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_in": 3600,
    }
    mal.session.post = MagicMock(return_value=mock_resp)

    with patch.object(config, "save_to_db") as mock_save:
        success, msg = mal.exchange_auth_code("auth_code", "verifier")
        assert success is True
        assert config.myanimelist_access_token == "new-access"
        assert config.myanimelist_refresh_token == "new-refresh"
        mock_save.assert_called_once()


def test_mal_exchange_auth_code_failure(mal) -> None:
    mal.session.post = MagicMock(side_effect=Exception("API Error"))
    success, msg = mal.exchange_auth_code("auth_code", "verifier")
    assert success is False
    assert "API Error" in msg


def test_mal_refresh_access_token_success(mal) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "access_token": "refreshed-access",
        "refresh_token": "refreshed-refresh",
        "expires_in": 3600,
    }
    mal.session.post = MagicMock(return_value=mock_resp)

    with patch.object(config, "save_to_db") as mock_save:
        success = mal.refresh_access_token()
        assert success is True
        assert config.myanimelist_access_token == "refreshed-access"
        assert config.myanimelist_refresh_token == "refreshed-refresh"
        mock_save.assert_called_once()


def test_mal_refresh_access_token_no_token(mal) -> None:
    config.myanimelist_refresh_token = ""
    assert mal.refresh_access_token() is False


def test_mal_refresh_access_token_failure(mal) -> None:
    mal.session.post = MagicMock(side_effect=Exception("API Error"))
    assert mal.refresh_access_token() is False


def test_mal_remove_connection(mal) -> None:
    with patch.object(config, "save_to_db") as mock_save:
        mal.remove_connection()
        assert config.myanimelist_access_token == ""
        assert config.myanimelist_refresh_token == ""
        assert config.myanimelist_token_expires_at == 0.0
        mock_save.assert_called_once()


def test_mal_search_anime(mal) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {
                "node": {
                    "id": 123,
                    "title": "Jujutsu Kaisen",
                    "num_episodes": 24,
                    "main_picture": {"medium": "url_medium"},
                    "start_date": "2020-10-03",
                }
            }
        ]
    }
    mal.session.get = MagicMock(return_value=mock_resp)

    results = mal.search_anime("Jujutsu")
    assert len(results) == 1
    assert results[0]["id"] == 123
    assert results[0]["title"] == "Jujutsu Kaisen"
    assert results[0]["num_episodes"] == 24
    assert results[0]["poster_path"] == "url_medium"


def test_mal_get_anime_details(mal) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": 123, "title": "Jujutsu Kaisen"}
    mal.session.get = MagicMock(return_value=mock_resp)

    details = mal.get_anime_details(123)
    assert details["id"] == 123
    assert details["title"] == "Jujutsu Kaisen"


def test_mal_update_watched_status(mal) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mal.session.put = MagicMock(return_value=mock_resp)

    success = mal.update_watched_status(123, 5, 12)
    assert success is True
    mal.session.put.assert_called_once()
    assert "watching" in mal.session.put.call_args[1]["data"]["status"]
    assert mal.session.put.call_args[1]["data"]["num_watched_episodes"] == 5


def test_mal_update_watched_status_completed(mal) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mal.session.put = MagicMock(return_value=mock_resp)

    success = mal.update_watched_status(123, 12, 12)
    assert success is True
    assert "completed" in mal.session.put.call_args[1]["data"]["status"]
