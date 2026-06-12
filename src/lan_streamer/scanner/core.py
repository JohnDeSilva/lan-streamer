import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

from lan_streamer.db import natural_sort_key
from lan_streamer.scanner.proxy import tmdb_client, clean_series_data, scanner_proxy
from lan_streamer.scanner.file_property_scanner import (
    get_detailed_file_info,
    get_stub_file_info,
)
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


def get_version_score_key(version: Dict[str, Any]) -> tuple:
    res = version.get("resolution") or ""
    res_score = 0
    if "x" in res:
        try:
            w, h = res.split("x")
            res_score = int(w) * int(h)
        except Exception:
            pass

    bit_rate = version.get("bit_rate") or 0
    try:
        bit_rate = int(bit_rate)
    except Exception:
        bit_rate = 0

    video_codec = (version.get("video_codec") or "").lower()
    video_ranks = {"av1": 4, "hevc": 3, "h265": 3, "h264": 2, "avc": 2}
    video_codec_score = 1
    for k, v in video_ranks.items():
        if k in video_codec:
            video_codec_score = max(video_codec_score, v)

    audio_tracks = version.get("audio_tracks") or []
    audio_ranks = {
        "truehd": 6,
        "atmos": 6,
        "dts-hd": 5,
        "dts": 4,
        "eac3": 3,
        "ac3": 3,
        "aac": 2,
        "opus": 2,
        "mp3": 1,
    }
    audio_codec_score = 0
    for track in audio_tracks:
        codec = (track.get("codec") or "").lower()
        track_score = 1
        for k, v in audio_ranks.items():
            if k in codec:
                track_score = max(track_score, v)
        audio_codec_score = max(audio_codec_score, track_score)

    return (res_score, bit_rate, video_codec_score, audio_codec_score)


def choose_active_version(
    versions: List[Dict[str, Any]], default_path: Optional[str] = None
) -> Dict[str, Any]:
    if not versions:
        return {}
    if default_path:
        for v in versions:
            if v.get("path") == default_path:
                return v
    sorted_versions = sorted(versions, key=get_version_score_key, reverse=True)
    return sorted_versions[0]


class LibraryDict(dict[str, Any]):
    """
    Custom dictionary subclass to hold library contents and track
    any root directories that were unavailable during scanning.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.unavailable_directories: List[str] = []


def _has_season_subdirs(directory: Path) -> bool:
    """
    Returns True if *directory* contains at least one subdirectory whose name
    looks like a season folder (contains 'season', 'special', 'extra',
    'featurette', 'bonus', 'shorts', or any digit sequence). This allows
    series folders with no local video files to still be indexed so that
    TMDB placeholder episodes can be seeded into the database.
    """
    try:
        for child in directory.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                name_lower = child.name.lower()
                if (
                    "season" in name_lower
                    or "special" in name_lower
                    or "extra" in name_lower
                    or "featurette" in name_lower
                    or "bonus" in name_lower
                    or "shorts" in name_lower
                    or bool(re.search(r"\d+", child.name))
                ):
                    return True
    except PermissionError:
        pass
    return False


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
    show_future_episodes: bool = True,
    offline: bool = False,
    season_callback: Any = None,
    movie_callback: Any = None,
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

        # Sort series directories by mtime (newest first).
        # Include a directory if it contains video files OR season-style subdirs,
        # so series with only TMDB placeholder episodes are still indexed.
        series_dirs = sorted(
            [
                directory
                for directory in root_path.iterdir()
                if directory.is_dir()
                and not directory.name.startswith(".")
                and (has_video_files(directory) or _has_season_subdirs(directory))
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
                (force_refresh or single_item_refresh or not has_meta)
                if not is_locked
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
                    offline=offline,
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
                if movie_callback and cleaned:
                    movie_callback(series_name, cleaned)
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
                    show_future_episodes=show_future_episodes,
                    offline=offline,
                    season_callback=season_callback,
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
    offline: bool = False,
) -> Dict[str, Any] | None:
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

    video_files = []
    for file in movie_directory.rglob("*"):
        if file.is_file() and file.suffix.lower() in VIDEO_EXTENSIONS:
            video_files.append(file)

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
                movie_metadata, tmdb_movie, existing_movie_data, movie_offline
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


def _has_season_files_changed(
    season_dir: Path, existing_season_data: Dict[str, Any]
) -> bool:
    """
    Checks if files have been added, modified, or removed in a season folder
    by comparing local paths/sizes to the pre-existing season metadata.
    """
    existing_episodes = existing_season_data.get("episodes", [])
    existing_by_path = {ep["path"]: ep for ep in existing_episodes if ep.get("path")}

    try:
        disk_files = [
            f
            for f in season_dir.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        ]
    except PermissionError, FileNotFoundError:
        return True

    # Filter out episodes without paths (e.g., TMDb future/placeholder episodes)
    existing_phys_eps = [ep for ep in existing_episodes if ep.get("path")]
    if len(disk_files) != len(existing_phys_eps):
        return True

    for disk_file in disk_files:
        path_str = str(disk_file.absolute())
        if path_str not in existing_by_path:
            return True

        # Check for size difference
        existing_ep = existing_by_path[path_str]
        sizes = [existing_ep.get("size_bytes")]
        if existing_ep.get("versions"):
            for v in existing_ep["versions"]:
                if v.get("path") == path_str:
                    sizes.append(v.get("size_bytes"))
        # Filter out None values
        sizes = [s for s in sizes if s is not None]

        try:
            disk_size = disk_file.stat().st_size
        except Exception:
            return True

        if not any(s == disk_size for s in sizes):
            return True

    return False


def _has_movie_files_changed(
    movie_dir: Path, existing_movie_data: Dict[str, Any]
) -> bool:
    """
    Checks if the files for a movie have changed in its folder.
    """
    try:
        disk_files = [
            f
            for f in movie_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        ]
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
    show_future_episodes: bool = True,
    offline: bool = False,
    season_callback: Any = None,
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

    (
        series_data,
        is_early_return,
        tmdb_series,
        existing_episodes_by_path,
        force_refresh,
    ) = _process_series_metadata(
        series_directory,
        tmdb_series,
        jellyfin_data,
        manual_jellyfin_id,
        existing_series_data,
        force_refresh,
        cleanup,
        single_item_refresh,
        offline=offline,
    )
    if is_early_return:
        if not show_future_episodes:
            import datetime

            today_str = datetime.date.today().isoformat()
            for season_name, season_data in list(
                series_data.get("seasons", {}).items()
            ):
                filtered_episodes = []
                for ep in season_data.get("episodes", []):
                    if ep.get("path") is None:
                        air_date = ep.get("air_date") or ""
                        if not air_date or air_date > today_str:
                            continue
                    filtered_episodes.append(ep)
                season_data["episodes"] = filtered_episodes
        return series_data

    for season_directory in series_directory.iterdir():
        if not season_directory.is_dir() or season_directory.name.startswith("."):
            continue

        season_name = season_directory.name
        is_season_changed = True
        if existing_series_data and season_name in existing_series_data.get(
            "seasons", {}
        ):
            if offline:
                is_season_changed = _has_season_files_changed(
                    season_directory, existing_series_data["seasons"][season_name]
                )
            else:
                is_season_changed = existing_series_data["seasons"][season_name].get(
                    "_changed", True
                )

        season_offline = offline or not is_season_changed

        season_name, season_index, season_metadata, tmdb_episodes = (
            _process_season_metadata(
                season_directory,
                series_data,
                existing_series_data,
                existing_episodes_by_path,
                force_refresh,
                single_item_refresh,
                offline=season_offline,
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
            "_changed": is_season_changed,
        }

        scanned_episodes = []
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
                    existing_series_data,
                    offline=season_offline,
                )
                scanned_episodes.append(episode_record)
                if detail_callback:
                    detail_callback(
                        "finish_file",
                        {
                            "file": str(episode_file),
                            "folder": series_directory.name,
                            "season": season_name,
                        },
                    )

        # Group by tmdb_number (or name if tmdb_number is None)
        grouped_episodes = {}
        for ep in scanned_episodes:
            key = ep.get("tmdb_number")
            if key is None:
                key = ep.get("name")
            if key not in grouped_episodes:
                grouped_episodes[key] = []
            grouped_episodes[key].append(ep)

        for key, ep_list in grouped_episodes.items():
            versions = []
            for ep in ep_list:
                path_str = ep["path"]
                existing_v = None
                if existing_series_data:
                    existing_season = existing_series_data.get("seasons", {}).get(
                        season_name, {}
                    )
                    for ex_ep in existing_season.get("episodes", []):
                        match = False
                        if ep.get("tmdb_number") is not None and ex_ep.get(
                            "tmdb_number"
                        ) == ep.get("tmdb_number"):
                            match = True
                        elif ep.get("name") == ex_ep.get("name"):
                            match = True
                        if match and ex_ep.get("versions"):
                            for ev in ex_ep["versions"]:
                                if ev.get("path") == path_str:
                                    existing_v = ev
                                    break
                        if existing_v:
                            break
                if existing_v and not force_refresh:
                    versions.append(existing_v)
                else:
                    if season_offline:
                        versions.append(get_stub_file_info(path_str))
                    else:
                        versions.append(get_detailed_file_info(path_str))

            default_path = None
            if existing_series_data:
                existing_season = existing_series_data.get("seasons", {}).get(
                    season_name, {}
                )
                for ex_ep in existing_season.get("episodes", []):
                    match = False
                    if ep_list[0].get("tmdb_number") is not None and ex_ep.get(
                        "tmdb_number"
                    ) == ep_list[0].get("tmdb_number"):
                        match = True
                    elif ep_list[0].get("name") == ex_ep.get("name"):
                        match = True
                    if match:
                        default_path = ex_ep.get("default_path")
                        break

            active_version = choose_active_version(versions, default_path)

            base_ep = ep_list[0].copy()
            base_ep["path"] = active_version.get("path")
            base_ep["video_codec"] = active_version.get("video_codec")
            base_ep["resolution"] = active_version.get("resolution")
            base_ep["bit_rate"] = active_version.get("bit_rate")
            base_ep["audio_tracks"] = active_version.get("audio_tracks")
            base_ep["subtitle_tracks"] = active_version.get("subtitle_tracks")
            base_ep["versions"] = versions
            base_ep["default_path"] = default_path

            series_data["seasons"][season_name]["episodes"].append(base_ep)

        # Add placeholders for remaining episodes in TMDB list that are not found locally
        local_numbers = {
            ep["tmdb_number"]
            for ep in series_data["seasons"][season_name]["episodes"]
            if ep.get("tmdb_number") is not None
        }

        if season_name.lower() == "specials":
            s_idx = 0
        else:
            m = re.search(r"\d+", season_name)
            s_idx = int(m.group()) if m else 1

        import datetime

        today_str = datetime.date.today().isoformat()

        for tmdb_ep in tmdb_episodes:
            ep_num = tmdb_ep.get("episode_number")
            if ep_num is not None and ep_num not in local_numbers:
                if not show_future_episodes:
                    air_date = tmdb_ep.get("air_date") or ""
                    if not air_date or air_date > today_str:
                        continue
                ep_name = tmdb_ep.get("name") or "TBA"
                formatted_name = f"S{s_idx:02d}E{ep_num:02d} - {ep_name}"
                mal_id = season_metadata.get("myanimelist_id")
                episode_record = {
                    "name": formatted_name,
                    "path": None,
                    "tmdb_identifier": str(tmdb_ep.get("id", "")),
                    "tmdb_episode_identifier": str(tmdb_ep.get("id", "")),
                    "tmdb_name": tmdb_ep.get("name", ""),
                    "tmdb_number": ep_num,
                    "air_date": tmdb_ep.get("air_date") or "",
                    "runtime": tmdb_ep.get("runtime") or 0,
                    "jellyfin_id": "",
                    "watched": False,
                    "date_added": 0,
                }
                if mal_id:
                    episode_record["myanimelist_anime_id"] = mal_id
                    episode_record["myanimelist_episode_number"] = ep_num
                series_data["seasons"][season_name]["episodes"].append(episode_record)

        if season_callback:
            series_name_val = (
                series_data.get("metadata", {}).get("name") or series_directory.name
            )
            clean_season_data = {
                "metadata": season_metadata,
                "episodes": series_data["seasons"][season_name]["episodes"],
            }
            season_callback(
                series_name_val, series_data, season_name, clean_season_data
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
                    if episode.get("path")
                }
                found_numbers = {
                    episode["tmdb_number"]
                    for episode in series_data["seasons"][old_season_name]["episodes"]
                    if episode.get("tmdb_number") is not None
                }
                for old_episode in old_season_data.get("episodes", []):
                    old_path = old_episode.get("path")
                    old_num = old_episode.get("tmdb_number")
                    if old_path:
                        if old_path not in found_paths:
                            if Path(old_path).exists():
                                logger.info(
                                    f"Preserving missing episode file '{old_episode['name']}' (non-destructive)"
                                )
                                series_data["seasons"][old_season_name][
                                    "episodes"
                                ].append(old_episode)
                    else:
                        if old_num not in found_numbers:
                            # Keep missing/placeholder episodes
                            if not show_future_episodes:
                                air_date = old_episode.get("air_date") or ""
                                if not air_date or air_date > today_str:
                                    continue
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
