"""
Movie scanning functions — scan a single movie directory and detect file changes.
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any

from lan_streamer.scanner.proxy import tmdb_client
from lan_streamer.scanner.file_property_scanner import (
    get_detailed_file_info,
    get_stub_file_info,
)
from lan_streamer.scanner.parser import (
    _parse_movie_folder,
    find_video_files,
)
from lan_streamer.scanner.metadata import (
    _build_movie_metadata_defaults,
    _apply_existing_movie_metadata,
    _apply_tmdb_movie_data,
    _resolve_movie_jellyfin_id,
)

logger = logging.getLogger("lan_streamer.scanner")


def _has_movie_files_changed(
    movie_dir: Path, existing_movie_data: Dict[str, Any]
) -> bool:
    """
    Checks if the files for a movie have changed in its folder.
    """
    try:
        disk_files = find_video_files(movie_dir)
    except Exception:
        return True

    existing_versions = existing_movie_data.get("versions", [])
    existing_by_path = {v["path"]: v for v in existing_versions if v.get("path")}
    if not existing_by_path and existing_movie_data.get("path"):
        existing_by_path[existing_movie_data["path"]] = existing_movie_data

    if len(disk_files) != len(existing_by_path):
        return True

    for disk_file in disk_files:
        path_str = str(disk_file.absolute())
        if path_str not in existing_by_path:
            return True

        existing_item = existing_by_path[path_str]
        sizes = [existing_item.get("size_bytes")]
        sizes = [s for s in sizes if s is not None]

        try:
            disk_size = disk_file.stat().st_size
        except Exception:
            return True

        if not any(s == disk_size for s in sizes):
            return True

    return False


def scan_movie(
    movie_directory: Path,
    tmdb_movie: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, dict] | None = None,
    manual_jellyfin_id: str | None = None,
    existing_movie_data: Dict[str, Any] | None = None,
    force_refresh: bool = False,
    cleanup: bool = False,
    single_item_refresh: bool = False,
    detail_callback: Any = None,
    offline: bool = False,
    metadata_only: bool = False,
) -> Dict[str, Any] | None:
    # Import here to avoid circular dependency with core.choose_active_version
    from lan_streamer.scanner.versioning import choose_active_version

    folder_name = movie_directory.name
    title, year = _parse_movie_folder(folder_name)

    is_movie_changed = True
    if existing_movie_data:
        if offline:
            is_movie_changed = _has_movie_files_changed(
                movie_directory, existing_movie_data
            )
        else:
            is_movie_changed = existing_movie_data.get("_changed", True)
    movie_offline = offline or not is_movie_changed

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
            if existing_v and not force_refresh:
                versions.append(existing_v)
            else:
                if movie_offline:
                    versions.append(get_stub_file_info(path_str))
                else:
                    versions.append(get_detailed_file_info(path_str))

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

    is_locked = (
        existing_movie_data.get("locked_metadata", False)
        if existing_movie_data
        else False
    )
    existing_tmdb_id = (
        existing_movie_data.get("tmdb_identifier", "") if existing_movie_data else ""
    )

    # Detect if this is a newly found file path
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

    movie_metadata = _build_movie_metadata_defaults()
    movie_metadata["jellyfin_id"] = manual_jellyfin_id or ""

    if existing_movie_data:
        _apply_existing_movie_metadata(
            movie_metadata, existing_movie_data, manual_jellyfin_id
        )

    if not force_refresh and not cleanup and existing_movie_data:
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

    if not movie_offline:
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

    movie_data = {
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
    }

    if detail_callback:
        detail_callback(
            "finish_file", {"file": str(video_file), "folder": movie_directory.name}
        )

    return movie_data
