import logging
from typing import List, Dict, Any
from PySide6.QtCore import QThread, Signal

from lan_streamer.backend.proxy import db, jellyfin_client

logger = logging.getLogger("lan_streamer.backend")


class JellyfinPullWorker(QThread):
    """Pulls watch history from Jellyfin and syncs it to the local DB."""

    finished = Signal(int)  # number of episodes updated
    error = Signal(str)

    def run(self) -> None:
        try:
            logger.info("JellyfinPullWorker starting run")
            watched_identifiers, watched_paths, watched_names = (
                jellyfin_client.fetch_watched_episodes()
            )
            updated_count: int = db.sync_watched_from_jellyfin_data(
                watched_identifiers, watched_paths, watched_names
            )
            logger.info(
                f"JellyfinPullWorker finished, updated {updated_count} episodes"
            )
            self.finished.emit(updated_count)
        except Exception as exc:
            logger.exception("JellyfinPullWorker failed")
            self.error.emit(str(exc))


class JellyfinPushWorker(QThread):
    """Pushes all local watched state to Jellyfin."""

    finished = Signal(int)  # number of episodes pushed
    error = Signal(str)

    def run(self) -> None:
        try:
            logger.info("JellyfinPushWorker starting run")
            episodes_list: List[Dict[str, Any]] = db.get_all_episodes_with_jellyfin_id()
            watched_episodes = [ep for ep in episodes_list if ep.get("watched")]
            total_episodes = len(watched_episodes)
            logger.info(
                f"JellyfinPushWorker pushing {total_episodes} watched episodes to Jellyfin"
            )
            pushed_count: int = 0
            for episode_record in watched_episodes:
                jellyfin_client.set_watched_status(episode_record["jellyfin_id"], True)
                pushed_count += 1
                if pushed_count % 50 == 0:
                    logger.debug(
                        f"JellyfinPushWorker progress: {pushed_count}/{total_episodes} episodes pushed"
                    )
            logger.info(f"JellyfinPushWorker finished, pushed {pushed_count} episodes")
            self.finished.emit(pushed_count)
        except Exception as exc:
            logger.exception("JellyfinPushWorker failed")
            self.error.emit(str(exc))
