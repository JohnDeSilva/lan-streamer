"""Repository: convert scanner dictionary output into agent ORM rows.

The scanner produces plain dictionaries (the ``LibraryDict`` shape: keys are
series/movie folder names, values carry ``metadata``, ``seasons``,
``episodes``, ``versions``, ``path``, …). These functions upsert that shape
into the agent database, preserving every ``versions`` entry as a separate
:class:`MediaFile` row (AGENTS.md section 7 invariant), and convert rows back
into the same dictionary shape for the scanner's ``existing_library`` input.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, joinedload, selectinload

from scan_agent.db.models import (
    Episode,
    Library,
    MediaFile,
    Movie,
    ScanJob,
    Season,
    Series,
    Subtitle,
    WatchEvent,
)
from scan_agent.db.serializers import (
    episode_to_dict,
    movie_to_dict,
    scan_job_to_dict,
    series_to_dict,
    subtitle_to_dict,
    watch_event_to_dict,
)

logger = logging.getLogger(__name__)

_SEASON_NUMBER_RE = re.compile(r"(\d+)")


def _derive_season_number(season_name: str) -> int:
    """Derive a numeric season index from a season folder name.

    ``"Specials"`` maps to 0; otherwise the first integer found in the name
    is used, falling back to 1.
    """
    if season_name.lower() == "specials":
        return 0
    match = _SEASON_NUMBER_RE.search(season_name)
    return int(match.group(1)) if match else 1


def _season_name_from_number(season_number: int) -> str:
    """Return the conventional season name for a numeric index."""
    return "Specials" if season_number == 0 else f"Season {season_number}"


def _version_to_media_file(version: dict[str, Any]) -> dict[str, Any]:
    """Map a scanner version dict onto :class:`MediaFile` column values."""
    return {
        "path": version.get("path"),
        "size_bytes": version.get("size_bytes"),
        "duration_seconds": version.get("runtime"),
        "codec": version.get("video_codec"),
        "resolution": version.get("resolution"),
        "container": version.get("video_type"),
    }


def _media_file_to_version(media_file: MediaFile) -> dict[str, Any]:
    """Map a :class:`MediaFile` row back onto a scanner version dict."""
    return {
        "path": media_file.path,
        "size_bytes": media_file.size_bytes,
        "video_type": media_file.container,
        "video_codec": media_file.codec,
        "resolution": media_file.resolution,
        "bit_rate": None,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "runtime": media_file.duration_seconds,
    }


def _sync_media_files(
    connection: Session,
    media_type: str,
    media_id: int,
    versions: list[dict[str, Any]] | None,
) -> int:
    """Replace or update the :class:`MediaFile` rows for one episode/movie.

    Handles deduplication and path re-assignment so that the unique
    constraint on ``media_files.path`` is never violated when files are moved
    or shared across items.
    """
    incoming_versions_by_path: dict[str, dict[str, Any]] = {}
    for version in versions or []:
        version_path = version.get("path")
        if version_path and version_path not in incoming_versions_by_path:
            incoming_versions_by_path[version_path] = version

    # Remove any existing media files for this media item whose path is no longer present
    existing_for_item = connection.scalars(
        select(MediaFile).where(
            MediaFile.media_type == media_type, MediaFile.media_id == media_id
        )
    ).all()
    for existing_item_file in existing_for_item:
        if existing_item_file.path not in incoming_versions_by_path:
            connection.delete(existing_item_file)

    written_count = 0
    for version_path, version in incoming_versions_by_path.items():
        values = _version_to_media_file(version)

        # Check if a MediaFile with this path already exists in session.new or DB
        existing_media_file: MediaFile | None = None
        for session_object in connection.new:
            if (
                isinstance(session_object, MediaFile)
                and session_object.path == version_path
            ):
                existing_media_file = session_object
                break

        if existing_media_file is None:
            existing_media_file = connection.scalars(
                select(MediaFile).where(MediaFile.path == version_path)
            ).first()

        if existing_media_file is not None:
            existing_media_file.media_type = media_type
            existing_media_file.media_id = media_id
            existing_media_file.size_bytes = values["size_bytes"]
            existing_media_file.duration_seconds = values["duration_seconds"]
            existing_media_file.codec = values["codec"]
            existing_media_file.resolution = values["resolution"]
            existing_media_file.container = values["container"]
            existing_media_file.active = True
        else:
            connection.add(
                MediaFile(
                    media_type=media_type,
                    media_id=media_id,
                    path=version_path,
                    size_bytes=values["size_bytes"],
                    duration_seconds=values["duration_seconds"],
                    codec=values["codec"],
                    resolution=values["resolution"],
                    container=values["container"],
                    active=True,
                )
            )
        written_count += 1
    return written_count


def _apply_episode_fields(
    connection: Session,
    episode: Episode,
    episode_data: dict[str, Any],
) -> int:
    """Copy scanner episode fields onto an :class:`Episode` row."""
    episode_path = episode_data.get("path")
    episode.episode_number = episode_data.get("episode_number") or episode_data.get(
        "tmdb_number"
    )
    episode.tmdb_number = episode_data.get("tmdb_number")
    target_name = episode_data.get("tmdb_name") or episode_data.get("name")
    if target_name:
        episode.name = target_name
    if episode_data.get("overview") is not None:
        episode.overview = episode_data.get("overview")

    if episode_path:
        episode.path = episode_path
        episode.is_missing = not Path(episode_path).exists()
    elif not episode.path:
        episode.path = None
        episode.is_missing = True
    else:
        episode.is_missing = not Path(episode.path).exists()

    runtime = episode_data.get("runtime") or episode_data.get("file_runtime")
    if runtime:
        episode.runtime_seconds = runtime
    if episode_data.get("air_date"):
        episode.air_date = episode_data.get("air_date")

    if "watched" in episode_data:
        episode.watched = bool(episode_data.get("watched"))
    if "last_played_at" in episode_data:
        episode.last_played_at = episode_data.get("last_played_at")
    if "last_played_position" in episode_data:
        episode.resume_position_seconds = episode_data.get("last_played_position")

    versions = episode_data.get("versions")
    if versions is None:
        if not episode.media_files and episode_path:
            versions = [{"path": episode_path}]
        else:
            # Multiple video files may map to this episode. Without an explicit
            # versions list, preserve the existing media files rather than
            # collapsing the episode back to a single synthesized version.
            return len(episode.media_files)
    return _sync_media_files(connection, "episode", episode.id, versions)


def _upsert_episodes(
    connection: Session,
    season: Season,
    episodes_data: list[dict[str, Any]],
) -> tuple[int, int]:
    """Upsert all episodes of a season, removing stale rows.

    Returns ``(episode_count, media_file_count)``.
    """
    existing_by_id: dict[int, Episode] = {
        episode.id: episode for episode in season.episodes
    }
    existing_by_path: dict[str, Episode] = {}
    existing_by_number: dict[int, Episode] = {}
    used_numbers: set[int] = set()

    for episode in season.episodes:
        if episode.path:
            existing_by_path[episode.path] = episode
        for media_file in episode.media_files:
            if media_file.path:
                existing_by_path[media_file.path] = episode
        if episode.episode_number is not None and episode.episode_number > 0:
            existing_by_number[episode.episode_number] = episode
            used_numbers.add(episode.episode_number)

    processed_episode_ids: set[int] = set()
    media_file_count = 0

    for episode_data in episodes_data:
        episode_number = episode_data.get("episode_number") or episode_data.get(
            "tmdb_number"
        )
        path = episode_data.get("path")

        candidate: Episode | None = None
        if path and path in existing_by_path:
            candidate = existing_by_path[path]
        elif (
            episode_number is not None
            and episode_number > 0
            and episode_number in existing_by_number
        ):
            candidate = existing_by_number[episode_number]

        if candidate is None:
            if (
                episode_number is None
                or episode_number <= 0
                or episode_number in used_numbers
            ):
                next_num = 1
                while next_num in used_numbers:
                    next_num += 1
                episode_number = next_num

            candidate = Episode(season_id=season.id, episode_number=episode_number)
            connection.add(candidate)
            connection.flush()
            season.episodes.append(candidate)
            existing_by_id[candidate.id] = candidate
        elif (
            episode_number is not None
            and episode_number > 0
            and (candidate.episode_number is None or candidate.episode_number <= 0)
            and (
                episode_number not in used_numbers
                or candidate.episode_number == episode_number
            )
        ):
            candidate.episode_number = episode_number

        if candidate.episode_number is not None and candidate.episode_number > 0:
            used_numbers.add(candidate.episode_number)
            existing_by_number[candidate.episode_number] = candidate
        if path:
            existing_by_path[path] = candidate

        processed_episode_ids.add(candidate.id)
        media_file_count += _apply_episode_fields(connection, candidate, episode_data)

    stale_episodes = [
        episode
        for episode_identifier, episode in existing_by_id.items()
        if episode_identifier not in processed_episode_ids
    ]
    for stale_episode in stale_episodes:
        connection.execute(
            delete(MediaFile).where(
                MediaFile.media_type == "episode",
                MediaFile.media_id == stale_episode.id,
            )
        )
        connection.delete(stale_episode)
        logger.info(
            "Removing stale episode %s from season %s",
            stale_episode.episode_number,
            season.season_number,
        )
    return len(episodes_data), media_file_count


def _merge_season_episodes(
    existing_episodes: list[dict[str, Any]],
    incoming_episodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge episodes from multiple representations of the same season number."""
    merged_episodes: list[dict[str, Any]] = []
    episodes_by_number: dict[int, dict[str, Any]] = {}
    episodes_by_path: dict[str, dict[str, Any]] = {}

    def _add_or_merge(episode_item: dict[str, Any]) -> None:
        item_copy = dict(episode_item)
        number = item_copy.get("episode_number") or item_copy.get("tmdb_number")
        path = item_copy.get("path")
        target: dict[str, Any] | None = None

        if number is not None and number > 0 and number in episodes_by_number:
            target = episodes_by_number[number]
        elif path and path in episodes_by_path:
            target = episodes_by_path[path]

        if target is not None:
            for key, val in item_copy.items():
                if val is not None and (
                    target.get(key) is None
                    or key in ("watched", "last_played_at", "last_played_position")
                ):
                    target[key] = val
            existing_versions = target.get("versions") or []
            incoming_versions = item_copy.get("versions") or []
            existing_vpaths = {
                v.get("path") for v in existing_versions if v.get("path")
            }
            for v in incoming_versions:
                if v.get("path") and v["path"] not in existing_vpaths:
                    existing_versions.append(v)
                    existing_vpaths.add(v["path"])
            if existing_versions:
                target["versions"] = existing_versions
        else:
            merged_episodes.append(item_copy)
            if number is not None and number > 0:
                episodes_by_number[number] = item_copy
            if path:
                episodes_by_path[path] = item_copy
            for version in item_copy.get("versions") or []:
                if version.get("path"):
                    episodes_by_path[version["path"]] = item_copy

    for single_episode in existing_episodes:
        _add_or_merge(single_episode)
    for single_episode in incoming_episodes:
        _add_or_merge(single_episode)

    return merged_episodes


def _upsert_seasons(
    connection: Session,
    series: Series,
    seasons_data: dict[str, Any],
) -> tuple[int, int, int]:
    """Upsert all seasons of a series, removing stale rows.

    Returns ``(season_count, episode_count, media_file_count)``.
    """
    grouped_seasons: dict[int, dict[str, Any]] = {}
    for season_name, season_data in seasons_data.items():
        season_number = _derive_season_number(season_name)
        if season_number not in grouped_seasons:
            grouped_seasons[season_number] = {
                "name": season_name,
                "metadata": dict(season_data.get("metadata", {})),
                "episodes": list(season_data.get("episodes", [])),
            }
        else:
            existing_group = grouped_seasons[season_number]
            has_files = any(
                episode_item.get("path")
                for episode_item in season_data.get("episodes", [])
            )
            if has_files:
                existing_group["name"] = season_name
            existing_group["episodes"] = _merge_season_episodes(
                existing_group["episodes"], season_data.get("episodes", [])
            )
            existing_group["metadata"].update(season_data.get("metadata", {}))

    existing_seasons = {season.season_number: season for season in series.seasons}
    season_rows: dict[int, Season] = dict(existing_seasons)
    processed_numbers: set[int] = set()
    episode_count = 0
    media_file_count = 0
    for season_number, grouped_season in grouped_seasons.items():
        season = season_rows.get(season_number)
        if season is None:
            season = Season(series_id=series.id, season_number=season_number)
            connection.add(season)
            connection.flush()
            series.seasons.append(season)
            season_rows[season_number] = season
        processed_numbers.add(season_number)
        season_metadata = grouped_season.get("metadata", {})
        season.name = grouped_season["name"]
        season.overview = season_metadata.get("overview")
        season.poster_path = season_metadata.get("poster_path")
        season.tmdb_identifier = season_metadata.get("tmdb_identifier")
        season.air_date = season_metadata.get("air_date")
        season_episode_count, season_media_file_count = _upsert_episodes(
            connection, season, grouped_season.get("episodes", [])
        )
        season.episode_count = season_episode_count
        season.watched_episode_count = sum(
            1 for episode in season.episodes if episode.watched
        )
        episode_count += season_episode_count
        media_file_count += season_media_file_count
    stale_seasons = [
        season
        for season_number, season in existing_seasons.items()
        if season_number not in processed_numbers
    ]
    for stale_season in stale_seasons:
        connection.delete(stale_season)
        logger.info(
            "Removing stale season %s from series %s",
            stale_season.season_number,
            series.folder_name,
        )
    return len(seasons_data), episode_count, media_file_count


def _apply_series_fields(series: Series, series_data: dict[str, Any]) -> None:
    """Copy scanner series fields onto a :class:`Series` row."""
    metadata = series_data.get("metadata", {})
    series.name = metadata.get("name") or series_data.get("name") or series.folder_name
    series.overview = metadata.get("overview")
    series.poster_path = metadata.get("poster_path")
    series.backdrop_path = metadata.get("backdrop_path")
    series.tmdb_identifier = metadata.get("tmdb_identifier") or series_data.get(
        "tmdb_identifier"
    )
    series.year = metadata.get("year")
    series.status = metadata.get("status")
    series.air_date_first = metadata.get("air_date_first") or metadata.get(
        "first_air_date"
    )
    series.air_date_last = metadata.get("air_date_last")
    series.locked_metadata = bool(metadata.get("locked_metadata"))
    series.path = series_data.get("path")
    series.last_modified = metadata.get("last_scanned_mtime")
    series.date_added = metadata.get("date_added")


def _apply_movie_fields(
    connection: Session, movie: Movie, movie_data: dict[str, Any]
) -> int:
    """Copy scanner movie fields onto a :class:`Movie` row.

    Returns the number of media files written.
    """
    movie.name = movie_data.get("name") or movie.folder_name
    movie.overview = movie_data.get("overview")
    movie.poster_path = movie_data.get("poster_path")
    movie.backdrop_path = movie_data.get("backdrop_path")
    movie.tmdb_identifier = movie_data.get("tmdb_identifier")
    movie.year = movie_data.get("year")
    movie.runtime_seconds = movie_data.get("runtime") or movie_data.get("file_runtime")
    movie_path = movie_data.get("path")
    movie.path = movie_path
    movie.locked_metadata = bool(movie_data.get("locked_metadata"))
    movie.last_modified = movie_data.get("last_scanned_mtime")
    movie.date_added = movie_data.get("date_added")
    movie.watched = bool(movie_data.get("watched"))
    movie.last_played_at = movie_data.get("last_played_at")
    movie.resume_position_seconds = movie_data.get("last_played_position")
    versions = movie_data.get("versions")
    if versions is None:
        if not movie.media_files and movie_path:
            versions = [{"path": movie_path}]
        else:
            # Preserve existing media files when the scan did not provide an
            # explicit versions list (multiple files can map to one movie).
            return len(movie.media_files)
    return _sync_media_files(connection, "movie", movie.id, versions)


def get_or_create_library(
    connection: Session,
    name: str,
    media_type: str,
    root_path: str,
) -> Library:
    """Return the :class:`Library` row for *name*, creating it when absent."""
    library = connection.scalars(select(Library).where(Library.name == name)).first()
    if library is None:
        library = Library(name=name, media_type=media_type, root_path=root_path)
        connection.add(library)
        connection.flush()
        logger.info("Created library '%s' (%s) at %s", name, media_type, root_path)
    else:
        library.media_type = media_type
        library.root_path = root_path
    return library


def get_library(connection: Session, library_identifier: str | int) -> Library | None:
    """Return a :class:`Library` by numeric id or by name."""
    if isinstance(library_identifier, int) or str(library_identifier).isdigit():
        library = connection.get(Library, int(library_identifier))
        if library is not None:
            return library
    return connection.scalars(
        select(Library).where(Library.name == str(library_identifier))
    ).first()


def upsert_library(connection: Session, library: dict[str, Any]) -> dict[str, Any]:
    """Upsert a full library scan result.

    Args:
        connection: SQLAlchemy session (the repository's unit of work).
        library: dict with ``name``, ``media_type``, ``root_path`` and
            ``items`` keys; ``items`` is the scanner ``LibraryDict`` mapping
            series/movie folder names to their data dicts.

    Returns:
        Stats dict with ``series``, ``seasons``, ``episodes``, ``movies`` and
        ``media_files`` counts.
    """
    library_name = str(library["name"])
    media_type = str(library["media_type"])
    root_path = str(library["root_path"])
    items = library.get("items", {})
    library_row = get_or_create_library(connection, library_name, media_type, root_path)
    stats: dict[str, int] = {
        "series": 0,
        "seasons": 0,
        "episodes": 0,
        "movies": 0,
        "media_files": 0,
    }
    if media_type == "movie":
        stats["movies"], stats["media_files"] = _upsert_movies(
            connection, library_row, items
        )
    else:
        stats["series"], stats["seasons"], stats["episodes"], stats["media_files"] = (
            _upsert_series(connection, library_row, items)
        )
    connection.flush()
    logger.info("Upserted library '%s': %s", library_name, json.dumps(stats))
    return stats


def _upsert_series(
    connection: Session,
    library: Library,
    items: dict[str, Any],
) -> tuple[int, int, int, int]:
    """Upsert all series in *items* for *library*; returns aggregate counts."""
    existing_series = {series.folder_name: series for series in library.series}
    processed_folders: set[str] = set()
    series_count = 0
    season_count = 0
    episode_count = 0
    media_file_count = 0
    for folder_name, series_data in items.items():
        try:
            with connection.begin_nested():
                series = existing_series.get(folder_name)
                if series is None:
                    series = Series(library_id=library.id, folder_name=folder_name)
                    connection.add(series)
                    connection.flush()
                processed_folders.add(folder_name)
                _apply_series_fields(series, series_data)
                season_count_delta, episode_count_delta, media_file_count_delta = (
                    _upsert_seasons(connection, series, series_data.get("seasons", {}))
                )
                series.watched_count = sum(
                    1
                    for season in series.seasons
                    for episode in season.episodes
                    if episode.watched
                )
                series_count += 1
                season_count += season_count_delta
                episode_count += episode_count_delta
                media_file_count += media_file_count_delta
        except Exception:
            processed_folders.add(folder_name)
            logger.exception(
                "Failed to upsert series '%s' in library '%s'",
                folder_name,
                library.name,
            )
    stale_series = [
        series
        for folder_name, series in existing_series.items()
        if folder_name not in processed_folders
    ]
    for stale_series_row in stale_series:
        connection.delete(stale_series_row)
        logger.info("Removing stale series '%s'", stale_series_row.folder_name)
    return series_count, season_count, episode_count, media_file_count


def _upsert_movies(
    connection: Session,
    library: Library,
    items: dict[str, Any],
) -> tuple[int, int]:
    """Upsert all movies in *items* for *library*; returns aggregate counts."""
    existing_movies = {movie.folder_name: movie for movie in library.movies}
    processed_folders: set[str] = set()
    movie_count = 0
    media_file_count = 0
    for folder_name, movie_data in items.items():
        try:
            with connection.begin_nested():
                movie = existing_movies.get(folder_name)
                if movie is None:
                    movie = Movie(library_id=library.id, folder_name=folder_name)
                    connection.add(movie)
                    connection.flush()
                processed_folders.add(folder_name)
                media_file_count += _apply_movie_fields(connection, movie, movie_data)
                movie_count += 1
        except Exception:
            processed_folders.add(folder_name)
            logger.exception(
                "Failed to upsert movie '%s' in library '%s'",
                folder_name,
                library.name,
            )
    stale_movies = [
        movie
        for folder_name, movie in existing_movies.items()
        if folder_name not in processed_folders
    ]
    for stale_movie in stale_movies:
        connection.delete(stale_movie)
        logger.info("Removing stale movie '%s'", stale_movie.folder_name)
    return movie_count, media_file_count


def upsert_series_scan(
    connection: Session,
    library_identifier: str | int,
    series_name: str,
    series_dict: dict[str, Any],
) -> dict[str, int]:
    """Upsert a single series (or movie) into its library.

    Used for incremental writes and single-item refreshes.
    """
    library = get_library(connection, library_identifier)
    if library is None:
        raise ValueError(f"Unknown library identifier: {library_identifier}")
    if library.media_type == "movie":
        movie_count, media_file_count = _upsert_movies(
            connection, library, {series_name: series_dict}
        )
        return {"movies": movie_count, "media_files": media_file_count}
    series_count, season_count, episode_count, media_file_count = _upsert_series(
        connection, library, {series_name: series_dict}
    )
    return {
        "series": series_count,
        "seasons": season_count,
        "episodes": episode_count,
        "media_files": media_file_count,
    }


def list_series(
    connection: Session,
    library_identifier: str | int | None = None,
    library_type: str | None = None,
    query: str | None = None,
    sort: str | None = None,
) -> list[dict[str, Any]]:
    """List series as plain dicts, optionally filtered and sorted.

    *sort* is one of ``"name"`` (default), ``"date_added"`` or ``"year"``.
    """
    statement = select(Series).options(
        selectinload(Series.seasons).selectinload(Season.episodes)
    )
    if library_identifier is not None:
        library = get_library(connection, library_identifier)
        if library is None:
            return []
        if library_type is not None and library.media_type != library_type:
            return []
        statement = statement.where(Series.library_id == library.id)
    elif library_type is not None:
        statement = statement.join(Series.library).where(
            Library.media_type == library_type
        )
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(Series.name.ilike(pattern), Series.folder_name.ilike(pattern))
        )
    sort_column = {
        "name": Series.name,
        "date_added": Series.date_added,
        "year": Series.year,
    }.get(sort or "name", Series.name)
    statement = statement.order_by(sort_column)
    return [series_to_dict(series) for series in connection.scalars(statement).all()]


def get_series(connection: Session, series_identifier: int) -> dict[str, Any] | None:
    """Return a single series (with nested seasons/episodes) as a dict."""
    series = connection.scalars(
        select(Series)
        .where(Series.id == series_identifier)
        .options(
            selectinload(Series.seasons)
            .selectinload(Season.episodes)
            .selectinload(Episode.media_files)
        )
    ).first()
    return series_to_dict(series) if series is not None else None


def list_episodes(
    connection: Session,
    library_type: str | None = None,
    library_identifier: str | int | None = None,
    query: str | None = None,
    watched: bool | None = None,
    sort: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List episodes, optionally filtered by library type, library ID, query, and watched state.

    Includes parent series, season, and library metadata.
    """
    statement = (
        select(Episode)
        .join(Episode.season)
        .join(Season.series)
        .join(Series.library)
        .options(
            joinedload(Episode.season)
            .joinedload(Season.series)
            .joinedload(Series.library),
            selectinload(Episode.media_files),
        )
    )
    if library_type is not None:
        statement = statement.where(Library.media_type == library_type)
    if library_identifier is not None:
        library = get_library(connection, library_identifier)
        if library is None:
            return []
        statement = statement.where(Library.id == library.id)
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(
                Episode.name.ilike(pattern),
                Episode.path.ilike(pattern),
                Series.name.ilike(pattern),
                Series.folder_name.ilike(pattern),
            )
        )
    if watched is not None:
        statement = statement.where(Episode.watched == watched)

    if sort == "name_desc":
        statement = statement.order_by(
            Series.name.desc(),
            Season.season_number.desc(),
            Episode.episode_number.desc(),
        )
    elif sort in ("air_date_desc", "date_added_desc"):
        statement = statement.order_by(
            Episode.air_date.desc().nulls_last(),
            Series.name.asc(),
            Episode.episode_number.asc(),
        )
    else:
        statement = statement.order_by(
            Series.name.asc(),
            Season.season_number.asc(),
            Episode.episode_number.asc(),
        )

    statement = statement.limit(limit).offset(offset)
    episodes = connection.scalars(statement).all()

    results: list[dict[str, Any]] = []
    for episode in episodes:
        serialized_episode = episode_to_dict(episode)
        season = episode.season
        if season is not None:
            serialized_episode["season_number"] = season.season_number
            series = season.series
            if series is not None:
                serialized_episode["series_id"] = series.id
                serialized_episode["series_name"] = series.name or series.folder_name
                serialized_episode["poster_path"] = (
                    season.poster_path or series.poster_path
                )
                library = series.library
                if library is not None:
                    serialized_episode["library_id"] = library.id
                    serialized_episode["library_name"] = library.name
                    serialized_episode["library_type"] = library.media_type
        results.append(serialized_episode)
    return results


def list_movies(
    connection: Session,
    library_identifier: str | int | None = None,
    query: str | None = None,
    sort: str | None = None,
) -> list[dict[str, Any]]:
    """List movies as plain dicts, optionally filtered and sorted."""
    statement = select(Movie)
    if library_identifier is not None:
        library = get_library(connection, library_identifier)
        if library is None:
            return []
        statement = statement.where(Movie.library_id == library.id)
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(Movie.name.ilike(pattern), Movie.folder_name.ilike(pattern))
        )
    sort_column = {
        "name": Movie.name,
        "date_added": Movie.date_added,
        "year": Movie.year,
    }.get(sort or "name", Movie.name)
    statement = statement.order_by(sort_column)
    movies = connection.scalars(statement).all()
    return [movie_to_dict(movie) for movie in movies]


def get_movie(connection: Session, movie_identifier: int) -> dict[str, Any] | None:
    """Return a single movie (with media files) as a dict."""
    movie = connection.scalars(
        select(Movie).where(Movie.id == movie_identifier)
    ).first()
    return movie_to_dict(movie) if movie is not None else None


def list_scan_jobs(
    connection: Session,
    library_identifier: str | int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List scan jobs newest-first as plain dicts."""
    statement = select(ScanJob).order_by(ScanJob.started_at.desc())
    if library_identifier is not None:
        library = get_library(connection, library_identifier)
        if library is None:
            return []
        statement = statement.where(ScanJob.library_id == library.id)
    if limit is not None:
        statement = statement.limit(limit)
    return [scan_job_to_dict(job) for job in connection.scalars(statement).all()]


def record_missing_files(
    connection: Session,
    library_identifier: str | int,
    library_dict: dict[str, Any],
) -> int:
    """Mark episodes/movies whose files are gone as missing.

    Walks the scanner output dict; for every episode/movie whose path is
    ``None`` or no longer exists on disk, sets ``is_missing`` (episodes) or
    clears the path (movies) and deactivates stale :class:`MediaFile` rows.

    Returns the number of items marked missing.
    """
    library = get_library(connection, library_identifier)
    if library is None:
        raise ValueError(f"Unknown library identifier: {library_identifier}")
    missing_count = 0
    if library.media_type == "movie":
        for folder_name, movie_data in library_dict.items():
            movie = connection.scalars(
                select(Movie).where(
                    Movie.library_id == library.id, Movie.folder_name == folder_name
                )
            ).first()
            if movie is None:
                continue
            movie_path = movie_data.get("path")
            if movie_path is None or not Path(movie_path).exists():
                movie.path = None
                _deactivate_missing_media_files(connection, "movie", movie.id)
                missing_count += 1
        return missing_count
    for folder_name, series_data in library_dict.items():
        series = connection.scalars(
            select(Series).where(
                Series.library_id == library.id, Series.folder_name == folder_name
            )
        ).first()
        if series is None:
            continue
        for season_data in series_data.get("seasons", {}).values():
            for episode_data in season_data.get("episodes", []):
                episode_number = episode_data.get("episode_number") or episode_data.get(
                    "tmdb_number"
                )
                if episode_number is None:
                    continue
                episode = connection.scalars(
                    select(Episode)
                    .join(Season)
                    .where(
                        Season.series_id == series.id,
                        Episode.episode_number == episode_number,
                    )
                ).first()
                if episode is None:
                    continue
                episode_path = episode_data.get("path")
                if episode_path is None or not Path(episode_path).exists():
                    episode.is_missing = True
                    episode.path = None
                    _deactivate_missing_media_files(connection, "episode", episode.id)
                    missing_count += 1
    return missing_count


def _deactivate_missing_media_files(
    connection: Session, media_type: str, media_id: int
) -> None:
    """Deactivate :class:`MediaFile` rows whose files no longer exist on disk."""
    media_files = connection.scalars(
        select(MediaFile).where(
            MediaFile.media_type == media_type, MediaFile.media_id == media_id
        )
    ).all()
    for media_file in media_files:
        if media_file.path and not Path(media_file.path).exists():
            media_file.active = False
            logger.info("Deactivated missing media file '%s'", media_file.path)


def load_library_dict(
    connection: Session,
    library_identifier: str | int,
) -> dict[str, Any]:
    """Load a library as the scanner's ``existing_library`` dictionary shape.

    Keys are series/movie folder names; values mirror the desktop
    ``orm_serialization`` dicts so the reused scanner can match existing
    records by path and preserve watched/version data across scans.
    """
    library = get_library(connection, library_identifier)
    if library is None:
        return {}
    if library.media_type == "movie":
        movies = connection.scalars(
            select(Movie).where(Movie.library_id == library.id)
        ).all()
        return {movie.folder_name: _movie_to_scanner_dict(movie) for movie in movies}
    series_rows = connection.scalars(
        select(Series)
        .where(Series.library_id == library.id)
        .options(
            selectinload(Series.seasons)
            .selectinload(Season.episodes)
            .selectinload(Episode.media_files)
        )
    ).all()
    return {
        series.folder_name: _series_to_scanner_dict(series) for series in series_rows
    }


def _series_to_scanner_dict(series: Series) -> dict[str, Any]:
    """Convert a :class:`Series` row into the scanner's series dict shape."""
    seasons: dict[str, Any] = {}
    for season in series.seasons:
        season_name = season.name or _season_name_from_number(season.season_number)
        seasons[season_name] = {
            "metadata": {
                "jellyfin_id": None,
                "tmdb_identifier": season.tmdb_identifier,
                "poster_path": season.poster_path,
                "myanimelist_id": None,
                "season_directory_path": "",
                "last_scanned_mtime": None,
            },
            "episodes": [
                _episode_to_scanner_dict(episode) for episode in season.episodes
            ],
        }
    return {
        "name": series.name or series.folder_name,
        "path": series.path,
        "metadata": {
            "jellyfin_id": None,
            "tmdb_identifier": series.tmdb_identifier,
            "poster_path": series.poster_path,
            "backdrop_path": series.backdrop_path,
            "overview": series.overview,
            "tmdb_name": series.name,
            "locked_metadata": series.locked_metadata,
            "first_air_date": series.air_date_first,
            "tmdb_episode_group_id": None,
            "status": series.status,
            "year": series.year,
            "air_date_first": series.air_date_first,
            "air_date_last": series.air_date_last,
            "genre": None,
            "network": None,
            "rating": None,
            "runtime": None,
            "myanimelist_id": None,
            "date_added": series.date_added,
            "last_scanned_mtime": series.last_modified,
        },
        "seasons": seasons,
        "tmdb_identifier": series.tmdb_identifier,
        "jellyfin_id": None,
        "myanimelist_id": None,
    }


def _episode_to_scanner_dict(episode: Episode) -> dict[str, Any]:
    """Convert an :class:`Episode` row into the scanner's episode dict shape."""
    versions = [
        _media_file_to_version(media_file) for media_file in episode.media_files
    ]
    primary_path = episode.path or (versions[0]["path"] if versions else None)
    return {
        "name": episode.name,
        "overview": episode.overview,
        "path": primary_path,
        "episode_number": episode.episode_number,
        "jellyfin_id": None,
        "tmdb_episode_identifier": None,
        "tmdb_name": episode.name,
        "tmdb_number": episode.tmdb_number,
        "myanimelist_anime_id": None,
        "myanimelist_episode_number": None,
        "watched": episode.watched,
        "date_added": 0,
        "air_date": episode.air_date or "",
        "runtime": episode.runtime_seconds,
        "file_runtime": episode.runtime_seconds,
        "last_played_at": episode.last_played_at,
        "last_played_position": episode.resume_position_seconds,
        "video_codec": versions[0].get("video_codec") if versions else None,
        "resolution": versions[0].get("resolution") if versions else None,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "bit_rate": None,
        "versions": versions,
        "default_path": episode.path or "",
    }


def _overlay_watch_fields(
    target_item: dict[str, Any], live_item: dict[str, Any]
) -> None:
    """Copy live watch/playback fields onto a scanned item's fields."""
    if "watched" in live_item:
        target_item["watched"] = bool(live_item.get("watched", False))
    if "last_played_at" in live_item:
        target_item["last_played_at"] = live_item.get("last_played_at")
    if "last_played_position" in live_item:
        target_item["last_played_position"] = live_item.get("last_played_position")


def _find_live_episode(
    scanned_episode: dict[str, Any], live_episodes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Locate the live DB episode matching a scanned episode.

    Matching prefers the primary file path, then falls back to the episode
    number (covering TMDB-only placeholders whose file is missing).
    """
    scanned_path = scanned_episode.get("path")
    for live_episode in live_episodes:
        if scanned_path and live_episode.get("path") == scanned_path:
            return live_episode
    scanned_number = scanned_episode.get("episode_number")
    if scanned_number is not None:
        for live_episode in live_episodes:
            if live_episode.get("episode_number") == scanned_number:
                return live_episode
    return None


def preserve_live_watch_state(
    connection: Session,
    library: Library,
    scan_result: dict[str, Any],
) -> None:
    """Overlay live watch/playback state onto a freshly scanned library.

    A scan can run for a long time; watched/playback fields may change between
    the baseline load and the upsert that follows.  This reloads the current
    database state and copies the volatile fields onto the scan result so they
    are never clobbered by (possibly stale) scan output.
    """
    live_items = load_library_dict(connection, library.id)
    for folder_name, item_data in scan_result.items():
        if not isinstance(item_data, dict):
            continue
        live_item = live_items.get(folder_name)
        if not isinstance(live_item, dict):
            continue
        if "seasons" in live_item:
            live_seasons = live_item.get("seasons", {})
            for season_name, season_data in item_data.get("seasons", {}).items():
                if not isinstance(season_data, dict):
                    continue
                live_season = live_seasons.get(season_name)
                if not isinstance(live_season, dict):
                    continue
                live_episodes = live_season.get("episodes", [])
                for scanned_episode in season_data.get("episodes", []):
                    if not isinstance(scanned_episode, dict):
                        continue
                    live_episode = _find_live_episode(scanned_episode, live_episodes)
                    if live_episode is not None:
                        _overlay_watch_fields(scanned_episode, live_episode)
        else:
            _overlay_watch_fields(item_data, live_item)


def _movie_to_scanner_dict(movie: Movie) -> dict[str, Any]:
    """Convert a :class:`Movie` row into the scanner's movie dict shape."""
    versions = [_media_file_to_version(media_file) for media_file in movie.media_files]
    return {
        "name": movie.name or movie.folder_name,
        "path": movie.path or (versions[0]["path"] if versions else None),
        "jellyfin_id": None,
        "tmdb_identifier": movie.tmdb_identifier,
        "poster_path": movie.poster_path,
        "overview": movie.overview,
        "tmdb_name": movie.name,
        "locked_metadata": movie.locked_metadata,
        "date_added": movie.date_added or 0,
        "myanimelist_anime_id": None,
        "runtime": movie.runtime_seconds,
        "file_runtime": movie.runtime_seconds,
        "rating": None,
        "genre": None,
        "year": movie.year,
        "watched": movie.watched,
        "last_played_position": movie.resume_position_seconds,
        "last_played_at": movie.last_played_at,
        "video_codec": versions[0].get("video_codec") if versions else None,
        "resolution": versions[0].get("resolution") if versions else None,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "bit_rate": None,
        "versions": versions,
        "default_path": movie.path or "",
    }


def count_library_items(connection: Session) -> dict[str, int]:
    """Return aggregate item counts per library for dashboard endpoints."""
    series_count = connection.scalar(select(func.count(Series.id))) or 0
    movie_count = connection.scalar(select(func.count(Movie.id))) or 0
    episode_count = connection.scalar(select(func.count(Episode.id))) or 0
    return {
        "series": int(series_count),
        "movies": int(movie_count),
        "episodes": int(episode_count),
    }


# ----------------------------------------------------------------------
# Watch events + subtitle records
# ----------------------------------------------------------------------


def count_items_per_library(connection: Session) -> dict[str, dict[str, int]]:
    """Return series/movie/episode counts grouped by library name."""
    series_rows = connection.execute(
        select(Library.name, func.count(Series.id))
        .outerjoin(Series, Series.library_id == Library.id)
        .group_by(Library.id)
    )
    movie_rows = connection.execute(
        select(Library.name, func.count(Movie.id))
        .outerjoin(Movie, Movie.library_id == Library.id)
        .group_by(Library.id)
    )
    episode_rows = connection.execute(
        select(Library.name, func.count(Episode.id))
        .select_from(Library)
        .outerjoin(Series, Series.library_id == Library.id)
        .outerjoin(Season, Season.series_id == Series.id)
        .outerjoin(Episode, Episode.season_id == Season.id)
        .group_by(Library.id)
    )
    series_counts = {name: int(count) for name, count in series_rows}
    movie_counts = {name: int(count) for name, count in movie_rows}
    episode_counts = {name: int(count) for name, count in episode_rows}
    library_names = set(series_counts) | set(movie_counts) | set(episode_counts)
    return {
        name: {
            "series": int(series_counts.get(name, 0)),
            "movies": int(movie_counts.get(name, 0)),
            "episodes": int(episode_counts.get(name, 0)),
        }
        for name in sorted(library_names)
    }


def record_watch_event(
    connection: Session,
    media_type: str,
    media_identifier: int,
    event: str,
    position_seconds: float | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    """Persist a playback watch event and update the watched state.

    A ``complete`` event marks the episode/movie watched. ``play`` and
    ``stop`` update the resume position and last-played timestamp. Parent
    season/series watched counters are kept consistent.
    """
    timestamp = time.time()
    watch_event = WatchEvent(
        media_type=media_type,
        media_id=media_identifier,
        event=event,
        position_seconds=position_seconds,
        client_id=client_id,
        timestamp=timestamp,
    )
    connection.add(watch_event)

    if media_type == "episode":
        episode = connection.get(Episode, media_identifier)
        if episode is not None:
            if event == "complete":
                episode.watched = True
            episode.last_played_at = timestamp
            if position_seconds is not None:
                episode.resume_position_seconds = position_seconds
            _recount_episode_watched(connection, episode)
    elif media_type == "movie":
        movie = connection.get(Movie, media_identifier)
        if movie is not None:
            if event == "complete":
                movie.watched = True
            movie.last_played_at = timestamp
            if position_seconds is not None:
                movie.resume_position_seconds = position_seconds

    connection.flush()
    logger.info(
        "Recorded watch event media_type=%s media_id=%s event=%s",
        media_type,
        media_identifier,
        event,
    )
    return watch_event_to_dict(watch_event)


def _recount_episode_watched(connection: Session, episode: Episode) -> None:
    """Refresh a season's watched counter and the series watched count."""
    season = episode.season
    if season is None:
        return
    season.watched_episode_count = (
        connection.scalar(
            select(func.count(Episode.id)).where(
                Episode.season_id == season.id, Episode.watched.is_(True)
            )
        )
        or 0
    )
    series_total = (
        connection.scalar(
            select(func.count(Episode.id))
            .join(Season, Season.id == Episode.season_id)
            .where(Season.series_id == season.series_id, Episode.watched.is_(True))
        )
        or 0
    )
    connection.execute(
        update(Series)
        .where(Series.id == season.series_id)
        .values(watched_count=series_total)
    )


def list_watch_events(
    connection: Session,
    media_type: str,
    media_identifier: int,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return recent watch events for a media item, newest first."""
    statement = (
        select(WatchEvent)
        .where(
            WatchEvent.media_type == media_type,
            WatchEvent.media_id == media_identifier,
        )
        .order_by(WatchEvent.timestamp.desc())
        .limit(limit)
    )
    return [watch_event_to_dict(event) for event in connection.scalars(statement).all()]


def get_watch_state(
    connection: Session, media_type: str, media_identifier: int
) -> dict[str, Any]:
    """Return the cumulative watch state for an episode or movie."""
    watched = False
    position_seconds: float | None = None
    last_played_at: float | None = None
    if media_type == "episode":
        episode = connection.get(Episode, media_identifier)
        if episode is not None:
            watched = bool(episode.watched)
            position_seconds = episode.resume_position_seconds
            last_played_at = episode.last_played_at
    elif media_type == "movie":
        movie = connection.get(Movie, media_identifier)
        if movie is not None:
            watched = bool(movie.watched)
            position_seconds = movie.resume_position_seconds
            last_played_at = movie.last_played_at
    recent = list_watch_events(connection, media_type, media_identifier, limit=1)
    event_count = (
        connection.scalar(
            select(func.count(WatchEvent.id)).where(
                WatchEvent.media_type == media_type,
                WatchEvent.media_id == media_identifier,
            )
        )
        or 0
    )
    return {
        "media_type": media_type,
        "media_id": media_identifier,
        "watched": watched,
        "position_seconds": position_seconds,
        "last_played_at": last_played_at,
        "last_event": recent[0]["event"] if recent else None,
        "event_count": int(event_count),
    }


def list_subtitles(
    connection: Session, media_type: str, media_identifier: int
) -> list[dict[str, Any]]:
    """Return stored subtitle entries for an episode or movie."""
    statement = (
        select(Subtitle)
        .where(
            Subtitle.media_type == media_type,
            Subtitle.media_id == media_identifier,
        )
        .order_by(Subtitle.language)
    )
    return [
        subtitle_to_dict(subtitle) for subtitle in connection.scalars(statement).all()
    ]


def add_subtitle(
    connection: Session,
    media_type: str,
    media_identifier: int,
    file_path: str,
    language: str,
    provider: str,
    forced: bool = False,
    default: bool = False,
) -> dict[str, Any]:
    """Persist a subtitle row and log the database write."""
    subtitle = Subtitle(
        media_type=media_type,
        media_id=media_identifier,
        path=file_path,
        language=language,
        provider=provider,
        forced=forced,
        default=default,
    )
    connection.add(subtitle)
    connection.flush()
    logger.info(
        "Added subtitle row media_type=%s media_id=%s path=%s language=%s",
        media_type,
        media_identifier,
        file_path,
        language,
    )
    return subtitle_to_dict(subtitle)


def _sync_series_tmdb_fallback(
    series_record: dict[str, Any],
    tmdb_identifier: str,
    tmdb_client: Any,
) -> dict[str, Any]:
    """Fallback in-memory synchronization matching episode dictionaries against TMDB.

    Used when the series directory cannot be resolved or the scanner pipeline fails.
    """
    import copy

    result_record = copy.deepcopy(series_record)
    seasons_dictionary: dict[str, Any] = result_record.get("seasons", {})

    for season_folder_name, season_data_dictionary in seasons_dictionary.items():
        if season_folder_name.lower() == "specials":
            target_season_number: int = 0
        else:
            parsed_season_match = re.search(r"\d+", season_folder_name)
            target_season_number = (
                int(parsed_season_match.group()) if parsed_season_match else -1
            )

        if target_season_number < 0:
            continue

        try:
            fetched_episodes_list = tmdb_client.get_episodes(
                tmdb_identifier, target_season_number
            )
            if not isinstance(fetched_episodes_list, list):
                fetched_episodes_list = []
        except Exception:
            logger.exception(
                "Failed to fetch TMDB episodes for season %s of series %s",
                target_season_number,
                tmdb_identifier,
            )
            fetched_episodes_list = []

        if not fetched_episodes_list:
            continue

        for episode_item_dictionary in season_data_dictionary.get("episodes", []):
            episode_filename: str = str(
                episode_item_dictionary.get("name")
                or Path(str(episode_item_dictionary.get("path", ""))).name
            )
            matched_tmdb_episode: dict[str, Any] | None = None

            episode_number_match = re.search(r"[Ss]\d+[Ee](\d+)", episode_filename)
            if episode_number_match:
                target_episode_number: int = int(episode_number_match.group(1))
                for candidate_episode in fetched_episodes_list:
                    if candidate_episode.get("episode_number") == target_episode_number:
                        matched_tmdb_episode = candidate_episode
                        break
            elif episode_item_dictionary.get("episode_number") is not None:
                target_episode_number = int(episode_item_dictionary["episode_number"])
                for candidate_episode in fetched_episodes_list:
                    if candidate_episode.get("episode_number") == target_episode_number:
                        matched_tmdb_episode = candidate_episode
                        break

            if matched_tmdb_episode is None:
                stem_lower: str = Path(episode_filename).stem.lower()
                for candidate_episode in fetched_episodes_list:
                    candidate_name: str = str(
                        candidate_episode.get("name") or ""
                    ).lower()
                    if candidate_name and candidate_name in stem_lower:
                        matched_tmdb_episode = candidate_episode
                        break

            if matched_tmdb_episode:
                matched_identifier_string: str = str(matched_tmdb_episode.get("id", ""))
                episode_item_dictionary["tmdb_identifier"] = matched_identifier_string
                episode_item_dictionary["tmdb_episode_identifier"] = (
                    matched_identifier_string
                )
                if matched_tmdb_episode.get("name"):
                    episode_item_dictionary["name"] = matched_tmdb_episode["name"]
                    episode_item_dictionary["tmdb_name"] = matched_tmdb_episode["name"]
                if matched_tmdb_episode.get("episode_number") is not None:
                    episode_item_dictionary["episode_number"] = matched_tmdb_episode[
                        "episode_number"
                    ]
                    episode_item_dictionary["tmdb_number"] = matched_tmdb_episode[
                        "episode_number"
                    ]
                if matched_tmdb_episode.get("air_date"):
                    episode_item_dictionary["air_date"] = matched_tmdb_episode[
                        "air_date"
                    ]
                if matched_tmdb_episode.get("runtime"):
                    episode_item_dictionary["runtime"] = matched_tmdb_episode["runtime"]
                if matched_tmdb_episode.get("overview") is not None:
                    episode_item_dictionary["overview"] = matched_tmdb_episode[
                        "overview"
                    ]

        try:
            from lan_streamer.scanner.pass2_metadata import (
                _create_tmdb_placeholder_episodes,
            )

            season_metadata = season_data_dictionary.get("metadata", {})
            placeholders = _create_tmdb_placeholder_episodes(
                fetched_episodes_list,
                season_data_dictionary.get("episodes", []),
                season_folder_name,
                season_metadata,
                show_future_episodes=True,
            )
            season_data_dictionary["episodes"].extend(placeholders)
        except ImportError, AttributeError, ValueError, KeyError, RuntimeError:
            logger.debug(
                "Could not create placeholder episodes in fallback sync for season %s",
                season_folder_name,
            )

    return result_record


def set_series_metadata_match(
    connection: Session,
    series_identifier: int,
    tmdb_identifier: str,
    enrichment: dict[str, Any],
    tmdb_client: Any = None,
    tmdb_details: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Apply a manual TMDB match to a series row and synchronize all episodes.

    Matches desktop behavior: stubs are re-discovered and matched against the
    fresh TMDB metadata so that correct episode names replace any previous names.
    The series metadata is locked upon completion.
    """
    series = connection.get(Series, series_identifier)
    if series is None:
        return None

    series.tmdb_identifier = tmdb_identifier
    series.name = enrichment.get("name", series.name)
    series.overview = enrichment.get("overview", series.overview)
    series.poster_path = enrichment.get("poster_path", series.poster_path)
    series.backdrop_path = enrichment.get("backdrop_path", series.backdrop_path)
    series.year = enrichment.get("year", series.year)
    series.status = enrichment.get("status", series.status) or series.status
    series.air_date_first = enrichment.get("air_date_first", series.air_date_first)
    series.air_date_last = enrichment.get("air_date_last", series.air_date_last)

    if tmdb_client is None:
        try:
            from lan_streamer.providers.tmdb import tmdb_client as default_tmdb_client

            tmdb_client = default_tmdb_client
        except ImportError, AttributeError:
            tmdb_client = None

    tmdb_series_data: dict[str, Any] | None = tmdb_details
    if tmdb_series_data is None and tmdb_client is not None:
        try:
            tmdb_series_data = tmdb_client.get_series_by_id(tmdb_identifier)
        except Exception:
            logger.exception(
                "Failed to fetch TMDB series data for series_id=%s tmdb_identifier=%s",
                series_identifier,
                tmdb_identifier,
            )
            tmdb_series_data = None

    series_record = _series_to_scanner_dict(series)
    target_metadata = series_record.get("metadata", series_record)
    target_metadata["locked_metadata"] = False
    target_metadata.pop("tmdb_episode_group_id", None)
    for _season_name, season_data in list(series_record.get("seasons", {}).items()):
        season_data.get("metadata", {}).pop("tmdb_identifier", None)
        filtered_episodes: list[dict[str, Any]] = []
        for single_episode in season_data.get("episodes", []):
            if single_episode.get("path"):
                for field_key in [
                    "tmdb_name",
                    "tmdb_identifier",
                    "tmdb_episode_identifier",
                    "tmdb_number",
                    "air_date",
                    "runtime",
                ]:
                    single_episode.pop(field_key, None)
                filtered_episodes.append(single_episode)
        season_data["episodes"] = filtered_episodes

    series_directory: Path | None = None
    if series.path and Path(series.path).is_dir():
        series_directory = Path(series.path)
    elif series.library and series.library.root_path:
        candidate_directory = Path(series.library.root_path) / series.folder_name
        if candidate_directory.is_dir():
            series_directory = candidate_directory

    synced_series_data: dict[str, Any] | None = None
    if series_directory is not None and tmdb_series_data is not None:
        try:
            from lan_streamer.scanner.pass1_file_discovery import scan_series_pass1
            from lan_streamer.scanner.pass2_metadata import scan_series_pass2
            from lan_streamer.services.metadata_updates import clean_series_data

            pass1_result = scan_series_pass1(
                series_directory,
                existing_series_data=series_record,
                force_refresh=True,
            )
            if pass1_result is not None:
                pass2_result = scan_series_pass2(
                    series_directory,
                    existing_series_data=pass1_result,
                    tmdb_series=tmdb_series_data,
                    force_refresh=True,
                    single_item_refresh=True,
                    show_future_episodes=True,
                )
                if pass2_result is not None:
                    synced_series_data = clean_series_data(pass2_result) or pass2_result
        except Exception:
            logger.exception(
                "Scanner pipeline execution failed for series %s; attempting fallback",
                series.folder_name,
            )
            synced_series_data = None

    if synced_series_data is None and tmdb_client is not None:
        synced_series_data = _sync_series_tmdb_fallback(
            series_record, tmdb_identifier, tmdb_client
        )

    if synced_series_data is not None:
        _upsert_seasons(connection, series, synced_series_data.get("seasons", {}))
        synced_metadata = synced_series_data.get("metadata", {})
        if synced_metadata.get("name") and not enrichment.get("name"):
            series.name = synced_metadata["name"]
        if synced_metadata.get("overview") and not enrichment.get("overview"):
            series.overview = synced_metadata["overview"]
        if synced_metadata.get("poster_path") and not enrichment.get("poster_path"):
            series.poster_path = synced_metadata["poster_path"]
        if synced_metadata.get("backdrop_path") and not enrichment.get("backdrop_path"):
            series.backdrop_path = synced_metadata["backdrop_path"]

    series.locked_metadata = True
    connection.flush()
    logger.info(
        "Applied series metadata match series_id=%s tmdb_identifier=%s",
        series_identifier,
        tmdb_identifier,
    )
    return series_to_dict(series)


def set_movie_metadata_match(
    connection: Session,
    movie_identifier: int,
    tmdb_identifier: str,
    enrichment: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply a manual TMDB match to a movie row."""
    movie = connection.get(Movie, movie_identifier)
    if movie is None:
        return None
    movie.tmdb_identifier = tmdb_identifier
    movie.locked_metadata = True
    movie.name = enrichment.get("name", movie.name)
    movie.overview = enrichment.get("overview", movie.overview)
    movie.poster_path = enrichment.get("poster_path", movie.poster_path)
    movie.backdrop_path = enrichment.get("backdrop_path", movie.backdrop_path)
    movie.year = enrichment.get("year", movie.year)
    if enrichment.get("runtime_seconds"):
        movie.runtime_seconds = enrichment["runtime_seconds"]
    connection.flush()
    logger.info(
        "Applied movie metadata match movie_id=%s tmdb_identifier=%s",
        movie_identifier,
        tmdb_identifier,
    )
    return movie_to_dict(movie)


def get_rename_source(
    connection: Session, media_type: str, media_identifier: int
) -> tuple[dict[str, Any], str] | None:
    """Return the rename source dict for a media item.

    For series the result mirrors the scanner-shaped dict the desktop
    renamer consumes: ``seasons`` keyed by season name, episodes as a list
    carrying ``versions``. The second tuple item is the display name used as
    the default rename template title.
    """
    if media_type == "series":
        detail = get_series(connection, media_identifier)
        if detail is None:
            return None
        seasons: dict[str, Any] = {}
        for season in detail["seasons"]:
            label = (
                str(season.get("name")) or f"Season {season.get('season_number', 0)}"
            )
            episodes = []
            for episode in season["episodes"]:
                episode["tmdb_number"] = episode.get("tmdb_number") or episode.get(
                    "episode_number"
                )
                episodes.append(episode)
            seasons[label] = {
                "season_number": season["season_number"],
                "episodes": episodes,
            }
        series_dict = {
            "metadata": {
                "tmdb_name": detail.get("name"),
                "name": detail.get("name"),
                "tmdb_identifier": detail.get("tmdb_identifier"),
            },
            "name": detail.get("name"),
            "folder_name": detail.get("folder_name"),
            "seasons": seasons,
        }
        return series_dict, str(detail.get("name") or "Unknown Series")
    return None


def get_episode_meta(
    connection: Session, episode_identifier: int
) -> tuple[str | None, int | None, int | None, str | None]:
    """Resolve TMDB subtitle-search context for an episode.

    Returns ``(series_tmdb_identifier, season_number, episode_number,
    display_name)`` using the series' resolved TMDB identifier.
    """
    episode = connection.get(Episode, episode_identifier)
    if episode is None or episode.season is None:
        return (None, None, None, None)
    season = episode.season
    series = season.series
    display_name = (
        str(episode.name)
        or f"{series.name} S{season.season_number}E{episode.episode_number}"
    )
    return (
        series.tmdb_identifier,
        season.season_number,
        episode.tmdb_number or episode.episode_number,
        display_name,
    )


def get_movie_meta(
    connection: Session, movie_identifier: int
) -> tuple[str | None, None, None, str | None]:
    """Resolve TMDB subtitle-search context for a movie."""
    movie = connection.get(Movie, movie_identifier)
    if movie is None:
        return (None, None, None, None)
    return (movie.tmdb_identifier, None, None, str(movie.name))


def get_episode_media_path(connection: Session, episode_identifier: int) -> Path | None:
    """Return the primary (preferred active) media file path for an episode."""
    media_file = connection.scalars(
        select(MediaFile)
        .where(
            MediaFile.media_type == "episode",
            MediaFile.media_id == episode_identifier,
            MediaFile.active.is_(True),
        )
        .order_by(MediaFile.id)
    ).first()
    if media_file is not None:
        return Path(media_file.path)
    episode = connection.get(Episode, episode_identifier)
    return Path(episode.path) if episode is not None and episode.path else None


def get_movie_media_path(connection: Session, movie_identifier: int) -> Path | None:
    """Return the primary (preferred active) media file path for a movie."""
    media_file = connection.scalars(
        select(MediaFile)
        .where(
            MediaFile.media_type == "movie",
            MediaFile.media_id == movie_identifier,
            MediaFile.active.is_(True),
        )
        .order_by(MediaFile.id)
    ).first()
    if media_file is not None:
        return Path(media_file.path)
    movie = connection.get(Movie, movie_identifier)
    return Path(movie.path) if movie is not None and movie.path else None
