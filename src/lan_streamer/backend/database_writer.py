import logging
import queue
import threading
from typing import Any, Callable, Dict, Optional

import lan_streamer.db as database_module

logger = logging.getLogger("lan_streamer.backend")


class DatabaseWriteTask:
    """Represents a database write request submitted to the database queue."""

    def __init__(
        self,
        action: str,
        payload: Dict[str, Any],
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """Initialise a database write task.

        Args:
            action: Action string ("save_season", "save_movie", etc.).
            payload: Parameters needed for database action.
            callback: Optional callback triggered on success.
        """
        self.action: str = action
        self.payload: Dict[str, Any] = payload
        self.callback: Optional[Callable[[Dict[str, Any]], None]] = callback
        self.event: threading.Event = threading.Event()
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[Exception] = None


class DatabaseWriterThread(threading.Thread):
    """A dedicated worker thread processing database write tasks sequentially."""

    def __init__(self, task_queue: queue.Queue) -> None:
        """Initialise the writer thread.

        Args:
            task_queue: A thread-safe queue containing DatabaseWriteTask items.
        """
        super().__init__(name="DatabaseWriterThread", daemon=False)
        self.task_queue: queue.Queue = task_queue
        self._stop_event: threading.Event = threading.Event()

    def stop(self) -> None:
        """Signal the writer thread to stop after queued writes are drained."""
        self._stop_event.set()
        self.task_queue.put(None)

    def run(self) -> None:
        """Loop continuously, processing tasks from the queue sequentially."""
        logger.info("DatabaseWriterThread started execution loop.")
        while True:
            try:
                task: Optional[DatabaseWriteTask] = self.task_queue.get(timeout=0.5)
            except queue.Empty:
                if self._stop_event.is_set():
                    logger.info("DatabaseWriterThread stopped with an empty queue.")
                    break
                continue
            if task is None:
                # Sentinel to stop processing
                self.task_queue.task_done()
                logger.info("DatabaseWriterThread received sentinel; stopping.")
                break

            try:
                task.result = self._execute_write_task(task.action, task.payload)
                if task.callback and task.result is not None:
                    task.callback(task.result)
            except Exception as error:
                logger.exception(
                    f"DatabaseWriterThread task '{task.action}' execution failed"
                )
                task.error = error
            finally:
                task.event.set()
                self.task_queue.task_done()

    def _execute_write_task(
        self, action: str, payload: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Map action to the corresponding database function and run it."""
        if action == "save_season":
            return database_module.save_season_data(
                payload["library_name"],
                payload["series_name"],
                payload["series_data"],
                payload["season_name"],
                payload["season_data"],
            )
        elif action == "save_movie":
            return database_module.save_movie_data(
                payload["library_name"],
                payload["movie_name"],
                payload["movie_data"],
            )
        elif action == "save_library":
            # Returns stats or empty dictionary
            stats: Dict[str, Any] = database_module.save_library(
                payload["library_name"], payload["library_data"]
            )
            return stats
        elif action == "save_movie_library":
            # Returns stats or empty dictionary
            stats = database_module.save_movie_library(
                payload["library_name"], payload["library_data"]
            )
            return stats
        elif action == "save_directory_mtime":
            database_module.save_directory_mtime(payload["path"], payload["mtime"])
            return {}
        elif action == "update_items_runtime_batch":
            database_module.update_items_runtime_batch(payload["updates"])
            return {}
        else:
            raise ValueError(f"Unknown database write action: {action}")
