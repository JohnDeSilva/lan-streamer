import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

from lan_streamer.db import natural_sort_key
from lan_streamer.scanner.proxy import tmdb_client, clean_series_data, scanner_proxy
from lan_streamer.scanner.parser import (
    VIDEO_EXTENSIONS,
    has_video_files,
    _is_video_file,
    _parse_movie_folder,
)
from lan_streamer.scanner.metadata import (
    _resolve_existing_jellyfin_id,
    _build_locked_movie_tmdb_stub,
    _build_locked_tv_tmdb_stub,
    _build_movie_metadata_defaults,
    _apply_existing_movie_metadata,
    _apply_tmdb_movie_data,
    _resolve_movie_jellyfin_id,
    _process_series_metadata,
    _process_season_metadata,
    _process_episode_file,
    _merge_season_episodes,
)

logger = logging.getLogger("lan_streamer.scanner")


class LibraryDict(dict[str, Any]):
    """
    Custom dictionary subclass to hold library contents and track
    any root directories that were unavailable during scanning.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.unavailable_directories: List[str] = []


def scan_directories(
    root_directories: List[str],
    library_type: str = "tv",
    existing_library: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, Any] | None = None,
    callback: Any = None,
    force_refresh: bool = False,
    cleanup: bool = False,
    single_item_refresh: bool = False,
    detail_callback: Any = None,
    root_directory_label: str = "",
) -> LibraryDict:
    """
    Scans root directories and matches with TMDB to pull metadata.
    Watch history (watched status) is handled separately via Jellyfin sync.
    """
    library = LibraryDict()
    existing_library = existing_library or {}

    logger.info(f"Starting directory scan. Root directories: {root_directories}")

    for root_directory in root_directories:
        logger.info(f"Scanning root directory: {root_directory}")
        root_path = Path(root_directory)
        if not root_path.exists() or not root_path.is_dir():
            logger.warning(f"Root directory '{root_directory}' is unavailable")
            library.unavailable_directories.append(root_directory)
            if detail_callback:
                detail_callback("unavailable_root", {"root": root_directory})
            continue

        # Sort series directories by mtime (newest first)
        series_dirs = sorted(
            [
                directory
                for directory in root_path.iterdir()
                if directory.is_dir()
                and not directory.name.startswith(".")
                and has_video_files(directory)
            ],
            key=lambda directory: directory.stat().st_mtime,
            reverse=True,
        )

        if detail_callback:
            detail_callback(
                "root_total",
                {"root": root_directory, "total": len(series_dirs)},
            )

        for series_directory in series_dirs:
            series_name = series_directory.name
            if detail_callback:
                detail_callback(
                    "start_folder",
                    {"root": root_directory, "folder": series_name},
                )

            # Check if we have an existing manual match for THIS SPECIFIC folder name
            existing_series = existing_library.get(series_name)
            tmdb_series = None
            is_locked = False
            existing_jellyfin_id = None
            has_meta = False

            if existing_series:
                existing_jellyfin_id = _resolve_existing_jellyfin_id(
                    existing_series, library_type
                )
                if library_type == "movie":
                    is_locked = bool(existing_series.get("locked_metadata", False))
                    has_meta = bool(existing_series.get("tmdb_identifier"))
                    if is_locked:
                        logger.info(
                            f"Using locked TMDB metadata for movie '{series_name}' "
                            f"(ID: {existing_series['tmdb_identifier']})"
                        )
                        tmdb_series = _build_locked_movie_tmdb_stub(
                            existing_series, series_name
                        )
                else:
                    is_locked = bool(
                        existing_series.get("metadata", {}).get(
                            "locked_metadata", False
                        )
                    )
                    has_meta = bool(
                        existing_series.get("metadata", {}).get("tmdb_identifier")
                    )
                    if is_locked:
                        logger.info(
                            f"Using locked TMDB metadata for '{series_name}' "
                            f"(ID: {existing_series['metadata']['tmdb_identifier']})"
                        )
                        tmdb_series = _build_locked_tv_tmdb_stub(existing_series)

            series_force_refresh = (
                force_refresh
                if not is_locked and (single_item_refresh or not has_meta)
                else False
            )
            cleaned: Optional[Dict[str, Any]] = None
            if library_type == "movie":
                series_data = scanner_proxy.scan_movie(
                    series_directory,
                    tmdb_movie=tmdb_series,
                    jellyfin_data=jellyfin_data,
                    manual_jellyfin_id=existing_jellyfin_id,
                    existing_movie_data=existing_series,
                    force_refresh=series_force_refresh,
                    cleanup=cleanup,
                    single_item_refresh=single_item_refresh,
                    detail_callback=detail_callback,
                )
                if not series_data:
                    if detail_callback:
                        detail_callback(
                            "finish_folder",
                            {
                                "root": root_directory,
                                "folder": series_name,
                                "skipped": True,
                            },
                        )
                    continue
                cleaned = series_data
            else:
                series_data = scan_series(
                    series_directory,
                    tmdb_series=tmdb_series,
                    jellyfin_data=jellyfin_data,
                    manual_jellyfin_id=existing_jellyfin_id,
                    existing_series_data=existing_series,
                    force_refresh=series_force_refresh,
                    cleanup=cleanup,
                    single_item_refresh=single_item_refresh,
                    detail_callback=detail_callback,
                )
                if is_locked:
                    series_data["metadata"]["locked_metadata"] = True

                cleaned = clean_series_data(series_data)
                if not cleaned:
                    if detail_callback:
                        detail_callback(
                            "finish_folder",
                            {
                                "root": root_directory,
                                "folder": series_name,
                                "skipped": True,
                            },
                        )
                    continue

            # Identify if this series matches something already in our library
            match_key = None
            if series_name in library:
                match_key = series_name

            if match_key:
                # Merge into existing entry
                existing = library[match_key]
                logger.info(
                    f"Merging '{series_name}' into existing entry '{match_key}'"
                )

                if library_type == "movie":
                    pass  # We just keep existing movie for now, no complex merge
                else:
                    for season_name, season_data in cleaned.get("seasons", {}).items():
                        if season_name in existing.get("seasons", {}):
                            existing_episodes = existing["seasons"][season_name][
                                "episodes"
                            ]
                            _merge_season_episodes(
                                existing_episodes, season_data["episodes"], season_name
                            )
                            existing_episodes.sort(
                                key=lambda x: natural_sort_key(x["name"])
                            )
                        else:
                            existing.setdefault("seasons", {})[season_name] = (
                                season_data
                            )
            else:
                library[series_name] = cleaned

            if detail_callback:
                detail_callback(
                    "finish_folder",
                    {"root": root_directory, "folder": series_name, "skipped": False},
                )

            if callback:
                callback(library)

    if not cleanup and existing_library:
        for old_series_name, old_series_data in existing_library.items():
            if old_series_name not in library:
                logger.info(
                    f"Preserving missing folder '{old_series_name}' (non-destructive)"
                )
                library[old_series_name] = old_series_data

    return library


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
) -> Dict[str, Any] | None:
    folder_name = movie_directory.name
    title, year = _parse_movie_folder(folder_name)

    # Find the first video file
    video_file = None
    for file in movie_directory.rglob("*"):
        if file.is_file() and file.suffix.lower() in VIDEO_EXTENSIONS:
            video_file = file
            break

    if not video_file:
        return None

    if detail_callback:
        detail_callback(
            "start_file", {"file": str(video_file), "folder": movie_directory.name}
        )

    try:
        ctime = os.path.getctime(video_file)
    except OSError:
        ctime = 0

    video_path = str(video_file.absolute())
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
        if existing_tmdb_id and not tmdb_movie:
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
        _apply_tmdb_movie_data(movie_metadata, tmdb_movie, existing_movie_data)

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
    }

    if existing_movie_data:
        movie_data["video_codec"] = existing_movie_data.get("video_codec")
        movie_data["resolution"] = existing_movie_data.get("resolution")
        movie_data["audio_tracks"] = existing_movie_data.get("audio_tracks")
        movie_data["subtitle_tracks"] = existing_movie_data.get("subtitle_tracks")

    if detail_callback:
        detail_callback(
            "finish_file", {"file": str(video_file), "folder": movie_directory.name}
        )

    return movie_data


def scan_series(
    series_directory: Path,
    tmdb_series: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, dict] | None = None,
    manual_jellyfin_id: str | None = None,
    existing_series_data: Dict[str, Any] | None = None,
    force_refresh: bool = False,
    cleanup: bool = False,
    single_item_refresh: bool = False,
    detail_callback: Any = None,
) -> Dict[str, Any]:
    """
    Scans a single series directory and fetches metadata from TMDB.
    """
    # Check for files outside of season or specials/extras folders
    outside_file_paths = []
    nested_too_deeply = []
    for file_path in series_directory.rglob("*"):
        if file_path.is_file() and _is_video_file(file_path):
            try:
                rel_path = file_path.relative_to(series_directory)
                parts = rel_path.parts
                if len(parts) == 1:
                    outside_file_paths.append(file_path)
                else:
                    first_dir = parts[0]
                    first_dir_lower = first_dir.lower()
                    is_valid = (
                        "season" in first_dir_lower
                        or "special" in first_dir_lower
                        or "extra" in first_dir_lower
                        or "featurette" in first_dir_lower
                        or "bonus" in first_dir_lower
                        or "shorts" in first_dir_lower
                        or bool(re.search(r"\d+", first_dir))
                    )
                    if not is_valid:
                        outside_file_paths.append(file_path)
                    elif len(parts) > 2:
                        nested_too_deeply.append(file_path)
            except Exception:
                pass

    if outside_file_paths:
        logger.warning(
            f"Series '{series_directory.name}' has {len(outside_file_paths)} video file(s) "
            f"outside of season or specials/extras folders. "
            f"Example: '{outside_file_paths[0].name}'"
        )

    if nested_too_deeply:
        logger.warning(
            f"Series '{series_directory.name}' has {len(nested_too_deeply)} video file(s) "
            f"nested too deeply inside season folders. These files will not be indexed. "
            f"Example: '{nested_too_deeply[0].relative_to(series_directory)}'"
        )

    series_data, is_early_return, tmdb_series, existing_episodes_by_path = (
        _process_series_metadata(
            series_directory,
            tmdb_series,
            jellyfin_data,
            manual_jellyfin_id,
            existing_series_data,
            force_refresh,
            cleanup,
            single_item_refresh,
        )
    )
    if is_early_return:
        return series_data

    for season_directory in series_directory.iterdir():
        if not season_directory.is_dir() or season_directory.name.startswith("."):
            continue

        season_name, season_index, season_metadata, tmdb_episodes = (
            _process_season_metadata(
                season_directory,
                series_data,
                existing_series_data,
                existing_episodes_by_path,
                single_item_refresh,
            )
        )

        if detail_callback:
            detail_callback(
                "start_season",
                {"folder": series_directory.name, "season": season_name},
            )

        series_data["seasons"][season_name] = {
            "metadata": season_metadata,
            "episodes": [],
            "_tmdb_episodes": tmdb_episodes,
        }

        for episode_file in season_directory.iterdir():
            if episode_file.is_dir() and not episode_file.name.startswith("."):
                logger.warning(
                    f"Ignoring subdirectory in season folder: '{episode_file.relative_to(series_directory)}'"
                )
                continue

            if (
                episode_file.is_file()
                and episode_file.suffix.lower() in VIDEO_EXTENSIONS
            ):
                if detail_callback:
                    detail_callback(
                        "start_file",
                        {
                            "file": str(episode_file),
                            "folder": series_directory.name,
                            "season": season_name,
                        },
                    )
                episode_record = _process_episode_file(
                    episode_file,
                    season_name,
                    series_directory,
                    series_data,
                    season_metadata,
                    tmdb_episodes,
                    tmdb_series,
                    jellyfin_data,
                    existing_episodes_by_path,
                )
                series_data["seasons"][season_name]["episodes"].append(episode_record)
                if detail_callback:
                    detail_callback(
                        "finish_file",
                        {
                            "file": str(episode_file),
                            "folder": series_directory.name,
                            "season": season_name,
                        },
                    )

        if detail_callback:
            detail_callback(
                "finish_season",
                {"folder": series_directory.name, "season": season_name},
            )

    if not cleanup and existing_series_data:
        for old_season_name, old_season_data in existing_series_data.get(
            "seasons", {}
        ).items():
            if old_season_name not in series_data["seasons"]:
                logger.info(
                    f"Preserving missing season folder '{old_season_name}' (non-destructive)"
                )
                series_data["seasons"][old_season_name] = old_season_data
            else:
                found_paths = {
                    episode["path"]
                    for episode in series_data["seasons"][old_season_name]["episodes"]
                }
                for old_episode in old_season_data.get("episodes", []):
                    if old_episode["path"] not in found_paths:
                        logger.info(
                            f"Preserving missing episode file '{old_episode['name']}' (non-destructive)"
                        )
                        series_data["seasons"][old_season_name]["episodes"].append(
                            old_episode
                        )
                series_data["seasons"][old_season_name]["episodes"].sort(
                    key=lambda x: natural_sort_key(x["name"])
                )

    logger.info(
        f"Completed scan for series '{series_directory.name}', found {len(series_data['seasons'])} seasons."
    )
    return series_data
