import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal

from lan_streamer import db
from lan_streamer.system.config import config
from lan_streamer.providers.jellyfin import jellyfin_client
from lan_streamer.scanner import scan_movie, scan_series
from lan_streamer.services.metadata_updates import clean_series_data
from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger("lan_streamer.backend")


class RefreshSeriesWorker(AsyncWorkerBase):
    """Refreshes metadata for a single series or movie by scanning its folder directly."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        library_name: str,
        item_name: str,
        library_type: str,
        root_directories: List[str],
        existing_library: Dict[str, Any],
        async_task_manager: Optional[AsyncTaskManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.library_name: str = library_name
        self.item_name: str = item_name
        self.library_type: str = library_type
        self.root_directories: List[str] = root_directories
        self.existing_library: Dict[str, Any] = existing_library

    async def run_async(self) -> Dict[str, Any]:
        logger.info(
            f"RefreshSeriesWorker starting for item: {self.item_name} in library {self.library_name}"
        )
        # Find the path of the specific series/movie directory within the root directories
        target_dir: Optional[Path] = None
        for root_dir in self.root_directories:
            potential_dir = Path(root_dir) / self.item_name
            if potential_dir.exists() and potential_dir.is_dir():
                target_dir = potential_dir
                break

        if not target_dir:
            raise ValueError(f"Could not find directory for '{self.item_name}'")

        # Run blocking scan and save operations in thread executor
        updated_library = await asyncio.to_thread(self._do_refresh, target_dir)

        logger.info("RefreshSeriesWorker finished successfully")
        return updated_library

    def _do_refresh(self, target_dir: Path) -> Dict[str, Any]:
        # Fetch Jellyfin correlation data if configured
        jellyfin_data: Optional[Dict[str, Any]] = None
        if jellyfin_client.is_configured():
            jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

        existing_item = self.existing_library.get(self.item_name)
        # We want to refresh this item from TMDB, bypassing lock.
        # So we pass tmdb_series/tmdb_movie = None, and single_item_refresh = True.
        if self.library_type == "movie":
            item_data = scan_movie(
                target_dir,
                tmdb_movie=None,
                jellyfin_data=jellyfin_data,
                manual_jellyfin_id=None,
                existing_movie_data=existing_item,
                force_refresh=True,
                cleanup=False,
                single_item_refresh=True,
            )
        else:
            show_future = config.libraries.get(self.library_name, {}).get(
                "show_future_episodes", True
            )
            item_data = scan_series(
                target_dir,
                tmdb_series=None,
                jellyfin_data=jellyfin_data,
                manual_jellyfin_id=None,
                existing_series_data=existing_item,
                force_refresh=True,
                cleanup=False,
                single_item_refresh=True,
                show_future_episodes=show_future,
            )

        if not item_data:
            raise ValueError(f"Scan failed for '{self.item_name}'")

        # Update the existing library dictionary with the new item data
        updated_library = self.existing_library.copy()
        if self.library_type != "movie":
            item_data = clean_series_data(item_data)
        updated_library[self.item_name] = item_data

        # Persist back to DB
        db.save_library(self.library_name, updated_library)
        return updated_library

    def run(self) -> None:
        """Synchronous compatibility fallback for tests."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_wrapper())
        finally:
            loop.close()
