"""Unit tests for the extracted helper functions in lan_streamer.scanner.scan_movie."""

from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from lan_streamer.scanner.scan_movie import (
    _build_movie_data,
    _detect_movie_changes,
    _handle_early_return,
    _resolve_tmdb_movie_data,
    _scan_movie_files,
    scan_movie,
)


# ---------------------------------------------------------------------------
# _detect_movie_changes
# ---------------------------------------------------------------------------


def test_detect_movie_changes_no_existing() -> None:
    """No existing data means both changed and not-offline."""
    result = _detect_movie_changes(Path("/dummy"), None, offline=False)
    assert result == (True, False)


def test_detect_movie_changes_offline_unchanged() -> None:
    """Offline means movie_offline even if unchanged."""
    existing = {"_changed": False}
    result = _detect_movie_changes(Path("/dummy"), existing, offline=True)
    assert result[1] is True  # movie_offline


def test_detect_movie_changes_online_with_changed_flag() -> None:
    """Online mode with _changed=True makes movie_offline=False."""
    existing = {"_changed": True}
    with patch(
        "lan_streamer.services.file_discovery.detect_movie_file_changes",
        return_value=False,
    ):
        result = _detect_movie_changes(Path("/dummy"), existing, offline=False)
    assert result == (True, False)


def test_detect_movie_changes_file_detected() -> None:
    """File changes detected even without _changed flag."""
    existing = {}
    with patch(
        "lan_streamer.services.file_discovery.detect_movie_file_changes",
        return_value=True,
    ):
        result = _detect_movie_changes(Path("/dummy"), existing, offline=False)
    assert result == (True, False)


# ---------------------------------------------------------------------------
# _scan_movie_files
# ---------------------------------------------------------------------------


def test_scan_files_metadata_only_no_data() -> None:
    """metadata_only with no existing data returns None."""
    result = _scan_movie_files(
        Path("/dummy"),
        None,
        movie_offline=False,
        force_refresh=False,
        metadata_only=True,
    )
    assert result is None


def test_scan_files_metadata_only_with_versions(tmp_path: Path) -> None:
    """metadata_only returns existing versions directly."""
    existing = {
        "versions": [{"path": "/m1.mkv", "video_codec": "h264"}],
        "default_path": "/m1.mkv",
        "path": "/m1.mkv",
        "date_added": 100,
    }
    result = _scan_movie_files(
        tmp_path,
        existing,
        movie_offline=False,
        force_refresh=False,
        metadata_only=True,
    )
    assert result is not None
    assert len(result["versions"]) == 1
    assert result["versions"][0]["path"] == "/m1.mkv"
    assert result["video_path"] == "/m1.mkv"
    assert result["ctime"] == 100


def test_scan_files_metadata_only_path_fallback(tmp_path: Path) -> None:
    """metadata_only creates a stub version when existing has no versions but has path."""
    existing = {
        "path": "/m1.mkv",
        "date_added": 200,
    }
    with patch(
        "lan_streamer.scanner.scan_movie.get_stub_file_info",
        return_value={"path": "/m1.mkv", "video_codec": "stub"},
    ):
        result = _scan_movie_files(
            tmp_path,
            existing,
            movie_offline=False,
            force_refresh=False,
            metadata_only=True,
        )
    assert result is not None
    assert len(result["versions"]) == 1
    assert result["versions"][0]["path"] == "/m1.mkv"
    assert result["ctime"] == 200


def test_scan_files_metadata_only_no_video_path(tmp_path: Path) -> None:
    """metadata_only returns None when active_version has no path."""
    existing = {"versions": [{"not_a_path": True}]}
    result = _scan_movie_files(
        tmp_path,
        existing,
        movie_offline=False,
        force_refresh=False,
        metadata_only=True,
    )
    assert result is None


def test_scan_files_normal_no_video_files(tmp_path: Path) -> None:
    """Normal path returns None when no video files found."""
    result = _scan_movie_files(
        tmp_path,
        None,
        movie_offline=False,
        force_refresh=False,
        metadata_only=False,
    )
    assert result is None


def test_scan_files_normal_single_file(tmp_path: Path) -> None:
    """Normal path scans a single video file."""
    movie_dir = tmp_path / "Movie (2020)"
    movie_dir.mkdir()
    video = movie_dir / "movie.mkv"
    video.touch()

    result = _scan_movie_files(
        movie_dir,
        None,
        movie_offline=False,
        force_refresh=False,
        metadata_only=False,
    )
    assert result is not None
    assert len(result["versions"]) == 1
    assert result["video_path"].endswith("movie.mkv")
    assert result["video_file"].name == "movie.mkv"


def test_scan_files_normal_multiple_files(tmp_path: Path) -> None:
    """Normal path returns multiple versions for multiple video files."""
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    (movie_dir / "m1.mkv").touch()
    (movie_dir / "m2.mkv").touch()

    result = _scan_movie_files(
        movie_dir,
        None,
        movie_offline=False,
        force_refresh=False,
        metadata_only=False,
    )
    assert result is not None
    assert len(result["versions"]) == 2
    # active_version picks one of them
    assert result["active_version"] is not None


def test_scan_files_normal_reuses_existing(tmp_path: Path) -> None:
    """Reuses existing version data when not force_refresh."""
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    video = movie_dir / "m.mkv"
    video.touch()
    existing = {
        "versions": [{"path": str(video.absolute()), "video_codec": "h265"}],
        "default_path": str(video.absolute()),
    }

    result = _scan_movie_files(
        movie_dir,
        existing,
        movie_offline=False,
        force_refresh=False,
        metadata_only=False,
    )
    assert result is not None
    assert result["versions"][0]["video_codec"] == "h265"


def test_scan_files_normal_force_refresh_rescans(tmp_path: Path) -> None:
    """force_refresh=True does not reuse existing version."""
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    video = movie_dir / "m.mkv"
    video.touch()
    existing = {
        "versions": [{"path": str(video.absolute()), "video_codec": "h265"}],
        "default_path": str(video.absolute()),
    }

    result = _scan_movie_files(
        movie_dir,
        existing,
        movie_offline=False,
        force_refresh=True,
        metadata_only=False,
    )
    assert result is not None
    assert result["versions"][0].get("video_codec") != "h265"


def test_scan_files_normal_offline_uses_stub(tmp_path: Path) -> None:
    """Offline mode uses get_stub_file_info instead of get_detailed_file_info."""
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    (movie_dir / "m.mkv").touch()

    with (
        patch(
            "lan_streamer.scanner.scan_movie.get_stub_file_info",
            return_value={"path": "stub", "stub": True},
        ) as stub_mock,
        patch(
            "lan_streamer.scanner.scan_movie.get_detailed_file_info",
        ) as detailed_mock,
    ):
        result = _scan_movie_files(
            movie_dir,
            None,
            movie_offline=True,
            force_refresh=False,
            metadata_only=False,
        )
    assert result is not None
    stub_mock.assert_called()
    detailed_mock.assert_not_called()


def test_scan_files_normal_online_rescans_stubs(tmp_path: Path) -> None:
    """Online mode rescans a version that was previously recorded as a stub (Unknown codec/resolution)."""
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    video = movie_dir / "m.mkv"
    video.touch()
    existing = {
        "versions": [
            {
                "path": str(video.absolute()),
                "video_codec": "Unknown",
                "resolution": "Unknown",
            }
        ],
        "default_path": str(video.absolute()),
    }

    with (
        patch(
            "lan_streamer.scanner.scan_movie.get_stub_file_info",
        ) as stub_mock,
        patch(
            "lan_streamer.scanner.scan_movie.get_detailed_file_info",
            return_value={
                "path": str(video.absolute()),
                "video_codec": "hevc",
                "resolution": "1920x1080",
            },
        ) as detailed_mock,
    ):
        result = _scan_movie_files(
            movie_dir,
            existing,
            movie_offline=False,
            force_refresh=False,
            metadata_only=False,
        )
    assert result is not None
    assert result["versions"][0]["video_codec"] == "hevc"
    assert result["versions"][0]["resolution"] == "1920x1080"
    detailed_mock.assert_called_once_with(str(video.absolute()))
    stub_mock.assert_not_called()


def test_scan_files_normal_preserves_old_versions(tmp_path: Path) -> None:
    """Preserves old versions from existing data no longer on disk."""
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    video = movie_dir / "current.mkv"
    video.touch()
    existing = {
        "versions": [
            {"path": "/old/deleted.mkv", "video_codec": "h264"},
        ],
    }

    result = _scan_movie_files(
        movie_dir,
        existing,
        movie_offline=False,
        force_refresh=False,
        metadata_only=False,
    )
    assert result is not None
    paths = {v["path"] for v in result["versions"]}
    assert str(video.absolute()) in paths
    assert "/old/deleted.mkv" in paths


def test_scan_files_normal_no_active_path(tmp_path: Path) -> None:
    """Returns None when active_version has no path."""
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    (movie_dir / "m.mkv").touch()

    with patch(
        "lan_streamer.scanner.versioning.choose_active_version",
        return_value={"not_path": True},
    ):
        result = _scan_movie_files(
            movie_dir,
            None,
            movie_offline=False,
            force_refresh=False,
            metadata_only=False,
        )
    assert result is None


# ---------------------------------------------------------------------------
# _handle_early_return
# ---------------------------------------------------------------------------


def test_early_return_no_existing() -> None:
    """Returns None when no existing movie data."""
    result = _handle_early_return(None, "/m.mkv", {}, [], None, None, None)
    assert result is None


def test_early_return_updates_existing() -> None:
    """Returns existing data with updated fields."""
    existing = {"name": "Movie", "tmdb_identifier": "123"}
    active_version = {"video_codec": "av1", "resolution": "4K"}
    versions = [active_version]

    result = _handle_early_return(
        existing,
        "/new.mkv",
        active_version,
        versions,
        "/new.mkv",
        None,
        None,
    )
    assert result is not None
    assert result["path"] == "/new.mkv"
    assert result["video_codec"] == "av1"
    assert result["resolution"] == "4K"
    assert result["versions"] == versions
    assert result["default_path"] == "/new.mkv"


def test_early_return_jellyfin_path_map() -> None:
    """Fills jellyfin_id from path_map."""
    existing = {"name": "Movie"}
    jellyfin = {"path_map": {"/m.mkv": {"id": "jf-123"}}}

    result = _handle_early_return(
        existing,
        "/m.mkv",
        {},
        [],
        None,
        None,
        jellyfin,
    )
    assert result is not None
    assert result["jellyfin_id"] == "jf-123"


def test_early_return_jellyfin_tmdb_map() -> None:
    """Fills jellyfin_id from tmdb_episode_map when path_map has no match."""
    existing = {"name": "Movie", "tmdb_identifier": "tmdb-99"}
    jellyfin = {"tmdb_episode_map": {"tmdb-99": {"id": "jf-456"}}}

    result = _handle_early_return(
        existing,
        "/m.mkv",
        {},
        [],
        None,
        None,
        jellyfin,
    )
    assert result is not None
    assert result["jellyfin_id"] == {"id": "jf-456"}


def test_early_return_manual_jellyfin_id() -> None:
    """Manual jellyfin_id overrides any resolved one."""
    existing = {"name": "Movie"}
    jellyfin = {"path_map": {"/m.mkv": {"id": "jf-auto"}}}

    result = _handle_early_return(
        existing,
        "/m.mkv",
        {},
        [],
        None,
        "jf-manual",
        jellyfin,
    )
    assert result is not None
    assert result["jellyfin_id"] == "jf-manual"


def test_early_return_missing_runtime() -> None:
    """Missing runtime defaults to 0."""
    existing = {"tmdb_identifier": "123"}

    result = _handle_early_return(
        existing,
        "/m.mkv",
        {},
        [],
        None,
        None,
        None,
    )
    assert result is not None
    assert result["runtime"] == 0


# ---------------------------------------------------------------------------
# _resolve_tmdb_movie_data
# ---------------------------------------------------------------------------


def test_resolve_tmdb_offline() -> None:
    """Returns immediately when movie is offline."""
    metadata: Dict[str, Any] = {"tmdb_identifier": ""}
    _resolve_tmdb_movie_data(
        None,
        metadata,
        "Test",
        2020,
        False,
        "",
        None,
        True,
        False,
        "/m.mkv",
        None,
        False,
    )
    assert metadata["tmdb_identifier"] == ""


def test_resolve_tmdb_partial_fetch() -> None:
    """Fetches full TMDB data when tmdb_movie has id but no title."""
    metadata: Dict[str, Any] = {"tmdb_name": ""}
    tmdb = {"id": "42"}

    with (
        patch(
            "lan_streamer.scanner.scan_movie.tmdb_client.get_movie_by_id",
            return_value={"id": "42", "title": "Full Title"},
        ),
        patch(
            "lan_streamer.scanner.scan_movie._apply_tmdb_movie_data",
        ),
        patch(
            "lan_streamer.scanner.scan_movie._resolve_movie_jellyfin_id",
            return_value="jf-1",
        ),
    ):
        _resolve_tmdb_movie_data(
            tmdb,
            metadata,
            "Test",
            2020,
            False,
            "",
            None,
            False,
            True,
            "/m.mkv",
            None,
            False,
        )


def test_resolve_tmdb_builds_stub_from_metadata() -> None:
    """Builds stub tmdb_movie from existing metadata when no tmdb_movie provided."""
    metadata: Dict[str, Any] = {
        "tmdb_identifier": "99",
        "tmdb_name": "Test Movie",
        "overview": "desc",
        "poster_path": "/p.jpg",
        "year": 2020,
        "jellyfin_id": "",
    }

    with (
        patch(
            "lan_streamer.scanner.scan_movie._apply_tmdb_movie_data",
        ) as apply_mock,
        patch(
            "lan_streamer.scanner.scan_movie._resolve_movie_jellyfin_id",
            return_value="jf-2",
        ),
    ):
        _resolve_tmdb_movie_data(
            None,
            metadata,
            "Test",
            2020,
            False,
            "",
            None,
            False,
            True,
            "/m.mkv",
            None,
            False,
        )
    apply_mock.assert_called_once()


def test_resolve_tmdb_searches() -> None:
    """Searches TMDB when no identifier and not locked."""
    metadata: Dict[str, Any] = {
        "tmdb_identifier": "",
        "tmdb_name": "",
        "overview": "",
        "poster_path": "",
        "year": 0,
        "jellyfin_id": "",
    }

    with (
        patch(
            "lan_streamer.scanner.scan_movie.tmdb_client.search_movie",
            return_value={"id": "42", "title": "Found"},
        ),
        patch(
            "lan_streamer.scanner.scan_movie._apply_tmdb_movie_data",
        ),
        patch(
            "lan_streamer.scanner.scan_movie._resolve_movie_jellyfin_id",
            return_value="jf-3",
        ),
    ):
        _resolve_tmdb_movie_data(
            None,
            metadata,
            "Test",
            2020,
            False,
            "",
            None,
            False,
            True,
            "/m.mkv",
            None,
            False,
        )


def test_resolve_tmdb_locked_skips_search() -> None:
    """Locked movies skip TMDB search."""
    metadata: Dict[str, Any] = {
        "tmdb_identifier": "",
        "tmdb_name": "",
        "overview": "",
        "poster_path": "",
        "year": 0,
        "jellyfin_id": "",
    }

    with (
        patch(
            "lan_streamer.scanner.scan_movie.tmdb_client.search_movie",
        ) as search_mock,
        patch(
            "lan_streamer.scanner.scan_movie._resolve_movie_jellyfin_id",
            return_value="jf-4",
        ),
    ):
        _resolve_tmdb_movie_data(
            None,
            metadata,
            "Test",
            2020,
            True,
            "",
            None,
            False,
            True,
            "/m.mkv",
            None,
            False,
        )
    search_mock.assert_not_called()


def test_resolve_tmdb_applies_data() -> None:
    """Calls _apply_tmdb_movie_data when tmdb_movie is available."""
    metadata: Dict[str, Any] = {
        "tmdb_identifier": "",
        "tmdb_name": "",
        "overview": "",
        "poster_path": "",
        "year": 0,
        "jellyfin_id": "",
    }
    tmdb = {"id": "42", "title": "Test", "overview": ""}

    with (
        patch(
            "lan_streamer.scanner.scan_movie._apply_tmdb_movie_data",
        ) as apply_mock,
        patch(
            "lan_streamer.scanner.scan_movie._resolve_movie_jellyfin_id",
            return_value="jf-5",
        ),
    ):
        _resolve_tmdb_movie_data(
            tmdb,
            metadata,
            "Test",
            2020,
            False,
            "",
            None,
            False,
            True,
            "/m.mkv",
            None,
            False,
        )
    apply_mock.assert_called_once_with(
        metadata,
        tmdb,
        None,
        False,
        metadata_only=False,
    )


def test_resolve_tmdb_updates_jellyfin_id() -> None:
    """Sets jellyfin_id from _resolve_movie_jellyfin_id."""
    metadata: Dict[str, Any] = {
        "tmdb_identifier": "",
        "tmdb_name": "",
        "overview": "",
        "poster_path": "",
        "year": 0,
        "jellyfin_id": "",
    }

    with patch(
        "lan_streamer.scanner.scan_movie._resolve_movie_jellyfin_id",
        return_value="jf-final",
    ):
        _resolve_tmdb_movie_data(
            None,
            metadata,
            "Test",
            2020,
            False,
            "",
            None,
            False,
            True,
            "/m.mkv",
            None,
            False,
        )
    assert metadata["jellyfin_id"] == "jf-final"


# ---------------------------------------------------------------------------
# _build_movie_data
# ---------------------------------------------------------------------------


def test_build_movie_data_all_keys() -> None:
    """Returns dict with all expected keys."""
    metadata: Dict[str, Any] = {
        "jellyfin_id": "jf-1",
        "tmdb_identifier": "tmdb-1",
        "poster_path": "/p.jpg",
        "overview": "desc",
        "tmdb_name": "Test",
        "runtime": 120,
        "rating": 8.0,
        "genre": ["Action"],
        "year": 2020,
    }

    result = _build_movie_data(
        "Movie (2020)",
        "/m.mkv",
        metadata,
        None,
        100.0,
        {"video_codec": "av1"},
        [{"path": "/m.mkv"}],
        "/m.mkv",
        True,
    )
    assert result["name"] == "Movie (2020)"
    assert result["path"] == "/m.mkv"
    assert result["jellyfin_id"] == "jf-1"
    assert result["tmdb_identifier"] == "tmdb-1"
    assert result["poster_path"] == "/p.jpg"
    assert result["overview"] == "desc"
    assert result["tmdb_name"] == "Test"
    assert result["date_added"] == 100.0
    assert result["runtime"] == 120
    assert result["rating"] == 8.0
    assert result["genre"] == ["Action"]
    assert result["year"] == 2020
    assert result["video_codec"] == "av1"
    assert result["locked_metadata"] is False
    assert result["watched"] is False
    assert result["last_played_position"] == 0
    assert result["_changed"] is True


def test_build_movie_data_with_existing() -> None:
    """Copies locked_metadata, watched, last_played_position from existing data."""
    metadata: Dict[str, Any] = {
        "jellyfin_id": "",
        "tmdb_identifier": "",
        "poster_path": "",
        "overview": "",
        "tmdb_name": "",
        "runtime": 0,
        "rating": 0.0,
        "genre": [],
        "year": 0,
    }
    existing = {
        "locked_metadata": True,
        "watched": True,
        "last_played_position": 500,
    }

    result = _build_movie_data(
        "M",
        "/m.mkv",
        metadata,
        existing,
        0.0,
        {},
        [],
        None,
        False,
    )
    assert result["locked_metadata"] is True
    assert result["watched"] is True
    assert result["last_played_position"] == 500


def test_build_movie_data_no_existing_defaults() -> None:
    """Defaults locked_metadata, watched, last_played_position when no existing."""
    metadata: Dict[str, Any] = {
        "jellyfin_id": "",
        "tmdb_identifier": "",
        "poster_path": "",
        "overview": "",
        "tmdb_name": "",
        "runtime": 0,
        "rating": 0.0,
        "genre": [],
        "year": 0,
    }

    result = _build_movie_data(
        "M",
        "/m.mkv",
        metadata,
        None,
        0.0,
        {},
        [],
        None,
        False,
    )
    assert result["locked_metadata"] is False
    assert result["watched"] is False
    assert result["last_played_position"] == 0


# ---------------------------------------------------------------------------
# scan_movie (orchestrator smoke tests)
# ---------------------------------------------------------------------------


def test_scan_movie_no_video(tmp_path: Path) -> None:
    """Returns None when no video files exist."""
    movie_dir = tmp_path / "Movie (2020)"
    movie_dir.mkdir()
    result = scan_movie(movie_dir)
    assert result is None


def test_scan_movie_success(tmp_path: Path) -> None:
    """Successful scan with mocked TMDB returns populated dict."""
    movie_dir = tmp_path / "Test Movie (2020)"
    movie_dir.mkdir()
    video = movie_dir / "movie.mkv"
    video.touch()

    with (
        patch(
            "lan_streamer.scanner.scan_movie.tmdb_client.search_movie",
            return_value={"id": "1", "title": "Test Movie"},
        ),
        patch(
            "lan_streamer.scanner.scan_movie._apply_tmdb_movie_data",
        ),
        patch(
            "lan_streamer.scanner.scan_movie._resolve_movie_jellyfin_id",
            return_value="jf-1",
        ),
    ):
        result = scan_movie(movie_dir)

    assert result is not None
    assert result["name"] == "Test Movie (2020)"
    assert result["path"] == str(video.absolute())
    assert result["_changed"] is True
    assert len(result["versions"]) == 1


def test_scan_movie_early_return(tmp_path: Path) -> None:
    """Early return reuses existing data when no refresh needed."""
    movie_dir = tmp_path / "Movie (2020)"
    movie_dir.mkdir()
    video = movie_dir / "m.mkv"
    video.touch()

    existing = {
        "name": "Movie (2020)",
        "path": str(video.absolute()),
        "tmdb_identifier": "42",
        "poster_path": "/old.jpg",
        "overview": "old",
        "tmdb_name": "Old",
        "locked_metadata": False,
        "date_added": 50,
        "runtime": 100,
        "rating": 7.0,
        "genre": [],
        "year": 2020,
        "watched": False,
        "last_played_position": 0,
        "versions": [{"path": str(video.absolute()), "video_codec": "h264"}],
        "video_codec": "h264",
        "resolution": "1080p",
        "bit_rate": 5000,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "default_path": str(video.absolute()),
        "_changed": False,
    }

    result = scan_movie(
        movie_dir,
        existing_movie_data=existing,
        force_refresh=False,
        cleanup=False,
    )
    assert result is not None
    assert result["name"] == "Movie (2020)"
    assert result["tmdb_identifier"] == "42"
    assert result["video_codec"] == "h264"
