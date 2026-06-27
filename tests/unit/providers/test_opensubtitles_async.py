"""
Tests for AsyncOpenSubtitlesClient — async OpenSubtitles provider.

All async tests use ``event_loop.run_until_complete()``.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lan_streamer.providers.http_client import AsyncHTTPClient
from lan_streamer.providers.opensubtitles_async import (
    AsyncOpenSubtitlesClient,
)


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
def mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.opensubtitles_api_key = "test_api_key"
    cfg.opensubtitles_username = "user"
    cfg.opensubtitles_password = "pass"
    return cfg


@pytest.fixture
def client(mock_config: Any) -> AsyncOpenSubtitlesClient:
    with patch("lan_streamer.providers.opensubtitles_async.config", mock_config):
        yield AsyncOpenSubtitlesClient()


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    return event_loop.run_until_complete(coro)


class TestGetHeaders:
    def test_without_token(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        headers = client._get_headers()
        assert headers["Api-Key"] == "test_api_key"
        assert "Authorization" not in headers

    def test_with_token(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        client._token = "my_jwt_token"
        headers = client._get_headers()
        assert headers["Authorization"] == "Bearer my_jwt_token"


class TestLogin:
    def test_missing_credentials_returns_false(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncOpenSubtitlesClient,
        mock_config: Any,
    ) -> None:
        async def run() -> None:
            mock_config.opensubtitles_username = ""
            mock_config.opensubtitles_password = ""
            result = await client.login()
            assert result is False
            assert client._token is None

        _run(run(), event_loop)

    def test_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.post = AsyncMock(return_value={"token": "jwt_abc123"})
            client._http_client = mock_http

            result = await client.login()
            assert result is True
            assert client._token == "jwt_abc123"
            mock_http.post.assert_called_once()

        _run(run(), event_loop)

    def test_failure(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.post = AsyncMock(side_effect=Exception("login failed"))
            client._http_client = mock_http

            result = await client.login()
            assert result is False
            assert client._token is None

        _run(run(), event_loop)


class TestSearchSubtitles:
    def test_missing_api_key_returns_empty(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncOpenSubtitlesClient,
        mock_config: Any,
    ) -> None:
        async def run() -> None:
            mock_config.opensubtitles_api_key = ""
            results = await client.search_subtitles(query="The Matrix")
            assert results == []

        _run(run(), event_loop)

    def test_by_tmdb_id_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(
                return_value={"data": [{"id": "sub1"}, {"id": "sub2"}]}
            )
            client._http_client = mock_http

            results = await client.search_subtitles(
                tmdb_identifier=603, season_number=1, episode_number=2
            )
            assert len(results) == 2
            assert results[0]["id"] == "sub1"

        _run(run(), event_loop)

    def test_by_query_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(return_value={"data": [{"id": "sub99"}]})
            client._http_client = mock_http

            results = await client.search_subtitles(query="some movie")
            assert len(results) == 1

        _run(run(), event_loop)

    def test_failure(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(side_effect=Exception("API error"))
            client._http_client = mock_http

            results = await client.search_subtitles(query="test")
            assert results == []

        _run(run(), event_loop)


class TestDownloadLink:
    def test_already_authenticated(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            client._token = "existing_token"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.post = AsyncMock(
                return_value={"link": "https://cdn.example.invalid/sub.srt"}
            )
            client._http_client = mock_http

            link = await client.get_download_link(file_id=98765)
            assert link == "https://cdn.example.invalid/sub.srt"
            mock_http.post.assert_called_once()

        _run(run(), event_loop)

    def test_triggers_login_when_no_token(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            client._token = None
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.post = AsyncMock(
                side_effect=[
                    {"token": "new_token"},
                    {"link": "https://example.invalid/file.srt"},
                ]
            )
            client._http_client = mock_http

            link = await client.get_download_link(file_id=111)
            assert link == "https://example.invalid/file.srt"
            assert client._token == "new_token"
            assert mock_http.post.call_count == 2

        _run(run(), event_loop)

    def test_login_fails_returns_none(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncOpenSubtitlesClient,
        mock_config: Any,
    ) -> None:
        async def run() -> None:
            client._token = None
            mock_config.opensubtitles_username = ""
            mock_config.opensubtitles_password = ""

            link = await client.get_download_link(file_id=222)
            assert link is None

        _run(run(), event_loop)

    def test_failure(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            client._token = "tok"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.post = AsyncMock(side_effect=Exception("error"))
            client._http_client = mock_http

            link = await client.get_download_link(file_id=333)
            assert link is None

        _run(run(), event_loop)


class TestDownloadSubtitle:
    def test_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get_bytes = AsyncMock(
                return_value=b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"
            )
            client._http_client = mock_http

            content = await client.download_subtitle("https://example.invalid/sub.srt")
            assert content == b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"

        _run(run(), event_loop)

    def test_failure(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get_bytes = AsyncMock(side_effect=Exception("error"))
            client._http_client = mock_http

            content = await client.download_subtitle("https://example.invalid/sub.srt")
            assert content is None

        _run(run(), event_loop)


class TestClose:
    def test_close(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncOpenSubtitlesClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            client._http_client = mock_http
            await client.close()
            mock_http.close.assert_awaited_once()

        _run(run(), event_loop)
