"""Mapping updates service — updates file-to-episode/movie mappings when files change, move, or are removed."""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import select

from lan_streamer.db.models import Series, Episode, MediaFile
from lan_streamer.db.library_tv import _cleanup_tv_library
from lan_streamer.db.library_movie import _cleanup_movie_library
from lan_streamer.system.config import config

logger = logging.getLogger("lan_streamer.services.mapping_updates")


def get_session() -> Any:
    """Get a database session using lazy import to avoid circular dependencies.

    Returns
    -------
    Any
        A SQLAlchemy session object.
    """
    import lan_streamer.db.connection  # noqa: PLC0415

    return lan_streamer.db.connection.get_session()


def update_file_path(old_path: str, new_path: str) -> None:
    """Update the file path for a media file (episode or movie) in the database.

    Searches for a ``MediaFile`` record matching *old_path* and updates it to
    *new_path*.  If the corresponding episode or movie had that path set as its
    ``default_path``, that is also updated.

    Parameters
    ----------
    old_path : str
        The current (old) file path to replace.
    new_path : str
        The new file path to store.
    """
    try:
        logger.debug(
            "Executing update_file_path: old_path=%s, new_path=%s", old_path, new_path
        )
        logger.info("Updating file path from %s to %s", old_path, new_path)
        with get_session() as session:
            from lan_streamer.db.models import MediaFile  # noqa: PLC0415

            mf = session.scalars(
                select(MediaFile).where(MediaFile.path == old_path)
            ).first()
            if mf:
                mf.path = new_path
                for ep in mf.episodes:
                    if ep.default_path == old_path:
                        ep.default_path = new_path
                for mv in mf.movies:
                    if mv.default_path == old_path:
                        mv.default_path = new_path
                logger.debug("Updated MediaFile path to %s", new_path)
            else:
                episode = session.scalars(
                    select(Episode).where(Episode.default_path == old_path)
                ).first()
                if episode:
                    episode.default_path = new_path
                    logger.debug("Updated Episode default_path to %s", new_path)
                else:
                    logger.debug("No MediaFile or Episode found for path: %s", old_path)
    except Exception:
        logger.exception("Error updating file path from %s to %s", old_path, new_path)


def is_movie_path(path: str) -> bool:
    """Return ``True`` if the given path corresponds to a movie in the database.

    Parameters
    ----------
    path : str
        The file path to check.

    Returns
    -------
    bool
        ``True`` when a ``Movie`` record is associated with the path.
    """
    try:
        logger.debug("Executing is_movie_path: path=%s", path)
        with get_session() as session:
            from lan_streamer.db.models import MediaFile, Movie  # noqa: PLC0415

            movie = session.scalars(
                select(Movie).join(Movie.media_files).where(MediaFile.path == path)
            ).first()
            result = movie is not None
            logger.debug("is_movie_path result for path=%s: %s", path, result)
            return result
    except Exception:
        logger.exception("Error checking if path is movie: %s", path)
        return False


def remove_series(library_name: str, series_name: str) -> None:
    """Delete a series record (and its cascaded seasons/episodes) from the database.

    Parameters
    ----------
    library_name : str
        Name of the library the series belongs to.
    series_name : str
        Name of the series to remove.
    """
    try:
        logger.debug(
            "Executing remove_series: library=%s, series=%s", library_name, series_name
        )
        logger.info(
            "Deleting series '%s' from library '%s' in database",
            series_name,
            library_name,
        )
        with get_session() as session:
            series = session.scalars(
                select(Series).where(
                    Series.library_name == library_name, Series.name == series_name
                )
            ).first()
            if series:
                session.delete(series)
                logger.debug(
                    "Deleted series '%s' from library '%s' successfully",
                    series_name,
                    library_name,
                )
            else:
                logger.debug(
                    "Series '%s' not found for deletion in library '%s'",
                    series_name,
                    library_name,
                )
    except Exception:
        logger.exception("Error deleting series '%s'", series_name)


def remove_episode_by_path(path: str) -> None:
    """Delete an episode record identified by its file path.

    Parameters
    ----------
    path : str
        The file path of the episode to remove.
    """
    try:
        logger.debug("Executing remove_episode_by_path: path=%s", path)
        logger.info("Deleting episode record for path: %s", path)
        with get_session() as session:
            from lan_streamer.db.models import Episode, MediaFile  # noqa: PLC0415

            episode = session.scalars(
                select(Episode).join(Episode.media_files).where(MediaFile.path == path)
            ).first()
            if episode:
                session.delete(episode)
                logger.debug("Deleted episode record for path: %s successfully", path)
            else:
                logger.debug("Episode record not found for deletion for path: %s", path)
    except Exception:
        logger.exception("Error deleting episode record for '%s'", path)


def _cleanup_orphaned_media_files(
    session: Any, root_directories: List[str], stats: Dict[str, int]
) -> None:
    """Remove ``MediaFile`` records under *root_directories* whose physical file no longer exists.

    Parameters
    ----------
    session : Any
        An active SQLAlchemy session.
    root_directories : list of str
        List of root directory paths to scope the cleanup to.
    stats : dict of str -> int
        A mutable statistics dictionary; the key ``"media_files_removed"`` will be
        incremented by the number of records removed.
    """

    media_files = session.scalars(select(MediaFile)).all()
    removed_count = 0
    for mf in media_files:
        in_library = False
        try:
            mf_path = Path(mf.path)
            for root in root_directories:
                try:
                    mf_path.relative_to(Path(root))
                    in_library = True
                    break
                except ValueError:
                    continue
        except Exception:
            pass

        if in_library:
            try:
                if not Path(mf.path).exists():
                    logger.info(
                        "Cleanup: Removing missing MediaFile record at '%s'", mf.path
                    )
                    session.delete(mf)
                    removed_count += 1
            except Exception:
                pass
    stats["media_files_removed"] = stats.get("media_files_removed", 0) + removed_count


def cleanup_library_records(
    library_name: str, root_directories: List[str]
) -> Dict[str, int]:
    """Remove series/seasons/episodes or movies that are no longer present on the file system.

    Parameters
    ----------
    library_name : str
        Name of the library to clean up.
    root_directories : list of str
        Root directories that scope which media files are considered part of this library.

    Returns
    -------
    dict of str -> int
        A dictionary with counts of deleted items for the keys ``"series"``,
        ``"seasons"``, ``"episodes"``, ``"movies"``, and ``"media_files_removed"``.
    """
    start_time = time.time()
    stats: Dict[str, int] = {
        "series": 0,
        "seasons": 0,
        "episodes": 0,
        "movies": 0,
        "media_files_removed": 0,
    }

    library_config = config.libraries.get(library_name, {})
    library_type = library_config.get("type", "tv")

    try:
        with get_session() as session:
            if library_type == "movie":
                _cleanup_movie_library(session, library_name, stats)
            else:
                _cleanup_tv_library(session, library_name, root_directories, stats)
            _cleanup_orphaned_media_files(session, root_directories, stats)

        duration = time.time() - start_time
        if library_type == "movie":
            logger.info(
                "Cleanup for movie library '%s' completed in %.3fs: "
                "%d movies removed. Removed %d missing MediaFile records.",
                library_name,
                duration,
                stats["movies"],
                stats["media_files_removed"],
            )
        else:
            logger.info(
                "Cleanup for tv library '%s' completed in %.3fs: "
                "%d series, %d seasons, %d episodes removed. "
                "Removed %d missing MediaFile records.",
                library_name,
                duration,
                stats["series"],
                stats["seasons"],
                stats["episodes"],
                stats["media_files_removed"],
            )
    except Exception:
        logger.exception("Error during library cleanup for '%s'", library_name)
        raise

    return stats
