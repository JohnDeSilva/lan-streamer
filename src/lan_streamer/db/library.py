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
from typing import Any

from sqlalchemy import select

from lan_streamer.db.library_movie import (  # noqa: F401
    _apply_movie_fields,
    _cleanup_movie_library,
    load_movie_library,
    save_movie_data,
    save_movie_library,
)
from lan_streamer.db.library_shared import (  # noqa: F401
    _sync_media_files,
    _update_field_safely,
    get_directory_mtime,
    get_session,
    save_directory_mtime,
)
from lan_streamer.db.library_tv import (  # noqa: F401
    _cleanup_tv_library,
    _save_episode_record,
    _save_season_record,
    _save_series_record,
    load_library,
    save_library,
    save_season_data,
)
from lan_streamer.system.config import config

logger = logging.getLogger(__name__)


def _cleanup_orphaned_media_files(
    session: Any, root_directories: list[str], stats: dict[str, int]
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
        except (OSError, ValueError) as exception_instance:
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
            except OSError as exception_instance:
                logger.warning(
                    f"Cleanup: Unable to check existence of '{mf.path}': {exception_instance}"
                )
    stats["media_files_removed"] = stats.get("media_files_removed", 0) + removed_count


def cleanup_library(library_name: str, root_directories: list[str]) -> dict[str, int]:
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
            # Clean up stale ScannedDirectory entries for paths that no longer
            # exist on the filesystem (e.g. series moved between roots, or
            # directories that were deleted after a scan).
            from lan_streamer.db.models import ScannedDirectory

            for root in root_directories:
                root_path = Path(root).resolve()
                root_prefix = str(root_path) + "/"
                stale_entries = session.scalars(
                    select(ScannedDirectory).where(
                        ScannedDirectory.path.startswith(root_prefix)
                    )
                ).all()
                for stale_entry in stale_entries:
                    if not Path(stale_entry.path).exists():
                        session.delete(stale_entry)
                        logger.debug(
                            "Cleanup: Removing stale ScannedDirectory entry for '%s'",
                            stale_entry.path,
                        )

            # Clean up ScannedDirectory entries for directories on disk that
            # no longer have a corresponding DB record.
            from sqlalchemy import delete as sa_delete

            from lan_streamer.db.models import (
                Movie as MovieModel,
            )
            from lan_streamer.db.models import (
                ScannedDirectory,
            )
            from lan_streamer.db.models import (
                Series as SeriesModel,
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


def reassign_library_items_by_root_path(
    old_library_name: str, new_library_name: str, root_path: str
) -> dict[str, int]:
    """Reassigns Series and Movie records whose files reside under root_path
    from old_library_name to new_library_name.

    Returns:
        A dictionary with counts of reassigned series and movies.
    """
    from sqlalchemy.orm import selectinload

    from lan_streamer.db.models import (
        Episode as EpisodeModel,
    )
    from lan_streamer.db.models import (
        Movie as MovieModel,
    )
    from lan_streamer.db.models import (
        Season as SeasonModel,
    )
    from lan_streamer.db.models import (
        Series as SeriesModel,
    )

    resolved_root_path = Path(root_path).resolve()
    reassigned_counts = {"series": 0, "movies": 0}

    with get_session() as session:
        # 1. TV Series
        series_records = session.scalars(
            select(SeriesModel)
            .where(SeriesModel.library_name == old_library_name)
            .options(
                selectinload(SeriesModel.seasons)
                .selectinload(SeasonModel.episodes)
                .selectinload(EpisodeModel.media_files)
            )
        ).all()

        for series_item in series_records:
            matches_root = False
            for season in series_item.seasons:
                for episode in season.episodes:
                    for media_file in episode.media_files:
                        if media_file.path:
                            try:
                                if (
                                    Path(media_file.path)
                                    .resolve()
                                    .is_relative_to(resolved_root_path)
                                ):
                                    matches_root = True
                                    break
                            except ValueError, OSError:
                                pass
                    if matches_root:
                        break
                if matches_root:
                    break

            if matches_root:
                series_item.library_name = new_library_name
                reassigned_counts["series"] += 1
                logger.info(
                    "Reassigned series '%s' from library '%s' to '%s'",
                    series_item.name,
                    old_library_name,
                    new_library_name,
                )

        # 2. Movies
        movie_records = session.scalars(
            select(MovieModel)
            .where(MovieModel.library_name == old_library_name)
            .options(selectinload(MovieModel.media_files))
        ).all()

        for movie_item in movie_records:
            matches_root = False
            if movie_item.default_path:
                try:
                    if (
                        Path(movie_item.default_path)
                        .resolve()
                        .is_relative_to(resolved_root_path)
                    ):
                        matches_root = True
                except ValueError, OSError:
                    pass
            if not matches_root:
                for media_file in movie_item.media_files:
                    if media_file.path:
                        try:
                            if (
                                Path(media_file.path)
                                .resolve()
                                .is_relative_to(resolved_root_path)
                            ):
                                matches_root = True
                                break
                        except ValueError, OSError:
                            pass

            if matches_root:
                movie_item.library_name = new_library_name
                reassigned_counts["movies"] += 1
                logger.info(
                    "Reassigned movie '%s' from library '%s' to '%s'",
                    movie_item.name,
                    old_library_name,
                    new_library_name,
                )

        session.commit()

    # Rebuild smart row cache if items were reassigned
    if reassigned_counts["series"] > 0 or reassigned_counts["movies"] > 0:
        try:
            from lan_streamer.db.smart_row_cache import rebuild_all_cache

            rebuild_all_cache()
        except Exception:
            logger.exception(
                "Could not rebuild smart row cache during library reassign"
            )

    return reassigned_counts


__all__ = [
    "cleanup_library",
    "get_directory_mtime",
    "get_session",
    "load_library",
    "load_movie_library",
    "reassign_library_items_by_root_path",
    "save_directory_mtime",
    "save_library",
    "save_movie_data",
    "save_movie_library",
    "save_season_data",
]
