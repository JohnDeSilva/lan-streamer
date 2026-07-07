"""Unit tests for pass3_technical.py — technical metadata enrichment and missing-file cleanup."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from lan_streamer.scanner.pass3_technical import (
    _handle_missing_file,
    _upgrade_episode_metadata,
    _upgrade_orphan_versions,
    scan_movie_pass3,
    scan_series_pass3,
)


# ---------------------------------------------------------------------------
# _upgrade_episode_metadata
# ---------------------------------------------------------------------------


def test_upgrade_episode_metadata_stub_codec_upgrades(tmp_path: Path) -> None:
    """When video_codec is 'Unknown', ffprobe data is fetched and merged."""
    video_file = tmp_path / "episode.mkv"
    video_file.write_text("dummy content")

    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": str(video_file),
        "video_codec": "Unknown",
        "resolution": None,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "versions": [],
    }

    fake_detailed: Dict[str, Any] = {
        "resolution": "1920x1080",
        "video_codec": "h264",
        "bit_rate": 5000000,
        "audio_tracks": [{"language": "eng", "codec": "aac"}],
        "subtitle_tracks": [{"language": "eng", "codec": "subrip"}],
        "runtime": 3600,
        "size_bytes": 1048576,
        "video_type": "MKV",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=fake_detailed,
    ) as mock_detailed:
        result = _upgrade_episode_metadata(episode, force_refresh=False)

    mock_detailed.assert_called_once_with(str(video_file))
    assert result["resolution"] == "1920x1080"
    assert result["video_codec"] == "h264"
    assert result["bit_rate"] == 5000000
    assert result["audio_tracks"] == [{"language": "eng", "codec": "aac"}]
    assert result["subtitle_tracks"] == [{"language": "eng", "codec": "subrip"}]
    assert result["runtime"] == 3600
    assert result["size_bytes"] == 1048576
    assert result["video_type"] == "MKV"


def test_upgrade_episode_metadata_none_codec_upgrades(tmp_path: Path) -> None:
    """When video_codec is None (stub), ffprobe data is fetched and merged."""
    video_file = tmp_path / "episode.mkv"
    video_file.write_text("dummy content")

    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": str(video_file),
        "video_codec": None,
        "versions": [],
    }

    fake_detailed: Dict[str, Any] = {
        "resolution": "1280x720",
        "video_codec": "h265",
        "bit_rate": 3000000,
        "audio_tracks": [{"language": "eng"}],
        "subtitle_tracks": [],
        "runtime": 1800,
        "size_bytes": 512000,
        "video_type": "MP4",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=fake_detailed,
    ):
        result = _upgrade_episode_metadata(episode, force_refresh=False)

    assert result["video_codec"] == "h265"
    assert result["resolution"] == "1280x720"
    assert result["runtime"] == 1800


def test_upgrade_episode_metadata_force_refresh_overrides_known(tmp_path: Path) -> None:
    """force_refresh=True upgrades even when video_codec is already known."""
    video_file = tmp_path / "episode.mkv"
    video_file.write_text("dummy content")

    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": str(video_file),
        "video_codec": "h264",
        "resolution": "1920x1080",
        "bit_rate": 4000000,
        "audio_tracks": [{"language": "eng"}],
        "subtitle_tracks": [],
        "runtime": 1200,
        "size_bytes": 99999,
        "video_type": "MKV",
        "versions": [],
    }

    upgraded_detailed: Dict[str, Any] = {
        "resolution": "3840x2160",
        "video_codec": "h265",
        "bit_rate": 15000000,
        "audio_tracks": [{"language": "eng", "codec": "eac3"}],
        "subtitle_tracks": [{"language": "spa", "codec": "subrip"}],
        "runtime": 1234,
        "size_bytes": 987654321,
        "video_type": "MKV",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=upgraded_detailed,
    ):
        result = _upgrade_episode_metadata(episode, force_refresh=True)

    assert result["video_codec"] == "h265"
    assert result["resolution"] == "3840x2160"
    assert result["bit_rate"] == 15000000


def test_upgrade_episode_metadata_known_codec_no_force(tmp_path: Path) -> None:
    """When codec is known and force_refresh=False, ffprobe is not called."""
    video_file = tmp_path / "episode.mkv"
    video_file.write_text("dummy content")

    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": str(video_file),
        "video_codec": "h264",
        "versions": [],
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
    ) as mock_detailed:
        result = _upgrade_episode_metadata(episode, force_refresh=False)

    mock_detailed.assert_not_called()
    assert result["video_codec"] == "h264"


def test_upgrade_episode_metadata_no_path() -> None:
    """Episode with no path is returned unchanged without ffprobe call."""
    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": None,
        "video_codec": "Unknown",
        "versions": [],
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
    ) as mock_detailed:
        result = _upgrade_episode_metadata(episode, force_refresh=False)

    mock_detailed.assert_not_called()
    assert result is episode


def test_upgrade_episode_metadata_file_gone(tmp_path: Path) -> None:
    """When the file does not exist on disk, a warning is logged and episode unchanged."""
    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": str(tmp_path / "nonexistent.mkv"),
        "video_codec": "Unknown",
        "versions": [],
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
    ) as mock_detailed:
        result = _upgrade_episode_metadata(episode, force_refresh=False)

    mock_detailed.assert_not_called()
    assert result is episode


def test_upgrade_episode_metadata_upgrades_versions_too(tmp_path: Path) -> None:
    """Version entries matching the same path are also upgraded with ffprobe data."""
    video_file = tmp_path / "episode.mkv"
    video_file.write_text("dummy content")

    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": str(video_file),
        "video_codec": "Unknown",
        "versions": [
            {"path": str(video_file), "video_codec": "Unknown"},
            {"path": "/other/version.mkv", "video_codec": "Unknown"},
        ],
    }

    fake_detailed: Dict[str, Any] = {
        "resolution": "1920x1080",
        "video_codec": "h264",
        "bit_rate": 5000000,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "runtime": 3600,
        "size_bytes": 1048576,
        "video_type": "MKV",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=fake_detailed,
    ):
        result = _upgrade_episode_metadata(episode, force_refresh=False)

    # Primary path fields upgraded
    assert result["video_codec"] == "h264"

    # Matching version upgraded
    assert result["versions"][0]["video_codec"] == "h264"
    # Non-matching version left alone
    assert result["versions"][1]["video_codec"] == "Unknown"


def test_upgrade_episode_metadata_ignores_none_values(tmp_path: Path) -> None:
    """Fields with None from ffprobe do not overwrite existing values."""
    video_file = tmp_path / "episode.mkv"
    video_file.write_text("dummy content")

    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": str(video_file),
        "video_codec": "Unknown",
        "resolution": "1280x720",
        "versions": [],
    }

    fake_detailed: Dict[str, Any] = {
        "resolution": None,  # Should NOT overwrite existing
        "video_codec": "h264",
        "bit_rate": None,
        "audio_tracks": None,
        "subtitle_tracks": None,
        "runtime": None,
        "size_bytes": None,
        "video_type": None,
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=fake_detailed,
    ):
        result = _upgrade_episode_metadata(episode, force_refresh=False)

    # Existing values preserved when ffprobe returns None
    assert result["resolution"] == "1280x720"
    # video_codec updated because ffprobe provided non-None
    assert result["video_codec"] == "h264"


# ---------------------------------------------------------------------------
# _handle_missing_file
# ---------------------------------------------------------------------------


def test_handle_missing_file_file_exists(tmp_path: Path) -> None:
    """When the file exists on disk, episode is returned unchanged."""
    video_file = tmp_path / "existing.mkv"
    video_file.write_text("dummy")

    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": str(video_file),
        "versions": [],
    }

    result = _handle_missing_file(episode)
    assert result["path"] == str(video_file)
    assert result is episode


def test_handle_missing_file_file_gone(tmp_path: Path) -> None:
    """When the file no longer exists, path is set to None."""
    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": str(tmp_path / "deleted.mkv"),
        "versions": [],
    }

    result = _handle_missing_file(episode)
    assert result["path"] is None


def test_handle_missing_file_no_path() -> None:
    """Episode with no path is returned unchanged."""
    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": None,
        "versions": [],
    }

    result = _handle_missing_file(episode)
    assert result["path"] is None
    assert result is episode


def test_handle_missing_file_clears_version_paths_too(tmp_path: Path) -> None:
    """Version entries matching the missing path also have their path set to None."""
    missing_path = str(tmp_path / "gone.mkv")

    episode: Dict[str, Any] = {
        "name": "S01E01",
        "path": missing_path,
        "versions": [
            {"path": missing_path, "video_codec": "h264"},
            {"path": "/other/version.mkv", "video_codec": "h265"},
        ],
    }

    result = _handle_missing_file(episode)
    assert result["path"] is None
    assert result["versions"][0]["path"] is None
    assert result["versions"][1]["path"] == "/other/version.mkv"


# ---------------------------------------------------------------------------
# _upgrade_orphan_versions
# ---------------------------------------------------------------------------


def test_upgrade_orphan_versions_upgrades_existing_unknown(tmp_path: Path) -> None:
    """Orphan version with Unknown codec and existing file gets upgraded."""
    version_path = tmp_path / "alternate.mkv"
    version_path.write_text("dummy")

    movie_data: Dict[str, Any] = {
        "path": str(tmp_path / "main.mkv"),
        "versions": [
            {
                "path": str(version_path),
                "video_codec": "Unknown",
                "resolution": None,
            },
        ],
    }

    fake_detailed: Dict[str, Any] = {
        "resolution": "1920x1080",
        "video_codec": "h264",
        "bit_rate": 5000000,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "runtime": 3600,
        "size_bytes": 1048576,
        "video_type": "MKV",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=fake_detailed,
    ):
        _upgrade_orphan_versions(movie_data, "Test Movie")

    assert movie_data["versions"][0]["video_codec"] == "h264"
    assert movie_data["versions"][0]["resolution"] == "1920x1080"


def test_upgrade_orphan_versions_clears_missing(tmp_path: Path) -> None:
    """Orphan version with missing file gets its path cleared."""
    movie_data: Dict[str, Any] = {
        "path": str(tmp_path / "main.mkv"),
        "versions": [
            {
                "path": str(tmp_path / "nonexistent.mkv"),
                "video_codec": "h264",
            },
        ],
    }

    _upgrade_orphan_versions(movie_data, "Test Movie")
    assert movie_data["versions"][0]["path"] is None


def test_upgrade_orphan_versions_skips_active_path(tmp_path: Path) -> None:
    """Versions with the same path as the active movie path are skipped."""
    common_path = str(tmp_path / "movie.mkv")

    movie_data: Dict[str, Any] = {
        "path": common_path,
        "versions": [
            {"path": common_path, "video_codec": "Unknown"},
        ],
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
    ) as mock_detailed:
        _upgrade_orphan_versions(movie_data, "Test Movie")

    mock_detailed.assert_not_called()
    assert movie_data["versions"][0]["path"] is not None


def test_upgrade_orphan_versions_skips_none_path() -> None:
    """Versions with no path are skipped."""
    movie_data: Dict[str, Any] = {
        "path": "/main.mkv",
        "versions": [
            {"path": None, "video_codec": "Unknown"},
        ],
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
    ) as mock_detailed:
        _upgrade_orphan_versions(movie_data, "Test Movie")

    mock_detailed.assert_not_called()


def test_upgrade_orphan_versions_known_codec_no_upgrade(tmp_path: Path) -> None:
    """Orphan version with known codec is not re-scanned."""
    version_path = tmp_path / "known.mkv"
    version_path.write_text("dummy")

    movie_data: Dict[str, Any] = {
        "path": str(tmp_path / "main.mkv"),
        "versions": [
            {
                "path": str(version_path),
                "video_codec": "h264",
            },
        ],
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
    ) as mock_detailed:
        _upgrade_orphan_versions(movie_data, "Test Movie")

    mock_detailed.assert_not_called()


# ---------------------------------------------------------------------------
# scan_series_pass3
# ---------------------------------------------------------------------------


def test_scan_series_pass3_normal(tmp_path: Path) -> None:
    """Normal case: episodes get upgraded and missing files handled."""
    series_dir = tmp_path / "Test Series"
    series_dir.mkdir()
    video_file = series_dir / "S01E01.mkv"
    video_file.write_text("dummy")

    series_data: Dict[str, Any] = {
        "name": "Test Series",
        "seasons": {
            "Season 1": {
                "episodes": [
                    {
                        "name": "S01E01",
                        "path": str(video_file),
                        "video_codec": "Unknown",
                        "versions": [],
                    },
                    {
                        "name": "S01E02",
                        "path": str(series_dir / "gone.mkv"),
                        "video_codec": "Unknown",
                        "versions": [],
                    },
                ],
            },
        },
    }

    fake_detailed: Dict[str, Any] = {
        "resolution": "1920x1080",
        "video_codec": "h264",
        "bit_rate": 4000000,
        "audio_tracks": [{"language": "eng"}],
        "subtitle_tracks": [],
        "runtime": 1800,
        "size_bytes": 500000,
        "video_type": "MKV",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=fake_detailed,
    ):
        result = scan_series_pass3(series_dir, series_data, force_refresh=False)

    # Existing episode — upgraded
    ep0 = result["seasons"]["Season 1"]["episodes"][0]
    assert ep0["video_codec"] == "h264"
    assert ep0["resolution"] == "1920x1080"

    # Missing file episode — path set to None
    ep1 = result["seasons"]["Season 1"]["episodes"][1]
    assert ep1["path"] is None

    # Ensure mutation in-place
    assert result is series_data


def test_scan_series_pass3_force_refresh(tmp_path: Path) -> None:
    """force_refresh=True re-scans all episodes regardless of codec state."""
    series_dir = tmp_path / "Series"
    series_dir.mkdir()
    video_file = series_dir / "ep.mkv"
    video_file.write_text("dummy")

    series_data: Dict[str, Any] = {
        "name": "Series",
        "seasons": {
            "Season 1": {
                "episodes": [
                    {
                        "name": "E01",
                        "path": str(video_file),
                        "video_codec": "h264",
                        "resolution": "1920x1080",
                        "versions": [],
                    },
                ],
            },
        },
    }

    upgraded: Dict[str, Any] = {
        "resolution": "3840x2160",
        "video_codec": "h265",
        "bit_rate": 12000000,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "runtime": 2500,
        "size_bytes": 2000000,
        "video_type": "MKV",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=upgraded,
    ):
        result = scan_series_pass3(series_dir, series_data, force_refresh=True)

    ep = result["seasons"]["Season 1"]["episodes"][0]
    assert ep["video_codec"] == "h265"
    assert ep["resolution"] == "3840x2160"


def test_scan_series_pass3_empty_seasons(tmp_path: Path) -> None:
    """Empty seasons dict results in no changes or errors."""
    series_dir = tmp_path / "Empty Series"
    series_dir.mkdir()

    series_data: Dict[str, Any] = {
        "name": "Empty Series",
        "seasons": {},
    }

    result = scan_series_pass3(series_dir, series_data, force_refresh=False)
    assert result["seasons"] == {}


def test_scan_series_pass3_no_seasons_key(tmp_path: Path) -> None:
    """Missing 'seasons' key is handled gracefully (defaults to empty dict)."""
    series_dir = tmp_path / "NoSeasons"
    series_dir.mkdir()

    series_data: Dict[str, Any] = {
        "name": "NoSeasons",
    }

    result = scan_series_pass3(series_dir, series_data, force_refresh=False)
    assert result is series_data


def test_scan_series_pass3_empty_episode_list(tmp_path: Path) -> None:
    """Season with empty episodes list doesn't cause errors."""
    series_dir = tmp_path / "Series"
    series_dir.mkdir()

    series_data: Dict[str, Any] = {
        "name": "Series",
        "seasons": {
            "Season 1": {"episodes": []},
        },
    }

    result = scan_series_pass3(series_dir, series_data, force_refresh=False)
    assert result["seasons"]["Season 1"]["episodes"] == []


def test_scan_series_pass3_name_fallback(tmp_path: Path) -> None:
    """When series_data has no 'name', the directory name is used (for logging)."""
    series_dir = tmp_path / "DirectoryName"
    series_dir.mkdir()

    series_data: Dict[str, Any] = {
        "seasons": {},
    }

    # Just ensure no crash
    result = scan_series_pass3(series_dir, series_data, force_refresh=False)
    assert result is series_data


# ---------------------------------------------------------------------------
# scan_movie_pass3
# ---------------------------------------------------------------------------


def test_scan_movie_pass3_normal(tmp_path: Path) -> None:
    """Normal case: movie metadata upgraded and missing file handled."""
    movie_dir = tmp_path / "Test Movie (2020)"
    movie_dir.mkdir()
    video_file = movie_dir / "movie.mkv"
    video_file.write_text("dummy")

    movie_data: Dict[str, Any] = {
        "name": "Test Movie",
        "path": str(video_file),
        "video_codec": "Unknown",
        "versions": [],
    }

    fake_detailed: Dict[str, Any] = {
        "resolution": "1920x1080",
        "video_codec": "h264",
        "bit_rate": 6000000,
        "audio_tracks": [{"language": "eng"}],
        "subtitle_tracks": [{"language": "fre"}],
        "runtime": 5400,
        "size_bytes": 2000000,
        "video_type": "MKV",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=fake_detailed,
    ):
        result = scan_movie_pass3(movie_dir, movie_data, force_refresh=False)

    assert result["video_codec"] == "h264"
    assert result["resolution"] == "1920x1080"
    assert result["runtime"] == 5400
    assert result is movie_data


def test_scan_movie_pass3_force_refresh(tmp_path: Path) -> None:
    """force_refresh=True re-scans movie even with known codec."""
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    video_file = movie_dir / "movie.mkv"
    video_file.write_text("dummy")

    movie_data: Dict[str, Any] = {
        "name": "Movie",
        "path": str(video_file),
        "video_codec": "h264",
        "resolution": "1920x1080",
        "bit_rate": 5000000,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "runtime": 60,
        "size_bytes": 100,
        "video_type": "MKV",
        "versions": [],
    }

    upgraded: Dict[str, Any] = {
        "resolution": "3840x2160",
        "video_codec": "h265",
        "bit_rate": 15000000,
        "audio_tracks": [{"language": "eng"}],
        "subtitle_tracks": [],
        "runtime": 5400,
        "size_bytes": 3000000000,
        "video_type": "MKV",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=upgraded,
    ):
        result = scan_movie_pass3(movie_dir, movie_data, force_refresh=True)

    assert result["video_codec"] == "h265"
    assert result["resolution"] == "3840x2160"


def test_scan_movie_pass3_missing_file(tmp_path: Path) -> None:
    """Movie whose file is missing has path set to None."""
    movie_dir = tmp_path / "Ghost Movie"
    movie_dir.mkdir()

    movie_data: Dict[str, Any] = {
        "name": "Ghost Movie",
        "path": str(movie_dir / "nonexistent.mkv"),
        "video_codec": "Unknown",
        "versions": [],
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
    ) as mock_detailed:
        result = scan_movie_pass3(movie_dir, movie_data, force_refresh=False)

    mock_detailed.assert_not_called()
    assert result["path"] is None


def test_scan_movie_pass3_with_orphan_versions(tmp_path: Path) -> None:
    """scan_movie_pass3 calls _upgrade_orphan_versions for alternative versions."""
    movie_dir = tmp_path / "Movie Versions"
    movie_dir.mkdir()
    main_video = movie_dir / "main.mkv"
    main_video.write_text("dummy")
    alt_video = movie_dir / "alt.mkv"
    alt_video.write_text("dummy")

    movie_data: Dict[str, Any] = {
        "name": "Movie Versions",
        "path": str(main_video),
        "video_codec": "Unknown",
        "versions": [
            {
                "path": str(alt_video),
                "video_codec": "Unknown",
                "resolution": None,
            },
        ],
    }

    fake_detailed: Dict[str, Any] = {
        "resolution": "1920x1080",
        "video_codec": "h264",
        "bit_rate": 5000000,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "runtime": 3600,
        "size_bytes": 1000000,
        "video_type": "MKV",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=fake_detailed,
    ):
        result = scan_movie_pass3(movie_dir, movie_data, force_refresh=False)

    # Main video upgraded
    assert result["video_codec"] == "h264"
    # Orphan version also upgraded
    assert result["versions"][0]["video_codec"] == "h264"
    assert result["versions"][0]["resolution"] == "1920x1080"


def test_scan_movie_pass3_name_fallback(tmp_path: Path) -> None:
    """When movie_data has no 'name', the directory name is used (for logging)."""
    movie_dir = tmp_path / "DirectoryMovie"
    movie_dir.mkdir()
    video_file = movie_dir / "movie.mkv"
    video_file.write_text("dummy")

    movie_data: Dict[str, Any] = {
        "path": str(video_file),
        "video_codec": "Unknown",
        "versions": [],
    }

    fake_detailed: Dict[str, Any] = {
        "resolution": "1280x720",
        "video_codec": "h264",
        "bit_rate": 2000000,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "runtime": 120,
        "size_bytes": 500,
        "video_type": "MKV",
    }

    with patch(
        "lan_streamer.scanner.pass3_technical.get_detailed_file_info",
        return_value=fake_detailed,
    ):
        result = scan_movie_pass3(movie_dir, movie_data, force_refresh=False)

    assert result["video_codec"] == "h264"
    assert result is movie_data
