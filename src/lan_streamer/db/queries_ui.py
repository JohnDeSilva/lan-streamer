import logging
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload

from lan_streamer.db.connection import get_session
from lan_streamer.db.models import (
    Series,
    Season,
    Episode,
    Movie,
    MediaFile,
    MetadataFileMapping,
)
from lan_streamer.db.utils import natural_sort_key

logger = logging.getLogger("lan_streamer.db.queries")


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
            from lan_streamer.db.models import PlaybackState

            # Find series that have any episode where watched is True or last_played_at > 0, and the episode has a file path (not missing/future)
            series_statement = (
                select(Series)
                .join(Season)
                .join(Episode)
                .join(PlaybackState, PlaybackState.episode_id == Episode.id)
                .where(
                    (Episode.default_path.isnot(None))
                    & (Episode.default_path != "")
                    & (
                        (PlaybackState.watched.is_(True))
                        | (PlaybackState.last_played_at > 0)
                    )
                )
            )
            if library_names:
                series_statement = series_statement.where(
                    Series.library_name.in_(library_names)
                )

            # Eager load relationships on the fetched series to avoid N+1 queries during loop
            series_statement = series_statement.options(
                selectinload(Series.seasons)
                .selectinload(Season.episodes)
                .selectinload(Episode.media_files),
                selectinload(Series.seasons)
                .selectinload(Season.episodes)
                .selectinload(Episode.playback_state),
            )
            series_list = session.scalars(series_statement.distinct()).all()

            results = []
            for series in series_list:
                # Get all episodes of the series, sorted naturally by season name and episode name
                all_episodes = []
                filtered_seasons = []
                for season in series.seasons:
                    if not season.name:
                        continue
                    season_lower = season.name.lower()
                    if (
                        season_lower == "specials"
                        or season_lower == "special"
                        or "special" in season_lower
                        or season_lower.startswith("season 0")
                    ):
                        continue
                    filtered_seasons.append(season)

                seasons = sorted(
                    filtered_seasons,
                    key=lambda season_item: natural_sort_key(season_item.name or ""),
                )
                for season in seasons:
                    episodes = sorted(
                        season.episodes,
                        key=lambda episode_item: (
                            episode_item.tmdb_number
                            if episode_item.tmdb_number is not None
                            else 9999,
                            natural_sort_key(episode_item.name or ""),
                        ),
                    )
                    for episode in episodes:
                        if episode.default_path or episode.media_files:
                            all_episodes.append(episode)

                if not all_episodes:
                    continue

                # Find the index of the latest watched episode
                last_watched_index = -1
                for index, episode in enumerate(all_episodes):
                    if episode.playback_state and episode.playback_state.watched:
                        last_watched_index = index

                # If no episode has been watched, it is not "in progress" (Next Up)
                if last_watched_index == -1:
                    continue

                # Find the first unwatched episode AFTER the latest watched episode
                next_up_episode = None
                for index in range(last_watched_index + 1, len(all_episodes)):
                    episode = all_episodes[index]
                    if not (episode.playback_state and episode.playback_state.watched):
                        next_up_episode = episode
                        break

                # If there are no unwatched episodes after the last watched episode, the show is fully watched
                if not next_up_episode:
                    continue

                next_season = next_up_episode.season
                if next_season is None:
                    continue

                # Find max last_played_at, date_added, and air_date across all episodes in standard seasons that have a path
                max_last_played = 0
                max_date_added = 0
                max_air_date = ""
                for season in seasons:
                    for episode in season.episodes:
                        if not (episode.default_path or episode.media_files):
                            continue
                        if episode.playback_state:
                            value = episode.playback_state.last_played_at or 0
                            if value > max_last_played:
                                max_last_played = value
                        added_value = episode.date_added or 0
                        if added_value > max_date_added:
                            max_date_added = added_value
                        air_value = episode.air_date or ""
                        if air_value > max_air_date:
                            max_air_date = air_value

                season_episodes = [
                    episode
                    for episode in next_season.episodes
                    if episode.default_path or episode.media_files
                ]
                watched_count = sum(
                    1
                    for episode in season_episodes
                    if episode.playback_state and episode.playback_state.watched
                )
                total_count = len(season_episodes)

                results.append(
                    {
                        "type": "season",
                        "series_name": series.name,
                        "season_name": next_season.name,
                        "poster_path": next_season.poster_path or series.poster_path,
                        "library_name": series.library_name,
                        "last_played_at": max_last_played,
                        "date_added": max_date_added,
                        "air_date": max_air_date or series.first_air_date or "",
                        "watched_count": watched_count,
                        "total_count": total_count,
                    }
                )

            # Sort by air_date descending first (secondary sort)
            results.sort(key=lambda item: item["air_date"] or "", reverse=True)
            # Sort by last_played_at descending second (primary sort)
            results.sort(
                key=lambda item: int(item["last_played_at"] or 0), reverse=True
            )
            logger.info(f"get_combined_next_up: returning {len(results)} seasons")
            logger.debug(f"get_combined_next_up query response: returning {results}")
            return results
    except Exception:
        logger.exception("Error in get_combined_next_up")
        return []


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

            # 1. Fetch Series with eager loaded relationships to avoid N+1 queries
            series_statement = select(Series).options(
                selectinload(Series.seasons)
                .selectinload(Season.episodes)
                .selectinload(Episode.media_files),
                selectinload(Series.seasons)
                .selectinload(Season.episodes)
                .selectinload(Episode.playback_state),
            )
            if library_names:
                series_statement = series_statement.where(
                    Series.library_name.in_(library_names)
                )
            series_list = session.scalars(series_statement).all()

            for series in series_list:
                total_episodes = 0
                watched_episodes = 0
                max_date_added = 0
                max_air_date = ""

                for season in series.seasons:
                    for episode in season.episodes:
                        # Exclude future/missing placeholder episodes from progress metrics
                        if not (episode.default_path or episode.media_files):
                            continue
                        total_episodes += 1
                        if episode.playback_state and episode.playback_state.watched:
                            watched_episodes += 1
                        value = episode.date_added or 0
                        if value > max_date_added:
                            max_date_added = value
                        air_value = episode.air_date or ""
                        if air_value > max_air_date:
                            max_air_date = air_value

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

            # 2. Fetch Movies with eager loaded relationship to avoid N+1 queries
            movie_statement = select(Movie).options(selectinload(Movie.playback_state))
            if library_names:
                movie_statement = movie_statement.where(
                    Movie.library_name.in_(library_names)
                )
            movies = session.scalars(movie_statement).all()

            for movie in movies:
                movie_watched = bool(
                    movie.playback_state and movie.playback_state.watched
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
                results.sort(key=lambda item: str(item["name"] or "").lower())
            elif sort_by == "Recently Added":
                results.sort(
                    key=lambda item: int(item["date_added"] or 0), reverse=True
                )
            elif sort_by == "Recently Aired":
                results.sort(key=lambda item: str(item["air_date"] or ""), reverse=True)
            else:
                # Default fallback
                results.sort(key=lambda item: str(item["name"] or "").lower())

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
                .options(joinedload(Episode.season).joinedload(Season.series))
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

            series_identifier = current_episode.season.series.id
            series = session.scalars(
                select(Series)
                .where(Series.id == series_identifier)
                .options(
                    selectinload(Series.seasons)
                    .selectinload(Season.episodes)
                    .selectinload(Episode.media_files),
                    selectinload(Series.seasons)
                    .selectinload(Season.episodes)
                    .selectinload(Episode.playback_state),
                )
            ).first()

            if not series:
                logger.debug("Series not found in database.")
                return None

            # Get all seasons of the series, sorted naturally by name
            seasons: List[Season] = sorted(
                series.seasons, key=lambda season: natural_sort_key(season.name)
            )

            # Construct flat list of all episodes in series in natural order
            ordered_episodes: List[Tuple[Episode, Season, int]] = []
            for season in seasons:
                # Sort episodes in this season by TMDB number (default grouping), excluding missing/future episodes
                valid_episodes = [
                    episode
                    for episode in season.episodes
                    if episode.default_path or episode.media_files
                ]
                season_episodes: List[Episode] = sorted(
                    valid_episodes,
                    key=lambda episode: (
                        episode.tmdb_number
                        if episode.tmdb_number is not None
                        else 9999,
                        natural_sort_key(episode.name or ""),
                    ),
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


def search_media_names(
    query_text: str,
    library_names: Optional[List[str]] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Search series and movies by name using case-insensitive partial matching.

    Results are ordered: exact matches first, starts-with matches second,
    contains matches third. If library_names is None or empty, searches all
    libraries. If library_names is provided, only searches those libraries.

    Args:
        query_text: The search string (minimum 2 characters after stripping).
        library_names: Optional filter to restrict which libraries to search.
        limit: Maximum number of results to return (default 50).

    Returns:
        A list of dicts with keys: name, library_name, poster_path, type.
    """
    try:
        logger.debug(
            f"Searching media names for query='{query_text}', "
            f"library_names={library_names}, limit={limit}"
        )
        if not query_text or len(query_text.strip()) < 2:
            return []

        clean_query = query_text.strip()
        like_pattern = f"%{clean_query}%"

        with get_session() as session:
            # Fetch matching series
            series_statement = select(Series).where(Series.name.ilike(like_pattern))
            if library_names:
                series_statement = series_statement.where(
                    Series.library_name.in_(library_names)
                )
            series_list = list(session.scalars(series_statement).all())

            # Fetch matching movies
            movie_statement = select(Movie).where(Movie.name.ilike(like_pattern))
            if library_names:
                movie_statement = movie_statement.where(
                    Movie.library_name.in_(library_names)
                )
            movie_list = list(session.scalars(movie_statement).all())

            # Sort all results together: exact match first, starts with second, contains third
            def sort_key(item: Any) -> Tuple[int, str]:
                name_lower = (item.name or "").lower()
                query_lower = clean_query.lower()
                if name_lower == query_lower:
                    return (0, name_lower)
                if name_lower.startswith(query_lower):
                    return (1, name_lower)
                return (2, name_lower)

            all_items: List[Any] = sorted(series_list + movie_list, key=sort_key)

            results: List[Dict[str, Any]] = []
            for item in all_items[:limit]:
                item_type = "series" if isinstance(item, Series) else "movie"
                results.append(
                    {
                        "name": item.name,
                        "library_name": item.library_name,
                        "poster_path": item.poster_path or "",
                        "type": item_type,
                    }
                )

            logger.info(
                f"search_media_names: found {len(results)} results for '{clean_query}'"
            )
            logger.debug(f"search_media_names results: {results}")
            return results

    except Exception:
        logger.exception(f"Error searching media names for query '{query_text}'")
        return []
