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
    select,
    update,
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
_db_initialized: bool = False


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
    logger.debug("Database session opened.")
    try:
        yield session
        logger.debug("Database session committing...")
        session.commit()
        logger.debug("Database session committed successfully.")
    except Exception as exc:
        logger.warning(f"Database session rollback triggered due to error: {exc}")
        session.rollback()
        raise
    finally:
        logger.debug("Database session closed.")
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
    Initializes the database by running Alembic migrations.
    Ensures the DB directory exists.
    Returns True if the database was successfully initialized/upgraded.
    """
    global _db_initialized
    if _db_initialized:
        logger.debug(
            "Database already initialized in this session; skipping migration check."
        )
        return False

    logger.info(f"Initializing database at: '{DB_FILE}'")
    try:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning(f"Could not create database directory {DB_FILE.parent}: {exc}")
        return False

    try:
        import sys
        from alembic.config import Config
        from alembic import command

        if getattr(sys, "frozen", False):
            base_path: Path = Path(getattr(sys, "_MEIPASS"))
        else:
            base_path = Path(__file__).parent.parent.parent

        alembic_ini_path: Path = base_path / "alembic.ini"
        alembic_directory_path: Path = base_path / "alembic"

        logger.info(f"Loading Alembic configuration from: '{alembic_ini_path}'")
        alembic_config: Config = Config(str(alembic_ini_path))

        # Dynamically set options to reference the absolute runtime paths
        alembic_config.set_main_option("script_location", str(alembic_directory_path))
        alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{DB_FILE}")

        logger.info("Executing database migration to latest revision (head)...")
        command.upgrade(alembic_config, "head")
        logger.info("Database migration completed successfully.")

        _db_initialized = True
        return True
    except Exception as exc:
        logger.error(f"Failed to run database migrations: {exc}", exc_info=True)
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
        "last_played_at": episode.last_played_at or 0,
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
        "last_played_at": movie.last_played_at or 0,
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
    logger.debug(f"Syncing watched status by ID for {len(watched_ids)} items")
    count = int(
        session.execute(
            update(Episode)
            .where(Episode.jellyfin_id.in_(watched_ids))
            .values(watched=True)
        ).rowcount  # type: ignore[attr-defined]
        or 0
    )
    count += int(
        session.execute(
            update(Movie).where(Movie.jellyfin_id.in_(watched_ids)).values(watched=True)
        ).rowcount  # type: ignore[attr-defined]
        or 0
    )
    logger.debug(f"Synced by ID: marked {count} items as watched")
    return count


def _sync_watched_by_paths(session: "Session", watched_paths: Set[str]) -> int:
    """
    Marks all Episodes and Movies whose file path is in *watched_paths* as watched.
    Returns the combined update count.
    """
    if not watched_paths:
        return 0
    logger.debug(f"Syncing watched status by path for {len(watched_paths)} items")
    count = int(
        session.execute(
            update(Episode)
            .where(Episode.watched.is_(False), Episode.path.in_(watched_paths))
            .values(watched=True)
        ).rowcount  # type: ignore[attr-defined]
        or 0
    )
    count += int(
        session.execute(
            update(Movie)
            .where(Movie.watched.is_(False), Movie.path.in_(watched_paths))
            .values(watched=True)
        ).rowcount  # type: ignore[attr-defined]
        or 0
    )
    logger.debug(f"Synced by path: marked {count} items as watched")
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
    logger.debug(f"Syncing watched status by names for {len(watched_names)} pairs")
    count = 0
    for series_name, episode_name in watched_names:
        episode_ids = list(
            session.scalars(
                select(Episode.id)
                .join(Season)
                .join(Series)
                .where(
                    Episode.watched.is_(False),
                    func.lower(Series.name) == series_name.lower(),
                    func.lower(Episode.name) == episode_name.lower(),
                )
            ).all()
        )
        if episode_ids:
            logger.debug(
                f"Found match: series '{series_name}', episode '{episode_name}' -> Episode IDs: {episode_ids}"
            )
            count += int(
                session.execute(
                    update(Episode)
                    .where(Episode.id.in_(episode_ids))
                    .values(watched=True)
                ).rowcount  # type: ignore[attr-defined]
                or 0
            )
    logger.debug(f"Synced by names: marked {count} items as watched")
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
    session: "Session",
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
    items: list = []
    try:
        with get_session() as session:
            model: type[Episode] | type[Movie]
            for model in (Episode, Movie):
                rows = session.scalars(
                    select(model).where(
                        model.jellyfin_id.is_not(None),
                        model.jellyfin_id != "",
                    )
                ).all()
                row: Episode | Movie
                for row in rows:  # type: ignore[assignment]
                    items.append(
                        {
                            "name": row.name,
                            "path": row.path,
                            "jellyfin_id": row.jellyfin_id,
                            "watched": row.watched,
                        }
                    )
    except Exception:
        logger.exception("Error fetching episodes/movies with Jellyfin ID")
    return items


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
    item_identifier: int, item_type: str, runtime_minutes: int
) -> None:
    """Updates the runtime field for a given episode or movie."""
    try:
        with get_session() as session:
            if item_type == "episode":
                episode = session.scalars(
                    select(Episode).where(Episode.id == item_identifier)
                ).first()
                if episode:
                    episode.runtime = runtime_minutes
            elif item_type == "movie":
                movie = session.scalars(
                    select(Movie).where(Movie.id == item_identifier)
                ).first()
                if movie:
                    movie.runtime = runtime_minutes
    except Exception:
        logger.exception(f"Error updating runtime for {item_type} ID {item_identifier}")


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

            result = {
                "title": next_episode.tmdb_name
                if next_episode.tmdb_name
                else (next_episode.name or "Unknown"),
                "season": next_season.name or "Unknown",
                "episode_number": next_episode.tmdb_number
                if next_episode.tmdb_number is not None
                else calculated_episode_number,
                "path": next_episode.path,
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
    import re

    def natural_sort_key(s: str) -> list:
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

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
