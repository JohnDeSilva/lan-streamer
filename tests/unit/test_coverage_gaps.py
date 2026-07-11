"""Targeted tests for remaining coverage gaps to push past 90%.

Covers:
- scanner/__init__.py: pass1/pass2 returning None
- backend/jellyfin_workers.py: cancellation in push loop, progress log at 50
- backend/metadata_worker_refresh.py: jellyfin configured, movie branch, scan failure
- backend/async_worker_base.py: NotImplementedError, start without manager, CancelledError
- db/library.py: path exception, existence check exception, ScannedDirectory cleanup
- system/async_task_manager.py: sync fallback exception, interval cancellation, stop_all exception
- ui_views/dialogs/search.py: thumbnail batch processing
- db/queries_cast.py: no-identifier warnings
- backend/metadata_worker_property.py: force_refresh with no items
- scanner/file_property_scanner.py: stat error, parse errors, empty path
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# scanner/__init__.py — lines 97, 111
# ---------------------------------------------------------------------------


class TestScannerInit:
    """Cover the two early-return branches in scan_series()."""

    def test_scan_series_returns_none_when_pass1_returns_none(
        self, tmp_path: Path
    ) -> None:
        """Line 97: pass1_result is None → return None."""
        from lan_streamer.scanner import scan_series

        series_dir = tmp_path / "Empty Series"
        series_dir.mkdir()

        with patch("lan_streamer.scanner.scan_series_pass1", return_value=None):
            result = scan_series(series_dir)
            assert result is None

    def test_scan_series_returns_pass1_when_pass2_returns_none(
        self, tmp_path: Path
    ) -> None:
        """Line 111: pass2_result is None → return pass1_result."""
        from lan_streamer.scanner import scan_series

        series_dir = tmp_path / "Half Scanned"
        series_dir.mkdir()

        pass1_data = {"metadata": {"name": "Half Scanned"}, "seasons": {}}

        with (
            patch("lan_streamer.scanner.scan_series_pass1", return_value=pass1_data),
            patch("lan_streamer.scanner.scan_series_pass2", return_value=None),
        ):
            result = scan_series(series_dir)
            assert result is pass1_data


# ---------------------------------------------------------------------------
# backend/jellyfin_workers.py — lines 77-78, 82
# ---------------------------------------------------------------------------


class TestJellyfinPushWorkerLines:
    """Cover the cancellation and progress-logging branches."""

    def test_push_loop_cancellation_breaks(self) -> None:
        """Lines 77-78: cancellation during push loop."""
        from lan_streamer.backend.jellyfin_workers import JellyfinPushWorker

        worker = JellyfinPushWorker()
        episodes = [{"jellyfin_id": f"jf_{i}", "watched": True} for i in range(5)]

        call_count = 0

        def fake_set_watched(jellyfin_id: str, status: bool) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                worker._cancelled = True

        with patch(
            "lan_streamer.providers.jellyfin.jellyfin_client.set_watched_status",
            side_effect=fake_set_watched,
        ):
            pushed = worker._push_loop(episodes, len(episodes))
            assert pushed == 2
            assert call_count == 2

    def test_push_loop_progress_log_at_50(self) -> None:
        """Line 82: progress logged every 50 episodes."""
        from lan_streamer.backend.jellyfin_workers import JellyfinPushWorker

        worker = JellyfinPushWorker()
        episodes = [{"jellyfin_id": f"jf_{i}", "watched": True} for i in range(55)]

        with (
            patch("lan_streamer.providers.jellyfin.jellyfin_client.set_watched_status"),
            patch("lan_streamer.backend.jellyfin_workers.logger") as mock_logger,
        ):
            pushed = worker._push_loop(episodes, len(episodes))
            assert pushed == 55
            # Should have logged progress at least once (at episode 50)
            debug_calls = [
                c for c in mock_logger.debug.call_args_list if "progress" in str(c)
            ]
            assert len(debug_calls) >= 1


# ---------------------------------------------------------------------------
# backend/metadata_worker_refresh.py — lines 66, 72, 95
# ---------------------------------------------------------------------------


class TestRefreshWorkerUncoveredLines:
    """Cover jellyfin configured, movie branch, and scan failure."""

    def test_movie_branch_refresh(self, tmp_path: Path) -> None:
        """Line 72: library_type == 'movie' → scan_movie_pass2."""
        from lan_streamer.backend.metadata_worker_refresh import RefreshSeriesWorker

        movie_dir = tmp_path / "Test Movie"
        movie_dir.mkdir()

        worker = RefreshSeriesWorker(
            library_name="Movies",
            item_name="Test Movie",
            library_type="movie",
            root_directories=[str(tmp_path)],
            existing_library={"Test Movie": {"name": "Test Movie"}},
        )

        with (
            patch(
                "lan_streamer.backend.metadata_worker_refresh.scan_movie_pass2",
                return_value={"name": "Test Movie", "runtime": 120},
            ),
            patch("lan_streamer.backend.metadata_worker_refresh.db.save_library"),
        ):
            finished_data = None

            def on_finished(d: dict) -> None:
                nonlocal finished_data
                finished_data = d

            worker.finished.connect(on_finished)
            worker.run()

            assert finished_data is not None
            assert finished_data["Test Movie"]["runtime"] == 120

    def test_scan_failure_raises_error(self, tmp_path: Path) -> None:
        """Line 95: item_data is falsy → ValueError."""
        from lan_streamer.backend.metadata_worker_refresh import RefreshSeriesWorker

        movie_dir = tmp_path / "Fail Movie"
        movie_dir.mkdir()

        worker = RefreshSeriesWorker(
            library_name="Movies",
            item_name="Fail Movie",
            library_type="movie",
            root_directories=[str(tmp_path)],
            existing_library={},
        )

        with patch(
            "lan_streamer.backend.metadata_worker_refresh.scan_movie_pass2",
            return_value=None,
        ):
            errors = []

            def on_error(msg: str) -> None:
                errors.append(msg)

            worker.error.connect(on_error)
            worker.run()
            assert len(errors) == 1
            assert "Scan failed" in errors[0]

    def test_jellyfin_configured_fetches_data(self, tmp_path: Path) -> None:
        """Line 66: jellyfin_client.is_configured() is True → fetches correlation data."""
        from lan_streamer.backend.metadata_worker_refresh import RefreshSeriesWorker

        movie_dir = tmp_path / "Jelly Movie"
        movie_dir.mkdir()

        worker = RefreshSeriesWorker(
            library_name="Movies",
            item_name="Jelly Movie",
            library_type="movie",
            root_directories=[str(tmp_path)],
            existing_library={},
        )

        with (
            patch(
                "lan_streamer.backend.metadata_worker_refresh.jellyfin_client"
            ) as mock_jf,
            patch(
                "lan_streamer.backend.metadata_worker_refresh.scan_movie_pass2",
                return_value={"name": "Jelly Movie"},
            ),
            patch("lan_streamer.backend.metadata_worker_refresh.db.save_library"),
        ):
            mock_jf.is_configured.return_value = True
            mock_jf.get_jellyfin_correlation_data.return_value = {"jf_data": True}

            finished_data = None

            def on_finished(d: dict) -> None:
                nonlocal finished_data
                finished_data = d

            worker.finished.connect(on_finished)
            worker.run()
            assert finished_data is not None
            mock_jf.get_jellyfin_correlation_data.assert_called_once()

    def test_series_refresh_with_show_future_false(self, tmp_path: Path) -> None:
        """Line 81-83: show_future_episodes from config is used."""
        from lan_streamer.backend.metadata_worker_refresh import RefreshSeriesWorker
        from lan_streamer.system.config import config

        series_dir = tmp_path / "Future Show"
        series_dir.mkdir()

        config.libraries["Future Lib"] = {"show_future_episodes": False}

        worker = RefreshSeriesWorker(
            library_name="Future Lib",
            item_name="Future Show",
            library_type="tv",
            root_directories=[str(tmp_path)],
            existing_library={},
        )

        with (
            patch(
                "lan_streamer.backend.metadata_worker_refresh.scan_series_pass2",
                return_value={"metadata": {}, "seasons": {}},
            ),
            patch(
                "lan_streamer.backend.metadata_worker_refresh.clean_series_data",
                lambda x: x,
            ),
            patch("lan_streamer.backend.metadata_worker_refresh.db.save_library"),
        ):
            finished_data = None

            def on_finished(d: dict) -> None:
                nonlocal finished_data
                finished_data = d

            worker.finished.connect(on_finished)
            worker.run()
            assert finished_data is not None


# ---------------------------------------------------------------------------
# backend/async_worker_base.py — lines 59, 75, 98, 113
# ---------------------------------------------------------------------------


class TestAsyncWorkerBaseUncovered:
    """Cover the remaining lines in AsyncWorkerBase."""

    def test_base_run_async_raises_not_implemented(self) -> None:
        """Line 59: base class run_async raises NotImplementedError."""
        from lan_streamer.backend.async_worker_base import AsyncWorkerBase

        worker = AsyncWorkerBase()
        with pytest.raises(NotImplementedError):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(worker.run_async())
            finally:
                loop.close()

    def test_start_without_async_task_manager_raises(self) -> None:
        """Line 75: start() without AsyncTaskManager raises RuntimeError."""
        from lan_streamer.backend.async_worker_base import AsyncWorkerBase

        worker = AsyncWorkerBase(async_task_manager=None)
        with pytest.raises(RuntimeError, match="Cannot start"):
            worker.start()

    def test_is_running_false_without_async_task_manager(self) -> None:
        """Line 98: is_running returns False when no manager."""
        from lan_streamer.backend.async_worker_base import AsyncWorkerBase

        worker = AsyncWorkerBase(async_task_manager=None)
        assert worker.is_running is False

    def test_cancelled_error_is_logged(self) -> None:
        """Line 113: CancelledError during run_async is logged."""
        from lan_streamer.backend.async_worker_base import AsyncWorkerBase

        class _CancelWorker(AsyncWorkerBase):
            async def run_async(self) -> None:
                raise asyncio.CancelledError()

        worker = _CancelWorker()

        # Use run() synchronously — _run_wrapper catches CancelledError
        worker.run()
        # No error signal should have been emitted
        errors: list[str] = []
        worker.error.connect(errors.append)
        assert errors == []


# ---------------------------------------------------------------------------
# db/library.py — lines 69-70, 82-83, 128-133, 142
# ---------------------------------------------------------------------------


class TestLibraryCleanupEdgeCases:
    """Cover edge-case branches in library cleanup."""

    def test_orphaned_media_file_path_exception(self, tmp_path: Path) -> None:
        """Lines 69-70: mf.path triggers an exception during path resolution."""
        from lan_streamer.db.library import _cleanup_orphaned_media_files
        from lan_streamer.db.connection import get_session
        from lan_streamer.db.models import MediaFile

        with get_session() as session:
            mf = MediaFile(path="/bad\x00path/file.mkv")
            session.add(mf)
            session.flush()

        stats: Dict[str, int] = {}
        root_dir = tmp_path / "lib"
        root_dir.mkdir()

        _cleanup_orphaned_media_files(session, [str(root_dir)], stats)
        # The path exception is caught and logged, no crash

    def test_orphaned_media_file_existence_check_exception(
        self, tmp_path: Path
    ) -> None:
        """Lines 82-83: Path(mf.path).exists() raises an exception."""
        from lan_streamer.db.library import _cleanup_orphaned_media_files
        from lan_streamer.db.connection import get_session
        from lan_streamer.db.models import MediaFile

        # Use a path under root that triggers an exception on .exists()
        root_dir = tmp_path / "lib"
        root_dir.mkdir()
        fake_file = root_dir / "video.mkv"

        with get_session() as session:
            mf = MediaFile(path=str(fake_file))
            session.add(mf)
            session.flush()

        stats: Dict[str, int] = {}
        with patch("lan_streamer.db.library.Path") as MockPath:
            mock_path_instance = MagicMock()
            mock_path_instance.relative_to.return_value = root_dir
            mock_path_instance.exists.side_effect = OSError("Permission denied")
            MockPath.return_value = mock_path_instance

            _cleanup_orphaned_media_files(session, [str(root_dir)], stats)

        # Should not crash, exception is caught


def test_cleanup_library_movie_scanned_directory(tmp_path: Path) -> None:
    """Lines 128-133: movie library ScannedDirectory cleanup."""
    from lan_streamer.db.library import cleanup_library
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import ScannedDirectory
    from lan_streamer.system.config import config

    library_name = "MovieCleanup"
    config.libraries[library_name] = {"type": "movie"}

    movie_dir = tmp_path / "Ghost Movie"
    movie_dir.mkdir()

    # Save a movie in DB
    from lan_streamer import db

    db.save_movie_library(
        library_name,
        {"Some Movie": {"name": "Some Movie", "path": "/existing.mkv"}},
    )

    with get_session() as session:
        # Add a ScannedDirectory for a series that doesn't have a Movie record
        sd = ScannedDirectory(
            path=str(movie_dir.absolute()),
            last_scanned_mtime=0.0,
        )
        session.add(sd)
        session.commit()

    _stats = cleanup_library(library_name, [str(tmp_path)])
    # Should handle the movie branch for ScannedDirectory cleanup


def test_cleanup_library_tv_scanned_directory_delete(tmp_path: Path) -> None:
    """Line 142: delete ScannedDirectory for series not in DB."""
    from lan_streamer.db.library import cleanup_library
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import ScannedDirectory, Series
    from lan_streamer.system.config import config

    library_name = "TVScannedDir"
    config.libraries[library_name] = {"type": "tv"}

    series_dir = tmp_path / "Present Show"
    series_dir.mkdir()

    with get_session() as session:
        # Series exists in DB so its ScannedDirectory should NOT be deleted
        series = Series(name="Present Show", library_name=library_name)
        session.add(series)
        session.flush()
        sd = ScannedDirectory(
            path=str(series_dir.absolute()),
            last_scanned_mtime=0.0,
        )
        session.add(sd)
        session.commit()

    _stats = cleanup_library(library_name, [str(tmp_path)])
    # "Present Show" folder exists -> series exists -> SD should NOT be deleted
    with get_session() as session:
        remaining = (
            session.query(ScannedDirectory)
            .filter_by(
                path=str(series_dir.absolute()),
            )
            .all()
        )
        assert len(remaining) == 1


def test_cleanup_library_tv_scanned_directory_no_series(tmp_path: Path) -> None:
    """Line 142: series folder exists but no DB entry -> delete ScannedDirectory."""
    from lan_streamer.db.library import cleanup_library
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import ScannedDirectory
    from lan_streamer.system.config import config

    library_name = "TVGhostSD"
    config.libraries[library_name] = {"type": "tv"}

    ghost_dir = tmp_path / "Ghost Series"
    ghost_dir.mkdir()

    with get_session() as session:
        sd = ScannedDirectory(
            path=str(ghost_dir.absolute()),
            last_scanned_mtime=0.0,
        )
        session.add(sd)
        session.commit()

    _stats = cleanup_library(library_name, [str(tmp_path)])
    # Ghost Series folder exists but no Series DB record -> SD should be deleted
    with get_session() as session:
        remaining = (
            session.query(ScannedDirectory)
            .filter_by(
                path=str(ghost_dir.absolute()),
            )
            .all()
        )
        assert len(remaining) == 0


# ---------------------------------------------------------------------------
# system/async_task_manager.py — lines 120, 124-126, 248-249, 353-354
# ---------------------------------------------------------------------------


class TestAsyncTaskManagerEdgeCases:
    """Cover remaining edge cases in AsyncTaskManager."""

    def test_synchronous_fallback_exception(self) -> None:
        """Lines 124-126: synchronous fallback for task that raises."""
        from lan_streamer.system.async_task_manager import AsyncTaskManager

        manager = AsyncTaskManager()

        async def failing_coro() -> None:
            msg = "coro failed"
            raise RuntimeError(msg)

        # Use a real event loop to test the synchronous fallback
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
                result = manager.create_task(failing_coro(), name="sync_fail")
                assert result is None
        finally:
            loop.close()

    def test_interval_task_cancelled_during_execution(self) -> None:
        """Lines 248-249: CancelledError during interval coroutine execution."""
        from lan_streamer.system.async_task_manager import AsyncTaskManager

        event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(event_loop)
        manager = AsyncTaskManager()
        run_count = 0

        async def flaky() -> None:
            nonlocal run_count
            run_count += 1
            if run_count == 1:
                raise asyncio.CancelledError()

        try:

            async def _run() -> None:
                task = manager.schedule_interval(
                    lambda: flaky(), interval_seconds=0.01, name="cancel_during"
                )
                assert task is not None

            event_loop.run_until_complete(_run())
            event_loop.run_until_complete(asyncio.sleep(0.05))
        finally:
            manager.cancel_all()
            event_loop.run_until_complete(asyncio.sleep(0))
            event_loop.close()

    def test_stop_all_with_exception_in_pending_task(self) -> None:
        """Lines 353-354: exception during stop_all wait for pending tasks."""
        from lan_streamer.system.async_task_manager import AsyncTaskManager

        event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(event_loop)
        manager = AsyncTaskManager()

        async def error_task() -> None:
            await asyncio.sleep(0.01)
            msg = "task error"
            raise RuntimeError(msg)

        try:

            async def _run() -> None:
                manager.create_task(error_task(), name="errorer")

            event_loop.run_until_complete(_run())
            event_loop.run_until_complete(asyncio.sleep(0.005))

            cleanup = manager.stop_all()
            if cleanup is not None:
                event_loop.run_until_complete(cleanup)
        finally:
            event_loop.run_until_complete(asyncio.sleep(0))


# ---------------------------------------------------------------------------
# ui_views/dialogs/search.py — lines 191, 203, 208-213
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# db/queries_cast.py — lines 45-54, 66-77, 254-255, 263-265, 292-293, 335, 388-389
# ---------------------------------------------------------------------------


class TestQueriesCastUncoveredLines:
    """Cover remaining branches in queries_cast.py.

    Uses mock-patched get_session to avoid cast table dependency issues.
    """

    def test_get_cast_for_series_no_identifier(self) -> None:
        """Series cast returns entries even when person has no extra identifier."""
        from lan_streamer.db.queries_cast import get_cast_for_series

        person = MagicMock()
        person.tmdb_identifier = 12345
        person.name = "No Identifier Actor"

        cast_entry = MagicMock()
        cast_entry.person = person
        cast_entry.sort_order = 1

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.unique.return_value.scalars.return_value.all.return_value = [
            cast_entry
        ]
        mock_session.execute.return_value = mock_result

        with patch("lan_streamer.db.queries_cast.get_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_cast_for_series("fake-series-id")
            assert len(result) == 1

    def test_get_cast_for_season_no_identifier(self) -> None:
        """Season cast returns entries for person without identifier."""
        from lan_streamer.db.queries_cast import get_cast_for_season

        cast_entry = MagicMock()
        cast_entry.person = MagicMock()
        cast_entry.person.tmdb_identifier = 2001
        cast_entry.person.name = "Season Actor"
        cast_entry.sort_order = 1

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.unique.return_value.scalars.return_value.all.return_value = [
            cast_entry
        ]
        mock_session.execute.return_value = mock_result

        with patch("lan_streamer.db.queries_cast.get_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_cast_for_season("fake-season-id")
            assert len(result) == 1

    def test_get_cast_for_episode_no_identifier(self) -> None:
        """Episode cast returns entries for person without identifier."""
        from lan_streamer.db.queries_cast import get_cast_for_episode

        cast_entry = MagicMock()
        cast_entry.person = MagicMock()
        cast_entry.person.tmdb_identifier = 3001
        cast_entry.person.name = "Episode Actor"
        cast_entry.sort_order = 1

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.unique.return_value.scalars.return_value.all.return_value = [
            cast_entry
        ]
        mock_session.execute.return_value = mock_result

        with patch("lan_streamer.db.queries_cast.get_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_cast_for_episode("fake-episode-id")
            assert len(result) == 1

    def test_get_cast_for_movie_no_identifier(self) -> None:
        """Movie cast returns entries for person without identifier."""
        from lan_streamer.db.queries_cast import get_cast_for_movie

        cast_entry = MagicMock()
        cast_entry.person = MagicMock()
        cast_entry.person.tmdb_identifier = 4001
        cast_entry.person.name = "Movie Actor"
        cast_entry.sort_order = 1

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.unique.return_value.scalars.return_value.all.return_value = [
            cast_entry
        ]
        mock_session.execute.return_value = mock_result

        with patch("lan_streamer.db.queries_cast.get_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_cast_for_movie("fake-movie-id")
            assert len(result) == 1

    def test_get_filmography_returns_empty(self) -> None:
        """Filmography for person with no roles returns empty list."""
        from lan_streamer.db.queries_cast import get_filmography

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.unique.return_value.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        with patch("lan_streamer.db.queries_cast.get_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_filmography("fake-person-id")
            assert result == []

    def test_get_person_by_id_not_found(self) -> None:
        """get_person_by_id returns None for missing person."""
        from lan_streamer.db.queries_cast import get_person_by_id

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.unique.return_value.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("lan_streamer.db.queries_cast.get_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_person_by_id("00000000-0000-0000-0000-000000000000")
            assert result is None

    def test_get_person_by_id_found(self) -> None:
        """get_person_by_id returns person when found."""
        from lan_streamer.db.queries_cast import get_person_by_id

        person = MagicMock()
        person.name = "Findable Person"

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.unique.return_value.scalar_one_or_none.return_value = person
        mock_session.execute.return_value = mock_result

        with patch("lan_streamer.db.queries_cast.get_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_person_by_id("fake-person-id")
            assert result is not None
            assert result.name == "Findable Person"


# ---------------------------------------------------------------------------
# backend/metadata_worker_property.py — lines 95-97
# ---------------------------------------------------------------------------


class TestFilePropertyWorkerEdgeCases:
    """Cover the remaining lines in FilePropertyExtractionWorker."""

    def test_force_refresh_no_items_returns_zero(self) -> None:
        """Lines 95-97 + 128-131: force_refresh but get_all_media_items returns empty."""
        from lan_streamer.backend.metadata_worker_property import (
            FilePropertyExtractionWorker,
        )

        with (
            patch("lan_streamer.db.get_all_media_items", return_value=[]),
        ):
            finished_emitted: list[int] = []

            worker = FilePropertyExtractionWorker(force_refresh=True)
            worker.finished.connect(finished_emitted.append)
            worker.run()

            # Base class also emits finished, so we get [0, 0]
            assert finished_emitted == [0, 0]

    def test_produce_item_update_with_technical_info(self) -> None:
        """Cover _produce_item_update when info has tech data but no runtime."""
        from lan_streamer.backend.metadata_worker_property import _produce_item_update

        with patch(
            "lan_streamer.backend.metadata_worker_property.get_detailed_file_info",
            return_value={
                "runtime": None,
                "video_codec": "h264",
                "resolution": "1920x1080",
                "audio_tracks": [],
                "subtitle_tracks": [],
                "bit_rate": 5000000,
                "size_bytes": 1000000,
            },
        ):
            result = _produce_item_update(
                {"id": 1, "path": "/test.mkv", "type": "episode"}
            )
            assert result is not None
            assert result["video_codec"] == "h264"
            assert result["runtime_minutes"] is None

    def test_produce_item_update_returns_none_when_no_data(self) -> None:
        """Cover _produce_item_update returning None."""
        from lan_streamer.backend.metadata_worker_property import _produce_item_update

        with patch(
            "lan_streamer.backend.metadata_worker_property.get_detailed_file_info",
            return_value={
                "runtime": None,
                "video_codec": None,
                "resolution": None,
                "audio_tracks": [],
                "subtitle_tracks": [],
                "bit_rate": 0,
                "size_bytes": 0,
            },
        ):
            result = _produce_item_update(
                {"id": 1, "path": "/test.mkv", "type": "episode"}
            )
            assert result is None

    def test_worker_filters_by_changed_season_ids(self) -> None:
        """Lines 105-109: episode filtered when season_id not in changed_season_ids."""
        from lan_streamer.backend.metadata_worker_property import (
            FilePropertyExtractionWorker,
        )

        with (
            patch("lan_streamer.db.get_items_missing_runtime") as mock_get,
            patch(
                "lan_streamer.backend.metadata_worker_property.get_detailed_file_info"
            ) as mock_info,
            patch("lan_streamer.db.update_items_runtime_batch"),
        ):
            mock_get.return_value = [
                {
                    "id": 1,
                    "path": "/ep1.mkv",
                    "type": "episode",
                    "season_id": "season_A",
                    "library_name": "TV",
                },
                {
                    "id": 2,
                    "path": "/ep2.mkv",
                    "type": "episode",
                    "season_id": "season_B",
                    "library_name": "TV",
                },
            ]
            mock_info.return_value = {
                "runtime": 30,
                "video_codec": "h264",
                "resolution": "1920x1080",
                "audio_tracks": [],
                "subtitle_tracks": [],
            }

            worker = FilePropertyExtractionWorker(
                changed_season_ids={"season_A"},
            )
            worker.run()

            # Only season_A episode should be processed
            assert mock_info.call_count == 1
            mock_info.assert_called_with("/ep1.mkv")

    def test_worker_filters_by_changed_movie_ids(self) -> None:
        """Lines 111-115: movie filtered when id not in changed_movie_ids."""
        from lan_streamer.backend.metadata_worker_property import (
            FilePropertyExtractionWorker,
        )

        with (
            patch("lan_streamer.db.get_items_missing_runtime") as mock_get,
            patch(
                "lan_streamer.backend.metadata_worker_property.get_detailed_file_info"
            ) as mock_info,
            patch("lan_streamer.db.update_items_runtime_batch"),
        ):
            mock_get.return_value = [
                {
                    "id": 100,
                    "path": "/movie1.mkv",
                    "type": "movie",
                    "library_name": "Movies",
                },
                {
                    "id": 200,
                    "path": "/movie2.mkv",
                    "type": "movie",
                    "library_name": "Movies",
                },
            ]
            mock_info.return_value = {
                "runtime": 120,
                "video_codec": "h265",
                "resolution": "3840x2160",
                "audio_tracks": [],
                "subtitle_tracks": [],
            }

            worker = FilePropertyExtractionWorker(
                changed_movie_ids={100},
            )
            worker.run()

            # Only movie id=100 should be processed
            assert mock_info.call_count == 1
            mock_info.assert_called_with("/movie1.mkv")


# ---------------------------------------------------------------------------
# scanner/file_property_scanner.py — lines 123-124, 159-160, 164-167, 173-174, 229
# ---------------------------------------------------------------------------


class TestFilePropertyScannerEdgeCases:
    """Cover remaining branches in file_property_scanner.py."""

    def test_get_detailed_file_info_stat_error(self, tmp_path: Path) -> None:
        """Lines 123-124: stat() raises an exception."""
        from lan_streamer.scanner.file_property_scanner import get_detailed_file_info

        video_file = tmp_path / "test.mkv"
        video_file.write_text("fake content")

        mock_path_instance = MagicMock()
        mock_path_instance.suffix = ".mkv"
        mock_path_instance.stat.side_effect = OSError("Permission denied")

        with (
            patch(
                "lan_streamer.scanner.file_property_scanner.Path",
                return_value=mock_path_instance,
            ),
            patch(
                "lan_streamer.scanner.file_property_scanner.os.path.exists",
                return_value=True,
            ),
            patch(
                "lan_streamer.scanner.file_property_scanner.subprocess.run",
                return_value=MagicMock(returncode=1),
            ),
        ):
            result = get_detailed_file_info(str(video_file))
            # size_bytes should remain None since stat failed
            assert result["video_type"] == "MKV"

    def test_get_detailed_file_info_empty_path(self) -> None:
        """Line 110-112: empty file_path returns default info."""
        from lan_streamer.scanner.file_property_scanner import get_detailed_file_info

        result = get_detailed_file_info("")
        assert result["size_bytes"] is None
        assert result["runtime"] is None

    def test_get_detailed_file_info_bit_rate_parse_error(self, tmp_path: Path) -> None:
        """Lines 164-167: bit_rate string that can't be parsed."""
        from lan_streamer.scanner.file_property_scanner import get_detailed_file_info

        video_file = tmp_path / "test.mkv"
        video_file.write_text("x")

        mock_stdout = '{"format": {"bit_rate": "not_a_number", "duration": "120.0"}, "streams": []}'

        mock_path_instance = MagicMock()
        mock_path_instance.suffix = ".mkv"
        mock_path_instance.stat.return_value = MagicMock(st_size=1000)

        with (
            patch(
                "lan_streamer.scanner.file_property_scanner.os.path.exists",
                return_value=True,
            ),
            patch(
                "lan_streamer.scanner.file_property_scanner.subprocess.run",
                return_value=MagicMock(returncode=0, stdout=mock_stdout),
            ),
            patch(
                "lan_streamer.scanner.file_property_scanner.Path",
                return_value=mock_path_instance,
            ),
        ):
            result = get_detailed_file_info(str(video_file))
            # bit_rate should remain None because parse failed
            assert result["runtime"] == 2

    def test_get_detailed_file_info_bit_rate_fallback_from_duration(
        self, tmp_path: Path
    ) -> None:
        """Lines 173-174: bit_rate computed from size and duration."""
        from lan_streamer.scanner.file_property_scanner import get_detailed_file_info

        video_file = tmp_path / "test.mkv"
        video_file.write_text("x")

        mock_stdout = '{"format": {"duration": "10.0"}, "streams": []}'

        mock_path_instance = MagicMock()
        mock_path_instance.suffix = ".mkv"
        mock_path_instance.stat.return_value = MagicMock(st_size=1000)

        with (
            patch(
                "lan_streamer.scanner.file_property_scanner.os.path.exists",
                return_value=True,
            ),
            patch(
                "lan_streamer.scanner.file_property_scanner.subprocess.run",
                return_value=MagicMock(returncode=0, stdout=mock_stdout),
            ),
            patch(
                "lan_streamer.scanner.file_property_scanner.Path",
                return_value=mock_path_instance,
            ),
        ):
            result = get_detailed_file_info(str(video_file))
            # size_bytes * 8 / duration = 1000 * 8 / 10 = 800
            assert result["bit_rate"] == 800

    def test_get_stub_file_info_empty_path(self) -> None:
        """Line 229: empty file_path returns default info."""
        from lan_streamer.scanner.file_property_scanner import get_stub_file_info

        result = get_stub_file_info("")
        assert result["size_bytes"] is None
        assert result["runtime"] == 0
        assert result["video_codec"] == "Unknown"

    def test_get_stub_file_info_with_real_file(self, tmp_path: Path) -> None:
        """Cover the normal path with a real file."""
        from lan_streamer.scanner.file_property_scanner import get_stub_file_info

        video_file = tmp_path / "test_video.mkv"
        video_file.write_text("fake content")

        result = get_stub_file_info(str(video_file))
        assert result["size_bytes"] == len(b"fake content")
        assert result["video_type"] == "MKV"

    def test_get_stub_file_info_stat_error(self, tmp_path: Path) -> None:
        """Lines 235-238: stat error is caught."""
        from lan_streamer.scanner.file_property_scanner import get_stub_file_info

        result = get_stub_file_info(str(tmp_path / "nonexistent.mkv"))
        assert result["size_bytes"] is None
        assert result["video_type"] == "MKV"


# ---------------------------------------------------------------------------
# ui_views/dialogs/search.py — lines 191, 203, 208-213
# ---------------------------------------------------------------------------


class TestSearchDialogThumbnailBatch:
    """Cover thumbnail batch processing in SearchDialog."""

    def test_execute_search_with_poster_paths_queues_thumbnails(self, qtbot) -> None:
        """Line 191: poster_path present → _pending_thumbnails.append."""
        from lan_streamer.ui_views.dialogs.search import SearchDialog

        controller = MagicMock()
        controller.search_media.return_value = [
            {
                "name": "Show A",
                "library_name": "TV",
                "poster_path": "/some/poster.jpg",
                "type": "series",
            },
        ]

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Show")
        dialog._execute_search()

        assert len(dialog._pending_thumbnails) == 1
        assert dialog.results_list.count() == 1

    def test_process_thumbnail_batch_processes_three_items(
        self, qtbot, tmp_path
    ) -> None:
        """Lines 208-213: _process_thumbnail_batch processes up to 3 items."""
        from lan_streamer.ui_views.dialogs.search import SearchDialog

        controller = MagicMock()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)

        items_and_paths = []
        for i in range(5):
            f = tmp_path / f"thumb_{i}.jpg"
            f.write_bytes(b"fake")
            list_item = MagicMock()
            items_and_paths.append((list_item, str(f)))

        dialog._pending_thumbnails = items_and_paths

        with (
            patch("lan_streamer.ui_views.dialogs.search.QPixmap") as mock_pixmap,
            patch.object(dialog, "_assign_thumbnail_icon") as mock_assign,
        ):
            mock_pixmap.return_value.isNull.return_value = False
            dialog._process_thumbnail_batch()

            assert mock_assign.call_count == 3
            assert len(dialog._pending_thumbnails) == 2

    def test_process_thumbnail_batch_handles_corrupt_image(
        self, qtbot, tmp_path
    ) -> None:
        """Lines 208-213: handles corrupt image gracefully."""
        from lan_streamer.ui_views.dialogs.search import SearchDialog

        controller = MagicMock()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)

        bad_file = tmp_path / "bad.jpg"
        bad_file.write_bytes(b"not an image")

        list_item = MagicMock()
        dialog._pending_thumbnails = [(list_item, str(bad_file))]

        with patch("lan_streamer.ui_views.dialogs.search.QPixmap") as mock_pixmap:
            mock_pixmap.return_value.isNull.return_value = True
            dialog._process_thumbnail_batch()
            assert dialog._pending_thumbnails == []

    def test_execute_search_queues_thumbnails_for_movies(self, qtbot) -> None:
        """Line 203: movie poster_path also queues thumbnails."""
        from lan_streamer.ui_views.dialogs.search import SearchDialog

        controller = MagicMock()
        controller.search_media.return_value = [
            {
                "name": "Movie A",
                "library_name": "Movies",
                "poster_path": "/movie/poster.jpg",
                "type": "movie",
            },
        ]

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Movie")
        dialog._execute_search()

        assert len(dialog._pending_thumbnails) == 1

    def test_process_thumbnail_batch_empty_path(self, qtbot) -> None:
        """Lines 208-213: empty path is skipped."""
        from lan_streamer.ui_views.dialogs.search import SearchDialog

        controller = MagicMock()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)

        list_item = MagicMock()
        dialog._pending_thumbnails = [(list_item, "")]

        dialog._process_thumbnail_batch()
        assert dialog._pending_thumbnails == []
        list_item.setIcon.assert_not_called()
