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
