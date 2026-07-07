"""
Pass 2 — metadata resolution pass for series and movies.

Handles all TMDB lookups, episode matching, poster downloads, and placeholder
creation. No filesystem walking — relies on existing data from Pass 1 for
file paths.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import logging
import re
from pathlib import Path
from collections.abc import Callable
from typing import Any, Dict

from lan_streamer.db.utils import natural_sort_key
from lan_streamer.providers.tmdb import tmdb_client
from lan_streamer.scanner.file_property_scanner import (
    get_detailed_file_info,
    get_stub_file_info,
)
from lan_streamer.scanner.parser import _parse_episode_number
from lan_streamer.scanner.versioning import choose_active_version
from lan_streamer.services.metadata_episode import (
    _process_episode_file,
    _process_season_metadata,
)
from lan_streamer.services.metadata_movie import (
    _apply_existing_movie_metadata,
    _apply_tmdb_movie_data,
    _build_movie_metadata_defaults,
    _resolve_movie_jellyfin_id,
)
from lan_streamer.services.metadata_series import _process_series_metadata
from lan_streamer.services.metadata_updates import clean_series_data

logger = logging.getLogger("lan_streamer.scanner.pass2_metadata")
_TODAY_STR: str = datetime.date.today().isoformat()


# =============================================================================
#  Helpers extracted from scan_tv.py (Pass 2 portions only)
# =============================================================================


def _fetch_tmdb_episodes_parallel(
    tmdb_series_id: str | int,
    season_indices: Dict[str, int],
    executor: concurrent.futures.ThreadPoolExecutor,
) -> Dict[str, list]:
    """Fetch TMDB episode lists for multiple seasons in parallel."""
    prefetched: Dict[str, list] = {}
    fetch_futures = {
        executor.submit(tmdb_client.get_episodes, tmdb_series_id, s_idx): s_name
        for s_name, s_idx in season_indices.items()
    }
    for future in concurrent.futures.as_completed(fetch_futures):
        season_name = fetch_futures[future]
        try:
            episodes = future.result()
            prefetched[season_name] = episodes
            logger.debug(
                f"Pre-fetched {len(episodes)} TMDB episodes for season '{season_name}'"
            )
        except Exception as error:
            logger.warning(
                f"Failed to pre-fetch TMDB episodes for season '{season_name}': {error}"
            )
    return prefetched


def _season_name_from_tmdb(tmdb_season: Dict[str, Any]) -> str:
    """Derive a local-friendly season name from a TMDB season dict."""
    if tmdb_season.get("season_number", -1) == 0:
        return "Specials"
    existing_name = (tmdb_season.get("name") or "").strip()
    if existing_name and re.match(
        r"^(Season|Part|Cour)\s+\d+", existing_name, re.IGNORECASE
    ):
        return existing_name
    return f"Season {tmdb_season.get('season_number', 1)}"


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
    season_index = (
        0
        if season_name.lower() == "specials"
        else int((re.search(r"\d+", season_name) or ["1"])[0])
    )
    placeholders: list[Dict[str, Any]] = []
    for tmdb_ep in tmdb_episodes:
        episode_number = tmdb_ep.get("episode_number")
        if episode_number is None or episode_number in local_numbers:
            continue
        if not show_future_episodes:
            air_date = tmdb_ep.get("air_date") or ""
            if not air_date or air_date > _TODAY_STR:
                continue
        mal_id = season_metadata.get("myanimelist_id")
        ep_name = tmdb_ep.get("name") or "TBA"
        record: Dict[str, Any] = {
            "name": f"S{season_index:02d}E{episode_number:02d} - {ep_name}",
            "path": None,
            "tmdb_identifier": str(tmdb_ep.get("id", "")),
            "tmdb_episode_identifier": str(tmdb_ep.get("id", "")),
            "tmdb_name": tmdb_ep.get("name", ""),
            "tmdb_number": episode_number,
            "air_date": tmdb_ep.get("air_date") or "",
            "runtime": tmdb_ep.get("runtime") or 0,
            "jellyfin_id": "",
            "watched": False,
            "date_added": 0,
        }
        if mal_id:
            record["myanimelist_anime_id"] = mal_id
            record["myanimelist_episode_number"] = episode_number
        placeholders.append(record)
    return placeholders


def _add_tmdb_only_seasons(
    series_data: Dict[str, Any],
    force_refresh: bool,
    single_item_refresh: bool,
    prefetched_season_episodes: Dict[str, list[Any]],
    show_future_episodes: bool = True,
) -> None:
    """Create season entries for TMDB seasons not represented on disk."""
    tmdb_seasons: list[Dict[str, Any]] = series_data.get("_tmdb_seasons", [])
    tmdb_series_id: str = str(series_data.get("_tmdb_series_id") or "")
    is_locked = bool(series_data.get("metadata", {}).get("locked_metadata", False))
    for tmdb_season in tmdb_seasons:
        season_name = _season_name_from_tmdb(tmdb_season)
        if season_name in series_data["seasons"]:
            continue
        season_number = tmdb_season.get("season_number", -1)
        logger.info(f"Adding TMDB-only season '{season_name}'")
        season_metadata: Dict[str, Any] = {
            "jellyfin_id": "",
            "tmdb_identifier": str(tmdb_season.get("id", "")),
            "season_directory_path": "",
            "last_scanned_mtime": None,
            "poster_path": "",
        }
        poster = tmdb_season.get("poster_path") or ""
        if poster and tmdb_season.get("id") and not is_locked:
            cached = tmdb_client.get_cached_image(f"tmdb_season_{tmdb_season['id']}")
            if cached and isinstance(cached, str):
                season_metadata["poster_path"] = cached
            else:
                dl = tmdb_client.download_image(
                    poster, f"tmdb_season_{tmdb_season['id']}"
                )
                if dl:
                    season_metadata["poster_path"] = dl

        tmdb_episodes_list: list[Dict[str, Any]] = []
        if not is_locked and tmdb_series_id:
            groups = series_data.get("_tmdb_episode_group_details")
            if groups and isinstance(groups, dict) and "groups" in groups:
                for group in groups["groups"]:
                    gname = group.get("name") or ""
                    nm = re.search(r"\d+", gname)
                    gsi = int(nm.group()) if nm else group.get("order", -1)
                    if gname.lower() == "specials":
                        gsi = 0
                    if gsi != season_number:
                        continue
                    for ge in group.get("episodes", []):
                        tmdb_episodes_list.append(
                            {
                                "id": ge.get("id"),
                                "name": ge.get("name"),
                                "episode_number": ge.get("order") + 1,
                                "air_date": ge.get("air_date") or "",
                                "runtime": ge.get("runtime") or 0,
                            }
                        )
                    break
            elif season_number >= 0:
                prefetched = prefetched_season_episodes.get(season_name)
                if prefetched is not None:
                    tmdb_episodes_list = prefetched
                else:
                    tmdb_episodes_list = tmdb_client.get_episodes(
                        tmdb_series_id, season_number
                    )

        placeholders = _create_tmdb_placeholder_episodes(
            tmdb_episodes_list,
            [],
            season_name,
            season_metadata,
            show_future_episodes=show_future_episodes,
        )
        series_data["seasons"][season_name] = {
            "metadata": season_metadata,
            "episodes": placeholders,
            "_tmdb_episodes": tmdb_episodes_list,
            "_changed": True,
        }
        logger.info(
            f"Added {len(placeholders)} TMDB placeholder episodes for season '{season_name}'"
        )


def _preserve_existing_episode_data(
    series_data: Dict[str, Any],
    existing_series_data: Dict[str, Any] | None,
    show_future_episodes: bool = True,
) -> None:
    """Preserve missing seasons and episodes from previous scans (non-destructive)."""
    if not existing_series_data:
        return
    for old_sn, old_sd in existing_series_data.get("seasons", {}).items():
        if old_sn not in series_data["seasons"]:
            logger.info(
                f"Preserving missing season folder '{old_sn}' (non-destructive)"
            )
            series_data["seasons"][old_sn] = old_sd
            continue
        found_paths: set[str] = set()
        for ep in series_data["seasons"][old_sn]["episodes"]:
            if ep.get("path"):
                found_paths.add(ep["path"])
            for v in ep.get("versions", []):
                if v.get("path"):
                    found_paths.add(v["path"])
        found_numbers: set[int] = {
            ep["tmdb_number"]
            for ep in series_data["seasons"][old_sn]["episodes"]
            if ep.get("tmdb_number") is not None
        }
        for old_ep in old_sd.get("episodes", []):
            old_path, old_num = old_ep.get("path"), old_ep.get("tmdb_number")
            if old_path:
                if old_path not in found_paths and Path(old_path).exists():
                    series_data["seasons"][old_sn]["episodes"].append(old_ep)
            elif old_num not in found_numbers:
                if not show_future_episodes:
                    air_date = old_ep.get("air_date") or ""
                    if not air_date or air_date > _TODAY_STR:
                        continue
                series_data["seasons"][old_sn]["episodes"].append(old_ep)
        series_data["seasons"][old_sn]["episodes"].sort(
            key=lambda ep: natural_sort_key(ep["name"])
        )


def _filter_future_episodes(series_data: Dict[str, Any]) -> None:
    """Remove future-dated placeholder episodes from series data in-place."""
    for season_data in series_data.get("seasons", {}).values():
        season_data["episodes"] = [
            ep
            for ep in season_data.get("episodes", [])
            if ep.get("path") is not None or (ep.get("air_date") or "") <= _TODAY_STR
        ]


def _group_and_resolve_episode_versions(
    scanned_episodes: list[Dict[str, Any]],
    existing_season_episodes: list[Dict[str, Any]],
    force_refresh: bool,
) -> list[Dict[str, Any]]:
    """Group episodes by identity, resolve versions, return finalised records."""
    grouped: Dict[Any, list] = {}
    for ep in scanned_episodes:
        key: Any = ep.get("tmdb_number")
        if key is None:
            parsed = _parse_episode_number(ep.get("name", ""))
            key = parsed if parsed else ep.get("name")
        grouped.setdefault(key, []).append(ep)

    finalised: list[Dict[str, Any]] = []
    for episode_list in grouped.values():
        versions: list[Dict[str, Any]] = []
        incoming = {ep["path"] for ep in episode_list if ep.get("path")}
        for ep in episode_list:
            ev = None
            for ex in existing_season_episodes:
                match = (
                    ep.get("tmdb_number") is not None
                    and ex.get("tmdb_number") == ep.get("tmdb_number")
                ) or ep.get("name") == ex.get("name")
                if match and ex.get("versions"):
                    for v in ex["versions"]:
                        if v.get("path") == ep["path"]:
                            ev = v
                            break
                if ev:
                    break
            if (
                ev is not None
                and not force_refresh
                and ev.get("video_codec") != "Unknown"
                and ev.get("resolution") != "Unknown"
            ):
                versions.append(ev)
            else:
                versions.append(get_detailed_file_info(ep["path"]))

        ref = episode_list[0]
        for ex in existing_season_episodes:
            match = (
                ref.get("tmdb_number") is not None
                and ex.get("tmdb_number") == ref.get("tmdb_number")
            ) or ref.get("name") == ex.get("name")
            if match and ex.get("versions"):
                for v in ex["versions"]:
                    if v.get("path") and v["path"] not in incoming:
                        versions.append(v)

        default_path = next(
            (
                ex.get("default_path")
                for ex in existing_season_episodes
                if (
                    ref.get("tmdb_number") is not None
                    and ex.get("tmdb_number") == ref.get("tmdb_number")
                )
                or ref.get("name") == ex.get("name")
            ),
            None,
        )
        active = choose_active_version(versions, default_path)
        base = ref.copy()
        for k in (
            "path",
            "video_codec",
            "resolution",
            "bit_rate",
            "audio_tracks",
            "subtitle_tracks",
        ):
            base[k] = active.get(k)
        base["versions"] = versions
        base["default_path"] = default_path
        finalised.append(base)
    return finalised


# =============================================================================
#  Series Pass 2
# =============================================================================


def scan_series_pass2(
    series_directory: Path,
    existing_series_data: Dict[str, Any] | None,
    tmdb_series: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, dict] | None = None,
    force_refresh: bool = False,
    single_item_refresh: bool = False,
    show_future_episodes: bool = True,
    detail_callback: Callable | None = None,
    season_callback: Callable | None = None,
    tmdb_prefetch_executor: concurrent.futures.ThreadPoolExecutor | None = None,
) -> Dict[str, Any]:
    """Run Pass 2 metadata resolution for a single TV series.

    Sub-passes: 2A (series metadata), 2B (season metadata + pre-fetch),
    2C (episode matching), 2D (placeholders). No filesystem walking.
    """
    if not existing_series_data:
        return None
    # Early exit for locked metadata — preserve existing data as-is.
    existing_meta = (
        existing_series_data.get("metadata", {}) if existing_series_data else {}
    )
    is_locked = bool(existing_meta.get("locked_metadata", False))
    if is_locked:
        logger.info(
            "Using locked TMDB metadata for '%s' (ID: %s)",
            series_directory.name,
            existing_meta.get("tmdb_identifier", ""),
        )
        result = dict(existing_series_data)
        result["seasons"] = dict(existing_series_data.get("seasons", {}))
        return clean_series_data(result) or result

    # Phase 2A: Series-level metadata resolution
    (series_data, is_early, tmdb_result, existing_by_path, refresh) = (
        _process_series_metadata(
            series_directory=series_directory,
            tmdb_series=tmdb_series,
            jellyfin_data=jellyfin_data,
            manual_jellyfin_id="",
            existing_series_data=existing_series_data,
            force_refresh=force_refresh,
            cleanup=False,
            single_item_refresh=single_item_refresh,
            offline=False,
            metadata_only=False,
        )
    )
    force_refresh = refresh
    tmdb_series = tmdb_result
    if is_early:
        if not show_future_episodes:
            _filter_future_episodes(series_data)
        return clean_series_data(series_data) or series_data

    # Phase 2B: Season metadata resolution + TMDB pre-fetch
    series_data["seasons"] = {
        sn: {
            "metadata": sd.get("metadata", {}),
            "episodes": [],
            "_tmdb_episodes": sd.get("_tmdb_episodes", []),
        }
        for sn, sd in existing_series_data.get("seasons", {}).items()
    }
    prefetched: Dict[str, list[Any]] = {}
    if not is_locked and tmdb_client.is_configured():
        tid = series_data.get("_tmdb_series_id")
        if tid and not series_data.get("_tmdb_episode_group_details"):
            indices: Dict[str, int] = {}
            for sn in series_data["seasons"]:
                if sn.lower() == "specials":
                    indices[sn] = 0
                else:
                    m = re.search(r"\d+", sn)
                    if m:
                        indices[sn] = int(m.group())
            if indices and tmdb_prefetch_executor:
                prefetched = _fetch_tmdb_episodes_parallel(
                    tid, indices, tmdb_prefetch_executor
                )

    # Phases 2C + 2D: Per-season TMDB matching + placeholders
    for season_name in list(series_data["seasons"].keys()):
        season_directory = series_directory / season_name
        if detail_callback:
            detail_callback(
                "start_season", {"folder": series_directory.name, "season": season_name}
            )
        _, _, season_metadata, tmdb_eps = _process_season_metadata(
            season_directory=season_directory,
            series_data=series_data,
            existing_series_data=existing_series_data,
            existing_episodes_by_path=existing_by_path,
            force_refresh=force_refresh,
            single_item_refresh=single_item_refresh,
            offline=False,
            metadata_only=True,
            prefetched_tmdb_episodes=prefetched.get(season_name),
        )
        series_data["seasons"][season_name]["metadata"] = season_metadata
        series_data["seasons"][season_name]["_tmdb_episodes"] = tmdb_eps

        existing_eps = (
            existing_series_data.get("seasons", {})
            .get(season_name, {})
            .get("episodes", [])
        )
        matched: list[Dict[str, Any]] = []
        for ed in existing_eps:
            ep_path = ed.get("path")
            if not ep_path:
                continue
            matched.append(
                _process_episode_file(
                    episode_file=Path(ep_path),
                    season_name=season_name,
                    series_directory=series_directory,
                    series_data=series_data,
                    season_metadata=season_metadata,
                    tmdb_episodes=tmdb_eps,
                    tmdb_series=tmdb_series,
                    jellyfin_data=jellyfin_data,
                    existing_episodes_by_path=existing_by_path,
                    existing_series_data=existing_series_data,
                    offline=False,
                    metadata_only=True,
                )
            )
        series_data["seasons"][season_name]["episodes"] = matched
        placeholders = _create_tmdb_placeholder_episodes(
            tmdb_eps,
            matched,
            season_name,
            season_metadata,
            show_future_episodes=show_future_episodes,
        )
        series_data["seasons"][season_name]["episodes"].extend(placeholders)

        if season_callback:
            season_callback(
                series_data.get("metadata", {}).get("name") or series_directory.name,
                series_data,
                season_name,
                {
                    "metadata": season_metadata,
                    "episodes": series_data["seasons"][season_name]["episodes"],
                },
            )
        if detail_callback:
            detail_callback(
                "finish_season",
                {"folder": series_directory.name, "season": season_name},
            )

    # Phase 2D continued: TMDB-only seasons, preserve, filter
    _add_tmdb_only_seasons(
        series_data,
        force_refresh,
        single_item_refresh,
        prefetched,
        show_future_episodes=show_future_episodes,
    )
    _preserve_existing_episode_data(
        series_data, existing_series_data, show_future_episodes=show_future_episodes
    )
    if not show_future_episodes:
        _filter_future_episodes(series_data)

    result = clean_series_data(series_data) or series_data
    logger.info(
        f"Completed Pass 2 metadata for series '{series_directory.name}', {len(result['seasons'])} seasons."
    )
    return result


# =============================================================================
#  Movie Pass 2 helpers
# =============================================================================


def _resolve_tmdb_movie_data(
    tmdb_movie: Dict[str, Any] | None,
    movie_metadata: Dict[str, Any],
    title: str,
    year: int | None,
    is_locked: bool,
    existing_tmdb_id: str,
    existing_movie_data: Dict[str, Any] | None,
    single_item_refresh: bool,
    video_path: str,
    jellyfin_data: Dict[str, dict] | None,
) -> None:
    """Fetch and apply TMDB metadata to movie_metadata in-place. Always online."""
    if is_locked:
        return
    if (
        tmdb_movie
        and "title" not in tmdb_movie
        and "id" in tmdb_movie
        and (single_item_refresh or not movie_metadata.get("tmdb_name"))
    ):
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
            movie_metadata, tmdb_movie, existing_movie_data, offline=False
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
    """Build the final movie data dictionary from gathered information."""
    return {
        "name": folder_name,
        "path": video_path,
        "movie_directory_path": str(Path(video_path).parent.absolute()),
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


# =============================================================================
#  Movie Pass 2
# =============================================================================


def scan_movie_pass2(
    movie_directory: Path,
    existing_movie_data: Dict[str, Any] | None,
    tmdb_movie: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, dict] | None = None,
    force_refresh: bool = False,
    single_item_refresh: bool = False,
    detail_callback: Callable | None = None,
) -> Dict[str, Any] | None:
    """Run Pass 2 metadata resolution for a single movie.

    Resolves TMDB movie data, applies metadata, and downloads the poster
    — all using the already-discovered file data from Pass 1.
    """
    if not existing_movie_data:
        return None
    folder_name = movie_directory.name
    from lan_streamer.scanner.parser import _parse_movie_folder

    title, year = _parse_movie_folder(folder_name)
    is_locked = existing_movie_data.get("locked_metadata", False)
    existing_tmdb_id = existing_movie_data.get("tmdb_identifier", "")

    versions: list[Dict[str, Any]] = existing_movie_data.get("versions", [])
    if not versions and existing_movie_data.get("path"):
        versions = [get_stub_file_info(existing_movie_data["path"])]
    default_path = existing_movie_data.get("default_path") or existing_movie_data.get(
        "path"
    )
    active_version = choose_active_version(versions, default_path)
    video_path: str | None = active_version.get("path")
    if not video_path:
        logger.warning(f"Movie '{folder_name}': no valid video path in existing data.")
        return None

    has_new_file = existing_movie_data.get("path") != video_path
    if has_new_file and not is_locked:
        logger.info(
            f"New file detected for movie '{folder_name}'. Automatically pulling fresh metadata."
        )
        if existing_tmdb_id and not tmdb_movie:
            full = tmdb_client.get_movie_by_id(existing_tmdb_id)
            if full:
                tmdb_movie = full

    movie_metadata = _build_movie_metadata_defaults()
    movie_metadata["jellyfin_id"] = existing_movie_data.get("jellyfin_id", "")
    if existing_movie_data:
        _apply_existing_movie_metadata(
            movie_metadata, existing_movie_data, manual_jellyfin_id=None
        )
    _resolve_tmdb_movie_data(
        tmdb_movie,
        movie_metadata,
        title,
        year,
        is_locked,
        existing_tmdb_id,
        existing_movie_data,
        single_item_refresh,
        video_path,
        jellyfin_data,
    )
    movie_data = _build_movie_data(
        folder_name=folder_name,
        video_path=video_path,
        movie_metadata=movie_metadata,
        existing_movie_data=existing_movie_data,
        ctime=existing_movie_data.get("date_added") or 0,
        active_version=active_version,
        versions=versions,
        default_path=default_path,
        is_movie_changed=existing_movie_data.get("_changed", True),
        last_scanned_mtime=existing_movie_data.get("last_scanned_mtime"),
    )
    if detail_callback:
        detail_callback(
            "finish_file", {"file": video_path, "folder": movie_directory.name}
        )
    logger.info(
        f"Completed Pass 2 metadata for movie '{folder_name}' (TMDB ID: {movie_metadata.get('tmdb_identifier', '')})"
    )
    return movie_data
