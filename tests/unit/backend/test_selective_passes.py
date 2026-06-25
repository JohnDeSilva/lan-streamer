from unittest.mock import patch

from lan_streamer.services.file_discovery import (
    detect_tv_file_changes,
    detect_movie_file_changes,
)
from lan_streamer.backend.metadata_worker_property import FilePropertyExtractionWorker


def test_detect_tv_file_changes(tmp_path) -> None:
    season_dir = tmp_path / "Season 1"
    season_dir.mkdir()
    ep_file = season_dir / "S01E01.mkv"
    ep_file.touch()

    # 1. Empty existing season -> changed
    existing = {"episodes": []}
    assert detect_tv_file_changes(season_dir, existing) is True

    # 2. Matching size and path -> not changed
    disk_size = ep_file.stat().st_size
    existing = {
        "episodes": [
            {
                "path": str(ep_file.absolute()),
                "size_bytes": disk_size,
            }
        ]
    }
    assert detect_tv_file_changes(season_dir, existing) is False

    # 3. Size mismatch -> changed
    existing = {
        "episodes": [
            {
                "path": str(ep_file.absolute()),
                "size_bytes": disk_size + 100,
            }
        ]
    }
    assert detect_tv_file_changes(season_dir, existing) is True


def test_detect_tv_file_changes_extra_file(tmp_path) -> None:
    season_dir = tmp_path / "Season 1"
    season_dir.mkdir()
    ep1 = season_dir / "S01E01.mkv"
    ep2 = season_dir / "S01E02.mkv"
    ep1.touch()
    ep2.touch()
    disk_size = ep1.stat().st_size

    # Only one episode in existing but two on disk -> changed
    existing = {
        "episodes": [
            {"path": str(ep1.absolute()), "size_bytes": disk_size},
        ]
    }
    assert detect_tv_file_changes(season_dir, existing) is True


def test_detect_tv_file_changes_unknown_path(tmp_path) -> None:
    season_dir = tmp_path / "Season 1"
    season_dir.mkdir()
    ep_file = season_dir / "S01E01.mkv"
    ep_file.touch()
    disk_size = ep_file.stat().st_size

    # Different path in existing -> changed
    existing = {
        "episodes": [
            {"path": "/some/other/path.mkv", "size_bytes": disk_size},
        ]
    }
    assert detect_tv_file_changes(season_dir, existing) is True


def test_detect_movie_file_changes(tmp_path) -> None:
    movie_dir = tmp_path / "Inception"
    movie_dir.mkdir()
    movie_file = movie_dir / "Inception.mkv"
    movie_file.touch()

    # 1. Empty existing -> changed
    assert detect_movie_file_changes(movie_dir, {}) is True

    # 2. Match -> unchanged
    disk_size = movie_file.stat().st_size
    existing = {
        "path": str(movie_file.absolute()),
        "size_bytes": disk_size,
        "versions": [{"path": str(movie_file.absolute()), "size_bytes": disk_size}],
    }
    assert detect_movie_file_changes(movie_dir, existing) is False

    # 3. Version mismatch -> changed
    existing = {
        "path": str(movie_file.absolute()),
        "size_bytes": disk_size,
        "versions": [
            {"path": str(movie_file.absolute()), "size_bytes": disk_size + 50}
        ],
    }
    assert detect_movie_file_changes(movie_dir, existing) is True


def test_detect_movie_file_changes_missing_version_path(tmp_path) -> None:
    movie_dir = tmp_path / "Matrix"
    movie_dir.mkdir()
    movie_file = movie_dir / "Matrix.mkv"
    movie_file.touch()
    disk_size = movie_file.stat().st_size

    # existing has no versions; path match via top-level path key
    existing = {
        "path": str(movie_file.absolute()),
        "size_bytes": disk_size,
    }
    # No versions key means existing_by_path built from top-level path
    assert detect_movie_file_changes(movie_dir, existing) is False


@patch("lan_streamer.backend.metadata_worker_property.db")
def test_file_property_worker_no_filter(mock_db) -> None:
    """No filter: all candidates are probed."""
    mock_db.get_items_missing_runtime.return_value = [
        {"id": "E1", "path": "/a.mkv", "type": "episode", "season_id": "S1"},
        {"id": "E2", "path": "/b.mkv", "type": "episode", "season_id": "S2"},
        {"id": "M1", "path": "/c.mkv", "type": "movie"},
    ]
    mock_db.has_tech_and_metadata.return_value = False

    worker = FilePropertyExtractionWorker()
    with patch(
        "lan_streamer.backend.metadata_worker_property.get_detailed_file_info"
    ) as mock_probe:
        mock_probe.return_value = {
            "runtime": 60,
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 5000,
            "audio_tracks": [],
            "subtitle_tracks": [],
            "size_bytes": 1000,
        }
        mock_db.update_items_runtime_batch.return_value = None
        mock_db.update_movie_runtime.return_value = None
        worker.run()
        assert mock_probe.call_count == 3


@patch("lan_streamer.backend.metadata_worker_property.db")
def test_file_property_worker_with_filter(mock_db) -> None:
    """Filter by season_id/movie_id: only changed items are probed."""
    mock_db.get_items_missing_runtime.return_value = [
        {"id": "E1", "path": "/a.mkv", "type": "episode", "season_id": "S1"},
        {"id": "E2", "path": "/b.mkv", "type": "episode", "season_id": "S2"},
        {"id": "M1", "path": "/c.mkv", "type": "movie"},
    ]
    mock_db.has_tech_and_metadata.return_value = False

    worker = FilePropertyExtractionWorker(
        changed_season_ids={"S1"},
        changed_movie_ids={"M1"},
    )
    with patch(
        "lan_streamer.backend.metadata_worker_property.get_detailed_file_info"
    ) as mock_probe:
        mock_probe.return_value = {
            "runtime": 60,
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 5000,
            "audio_tracks": [],
            "subtitle_tracks": [],
            "size_bytes": 1000,
        }
        mock_db.update_items_runtime_batch.return_value = None
        mock_db.update_movie_runtime.return_value = None
        worker.run()
        # Only E1 (S1) and M1 are probed; E2 (S2) is skipped
        assert mock_probe.call_count == 2
        probed_paths = [call.args[0] for call in mock_probe.call_args_list]
        assert "/a.mkv" in probed_paths
        assert "/c.mkv" in probed_paths
        assert "/b.mkv" not in probed_paths


@patch("lan_streamer.backend.metadata_worker_property.db")
def test_file_property_worker_empty_changed_set(mock_db) -> None:
    """Empty changed sets: nothing is probed."""
    mock_db.get_items_missing_runtime.return_value = [
        {"id": "E1", "path": "/a.mkv", "type": "episode", "season_id": "S1"},
        {"id": "M1", "path": "/c.mkv", "type": "movie"},
    ]
    mock_db.has_tech_and_metadata.return_value = False

    worker = FilePropertyExtractionWorker(
        changed_season_ids=set(),
        changed_movie_ids=set(),
    )
    with patch(
        "lan_streamer.backend.metadata_worker_property.get_detailed_file_info"
    ) as mock_probe:
        mock_probe.return_value = {"runtime": 0}
        worker.run()
        assert mock_probe.call_count == 0


def test_detect_tv_file_changes_scandir(tmp_path) -> None:
    season_dir = tmp_path / "Season 1"
    season_dir.mkdir()
    ep_file = season_dir / "S01E01.mkv"
    ep_file.touch()

    # Match case
    disk_size = ep_file.stat().st_size
    existing = {
        "episodes": [
            {
                "path": str(ep_file.absolute()),
                "size_bytes": disk_size,
            }
        ]
    }
    assert detect_tv_file_changes(season_dir, existing) is False

    # Extra folder/file check
    extra_file = season_dir / "ignored.txt"
    extra_file.touch()
    assert detect_tv_file_changes(season_dir, existing) is False  # TXT is ignored

    another_mkv = season_dir / "S01E02.mkv"
    another_mkv.touch()


def test_tv_season_mtime_skip_scanning(tmp_path) -> None:
    from lan_streamer.scanner.scan_tv import _discover_seasons_to_process
    from lan_streamer import db

    series_dir = tmp_path / "Series A"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    ep_file = season_dir / "S01E01.mkv"
    ep_file.touch()

    current_mtime = season_dir.stat().st_mtime
    db.save_directory_mtime(str(season_dir.absolute()), current_mtime)

    existing_series_data = {
        "seasons": {
            "Season 1": {
                "metadata": {},
                "episodes": [
                    {
                        "path": str(ep_file.absolute()),
                        "size_bytes": ep_file.stat().st_size,
                    }
                ],
                "_changed": False,
            }
        }
    }

    # Discover seasons with matching mtime -> is_changed must be False
    seasons = _discover_seasons_to_process(
        series_dir, existing_series_data, False, False
    )
    assert len(seasons) == 1
    assert seasons[0][0] == "Season 1"
    assert seasons[0][1] is False  # Not changed!

    # Change mtime in cached -> is_changed must be True
    db.save_directory_mtime(str(season_dir.absolute()), current_mtime - 10)
    # Modify cached size to trigger change detection fallback
    existing_series_data["seasons"]["Season 1"]["episodes"][0]["size_bytes"] += 100
    seasons = _discover_seasons_to_process(
        series_dir, existing_series_data, False, False
    )
    assert seasons[0][1] is True  # Changed!


def test_tv_series_mtime_unchanged_skips_iterdir(tmp_path) -> None:
    """When the series directory mtime matches the cache, _discover_seasons_to_process
    must use existing season names without calling iterdir() on the series directory."""
    import pathlib
    from unittest.mock import patch
    from lan_streamer.scanner.scan_tv import _discover_seasons_to_process
    from lan_streamer import db

    series_dir = tmp_path / "Series B"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    ep_file = season_dir / "S01E01.mkv"
    ep_file.touch()

    # Record both series and season mtimes as current
    db.save_directory_mtime(str(series_dir.absolute()), series_dir.stat().st_mtime)
    db.save_directory_mtime(str(season_dir.absolute()), season_dir.stat().st_mtime)

    existing_series_data = {
        "seasons": {
            "Season 1": {
                "metadata": {},
                "episodes": [
                    {
                        "path": str(ep_file.absolute()),
                        "size_bytes": ep_file.stat().st_size,
                    }
                ],
            }
        }
    }

    series_dir_str = str(series_dir.absolute())
    iterdir_called_on_series: list[bool] = []
    original_iterdir = pathlib.Path.iterdir

    def tracking_iterdir(self: pathlib.Path):  # type: ignore[override]
        if str(self.absolute()) == series_dir_str:
            iterdir_called_on_series.append(True)
        return original_iterdir(self)

    with patch.object(pathlib.Path, "iterdir", tracking_iterdir):
        seasons = _discover_seasons_to_process(
            series_dir, existing_series_data, False, False
        )

    # iterdir() must NOT have been called on the series directory
    assert not iterdir_called_on_series, (
        "iterdir() was called on the series directory despite matching mtime"
    )

    assert len(seasons) == 1
    assert seasons[0][0] == "Season 1"
    assert seasons[0][1] is False  # Season also unchanged


def test_check_series_directory_mtime_unchanged(tmp_path) -> None:
    from lan_streamer.scanner.scan_tv import _check_series_directory_mtime_unchanged
    from lan_streamer import db

    series_dir = tmp_path / "My Series"
    series_dir.mkdir()

    existing_with_seasons = {"seasons": {"Season 1": {}}}

    # No cached mtime -> not unchanged
    assert (
        _check_series_directory_mtime_unchanged(series_dir, existing_with_seasons)
        is False
    )

    # Cached mtime matches -> unchanged
    current = series_dir.stat().st_mtime
    db.save_directory_mtime(str(series_dir.absolute()), current)
    assert (
        _check_series_directory_mtime_unchanged(series_dir, existing_with_seasons)
        is True
    )

    # Cached mtime stale -> not unchanged
    db.save_directory_mtime(str(series_dir.absolute()), current - 5.0)
    assert (
        _check_series_directory_mtime_unchanged(series_dir, existing_with_seasons)
        is False
    )

    # No existing seasons -> not unchanged (must walk filesystem)
    db.save_directory_mtime(str(series_dir.absolute()), current)
    assert _check_series_directory_mtime_unchanged(series_dir, {"seasons": {}}) is False
    assert _check_series_directory_mtime_unchanged(series_dir, None) is False


def test_movie_mtime_skip_scanning(tmp_path) -> None:
    from lan_streamer.scanner.scan_movie import _detect_movie_changes
    from lan_streamer import db

    movie_dir = tmp_path / "Movie A"
    movie_dir.mkdir()
    movie_file = movie_dir / "Movie A.mkv"
    movie_file.touch()

    current_mtime = movie_dir.stat().st_mtime
    db.save_directory_mtime(str(movie_dir.absolute()), current_mtime)

    existing_movie_data = {
        "path": str(movie_file.absolute()),
        "size_bytes": movie_file.stat().st_size,
        "_changed": False,
        "versions": [
            {
                "path": str(movie_file.absolute()),
                "size_bytes": movie_file.stat().st_size,
            }
        ],
    }

    # Match mtime -> is_changed must be False
    is_changed, offline = _detect_movie_changes(movie_dir, existing_movie_data, False)
    assert is_changed is False

    # Mismatch mtime -> is_changed must be True
    db.save_directory_mtime(str(movie_dir.absolute()), current_mtime - 10)
    # Modify cached size to trigger change detection fallback
    existing_movie_data["size_bytes"] += 100
    existing_movie_data["versions"][0]["size_bytes"] += 100
    is_changed, offline = _detect_movie_changes(movie_dir, existing_movie_data, False)
    assert is_changed is True


def test_series_mtime_skip_scanning(tmp_path) -> None:
    """When the series directory mtime matches the cached DB value, scan_directories
    must skip calling scan_series entirely and reuse the existing series data.
    Uses offline=True (Pass 1) which is the real production path that was
    previously blocked by the erroneous 'not offline' guard."""
    from unittest.mock import patch
    from lan_streamer.scanner.core import scan_directories
    from lan_streamer import db

    # Build a minimal on-disk series layout
    series_dir = tmp_path / "My Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "S01E01.mkv"
    episode_file.touch()

    current_series_mtime = series_dir.stat().st_mtime
    db.save_directory_mtime(str(series_dir.absolute()), current_series_mtime)

    existing_library = {
        "My Show": {
            "metadata": {
                "name": "My Show",
                "tmdb_identifier": "12345",
            },
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "S01E01",
                            "path": str(episode_file.absolute()),
                            "size_bytes": episode_file.stat().st_size,
                        }
                    ],
                }
            },
        }
    }

    # Test with offline=True (Pass 1) — this was the dead code path before the fix.
    with patch("lan_streamer.scanner.core.scan_series") as mock_scan_series:
        result = scan_directories(
            [str(tmp_path)],
            library_type="tv",
            existing_library=existing_library,
            force_refresh=False,
            offline=True,
        )
        mock_scan_series.assert_not_called()

    # The existing series data should be preserved in the result
    assert "My Show" in result
    assert result["My Show"] is existing_library["My Show"]

    # Also verify it still works for offline=False (single-pass online scan).
    with patch("lan_streamer.scanner.core.scan_series") as mock_scan_series:
        result = scan_directories(
            [str(tmp_path)],
            library_type="tv",
            existing_library=existing_library,
            force_refresh=False,
            offline=False,
        )
        mock_scan_series.assert_not_called()

    assert "My Show" in result
    assert result["My Show"] is existing_library["My Show"]


def test_series_mtime_changed_triggers_scan(tmp_path) -> None:
    """When the cached series directory mtime differs from the current mtime,
    scan_directories must NOT skip and must call scan_series."""
    from unittest.mock import patch
    from lan_streamer.scanner.core import scan_directories
    from lan_streamer import db

    series_dir = tmp_path / "New Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "S01E01.mkv"
    episode_file.touch()

    # Store a stale (older) mtime so the check fails
    stale_mtime = series_dir.stat().st_mtime - 100.0
    db.save_directory_mtime(str(series_dir.absolute()), stale_mtime)

    existing_library = {
        "New Show": {
            "metadata": {
                "name": "New Show",
                "tmdb_identifier": "99999",
            },
            "seasons": {},
        }
    }

    sentinel_result: dict = {
        "metadata": {"name": "New Show", "tmdb_identifier": "99999"},
        "seasons": {"Season 1": {"metadata": {}, "episodes": []}},
    }

    # Test with offline=True (Pass 1 path) — mtime mismatch must NOT skip.
    with patch(
        "lan_streamer.scanner.core.scan_series", return_value=sentinel_result
    ) as mock_scan_series:
        with patch(
            "lan_streamer.services.metadata_updates.clean_series_data",
            return_value=sentinel_result,
        ):
            scan_directories(
                [str(tmp_path)],
                library_type="tv",
                existing_library=existing_library,
                force_refresh=False,
                offline=True,
            )
        # scan_series must have been called because the mtime changed
        mock_scan_series.assert_called_once()
