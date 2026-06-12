from unittest.mock import patch

from lan_streamer.scanner.core import (
    _has_season_files_changed,
    _has_movie_files_changed,
)
from lan_streamer.backend.metadata_worker_property import FilePropertyExtractionWorker


def test_has_season_files_changed(tmp_path) -> None:
    season_dir = tmp_path / "Season 1"
    season_dir.mkdir()
    ep_file = season_dir / "S01E01.mkv"
    ep_file.touch()

    # 1. Empty existing season -> changed
    existing = {"episodes": []}
    assert _has_season_files_changed(season_dir, existing) is True

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
    assert _has_season_files_changed(season_dir, existing) is False

    # 3. Size mismatch -> changed
    existing = {
        "episodes": [
            {
                "path": str(ep_file.absolute()),
                "size_bytes": disk_size + 100,
            }
        ]
    }
    assert _has_season_files_changed(season_dir, existing) is True


def test_has_season_files_changed_extra_file(tmp_path) -> None:
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
    assert _has_season_files_changed(season_dir, existing) is True


def test_has_season_files_changed_unknown_path(tmp_path) -> None:
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
    assert _has_season_files_changed(season_dir, existing) is True


def test_has_movie_files_changed(tmp_path) -> None:
    movie_dir = tmp_path / "Inception"
    movie_dir.mkdir()
    movie_file = movie_dir / "Inception.mkv"
    movie_file.touch()

    # 1. Empty existing -> changed
    assert _has_movie_files_changed(movie_dir, {}) is True

    # 2. Match -> unchanged
    disk_size = movie_file.stat().st_size
    existing = {
        "path": str(movie_file.absolute()),
        "size_bytes": disk_size,
        "versions": [{"path": str(movie_file.absolute()), "size_bytes": disk_size}],
    }
    assert _has_movie_files_changed(movie_dir, existing) is False

    # 3. Version mismatch -> changed
    existing = {
        "path": str(movie_file.absolute()),
        "size_bytes": disk_size,
        "versions": [
            {"path": str(movie_file.absolute()), "size_bytes": disk_size + 50}
        ],
    }
    assert _has_movie_files_changed(movie_dir, existing) is True


def test_has_movie_files_changed_missing_version_path(tmp_path) -> None:
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
    assert _has_movie_files_changed(movie_dir, existing) is False


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
