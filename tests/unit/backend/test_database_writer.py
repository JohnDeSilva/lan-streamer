import asyncio
from typing import Any
import pytest
from unittest.mock import MagicMock, patch
from lan_streamer.backend.database_writer import (
    AsyncDatabaseWriter,
    DatabaseWriteTask,
)


@pytest.fixture()
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    return event_loop.run_until_complete(coro)


class TestAsyncDatabaseWriter:
    """Tests for the asyncio-based database writer."""

    def test_lifecycle(self, event_loop: asyncio.AbstractEventLoop) -> None:
        """Verify start and stop without any tasks."""
        writer = AsyncDatabaseWriter()

        async def run() -> None:
            await writer.start()
            await writer.stop()

        _run(run(), event_loop)

    def test_execute_task(self, event_loop: asyncio.AbstractEventLoop) -> None:
        """Verify the writer executes a task and populates result."""
        writer = AsyncDatabaseWriter()
        payload = {"path": "/tmp/test", "mtime": 42.0}

        async def run() -> None:
            await writer.start()
            task = await writer.submit("save_directory_mtime", payload)
            await asyncio.wait_for(task.async_event.wait(), timeout=2.0)
            assert task.result == {}
            assert task.error is None
            await writer.stop()

        with patch(
            "lan_streamer.backend.database_writer.database_module.save_directory_mtime"
        ) as mock_save:
            _run(run(), event_loop)

        mock_save.assert_called_once_with("/tmp/test", 42.0)

    def test_execute_task_with_callback(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Verify the writer invokes the optional callback."""
        writer = AsyncDatabaseWriter()
        mock_callback = MagicMock()

        async def run() -> None:
            await writer.start()
            task = DatabaseWriteTask(
                "save_directory_mtime",
                {"path": "/tmp/a", "mtime": 1.0},
                callback=mock_callback,
            )
            task.async_event = asyncio.Event()
            await writer._queue.put(task)
            await asyncio.wait_for(task.async_event.wait(), timeout=2.0)
            assert task.result == {}
            mock_callback.assert_called_once_with({})
            await writer.stop()

        with patch("lan_streamer.db.save_directory_mtime"):
            _run(run(), event_loop)

    def test_handles_exception(self, event_loop: asyncio.AbstractEventLoop) -> None:
        """Verify the writer catches exceptions and sets task.error."""
        writer = AsyncDatabaseWriter()

        async def run() -> None:
            await writer.start()
            task = await writer.submit(
                "save_movie", {"library_name": "L", "movie_name": "M", "movie_data": {}}
            )
            await asyncio.wait_for(task.async_event.wait(), timeout=2.0)
            assert task.result is None
            assert isinstance(task.error, ValueError)
            assert str(task.error) == "DB Error"
            await writer.stop()

        with patch(
            "lan_streamer.backend.database_writer.database_module.save_movie_data",
            side_effect=ValueError("DB Error"),
        ):
            _run(run(), event_loop)

    def test_drains_queued_tasks_on_stop(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Verify stop waits for queued tasks to complete."""
        writer = AsyncDatabaseWriter()

        async def run() -> None:
            await writer.start()
            task1 = await writer.submit(
                "save_directory_mtime", {"path": "/tmp/a", "mtime": 1.0}
            )
            task2 = await writer.submit(
                "save_directory_mtime", {"path": "/tmp/b", "mtime": 2.0}
            )
            await writer.stop()
            assert task1.async_event.is_set()
            assert task2.async_event.is_set()

        with patch(
            "lan_streamer.backend.database_writer.database_module.save_directory_mtime"
        ) as mock_save:
            _run(run(), event_loop)

        assert mock_save.call_count == 2

    def test_stop_without_start(self, event_loop: asyncio.AbstractEventLoop) -> None:
        """Verify stop on unstarted writer does not raise."""
        writer = AsyncDatabaseWriter()

        async def run() -> None:
            await writer.stop()

        _run(run(), event_loop)

    def test_submit_returns_task_immediately(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Verify submit returns immediately without waiting for execution."""
        writer = AsyncDatabaseWriter()

        async def run() -> None:
            await writer.start()
            # Submit but do NOT await the event
            task = await writer.submit(
                "save_directory_mtime", {"path": "/tmp/x", "mtime": 99.0}
            )
            assert isinstance(task, DatabaseWriteTask)
            assert task.action == "save_directory_mtime"
            assert task.payload == {"path": "/tmp/x", "mtime": 99.0}
            assert task.async_event is not None
            # Wait for completion to avoid lingering tasks
            await asyncio.wait_for(task.async_event.wait(), timeout=2.0)
            await writer.stop()

        with patch(
            "lan_streamer.backend.database_writer.database_module.save_directory_mtime"
        ):
            _run(run(), event_loop)

    def test_execute_fetch_and_store_series_credits_and_images(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Verify the writer executes fetch_and_store_series_credits_and_images."""
        writer = AsyncDatabaseWriter()
        payload = {"series_id": "series-123", "tmdb_id": 456}

        async def run() -> None:
            await writer.start()
            task = await writer.submit(
                "fetch_and_store_series_credits_and_images", payload
            )
            await asyncio.wait_for(task.async_event.wait(), timeout=2.0)
            assert task.result == {}
            assert task.error is None
            await writer.stop()

        with (
            patch(
                "lan_streamer.services.metadata_cast.fetch_and_store_series_credits"
            ) as mock_cast,
            patch(
                "lan_streamer.services.metadata_images.fetch_and_store_series_images"
            ) as mock_images,
        ):
            _run(run(), event_loop)

        mock_cast.assert_called_once_with("series-123", 456)
        mock_images.assert_called_once_with("series-123", 456)

    def test_execute_fetch_and_store_movie_credits_and_images(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Verify the writer executes fetch_and_store_movie_credits_and_images."""
        writer = AsyncDatabaseWriter()
        payload = {"movie_id": "movie-123", "tmdb_id": 789}

        async def run() -> None:
            await writer.start()
            task = await writer.submit(
                "fetch_and_store_movie_credits_and_images", payload
            )
            await asyncio.wait_for(task.async_event.wait(), timeout=2.0)
            assert task.result == {}
            assert task.error is None
            await writer.stop()

        with (
            patch(
                "lan_streamer.services.metadata_cast.fetch_and_store_movie_credits"
            ) as mock_cast,
            patch(
                "lan_streamer.services.metadata_images.fetch_and_store_movie_images"
            ) as mock_images,
        ):
            _run(run(), event_loop)

        mock_cast.assert_called_once_with("movie-123", 789)
        mock_images.assert_called_once_with("movie-123", 789)
