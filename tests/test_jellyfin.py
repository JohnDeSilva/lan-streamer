import pytest
from unittest.mock import MagicMock
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
