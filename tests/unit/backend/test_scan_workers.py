from unittest.mock import patch
from typing import List, Dict, Any

from PySide6.QtCore import Qt

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

    def _scan_side_effect(*args, **kwargs):
        existing = kwargs.get("existing_library", {})
        if existing == {"old_tv": {}}:
            ld = LibraryDict({"new_data": {}})
            ld.unavailable_directories = ["/unavailable_tv"]
            return ld
        ld = LibraryDict({"new_data": {}})
        ld.unavailable_directories = ["/unavailable_movie"]
        return ld

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
            side_effect=_scan_side_effect,
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
        batch_emitted: List[List[Dict[str, Any]]] = []
        finished_emitted: List[bool] = []

        worker = ScanAllLibrariesWorker(force_refresh=True)
        worker.library_progress.connect(
            lambda name, comp, tot: progress_emitted.append((name, comp, tot)),
            Qt.DirectConnection,
        )
        worker.detail_progress_batch.connect(
            lambda batch: batch_emitted.append(batch),
            Qt.DirectConnection,
        )
        worker.finished.connect(
            lambda: finished_emitted.append(True),
            Qt.DirectConnection,
        )
        worker.run()

        assert len(mock_scan.call_args_list) == 4
        assert mock_save_tv.call_count == 2
        assert mock_save_movie.call_count == 2
        assert len(progress_emitted) == 2
        libraries_in_progress = {p[0] for p in progress_emitted}
        assert libraries_in_progress == {"TV_Lib", "Movie_Lib"}
        all_total_2 = all(p[2] == 2 for p in progress_emitted)
        assert all_total_2
        assert finished_emitted == [True]
        assert sorted(worker.unavailable_directories) == [
            "/unavailable_movie",
            "/unavailable_tv",
        ]
        # Check batch emissions contain expected events
        flat_events = [event for batch in batch_emitted for event in batch]
        # Each event is a dict with 'event' and 'payload' keys
        event_pairs = [(e["event"], e["payload"]) for e in flat_events]
        assert (
            "start_root",
            {"library": "TV_Lib", "root": "/tv_path"},
        ) in event_pairs
        assert (
            "finish_root",
            {"library": "TV_Lib", "root": "/tv_path"},
        ) in event_pairs
        assert (
            "start_root",
            {"library": "Movie_Lib", "root": "/movie_path"},
        ) in event_pairs
        assert (
            "finish_root",
            {"library": "Movie_Lib", "root": "/movie_path"},
        ) in event_pairs

    # Per-library exception run — task-level failures emit library_error
    with patch("lan_streamer.backend.scan_worker_all.config") as mock_config:
        mock_config.libraries = {"TV_Lib": {"paths": [], "type": "tv"}}
        with patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=Exception("Scan error"),
        ):
            library_errors_emitted: List[tuple] = []
            worker = ScanAllLibrariesWorker()
            worker.library_error.connect(
                lambda lib, msg: library_errors_emitted.append((lib, msg)),
                Qt.DirectConnection,
            )
            worker.run()
            assert len(library_errors_emitted) == 1
            assert library_errors_emitted[0][0] == "TV_Lib"
            assert "Scan error" in library_errors_emitted[0][1]


def test_scan_worker_detail_progress() -> None:
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = []

    # Mock discover_single_library_tree to return custom structure
    mock_tree = {"/path": ["Series A", "Series B"]}

    with (
        patch(
            "lan_streamer.backend.scan_worker_single.discover_single_library_tree_impl",
            return_value=mock_tree,
        ) as mock_discover,
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
    ):
        emitted_batches = []
        worker = ScanWorker(["/path"], "tv", {})
        worker.detail_progress_batch.connect(
            lambda batch: emitted_batches.append(batch)
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

        mock_discover.assert_called_once_with(["/path"], "tv", {})
        assert mock_scan.call_count == 2

        # Verify the progress signals emitted via batch
        flat_events = [event for batch in emitted_batches for event in batch]
        # Each event is a dict with 'event' and 'payload' keys
        event_pairs = [(e["event"], e["payload"]) for e in flat_events]
        assert len(event_pairs) == 7
        assert event_pairs[0] == (
            "init_library_scan",
            {"roots": mock_tree, "roots_order": ["/path"]},
        )
        assert event_pairs[1] == ("start_offline_scan", {"library": ""})
        assert event_pairs[2] == (
            "start_folder",
            {"root": "/path", "folder": "Series A"},
        )
        assert event_pairs[3] == (
            "finish_folder",
            {"root": "/path", "folder": "Series A", "skipped": False},
        )
        assert event_pairs[4] == ("start_metadata_resolution", {"library": ""})
        assert event_pairs[5] == (
            "start_folder",
            {"root": "/path", "folder": "Series A"},
        )
        assert event_pairs[6] == (
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
            "lan_streamer.backend.scan_worker_single.discover_single_library_tree_impl",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.database_writer.database_module.save_season_data"
        ) as mock_save_season,
        patch(
            "lan_streamer.backend.database_writer.database_module.save_movie_data",
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
            "lan_streamer.backend.scan_worker_single.discover_single_library_tree_impl",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.database_writer.database_module.save_season_data",
            return_value={"series_added": 1, "seasons_added": 1, "episodes_added": 5},
        ),
        patch(
            "lan_streamer.backend.database_writer.database_module.save_movie_data",
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
        assert any("Series: Scanned=1 | Added=2" in log for log in report_logs)
        assert any("Seasons: Scanned=2 | Added=2" in log for log in report_logs)
        assert any("Episodes: Scanned=0 | Added=10" in log for log in report_logs)
        assert any("Movies: Scanned=1 | Added=4" in log for log in report_logs)

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
            "lan_streamer.backend.database_writer.database_module.save_season_data",
            return_value={"series_added": 2, "seasons_added": 3, "episodes_added": 12},
        ),
        patch(
            "lan_streamer.backend.database_writer.database_module.save_library",
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
        # With unique tracking, series scanned across both passes = 1 (unique),
        # not 2 (sum of passes). The test was written for old double-counting behavior.
        assert any(
            "Series: Scanned=1 | Added=4 | Updated=0 | Removed=2" in log
            for log in report_logs
        )
        assert any(
            "Seasons: Scanned=1 | Added=6 | Updated=0 | Removed=2" in log
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
            "lan_streamer.backend.scan_worker_single.discover_single_library_tree_impl",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.database_writer.database_module.save_season_data",
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
            "lan_streamer.backend.scan_worker_single.discover_single_library_tree_impl",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.database_writer.database_module.save_season_data"
        ) as mock_save_season,
        patch(
            "lan_streamer.backend.database_writer.database_module.save_movie_data"
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
        assert worker.stats["series_scanned"] == 1
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

        assert worker.stats["movies_scanned"] == 1
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
            "Series: Scanned=1 | Added=1 | Updated=1 | Removed=0 | Skipped=1" in log
            for log in report_logs
        )


def test_scan_worker_db_stats_no_double_counting() -> None:
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = []

    with (
        patch(
            "lan_streamer.backend.scan_worker_single.discover_single_library_tree_impl",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.database_writer.database_module.save_season_data"
        ) as mock_save_season,
        patch(
            "lan_streamer.backend.database_writer.database_module.save_movie_data"
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
        assert worker.stats["series_scanned"] == 1
        assert worker.stats["seasons_scanned"] == 2
        assert worker.stats["movies_scanned"] == 1


def test_scan_worker_changed_ids_in_callbacks() -> None:
    """ScanWorker callbacks populate changed_season_ids and changed_movie_ids."""
    from lan_streamer.scanner import LibraryDict

    lib = LibraryDict({"Cosmos": {}})
    lib.unavailable_directories = []

    with (
        patch(
            "lan_streamer.backend.scan_worker_single.discover_single_library_tree_impl",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories", return_value=lib
        ) as mock_scan,
        patch(
            "lan_streamer.backend.database_writer.database_module.save_season_data",
            return_value={
                "season_id": "sid_1",
                "series_added": 1,
                "seasons_added": 1,
                "episodes_added": 3,
            },
        ),
        patch(
            "lan_streamer.backend.database_writer.database_module.save_movie_data",
            return_value={"movie_id": "mid_1", "movies_added": 1},
        ),
        patch("lan_streamer.backend.scan_worker_single.logger"),
    ):

        def fake_scan(*args, **kwargs):
            offline = kwargs.get("offline", True)
            season_cb = kwargs.get("season_callback")
            movie_cb = kwargs.get("movie_callback")
            if season_cb:
                season_cb(
                    "Cosmos",
                    {"seasons": {"Season 1": {"episodes": [{}], "_changed": True}}},
                    "Season 1",
                    {"episodes": [{"path": "ep1.mp4"}], "_changed": offline},
                )
            if movie_cb:
                movie_cb("Inception", {"path": "movie.mp4", "_changed": offline})
            return lib

        mock_scan.side_effect = fake_scan

        worker = ScanWorker(["/path"], "tv", {}, library_name="TV_Lib")
        worker.run()

        assert "sid_1" in worker.changed_season_ids
        assert "mid_1" in worker.changed_movie_ids


def test_scan_all_libraries_pass2_only() -> None:
    """ScanAllLibrariesWorker with run_pass1=False skips offline pass."""
    from lan_streamer.scanner import LibraryDict

    empty_lib = LibraryDict({})
    empty_lib.unavailable_directories = []

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            return_value=empty_lib,
        ) as mock_scan,
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch("lan_streamer.backend.scan_worker_all.db.save_library"),
    ):
        mock_config.libraries = {
            "Lib1": {"paths": ["/tv"], "type": "tv"},
        }

        finished = []
        worker = ScanAllLibrariesWorker(run_pass1=False, run_pass2=True)
        worker.finished.connect(lambda: finished.append(True))
        worker.run()

        assert finished == [True]
        assert mock_scan.call_count == 1  # only Pass 2


def test_scan_all_libraries_pass1_only() -> None:
    """ScanAllLibrariesWorker with run_pass2=False skips metadata pass."""
    from lan_streamer.scanner import LibraryDict

    empty_lib = LibraryDict({})
    empty_lib.unavailable_directories = []

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            return_value=empty_lib,
        ) as mock_scan,
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch("lan_streamer.backend.scan_worker_all.db.save_library"),
    ):
        mock_config.libraries = {
            "Lib1": {"paths": ["/tv"], "type": "tv"},
        }

        finished = []
        worker = ScanAllLibrariesWorker(run_pass1=True, run_pass2=False)
        worker.finished.connect(lambda: finished.append(True))
        worker.run()

        assert finished == [True]
        assert mock_scan.call_count == 1  # only Pass 1


def test_scan_all_libraries_both_passes_disabled() -> None:
    """ScanAllLibrariesWorker with both passes disabled still finishes."""
    from lan_streamer.scanner import LibraryDict

    empty_lib = LibraryDict({})
    empty_lib.unavailable_directories = []

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            return_value=empty_lib,
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch("lan_streamer.backend.scan_worker_all.db.save_library"),
    ):
        mock_config.libraries = {
            "Lib1": {"paths": ["/tv"], "type": "tv"},
        }

        finished = []
        worker = ScanAllLibrariesWorker(run_pass1=False, run_pass2=False)
        worker.finished.connect(lambda: finished.append(True))
        worker.run()

        assert finished == [True]


def test_scan_all_libraries_worker_zero_libraries() -> None:
    """ScanAllLibrariesWorker handles empty library configuration gracefully."""
    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library"),
    ):
        mock_config.libraries = {}

        detail_events = []
        worker = ScanAllLibrariesWorker()
        worker.detail_progress_batch.connect(
            lambda batch: [detail_events.append(e["event"]) for e in batch]
        )
        worker.run()

        assert "init_tree" in detail_events
        # All stats should remain zeroed since there are no libraries to scan
        assert all(v == 0 for v in worker.stats.values())


def test_scan_all_libraries_unavailable_dir_dedup() -> None:
    """Duplicate unavailable directories across libraries are not duplicated."""
    from lan_streamer.scanner import LibraryDict

    def _make_lib(unavailable_dirs):
        ld = LibraryDict({})
        ld.unavailable_directories = unavailable_dirs
        return ld

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=[
                _make_lib(["/missing/path"]),
                _make_lib(["/missing/path"]),
            ],
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch(
            "lan_streamer.backend.scan_worker_all.db.load_movie_library",
            return_value={},
        ),
        patch("lan_streamer.backend.scan_worker_all.db.save_library"),
        patch("lan_streamer.backend.scan_worker_all.db.save_movie_library"),
    ):
        mock_config.libraries = {
            "TVLib": {"paths": ["/tv"], "type": "tv"},
            "MovieLib": {"paths": ["/movies"], "type": "movie"},
        }

        worker = ScanAllLibrariesWorker(run_pass2=False)
        worker.run()

        assert worker.unavailable_directories == ["/missing/path"]


def test_scan_worker_cancellation() -> None:
    """Verify that ScanWorker exits early on interruption request and does not emit finished."""
    from unittest.mock import patch, MagicMock
    from lan_streamer.backend.scan_worker_single import ScanWorker

    with (
        patch("lan_streamer.backend.scan_worker_single.config"),
        patch("lan_streamer.backend.scan_worker_single.jellyfin_client"),
        patch("lan_streamer.backend.scan_worker_single.scan_directories") as mock_scan,
        patch("lan_streamer.backend.scan_worker_single.DatabaseWriterThread"),
    ):
        mock_scan.return_value = {}
        worker = ScanWorker(["/path"], "tv", {}, library_name="TV_Lib")

        # Simulate interruption requested
        worker.isInterruptionRequested = MagicMock(return_value=True)

        finished_mock = MagicMock()
        worker.finished.connect(finished_mock)

        worker.run()

        # Finished signal should NOT be emitted
        finished_mock.assert_not_called()


def test_scan_all_libraries_worker_cancellation() -> None:
    """Verify that ScanAllLibrariesWorker aborts early on interruption request and does not save."""
    from unittest.mock import patch, MagicMock
    from lan_streamer.backend.scan_worker_all import ScanAllLibrariesWorker

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch("lan_streamer.backend.scan_worker_all.jellyfin_client"),
        patch("lan_streamer.backend.scan_worker_all.scan_directories") as mock_scan,
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch(
            "lan_streamer.backend.scan_worker_all.db.load_movie_library",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.DatabaseWriteTask"
        ) as mock_write_task,
        patch("lan_streamer.backend.scan_worker_all.DatabaseWriterThread"),
    ):
        mock_config.libraries = {"TVLib": {"paths": ["/tv"], "type": "tv"}}
        mock_scan.return_value = {}

        worker = ScanAllLibrariesWorker()

        # Simulate interruption requested
        worker.isInterruptionRequested = MagicMock(return_value=True)

        finished_mock = MagicMock()
        worker.finished.connect(finished_mock)

        worker.run()

        # Write task should not be posted to queue (so save was skipped)
        mock_write_task.assert_not_called()
