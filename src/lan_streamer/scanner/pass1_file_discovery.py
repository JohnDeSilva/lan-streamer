"""
Pass 1 — file discovery for series and movies.

Discovers video files on disk and creates stub records.  No TMDB calls,
no ffprobe (uses ``get_stub_file_info()`` — just file path and size).
"""

import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lan_streamer.scanner.file_property_scanner import get_stub_file_info
from lan_streamer.scanner.parser import (
    VIDEO_EXTENSIONS,
    _parse_episode_number,
    find_video_files,
)

logger = logging.getLogger("lan_streamer.scanner.pass1_file_discovery")


def _validate_series_file_layout(series_directory: Path) -> None:
    """Warn about video files outside season folders or nested too deeply."""
    outside_file_paths: list[Path] = []
    nested_too_deeply: list[Path] = []
    for file_path in find_video_files(series_directory):
        try:
            rel_path = file_path.relative_to(series_directory)
            parts = rel_path.parts
            if len(parts) == 1:
                outside_file_paths.append(file_path)
            else:
                first_dir_lower = parts[0].lower()
                is_valid = (
                    "season" in first_dir_lower
                    or "special" in first_dir_lower
                    or "extra" in first_dir_lower
                    or "featurette" in first_dir_lower
                    or "bonus" in first_dir_lower
                    or "shorts" in first_dir_lower
                    or bool(re.search(r"\d+", parts[0]))
                )
                if not is_valid:
                    outside_file_paths.append(file_path)
                elif len(parts) > 2:
                    nested_too_deeply.append(file_path)
        except Exception:
            pass

    if outside_file_paths:
        logger.warning(
            "Series '%s' has %d video file(s) outside of season or "
            "specials/extras folders. Example: '%s'",
            series_directory.name,
            len(outside_file_paths),
            outside_file_paths[0].name,
        )
    if nested_too_deeply:
        logger.warning(
            "Series '%s' has %d video file(s) nested too deeply. Example: '%s'",
            series_directory.name,
            len(nested_too_deeply),
            nested_too_deeply[0].relative_to(series_directory),
        )


def _check_season_unchanged(
    season_directory: Path, existing_season: dict[str, Any]
) -> bool:
    """Return True if mtime matches cached value and all existing files still exist."""
    from lan_streamer import db

    try:
        current_mtime = season_directory.stat().st_mtime
    except OSError:
        return False
    cached_mtime = db.get_directory_mtime(str(season_directory.absolute()))
    if cached_mtime is None or current_mtime != cached_mtime or current_mtime <= 0:
        return False
    for episode in existing_season.get("episodes", []):
        episode_path = episode.get("path")
        if episode_path is not None and not Path(episode_path).exists():
            return False
    return True


def _scan_season_files(season_directory: Path) -> list[dict[str, Any]]:
    """Walk a season directory and return stub episode records for video files."""
    stub_episodes: list[dict[str, Any]] = []
    try:
        with os.scandir(str(season_directory)) as scan_iterator:
            for entry in scan_iterator:
                if entry.is_dir(follow_symlinks=True):
                    logger.warning(
                        "Ignoring subdirectory in season folder: '%s'", entry.path
                    )
                    continue
                if entry.name.startswith(".") or not entry.is_file(
                    follow_symlinks=True
                ):
                    continue
                suffix = Path(entry.name).suffix.lower()
                if suffix not in VIDEO_EXTENSIONS:
                    continue
                file_path = Path(entry.path)
                path_str = str(file_path.absolute())
                parsed = _parse_episode_number(entry.name)
                try:
                    ctime = file_path.stat().st_ctime
                except OSError:
                    ctime = 0.0
                stub_episodes.append(
                    {
                        "path": path_str,
                        "name": entry.name,
                        "season_number": parsed[0] if parsed else 0,
                        "episode_number": parsed[1] if parsed else 0,
                        "date_added": ctime,
                        "versions": [get_stub_file_info(path_str)],
                    }
                )
    except PermissionError:
        logger.warning(
            "Permission denied reading season directory: '%s'", season_directory
        )
    except OSError as error:
        logger.error("Error reading season directory '%s': %s", season_directory, error)
    # Merge duplicate episodes with the same number into a single entry with combined versions.
    merged: dict[tuple[int, int], dict[str, Any]] = {}
    unnumbered: list[dict[str, Any]] = []
    for episode in stub_episodes:
        episode_number = episode.get("episode_number", 0)
        if episode_number > 0:
            key = (episode["season_number"], episode_number)
            if key in merged:
                existing = merged[key]
                existing["versions"].extend(episode.get("versions", []))
            else:
                episode_copy = dict(episode)
                episode_copy["versions"] = list(episode.get("versions", []))
                merged[key] = episode_copy
        else:
            unnumbered.append(episode)
    return unnumbered + list(merged.values())


def _link_existing_episodes(
    scanned_episodes: list[dict[str, Any]],
    existing_episodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Cross-reference scanned episodes with existing records by path.

    When a file path matches an existing episode, the existing episode's
    metadata is preserved (watched, TMDB identifiers, etc.) while updating
    the technical stub info from the fresh file scan.
    """
    existing_by_path: dict[str, dict[str, Any]] = {}
    for ep in existing_episodes:
        path = ep.get("path")
        if path:
            existing_by_path[path] = ep
        for version in ep.get("versions", []):
            vpath = version.get("path")
            if vpath:
                existing_by_path.setdefault(vpath, ep)

    linked: list[dict[str, Any]] = []
    for scanned in scanned_episodes:
        scan_path = scanned.get("path")
        if scan_path and scan_path in existing_by_path:
            matched = existing_by_path[scan_path]
            merged = {**matched, **scanned}
            merged["versions"] = scanned.get("versions", matched.get("versions", []))
            linked.append(merged)
        else:
            linked.append(scanned)

    # Carry forward existing episodes whose files are no longer on disk
    # (placeholder records for TMDB-only episodes).
    scanned_paths = {ep.get("path") for ep in linked if ep.get("path")}
    for ep in existing_episodes:
        if ep.get("path") not in scanned_paths:
            linked.append(ep)

    return linked


def _save_directory_mtime(path: str, display_name: str) -> None:
    """Persist the current directory mtime into the ScannedDirectory table."""
    try:
        from lan_streamer import db

        db.save_directory_mtime(path, Path(path).stat().st_mtime)
        logger.debug("Saved directory mtime for '%s'", display_name)
    except OSError as mtime_error:
        logger.warning(
            "Could not read directory mtime for '%s': %s", display_name, mtime_error
        )
    except Exception:
        logger.debug(
            "Could not persist directory mtime for '%s' (DB not ready)", display_name
        )


def scan_series_pass1(
    series_directory: Path,
    existing_series_data: dict[str, Any] | None = None,
    force_refresh: bool = False,
    detail_callback: Callable | None = None,
) -> dict[str, Any]:
    """Pass 1 file discovery for a TV series directory.

    Discovers video files on disk and creates stub episode records.  No TMDB
    calls are made.

    Args:
        series_directory: The top-level series directory.
        existing_series_data: Data from a previous scan, if any.
        force_refresh: If True, re-scan even when mtimes match.
        detail_callback: Optional progress callback ``(event_type, event_data)``.

    Returns:
        A series_data dict with ``seasons``, ``_pass1_season_mtimes``,
        and minimal metadata keys.
    """
    logger.info("Pass 1 file discovery for series '%s'", series_directory.name)
    _validate_series_file_layout(series_directory)

    series_name = series_directory.name

    # Bootstrap metadata from existing data.
    metadata: dict[str, Any] = {
        "name": series_name,
        "overview": "",
        "poster_path": "",
        "backdrop_path": "",
        "genre": "",
        "year": 0,
        "rating": 0.0,
        "runtime": 0,
        "status": "",
        "network": "",
        "tmdb_identifier": "",
        "tmdb_name": "",
        "jellyfin_id": "",
        "myanimelist_id": "",
        "locked_metadata": False,
    }
    if existing_series_data:
        existing_meta = existing_series_data.get("metadata", {})
        for key in metadata:
            if existing_meta.get(key):
                metadata[key] = existing_meta[key]

    series_data: dict[str, Any] = {
        "name": series_name,
        "path": str(series_directory.absolute()),
        "metadata": metadata,
        "seasons": {},
        "_pass1_season_mtimes": {},
    }
    for key in ("tmdb_identifier", "jellyfin_id", "myanimelist_id"):
        if existing_series_data and existing_series_data.get(key):
            series_data[key] = existing_series_data[key]

    # Discover season directories.
    season_directories: list[tuple[str, Path, dict[str, Any] | None]] = []
    try:
        with os.scandir(str(series_directory)) as scan_iterator:
            for entry in scan_iterator:
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                season_dir = Path(entry.path)
                existing_season: dict[str, Any] | None = None
                if existing_series_data and entry.name in existing_series_data.get(
                    "seasons", {}
                ):
                    existing_season = existing_series_data["seasons"][entry.name]
                season_directories.append((entry.name, season_dir, existing_season))
    except PermissionError:
        logger.warning(
            "Permission denied reading series directory '%s'", series_directory
        )
    except OSError as error:
        logger.error("Error reading series directory '%s': %s", series_directory, error)

    # Process each season.
    for season_name, season_directory_path, existing_season in season_directories:
        if detail_callback:
            detail_callback(
                "start_season", {"folder": series_directory.name, "season": season_name}
            )

        unchanged = (
            not force_refresh
            and existing_season is not None
            and _check_season_unchanged(season_directory_path, existing_season)
        )

        if unchanged:
            logger.debug(
                "Season '%s' in '%s' is unchanged; reusing existing data.",
                season_name,
                series_directory.name,
            )
            assert existing_season is not None
            episodes = list(existing_season.get("episodes", []))
            is_changed = False
        else:
            episodes = _scan_season_files(season_directory_path)
            is_changed = True
            if existing_season:
                episodes = _link_existing_episodes(
                    episodes, existing_season.get("episodes", [])
                )
            if detail_callback:
                for episode in episodes:
                    ep_path = episode.get("path")
                    if ep_path is None:
                        continue
                    detail_callback(
                        "start_file",
                        {
                            "file": ep_path,
                            "folder": series_directory.name,
                            "season": season_name,
                        },
                    )
                    detail_callback(
                        "finish_file",
                        {
                            "file": ep_path,
                            "folder": series_directory.name,
                            "season": season_name,
                        },
                    )

        try:
            current_mtime = season_directory_path.stat().st_mtime
        except OSError:
            current_mtime = None

        season_metadata: dict[str, Any] = {
            "season_directory_path": str(season_directory_path.absolute()),
            "last_scanned_mtime": current_mtime,
        }
        if existing_season is not None:
            existing_meta = existing_season.get("metadata", {})
            for key in ("jellyfin_id", "tmdb_identifier", "poster_path"):
                if existing_meta.get(key):
                    season_metadata[key] = existing_meta[key]

        series_data["seasons"][season_name] = {
            "metadata": season_metadata,
            "episodes": episodes,
            "_changed": is_changed,
        }
        if current_mtime is not None:
            series_data["_pass1_season_mtimes"][season_name] = current_mtime

        if detail_callback:
            detail_callback(
                "finish_season",
                {"folder": series_directory.name, "season": season_name},
            )

    # Preserve seasons from existing data that no longer have directories.
    if existing_series_data:
        for old_name, old_data in existing_series_data.get("seasons", {}).items():
            if old_name not in series_data["seasons"]:
                logger.info(
                    "Preserving missing season '%s' from existing data.", old_name
                )
                series_data["seasons"][old_name] = old_data

    _save_directory_mtime(str(series_directory.absolute()), series_directory.name)

    total_episodes = sum(len(s["episodes"]) for s in series_data["seasons"].values())
    logger.info(
        "Pass 1 complete for series '%s': %d seasons, %d episodes.",
        series_directory.name,
        len(series_data["seasons"]),
        total_episodes,
    )
    return series_data


def scan_movie_pass1(
    movie_directory: Path,
    existing_movie_data: dict[str, Any] | None = None,
    force_refresh: bool = False,
    detail_callback: Callable | None = None,
) -> dict[str, Any] | None:
    """Pass 1 file discovery for a movie directory.

    Discovers video files on disk and creates a stub movie record.  No TMDB
    calls are made.

    Args:
        movie_directory: The movie directory to scan.
        existing_movie_data: Data from a previous scan, if any.
        force_refresh: If True, re-scan even when mtimes match.
        detail_callback: Optional progress callback.

    Returns:
        A movie_data dict or None if no video files were found.
    """
    from lan_streamer import db

    logger.info("Pass 1 file discovery for movie '%s'", movie_directory.name)

    # Fast path: unchanged directory.
    if not force_refresh and existing_movie_data is not None:
        try:
            current_mtime = movie_directory.stat().st_mtime
        except OSError:
            current_mtime = None
        if current_mtime is not None and current_mtime > 0:
            cached_mtime = db.get_directory_mtime(str(movie_directory.absolute()))
            if cached_mtime is not None and current_mtime == cached_mtime:
                existing_path = existing_movie_data.get("path")
                if existing_path and Path(existing_path).exists():
                    logger.debug(
                        "Movie '%s' is unchanged; reusing existing data.",
                        movie_directory.name,
                    )
                    existing_movie_data["_changed"] = False
                    return existing_movie_data

    # Find video files.
    video_files = find_video_files(movie_directory)
    if not video_files:
        logger.warning("No video files found in movie directory '%s'.", movie_directory)
        return None

    # Build versions from ALL video files so duplicates are linked to the same movie.
    versions = [get_stub_file_info(str(f.absolute())) for f in video_files]

    # Carry forward existing versions not found on disk (e.g. manually added).
    if existing_movie_data:
        fresh_paths = {v.get("path") for v in versions if v.get("path")}
        for ev in existing_movie_data.get("versions", []):
            if ev.get("path") and ev["path"] not in fresh_paths:
                versions.append(ev)

    video_file = video_files[0]
    path_str = str(video_file.absolute())

    if detail_callback:
        detail_callback(
            "start_file", {"file": path_str, "folder": movie_directory.name}
        )

    try:
        ctime = video_file.stat().st_ctime
    except OSError:
        ctime = 0.0

    movie_data: dict[str, Any] = {
        "name": movie_directory.name,
        "path": path_str,
        "movie_directory_path": str(movie_directory.absolute()),
        "date_added": ctime,
        "versions": versions,
        "_changed": True,
        "default_path": existing_movie_data.get("default_path")
        if existing_movie_data
        else None,
    }

    # Carry forward existing metadata.
    field_defaults: dict[str, Any] = {
        "tmdb_identifier": "",
        "jellyfin_id": "",
        "poster_path": "",
        "overview": "",
        "tmdb_name": "",
        "locked_metadata": False,
        "runtime": 0,
        "rating": 0.0,
        "genre": "",
        "year": 0,
        "watched": False,
        "last_played_position": 0,
    }
    for key in field_defaults:
        if existing_movie_data and key in existing_movie_data:
            movie_data[key] = existing_movie_data[key]
        else:
            movie_data[key] = field_defaults[key]

    _save_directory_mtime(str(movie_directory.absolute()), movie_directory.name)

    if detail_callback:
        detail_callback(
            "finish_file", {"file": path_str, "folder": movie_directory.name}
        )

    logger.info(
        "Pass 1 complete for movie '%s': %d video file(s).",
        movie_directory.name,
        len(video_files),
    )
    return movie_data
