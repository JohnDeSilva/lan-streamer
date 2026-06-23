"""Unit tests for the extracted helper functions in lan_streamer.scanner.scan_tv."""

import logging
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from lan_streamer.scanner.scan_tv import (
    _EpisodeScanContext,
    _create_tmdb_placeholder_episodes,
    _discover_seasons_to_process,
    _filter_future_episodes,
    _group_and_resolve_episode_versions,
    _preserve_existing_episode_data,
    _scan_season_episodes,
    _validate_series_file_layout,
    scan_series,
)


# ---------------------------------------------------------------------------
# _validate_series_file_layout
# ---------------------------------------------------------------------------


def test_validate_layout_no_warnings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid layout with all files in season folders should produce no warnings."""
    series_dir = tmp_path / "My Show"
    season_dir = series_dir / "Season 1"
    season_dir.mkdir(parents=True)
    (season_dir / "S01E01.mkv").touch()
    (season_dir / "S01E02.mkv").touch()

    caplog.set_level(logging.WARNING)
    _validate_series_file_layout(series_dir, metadata_only=False)
    assert caplog.text == "", f"Unexpected warnings: {caplog.text}"


def test_validate_layout_warns_outside_files(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Files outside season folders should produce a warning."""
    series_dir = tmp_path / "My Show"
    series_dir.mkdir()
    (series_dir / "S01E01.mkv").touch()

    caplog.set_level(logging.WARNING)
    _validate_series_file_layout(series_dir, metadata_only=False)
    assert "outside of season or specials/extras folders" in caplog.text
    assert "S01E01.mkv" in caplog.text


def test_validate_layout_warns_nested_deep(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Files nested deeper than 2 levels under a season dir should produce a warning."""
    series_dir = tmp_path / "My Show"
    season_dir = series_dir / "Season 1"
    season_dir.mkdir(parents=True)
    nested = season_dir / "Featurettes"
    nested.mkdir()
    (nested / "Bonus.mkv").touch()

    caplog.set_level(logging.WARNING)
    _validate_series_file_layout(series_dir, metadata_only=False)
    assert "nested too deeply" in caplog.text


def test_validate_layout_skips_when_metadata_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """When metadata_only=True, no filesystem validation should occur."""
    series_dir = tmp_path / "My Show"
    series_dir.mkdir()
    (series_dir / "S01E01.mkv").touch()

    caplog.set_level(logging.WARNING)
    _validate_series_file_layout(series_dir, metadata_only=True)
    assert caplog.text == "", f"Unexpected warnings: {caplog.text}"


def test_validate_layout_catches_invalid_folder_names(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Files under a folder that is not season/special/extras should be warned."""
    series_dir = tmp_path / "My Show"
    bad_folder = series_dir / "Random Folder"
    bad_folder.mkdir(parents=True)
    (bad_folder / "clip.mkv").touch()

    caplog.set_level(logging.WARNING)
    _validate_series_file_layout(series_dir, metadata_only=False)
    assert "outside of season or specials/extras folders" in caplog.text


# ---------------------------------------------------------------------------
# _discover_seasons_to_process
# ---------------------------------------------------------------------------


def test_discover_seasons_filesystem(tmp_path: Path) -> None:
    """Filesystem iteration discovers season directories."""
    series_dir = tmp_path / "Show"
    (series_dir / "Season 1").mkdir(parents=True)
    (series_dir / "Season 2").mkdir()
    (series_dir / ".hidden").mkdir()

    result = _discover_seasons_to_process(
        series_dir,
        existing_series_data=None,
        metadata_only=False,
        offline=False,
    )
    names = {r[0] for r in result}
    assert names == {"Season 1", "Season 2"}
    for _, changed, _ in result:
        assert changed is True  # No existing data → always changed


def test_discover_seasons_metadata_only(tmp_path: Path) -> None:
    """metadata_only=True reuses existing season data."""
    series_dir = tmp_path / "Show"
    series_dir.mkdir()

    existing = {
        "seasons": {
            "Season 1": {"episodes": []},
            "Season 2": {"episodes": []},
        }
    }
    result = _discover_seasons_to_process(
        series_dir,
        existing_series_data=existing,
        metadata_only=True,
        offline=False,
    )
    assert len(result) == 2
    for name, changed, existing_season in result:
        assert changed is True
        assert existing_season is not None


def test_discover_seasons_skips_dot_dirs(tmp_path: Path) -> None:
    """Directories starting with '.' should be skipped."""
    series_dir = tmp_path / "Show"
    (series_dir / "Season 1").mkdir(parents=True)
    (series_dir / ".trash").mkdir()

    result = _discover_seasons_to_process(
        series_dir,
        existing_series_data=None,
        metadata_only=False,
        offline=False,
    )
    names = {r[0] for r in result}
    assert names == {"Season 1"}


def test_discover_seasons_change_detection(tmp_path: Path) -> None:
    """Existing unchanged season should have is_season_changed=False when offline."""
    series_dir = tmp_path / "Show"
    season_dir = series_dir / "Season 1"
    season_dir.mkdir(parents=True)
    (season_dir / "S01E01.mkv").touch()

    existing = {
        "seasons": {
            "Season 1": {
                "episodes": [
                    {
                        "name": "S01E01.mkv",
                        "path": str((season_dir / "S01E01.mkv").absolute()),
                    }
                ],
            }
        }
    }

    # detect_tv_file_changes will compare files — since file exists and is in
    # existing data, it returns False for unchanged. We mock to isolate.
    with patch(
        "lan_streamer.scanner.scan_tv.detect_tv_file_changes",
        return_value=False,
    ):
        result = _discover_seasons_to_process(
            series_dir,
            existing_series_data=existing,
            metadata_only=False,
            offline=True,
        )
    assert len(result) == 1
    assert result[0][1] is False  # is_season_changed = False


# ---------------------------------------------------------------------------
# _scan_season_episodes
# ---------------------------------------------------------------------------


def test_scan_season_episodes_filesystem(tmp_path: Path) -> None:
    """Regular filesystem scan discovers video files."""
    series_dir = tmp_path / "Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()
    (season_dir / "S01E02.mkv").touch()
    (season_dir / "notes.txt").touch()  # Should be ignored

    detail_callback = MagicMock()
    context = _EpisodeScanContext(
        series_directory=series_dir,
        series_data={"seasons": {}, "metadata": {}},
        season_metadata={},
        tmdb_episodes=[],
        tmdb_series=None,
        jellyfin_data=None,
        existing_episodes_by_path={},
        existing_series_data=None,
        season_offline=True,
        detail_callback=detail_callback,
    )
    result = _scan_season_episodes(
        season_directory=season_dir,
        season_name="Season 1",
        existing_season=None,
        metadata_only=False,
        context=context,
    )
    assert len(result) == 2
    assert detail_callback.call_count == 4  # start_file + finish_file per file


def test_scan_season_episodes_metadata_only(tmp_path: Path) -> None:
    """metadata_only=True iterates existing episode paths rather than filesystem."""
    series_dir = tmp_path / "Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    real_file = season_dir / "S01E01.mkv"
    real_file.touch()

    existing_season = {
        "episodes": [
            {"path": str(real_file.absolute())},
        ]
    }

    detail_callback = MagicMock()
    context = _EpisodeScanContext(
        series_directory=series_dir,
        series_data={"seasons": {}, "metadata": {}},
        season_metadata={},
        tmdb_episodes=[],
        tmdb_series=None,
        jellyfin_data=None,
        existing_episodes_by_path={},
        existing_series_data=None,
        season_offline=True,
        detail_callback=detail_callback,
    )
    with patch(
        "lan_streamer.scanner.scan_tv._process_episode_file",
        return_value={"name": "S01E01", "path": str(real_file.absolute())},
    ):
        result = _scan_season_episodes(
            season_directory=season_dir,
            season_name="Season 1",
            existing_season=existing_season,
            metadata_only=True,
            context=context,
        )
    assert len(result) == 1
    assert result[0]["name"] == "S01E01"
    assert detail_callback.call_count == 2  # start_file + finish_file


def test_scan_season_episodes_skips_dirs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Subdirectories inside a season folder should be logged as warnings."""
    series_dir = tmp_path / "Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    sub_dir = season_dir / "Extras"
    sub_dir.mkdir()
    (sub_dir / "extra.mkv").touch()

    caplog.set_level(logging.WARNING)
    context = _EpisodeScanContext(
        series_directory=series_dir,
        series_data={"seasons": {}, "metadata": {}},
        season_metadata={},
        tmdb_episodes=[],
        tmdb_series=None,
        jellyfin_data=None,
        existing_episodes_by_path={},
        existing_series_data=None,
        season_offline=True,
        detail_callback=None,
    )
    result = _scan_season_episodes(
        season_directory=season_dir,
        season_name="Season 1",
        existing_season=None,
        metadata_only=False,
        context=context,
    )
    assert len(result) == 0
    assert "Ignoring subdirectory in season folder" in caplog.text


# ---------------------------------------------------------------------------
# _group_and_resolve_episode_versions
# ---------------------------------------------------------------------------


def test_group_and_resolve_single_episode() -> None:
    """A single scanned episode should be returned as-is with version info."""
    scanned = [
        {"name": "S01E01", "path": "/show/Season 1/S01E01.mkv", "tmdb_number": 1}
    ]
    with (
        patch(
            "lan_streamer.scanner.scan_tv.get_stub_file_info",
            return_value={"path": "/show/Season 1/S01E01.mkv", "resolution": None},
        ),
        patch(
            "lan_streamer.scanner.versioning.choose_active_version",
            return_value={"path": "/show/Season 1/S01E01.mkv"},
        ),
    ):
        result = _group_and_resolve_episode_versions(
            scanned_episodes=scanned,
            existing_season_episodes=[],
            season_offline=True,
            force_refresh=False,
            metadata_only=False,
        )
    assert len(result) == 1
    assert result[0]["name"] == "S01E01"
    assert result[0]["path"] == "/show/Season 1/S01E01.mkv"
    assert "versions" in result[0]


def test_group_and_resolve_groups_duplicates() -> None:
    """Two files for the same episode should be grouped into one record with two versions."""
    scanned = [
        {"name": "S01E01", "path": "/show/Season 1/S01E01_1080p.mkv", "tmdb_number": 1},
        {"name": "S01E01", "path": "/show/Season 1/S01E01_720p.mkv", "tmdb_number": 1},
    ]
    with (
        patch(
            "lan_streamer.scanner.scan_tv.get_stub_file_info",
            side_effect=lambda p: {"path": p, "resolution": "stub"},
        ),
        patch(
            "lan_streamer.scanner.versioning.choose_active_version",
            return_value={"path": "/show/Season 1/S01E01_1080p.mkv"},
        ),
    ):
        result = _group_and_resolve_episode_versions(
            scanned_episodes=scanned,
            existing_season_episodes=[],
            season_offline=True,
            force_refresh=False,
            metadata_only=False,
        )
    assert len(result) == 1
    assert len(result[0]["versions"]) == 2


def test_group_and_resolve_preserves_existing_versions() -> None:
    """Existing version data should be reused when not force_refresh."""
    scanned = [{"name": "S01E01", "path": "/show/S01E01.mkv", "tmdb_number": 1}]
    existing_eps = [
        {
            "name": "S01E01",
            "tmdb_number": 1,
            "versions": [
                {
                    "path": "/show/S01E01.mkv",
                    "resolution": "1080p",
                    "video_codec": "h264",
                }
            ],
            "default_path": None,
        }
    ]
    with patch(
        "lan_streamer.scanner.versioning.choose_active_version",
        return_value={
            "path": "/show/S01E01.mkv",
            "resolution": "1080p",
            "video_codec": "h264",
        },
    ):
        result = _group_and_resolve_episode_versions(
            scanned_episodes=scanned,
            existing_season_episodes=existing_eps,
            season_offline=False,
            force_refresh=False,
            metadata_only=False,
        )
    assert len(result) == 1
    assert result[0]["versions"][0]["resolution"] == "1080p"


def test_group_and_resolve_rescans_stubs() -> None:
    """Stub versions should be re-scanned online even if force_refresh is False."""
    scanned = [{"name": "S01E01", "path": "/show/S01E01.mkv", "tmdb_number": 1}]
    existing_eps = [
        {
            "name": "S01E01",
            "tmdb_number": 1,
            "versions": [
                {
                    "path": "/show/S01E01.mkv",
                    "resolution": "Unknown",
                    "video_codec": "Unknown",
                }
            ],
            "default_path": "/show/S01E01.mkv",
        }
    ]

    with (
        patch(
            "lan_streamer.scanner.scan_tv.get_detailed_file_info",
            return_value={
                "path": "/show/S01E01.mkv",
                "resolution": "1080p",
                "video_codec": "hevc",
            },
        ) as mock_detailed,
        patch(
            "lan_streamer.scanner.scan_tv.get_stub_file_info",
        ) as mock_stub,
        patch(
            "lan_streamer.scanner.versioning.choose_active_version",
            return_value={
                "path": "/show/S01E01.mkv",
                "resolution": "1080p",
                "video_codec": "hevc",
            },
        ),
    ):
        result = _group_and_resolve_episode_versions(
            scanned_episodes=scanned,
            existing_season_episodes=existing_eps,
            season_offline=False,
            force_refresh=False,
            metadata_only=False,
        )
    assert len(result) == 1
    assert result[0]["versions"][0]["resolution"] == "1080p"
    assert result[0]["versions"][0]["video_codec"] == "hevc"
    mock_detailed.assert_called_once_with("/show/S01E01.mkv")
    mock_stub.assert_not_called()


def test_group_and_resolve_fallback_to_name_key() -> None:
    """Episode without tmdb_number should fall back to parsed number or name."""
    scanned = [{"name": "Show.S01E05.mkv", "path": "/show/ep.mkv", "tmdb_number": None}]
    with (
        patch(
            "lan_streamer.scanner.scan_tv.get_stub_file_info",
            return_value={"path": "/show/ep.mkv"},
        ),
        patch(
            "lan_streamer.scanner.versioning.choose_active_version",
            return_value={"path": "/show/ep.mkv"},
        ),
    ):
        result = _group_and_resolve_episode_versions(
            scanned_episodes=scanned,
            existing_season_episodes=[],
            season_offline=True,
            force_refresh=False,
            metadata_only=False,
        )
    assert len(result) == 1
    # The key would be (1, 5) from the parsed episode name


# ---------------------------------------------------------------------------
# _create_tmdb_placeholder_episodes
# ---------------------------------------------------------------------------


def test_create_placeholders_all_local() -> None:
    """When all TMDB episodes are present locally, no placeholders are created."""
    tmdb_eps = [
        {"id": "e1", "episode_number": 1, "name": "Episode 1"},
        {"id": "e2", "episode_number": 2, "name": "Episode 2"},
    ]
    local_eps = [
        {"tmdb_number": 1, "name": "S01E01 - Episode 1"},
        {"tmdb_number": 2, "name": "S01E02 - Episode 2"},
    ]
    placeholders = _create_tmdb_placeholder_episodes(
        tmdb_episodes=tmdb_eps,
        local_episodes=local_eps,
        season_name="Season 1",
        season_metadata={},
    )
    assert placeholders == []


def test_create_placeholders_missing_episode() -> None:
    """Missing TMDB episodes should get placeholder records."""
    tmdb_eps = [
        {"id": "e1", "episode_number": 1, "name": "Episode 1"},
        {"id": "e2", "episode_number": 2, "name": "Episode 2"},
    ]
    local_eps = [
        {"tmdb_number": 1, "name": "S01E01 - Episode 1"},
    ]
    placeholders = _create_tmdb_placeholder_episodes(
        tmdb_episodes=tmdb_eps,
        local_episodes=local_eps,
        season_name="Season 1",
        season_metadata={},
    )
    assert len(placeholders) == 1
    assert placeholders[0]["tmdb_number"] == 2
    assert placeholders[0]["path"] is None
    assert "S01E02 - Episode 2" in placeholders[0]["name"]


def test_create_placeholders_always_creates_all() -> None:
    """All TMDB episodes should get placeholder records regardless of air date."""
    import datetime

    today = datetime.date.today()
    future_date = (today + datetime.timedelta(days=10)).isoformat()
    past_date = (today - datetime.timedelta(days=10)).isoformat()

    tmdb_eps = [
        {"id": "e1", "episode_number": 1, "name": "Past Ep", "air_date": past_date},
        {"id": "e2", "episode_number": 2, "name": "Future Ep", "air_date": future_date},
    ]
    local_eps = []
    placeholders = _create_tmdb_placeholder_episodes(
        tmdb_episodes=tmdb_eps,
        local_episodes=local_eps,
        season_name="Season 1",
        season_metadata={},
    )
    assert len(placeholders) == 2
    assert placeholders[0]["tmdb_number"] == 1
    assert placeholders[1]["tmdb_number"] == 2


def test_create_placeholders_specials_season() -> None:
    """Specials season should use index 0 for episode formatting."""
    tmdb_eps = [
        {"id": "s1", "episode_number": 1, "name": "Special Feature"},
    ]
    placeholders = _create_tmdb_placeholder_episodes(
        tmdb_episodes=tmdb_eps,
        local_episodes=[],
        season_name="Specials",
        season_metadata={},
    )
    assert len(placeholders) == 1
    assert "S00E01" in placeholders[0]["name"]


def test_create_placeholders_with_mal_id() -> None:
    """When season has myanimelist_id, placeholders should include it."""
    tmdb_eps = [
        {"id": "e1", "episode_number": 1, "name": "Episode 1"},
    ]
    season_meta = {"myanimelist_id": 12345}
    placeholders = _create_tmdb_placeholder_episodes(
        tmdb_episodes=tmdb_eps,
        local_episodes=[],
        season_name="Season 1",
        season_metadata=season_meta,
    )
    assert len(placeholders) == 1
    assert placeholders[0]["myanimelist_anime_id"] == 12345
    assert placeholders[0]["myanimelist_episode_number"] == 1


# ---------------------------------------------------------------------------
# _preserve_existing_episode_data
# ---------------------------------------------------------------------------


def test_preserve_missing_season() -> None:
    """A season present in existing data but missing from scan should be preserved."""
    series_data = {"seasons": {}}
    existing = {
        "seasons": {
            "Season 1": {"episodes": [{"name": "S01E01", "path": "/old/path.mkv"}]},
        }
    }
    _preserve_existing_episode_data(
        series_data=series_data,
        existing_series_data=existing,
        cleanup=False,
        metadata_only=False,
    )
    assert "Season 1" in series_data["seasons"]
    assert len(series_data["seasons"]["Season 1"]["episodes"]) == 1


def test_preserve_missing_episode_with_path() -> None:
    """A path-based episode not found in the new scan should be preserved when it still exists on disk."""
    series_data = {
        "seasons": {
            "Season 1": {"episodes": []},
        }
    }
    existing = {
        "seasons": {
            "Season 1": {
                "episodes": [
                    {
                        "name": "S01E01.mkv",
                        "path": "/still/exists/S01E01.mkv",
                        "tmdb_number": 1,
                    },
                ]
            }
        }
    }
    with patch("pathlib.Path.exists", return_value=True):
        _preserve_existing_episode_data(
            series_data=series_data,
            existing_series_data=existing,
            cleanup=False,
            metadata_only=False,
        )
    assert len(series_data["seasons"]["Season 1"]["episodes"]) == 1


def test_preserve_placeholder_episode() -> None:
    """A placeholder episode (path=None) should be preserved if not replaced."""
    series_data = {
        "seasons": {
            "Season 1": {"episodes": [{"name": "S01E01 - Real", "tmdb_number": 1}]},
        }
    }
    existing = {
        "seasons": {
            "Season 1": {
                "episodes": [
                    {"name": "S01E01 - Real", "tmdb_number": 1, "path": "/real.mkv"},
                    {
                        "name": "S01E02 - TBA",
                        "tmdb_number": 2,
                        "path": None,
                        "watched": False,
                    },
                ]
            }
        }
    }
    _preserve_existing_episode_data(
        series_data=series_data,
        existing_series_data=existing,
        cleanup=False,
        metadata_only=False,
    )
    # S01E02 (placeholder) should be preserved because tmdb_number 2 is not in the new data
    eps = series_data["seasons"]["Season 1"]["episodes"]
    numbers = {e["tmdb_number"] for e in eps if e.get("tmdb_number")}
    assert 2 in numbers


def test_preserve_skips_when_cleanup() -> None:
    """When cleanup=True, no existing data should be preserved."""
    series_data = {
        "seasons": {"Season 1": {"episodes": [{"name": "S01E01", "path": "/new.mkv"}]}}
    }
    existing = {
        "seasons": {
            "Season 2": {"episodes": [{"name": "S02E01", "path": "/old.mkv"}]},
        }
    }
    _preserve_existing_episode_data(
        series_data=series_data,
        existing_series_data=existing,
        cleanup=True,
        metadata_only=False,
    )
    assert "Season 2" not in series_data["seasons"]


def test_preserve_preserves_all_placeholders() -> None:
    """All placeholder episodes should be preserved (future filtering is done by _filter_future_episodes)."""
    import datetime

    today = datetime.date.today()
    future_date = (today + datetime.timedelta(days=10)).isoformat()
    past_date = (today - datetime.timedelta(days=10)).isoformat()

    series_data = {
        "seasons": {
            "Season 1": {
                "episodes": [{"name": "S01E01", "tmdb_number": 1, "path": "/real.mkv"}]
            },
        }
    }
    existing = {
        "seasons": {
            "Season 1": {
                "episodes": [
                    {"name": "S01E01", "tmdb_number": 1, "path": "/real.mkv"},
                    {
                        "name": "Past TBA",
                        "tmdb_number": 2,
                        "path": None,
                        "air_date": past_date,
                    },
                    {
                        "name": "Future TBA",
                        "tmdb_number": 3,
                        "path": None,
                        "air_date": future_date,
                    },
                ]
            }
        }
    }
    _preserve_existing_episode_data(
        series_data=series_data,
        existing_series_data=existing,
        cleanup=False,
        metadata_only=False,
    )
    eps = series_data["seasons"]["Season 1"]["episodes"]
    numbers = {e["tmdb_number"] for e in eps}
    assert 1 in numbers
    assert 2 in numbers
    assert 3 in numbers


def test_preserve_metadata_only_skips_disk_check() -> None:
    """When metadata_only=True, episodes are preserved without checking disk existence."""
    series_data = {
        "seasons": {
            "Season 1": {"episodes": []},
        }
    }
    existing = {
        "seasons": {
            "Season 1": {
                "episodes": [
                    {
                        "name": "S01E01.mkv",
                        "path": "/nonexistent/S01E01.mkv",
                        "tmdb_number": 1,
                    },
                ]
            }
        }
    }
    with patch("pathlib.Path.exists", return_value=False):
        _preserve_existing_episode_data(
            series_data=series_data,
            existing_series_data=existing,
            cleanup=False,
            metadata_only=True,
        )
    # Even though Path.exists() is False, metadata_only=True skips the check
    assert len(series_data["seasons"]["Season 1"]["episodes"]) == 1


# ---------------------------------------------------------------------------
# _filter_future_episodes
# ---------------------------------------------------------------------------


def test_filter_future_episodes_removes_future_placeholders() -> None:
    """Placeholder episodes with future air dates should be removed."""
    import datetime

    today = datetime.date.today()
    future_date = (today + datetime.timedelta(days=10)).isoformat()
    past_date = (today - datetime.timedelta(days=10)).isoformat()

    series_data: Dict[str, Any] = {
        "seasons": {
            "Season 1": {
                "episodes": [
                    {"name": "S01E01", "path": "/real.mkv", "tmdb_number": 1},
                    {
                        "name": "Future Ep",
                        "path": None,
                        "tmdb_number": 2,
                        "air_date": future_date,
                    },
                    {
                        "name": "Past Ep",
                        "path": None,
                        "tmdb_number": 3,
                        "air_date": past_date,
                    },
                    {
                        "name": "No Date Ep",
                        "path": None,
                        "tmdb_number": 4,
                        "air_date": "",
                    },
                ],
            }
        }
    }
    _filter_future_episodes(series_data)
    episodes = series_data["seasons"]["Season 1"]["episodes"]
    numbers = {e["tmdb_number"] for e in episodes}
    assert 1 in numbers  # Has a path, always kept
    assert 2 not in numbers  # Future date, removed
    assert 3 in numbers  # Past date, kept
    assert 4 not in numbers  # No date, removed


def test_filter_future_episodes_keeps_all_when_no_placeholders() -> None:
    """When all episodes have paths, nothing is removed."""
    series_data = {
        "seasons": {
            "Season 1": {
                "episodes": [
                    {"name": "S01E01", "path": "/real1.mkv", "tmdb_number": 1},
                    {"name": "S01E02", "path": "/real2.mkv", "tmdb_number": 2},
                ],
            }
        }
    }
    _filter_future_episodes(series_data)
    assert len(series_data["seasons"]["Season 1"]["episodes"]) == 2


def test_filter_future_episodes_empty_seasons() -> None:
    """Empty series data should not raise errors."""
    series_data: Dict[str, Any] = {"seasons": {}}
    _filter_future_episodes(series_data)
    assert series_data == {"seasons": {}}


# ---------------------------------------------------------------------------
# Integration tests for _group_and_resolve_episode_versions
# ---------------------------------------------------------------------------


def test_group_and_resolve_version_matching_real_flow() -> None:
    """Integration: existing versions matched by path without mocking choose_active_version."""
    scanned = [
        {"name": "S01E01", "path": "/show/S01E01.mkv", "tmdb_number": 1},
    ]
    existing_eps = [
        {
            "name": "S01E01",
            "tmdb_number": 1,
            "versions": [
                {
                    "path": "/show/S01E01.mkv",
                    "resolution": "1080p",
                    "video_codec": "h264",
                },
            ],
            "default_path": None,
        },
    ]
    # Patch only file info functions (which do I/O), not choose_active_version
    with (
        patch(
            "lan_streamer.scanner.scan_tv.get_stub_file_info",
            return_value={"path": "/show/S01E01.mkv", "resolution": "1080p"},
        ),
        patch(
            "lan_streamer.scanner.scan_tv.get_detailed_file_info",
            return_value={"path": "/show/S01E01.mkv", "resolution": "1080p"},
        ),
    ):
        result = _group_and_resolve_episode_versions(
            scanned_episodes=scanned,
            existing_season_episodes=existing_eps,
            season_offline=False,
            force_refresh=False,
            metadata_only=False,
        )
    assert len(result) == 1
    # Existing version reused because force_refresh=False → path matched
    assert result[0]["versions"][0]["video_codec"] == "h264"


def test_group_and_resolve_version_force_refresh() -> None:
    """Integration: force_refresh=True causes re-fetch even with existing version."""
    scanned = [
        {"name": "S01E01", "path": "/show/S01E01.mkv", "tmdb_number": 1},
    ]
    existing_eps = [
        {
            "name": "S01E01",
            "tmdb_number": 1,
            "versions": [
                {"path": "/show/S01E01.mkv", "resolution": "old", "video_codec": "old"},
            ],
            "default_path": None,
        },
    ]
    with (
        patch(
            "lan_streamer.scanner.scan_tv.get_detailed_file_info",
            return_value={
                "path": "/show/S01E01.mkv",
                "resolution": "fresh",
                "video_codec": "fresh",
            },
        ),
    ):
        result = _group_and_resolve_episode_versions(
            scanned_episodes=scanned,
            existing_season_episodes=existing_eps,
            season_offline=False,
            force_refresh=True,
            metadata_only=False,
        )
    assert len(result) == 1
    # With force_refresh=True, the existing version is NOT reused;
    # get_detailed_file_info is called instead
    assert result[0]["versions"][0]["resolution"] == "fresh"


# ---------------------------------------------------------------------------
# scan_series orchestration — basic integration smoke test
# ---------------------------------------------------------------------------


def test_scan_series_importable() -> None:
    """The refactored scan_series is importable via the public API."""
    from lan_streamer.scanner import scan_series as public_scan_series

    assert public_scan_series is scan_series


def test_scan_series_basic_smoke(tmp_path: Path) -> None:
    """Minimal integration test: series with one episode returns expected structure."""
    series_dir = tmp_path / "Test Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "Test Show S01E01.mkv"
    episode_file.write_text("video content")

    with (
        patch("lan_streamer.services.metadata_series.tmdb_client") as mock_tmdb,
        patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb),
    ):
        mock_tmdb.is_configured.return_value = True
        mock_tmdb.search_series.return_value = {
            "id": "series123",
            "tmdb_identifier": "series123",
            "name": "Test Show",
            "overview": "A test show",
            "poster_path": "",
        }
        mock_tmdb.get_seasons.return_value = [
            {
                "id": "season123",
                "episode_number": 1,
                "name": "Season 1",
                "season_number": 1,
                "image": "",
            }
        ]
        mock_tmdb.get_episodes.return_value = [
            {"id": "ep123", "episode_number": 1, "name": "Episode 1"}
        ]
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(series_dir)

    assert series_data["metadata"]["tmdb_identifier"] == "series123"
    assert "Season 1" in series_data["seasons"]
    episodes = series_data["seasons"]["Season 1"]["episodes"]
    assert len(episodes) >= 1
    assert episodes[0]["tmdb_identifier"] == "ep123"
    assert episodes[0]["watched"] is False


def test_scan_series_early_return(tmp_path: Path) -> None:
    """When existing data has all episodes, early return path works."""
    series_dir = tmp_path / "Fast Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "S01E01.mkv"
    episode_file.touch()

    existing = {
        "metadata": {
            "tmdb_identifier": "fast_id",
            "tmdb_name": "Fast Show",
        },
        "seasons": {
            "Season 1": {
                "metadata": {},
                "episodes": [
                    {
                        "name": "S01E01.mkv",
                        "path": str(episode_file.absolute()),
                        "tmdb_identifier": "ep_old",
                        "watched": True,
                    }
                ],
            }
        },
    }

    with (
        patch("lan_streamer.services.metadata_series.tmdb_client") as mock_tmdb,
        patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb),
    ):
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 1, "id": "s1", "name": "Season 1"}
        ]
        mock_tmdb.get_episodes.return_value = [
            {"id": "ep_new", "episode_number": 1, "name": "Pilot"}
        ]

        series_data = scan_series(
            series_dir, existing_series_data=existing, force_refresh=False
        )

    assert series_data["metadata"]["tmdb_name"] == "Fast Show"
    assert series_data["seasons"]["Season 1"]["episodes"][0]["watched"] is True
