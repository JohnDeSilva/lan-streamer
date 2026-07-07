from unittest.mock import patch
from lan_streamer.backend import ScanAllLibrariesWorker
from lan_streamer.scanner.core import LibraryDict


def test_scan_all_libraries_discover_tree_movie(tmp_path) -> None:
    # 1. Test _discover_tree line 85 (movie library branch)
    movie_root = tmp_path / "movies"
    movie_root.mkdir()
    movie_dir = movie_root / "My Movie"
    movie_dir.mkdir()
    (movie_dir / "movie.mkv").write_bytes(b"\x00")

    with patch("lan_streamer.backend.scan_worker_all.config") as mock_config:
        mock_config.libraries = {
            "MovieLib": {"paths": [str(movie_root)], "type": "movie"},
        }
        import asyncio

        worker = ScanAllLibrariesWorker()
        tree = asyncio.run(worker._discover_tree({}))
        assert "MovieLib" in tree
        assert "My Movie" in tree["MovieLib"]["roots"][str(movie_root)]


def test_scan_all_libraries_callbacks_and_errors(tmp_path) -> None:
    # 2. Test callback branches and error branches
    tv_root = tmp_path / "tv"

    mock_db_stats = {
        "issues": [{"type": "DbIssue", "error": "mock error", "item": "test item"}],
        "season_id": "mock_season_1",
        "movie_id": "mock_movie_1",
        "series_added": 1,
        "movies_added": 1,
    }

    def fake_scan(*args, **kwargs):
        season_cb = kwargs.get("season_callback")
        movie_cb = kwargs.get("movie_callback")
        detail_cb = kwargs.get("detail_callback")

        if detail_cb:
            detail_cb("custom_event", {"info": "test"})

        if season_cb:
            season_cb("TestSeries", {}, "Season 1", {"_changed": True})

        if movie_cb:
            movie_cb("TestMovie", {"_changed": True})

        ld = LibraryDict({})
        ld.unavailable_directories = ["/nonexistent/root"]
        return ld

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=True,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.get_jellyfin_correlation_data",
            return_value={},
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch(
            "lan_streamer.backend.scan_worker_all.db.load_movie_library",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_season_data",
            return_value=mock_db_stats,
        ) as mock_save_season,
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_movie_data",
            return_value=mock_db_stats,
        ) as mock_save_movie_data,
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_library",
            return_value=mock_db_stats,
        ) as mock_save_lib,
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_movie_library",
            return_value=mock_db_stats,
        ) as mock_save_movie_lib,
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=fake_scan,
        ),
    ):
        mock_config.libraries = {
            "TVLib": {"paths": [str(tv_root)], "type": "tv"},
            "MovieLib": {
                "paths": [],
                "type": "movie",
            },  # paths empty to trigger "not root_directories" logic
        }

        worker = ScanAllLibrariesWorker(force_refresh=True)
        detail_payloads = []
        worker.detail_progress.connect(lambda ev, pl: detail_payloads.append((ev, pl)))

        worker.run()

        assert mock_save_season.call_count > 0
        assert mock_save_movie_data.call_count > 0
        assert mock_save_lib.call_count > 0
        assert mock_save_movie_lib.call_count > 0

        assert len(worker.problems) > 0
        assert "/nonexistent/root" in worker.unavailable_directories
        assert "mock_season_1" in worker.changed_season_ids
        assert "mock_movie_1" in worker.changed_movie_ids


def test_scan_all_libraries_database_exceptions() -> None:
    # 3. Test exception handling in callbacks
    def fake_scan_error(*args, **kwargs):
        season_cb = kwargs.get("season_callback")
        movie_cb = kwargs.get("movie_callback")
        if season_cb:
            season_cb("TestSeries", {}, "Season 1", {"_changed": True})
        if movie_cb:
            movie_cb("TestMovie", {"_changed": True})
        return LibraryDict({})

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch(
            "lan_streamer.backend.scan_worker_all.db.load_movie_library",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_season_data",
            side_effect=RuntimeError("db season error\nline2"),
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_movie_data",
            side_effect=RuntimeError("db movie error\nline2"),
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_library",
            side_effect=RuntimeError("db lib error\nline2"),
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_movie_library",
            side_effect=RuntimeError("db movie lib error\nline2"),
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=fake_scan_error,
        ),
    ):
        mock_config.libraries = {
            "TVLib": {"paths": ["/some/path"], "type": "tv"},
            "MovieLib": {"paths": [], "type": "movie"},
        }

        worker = ScanAllLibrariesWorker()
        worker.run()

        types = [p["type"] for p in worker.problems]
        assert "Database Write Failure" in types
        errors = [p["error"] for p in worker.problems]
        assert "db season error" in errors
        assert "db movie error" in errors
        assert "db lib error" in errors


def test_scan_all_libraries_pass2_exception_with_good_pass1() -> None:
    """Library that succeeds in Pass 1 but fails in Pass 2 emits library_error."""
    from lan_streamer.backend import ScanAllLibrariesWorker
    from lan_streamer.scanner.core import LibraryDict

    pass1_lib = LibraryDict({})
    pass1_lib.unavailable_directories = []

    call_count = [0]

    def _scan_side_effect(*args, **kwargs):
        call_count[0] += 1
        pass_number = kwargs.get("pass_number", 0)
        if pass_number == 1:
            return pass1_lib
        raise RuntimeError("Pass 2 failure")

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=_scan_side_effect,
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch("lan_streamer.backend.scan_worker_all.db.save_library"),
    ):
        mock_config.libraries = {
            "Lib1": {"paths": ["/tv"], "type": "tv"},
            "Lib2": {"paths": ["/tv2"], "type": "tv"},
        }

        library_error_events = []
        worker = ScanAllLibrariesWorker()
        worker.library_error.connect(
            lambda name, msg: library_error_events.append((name, msg))
        )
        worker.run()

        assert any(name == "Lib1" for name, _ in library_error_events)
        assert any(name == "Lib2" for name, _ in library_error_events)
        assert all("Pass 2 failure" in msg for _, msg in library_error_events)
        assert call_count[0] == 4  # 2 libs × 2 passes
