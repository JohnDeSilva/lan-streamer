"""Coverage tests for AsyncMyAnimeListClient — targeting uncovered lines."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lan_streamer.providers.http_client import AsyncHTTPClient
from lan_streamer.providers.myanimelist_async import AsyncMyAnimeListClient
from lan_streamer.system.config import config


def _mock_response(
    status: int = 200, json_data: dict | None = None, text_data: str = ""
) -> AsyncMock:
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=text_data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock()
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.run_until_complete(
        asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True)
    )
    loop.close()


@pytest.fixture
def client() -> AsyncMyAnimeListClient:
    with (
        patch.object(config, "myanimelist_client_id", "test-client-id"),
        patch.object(config, "myanimelist_client_secret", "test-client-secret"),
        patch.object(config, "myanimelist_access_token", "test-access-token"),
        patch.object(config, "myanimelist_refresh_token", "test-refresh-token"),
        patch.object(config, "myanimelist_token_expires_at", time.time() + 3600),
    ):
        yield AsyncMyAnimeListClient()


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    return event_loop.run_until_complete(coro)


class TestTokenRefreshTrigger:
    """Lines 43-44: token refresh when close to expiry in _get_auth_headers."""

    def test_triggers_refresh_when_expiring(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        async def run() -> None:
            with (
                patch.object(config, "myanimelist_client_id", "test-client-id"),
                patch.object(config, "myanimelist_client_secret", ""),
                patch.object(config, "myanimelist_access_token", "current-token"),
                patch.object(config, "myanimelist_refresh_token", "refresh-tok"),
                patch.object(
                    config,
                    "myanimelist_token_expires_at",
                    time.time() + 100,
                ),
            ):
                c = AsyncMyAnimeListClient()
                mock_session = MagicMock()
                mock_resp = _mock_response(
                    status=200,
                    json_data={
                        "access_token": "new-token",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                    },
                )
                mock_session.post = MagicMock(return_value=mock_resp)
                c._http_client._get_session = AsyncMock(return_value=mock_session)

                with patch.object(config, "save_to_db"):
                    headers = await c._get_auth_headers()
                    assert headers["Authorization"] == "Bearer new-token"

        _run(run(), event_loop)


class TestExchangeAuthCodeErrors:
    """Lines 83-96: error response handling in exchange_auth_code."""

    def test_non_200_with_json_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = AsyncMock()
            mock_resp = _mock_response(
                status=401,
                json_data={"error_description": "Invalid code"},
            )
            mock_session.post = MagicMock(return_value=mock_resp)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            success, msg = await client.exchange_auth_code("bad_code", "verifier")
            assert success is False
            assert "401" in msg
            assert "Invalid code" in msg

        _run(run(), event_loop)

    def test_non_200_with_message_field(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = AsyncMock()
            mock_resp = _mock_response(
                status=400,
                json_data={"message": "Bad request"},
            )
            mock_session.post = MagicMock(return_value=mock_resp)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            success, msg = await client.exchange_auth_code("code", "v")
            assert success is False
            assert "Bad request" in msg

        _run(run(), event_loop)

    def test_non_200_with_error_field(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = AsyncMock()
            mock_resp = _mock_response(
                status=403,
                json_data={"error": "forbidden"},
            )
            mock_session.post = MagicMock(return_value=mock_resp)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            success, msg = await client.exchange_auth_code("code", "v")
            assert success is False
            assert "forbidden" in msg

        _run(run(), event_loop)

    def test_non_200_json_parse_fails_uses_text(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = AsyncMock()
            mock_resp = _mock_response(status=500, text_data="Server Error")
            mock_resp.json = AsyncMock(side_effect=Exception("not json"))
            mock_session.post = MagicMock(return_value=mock_resp)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            success, msg = await client.exchange_auth_code("code", "v")
            assert success is False
            assert "500" in msg

        _run(run(), event_loop)

    def test_non_200_no_error_fields(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = AsyncMock()
            mock_resp = _mock_response(
                status=422,
                json_data={"unknown_field": "val"},
            )
            mock_session.post = MagicMock(return_value=mock_resp)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            success, msg = await client.exchange_auth_code("code", "v")
            assert success is False
            assert "422" in msg

        _run(run(), event_loop)


class TestRefreshAccessTokenException:
    """Lines 145-147: exception in refresh_access_token."""

    def test_exception_returns_false(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_session.post = MagicMock(side_effect=Exception("network error"))
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            result = await client.refresh_access_token()
            assert result is False

        _run(run(), event_loop)


class TestGetAnimeDetailsException:
    """Lines 223-225: exception in get_anime_details."""

    def test_exception_returns_none(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(side_effect=Exception("timeout"))
            client._http_client = mock_http

            result = await client.get_anime_details(123)
            assert result is None

        _run(run(), event_loop)


class TestUpdateWatchedStatusCompleted:
    """Line 243: status = 'completed' when all episodes watched."""

    def test_completed_status(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_resp = _mock_response(status=200)
            mock_session.put = MagicMock(return_value=mock_resp)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            success = await client.update_watched_status(123, 12, 12)
            assert success is True
            call_kwargs = mock_session.put.call_args
            sent_data = (
                call_kwargs[1].get("data") or call_kwargs[0][2]
                if len(call_kwargs[0]) > 2
                else call_kwargs[1].get("data")
            )
            assert sent_data["status"] == "completed"

        _run(run(), event_loop)


class TestUpdateWatchedException:
    """Lines 265-267: exception in update_watched_status."""

    def test_exception_returns_false(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_session.put = MagicMock(side_effect=Exception("network error"))
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            result = await client.update_watched_status(123, 5, 12)
            assert result is False

        _run(run(), event_loop)


class TestUpdateWatchedNotConfigured:
    """Lines 230-234: not configured or not authenticated."""

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            with patch.object(config, "myanimelist_client_id", ""):
                c = AsyncMyAnimeListClient()
                result = await c.update_watched_status(123, 5, 12)
                assert result is False

        _run(run(), event_loop)


class TestRemoveConnection:
    """Lines 149-154: remove_connection clears credentials."""

    def test_removes_credentials(self) -> None:
        with (
            patch.object(config, "myanimelist_client_id", "test-id"),
            patch.object(config, "myanimelist_access_token", "old-token"),
            patch.object(config, "myanimelist_refresh_token", "old-refresh"),
            patch.object(config, "myanimelist_token_expires_at", 9999.0),
            patch.object(config, "save_to_db") as mock_save,
        ):
            c = AsyncMyAnimeListClient()
            c.remove_connection()
            assert config.myanimelist_access_token == ""
            assert config.myanimelist_refresh_token == ""
            assert config.myanimelist_token_expires_at == 0.0
            mock_save.assert_called_once()


class TestGenerateAuthUrl:
    """Lines 51-60: generate_auth_url builds correct URL."""

    def test_builds_url(self) -> None:
        with patch.object(config, "myanimelist_client_id", "my-client-id"):
            c = AsyncMyAnimeListClient()
            url = c.generate_auth_url("test_verifier_123")
            assert "my-client-id" in url
            assert "test_verifier_123" in url
            assert "code_challenge_method=plain" in url


class TestExchangeAuthCodeSuccess:
    """Lines 101-109: successful token exchange."""

    def test_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = AsyncMock()
            mock_resp = _mock_response(
                status=200,
                json_data={
                    "access_token": "new-token",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                },
            )
            mock_session.post = MagicMock(return_value=mock_resp)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            with patch.object(config, "save_to_db"):
                success, msg = await client.exchange_auth_code("code123", "verifier")
                assert success is True
                assert "successful" in msg.lower()

        _run(run(), event_loop)


class TestRefreshAccessTokenSuccess:
    """Lines 129-144: successful token refresh."""

    def test_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_resp = _mock_response(
                status=200,
                json_data={
                    "access_token": "refreshed-token",
                    "refresh_token": "refreshed-refresh",
                    "expires_in": 3600,
                },
            )
            mock_session.post = MagicMock(return_value=mock_resp)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            with patch.object(config, "save_to_db"):
                result = await client.refresh_access_token()
                assert result is True

        _run(run(), event_loop)


class TestRefreshAccessTokenNoRefreshToken:
    """Lines 115-117: no refresh token available."""

    def test_no_refresh_token(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            with patch.object(config, "myanimelist_refresh_token", ""):
                c = AsyncMyAnimeListClient()
                result = await c.refresh_access_token()
                assert result is False

        _run(run(), event_loop)


class TestSearchAnimeSuccess:
    """Lines 172-204: successful anime search."""

    def test_returns_results(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(
                return_value={
                    "data": [
                        {
                            "node": {
                                "id": 123,
                                "title": "Test Anime",
                                "num_episodes": 12,
                                "main_picture": {
                                    "medium": "http://example.invalid/pic.jpg"
                                },
                                "start_date": "2024-01-01",
                                "end_date": "2024-03-01",
                                "synopsis": "A test anime",
                                "mean": 8.5,
                                "media_type": "tv",
                                "status": "finished",
                                "alternative_titles": {
                                    "synonyms": ["TA"],
                                    "en": "Test Anime EN",
                                },
                                "genres": [{"name": "Action"}],
                            }
                        }
                    ]
                }
            )
            client._http_client = mock_http

            results = await client.search_anime("Test")
            assert len(results) == 1
            assert results[0]["title"] == "Test Anime"
            assert results[0]["score"] == 8.5
            assert results[0]["genres"] == ["Action"]

        _run(run(), event_loop)


class TestSearchAnimeNotConfigured:
    """Lines 157-159: search_anime when not configured."""

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            with patch.object(config, "myanimelist_client_id", ""):
                c = AsyncMyAnimeListClient()
                results = await c.search_anime("Test")
                assert results == []

        _run(run(), event_loop)


class TestGetAnimeDetailsSuccess:
    """Lines 218-222: successful get_anime_details."""

    def test_returns_details(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(return_value={"id": 123, "title": "Test Anime"})
            client._http_client = mock_http

            result = await client.get_anime_details(123)
            assert result is not None
            assert result["title"] == "Test Anime"

        _run(run(), event_loop)


class TestGetAnimeDetailsNotConfigured:
    """Lines 210-211: get_anime_details when not configured."""

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            with patch.object(config, "myanimelist_client_id", ""):
                c = AsyncMyAnimeListClient()
                result = await c.get_anime_details(123)
                assert result is None

        _run(run(), event_loop)


class TestUpdateWatchedWatching:
    """Line 241: status = 'watching' when not all episodes watched."""

    def test_watching_status(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_resp = _mock_response(status=200)
            mock_session.put = MagicMock(return_value=mock_resp)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            success = await client.update_watched_status(123, 5, 12)
            assert success is True

        _run(run(), event_loop)


class TestUpdateWatchedHttpError:
    """Lines 256-262: update_watched_status non-200 response."""

    def test_http_error_returns_false(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_resp = _mock_response(status=500, text_data="Server Error")
            mock_session.put = MagicMock(return_value=mock_resp)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            result = await client.update_watched_status(123, 5, 12)
            assert result is False

        _run(run(), event_loop)


class TestCloseMethod:
    """Line 269-270: close method."""

    def test_close(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.close = AsyncMock()
            client._http_client = mock_http
            await client.close()
            mock_http.close.assert_called_once()

        _run(run(), event_loop)


class TestGetAuthHeadersNotAuthenticated:
    """Lines 39-40: _get_auth_headers when not authenticated."""

    def test_returns_client_id_header(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        async def run() -> None:
            with (
                patch.object(config, "myanimelist_client_id", "client-id"),
                patch.object(config, "myanimelist_access_token", ""),
            ):
                c = AsyncMyAnimeListClient()
                headers = await c._get_auth_headers()
                assert headers["X-MAL-CLIENT-ID"] == "client-id"

        _run(run(), event_loop)
