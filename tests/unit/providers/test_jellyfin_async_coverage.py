"""Coverage tests for AsyncJellyfinClient — targeting uncovered lines."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from lan_streamer.providers.http_client import AsyncHTTPClient
from lan_streamer.providers.jellyfin_async import AsyncJellyfinClient


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


class TestGetCurrentUserIdRetryHttp:
    """Lines 112-113: retry with http succeeding after https failure."""

    def test_retry_http_succeeds(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(
                jellyfin_url="jellyfin.local",
                jellyfin_api_key="key",
            )
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get_json = AsyncMock(
                side_effect=[
                    Exception("https fail"),
                    [{"Id": "u1"}],
                ]
            )
            c._http_client = mock_http
            result = await c.get_current_user_id()
            assert result == "u1"
            assert mock_http.get_json.call_count == 2

        _run(run(), event_loop)

    def test_retry_http_also_fails(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(
                jellyfin_url="jellyfin.local",
                jellyfin_api_key="key",
            )
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get_json = AsyncMock(
                side_effect=[Exception("https fail"), Exception("http fail")]
            )
            c._http_client = mock_http
            result = await c.get_current_user_id()
            assert result is None

        _run(run(), event_loop)

    def test_non_dict_user_entry_skipped(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get_json = AsyncMock(return_value=["not-a-dict"])
            client._http_client = mock_http
            result = await client.get_current_user_id()
            assert result is None

        _run(run(), event_loop)


class TestFetchWatchedException:
    """Lines 163-165: exception in fetch_watched_episodes loop."""

    def test_exception_during_fetch_breaks_loop(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(side_effect=Exception("network error"))
            client._http_client = mock_http

            ids, paths, names = await client.fetch_watched_episodes()
            assert ids == set()
            assert paths == set()
            assert names == set()

        _run(run(), event_loop)


class TestGetCorrelationData:
    """Lines 179, 228-237, 243-246, 271-274: uncovered correlation paths."""

    def test_no_user_id_returns_empty(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client.get_current_user_id = AsyncMock(return_value=None)
            result = await client.get_jellyfin_correlation_data()
            assert result == {}

        _run(run(), event_loop)

    def test_series_id_map_building(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            episode_response = {
                "Items": [
                    {
                        "Id": "ep1",
                        "Path": "/path1",
                        "SeriesId": "series_a",
                        "ParentIndexNumber": 1,
                        "IndexNumber": 1,
                        "Name": "Episode One",
                        "SeriesName": "Show",
                    }
                ]
            }
            series_response = {"Items": []}
            mock_http.get = AsyncMock(side_effect=[episode_response, series_response])
            client._http_client = mock_http

            data = await client.get_jellyfin_correlation_data()
            assert "series_a" in data["series_id_map"]
            assert data["series_id_map"]["series_a"]["episodes"][(1, 1)] == "ep1"
            assert data["series_id_map"]["series_a"]["names"]["episode one"] == "ep1"

        _run(run(), event_loop)

    def test_episode_fetch_exception(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(side_effect=Exception("fail"))
            client._http_client = mock_http

            data = await client.get_jellyfin_correlation_data()
            assert data["path_map"] == {}

        _run(run(), event_loop)

    def test_series_fetch_exception(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(
                side_effect=[
                    {"Items": []},
                    Exception("series fetch fail"),
                ]
            )
            client._http_client = mock_http

            data = await client.get_jellyfin_correlation_data()
            assert data["tmdb_series_map"] == {}

        _run(run(), event_loop)

    def test_episode_without_series_id_skipped(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            episode_response = {
                "Items": [
                    {
                        "Id": "ep1",
                        "Path": "/path1",
                        "SeriesId": None,
                        "Name": "Ep1",
                    }
                ]
            }
            series_response = {"Items": []}
            mock_http.get = AsyncMock(side_effect=[episode_response, series_response])
            client._http_client = mock_http

            data = await client.get_jellyfin_correlation_data()
            assert data["series_id_map"] == {}

        _run(run(), event_loop)

    def test_episode_with_tmdb_but_no_series_name(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            episode_response = {
                "Items": [
                    {
                        "Id": "ep1",
                        "ProviderIds": {"Tmdb": "tmdb1"},
                        "SeriesId": None,
                        "Name": "Ep1",
                        "SeriesName": None,
                    }
                ]
            }
            series_response = {"Items": []}
            mock_http.get = AsyncMock(side_effect=[episode_response, series_response])
            client._http_client = mock_http

            data = await client.get_jellyfin_correlation_data()
            assert "tmdb1" in data["tmdb_episode_map"]
            assert data["name_map"] == {}

        _run(run(), event_loop)


class TestSearchSeriesNoUser:
    """Line 297: search_series returns [] when no user_id."""

    def test_no_user_id(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client.get_current_user_id = AsyncMock(return_value=None)
            results = await client.search_series("Test")
            assert results == []

        _run(run(), event_loop)


class TestSearchMovieCoverage:
    """Lines 318, 322, 337-339: search_movie uncovered paths."""

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(jellyfin_url="", jellyfin_api_key="")
            results = await c.search_movie("Test")
            assert results == []

        _run(run(), event_loop)

    def test_no_user_id(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client.get_current_user_id = AsyncMock(return_value=None)
            results = await client.search_movie("Test")
            assert results == []

        _run(run(), event_loop)

    def test_exception_returns_empty(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(side_effect=Exception("api error"))
            client._http_client = mock_http
            results = await client.search_movie("Test")
            assert results == []

        _run(run(), event_loop)


class TestSetWatchedException:
    """Lines 364-365: exception in set_watched_status."""

    def test_exception_logged_not_raised(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.post = AsyncMock(side_effect=Exception("network error"))
            client._http_client = mock_http

            await client.set_watched_status("item123", True)
            mock_http.post.assert_called_once()

        _run(run(), event_loop)


class TestSetWatchedNotConfigured:
    """Lines 342-346: set_watched_status when not configured or no user_id."""

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(jellyfin_url="", jellyfin_api_key="")
            await c.set_watched_status("item123", True)

        _run(run(), event_loop)

    def test_no_user_id(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client.get_current_user_id = AsyncMock(return_value=None)
            await client.set_watched_status("item123", True)

        _run(run(), event_loop)


class TestSetWatchedUnwatched:
    """Lines 358-361: set_watched_status unwatched path (delete)."""

    def test_unwatched_calls_delete(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.delete = AsyncMock()
            client._http_client = mock_http

            await client.set_watched_status("item123", False)
            mock_http.delete.assert_called_once()

        _run(run(), event_loop)


class TestCloseMethod:
    """Line 368: close method."""

    def test_close(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.close = AsyncMock()
            client._http_client = mock_http
            await client.close()
            mock_http.close.assert_called_once()

        _run(run(), event_loop)


class TestFetchWatchedNotConfigured:
    """Lines 119-120, 123-124: fetch_watched when not configured or no user."""

    def test_not_configured(self, event_loop: asyncio.AbstractEventLoop) -> None:
        async def run() -> None:
            c = AsyncJellyfinClient(jellyfin_url="", jellyfin_api_key="")
            ids, paths, names = await c.fetch_watched_episodes()
            assert ids == set()

        _run(run(), event_loop)

    def test_no_user_id(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client.get_current_user_id = AsyncMock(return_value=None)
            ids, paths, names = await client.fetch_watched_episodes()
            assert ids == set()

        _run(run(), event_loop)


class TestGetBaseUrlEdgeCases:
    """Lines 69-76: _get_base_url edge cases."""

    def test_empty_url_returns_empty(self) -> None:
        c = AsyncJellyfinClient(jellyfin_url="   ", jellyfin_api_key="key")
        assert c._get_base_url() == ""

    def test_ip_address_gets_http(self) -> None:
        c = AsyncJellyfinClient(
            jellyfin_url="192.168.1.10:8096", jellyfin_api_key="key"
        )
        assert c._get_base_url() == "http://192.168.1.10:8096"

    def test_localhost_gets_http(self) -> None:
        c = AsyncJellyfinClient(jellyfin_url="localhost:8096", jellyfin_api_key="key")
        assert c._get_base_url() == "http://localhost:8096"

    def test_domain_gets_https(self) -> None:
        c = AsyncJellyfinClient(jellyfin_url="jellyfin.local", jellyfin_api_key="key")
        assert c._get_base_url() == "https://jellyfin.local"

    def test_already_has_http(self) -> None:
        c = AsyncJellyfinClient(
            jellyfin_url="http://localhost:8096", jellyfin_api_key="key"
        )
        assert c._get_base_url() == "http://localhost:8096"


class TestFetchWatchedSuccess:
    """Lines 146-162: fetch_watched_episodes with actual items."""

    def test_fetches_items(
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
                            "Path": "/shows/ep1.mkv",
                            "SeriesName": "MyShow",
                            "Name": "Episode One",
                        },
                        {
                            "Id": "mov1",
                            "Path": "/movies/mov.mkv",
                        },
                    ]
                }
            )
            client._http_client = mock_http

            ids, paths, names = await client.fetch_watched_episodes()
            assert "ep1" in ids
            assert "/shows/ep1.mkv" in paths
            assert ("myshow", "episode one") in names

        _run(run(), event_loop)


class TestSearchSeriesSuccess:
    """Lines 299-314: search_series with results."""

    def test_returns_items(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(return_value={"Items": [{"Name": "Found Show"}]})
            client._http_client = mock_http

            results = await client.search_series("Found")
            assert len(results) == 1
            assert results[0]["Name"] == "Found Show"

        _run(run(), event_loop)

    def test_exception_returns_empty(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(side_effect=Exception("network error"))
            client._http_client = mock_http

            results = await client.search_series("Test")
            assert results == []

        _run(run(), event_loop)


class TestSearchMovieSuccess:
    """Line 336: search_movie returns items."""

    def test_returns_items(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncJellyfinClient
    ) -> None:
        async def run() -> None:
            client._cached_user_id = "user123"
            mock_http = AsyncMock(spec=AsyncHTTPClient)
            mock_http.get = AsyncMock(return_value={"Items": [{"Name": "Found Movie"}]})
            client._http_client = mock_http

            results = await client.search_movie("Found")
            assert len(results) == 1

        _run(run(), event_loop)
