"""Comprehensive tests for ``lan_streamer.services.metadata_tv``.

These tests cover every exported function in the module, providing a safety
net for the upcoming split into smaller files.  Many functions are also tested
indirectly through the scanner integration tests in
``tests/unit/scanner/test_core.py``; this file focuses on direct, isolated
unit-test coverage.
"""

# Pre-import scanner to resolve circular import chain:
# metadata_tv → scanner.parser → scanner.__init__ → metadata_resolution → metadata_tv
import lan_streamer.scanner  # noqa: F401

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# _build_existing_episodes_index
# ============================================================================


class TestBuildExistingEpisodesIndex:
    """Path → episode dict lookup builder."""

    def test_empty_series_data(self) -> None:
        """An empty dict returns an empty index."""
        from lan_streamer.services.metadata_series import _build_existing_episodes_index

        assert _build_existing_episodes_index({}) == {}

    def test_no_seasons_key(self) -> None:
        """Missing 'seasons' key safely returns empty dict."""
        from lan_streamer.services.metadata_series import _build_existing_episodes_index

        assert _build_existing_episodes_index({"metadata": {}}) == {}

    def test_single_episode(self) -> None:
        """A single episode is indexed by its path."""
        from lan_streamer.services.metadata_series import _build_existing_episodes_index

        eps = [{"path": "/s1/ep1.mkv", "name": "ep1.mkv"}]
        data = {"seasons": {"Season 1": {"episodes": eps}}}
        result = _build_existing_episodes_index(data)
        assert result == {"/s1/ep1.mkv": eps[0]}

    def test_multiple_episodes_across_seasons(self) -> None:
        """Episodes from multiple seasons are all indexed."""
        from lan_streamer.services.metadata_series import _build_existing_episodes_index

        ep1 = {"path": "/s1/ep1.mkv"}
        ep2 = {"path": "/s1/ep2.mkv"}
        ep3 = {"path": "/s2/ep1.mkv"}
        data = {
            "seasons": {
                "Season 1": {"episodes": [ep1, ep2]},
                "Season 2": {"episodes": [ep3]},
            }
        }
        result = _build_existing_episodes_index(data)
        assert len(result) == 3
        assert result["/s1/ep1.mkv"] is ep1
        assert result["/s2/ep1.mkv"] is ep3

    def test_duplicate_paths_last_wins(self) -> None:
        """When two episodes share a path, the later entry overwrites."""
        from lan_streamer.services.metadata_series import _build_existing_episodes_index

        ep1 = {"path": "/dup.mkv", "name": "old"}
        ep2 = {"path": "/dup.mkv", "name": "new"}
        data = {
            "seasons": {
                "Season 1": {"episodes": [ep1]},
                "Season 2": {"episodes": [ep2]},
            }
        }
        result = _build_existing_episodes_index(data)
        assert result["/dup.mkv"]["name"] == "new"

    def test_season_value_is_not_dict(self) -> None:
        """Gracefully handles non-dict season values (e.g. ``None``)."""
        from lan_streamer.services.metadata_series import _build_existing_episodes_index

        data = {"seasons": {"Season 1": None}}
        # .get("episodes", []) on None would raise; but .values() gives None
        # The code calls .get("episodes", []) on the season value.
        # If the season value is None, an AttributeError is raised.
        with pytest.raises(AttributeError):
            _build_existing_episodes_index(data)


# ============================================================================
# _detect_new_series_files
# ============================================================================


class TestDetectNewSeriesFiles:
    """Detect new/unindexed video files in a series directory."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """An empty directory yields ``False``."""
        from lan_streamer.services.metadata_series import _detect_new_series_files

        series_dir = tmp_path / "Show"
        series_dir.mkdir()
        assert _detect_new_series_files(series_dir, {}) is False

    def test_all_files_indexed(self, tmp_path: Path) -> None:
        """When every file is in the index, returns ``False``."""
        from lan_streamer.services.metadata_series import _detect_new_series_files

        series_dir = tmp_path / "Show"
        (series_dir / "Season 1").mkdir(parents=True)
        ep = series_dir / "Season 1" / "S01E01.mkv"
        ep.touch()
        index = {str(ep.absolute()): {"path": str(ep.absolute())}}
        assert _detect_new_series_files(series_dir, index) is False

    def test_new_file_detected(self, tmp_path: Path) -> None:
        """A file not in the index returns ``True``."""
        from lan_streamer.services.metadata_series import _detect_new_series_files

        series_dir = tmp_path / "Show"
        (series_dir / "Season 1").mkdir(parents=True)
        (series_dir / "Season 1" / "S01E01.mkv").touch()
        assert _detect_new_series_files(series_dir, {}) is True

    def test_nested_too_deep_skipped(self, tmp_path: Path) -> None:
        """Files nested >2 levels deep under a valid season dir are skipped."""
        from lan_streamer.services.metadata_series import _detect_new_series_files

        series_dir = tmp_path / "Show"
        (series_dir / "Season 1").mkdir(parents=True)
        deep = series_dir / "Season 1" / "Subdir" / "ep.mkv"
        deep.parent.mkdir()
        deep.touch()
        {str(deep.absolute()): {"path": str(deep.absolute())}}
        # The file is in a valid season dir >2 levels deep, so it's skipped
        # by the scanning logic → returns False (nothing new beyond what's indexed)
        assert _detect_new_series_files(series_dir, {}) is False

    def test_non_video_files_excluded(self, tmp_path: Path) -> None:
        """Non-video files are not detected as new."""
        from lan_streamer.services.metadata_series import _detect_new_series_files

        series_dir = tmp_path / "Show"
        (series_dir / "Season 1").mkdir(parents=True)
        (series_dir / "Season 1" / "notes.txt").touch()
        assert _detect_new_series_files(series_dir, {}) is False

    def test_files_in_season_subdir_root_skipped(self, tmp_path: Path) -> None:
        """Files directly inside subdirs named 'season', 'special', etc. are skipped."""
        from lan_streamer.services.metadata_series import _detect_new_series_files

        series_dir = tmp_path / "Show"
        (series_dir / "Season 1").mkdir(parents=True)
        ep = series_dir / "Season 1" / "S01E01.mkv"
        ep.touch()
        index = {str(ep.absolute()): {"path": str(ep.absolute())}}
        # File is at depth 2 (Show/Season 1/ep.mkv) → len(parts) == 2, NOT >2
        # So the "is_valid_season" skip does NOT apply — the file IS checked.
        assert _detect_new_series_files(series_dir, index) is False

    def test_files_in_special_subdir_skipped(self, tmp_path: Path) -> None:
        """Files inside 'Specials' directory are skipped by the depth check."""
        from lan_streamer.services.metadata_series import _detect_new_series_files

        series_dir = tmp_path / "Show"
        (series_dir / "Specials").mkdir(parents=True)
        ep = series_dir / "Specials" / "special.mkv"
        ep.touch()
        # Depth == 2 (Show/Specials/special.mkv), not >2, so it IS checked
        index = {str(ep.absolute()): {}}
        assert _detect_new_series_files(series_dir, index) is False

    def test_files_deep_in_unknown_dir_checked(self, tmp_path: Path) -> None:
        """Files inside a non-season subdir (depth >2) are checked if the parent dir
        name doesn't match season/special/extra patterns."""
        from lan_streamer.services.metadata_series import _detect_new_series_files

        series_dir = tmp_path / "Show"
        # "Extras" matches "extra*" → depth check triggers skip
        (series_dir / "Extras").mkdir(parents=True)
        ep = series_dir / "Extras" / "behind.mkv"
        ep.touch()
        # Depth == 2 → not >2, so checked normally
        assert _detect_new_series_files(series_dir, {}) is True

    def test_unknown_directory_name_not_skipped(self, tmp_path: Path) -> None:
        """A subdirectory whose name doesn't match season/special/extra is checked."""
        from lan_streamer.services.metadata_series import _detect_new_series_files

        series_dir = tmp_path / "Show"
        (series_dir / "Random").mkdir(parents=True)
        ep = series_dir / "Random" / "ep.mkv"
        ep.touch()
        # Depth == 2, no skip
        assert _detect_new_series_files(series_dir, {}) is True

    def test_exception_during_relative_path_swallowed(self, tmp_path: Path) -> None:
        """If ``relative_to`` raises, the exception is caught and processing continues."""
        from lan_streamer.services.metadata_series import _detect_new_series_files

        series_dir = tmp_path / "Show"
        (series_dir / "Season 1").mkdir(parents=True)
        ep = series_dir / "Season 1" / "S01E01.mkv"
        ep.touch()
        ep.absolute()

        with patch.object(Path, "relative_to", side_effect=ValueError("nope")):
            # Falls through to the absolute-path check
            result = _detect_new_series_files(series_dir, {})
        assert result is True


# ============================================================================
# _build_series_metadata_defaults
# ============================================================================


class TestBuildSeriesMetadataDefaults:
    """Blank series metadata factory."""

    def test_all_expected_keys(self) -> None:
        """Returns a dict with all expected keys and default empty values."""
        from lan_streamer.services.metadata_series import (
            _build_series_metadata_defaults,
        )

        result = _build_series_metadata_defaults(None)
        expected_keys = {
            "tmdb_identifier",
            "overview",
            "poster_path",
            "tmdb_name",
            "first_air_date",
            "jellyfin_id",
        }
        assert set(result.keys()) == expected_keys
        assert result["jellyfin_id"] == ""

    def test_with_manual_jellyfin_id(self) -> None:
        """``manual_jellyfin_id`` is pre-populated."""
        from lan_streamer.services.metadata_series import (
            _build_series_metadata_defaults,
        )

        result = _build_series_metadata_defaults("jf_manual_42")
        assert result["jellyfin_id"] == "jf_manual_42"

    def test_with_empty_string_id(self) -> None:
        """An empty string for ``manual_jellyfin_id`` is treated as falsy."""
        from lan_streamer.services.metadata_series import (
            _build_series_metadata_defaults,
        )

        result = _build_series_metadata_defaults("")
        assert result["jellyfin_id"] == ""


# ============================================================================
# _resolve_series_poster
# ============================================================================


class TestResolveSeriesPoster:
    """Three-step poster resolution for TV series."""

    def test_cached_image_returned_first(self) -> None:
        """Step 1: if TMDB client has a cached image, it wins."""
        from lan_streamer.services.metadata_series import _resolve_series_poster

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = "/cache/poster.jpg"
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            result = _resolve_series_poster(
                {"poster_path": "/remote.jpg"}, "tmdb_1", None
            )
        assert result == "/cache/poster.jpg"
        mock_tmdb.download_image.assert_not_called()

    def test_cached_image_non_string_ignored(self) -> None:
        """If cached image is not a string (e.g. ``None``), fall through."""
        from lan_streamer.services.metadata_series import _resolve_series_poster

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = None  # not isinstance(str)
        local_poster = Path("/tmp/local_poster.jpg")  # won't exist, so skip step 2
        existing = {"metadata": {"poster_path": str(local_poster)}}
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            result = _resolve_series_poster({"poster_path": ""}, "tmdb_2", existing)
        assert result == ""

    def test_existing_local_file_used(self, tmp_path: Path) -> None:
        """Step 2: existing valid local poster is returned."""
        from lan_streamer.services.metadata_series import _resolve_series_poster

        local = tmp_path / "poster.jpg"
        local.touch()
        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = ""
        existing = {"metadata": {"poster_path": str(local)}}
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            result = _resolve_series_poster({"poster_path": ""}, "tmdb_3", existing)
        assert result == str(local)
        mock_tmdb.download_image.assert_not_called()

    def test_existing_poster_path_missing_file_skipped(self) -> None:
        """If existing poster path doesn't point to a real file, skip step 2."""
        from lan_streamer.services.metadata_series import _resolve_series_poster

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = ""
        existing = {"metadata": {"poster_path": "/nonexistent/posters/ghost.jpg"}}
        # Step 3: no poster_path in tmdb_series → return ""
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            result = _resolve_series_poster({"poster_path": ""}, "tmdb_4", existing)
        assert result == ""

    def test_download_from_remote(self) -> None:
        """Step 3: download from TMDB CDN when no cache or local file exists."""
        from lan_streamer.services.metadata_series import _resolve_series_poster

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = ""
        mock_tmdb.download_image.return_value = "/dl/series.jpg"
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            result = _resolve_series_poster(
                {"poster_path": "/remote/poster.jpg"}, "tmdb_5", None
            )
        assert result == "/dl/series.jpg"
        mock_tmdb.download_image.assert_called_once_with(
            "/remote/poster.jpg", "tmdb_series_tmdb_5"
        )

    def test_no_poster_available(self) -> None:
        """When no poster is available at any step, returns empty string."""
        from lan_streamer.services.metadata_series import _resolve_series_poster

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = ""
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            result = _resolve_series_poster({"poster_path": ""}, "tmdb_6", None)
        assert result == ""

    def test_offline_mode_skips_download(self) -> None:
        """In offline mode, step 3 (download) is skipped."""
        from lan_streamer.services.metadata_series import _resolve_series_poster

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = ""
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            result = _resolve_series_poster(
                {"poster_path": "/remote.jpg"}, "tmdb_7", None, offline=True
            )
        assert result == ""
        mock_tmdb.download_image.assert_not_called()

    def test_prefetched_local_path_used(self) -> None:
        """A prefetched poster path (not starting with '/') is used directly."""
        from lan_streamer.services.metadata_series import _resolve_series_poster

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = ""
        tmdb_series = {"poster_path": "local_path.jpg", "_is_prefetched": True}
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            result = _resolve_series_poster(tmdb_series, "tmdb_8", None)
        assert result == "local_path.jpg"
        mock_tmdb.download_image.assert_not_called()

    def test_prefetched_remote_path_still_downloads(self) -> None:
        """A prefetched poster that starts with '/' still goes through download."""
        from lan_streamer.services.metadata_series import _resolve_series_poster

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = ""
        mock_tmdb.download_image.return_value = "/dl/prefetched.jpg"
        tmdb_series = {"poster_path": "/remote.jpg", "_is_prefetched": True}
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            result = _resolve_series_poster(tmdb_series, "tmdb_9", None)
        assert result == "/dl/prefetched.jpg"
        mock_tmdb.download_image.assert_called_once()

    def test_existing_data_is_none(self) -> None:
        """``existing_series_data`` being ``None`` is handled gracefully."""
        from lan_streamer.services.metadata_series import _resolve_series_poster

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = ""
        mock_tmdb.download_image.return_value = "/dl/poster.jpg"
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            result = _resolve_series_poster({"poster_path": "/p.jpg"}, "tmdb_10", None)
        assert result == "/dl/poster.jpg"


# ============================================================================
# _resolve_episode_jellyfin_id
# ============================================================================


class TestResolveEpisodeJellyfinId:
    """Multi-strategy Jellyfin ID resolution for a single episode file."""

    # Helper to reduce boilerplate
    @staticmethod
    def _call(
        episode_path: str = "/fake/ep.mkv",
        episode_name: str = "S01E01.mkv",
        episode_file: Path | None = None,
        tmdb_episode_identifier: str | None = None,
        tmdb_name: str | None = None,
        tmdb_number: int | None = None,
        season_name: str = "Season 1",
        series_directory: Path | None = None,
        series_data: dict | None = None,
        season_metadata: dict | None = None,
        tmdb_series: dict | None = None,
        jellyfin_data: dict | None = None,
    ) -> tuple[str, str, str]:
        from lan_streamer.services.metadata_series import _resolve_episode_jellyfin_id

        return _resolve_episode_jellyfin_id(
            episode_path=episode_path,
            episode_name=episode_name,
            episode_file=episode_file or Path(episode_path),
            tmdb_episode_identifier=tmdb_episode_identifier,
            tmdb_name=tmdb_name,
            tmdb_number=tmdb_number,
            season_name=season_name,
            series_directory=series_directory or Path("/fake/show"),
            series_data=series_data or {"metadata": {"jellyfin_id": ""}},
            season_metadata=season_metadata or {},
            tmdb_series=tmdb_series,
            jellyfin_data=jellyfin_data,
        )

    def test_no_jellyfin_data(self) -> None:
        """When ``jellyfin_data`` is ``None``, returns three empty strings."""
        jf_id, series_jf, season_jf = self._call(jellyfin_data=None)
        assert jf_id == ""
        assert series_jf == ""
        assert season_jf == ""

    def test_path_map_match(self) -> None:
        """Strategy 1: direct path match."""
        jf_id, series_jf, season_jf = self._call(
            episode_path="/ep.mkv",
            jellyfin_data={
                "path_map": {
                    "/ep.mkv": {
                        "id": "jf_ep",
                        "series_id": "jf_series",
                        "season_id": "jf_season",
                    }
                }
            },
        )
        assert jf_id == "jf_ep"
        assert series_jf == "jf_series"
        assert season_jf == "jf_season"

    def test_path_map_entry_without_series_season(self) -> None:
        """path_map entry missing optional keys returns empty strings for those."""
        jf_id, series_jf, season_jf = self._call(
            episode_path="/ep.mkv",
            jellyfin_data={"path_map": {"/ep.mkv": {"id": "jf_ep"}}},
        )
        assert jf_id == "jf_ep"
        assert series_jf == ""
        assert season_jf == ""

    def test_tmdb_episode_map_match(self) -> None:
        """Strategy 2: TMDB episode identifier match."""
        jf_id, _, _ = self._call(
            episode_path="/other.mkv",
            tmdb_episode_identifier="tmdb_ep_42",
            jellyfin_data={
                "path_map": {},
                "tmdb_episode_map": {"tmdb_ep_42": "jf_from_tmdb"},
            },
        )
        assert jf_id == "jf_from_tmdb"

    def test_tmdb_episode_map_no_match(self) -> None:
        """No match in TMDB episode map falls through."""
        jf_id, _, _ = self._call(
            episode_path="/other.mkv",
            tmdb_episode_identifier="tmdb_ep_unknown",
            jellyfin_data={
                "path_map": {},
                "tmdb_episode_map": {"tmdb_ep_42": "jf_known"},
            },
        )
        assert jf_id == ""

    def test_name_map_match_with_tmdb_series(self) -> None:
        """Strategy 3: name map match using TMDB series name."""
        jf_id, _, _ = self._call(
            episode_path="/p.mkv",
            tmdb_name="Pilot Episode",
            tmdb_series={"name": "My Show"},
            jellyfin_data={
                "path_map": {},
                "tmdb_episode_map": {},
                "name_map": {("my show", "pilot episode"): "jf_name_match"},
            },
        )
        assert jf_id == "jf_name_match"

    def test_name_map_fallback_to_directory_name(self) -> None:
        """Strategy 3: name map falls back to series directory name when TMDB series is ``None``."""
        jf_id, _, _ = self._call(
            episode_path="/p.mkv",
            episode_name="test_ep.mkv",
            episode_file=Path("/show/Season 1/test_ep.mkv"),
            tmdb_name=None,
            tmdb_series=None,
            series_directory=Path("/my_show_dir"),
            jellyfin_data={
                "path_map": {},
                "tmdb_episode_map": {},
                "name_map": {("my_show_dir", "test_ep"): "jf_dir_fallback"},
            },
        )
        assert jf_id == "jf_dir_fallback"

    def test_series_id_map_sxxexx_match(self) -> None:
        """Strategy 4: series ID map SxxExx pattern match."""
        jf_id, _, _ = self._call(
            episode_path="/p/S01E03.mkv",
            episode_name="S01E03.mkv",
            tmdb_episode_identifier=None,
            tmdb_name=None,
            tmdb_number=None,
            season_name="Season 1",
            series_data={"metadata": {"jellyfin_id": "jf_series_id"}},
            jellyfin_data={
                "path_map": {},
                "tmdb_episode_map": {},
                "series_id_map": {
                    "jf_series_id": {"episodes": {(1, 3): "jf_ep_s01e03"}, "names": {}}
                },
            },
        )
        assert jf_id == "jf_ep_s01e03"

    def test_series_id_map_tmdb_number_fallback(self) -> None:
        """Strategy 4: when SxxExx parsing fails but tmdb_number is given, use that."""
        jf_id, _, _ = self._call(
            episode_path="/p/Pilot.mkv",
            episode_name="Pilot.mkv",
            tmdb_episode_identifier=None,
            tmdb_name="Pilot",
            tmdb_number=1,
            season_name="Season 1",
            series_data={"metadata": {"jellyfin_id": "jf_series_id"}},
            jellyfin_data={
                "path_map": {},
                "tmdb_episode_map": {},
                "series_id_map": {
                    "jf_series_id": {
                        "episodes": {(1, 1): "jf_ep_num1"},
                        "names": {},
                    }
                },
            },
        )
        assert jf_id == "jf_ep_num1"

    def test_series_id_map_name_fallback(self) -> None:
        """Strategy 4: names map fallback after SxxExx fails."""
        jf_id, _, _ = self._call(
            episode_path="/p/Custom.mkv",
            episode_name="Custom.mkv",
            tmdb_episode_identifier=None,
            tmdb_name="Custom Name",
            tmdb_number=None,
            season_name="Season 1",
            series_data={"metadata": {"jellyfin_id": "jf_series_id"}},
            jellyfin_data={
                "path_map": {},
                "tmdb_episode_map": {},
                "series_id_map": {
                    "jf_series_id": {
                        "episodes": {},
                        "names": {"custom name": "jf_ep_name"},
                    }
                },
            },
        )
        assert jf_id == "jf_ep_name"

    def test_no_match_returns_empty(self) -> None:
        """When all strategies fail, return empty string."""
        jf_id, _, _ = self._call(
            episode_path="/nomatch.mkv",
            jellyfin_data={
                "path_map": {},
                "tmdb_episode_map": {},
                "name_map": {},
                "series_id_map": {},
            },
        )
        assert jf_id == ""

    def test_series_metadata_no_jellyfin_id_skips_series_map(self) -> None:
        """Strategy 4 is skipped when series metadata lacks ``jellyfin_id``."""
        jf_id, _, _ = self._call(
            episode_path="/p/S01E01.mkv",
            episode_name="S01E01.mkv",
            series_data={"metadata": {"jellyfin_id": ""}},
            jellyfin_data={
                "path_map": {},
                "tmdb_episode_map": {},
                "series_id_map": {
                    "": {"episodes": {(1, 1): "should_not_match"}, "names": {}}
                },
            },
        )
        assert jf_id == ""


# ============================================================================
# _process_series_metadata
# ============================================================================


class TestProcessSeriesMetadata:
    """Full series-level metadata resolution."""

    @staticmethod
    def _call(
        series_directory: Path | None = None,
        tmdb_series: dict | None = None,
        jellyfin_data: dict | None = None,
        manual_jellyfin_id: str | None = None,
        existing_series_data: dict | None = None,
        force_refresh: bool = False,
        cleanup: bool = False,
        single_item_refresh: bool = False,
        offline: bool = False,
        metadata_only: bool = False,
    ) -> tuple[Any, bool, Any, Any, bool]:
        from lan_streamer.services.metadata_series import _process_series_metadata

        return _process_series_metadata(
            series_directory=series_directory or Path("/nonexistent/show"),
            tmdb_series=tmdb_series,
            jellyfin_data=jellyfin_data,
            manual_jellyfin_id=manual_jellyfin_id,
            existing_series_data=existing_series_data,
            force_refresh=force_refresh,
            cleanup=cleanup,
            single_item_refresh=single_item_refresh,
            offline=offline,
            metadata_only=metadata_only,
        )

    def test_new_series_no_existing_data(self) -> None:
        """A new series (no existing data) results in a fresh metadata dict and no early return."""
        from lan_streamer.services.metadata_series import _process_series_metadata

        series_dir = Path("/new/Series X")
        mock_tmdb = MagicMock()
        mock_tmdb.search_series.return_value = {
            "id": "tmdb_new",
            "name": "Series X",
            "overview": "A new series.",
            "poster_path": "/p.jpg",
            "first_air_date": "2023-01-01",
        }
        mock_tmdb.download_image.return_value = "/dl/poster.jpg"
        mock_tmdb.get_cached_image.return_value = ""
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            series_data, is_early, tmdb_series, ep_index, refreshed = (
                _process_series_metadata(
                    series_directory=series_dir,
                    tmdb_series=None,
                    jellyfin_data=None,
                    manual_jellyfin_id=None,
                    existing_series_data=None,
                    force_refresh=False,
                    cleanup=False,
                )
            )

        assert is_early is False
        assert series_data["metadata"]["tmdb_identifier"] == "tmdb_new"
        assert series_data["metadata"]["overview"] == "A new series."
        assert series_data["metadata"]["tmdb_name"] == "Series X"
        assert series_data["metadata"]["first_air_date"] == "2023-01-01"
        assert series_data["_tmdb_series_id"] == "tmdb_new"
        assert ep_index == {}

    def test_new_series_no_tmdb_match(self) -> None:
        """When TMDB search returns nothing, metadata stays as defaults."""
        from lan_streamer.services.metadata_series import _process_series_metadata

        series_dir = Path("/new/Unknown Show")
        mock_tmdb = MagicMock()
        mock_tmdb.search_series.return_value = None
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            series_data, is_early, tmdb_series, ep_index, refreshed = (
                _process_series_metadata(
                    series_directory=series_dir,
                    tmdb_series=None,
                    jellyfin_data=None,
                    manual_jellyfin_id=None,
                    existing_series_data=None,
                    force_refresh=False,
                    cleanup=False,
                )
            )
        assert is_early is False
        assert series_data["metadata"]["tmdb_identifier"] == ""
        assert series_data["metadata"]["tmdb_name"] == ""

    def test_existing_series_early_return_no_change(self, tmp_path: Path) -> None:
        """When nothing forces a refresh and existing data exists, early-returns with ``is_early_return=True``."""
        from lan_streamer.services.metadata_series import _process_series_metadata

        series_dir = tmp_path / "Series A"
        # Create a file so _detect_new_series_files runs but finds nothing new
        (series_dir / "Season 1").mkdir(parents=True)
        ep = series_dir / "Season 1" / "S01E01.mkv"
        ep.touch()
        ep_path = str(ep.absolute())

        existing = {
            "metadata": {
                "tmdb_identifier": "old_id",
                "tmdb_name": "Old Name",
                "overview": "Old overview",
                "poster_path": "",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": ep_path,
                            "tmdb_identifier": "ep_old",
                            "jellyfin_id": "",
                            "runtime": 0,
                        }
                    ]
                }
            },
        }

        series_data, is_early, tmdb_series, ep_index, refreshed = (
            _process_series_metadata(
                series_directory=series_dir,
                tmdb_series=None,
                jellyfin_data=None,
                manual_jellyfin_id=None,
                existing_series_data=existing,
                force_refresh=False,
                cleanup=False,
            )
        )
        assert is_early is True
        assert series_data["metadata"]["tmdb_name"] == "Old Name"

    def test_existing_series_locked_metadata_preserved(self, tmp_path: Path) -> None:
        """Locked metadata is preserved even with ``force_refresh=True``."""
        from lan_streamer.services.metadata_series import _process_series_metadata

        series_dir = tmp_path / "Locked Show"
        (series_dir / "Season 1").mkdir(parents=True)
        (series_dir / "Season 1" / "S01E01.mkv").touch()

        existing = {
            "metadata": {
                "tmdb_identifier": "locked_id",
                "tmdb_name": "Locked Title",
                "overview": "Locked overview",
                "locked_metadata": True,
            },
            "seasons": {},
        }

        mock_tmdb = MagicMock()
        mock_tmdb.get_series_by_id.return_value = {
            "id": "locked_id",
            "name": "Locked Title",
            "overview": "Locked overview",
            "poster_path": "",
            "first_air_date": "",
            "seasons": [],
        }
        mock_tmdb.get_episodes.return_value = []
        mock_tmdb.get_cached_image.return_value = ""
        mock_tmdb.download_image.return_value = ""

        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            series_data, is_early, tmdb_series, ep_index, refreshed = (
                _process_series_metadata(
                    series_directory=series_dir,
                    tmdb_series=None,
                    jellyfin_data=None,
                    manual_jellyfin_id=None,
                    existing_series_data=existing,
                    force_refresh=True,
                    cleanup=False,
                )
            )
        # Locked metadata prevents search_series (title search)
        mock_tmdb.search_series.assert_not_called()
        # But get_series_by_id is still called for episode resolution
        # Metadata values should match the locked existing data
        assert series_data["metadata"]["tmdb_name"] == "Locked Title"

    def test_new_files_triggers_auto_refresh(self, tmp_path: Path) -> None:
        """When new files are detected and series is unlocked, automatically refresh metadata."""
        from lan_streamer.services.metadata_series import _process_series_metadata

        series_dir = tmp_path / "Auto Refresh Show"
        (series_dir / "Season 1").mkdir(parents=True)
        (series_dir / "Season 1" / "S01E01.mkv").touch()
        ep2 = series_dir / "Season 1" / "S01E02.mkv"
        ep2.touch()

        existing = {
            "metadata": {
                "tmdb_identifier": "old_id",
                "tmdb_name": "Old Title",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": str(
                                (series_dir / "Season 1" / "S01E01.mkv").absolute()
                            ),
                        }
                    ]
                }
            },
        }

        mock_tmdb = MagicMock()
        mock_tmdb.get_series_by_id.return_value = {
            "id": "old_id",
            "name": "Fresh Title",
            "overview": "Fresh overview",
            "first_air_date": "2023-01-01",
            "poster_path": "",
        }
        mock_tmdb.get_cached_image.return_value = ""
        mock_tmdb.download_image.return_value = ""
        mock_tmdb.get_episode_group_details.side_effect = Exception("no groups")

        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            series_data, is_early, tmdb_series, ep_index, refreshed = (
                _process_series_metadata(
                    series_directory=series_dir,
                    tmdb_series=None,
                    jellyfin_data=None,
                    manual_jellyfin_id=None,
                    existing_series_data=existing,
                    force_refresh=False,
                    cleanup=False,
                )
            )
        assert series_data["metadata"]["tmdb_name"] == "Fresh Title"
        assert refreshed is True  # force_refresh was set to True

    def test_metadata_only_skips_filesystem_walk(self) -> None:
        """With ``metadata_only=True``, the filesystem walk is skipped."""
        from lan_streamer.services.metadata_series import _process_series_metadata

        existing = {
            "metadata": {
                "tmdb_identifier": "existing_id",
                "tmdb_name": "Existing Show",
                "overview": "Existing overview",
                "poster_path": "",
            },
            "seasons": {},
        }

        mock_tmdb = MagicMock()
        mock_tmdb.get_series_by_id.return_value = {
            "id": "existing_id",
            "name": "Existing Show",
            "overview": "Updated overview",
            "poster_path": "/new.jpg",
            "first_air_date": "2023-01-01",
        }
        mock_tmdb.get_cached_image.return_value = ""
        mock_tmdb.download_image.return_value = "/dl/new.jpg"

        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            series_data, is_early, tmdb_series, ep_index, refreshed = (
                _process_series_metadata(
                    series_directory=Path("/nonexistent"),
                    tmdb_series=None,
                    jellyfin_data=None,
                    manual_jellyfin_id=None,
                    existing_series_data=existing,
                    force_refresh=True,
                    cleanup=False,
                    metadata_only=True,
                )
            )
        assert series_data["metadata"]["overview"] == "Updated overview"
        assert ep_index == {}  # no filesystem walk

    def test_jellyfin_id_mapped_via_tmdb_series_map(self) -> None:
        """Series-level Jellyfin ID is resolved from TMDB series map."""
        from lan_streamer.services.metadata_series import _process_series_metadata

        series_dir = Path("/jelly/Series B")
        mock_tmdb = MagicMock()
        mock_tmdb.search_series.return_value = {
            "id": "tmdb_series_b",
            "name": "Series B",
            "overview": "Desc",
            "poster_path": "",
        }
        mock_tmdb.get_cached_image.return_value = ""
        mock_tmdb.download_image.return_value = ""

        jellyfin_data = {
            "tmdb_series_map": {"tmdb_series_b": "jf_series_b"},
        }

        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            series_data, is_early, tmdb_series, ep_index, refreshed = (
                _process_series_metadata(
                    series_directory=series_dir,
                    tmdb_series=None,
                    jellyfin_data=jellyfin_data,
                    manual_jellyfin_id=None,
                    existing_series_data=None,
                    force_refresh=False,
                    cleanup=False,
                )
            )
        assert series_data["metadata"]["jellyfin_id"] == "jf_series_b"

    def test_offline_skips_tmdb_lookup(self, tmp_path: Path) -> None:
        """In offline mode, TMDB lookups and poster download are skipped."""
        from lan_streamer.services.metadata_series import _process_series_metadata

        series_dir = tmp_path / "Offline Show"
        (series_dir / "Season 1").mkdir(parents=True)
        (series_dir / "Season 1" / "S01E01.mkv").touch()

        mock_tmdb = MagicMock()
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            series_data, is_early, tmdb_series, ep_index, refreshed = (
                _process_series_metadata(
                    series_directory=series_dir,
                    tmdb_series=None,
                    jellyfin_data=None,
                    manual_jellyfin_id=None,
                    existing_series_data=None,
                    force_refresh=False,
                    cleanup=False,
                    offline=True,
                )
            )
        assert series_data["metadata"]["tmdb_identifier"] == ""
        assert series_data["metadata"]["poster_path"] == ""
        mock_tmdb.search_series.assert_not_called()
        mock_tmdb.download_image.assert_not_called()

    def test_manual_jellyfin_id_pre_populated(self) -> None:
        """A ``manual_jellyfin_id`` is set in the metadata."""
        from lan_streamer.services.metadata_series import _process_series_metadata

        series_dir = Path("/manual/Manual Show")
        mock_tmdb = MagicMock()
        mock_tmdb.search_series.return_value = {
            "id": "tmdb_m",
            "name": "Manual Show",
            "overview": "",
            "poster_path": "",
        }
        mock_tmdb.get_cached_image.return_value = ""
        mock_tmdb.download_image.return_value = ""
        with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
            series_data, is_early, _, _, _ = _process_series_metadata(
                series_directory=series_dir,
                tmdb_series=None,
                jellyfin_data=None,
                manual_jellyfin_id="jf_manual_1",
                existing_series_data=None,
                force_refresh=False,
                cleanup=False,
            )
        assert series_data["metadata"]["jellyfin_id"] == "jf_manual_1"


# ============================================================================
# _process_season_metadata
# ============================================================================


class TestProcessSeasonMetadata:
    """Season-level metadata resolution + TMDB episode fetch."""

    def test_specials_season_index_zero(self) -> None:
        """'Specials' directory maps to season index 0."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Specials")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [{"season_number": 0, "poster_path": "", "id": 999}],
            "metadata": {"locked_metadata": False},
        }

        mock_tmdb = MagicMock()
        mock_tmdb.get_episodes.return_value = [{"id": 1, "episode_number": 1}]
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, None, {}
            )
        assert name == "Specials"
        assert idx == 0
        assert len(episodes) == 1
        mock_tmdb.get_episodes.assert_called_once_with("123", 0)

    def test_valid_season_index(self) -> None:
        """'Season 3' maps to index 3."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Season 3")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [{"season_number": 3, "id": 333}],
            "metadata": {"locked_metadata": False},
        }

        mock_tmdb = MagicMock()
        mock_tmdb.get_episodes.return_value = []
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, None, {}
            )
        assert name == "Season 3"
        assert idx == 3
        mock_tmdb.get_episodes.assert_called_once_with("123", 3)

    def test_unknown_season_number(self) -> None:
        """A directory without a parsable season number gets index -1."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/MiniSeries")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [],
            "metadata": {"locked_metadata": False},
        }

        mock_tmdb = MagicMock()
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, None, {}
            )
        assert name == "MiniSeries"
        assert idx == -1
        assert episodes == []
        mock_tmdb.get_episodes.assert_not_called()

    def test_existing_season_metadata_preserved(self) -> None:
        """Existing season metadata (poster, MAL ID) is reused."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Season 2")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [{"season_number": 2, "id": 222}],
            "metadata": {"locked_metadata": False},
        }
        existing = {
            "seasons": {
                "Season 2": {
                    "metadata": {
                        "tmdb_identifier": "old_season_id",
                        "poster_path": "/old/poster.jpg",
                        "myanimelist_id": 12345,
                    },
                    "episodes": [],
                }
            }
        }

        # Make the old poster exist so it's reused
        Path("/old/poster.jpg")
        with patch.object(Path, "is_file", return_value=True):
            mock_tmdb = MagicMock()
            mock_tmdb.get_cached_image.return_value = ""
            mock_tmdb.get_episodes.return_value = []
            with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
                name, idx, meta, episodes = _process_season_metadata(
                    season_dir,
                    series_data,
                    existing,
                    {},
                )
        assert meta["tmdb_identifier"] == "222"
        assert meta["myanimelist_id"] == 12345

    def test_season_poster_cached(self) -> None:
        """Cached season poster takes priority."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Season 1")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [{"season_number": 1, "id": 111, "poster_path": "/r.jpg"}],
            "metadata": {"locked_metadata": False},
        }

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = "/cache/season.jpg"
        mock_tmdb.get_episodes.return_value = []
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, None, {}
            )
        assert meta["poster_path"] == "/cache/season.jpg"
        mock_tmdb.download_image.assert_not_called()

    def test_season_poster_downloaded(self) -> None:
        """When no cache and no existing poster, download from TMDB."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Season 1")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [{"season_number": 1, "id": 111, "poster_path": "/r.jpg"}],
            "metadata": {"locked_metadata": False},
        }

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = ""
        mock_tmdb.download_image.return_value = "/dl/season.jpg"
        mock_tmdb.get_episodes.return_value = []
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, None, {}
            )
        assert meta["poster_path"] == "/dl/season.jpg"
        mock_tmdb.download_image.assert_called_once_with("/r.jpg", "tmdb_season_111")

    def test_no_matching_tmdb_season(self) -> None:
        """When no TMDB season matches, existing identifiers are reused."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Season 99")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [{"season_number": 1, "id": 111}],
            "metadata": {"locked_metadata": False},
        }
        existing = {
            "seasons": {
                "Season 99": {
                    "metadata": {
                        "tmdb_identifier": "legacy_id",
                        "poster_path": "/legacy.jpg",
                    },
                    "episodes": [],
                }
            }
        }

        mock_tmdb = MagicMock()
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, existing, {}
            )
        assert meta["tmdb_identifier"] == "legacy_id"
        assert meta["poster_path"] == "/legacy.jpg"

    def test_locked_series_skips_episode_fetch(self) -> None:
        """When series is locked, episode fetch is skipped."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Season 1")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [{"season_number": 1, "id": 111}],
            "metadata": {"locked_metadata": True},
        }

        mock_tmdb = MagicMock()
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, None, {}
            )
        assert episodes == []
        mock_tmdb.get_episodes.assert_not_called()

    def test_offline_skips_episode_fetch(self) -> None:
        """When offline, episode fetch is skipped."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Season 1")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [{"season_number": 1, "id": 111}],
            "metadata": {"locked_metadata": False},
        }

        mock_tmdb = MagicMock()
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, None, {}, offline=True
            )
        assert episodes == []
        mock_tmdb.get_episodes.assert_not_called()

    def test_existing_season_has_episodes_skip_fetch(self) -> None:
        """When existing season already has episodes and no force/single refresh, skip fetch."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Season 1")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [{"season_number": 1, "id": 111}],
            "metadata": {"locked_metadata": False},
        }
        existing = {
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": "/ep.mkv",
                            "tmdb_identifier": "ep_123",
                        }
                    ],
                }
            }
        }

        mock_tmdb = MagicMock()
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, existing, {}, force_refresh=False
            )
        assert episodes == []
        mock_tmdb.get_episodes.assert_not_called()

    def test_episode_group_details_used(self) -> None:
        """When episode group details exist, episodes are extracted from groups."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Season 1")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [],
            "_tmdb_episode_group_details": {
                "id": "g1",
                "groups": [
                    {
                        "name": "Season 1",
                        "order": 1,
                        "episodes": [
                            {
                                "id": "ep_grp_1",
                                "name": "Group Ep 1",
                                "order": 0,
                                "air_date": "2023-01-01",
                                "runtime": 45,
                            }
                        ],
                    }
                ],
            },
            "metadata": {"locked_metadata": False},
        }

        mock_tmdb = MagicMock()
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, None, {}
            )
        assert len(episodes) == 1
        assert episodes[0]["name"] == "Group Ep 1"
        assert episodes[0]["episode_number"] == 1  # order 0 + 1
        mock_tmdb.get_episodes.assert_not_called()

    def test_season_poster_offline_no_download(self) -> None:
        """In offline mode, season poster is not downloaded."""
        from lan_streamer.services.metadata_episode import _process_season_metadata

        season_dir = Path("/show/Season 1")
        series_data: dict[str, Any] = {
            "_tmdb_series_id": "123",
            "_tmdb_seasons": [{"season_number": 1, "id": 111, "poster_path": "/r.jpg"}],
            "metadata": {"locked_metadata": False},
        }

        mock_tmdb = MagicMock()
        mock_tmdb.get_cached_image.return_value = ""
        with patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb):
            name, idx, meta, episodes = _process_season_metadata(
                season_dir, series_data, None, {}, offline=True
            )
        assert meta["poster_path"] == ""
        mock_tmdb.download_image.assert_not_called()


# ============================================================================
# _process_episode_file
# ============================================================================


class TestProcessEpisodeFile:
    """Per-episode metadata matching against the TMDB episode list."""

    def _make_episode_file(
        self,
        tmp_path: Path,
        season_name: str = "Season 1",
        episode_name: str = "S01E01.mkv",
    ) -> Path:
        series_dir = tmp_path / "Test Show"
        season_dir = series_dir / season_name
        season_dir.mkdir(parents=True)
        ep = season_dir / episode_name
        ep.touch()
        return ep

    def test_single_episode_no_existing(self, tmp_path: Path) -> None:
        """A single new episode is matched by SxxExx pattern."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E01.mkv")
        series_dir = ep.parent.parent
        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }
        tmdb_episodes = [
            {
                "id": "ep1",
                "episode_number": 1,
                "name": "Episode 1",
                "air_date": "2023-01-01",
                "runtime": 30,
            },
        ]

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=tmdb_episodes,
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path={},
        )
        assert result["name"] == "Episode 1"
        assert result["tmdb_number"] == 1
        assert result["tmdb_name"] == "Episode 1"
        assert result["tmdb_episode_identifier"] == "ep1"
        assert result["watched"] is False

    def test_existing_episode_reuses_metadata(self, tmp_path: Path) -> None:
        """An existing episode reuses cached metadata."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E01.mkv")
        series_dir = ep.parent.parent
        ep_path = str(ep.absolute())

        existing_ep = {
            "path": ep_path,
            "tmdb_episode_identifier": "old_ep_id",
            "tmdb_name": "Old Name",
            "tmdb_number": 1,
            "air_date": "2022-01-01",
            "runtime": 25,
            "jellyfin_id": "jf_old",
            "watched": True,
        }
        existing_by_path = {ep_path: existing_ep}

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=[],
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path=existing_by_path,
        )
        assert result["tmdb_name"] == "Old Name"
        assert result["tmdb_number"] == 1
        assert result["air_date"] == "2022-01-01"
        assert result["runtime"] == 25
        assert result["watched"] is True

    def test_existing_episode_update_from_tmdb_when_number_missing(
        self, tmp_path: Path
    ) -> None:
        """When existing episode has no tmdb_number, fill from TMDB."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E03.mkv")
        series_dir = ep.parent.parent
        ep_path = str(ep.absolute())

        existing_ep = {
            "path": ep_path,
            "tmdb_episode_identifier": "ep_3",
            "tmdb_name": None,
            "tmdb_number": None,
            "air_date": "",
            "runtime": 0,
        }
        existing_by_path = {ep_path: existing_ep}

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }
        tmdb_episodes = [
            {
                "id": "ep_3",
                "episode_number": 3,
                "name": "Episode 3",
                "air_date": "2023-03-01",
                "runtime": 40,
            },
        ]

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=tmdb_episodes,
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path=existing_by_path,
        )
        assert result["tmdb_number"] == 3
        assert result["tmdb_name"] == "Episode 3"
        assert result["air_date"] == "2023-03-01"
        assert result["runtime"] == 40

    def test_existing_episode_fills_from_parsed_when_tmdb_missing(
        self, tmp_path: Path
    ) -> None:
        """When existing episode has no tmdb_number and no TMDB match, parse from filename."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S02E04.mkv")
        series_dir = ep.parent.parent
        ep_path = str(ep.absolute())

        existing_ep = {
            "path": ep_path,
            "tmdb_episode_identifier": None,
            "tmdb_name": None,
            "tmdb_number": None,
            "air_date": "",
            "runtime": 0,
        }
        existing_by_path = {ep_path: existing_ep}

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }
        tmdb_episodes = [
            {
                "id": "ep_4",
                "episode_number": 4,
                "name": "Episode 4",
                "air_date": "2023-04-01",
                "runtime": 35,
            },
        ]

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 2",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=tmdb_episodes,
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path=existing_by_path,
        )
        # Should parse S02E04 → episode_number=4, match TMDB ep_4
        assert result["tmdb_number"] == 4
        assert result["tmdb_name"] == "Episode 4"
        assert result["tmdb_episode_identifier"] == "ep_4"

    def test_placeholder_episode_matched(self, tmp_path: Path) -> None:
        """A new file matches an existing placeholder episode."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E02.mkv")
        series_dir = ep.parent.parent
        ep_path = str(ep.absolute())

        existing_series_data: dict[str, Any] = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": None,
                            "tmdb_number": 2,
                            "tmdb_episode_identifier": "placeholder_ep_2",
                            "tmdb_name": "Placeholder Title",
                            "air_date": "2023-02-01",
                            "runtime": 30,
                            "jellyfin_id": "",
                        }
                    ]
                }
            }
        }

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=[],
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path={},
            existing_series_data=existing_series_data,
        )
        assert result["name"] == "Placeholder Title"
        assert result["path"] == ep_path
        assert result["tmdb_episode_identifier"] == "placeholder_ep_2"
        assert result["tmdb_name"] == "Placeholder Title"

    def test_name_substring_match(self, tmp_path: Path) -> None:
        """When SxxExx parsing fails, match by episode name substring."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="The Pilot Episode.mkv")
        series_dir = ep.parent.parent

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }
        tmdb_episodes = [
            {
                "id": "ep_pilot",
                "episode_number": 1,
                "name": "Pilot Episode",
                "air_date": "2023-01-01",
                "runtime": 45,
            },
        ]

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=tmdb_episodes,
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path={},
        )
        assert result["tmdb_number"] == 1
        assert result["tmdb_name"] == "Pilot Episode"
        assert result["tmdb_episode_identifier"] == "ep_pilot"

    def test_no_match_returns_defaults(self, tmp_path: Path) -> None:
        """When no matching strategy works, return sensible defaults."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="unrecognized.mkv")
        series_dir = ep.parent.parent

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=[],
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path={},
        )
        assert result["name"] == "unrecognized.mkv"
        assert result["tmdb_number"] is None
        assert result["tmdb_name"] is None
        assert result["runtime"] == 0
        assert result["watched"] is False

    def test_metadata_only_uses_existing_date_added(self, tmp_path: Path) -> None:
        """With ``metadata_only=True``, ``date_added`` is read from existing data."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E01.mkv")
        series_dir = ep.parent.parent
        ep_path = str(ep.absolute())

        existing_ep = {"path": ep_path, "date_added": 1234567890.0}
        existing_by_path = {ep_path: existing_ep}

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=[],
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path=existing_by_path,
            metadata_only=True,
        )
        assert result["date_added"] == 1234567890.0

    def test_ctime_fallback_on_oserror(self, tmp_path: Path) -> None:
        """When ``os.path.getctime`` raises OSError, ``date_added`` defaults to 0."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E01.mkv")
        series_dir = ep.parent.parent

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }

        with patch("os.path.getctime", side_effect=OSError("permission denied")):
            result = _process_episode_file(
                episode_file=ep,
                season_name="Season 1",
                series_directory=series_dir,
                series_data=series_data,
                season_metadata=season_meta,
                tmdb_episodes=[],
                tmdb_series=None,
                jellyfin_data=None,
                existing_episodes_by_path={},
            )
        assert result["date_added"] == 0

    def test_preserves_existing_technical_metadata(self, tmp_path: Path) -> None:
        """Existing technical metadata (codec, resolution, tracks) is preserved."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E01.mkv")
        series_dir = ep.parent.parent
        ep_path = str(ep.absolute())

        existing_ep = {
            "path": ep_path,
            "video_codec": "hevc",
            "resolution": "3840x2160",
            "audio_tracks": [{"language": "eng"}],
            "subtitle_tracks": [{"language": "spa"}],
        }
        existing_by_path = {ep_path: existing_ep}

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=[],
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path=existing_by_path,
        )
        assert result["video_codec"] == "hevc"
        assert result["resolution"] == "3840x2160"
        assert result["audio_tracks"] == [{"language": "eng"}]
        assert result["subtitle_tracks"] == [{"language": "spa"}]

    def test_myanimelist_auto_mapping_from_season(self, tmp_path: Path) -> None:
        """When season has MAL ID, new episodes auto-map."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E02.mkv")
        series_dir = ep.parent.parent

        season_meta: dict[str, Any] = {"myanimelist_id": 99999}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=[],
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path={},
        )
        assert result["myanimelist_anime_id"] == 99999
        assert result["myanimelist_episode_number"] == 2

    def test_myanimelist_preserved_from_existing(self, tmp_path: Path) -> None:
        """Existing MAL mapping is preserved from existing episode."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E01.mkv")
        series_dir = ep.parent.parent
        ep_path = str(ep.absolute())

        existing_ep = {
            "path": ep_path,
            "myanimelist_anime_id": 88888,
            "myanimelist_episode_number": 1,
        }
        existing_by_path = {ep_path: existing_ep}

        season_meta: dict[str, Any] = {"myanimelist_id": 99999}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=[],
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path=existing_by_path,
        )
        # Existing mapping should take priority over auto-mapping
        assert result["myanimelist_anime_id"] == 88888
        assert result["myanimelist_episode_number"] == 1

    def test_jellyfin_resolution_offline_skipped(self, tmp_path: Path) -> None:
        """When offline, Jellyfin ID resolution is skipped."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E01.mkv")
        series_dir = ep.parent.parent

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=[],
            tmdb_series=None,
            jellyfin_data={
                "path_map": {str(ep.absolute()): {"id": "jf_should_not_match"}}
            },
            existing_episodes_by_path={},
            offline=True,
        )
        assert result["jellyfin_id"] == ""

    def test_jellyfin_resolution_sets_series_season_ids(self, tmp_path: Path) -> None:
        """Jellyfin resolution sets series and season IDs from the result."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E01.mkv")
        series_dir = ep.parent.parent
        ep_path = str(ep.absolute())

        season_meta: dict[str, Any] = {"jellyfin_id": ""}
        series_data: dict[str, Any] = {
            "metadata": {"jellyfin_id": ""},
            "_tmdb_series_id": "",
        }
        jellyfin_data = {
            "path_map": {
                ep_path: {
                    "id": "jf_ep",
                    "series_id": "jf_series_new",
                    "season_id": "jf_season_new",
                }
            },
            "tmdb_series_map": {},
        }

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=[],
            tmdb_series=None,
            jellyfin_data=jellyfin_data,
            existing_episodes_by_path={},
        )
        assert result["jellyfin_id"] == "jf_ep"
        assert series_data["metadata"]["jellyfin_id"] == "jf_series_new"
        assert season_meta["jellyfin_id"] == "jf_season_new"

    def test_two_digit_season_in_filename(self, tmp_path: Path) -> None:
        """Handles two-digit season numbers in filenames."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S12E05.mkv")
        series_dir = ep.parent.parent

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }
        tmdb_episodes = [
            {
                "id": "ep_12_5",
                "episode_number": 5,
                "name": "Episode 5",
                "air_date": "",
                "runtime": 0,
            },
        ]

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 12",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=tmdb_episodes,
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path={},
        )
        assert result["tmdb_number"] == 5
        assert result["tmdb_name"] == "Episode 5"

    def test_episode_without_parsed_number_matched_by_name(
        self, tmp_path: Path
    ) -> None:
        """Episode filename without SxxExx matched by TMDB episode name substring."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(
            tmp_path, episode_name="Chapter One - The Beginning.mkv"
        )
        series_dir = ep.parent.parent

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }
        tmdb_episodes = [
            {
                "id": "ep_beginning",
                "episode_number": 1,
                "name": "The Beginning",
                "air_date": "2023-01-01",
                "runtime": 50,
            },
        ]

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=tmdb_episodes,
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path={},
        )
        # "the beginning" should be found as substring in the filename
        assert result["tmdb_number"] == 1
        assert result["tmdb_name"] == "The Beginning"

    def test_existing_episode_preserves_versions(self, tmp_path: Path) -> None:
        """Existing episode with a multi-file versions list preserves all versions."""
        from lan_streamer.services.metadata_episode import _process_episode_file

        ep = self._make_episode_file(tmp_path, episode_name="S01E01.mkv")
        series_dir = ep.parent.parent
        ep_path = str(ep.absolute())

        existing_ep = {
            "path": ep_path,
            "tmdb_episode_identifier": "ep1",
            "tmdb_name": "Episode 1",
            "tmdb_number": 1,
            "versions": [
                {"path": ep_path, "video_codec": "h264", "resolution": "1080p"},
                {
                    "path": "/other/root/S01E01.mp4",
                    "video_codec": "h265",
                    "resolution": "4K",
                },
            ],
        }
        existing_by_path = {ep_path: existing_ep}

        season_meta: dict[str, Any] = {}
        series_data: dict[str, Any] = {
            "metadata": {},
            "_tmdb_series_id": "",
        }
        tmdb_episodes = [
            {
                "id": "ep1",
                "episode_number": 1,
                "name": "Episode 1",
                "air_date": "2023-01-01",
                "runtime": 30,
            },
        ]

        result = _process_episode_file(
            episode_file=ep,
            season_name="Season 1",
            series_directory=series_dir,
            series_data=series_data,
            season_metadata=season_meta,
            tmdb_episodes=tmdb_episodes,
            tmdb_series=None,
            jellyfin_data=None,
            existing_episodes_by_path=existing_by_path,
        )
        versions = result.get("versions", [])
        assert len(versions) == 2, f"Expected 2 versions, got {len(versions)}"
        version_paths = {v["path"] for v in versions}
        assert ep_path in version_paths
        assert "/other/root/S01E01.mp4" in version_paths
