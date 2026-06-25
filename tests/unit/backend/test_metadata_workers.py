from pathlib import Path
from unittest.mock import patch, MagicMock
from typing import List, Dict, Any

from PySide6.QtCore import Qt

import pytest

from lan_streamer.backend import (
    FilePropertyExtractionWorker,
    SubtitleMergeWorker,
    MetadataEmbedWorker,
    SeriesMetadataEmbedWorker,
    RefreshSeriesWorker,
)


def test_runtime_extraction_worker_execution() -> None:
    # Successful run
    with (
        patch("lan_streamer.db.get_items_missing_runtime") as mock_get_items,
        patch("lan_streamer.db.has_tech_and_metadata", return_value=False),
        patch(
            "lan_streamer.backend.metadata_worker_property.get_detailed_file_info"
        ) as mock_info,
        patch("lan_streamer.db.update_items_runtime_batch") as mock_update_batch,
    ):
        mock_get_items.return_value = [
            {
                "id": 101,
                "path": "/vid1.mkv",
                "type": "episode",
                "season_id": "season_1",
                "library_name": "TV",
            },
            {"id": 102, "path": "/vid2.mkv", "type": "movie", "library_name": "TV"},
        ]
        mock_info.side_effect = [
            {
                "runtime": 22,
                "video_codec": "h264",
                "resolution": "1920x1080",
                "audio_tracks": [],
                "subtitle_tracks": [],
            },
            {
                "runtime": None,
                "video_codec": None,
                "resolution": None,
                "audio_tracks": [],
                "subtitle_tracks": [],
            },
        ]

        progress_emitted: List[tuple] = []
        finished_emitted: List[int] = []

        worker = FilePropertyExtractionWorker()
        worker.progress_updated.connect(
            lambda completed, total: progress_emitted.append((completed, total)),
            Qt.DirectConnection,
        )
        worker.finished.connect(finished_emitted.append)
        worker.run()

        assert mock_info.call_count == 2
        mock_update_batch.assert_called_once_with(
            [
                {
                    "item_identifier": 101,
                    "item_type": "episode",
                    "runtime_minutes": 22,
                    "video_codec": "h264",
                    "resolution": "1920x1080",
                    "audio_tracks": [],
                    "subtitle_tracks": [],
                    "bit_rate": None,
                    "size_bytes": None,
                }
            ]
        )
        assert progress_emitted == [(2, 2)]
        assert finished_emitted == [1]

    # Exception run
    with patch(
        "lan_streamer.db.get_items_missing_runtime",
        side_effect=Exception("DB connection error"),
    ):
        errors_emitted: List[str] = []
        worker = FilePropertyExtractionWorker()
        worker.error.connect(errors_emitted.append)
        worker.run()
        assert errors_emitted == ["DB connection error"]


def test_subtitle_merge_worker_success(tmp_path: Path) -> None:
    video_file = tmp_path / "video.mp4"
    video_file.touch()
    subtitle_file = tmp_path / "sub.srt"
    subtitle_file.touch()

    mock_result = MagicMock()
    mock_result.returncode = 0

    finished_emitted: List[str] = []
    worker = SubtitleMergeWorker(str(video_file), [str(subtitle_file)])
    worker.finished.connect(finished_emitted.append)

    with (
        patch("subprocess.run", return_value=mock_result),
        patch("os.replace"),
        patch("os.remove"),
    ):
        worker.run()

    assert finished_emitted == [str(video_file)]


def test_subtitle_merge_worker_language_metadata(tmp_path: Path) -> None:
    """Subtitle files with .en.srt suffixes should inject language metadata args."""
    video_file = tmp_path / "video.mp4"
    video_file.touch()
    subtitle_file = tmp_path / "movie.en.srt"
    subtitle_file.touch()

    captured_command: List[List[str]] = []

    def fake_run(cmd: List[str], **kwargs: Any) -> MagicMock:
        captured_command.append(cmd)
        result = MagicMock()
        result.returncode = 0
        return result

    finished_emitted: List[str] = []
    worker = SubtitleMergeWorker(str(video_file), [str(subtitle_file)])
    worker.finished.connect(finished_emitted.append)

    with (
        patch("subprocess.run", side_effect=fake_run),
        patch("os.replace"),
        patch("os.remove"),
    ):
        worker.run()

    assert captured_command
    command_string = " ".join(captured_command[0])
    assert "language=en" in command_string


def test_subtitle_merge_worker_ffmpeg_failure(tmp_path: Path) -> None:
    """A non-zero ffmpeg returncode should emit error and not replace files."""
    video_file = tmp_path / "video.mp4"
    video_file.touch()

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "ffmpeg: codec not found"

    errors_emitted: List[str] = []
    worker = SubtitleMergeWorker(str(video_file), [str(tmp_path / "sub.srt")])
    worker.error.connect(errors_emitted.append)

    with patch("subprocess.run", return_value=mock_result):
        worker.run()

    assert len(errors_emitted) == 1
    assert "ffmpeg" in errors_emitted[0]


def test_subtitle_merge_worker_exception(tmp_path: Path) -> None:
    """Unexpected exceptions should be caught and emitted via the error signal."""
    video_file = tmp_path / "video.mp4"
    video_file.touch()

    errors_emitted: List[str] = []
    worker = SubtitleMergeWorker(str(video_file), [])
    worker.error.connect(errors_emitted.append)

    with patch("subprocess.run", side_effect=RuntimeError("unexpected")):
        worker.run()

    assert len(errors_emitted) == 1


def test_metadata_embed_worker_success(tmp_path: Path) -> None:
    video_file = tmp_path / "movie.mp4"
    video_file.touch()

    mock_result = MagicMock()
    mock_result.returncode = 0

    finished_emitted: List[str] = []
    worker = MetadataEmbedWorker(str(video_file), {"title": "Test Movie", "year": ""})
    worker.finished.connect(finished_emitted.append)

    with (
        patch("subprocess.run", return_value=mock_result),
        patch("os.replace"),
    ):
        worker.run()

    assert finished_emitted == [str(video_file)]


def test_metadata_embed_worker_ffmpeg_failure(tmp_path: Path) -> None:
    """Non-zero ffmpeg returncode emits error."""
    video_file = tmp_path / "movie.mp4"
    video_file.touch()

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "codec error"

    errors_emitted: List[str] = []
    worker = MetadataEmbedWorker(str(video_file), {"title": "Test"})
    worker.error.connect(errors_emitted.append)

    with patch("subprocess.run", return_value=mock_result):
        worker.run()

    assert len(errors_emitted) == 1


def test_series_metadata_embed_worker_success(tmp_path: Path) -> None:
    """Worker iterates over all episodes and embeds metadata."""
    ep1 = tmp_path / "S01E01.mp4"
    ep2 = tmp_path / "S01E02.mp4"
    ep1.touch()
    ep2.touch()

    episodes: List[Dict[str, Any]] = [
        {
            "path": str(ep1),
            "tmdb_name": "Episode 1",
            "tmdb_number": 1,
            "air_date": "2024-01-01",
        },
        {"path": str(ep2), "tmdb_name": "Episode 2", "tmdb_number": 2, "air_date": ""},
    ]

    mock_result = MagicMock()
    mock_result.returncode = 0

    progress_emitted: List[tuple] = []
    finished_emitted: List[bool] = []

    worker = SeriesMetadataEmbedWorker("My Series", episodes)
    worker.progress_updated.connect(
        lambda msg, current, total: progress_emitted.append((msg, current, total))
    )
    worker.finished.connect(lambda: finished_emitted.append(True))

    with (
        patch("subprocess.run", return_value=mock_result),
        patch("os.replace"),
    ):
        worker.run()

    assert finished_emitted == [True]
    assert len(progress_emitted) == 2


def test_series_metadata_embed_worker_skips_empty_path() -> None:
    """Episodes with an empty or None path should be silently skipped."""
    episodes: List[Dict[str, Any]] = [
        {"path": "", "tmdb_name": "Ghost Episode"},
        {"path": None, "tmdb_name": "Ghost Episode 2"},
    ]

    finished_emitted: List[bool] = []
    worker = SeriesMetadataEmbedWorker("Test Series", episodes)
    worker.finished.connect(lambda: finished_emitted.append(True))

    # subprocess.run must never be called for an empty or None path
    with patch("subprocess.run") as mock_run:
        worker.run()
        mock_run.assert_not_called()

    assert finished_emitted == [True]


def test_series_metadata_embed_worker_exception() -> None:
    """Unexpected exceptions should emit via the error signal."""
    episodes: List[Dict[str, Any]] = [
        {"path": "/some/video.mp4", "tmdb_name": "EP"},
    ]

    errors_emitted: List[str] = []
    worker = SeriesMetadataEmbedWorker("Series X", episodes)
    worker.error.connect(errors_emitted.append)

    with patch("subprocess.run", side_effect=OSError("Disk I/O error")):
        worker.run()

    assert len(errors_emitted) == 1


@pytest.fixture
def mock_db_save():
    with (
        patch("lan_streamer.db.save_library") as mock_save,
        patch("lan_streamer.db.save_movie_library") as mock_movie_save,
    ):
        yield mock_save, mock_movie_save


def test_refresh_series_worker_success(tmp_path, mock_db_save):
    mock_save, _ = mock_db_save
    series_dir = tmp_path / "Refresh Show"
    series_dir.mkdir()

    existing = {
        "Refresh Show": {"metadata": {"tmdb_identifier": "id_123"}, "seasons": {}}
    }

    worker = RefreshSeriesWorker(
        library_name="TV",
        item_name="Refresh Show",
        library_type="tv",
        root_directories=[str(tmp_path)],
        existing_library=existing,
    )

    with (
        patch("lan_streamer.backend.metadata_worker_refresh.scan_series") as mock_scan,
        patch(
            "lan_streamer.backend.metadata_worker_refresh.clean_series_data",
            lambda x: x,
        ),
    ):
        mock_scan.return_value = {
            "metadata": {"tmdb_identifier": "id_123", "tmdb_name": "Fresh Show"},
            "seasons": {},
        }

        # Catch finished signal
        finished_data = None

        def on_finished(d):
            nonlocal finished_data
            finished_data = d

        worker.finished.connect(on_finished)
        worker.run()

        assert finished_data is not None
        assert finished_data["Refresh Show"]["metadata"]["tmdb_name"] == "Fresh Show"
        mock_save.assert_called_once()
        mock_scan.assert_called_once_with(
            series_dir,
            tmdb_series=None,
            jellyfin_data=None,
            manual_jellyfin_id=None,
            existing_series_data=existing["Refresh Show"],
            force_refresh=True,
            cleanup=False,
            single_item_refresh=True,
            show_future_episodes=True,
        )


def test_refresh_series_worker_not_found(tmp_path):
    worker = RefreshSeriesWorker(
        library_name="TV",
        item_name="Missing Show",
        library_type="tv",
        root_directories=[str(tmp_path)],
        existing_library={},
    )

    error_msg = None

    def on_error(msg):
        nonlocal error_msg
        error_msg = msg

    worker.error.connect(on_error)
    worker.run()
    assert error_msg is not None
    assert "Could not find directory" in error_msg


def test_subtitle_merge_worker_direct():
    worker = SubtitleMergeWorker(
        "/media/tv/Cosmos/S01E01.mkv", ["/media/tv/Cosmos/S01E01.en.srt"]
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("os.replace"):
            with patch("os.remove"):
                worker.run()
                assert mock_run.call_count == 1


def test_file_property_extraction_worker_skips_and_batches() -> None:
    """Verify that FilePropertyExtractionWorker groups/batches database writes per season."""
    with (
        patch("lan_streamer.db.get_items_missing_runtime") as mock_get_items,
        patch(
            "lan_streamer.backend.metadata_worker_property.get_detailed_file_info"
        ) as mock_info,
        patch("lan_streamer.db.update_items_runtime_batch") as mock_update_batch,
    ):
        # 1. Mock get_items_missing_runtime
        # We have two episode candidates:
        # - Episode 201: season_1, missing specs, will be probed
        # - Episode 202: season_1, missing specs, will be probed
        mock_get_items.return_value = [
            {
                "id": 201,
                "path": "/season1_ep1.mkv",
                "type": "episode",
                "season_id": "season_1",
                "library_name": "TV",
            },
            {
                "id": 202,
                "path": "/season1_ep2.mkv",
                "type": "episode",
                "season_id": "season_1",
                "library_name": "TV",
            },
        ]

        # Mock probe info
        mock_info.side_effect = [
            {
                "runtime": 25,
                "video_codec": "hevc",
                "resolution": "3840x2160",
                "audio_tracks": [],
                "subtitle_tracks": [],
            },
            {
                "runtime": 24,
                "video_codec": "hevc",
                "resolution": "3840x2160",
                "audio_tracks": [],
                "subtitle_tracks": [],
            },
        ]

        worker = FilePropertyExtractionWorker()
        worker.run()

        # Check: get_detailed_file_info called twice (for 201 and 202)
        assert mock_info.call_count == 2
        mock_info.assert_any_call("/season1_ep1.mkv")
        mock_info.assert_any_call("/season1_ep2.mkv")

        # Check: 201 and 202 are both in season_1, so their database writes are batched in a single call
        mock_update_batch.assert_called_once()
        batch_arg = mock_update_batch.call_args[0][0]
        assert len(batch_arg) == 2
        assert batch_arg[0]["item_identifier"] == 201
        assert batch_arg[1]["item_identifier"] == 202
