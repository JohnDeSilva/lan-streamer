"""
Movie scanning functions — scan a single movie directory and detect file changes.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, TypedDict

from lan_streamer.providers.tmdb import tmdb_client
from lan_streamer.scanner.file_property_scanner import (
    get_detailed_file_info,
    get_stub_file_info,
)
from lan_streamer.scanner.parser import (
    _parse_movie_folder,
    find_video_files,
)
from lan_streamer.services.metadata_movie import (
    _build_movie_metadata_defaults,
    _apply_existing_movie_metadata,
    _apply_tmdb_movie_data,
    _resolve_movie_jellyfin_id,
)
from lan_streamer.services.file_discovery import detect_movie_file_changes

logger = logging.getLogger("lan_streamer.scanner")


class _MovieScanFilesResult(TypedDict):
    """Typed result from _scan_movie_files."""

    versions: list[Dict[str, Any]]
    default_path: str | None
    active_version: Dict[str, Any]
    video_path: str
    video_file: Path
    ctime: float


def _detect_movie_changes(
    movie_directory: Path,
    existing_movie_data: Dict[str, Any] | None,
    offline: bool,
) -> tuple[bool, bool]:
    """Detect if movie files have changed and determine offline mode."""
    is_movie_changed = True
    if existing_movie_data:
        # Check directory mtime to skip walking files
        try:
            current_mtime = movie_directory.stat().st_mtime
        except Exception:
            current_mtime = None

        cached_mtime = existing_movie_data.get("last_scanned_mtime")
        if cached_mtime is not None and current_mtime == cached_mtime:
            is_movie_changed = False
        else:
            is_movie_changed = detect_movie_file_changes(
                movie_directory, existing_movie_data
            )

        if not offline:
            is_movie_changed = is_movie_changed or existing_movie_data.get(
                "_changed", True
            )
    movie_offline = offline or not is_movie_changed
    return is_movie_changed, movie_offline


def _scan_movie_files(
    movie_directory: Path,
    existing_movie_data: Dict[str, Any] | None,
    movie_offline: bool,
    force_refresh: bool,
    metadata_only: bool,
    detail_callback: Callable | None = None,
) -> _MovieScanFilesResult | None:
    """Scan video files and resolve versions, or load from existing data.

    Returns None when no video is available.
    """
    from lan_streamer.scanner.versioning import choose_active_version

    if metadata_only:
        if not existing_movie_data:
            return None
        versions = existing_movie_data.get("versions", [])
        if not versions and existing_movie_data.get("path"):
            versions = [get_stub_file_info(existing_movie_data["path"])]
        default_path = existing_movie_data.get(
            "default_path"
        ) or existing_movie_data.get("path")
        active_version = choose_active_version(versions, default_path)
        video_path = active_version.get("path")
        if not video_path:
            return None
        video_file = Path(video_path)
        ctime = existing_movie_data.get("date_added") or 0
    else:
        video_files = find_video_files(movie_directory)

        if not video_files:
            return None

        versions = []
        for file in video_files:
            path_str = str(file.absolute())
            existing_v = None
            if existing_movie_data and existing_movie_data.get("versions"):
                for ev in existing_movie_data["versions"]:
                    if ev.get("path") == path_str:
                        existing_v = ev
                        break
            use_existing = False
            if existing_v and not force_refresh:
                # If we are online, but the existing version was only a stub (missing technical info),
                # we should re-scan it to fetch full media details.
                is_stub = (
                    existing_v.get("video_codec") == "Unknown"
                    or existing_v.get("resolution") == "Unknown"
                )
                if not (is_stub and not movie_offline):
                    use_existing = True

            if use_existing:
                versions.append(existing_v)
            else:
                if movie_offline:
                    versions.append(get_stub_file_info(path_str))
                else:
                    versions.append(get_detailed_file_info(path_str))

        # Preserve old versions from existing data no longer found on disk
        incoming_paths = {v["path"] for v in versions if v.get("path")}
        if existing_movie_data and existing_movie_data.get("versions"):
            for ev in existing_movie_data["versions"]:
                ev_path = ev.get("path")
                if ev_path and ev_path not in incoming_paths:
                    versions.append(ev)

        default_path = (
            existing_movie_data.get("default_path") if existing_movie_data else None
        )
        active_version = choose_active_version(versions, default_path)
        video_path = active_version.get("path")
        if not video_path:
            return None
        video_file = Path(video_path)

        if detail_callback:
            detail_callback(
                "start_file", {"file": str(video_file), "folder": movie_directory.name}
            )

        try:
            ctime = os.path.getctime(video_file)
        except OSError:
            ctime = 0

    return _MovieScanFilesResult(
        versions=versions,
        default_path=default_path,
        active_version=active_version,
        video_path=video_path,
        video_file=video_file,
        ctime=ctime,
    )


def _handle_early_return(
    existing_movie_data: Dict[str, Any] | None,
    video_path: str | None,
    active_version: Dict[str, Any],
    versions: list[Dict[str, Any]],
    default_path: str | None,
    manual_jellyfin_id: str | None,
    jellyfin_data: Dict[str, dict] | None,
) -> Dict[str, Any] | None:
    """Return updated existing data when no force refresh or cleanup is needed.

    Returns a movie_data dict if conditions are met, or None to continue to full scan.
    """
    if not existing_movie_data:
        return None

    movie_data = existing_movie_data.copy()
    if video_path:
        movie_data["path"] = video_path
    movie_data["video_codec"] = active_version.get("video_codec")
    movie_data["resolution"] = active_version.get("resolution")
    movie_data["bit_rate"] = active_version.get("bit_rate")
    movie_data["audio_tracks"] = active_version.get("audio_tracks")
    movie_data["subtitle_tracks"] = active_version.get("subtitle_tracks")
    movie_data["versions"] = versions
    movie_data["default_path"] = default_path

    if not movie_data.get("jellyfin_id") and jellyfin_data:
        path_map = jellyfin_data.get("path_map", {})
        if video_path in path_map:
            movie_data["jellyfin_id"] = path_map[video_path]["id"]
        elif movie_data.get("tmdb_identifier"):
            tmdb_map = jellyfin_data.get("tmdb_episode_map", {})
            if movie_data["tmdb_identifier"] in tmdb_map:
                movie_data["jellyfin_id"] = tmdb_map[movie_data["tmdb_identifier"]]
    if manual_jellyfin_id:
        movie_data["jellyfin_id"] = manual_jellyfin_id
    if not movie_data.get("runtime"):
        movie_data["runtime"] = 0
    return movie_data


def _resolve_tmdb_movie_data(
    tmdb_movie: Dict[str, Any] | None,
    movie_metadata: Dict[str, Any],
    title: str,
    year: int | None,
    is_locked: bool,
    existing_tmdb_id: str,
    existing_movie_data: Dict[str, Any] | None,
    movie_offline: bool,
    single_item_refresh: bool,
    video_path: str,
    jellyfin_data: Dict[str, dict] | None,
    metadata_only: bool,
) -> None:
    """Fetch and apply TMDB metadata to movie_metadata in-place."""
    if movie_offline:
        return

    if tmdb_movie and "title" not in tmdb_movie and "id" in tmdb_movie:
        if single_item_refresh or not movie_metadata.get("tmdb_name"):
            full = tmdb_client.get_movie_by_id(tmdb_movie["id"])
            if full:
                tmdb_movie = full

    if not tmdb_movie:
        if movie_metadata["tmdb_identifier"]:
            tmdb_movie = {
                "id": movie_metadata["tmdb_identifier"],
                "title": movie_metadata["tmdb_name"],
                "overview": movie_metadata["overview"],
                "poster_path": movie_metadata["poster_path"],
                "release_date": f"{movie_metadata['year']}-01-01"
                if movie_metadata["year"]
                else "",
            }
        elif not is_locked and (
            single_item_refresh or not existing_movie_data or not existing_tmdb_id
        ):
            tmdb_movie = tmdb_client.search_movie(title, year)

    if tmdb_movie:
        _apply_tmdb_movie_data(
            movie_metadata,
            tmdb_movie,
            existing_movie_data,
            movie_offline,
            metadata_only=metadata_only,
        )

    movie_metadata["jellyfin_id"] = _resolve_movie_jellyfin_id(
        movie_metadata, video_path, jellyfin_data
    )


def _build_movie_data(
    folder_name: str,
    video_path: str,
    movie_metadata: Dict[str, Any],
    existing_movie_data: Dict[str, Any] | None,
    ctime: float,
    active_version: Dict[str, Any],
    versions: list[Dict[str, Any]],
    default_path: str | None,
    is_movie_changed: bool,
    last_scanned_mtime: float | None = None,
) -> Dict[str, Any]:
    """Build the final movie_data dict from all gathered information."""
    return {
        "name": folder_name,
        "path": video_path,
        "jellyfin_id": movie_metadata["jellyfin_id"],
        "tmdb_identifier": movie_metadata["tmdb_identifier"],
        "poster_path": movie_metadata["poster_path"],
        "overview": movie_metadata["overview"],
        "tmdb_name": movie_metadata["tmdb_name"],
        "locked_metadata": existing_movie_data.get("locked_metadata", False)
        if existing_movie_data
        else False,
        "date_added": ctime,
        "runtime": movie_metadata["runtime"] or 0,
        "rating": movie_metadata["rating"],
        "genre": movie_metadata["genre"],
        "year": movie_metadata["year"],
        "watched": existing_movie_data.get("watched", False)
        if existing_movie_data
        else False,
        "last_played_position": existing_movie_data.get("last_played_position", 0)
        if existing_movie_data
        else 0,
        "video_codec": active_version.get("video_codec"),
        "resolution": active_version.get("resolution"),
        "bit_rate": active_version.get("bit_rate"),
        "audio_tracks": active_version.get("audio_tracks"),
        "subtitle_tracks": active_version.get("subtitle_tracks"),
        "versions": versions,
        "default_path": default_path,
        "_changed": is_movie_changed,
        "last_scanned_mtime": last_scanned_mtime
        if last_scanned_mtime is not None
        else (
            existing_movie_data.get("last_scanned_mtime")
            if existing_movie_data
            else None
        ),
    }


def scan_movie(
    movie_directory: Path,
    tmdb_movie: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, dict] | None = None,
    manual_jellyfin_id: str | None = None,
    existing_movie_data: Dict[str, Any] | None = None,
    force_refresh: bool = False,
    cleanup: bool = False,
    single_item_refresh: bool = False,
    detail_callback: Callable | None = None,
    offline: bool = False,
    metadata_only: bool = False,
) -> Dict[str, Any] | None:
    """Scans a single movie directory and fetches metadata from TMDB."""

    # Phase 1: Parse folder name
    folder_name = movie_directory.name
    title, year = _parse_movie_folder(folder_name)

    # Phase 2: Detect changes
    is_movie_changed, movie_offline = _detect_movie_changes(
        movie_directory, existing_movie_data, offline
    )

    # Phase 3: Scan video files
    scan_result = _scan_movie_files(
        movie_directory,
        existing_movie_data,
        movie_offline,
        force_refresh,
        metadata_only,
        detail_callback,
    )
    if scan_result is None:
        return None

    versions = scan_result["versions"]
    default_path = scan_result["default_path"]
    active_version = scan_result["active_version"]
    video_path = scan_result["video_path"]
    video_file = scan_result["video_file"]
    ctime = scan_result["ctime"]

    # Phase 4: Determine locked status and existing TMDB id
    is_locked = (
        existing_movie_data.get("locked_metadata", False)
        if existing_movie_data
        else False
    )
    existing_tmdb_id = (
        existing_movie_data.get("tmdb_identifier", "") if existing_movie_data else ""
    )

    # Phase 5: Detect new file — auto-refresh metadata
    has_new_file = (
        not existing_movie_data or existing_movie_data.get("path") != video_path
    )
    if has_new_file and not is_locked:
        logger.info(
            f"New file detected for movie '{folder_name}'. Automatically pulling fresh metadata."
        )
        force_refresh = True
        if existing_tmdb_id and not tmdb_movie and not movie_offline:
            full = tmdb_client.get_movie_by_id(existing_tmdb_id)
            if full:
                tmdb_movie = full

    # Phase 6: Build base metadata
    movie_metadata = _build_movie_metadata_defaults()
    movie_metadata["jellyfin_id"] = manual_jellyfin_id or ""

    if existing_movie_data:
        _apply_existing_movie_metadata(
            movie_metadata, existing_movie_data, manual_jellyfin_id
        )

    # Phase 7: Early return (no refresh/cleanup — reuse existing data)
    if not force_refresh and not cleanup:
        early_result = _handle_early_return(
            existing_movie_data,
            video_path,
            active_version,
            versions,
            default_path,
            manual_jellyfin_id,
            jellyfin_data,
        )
        if early_result is not None:
            if detail_callback and not metadata_only:
                detail_callback(
                    "finish_file",
                    {"file": str(video_file), "folder": movie_directory.name},
                )
            return early_result

    # Phase 8: Resolve TMDB metadata
    _resolve_tmdb_movie_data(
        tmdb_movie,
        movie_metadata,
        title,
        year,
        is_locked,
        existing_tmdb_id,
        existing_movie_data,
        movie_offline,
        single_item_refresh,
        video_path,
        jellyfin_data,
        metadata_only,
    )

    current_mtime = None
    if not metadata_only:
        try:
            current_mtime = movie_directory.stat().st_mtime
        except Exception:
            pass

    # Phase 9: Build final movie data
    movie_data = _build_movie_data(
        folder_name,
        video_path,
        movie_metadata,
        existing_movie_data,
        ctime,
        active_version,
        versions,
        default_path,
        is_movie_changed,
        last_scanned_mtime=current_mtime,
    )

    if detail_callback and not metadata_only:
        detail_callback(
            "finish_file", {"file": str(video_file), "folder": movie_directory.name}
        )

    return movie_data
