from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, Dict, Optional

import lan_streamer.db as database_module

logger = logging.getLogger("lan_streamer.backend")


class DatabaseWriteTask:
    """Represents a database write request submitted to the database queue.

    Supports both sync (``threading.Event``) and async (``asyncio.Event``)
    completion signalling.
    """

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
        self.async_event: asyncio.Event | None = None
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[Exception] = None


class AsyncDatabaseWriter:
    """Asyncio-based database writer that processes write tasks sequentially.

    Replaces :class:`DatabaseWriterThread` in async contexts.  Uses an
    ``asyncio.Queue`` and runs the processing loop as a background coroutine.

    Usage::

        writer = AsyncDatabaseWriter()
        task = await writer.submit("save_library", {"library_name": ...})
        # … task.result is populated when done
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[DatabaseWriteTask | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Launch the background processing coroutine."""
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run())

    async def stop(self) -> None:
        """Signal the writer to stop after draining queued writes."""
        await self._queue.put(None)
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=30.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

    async def submit(self, action: str, payload: Dict[str, Any]) -> DatabaseWriteTask:
        """Enqueue a write task and return it immediately.

        The caller can ``await task.async_event.wait()`` to block until
        the write completes.
        """
        task = DatabaseWriteTask(action=action, payload=payload)
        task.async_event = asyncio.Event()
        await self._queue.put(task)
        return task

    def sync_submit(
        self, action: str, payload: Dict[str, Any], loop: asyncio.AbstractEventLoop
    ) -> DatabaseWriteTask:
        """Synchronous submit for use from scanner callbacks in other threads.

        Puts the task onto the async queue via ``run_coroutine_threadsafe``
        and blocks the calling thread on ``task.event.wait()`` until the
        async consumer processes it.

        Args:
            action: Action string.
            payload: Parameters for the action.
            loop: The asyncio event loop (``asyncio.get_running_loop()``
                from the owning coroutine).

        Returns:
            The completed ``DatabaseWriteTask``.
        """
        task = DatabaseWriteTask(action=action, payload=payload)
        task.async_event = asyncio.Event()
        asyncio.run_coroutine_threadsafe(self._queue.put(task), loop)
        task.event.wait(timeout=60.0)
        return task

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
            stats: Dict[str, Any] = database_module.save_library(
                payload["library_name"], payload["library_data"]
            )
            return stats
        elif action == "save_movie_library":
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
        elif action == "fetch_and_store_series_credits_and_images":
            from lan_streamer.services import metadata_cast, metadata_images

            metadata_cast.fetch_and_store_series_credits(
                payload["series_id"], payload["tmdb_id"]
            )
            metadata_images.fetch_and_store_series_images(
                payload["series_id"], payload["tmdb_id"]
            )
            return {}
        elif action == "fetch_and_store_movie_credits_and_images":
            from lan_streamer.services import metadata_cast, metadata_images

            metadata_cast.fetch_and_store_movie_credits(
                payload["movie_id"], payload["tmdb_id"]
            )
            metadata_images.fetch_and_store_movie_images(
                payload["movie_id"], payload["tmdb_id"]
            )
            return {}
        else:
            raise ValueError(f"Unknown database write action: {action}")

    def _execute_batch(self, batch: list[DatabaseWriteTask]) -> None:
        """Execute a batch of write tasks in sequence within a single thread."""
        for task in batch:
            try:
                task.result = self._execute_write_task(task.action, task.payload)
                if task.callback and task.result is not None:
                    task.callback(task.result)
            except Exception as error:
                logger.exception(
                    f"AsyncDatabaseWriter task '{task.action}' execution failed"
                )
                task.error = error

    # Long-running actions (HTTP calls) are not batched with quick DB writes
    # to avoid blocking the fast tasks behind network latency.
    _EXCLUSIVE_ACTIONS = frozenset(
        {
            "fetch_and_store_series_credits_and_images",
            "fetch_and_store_movie_credits_and_images",
        }
    )

    async def _run(self) -> None:
        """Background coroutine: drain the queue and execute writes in batches.

        Tasks are collected into batches of up to 5 and dispatched together
        via a single ``asyncio.to_thread`` call, reducing thread creation
        overhead and SQLite transaction costs.

        Long-running HTTP actions (fetch_and_store_*) are processed
        individually to avoid blocking quick DB writes behind network I/O.
        """
        logger.info("AsyncDatabaseWriter started.")
        while True:
            task = await self._queue.get()
            if task is None:
                logger.info("AsyncDatabaseWriter received sentinel; stopping.")
                self._queue.task_done()
                break

            if task.action in self._EXCLUSIVE_ACTIONS:
                await asyncio.to_thread(self._execute_batch, [task])
                if task.async_event is not None:
                    task.async_event.set()
                if task.event is not None:
                    task.event.set()
                self._queue.task_done()
                continue

            batch: list[DatabaseWriteTask] = [task]
            saw_sentinel = False
            while len(batch) < 5 and not saw_sentinel:
                try:
                    next_task = self._queue.get_nowait()
                    if next_task is None:
                        self._queue.task_done()
                        saw_sentinel = True
                    else:
                        batch.append(next_task)
                except asyncio.QueueEmpty:
                    break

            await asyncio.to_thread(self._execute_batch, batch)
            for bt in batch:
                if bt.async_event is not None:
                    bt.async_event.set()
                if bt.event is not None:
                    bt.event.set()
                self._queue.task_done()

            if saw_sentinel:
                break
