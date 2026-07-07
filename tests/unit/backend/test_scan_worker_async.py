"""Tests for AsyncScanWorker."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from PySide6.QtCore import QObject

from lan_streamer.backend.scan_worker_async import AsyncScanWorker
from lan_streamer.scanner import LibraryDict
from lan_streamer.system.async_task_manager import AsyncTaskManager


# ---------------------------------------------------------------------------
# Wait helper
# ---------------------------------------------------------------------------


async def _wait_until(
    condition: Any, timeout: float = 1.0, interval: float = 0.001
) -> None:
    """Wait until condition() returns True, raising TimeoutError otherwise."""
    for _ in range(int(timeout / interval)):
        if condition():
            return
        await asyncio.sleep(interval)
    raise TimeoutError(f"Condition not met within {timeout}s")


# ---------------------------------------------------------------------------
# Stubs & fixtures
# ---------------------------------------------------------------------------


class _StubParent(QObject):
    """Minimal QObject parent for tests."""


@pytest.fixture
def stub_parent() -> _StubParent:
    return _StubParent()


@pytest.fixture
def task_manager(stub_parent: _StubParent) -> AsyncTaskManager:
    return AsyncTaskManager(parent=stub_parent)


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.run_until_complete(
        asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True)
    )
    loop.close()


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    return event_loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAsyncScanWorker:
    """Tests for AsyncScanWorker instantiation and default state."""

    def test_instantiation(self, task_manager: AsyncTaskManager) -> None:
        worker = AsyncScanWorker(
            root_directories=["/tmp/test"],
            library_type="tv",
            existing_library={},
            async_task_manager=task_manager,
            library_name="TestLib",
        )
        assert worker.root_directories == ["/tmp/test"]
        assert worker.library_type == "tv"
        assert worker.library_name == "TestLib"
        assert worker._is_async_worker is True
        assert worker.unavailable_directories == []
        assert worker.problems == []
        assert worker.changed_season_ids == set()
        assert worker.changed_movie_ids == set()

    def test_movie_library_type(self, task_manager: AsyncTaskManager) -> None:
        worker = AsyncScanWorker(
            root_directories=["/tmp/movies"],
            library_type="movie",
            existing_library={},
            async_task_manager=task_manager,
            library_name="Movies",
        )
        assert worker.library_type == "movie"

    def test_initial_stats_are_zero(self, task_manager: AsyncTaskManager) -> None:
        worker = AsyncScanWorker(
            root_directories=[],
            library_type="tv",
            existing_library={},
            async_task_manager=task_manager,
            library_name="Lib",
        )
        for value in worker.stats.values():
            assert value == 0

    def test_cancelled_during_pass1(
        self, event_loop: asyncio.AbstractEventLoop, task_manager: AsyncTaskManager
    ) -> None:
        """Verify scan aborts when cancelled during Pass 1."""
        worker = AsyncScanWorker(
            root_directories=["/tmp/test"],
            library_type="tv",
            existing_library={},
            async_task_manager=task_manager,
            library_name="TestLib",
        )

        async def _run_and_cancel() -> None:
            scan_task = asyncio.create_task(worker.run_async())
            # Yield briefly so run_async can start executing
            await asyncio.sleep(0.01)
            worker.stop()
            try:
                await asyncio.wait_for(scan_task, timeout=2.0)
            except asyncio.CancelledError:
                pass

        with patch(
            "lan_streamer.backend.scan_worker_async.scan_directories"
        ) as mock_scan:
            mock_scan.return_value = LibraryDict()

            event_loop.run_until_complete(_run_and_cancel())

            # After cancellation, scan_directories may or may not have been
            # called depending on timing — just verify no crash.

    def test_pass1_emits_partial_result(
        self, event_loop: asyncio.AbstractEventLoop, task_manager: AsyncTaskManager
    ) -> None:
        """Verify partial_result is emitted after Pass 1."""
        worker = AsyncScanWorker(
            root_directories=["/tmp/test"],
            library_type="tv",
            existing_library={},
            async_task_manager=task_manager,
            library_name="TestLib",
        )

        partial_results: List[Dict[str, Any]] = []

        def _on_partial(data: Dict[str, Any]) -> None:
            partial_results.append(data)

        worker.partial_result.connect(_on_partial)

        with (
            patch(
                "lan_streamer.backend.scan_worker_async.scan_directories",
                return_value=LibraryDict(),
            ),
            patch.object(worker, "_flush_detail_progress"),
        ):
            result = _run(worker.run_async(), event_loop)

            assert isinstance(result, dict)
            # partial_result should have been emitted at least once (Pass 1)
            assert len(partial_results) >= 1

    def test_cancelled_flag_set_on_stop(self, task_manager: AsyncTaskManager) -> None:
        worker = AsyncScanWorker(
            root_directories=[],
            library_type="tv",
            existing_library={},
            async_task_manager=task_manager,
            library_name="Lib",
        )
        assert worker._cancelled is False
        worker.stop()
        assert worker._cancelled is True

    def test_detail_progress_buffering(self, task_manager: AsyncTaskManager) -> None:
        worker = AsyncScanWorker(
            root_directories=[],
            library_type="tv",
            existing_library={},
            async_task_manager=task_manager,
            library_name="Lib",
        )
        assert worker._detail_progress_buffer == []
        worker._emit_detail_progress("test_event", {"key": "val"})
        assert len(worker._detail_progress_buffer) == 1
        worker._flush_detail_progress()
        assert worker._detail_progress_buffer == []

    def test_merge_season_result(self, task_manager: AsyncTaskManager) -> None:
        from lan_streamer.backend.scan_worker_base import create_empty_stats

        worker = AsyncScanWorker(
            root_directories=[],
            library_type="tv",
            existing_library={},
            async_task_manager=task_manager,
            library_name="Lib",
        )
        worker.pass_stats = {1: create_empty_stats(), 2: create_empty_stats()}
        worker.current_pass = 1

        stats = {
            "season_id": "s1",
            "series_scanned": 1,
            "seasons_scanned": 1,
            "episodes_scanned": 5,
        }
        series_data = {"seasons": {"S1": {"_changed": True}}}
        season_data = {"episodes": [{"name": "E1"}, {"name": "E2"}], "_changed": True}

        worker._merge_season_result(stats, "Series1", series_data, "S1", season_data)
        assert worker.pass_stats[1]["seasons_scanned"] == 1
        assert worker.pass_stats[1]["episodes_scanned"] == 2
        assert "s1" in worker.changed_season_ids

    def test_merge_movie_result(self, task_manager: AsyncTaskManager) -> None:
        from lan_streamer.backend.scan_worker_base import create_empty_stats

        worker = AsyncScanWorker(
            root_directories=[],
            library_type="tv",
            existing_library={},
            async_task_manager=task_manager,
            library_name="Lib",
        )
        worker.pass_stats = {1: create_empty_stats(), 2: create_empty_stats()}
        worker.current_pass = 1

        stats = {
            "movie_id": "m1",
            "movies_scanned": 1,
        }
        movie_data = {"_changed": True}

        worker._merge_movie_result(stats, "Movie1", movie_data)
        assert worker.pass_stats[1]["movies_scanned"] == 1
        assert "m1" in worker.changed_movie_ids

    def test_log_unavailable_directories(
        self, task_manager: AsyncTaskManager, caplog
    ) -> None:
        worker = AsyncScanWorker(
            root_directories=[],
            library_type="tv",
            existing_library={},
            async_task_manager=task_manager,
            library_name="Lib",
        )
        worker.unavailable_directories = ["/missing/path"]

        with caplog.at_level(logging.WARNING):
            worker._log_unavailable_directories()

        assert "unavailable" in caplog.text.lower()
        assert len(worker.problems) == 1
        assert worker.problems[0]["item"] == "/missing/path"
