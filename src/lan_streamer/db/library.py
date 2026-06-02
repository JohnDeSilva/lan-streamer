import logging
import time
import json
from pathlib import Path
from typing import Dict, Any, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from lan_streamer.db.models import Series, Season, Episode, Movie
from lan_streamer.system.config import config
from lan_streamer.db.queries import (
    _build_series_dict,
    _build_movie_dict,
)


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


logger = logging.getLogger(__name__)


def _apply_movie_fields(movie: Movie, movie_data: Dict[str, Any]) -> None:
    """
    Applies all scalar fields from *movie_data* onto the *movie* ORM object.
    Only overrides existing values when the incoming value is non-falsy.
    """
    path = movie_data.get("path")
    movie.path = path or movie.path
    movie.jellyfin_id = movie_data.get("jellyfin_id") or movie.jellyfin_id
    movie.tmdb_identifier = movie_data.get("tmdb_identifier") or movie.tmdb_identifier
    movie.poster_path = movie_data.get("poster_path") or movie.poster_path
    movie.overview = movie_data.get("overview") or movie.overview
    movie.tmdb_name = movie_data.get("tmdb_name") or movie.tmdb_name
    if "locked_metadata" in movie_data:
        movie.locked_metadata = bool(movie_data["locked_metadata"])
    movie.date_added = movie_data.get("date_added") or movie.date_added or 0
    movie.runtime = movie_data.get("runtime") or movie.runtime or 0
    movie.rating = movie_data.get("rating") or movie.rating or ""
    movie.genre = movie_data.get("genre") or movie.genre or ""
    movie.year = movie_data.get("year") or movie.year or 0
    movie.watched = movie.watched or bool(movie_data.get("watched"))
    movie.last_played_position = (
        movie_data.get("last_played_position") or movie.last_played_position or 0
    )
    if "video_codec" in movie_data:
        movie.video_codec = movie_data.get("video_codec") or movie.video_codec
    if "resolution" in movie_data:
        movie.resolution = movie_data.get("resolution") or movie.resolution

    if "audio_tracks" in movie_data:
        movie.audio_tracks = (
            json.dumps(movie_data["audio_tracks"])
            if movie_data["audio_tracks"]
            else movie.audio_tracks
        )
    if "subtitle_tracks" in movie_data:
        movie.subtitle_tracks = (
            json.dumps(movie_data["subtitle_tracks"])
            if movie_data["subtitle_tracks"]
            else movie.subtitle_tracks
        )


def _cleanup_movie_library(
    session: Session,
    library_name: str,
    stats: Dict[str, int],
) -> None:
    """Removes Movie records whose file path no longer exists on disk."""
    movie_list = session.scalars(
        select(Movie).where(Movie.library_name == library_name)
    ).all()
    for movie in movie_list:
        if movie.path and not Path(movie.path).exists():
            logger.info(
                f"Cleanup: Removing missing movie '{movie.name}' at '{movie.path}'"
            )
            session.delete(movie)
            stats["movies"] += 1


def _cleanup_tv_library(
    session: Session,
    library_name: str,
    root_directories: List[str],
    stats: Dict[str, int],
) -> None:
    """
    Removes Series/Season/Episode records whose corresponding paths no longer
    exist on disk, then purges any empty seasons or series left behind.
    """
    series_list = session.scalars(
        select(Series).where(Series.library_name == library_name)
    ).all()

    for series in series_list:
        series_path_exists = any(
            series.name and (Path(root) / series.name).is_dir()
            for root in root_directories
        )
        if not series_path_exists:
            logger.info(f"Cleanup: Removing missing series '{series.name}'")
            stats["seasons"] += len(series.seasons)
            for season in series.seasons:
                stats["episodes"] += len(season.episodes)
            session.delete(series)
            stats["series"] += 1
            continue

        for season in series.seasons:
            season_path_exists = any(
                series.name
                and season.name
                and (Path(root) / series.name / season.name).is_dir()
                for root in root_directories
            )
            if not season_path_exists:
                logger.info(
                    f"Cleanup: Removing missing season '{season.name}' "
                    f"from series '{series.name}'"
                )
                stats["episodes"] += len(season.episodes)
                session.delete(season)
                stats["seasons"] += 1
                continue

            for episode in season.episodes:
                if episode.path and not Path(episode.path).exists():
                    logger.info(
                        f"Cleanup: Removing missing episode '{episode.name}' "
                        f"at '{episode.path}'"
                    )
                    session.delete(episode)
                    stats["episodes"] += 1

    # Purge seasons and series that became empty after episode deletion
    session.flush()
    session.expire_all()

    empty_seasons = session.scalars(
        select(Season)
        .join(Series)
        .where(Series.library_name == library_name)
        .where(~Season.episodes.any())
    ).all()
    for season in empty_seasons:
        season_series_name = (
            season.series.name if season.series and season.series.name else "Unknown"
        )
        logger.info(
            f"Cleanup: Removing empty season '{season.name}' "
            f"from series '{season_series_name}'"
        )
        session.delete(season)
        stats["seasons"] += 1

    session.flush()

    empty_series = session.scalars(
        select(Series)
        .where(Series.library_name == library_name)
        .where(~Series.seasons.any())
    ).all()
    for series in empty_series:
        logger.info(f"Cleanup: Removing empty series '{series.name}'")
        session.delete(series)
        stats["series"] += 1


def load_library(library_name: str) -> Dict[str, Any]:
    """
    Loads the library from the database and constructs a nested dictionary structure.
    """

    start_time = time.time()
    library_data = {}
    stats = {"series": 0, "seasons": 0, "episodes": 0}

    try:
        with get_session() as session:
            series_list = session.scalars(
                select(Series)
                .where(Series.library_name == library_name)
                .order_by(Series.name)
            ).all()

            for series in series_list:
                stats["series"] += 1
                stats["seasons"] += len(series.seasons)
                for season in series.seasons:
                    stats["episodes"] += len(season.episodes)
                if series.name is not None:
                    library_data[series.name] = _build_series_dict(series)

    except Exception:
        logger.exception(f"Error loading library '{library_name}' from database")
        return {}

    duration = time.time() - start_time
    logger.info(
        f"Loaded library '{library_name}' in {duration:.3f}s: {stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes."
    )
    return library_data


def _save_series_record(
    session: Session,
    library_name: str,
    series_name: str,
    series_data: Dict[str, Any],
    existing_series: Dict[str, Series],
    stats: Dict[str, int],
) -> Series:
    series = existing_series.get(series_name)
    if not series:
        series = Series(library_name=library_name, name=series_name)
        session.add(series)
    stats["series"] += 1

    series_metadata = series_data.get("metadata", {})
    series.jellyfin_id = series_metadata.get("jellyfin_id") or series.jellyfin_id
    series.tmdb_identifier = (
        series_metadata.get("tmdb_identifier") or series.tmdb_identifier
    )
    series.poster_path = series_metadata.get("poster_path") or series.poster_path
    series.overview = series_metadata.get("overview") or series.overview
    series.tmdb_name = series_metadata.get("tmdb_name") or series.tmdb_name
    if "locked_metadata" in series_metadata:
        series.locked_metadata = bool(series_metadata["locked_metadata"])
    series.first_air_date = (
        series_metadata.get("first_air_date") or series.first_air_date
    )
    return series


def _save_season_record(
    session: Session,
    series: Series,
    season_name: str,
    season_data: Dict[str, Any],
    existing_seasons: Dict[str, Season],
    stats: Dict[str, int],
) -> Season:
    season = existing_seasons.get(season_name)
    if not season:
        season = Season(name=season_name, series=series)
        session.add(season)
    stats["seasons"] += 1

    season_metadata = season_data.get("metadata", {})
    season.jellyfin_id = season_metadata.get("jellyfin_id") or season.jellyfin_id
    season.poster_path = season_metadata.get("poster_path") or season.poster_path
    return season


def _save_episode_record(
    session: Session,
    season: Season,
    episode_data: Dict[str, Any],
    existing_by_path: Dict[str, Episode],
    existing_by_number: Dict[int, Episode],
    stats: Dict[str, int],
) -> Episode:
    path = episode_data.get("path") or None
    tmdb_num = episode_data.get("tmdb_number")

    episode = None
    if path:
        episode = existing_by_path.get(path)
        # If not found by path, check if there was a missing/future episode placeholder
        if not episode and tmdb_num is not None:
            episode = existing_by_number.get(tmdb_num)
            if episode:
                # Promote placeholder to local file
                logger.info(
                    f"Promoting placeholder episode S{season.name} E{tmdb_num} to local path {path}"
                )
                episode.path = path
                existing_by_path[path] = episode
                existing_by_number.pop(tmdb_num, None)
    elif tmdb_num is not None:
        episode = existing_by_number.get(tmdb_num)

    if not episode:
        episode = Episode(path=path, season=season)
        session.add(episode)
        if path:
            existing_by_path[path] = episode
        elif tmdb_num is not None:
            existing_by_number[tmdb_num] = episode

    stats["episodes"] += 1

    episode.name = episode_data["name"]
    episode.jellyfin_id = episode_data.get("jellyfin_id") or episode.jellyfin_id
    episode.tmdb_episode_identifier = (
        episode_data.get("tmdb_episode_identifier") or episode.tmdb_episode_identifier
    )
    episode.tmdb_name = episode_data.get("tmdb_name") or episode.tmdb_name
    episode.tmdb_number = episode_data.get("tmdb_number") or episode.tmdb_number
    episode.watched = episode.watched or bool(episode_data.get("watched"))
    episode.date_added = episode_data.get("date_added") or episode.date_added or 0
    episode.air_date = episode_data.get("air_date") or episode.air_date
    episode.runtime = episode_data.get("runtime") or episode.runtime or 0
    if "video_codec" in episode_data:
        episode.video_codec = episode_data.get("video_codec") or episode.video_codec
    if "resolution" in episode_data:
        episode.resolution = episode_data.get("resolution") or episode.resolution

    if "audio_tracks" in episode_data:
        episode.audio_tracks = (
            json.dumps(episode_data["audio_tracks"])
            if episode_data["audio_tracks"]
            else episode.audio_tracks
        )
    if "subtitle_tracks" in episode_data:
        episode.subtitle_tracks = (
            json.dumps(episode_data["subtitle_tracks"])
            if episode_data["subtitle_tracks"]
            else episode.subtitle_tracks
        )
    return episode


def save_library(library_name: str, library: Dict[str, Any]) -> None:
    """
    Updates the database for the given library name using SQLAlchemy ORM.
    """

    start_time = time.time()
    stats = {"series": 0, "seasons": 0, "episodes": 0, "deleted": 0}

    try:
        with get_session() as session:
            existing_series = {
                series_obj.name: series_obj
                for series_obj in session.scalars(
                    select(Series).where(Series.library_name == library_name)
                ).all()
                if series_obj.name is not None
            }

            for series_name, series_data in library.items():
                series = _save_series_record(
                    session,
                    library_name,
                    series_name,
                    series_data,
                    existing_series,
                    stats,
                )

                existing_seasons = {
                    season_obj.name: season_obj
                    for season_obj in series.seasons
                    if season_obj.name is not None
                }

                for season_name, season_data in series_data.get("seasons", {}).items():
                    season = _save_season_record(
                        session,
                        series,
                        season_name,
                        season_data,
                        existing_seasons,
                        stats,
                    )

                    existing_by_path = {}
                    existing_by_number = {}
                    for episode_obj in season.episodes:
                        if episode_obj.path is not None:
                            existing_by_path[episode_obj.path] = episode_obj
                        elif episode_obj.tmdb_number is not None:
                            existing_by_number[episode_obj.tmdb_number] = episode_obj

                    for episode_data in season_data.get("episodes", []):
                        _save_episode_record(
                            session,
                            season,
                            episode_data,
                            existing_by_path,
                            existing_by_number,
                            stats,
                        )

    except Exception:
        logger.exception(f"Error saving library '{library_name}' to database")

    duration = time.time() - start_time
    logger.info(
        f"Library '{library_name}' updated in {duration:.3f}s: "
        f"{stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes saved. "
        f"{stats['deleted']} stale items removed."
    )


def load_movie_library(library_name: str) -> Dict[str, Any]:
    """
    Loads the movie library from the database and constructs a dictionary structure.
    """

    start_time = time.time()
    library_data = {}
    stats = {"movies": 0}

    try:
        with get_session() as session:
            movie_list = session.scalars(
                select(Movie)
                .where(Movie.library_name == library_name)
                .order_by(Movie.name)
            ).all()

            for movie in movie_list:
                stats["movies"] += 1
                if movie.name is not None:
                    library_data[movie.name] = _build_movie_dict(movie)
    except Exception:
        logger.exception(f"Error loading movie library '{library_name}' from database")
        return {}

    duration = time.time() - start_time
    logger.info(
        f"Loaded movie library '{library_name}' in {duration:.3f}s: {stats['movies']} movies."
    )
    return library_data


def save_movie_library(library_name: str, library: Dict[str, Any]) -> None:
    """
    Updates the database for the given movie library name using SQLAlchemy ORM.
    """

    start_time = time.time()
    stats = {"movies": 0, "deleted": 0}

    try:
        with get_session() as session:
            existing_movies_by_name = {
                m.name: m
                for m in session.scalars(
                    select(Movie).where(Movie.library_name == library_name)
                ).all()
                if m.name is not None
            }
            incoming_paths = [
                data.get("path") for data in library.values() if data.get("path")
            ]
            existing_movies_by_path = {}
            if incoming_paths:
                existing_movies_by_path = {
                    m.path: m
                    for m in session.scalars(
                        select(Movie).where(Movie.path.in_(incoming_paths))
                    ).all()
                    if m.path is not None
                }

            touched_movie_names = set()

            for movie_name, movie_data in library.items():
                touched_movie_names.add(movie_name)
                path = movie_data.get("path")

                movie = None
                if path and path in existing_movies_by_path:
                    movie = existing_movies_by_path[path]
                elif movie_name in existing_movies_by_name:
                    movie = existing_movies_by_name[movie_name]

                if not movie:
                    movie = Movie(library_name=library_name, name=movie_name)
                    session.add(movie)
                else:
                    if movie.name != movie_name:
                        stale_movie = existing_movies_by_name.get(movie_name)
                        if stale_movie and stale_movie is not movie:
                            logger.info(
                                f"Removing stale movie record '{movie_name}' to avoid name collision."
                            )
                            session.delete(stale_movie)
                            session.flush()
                            del existing_movies_by_name[movie_name]
                    movie.library_name = library_name
                    movie.name = movie_name

                stats["movies"] += 1

                if path:
                    existing_movies_by_path[path] = movie
                existing_movies_by_name[movie_name] = movie

                _apply_movie_fields(movie, movie_data)

    except Exception:
        logger.exception(f"Error saving movie library '{library_name}' to database")

    duration = time.time() - start_time
    logger.info(
        f"Movie library '{library_name}' updated in {duration:.3f}s: "
        f"{stats['movies']} movies saved. "
    )


def cleanup_library(library_name: str, root_directories: List[str]) -> Dict[str, int]:
    """
    Removes series/seasons/episodes or movies that are no longer present on the file system.
    Returns a dictionary with counts of deleted items.
    """

    start_time = time.time()
    stats = {"series": 0, "seasons": 0, "episodes": 0, "movies": 0}

    library_config = config.libraries.get(library_name, {})
    library_type = library_config.get("type", "tv")

    try:
        with get_session() as session:
            if library_type == "movie":
                _cleanup_movie_library(session, library_name, stats)
            else:
                _cleanup_tv_library(session, library_name, root_directories, stats)

        duration = time.time() - start_time
        if library_type == "movie":
            logger.info(
                f"Cleanup for movie library '{library_name}' completed in {duration:.3f}s: "
                f"{stats['movies']} movies removed."
            )
        else:
            logger.info(
                f"Cleanup for tv library '{library_name}' completed in {duration:.3f}s: "
                f"{stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes removed."
            )
    except Exception:
        logger.exception(f"Error during library cleanup for '{library_name}'")
        raise

    return stats
