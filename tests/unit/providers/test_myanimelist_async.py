"""
Tests for AsyncMyAnimeListClient — async MyAnimeList provider.

All async tests use ``event_loop.run_until_complete()``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lan_streamer.providers.http_client import AsyncHTTPClient
from lan_streamer.providers.myanimelist_async import AsyncMyAnimeListClient
from lan_streamer.system.config import config


def _mock_async_context_manager(return_value: Any = None) -> AsyncMock:
    """Create an AsyncMock that works as an async context manager."""
    obj = AsyncMock()
    obj.__aenter__ = AsyncMock(
        return_value=return_value if return_value is not None else obj
    )
    obj.__aexit__ = AsyncMock()
    return obj


def _mock_response(status: int = 200, json_data: dict | None = None) -> AsyncMock:
    """Create a mock aiohttp response with async context manager support."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value="")
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


class TestConfiguration:
    def test_is_configured(self, client: AsyncMyAnimeListClient) -> None:
        assert client.is_configured() is True

    def test_is_configured_false(self) -> None:
        with patch.object(config, "myanimelist_client_id", ""):
            c = AsyncMyAnimeListClient()
            assert c.is_configured() is False

    def test_is_authenticated(self, client: AsyncMyAnimeListClient) -> None:
        assert client.is_authenticated() is True

    def test_is_authenticated_false(self) -> None:
        with patch.object(config, "myanimelist_access_token", ""):
            c = AsyncMyAnimeListClient()
            assert c.is_authenticated() is False

    def test_generate_auth_url(self, client: AsyncMyAnimeListClient) -> None:
        url = client.generate_auth_url("my_verifier")
        assert "client_id=test-client-id" in url
        assert "code_challenge=my_verifier" in url
        assert "code_challenge_method=plain" in url

    def test_remove_connection(self, client: AsyncMyAnimeListClient) -> None:
        with patch.object(config, "save_to_db") as mock_save:
            client.remove_connection()
            assert config.myanimelist_access_token == ""
            assert config.myanimelist_refresh_token == ""
            assert config.myanimelist_token_expires_at == 0.0
            mock_save.assert_called_once()


class TestGetAuthHeaders:
    def test_authenticated(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            headers = await client._get_auth_headers()
            assert headers["Authorization"] == "Bearer test-access-token"

        _run(run(), event_loop)

    def test_unauthenticated(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            with patch.object(config, "myanimelist_client_id", "test-client-id"):
                with patch.object(config, "myanimelist_access_token", ""):
                    c = AsyncMyAnimeListClient()
                    headers = await c._get_auth_headers()
                    assert headers["X-MAL-CLIENT-ID"] == "test-client-id"

        _run(run(), event_loop)


class TestExchangeAuthCode:
    def test_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = AsyncMock()
            mock_response = _mock_response(
                status=200,
                json_data={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                },
            )
            mock_session.post = MagicMock(return_value=mock_response)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            with patch.object(config, "save_to_db") as mock_save:
                success, msg = await client.exchange_auth_code("auth_code", "verifier")
                assert success is True
                mock_save.assert_called_once()

        _run(run(), event_loop)

    def test_failure(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_session.post = MagicMock(side_effect=Exception("API Error"))
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            success, msg = await client.exchange_auth_code("auth_code", "verifier")
            assert success is False

        _run(run(), event_loop)


class TestRefreshAccessToken:
    def test_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_response = _mock_response(
                status=200,
                json_data={
                    "access_token": "refreshed-access",
                    "refresh_token": "refreshed-refresh",
                    "expires_in": 3600,
                },
            )
            mock_session.post = MagicMock(return_value=mock_response)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            with patch.object(config, "save_to_db") as mock_save:
                success = await client.refresh_access_token()
                assert success is True
                mock_save.assert_called_once()

        _run(run(), event_loop)

    def test_no_token(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            with patch.object(config, "myanimelist_refresh_token", ""):
                assert await client.refresh_access_token() is False

        _run(run(), event_loop)


class TestSearchAnime:
    def test_success(
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
                                "title": "Jujutsu Kaisen",
                                "num_episodes": 24,
                                "main_picture": {"medium": "url_medium"},
                                "start_date": "2020-10-03",
                            }
                        }
                    ]
                }
            )
            client._http_client = mock_http

            results = await client.search_anime("Jujutsu")
            assert len(results) == 1
            assert results[0]["id"] == 123
            assert results[0]["title"] == "Jujutsu Kaisen"
            assert results[0]["num_episodes"] == 24
            assert results[0]["poster_path"] == "url_medium"

        _run(run(), event_loop)

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            with patch.object(config, "myanimelist_client_id", ""):
                c = AsyncMyAnimeListClient()
                assert await c.search_anime("test") == []

        _run(run(), event_loop)

    def test_failure(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(side_effect=Exception("API error"))
            client._http_client = mock_http
            assert await client.search_anime("test") == []

        _run(run(), event_loop)


class TestGetAnimeDetails:
    def test_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(
                return_value={"id": 123, "title": "Jujutsu Kaisen"}
            )
            client._http_client = mock_http

            details = await client.get_anime_details(123)
            assert details is not None
            assert details["id"] == 123

        _run(run(), event_loop)

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            with patch.object(config, "myanimelist_client_id", ""):
                c = AsyncMyAnimeListClient()
                assert await c.get_anime_details(123) is None

        _run(run(), event_loop)


class TestUpdateWatchedStatus:
    def test_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_response = _mock_response(status=200)
            mock_session.put = MagicMock(return_value=mock_response)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            success = await client.update_watched_status(123, 5, 12)
            assert success is True

        _run(run(), event_loop)

    def test_not_authenticated(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            with patch.object(config, "myanimelist_access_token", ""):
                c = AsyncMyAnimeListClient()
                assert await c.update_watched_status(123, 5, 12) is False

        _run(run(), event_loop)

    def test_server_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_response = _mock_response(status=500)
            mock_session.put = MagicMock(return_value=mock_response)
            client._http_client._get_session = AsyncMock(return_value=mock_session)

            success = await client.update_watched_status(123, 5, 12)
            assert success is False

        _run(run(), event_loop)


class TestClose:
    def test_close(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncMyAnimeListClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            client._http_client = mock_http
            await client.close()
            mock_http.close.assert_awaited_once()

        _run(run(), event_loop)
