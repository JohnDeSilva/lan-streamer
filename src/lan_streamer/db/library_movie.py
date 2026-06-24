"""
Movie library persistence functions — load, save, and cleanup of Movie records.
"""

import logging
import time
import json
from pathlib import Path
from typing import Dict, Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lan_streamer.db.models import Movie, MediaFile
from lan_streamer.db.library_shared import (
    get_session,
    _update_field_safely,
    _sync_media_files,
)

logger = logging.getLogger(__name__)


def _apply_movie_fields(movie: Movie, movie_data: Dict[str, Any]) -> bool:
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

    for attr, key, default_val in [
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

    return changed


def _cleanup_movie_library(
    session: Session,
    library_name: str,
    stats: Dict[str, int],
) -> None:
    """Removes Movie records whose file path no longer exists on disk."""
    movie_list = session.scalars(
        select(Movie)
        .where(Movie.library_name == library_name)
        .options(selectinload(Movie.media_files))
    ).all()
    for movie in movie_list:
        path = movie.default_path or (
            movie.media_files[0].path if movie.media_files else None
        )
        if path and not Path(path).exists():
            logger.info(f"Cleanup: Removing missing movie '{movie.name}' at '{path}'")
            session.delete(movie)
            stats["movies"] += 1
            stats["movies_removed"] = stats.get("movies_removed", 0) + 1


def load_movie_library(library_name: str) -> Dict[str, Any]:
    """
    Loads the movie library from the database and constructs a dictionary structure.
    """
    from lan_streamer.db.orm_serialization import _build_movie_dict

    start_time = time.time()
    library_data = {}
    stats = {"movies": 0}

    try:
        with get_session() as session:
            movie_list = session.scalars(
                select(Movie)
                .where(Movie.library_name == library_name)
                .options(
                    selectinload(Movie.media_files), selectinload(Movie.playback_state)
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


def save_movie_library(library_name: str, library: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates the database for the given movie library name using SQLAlchemy ORM.
    """

    start_time = time.time()
    stats: Dict[str, Any] = {
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
            existing_movies_by_name = {
                m.name: m
                for m in session.scalars(
                    select(Movie)
                    .where(Movie.library_name == library_name)
                    .options(
                        selectinload(Movie.media_files),
                        selectinload(Movie.playback_state),
                    )
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
                        select(Movie)
                        .join(Movie.media_files)
                        .where(MediaFile.path.in_(incoming_paths))
                        .options(
                            selectinload(Movie.media_files),
                            selectinload(Movie.playback_state),
                        )
                    ).all()
                    if m.path is not None
                }

            existing_movies_by_tmdb = {}
            for m in list(existing_movies_by_name.values()):
                if m.tmdb_identifier:
                    is_missing = False
                    if m.path:
                        try:
                            if not Path(m.path).exists():
                                is_missing = True
                        except Exception:
                            is_missing = True
                    if is_missing:
                        existing_movies_by_tmdb[m.tmdb_identifier] = m

            touched_movie_names = set()

            for movie_name, movie_data in library.items():
                touched_movie_names.add(movie_name)
                path = movie_data.get("path")
                is_new_file = False
                if path and path not in existing_movies_by_path:
                    is_new_file = True

                movie = None
                if path and path in existing_movies_by_path:
                    movie = existing_movies_by_path[path]
                elif movie_name in existing_movies_by_name:
                    movie = existing_movies_by_name[movie_name]
                else:
                    tmdb_id = movie_data.get("tmdb_identifier")
                    if tmdb_id and tmdb_id in existing_movies_by_tmdb:
                        movie = existing_movies_by_tmdb[tmdb_id]

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
                    movie.library_name = library_name
                    movie.name = movie_name

                stats["movies"] += 1

                if path:
                    existing_movies_by_path[path] = movie
                existing_movies_by_name[movie_name] = movie

                versions = movie_data.get("versions")
                if versions is None and movie_data.get("path"):
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
                _sync_media_files(session, movie, versions)
                if is_new_file:
                    movie.watched = False
                changed = _apply_movie_fields(movie, movie_data)

                if not is_new and changed:
                    stats["movies_updated"] = stats.get("movies_updated", 0) + 1
                stats["movies_scanned"] = stats.get("movies_scanned", 0) + 1

    except Exception as e:
        logger.exception(f"Error saving movie library '{library_name}' to database")
        stats["issues"].append(
            {
                "type": "Database Write Failure",
                "item": f"Movie Library '{library_name}'",
                "error": str(e),
            }
        )

    duration = time.time() - start_time
    logger.info(
        f"Movie library '{library_name}' updated in {duration:.3f}s: "
        f"{stats['movies']} movies saved. "
    )
    return stats


def save_movie_data(
    library_name: str, movie_name: str, movie_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Saves or updates a single movie in the database.
    """
    stats: Dict[str, Any] = {
        "series": 0,
        "seasons": 0,
        "episodes": 0,
        "movies": 0,
        "deleted": 0,
        "issues": [],
        "series_added": 0,
        "series_removed": 0,
        "seasons_added": 0,
        "seasons_removed": 0,
        "episodes_added": 0,
        "episodes_removed": 0,
        "movies_added": 0,
        "movies_removed": 0,
        "movies_scanned": 0,
        "movies_updated": 0,
    }
    try:
        with get_session() as session:
            existing_movie = session.scalars(
                select(Movie)
                .where(Movie.library_name == library_name)
                .where(Movie.name == movie_name)
                .options(
                    selectinload(Movie.media_files), selectinload(Movie.playback_state)
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
                        selectinload(Movie.media_files),
                        selectinload(Movie.playback_state),
                    )
                ).first()

            if not movie:
                movie = existing_movie

            if not movie:
                tmdb_id = movie_data.get("tmdb_identifier")
                if tmdb_id:
                    movie = session.scalars(
                        select(Movie)
                        .where(Movie.library_name == library_name)
                        .where(Movie.tmdb_identifier == tmdb_id)
                        .options(
                            selectinload(Movie.media_files),
                            selectinload(Movie.playback_state),
                        )
                    ).first()

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

                movie.library_name = library_name
                movie.name = movie_name

            stats["movies"] += 1

            versions = movie_data.get("versions")
            if versions is None and movie_data.get("path"):
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
            _sync_media_files(session, movie, versions)
            changed = _apply_movie_fields(movie, movie_data)

            session.commit()
            stats["movie_id"] = movie.id
            if not is_new and changed:
                stats["movies_updated"] = stats.get("movies_updated", 0) + 1
            stats["movies_scanned"] = stats.get("movies_scanned", 0) + 1
            logger.info(
                f"Successfully saved movie '{movie_name}' to database. Stats: {stats}"
            )
            return stats
    except Exception as e:
        logger.exception(f"Failed to save movie '{movie_name}' to database: {e}")
        raise e
