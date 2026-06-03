import logging
import re
import time
import json
from typing import Dict, Any, List, Tuple, Optional

from sqlalchemy import select, update

from lan_streamer.db.models import Series, Season, Episode, Movie


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


logger = logging.getLogger(__name__)


def natural_sort_key(s: Optional[str]) -> List[Any]:
    """
    Key function for natural sorting (e.g., "Season 2" < "Season 10").
    """
    if s is None:
        return []
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split("([0-9]+)", str(s))
    ]


def _build_episode_dict(episode: Episode) -> Dict[str, Any]:
    """Maps a single Episode ORM row to its plain dictionary representation."""
    try:
        audio_tracks = json.loads(episode.audio_tracks) if episode.audio_tracks else []
    except Exception:
        audio_tracks = []
    try:
        subtitle_tracks = (
            json.loads(episode.subtitle_tracks) if episode.subtitle_tracks else []
        )
    except Exception:
        subtitle_tracks = []

    return {
        "name": episode.name,
        "path": episode.path,
        "jellyfin_id": episode.jellyfin_id,
        "tmdb_episode_identifier": episode.tmdb_episode_identifier,
        "tmdb_name": episode.tmdb_name,
        "tmdb_number": episode.tmdb_number,
        "watched": bool(episode.watched),
        "date_added": episode.date_added or 0,
        "air_date": episode.air_date or "",
        "runtime": episode.runtime or 0,
        "last_played_at": episode.last_played_at or 0,
        "video_codec": episode.video_codec or "",
        "resolution": episode.resolution or "",
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
    }


def _build_season_dict(season: Season) -> Dict[str, Any]:
    """Maps a single Season ORM row (with its episodes) to a plain dict."""
    episodes = [_build_episode_dict(episode) for episode in season.episodes]
    episodes.sort(key=lambda x: natural_sort_key(x["name"]))
    return {
        "metadata": {
            "jellyfin_id": season.jellyfin_id,
            "poster_path": season.poster_path,
        },
        "episodes": episodes,
    }


def _build_series_dict(series: Series) -> Dict[str, Any]:
    """Maps a single Series ORM row (with seasons and episodes) to a plain dict."""
    seasons: Dict[str, Any] = {}
    for season in series.seasons:
        if season.name is not None:
            seasons[season.name] = _build_season_dict(season)
    return {
        "metadata": {
            "jellyfin_id": series.jellyfin_id,
            "tmdb_identifier": series.tmdb_identifier,
            "poster_path": series.poster_path,
            "overview": series.overview,
            "tmdb_name": series.tmdb_name,
            "locked_metadata": bool(series.locked_metadata),
            "first_air_date": series.first_air_date or "",
        },
        "seasons": seasons,
    }


def _build_movie_dict(movie: Movie) -> Dict[str, Any]:
    """Maps a single Movie ORM row to its plain dictionary representation."""
    try:
        audio_tracks = json.loads(movie.audio_tracks) if movie.audio_tracks else []
    except Exception:
        audio_tracks = []
    try:
        subtitle_tracks = (
            json.loads(movie.subtitle_tracks) if movie.subtitle_tracks else []
        )
    except Exception:
        subtitle_tracks = []

    return {
        "name": movie.name,
        "path": movie.path,
        "jellyfin_id": movie.jellyfin_id,
        "tmdb_identifier": movie.tmdb_identifier,
        "poster_path": movie.poster_path,
        "overview": movie.overview,
        "tmdb_name": movie.tmdb_name,
        "locked_metadata": bool(movie.locked_metadata),
        "date_added": movie.date_added or 0,
        "runtime": movie.runtime or 0,
        "rating": movie.rating or "",
        "genre": movie.genre or "",
        "year": movie.year or 0,
        "watched": bool(movie.watched),
        "last_played_position": movie.last_played_position or 0,
        "last_played_at": movie.last_played_at or 0,
        "video_codec": movie.video_codec or "",
        "resolution": movie.resolution or "",
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
    }


def update_episode_watched_status(path: str, watched: bool) -> None:

    try:
        logger.info(f"Updating watched status for {path} to {watched}")
        with get_session() as session:
            episode = session.scalars(
                select(Episode).where(Episode.path == path)
            ).first()
            if episode:
                episode.watched = watched
                if watched:
                    episode.last_played_at = int(time.time())
            else:
                movie = session.scalars(select(Movie).where(Movie.path == path)).first()
                if movie:
                    movie.watched = watched
                    if watched:
                        movie.last_played_at = int(time.time())
    except Exception:
        logger.exception(f"Error updating watched status for {path}")


def update_episode_path(old_path: str, new_path: str) -> None:
    """Updates the file path for an episode in the database."""

    try:
        logger.info(f"Updating episode path from {old_path} to {new_path}")
        with get_session() as session:
            episode = session.scalars(
                select(Episode).where(Episode.path == old_path)
            ).first()
            if episode:
                episode.path = new_path
    except Exception:
        logger.exception(f"Error updating episode path from {old_path} to {new_path}")


def update_episode_playback_position(path: str, position: int) -> bool:
    """Saves the last played playback offset (in seconds) for a given episode."""

    try:
        logger.debug(f"Saving playback position for '{path}' to {position}s")
        with get_session() as session:
            episode = session.scalars(
                select(Episode).where(Episode.path == path)
            ).first()
            if episode:
                episode.last_played_position = position
                episode.last_played_at = int(time.time())
                return True
            movie = session.scalars(select(Movie).where(Movie.path == path)).first()
            if movie:
                movie.last_played_position = position
                movie.last_played_at = int(time.time())
                return True
    except Exception:
        logger.exception(f"Error updating playback position for {path}")
    return False


def get_episode_playback_position(path: str) -> int:
    """Retrieves the stored last played playback offset (in seconds) for a given episode."""

    try:
        logger.debug(f"Retrieving playback position for '{path}'")
        with get_session() as session:
            episode = session.scalars(
                select(Episode).where(Episode.path == path)
            ).first()
            if episode and episode.last_played_position:
                logger.debug(
                    f"Playback position for episode '{path}' is {episode.last_played_position}s"
                )
                return int(episode.last_played_position)
            movie = session.scalars(select(Movie).where(Movie.path == path)).first()
            if movie and movie.last_played_position:
                logger.debug(
                    f"Playback position for movie '{path}' is {movie.last_played_position}s"
                )
                return int(movie.last_played_position)
    except Exception:
        logger.exception(f"Error retrieving playback position for {path}")
    return 0


def is_movie(path: str) -> bool:
    """Returns True if the given path corresponds to a movie in the database."""
    try:
        with get_session() as session:
            movie = session.scalars(select(Movie).where(Movie.path == path)).first()
            return movie is not None
    except Exception:
        logger.exception(f"Error checking if path is movie: {path}")
        return False


def update_season_watched_status(
    library_name: str, series_name: str, season_name: str, watched: bool
) -> None:
    """
    Bulk updates the watched status for all episodes in a specific season.
    """

    try:
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
                session.execute(
                    update(Episode)
                    .where(Episode.season_id == season.id)
                    .values(watched=watched)
                )
    except Exception:
        logger.exception(
            f"Error updating watched status for {series_name} - {season_name}"
        )


def update_series_watched_status(
    library_name: str, series_name: str, watched: bool
) -> None:
    """
    Bulk updates the watched status for all episodes in an entire series.
    """

    try:
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
                for season in series.seasons:
                    for episode in season.episodes:
                        episode.watched = watched
    except Exception:
        logger.exception(f"Error updating watched status for series {series_name}")


def get_items_missing_runtime() -> List[Dict[str, Any]]:
    """Retrieves all episodes and movies whose runtime is 0 or missing."""

    items_list: List[Dict[str, Any]] = []
    try:
        with get_session() as session:
            episodes = session.scalars(
                select(Episode).where(
                    (Episode.runtime == 0) | (Episode.runtime.is_(None))
                )
            ).all()
            for episode in episodes:
                if episode.path:
                    items_list.append(
                        {"id": episode.id, "path": episode.path, "type": "episode"}
                    )

            movies = session.scalars(
                select(Movie).where((Movie.runtime == 0) | (Movie.runtime.is_(None)))
            ).all()
            for movie in movies:
                if movie.path:
                    items_list.append(
                        {"id": movie.id, "path": movie.path, "type": "movie"}
                    )
    except Exception:
        logger.exception("Error fetching items missing runtime")
    return items_list


def update_item_runtime(
    item_identifier: int,
    item_type: str,
    runtime_minutes: int,
    video_codec: Optional[str] = None,
    resolution: Optional[str] = None,
    audio_tracks: Optional[List[Dict[str, Any]]] = None,
    subtitle_tracks: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Updates the runtime and technical info fields for a given episode or movie."""

    try:
        with get_session() as session:
            if item_type == "episode":
                episode = session.scalars(
                    select(Episode).where(Episode.id == item_identifier)
                ).first()
                if episode:
                    episode.runtime = runtime_minutes
                    if video_codec:
                        episode.video_codec = video_codec
                    if resolution:
                        episode.resolution = resolution
                    if audio_tracks is not None:
                        episode.audio_tracks = json.dumps(audio_tracks)
                    if subtitle_tracks is not None:
                        episode.subtitle_tracks = json.dumps(subtitle_tracks)
            elif item_type == "movie":
                movie = session.scalars(
                    select(Movie).where(Movie.id == item_identifier)
                ).first()
                if movie:
                    movie.runtime = runtime_minutes
                    if video_codec:
                        movie.video_codec = video_codec
                    if resolution:
                        movie.resolution = resolution
                    if audio_tracks is not None:
                        movie.audio_tracks = json.dumps(audio_tracks)
                    if subtitle_tracks is not None:
                        movie.subtitle_tracks = json.dumps(subtitle_tracks)
    except Exception:
        logger.exception(
            f"Error updating runtime and technical info for {item_type} ID {item_identifier}"
        )


def get_next_episode(current_path: str) -> Optional[Dict[str, Any]]:
    """
    Finds the next episode in the same series for a given episode path.
    Sorts seasons and episodes naturally by name.
    """

    try:
        logger.debug(f"Determining next episode after: '{current_path}'")
        with get_session() as session:
            current_episode: Optional[Episode] = session.scalars(
                select(Episode).where(Episode.path == current_path)
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
                # Sort episodes in this season naturally by name
                season_episodes: List[Episode] = sorted(
                    season.episodes, key=lambda e: natural_sort_key(e.name)
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

            if not next_episode.path:
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
                "path": next_episode.path,
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
        logger.debug(f"get_combined_next_up called with libraries={library_names}")
        with get_session() as session:
            # Find series that have any episode where watched is True or last_played_at > 0
            series_stmt = (
                select(Series)
                .join(Season)
                .join(Episode)
                .where((Episode.watched.is_(True)) | (Episode.last_played_at > 0))
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
                    episodes = season.episodes
                    if not episodes:
                        continue
                    # Check if all episodes in this season are watched
                    fully_watched = all(ep.watched for ep in episodes)
                    if not fully_watched:
                        next_season = season
                        break

                if next_season:
                    # Find max last_played_at across all episodes in the series
                    max_lp = 0
                    for s in series.seasons:
                        for ep in s.episodes:
                            val = ep.last_played_at or 0
                            if val > max_lp:
                                max_lp = val

                    season_episodes = next_season.episodes
                    watched_count = sum(1 for ep in season_episodes if ep.watched)
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
                            "watched_count": watched_count,
                            "total_count": total_count,
                        }
                    )

            # Sort by last_played_at descending
            results.sort(key=lambda x: int(x["last_played_at"] or 0), reverse=True)
            logger.debug(f"get_combined_next_up returning {len(results)} results")
            return results
    except Exception:
        logger.exception("Error in get_combined_next_up")
        return []


def get_combined_recently_added(library_names: List[str]) -> List[Dict[str, Any]]:
    """
    Returns series and movies sorted by their date_added (max episode date_added for series, movie date_added for movies).
    """
    logger.debug(f"get_combined_recently_added called with libraries={library_names}")
    return get_combined_smart_row(library_names, "Recently Added", "All")


def get_combined_smart_row(
    library_names: List[str], sort_by: str, filter_mode: str
) -> List[Dict[str, Any]]:
    """
    Returns filtered and sorted series and movies across the specified libraries.
    """

    try:
        logger.debug(
            f"get_combined_smart_row called with libraries={library_names}, "
            f"sort_by='{sort_by}', filter_mode='{filter_mode}'"
        )
        if sort_by == "Next Up":
            return get_combined_next_up(library_names)

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
                        if ep.path is None:
                            continue
                        total_episodes += 1
                        if ep.watched:
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
                keep = True
                if filter_mode == "Watched":
                    keep = bool(movie.watched)
                elif filter_mode == "Unwatched":
                    keep = not bool(movie.watched)

                if keep:
                    results.append(
                        {
                            "type": "movie",
                            "name": movie.name,
                            "poster_path": movie.poster_path,
                            "library_name": movie.library_name,
                            "date_added": movie.date_added or 0,
                            "air_date": str(movie.year or ""),
                            "watched_count": 1 if movie.watched else 0,
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

            logger.debug(f"get_combined_smart_row returning {len(results)} results")
            return results
    except Exception:
        logger.exception("Error in get_combined_smart_row")
        return []
