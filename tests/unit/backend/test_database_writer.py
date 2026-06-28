import queue
import pytest
from unittest.mock import MagicMock, patch
from lan_streamer.backend.database_writer import DatabaseWriteTask, DatabaseWriterThread
from lan_streamer.backend.scan_worker_base import wait_for_database_write_task


def test_database_writer_lifecycle() -> None:
    """Verify that DatabaseWriterThread starts and shuts down cleanly via sentinel."""
    task_queue: queue.Queue = queue.Queue()
    writer = DatabaseWriterThread(task_queue)
    assert writer.daemon is False
    writer.start()

    # Push None sentinel to request stop
    task_queue.put(None)
    writer.join(timeout=2.0)
    assert not writer.is_alive()


def test_database_writer_stop_drains_queued_tasks_before_exit() -> None:
    task_queue: queue.Queue = queue.Queue()
    writer = DatabaseWriterThread(task_queue)

    first_task = DatabaseWriteTask(
        "save_directory_mtime", {"path": "/tmp/a", "mtime": 1}
    )
    second_task = DatabaseWriteTask(
        "save_directory_mtime", {"path": "/tmp/b", "mtime": 2}
    )

    with patch("lan_streamer.db.save_directory_mtime") as mock_save:
        task_queue.put(first_task)
        task_queue.put(second_task)
        writer.start()
        writer.stop()
        writer.join(timeout=2.0)

    assert not writer.is_alive()
    assert first_task.event.is_set()
    assert second_task.event.is_set()
    assert mock_save.call_count == 2


def test_database_writer_executes_task() -> None:
    """Verify database writer executes DB task and triggers callbacks."""
    task_queue: queue.Queue = queue.Queue()
    writer = DatabaseWriterThread(task_queue)
    writer.start()

    mock_callback = MagicMock()
    payload = {
        "library_name": "Lib",
        "series_name": "Series",
        "series_data": {},
        "season_name": "Season 1",
        "season_data": {},
    }

    task = DatabaseWriteTask("save_season", payload, callback=mock_callback)

    with patch(
        "lan_streamer.db.save_season_data", return_value={"test": "stats"}
    ) as mock_save:
        task_queue.put(task)
        task.event.wait(timeout=2.0)

        mock_save.assert_called_once_with("Lib", "Series", {}, "Season 1", {})
        assert task.result == {"test": "stats"}
        mock_callback.assert_called_once_with({"test": "stats"})
        assert task.error is None

    task_queue.put(None)
    writer.join(timeout=2.0)


def test_database_writer_handles_exception() -> None:
    """Verify database writer catches exceptions and sets them on task.error."""
    task_queue: queue.Queue = queue.Queue()
    writer = DatabaseWriterThread(task_queue)
    writer.start()

    payload = {
        "library_name": "Lib",
        "movie_name": "Movie",
        "movie_data": {},
    }

    task = DatabaseWriteTask("save_movie", payload)

    with patch("lan_streamer.db.save_movie_data", side_effect=ValueError("DB Error")):
        task_queue.put(task)
        task.event.wait(timeout=2.0)

        assert task.result is None
        assert isinstance(task.error, ValueError)
        assert str(task.error) == "DB Error"

    task_queue.put(None)
    writer.join(timeout=2.0)


def test_wait_for_database_write_task_success() -> None:
    task = DatabaseWriteTask("action", {})
    task.event.set()  # Complete immediately
    # Should not raise any exception
    wait_for_database_write_task(task, "test task", timeout=1.0)


def test_wait_for_database_write_task_timeout() -> None:
    task = DatabaseWriteTask("action", {})
    # Event is NOT set, should raise TimeoutError
    with pytest.raises(TimeoutError, match="Database write timed out: test task"):
        wait_for_database_write_task(task, "test task", timeout=0.1)


def test_wait_for_database_write_task_warning(caplog) -> None:
    import logging
    from lan_streamer.backend.scan_worker_base import wait_for_database_write_task

    task = DatabaseWriteTask("action", {})

    # We want it to take longer than warning_threshold but complete before timeout.
    # warning_threshold is min(10.0, timeout / 2.0). If timeout = 0.4, warning_threshold = 0.2.
    # We can patch task.event.wait so the first wait (warning_threshold) returns False,
    # and the second wait (remaining) sets the event and returns True.
    original_wait = task.event.wait
    call_count = 0

    def mock_wait(timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return False  # Simulate warning threshold exceeded
        task.event.set()
        return original_wait(timeout)

    task.event.wait = mock_wait

    with caplog.at_level(logging.WARNING):
        wait_for_database_write_task(task, "test warning task", timeout=0.4)

    assert call_count == 2
    assert "Database write is taking longer than expected" in caplog.text
    assert "Action: action" in caplog.text
    assert "Description: test warning task" in caplog.text
