"""Regression tests for ``save_directory_mtime`` / ``get_directory_mtime``.

Critical bug: ``save_directory_mtime`` lacked ``session.commit()`` so every
mtime write was silently rolled back when the SQLAlchemy context manager
closed the session.  These tests guard against regressions by reading back
the value through a *separate* ``get_directory_mtime`` call, which opens its
own fresh session — ensuring data was actually committed to the database.
"""

from lan_streamer.db.library_shared import get_directory_mtime, save_directory_mtime


def test_save_directory_mtime_is_durable() -> None:
    """save_directory_mtime must commit so the value survives a fresh session."""
    path = "/tmp/test_series_commit_regression"
    mtime = 1782369477.605

    save_directory_mtime(path, mtime)

    # Read back via a completely independent get_directory_mtime call,
    # which opens its own session.  If commit() was missing this returns None.
    result = get_directory_mtime(path)
    assert result is not None, (
        "save_directory_mtime did not persist — session.commit() was likely missing"
    )
    assert abs(result - mtime) < 1e-6


def test_save_directory_mtime_updates_existing_record() -> None:
    """Subsequent saves to the same path must update, not duplicate."""
    path = "/tmp/test_series_update_regression"
    first_mtime = 1000.0
    second_mtime = 2000.0

    save_directory_mtime(path, first_mtime)
    assert get_directory_mtime(path) == first_mtime

    # Update — should not raise a UNIQUE constraint error.
    save_directory_mtime(path, second_mtime)
    assert get_directory_mtime(path) == second_mtime


def test_get_directory_mtime_returns_none_for_unknown_path() -> None:
    """get_directory_mtime returns None for a path that has never been saved."""
    result = get_directory_mtime("/tmp/__nonexistent_path_12345__")
    assert result is None


def test_database_writer_saves_directory_mtime() -> None:
    """DatabaseWriterThread must support and correctly execute save_directory_mtime task."""
    import queue
    from lan_streamer.backend.database_writer import (
        DatabaseWriteTask,
        DatabaseWriterThread,
    )
    from lan_streamer.db.library_shared import get_directory_mtime

    path = "/tmp/test_db_writer_mtime"
    mtime = 987654321.0

    task_queue = queue.Queue()
    writer = DatabaseWriterThread(task_queue)
    writer.start()

    try:
        task = DatabaseWriteTask(
            action="save_directory_mtime",
            payload={"path": path, "mtime": mtime},
        )
        task_queue.put(task)
        assert task.event.wait(timeout=5.0), "Task event was not set within timeout"
        assert task.error is None, f"Database write failed with: {task.error}"

        assert get_directory_mtime(path) == mtime
    finally:
        task_queue.put(None)
        writer.join(timeout=5.0)
