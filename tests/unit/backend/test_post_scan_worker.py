import asyncio
from typing import Any
from unittest.mock import MagicMock, patch
import pytest

from lan_streamer.backend.post_scan_worker import PostScanWorker
from lan_streamer.services.smart_row_service import SmartRowService
from lan_streamer.system.async_task_manager import AsyncTaskManager


@pytest.fixture()
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    return event_loop.run_until_complete(coro)


class TestPostScanWorker:
    """Tests for the PostScanWorker."""

    def test_run_sync_tv(self) -> None:
        """Verify synchronous execution for TV library."""
        mock_smart_row_service = MagicMock(spec=SmartRowService)
        mock_smart_row_service.rebuild_for_libraries.return_value = ["hash1", "hash2"]

        worker = PostScanWorker(
            library_name="TestTV",
            library_data={"series": {}},
            library_type="tv",
            smart_row_service=mock_smart_row_service,
            async_task_manager=None,
        )

        # Trigger start - since no event loop runs, it should run synchronously
        mock_finished = MagicMock()
        worker.finished.connect(mock_finished)
        worker.start()

        mock_finished.assert_called_once_with(
            {
                "library_name": "TestTV",
                "changed_hashes": ["hash1", "hash2"],
            }
        )

    def test_run_sync_movie(self) -> None:
        """Verify synchronous execution for Movie library."""
        mock_smart_row_service = MagicMock(spec=SmartRowService)
        mock_smart_row_service.rebuild_for_libraries.return_value = ["hash3"]

        worker = PostScanWorker(
            library_name="TestMovie",
            library_data={"movies": {}},
            library_type="movie",
            smart_row_service=mock_smart_row_service,
            async_task_manager=None,
        )

        with (
            patch("lan_streamer.db.save_movie_library") as mock_save_movie,
            patch("lan_streamer.db.save_library") as mock_save_tv,
        ):
            worker.start()
            mock_save_movie.assert_called_once_with("TestMovie", {"movies": {}})
            mock_save_tv.assert_not_called()

        mock_smart_row_service.rebuild_for_libraries.assert_called_once_with(
            ["TestMovie"]
        )

    def test_run_async_tv(self, event_loop: asyncio.AbstractEventLoop) -> None:
        """Verify asynchronous execution for TV library."""
        mock_smart_row_service = MagicMock(spec=SmartRowService)
        mock_smart_row_service.rebuild_for_libraries.return_value = ["hash_async"]

        async_task_manager = AsyncTaskManager()

        worker = PostScanWorker(
            library_name="AsyncTV",
            library_data={"series_async": {}},
            library_type="tv",
            smart_row_service=mock_smart_row_service,
            async_task_manager=async_task_manager,
        )

        async def run() -> None:
            # We connect to finished to assert
            future = asyncio.Future()
            worker.finished.connect(future.set_result)
            worker.start()
            result = await asyncio.wait_for(future, timeout=2.0)
            assert result == {
                "library_name": "AsyncTV",
                "changed_hashes": ["hash_async"],
            }
            # Clean up task manager
            task = async_task_manager.stop_all()
            if task is not None:
                await task

        with (
            patch("lan_streamer.db.save_library") as mock_save_tv,
            patch("lan_streamer.db.save_movie_library") as mock_save_movie,
        ):
            _run(run(), event_loop)
            mock_save_tv.assert_called_once_with("AsyncTV", {"series_async": {}})
            mock_save_movie.assert_not_called()

        mock_smart_row_service.rebuild_for_libraries.assert_called_once_with(
            ["AsyncTV"]
        )
