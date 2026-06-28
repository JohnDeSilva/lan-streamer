import asyncio
import logging
from typing import Dict, Any, List, Optional, Set
from PySide6.QtCore import QObject, Signal

from lan_streamer import db
from lan_streamer.scanner.file_property_scanner import get_detailed_file_info
from lan_streamer.backend.database_writer import (
    AsyncDatabaseWriter,
    DatabaseWriterThread,  # noqa: F401
)
from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger("lan_streamer.backend")


def _produce_item_update(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Probe a single item and return its update dict, or ``None`` if no
    new data was extracted."""
    file_path = item["path"]
    info = get_detailed_file_info(file_path)
    extracted_runtime = info.get("runtime")
    runtime_val = extracted_runtime if extracted_runtime is not None else 0

    has_tech_info = (
        (info.get("video_codec") and info.get("video_codec") != "Unknown")
        or (info.get("resolution") and info.get("resolution") != "Unknown")
        or ((info.get("bit_rate") or 0) > 0)
    )

    if not (runtime_val > 0 or has_tech_info):
        return None

    return {
        "item_identifier": item["id"],
        "item_type": item["type"],
        "runtime_minutes": extracted_runtime,
        "video_codec": info.get("video_codec"),
        "resolution": info.get("resolution"),
        "audio_tracks": info.get("audio_tracks"),
        "subtitle_tracks": info.get("subtitle_tracks"),
        "bit_rate": info.get("bit_rate"),
        "size_bytes": info.get("size_bytes"),
    }


class FilePropertyExtractionWorker(AsyncWorkerBase):
    """Processes videos in parallel (by library) to extract missing runtimes
    and technical metadata.
    """

    progress_updated = Signal(int, int)
    finished = Signal(int)
    error = Signal(str)

    _BATCH_INTERVAL: int = 100

    def __init__(
        self,
        async_task_manager: Optional[AsyncTaskManager] = None,
        changed_season_ids: Optional[Set[str]] = None,
        changed_movie_ids: Optional[Set[str]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.changed_season_ids: Optional[Set[str]] = changed_season_ids
        self.changed_movie_ids: Optional[Set[str]] = changed_movie_ids
        self._lock: asyncio.Lock = asyncio.Lock()
        self._total_count: int = 0
        self._completed_count: int = 0
        self._last_batch_emitted: int = 0
        self._database_writer: Optional[AsyncDatabaseWriter] = None

    async def _emit_progress_batch(self) -> None:
        """Emit progress_updated signal if batch interval has been reached."""
        async with self._lock:
            completed = self._completed_count
            total = self._total_count
            if completed - self._last_batch_emitted < self._BATCH_INTERVAL:
                return
            self._last_batch_emitted = completed
        self.progress_updated.emit(completed, total)

    async def run_async(self) -> int:
        self._database_writer = AsyncDatabaseWriter()
        await self._database_writer.start()

        try:
            logger.info("FilePropertyExtractionWorker starting run")
            logger.info(
                "Starting Pass 3 (Technical Metadata Extraction) for candidates..."
            )

            items_list: List[Dict[str, Any]] = await asyncio.to_thread(
                db.get_items_missing_runtime
            )

            # Filter out items that already have complete metadata
            candidates: List[Dict[str, Any]] = []
            for item in items_list:
                if item["type"] == "episode":
                    if (
                        self.changed_season_ids is not None
                        and item.get("season_id") not in self.changed_season_ids
                    ):
                        continue
                else:
                    if (
                        self.changed_movie_ids is not None
                        and item.get("id") not in self.changed_movie_ids
                    ):
                        continue

                candidates.append(item)

            self._total_count = len(candidates)
            logger.info(
                f"Found {self._total_count} candidates "
                "for background technical extraction"
            )
            self._completed_count = 0
            self._last_batch_emitted = 0
            updated_count = 0

            if self._total_count == 0:
                self.progress_updated.emit(0, 0)
                self.finished.emit(0)
                return 0

            # Group candidates by library
            items_by_library: Dict[str, List[Dict[str, Any]]] = {}
            for item in candidates:
                library = item.get("library_name") or "_unknown"
                items_by_library.setdefault(library, []).append(item)

            # Process each library concurrently
            async def process_library(library_items: List[Dict[str, Any]]) -> int:
                local_updated = 0

                # Group episodes by season
                episodes_by_season: Dict[Optional[str], List[Dict[str, Any]]] = {}
                movies: List[Dict[str, Any]] = []
                for item in library_items:
                    if item["type"] == "episode":
                        season_id = item.get("season_id")
                        episodes_by_season.setdefault(season_id, []).append(item)
                    else:
                        movies.append(item)

                # Process episodes by season (sequential within library)
                for season_id, season_episodes in episodes_by_season.items():
                    if self.isInterruptionRequested():
                        logger.info(
                            "FilePropertyExtractionWorker: cancelled. Stopping season processing."
                        )
                        break

                    season_updates: List[Dict[str, Any]] = []
                    for ep in season_episodes:
                        if self.isInterruptionRequested():
                            break
                        update = await asyncio.to_thread(_produce_item_update, ep)
                        if update:
                            season_updates.append(update)
                            local_updated += 1

                        async with self._lock:
                            self._completed_count += 1

                    await self._emit_progress_batch()

                    if season_updates and not self.isInterruptionRequested():
                        logger.info(
                            f"Committing batch write for season "
                            f"{season_id} ({len(season_updates)} episodes)"
                        )
                        assert self._database_writer is not None
                        task = await self._database_writer.submit(
                            "update_items_runtime_batch",
                            {"updates": season_updates},
                        )
                        assert task.async_event is not None
                        await task.async_event.wait()
                        if task.error:
                            raise task.error

                # Process movies individually
                for movie in movies:
                    if self.isInterruptionRequested():
                        logger.info(
                            "FilePropertyExtractionWorker: cancelled. Stopping movie processing."
                        )
                        break

                    update = await asyncio.to_thread(_produce_item_update, movie)
                    if update:
                        logger.info(f"Committing write for movie {movie['path']}")
                        assert self._database_writer is not None
                        task = await self._database_writer.submit(
                            "update_items_runtime_batch",
                            {"updates": [update]},
                        )
                        assert task.async_event is not None
                        await task.async_event.wait()
                        if task.error:
                            raise task.error
                        local_updated += 1

                    async with self._lock:
                        self._completed_count += 1

                    await self._emit_progress_batch()

                return local_updated

            # Run tasks concurrently
            tasks = [process_library(items) for items in items_by_library.values()]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, BaseException):
                    logger.exception("Error in process_library task", exc_info=res)
                    raise res
                else:
                    updated_count += res

            self.progress_updated.emit(self._completed_count, self._total_count)
            logger.info(
                f"FilePropertyExtractionWorker finished, updated "
                f"{updated_count} of {self._total_count} items"
            )
            return updated_count
        except Exception as exception_instance:
            logger.exception("FilePropertyExtractionWorker failed")
            raise exception_instance
        finally:
            if self._database_writer is not None:
                await self._database_writer.stop()

    def run(self) -> None:
        """Synchronous compatibility fallback for tests."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_wrapper())
        finally:
            loop.close()
