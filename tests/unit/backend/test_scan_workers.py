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
            "lan_streamer.backend.scan_worker_single._discover_single_library_tree_impl",
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
            "lan_streamer.backend.scan_worker_single._discover_single_library_tree_impl",
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


def test_scan_worker_stats_reporting() -> None:
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = []

    with (
        patch(
            "lan_streamer.backend.scan_worker_single._discover_single_library_tree_impl",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.scan_worker_single.db.save_season_data",
            return_value={"series_added": 1, "seasons_added": 1, "episodes_added": 5},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.db.save_movie_data",
            return_value={"movies_added": 2},
        ),
        patch("lan_streamer.backend.scan_worker_single.logger") as mock_log,
    ):

        def fake_scan(*args, **kwargs):
            season_cb = kwargs.get("season_callback")
            if season_cb:
                season_cb("Cosmos", {}, "Season 1", {})
            movie_cb = kwargs.get("movie_callback")
            if movie_cb:
                movie_cb("Inception", {})
            return lib

        mock_scan.side_effect = fake_scan

        worker = ScanWorker(["/path"], "tv", {}, library_name="TV_Lib")
        worker.run()

        # Check stats were accumulated
        assert worker.stats["series_added"] == 2
        assert worker.stats["seasons_added"] == 2
        assert worker.stats["episodes_added"] == 10
        assert worker.stats["movies_added"] == 4

        # Check logs contain SCAN_REPORT stats
        log_infos = [call.args[0] for call in mock_log.info.call_args_list]
        report_logs = [log for log in log_infos if "[SCAN_REPORT]" in log]
        assert len(report_logs) > 0
        assert any("Series: Scanned=2 | Added=2" in log for log in report_logs)
        assert any("Seasons: Scanned=2 | Added=2" in log for log in report_logs)
        assert any("Episodes: Scanned=0 | Added=10" in log for log in report_logs)
        assert any("Movies: Scanned=2 | Added=4" in log for log in report_logs)

        # Verify each entity type appears in ALL three sections
        section_entities: dict[str, dict[str, int]] = {
            s: {"Series": 0, "Seasons": 0, "Episodes": 0, "Movies": 0}
            for s in ("PASS 1", "PASS 2", "TOTAL")
        }
        current_section: str | None = None
        for log in report_logs:
            if "PASS 1: OFFLINE FILE DISCOVERY BREAKDOWN" in log:
                current_section = "PASS 1"
            elif "PASS 2: ONLINE METADATA RESOLUTION BREAKDOWN" in log:
                current_section = "PASS 2"
            elif "TOTAL ACCUMULATED RUN STATS" in log:
                current_section = "TOTAL"
            elif "Series: Scanned" in log and current_section:
                section_entities[current_section]["Series"] += 1
            elif "Seasons: Scanned" in log and current_section:
                section_entities[current_section]["Seasons"] += 1
            elif "Episodes: Scanned" in log and current_section:
                section_entities[current_section]["Episodes"] += 1
            elif "Movies: Scanned" in log and current_section:
                section_entities[current_section]["Movies"] += 1
        for section in ("PASS 1", "PASS 2", "TOTAL"):
            for entity in ("Series", "Seasons", "Episodes", "Movies"):
                assert section_entities[section][entity] == 1, (
                    f"{section} has {section_entities[section][entity]} {entity} lines (expected 1)"
                )


def test_scan_all_libraries_worker_stats_reporting() -> None:
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = []

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_season_data",
            return_value={"series_added": 2, "seasons_added": 3, "episodes_added": 12},
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_library",
            return_value={"series_removed": 1, "seasons_removed": 1},
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            return_value=lib,
        ) as mock_scan_all,
        patch("lan_streamer.backend.scan_worker_all.logger") as mock_log,
    ):
        mock_config.libraries = {"TV_Lib": {"paths": ["/path"], "type": "tv"}}

        def fake_scan(*args, **kwargs):
            season_cb = kwargs.get("season_callback")
            if season_cb:
                season_cb("Cosmos", {}, "Season 1", {})
            return lib

        mock_scan_all.side_effect = fake_scan

        worker = ScanAllLibrariesWorker()
        worker.run()

        # Check stats were accumulated
        assert worker.stats["series_added"] == 4
        assert worker.stats["seasons_added"] == 6
        assert worker.stats["episodes_added"] == 24
        assert worker.stats["series_removed"] == 2
        assert worker.stats["seasons_removed"] == 2

        # Check logs contain SCAN_REPORT stats
        log_infos = [call.args[0] for call in mock_log.info.call_args_list]
        report_logs = [log for log in log_infos if "[SCAN_REPORT]" in log]
        assert len(report_logs) > 0
        assert any(
            "Series: Scanned=2 | Added=4 | Updated=0 | Removed=2" in log
            for log in report_logs
        )
        assert any(
            "Seasons: Scanned=2 | Added=6 | Updated=0 | Removed=2" in log
            for log in report_logs
        )
        assert any(
            "Episodes: Scanned=0 | Added=24 | Updated=0 | Removed=0" in log
            for log in report_logs
        )


def test_scan_worker_formats_multiline_database_error_cleanly() -> None:
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = []

    multiline_err = (
        "(sqlite3.IntegrityError) UNIQUE constraint failed: episodes.season_id, episodes.name\n"
        "[SQL: UPDATE episodes SET name=? WHERE id = ?]\n"
        "[parameters: ('Canada Drag Race', 4)]"
    )

    with (
        patch(
            "lan_streamer.backend.scan_worker_single._discover_single_library_tree_impl",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.scan_worker_single.db.save_season_data",
            side_effect=Exception(multiline_err),
        ),
        patch("lan_streamer.backend.scan_worker_single.logger") as mock_log,
    ):

        def fake_scan(*args, **kwargs):
            season_cb = kwargs.get("season_callback")
            if season_cb:
                season_cb("Cosmos", {}, "Season 1", {})
            return lib

        mock_scan.side_effect = fake_scan

        worker = ScanWorker(["/path"], "tv", {}, library_name="TV_Lib")
        worker.run()

        # It should record only the first line of the error in problems list (twice, once per pass)
        assert len(worker.problems) == 2
        for prob in worker.problems:
            assert prob["type"] == "Database Write Failure"
            assert (
                prob["error"]
                == "(sqlite3.IntegrityError) UNIQUE constraint failed: episodes.season_id, episodes.name"
            )

        # It should log the detailed block at debug level
        log_debugs = [call.args[0] for call in mock_log.debug.call_args_list]
        assert any("Database write failure detailed error" in d for d in log_debugs)

        # It should log warnings with the clean first-line message
        log_warnings = [call.args[0] for call in mock_log.warning.call_args_list]
        assert any(
            "[SCAN_ISSUE] Type=Database Write Failure" in w for w in log_warnings
        )
        assert not any("[SQL:" in w for w in log_warnings)


def test_detailed_scan_report_counts_validation() -> None:
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = []

    # Mock discover tree impl and scan_directories
    with (
        patch(
            "lan_streamer.backend.scan_worker_single._discover_single_library_tree_impl",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.scan_worker_single.db.save_season_data"
        ) as mock_save_season,
        patch(
            "lan_streamer.backend.scan_worker_single.db.save_movie_data"
        ) as mock_save_movie,
        patch("lan_streamer.backend.scan_worker_single.logger") as mock_log,
    ):
        # Stats returned by DB calls:
        # Pass 1: 1 series added, 1 season added, 5 episodes added, 1 episode updated.
        # Pass 2: 1 series updated, 1 season updated, 3 episodes updated.
        # Movies: Pass 1: 1 movie added. Pass 2: 1 movie updated.
        mock_save_season.side_effect = [
            # Pass 1 callback
            {
                "series_added": 1,
                "seasons_added": 1,
                "episodes_added": 5,
                "episodes_updated": 1,
            },
            # Pass 2 callback
            {
                "series_updated": 1,
                "seasons_updated": 1,
                "episodes_updated": 3,
            },
        ]
        mock_save_movie.side_effect = [
            # Pass 1 callback
            {"movies_added": 1},
            # Pass 2 callback
            {"movies_updated": 1},
        ]

        def fake_scan(*args, **kwargs):
            # Pass 1 will have changed=True
            # Pass 2 will have changed=False (skipped)
            offline = kwargs.get("offline", True)
            season_cb = kwargs.get("season_callback")
            movie_cb = kwargs.get("movie_callback")

            if season_cb:
                # Season 1 has 6 episodes
                season_data = {
                    "episodes": [{"path": f"ep{i}.mp4"} for i in range(6)],
                    "_changed": offline,  # Changed in Pass 1, unchanged (skipped) in Pass 2
                }
                season_cb(
                    "Cosmos",
                    {"seasons": {"Season 1": season_data}},
                    "Season 1",
                    season_data,
                )

            if movie_cb:
                movie_data = {
                    "path": "movie.mp4",
                    "_changed": offline,
                }
                movie_cb("Inception", movie_data)
            return lib

        mock_scan.side_effect = fake_scan

        worker = ScanWorker(["/path"], "tv", {}, library_name="TV_Lib")
        worker.run()

        # Check total accumulated stats
        assert worker.stats["series_scanned"] == 2
        assert worker.stats["series_added"] == 1
        assert worker.stats["series_updated"] == 1
        assert worker.stats["series_skipped"] == 1

        assert worker.stats["seasons_scanned"] == 2
        assert worker.stats["seasons_added"] == 1
        assert worker.stats["seasons_updated"] == 1
        assert worker.stats["seasons_skipped"] == 1

        assert worker.stats["episodes_scanned"] == 12
        assert worker.stats["episodes_added"] == 5
        assert worker.stats["episodes_updated"] == 4
        assert worker.stats["episodes_skipped"] == 6

        assert worker.stats["movies_scanned"] == 2
        assert worker.stats["movies_added"] == 1
        assert worker.stats["movies_updated"] == 1
        assert worker.stats["movies_skipped"] == 1

        # Check Pass 1 stats
        p1 = worker.pass1_stats
        assert p1["series_scanned"] == 1
        assert p1["series_added"] == 1
        assert p1["series_skipped"] == 0
        assert p1["seasons_scanned"] == 1
        assert p1["seasons_added"] == 1
        assert p1["seasons_skipped"] == 0
        assert p1["episodes_scanned"] == 6
        assert p1["episodes_added"] == 5
        assert p1["episodes_updated"] == 1
        assert p1["episodes_skipped"] == 0
        assert p1["movies_scanned"] == 1
        assert p1["movies_added"] == 1
        assert p1["movies_skipped"] == 0

        # Check Pass 2 stats
        p2 = worker.pass2_stats
        assert p2["series_scanned"] == 1
        assert p2["series_added"] == 0
        assert p2["series_updated"] == 1
        assert p2["series_skipped"] == 1
        assert p2["seasons_scanned"] == 1
        assert p2["seasons_added"] == 0
        assert p2["seasons_updated"] == 1
        assert p2["seasons_skipped"] == 1
        assert p2["episodes_scanned"] == 6
        assert p2["episodes_added"] == 0
        assert p2["episodes_updated"] == 3
        assert p2["episodes_skipped"] == 6
        assert p2["movies_scanned"] == 1
        assert p2["movies_added"] == 0
        assert p2["movies_updated"] == 1
        assert p2["movies_skipped"] == 1

        # Verify logger messages
        log_infos = [call.args[0] for call in mock_log.info.call_args_list]
        report_logs = [log for log in log_infos if "[SCAN_REPORT]" in log]
        assert len(report_logs) > 0
        assert any(
            "Series: Scanned=2 | Added=1 | Updated=1 | Removed=0 | Skipped=1" in log
            for log in report_logs
        )


def test_scan_worker_db_stats_no_double_counting() -> None:
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = []

    with (
        patch(
            "lan_streamer.backend.scan_worker_single._discover_single_library_tree_impl",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.scan_worker_single.db.save_season_data"
        ) as mock_save_season,
        patch(
            "lan_streamer.backend.scan_worker_single.db.save_movie_data"
        ) as mock_save_movie,
        patch("lan_streamer.backend.scan_worker_single.logger"),
    ):
        mock_save_season.return_value = {
            "series_scanned": 1,
            "seasons_scanned": 1,
            "episodes_scanned": 6,
            "series_added": 1,
            "seasons_added": 1,
            "episodes_added": 5,
        }
        mock_save_movie.return_value = {
            "movies_scanned": 1,
            "movies_added": 1,
        }

        def fake_scan(*args, **kwargs):
            season_cb = kwargs.get("season_callback")
            movie_cb = kwargs.get("movie_callback")

            if season_cb:
                season_data = {
                    "episodes": [{"path": f"ep{i}.mp4"} for i in range(6)],
                    "_changed": True,
                }
                season_cb(
                    "Cosmos",
                    {"seasons": {"Season 1": season_data}},
                    "Season 1",
                    season_data,
                )

            if movie_cb:
                movie_cb("Inception", {"path": "movie.mp4", "_changed": True})
            return lib

        mock_scan.side_effect = fake_scan

        worker = ScanWorker(["/path"], "tv", {}, library_name="TV_Lib")
        worker.run()

        # Check total accumulated stats (should NOT double count despite DB returning scanned/skipped keys)
        assert worker.stats["episodes_scanned"] == 12
        assert worker.stats["series_scanned"] == 2
        assert worker.stats["seasons_scanned"] == 2
        assert worker.stats["movies_scanned"] == 2
