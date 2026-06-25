"""
Backward-compatible shim for db/library.py.

The library persistence functions have been split into focused modules:
  - library_shared.py  → get_session, _update_field_safely, _sync_media_files
  - library_tv.py      → load_library, save_library, save_season_data, TV cleanup helpers
  - library_movie.py   → load_movie_library, save_movie_library, save_movie_data, _apply_movie_fields

All public names are re-exported from here so existing import sites continue to work.
cleanup_library is defined here as it bridges both TV and Movie cleanup.
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Any

from sqlalchemy import select

from lan_streamer.system.config import config
from lan_streamer.db.library_shared import (  # noqa: F401
    get_session,
    _update_field_safely,
    _sync_media_files,
    get_directory_mtime,
    save_directory_mtime,
)
from lan_streamer.db.library_tv import (  # noqa: F401
    load_library,
    save_library,
    save_season_data,
    _save_series_record,
    _save_season_record,
    _save_episode_record,
    _cleanup_tv_library,
)
from lan_streamer.db.library_movie import (  # noqa: F401
    load_movie_library,
    save_movie_library,
    save_movie_data,
    _apply_movie_fields,
    _cleanup_movie_library,
)

logger = logging.getLogger(__name__)


def _cleanup_orphaned_media_files(
    session: Any, root_directories: List[str], stats: Dict[str, int]
) -> None:
    """Removes MediaFile records under root_directories whose physical file no longer exists on disk."""
    from pathlib import Path
    from sqlalchemy import select
    from lan_streamer.db.models import MediaFile

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
        except Exception as exception_instance:
            logger.warning(
                f"Cleanup: Unable to resolve path '{mf.path}': {exception_instance}"
            )

        if in_library:
            try:
                if not Path(mf.path).exists():
                    logger.info(
                        f"Cleanup: Removing missing MediaFile record at '{mf.path}'"
                    )
                    session.delete(mf)
                    removed_count += 1
            except Exception as exception_instance:
                logger.warning(
                    f"Cleanup: Unable to check existence of '{mf.path}': {exception_instance}"
                )
    stats["media_files_removed"] = stats.get("media_files_removed", 0) + removed_count


def cleanup_library(library_name: str, root_directories: List[str]) -> Dict[str, int]:
    """
    Removes series/seasons/episodes or movies that are no longer present on the file system.
    Returns a dictionary with counts of deleted items.
    """

    start_time = time.time()
    stats = {
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
            # Clean up stale ScannedDirectory entries for removed series
            from sqlalchemy import delete as sa_delete
            from lan_streamer.db.models import (
                ScannedDirectory,
                Series as SeriesModel,
                Movie as MovieModel,
            )

            for root in root_directories:
                root_path = Path(root)
                if root_path.is_dir():
                    for series_path in root_path.iterdir():
                        if series_path.is_dir():
                            series_name = series_path.name
                            if library_type == "movie":
                                db_entry = session.scalars(
                                    select(MovieModel)
                                    .where(MovieModel.library_name == library_name)
                                    .where(MovieModel.name == series_name)
                                ).first()
                                series_exists = db_entry is not None
                            else:
                                db_entry = session.scalars(
                                    select(SeriesModel)
                                    .where(SeriesModel.library_name == library_name)
                                    .where(SeriesModel.name == series_name)
                                ).first()
                                series_exists = db_entry is not None
                            if not series_exists:
                                session.execute(
                                    sa_delete(ScannedDirectory).where(
                                        ScannedDirectory.path
                                        == str(series_path.absolute())
                                    )
                                )
            _cleanup_orphaned_media_files(session, root_directories, stats)

        duration = time.time() - start_time
        if library_type == "movie":
            logger.info(
                f"Cleanup for movie library '{library_name}' completed in {duration:.3f}s: "
                f"{stats['movies']} movies removed. "
                f"Removed {stats['media_files_removed']} missing MediaFile records."
            )
        else:
            logger.info(
                f"Cleanup for tv library '{library_name}' completed in {duration:.3f}s: "
                f"{stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes removed. "
                f"Removed {stats['media_files_removed']} missing MediaFile records."
            )
    except Exception:
        logger.exception(f"Error during library cleanup for '{library_name}'")
        raise

    return stats


__all__ = [
    "get_session",
    "load_library",
    "save_library",
    "save_season_data",
    "load_movie_library",
    "save_movie_library",
    "save_movie_data",
    "cleanup_library",
    "get_directory_mtime",
    "save_directory_mtime",
]
