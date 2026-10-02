"""
Movie library persistence functions — load, save, and cleanup of Movie records.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from lan_streamer.db.library_shared import (
    _sync_media_files,
    _update_field_safely,
    get_session,
)
from lan_streamer.db.models import MediaFile, Movie, MovieLibrary

logger = logging.getLogger(__name__)


def _apply_movie_fields(movie: Movie, movie_data: dict[str, Any]) -> bool:
    """
    Applies all creative metadata fields from *movie_data* onto the *movie* ORM object.
    Only overrides existing values when the incoming value is non-falsy.
    Returns True if any fields were actually changed.
    """
    changed = False

    for attr, key in [
        ("jellyfin_id", "jellyfin_id"),
        ("tmdb_identifier", "tmdb_identifier"),
        ("poster_path", "poster_path"),
        ("overview", "overview"),
        ("tmdb_name", "tmdb_name"),
        ("rating", "rating"),
        ("genre", "genre"),
    ]:
        val = movie_data.get(key)
        if val and getattr(movie, attr) != val:
            setattr(movie, attr, val)
            changed = True

    if "locked_metadata" in movie_data:
        val = bool(movie_data["locked_metadata"])
        if movie.locked_metadata != val:
            movie.locked_metadata = val
            changed = True

    for attr, key, _default_val in [
        ("date_added", "date_added", 0),
        ("runtime", "runtime", 0),
        ("year", "year", 0),
    ]:
        val = movie_data.get(key)
        if val:
            if key == "date_added":
                val = int(val)
            if getattr(movie, attr) != val:
                setattr(movie, attr, val)
                changed = True

    if "myanimelist_anime_id" in movie_data:
        val = movie_data["myanimelist_anime_id"]
        if movie.myanimelist_anime_id != val:
            movie.myanimelist_anime_id = val
            changed = True

    for attr, key in [
        ("video_codec", "video_codec"),
        ("resolution", "resolution"),
        ("bit_rate", "bit_rate"),
    ]:
        val = movie_data.get(key)
        if val is not None:
            old_val = getattr(movie, attr)
            new_val = _update_field_safely(old_val, val)
            if old_val != new_val:
                setattr(movie, attr, new_val)
                changed = True

    incoming_audio = movie_data.get("audio_tracks")
    if incoming_audio is not None and len(incoming_audio) > 0:
        val = json.dumps(incoming_audio)
        if movie.audio_tracks != val:
            movie.audio_tracks = val
            changed = True

    incoming_subs = movie_data.get("subtitle_tracks")
    if incoming_subs is not None and len(incoming_subs) > 0:
        val = json.dumps(incoming_subs)
        if movie.subtitle_tracks != val:
            movie.subtitle_tracks = val
            changed = True

    new_path = movie_data.get("default_path") or movie_data.get("path")
    if new_path:
        old_val = movie.default_path
        new_val = _update_field_safely(old_val, new_path)
        if old_val != new_val:
            movie.default_path = new_val
            changed = True

    watched = bool(movie_data.get("watched"))
    if watched and not movie.watched:
        movie.watched = True
        changed = True
    if (
        movie_data.get("last_played_position") is not None
        and movie.last_played_position != movie_data["last_played_position"]
    ):
        movie.last_played_position = movie_data["last_played_position"]
        changed = True
    if (
        movie_data.get("last_played_at") is not None
        and movie.last_played_at != movie_data["last_played_at"]
    ):
        movie.last_played_at = movie_data["last_played_at"]
        changed = True

    return changed


def _cleanup_movie_library(
    session: Session,
    library_name: str,
    stats: dict[str, int],
) -> None:
    """Removes Movie records whose file path no longer exists on disk."""
    movie_list = session.scalars(
        select(Movie)
        .join(Movie.libraries, isouter=True)
        .where(
            (Movie.library_name == library_name)
            | (MovieLibrary.library_name == library_name)
        )
        .distinct()
        .options(
            selectinload(Movie.libraries),
            selectinload(Movie.media_files),
        )
    ).all()
    for movie in movie_list:
        path = movie.default_path or (
            movie.media_files[0].path if movie.media_files else None
        )
        if path and not Path(path).exists():
            other_libraries = [
                movie_library
                for movie_library in movie.libraries
                if movie_library.library_name != library_name
            ]
            if other_libraries:
                logger.info(
                    f"Cleanup: Movie '{movie.name}' at '{path}' missing from '{library_name}', "
                    f"but still associated with {len(other_libraries)} other libraries."
                )
                for movie_library in list(movie.libraries):
                    if movie_library.library_name == library_name:
                        session.delete(movie_library)
                if movie.library_name == library_name:
                    movie.library_name = other_libraries[0].library_name
                continue

            logger.info(f"Cleanup: Removing missing movie '{movie.name}' at '{path}'")
            session.delete(movie)
            stats["movies"] += 1
            stats["movies_removed"] = stats.get("movies_removed", 0) + 1


def load_movie_library(library_name: str | list[str]) -> dict[str, Any]:
    """Loads the movie library from the database and constructs a dictionary structure.

    Supports either a single library name or a list of library names.
    """
    from lan_streamer.db.orm_serialization import _build_movie_dict

    start_time = time.time()
    library_data = {}
    stats = {"movies": 0}

    if library_name is None:
        return {}
    names = (
        [library_name]
        if isinstance(library_name, str)
        else [single_name for single_name in library_name if single_name is not None]
    )
    if not names:
        return {}

    try:
        with get_session() as session:
            movie_list = session.scalars(
                select(Movie)
                .join(Movie.libraries, isouter=True)
                .where(
                    (Movie.library_name.in_(names))
                    | (MovieLibrary.library_name.in_(names))
                )
                .distinct()
                .options(
                    selectinload(Movie.libraries),
                    selectinload(Movie.media_files),
                    selectinload(Movie.playback_state),
                )
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


def _load_existing_movies_for_save(
    session: Session, library: dict[str, Any]
) -> tuple[dict[str, Movie], dict[str, Movie], dict[str, Movie]]:
    """Loads existing movies by name, path, and TMDB identifier for save."""
    incoming_movie_names = [name for name in library if name]
    incoming_tmdb_identifiers = [
        str(
            movie_dict.get("tmdb_identifier")
            or movie_dict.get("tmdb_id")
            or movie_dict.get("metadata", {}).get("tmdb_identifier")
            or movie_dict.get("metadata", {}).get("tmdb_id")
        )
        for movie_dict in library.values()
        if (
            movie_dict.get("tmdb_identifier")
            or movie_dict.get("tmdb_id")
            or movie_dict.get("metadata", {}).get("tmdb_identifier")
            or movie_dict.get("metadata", {}).get("tmdb_id")
        )
    ]
    filter_predicates = []
    if incoming_movie_names:
        filter_predicates.append(Movie.name.in_(incoming_movie_names))
    if incoming_tmdb_identifiers:
        filter_predicates.append(Movie.tmdb_identifier.in_(incoming_tmdb_identifiers))

    existing_movies_by_name: dict[str, Movie] = {}
    if filter_predicates:
        existing_movies_by_name = {
            movie_obj.name: movie_obj
            for movie_obj in session.scalars(
                select(Movie)
                .where(or_(*filter_predicates))
                .options(
                    selectinload(Movie.libraries),
                    selectinload(Movie.media_files),
                    selectinload(Movie.playback_state),
                )
            ).all()
            if movie_obj.name is not None
        }
    incoming_paths = [data.get("path") for data in library.values() if data.get("path")]
    existing_movies_by_path: dict[str, Movie] = {}
    if incoming_paths:
        existing_movies_by_path = {
            movie_obj.path: movie_obj
            for movie_obj in session.scalars(
                select(Movie)
                .join(Movie.media_files)
                .where(MediaFile.path.in_(incoming_paths))
                .options(
                    selectinload(Movie.libraries),
                    selectinload(Movie.media_files),
                    selectinload(Movie.playback_state),
                )
            ).all()
            if movie_obj.path is not None
        }

    existing_movies_by_tmdb = {}
    for movie_obj in list(existing_movies_by_name.values()):
        if movie_obj.tmdb_identifier:
            existing_movies_by_tmdb[str(movie_obj.tmdb_identifier)] = movie_obj

    return existing_movies_by_name, existing_movies_by_path, existing_movies_by_tmdb


def save_movie_library(library_name: str, library: dict[str, Any]) -> dict[str, Any]:
    """
    Updates the database for the given movie library name using SQLAlchemy ORM.
    """

    start_time = time.time()
    stats: dict[str, Any] = {
        "movies": 0,
        "deleted": 0,
        "issues": [],
        "movies_added": 0,
        "movies_removed": 0,
        "movies_scanned": 0,
        "movies_updated": 0,
    }

    try:
        from lan_streamer.db.models import ScannedDirectory

        with get_session() as session:
            (
                existing_movies_by_name,
                existing_movies_by_path,
                existing_movies_by_tmdb,
            ) = _load_existing_movies_for_save(session, library)

            touched_movie_names = set()

            for movie_name, movie_data in library.items():
                touched_movie_names.add(movie_name)
                path = movie_data.get("path")
                is_new_file = False
                if path and path not in existing_movies_by_path:
                    is_new_file = True

                tmdb_identifier = movie_data.get("tmdb_identifier") or movie_data.get(
                    "tmdb_id"
                )
                movie = None
                if path and path in existing_movies_by_path:
                    movie = existing_movies_by_path[path]
                elif (
                    tmdb_identifier and str(tmdb_identifier) in existing_movies_by_tmdb
                ):
                    movie = existing_movies_by_tmdb[str(tmdb_identifier)]
                elif movie_name in existing_movies_by_name:
                    movie = existing_movies_by_name[movie_name]

                is_new = False
                if not movie:
                    movie = Movie(library_name=library_name, name=movie_name)
                    session.add(movie)
                    stats["movies_added"] = stats.get("movies_added", 0) + 1
                    is_new = True
                else:
                    if movie.name != movie_name:
                        stale_movie = existing_movies_by_name.get(movie_name)
                        if stale_movie and stale_movie is not movie:
                            logger.info(
                                f"Removing stale movie record '{movie_name}' to avoid name collision."
                            )
                            session.delete(stale_movie)
                            session.flush()
                            stats["movies_removed"] = stats.get("movies_removed", 0) + 1
                            del existing_movies_by_name[movie_name]
                    movie.name = movie_name

                # Ensure MovieLibrary junction link exists
                has_library_link = any(
                    movie_library.library_name == library_name
                    for movie_library in movie.libraries
                )
                if not has_library_link:
                    new_movie_library = MovieLibrary(
                        movie_id=movie.id, library_name=library_name
                    )
                    session.add(new_movie_library)
                    movie.libraries.append(new_movie_library)

                stats["movies"] += 1

                if path:
                    existing_movies_by_path[path] = movie
                existing_movies_by_name[movie_name] = movie

                versions = movie_data.get("versions")
                if not versions and movie_data.get("path"):
                    versions = [
                        {
                            "path": movie_data.get("path"),
                            "video_codec": movie_data.get("video_codec"),
                            "resolution": movie_data.get("resolution"),
                            "bit_rate": movie_data.get("bit_rate"),
                            "audio_tracks": movie_data.get("audio_tracks"),
                            "subtitle_tracks": movie_data.get("subtitle_tracks"),
                        }
                    ]
                if versions is not None:
                    versions = list(versions)
                    from lan_streamer.system.config import config

                    configured_paths = config.libraries.get(library_name, {}).get(
                        "paths", []
                    )
                    resolved_roots = [
                        str(Path(path_item).resolve()) for path_item in configured_paths
                    ]
                    existing_paths_in_versions = {
                        version_item.get("path")
                        for version_item in versions
                        if version_item.get("path")
                    }
                    for existing_media_file in movie.media_files:
                        if (
                            existing_media_file.path
                            and existing_media_file.path
                            not in existing_paths_in_versions
                        ):
                            is_under_current_library = False
                            if resolved_roots:
                                try:
                                    resolved_media_file = str(
                                        Path(existing_media_file.path).resolve()
                                    )
                                    is_under_current_library = any(
                                        resolved_media_file.startswith(root_path)
                                        for root_path in resolved_roots
                                    )
                                except ValueError, OSError:
                                    is_under_current_library = False
                            if not is_under_current_library:
                                versions.append(
                                    {
                                        "path": existing_media_file.path,
                                        "video_codec": existing_media_file.video_codec,
                                        "resolution": existing_media_file.resolution,
                                        "bit_rate": existing_media_file.bit_rate,
                                        "audio_tracks": existing_media_file.audio_tracks,
                                        "subtitle_tracks": existing_media_file.subtitle_tracks,
                                        "runtime": existing_media_file.runtime,
                                    }
                                )
                _sync_media_files(session, movie, versions)

                if is_new_file:
                    movie.watched = False
                changed = _apply_movie_fields(movie, movie_data)

                if not is_new and changed:
                    stats["movies_updated"] = stats.get("movies_updated", 0) + 1
                stats["movies_scanned"] = stats.get("movies_scanned", 0) + 1

            # Persist movie directory mtimes
            for _, movie_data in library.items():
                movie_dir = movie_data.get("movie_directory_path")
                movie_mtime = movie_data.get("last_scanned_mtime")
                if movie_dir and movie_mtime is not None:
                    record = session.scalars(
                        select(ScannedDirectory).where(
                            ScannedDirectory.path == movie_dir
                        )
                    ).first()
                    if record:
                        record.last_scanned_mtime = movie_mtime
                    else:
                        session.add(
                            ScannedDirectory(
                                path=movie_dir, last_scanned_mtime=movie_mtime
                            )
                        )

            session.flush()

    except Exception as e:
        logger.exception(f"Error saving movie library '{library_name}' to database")
        stats["issues"].append(
            {
                "type": "Database Write Failure",
                "item": f"Movie Library '{library_name}'",
                "error": str(e),
            }
        )
        raise

    duration = time.time() - start_time
    logger.info(
        f"Movie library '{library_name}' updated in {duration:.3f}s: "
        f"{stats['movies']} movies saved. "
    )
    return stats


def save_movie_data(
    library_name: str, movie_name: str, movie_data: dict[str, Any]
) -> dict[str, Any]:
    """
    Saves or updates a single movie in the database.
    """
    stats: dict[str, Any] = {
        "movies": 0,
        "deleted": 0,
        "issues": [],
        "movies_added": 0,
        "movies_removed": 0,
        "movies_scanned": 0,
        "movies_updated": 0,
    }
    try:
        with get_session() as session:
            existing_movie = session.scalars(
                select(Movie)
                .where(Movie.name == movie_name)
                .options(
                    selectinload(Movie.libraries),
                    selectinload(Movie.media_files),
                    selectinload(Movie.playback_state),
                )
            ).first()

            path = movie_data.get("path")
            movie = None
            if path:
                movie = session.scalars(
                    select(Movie)
                    .join(Movie.media_files)
                    .where(MediaFile.path == path)
                    .options(
                        selectinload(Movie.libraries),
                        selectinload(Movie.media_files),
                        selectinload(Movie.playback_state),
                    )
                ).first()

            if not movie:
                tmdb_identifier = movie_data.get("tmdb_identifier") or movie_data.get(
                    "tmdb_id"
                )
                if tmdb_identifier:
                    movie = session.scalars(
                        select(Movie)
                        .where(Movie.tmdb_identifier == tmdb_identifier)
                        .options(
                            selectinload(Movie.libraries),
                            selectinload(Movie.media_files),
                            selectinload(Movie.playback_state),
                        )
                    ).first()

            if not movie:
                movie = existing_movie

            is_new = False
            if not movie:
                movie = Movie(library_name=library_name, name=movie_name)
                session.add(movie)
                stats["movies_added"] = stats.get("movies_added", 0) + 1
                is_new = True
            else:
                if movie.name != movie_name:
                    stale_movie = existing_movie
                    if stale_movie and stale_movie is not movie:
                        logger.info(
                            f"Removing stale movie record '{movie_name}' to avoid name collision."
                        )
                        session.delete(stale_movie)
                        session.flush()
                        stats["movies_removed"] = stats.get("movies_removed", 0) + 1

                movie.name = movie_name

            # Ensure MovieLibrary junction link exists
            has_library_link = any(
                movie_library.library_name == library_name
                for movie_library in movie.libraries
            )
            if not has_library_link:
                new_movie_library = MovieLibrary(
                    movie_id=movie.id, library_name=library_name
                )
                session.add(new_movie_library)
                movie.libraries.append(new_movie_library)

            stats["movies"] += 1

            versions = movie_data.get("versions")
            if not versions and movie_data.get("path"):
                versions = [
                    {
                        "path": movie_data.get("path"),
                        "video_codec": movie_data.get("video_codec"),
                        "resolution": movie_data.get("resolution"),
                        "bit_rate": movie_data.get("bit_rate"),
                        "audio_tracks": movie_data.get("audio_tracks"),
                        "subtitle_tracks": movie_data.get("subtitle_tracks"),
                    }
                ]
            if versions is not None:
                versions = list(versions)
                from lan_streamer.system.config import config

                configured_paths = config.libraries.get(library_name, {}).get(
                    "paths", []
                )
                resolved_roots = [
                    str(Path(path_item).resolve()) for path_item in configured_paths
                ]
                existing_paths_in_versions = {
                    version_entry.get("path")
                    for version_entry in versions
                    if version_entry.get("path")
                }
                for existing_media_file in movie.media_files:
                    if (
                        existing_media_file.path
                        and existing_media_file.path not in existing_paths_in_versions
                    ):
                        is_under_current_library = False
                        if resolved_roots:
                            try:
                                resolved_media_file = str(
                                    Path(existing_media_file.path).resolve()
                                )
                                is_under_current_library = any(
                                    resolved_media_file.startswith(root_path)
                                    for root_path in resolved_roots
                                )
                            except ValueError, OSError:
                                is_under_current_library = False
                        if not is_under_current_library:
                            versions.append(
                                {
                                    "path": existing_media_file.path,
                                    "video_codec": existing_media_file.video_codec,
                                    "resolution": existing_media_file.resolution,
                                    "bit_rate": existing_media_file.bit_rate,
                                    "audio_tracks": existing_media_file.audio_tracks,
                                    "subtitle_tracks": existing_media_file.subtitle_tracks,
                                    "runtime": existing_media_file.runtime,
                                }
                            )
                _sync_media_files(session, movie, versions)
            changed = _apply_movie_fields(movie, movie_data)

            # Save movie directory mtime to scanned_directories table
            dir_path = movie_data.get("movie_directory_path")
            mtime = movie_data.get("last_scanned_mtime")
            if dir_path and mtime is not None:
                from lan_streamer.db.models import ScannedDirectory

                record = session.scalars(
                    select(ScannedDirectory).where(ScannedDirectory.path == dir_path)
                ).first()
                if record:
                    record.last_scanned_mtime = mtime
                else:
                    record = ScannedDirectory(path=dir_path, last_scanned_mtime=mtime)
                    session.add(record)

            session.flush()
            stats["movie_id"] = movie.id
            if not is_new and changed:
                stats["movies_updated"] = stats.get("movies_updated", 0) + 1
            stats["movies_scanned"] = stats.get("movies_scanned", 0) + 1
            logger.info(
                f"Successfully saved movie '{movie_name}' to database. Stats: {stats}"
            )
            return stats
    except Exception:
        logger.exception(f"Failed to save movie '{movie_name}' to database")
        raise
