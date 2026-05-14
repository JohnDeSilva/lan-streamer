import logging
import time
import re
import os
from pathlib import Path
from typing import Dict, Any, Set, Tuple, List, Generator, Optional
from contextlib import contextmanager

from sqlalchemy import (
    create_engine,
    func,
    event,
)
from sqlalchemy.orm import (
    sessionmaker,
    Session,
)
from sqlalchemy.engine import Engine

from .models import Base, Series, Season, Episode, Movie  # noqa: F401
from .config import config

logger = logging.getLogger(__name__)

DB_FILE = Path(os.getenv("LAN_STREAMER_DB", config.database_path))


# Database setup logic
_engine = None
_SessionLocal = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{DB_FILE}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


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


def init_db() -> bool:
    """
    Initializes the database.
    Ensures the DB directory exists.
    Returns True if the database was recreated.
    """
    try:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning(f"Could not create database directory {DB_FILE.parent}: {exc}")
    return False


# ---------------------------------------------------------------------------
# Pure ORM → dict builders — each converts a single ORM row to a plain dict.
# These are extracted for readability and to enable isolated unit testing.
# ---------------------------------------------------------------------------


def _build_episode_dict(episode: "Episode") -> Dict[str, Any]:
    """Maps a single Episode ORM row to its plain dictionary representation."""
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
    }


def _build_season_dict(season: "Season") -> Dict[str, Any]:
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


def _build_series_dict(series: "Series") -> Dict[str, Any]:
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


def _build_movie_dict(movie: "Movie") -> Dict[str, Any]:
    """Maps a single Movie ORM row to its plain dictionary representation."""
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
    }


def _apply_movie_fields(movie: "Movie", movie_data: Dict[str, Any]) -> None:
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
    movie.locked_metadata = (
        bool(movie_data.get("locked_metadata")) or movie.locked_metadata
    )
    movie.date_added = movie_data.get("date_added") or movie.date_added or 0
    movie.runtime = movie_data.get("runtime") or movie.runtime or 0
    movie.rating = movie_data.get("rating") or movie.rating or ""
    movie.genre = movie_data.get("genre") or movie.genre or ""
    movie.year = movie_data.get("year") or movie.year or 0
    movie.watched = movie.watched or bool(movie_data.get("watched"))
    movie.last_played_position = (
        movie_data.get("last_played_position") or movie.last_played_position or 0
    )


# ---------------------------------------------------------------------------
# Isolated sync helpers — each handles one strategy of the Jellyfin sync pass.
# ---------------------------------------------------------------------------


def _sync_watched_by_ids(session: "Session", watched_ids: Set[str]) -> int:
    """
    Marks all Episodes and Movies whose Jellyfin ID is in *watched_ids* as watched.
    Returns the combined update count.
    """
    if not watched_ids:
        return 0
    count = int(
        session.query(Episode)
        .filter(Episode.jellyfin_id.in_(watched_ids))
        .update({"watched": True}, synchronize_session=False)
    )
    count += int(
        session.query(Movie)
        .filter(Movie.jellyfin_id.in_(watched_ids))
        .update({"watched": True}, synchronize_session=False)
    )
    return count


def _sync_watched_by_paths(session: "Session", watched_paths: Set[str]) -> int:
    """
    Marks all Episodes and Movies whose file path is in *watched_paths* as watched.
    Returns the combined update count.
    """
    if not watched_paths:
        return 0
    count = int(
        session.query(Episode)
        .filter(Episode.watched.is_(False), Episode.path.in_(watched_paths))
        .update({"watched": True}, synchronize_session=False)
    )
    count += int(
        session.query(Movie)
        .filter(Movie.watched.is_(False), Movie.path.in_(watched_paths))
        .update({"watched": True}, synchronize_session=False)
    )
    return count


def _sync_watched_by_names(
    session: "Session", watched_names: Set[Tuple[str, str]]
) -> int:
    """
    Marks Episodes whose (series_name, episode_name) pair is in *watched_names* as watched.
    Returns the total update count.
    """
    if not watched_names:
        return 0
    count = 0
    for series_name, episode_name in watched_names:
        episode_ids = [
            row.id
            for row in session.query(Episode.id)
            .join(Season)
            .join(Series)
            .filter(
                Episode.watched.is_(False),
                func.lower(Series.name) == series_name.lower(),
                func.lower(Episode.name) == episode_name.lower(),
            )
            .all()
        ]
        if episode_ids:
            count += int(
                session.query(Episode)
                .filter(Episode.id.in_(episode_ids))
                .update({"watched": True}, synchronize_session=False)
            )
    return count


# ---------------------------------------------------------------------------
# Isolated cleanup helpers — each handles one library type's cleanup pass.
# ---------------------------------------------------------------------------


def _cleanup_movie_library(
    session: "Session",
    library_name: str,
    stats: Dict[str, int],
) -> None:
    """Removes Movie records whose file path no longer exists on disk."""
    movie_list = session.query(Movie).filter(Movie.library_name == library_name).all()
    for movie in movie_list:
        if movie.path and not Path(movie.path).exists():
            logger.info(
                f"Cleanup: Removing missing movie '{movie.name}' at '{movie.path}'"
            )
            session.delete(movie)
            stats["movies"] += 1


def _cleanup_tv_library(
    session: "Session",
    library_name: str,
    root_directories: List[str],
    stats: Dict[str, int],
) -> None:
    """
    Removes Series/Season/Episode records whose corresponding paths no longer
    exist on disk, then purges any empty seasons or series left behind.
    """
    series_list = (
        session.query(Series).filter(Series.library_name == library_name).all()
    )

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

    empty_seasons = (
        session.query(Season)
        .join(Series)
        .filter(Series.library_name == library_name)
        .filter(~Season.episodes.any())
        .all()
    )
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

    empty_series = (
        session.query(Series)
        .filter(Series.library_name == library_name)
        .filter(~Series.seasons.any())
        .all()
    )
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
            series_list = (
                session.query(Series)
                .filter(Series.library_name == library_name)
                .order_by(Series.name)
                .all()
            )

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
    series.locked_metadata = (
        bool(series_metadata.get("locked_metadata")) or series.locked_metadata
    )
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
    existing_episodes: Dict[str, Episode],
    stats: Dict[str, int],
) -> Episode:
    path = episode_data["path"]
    episode = existing_episodes.get(path)
    if not episode:
        episode = Episode(path=path, season=season)
        session.add(episode)
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
                for series_obj in session.query(Series)
                .filter(Series.library_name == library_name)
                .all()
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

                    existing_episodes = {
                        episode_obj.path: episode_obj
                        for episode_obj in season.episodes
                        if episode_obj.path is not None
                    }

                    for episode_data in season_data.get("episodes", []):
                        _save_episode_record(
                            session, season, episode_data, existing_episodes, stats
                        )

    # Deletions are now handled exclusively by cleanup_library to prevent accidental data loss
    # during temporary drive disconnection or partial scans.
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
            movie_list = (
                session.query(Movie)
                .filter(Movie.library_name == library_name)
                .order_by(Movie.name)
                .all()
            )

            for movie in movie_list:
                stats["movies"] += 1
                movie_dict: Dict[str, Any] = {
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
                }

                if movie.name is not None:
                    library_data[movie.name] = movie_dict
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
                for m in session.query(Movie)
                .filter(Movie.library_name == library_name)
                .all()
                if m.name is not None
            }
            incoming_paths = [
                data.get("path") for data in library.values() if data.get("path")
            ]
            existing_movies_by_path = {}
            if incoming_paths:
                existing_movies_by_path = {
                    m.path: m
                    for m in session.query(Movie)
                    .filter(Movie.path.in_(incoming_paths))
                    .all()
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


def update_episode_watched_status(path: str, watched: bool) -> None:
    try:
        logger.info(f"Updating watched status for {path} to {watched}")
        with get_session() as session:
            episode = session.query(Episode).filter(Episode.path == path).first()
            if episode:
                episode.watched = watched
            else:
                movie = session.query(Movie).filter(Movie.path == path).first()
                if movie:
                    movie.watched = watched
    except Exception:
        logger.exception(f"Error updating watched status for {path}")


def update_episode_path(old_path: str, new_path: str) -> None:
    """Updates the file path for an episode in the database."""
    try:
        logger.info(f"Updating episode path from {old_path} to {new_path}")
        with get_session() as session:
            episode = session.query(Episode).filter(Episode.path == old_path).first()
            if episode:
                episode.path = new_path
    except Exception:
        logger.exception(f"Error updating episode path from {old_path} to {new_path}")


def update_episode_playback_position(path: str, position: int) -> bool:
    """Saves the last played playback offset (in seconds) for a given episode."""
    try:
        with get_session() as session:
            episode = session.query(Episode).filter(Episode.path == path).first()
            if episode:
                episode.last_played_position = position
                return True
            movie = session.query(Movie).filter(Movie.path == path).first()
            if movie:
                movie.last_played_position = position
                return True
    except Exception:
        logger.exception(f"Error updating playback position for {path}")
    return False


def get_episode_playback_position(path: str) -> int:
    """Retrieves the stored last played playback offset (in seconds) for a given episode."""
    try:
        with get_session() as session:
            episode = session.query(Episode).filter(Episode.path == path).first()
            if episode and episode.last_played_position:
                return int(episode.last_played_position)
            movie = session.query(Movie).filter(Movie.path == path).first()
            if movie and movie.last_played_position:
                return int(movie.last_played_position)
    except Exception:
        logger.exception(f"Error retrieving playback position for {path}")
    return 0


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
            season = (
                session.query(Season)
                .join(Series)
                .filter(
                    Series.library_name == library_name,
                    Series.name == series_name,
                    Season.name == season_name,
                )
                .first()
            )
            if season:
                for episode in season.episodes:
                    episode.watched = watched
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
            series = (
                session.query(Series)
                .filter(Series.library_name == library_name, Series.name == series_name)
                .first()
            )
            if series:
                for season in series.seasons:
                    for episode in season.episodes:
                        episode.watched = watched
    except Exception:
        logger.exception(f"Error updating watched status for series {series_name}")


def sync_watched_from_jellyfin_data(
    watched_ids: Set[str],
    watched_paths: Set[str],
    watched_names: Set[Tuple[str, str]] | None = None,
) -> int:
    """
    Bulk-updates watched=True for all episodes whose Jellyfin ID is in watched_ids
    OR whose file path is in watched_paths
    OR whose (series_name, episode_name) is in watched_names.
    Returns the total number of rows updated.
    """
    if not watched_ids and not watched_paths and not watched_names:
        logger.info("No watched IDs, paths, or names provided for Jellyfin sync.")
        return 0

    start_time = time.time()
    logger.info(
        f"Starting bulk watched status sync: {len(watched_ids)} IDs, "
        f"{len(watched_paths)} paths, {len(watched_names or [])} names."
    )
    updated_count = 0
    try:
        with get_session() as session:
            updated_count += _sync_watched_by_ids(session, watched_ids)
            updated_count += _sync_watched_by_paths(session, watched_paths)
            updated_count += _sync_watched_by_names(session, watched_names or set())

        duration = time.time() - start_time
        logger.info(
            f"sync_watched_from_jellyfin_data: marked {updated_count} episodes as "
            f"watched in {duration:.3f}s."
        )
    except Exception:
        logger.exception("Error in sync_watched_from_jellyfin_data")

    return updated_count


def get_all_episodes_with_jellyfin_id() -> list:
    """Returns a list of all episodes and movies that have a Jellyfin ID associated."""
    episodes = []
    try:
        with get_session() as session:
            rows = (
                session.query(Episode)
                .filter(Episode.jellyfin_id.is_not(None), Episode.jellyfin_id != "")
                .all()
            )
            for row in rows:
                episodes.append(
                    {
                        "name": row.name,
                        "path": row.path,
                        "jellyfin_id": row.jellyfin_id,
                        "watched": row.watched,
                    }
                )
            mrows = (
                session.query(Movie)
                .filter(Movie.jellyfin_id.is_not(None), Movie.jellyfin_id != "")
                .all()
            )
            for mrow in mrows:
                episodes.append(
                    {
                        "name": mrow.name,
                        "path": mrow.path,
                        "jellyfin_id": mrow.jellyfin_id,
                        "watched": mrow.watched,
                    }
                )
    except Exception:
        logger.exception("Error fetching episodes/movies with Jellyfin ID")
    return episodes


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


def get_items_missing_runtime() -> List[Dict[str, Any]]:
    """Retrieves all episodes and movies whose runtime is 0 or missing."""
    items_list: List[Dict[str, Any]] = []
    try:
        with get_session() as session:
            episodes = (
                session.query(Episode)
                .filter((Episode.runtime == 0) | (Episode.runtime.is_(None)))
                .all()
            )
            for episode in episodes:
                if episode.path:
                    items_list.append(
                        {"id": episode.id, "path": episode.path, "type": "episode"}
                    )

            movies = (
                session.query(Movie)
                .filter((Movie.runtime == 0) | (Movie.runtime.is_(None)))
                .all()
            )
            for movie in movies:
                if movie.path:
                    items_list.append(
                        {"id": movie.id, "path": movie.path, "type": "movie"}
                    )
    except Exception:
        logger.exception("Error fetching items missing runtime")
    return items_list


def update_item_runtime(
    item_identifier: int, item_type: str, runtime_minutes: int
) -> None:
    """Updates the runtime field for a given episode or movie."""
    try:
        with get_session() as session:
            if item_type == "episode":
                episode = (
                    session.query(Episode).filter(Episode.id == item_identifier).first()
                )
                if episode:
                    episode.runtime = runtime_minutes
            elif item_type == "movie":
                movie = session.query(Movie).filter(Movie.id == item_identifier).first()
                if movie:
                    movie.runtime = runtime_minutes
    except Exception:
        logger.exception(f"Error updating runtime for {item_type} ID {item_identifier}")
