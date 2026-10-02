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
        MovieLibrary as MovieLibraryModel,
    )
    from lan_streamer.db.models import (
        Season as SeasonModel,
    )
    from lan_streamer.db.models import (
        Series as SeriesModel,
    )
    from lan_streamer.db.models import (
        SeriesLibrary as SeriesLibraryModel,
    )

    resolved_root_path = Path(root_path).resolve()
    reassigned_counts = {"series": 0, "movies": 0}

    with get_session() as session:
        # 1. TV Series
        series_records = session.scalars(
            select(SeriesModel)
            .where(
                (SeriesModel.library_name == old_library_name)
                | (
                    SeriesModel.id.in_(
                        select(SeriesLibraryModel.series_id).where(
                            SeriesLibraryModel.library_name == old_library_name
                        )
                    )
                )
            )
            .distinct()
            .options(
                selectinload(SeriesModel.libraries),
                selectinload(SeriesModel.seasons)
                .selectinload(SeasonModel.episodes)
                .selectinload(EpisodeModel.media_files),
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
                for series_library_record in list(series_item.libraries):
                    if series_library_record.library_name == old_library_name:
                        session.delete(series_library_record)
                existing_libraries = {
                    record.library_name
                    for record in series_item.libraries
                    if record.library_name != old_library_name
                }
                if new_library_name not in existing_libraries:
                    session.add(
                        SeriesLibraryModel(
                            series_id=series_item.id,
                            library_name=new_library_name,
                        )
                    )
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
            .where(
                (MovieModel.library_name == old_library_name)
                | (
                    MovieModel.id.in_(
                        select(MovieLibraryModel.movie_id).where(
                            MovieLibraryModel.library_name == old_library_name
                        )
                    )
                )
            )
            .distinct()
            .options(
                selectinload(MovieModel.libraries),
                selectinload(MovieModel.media_files),
            )
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
                for movie_library_record in list(movie_item.libraries):
                    if movie_library_record.library_name == old_library_name:
                        session.delete(movie_library_record)
                existing_movie_libraries = {
                    record.library_name
                    for record in movie_item.libraries
                    if record.library_name != old_library_name
                }
                if new_library_name not in existing_movie_libraries:
                    session.add(
                        MovieLibraryModel(
                            movie_id=movie_item.id,
                            library_name=new_library_name,
                        )
                    )
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


def delete_library_records(library_name: str) -> dict[str, int]:
    """Destructively removes all media and junction records associated with a library.

    If a series or movie is associated with other libraries, it is unlinked from
    library_name. If it has no remaining library associations, the series or
    movie record and its related entities are completely deleted from the database.
    Orphaned MediaFile records and smart row caches are cleaned up.

    Returns:
        A dictionary with counts of deleted or unlinked items.
    """
    from sqlalchemy.orm import selectinload

    from lan_streamer.db.models import (
        Episode as EpisodeModel,
    )
    from lan_streamer.db.models import (
        MediaFile as MediaFileModel,
    )
    from lan_streamer.db.models import (
        MetadataFileMapping as MetadataFileMappingModel,
    )
    from lan_streamer.db.models import (
        Movie as MovieModel,
    )
    from lan_streamer.db.models import (
        MovieLibrary as MovieLibraryModel,
    )
    from lan_streamer.db.models import (
        Season as SeasonModel,
    )
    from lan_streamer.db.models import (
        Series as SeriesModel,
    )
    from lan_streamer.db.models import (
        SeriesLibrary as SeriesLibraryModel,
    )

    stats_dictionary: dict[str, int] = {
        "series_deleted": 0,
        "series_unlinked": 0,
        "movies_deleted": 0,
        "movies_unlinked": 0,
        "media_files_removed": 0,
    }

    with get_session() as session:
        # 1. TV Series
        series_records = session.scalars(
            select(SeriesModel)
            .join(SeriesModel.libraries, isouter=True)
            .where(
                (SeriesModel.library_name == library_name)
                | (SeriesLibraryModel.library_name == library_name)
            )
            .distinct()
            .options(
                selectinload(SeriesModel.libraries),
                selectinload(SeriesModel.seasons)
                .selectinload(SeasonModel.episodes)
                .selectinload(EpisodeModel.media_files),
            )
        ).all()

        for series_item in series_records:
            other_libraries = [
                series_library
                for series_library in series_item.libraries
                if series_library.library_name != library_name
            ]
            for series_library in list(series_item.libraries):
                if series_library.library_name == library_name:
                    session.delete(series_library)

            if other_libraries:
                if series_item.library_name == library_name:
                    series_item.library_name = other_libraries[0].library_name
                stats_dictionary["series_unlinked"] += 1
            else:
                session.delete(series_item)
                stats_dictionary["series_deleted"] += 1

        # 2. Movies
        movie_records = session.scalars(
            select(MovieModel)
            .join(MovieModel.libraries, isouter=True)
            .where(
                (MovieModel.library_name == library_name)
                | (MovieLibraryModel.library_name == library_name)
            )
            .distinct()
            .options(
                selectinload(MovieModel.libraries),
                selectinload(MovieModel.media_files),
            )
        ).all()

        for movie_item in movie_records:
            other_libraries = [
                movie_library
                for movie_library in movie_item.libraries
                if movie_library.library_name != library_name
            ]
            for movie_library in list(movie_item.libraries):
                if movie_library.library_name == library_name:
                    session.delete(movie_library)

            if other_libraries:
                if movie_item.library_name == library_name:
                    movie_item.library_name = other_libraries[0].library_name
                stats_dictionary["movies_unlinked"] += 1
            else:
                session.delete(movie_item)
                stats_dictionary["movies_deleted"] += 1

        session.flush()

        # 3. Clean up orphaned MediaFile records
        subquery = select(MetadataFileMappingModel.media_file_id).distinct()
        orphaned_media_files = session.scalars(
            select(MediaFileModel).where(~MediaFileModel.id.in_(subquery))
        ).all()
        for media_file_record in orphaned_media_files:
            session.delete(media_file_record)
            stats_dictionary["media_files_removed"] += 1

        session.commit()

    try:
        from lan_streamer.db.smart_row_cache import rebuild_all_cache

        rebuild_all_cache()
    except Exception:
        logger.exception(
            "Could not rebuild smart row cache during library deletion of '%s'",
            library_name,
        )

    logger.info(
        "delete_library_records for '%s' completed: %s",
        library_name,
        stats_dictionary,
    )
    return stats_dictionary


def rename_library_records(
    old_library_name: str, new_library_name: str
) -> dict[str, int]:
    """Updates library name across Series, Movie, SeriesLibrary, and MovieLibrary records.

    Returns:
        A dictionary with counts of updated items.
    """
    from sqlalchemy.orm import selectinload

    from lan_streamer.db.models import (
        Movie as MovieModel,
    )
    from lan_streamer.db.models import (
        MovieLibrary as MovieLibraryModel,
    )
    from lan_streamer.db.models import (
        Series as SeriesModel,
    )
    from lan_streamer.db.models import (
        SeriesLibrary as SeriesLibraryModel,
    )

    stats_dictionary: dict[str, int] = {"series_updated": 0, "movies_updated": 0}

    with get_session() as session:
        # Update Series records
        series_records = session.scalars(
            select(SeriesModel)
            .join(SeriesModel.libraries, isouter=True)
            .where(
                (SeriesModel.library_name == old_library_name)
                | (SeriesLibraryModel.library_name == old_library_name)
            )
            .distinct()
            .options(selectinload(SeriesModel.libraries))
        ).all()

        for series_item in series_records:
            if series_item.library_name == old_library_name:
                series_item.library_name = new_library_name
            for series_library in series_item.libraries:
                if series_library.library_name == old_library_name:
                    series_library.library_name = new_library_name
            stats_dictionary["series_updated"] += 1

        # Update Movie records
        movie_records = session.scalars(
            select(MovieModel)
            .join(MovieModel.libraries, isouter=True)
            .where(
                (MovieModel.library_name == old_library_name)
                | (MovieLibraryModel.library_name == old_library_name)
            )
            .distinct()
            .options(selectinload(MovieModel.libraries))
        ).all()

        for movie_item in movie_records:
            if movie_item.library_name == old_library_name:
                movie_item.library_name = new_library_name
            for movie_library in movie_item.libraries:
                if movie_library.library_name == old_library_name:
                    movie_library.library_name = new_library_name
            stats_dictionary["movies_updated"] += 1

        session.commit()

    try:
        from lan_streamer.db.smart_row_cache import rebuild_all_cache

        rebuild_all_cache()
    except Exception:
        logger.exception(
            "Could not rebuild smart row cache during library rename from '%s' to '%s'",
            old_library_name,
            new_library_name,
        )

    logger.info(
        "rename_library_records from '%s' to '%s' completed: %s",
        old_library_name,
        new_library_name,
        stats_dictionary,
    )
    return stats_dictionary


__all__ = [
    "cleanup_library",
    "delete_library_records",
    "get_directory_mtime",
    "get_session",
    "load_library",
    "load_movie_library",
    "reassign_library_items_by_root_path",
    "rename_library_records",
    "save_directory_mtime",
    "save_library",
    "save_movie_data",
    "save_movie_library",
    "save_season_data",
]
