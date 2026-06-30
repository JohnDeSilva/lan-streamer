import asyncio
from unittest.mock import patch
from typing import Any, Callable, Dict, List

from PySide6.QtCore import Qt

from lan_streamer.backend import (
    CleanupWorker,
    ScanAllLibrariesWorker,
)


# ---------------------------------------------------------------------------
# Wait helper
# ---------------------------------------------------------------------------


async def _wait_until(
    condition: Callable[[], bool], timeout: float = 1.0, interval: float = 0.001
) -> None:
    """Wait until condition() returns True, raising TimeoutError otherwise."""
    for _ in range(int(timeout / interval)):
        if condition():
            return
        await asyncio.sleep(interval)
    raise TimeoutError(f"Condition not met within {timeout}s")


def test_cleanup_worker_execution() -> None:
    from lan_streamer.system.async_task_manager import AsyncTaskManager
    from PySide6.QtCore import QObject

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        parent = QObject()
        task_manager = AsyncTaskManager(parent=parent)

        # Successful run
        with patch(
            "lan_streamer.backend.scan_worker_cleanup.db.cleanup_library",
            return_value={"series": 1},
        ) as mock_clean:
            emitted_results: List[Dict[str, Any]] = []
            worker = CleanupWorker(
                "TestLib", ["/path"], async_task_manager=task_manager
            )
            worker.finished.connect(emitted_results.append)

            async def run_success():
                worker.start()
                await asyncio.sleep(0.01)  # brief yield for task startup
                worker.stop()
                await _wait_until(lambda: len(emitted_results) > 0)

            loop.run_until_complete(run_success())
            mock_clean.assert_called_once_with("TestLib", ["/path"])
            assert emitted_results == [{"series": 1}]

        # Exception run
        with patch(
            "lan_streamer.backend.scan_worker_cleanup.db.cleanup_library",
            side_effect=Exception("Cleanup error"),
        ):
            emitted_errors: List[str] = []
            worker = CleanupWorker(
                "TestLib", ["/path"], async_task_manager=task_manager
            )
            worker.error.connect(emitted_errors.append)

            async def run_fail():
                worker.start()
                await asyncio.sleep(0.01)  # brief yield for task startup
                worker.stop()
                await _wait_until(lambda: len(emitted_errors) > 0)

            loop.run_until_complete(run_fail())
            assert emitted_errors == ["Cleanup error"]
    finally:
        loop.close()


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


def test_scan_all_libraries_worker_reporting() -> None:
    from lan_streamer.scanner import LibraryDict

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
            "lan_streamer.backend.scan_worker_all.AsyncDatabaseWriter"
        ) as mock_writer_class,
    ):
        mock_config.libraries = {"TVLib": {"paths": ["/tv"], "type": "tv"}}
        mock_scan.return_value = {}

        worker = ScanAllLibrariesWorker()

        # Simulate interruption requested
        worker.isInterruptionRequested = MagicMock(return_value=True)

        finished_mock = MagicMock()
        worker.finished.connect(finished_mock)

        worker.run()

        # Write task should not be submitted to writer
        mock_writer_instance = mock_writer_class.return_value
        mock_writer_instance.submit.assert_not_called()
        mock_writer_instance.sync_submit.assert_not_called()
