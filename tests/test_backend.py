from unittest.mock import patch
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
    with patch(
        "lan_streamer.backend.scan_directories", return_value={"Cosmos": {}}
    ) as mock_scan:
        emitted_results: List[Dict[str, Any]] = []
        worker = ScanWorker(["/path"], "tv", {})
        worker.finished.connect(emitted_results.append)
        worker.run()
        mock_scan.assert_called_once()
        assert emitted_results == [{"Cosmos": {}}]

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
            "lan_streamer.backend.scan_directories", return_value={"new_data": {}}
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
