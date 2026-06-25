"""
TV/series scanning functions — scan a single series directory and detect file changes.
"""

import datetime
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any, Dict

from lan_streamer.db.utils import natural_sort_key
from lan_streamer.scanner.file_property_scanner import (
    get_detailed_file_info,
    get_stub_file_info,
)
from lan_streamer.scanner.parser import VIDEO_EXTENSIONS, _parse_episode_number
from lan_streamer.services.metadata_episode import (
    _process_episode_file,
    _process_season_metadata,
)
from lan_streamer.services.metadata_series import (
    _process_series_metadata,
)

logger = logging.getLogger("lan_streamer.scanner")

# Computed once per process start; accurate enough for a single scan run.
_TODAY_STR = datetime.date.today().isoformat()


@dataclass
class _EpisodeScanContext:
    """Context passed through to _process_episode_file during season scanning."""

    series_directory: Path
    series_data: Dict[str, Any]
    season_metadata: Dict[str, Any]
    tmdb_episodes: list[Dict[str, Any]]
    tmdb_series: Dict[str, Any] | None
    jellyfin_data: Dict[str, dict] | None
    existing_episodes_by_path: Dict[str, Any]
    existing_series_data: Dict[str, Any] | None
    season_offline: bool
    detail_callback: Callable | None = None


def _validate_series_file_layout(
    series_directory: Path,
    metadata_only: bool,
) -> None:
    """Warn about video files outside season folders or nested too deeply."""
    # Import here to avoid circular dependency with parser.find_video_files
    from lan_streamer.scanner.parser import find_video_files

    outside_file_paths: list[Path] = []
    nested_too_deeply: list[Path] = []
    if not metadata_only:
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


def _check_series_directory_mtime_unchanged(
    series_directory: Path,
    existing_series_data: Dict[str, Any] | None,
) -> bool:
    """Return True if the series directory mtime matches the cached DB value.

    A matching mtime means no season sub-directories were added or removed since
    the last scan, so ``iterdir()`` on the series directory can be skipped.
    Files *within* existing seasons may still have changed — the caller must
    check each season's individual mtime separately.
    """
    if not existing_series_data or not existing_series_data.get("seasons"):
        return False

    from lan_streamer import db

    series_directory_path = str(series_directory.absolute())
    try:
        current_series_mtime = series_directory.stat().st_mtime
    except OSError:
        return False

    cached_series_mtime = db.get_directory_mtime(series_directory_path)
    return (
        cached_series_mtime is not None and current_series_mtime == cached_series_mtime
    )


def _check_single_season_changed(
    season_directory: Path,
    existing_season: Dict[str, Any],
    offline: bool,
) -> bool:
    """Return True if a season directory has changed since the last scan.

    Checks the cached directory mtime first.  If the mtime matches the cached
    value the season is definitively unchanged regardless of any ``_changed``
    flag left by a previous pass.  When the mtime has changed or is unknown,
    falls back to file-size comparison and then respects the online ``_changed``
    flag (which signals pending metadata refresh).
    """
    from lan_streamer import db

    try:
        current_mtime = season_directory.stat().st_mtime
    except OSError:
        current_mtime = None

    cached_mtime = db.get_directory_mtime(str(season_directory.absolute()))
    if cached_mtime is not None and current_mtime == cached_mtime:
        # Mtime match: season directory contents are definitively unchanged.
        return False

    # Mtime changed or unknown: check file sizes and respect the _changed flag.
    from lan_streamer.services.file_discovery import detect_tv_file_changes

    is_changed = detect_tv_file_changes(season_directory, existing_season)
    if not offline:
        is_changed = is_changed or existing_season.get("_changed", True)
    return is_changed


def _discover_seasons_to_process(
    series_directory: Path,
    existing_series_data: Dict[str, Any] | None,
    metadata_only: bool,
    offline: bool,
) -> list[tuple[str, bool, Dict[str, Any] | None]]:
    """Build list of (season_name, is_changed, existing_season) tuples.

    When the series directory mtime matches the cached DB value, ``iterdir()``
    on the series directory is skipped entirely (one fewer network round-trip
    per series on SMB/NFS) and the season list is derived from existing data.
    Each season's individual mtime is still checked so that file-level changes
    inside an existing season (which only update the *season* directory mtime,
    not the parent series directory mtime) are still detected.
    """
    seasons_to_process: list[tuple[str, bool, Dict[str, Any] | None]] = []
    if metadata_only:
        if existing_series_data and existing_series_data.get("seasons"):
            for season_name, existing_season in existing_series_data["seasons"].items():
                is_season_changed = existing_season.get("_changed", True)
                seasons_to_process.append(
                    (season_name, is_season_changed, existing_season)
                )
        return seasons_to_process

    # Check whether the series directory itself has changed.  A matching mtime
    # means no season folders were added or removed, so we can skip iterdir()
    # and read season names directly from the existing database record.
    series_directory_unchanged = _check_series_directory_mtime_unchanged(
        series_directory, existing_series_data
    )

    if series_directory_unchanged and existing_series_data:
        logger.debug(
            f"Series '{series_directory.name}' directory mtime unchanged; "
            "skipping iterdir(), reading season list from existing data."
        )
        for season_name, existing_season in existing_series_data["seasons"].items():
            season_directory = series_directory / season_name
            is_season_changed = _check_single_season_changed(
                season_directory, existing_season, offline
            )
            seasons_to_process.append((season_name, is_season_changed, existing_season))
        return seasons_to_process

    # Series directory changed (or no cached mtime): walk the filesystem.
    for season_directory in series_directory.iterdir():
        if not season_directory.is_dir() or season_directory.name.startswith("."):
            continue

        season_name = season_directory.name
        existing_season: Dict[str, Any] | None = None
        if existing_series_data and season_name in existing_series_data.get(
            "seasons", {}
        ):
            existing_season = existing_series_data["seasons"][season_name]
            is_season_changed = _check_single_season_changed(
                season_directory, existing_season, offline
            )
        else:
            is_season_changed = True

        seasons_to_process.append((season_name, is_season_changed, existing_season))

    return seasons_to_process


def _scan_season_episodes(
    season_directory: Path,
    season_name: str,
    existing_season: Dict[str, Any] | None,
    metadata_only: bool,
    context: _EpisodeScanContext,
) -> list[Dict[str, Any]]:
    """Scan all episode files in a season and return their records."""
    scanned_episodes: list[Dict[str, Any]] = []
    if metadata_only:
        if existing_season:
            for ep in existing_season.get("episodes", []):
                ep_path = ep.get("path")
                if not ep_path:
                    continue
                episode_file = Path(ep_path)
                if context.detail_callback:
                    context.detail_callback(
                        "start_file",
                        {
                            "file": str(episode_file),
                            "folder": context.series_directory.name,
                            "season": season_name,
                        },
                    )
                episode_record = _process_episode_file(
                    episode_file,
                    season_name,
                    context.series_directory,
                    context.series_data,
                    context.season_metadata,
                    context.tmdb_episodes,
                    context.tmdb_series,
                    context.jellyfin_data,
                    context.existing_episodes_by_path,
                    context.existing_series_data,
                    offline=context.season_offline,
                    metadata_only=True,
                )
                scanned_episodes.append(episode_record)
                if context.detail_callback:
                    context.detail_callback(
                        "finish_file",
                        {
                            "file": str(episode_file),
                            "folder": context.series_directory.name,
                            "season": season_name,
                        },
                    )
    else:
        for episode_file in season_directory.iterdir():
            if episode_file.is_dir() and not episode_file.name.startswith("."):
                logger.warning(
                    f"Ignoring subdirectory in season folder: '{episode_file.relative_to(context.series_directory)}'"
                )
                continue

            if (
                episode_file.is_file()
                and episode_file.suffix.lower() in VIDEO_EXTENSIONS
            ):
                if context.detail_callback:
                    context.detail_callback(
                        "start_file",
                        {
                            "file": str(episode_file),
                            "folder": context.series_directory.name,
                            "season": season_name,
                        },
                    )
                episode_record = _process_episode_file(
                    episode_file,
                    season_name,
                    context.series_directory,
                    context.series_data,
                    context.season_metadata,
                    context.tmdb_episodes,
                    context.tmdb_series,
                    context.jellyfin_data,
                    context.existing_episodes_by_path,
                    context.existing_series_data,
                    offline=context.season_offline,
                )
                scanned_episodes.append(episode_record)
                if context.detail_callback:
                    context.detail_callback(
                        "finish_file",
                        {
                            "file": str(episode_file),
                            "folder": context.series_directory.name,
                            "season": season_name,
                        },
                    )
    return scanned_episodes


def _group_and_resolve_episode_versions(
    scanned_episodes: list[Dict[str, Any]],
    existing_season_episodes: list[Dict[str, Any]],
    season_offline: bool,
    force_refresh: bool,
    metadata_only: bool,
) -> list[Dict[str, Any]]:
    """Group episodes by identity, resolve versions, return finalised records."""
    # Import here to avoid circular dependency with core.choose_active_version
    from lan_streamer.scanner.versioning import choose_active_version

    # Group by tmdb_number, parsed episode number, or name as last resort.
    grouped_episodes: Dict[Any, list] = {}
    for ep in scanned_episodes:
        key: Any = ep.get("tmdb_number")
        if key is None:
            parsed = _parse_episode_number(ep.get("name", ""))
            if parsed:
                key = parsed
            else:
                key = ep.get("name")
        if key not in grouped_episodes:
            grouped_episodes[key] = []
        grouped_episodes[key].append(ep)

    finalised_episodes: list[Dict[str, Any]] = []
    for key, ep_list in grouped_episodes.items():
        versions: list[Dict[str, Any]] = []
        incoming_paths = {ep["path"] for ep in ep_list if ep.get("path")}
        for ep in ep_list:
            path_str = ep["path"]
            existing_v = None
            for ex_ep in existing_season_episodes:
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
            use_existing = False
            if existing_v and (not force_refresh or metadata_only):
                # If we are online, but the existing version was only a stub (missing technical info),
                # we should re-scan it to fetch full media details.
                is_stub = (
                    existing_v.get("video_codec") == "Unknown"
                    or existing_v.get("resolution") == "Unknown"
                )
                if not (is_stub and not season_offline and not metadata_only):
                    use_existing = True

            if use_existing and existing_v is not None:
                versions.append(existing_v)
            else:
                if season_offline or metadata_only:
                    versions.append(get_stub_file_info(path_str))
                else:
                    versions.append(get_detailed_file_info(path_str))

        for ex_ep in existing_season_episodes:
            match = (
                ep_list[0].get("tmdb_number") is not None
                and ex_ep.get("tmdb_number") == ep_list[0].get("tmdb_number")
            ) or ep_list[0].get("name") == ex_ep.get("name")
            if match and ex_ep.get("versions"):
                for ev in ex_ep["versions"]:
                    ev_path = ev.get("path")
                    if ev_path and ev_path not in incoming_paths:
                        versions.append(ev)

        default_path = None
        for ex_ep in existing_season_episodes:
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

        finalised_episodes.append(base_ep)

    return finalised_episodes


def _create_tmdb_placeholder_episodes(
    tmdb_episodes: list[Dict[str, Any]],
    local_episodes: list[Dict[str, Any]],
    season_name: str,
    season_metadata: Dict[str, Any],
    show_future_episodes: bool = True,
) -> list[Dict[str, Any]]:
    """Create placeholder records for TMDB episodes not found locally."""
    local_numbers = {
        ep["tmdb_number"] for ep in local_episodes if ep.get("tmdb_number") is not None
    }

    if season_name.lower() == "specials":
        s_idx = 0
    else:
        m = re.search(r"\d+", season_name)
        s_idx = int(m.group()) if m else 1

    placeholders: list[Dict[str, Any]] = []
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
            episode_record: Dict[str, Any] = {
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
            placeholders.append(episode_record)

    return placeholders


def _preserve_existing_episode_data(
    series_data: Dict[str, Any],
    existing_series_data: Dict[str, Any] | None,
    cleanup: bool,
    metadata_only: bool,
    show_future_episodes: bool = True,
) -> None:
    """Preserve missing seasons/episodes from previous scans (non-destructive)."""
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
                found_paths = set()
                for episode in series_data["seasons"][old_season_name]["episodes"]:
                    if episode.get("path"):
                        found_paths.add(episode["path"])
                    for version in episode.get("versions", []):
                        if version.get("path"):
                            found_paths.add(version["path"])
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


def _filter_future_episodes(series_data: Dict[str, Any]) -> None:
    """Remove future-dated placeholder episodes from series data in-place."""
    today_str = _TODAY_STR
    for season_name, season_data in list(series_data.get("seasons", {}).items()):
        filtered_episodes = []
        for ep in season_data.get("episodes", []):
            if ep.get("path") is None:
                air_date = ep.get("air_date") or ""
                if not air_date or air_date > today_str:
                    continue
            filtered_episodes.append(ep)
        season_data["episodes"] = filtered_episodes


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
    database_queue: Any | None = None,
) -> Dict[str, Any]:
    """Scans a single series directory and fetches metadata from TMDB."""

    # Phase 1: Validate file layout
    _validate_series_file_layout(series_directory, metadata_only)

    # Phase 2: Bootstrap series metadata
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
            _filter_future_episodes(series_data)
        return series_data

    # Phase 3: Discover seasons
    seasons_to_process = _discover_seasons_to_process(
        series_directory,
        existing_series_data,
        metadata_only,
        offline,
    )

    # Phase 4: Per-season loop
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

        try:
            current_mtime = season_directory.stat().st_mtime
        except Exception:
            current_mtime = None
        season_metadata["season_directory_path"] = str(season_directory.absolute())
        season_metadata["last_scanned_mtime"] = current_mtime

        series_data["seasons"][season_name] = {
            "metadata": season_metadata,
            "episodes": [],
            "_tmdb_episodes": tmdb_episodes,
            "_changed": is_season_changed,
        }

        # Build scanning context
        scan_context = _EpisodeScanContext(
            series_directory=series_directory,
            series_data=series_data,
            season_metadata=season_metadata,
            tmdb_episodes=tmdb_episodes,
            tmdb_series=tmdb_series,
            jellyfin_data=jellyfin_data,
            existing_episodes_by_path=existing_episodes_by_path,
            existing_series_data=existing_series_data,
            season_offline=season_offline,
            detail_callback=detail_callback,
        )

        # Scan episodes
        scanned_episodes = _scan_season_episodes(
            season_directory,
            season_name,
            existing_season,
            metadata_only,
            scan_context,
        )

        # Group and resolve versions
        existing_season_eps: list = []
        if existing_series_data:
            existing_season_eps = (
                existing_series_data.get("seasons", {})
                .get(season_name, {})
                .get("episodes", [])
            )
        finalised_episodes = _group_and_resolve_episode_versions(
            scanned_episodes,
            existing_season_eps,
            season_offline,
            force_refresh,
            metadata_only,
        )
        series_data["seasons"][season_name]["episodes"] = finalised_episodes

        # Add TMDB placeholders
        placeholders = _create_tmdb_placeholder_episodes(
            tmdb_episodes,
            finalised_episodes,
            season_name,
            season_metadata,
            show_future_episodes=show_future_episodes,
        )
        series_data["seasons"][season_name]["episodes"].extend(placeholders)

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

    # Phase 5: Preserve existing data
    _preserve_existing_episode_data(
        series_data,
        existing_series_data,
        cleanup,
        metadata_only,
        show_future_episodes=show_future_episodes,
    )

    # Phase 6: Persist series directory mtime so subsequent scans can skip
    # this series entirely when its directory has not changed.
    if not metadata_only:
        try:
            series_directory_mtime = series_directory.stat().st_mtime
            from lan_streamer import db as _db

            if database_queue is not None:
                from lan_streamer.backend.database_writer import DatabaseWriteTask

                task = DatabaseWriteTask(
                    action="save_directory_mtime",
                    payload={
                        "path": str(series_directory.absolute()),
                        "mtime": series_directory_mtime,
                    },
                )
                database_queue.put(task)
            else:
                _db.save_directory_mtime(
                    str(series_directory.absolute()), series_directory_mtime
                )
            logger.debug(
                f"Saved series directory mtime for '{series_directory.name}': "
                f"{series_directory_mtime}"
            )
        except OSError as mtime_error:
            logger.warning(
                f"Could not read series directory mtime for "
                f"'{series_directory.name}': {mtime_error}"
            )

    logger.info(
        f"Completed scan for series '{series_directory.name}', found {len(series_data['seasons'])} seasons."
    )
    return series_data
