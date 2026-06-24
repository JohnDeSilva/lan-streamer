import queue
from unittest.mock import MagicMock, patch
from lan_streamer.backend.database_writer import DatabaseWriteTask, DatabaseWriterThread


def test_database_writer_lifecycle() -> None:
    """Verify that DatabaseWriterThread starts and shuts down cleanly via sentinel."""
    task_queue: queue.Queue = queue.Queue()
    writer = DatabaseWriterThread(task_queue)
    writer.start()

    # Push None sentinel to request stop
    task_queue.put(None)
    writer.join(timeout=2.0)
    assert not writer.is_alive()


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
