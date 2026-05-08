import logging
import time
import re
import os
from pathlib import Path
from typing import Dict, Any, Set, Tuple, List
from contextlib import contextmanager

from sqlalchemy import (
    create_engine,
    func,
    event,
)
from sqlalchemy.orm import (
    sessionmaker,
)

from .models import Base, Series, Season, Episode  # noqa: F401
from .config import config

logger = logging.getLogger(__name__)

DB_FILE = Path(os.getenv("LAN_STREAMER_DB", config.database_path))


# Database setup logic
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{DB_FILE}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
    return _SessionLocal


@contextmanager
def get_session():
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


def natural_sort_key(s):
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
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    return False


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
                series_dict = {
                    "metadata": {
                        "jellyfin_id": series.jellyfin_id,
                        "tmdb_identifier": series.tmdb_identifier,
                        "poster_path": series.poster_path,
                        "overview": series.overview,
                        "tmdb_name": series.tmdb_name,
                        "locked_metadata": bool(series.locked_metadata),
                    },
                    "seasons": {},
                }

                for season in series.seasons:
                    stats["seasons"] += 1
                    season_dict = {
                        "metadata": {
                            "jellyfin_id": season.jellyfin_id,
                            "poster_path": season.poster_path,
                        },
                        "episodes": [],
                    }

                    for episode in season.episodes:
                        stats["episodes"] += 1
                        episode_data = {
                            "name": episode.name,
                            "path": episode.path,
                            "jellyfin_id": episode.jellyfin_id,
                            "tmdb_episode_identifier": episode.tmdb_episode_identifier,
                            "tmdb_name": episode.tmdb_name,
                            "tmdb_number": episode.tmdb_number,
                            "watched": bool(episode.watched),
                            "date_added": episode.date_added or 0,
                        }
                        season_dict["episodes"].append(episode_data)

                    season_dict["episodes"].sort(
                        key=lambda x: natural_sort_key(x["name"])
                    )
                    series_dict["seasons"][season.name] = season_dict

                library_data[series.name] = series_dict
    except Exception as e:
        logger.error(f"Error loading library '{library_name}' from database: {e}")
        return {}

    duration = time.time() - start_time
    logger.info(
        f"Loaded library '{library_name}' in {duration:.3f}s: {stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes."
    )
    return library_data


def save_library(library_name: str, library: Dict[str, Any]):
    """
    Updates the database for the given library name using SQLAlchemy ORM.
    """
    start_time = time.time()
    stats = {"series": 0, "seasons": 0, "episodes": 0, "deleted": 0}

    try:
        with get_session() as session:
            existing_series = {
                s.name: s
                for s in session.query(Series)
                .filter(Series.library_name == library_name)
                .all()
            }
            touched_series_names = set()

            for series_name, series_data in library.items():
                touched_series_names.add(series_name)
                series_metadata = series_data.get("metadata", {})

                series = existing_series.get(series_name)
                if not series:
                    series = Series(library_name=library_name, name=series_name)
                    session.add(series)
                    stats["series"] += 1

                series.jellyfin_id = series_metadata.get("jellyfin_id")
                series.tmdb_identifier = series_metadata.get("tmdb_identifier")
                series.poster_path = series_metadata.get("poster_path")
                series.overview = series_metadata.get("overview")
                series.tmdb_name = series_metadata.get("tmdb_name")
                series.locked_metadata = bool(series_metadata.get("locked_metadata"))

                existing_seasons = {sea.name: sea for sea in series.seasons}
                touched_season_names = set()

                for season_name, season_data in series_data.get("seasons", {}).items():
                    touched_season_names.add(season_name)
                    season_metadata = season_data.get("metadata", {})

                    season = existing_seasons.get(season_name)
                    if not season:
                        season = Season(name=season_name, series=series)
                        session.add(season)
                        stats["seasons"] += 1

                    season.jellyfin_id = season_metadata.get("jellyfin_id")
                    season.poster_path = season_metadata.get("poster_path")

                    existing_episodes = {ep.path: ep for ep in season.episodes}
                    touched_episode_paths = set()

                    for ep_data in season_data.get("episodes", []):
                        path = ep_data["path"]
                        touched_episode_paths.add(path)

                        episode = existing_episodes.get(path)
                        if not episode:
                            episode = Episode(path=path, season=season)
                            session.add(episode)
                            stats["episodes"] += 1

                        episode.name = ep_data["name"]
                        episode.jellyfin_id = ep_data.get("jellyfin_id")
                        episode.tmdb_episode_identifier = ep_data.get(
                            "tmdb_episode_identifier"
                        )
                        episode.tmdb_name = ep_data.get("tmdb_name")
                        episode.tmdb_number = ep_data.get("tmdb_number")
                        episode.watched = episode.watched or bool(
                            ep_data.get("watched")
                        )
                        episode.date_added = ep_data.get("date_added", 0)

                    for path, ep in existing_episodes.items():
                        if path not in touched_episode_paths:
                            session.delete(ep)
                            stats["deleted"] += 1

                for name, sea in existing_seasons.items():
                    if name not in touched_season_names:
                        session.delete(sea)
                        stats["deleted"] += 1

            for name, s in existing_series.items():
                if name not in touched_series_names:
                    session.delete(s)
                    stats["deleted"] += 1
    except Exception as e:
        logger.error(f"Error saving library '{library_name}' to database: {e}")

    duration = time.time() - start_time
    logger.info(
        f"Library '{library_name}' updated in {duration:.3f}s: "
        f"{stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes saved. "
        f"{stats['deleted']} stale items removed."
    )


def update_episode_watched_status(path: str, watched: bool):
    try:
        logger.info(f"Updating watched status for {path} to {watched}")
        with get_session() as session:
            episode = session.query(Episode).filter(Episode.path == path).first()
            if episode:
                episode.watched = watched
    except Exception as e:
        logger.error(f"Error updating watched status for {path}: {e}")


def update_season_watched_status(
    library_name: str, series_name: str, season_name: str, watched: bool
):
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
    except Exception as e:
        logger.error(
            f"Error updating watched status for {series_name} - {season_name}: {e}"
        )


def sync_watched_from_jellyfin_data(
    watched_ids: Set[str],
    watched_paths: Set[str],
    watched_names: Set[Tuple[str, str]] = None,
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
        f"Starting bulk watched status sync: {len(watched_ids)} IDs, {len(watched_paths)} paths, {len(watched_names or [])} names."
    )
    updated_count = 0
    try:
        with get_session() as session:
            if watched_ids:
                res = (
                    session.query(Episode)
                    .filter(Episode.jellyfin_id.in_(watched_ids))
                    .update({"watched": True}, synchronize_session=False)
                )
                updated_count += res

            if watched_paths:
                res = (
                    session.query(Episode)
                    .filter(Episode.watched.is_(False), Episode.path.in_(watched_paths))
                    .update({"watched": True}, synchronize_session=False)
                )
                updated_count += res

            if watched_names:
                for series_name, episode_name in watched_names:
                    # Find IDs first because update() doesn't support join() directly in all dialects
                    ep_ids = [
                        e.id
                        for e in session.query(Episode.id)
                        .join(Season)
                        .join(Series)
                        .filter(
                            Episode.watched.is_(False),
                            func.lower(Series.name) == series_name.lower(),
                            func.lower(Episode.name) == episode_name.lower(),
                        )
                        .all()
                    ]
                    if ep_ids:
                        res = (
                            session.query(Episode)
                            .filter(Episode.id.in_(ep_ids))
                            .update({"watched": True}, synchronize_session=False)
                        )
                        updated_count += res

        duration = time.time() - start_time
        logger.info(
            f"sync_watched_from_jellyfin_data: marked {updated_count} episodes as watched in {duration:.3f}s."
        )
    except Exception as exception:
        logger.error(f"Error in sync_watched_from_jellyfin_data: {exception}")

    return updated_count


def get_all_episodes_with_jellyfin_id() -> list:
    """Returns a list of all episodes that have a Jellyfin ID associated."""
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
    except Exception as e:
        logger.error(f"Error fetching episodes with Jellyfin ID: {e}")
    return episodes


def cleanup_library(library_name: str, root_directories: List[str]) -> Dict[str, int]:
    """
    Removes series, seasons, and episodes that are no longer present on the file system.
    Returns a dictionary with counts of deleted items.
    """
    start_time = time.time()
    stats = {"series": 0, "seasons": 0, "episodes": 0}
    try:
        with get_session() as session:
            # 1. Check all series in this library
            series_list = (
                session.query(Series).filter(Series.library_name == library_name).all()
            )

            for series in series_list:
                series_path_exists = False
                for root in root_directories:
                    if (Path(root) / series.name).is_dir():
                        series_path_exists = True
                        break

                if not series_path_exists:
                    logger.info(f"Cleanup: Removing missing series '{series.name}'")
                    # Count children before deletion for accurate stats
                    stats["seasons"] += len(series.seasons)
                    for season in series.seasons:
                        stats["episodes"] += len(season.episodes)

                    session.delete(series)
                    stats["series"] += 1
                    continue

                # 2. Check seasons within existing series
                for season in series.seasons:
                    season_path_exists = False
                    for root in root_directories:
                        if (Path(root) / series.name / season.name).is_dir():
                            season_path_exists = True
                            break

                    if not season_path_exists:
                        logger.info(
                            f"Cleanup: Removing missing season '{season.name}' from series '{series.name}'"
                        )
                        # Count episodes before deletion for accurate stats
                        stats["episodes"] += len(season.episodes)
                        session.delete(season)
                        stats["seasons"] += 1
                        continue

                    # 3. Check episodes within existing seasons
                    for episode in season.episodes:
                        if not Path(episode.path).exists():
                            logger.info(
                                f"Cleanup: Removing missing episode '{episode.name}' at '{episode.path}'"
                            )
                            session.delete(episode)
                            stats["episodes"] += 1

            # 4. Clean up seasons/series that became empty after episode deletion
            session.flush()
            session.expire_all()

            # Find seasons with no episodes
            empty_seasons = (
                session.query(Season)
                .join(Series)
                .filter(Series.library_name == library_name)
                .filter(~Season.episodes.any())
                .all()
            )
            for season in empty_seasons:
                logger.info(
                    f"Cleanup: Removing empty season '{season.name}' from series '{season.series.name}'"
                )
                session.delete(season)
                stats["seasons"] += 1

            session.flush()

            # Find series with no seasons
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

        duration = time.time() - start_time
        logger.info(
            f"Cleanup for '{library_name}' completed in {duration:.3f}s: "
            f"{stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes removed."
        )
    except Exception as e:
        logger.error(f"Error during library cleanup for '{library_name}': {e}")
        raise

    return stats
