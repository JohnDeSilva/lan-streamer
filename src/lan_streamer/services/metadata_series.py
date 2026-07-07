"""Series-level metadata resolution helpers.

Provides functions for building series metadata defaults,
resolving Jellyfin IDs, downloading posters, processing TMDB episode groups,
and detecting new series files.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict

from lan_streamer.providers.tmdb import tmdb_client
from lan_streamer.scanner.parser import (
    _parse_episode_number,
    _parse_season_number,
    find_video_files,
)

logger = logging.getLogger("lan_streamer.services.metadata_series")


def _build_existing_episodes_index(
    existing_series_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Builds a path → episode-dict lookup from an existing series data structure.

    Args:
        existing_series_data: The full existing series data dictionary.

    Returns:
        A mapping of absolute file paths to episode dictionaries.
    """
    index: Dict[str, Any] = {}
    for season in existing_series_data.get("seasons", {}).values():
        for episode in season.get("episodes", []):
            index[episode["path"]] = episode
    return index


def _detect_new_series_files(
    series_directory: Path,
    existing_episodes_by_path: Dict[str, Any],
) -> bool:
    """Returns ``True`` when at least one video file inside *series_directory*
    is not present in *existing_episodes_by_path*, indicating the library has
    grown.

    Args:
        series_directory: The top-level series directory on disk.
        existing_episodes_by_path: A path → episode-dict lookup from the
            existing series data.

    Returns:
        ``True`` if new or unindexed files were found.
    """
    for file_path in find_video_files(series_directory):
        try:
            rel_path = file_path.relative_to(series_directory)
            parts = rel_path.parts
            if len(parts) > 2:
                first_dir = parts[0]
                first_dir_lower = first_dir.lower()
                is_valid_season = (
                    "season" in first_dir_lower
                    or "special" in first_dir_lower
                    or "extra" in first_dir_lower
                    or "featurette" in first_dir_lower
                    or "bonus" in first_dir_lower
                    or "shorts" in first_dir_lower
                    or bool(re.search(r"\d+", first_dir))
                )
                if is_valid_season:
                    continue
        except Exception:
            pass

        abs_path = str(file_path.absolute())
        if abs_path not in existing_episodes_by_path:
            logger.debug(
                f"New/unindexed file detected in '{series_directory.name}': '{abs_path}'"
            )
            return True
    return False


def _build_series_metadata_defaults(
    manual_jellyfin_id: str | None,
) -> Dict[str, Any]:
    """Returns a blank series metadata dictionary with all expected keys.

    Args:
        manual_jellyfin_id: Optional Jellyfin ID to pre-populate.

    Returns:
        A dictionary with keys ``tmdb_identifier``, ``overview``,
        ``poster_path``, ``tmdb_name``, ``first_air_date``, and
        ``jellyfin_id``.
    """
    return {
        "tmdb_identifier": "",
        "overview": "",
        "poster_path": "",
        "tmdb_name": "",
        "first_air_date": "",
        "jellyfin_id": manual_jellyfin_id or "",
    }


def _resolve_series_poster(
    tmdb_series: Dict[str, Any],
    tmdb_identifier: str,
    existing_series_data: Dict[str, Any] | None,
    offline: bool = False,
) -> str:
    """Three-step poster resolution for a TV series.

    1. Cached local image.
    2. Existing valid local file.
    3. Download from TMDB CDN.

    Args:
        tmdb_series: TMDB series data.
        tmdb_identifier: TMDB identifier string.
        existing_series_data: Previously stored series data (may be ``None``).
        offline: When ``True``, skip network downloads.

    Returns:
        Local file path string (may be empty).
    """
    cached = tmdb_client.get_cached_image(f"tmdb_series_{tmdb_identifier}")
    if cached and isinstance(cached, str):
        return cached

    if existing_series_data:
        existing_poster = existing_series_data.get("metadata", {}).get(
            "poster_path", ""
        )
        if existing_poster and Path(existing_poster).is_file():
            return existing_poster

    poster_path = tmdb_series.get("poster_path") or ""
    if poster_path:
        if tmdb_series.get("_is_prefetched") and not poster_path.startswith("/"):
            return poster_path
        if not offline:
            return tmdb_client.download_image(
                poster_path, f"tmdb_series_{tmdb_identifier}"
            )

    return ""


def _resolve_episode_jellyfin_id(
    episode_path: str,
    episode_name: str,
    episode_file: Path,
    tmdb_episode_identifier: str | None,
    tmdb_name: str | None,
    tmdb_number: int | None,
    season_name: str,
    series_directory: Path,
    series_data: Dict[str, Any],
    season_metadata: Dict[str, Any],
    tmdb_series: Dict[str, Any] | None,
    jellyfin_data: Dict[str, Any] | None,
) -> tuple[str, str, str]:
    """Multi-strategy Jellyfin ID resolution for a single episode file.

    Strategies tried in order:

    1. Path map (direct path → Jellyfin item lookup).
    2. TMDB episode map (TMDB identifier → Jellyfin ID).
    3. Name map (series name + episode name → Jellyfin ID).
    4. Series-ID map — SxxExx pattern, then episode name fallback.

    Args:
        episode_path: Absolute path to the episode file.
        episode_name: Filename string (e.g. ``"S01E02.mkv"``).
        episode_file: ``Path`` object for the episode.
        tmdb_episode_identifier: TMDB episode ID (may be ``None``).
        tmdb_name: TMDB episode name (may be ``None``).
        tmdb_number: TMDB episode number (may be ``None``).
        season_name: Season folder name (e.g. ``"Season 1"``).
        series_directory: Top-level series directory.
        series_data: Full series data dictionary including metadata.
        season_metadata: Season-level metadata dictionary.
        tmdb_series: TMDB series data (may be ``None``).
        jellyfin_data: Jellyfin sync data (may be ``None``).

    Returns:
        A 3-tuple ``(jellyfin_id, new_series_jellyfin_id, new_season_jellyfin_id)``.
    """
    jellyfin_id = ""
    new_series_jellyfin_id = ""
    new_season_jellyfin_id = ""

    if not jellyfin_data:
        return jellyfin_id, new_series_jellyfin_id, new_season_jellyfin_id

    # 1. Path map
    path_map = jellyfin_data.get("path_map") or {}
    jellyfin_info = path_map.get(episode_path)
    if jellyfin_info:
        jellyfin_id = jellyfin_info["id"]
        new_series_jellyfin_id = jellyfin_info.get("series_id") or ""
        new_season_jellyfin_id = jellyfin_info.get("season_id") or ""

    # 2. TMDB episode map
    if not jellyfin_id and tmdb_episode_identifier:
        jellyfin_id = jellyfin_data.get("tmdb_episode_map", {}).get(
            str(tmdb_episode_identifier), ""
        )

    # 3. Name map
    if not jellyfin_id:
        name_map = jellyfin_data.get("name_map", {})
        lookup_series = str(
            tmdb_series.get("name")
            if tmdb_series and tmdb_series.get("name")
            else series_directory.name
        ).lower()
        lookup_episode = str(tmdb_name if tmdb_name else episode_file.stem).lower()
        jellyfin_id = name_map.get((lookup_series, lookup_episode), "")

    # 4. Series-ID map — SxxExx then episode name
    series_metadata = series_data["metadata"]
    if not jellyfin_id and series_metadata.get("jellyfin_id"):
        series_map = jellyfin_data.get("series_id_map", {}).get(
            series_metadata["jellyfin_id"]
        )
        if series_map:
            parsed = _parse_episode_number(episode_name)
            season_num: int | None = None
            episode_num: int | None = None
            if parsed:
                season_num, episode_num = parsed
            elif tmdb_number is not None:
                episode_num = tmdb_number
                season_num = _parse_season_number(season_name)

            if season_num is not None and episode_num is not None:
                jellyfin_id = series_map["episodes"].get((season_num, episode_num), "")
                if jellyfin_id:
                    logger.debug(
                        f"Matched '{episode_name}' via Series ID map "
                        f"(S{season_num:02}E{episode_num:02})"
                    )

            if not jellyfin_id:
                lookup_name = (tmdb_name or episode_file.stem).lower()
                jellyfin_id = series_map["names"].get(lookup_name, "")
                if jellyfin_id:
                    logger.debug(
                        f"Matched '{episode_name}' via Series ID map name '{lookup_name}'"
                    )

    if jellyfin_id:
        logger.info(f"Matched Jellyfin ID for '{episode_name}': {jellyfin_id}")

    return jellyfin_id, new_series_jellyfin_id, new_season_jellyfin_id


def _process_series_metadata(
    series_directory: Path,
    tmdb_series: Dict[str, Any] | None,
    jellyfin_data: Dict[str, Any] | None,
    manual_jellyfin_id: str | None,
    existing_series_data: Dict[str, Any] | None,
    force_refresh: bool,
    cleanup: bool,
    single_item_refresh: bool = False,
    offline: bool = False,
    metadata_only: bool = False,
) -> tuple[Dict[str, Any], bool, Dict[str, Any] | None, Dict[str, Any], bool]:
    """Full series-level metadata resolution.

    Handles locked-series stubs, early returns when nothing has changed, TMDB
    lookups, poster resolution, and Jellyfin series-ID matching.

    Args:
        series_directory: The series directory on disk.
        tmdb_series: Pre-loaded TMDB series data or ``None``.
        jellyfin_data: Jellyfin sync data or ``None``.
        manual_jellyfin_id: Optional manual Jellyfin ID override.
        existing_series_data: Previously indexed series data (may be ``None``).
        force_refresh: Force a fresh TMDB lookup even when data exists.
        cleanup: When ``True``, stale metadata may be pruned.
        single_item_refresh: Refresh just this single item.
        offline: When ``True``, skip all network calls.
        metadata_only: Only resolve metadata, skip disk I/O for files.

    Returns:
        A 5-tuple:

        - ``series_data``: The resolved series data dictionary.
        - ``is_early_return``: ``True`` when caller can skip further
          processing.
        - ``tmdb_series``: Possibly-updated TMDB series data.
        - ``existing_episodes_by_path``: Path → episode lookup.
        - ``force_refresh``: Possibly-updated refresh flag.
    """
    series_name = series_directory.name

    existing_episodes_by_path: Dict[str, Any] = {}
    is_locked = False
    existing_tmdb_identifier = ""
    if existing_series_data:
        ext_metadata = existing_series_data.get("metadata", {})
        is_locked = ext_metadata.get("locked_metadata", False)
        existing_tmdb_identifier = ext_metadata.get("tmdb_identifier", "")
        existing_episodes_by_path = _build_existing_episodes_index(existing_series_data)

    has_new_files = False
    if existing_series_data and not metadata_only:
        has_new_files = existing_series_data.get(
            "_has_new_files", False
        ) or _detect_new_series_files(series_directory, existing_episodes_by_path)

    if has_new_files and not is_locked and not offline:
        logger.info(
            f"New files detected in series '{series_name}'. Automatically pulling fresh metadata."
        )
        force_refresh = True
        if existing_tmdb_identifier and not tmdb_series:
            full = tmdb_client.get_series_by_id(existing_tmdb_identifier)
            if full:
                tmdb_series = full

    series_metadata: Dict[str, Any] = _build_series_metadata_defaults(
        manual_jellyfin_id
    )

    if existing_series_data:
        ext_metadata = existing_series_data.get("metadata", {})
        for key, value in ext_metadata.items():
            if value:
                series_metadata[key] = value
        if "tmdb_episode_group_id" in ext_metadata:
            series_metadata["tmdb_episode_group_id"] = ext_metadata[
                "tmdb_episode_group_id"
            ]
        if manual_jellyfin_id:
            series_metadata["jellyfin_id"] = manual_jellyfin_id

    if (
        not force_refresh
        and not has_new_files
        and not cleanup
        and existing_series_data
        and existing_series_data.get("metadata", {}).get("tmdb_identifier")
    ):
        series_data = existing_series_data.copy()
        meta = series_data.get("metadata", {})
        if (
            not meta.get("jellyfin_id")
            and jellyfin_data
            and meta.get("tmdb_identifier")
        ):
            meta["jellyfin_id"] = jellyfin_data.get("tmdb_series_map", {}).get(
                meta["tmdb_identifier"], ""
            )
        if manual_jellyfin_id:
            meta["jellyfin_id"] = manual_jellyfin_id
        path_map = jellyfin_data.get("path_map", {}) if jellyfin_data else {}
        tmdb_map = jellyfin_data.get("tmdb_episode_map", {}) if jellyfin_data else {}
        for season in series_data.get("seasons", {}).values():
            for episode in season.get("episodes", []):
                if jellyfin_data and not episode.get("jellyfin_id"):
                    if episode.get("path") in path_map:
                        episode["jellyfin_id"] = path_map[episode["path"]]["id"]
                    elif episode.get("tmdb_identifier") in tmdb_map:
                        episode["jellyfin_id"] = tmdb_map[episode["tmdb_identifier"]]
                    elif episode.get("tmdb_episode_identifier") in tmdb_map:
                        episode["jellyfin_id"] = tmdb_map[
                            episode["tmdb_episode_identifier"]
                        ]
                if not episode.get("runtime"):
                    episode["runtime"] = 0
        return series_data, True, tmdb_series, existing_episodes_by_path, force_refresh

    tmdb_seasons: list[Any] = []
    episode_group_details = None

    if not offline:
        if tmdb_series and "name" not in tmdb_series and "id" in tmdb_series:
            if single_item_refresh or not series_metadata.get("tmdb_name"):
                full = tmdb_client.get_series_by_id(tmdb_series["id"])
                if full:
                    tmdb_series = full

        if not tmdb_series:
            if series_metadata["tmdb_identifier"]:
                if force_refresh or single_item_refresh:
                    full = tmdb_client.get_series_by_id(
                        series_metadata["tmdb_identifier"]
                    )
                    if full:
                        tmdb_series = full
                if not tmdb_series:
                    tmdb_series = {
                        "id": series_metadata["tmdb_identifier"],
                        "name": series_metadata["tmdb_name"],
                        "overview": series_metadata["overview"],
                        "poster_path": series_metadata["poster_path"],
                        "first_air_date": series_metadata.get("first_air_date", ""),
                    }
            elif not is_locked and (
                single_item_refresh
                or not existing_series_data
                or not existing_tmdb_identifier
            ):
                tmdb_series = tmdb_client.search_series(series_name)

        if tmdb_series:
            tmdb_identifier = str(tmdb_series.get("id") or "")
            series_metadata["tmdb_identifier"] = tmdb_identifier
            series_metadata["overview"] = tmdb_series.get("overview", "")
            series_metadata["tmdb_name"] = tmdb_series.get("name", "")
            series_metadata["first_air_date"] = tmdb_series.get("first_air_date", "")

            if tmdb_identifier:
                series_metadata["poster_path"] = _resolve_series_poster(
                    tmdb_series, tmdb_identifier, existing_series_data, offline
                )
            else:
                if not series_metadata.get("poster_path"):
                    series_metadata["poster_path"] = ""

            if tmdb_identifier and not is_locked:
                if force_refresh or single_item_refresh or not existing_series_data:
                    episode_group_details = None
                    existing_metadata = (
                        existing_series_data.get("metadata", {})
                        if existing_series_data
                        else {}
                    )
                    saved_group_id = existing_metadata.get("tmdb_episode_group_id")
                    if saved_group_id and saved_group_id != "default":
                        try:
                            episode_group_details = (
                                tmdb_client.get_episode_group_details(saved_group_id)
                            )
                            logger.info(
                                f"Using saved default group ID {saved_group_id} for series '{series_name}' metadata scan"
                            )
                        except Exception as e:
                            logger.exception(
                                f"Failed to fetch saved group details {saved_group_id}: {e}"
                            )
                    if saved_group_id == "default":
                        episode_group_details = None
                    elif not episode_group_details:
                        episode_group_details = (
                            tmdb_client.get_season_based_episode_group(tmdb_identifier)
                        )
                    if (
                        episode_group_details
                        and isinstance(episode_group_details, dict)
                        and "groups" in episode_group_details
                    ):
                        tmdb_seasons = []
                        for group in episode_group_details.get("groups", []):
                            group_name = group.get("name") or ""
                            season_num_match = re.search(r"\d+", group_name)
                            season_num = (
                                int(season_num_match.group())
                                if season_num_match
                                else group.get("order", -1)
                            )
                            if group_name.lower() == "specials":
                                season_num = 0
                            if season_num >= 0:
                                tmdb_seasons.append(
                                    {
                                        "season_number": season_num,
                                        "name": group_name,
                                        "id": group.get("id"),
                                        "episode_count": len(group.get("episodes", [])),
                                        "poster_path": "",
                                    }
                                )
                    else:
                        episode_group_details = None
                        if tmdb_series and "seasons" in tmdb_series:
                            tmdb_seasons = tmdb_series["seasons"]
                        else:
                            tmdb_seasons = tmdb_client.get_seasons(tmdb_identifier)

    if (
        not series_metadata["jellyfin_id"]
        and jellyfin_data
        and tmdb_series
        and not offline
    ):
        tmdb_id = str(tmdb_series.get("id") or "")
        if tmdb_id:
            series_metadata["jellyfin_id"] = jellyfin_data.get(
                "tmdb_series_map", {}
            ).get(tmdb_id, "")

    series_data: Dict[str, Any] = {
        "metadata": series_metadata,
        "seasons": {},
        "_tmdb_seasons": tmdb_seasons,
        "_tmdb_series_id": series_metadata.get("tmdb_identifier"),
        "_tmdb_episode_group_details": episode_group_details,
        "_jellyfin_id": "",
    }

    return series_data, False, tmdb_series, existing_episodes_by_path, force_refresh
