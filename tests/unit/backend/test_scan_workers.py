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
        "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
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
        "lan_streamer.backend.scan_worker_single.scan_directories",
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
        "lan_streamer.backend.scan_worker_cleanup.db.cleanup_library",
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
        "lan_streamer.backend.scan_worker_cleanup.db.cleanup_library",
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
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=True,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.get_jellyfin_correlation_data",
            return_value={"map": {}},
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.load_library",
            return_value={"old_tv": {}},
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.load_movie_library",
            return_value={"old_movie": {}},
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=[lib_tv, lib_tv, lib_movie, lib_movie],
        ) as mock_scan,
        patch("lan_streamer.backend.scan_worker_all.db.save_library") as mock_save_tv,
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_movie_library"
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
    with patch("lan_streamer.backend.scan_worker_all.config") as mock_config:
        mock_config.libraries = {"TV_Lib": {}}
        with patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
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
            "lan_streamer.backend.scan_worker_single.discover_single_library_tree",
            return_value=mock_tree,
        ) as mock_discover,
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
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


def test_scan_workers_reporting() -> None:
    from lan_streamer.scanner import LibraryDict

    # 1. Test ScanWorker reporting
    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = ["/unavailable/root"]

    # We want to mock db methods called inside callbacks
    with (
        patch(
            "lan_streamer.backend.scan_worker_single.discover_single_library_tree",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.scan_worker_single.db.save_season_data"
        ) as mock_save_season,
        patch(
            "lan_streamer.backend.scan_worker_single.db.save_movie_data",
            side_effect=Exception("DB Fail Movie"),
        ),
        patch("lan_streamer.backend.scan_worker_single.logger") as mock_log,
    ):
        mock_save_season.return_value = {
            "series": 1,
            "seasons": 1,
            "episodes": 1,
            "deleted": 0,
            "issues": [
                {
                    "type": "Name Conflict Resolution",
                    "item": "Episode 'Ep 1' (Season: 'Season 1')",
                    "error": "A renamed to B",
                }
            ],
        }

        # Simulate scan_directories invoking callbacks
        def fake_scan(*args, **kwargs):
            season_cb = kwargs.get("season_callback")
            movie_cb = kwargs.get("movie_callback")
            if season_cb:
                season_cb("Cosmos", {}, "Season 1", {})
            if movie_cb:
                movie_cb("Inception", {})
            return lib

        mock_scan.side_effect = fake_scan

        worker = ScanWorker(
            ["/path", "/unavailable/root"], "tv", {}, library_name="TV_Lib"
        )
        worker.run()

        # Check issues gathered in problems list
        assert len(worker.problems) == 5

        # Issue 1: Name Conflict Resolution (returned in stats from save_season_data) from Pass 1
        assert worker.problems[0]["type"] == "Name Conflict Resolution"
        assert "A renamed to B" in worker.problems[0]["error"]

        # Issue 2: Database Write Failure (from save_movie_data exception) from Pass 1
        assert worker.problems[1]["type"] == "Database Write Failure"
        assert "DB Fail Movie" in worker.problems[1]["error"]

        # Issue 3: Name Conflict Resolution (returned in stats from save_season_data) from Pass 2
        assert worker.problems[2]["type"] == "Name Conflict Resolution"
        assert "A renamed to B" in worker.problems[2]["error"]

        # Issue 4: Database Write Failure (from save_movie_data exception) from Pass 2
        assert worker.problems[3]["type"] == "Database Write Failure"
        assert "DB Fail Movie" in worker.problems[3]["error"]

        # Issue 5: Unavailable Directory
        assert worker.problems[4]["type"] == "Unavailable Directory"
        assert "/unavailable/root" in worker.problems[4]["item"]

        # Verify logs were prefixed correctly
        log_warnings = [call.args[0] for call in mock_log.warning.call_args_list]
        assert any(
            "[SCAN_ISSUE] Type=Database Write Failure" in w for w in log_warnings
        )
        assert any("[SCAN_ISSUE] Type=Unavailable Directory" in w for w in log_warnings)

        log_infos = [call.args[0] for call in mock_log.info.call_args_list]
        report_logs = [log for log in log_infos if "[SCAN_REPORT]" in log]
        assert len(report_logs) > 0
        assert any("SCAN RUN ISSUES REPORT" in log for log in report_logs)
        assert any("Type: Name Conflict Resolution" in log for log in report_logs)
        assert any("Type: Database Write Failure" in log for log in report_logs)
        assert any("Type: Unavailable Directory" in log for log in report_logs)

    # 2. Test ScanAllLibrariesWorker reporting
    lib_all = LibraryDict({"Cosmos": {}})
    lib_all.unavailable_directories = ["/unavailable_all"]

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_library",
            side_effect=Exception("DB Fail Library Save"),
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            return_value=lib_all,
        ) as mock_scan_all,
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_season_data",
            side_effect=Exception("DB Fail Progressive Season"),
        ),
        patch("lan_streamer.backend.scan_worker_all.logger") as mock_log_all,
    ):
        mock_config.libraries = {
            "TV_Lib": {"paths": ["/unavailable_all"], "type": "tv"}
        }

        # Simulate callbacks being invoked during scanning
        def fake_scan_all(*args, **kwargs):
            season_cb = kwargs.get("season_callback")
            if season_cb:
                season_cb("Cosmos", {}, "Season 1", {})
            return lib_all

        mock_scan_all.side_effect = fake_scan_all

        worker_all = ScanAllLibrariesWorker()
        worker_all.run()

        # Check issues gathered
        assert len(worker_all.problems) == 5

        # 1. Progressive season save failure (Pass 1)
        assert worker_all.problems[0]["type"] == "Database Write Failure"
        assert "DB Fail Progressive Season" in worker_all.problems[0]["error"]

        # 2. Unavailable directory (Pass 1)
        assert worker_all.problems[1]["type"] == "Unavailable Directory"
        assert "/unavailable_all" in worker_all.problems[1]["item"]

        # 3. Library-wide save failure (Pass 1)
        assert worker_all.problems[2]["type"] == "Database Write Failure"
        assert "DB Fail Library Save" in worker_all.problems[2]["error"]

        # 4. Progressive season save failure (Pass 2)
        assert worker_all.problems[3]["type"] == "Database Write Failure"
        assert "DB Fail Progressive Season" in worker_all.problems[3]["error"]

        # 5. Library-wide save failure (Pass 2)
        assert worker_all.problems[4]["type"] == "Database Write Failure"
        assert "DB Fail Library Save" in worker_all.problems[4]["error"]

        # Verify prefixes in logs
        log_warnings_all = [
            call.args[0] for call in mock_log_all.warning.call_args_list
        ]
        assert any(
            "[SCAN_ISSUE] Type=Database Write Failure" in w for w in log_warnings_all
        )
        assert any(
            "[SCAN_ISSUE] Type=Unavailable Directory" in w for w in log_warnings_all
        )

        log_infos_all = [call.args[0] for call in mock_log_all.info.call_args_list]
        report_logs_all = [log for log in log_infos_all if "[SCAN_REPORT]" in log]
        assert len(report_logs_all) > 0
        assert any("SCAN RUN ISSUES REPORT" in log for log in report_logs_all)
