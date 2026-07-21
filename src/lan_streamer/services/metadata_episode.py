"""Episode-level metadata resolution helpers.

Provides functions for processing season metadata and individual episode
files, matching local video files against TMDB episode lists, and resolving
Jellyfin IDs.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict

from lan_streamer.providers.tmdb import tmdb_client
from lan_streamer.scanner.parser import (
    _parse_episode_number,
)
from lan_streamer.services.metadata_series import _resolve_episode_jellyfin_id

logger = logging.getLogger("lan_streamer.services.metadata_episode")


def _process_season_metadata(
    season_directory: Path,
    series_data: Dict[str, Any],
    existing_series_data: Dict[str, Any] | None,
    existing_episodes_by_path: Dict[str, Any],
    force_refresh: bool = False,
    single_item_refresh: bool = False,
    offline: bool = False,
    metadata_only: bool = False,
    prefetched_tmdb_episodes: list[Any] | None = None,
) -> tuple[str, int, Dict[str, Any], list[Any]]:
    """Season-level metadata resolution + TMDB episode fetch.

    Matches a local season directory to a TMDB season, resolves the season
    poster, and fetches the episode list from TMDB (or from an episode group).

    Args:
        season_directory: The season folder on disk.
        series_data: The parent series data (including ``_tmdb_seasons`` and
            ``_tmdb_episode_group_details``).
        existing_series_data: Previously indexed series data (may be ``None``).
        existing_episodes_by_path: Path → episode lookup from existing data.
        force_refresh: Force a fresh TMDB lookup.
        single_item_refresh: Refresh just this single item.
        offline: When ``True``, skip network calls.
        metadata_only: Only resolve metadata, skip disk I/O.
        prefetched_tmdb_episodes: Pre-fetched TMDB episode list for this
            season. When provided, skips the TMDB API call.

    Returns:
        A 4-tuple ``(season_name, season_index, season_metadata, tmdb_episodes)``.
    """
    season_name = season_directory.name
    season_metadata: Dict[str, Any] = {
        "jellyfin_id": "",
    }
    tmdb_episodes: list[Any] = []

    if season_name.lower() == "specials":
        season_index = 0
    else:
        season_number_match = re.search(r"\d+", season_name)
        if season_number_match:
            season_index = int(season_number_match.group())
        else:
            season_index = -1
            logger.warning(
                f"Season directory '{season_name}' contains no recognisable season number "
                "— TMDB episode lookup will be skipped for this directory."
            )

    logger.debug(
        f"Processing season directory: '{season_name}' (Season index: {season_index})"
    )
    matched_tmdb_season = None
    for tmdb_season in series_data.get("_tmdb_seasons", []):
        if (
            tmdb_season.get("season_number") == season_index
            or tmdb_season.get("name") == season_name
        ):
            matched_tmdb_season = tmdb_season
            break

    existing_season_id = ""
    existing_season_poster = ""
    existing_mal_id = None
    existing_last_scanned_mtime = None
    if existing_series_data and season_name in existing_series_data.get("seasons", {}):
        old_season_metadata = existing_series_data["seasons"][season_name].get(
            "metadata", {}
        )
        existing_season_id = old_season_metadata.get("tmdb_identifier", "")
        existing_season_poster = old_season_metadata.get("poster_path", "")
        existing_mal_id = old_season_metadata.get("myanimelist_id")

    from lan_streamer import db

    existing_last_scanned_mtime = db.get_directory_mtime(
        str(season_directory.absolute())
    )

    if matched_tmdb_season and series_data["_tmdb_series_id"]:
        season_tmdb_identifier = matched_tmdb_season.get("id")
        season_metadata["tmdb_identifier"] = (
            str(season_tmdb_identifier) if season_tmdb_identifier else ""
        )

        cached_season_poster = (
            tmdb_client.get_cached_image(f"tmdb_season_{season_tmdb_identifier}")
            if season_tmdb_identifier
            else ""
        )
        if cached_season_poster and isinstance(cached_season_poster, str):
            season_metadata["poster_path"] = cached_season_poster
        elif existing_season_poster and Path(existing_season_poster).is_file():
            season_metadata["poster_path"] = existing_season_poster
        else:
            artwork = matched_tmdb_season.get("poster_path") or ""
            if artwork and season_tmdb_identifier and not offline:
                season_metadata["poster_path"] = tmdb_client.download_image(
                    artwork, f"tmdb_season_{season_tmdb_identifier}"
                )
            else:
                season_metadata["poster_path"] = ""
    else:
        season_metadata["tmdb_identifier"] = existing_season_id
        season_metadata["poster_path"] = existing_season_poster

    if existing_mal_id:
        season_metadata["myanimelist_id"] = existing_mal_id

    is_locked = bool(series_data.get("metadata", {}).get("locked_metadata", False))
    season_already_has_episodes = False
    has_unresolved_episodes = False
    if existing_series_data and season_name in existing_series_data.get("seasons", {}):
        eps = existing_series_data["seasons"][season_name].get("episodes", [])
        season_already_has_episodes = len(eps) > 0
        has_unresolved_episodes = any(not ep.get("tmdb_identifier") for ep in eps)

    needs_episode_search = (
        not is_locked
        and not offline
        and (
            force_refresh
            or single_item_refresh
            or not season_already_has_episodes
            or has_unresolved_episodes
        )
    )

    tmdb_episodes = []
    if needs_episode_search and series_data["_tmdb_series_id"]:
        if prefetched_tmdb_episodes is not None:
            tmdb_episodes = prefetched_tmdb_episodes
            logger.debug(
                f"Using prefetched TMDB episodes for season '{season_name}' "
                f"({len(tmdb_episodes)} episodes)"
            )
        else:
            episode_group_details = series_data.get("_tmdb_episode_group_details")
            if (
                episode_group_details
                and isinstance(episode_group_details, dict)
                and "groups" in episode_group_details
            ):
                # Find the sub-group for this season
                matched_group = None
                for group in episode_group_details.get("groups", []):
                    group_name = group.get("name") or ""
                    season_num_match = re.search(r"\d+", group_name)
                    group_season_index = (
                        int(season_num_match.group())
                        if season_num_match
                        else group.get("order", -1)
                    )
                    if group_name.lower() == "specials":
                        group_season_index = 0
                    if group_season_index == season_index:
                        matched_group = group
                        break
                if matched_group:
                    for group_ep in matched_group.get("episodes", []):
                        tmdb_episodes.append(
                            {
                                "id": group_ep.get("id"),
                                "name": group_ep.get("name"),
                                "episode_number": group_ep.get("order") + 1,
                                "air_date": group_ep.get("air_date") or "",
                                "runtime": group_ep.get("runtime") or 0,
                            }
                        )
            else:
                if season_index < 0:
                    logger.warning(
                        f"Skipping TMDB episode fetch for series ID '{series_data['_tmdb_series_id']}': "
                        f"season index '{season_index}' is invalid (could not parse a season number "
                        f"from directory name '{season_name}')."
                    )
                else:
                    logger.info(
                        f"Fetching TMDB episodes list for series ID '{series_data['_tmdb_series_id']}', season index '{season_index}'"
                    )
                    tmdb_episodes = tmdb_client.get_episodes(
                        series_data["_tmdb_series_id"], season_index
                    )

    current_mtime = None
    if not metadata_only and season_directory.exists():
        try:
            current_mtime = season_directory.stat().st_mtime
        except Exception:
            pass
    season_metadata["last_scanned_mtime"] = (
        current_mtime if current_mtime is not None else existing_last_scanned_mtime
    )

    return season_name, season_index, season_metadata, tmdb_episodes


def _process_episode_file(
    episode_file: Path,
    season_name: str,
    series_directory: Path,
    series_data: Dict[str, Any],
    season_metadata: Dict[str, Any],
    tmdb_episodes: list[Any],
    tmdb_series: Dict[str, Any] | None,
    jellyfin_data: Dict[str, dict] | None,
    existing_episodes_by_path: Dict[str, Any],
    existing_series_data: Dict[str, Any] | None = None,
    offline: bool = False,
    metadata_only: bool = False,
    hint_episode_number: int | None = None,
) -> Dict[str, Any]:
    """Per-episode metadata matching against the TMDB episode list.

    Attempts to match a local video file to a TMDB episode using, in order:
    the existing cached identifier, the parsed SxxExx pattern, a placeholder
    episode from a previous scan, the TMDB episode number, and finally a
    substring match on the episode name.

    Args:
        episode_file: ``Path`` to the local video file.
        season_name: Season folder name (e.g. ``"Season 1"``).
        series_directory: Top-level series directory.
        series_data: Full series data dictionary (mutated in-place for
            Jellyfin IDs).
        season_metadata: Season-level metadata dictionary.
        tmdb_episodes: List of TMDB episode dictionaries for this season.
        tmdb_series: TMDB series data (may be ``None``).
        jellyfin_data: Jellyfin sync data (may be ``None``).
        existing_episodes_by_path: Path → episode-dict lookup from existing
            data.
        existing_series_data: Previously indexed series data (may be
            ``None``).
        offline: When ``True``, skip network calls.
        metadata_only: When ``True``, read ``date_added`` from the existing
            record instead of the filesystem.

    Returns:
        The fully resolved episode dictionary.
    """
    episode_path = str(episode_file.absolute())
    episode_name = episode_file.name

    tmdb_episode_identifier = None
    tmdb_name = None
    tmdb_number = None
    air_date = ""
    runtime = 0
    jellyfin_id = ""

    existing_episode = existing_episodes_by_path.get(episode_path)
    cached_tmdb_episode_identifier = (
        existing_episode.get("tmdb_episode_identifier")
        or existing_episode.get("tmdb_identifier")
        if existing_episode
        else None
    )
    if existing_episode:
        tmdb_episode_identifier = cached_tmdb_episode_identifier or ""
        tmdb_name = existing_episode.get("tmdb_name")
        tmdb_number = existing_episode.get("tmdb_number")
        air_date = existing_episode.get("air_date", "")
        runtime = existing_episode.get("runtime", 0)
        jellyfin_id = existing_episode.get("jellyfin_id", "")
        logger.debug(f"Reusing existing metadata for '{episode_name}'")
        # Fill in missing tmdb_name from TMDB episode list when we have
        # a tmdb_number but no cached name.
        if tmdb_name is None and tmdb_number is not None and tmdb_episodes:
            for tmdb_ep in tmdb_episodes:
                if tmdb_ep.get("episode_number") == tmdb_number:
                    tmdb_name = tmdb_ep.get("name")
                    if not tmdb_episode_identifier:
                        tmdb_episode_identifier = str(tmdb_ep.get("id", ""))
                    if not air_date:
                        air_date = tmdb_ep.get("air_date", "")
                    if not runtime:
                        runtime = tmdb_ep.get("runtime", 0)
                    break
        if tmdb_number is None:
            if cached_tmdb_episode_identifier and tmdb_episodes:
                for tmdb_ep in tmdb_episodes:
                    if str(tmdb_ep.get("id")) == str(cached_tmdb_episode_identifier):
                        tmdb_number = tmdb_ep.get("episode_number")
                        if not tmdb_name:
                            tmdb_name = tmdb_ep.get("name")
                        if not air_date:
                            air_date = tmdb_ep.get("air_date", "")
                        if not runtime:
                            runtime = tmdb_ep.get("runtime", 0)
                        break
            if tmdb_number is None:
                if hint_episode_number is not None and hint_episode_number > 0:
                    tmdb_number = hint_episode_number
                else:
                    parsed = _parse_episode_number(episode_name)
                    if parsed:
                        _, parsed_num = parsed
                        tmdb_number = parsed_num
                if tmdb_number is not None and tmdb_episodes:
                    for tmdb_ep in tmdb_episodes:
                        if tmdb_ep.get("episode_number") == tmdb_number:
                            if not tmdb_episode_identifier:
                                tmdb_episode_identifier = str(tmdb_ep.get("id", ""))
                            if not tmdb_name:
                                tmdb_name = tmdb_ep.get("name")
                            if not air_date:
                                air_date = tmdb_ep.get("air_date", "")
                            if not runtime:
                                runtime = tmdb_ep.get("runtime", 0)
                            break
                else:
                    lookup_name = episode_file.stem.lower()
                    for tmdb_ep in tmdb_episodes:
                        tmdb_episode_name = str(tmdb_ep.get("name") or "").lower()
                        if tmdb_episode_name and tmdb_episode_name in lookup_name:
                            tmdb_episode_identifier = str(tmdb_ep.get("id", ""))
                            tmdb_name = tmdb_ep.get("name")
                            tmdb_number = tmdb_ep.get("episode_number")
                            air_date = tmdb_ep.get("air_date", "")
                            runtime = tmdb_ep.get("runtime", 0)
                            logger.debug(
                                f"Matched '{episode_name}' by parsed substring: "
                                f"'{tmdb_episode_name}' -> TMDB Name: '{tmdb_name}'"
                            )
                            break
    else:
        # Check if there is an existing placeholder in this season in existing_series_data
        placeholder_episode = None
        if hint_episode_number is not None and hint_episode_number > 0:
            parsed = (0, hint_episode_number)
        else:
            parsed = _parse_episode_number(episode_name)
        if (
            parsed
            and existing_series_data
            and season_name in existing_series_data.get("seasons", {})
        ):
            _, episode_number = parsed
            for ep in existing_series_data["seasons"][season_name].get("episodes", []):
                if not ep.get("path") and ep.get("tmdb_number") == episode_number:
                    placeholder_episode = ep
                    break

        if placeholder_episode:
            tmdb_episode_identifier = placeholder_episode.get(
                "tmdb_episode_identifier"
            ) or placeholder_episode.get("tmdb_identifier")
            tmdb_name = placeholder_episode.get("tmdb_name")
            tmdb_number = placeholder_episode.get("tmdb_number")
            air_date = placeholder_episode.get("air_date", "")
            runtime = placeholder_episode.get("runtime", 0)
            jellyfin_id = placeholder_episode.get("jellyfin_id", "")
            logger.info(
                f"Matched '{episode_name}' to existing placeholder episode S{season_name} E{tmdb_number}"
            )
        elif parsed:
            _, episode_number = parsed
            tmdb_number = episode_number
            for tmdb_episode in tmdb_episodes:
                if tmdb_episode.get("episode_number") == episode_number:
                    tmdb_episode_identifier = str(tmdb_episode.get("id", ""))
                    tmdb_name = tmdb_episode.get("name")
                    tmdb_number = tmdb_episode.get("episode_number")
                    air_date = tmdb_episode.get("air_date", "")
                    runtime = tmdb_episode.get("runtime", 0)
                    logger.debug(
                        f"Matched '{episode_name}' by parsed episode number: "
                        f"{episode_number} -> TMDB Name: '{tmdb_name}'"
                    )
                    break
        else:
            lookup_name = episode_file.stem.lower()
            for tmdb_episode in tmdb_episodes:
                tmdb_episode_name = str(tmdb_episode.get("name") or "").lower()
                if tmdb_episode_name and tmdb_episode_name in lookup_name:
                    tmdb_episode_identifier = str(tmdb_episode.get("id", ""))
                    tmdb_name = tmdb_episode.get("name")
                    tmdb_number = tmdb_episode.get("episode_number")
                    air_date = tmdb_episode.get("air_date", "")
                    runtime = tmdb_episode.get("runtime", 0)
                    logger.debug(
                        f"Matched '{episode_name}' by parsed substring: "
                        f"'{tmdb_episode_name}' -> TMDB Name: '{tmdb_name}'"
                    )
                    break

    if metadata_only:
        ctime = existing_episode.get("date_added") or 0 if existing_episode else 0
    else:
        try:
            ctime = os.path.getctime(episode_path)
        except OSError as error_instance:
            logger.debug(f"Could not read ctime for {episode_path}: {error_instance}")
            ctime = 0

    jellyfin_id = ""
    new_series_jf_id = ""
    new_season_jf_id = ""
    if not offline:
        jellyfin_id, new_series_jf_id, new_season_jf_id = _resolve_episode_jellyfin_id(
            episode_path=episode_path,
            episode_name=episode_name,
            episode_file=episode_file,
            tmdb_episode_identifier=tmdb_episode_identifier,
            tmdb_name=tmdb_name,
            tmdb_number=tmdb_number,
            season_name=season_name,
            series_directory=series_directory,
            series_data=series_data,
            season_metadata=season_metadata,
            tmdb_series=tmdb_series,
            jellyfin_data=jellyfin_data,
        )

    if new_series_jf_id and not series_data["metadata"].get("jellyfin_id"):
        series_data["metadata"]["jellyfin_id"] = new_series_jf_id
    if new_season_jf_id and not season_metadata.get("jellyfin_id"):
        season_metadata["jellyfin_id"] = new_season_jf_id

    series_metadata = series_data["metadata"]
    if (
        not series_metadata.get("jellyfin_id")
        and series_data.get("_tmdb_series_id")
        and jellyfin_data
        and not offline
    ):
        series_metadata["jellyfin_id"] = jellyfin_data.get("tmdb_series_map", {}).get(
            str(series_data["_tmdb_series_id"]), ""
        )

    res = {
        "name": tmdb_name
        or (
            f"S{int(season_match.group()):02d}E{tmdb_number:02d}"
            if tmdb_number is not None
            and (season_match := re.search(r"\d+", season_name))
            else episode_name
        ),
        "path": episode_path,
        "tmdb_identifier": tmdb_episode_identifier,
        "tmdb_episode_identifier": tmdb_episode_identifier,
        "tmdb_name": tmdb_name,
        "tmdb_number": tmdb_number,
        "air_date": air_date,
        "runtime": runtime or 0,
        "jellyfin_id": jellyfin_id,
        "watched": existing_episode.get("watched", False)
        if existing_episode
        else False,
        "date_added": ctime,
    }

    if existing_episode:
        res["video_codec"] = existing_episode.get("video_codec")
        res["resolution"] = existing_episode.get("resolution")
        res["audio_tracks"] = existing_episode.get("audio_tracks")
        res["subtitle_tracks"] = existing_episode.get("subtitle_tracks")
        if existing_episode.get("versions"):
            res["versions"] = [
                v
                for v in existing_episode["versions"]
                if v.get("path") and Path(v["path"]).exists()
            ]

    # Preserve existing MyAnimeList mapping if it exists
    if existing_episode:
        res["myanimelist_anime_id"] = existing_episode.get("myanimelist_anime_id")
        res["myanimelist_episode_number"] = existing_episode.get(
            "myanimelist_episode_number"
        )
    elif placeholder_episode:
        res["myanimelist_anime_id"] = placeholder_episode.get("myanimelist_anime_id")
        res["myanimelist_episode_number"] = placeholder_episode.get(
            "myanimelist_episode_number"
        )

    # Automatically map to MyAnimeList if the season has a myanimelist_id
    mal_id = season_metadata.get("myanimelist_id")
    if mal_id and not res.get("myanimelist_anime_id"):
        res["myanimelist_anime_id"] = mal_id
        # Use tmdb_number, or fallback to parsed episode number from name
        ep_num = res.get("tmdb_number")
        if ep_num is None:
            parsed = _parse_episode_number(episode_name)
            if parsed:
                _, ep_num = parsed
        res["myanimelist_episode_number"] = ep_num

    return res
