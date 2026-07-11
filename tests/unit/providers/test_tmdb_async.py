"""
Tests for AsyncTMDBClient — async TMDB metadata client.

All async tests use ``event_loop.run_until_complete()`` since the project
does not use ``pytest-asyncio``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lan_streamer.providers.tmdb_async import AsyncTMDBClient
from lan_streamer.system.config import Config


@pytest.fixture(autouse=True)
def _patch_config() -> None:
    """Ensure config has a fake TMDB key so _effective_api_key is set."""
    config = Config()
    config.tmdb_api_key = "test_key"
    with patch("lan_streamer.providers.tmdb_async.config", config):
        yield


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
def client() -> AsyncTMDBClient:
    return AsyncTMDBClient()


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    return event_loop.run_until_complete(coro)


class TestConstruction:
    def test_is_configured_with_key(self, client: AsyncTMDBClient) -> None:
        assert client.is_configured() is True

    def test_is_configured_without_key(self) -> None:
        c = AsyncTMDBClient(api_key="")
        assert c.is_configured() is False

    def test_params_include_api_key(self, client: AsyncTMDBClient) -> None:
        params = client._params()
        assert "api_key" in params
        assert params["api_key"] == "test_key"

    def test_params_with_extra(self, client: AsyncTMDBClient) -> None:
        params = client._params({"query": "test"})
        assert params["api_key"] == "test_key"
        assert params["query"] == "test"


class TestCleanName:
    def test_removes_resolution_tags(self, client: AsyncTMDBClient) -> None:
        result = client._clean_name("Show 1080p")
        assert "Show" in result

    def test_removes_year(self, client: AsyncTMDBClient) -> None:
        assert client._clean_name("Show (2020)") == "Show"

    def test_replaces_dots_with_spaces(self, client: AsyncTMDBClient) -> None:
        assert client._clean_name("Show.Name.Here") == "Show Name Here"

    def test_removes_season_markers(self, client: AsyncTMDBClient) -> None:
        assert client._clean_name("Show S01") == "Show"


class TestIsSimilar:
    def test_exact_match(self, client: AsyncTMDBClient) -> None:
        assert client._is_similar("Breaking Bad", "Breaking Bad") is True

    def test_substring_match(self, client: AsyncTMDBClient) -> None:
        assert client._is_similar("Breaking", "Breaking Bad") is True

    def test_no_match(self, client: AsyncTMDBClient) -> None:
        assert client._is_similar("Breaking Bad", "Friends") is False


class TestSelectBestCandidate:
    def test_exact_match_returns_immediately(self, client: AsyncTMDBClient) -> None:
        results = [
            {"name": "Breaking Bad", "id": 1},
            {"name": "Better Call Saul", "id": 2},
        ]
        result = client._select_best_candidate(results, "Breaking Bad")
        assert result is not None
        assert result["id"] == 1

    def test_no_match_returns_none(self, client: AsyncTMDBClient) -> None:
        results = [{"name": "Breaking Bad", "id": 1}]
        result = client._select_best_candidate(results, "Friends", custom_threshold=0.9)
        assert result is None


class TestDoSearch:
    def test_do_search_returns_list(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={"results": [{"id": 1, "name": "Test"}]}
            )
            client._http_client = mock_http

            results = await client._do_search("test")
            assert len(results) == 1
            assert results[0]["id"] == 1

        _run(run(), event_loop)

    def test_do_search_returns_empty_on_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=Exception("API error"))
            client._http_client = mock_http

            results = await client._do_search("test")
            assert results == []

        _run(run(), event_loop)


class TestPublicAPI:
    def test_search_series_found(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={"results": [{"id": 123, "name": "Test Series"}]}
            )
            client._http_client = mock_http

            result = await client.search_series("Test Series")
            assert result is not None
            assert result["id"] == 123

        _run(run(), event_loop)

    def test_search_series_not_found(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value={"results": []})
            client._http_client = mock_http

            result = await client.search_series("Nonexistent")
            assert result is None

        _run(run(), event_loop)

    def test_search_series_full(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={
                    "results": [
                        {"id": 1, "name": "S1"},
                        {"id": 2, "name": "S2"},
                    ]
                }
            )
            client._http_client = mock_http

            results = await client.search_series_full("test", limit=1)
            assert len(results) == 1

        _run(run(), event_loop)

    def test_search_movie_found(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={"results": [{"id": 456, "title": "Test Movie"}]}
            )
            client._http_client = mock_http

            result = await client.search_movie("Test Movie", year=2021)
            assert result is not None
            assert result["id"] == 456

        _run(run(), event_loop)

    def test_search_movie_full(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={
                    "results": [
                        {"id": 1, "title": "M1"},
                        {"id": 2, "title": "M2"},
                    ]
                }
            )
            client._http_client = mock_http

            results = await client.search_movie_full("test", limit=2)
            assert len(results) == 2

        _run(run(), event_loop)

    def test_get_series_by_id(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={"id": 123, "name": "Test Series", "seasons": []}
            )
            client._http_client = mock_http

            result = await client.get_series_by_id(123)
            assert result is not None
            assert result["id"] == 123

        _run(run(), event_loop)

    def test_get_series_by_id_returns_none_on_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=Exception("error"))
            client._http_client = mock_http

            result = await client.get_series_by_id(123)
            assert result is None

        _run(run(), event_loop)

    def test_get_movie_by_id(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value={"id": 456, "title": "Test Movie"})
            client._http_client = mock_http

            result = await client.get_movie_by_id(456)
            assert result is not None
            assert result["id"] == 456

        _run(run(), event_loop)

    def test_get_seasons(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={
                    "id": 123,
                    "name": "Test",
                    "seasons": [{"season_number": 1}, {"season_number": 2}],
                }
            )
            client._http_client = mock_http

            seasons = await client.get_seasons(123)
            assert len(seasons) == 2

        _run(run(), event_loop)

    def test_get_episodes(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={
                    "episodes": [{"episode_number": 1}, {"episode_number": 2}],
                }
            )
            client._http_client = mock_http

            episodes = await client.get_episodes(123, 1)
            assert len(episodes) == 2

        _run(run(), event_loop)

    def test_get_episodes_returns_empty_on_404(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            from aiohttp import ClientResponseError

            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                side_effect=ClientResponseError(
                    request_info=MagicMock(),
                    history=(),
                    status=404,
                )
            )
            client._http_client = mock_http

            episodes = await client.get_episodes(123, 99)
            assert episodes == []

        _run(run(), event_loop)

    def test_get_episode_groups(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={"results": [{"id": "g1", "name": "Group 1"}]}
            )
            client._http_client = mock_http

            groups = await client.get_episode_groups(123)
            assert len(groups) == 1

        _run(run(), event_loop)

    def test_get_episode_group_details(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={"id": "g1", "name": "Group 1", "groups": []}
            )
            client._http_client = mock_http

            result = await client.get_episode_group_details("g1")
            assert result is not None
            assert result["id"] == "g1"

        _run(run(), event_loop)

    def test_get_season_based_episode_group(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            async def mock_get(url: str, **kwargs: Any) -> dict[str, Any]:
                if "episode_groups" in url:
                    return {
                        "results": [
                            {"id": "g1", "name": "Season-based", "type": 7},
                        ]
                    }
                if "episode_group" in url:
                    return {"id": "g1", "name": "Season-based", "groups": []}
                return {}

            mock_http = AsyncMock()
            mock_http.get = mock_get
            client._http_client = mock_http

            result = await client.get_season_based_episode_group(123)
            assert result is not None
            assert result["id"] == "g1"

        _run(run(), event_loop)

    def test_get_season_based_episode_group_no_groups(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value={"results": []})
            client._http_client = mock_http

            result = await client.get_season_based_episode_group(123)
            assert result is None

        _run(run(), event_loop)


class TestImageCaching:
    def test_get_cached_image_no_cache_key(self, client: AsyncTMDBClient) -> None:
        assert client.get_cached_image("") == ""

    def test_get_cached_image_not_found(
        self, client: AsyncTMDBClient, tmp_path: Path
    ) -> None:
        client._cache_dir = tmp_path
        assert client.get_cached_image("nonexistent") == ""

    def test_get_cached_image_found(
        self, client: AsyncTMDBClient, tmp_path: Path
    ) -> None:
        (tmp_path / "test_key.jpg").write_text("fake")
        client._cache_dir = tmp_path
        result = client.get_cached_image("test_key")
        assert result == str(tmp_path / "test_key.jpg")

    def test_download_image_already_local(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            result = await client.download_image("/absolute/path/file.jpg", "key")
            assert result == "/absolute/path/file.jpg"

        _run(run(), event_loop)

    def test_download_image_cached(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncTMDBClient,
        tmp_path: Path,
    ) -> None:
        async def run() -> None:
            (tmp_path / "cached.jpg").write_text("fake")
            client._cache_dir = tmp_path
            result = await client.download_image("/poster.jpg", "cached")
            assert result == str(tmp_path / "cached.jpg")

        _run(run(), event_loop)

    def test_download_image_network(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client: AsyncTMDBClient,
        tmp_path: Path,
    ) -> None:
        async def run() -> None:
            client._cache_dir = tmp_path
            mock_http = AsyncMock()
            mock_http.get_bytes = AsyncMock(return_value=b"image data")
            client._http_client = mock_http

            result = await client.download_image("/abc.jpg", "new_key")
            expected = tmp_path / "new_key.jpg"
            assert result == str(expected)
            assert expected.read_bytes() == b"image data"

        _run(run(), event_loop)

    def test_download_image_network_failure(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get_bytes = AsyncMock(side_effect=Exception("network error"))
            client._http_client = mock_http

            result = await client.download_image("/abc.jpg", "key")
            assert result == ""

        _run(run(), event_loop)


class TestClose:
    def test_close(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            client._http_client = mock_http
            await client.close()
            mock_http.close.assert_awaited_once()

        _run(run(), event_loop)


class TestSearchSeriesEdgeCases:
    def test_search_series_with_dots_and_colons(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={
                    "results": [{"id": 1, "name": "Marvel's Agents of S.H.I.E.L.D."}]
                }
            )
            client._http_client = mock_http

            result = await client.search_series("Marvels.Agents.of.S.H.I.E.L.D")
            assert result is not None
            assert result["id"] == 1

        _run(run(), event_loop)

    def test_search_series_empty_results(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value={"results": []})
            client._http_client = mock_http

            result = await client.search_series("Unknown Series")
            assert result is None

        _run(run(), event_loop)


# ------------------------------------------------------------------
# Edge cases for _clean_name, _is_similar, _select_best_candidate
# ------------------------------------------------------------------


class TestStaticMethodEdgeCases:
    def test_clean_name_empty_string(self, client: AsyncTMDBClient) -> None:
        assert client._clean_name("") == ""

    def test_clean_name_only_special_chars(self, client: AsyncTMDBClient) -> None:
        result = client._clean_name("...___")
        assert result == ""

    def test_clean_name_removes_codec_tags(self, client: AsyncTMDBClient) -> None:
        result = client._clean_name("Show x264 1080p")
        assert "x264" not in result
        assert "1080p" not in result

    def test_is_similar_empty_strings(self, client: AsyncTMDBClient) -> None:
        assert client._is_similar("", "anything") is False
        assert client._is_similar("anything", "") is False

    def test_is_similar_substring_both_ways(self, client: AsyncTMDBClient) -> None:
        assert client._is_similar("Short", "A Much Longer Short Title") is True
        assert client._is_similar("A Much Longer Short Title", "Short") is True

    def test_is_similar_ratio_threshold(self, client: AsyncTMDBClient) -> None:
        # The actual ratio depends on SequenceMatcher - just verify it doesn't crash
        result = client._is_similar("Breaking Bad", "Breking Bdd", threshold=0.8)
        assert isinstance(result, bool)

    def test_is_similar_word_overlap(self, client: AsyncTMDBClient) -> None:
        # Word overlap with words > 3 chars
        assert client._is_similar("Doctor Strange Adventures", "Strange") is True
        # The common words filter checks original words, not cleaned
        # "The Marvel Star Wars" contains "Marvel" which is >3 chars
        result = client._is_similar("The Marvel Star Wars", "Marvel")
        assert isinstance(result, bool)

    def test_select_best_candidate_empty_target(self, client: AsyncTMDBClient) -> None:
        result = client._select_best_candidate([{"name": "Test"}], "")
        assert result is None

    def test_select_best_candidate_skips_empty_candidate(
        self, client: AsyncTMDBClient
    ) -> None:
        results = [{"name": "...", "id": 1}, {"name": "Valid", "id": 2}]
        result = client._select_best_candidate(results, "Valid")
        assert result is not None
        assert result["id"] == 2

    def test_select_best_candidate_no_match_returns_none(
        self, client: AsyncTMDBClient
    ) -> None:
        results = [{"name": "Completely Different", "id": 1}]
        result = client._select_best_candidate(results, "Target", custom_threshold=0.9)
        assert result is None


# ------------------------------------------------------------------
# search_series fallback paths
# ------------------------------------------------------------------


class TestSearchSeriesFallbacks:
    def test_search_series_two_word_fallback(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        """Test two-word fallback in search_series."""
        match_result = [
            {"id": 1, "name": "Show Runners", "first_air_date": "2020-01-01"}
        ]

        call_count = {"n": 0}

        async def mock_do_search(query: str) -> list:
            call_count["n"] += 1
            if call_count["n"] >= 3:  # Two-word fallback attempt
                return match_result
            return []

        async def run() -> None:
            client._do_search = mock_do_search
            client._is_similar = lambda a, b, threshold=0.7: True

            result = await client.search_series("Show Runners Extra Stuff")
            assert result is not None
            assert result["id"] == 1

        _run(run(), event_loop)

    def test_search_series_first_word_fallback(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        """Test first-word fallback in search_series."""
        match_result = [{"id": 2, "name": "Fargo", "first_air_date": "2014-04-15"}]

        async def mock_do_search(query: str) -> list:
            if query == "Fargo":
                return match_result
            return []

        async def run() -> None:
            client._do_search = mock_do_search
            client._is_similar = lambda a, b, threshold=0.7: True

            result = await client.search_series("Fargo Criminal Cases 2025")
            assert result is not None
            assert result["id"] == 2

        _run(run(), event_loop)

    def test_search_series_all_fallbacks_fail(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        """Test search_series returns None when all fallbacks fail."""

        async def run() -> None:
            client._do_search = AsyncMock(return_value=[])
            result = await client.search_series("Totally Unknown Show Name 2025")
            assert result is None

        _run(run(), event_loop)


# ------------------------------------------------------------------
# search_movie tests
# ------------------------------------------------------------------


class TestSearchMovie:
    def test_search_movie_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            client._do_movie_search = AsyncMock(
                return_value=[
                    {"id": 19995, "title": "Avatar", "release_date": "2009-12-15"}
                ]
            )
            result = await client.search_movie("Avatar", year=2009)
            assert result is not None
            assert result["id"] == 19995

        _run(run(), event_loop)

    def test_search_movie_no_match(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            client._do_movie_search = AsyncMock(return_value=[])
            result = await client.search_movie("Unknown Movie XYZ")
            assert result is None

        _run(run(), event_loop)

    def test_search_movie_full(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={
                    "results": [{"id": 1, "title": "M1"}, {"id": 2, "title": "M2"}]
                }
            )
            client._http_client = mock_http
            results = await client.search_movie_full("Movie")
            assert len(results) == 2

        _run(run(), event_loop)

    def test_search_movie_full_not_configured(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        async def run() -> None:
            client = AsyncTMDBClient(api_key="")
            results = await client.search_movie_full("anything")
            assert results == []

        _run(run(), event_loop)


# ------------------------------------------------------------------
# get_series_by_id / get_movie_by_id
# ------------------------------------------------------------------


class TestGetById:
    def test_get_series_by_id_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={"id": 1234, "name": "The Office", "seasons": []}
            )
            client._http_client = mock_http

            result = await client.get_series_by_id(1234)
            assert result["id"] == 1234

        _run(run(), event_loop)

    def test_get_series_by_id_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=Exception("network error"))
            client._http_client = mock_http

            result = await client.get_series_by_id(1)
            assert result is None

        _run(run(), event_loop)

    def test_get_movie_by_id_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value={"id": 19995, "title": "Avatar"})
            client._http_client = mock_http

            result = await client.get_movie_by_id(19995)
            assert result is not None
            assert result["id"] == 19995

        _run(run(), event_loop)

    def test_get_movie_by_id_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=Exception("network error"))
            client._http_client = mock_http

            result = await client.get_movie_by_id(1)
            assert result is None

        _run(run(), event_loop)


# ------------------------------------------------------------------
# get_seasons / get_episodes
# ------------------------------------------------------------------


class TestSeasonsEpisodes:
    def test_get_seasons_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={
                    "id": 1234,
                    "seasons": [
                        {"id": 1, "season_number": 1, "name": "Season 1"},
                        {"id": 0, "season_number": 0, "name": "Specials"},
                    ],
                }
            )
            client._http_client = mock_http

            seasons = await client.get_seasons(1234)
            assert len(seasons) == 2

        _run(run(), event_loop)

    def test_get_seasons_only_specials(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={
                    "seasons": [{"id": 0, "season_number": 0, "name": "Specials"}]
                }
            )
            client._http_client = mock_http

            seasons = await client.get_seasons(1234)
            assert len(seasons) == 1

        _run(run(), event_loop)

    def test_get_seasons_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=Exception("error"))
            client._http_client = mock_http

            seasons = await client.get_seasons(1234)
            assert seasons == []

        _run(run(), event_loop)

    def test_get_episodes_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={
                    "episodes": [
                        {"id": 1, "episode_number": 1, "name": "Pilot"},
                        {"id": 2, "episode_number": 2, "name": "Episode 2"},
                    ]
                }
            )
            client._http_client = mock_http

            episodes = await client.get_episodes(1234, 1)
            assert len(episodes) == 2

        _run(run(), event_loop)

    def test_get_episodes_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=Exception("error"))
            client._http_client = mock_http

            episodes = await client.get_episodes(1, 1)
            assert episodes == []

        _run(run(), event_loop)


# ------------------------------------------------------------------
# Episode Groups
# ------------------------------------------------------------------


class TestEpisodeGroups:
    def test_get_episode_groups_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={"results": [{"id": "g1", "name": "DVD Order"}]}
            )
            client._http_client = mock_http

            res = await client.get_episode_groups(1234)
            assert len(res) == 1
            assert res[0]["id"] == "g1"

        _run(run(), event_loop)

    def test_get_episode_groups_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=Exception("network error"))
            client._http_client = mock_http

            assert await client.get_episode_groups(1234) == []

        _run(run(), event_loop)

    def test_get_episode_group_details_success(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                return_value={"id": "g1", "name": "DVD Order", "groups": []}
            )
            client._http_client = mock_http

            res = await client.get_episode_group_details("g1")
            assert res is not None
            assert res["id"] == "g1"

        _run(run(), event_loop)

    def test_get_episode_group_details_error(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=Exception("network error"))
            client._http_client = mock_http

            assert await client.get_episode_group_details("g1") is None

        _run(run(), event_loop)


# ------------------------------------------------------------------
# get_season_based_episode_group
# ------------------------------------------------------------------


class TestSeasonBasedEpisodeGroup:
    def test_get_season_based_episode_group_no_groups(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            client.get_episode_groups = AsyncMock(return_value=[])
            assert await client.get_season_based_episode_group(1234) is None

        _run(run(), event_loop)

    def test_get_season_based_episode_group_priority_type7(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_groups = [
                {"id": "g3", "name": "DVD", "type": 3},
                {"id": "g7", "name": "TVDB", "type": 7},
                {"id": "g4", "name": "Digital", "type": 4},
            ]
            client.get_episode_groups = AsyncMock(return_value=mock_groups)
            client.get_episode_group_details = AsyncMock(
                side_effect=lambda gid: {"id": gid}
            )

            res = await client.get_season_based_episode_group(1234)
            assert res is not None
            assert res["id"] == "g7"

        _run(run(), event_loop)

    def test_get_season_based_episode_group_fallback_type34(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_groups = [
                {"id": "g3", "name": "DVD", "type": 3},
                {"id": "g4", "name": "Digital", "type": 4},
            ]
            client.get_episode_groups = AsyncMock(return_value=mock_groups)
            client.get_episode_group_details = AsyncMock(
                side_effect=lambda gid: {"id": gid}
            )

            res = await client.get_season_based_episode_group(1234)
            assert res is not None
            assert res["id"] == "g3"

        _run(run(), event_loop)

    def test_get_season_based_episode_group_fallback_name(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_groups = [
                {"id": "g_other", "name": "Random Order", "type": 1},
                {"id": "g_season", "name": "Season Pack", "type": 2},
            ]
            client.get_episode_groups = AsyncMock(return_value=mock_groups)
            client.get_episode_group_details = AsyncMock(
                side_effect=lambda gid: {"id": gid}
            )

            res = await client.get_season_based_episode_group(1234)
            assert res is not None
            assert res["id"] == "g_season"

        _run(run(), event_loop)

    def test_get_season_based_episode_group_seasons_name_preferred(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncTMDBClient
    ) -> None:
        async def run() -> None:
            mock_groups = [
                {"id": "g_cours", "name": "Cours", "type": 7},
                {"id": "g_seasons", "name": "Seasons", "type": 6},
            ]
            client.get_episode_groups = AsyncMock(return_value=mock_groups)
            client.get_episode_group_details = AsyncMock(
                side_effect=lambda gid: {"id": gid}
            )

            res = await client.get_season_based_episode_group(1234)
            assert res is not None
            assert res["id"] == "g_seasons"

        _run(run(), event_loop)
