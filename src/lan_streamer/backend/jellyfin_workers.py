import asyncio
import logging
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal

from lan_streamer import db
from lan_streamer.providers.jellyfin import jellyfin_client
from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger("lan_streamer.backend")


class JellyfinPullWorker(AsyncWorkerBase):
    """Pulls watch history from Jellyfin and syncs it to the local DB."""

    finished = Signal(int)  # number of episodes updated
    error = Signal(str)

    def __init__(
        self,
        async_task_manager: Optional[AsyncTaskManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)

    async def run_async(self) -> int:
        logger.info("JellyfinPullWorker starting run")
        watched_identifiers, watched_paths, watched_names = await asyncio.to_thread(
            jellyfin_client.fetch_watched_episodes
        )
        updated_count: int = await asyncio.to_thread(
            db.sync_watched_from_jellyfin_data,
            watched_identifiers,
            watched_paths,
            watched_names,
        )
        logger.info(f"JellyfinPullWorker finished, updated {updated_count} episodes")
        return updated_count


class JellyfinPushWorker(AsyncWorkerBase):
    """Pushes all local watched state to Jellyfin."""

    finished = Signal(int)  # number of episodes pushed
    error = Signal(str)

    def __init__(
        self,
        async_task_manager: Optional[AsyncTaskManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)

    async def run_async(self) -> int:
        logger.info("JellyfinPushWorker starting run")
        episodes_list: List[Dict[str, Any]] = await asyncio.to_thread(
            db.get_all_episodes_with_jellyfin_id
        )
        watched_episodes = [ep for ep in episodes_list if ep.get("watched")]
        total_episodes = len(watched_episodes)
        logger.info(
            f"JellyfinPushWorker pushing {total_episodes} watched episodes to Jellyfin"
        )
        pushed_count = await asyncio.to_thread(
            self._push_loop, watched_episodes, total_episodes
        )
        logger.info(f"JellyfinPushWorker finished, pushed {pushed_count} episodes")
        return pushed_count

    def _push_loop(
        self, watched_episodes: List[Dict[str, Any]], total_episodes: int
    ) -> int:
        pushed_count = 0
        for episode_record in watched_episodes:
            if self._cancelled:
                logger.info("JellyfinPushWorker cancelled during push loop.")
                break
            jellyfin_client.set_watched_status(episode_record["jellyfin_id"], True)
            pushed_count += 1
            if pushed_count % 50 == 0:
                logger.debug(
                    f"JellyfinPushWorker progress: {pushed_count}/{total_episodes} episodes pushed"
                )
        return pushed_count
