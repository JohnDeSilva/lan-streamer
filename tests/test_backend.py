from unittest.mock import patch
from typing import List, Dict, Any
from lan_streamer.backend import (
    ScanWorker,
    CleanupWorker,
    JellyfinPullWorker,
    JellyfinPushWorker,
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
