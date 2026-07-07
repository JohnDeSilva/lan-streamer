from unittest.mock import patch
from lan_streamer.backend.metadata_worker_property import FilePropertyExtractionWorker


@patch("lan_streamer.backend.metadata_worker_property.db")
def test_file_property_worker_no_filter(mock_db) -> None:
    """No filter: all candidates are probed."""
    mock_db.get_items_missing_runtime.return_value = [
        {"id": "E1", "path": "/a.mkv", "type": "episode", "season_id": "S1"},
        {"id": "E2", "path": "/b.mkv", "type": "episode", "season_id": "S2"},
        {"id": "M1", "path": "/c.mkv", "type": "movie"},
    ]

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
