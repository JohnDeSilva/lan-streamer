"""
Tests for AsyncJellyfinClient — async Jellyfin provider.

All async tests use ``event_loop.run_until_complete()``.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from lan_streamer.providers.jellyfin_async import AsyncJellyfinClient
from lan_streamer.providers.http_client import AsyncHTTPClient


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
def client() -> AsyncJellyfinClient:
    return AsyncJellyfinClient(
        jellyfin_url="http://test-jf",
        jellyfin_api_key="test-key",
    )


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    return event_loop.run_until_complete(coro)


class TestConstruction:
    def test_is_configured(self, client: AsyncJellyfinClient) -> None:
        assert client.is_configured() is True

    def test_not_configured(self) -> None:
        c = AsyncJellyfinClient(jellyfin_url="", jellyfin_api_key="")
        assert c.is_configured() is False

    def test_get_headers(self, client: AsyncJellyfinClient) -> None:
        headers = client._get_headers()
        assert "Authorization" in headers
        assert "test-key" in headers["Authorization"]

    def test_get_base_url_with_domain(self, client: AsyncJellyfinClient) -> None:
        client._jellyfin_url = "jellyfin.local"
        assert client._get_base_url() == "https://jellyfin.local"

    def test_get_base_url_localhost(self, client: AsyncJellyfinClient) -> None:
        client._jellyfin_url = "localhost"
        assert client._get_base_url() == "http://localhost"

    def test_get_base_url_empty(self, client: AsyncJellyfinClient) -> None:
        client._jellyfin_url = ""
        assert client._get_base_url() == ""


class TestGetCurrentUserId:
    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(jellyfin_url="", jellyfin_api_key="")
            assert await c.get_current_user_id() is None

        _run(run(), event_loop)

    def test_fetches_user_id(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get_json = AsyncMock(return_value=[{"Id": "user123"}])
            client._http_client = mock_http

            result = await client.get_current_user_id()
            assert result == "user123"

            # Second call should use cache
            mock_http.get_json.reset_mock()
            result = await client.get_current_user_id()
            assert result == "user123"
            mock_http.get_json.assert_not_called()

        _run(run(), event_loop)

    def test_returns_none_on_empty_list(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get_json = AsyncMock(return_value=[])
            client._http_client = mock_http
            assert await client.get_current_user_id() is None

        _run(run(), event_loop)

    def test_retry_with_http(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(
                jellyfin_url="test.com",
                jellyfin_api_key="key",
            )
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            # First call (https) raises
            mock_http.get_json = AsyncMock(
                side_effect=[Exception("https fail"), [{"Id": "u1"}]]
            )
            c._http_client = mock_http
            assert await c.get_current_user_id() == "u1"

        _run(run(), event_loop)


class TestSetWatchedStatus:
    def test_set_watched(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            client._http_client = mock_http
            await client.set_watched_status("item123", True)
            mock_http.post.assert_called_once()

        _run(run(), event_loop)

    def test_set_unwatched(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            client._http_client = mock_http
            await client.set_watched_status("item123", False)
            mock_http.delete.assert_called_once()

        _run(run(), event_loop)

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(jellyfin_url="", jellyfin_api_key="")
            await c.set_watched_status("1", True)

        _run(run(), event_loop)

    def test_no_user_id(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client.get_current_user_id = AsyncMock(return_value=None)
            await client.set_watched_status("1", True)

        _run(run(), event_loop)


class TestFetchWatchedEpisodes:
    def test_returns_watched(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(
                return_value={
                    "Items": [
                        {
                            "Id": "ep1",
                            "Path": "/show/s01e01.mkv",
                            "SeriesName": "Show",
                            "Name": "Ep1",
                        },
                        {"Id": "ep2", "Path": "/show/s01e02.mkv"},
                    ]
                }
            )
            client._http_client = mock_http

            ids, paths, names = await client.fetch_watched_episodes()
            assert paths == {"/show/s01e01.mkv", "/show/s01e02.mkv"}
            assert ids == {"ep1", "ep2"}
            assert ("show", "ep1") in names

        _run(run(), event_loop)

    def test_pagination(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            items_page1 = [{"Path": f"/ep{i}.mkv"} for i in range(5000)]
            items_page2 = [{"Path": "/ep_last.mkv"}]
            mock_http.get = AsyncMock(
                side_effect=[
                    {"Items": items_page1},
                    {"Items": items_page2},
                ]
            )
            client._http_client = mock_http

            ids, paths, names = await client.fetch_watched_episodes()
            assert len(paths) == 5001
            assert mock_http.get.call_count == 2

        _run(run(), event_loop)

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(jellyfin_url="", jellyfin_api_key="")
            ids, paths, names = await c.fetch_watched_episodes()
            assert ids == set()
            assert paths == set()

        _run(run(), event_loop)

    def test_no_user_id(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client.get_current_user_id = AsyncMock(return_value=None)
            ids, paths, names = await client.fetch_watched_episodes()
            assert ids == set()

        _run(run(), event_loop)


class TestGetJellyfinCorrelationData:
    def test_returns_mapping(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(
                return_value={
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
            )
            client._http_client = mock_http

            data = await client.get_jellyfin_correlation_data()
            assert "/path1" in data["path_map"]
            assert "tmdb1" in data["tmdb_episode_map"]
            assert ("show", "ep1") in data["name_map"]

        _run(run(), event_loop)

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(jellyfin_url="", jellyfin_api_key="")
            assert await c.get_jellyfin_correlation_data() == {}

        _run(run(), event_loop)


class TestSearch:
    def test_search_series(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(
                return_value={"Items": [{"Id": "s1", "Name": "Series One"}]}
            )
            client._http_client = mock_http

            results = await client.search_series("Series One")
            assert len(results) == 1
            assert results[0]["Id"] == "s1"

        _run(run(), event_loop)

    def test_search_series_not_configured(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(jellyfin_url="", jellyfin_api_key="")
            assert await c.search_series("Test") == []

        _run(run(), event_loop)

    def test_search_series_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(side_effect=Exception("API Error"))
            client._http_client = mock_http
            assert await client.search_series("Test") == []

        _run(run(), event_loop)

    def test_search_movie(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(
                return_value={"Items": [{"Id": "m1", "Name": "Movie One"}]}
            )
            client._http_client = mock_http

            results = await client.search_movie("Movie One")
            assert len(results) == 1
            assert results[0]["Id"] == "m1"

        _run(run(), event_loop)


class TestClose:
    def test_close(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            client._http_client = mock_http
            await client.close()
            mock_http.close.assert_awaited_once()

        _run(run(), event_loop)
