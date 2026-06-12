from unittest.mock import patch
from typing import List, Dict, Any

from lan_streamer.backend import (
    ScanWorker,
    CleanupWorker,
    ScanAllLibrariesWorker,
)


def test_scan_worker_execution() -> None:
    # Successful run
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = ["/unavailable/path"]
    with patch(
        "lan_streamer.backend.scan_workers.scan_directories", return_value=lib
    ) as mock_scan:
        emitted_results: List[Dict[str, Any]] = []
        worker = ScanWorker(["/path", "/unavailable/path"], "tv", {})
        worker.finished.connect(emitted_results.append)
        worker.run()
        assert mock_scan.call_count == 2
        assert emitted_results == [{"Cosmos": {}}]
        assert worker.unavailable_directories == ["/unavailable/path"]

    # Exception run
    with patch(
        "lan_streamer.backend.scan_workers.scan_directories",
        side_effect=Exception("Scan error"),
    ):
        emitted_errors: List[str] = []
        worker = ScanWorker(["/path"], "tv", {})
        worker.error.connect(emitted_errors.append)
        worker.run()
        assert emitted_errors == ["Scan error"]


def test_cleanup_worker_execution() -> None:
    # Successful run
    with patch(
        "lan_streamer.backend.scan_workers.db.cleanup_library",
        return_value={"series": 1},
    ) as mock_clean:
        emitted_results: List[Dict[str, Any]] = []
        worker = CleanupWorker("TestLib", ["/path"])
        worker.finished.connect(emitted_results.append)
        worker.run()
        mock_clean.assert_called_once()
        assert emitted_results == [{"series": 1}]

    # Exception run
    with patch(
        "lan_streamer.backend.scan_workers.db.cleanup_library",
        side_effect=Exception("Cleanup error"),
    ):
        emitted_errors: List[str] = []
        worker = CleanupWorker("TestLib", ["/path"])
        worker.error.connect(emitted_errors.append)
        worker.run()
        assert emitted_errors == ["Cleanup error"]


def test_scan_all_libraries_worker_execution() -> None:
    # Successful run
    from lan_streamer.scanner import LibraryDict

    lib_tv = LibraryDict({"new_data": {}})
    lib_tv.unavailable_directories = ["/unavailable_tv"]
    lib_movie = LibraryDict({"new_data": {}})
    lib_movie.unavailable_directories = ["/unavailable_movie"]

    with (
        patch("lan_streamer.backend.scan_workers.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_workers.jellyfin_client.is_configured",
            return_value=True,
        ),
        patch(
            "lan_streamer.backend.scan_workers.jellyfin_client.get_jellyfin_correlation_data",
            return_value={"map": {}},
        ),
        patch(
            "lan_streamer.backend.scan_workers.db.load_library",
            return_value={"old_tv": {}},
        ),
        patch(
            "lan_streamer.backend.scan_workers.db.load_movie_library",
            return_value={"old_movie": {}},
        ),
        patch(
            "lan_streamer.backend.scan_workers.scan_directories",
            side_effect=[lib_tv, lib_tv, lib_movie, lib_movie],
        ) as mock_scan,
        patch("lan_streamer.backend.scan_workers.db.save_library") as mock_save_tv,
        patch(
            "lan_streamer.backend.scan_workers.db.save_movie_library"
        ) as mock_save_movie,
    ):
        mock_config.libraries = {
            "TV_Lib": {"paths": ["/tv_path"], "type": "tv"},
            "Movie_Lib": {"paths": ["/movie_path"], "type": "movie"},
        }
        progress_emitted: List[tuple] = []
        detail_emitted: List[tuple] = []
        finished_emitted: List[bool] = []

        worker = ScanAllLibrariesWorker(force_refresh=True)
        worker.library_progress.connect(
            lambda name, comp, tot: progress_emitted.append((name, comp, tot))
        )
        worker.detail_progress.connect(
            lambda ev, payload: detail_emitted.append((ev, payload))
        )
        worker.finished.connect(lambda: finished_emitted.append(True))
        worker.run()

        assert len(mock_scan.call_args_list) == 4
        assert mock_save_tv.call_count == 2
        assert mock_save_movie.call_count == 2
        assert progress_emitted == [("TV_Lib", 1, 2), ("Movie_Lib", 2, 2)]
        assert finished_emitted == [True]
        assert worker.unavailable_directories == [
            "/unavailable_tv",
            "/unavailable_movie",
        ]
        assert (
            "start_root",
            {"library": "TV_Lib", "root": "/tv_path"},
        ) in detail_emitted
        assert (
            "finish_root",
            {"library": "TV_Lib", "root": "/tv_path"},
        ) in detail_emitted
        assert (
            "start_root",
            {"library": "Movie_Lib", "root": "/movie_path"},
        ) in detail_emitted
        assert (
            "finish_root",
            {"library": "Movie_Lib", "root": "/movie_path"},
        ) in detail_emitted

    # Exception run
    with patch("lan_streamer.backend.scan_workers.config") as mock_config:
        mock_config.libraries = {"TV_Lib": {}}
        with patch(
            "lan_streamer.backend.scan_workers.scan_directories",
            side_effect=Exception("Global scan error"),
        ):
            errors_emitted: List[str] = []
            worker = ScanAllLibrariesWorker()
            worker.error.connect(errors_emitted.append)
            worker.run()
            assert errors_emitted == ["Global scan error"]


def test_scan_worker_detail_progress() -> None:
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = []

    # Mock discover_single_library_tree to return custom structure
    mock_tree = {"/path": ["Series A", "Series B"]}

    with (
        patch(
            "lan_streamer.backend.scan_workers.discover_single_library_tree",
            return_value=mock_tree,
        ) as mock_discover,
        patch(
            "lan_streamer.backend.scan_workers.scan_directories", return_value=lib
        ) as mock_scan,
    ):
        emitted_details = []
        worker = ScanWorker(["/path"], "tv", {})
        worker.detail_progress.connect(
            lambda ev, payload: emitted_details.append((ev, payload))
        )

        # We also want to simulate scan_directories calling the detail_callback
        def fake_scan(*args, **kwargs):
            detail_cb = kwargs.get("detail_callback")
            if detail_cb:
                detail_cb("start_folder", {"root": "/path", "folder": "Series A"})
                detail_cb(
                    "finish_folder",
                    {"root": "/path", "folder": "Series A", "skipped": False},
                )
            return lib

        mock_scan.side_effect = fake_scan

        worker.run()

        mock_discover.assert_called_once_with(["/path"], "tv")
        assert mock_scan.call_count == 2

        # Verify the progress signals emitted
        assert len(emitted_details) == 7
        assert emitted_details[0] == (
            "init_library_scan",
            {"roots": mock_tree, "roots_order": ["/path"]},
        )
        assert emitted_details[1] == ("start_offline_scan", {"library": ""})
        assert emitted_details[2] == (
            "start_folder",
            {"root": "/path", "folder": "Series A"},
        )
        assert emitted_details[3] == (
            "finish_folder",
            {"root": "/path", "folder": "Series A", "skipped": False},
        )
        assert emitted_details[4] == ("start_metadata_resolution", {"library": ""})
        assert emitted_details[5] == (
            "start_folder",
            {"root": "/path", "folder": "Series A"},
        )
        assert emitted_details[6] == (
            "finish_folder",
            {"root": "/path", "folder": "Series A", "skipped": False},
        )
