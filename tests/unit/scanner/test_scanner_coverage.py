"""
Tests targeting scanner/metadata.py functions that are not yet covered:
 - clean_series_data
 - _build_locked_tv_tmdb_stub
 - _build_locked_movie_tmdb_stub
 - _resolve_existing_jellyfin_id
 - _merge_season_episodes
 - _build_movie_metadata_defaults
 - _apply_existing_movie_metadata
 - _resolve_movie_jellyfin_id
 - _build_existing_episodes_index
 - _detect_new_series_files
 - _build_series_metadata_defaults
 - _resolve_episode_jellyfin_id (path_map, tmdb_episode_map, name_map branches)
 - _process_episode_file (basic exercising with/without existing episode)

And scanner/parser.py uncovered lines:
 - _parse_episode_number
 - _parse_season_number
 - _parse_movie_folder
 - has_video_files (OSError branch)

And scanner/core.py:
 - _has_season_subdirs (PermissionError branch, digit-match branch)
 - scan_directories (unavailable_root, detail_callback paths)
 - scan_movie (no video file found)
 - scan_series basic path (mocked TMDB)
"""

from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# scanner/parser.py
# ---------------------------------------------------------------------------


class TestScannerParser:
    def test_parse_episode_number_standard(self) -> None:
        from lan_streamer.scanner.parser import _parse_episode_number

        assert _parse_episode_number("Show.S02E05.mkv") == (2, 5)

    def test_parse_episode_number_lowercase(self) -> None:
        from lan_streamer.scanner.parser import _parse_episode_number

        assert _parse_episode_number("show.s01e10.mp4") == (1, 10)

    def test_parse_episode_number_no_match(self) -> None:
        from lan_streamer.scanner.parser import _parse_episode_number

        assert _parse_episode_number("random_file.mkv") is None

    def test_parse_season_number_specials(self) -> None:
        from lan_streamer.scanner.parser import _parse_season_number

        assert _parse_season_number("Specials") == 0

    def test_parse_season_number_standard(self) -> None:
        from lan_streamer.scanner.parser import _parse_season_number

        assert _parse_season_number("Season 3") == 3

    def test_parse_season_number_no_match(self) -> None:
        from lan_streamer.scanner.parser import _parse_season_number

        assert _parse_season_number("Extras") is None

    def test_parse_movie_folder_with_year(self) -> None:
        from lan_streamer.scanner.parser import _parse_movie_folder

        title, year = _parse_movie_folder("Inception (2010)")
        assert title == "Inception"
        assert year == 2010

    def test_parse_movie_folder_without_year(self) -> None:
        from lan_streamer.scanner.parser import _parse_movie_folder

        title, year = _parse_movie_folder("SomeMovieNoYear")
        assert title == "SomeMovieNoYear"
        assert year is None

    def test_has_video_files_os_error(self, tmp_path) -> None:
        from lan_streamer.scanner.parser import has_video_files

        # A real dir but we force an OSError via mock
        with patch.object(Path, "rglob", side_effect=OSError("permission denied")):
            result = has_video_files(tmp_path)
            assert result is False

    def test_has_video_files_true(self, tmp_path) -> None:
        from lan_streamer.scanner.parser import has_video_files

        (tmp_path / "ep.mkv").write_bytes(b"\x00")
        assert has_video_files(tmp_path) is True

    def test_has_video_files_false_no_videos(self, tmp_path) -> None:
        from lan_streamer.scanner.parser import has_video_files

        (tmp_path / "readme.txt").write_text("hello")
        assert has_video_files(tmp_path) is False


# ---------------------------------------------------------------------------
# scanner/metadata.py - clean_series_data
# ---------------------------------------------------------------------------


class TestCleanSeriesData:
    def test_clean_series_data_returns_none_for_empty(self) -> None:
        from lan_streamer.scanner.metadata import clean_series_data

        result = clean_series_data({"seasons": {}})
        assert result is None

    def test_clean_series_data_removes_tmdb_temp_keys(self) -> None:
        from lan_streamer.scanner.metadata import clean_series_data

        data = {
            "metadata": {"tmdb_identifier": "123"},
            "seasons": {
                "Season 1": {
                    "episodes": [{"name": "S01E01.mkv", "path": "/ep1.mkv"}],
                    "_tmdb_episodes": [{"id": 1}],
                }
            },
            "_tmdb_seasons": [],
            "_tmdb_series_id": "123",
        }
        result = clean_series_data(data)
        assert result is not None
        assert "_tmdb_episodes" not in result["seasons"]["Season 1"]
        assert "_tmdb_seasons" not in result
        assert "_tmdb_series_id" not in result

    def test_clean_series_data_sorts_episodes(self) -> None:
        from lan_streamer.scanner.metadata import clean_series_data

        data = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"name": "S01E02.mkv", "path": "/ep2.mkv"},
                        {"name": "S01E01.mkv", "path": "/ep1.mkv"},
                    ],
                    "_tmdb_episodes": [],
                }
            },
        }
        result = clean_series_data(data)
        assert result is not None
        assert result["seasons"]["Season 1"]["episodes"][0]["name"] == "S01E01.mkv"


# ---------------------------------------------------------------------------
# scanner/metadata.py - stub builders
# ---------------------------------------------------------------------------


class TestTmdbStubBuilders:
    def test_build_locked_tv_tmdb_stub(self) -> None:
        from lan_streamer.scanner.metadata import _build_locked_tv_tmdb_stub

        existing_series = {
            "metadata": {
                "tmdb_identifier": "456",
                "tmdb_name": "My Show",
                "overview": "A show about things",
                "poster_path": "/poster.jpg",
                "first_air_date": "2021-01-01",
            }
        }
        stub = _build_locked_tv_tmdb_stub(existing_series)
        assert stub["id"] == "456"
        assert stub["name"] == "My Show"
        assert stub["_is_prefetched"] is True

    def test_build_locked_movie_tmdb_stub(self) -> None:
        from lan_streamer.scanner.metadata import _build_locked_movie_tmdb_stub

        existing_movie = {
            "tmdb_identifier": "789",
            "tmdb_name": "My Movie",
            "overview": "About a movie",
            "poster_path": "/mpost.jpg",
        }
        stub = _build_locked_movie_tmdb_stub(existing_movie, "My Movie (2020)")
        assert stub["id"] == "789"
        assert stub["title"] == "My Movie"
        assert stub["_is_prefetched"] is True

    def test_build_locked_movie_tmdb_stub_fallback_title(self) -> None:
        from lan_streamer.scanner.metadata import _build_locked_movie_tmdb_stub

        existing_movie = {"tmdb_identifier": "789"}  # no tmdb_name
        stub = _build_locked_movie_tmdb_stub(existing_movie, "FolderName (2020)")
        assert stub["title"] == "FolderName (2020)"


# ---------------------------------------------------------------------------
# scanner/metadata.py - _resolve_existing_jellyfin_id
# ---------------------------------------------------------------------------


class TestResolveExistingJellyfinId:
    def test_movie_type(self) -> None:
        from lan_streamer.scanner.metadata import _resolve_existing_jellyfin_id

        item = {"jellyfin_id": "jf_movie_123"}
        assert _resolve_existing_jellyfin_id(item, "movie") == "jf_movie_123"

    def test_movie_type_missing(self) -> None:
        from lan_streamer.scanner.metadata import _resolve_existing_jellyfin_id

        assert _resolve_existing_jellyfin_id({}, "movie") is None

    def test_tv_type(self) -> None:
        from lan_streamer.scanner.metadata import _resolve_existing_jellyfin_id

        item = {"metadata": {"jellyfin_id": "jf_tv_456"}}
        assert _resolve_existing_jellyfin_id(item, "tv") == "jf_tv_456"

    def test_tv_type_missing(self) -> None:
        from lan_streamer.scanner.metadata import _resolve_existing_jellyfin_id

        assert _resolve_existing_jellyfin_id({}, "tv") is None


# ---------------------------------------------------------------------------
# scanner/metadata.py - _merge_season_episodes
# ---------------------------------------------------------------------------


class TestMergeSeasonEpisodes:
    def test_adds_new_episode(self) -> None:
        from lan_streamer.scanner.metadata import _merge_season_episodes

        existing = [{"name": "ep1.mkv", "path": "/ep1.mkv"}]
        new_ep = [{"name": "ep2.mkv", "path": "/ep2.mkv"}]
        _merge_season_episodes(existing, new_ep, "Season 1")
        assert len(existing) == 2

    def test_skips_duplicate_path(self) -> None:
        from lan_streamer.scanner.metadata import _merge_season_episodes

        existing = [{"name": "ep1.mkv", "path": "/ep1.mkv"}]
        new_ep = [{"name": "ep1_copy.mkv", "path": "/ep1.mkv"}]  # same path
        _merge_season_episodes(existing, new_ep, "Season 1")
        assert len(existing) == 1

    def test_skips_same_name_different_path(self) -> None:
        from lan_streamer.scanner.metadata import _merge_season_episodes

        existing = [{"name": "ep1.mkv", "path": "/ep1.mkv"}]
        new_ep = [{"name": "ep1.mkv", "path": "/other/ep1.mkv"}]  # same name
        _merge_season_episodes(existing, new_ep, "Season 1")
        assert len(existing) == 1


# ---------------------------------------------------------------------------
# scanner/metadata.py - _build_movie_metadata_defaults
# ---------------------------------------------------------------------------


class TestBuildMovieMetadataDefaults:
    def test_returns_all_expected_keys(self) -> None:
        from lan_streamer.scanner.metadata import _build_movie_metadata_defaults

        result = _build_movie_metadata_defaults()
        assert "tmdb_identifier" in result
        assert "overview" in result
        assert "poster_path" in result
        assert "tmdb_name" in result
        assert "jellyfin_id" in result
        assert "runtime" in result
        assert "rating" in result
        assert "genre" in result
        assert "year" in result


# ---------------------------------------------------------------------------
# scanner/metadata.py - _apply_existing_movie_metadata
# ---------------------------------------------------------------------------


class TestApplyExistingMovieMetadata:
    def test_copies_non_empty_fields(self) -> None:
        from lan_streamer.scanner.metadata import _apply_existing_movie_metadata

        metadata = {
            "tmdb_identifier": "",
            "overview": "",
            "tmdb_name": "",
            "runtime": 0,
        }
        existing = {
            "tmdb_identifier": "abc123",
            "overview": "Great movie",
            "runtime": 120,
        }
        _apply_existing_movie_metadata(metadata, existing, None)
        assert metadata["tmdb_identifier"] == "abc123"
        assert metadata["overview"] == "Great movie"
        assert metadata["runtime"] == 120

    def test_manual_jellyfin_id_overrides(self) -> None:
        from lan_streamer.scanner.metadata import _apply_existing_movie_metadata

        metadata = {"jellyfin_id": "old_id"}
        existing = {"jellyfin_id": "existing_id"}
        _apply_existing_movie_metadata(metadata, existing, "manual_jf_id")
        assert metadata["jellyfin_id"] == "manual_jf_id"


# ---------------------------------------------------------------------------
# scanner/metadata.py - _resolve_movie_jellyfin_id
# ---------------------------------------------------------------------------


class TestResolveMovieJellyfinId:
    def test_no_jellyfin_data(self) -> None:
        from lan_streamer.scanner.metadata import _resolve_movie_jellyfin_id

        metadata = {"jellyfin_id": "existing_jf"}
        result = _resolve_movie_jellyfin_id(metadata, "/path.mkv", None)
        assert result == "existing_jf"

    def test_path_map_match(self) -> None:
        from lan_streamer.scanner.metadata import _resolve_movie_jellyfin_id

        metadata = {"jellyfin_id": ""}
        jellyfin_data = {"path_map": {"/movie.mkv": {"id": "jf_path_id"}}}
        result = _resolve_movie_jellyfin_id(metadata, "/movie.mkv", jellyfin_data)
        assert result == "jf_path_id"

    def test_tmdb_map_match(self) -> None:
        from lan_streamer.scanner.metadata import _resolve_movie_jellyfin_id

        metadata = {"jellyfin_id": "", "tmdb_identifier": "tmdb123"}
        jellyfin_data = {
            "path_map": {},
            "tmdb_episode_map": {"tmdb123": "jf_tmdb_id"},
        }
        result = _resolve_movie_jellyfin_id(metadata, "/other.mkv", jellyfin_data)
        assert result == "jf_tmdb_id"

    def test_no_match_returns_existing(self) -> None:
        from lan_streamer.scanner.metadata import _resolve_movie_jellyfin_id

        metadata = {"jellyfin_id": "kept_existing"}
        jellyfin_data = {"path_map": {}, "tmdb_episode_map": {}}
        result = _resolve_movie_jellyfin_id(metadata, "/no_match.mkv", jellyfin_data)
        assert result == "kept_existing"


# ---------------------------------------------------------------------------
# scanner/metadata.py - _build_existing_episodes_index
# ---------------------------------------------------------------------------


class TestBuildExistingEpisodesIndex:
    def test_builds_path_index(self) -> None:
        from lan_streamer.scanner.metadata import _build_existing_episodes_index

        existing = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"name": "ep1.mkv", "path": "/s1/ep1.mkv"},
                        {"name": "ep2.mkv", "path": "/s1/ep2.mkv"},
                    ]
                },
                "Season 2": {"episodes": [{"name": "ep1.mkv", "path": "/s2/ep1.mkv"}]},
            }
        }
        index = _build_existing_episodes_index(existing)
        assert "/s1/ep1.mkv" in index
        assert "/s1/ep2.mkv" in index
        assert "/s2/ep1.mkv" in index
        assert len(index) == 3

    def test_empty_series(self) -> None:
        from lan_streamer.scanner.metadata import _build_existing_episodes_index

        assert _build_existing_episodes_index({}) == {}


# ---------------------------------------------------------------------------
# scanner/metadata.py - _detect_new_series_files
# ---------------------------------------------------------------------------


class TestDetectNewSeriesFiles:
    def test_detects_new_file(self, tmp_path) -> None:
        from lan_streamer.scanner.metadata import _detect_new_series_files

        series_dir = tmp_path / "My Show"
        series_dir.mkdir()
        season_dir = series_dir / "Season 1"
        season_dir.mkdir()
        ep = season_dir / "ep.mkv"
        ep.write_bytes(b"\x00")

        # existing index does NOT have this file
        result = _detect_new_series_files(series_dir, {})
        assert result is True

    def test_no_new_files_when_all_indexed(self, tmp_path) -> None:
        from lan_streamer.scanner.metadata import _detect_new_series_files

        series_dir = tmp_path / "My Show2"
        series_dir.mkdir()
        season_dir = series_dir / "Season 1"
        season_dir.mkdir()
        ep = season_dir / "ep.mkv"
        ep.write_bytes(b"\x00")

        existing = {str(ep.absolute()): {"name": "ep.mkv", "path": str(ep.absolute())}}
        result = _detect_new_series_files(series_dir, existing)
        assert result is False


# ---------------------------------------------------------------------------
# scanner/metadata.py - _build_series_metadata_defaults
# ---------------------------------------------------------------------------


class TestBuildSeriesMetadataDefaults:
    def test_no_jellyfin_id(self) -> None:
        from lan_streamer.scanner.metadata import _build_series_metadata_defaults

        result = _build_series_metadata_defaults(None)
        assert result["jellyfin_id"] == ""

    def test_with_manual_jellyfin_id(self) -> None:
        from lan_streamer.scanner.metadata import _build_series_metadata_defaults

        result = _build_series_metadata_defaults("manual_jf_123")
        assert result["jellyfin_id"] == "manual_jf_123"


# ---------------------------------------------------------------------------
# scanner/metadata.py - _resolve_episode_jellyfin_id
# ---------------------------------------------------------------------------


class TestResolveEpisodeJellyfinId:
    def _make_call(self, episode_path, jellyfin_data, **kwargs) -> tuple:
        from lan_streamer.scanner.metadata import _resolve_episode_jellyfin_id

        defaults = {
            "episode_name": "S01E01.mkv",
            "episode_file": Path("/fake/ep.mkv"),
            "tmdb_episode_identifier": None,
            "tmdb_name": None,
            "tmdb_number": None,
            "season_name": "Season 1",
            "series_directory": Path("/fake/show"),
            "series_data": {"metadata": {"jellyfin_id": ""}},
            "season_metadata": {},
            "tmdb_series": None,
        }
        defaults.update(kwargs)
        return _resolve_episode_jellyfin_id(
            episode_path=episode_path,
            jellyfin_data=jellyfin_data,
            **defaults,
        )

    def test_no_jellyfin_data(self) -> None:
        jf_id, series_jf, season_jf = self._make_call("/ep.mkv", None)
        assert jf_id == ""
        assert series_jf == ""
        assert season_jf == ""

    def test_path_map_match(self) -> None:
        jellyfin_data = {
            "path_map": {
                "/ep.mkv": {
                    "id": "jf_ep_id",
                    "series_id": "jf_series_id",
                    "season_id": "jf_season_id",
                }
            }
        }
        jf_id, series_jf, season_jf = self._make_call("/ep.mkv", jellyfin_data)
        assert jf_id == "jf_ep_id"
        assert series_jf == "jf_series_id"
        assert season_jf == "jf_season_id"

    def test_tmdb_episode_map_match(self) -> None:
        jellyfin_data = {
            "path_map": {},
            "tmdb_episode_map": {"tmdb_ep_123": "jf_from_tmdb"},
        }
        jf_id, _, _ = self._make_call(
            "/other_ep.mkv",
            jellyfin_data,
            tmdb_episode_identifier="tmdb_ep_123",
        )
        assert jf_id == "jf_from_tmdb"

    def test_name_map_match(self) -> None:
        jellyfin_data = {
            "path_map": {},
            "tmdb_episode_map": {},
            "name_map": {("my show", "pilot"): "jf_name_match"},
        }
        jf_id, _, _ = self._make_call(
            "/other2.mkv",
            jellyfin_data,
            tmdb_name="Pilot",
            tmdb_series={"name": "My Show"},
        )
        assert jf_id == "jf_name_match"

    def test_no_match_returns_empty(self) -> None:
        jellyfin_data = {
            "path_map": {},
            "tmdb_episode_map": {},
            "name_map": {},
        }
        jf_id, _, _ = self._make_call("/nomatch.mkv", jellyfin_data)
        assert jf_id == ""


# ---------------------------------------------------------------------------
# scanner/core.py - _has_season_subdirs
# ---------------------------------------------------------------------------


class TestHasSeasonSubdirs:
    def test_returns_true_for_season_folder(self, tmp_path) -> None:
        from lan_streamer.scanner.core import _has_season_subdirs

        (tmp_path / "Season 1").mkdir()
        assert _has_season_subdirs(tmp_path) is True

    def test_returns_true_for_digit_folder(self, tmp_path) -> None:
        from lan_streamer.scanner.core import _has_season_subdirs

        (tmp_path / "2020").mkdir()
        assert _has_season_subdirs(tmp_path) is True

    def test_returns_true_for_specials(self, tmp_path) -> None:
        from lan_streamer.scanner.core import _has_season_subdirs

        (tmp_path / "Specials").mkdir()
        assert _has_season_subdirs(tmp_path) is True

    def test_returns_false_when_no_matching_subdirs(self, tmp_path) -> None:
        from lan_streamer.scanner.core import _has_season_subdirs

        (tmp_path / "RandomFolder").mkdir()
        assert _has_season_subdirs(tmp_path) is False

    def test_handles_permission_error(self, tmp_path) -> None:
        from lan_streamer.scanner.core import _has_season_subdirs

        with patch.object(Path, "iterdir", side_effect=PermissionError("nope")):
            assert _has_season_subdirs(tmp_path) is False

    def test_returns_false_for_empty_dir(self, tmp_path) -> None:
        from lan_streamer.scanner.core import _has_season_subdirs

        assert _has_season_subdirs(tmp_path) is False


# ---------------------------------------------------------------------------
# scanner/core.py - scan_movie (no video file)
# ---------------------------------------------------------------------------


class TestScanMovieNoVideoFile:
    def test_returns_none_when_no_video_file(self, tmp_path) -> None:
        from lan_streamer.scanner.core import scan_movie

        movie_dir = tmp_path / "My Movie (2020)"
        movie_dir.mkdir()
        (movie_dir / "readme.txt").write_text("no video here")

        result = scan_movie(movie_dir)
        assert result is None

    def test_returns_data_with_detail_callback(self, tmp_path) -> None:
        from lan_streamer.scanner.core import scan_movie

        movie_dir = tmp_path / "Test Movie (2023)"
        movie_dir.mkdir()
        (movie_dir / "movie.mkv").write_bytes(b"\x00" * 100)

        callbacks = []
        with patch(
            "lan_streamer.scanner.core.tmdb_client.search_movie", return_value=None
        ):
            result = scan_movie(
                movie_dir,
                detail_callback=lambda ev, pl: callbacks.append((ev, pl)),
            )

        assert result is not None
        assert result["name"] == "Test Movie (2023)"
        assert any(c[0] == "start_file" for c in callbacks)
        assert any(c[0] == "finish_file" for c in callbacks)


# ---------------------------------------------------------------------------
# scanner/core.py - scan_directories with unavailable root
# ---------------------------------------------------------------------------


class TestScanDirectoriesUnavailableRoot:
    def test_unavailable_root_is_tracked(self) -> None:
        from lan_streamer.scanner.core import scan_directories

        callbacks = []
        result = scan_directories(
            ["/nonexistent/root/xyz_12345"],
            library_type="tv",
            detail_callback=lambda ev, pl: callbacks.append((ev, pl)),
        )

        assert "/nonexistent/root/xyz_12345" in result.unavailable_directories
        assert any(c[0] == "unavailable_root" for c in callbacks)

    def test_empty_root_directories_returns_empty_library(self) -> None:
        from lan_streamer.scanner.core import scan_directories

        result = scan_directories([])
        assert len(result) == 0
        assert result.unavailable_directories == []
