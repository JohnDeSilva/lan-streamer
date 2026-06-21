"""
TV/series scanning functions — scan a single series directory and detect file changes.
"""

import datetime
import logging
import re
from pathlib import Path
from typing import Dict, Any

from lan_streamer.db.utils import natural_sort_key
from lan_streamer.scanner.file_property_scanner import (
    get_detailed_file_info,
    get_stub_file_info,
)
from lan_streamer.services.metadata_tv import (
    _process_episode_file,
    _process_season_metadata,
    _process_series_metadata,
)
from lan_streamer.services.metadata_common import _merge_season_episodes  # noqa: F401
from lan_streamer.services.file_discovery import detect_tv_file_changes
from lan_streamer.scanner.parser import VIDEO_EXTENSIONS

logger = logging.getLogger("lan_streamer.scanner")

# Computed once per process start; accurate enough for a single scan run.
_TODAY_STR = datetime.date.today().isoformat()


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
    metadata_only: bool = False,
) -> Dict[str, Any]:
    """
    Scans a single series directory and fetches metadata from TMDB.
    """
    # Import here to avoid circular dependency with core.choose_active_version
    from lan_streamer.scanner.versioning import choose_active_version

    # Check for files outside of season or specials/extras folders
    outside_file_paths = []
    nested_too_deeply = []
    if not metadata_only:
        from lan_streamer.scanner.parser import find_video_files

        for file_path in find_video_files(series_directory):
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
        metadata_only=metadata_only,
    )
    if is_early_return:
        if not show_future_episodes:
            today_str = _TODAY_STR
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

    seasons_to_process = []
    if metadata_only:
        if existing_series_data and existing_series_data.get("seasons"):
            for season_name, existing_season in existing_series_data["seasons"].items():
                seasons_to_process.append((season_name, True, existing_season))
    else:
        for season_directory in series_directory.iterdir():
            if not season_directory.is_dir() or season_directory.name.startswith("."):
                continue

            season_name = season_directory.name
            is_season_changed = True
            existing_season = None
            if existing_series_data and season_name in existing_series_data.get(
                "seasons", {}
            ):
                existing_season = existing_series_data["seasons"][season_name]
                if offline:
                    is_season_changed = detect_tv_file_changes(
                        season_directory, existing_season
                    )
                else:
                    is_season_changed = existing_season.get("_changed", True)
            seasons_to_process.append((season_name, is_season_changed, existing_season))

    for season_name, is_season_changed, existing_season in seasons_to_process:
        season_directory = series_directory / season_name
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
                metadata_only=metadata_only,
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
        if metadata_only:
            if existing_season:
                for ep in existing_season.get("episodes", []):
                    ep_path = ep.get("path")
                    if not ep_path:
                        continue
                    episode_file = Path(ep_path)
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
                        metadata_only=True,
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
        else:
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

        # Cache the existing season dict once; looked up twice below (versions + default_path).
        existing_season_eps: list = []
        if existing_series_data:
            existing_season_eps = (
                existing_series_data.get("seasons", {})
                .get(season_name, {})
                .get("episodes", [])
            )

        for key, ep_list in grouped_episodes.items():
            versions = []
            for ep in ep_list:
                path_str = ep["path"]
                existing_v = None
                for ex_ep in existing_season_eps:
                    match = (
                        ep.get("tmdb_number") is not None
                        and ex_ep.get("tmdb_number") == ep.get("tmdb_number")
                    ) or ep.get("name") == ex_ep.get("name")
                    if match and ex_ep.get("versions"):
                        for ev in ex_ep["versions"]:
                            if ev.get("path") == path_str:
                                existing_v = ev
                                break
                    if existing_v:
                        break
                if existing_v and (not force_refresh or metadata_only):
                    versions.append(existing_v)
                else:
                    if season_offline or metadata_only:
                        versions.append(get_stub_file_info(path_str))
                    else:
                        versions.append(get_detailed_file_info(path_str))

            default_path = None
            for ex_ep in existing_season_eps:
                match = (
                    ep_list[0].get("tmdb_number") is not None
                    and ex_ep.get("tmdb_number") == ep_list[0].get("tmdb_number")
                ) or ep_list[0].get("name") == ex_ep.get("name")
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

        for tmdb_ep in tmdb_episodes:
            ep_num = tmdb_ep.get("episode_number")
            if ep_num is not None and ep_num not in local_numbers:
                if not show_future_episodes:
                    air_date = tmdb_ep.get("air_date") or ""
                    if not air_date or air_date > _TODAY_STR:
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
                            if metadata_only or Path(old_path).exists():
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
                                if not air_date or air_date > _TODAY_STR:
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
