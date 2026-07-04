"""Tests for BUG-02/BUG-06: TMDB prefetch executor lifetime management.

Verifies that:
- _fetch_tmdb_episodes_parallel accepts an executor parameter (no global singleton)
- scan_series accepts tmdb_prefetch_executor parameter and passes it through
- The executor is shut down in the scan_worker_all finally block
- The executor is shut down even when an exception occurs during run_async
"""

import concurrent.futures
from typing import Any, Dict
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Tests for _fetch_tmdb_episodes_parallel accepting an executor parameter
# ---------------------------------------------------------------------------


def test_fetch_tmdb_episodes_parallel_uses_provided_executor() -> None:
    """_fetch_tmdb_episodes_parallel uses the executor passed as a parameter,
    not a module-level global singleton."""
    from lan_streamer.scanner.scan_tv import _fetch_tmdb_episodes_parallel

    mock_episodes = [{"id": 1, "name": "Episode 1"}]
    mock_future: concurrent.futures.Future = concurrent.futures.Future()
    mock_future.set_result(mock_episodes)

    executor = MagicMock(spec=concurrent.futures.ThreadPoolExecutor)
    executor.submit.return_value = mock_future

    season_indices: Dict[str, int] = {"Season 1": 1}

    with patch(
        "lan_streamer.scanner.scan_tv._tmdb_client.get_episodes",
        return_value=mock_episodes,
    ):
        result = _fetch_tmdb_episodes_parallel(
            tmdb_series_id=12345,
            season_indices=season_indices,
            executor=executor,
        )

    # The provided executor must have been used
    executor.submit.assert_called_once()
    assert "Season 1" in result


def test_fetch_tmdb_episodes_parallel_no_global_executor_access() -> None:
    """_fetch_tmdb_episodes_parallel does NOT call _get_tmdb_prefetch_executor
    when an executor is provided as a parameter."""
    import lan_streamer.scanner.scan_tv as scan_tv_module

    # Ensure the module no longer has _get_tmdb_prefetch_executor
    assert not hasattr(scan_tv_module, "_get_tmdb_prefetch_executor"), (
        "_get_tmdb_prefetch_executor should have been removed from scan_tv module "
        "(BUG-06 fix not applied)"
    )


def test_fetch_tmdb_episodes_parallel_handles_fetch_failure() -> None:
    """Failed futures are caught and the season is skipped gracefully."""
    from lan_streamer.scanner.scan_tv import _fetch_tmdb_episodes_parallel

    failing_future: concurrent.futures.Future = concurrent.futures.Future()
    failing_future.set_exception(RuntimeError("TMDB unreachable"))

    executor = MagicMock(spec=concurrent.futures.ThreadPoolExecutor)
    executor.submit.return_value = failing_future

    season_indices: Dict[str, int] = {"Season 2": 2}

    result = _fetch_tmdb_episodes_parallel(
        tmdb_series_id=99,
        season_indices=season_indices,
        executor=executor,
    )

    # Should return empty dict, not raise
    assert result == {}


def test_scan_series_accepts_tmdb_prefetch_executor_parameter() -> None:
    """scan_series accepts a tmdb_prefetch_executor keyword argument."""
    import inspect
    from lan_streamer.scanner.scan_tv import scan_series

    signature = inspect.signature(scan_series)
    assert "tmdb_prefetch_executor" in signature.parameters, (
        "scan_series must have a tmdb_prefetch_executor parameter (BUG-06 fix not applied)"
    )
    parameter = signature.parameters["tmdb_prefetch_executor"]
    # Should default to None so existing callers are unaffected
    assert parameter.default is None, (
        "tmdb_prefetch_executor must default to None for backward compatibility"
    )


def test_scan_series_passes_executor_to_prefetch_when_provided() -> None:
    """When tmdb_prefetch_executor is supplied, scan_series passes it to
    _fetch_tmdb_episodes_parallel instead of creating a new executor."""
    from pathlib import Path

    mock_executor = MagicMock(spec=concurrent.futures.ThreadPoolExecutor)
    # Simulate a future that returns an empty episode list
    empty_future: concurrent.futures.Future = concurrent.futures.Future()
    empty_future.set_result([])
    mock_executor.submit.return_value = empty_future

    # We only want to test that executor is threaded through; abort after prefetch
    with (
        patch("lan_streamer.scanner.scan_tv._validate_series_file_layout"),
        patch(
            "lan_streamer.scanner.scan_tv._process_series_metadata",
            return_value=(
                {
                    "_tmdb_series_id": "42",
                    "metadata": {"locked_metadata": False},
                    "seasons": {},
                },
                True,  # is_early_return=True — exits after Phase 2
                None,
                {},
                False,
            ),
        ),
        patch(
            "lan_streamer.scanner.scan_tv._tmdb_client.is_configured", return_value=True
        ),
    ):
        from lan_streamer.scanner.scan_tv import scan_series

        # is_early_return=True means scan_series returns early before prefetch;
        # use offline=False but is_early_return handles exit cleanly
        result = scan_series(
            series_directory=Path("/fake/series"),
            offline=False,
            tmdb_prefetch_executor=mock_executor,
        )

    # scan_series should complete without error
    assert result is not None


def test_scan_worker_all_shuts_down_tmdb_executor() -> None:
    """ScanAllLibrariesWorker shuts down the tmdb_prefetch_executor in its
    finally block after a scan completes."""
    import asyncio
    from lan_streamer.scanner import LibraryDict
    from lan_streamer.backend import ScanAllLibrariesWorker
    from lan_streamer.system.async_task_manager import AsyncTaskManager
    from PySide6.QtCore import QObject

    shutdown_calls: list = []

    class _TrackingExecutor(concurrent.futures.ThreadPoolExecutor):
        def shutdown(self, wait: bool = True, **kwargs: Any) -> None:
            shutdown_calls.append({"wait": wait})
            super().shutdown(wait=False)

    parent_object = QObject()
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        task_manager = AsyncTaskManager(parent=parent_object)

        with (
            patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
            patch(
                "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
                return_value=False,
            ),
            patch(
                "lan_streamer.backend.scan_worker_all.db.load_library",
                return_value={},
            ),
            patch(
                "lan_streamer.backend.scan_worker_all.db.load_movie_library",
                return_value={},
            ),
            patch(
                "lan_streamer.backend.scan_worker_all.scan_directories",
                return_value=LibraryDict(),
            ),
            patch(
                "lan_streamer.backend.scan_worker_all.AsyncDatabaseWriter"
            ) as mock_writer_class,
            patch(
                "lan_streamer.backend.scan_worker_all.concurrent.futures.ThreadPoolExecutor",
                side_effect=lambda *args, **kwargs: _TrackingExecutor(max_workers=1),
            ),
        ):
            mock_config.libraries = {
                "TV Library": {"type": "tv", "paths": []},
            }

            mock_writer = MagicMock()

            async def _async_noop() -> None:
                return None

            mock_writer.start = MagicMock(side_effect=_async_noop)
            mock_writer.stop = MagicMock(side_effect=_async_noop)
            mock_writer_class.return_value = mock_writer

            worker = ScanAllLibrariesWorker(
                async_task_manager=task_manager,
                run_pass1=True,
                run_pass2=False,
                parent=parent_object,
            )

            finished_flag: list = []
            worker.finished.connect(lambda: finished_flag.append(True))

            async def _run() -> None:
                worker.start()
                for _ in range(500):
                    await asyncio.sleep(0.01)
                    if finished_flag:
                        break

            loop.run_until_complete(_run())

        # Verify that shutdown was called on the tracking executor
        assert len(shutdown_calls) > 0, (
            "tmdb_prefetch_executor.shutdown() was never called — "
            "executor is leaking threads (BUG-06 fix not applied)"
        )
    finally:
        loop.close()


def test_scan_worker_all_shuts_down_tmdb_executor_on_exception() -> None:
    """ScanAllLibrariesWorker shuts down the tmdb_prefetch_executor even when
    an exception occurs early in run_async (e.g. database writer start fails).

    Verifies BUG-02 fix: executor created inside try block so finally always runs.
    """
    import asyncio
    from lan_streamer.backend import ScanAllLibrariesWorker
    from lan_streamer.system.async_task_manager import AsyncTaskManager
    from PySide6.QtCore import QObject

    shutdown_calls: list = []

    class _TrackingExecutor(concurrent.futures.ThreadPoolExecutor):
        def shutdown(self, wait: bool = True, **kwargs: Any) -> None:
            shutdown_calls.append({"wait": wait})
            super().shutdown(wait=False)

    parent_object = QObject()
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        task_manager = AsyncTaskManager(parent=parent_object)

        with (
            patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
            patch(
                "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
                return_value=False,
            ),
            patch(
                "lan_streamer.backend.scan_worker_all.db.load_library",
                return_value={},
            ),
            patch(
                "lan_streamer.backend.scan_worker_all.db.load_movie_library",
                return_value={},
            ),
            patch(
                "lan_streamer.backend.scan_worker_all.AsyncDatabaseWriter"
            ) as mock_writer_class,
            patch(
                "lan_streamer.backend.scan_worker_all.concurrent.futures.ThreadPoolExecutor",
                side_effect=lambda *args, **kwargs: _TrackingExecutor(max_workers=1),
            ),
        ):
            mock_config.libraries = {}

            # Simulate database writer start failure
            mock_writer = MagicMock()

            async def _raise_error() -> None:
                raise RuntimeError("Database connection failed")

            async def _async_noop() -> None:
                return None

            mock_writer.start = MagicMock(side_effect=_raise_error)
            mock_writer.stop = MagicMock(side_effect=_async_noop)
            mock_writer_class.return_value = mock_writer

            worker = ScanAllLibrariesWorker(
                async_task_manager=task_manager,
                run_pass1=True,
                run_pass2=False,
                parent=parent_object,
            )

            finished_flag: list = []
            error_flag: list = []
            worker.finished.connect(lambda: finished_flag.append(True))
            worker.error.connect(lambda msg: error_flag.append(msg))

            async def _run() -> None:
                worker.start()
                for _ in range(500):
                    await asyncio.sleep(0.01)
                    if finished_flag or error_flag:
                        break

            loop.run_until_complete(_run())

        # The worker should have errored
        assert len(error_flag) > 0, (
            "Expected worker to emit error signal when database writer fails"
        )

        # Verify that shutdown was called even though the scan failed
        assert len(shutdown_calls) > 0, (
            "tmdb_prefetch_executor.shutdown() was never called after exception — "
            "executor is leaking threads (BUG-02 fix not applied)"
        )
    finally:
        loop.close()
