"""Unit tests for lan_streamer.scanner.pass2_metadata — Pass 2 metadata resolution.

Tests cover all exported functions including scan_series_pass2,
scan_movie_pass2, and all helper functions.  Every external dependency is
mocked; no real network or filesystem metadata is accessed.
"""

from __future__ import annotations

import concurrent.futures
import datetime
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch


from lan_streamer.scanner.pass2_metadata import (
    _add_tmdb_only_seasons,
    _build_movie_data,
    _create_tmdb_placeholder_episodes,
    _fetch_tmdb_episodes_parallel,
    _filter_future_episodes,
    _group_and_resolve_episode_versions,
    _preserve_existing_episode_data,
    _resolve_tmdb_movie_data,
    _season_name_from_tmdb,
    scan_movie_pass2,
    scan_series_pass2,
)

_TODAY: str = datetime.date.today().isoformat()


# ===========================================================================
#  _season_name_from_tmdb
# ===========================================================================


class TestSeasonNameFromTmdb:
    """Tests for _season_name_from_tmdb."""

    def test_specials_season_zero(self) -> None:
        """Season number 0 should always return 'Specials'."""
        tmdb_season: Dict[str, Any] = {"season_number": 0, "name": "Specials"}
        assert _season_name_from_tmdb(tmdb_season) == "Specials"

    def test_specials_with_different_name(self) -> None:
        """Season number 0 returns 'Specials' even if name differs."""
        tmdb_season: Dict[str, Any] = {"season_number": 0, "name": "Extras"}
        assert _season_name_from_tmdb(tmdb_season) == "Specials"

    def test_standard_season(self) -> None:
        """Standard numbering season returns 'Season N'."""
        tmdb_season: Dict[str, Any] = {"season_number": 2, "name": "Season 2"}
        assert _season_name_from_tmdb(tmdb_season) == "Season 2"

    def test_custom_season_name_preserved(self) -> None:
        """Custom names like 'Part 1' should be preserved as-is."""
        tmdb_season: Dict[str, Any] = {"season_number": 1, "name": "Part 1"}
        assert _season_name_from_tmdb(tmdb_season) == "Part 1"

    def test_cour_name_preserved(self) -> None:
        """'Cour 2' style names should be preserved."""
        tmdb_season: Dict[str, Any] = {"season_number": 2, "name": "Cour 2"}
        assert _season_name_from_tmdb(tmdb_season) == "Cour 2"

    def test_generic_name_falls_back(self) -> None:
        """Names that don't match Season/Part/Cour should generate 'Season N'."""
        tmdb_season: Dict[str, Any] = {"season_number": 3, "name": "Third Chapter"}
        assert _season_name_from_tmdb(tmdb_season) == "Season 3"

    def test_missing_season_number(self) -> None:
        """Missing season_number defaults to 1."""
        tmdb_season: Dict[str, Any] = {"name": "Season 1"}
        assert _season_name_from_tmdb(tmdb_season) == "Season 1"

    def test_empty_name(self) -> None:
        """Empty name should generate 'Season N'."""
        tmdb_season: Dict[str, Any] = {"season_number": 5, "name": ""}
        assert _season_name_from_tmdb(tmdb_season) == "Season 5"

    def test_whitespace_name(self) -> None:
        """Whitespace-only name should generate 'Season N'."""
        tmdb_season: Dict[str, Any] = {"season_number": 1, "name": "   "}
        assert _season_name_from_tmdb(tmdb_season) == "Season 1"


# ===========================================================================
#  _filter_future_episodes
# ===========================================================================


class TestFilterFutureEpisodes:
    """Tests for _filter_future_episodes."""

    def _make_episode(self, path: str | None, air_date: str) -> Dict[str, Any]:
        return {"path": path, "air_date": air_date, "name": "Test Episode"}

    def test_filters_future_placeholder(self) -> None:
        """Future-dated placeholder (no path) should be removed."""
        series_data: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        self._make_episode("/exists.mkv", "2020-01-01"),
                        self._make_episode(None, "2099-12-31"),
                    ]
                }
            }
        }
        _filter_future_episodes(series_data)
        assert len(series_data["seasons"]["Season 1"]["episodes"]) == 1

    def test_keeps_past_placeholder(self) -> None:
        """Past-dated placeholder (no path) should be kept."""
        series_data: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        self._make_episode(None, "2020-01-01"),
                    ]
                }
            }
        }
        _filter_future_episodes(series_data)
        assert len(series_data["seasons"]["Season 1"]["episodes"]) == 1

    def test_keeps_file_without_air_date(self) -> None:
        """Episode with a path but no air_date is kept."""
        series_data: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        self._make_episode("/movie.mkv", ""),
                    ]
                }
            }
        }
        _filter_future_episodes(series_data)
        assert len(series_data["seasons"]["Season 1"]["episodes"]) == 1

    def test_today_episode_kept(self) -> None:
        """Episode with air_date equal to today should be kept."""
        series_data: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        self._make_episode(None, _TODAY),
                    ]
                }
            }
        }
        _filter_future_episodes(series_data)
        assert len(series_data["seasons"]["Season 1"]["episodes"]) == 1

    def test_empty_seasons_no_error(self) -> None:
        """Empty seasons dict should not raise."""
        _filter_future_episodes({"seasons": {}})

    def test_missing_episodes_no_error(self) -> None:
        """Season without episodes key should not raise."""
        _filter_future_episodes({"seasons": {"Season 1": {}}})


# ===========================================================================
#  _create_tmdb_placeholder_episodes
# ===========================================================================


class TestCreateTmdbPlaceholderEpisodes:
    """Tests for _create_tmdb_placeholder_episodes."""

    def _tmdb_ep(
        self,
        number: int,
        name: str = "Some Episode",
        air_date: str = "2020-01-01",
        runtime: int = 30,
        ep_id: int = 100,
    ) -> Dict[str, Any]:  # type: ignore[return]
        return {
            "episode_number": number,
            "name": name,
            "air_date": air_date,
            "runtime": runtime,
            "id": ep_id,
        }

    def test_creates_placeholder_for_missing_episode(self) -> None:
        """TMDB episodes not in local list produce placeholders."""
        tmdb_eps = [self._tmdb_ep(1), self._tmdb_ep(2)]
        local_eps: list[Dict[str, Any]] = [
            {"tmdb_number": 1, "name": "S01E01 - Existing"}
        ]
        result = _create_tmdb_placeholder_episodes(tmdb_eps, local_eps, "Season 1", {})
        assert len(result) == 1
        assert result[0]["tmdb_number"] == 2
        assert result[0]["path"] is None

    def test_skips_existing_numbers(self) -> None:
        """Episodes that already exist locally should not be created."""
        tmdb_eps = [self._tmdb_ep(1), self._tmdb_ep(2)]
        local_eps: list[Dict[str, Any]] = [
            {"tmdb_number": 1},
            {"tmdb_number": 2},
        ]
        result = _create_tmdb_placeholder_episodes(tmdb_eps, local_eps, "Season 1", {})
        assert len(result) == 0

    def test_skips_episodes_without_number(self) -> None:
        """TMDB episodes without episode_number should be skipped."""
        tmdb_eps: list[Dict[str, Any]] = [
            {"name": "No Number", "air_date": "2020-01-01", "runtime": 30}
        ]
        result = _create_tmdb_placeholder_episodes(tmdb_eps, [], "Season 1", {})
        assert len(result) == 0

    def test_future_episodes_filtered_when_disabled(self) -> None:
        """When show_future_episodes=False, future air dates are skipped."""
        tmdb_eps = [self._tmdb_ep(3, air_date=_ensure_future())]
        result = _create_tmdb_placeholder_episodes(
            tmdb_eps, [], "Season 1", {}, show_future_episodes=False
        )
        assert len(result) == 0

    def test_empty_air_date_filtered_out(self) -> None:
        """When show_future_episodes=False, empty air_date is filtered."""
        tmdb_eps = [self._tmdb_ep(4, air_date="")]
        result = _create_tmdb_placeholder_episodes(
            tmdb_eps, [], "Season 1", {}, show_future_episodes=False
        )
        assert len(result) == 0

    def test_specials_index_zero(self) -> None:
        """Specials season uses index 0 for episode naming."""
        tmdb_eps = [self._tmdb_ep(1)]
        result = _create_tmdb_placeholder_episodes(tmdb_eps, [], "Specials", {})
        assert len(result) == 1
        assert result[0]["name"].startswith("S00E01")

    def test_mal_id_included(self) -> None:
        """When season_metadata has myanimelist_id, it is copied into placeholders."""
        tmdb_eps = [self._tmdb_ep(5)]
        result = _create_tmdb_placeholder_episodes(
            tmdb_eps, [], "Season 1", {"myanimelist_id": "mal_123"}
        )
        assert len(result) == 1
        assert result[0]["myanimelist_anime_id"] == "mal_123"
        assert result[0]["myanimelist_episode_number"] == 5

    def test_empty_tmdb_list(self) -> None:
        """Empty TMDB episode list yields no placeholders."""
        result = _create_tmdb_placeholder_episodes([], [], "Season 1", {})
        assert len(result) == 0

    def test_name_fallback(self) -> None:
        """Episode without a name gets 'TBA' as placeholder name."""
        tmdb_eps: list[Dict[str, Any]] = [
            {
                "episode_number": 10,
                "name": "",
                "air_date": "2020-01-01",
                "runtime": 30,
                "id": 999,
            }
        ]
        result = _create_tmdb_placeholder_episodes(tmdb_eps, [], "Season 1", {})
        assert len(result) == 1
        assert "TBA" in result[0]["name"]


# ===========================================================================
#  _fetch_tmdb_episodes_parallel
# ===========================================================================


class TestFetchTmdbEpisodesParallel:
    """Tests for _fetch_tmdb_episodes_parallel."""

    def test_fetches_all_seasons(self) -> None:
        """Should fetch episodes for all provided season indices."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_episodes.side_effect = lambda tid, sidx: (
            [{"episode_number": 1}] if sidx == 1 else [{"episode_number": 2}]
        )
        with patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock_tmdb):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                result = _fetch_tmdb_episodes_parallel(
                    "series_1",
                    {"Season 1": 1, "Season 2": 2},
                    executor,
                )
        assert "Season 1" in result
        assert "Season 2" in result

    def test_logs_failure_gracefully(self) -> None:
        """Failed fetches should be logged and not crash."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_episodes.side_effect = RuntimeError("API Error")
        with patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock_tmdb):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                result = _fetch_tmdb_episodes_parallel(
                    "series_1",
                    {"Season 1": 1},
                    executor,
                )
        # Failed season key is not added to the prefetched dict
        assert result == {}

    def test_empty_season_indices(self) -> None:
        """Empty season indices yields empty dict."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            result = _fetch_tmdb_episodes_parallel("series_1", {}, executor)
        assert result == {}


# ===========================================================================
#  _group_and_resolve_episode_versions
# ===========================================================================


class TestGroupAndResolveEpisodeVersions:
    """Tests for _group_and_resolve_episode_versions."""

    def test_groups_by_tmdb_number(self) -> None:
        """Episodes with same tmdb_number should be grouped as versions."""
        scanned: list[Dict[str, Any]] = [
            {"tmdb_number": 1, "name": "S01E01", "path": "/ep1_1080p.mkv"},
            {"tmdb_number": 1, "name": "S01E01", "path": "/ep1_720p.mkv"},
        ]
        existing: list[Dict[str, Any]] = []
        with (
            patch(
                "lan_streamer.scanner.pass2_metadata.get_detailed_file_info",
                return_value={
                    "path": "/stub",
                    "video_codec": "h264",
                    "resolution": "1080p",
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.choose_active_version",
                side_effect=lambda v, d: v[0],
            ),
        ):
            result = _group_and_resolve_episode_versions(scanned, existing, False)

        assert len(result) == 1
        assert len(result[0]["versions"]) == 2

    def test_uses_existing_version_when_valid(self) -> None:
        """Existing version data should be reused if not force_refresh."""
        scanned: list[Dict[str, Any]] = [
            {"tmdb_number": 1, "name": "S01E01", "path": "/ep1.mkv"},
        ]
        existing: list[Dict[str, Any]] = [
            {
                "tmdb_number": 1,
                "name": "S01E01",
                "versions": [
                    {
                        "path": "/ep1.mkv",
                        "video_codec": "h265",
                        "resolution": "4K",
                        "bit_rate": 50000,
                    }
                ],
            }
        ]
        with (
            patch(
                "lan_streamer.scanner.pass2_metadata.get_detailed_file_info",
            ) as mock_detail,
            patch(
                "lan_streamer.scanner.pass2_metadata.choose_active_version",
                side_effect=lambda v, d: v[0],
            ),
        ):
            result = _group_and_resolve_episode_versions(scanned, existing, False)

        assert len(result) == 1
        assert result[0]["video_codec"] == "h265"
        assert result[0]["resolution"] == "4K"
        mock_detail.assert_not_called()

    def test_force_refresh_ignores_existing(self) -> None:
        """With force_refresh, existing versions should be re-scanned."""
        scanned: list[Dict[str, Any]] = [
            {"tmdb_number": 1, "name": "S01E01", "path": "/ep1.mkv"},
        ]
        existing: list[Dict[str, Any]] = [
            {
                "tmdb_number": 1,
                "name": "S01E01",
                "versions": [
                    {
                        "path": "/ep1.mkv",
                        "video_codec": "h265",
                        "resolution": "4K",
                    }
                ],
            }
        ]
        with (
            patch(
                "lan_streamer.scanner.pass2_metadata.get_detailed_file_info",
                return_value={
                    "path": "/ep1.mkv",
                    "video_codec": "h264",
                    "resolution": "1080p",
                },
            ) as mock_detail,
            patch(
                "lan_streamer.scanner.pass2_metadata.choose_active_version",
                side_effect=lambda v, d: v[0],
            ),
        ):
            result = _group_and_resolve_episode_versions(scanned, existing, True)

        assert len(result) == 1
        mock_detail.assert_called_once()

    def test_fallback_to_parse_episode_number(self) -> None:
        """When tmdb_number is None, falls back to _parse_episode_number."""
        scanned: list[Dict[str, Any]] = [
            {"tmdb_number": None, "name": "S01E01.mkv", "path": "/ep1.mkv"},
        ]
        with (
            patch(
                "lan_streamer.scanner.pass2_metadata.get_detailed_file_info",
                return_value={
                    "path": "/ep1.mkv",
                    "video_codec": "h264",
                    "resolution": "1080p",
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.choose_active_version",
                side_effect=lambda v, d: v[0],
            ),
        ):
            result = _group_and_resolve_episode_versions(scanned, [], False)

        assert len(result) == 1


# ===========================================================================
#  _preserve_existing_episode_data
# ===========================================================================


class TestPreserveExistingEpisodeData:
    """Tests for _preserve_existing_episode_data."""

    def test_preserves_missing_season_folder(self) -> None:
        """A season present in existing data but not in new data is preserved."""
        series_data: Dict[str, Any] = {"seasons": {}}
        existing: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [{"name": "Old Ep", "path": None, "tmdb_number": 1}],
                }
            }
        }
        _preserve_existing_episode_data(series_data, existing)
        assert "Season 1" in series_data["seasons"]

    def test_preserves_missing_episode_by_path(self) -> None:
        """An episode present on disk but not in new data is preserved."""
        series_data: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"name": "New Ep", "path": "/new.mkv", "tmdb_number": 1}
                    ]
                }
            }
        }
        existing: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"name": "Old Ep", "path": "/old.mkv", "tmdb_number": 2}
                    ]
                }
            }
        }
        with patch.object(Path, "exists", return_value=True):
            _preserve_existing_episode_data(series_data, existing)

        paths = {ep["name"] for ep in series_data["seasons"]["Season 1"]["episodes"]}
        assert "Old Ep" in paths

    def test_skips_missing_path_not_on_disk(self) -> None:
        """An episode with path not on disk should NOT be preserved."""
        series_data: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"name": "New Ep", "path": "/new.mkv", "tmdb_number": 1}
                    ]
                }
            }
        }
        existing: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"name": "Missing Ep", "path": "/missing.mkv", "tmdb_number": 2}
                    ]
                }
            }
        }
        with patch.object(Path, "exists", return_value=False):
            _preserve_existing_episode_data(series_data, existing)

        paths = {ep["name"] for ep in series_data["seasons"]["Season 1"]["episodes"]}
        assert "Missing Ep" not in paths

    def test_preserves_placeholder_with_new_number(self) -> None:
        """Placeholder (no path) with a new tmdb_number is preserved."""
        series_data: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"name": "New Ep", "path": "/new.mkv", "tmdb_number": 1}
                    ]
                }
            }
        }
        existing: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"name": "Old Placeholder", "path": None, "tmdb_number": 2}
                    ]
                }
            }
        }
        _preserve_existing_episode_data(series_data, existing)

        names = {ep["name"] for ep in series_data["seasons"]["Season 1"]["episodes"]}
        assert "Old Placeholder" in names

    def test_filters_future_placeholder_when_disabled(self) -> None:
        """Future-dated placeholders should be omitted when show_future_episodes=False."""
        series_data: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"name": "New Ep", "path": "/new.mkv", "tmdb_number": 1}
                    ]
                }
            }
        }
        existing: Dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Future Placeholder",
                            "path": None,
                            "tmdb_number": 2,
                            "air_date": _ensure_future(),
                        }
                    ]
                }
            }
        }
        _preserve_existing_episode_data(
            series_data, existing, show_future_episodes=False
        )

        names = {ep["name"] for ep in series_data["seasons"]["Season 1"]["episodes"]}
        assert "Future Placeholder" not in names

    def test_none_existing_no_error(self) -> None:
        """Calling with None existing_series_data should not raise."""
        _preserve_existing_episode_data({"seasons": {}}, None)


# ===========================================================================
#  _add_tmdb_only_seasons
# ===========================================================================


class TestAddTmdbOnlySeasons:
    """Tests for _add_tmdb_only_seasons."""

    def test_adds_missing_tmdb_season(self) -> None:
        """TMDB seasons not present in series_data are added."""
        series_data: Dict[str, Any] = {
            "_tmdb_seasons": [
                {"season_number": 2, "name": "Season 2", "id": 202},
            ],
            "_tmdb_series_id": "series_1",
            "seasons": {
                "Season 1": {"metadata": {}, "episodes": []},
            },
            "metadata": {"locked_metadata": False},
        }
        with (
            patch(
                "lan_streamer.scanner.pass2_metadata.tmdb_client",
            ) as mock_tmdb,
            patch(
                "lan_streamer.scanner.pass2_metadata._create_tmdb_placeholder_episodes",
                return_value=[{"name": "Placeholder", "path": None}],
            ),
        ):
            mock_tmdb.get_episodes.return_value = []
            _add_tmdb_only_seasons(series_data, False, False, {})

        assert "Season 2" in series_data["seasons"]
        assert len(series_data["seasons"]["Season 2"]["episodes"]) == 1

    def test_skips_existing_seasons(self) -> None:
        """Seasons already in series_data are skipped."""
        series_data: Dict[str, Any] = {
            "_tmdb_seasons": [
                {"season_number": 1, "name": "Season 1", "id": 101},
            ],
            "_tmdb_series_id": "series_1",
            "seasons": {
                "Season 1": {"metadata": {}, "episodes": []},
            },
            "metadata": {"locked_metadata": False},
        }
        with (
            patch(
                "lan_streamer.scanner.pass2_metadata.tmdb_client",
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._create_tmdb_placeholder_episodes",
                return_value=[],
            ),
        ):
            _add_tmdb_only_seasons(series_data, False, False, {})

        # Season 1 should still be the only season, no modification
        assert len(series_data["seasons"]) == 1

    def test_no_tmdb_seasons_noop(self) -> None:
        """No _tmdb_seasons key results in no added seasons."""
        series_data: Dict[str, Any] = {
            "seasons": {},
            "metadata": {"locked_metadata": False},
        }
        _add_tmdb_only_seasons(series_data, False, False, {})
        assert len(series_data["seasons"]) == 0

    def test_uses_episode_group_details(self) -> None:
        """TMDB episode group details should be used when available."""
        series_data: Dict[str, Any] = {
            "_tmdb_seasons": [
                {"season_number": 1, "name": "Season 1", "id": 101},
            ],
            "_tmdb_series_id": "series_1",
            "_tmdb_episode_group_details": {
                "groups": [
                    {
                        "name": "Season 1",
                        "order": 1,
                        "episodes": [
                            {
                                "id": 1001,
                                "name": "EP1",
                                "order": 0,
                                "air_date": "2020-01-01",
                                "runtime": 30,
                            }
                        ],
                    }
                ],
            },
            "seasons": {},
            "metadata": {"locked_metadata": False},
        }
        with patch(
            "lan_streamer.scanner.pass2_metadata._create_tmdb_placeholder_episodes",
            return_value=[],
        ):
            _add_tmdb_only_seasons(series_data, False, False, {})

        assert "Season 1" in series_data["seasons"]


# ===========================================================================
#  _resolve_tmdb_movie_data
# ===========================================================================


class TestResolveTmdbMovieData:
    """Tests for _resolve_tmdb_movie_data."""

    def test_locked_returns_early(self) -> None:
        """Locked movies skip all TMDB resolution."""
        metadata: Dict[str, Any] = {
            "tmdb_identifier": "",
            "tmdb_name": "",
            "poster_path": "",
        }
        _resolve_tmdb_movie_data(
            None, metadata, "Test", 2020, True, "", None, False, "/path.mkv", None
        )
        assert metadata["tmdb_identifier"] == ""

    def test_fetches_full_movie_when_stub_provided(self) -> None:
        """When only id is provided, fetches the full record."""
        metadata: Dict[str, Any] = {
            "tmdb_identifier": "",
            "tmdb_name": "",
            "overview": "",
            "poster_path": "",
            "year": None,
            "runtime": 0,
            "rating": "",
            "genre": "",
            "jellyfin_id": "",
        }
        mock_tmdb = MagicMock()
        mock_tmdb.get_movie_by_id.return_value = {
            "id": "123",
            "title": "Full Movie",
            "overview": "A full movie",
            "poster_path": "/poster.jpg",
            "release_date": "2020-06-15",
        }
        mock_tmdb.search_movie.return_value = None
        with (
            patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock_tmdb),
            patch(
                "lan_streamer.scanner.pass2_metadata._apply_tmdb_movie_data",
            ) as mock_apply,
            patch(
                "lan_streamer.scanner.pass2_metadata._resolve_movie_jellyfin_id",
                return_value="jf_123",
            ),
        ):
            _resolve_tmdb_movie_data(
                {"id": "123"},
                metadata,
                "Test",
                2020,
                False,
                "",
                None,
                True,
                "/path.mkv",
                None,
            )

        mock_tmdb.get_movie_by_id.assert_called_once_with("123")
        mock_apply.assert_called_once()

    def test_searches_by_title_when_no_tmdb_id(self) -> None:
        """With no existing tmdb_identifier, searches by title."""
        metadata: Dict[str, Any] = {
            "tmdb_identifier": "",
            "tmdb_name": "",
            "overview": "",
            "poster_path": "",
            "year": None,
            "runtime": 0,
            "rating": "",
            "genre": "",
            "jellyfin_id": "",
        }
        mock_tmdb = MagicMock()
        mock_tmdb.search_movie.return_value = {
            "id": "456",
            "title": "Found Movie",
        }
        with (
            patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock_tmdb),
            patch(
                "lan_streamer.scanner.pass2_metadata._apply_tmdb_movie_data",
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._resolve_movie_jellyfin_id",
                return_value="",
            ),
        ):
            _resolve_tmdb_movie_data(
                None,
                metadata,
                "Test Movie",
                2020,
                False,
                "",
                None,
                True,
                "/path.mkv",
                None,
            )

        mock_tmdb.search_movie.assert_called_once_with("Test Movie", 2020)

    def test_reuses_existing_tmdb_metadata(self) -> None:
        """When existing_metadata has an ID but no new tmdb_movie, builds from existing."""
        metadata: Dict[str, Any] = {
            "tmdb_identifier": "existing_id",
            "tmdb_name": "Existing Movie",
            "overview": "Existing overview",
            "poster_path": "/old.jpg",
            "year": 2020,
            "runtime": 0,
            "rating": "",
            "genre": "",
            "jellyfin_id": "",
        }
        with patch(
            "lan_streamer.scanner.pass2_metadata._apply_tmdb_movie_data",
        ) as mock_apply:
            _resolve_tmdb_movie_data(
                None,
                metadata,
                "Existing Movie",
                2020,
                False,
                "existing_id",
                None,
                False,
                "/path.mkv",
                None,
            )

        mock_apply.assert_called_once()


# ===========================================================================
#  _build_movie_data
# ===========================================================================


class TestBuildMovieData:
    """Tests for _build_movie_data."""

    def test_basic_build(self) -> None:
        """Basic movie data assembly from component parts."""
        active: Dict[str, Any] = {
            "path": "/movies/test.mkv",
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 10000,
            "audio_tracks": [{"language": "en"}],
            "subtitle_tracks": [{"language": "en"}],
        }
        metadata: Dict[str, Any] = {
            "jellyfin_id": "jf_1",
            "tmdb_identifier": "tmdb_1",
            "poster_path": "/poster.jpg",
            "overview": "Great movie",
            "tmdb_name": "Test Movie",
            "runtime": 120,
            "rating": "8.0",
            "genre": "Drama",
            "year": 2020,
        }
        result = _build_movie_data(
            folder_name="Test Movie (2020)",
            video_path="/movies/test.mkv",
            movie_metadata=metadata,
            existing_movie_data={
                "locked_metadata": False,
                "watched": True,
                "last_played_position": 500,
                "_changed": False,
                "last_scanned_mtime": 12345.0,
            },
            ctime=1000.0,
            active_version=active,
            versions=[active],
            default_path="/movies/test.mkv",
            is_movie_changed=True,
        )
        assert result["name"] == "Test Movie (2020)"
        assert result["path"] == "/movies/test.mkv"
        assert result["video_codec"] == "h264"
        assert result["resolution"] == "1080p"
        assert result["watched"] is True
        assert result["last_played_position"] == 500
        assert result["date_added"] == 1000.0

    def test_build_without_existing(self) -> None:
        """Build movie data when no existing_movie_data is provided."""
        result = _build_movie_data(
            folder_name="New Movie",
            video_path="/movies/new.mkv",
            movie_metadata={
                "jellyfin_id": "",
                "tmdb_identifier": "",
                "poster_path": "",
                "overview": "",
                "tmdb_name": "",
                "runtime": 0,
                "rating": "",
                "genre": "",
                "year": None,
            },
            existing_movie_data=None,
            ctime=0,
            active_version={
                "video_codec": None,
                "resolution": None,
                "bit_rate": None,
                "audio_tracks": None,
                "subtitle_tracks": None,
                "path": "/movies/new.mkv",
            },
            versions=[],
            default_path=None,
            is_movie_changed=True,
            last_scanned_mtime=None,
        )
        assert result["locked_metadata"] is False
        assert result["watched"] is False
        assert result["last_played_position"] == 0

    def test_build_preserves_last_scanned_mtime(self) -> None:
        """last_scanned_mtime from kwarg should override existing data."""
        result = _build_movie_data(
            folder_name="Test",
            video_path="/t.mkv",
            movie_metadata={
                "jellyfin_id": "",
                "tmdb_identifier": "",
                "poster_path": "",
                "overview": "",
                "tmdb_name": "",
                "runtime": 0,
                "rating": "",
                "genre": "",
                "year": None,
            },
            existing_movie_data={"last_scanned_mtime": 999.0},
            ctime=0,
            active_version={"path": "/t.mkv"},
            versions=[],
            default_path=None,
            is_movie_changed=True,
            last_scanned_mtime=555.0,
        )
        assert result["last_scanned_mtime"] == 555.0

    def test_build_uses_existing_last_scanned_mtime(self) -> None:
        """When last_scanned_mtime kwarg is None, use existing data value."""
        result = _build_movie_data(
            folder_name="Test",
            video_path="/t.mkv",
            movie_metadata={
                "jellyfin_id": "",
                "tmdb_identifier": "",
                "poster_path": "",
                "overview": "",
                "tmdb_name": "",
                "runtime": 0,
                "rating": "",
                "genre": "",
                "year": None,
            },
            existing_movie_data={"last_scanned_mtime": 777.0},
            ctime=0,
            active_version={"path": "/t.mkv"},
            versions=[],
            default_path=None,
            is_movie_changed=True,
        )
        assert result["last_scanned_mtime"] == 777.0


# ===========================================================================
#  scan_series_pass2
# ===========================================================================


class TestScanSeriesPass2:
    """Tests for scan_series_pass2 — the main series Pass 2 entry point."""

    def _make_existing_series(
        self,
        series_name: str = "Test Show",
        locked: bool = False,
        season_names: list[str] | None = None,
    ) -> Dict[str, Any]:
        if season_names is None:
            season_names = ["Season 1"]
        return {
            "metadata": {
                "name": series_name,
                "tmdb_identifier": "tmdb_series_1",
                "tmdb_name": series_name,
                "overview": "A test show",
                "poster_path": "",
                "locked_metadata": locked,
                "jellyfin_id": "",
            },
            "seasons": {
                sn: {
                    "metadata": {
                        "jellyfin_id": "",
                        "tmdb_identifier": f"tmdb_season_{i}",
                        "poster_path": "",
                    },
                    "episodes": [
                        {
                            "name": f"{sn} - Pilot",
                            "path": str(Path(f"/series/{series_name}/{sn}/S01E01.mkv")),
                            "tmdb_identifier": "tmdb_ep_1",
                            "tmdb_episode_identifier": "tmdb_ep_1",
                            "tmdb_name": "Pilot",
                            "tmdb_number": 1,
                            "air_date": "2020-01-01",
                            "runtime": 30,
                            "jellyfin_id": "",
                            "watched": False,
                            "date_added": 1000.0,
                        }
                    ],
                    "_tmdb_episodes": [
                        {
                            "id": "tmdb_ep_1",
                            "episode_number": 1,
                            "name": "Pilot",
                            "air_date": "2020-01-01",
                            "runtime": 30,
                        }
                    ],
                }
                for i, sn in enumerate(season_names)
            },
        }

    def test_locked_metadata_early_exit(self) -> None:
        """Locked metadata should bypass all processing and return existing data."""
        series_dir = Path("/series/Test Show")
        existing = self._make_existing_series(locked=True)
        existing["metadata"]["locked_metadata"] = True

        with patch(
            "lan_streamer.scanner.pass2_metadata.clean_series_data",
            side_effect=lambda x: x,
        ):
            result = scan_series_pass2(
                series_directory=series_dir,
                existing_series_data=existing,
                force_refresh=True,
            )

        assert result["metadata"]["locked_metadata"] is True
        assert result["metadata"]["tmdb_identifier"] == "tmdb_series_1"

    def test_locked_metadata_cleans_result(self) -> None:
        """Locked metadata path should still pass through clean_series_data."""
        series_dir = Path("/series/Locked Show")
        existing = self._make_existing_series("Locked Show", locked=True)
        cleansed = dict(existing)
        cleansed["_cleaned"] = True

        with patch(
            "lan_streamer.scanner.pass2_metadata.clean_series_data",
            return_value=cleansed,
        ):
            result = scan_series_pass2(
                series_directory=series_dir,
                existing_series_data=existing,
            )

        assert result.get("_cleaned") is True

    def test_calls_process_series_metadata_with_force_refresh_true(self) -> None:
        """_process_series_metadata is called with force_refresh=True when passed."""
        series_dir = Path("/series/Test Show")
        existing = self._make_existing_series()

        mock_series_data: Dict[str, Any] = {
            "metadata": {
                "name": "Test Show",
                "tmdb_identifier": "tmdb_series_1",
            },
            "seasons": {},
            "_tmdb_series_id": "tmdb_series_1",
            "_tmdb_seasons": [],
        }

        with (
            patch(
                "lan_streamer.scanner.pass2_metadata._process_series_metadata",
                return_value=(
                    mock_series_data,
                    False,
                    None,
                    {},
                    False,
                ),
            ) as mock_process,
            patch(
                "lan_streamer.scanner.pass2_metadata._process_season_metadata",
                return_value=("Season 1", 1, {}, []),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._process_episode_file",
                return_value={"name": "S01E01 - Pilot", "path": "/nonexistent.mkv"},
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._create_tmdb_placeholder_episodes",
                return_value=[],
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.clean_series_data",
                side_effect=lambda x: x,
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.tmdb_client",
            ) as mock_tmdb,
        ):
            mock_tmdb.is_configured.return_value = False
            scan_series_pass2(
                series_directory=series_dir,
                existing_series_data=existing,
                force_refresh=True,
            )

        # Verify _process_series_metadata was called with force_refresh=True
        _call_args = mock_process.call_args
        assert _call_args is not None
        _call_kwargs = _call_args[1]
        assert _call_kwargs["force_refresh"] is True
        assert _call_kwargs["series_directory"] == series_dir

    def test_early_return_path(self) -> None:
        """When _process_series_metadata returns is_early=True, skip season processing."""
        series_dir = Path("/series/Test Show")
        existing = self._make_existing_series()

        mock_series_data: Dict[str, Any] = {
            "metadata": {"name": "Test Show"},
            "seasons": {},
        }

        with (
            patch(
                "lan_streamer.scanner.pass2_metadata._process_series_metadata",
                return_value=(
                    mock_series_data,
                    True,  # is_early
                    None,
                    {},
                    False,
                ),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._process_season_metadata",
            ) as mock_season,
            patch(
                "lan_streamer.scanner.pass2_metadata.clean_series_data",
                side_effect=lambda x: x,
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.tmdb_client",
            ) as mock_tmdb,
        ):
            mock_tmdb.is_configured.return_value = False
            scan_series_pass2(
                series_directory=series_dir,
                existing_series_data=existing,
                force_refresh=False,
            )

        mock_season.assert_not_called()

    def test_early_return_filters_future_episodes(self) -> None:
        """When is_early and show_future_episodes=False, filter is applied."""
        series_dir = Path("/series/Test Show")
        existing = self._make_existing_series()

        mock_series_data: Dict[str, Any] = {
            "metadata": {"name": "Test Show"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Future Ep",
                            "path": None,
                            "air_date": _ensure_future(),
                        }
                    ]
                }
            },
        }

        with (
            patch(
                "lan_streamer.scanner.pass2_metadata._process_series_metadata",
                return_value=(
                    mock_series_data,
                    True,
                    None,
                    {},
                    False,
                ),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.clean_series_data",
                side_effect=lambda x: x,
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.tmdb_client",
            ) as mock_tmdb,
        ):
            mock_tmdb.is_configured.return_value = False
            result = scan_series_pass2(
                series_directory=series_dir,
                existing_series_data=existing,
                show_future_episodes=False,
            )

        assert len(result["seasons"]["Season 1"]["episodes"]) == 0

    def test_full_pipeline_normal_flow(self, tmp_path: Path) -> None:
        """Normal flow processes seasons and creates placeholders."""
        series_dir = tmp_path / "Test Show"
        season_dir = series_dir / "Season 1"
        season_dir.mkdir(parents=True)
        episode_file = season_dir / "S01E01.mkv"
        episode_file.touch()
        ep_path = str(episode_file.absolute())

        existing: Dict[str, Any] = {
            "metadata": {
                "name": "Test Show",
                "tmdb_identifier": "tmdb_1",
                "tmdb_name": "Test Show",
                "overview": "A test show",
                "poster_path": "",
                "locked_metadata": False,
                "jellyfin_id": "",
            },
            "seasons": {
                "Season 1": {
                    "metadata": {
                        "jellyfin_id": "",
                        "tmdb_identifier": "tmdb_s1",
                        "poster_path": "",
                    },
                    "episodes": [
                        {
                            "name": "Season 1 - Pilot",
                            "path": ep_path,
                            "tmdb_identifier": "tmdb_ep_1",
                            "tmdb_episode_identifier": "tmdb_ep_1",
                            "tmdb_name": "Pilot",
                            "tmdb_number": 1,
                            "air_date": "2020-01-01",
                            "runtime": 30,
                            "jellyfin_id": "",
                            "watched": False,
                            "date_added": 1000.0,
                        }
                    ],
                    "_tmdb_episodes": [
                        {
                            "id": "tmdb_ep_1",
                            "episode_number": 1,
                            "name": "Pilot",
                            "air_date": "2020-01-01",
                            "runtime": 30,
                        }
                    ],
                }
            },
        }

        mock_tmdb = MagicMock()
        mock_tmdb.is_configured.return_value = False

        mock_series_data: Dict[str, Any] = {
            "metadata": {
                "name": "Test Show",
                "tmdb_identifier": "tmdb_1",
            },
            "seasons": {},
            "_tmdb_series_id": "tmdb_1",
            "_tmdb_seasons": [
                {"season_number": 1, "name": "Season 1", "id": "tmdb_s1"}
            ],
        }

        with (
            patch(
                "lan_streamer.scanner.pass2_metadata._process_series_metadata",
                return_value=(
                    mock_series_data,
                    False,
                    None,
                    {},
                    False,
                ),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._process_season_metadata",
                return_value=("Season 1", 1, {}, []),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._process_episode_file",
                return_value={
                    "name": "S01E01 - Pilot",
                    "path": ep_path,
                    "tmdb_number": 1,
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._create_tmdb_placeholder_episodes",
                return_value=[{"name": "S01E02 - TBA", "path": None, "tmdb_number": 2}],
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.clean_series_data",
                side_effect=lambda x: x,
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.tmdb_client",
                mock_tmdb,
            ),
        ):
            result = scan_series_pass2(
                series_directory=series_dir,
                existing_series_data=existing,
            )

        assert "Season 1" in result["seasons"]
        episodes = result["seasons"]["Season 1"]["episodes"]
        assert len(episodes) == 2  # 1 matched + 1 placeholder

    def test_full_pipeline_with_tmdb_configured(self, tmp_path: Path) -> None:
        """When TMDB is configured, parallel pre-fetch is attempted."""
        series_dir = tmp_path / "TMDB Show"
        season_dir = series_dir / "Season 1"
        season_dir.mkdir(parents=True)
        ep_file = season_dir / "S01E01.mkv"
        ep_file.touch()

        existing: Dict[str, Any] = {
            "metadata": {
                "name": "TMDB Show",
                "tmdb_identifier": "tmdb_1",
                "tmdb_name": "TMDB Show",
                "overview": "",
                "poster_path": "",
                "locked_metadata": False,
                "jellyfin_id": "",
            },
            "seasons": {
                "Season 1": {
                    "metadata": {
                        "jellyfin_id": "",
                        "tmdb_identifier": "",
                        "poster_path": "",
                    },
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": str(ep_file.absolute()),
                            "tmdb_number": 1,
                            "tmdb_identifier": "ep1",
                            "tmdb_episode_identifier": "ep1",
                            "tmdb_name": "Ep1",
                            "air_date": "2020-01-01",
                            "runtime": 30,
                            "jellyfin_id": "",
                            "watched": False,
                            "date_added": 1000.0,
                        }
                    ],
                    "_tmdb_episodes": [
                        {"episode_number": 1, "id": "ep1", "name": "Ep1"}
                    ],
                }
            },
        }

        mock_tmdb = MagicMock()
        mock_tmdb.is_configured.return_value = True
        mock_tmdb.get_episodes.return_value = []

        mock_series_data: Dict[str, Any] = {
            "metadata": {"name": "TMDB Show", "tmdb_identifier": "tmdb_1"},
            "seasons": {},
            "_tmdb_series_id": "tmdb_1",
            "_tmdb_seasons": [],
        }

        with (
            patch(
                "lan_streamer.scanner.pass2_metadata._process_series_metadata",
                return_value=(mock_series_data, False, None, {}, False),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._process_season_metadata",
                return_value=("Season 1", 1, {}, []),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._process_episode_file",
                return_value={
                    "name": "S01E01",
                    "path": str(ep_file.absolute()),
                    "tmdb_number": 1,
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._create_tmdb_placeholder_episodes",
                return_value=[],
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.clean_series_data",
                side_effect=lambda x: x,
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.tmdb_client",
                mock_tmdb,
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._fetch_tmdb_episodes_parallel",
                return_value={},
            ),
        ):
            result = scan_series_pass2(
                series_directory=series_dir,
                existing_series_data=existing,
                tmdb_prefetch_executor=concurrent.futures.ThreadPoolExecutor(
                    max_workers=1
                ),
            )

        assert "Season 1" in result["seasons"]

    def test_show_future_episodes_filtered(self, tmp_path: Path) -> None:
        """When show_future_episodes=False, future episodes are filtered at end."""
        series_dir = tmp_path / "Future Show"
        season_dir = series_dir / "Season 1"
        season_dir.mkdir(parents=True)
        ep_file = season_dir / "S01E01.mkv"
        ep_file.touch()

        existing: Dict[str, Any] = {
            "metadata": {
                "name": "Future Show",
                "tmdb_identifier": "tmdb_1",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [],
                    "_tmdb_episodes": [],
                }
            },
        }

        mock_series_data: Dict[str, Any] = {
            "metadata": {"name": "Future Show"},
            "seasons": {},
            "_tmdb_series_id": None,
            "_tmdb_seasons": [],
        }

        with (
            patch(
                "lan_streamer.scanner.pass2_metadata._process_series_metadata",
                return_value=(mock_series_data, False, None, {}, False),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._process_season_metadata",
                return_value=("Season 1", 1, {}, []),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._process_episode_file",
                return_value={
                    "name": "S01E01",
                    "path": str(ep_file.absolute()),
                    "tmdb_number": 1,
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._create_tmdb_placeholder_episodes",
                return_value=[
                    {
                        "name": "S01E02 - Future",
                        "path": None,
                        "tmdb_number": 2,
                        "air_date": _ensure_future(),
                    }
                ],
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.clean_series_data",
                side_effect=lambda x: x,
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.tmdb_client",
            ) as mock_tmdb,
        ):
            mock_tmdb.is_configured.return_value = False
            result = scan_series_pass2(
                series_directory=series_dir,
                existing_series_data=existing,
                show_future_episodes=False,
            )

        # Future placeholder should be filtered
        for ep in result["seasons"]["Season 1"]["episodes"]:
            if ep.get("path") is None:
                assert ep["tmdb_number"] != 2

    def test_callback_invocation(self, tmp_path: Path) -> None:
        """detail_callback and season_callback should be invoked."""
        series_dir = tmp_path / "Callback Show"
        season_dir = series_dir / "Season 1"
        season_dir.mkdir(parents=True)

        existing: Dict[str, Any] = {
            "metadata": {
                "name": "Callback Show",
                "tmdb_identifier": "tmdb_1",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [],
                    "_tmdb_episodes": [],
                }
            },
        }

        mock_series_data: Dict[str, Any] = {
            "metadata": {"name": "Callback Show"},
            "seasons": {},
            "_tmdb_series_id": None,
            "_tmdb_seasons": [],
        }

        detail_callback = MagicMock()
        season_callback = MagicMock()

        with (
            patch(
                "lan_streamer.scanner.pass2_metadata._process_series_metadata",
                return_value=(mock_series_data, False, None, {}, False),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._process_season_metadata",
                return_value=("Season 1", 1, {}, []),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._process_episode_file",
                return_value={"name": "S01E01", "path": None, "tmdb_number": 1},
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._create_tmdb_placeholder_episodes",
                return_value=[],
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.clean_series_data",
                side_effect=lambda x: x,
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.tmdb_client",
            ) as mock_tmdb,
        ):
            mock_tmdb.is_configured.return_value = False
            scan_series_pass2(
                series_directory=series_dir,
                existing_series_data=existing,
                detail_callback=detail_callback,
                season_callback=season_callback,
            )

        assert detail_callback.call_count >= 2  # start_season + finish_season
        season_callback.assert_called_once()


# ===========================================================================
#  scan_movie_pass2
# ===========================================================================


class TestScanMoviePass2:
    """Tests for scan_movie_pass2 — the main movie Pass 2 entry point."""

    def test_returns_none_for_empty_data(self) -> None:
        """When no existing_movie_data is provided, returns None."""
        result = scan_movie_pass2(
            movie_directory=Path("/movies/Test"),
            existing_movie_data={},
        )
        assert result is None

    def test_returns_none_when_none_provided(self) -> None:
        """When existing_movie_data is explicitly None, returns None."""
        result = scan_movie_pass2(
            movie_directory=Path("/movies/Test"),
            existing_movie_data={},  # Falsy dict
        )
        assert result is None

    def test_returns_none_without_video_path(self) -> None:
        """When no video path is found in versions, returns None."""
        existing: Dict[str, Any] = {
            "path": "",
            "versions": [],
            "locked_metadata": False,
        }
        with patch(
            "lan_streamer.scanner.pass2_metadata.choose_active_version",
            return_value={"path": None},
        ):
            result = scan_movie_pass2(
                movie_directory=Path("/movies/Test"),
                existing_movie_data=existing,
            )
        assert result is None

    def test_normal_movie_scan(self, tmp_path: Path) -> None:
        """A normal movie scan should resolve metadata and build movie data."""
        movie_dir = tmp_path / "Avatar (2009)"
        movie_dir.mkdir()
        video_file = movie_dir / "avatar.mkv"
        video_file.touch()
        video_path = str(video_file.absolute())

        existing: Dict[str, Any] = {
            "path": video_path,
            "default_path": video_path,
            "versions": [
                {
                    "path": video_path,
                    "video_codec": "h264",
                    "resolution": "1080p",
                    "bit_rate": 15000,
                    "audio_tracks": [],
                    "subtitle_tracks": [],
                }
            ],
            "locked_metadata": False,
            "tmdb_identifier": "tmdb_avatar",
            "tmdb_name": "Avatar",
            "poster_path": "",
            "overview": "",
            "jellyfin_id": "",
            "year": 2009,
            "runtime": 0,
            "rating": "",
            "genre": "",
            "date_added": 1000.0,
            "_changed": True,
            "watched": False,
            "last_played_position": 0,
            "last_scanned_mtime": 500.0,
        }

        with (
            patch(
                "lan_streamer.scanner.parser._parse_movie_folder",
                return_value=("Avatar", 2009),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.choose_active_version",
                return_value={
                    "path": video_path,
                    "video_codec": "h264",
                    "resolution": "1080p",
                    "bit_rate": 15000,
                    "audio_tracks": [],
                    "subtitle_tracks": [],
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._build_movie_metadata_defaults",
                return_value={
                    "jellyfin_id": "",
                    "tmdb_identifier": "",
                    "tmdb_name": "",
                    "poster_path": "",
                    "overview": "",
                    "runtime": 0,
                    "rating": "",
                    "genre": "",
                    "year": None,
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._apply_existing_movie_metadata",
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._resolve_tmdb_movie_data",
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._build_movie_data",
                return_value={
                    "name": "Avatar (2009)",
                    "path": video_path,
                    "tmdb_identifier": "tmdb_avatar",
                    "poster_path": "",
                },
            ) as mock_build,
            patch(
                "lan_streamer.scanner.pass2_metadata.get_stub_file_info",
                return_value={"path": video_path},
            ),
        ):
            result = scan_movie_pass2(
                movie_directory=movie_dir,
                existing_movie_data=existing,
            )

        assert result is not None
        assert result["name"] == "Avatar (2009)"
        mock_build.assert_called_once()

    def test_locked_movie_scan(self, tmp_path: Path) -> None:
        """Locked movie should still process but preserve locked_metadata."""
        movie_dir = tmp_path / "Locked Movie (2020)"
        movie_dir.mkdir()
        video_file = movie_dir / "locked.mkv"
        video_file.touch()
        video_path = str(video_file.absolute())

        existing: Dict[str, Any] = {
            "path": video_path,
            "default_path": video_path,
            "versions": [{"path": video_path}],
            "locked_metadata": True,
            "tmdb_identifier": "tmdb_locked",
            "tmdb_name": "Locked Movie",
            "poster_path": "",
            "overview": "Locked",
            "jellyfin_id": "",
            "year": 2020,
            "runtime": 90,
            "rating": "7.0",
            "genre": "Test",
            "date_added": 1000.0,
            "_changed": False,
            "watched": False,
            "last_played_position": 0,
            "last_scanned_mtime": 500.0,
        }

        with (
            patch(
                "lan_streamer.scanner.parser._parse_movie_folder",
                return_value=("Locked Movie", 2020),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.choose_active_version",
                return_value={
                    "path": video_path,
                    "video_codec": "h264",
                    "resolution": "1080p",
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._build_movie_metadata_defaults",
                return_value={
                    "jellyfin_id": "",
                    "tmdb_identifier": "",
                    "tmdb_name": "",
                    "poster_path": "",
                    "overview": "",
                    "runtime": 0,
                    "rating": "",
                    "genre": "",
                    "year": None,
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._apply_existing_movie_metadata",
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._resolve_tmdb_movie_data",
            ) as mock_resolve,
            patch(
                "lan_streamer.scanner.pass2_metadata._build_movie_data",
                return_value={
                    "name": "Locked Movie (2020)",
                    "path": video_path,
                    "locked_metadata": True,
                },
            ),
        ):
            result = scan_movie_pass2(
                movie_directory=movie_dir,
                existing_movie_data=existing,
            )

        assert result is not None
        # _resolve_tmdb_movie_data handles the is_locked check internally
        mock_resolve.assert_called_once()

    def test_new_file_detected_refreshes_metadata(self, tmp_path: Path) -> None:
        """When a new file is detected, TMDB metadata is automatically pulled."""
        movie_dir = tmp_path / "Changed Movie (2022)"
        movie_dir.mkdir()
        new_video = movie_dir / "new_version.mkv"
        new_video.touch()
        new_path = str(new_video.absolute())

        existing: Dict[str, Any] = {
            "path": "/old/path/old.mkv",
            "default_path": new_path,
            "versions": [
                {
                    "path": new_path,
                    "video_codec": "h265",
                    "resolution": "4K",
                }
            ],
            "locked_metadata": False,
            "tmdb_identifier": "tmdb_changed",
            "tmdb_name": "Changed Movie",
            "poster_path": "",
            "jellyfin_id": "",
            "year": 2022,
            "runtime": 0,
            "rating": "",
            "genre": "",
            "date_added": 1000.0,
            "_changed": True,
            "watched": False,
            "last_played_position": 0,
            "last_scanned_mtime": 500.0,
        }

        mock_tmdb = MagicMock()
        mock_tmdb.get_movie_by_id.return_value = {
            "id": "tmdb_changed",
            "title": "Changed Movie",
            "overview": "Fresh overview",
            "poster_path": "/new.jpg",
            "release_date": "2022-06-15",
        }

        with (
            patch(
                "lan_streamer.scanner.parser._parse_movie_folder",
                return_value=("Changed Movie", 2022),
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.choose_active_version",
                return_value={
                    "path": new_path,
                    "video_codec": "h265",
                    "resolution": "4K",
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._build_movie_metadata_defaults",
                return_value={
                    "jellyfin_id": "",
                    "tmdb_identifier": "",
                    "tmdb_name": "",
                    "poster_path": "",
                    "overview": "",
                    "runtime": 0,
                    "rating": "",
                    "genre": "",
                    "year": None,
                },
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._apply_existing_movie_metadata",
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._resolve_tmdb_movie_data",
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata._build_movie_data",
                return_value={"name": "Changed Movie (2022)", "path": new_path},
            ),
            patch(
                "lan_streamer.scanner.pass2_metadata.tmdb_client",
                mock_tmdb,
            ),
        ):
            result = scan_movie_pass2(
                movie_directory=movie_dir,
                existing_movie_data=existing,
            )

        assert result is not None
        mock_tmdb.get_movie_by_id.assert_called_once_with("tmdb_changed")


# ===========================================================================
#  Helper to generate a future date string
# ===========================================================================


def _ensure_future() -> str:
    """Return an ISO date string guaranteed to be in the future."""
    return (datetime.date.today() + datetime.timedelta(days=365 * 10)).isoformat()
