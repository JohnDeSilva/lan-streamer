"""
Additional targeted tests for:
 - backend/scan_workers.py – ScanAllLibrariesWorker.run() with root_dir loop (lines 186-216, 264-265, 288)
 - backend/scan_workers.py – ScanWorker.run() Jellyfin configured branch (line 97)
 - backend/scan_workers.py – CleanupWorker.run() both success and error paths
 - backend/scan_workers.py – ScanAllLibrariesWorker._discover_tree() branches
 - db/connection.py – init_db frozen path (line 112) and mkdir failure (lines 103-105)
                       and alembic failure path (lines 133-135)
 - db/queries.py – remaining lines: corrupt audio/subtitle JSON (lines 37-44),
                   get_next_episode last-episode path, get_next_episode missing current
 - scanner/core.py – scan_directories existing_library merge/preserve paths
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# backend/scan_workers.py – ScanAllLibrariesWorker with root_dirs loop
# ---------------------------------------------------------------------------


def _empty_lib_dict():
    """Returns a scanner LibraryDict with no unavailable dirs."""
    from lan_streamer.scanner.core import LibraryDict

    ld = LibraryDict({})
    ld.unavailable_directories = []
    return ld


def test_scan_all_libraries_worker_with_root_dirs(tmp_path) -> None:
    """ScanAllLibrariesWorker scans root dirs one by one (the else branch, lines 291-320)."""
    from lan_streamer.backend import ScanAllLibrariesWorker

    root_dir = str(tmp_path / "tv")

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            return_value=_empty_lib_dict(),
        ) as mock_scan,
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch("lan_streamer.backend.scan_worker_all.db.save_library") as mock_save,
    ):
        mock_config.libraries = {
            "TVLib": {"paths": [root_dir], "type": "tv", "show_future_episodes": True},
        }

        # Capture emitted signals
        detail_events = []
        progress_events = []
        finished = []

        worker = ScanAllLibrariesWorker()
        worker.detail_progress.connect(lambda ev, pl: detail_events.append(ev))
        worker.library_progress.connect(
            lambda lib, done, total: progress_events.append((lib, done, total))
        )
        worker.finished.connect(lambda: finished.append(True))
        worker.run()

        assert finished == [True]
        # scan_directories called once per root_dir
        assert mock_scan.call_count == 2
        assert mock_save.call_count == 2
        assert "start_root" in detail_events
        assert "finish_root" in detail_events
        assert "finish_library" in detail_events
        assert ("TVLib", 1, 1) in progress_events


def test_scan_all_libraries_worker_with_root_dirs_movie(tmp_path) -> None:
    """When library type is 'movie' and has root dirs, saves via save_movie_library."""
    from lan_streamer.backend import ScanAllLibrariesWorker

    root_dir = str(tmp_path / "movies")

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            return_value=_empty_lib_dict(),
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.load_movie_library",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_movie_library"
        ) as mock_save_movie,
    ):
        mock_config.libraries = {
            "Movies": {"paths": [root_dir], "type": "movie"},
        }

        finished = []
        worker = ScanAllLibrariesWorker()
        worker.finished.connect(lambda: finished.append(True))
        worker.run()

        assert finished == [True]
        assert mock_save_movie.call_count == 2


def test_scan_all_libraries_worker_with_jellyfin(tmp_path) -> None:
    """When jellyfin is configured, get_jellyfin_correlation_data is called."""
    from lan_streamer.backend import ScanAllLibrariesWorker

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=True,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.get_jellyfin_correlation_data",
            return_value={"path_map": {}},
        ) as mock_jf,
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            return_value=_empty_lib_dict(),
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch("lan_streamer.backend.scan_worker_all.db.save_library"),
    ):
        mock_config.libraries = {
            "TVLib": {"paths": [], "type": "tv"},
        }

        finished = []
        worker = ScanAllLibrariesWorker()
        worker.finished.connect(lambda: finished.append(True))
        worker.run()

        assert finished == [True]
        mock_jf.assert_called_once()


def test_scan_all_libraries_worker_error() -> None:
    """ScanAllLibrariesWorker emits error signal on exception."""
    from lan_streamer.backend import ScanAllLibrariesWorker

    with patch("lan_streamer.backend.scan_worker_all.config") as mock_config:
        mock_config.libraries = {"Bad": {"paths": [], "type": "tv"}}
        with patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=RuntimeError("Scan failed"),
        ):
            errors = []
            worker = ScanAllLibrariesWorker()
            worker.error.connect(errors.append)
            worker.run()

            assert len(errors) == 1
            assert "Scan failed" in errors[0]


def test_scan_worker_with_jellyfin() -> None:
    """ScanWorker fetches Jellyfin data when configured (line 97)."""
    from lan_streamer.backend import ScanWorker

    with (
        patch(
            "lan_streamer.backend.scan_worker_single.jellyfin_client.is_configured",
            return_value=True,
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.jellyfin_client.get_jellyfin_correlation_data",
            return_value={"path_map": {}},
        ) as mock_jf,
        patch(
            "lan_streamer.backend.scan_worker_single._discover_single_library_tree_impl",
            return_value={"/root": []},
        ),
        patch(
            "lan_streamer.backend.scan_worker_single.scan_directories",
            return_value=_empty_lib_dict(),
        ),
        patch("lan_streamer.backend.scan_worker_single.config") as mock_config,
    ):
        mock_config.libraries = {
            "Lib": {"paths": ["/root"], "type": "tv", "show_future_episodes": True}
        }

        finished = []
        worker = ScanWorker(
            root_directories=["/root"],
            library_type="tv",
            existing_library={},
            library_name="Lib",
        )
        worker.finished.connect(finished.append)
        worker.run()

        assert len(finished) == 1
        mock_jf.assert_called_once()


def test_cleanup_worker_success() -> None:
    """CleanupWorker emits finished with cleanup results."""
    from lan_streamer.backend.scan_worker_cleanup import CleanupWorker

    with patch(
        "lan_streamer.backend.scan_worker_cleanup.db.cleanup_library",
        return_value={"removed": 2},
    ) as mock_cleanup:
        finished = []
        worker = CleanupWorker("TestLib", ["/root"])
        worker.finished.connect(finished.append)
        worker.run()

        assert finished == [{"removed": 2}]
        mock_cleanup.assert_called_once_with("TestLib", ["/root"])


def test_cleanup_worker_error() -> None:
    """CleanupWorker emits error on exception."""
    from lan_streamer.backend.scan_worker_cleanup import CleanupWorker

    with patch(
        "lan_streamer.backend.scan_worker_cleanup.db.cleanup_library",
        side_effect=RuntimeError("cleanup failed"),
    ):
        errors = []
        worker = CleanupWorker("TestLib", ["/root"])
        worker.error.connect(errors.append)
        worker.run()

        assert len(errors) == 1
        assert "cleanup failed" in errors[0]


def test_scan_all_libraries_worker_discover_tree(tmp_path) -> None:
    """_discover_tree correctly categorizes TV and movie libraries."""
    from lan_streamer.backend import ScanAllLibrariesWorker

    tv_root = tmp_path / "tv"
    tv_root.mkdir()
    series_dir = tv_root / "My Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "ep1.mkv").write_bytes(b"\x00")

    with patch("lan_streamer.backend.scan_worker_all.config") as mock_config:
        mock_config.libraries = {
            "TVLib": {"paths": [str(tv_root)], "type": "tv"},
        }
        worker = ScanAllLibrariesWorker()
        tree = worker._discover_tree()

    assert "TVLib" in tree
    assert str(tv_root) in tree["TVLib"]["roots"]
    # My Show folder should be in the tree
    assert "My Show" in tree["TVLib"]["roots"][str(tv_root)]
    # Season 1 should be listed
    seasons = tree["TVLib"]["roots"][str(tv_root)]["My Show"].get("seasons", {})
    assert "Season 1" in seasons


# ---------------------------------------------------------------------------
# db/connection.py – init_db edge cases
# ---------------------------------------------------------------------------


def test_init_db_mkdir_failure(tmp_path) -> None:
    """When mkdir fails, init_db returns False."""
    import lan_streamer.db as db_module
    from lan_streamer.db.connection import init_db

    db_path = tmp_path / "some_subdir" / "library.db"

    with patch("lan_streamer.db.DB_FILE", db_path):
        with patch.object(Path, "mkdir", side_effect=PermissionError("no perms")):
            db_module._db_initialized = False
            result = init_db()
            assert result is False


def test_init_db_already_initialized(tmp_path) -> None:
    """When already initialized, init_db returns False without re-running."""
    import lan_streamer.db as db_module
    from lan_streamer.db.connection import init_db

    db_path = tmp_path / "library.db"

    with patch("lan_streamer.db.DB_FILE", db_path):
        # Mark as already initialized
        db_module._db_initialized = True
        result = init_db()
        assert result is False
        # Reset
        db_module._db_initialized = False


def test_init_db_alembic_failure(tmp_path) -> None:
    """When alembic command.upgrade raises, init_db returns False."""
    import lan_streamer.db as db_module
    from lan_streamer.db.connection import init_db

    db_path = tmp_path / "library.db"

    with patch("lan_streamer.db.DB_FILE", db_path):
        db_module._db_initialized = False
        with patch("alembic.command.upgrade", side_effect=RuntimeError("alembic fail")):
            result = init_db()
            assert result is False


def test_init_db_frozen_path() -> None:
    """When sys.frozen is set, init_db uses _MEIPASS as base path."""
    import sys
    import lan_streamer.db as db_module
    from lan_streamer.db.connection import init_db

    db_module._db_initialized = False

    fake_meipass = "/fake/meipass"
    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "_MEIPASS", fake_meipass, create=True),
        patch("alembic.command.upgrade", side_effect=RuntimeError("not real")),
    ):
        result = init_db()
        # Should fail gracefully without crashing
        assert result is False


def test_init_db_creates_backup_if_db_exists(tmp_path) -> None:
    """When the database file already exists, init_db backs it up before running alembic."""
    import lan_streamer.db as db_module
    from lan_streamer.db.connection import init_db

    db_path = tmp_path / "library.db"
    db_path.write_text("existing database content")

    db_module._db_initialized = False

    with (
        patch("lan_streamer.db.DB_FILE", db_path),
        patch("alembic.command.upgrade") as mock_upgrade,
        patch("lan_streamer.system.backup.create_database_backup") as mock_backup,
    ):
        result = init_db()
        assert result is True
        mock_backup.assert_called_once()
        mock_upgrade.assert_called_once()


# ---------------------------------------------------------------------------
# db/queries.py – corrupt JSON in audio_tracks / subtitle_tracks
# ---------------------------------------------------------------------------


def test_build_episode_dict_corrupt_json(mock_db_file) -> None:
    """Episode with corrupt JSON in audio_tracks falls back to empty list."""
    from lan_streamer.db import get_session
    from lan_streamer.db.queries_file_discovery import _build_episode_dict
    from lan_streamer.db.models import Episode, Season, Series

    with get_session() as session:
        series = Series(name="JSONShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="S1")
        session.add(season)
        session.flush()
        ep = Episode(
            season_id=season.id,
            name="ep.mkv",
            path="/json/ep.mkv",
            audio_tracks="{invalid json",
            subtitle_tracks="not json either",
        )
        session.add(ep)
        session.commit()

        result = _build_episode_dict(ep)
        assert result["audio_tracks"] == []
        assert result["subtitle_tracks"] == []


def test_build_movie_dict_corrupt_json(mock_db_file) -> None:
    """Movie with corrupt JSON in audio_tracks falls back to empty list."""
    from lan_streamer.db import get_session
    from lan_streamer.db.queries_file_discovery import _build_movie_dict
    from lan_streamer.db.models import Movie

    with get_session() as session:
        movie = Movie(
            name="JSONMovie",
            library_name="Movies",
            path="/json/movie.mkv",
            audio_tracks="{bad json",
            subtitle_tracks="not json",
        )
        session.add(movie)
        session.commit()

        result = _build_movie_dict(movie)
        assert result["audio_tracks"] == []
        assert result["subtitle_tracks"] == []


# ---------------------------------------------------------------------------
# db/queries.py – get_next_episode edge cases
# ---------------------------------------------------------------------------


def test_get_next_episode_is_last_in_series(mock_db_file) -> None:
    """get_next_episode returns None when episode is last in series."""
    from lan_streamer.db import get_session
    from lan_streamer.db.models import Series, Season, Episode
    import lan_streamer.db as db

    with get_session() as session:
        series = Series(name="LastShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep = Episode(
            season_id=season.id,
            name="S01E01.mkv",
            path="/last/ep1.mkv",
            watched=True,
        )
        session.add(ep)
        session.commit()

    result = db.get_next_episode("/last/ep1.mkv")
    assert result is None  # Only episode → last → returns None


def test_get_next_episode_next_has_no_path(mock_db_file) -> None:
    """get_next_episode returns None when next episode is a placeholder (no path)."""
    from lan_streamer.db import get_session
    from lan_streamer.db.models import Series, Season, Episode
    import lan_streamer.db as db

    with get_session() as session:
        series = Series(name="PlaceholderShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep1 = Episode(
            season_id=season.id,
            name="S01E01.mkv",
            path="/placeholder/ep1.mkv",
            watched=True,
        )
        ep2 = Episode(
            season_id=season.id,
            name="S01E02.mkv",
            path=None,  # placeholder
            watched=False,
        )
        session.add_all([ep1, ep2])
        session.commit()

    result = db.get_next_episode("/placeholder/ep1.mkv")
    assert result is None


# ---------------------------------------------------------------------------
# scanner/core.py – scan_directories preserve-existing-library path
# ---------------------------------------------------------------------------


def test_scan_directories_preserves_existing_series(tmp_path) -> None:
    """When not cleanup mode, series in existing_library not found on disk are preserved."""
    from lan_streamer.scanner.core import scan_directories

    # Existing library has series not on disk
    existing_library = {
        "OldShow": {
            "metadata": {"tmdb_identifier": "111"},
            "seasons": {
                "Season 1": {
                    "episodes": [{"name": "ep1.mkv", "path": "/old/ep1.mkv"}],
                    "metadata": {},
                }
            },
        }
    }

    # Scan an empty directory (no series dirs present)
    empty_root = tmp_path / "empty_tv"
    empty_root.mkdir()

    with patch("lan_streamer.services.metadata_resolution.tmdb_client", MagicMock()):
        result = scan_directories(
            [str(empty_root)],
            library_type="tv",
            existing_library=existing_library,
            cleanup=False,  # non-destructive
        )

    # OldShow should be preserved in the result
    assert "OldShow" in result


def test_scan_directories_cleanup_removes_missing(tmp_path) -> None:
    """In cleanup mode, series not found on disk are NOT preserved."""
    from lan_streamer.scanner.core import scan_directories

    existing_library = {
        "GoneShow": {
            "metadata": {"tmdb_identifier": "222"},
            "seasons": {},
        }
    }

    empty_root = tmp_path / "empty_tv2"
    empty_root.mkdir()

    with patch("lan_streamer.services.metadata_resolution.tmdb_client", MagicMock()):
        result = scan_directories(
            [str(empty_root)],
            library_type="tv",
            existing_library=existing_library,
            cleanup=True,  # cleanup mode - missing series not preserved
        )

    assert "GoneShow" not in result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_file(tmp_path):
    return tmp_path / "library.db"
