import logging
import time
from typing import Any
from sqlalchemy import select

from lan_streamer.db.models import (
    Series,
    Season,
    MediaFile,
)

logger = logging.getLogger("lan_streamer.db.queries")


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


def _trigger_mal_push_async(anime_id: int, num_watched_episodes: int) -> None:
    """Helper to asynchronously push watch status to MyAnimeList."""
    from lan_streamer.providers.myanimelist import trigger_mal_push_async

    trigger_mal_push_async(anime_id, num_watched_episodes)


def update_episode_watched_status(path: str, watched: bool) -> None:
    try:
        logger.debug(
            f"Executing DB update_episode_watched_status: path={path}, watched={watched}"
        )
        logger.info(f"Updating watched status for {path} to {watched}")
        with get_session() as session:
            from lan_streamer.db.models import PlaybackState

            mf = session.scalars(
                select(MediaFile).where(MediaFile.path == path)
            ).first()
            if mf:
                for ep in mf.episodes:
                    if not ep.playback_state:
                        ep.playback_state = PlaybackState(episode_id=ep.id)
                    ep.playback_state.watched = watched
                    if watched:
                        ep.playback_state.last_played_at = int(time.time())
                        if ep.myanimelist_anime_id and ep.myanimelist_episode_number:
                            _trigger_mal_push_async(
                                ep.myanimelist_anime_id,
                                ep.myanimelist_episode_number,
                            )
                for mv in mf.movies:
                    if not mv.playback_state:
                        mv.playback_state = PlaybackState(movie_id=mv.id)
                    mv.playback_state.watched = watched
                    if watched:
                        mv.playback_state.last_played_at = int(time.time())
                        if mv.myanimelist_anime_id:
                            _trigger_mal_push_async(mv.myanimelist_anime_id, 1)
                logger.debug(
                    f"Updated watched status in database: path={path}, watched={watched}"
                )
            else:
                logger.debug(
                    f"No MediaFile found for watched status update for path: {path}"
                )
    except Exception:
        logger.exception(f"Error updating watched status for {path}")


def update_episode_playback_position(path: str, position: int) -> bool:
    """Saves the last played playback offset (in seconds) for a given episode."""
    try:
        logger.debug(f"Saving playback position for '{path}' to {position}s")
        with get_session() as session:
            from lan_streamer.db.models import PlaybackState

            mf = session.scalars(
                select(MediaFile).where(MediaFile.path == path)
            ).first()
            if mf:
                for ep in mf.episodes:
                    if not ep.playback_state:
                        ep.playback_state = PlaybackState(episode_id=ep.id)
                    ep.playback_state.last_played_position = position
                    ep.playback_state.last_played_at = int(time.time())
                for mv in mf.movies:
                    if not mv.playback_state:
                        mv.playback_state = PlaybackState(movie_id=mv.id)
                    mv.playback_state.last_played_position = position
                    mv.playback_state.last_played_at = int(time.time())
                return True
    except Exception:
        logger.exception(f"Error updating playback position for {path}")
    return False


def get_episode_playback_position(path: str) -> int:
    """Retrieves the stored last played playback offset (in seconds) for a given episode."""
    try:
        logger.debug(f"Retrieving playback position for '{path}'")
        with get_session() as session:
            mf = session.scalars(
                select(MediaFile).where(MediaFile.path == path)
            ).first()
            if mf:
                if mf.episodes and mf.episodes[0].playback_state:
                    pos = mf.episodes[0].playback_state.last_played_position
                    logger.debug(f"Playback position for '{path}' is {pos}s")
                    return int(pos or 0)
                if mf.movies and mf.movies[0].playback_state:
                    pos = mf.movies[0].playback_state.last_played_position
                    logger.debug(f"Playback position for '{path}' is {pos}s")
                    return int(pos or 0)
    except Exception:
        logger.exception(f"Error retrieving playback position for {path}")
    return 0


def update_season_watched_status(
    library_name: str, series_name: str, season_name: str, watched: bool
) -> None:
    """Bulk updates the watched status for all episodes in a specific season."""
    try:
        logger.debug(
            f"Executing DB update_season_watched_status: library={library_name}, "
            f"series={series_name}, season={season_name}, watched={watched}"
        )
        logger.info(
            f"Updating watched status for {series_name} - {season_name} in {library_name} to {watched}"
        )
        with get_session() as session:
            season = session.scalars(
                select(Season)
                .join(Series)
                .where(
                    Series.library_name == library_name,
                    Series.name == series_name,
                    Season.name == season_name,
                )
            ).first()
            if season:
                from lan_streamer.db.models import PlaybackState

                for ep in season.episodes:
                    if not ep.playback_state:
                        ep.playback_state = PlaybackState(episode_id=ep.id)
                    ep.playback_state.watched = watched
                    if watched:
                        ep.playback_state.last_played_at = int(time.time())
                if watched:
                    mal_updates = {}
                    for ep in season.episodes:
                        if ep.myanimelist_anime_id and ep.myanimelist_episode_number:
                            mal_updates[ep.myanimelist_anime_id] = max(
                                mal_updates.get(ep.myanimelist_anime_id, 0),
                                ep.myanimelist_episode_number,
                            )
                    for anime_id, max_ep in mal_updates.items():
                        _trigger_mal_push_async(anime_id, max_ep)
                logger.debug(
                    f"Successfully bulk updated watched status to {watched} for season {season_name}"
                )
            else:
                logger.debug(
                    f"Season {season_name} not found in series {series_name} of library {library_name}"
                )
    except Exception:
        logger.exception(
            f"Error updating watched status for {series_name} - {season_name}"
        )


def update_series_watched_status(
    library_name: str, series_name: str, watched: bool
) -> None:
    """Bulk updates the watched status for all episodes in an entire series."""
    try:
        logger.debug(
            f"Executing DB update_series_watched_status: library={library_name}, "
            f"series={series_name}, watched={watched}"
        )
        logger.info(
            f"Updating watched status for entire series {series_name} in {library_name} to {watched}"
        )
        with get_session() as session:
            series = session.scalars(
                select(Series).where(
                    Series.library_name == library_name, Series.name == series_name
                )
            ).first()
            if series:
                from lan_streamer.db.models import PlaybackState

                for season in series.seasons:
                    for ep in season.episodes:
                        if not ep.playback_state:
                            ep.playback_state = PlaybackState(episode_id=ep.id)
                        ep.playback_state.watched = watched
                        if watched:
                            ep.playback_state.last_played_at = int(time.time())

                mal_updates = {}
                for season in series.seasons:
                    for episode in season.episodes:
                        if (
                            watched
                            and episode.myanimelist_anime_id
                            and episode.myanimelist_episode_number
                        ):
                            mal_updates[episode.myanimelist_anime_id] = max(
                                mal_updates.get(episode.myanimelist_anime_id, 0),
                                episode.myanimelist_episode_number,
                            )
                for anime_id, max_ep in mal_updates.items():
                    _trigger_mal_push_async(anime_id, max_ep)
                logger.debug(
                    f"Successfully bulk updated watched status to {watched} for series {series_name}"
                )
            else:
                logger.debug(
                    f"Series {series_name} not found in library {library_name}"
                )
    except Exception:
        logger.exception(f"Error updating watched status for series {series_name}")
