from pathlib import Path
from unittest.mock import patch, MagicMock
from typing import List, Dict, Any
from lan_streamer.backend import (
    ScanWorker,
    CleanupWorker,
    JellyfinPullWorker,
    JellyfinPushWorker,
    ScanAllLibrariesWorker,
    CleanupAllLibrariesWorker,
    RuntimeExtractionWorker,
)


def test_scan_worker_execution() -> None:
    # Successful run
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = ["/unavailable/path"]
    with patch("lan_streamer.backend.scan_directories", return_value=lib) as mock_scan:
        emitted_results: List[Dict[str, Any]] = []
        worker = ScanWorker(["/path", "/unavailable/path"], "tv", {})
        worker.finished.connect(emitted_results.append)
        worker.run()
        mock_scan.assert_called_once()
        assert emitted_results == [{"Cosmos": {}}]
        assert worker.unavailable_directories == ["/unavailable/path"]

    # Exception run
    with patch(
        "lan_streamer.backend.scan_directories", side_effect=Exception("Scan error")
    ):
        emitted_errors: List[str] = []
        worker = ScanWorker(["/path"], "tv", {})
        worker.error.connect(emitted_errors.append)
        worker.run()
        assert emitted_errors == ["Scan error"]


def test_cleanup_worker_execution() -> None:
    # Successful run
    with patch(
        "lan_streamer.db.cleanup_library", return_value={"series": 1}
    ) as mock_clean:
        emitted_results: List[Dict[str, Any]] = []
        worker = CleanupWorker("TestLib", ["/path"])
        worker.finished.connect(emitted_results.append)
        worker.run()
        mock_clean.assert_called_once()
        assert emitted_results == [{"series": 1}]

    # Exception run
    with patch(
        "lan_streamer.db.cleanup_library", side_effect=Exception("Cleanup error")
    ):
        emitted_errors: List[str] = []
        worker = CleanupWorker("TestLib", ["/path"])
        worker.error.connect(emitted_errors.append)
        worker.run()
        assert emitted_errors == ["Cleanup error"]


def test_jellyfin_pull_worker_execution() -> None:
    # Successful run
    with (
        patch(
            "lan_streamer.jellyfin.jellyfin_client.fetch_watched_episodes",
            return_value=(["id1"], ["/path"], ["ep1"]),
        ),
        patch(
            "lan_streamer.db.sync_watched_from_jellyfin_data", return_value=1
        ) as mock_sync,
    ):
        emitted_results: List[int] = []
        worker = JellyfinPullWorker()
        worker.finished.connect(emitted_results.append)
        worker.run()
        mock_sync.assert_called_once_with(["id1"], ["/path"], ["ep1"])
        assert emitted_results == [1]

    # Exception run
    with patch(
        "lan_streamer.jellyfin.jellyfin_client.fetch_watched_episodes",
        side_effect=Exception("Pull error"),
    ):
        emitted_errors: List[str] = []
        worker = JellyfinPullWorker()
        worker.error.connect(emitted_errors.append)
        worker.run()
        assert emitted_errors == ["Pull error"]


def test_jellyfin_push_worker_execution() -> None:
    # Successful run
    with (
        patch(
            "lan_streamer.db.get_all_episodes_with_jellyfin_id",
            return_value=[{"jellyfin_id": "jf1", "watched": True}],
        ),
        patch("lan_streamer.jellyfin.jellyfin_client.set_watched_status") as mock_set,
    ):
        emitted_results: List[int] = []
        worker = JellyfinPushWorker()
        worker.finished.connect(emitted_results.append)
        worker.run()
        mock_set.assert_called_once_with("jf1", True)
        assert emitted_results == [1]

    # Exception run
    with patch(
        "lan_streamer.db.get_all_episodes_with_jellyfin_id",
        side_effect=Exception("Push error"),
    ):
        emitted_errors: List[str] = []
        worker = JellyfinPushWorker()
        worker.error.connect(emitted_errors.append)
        worker.run()
        assert emitted_errors == ["Push error"]


def test_scan_all_libraries_worker_execution() -> None:
    # Successful run
    from lan_streamer.scanner import LibraryDict

    lib_tv = LibraryDict({"new_data": {}})
    lib_tv.unavailable_directories = ["/unavailable_tv"]
    lib_movie = LibraryDict({"new_data": {}})
    lib_movie.unavailable_directories = ["/unavailable_movie"]

    with (
        patch("lan_streamer.backend.config") as mock_config,
        patch("lan_streamer.backend.jellyfin_client.is_configured", return_value=True),
        patch(
            "lan_streamer.backend.jellyfin_client.get_jellyfin_correlation_data",
            return_value={"map": {}},
        ),
        patch("lan_streamer.backend.db.load_library", return_value={"old_tv": {}}),
        patch(
            "lan_streamer.backend.db.load_movie_library",
            return_value={"old_movie": {}},
        ),
        patch(
            "lan_streamer.backend.scan_directories", side_effect=[lib_tv, lib_movie]
        ) as mock_scan,
        patch("lan_streamer.backend.db.save_library") as mock_save_tv,
        patch("lan_streamer.backend.db.save_movie_library") as mock_save_movie,
    ):
        mock_config.libraries = {
            "TV_Lib": {"paths": ["/tv_path"], "type": "tv"},
            "Movie_Lib": {"paths": ["/movie_path"], "type": "movie"},
        }
        progress_emitted: List[tuple] = []
        finished_emitted: List[bool] = []

        worker = ScanAllLibrariesWorker(force_refresh=True)
        worker.library_progress.connect(
            lambda name, comp, tot: progress_emitted.append((name, comp, tot))
        )
        worker.finished.connect(lambda: finished_emitted.append(True))
        worker.run()

        assert len(mock_scan.call_args_list) == 2
        mock_save_tv.assert_called_once_with("TV_Lib", {"new_data": {}})
        mock_save_movie.assert_called_once_with("Movie_Lib", {"new_data": {}})
        assert progress_emitted == [("TV_Lib", 1, 2), ("Movie_Lib", 2, 2)]
        assert finished_emitted == [True]
        assert worker.unavailable_directories == [
            "/unavailable_tv",
            "/unavailable_movie",
        ]

    # Exception run
    with patch("lan_streamer.backend.config") as mock_config:
        mock_config.libraries = {"TV_Lib": {}}
        with patch(
            "lan_streamer.backend.scan_directories",
            side_effect=Exception("Global scan error"),
        ):
            errors_emitted: List[str] = []
            worker = ScanAllLibrariesWorker()
            worker.error.connect(errors_emitted.append)
            worker.run()
            assert errors_emitted == ["Global scan error"]


def test_cleanup_all_libraries_worker_execution() -> None:
    # Successful run
    with (
        patch("lan_streamer.backend.config") as mock_config,
        patch("lan_streamer.backend.db.cleanup_library") as mock_clean,
    ):
        mock_config.libraries = {
            "LibA": {"paths": ["/path_a"]},
            "LibB": {"paths": ["/path_b"]},
        }
        progress_emitted: List[tuple] = []
        finished_emitted: List[bool] = []

        worker = CleanupAllLibrariesWorker()
        worker.library_progress.connect(
            lambda name, comp, tot: progress_emitted.append((name, comp, tot))
        )
        worker.finished.connect(lambda: finished_emitted.append(True))
        worker.run()

        assert mock_clean.call_count == 2
        mock_clean.assert_any_call("LibA", ["/path_a"])
        mock_clean.assert_any_call("LibB", ["/path_b"])
        assert progress_emitted == [("LibA", 1, 2), ("LibB", 2, 2)]
        assert finished_emitted == [True]

    # Exception run
    with patch("lan_streamer.backend.config") as mock_config:
        mock_config.libraries = {"LibA": {}}
        with patch(
            "lan_streamer.backend.db.cleanup_library",
            side_effect=Exception("Global clean error"),
        ):
            errors_emitted: List[str] = []
            worker = CleanupAllLibrariesWorker()
            worker.error.connect(errors_emitted.append)
            worker.run()
            assert errors_emitted == ["Global clean error"]


def test_runtime_extraction_worker_execution() -> None:
    # Successful run
    with (
        patch("lan_streamer.backend.db.get_items_missing_runtime") as mock_get_items,
        patch("lan_streamer.scanner._extract_video_runtime") as mock_extract,
        patch("lan_streamer.backend.db.update_item_runtime") as mock_update,
    ):
        mock_get_items.return_value = [
            {"id": 101, "path": "/vid1.mkv", "type": "episode"},
            {"id": 102, "path": "/vid2.mkv", "type": "movie"},
        ]
        mock_extract.side_effect = [22, 0]

        progress_emitted: List[tuple] = []
        finished_emitted: List[int] = []

        worker = RuntimeExtractionWorker()
        worker.progress_updated.connect(
            lambda completed, total: progress_emitted.append((completed, total))
        )
        worker.finished.connect(finished_emitted.append)
        worker.run()

        assert mock_extract.call_count == 2
        mock_update.assert_called_once_with(101, "episode", 22)
        assert progress_emitted == [(1, 2), (2, 2)]
        assert finished_emitted == [1]

    # Exception run
    with patch(
        "lan_streamer.backend.db.get_items_missing_runtime",
        side_effect=Exception("DB connection error"),
    ):
        errors_emitted: List[str] = []
        worker = RuntimeExtractionWorker()
        worker.error.connect(errors_emitted.append)
        worker.run()
        assert errors_emitted == ["DB connection error"]


# ---------------------------------------------------------------------------
# SubtitleMergeWorker
# ---------------------------------------------------------------------------


def test_subtitle_merge_worker_success(tmp_path: Path) -> None:
    from lan_streamer.backend import SubtitleMergeWorker

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
    from lan_streamer.backend import SubtitleMergeWorker

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
    from lan_streamer.backend import SubtitleMergeWorker

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
    from lan_streamer.backend import SubtitleMergeWorker

    video_file = tmp_path / "video.mp4"
    video_file.touch()

    errors_emitted: List[str] = []
    worker = SubtitleMergeWorker(str(video_file), [])
    worker.error.connect(errors_emitted.append)

    with patch("subprocess.run", side_effect=RuntimeError("unexpected")):
        worker.run()

    assert len(errors_emitted) == 1


# ---------------------------------------------------------------------------
# MetadataEmbedWorker
# ---------------------------------------------------------------------------


def test_metadata_embed_worker_success(tmp_path: Path) -> None:
    from lan_streamer.backend import MetadataEmbedWorker

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
    from lan_streamer.backend import MetadataEmbedWorker

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


# ---------------------------------------------------------------------------
# SeriesMetadataEmbedWorker
# ---------------------------------------------------------------------------


def test_series_metadata_embed_worker_success(tmp_path: Path) -> None:
    """Worker iterates over all episodes and embeds metadata."""
    from lan_streamer.backend import SeriesMetadataEmbedWorker

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
    """Episodes with an empty path should be silently skipped."""
    from lan_streamer.backend import SeriesMetadataEmbedWorker

    episodes: List[Dict[str, Any]] = [
        {"path": "", "tmdb_name": "Ghost Episode"},
    ]

    finished_emitted: List[bool] = []
    worker = SeriesMetadataEmbedWorker("Test Series", episodes)
    worker.finished.connect(lambda: finished_emitted.append(True))

    # subprocess.run must never be called for an empty path
    with patch("subprocess.run") as mock_run:
        worker.run()
        mock_run.assert_not_called()

    assert finished_emitted == [True]


def test_series_metadata_embed_worker_exception() -> None:
    """Unexpected exceptions should emit via the error signal."""
    from lan_streamer.backend import SeriesMetadataEmbedWorker

    episodes: List[Dict[str, Any]] = [
        {"path": "/some/video.mp4", "tmdb_name": "EP"},
    ]

    errors_emitted: List[str] = []
    worker = SeriesMetadataEmbedWorker("Series X", episodes)
    worker.error.connect(errors_emitted.append)

    with patch("subprocess.run", side_effect=OSError("Disk I/O error")):
        worker.run()

    assert len(errors_emitted) == 1
