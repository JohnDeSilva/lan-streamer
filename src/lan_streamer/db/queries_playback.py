import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import select

from lan_streamer.db.models import (
    Series,
    Season,
    Episode,
    Movie,
    MediaFile,
    MetadataFileMapping,
)
from lan_streamer.db.queries_file_discovery import natural_sort_key

logger = logging.getLogger("lan_streamer.db.queries")


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


def _trigger_mal_push_async(anime_id: int, num_watched_episodes: int) -> None:
    """Helper to asynchronously push watch status to MyAnimeList."""
    import lan_streamer.db.queries_playback

    target = lan_streamer.db.queries_playback._trigger_mal_push_async
    if target is not _trigger_mal_push_async:
        target(anime_id, num_watched_episodes)
        return

    from lan_streamer.providers.myanimelist import myanimelist_client

    if myanimelist_client.is_configured() and myanimelist_client.is_authenticated():
        import threading

        def _run() -> None:
            try:
                myanimelist_client.update_watched_status(anime_id, num_watched_episodes)
            except Exception:
                logger.exception(
                    f"Background MyAnimeList push failed for anime {anime_id}"
                )

        threading.Thread(target=_run, daemon=True).start()


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
                if not mf.playback_state:
                    mf.playback_state = PlaybackState(media_file_id=mf.id)
                mf.playback_state.watched = watched
                if watched:
                    mf.playback_state.last_played_at = int(time.time())
                    for ep in mf.episodes:
                        if ep.myanimelist_anime_id and ep.myanimelist_episode_number:
                            _trigger_mal_push_async(
                                ep.myanimelist_anime_id,
                                ep.myanimelist_episode_number,
                            )
                    for mv in mf.movies:
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
                if not mf.playback_state:
                    mf.playback_state = PlaybackState(media_file_id=mf.id)
                mf.playback_state.last_played_position = position
                mf.playback_state.last_played_at = int(time.time())
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
            if mf and mf.playback_state and mf.playback_state.last_played_position:
                logger.debug(
                    f"Playback position for '{path}' is {mf.playback_state.last_played_position}s"
                )
                return int(mf.playback_state.last_played_position)
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
                ep_ids = [ep.id for ep in season.episodes]
                if ep_ids:
                    from lan_streamer.db.models import (
                        MetadataFileMapping,
                        PlaybackState,
                    )

                    mfs = session.scalars(
                        select(MediaFile)
                        .join(MetadataFileMapping)
                        .where(MetadataFileMapping.episode_id.in_(ep_ids))
                    ).all()
                    for mf in mfs:
                        if not mf.playback_state:
                            mf.playback_state = PlaybackState(media_file_id=mf.id)
                        mf.playback_state.watched = watched
                        if watched:
                            mf.playback_state.last_played_at = int(time.time())
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
                ep_ids = []
                for season in series.seasons:
                    for ep in season.episodes:
                        ep_ids.append(ep.id)
                if ep_ids:
                    from lan_streamer.db.models import (
                        MetadataFileMapping,
                        PlaybackState,
                    )

                    mfs = session.scalars(
                        select(MediaFile)
                        .join(MetadataFileMapping)
                        .where(MetadataFileMapping.episode_id.in_(ep_ids))
                    ).all()
                    for mf in mfs:
                        if not mf.playback_state:
                            mf.playback_state = PlaybackState(media_file_id=mf.id)
                        mf.playback_state.watched = watched
                        if watched:
                            mf.playback_state.last_played_at = int(time.time())

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


def get_next_episode(current_path: str) -> Optional[Dict[str, Any]]:
    """
    Finds the next episode in the same series for a given episode path.
    Sorts seasons and episodes naturally by name.
    """
    try:
        logger.debug(f"Determining next episode after: '{current_path}'")
        with get_session() as session:
            current_episode: Optional[Episode] = session.scalars(
                select(Episode)
                .join(MetadataFileMapping, MetadataFileMapping.episode_id == Episode.id)
                .join(MediaFile, MediaFile.id == MetadataFileMapping.media_file_id)
                .where(MediaFile.path == current_path)
            ).first()
            if (
                not current_episode
                or not current_episode.season
                or not current_episode.season.series
            ):
                logger.debug(
                    "Current episode, season, or series not found in database."
                )
                return None

            series: Series = current_episode.season.series

            # Get all seasons of the series, sorted naturally by name
            seasons: List[Season] = sorted(
                series.seasons, key=lambda s: natural_sort_key(s.name)
            )

            # Construct flat list of all episodes in series in natural order
            ordered_episodes: List[Tuple[Episode, Season, int]] = []
            for season in seasons:
                # Sort episodes in this season naturally by name, excluding missing/future episodes
                valid_episodes = [
                    e for e in season.episodes if e.default_path or e.media_files
                ]
                season_episodes: List[Episode] = sorted(
                    valid_episodes, key=lambda e: natural_sort_key(e.name)
                )
                for index, episode in enumerate(season_episodes):
                    ordered_episodes.append((episode, season, index + 1))

            # Find current episode index in the ordered list
            current_index: int = -1
            for index, (episode, _, _) in enumerate(ordered_episodes):
                if episode.id == current_episode.id:
                    current_index = index
                    break

            if current_index == -1:
                logger.debug("Current episode index could not be determined.")
                return None

            if current_index == len(ordered_episodes) - 1:
                logger.info("Current episode is the last episode in the series.")
                return None

            # Retrieve next episode and its season / calculated episode number
            next_episode, next_season, calculated_episode_number = ordered_episodes[
                current_index + 1
            ]

            next_path = next_episode.default_path or (
                next_episode.media_files[0].path if next_episode.media_files else None
            )
            if not next_path:
                logger.info("Next episode has no file path (placeholder).")
                return None

            result = {
                "title": next_episode.tmdb_name
                if next_episode.tmdb_name
                else (next_episode.name or "Unknown"),
                "season": next_season.name or "Unknown",
                "episode_number": next_episode.tmdb_number
                if next_episode.tmdb_number is not None
                else calculated_episode_number,
                "path": next_path,
                "poster_path": series.poster_path if series.poster_path else "",
                "runtime": next_episode.runtime or 0,
            }
            logger.info(
                f"Resolved next episode: '{result['title']}' (S: '{result['season']}', E: {result['episode_number']}) at path '{result['path']}'"
            )
            return result
    except Exception:
        logger.exception(f"Error getting next episode for path {current_path}")
    return None


def get_combined_next_up(library_names: List[str]) -> List[Dict[str, Any]]:
    """
    For partially watched series (having at least one watched episode or playback position),
    returns the next unplayed season in the series.
    Ordered by the max(last_played_at) of any episode in the series (most recently played first).
    """
    try:
        logger.debug(
            f"Executing DB query get_combined_next_up for libraries={library_names}"
        )
        logger.info(
            f"get_combined_next_up: fetching next up items for libraries={library_names}"
        )
        with get_session() as session:
            from lan_streamer.db.models import PlaybackState, MetadataFileMapping

            # Find series that have any episode where watched is True or last_played_at > 0, and the episode has a file path (not missing/future)
            series_stmt = (
                select(Series)
                .join(Season)
                .join(Episode)
                .join(MetadataFileMapping, MetadataFileMapping.episode_id == Episode.id)
                .join(MediaFile, MediaFile.id == MetadataFileMapping.media_file_id)
                .join(PlaybackState, PlaybackState.media_file_id == MediaFile.id)
                .where(
                    (MediaFile.path.isnot(None))
                    & (MediaFile.path != "")
                    & (
                        (PlaybackState.watched.is_(True))
                        | (PlaybackState.last_played_at > 0)
                    )
                )
            )
            if library_names:
                series_stmt = series_stmt.where(Series.library_name.in_(library_names))
            series_list = session.scalars(series_stmt.distinct()).all()

            results = []
            for series in series_list:
                # Get all seasons of this series
                seasons = sorted(
                    series.seasons, key=lambda s: natural_sort_key(s.name or "")
                )
                next_season = None

                # Find the first season that is not fully watched
                for season in seasons:
                    # Do not consider missing or future episodes (those with no path)
                    episodes = [
                        ep
                        for ep in season.episodes
                        if ep.default_path or ep.media_files
                    ]
                    if not episodes:
                        continue
                    # Check if all episodes in this season are watched
                    fully_watched = all(
                        any(
                            mf.playback_state and mf.playback_state.watched
                            for mf in ep.media_files
                        )
                        for ep in episodes
                    )
                    if not fully_watched:
                        next_season = season
                        break

                if next_season:
                    # Find max last_played_at, date_added, and air_date across all episodes in the series that have a path
                    max_lp = 0
                    max_date_added = 0
                    max_air_date = ""
                    for s in series.seasons:
                        for ep in s.episodes:
                            if not (ep.default_path or ep.media_files):
                                continue
                            for mf in ep.media_files:
                                if mf.playback_state:
                                    val = mf.playback_state.last_played_at or 0
                                    if val > max_lp:
                                        max_lp = val
                            added_val = ep.date_added or 0
                            if added_val > max_date_added:
                                max_date_added = added_val
                            air_val = ep.air_date or ""
                            if air_val > max_air_date:
                                max_air_date = air_val

                    season_episodes = [
                        ep
                        for ep in next_season.episodes
                        if ep.default_path or ep.media_files
                    ]
                    watched_count = sum(
                        1
                        for ep in season_episodes
                        if any(
                            mf.playback_state and mf.playback_state.watched
                            for mf in ep.media_files
                        )
                    )
                    total_count = len(season_episodes)

                    results.append(
                        {
                            "type": "season",
                            "series_name": series.name,
                            "season_name": next_season.name,
                            "poster_path": next_season.poster_path
                            or series.poster_path,
                            "library_name": series.library_name,
                            "last_played_at": max_lp,
                            "date_added": max_date_added,
                            "air_date": max_air_date or series.first_air_date or "",
                            "watched_count": watched_count,
                            "total_count": total_count,
                        }
                    )

            # Sort by last_played_at descending
            results.sort(key=lambda x: int(x["last_played_at"] or 0), reverse=True)
            logger.info(f"get_combined_next_up: returning {len(results)} seasons")
            logger.debug(f"get_combined_next_up query response: returning {results}")
            return results
    except Exception:
        logger.exception("Error in get_combined_next_up")
        return []


def get_combined_recently_added(library_names: List[str]) -> List[Dict[str, Any]]:
    """Returns series and movies sorted by their date_added (max episode date_added for series, movie date_added for movies)."""
    logger.debug(f"get_combined_recently_added called with libraries={library_names}")
    return get_combined_smart_row(library_names, "Recently Added", "All")


def get_combined_smart_row(
    library_names: List[str], sort_by: str, filter_mode: str
) -> List[Dict[str, Any]]:
    """Returns filtered and sorted series and movies across the specified libraries."""
    try:
        logger.debug(
            f"Executing DB query get_combined_smart_row: libraries={library_names}, "
            f"sort_by='{sort_by}', filter_mode='{filter_mode}'"
        )
        logger.info(
            f"get_combined_smart_row processing request: libraries={library_names}, "
            f"sort_by='{sort_by}', filter_mode='{filter_mode}'"
        )
        if sort_by == "Next Up":
            results = get_combined_next_up(library_names)
            logger.info(
                f"get_combined_smart_row (Next Up) returned {len(results)} items"
            )
            return results

        with get_session() as session:
            results = []

            # 1. Fetch Series
            series_stmt = select(Series)
            if library_names:
                series_stmt = series_stmt.where(Series.library_name.in_(library_names))
            series_list = session.scalars(series_stmt).all()

            for series in series_list:
                total_episodes = 0
                watched_episodes = 0
                max_date_added = 0
                max_air_date = ""

                for season in series.seasons:
                    for ep in season.episodes:
                        if not (ep.default_path or ep.media_files):
                            continue
                        total_episodes += 1
                        if any(
                            mf.playback_state and mf.playback_state.watched
                            for mf in ep.media_files
                        ):
                            watched_episodes += 1
                        val = ep.date_added or 0
                        if val > max_date_added:
                            max_date_added = val
                        air_val = ep.air_date or ""
                        if air_val > max_air_date:
                            max_air_date = air_val

                if total_episodes == 0:
                    continue

                # Check filter
                keep = True
                if filter_mode == "Watched":
                    keep = (
                        (watched_episodes == total_episodes)
                        if total_episodes > 0
                        else False
                    )
                elif filter_mode == "Unwatched":
                    keep = watched_episodes < total_episodes

                if keep:
                    results.append(
                        {
                            "type": "series",
                            "name": series.name,
                            "poster_path": series.poster_path,
                            "library_name": series.library_name,
                            "date_added": max_date_added,
                            "air_date": max_air_date or series.first_air_date or "",
                            "watched_count": watched_episodes,
                            "total_count": total_episodes,
                        }
                    )

            # 2. Fetch Movies
            movie_stmt = select(Movie)
            if library_names:
                movie_stmt = movie_stmt.where(Movie.library_name.in_(library_names))
            movies = session.scalars(movie_stmt).all()

            for movie in movies:
                movie_watched = any(
                    mf.playback_state and mf.playback_state.watched
                    for mf in movie.media_files
                )
                keep = True
                if filter_mode == "Watched":
                    keep = movie_watched
                elif filter_mode == "Unwatched":
                    keep = not movie_watched

                if keep:
                    results.append(
                        {
                            "type": "movie",
                            "name": movie.name,
                            "poster_path": movie.poster_path,
                            "library_name": movie.library_name,
                            "date_added": movie.date_added or 0,
                            "air_date": str(movie.year or ""),
                            "watched_count": 1 if movie_watched else 0,
                            "total_count": 1,
                        }
                    )

            # Apply sorting
            if sort_by == "Alphabetical":
                results.sort(key=lambda x: str(x["name"] or "").lower())
            elif sort_by == "Recently Added":
                results.sort(key=lambda x: int(x["date_added"] or 0), reverse=True)
            elif sort_by == "Recently Aired":
                results.sort(key=lambda x: str(x["air_date"] or ""), reverse=True)
            else:
                # Default fallback
                results.sort(key=lambda x: str(x["name"] or "").lower())

            logger.info(
                f"get_combined_smart_row: returning {len(results)} items (type counts: "
                f"Series={len([r for r in results if r['type'] == 'series'])} "
                f"Movies={len([r for r in results if r['type'] == 'movie'])})"
            )
            logger.debug(f"get_combined_smart_row response items: {results}")
            return results
    except Exception:
        logger.exception("Error in get_combined_smart_row")
        return []
