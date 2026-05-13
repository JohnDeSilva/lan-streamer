import os
import logging
import re
from pathlib import Path
from typing import Dict, List, Any
from .tmdb import tmdb_client
from .db import natural_sort_key

logger = logging.getLogger(__name__)

# Video file extensions we support
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"}

# Regex to extract S01E02 style episode numbers from filenames
_EPISODE_REGEX = re.compile(r"[Ss](\d+)[Ee](\d+)")
# Regex to extract season number from folder names (e.g. "Season 1")
_SEASON_REGEX = re.compile(r"[Ss]eason\s*(\d+)", re.IGNORECASE)


def _parse_episode_number(filename: str) -> tuple[int, int] | None:
    """Returns (season_num, episode_num) parsed from filename, or None."""
    match = _EPISODE_REGEX.search(filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _parse_season_number(season_name: str) -> int | None:
    """Returns season number parsed from folder name (e.g. 'Season 1'), or None."""
    match = _SEASON_REGEX.search(season_name)
    if match:
        return int(match.group(1))
    return None


def clean_series_data(series_data: Dict[str, Any]) -> Dict[str, Any] | None:
    """Cleans up temporary tmdb variables from series data."""
    clean_seasons = {}
    for season, season_data in series_data.get("seasons", {}).items():
        if season_data["episodes"]:
            # Sort episodes naturally
            season_data["episodes"].sort(key=lambda x: natural_sort_key(x["name"]))
            season_data.pop("_tmdb_episodes", None)
            clean_seasons[season] = season_data

    if clean_seasons:
        series_data["seasons"] = clean_seasons
        series_data.pop("_tmdb_seasons", None)
        series_data.pop("_tmdb_series_id", None)
        return series_data
    return None


def scan_directories(
    root_directories: List[str],
    existing_library: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, Any] | None = None,
    callback: Any = None,
    force_refresh: bool = False,
    cleanup: bool = False,
) -> Dict[str, Any]:
    """
    Scans root directories and matches with TMDB to pull metadata.
    Watch history (watched status) is handled separately via Jellyfin sync.
    """
    library: Dict[str, Any] = {}
    existing_library = existing_library or {}

    logger.info(f"Starting directory scan. Root directories: {root_directories}")

    for root_directory in root_directories:
        logger.info(f"Scanning root directory: {root_directory}")
        root_path = Path(root_directory)
        if not root_path.exists():
            continue
        if not root_path.is_dir():
            continue

        # Sort series directories by mtime (newest first)
        series_dirs = sorted(
            [
                directory
                for directory in root_path.iterdir()
                if directory.is_dir() and not directory.name.startswith(".")
            ],
            key=lambda directory: directory.stat().st_mtime,
            reverse=True,
        )

        for series_directory in series_dirs:
            series_name = series_directory.name

            # Check if we have an existing manual match for THIS SPECIFIC folder name
            existing_series = existing_library.get(series_name)
            tmdb_series = None
            is_locked = False
            existing_jellyfin_id = None

            if existing_series:
                existing_jellyfin_id = existing_series.get("metadata", {}).get(
                    "jellyfin_id"
                )
                if existing_series.get("metadata", {}).get("locked_metadata"):
                    tmdb_identifier = existing_series["metadata"].get("tmdb_identifier")
                    if tmdb_identifier:
                        logger.info(
                            f"Using locked TMDB metadata for '{series_name}' (ID: {tmdb_identifier})"
                        )
                        # Use existing metadata exactly as is
                        tmdb_series = {
                            "id": tmdb_identifier,
                            "name": existing_series["metadata"].get(
                                "tmdb_name", series_name
                            ),
                            "overview": existing_series["metadata"].get("overview", ""),
                            "poster_path": existing_series["metadata"].get(
                                "poster_path", ""
                            ),
                            "first_air_date": existing_series["metadata"].get(
                                "first_air_date", ""
                            ),
                            "_is_prefetched": True,
                        }
                        is_locked = True

            series_data = scan_series(
                series_directory,
                tmdb_series=tmdb_series,
                jellyfin_data=jellyfin_data,
                manual_jellyfin_id=existing_jellyfin_id,
                existing_series_data=existing_series,
                force_refresh=force_refresh,
                cleanup=cleanup,
            )
            if is_locked:
                series_data["metadata"]["locked_metadata"] = True

            cleaned = clean_series_data(series_data)
            if not cleaned:
                continue

            # Identify if this series matches something already in our library
            match_key = None
            if series_name in library:
                match_key = series_name

            if match_key:
                # Merge into existing entry
                existing = library[match_key]
                logger.info(
                    f"Merging '{series_name}' into existing series entry '{match_key}'"
                )

                for season_name, season_data in cleaned["seasons"].items():
                    if season_name in existing["seasons"]:
                        # Merge episodes
                        existing_episodes = existing["seasons"][season_name]["episodes"]
                        new_episodes = season_data["episodes"]

                        # Avoid duplicates by path or name within the same season
                        episode_paths = {
                            episode["path"] for episode in existing_episodes
                        }
                        episode_names = {
                            episode["name"] for episode in existing_episodes
                        }
                        for episode in new_episodes:
                            if (
                                episode["path"] not in episode_paths
                                and episode["name"] not in episode_names
                            ):
                                logger.debug(
                                    f"Adding episode '{episode['name']}' from '{episode['path']}'"
                                )
                                existing_episodes.append(episode)
                            elif episode["path"] not in episode_paths:
                                logger.warning(
                                    f"Skipping episode '{episode['name']}' from '{episode['path']}' because an episode with the same name already exists in this season."
                                )
                            else:
                                logger.debug(
                                    f"Skipping exact duplicate path: {episode['path']}"
                                )

                        # Re-sort episodes naturally
                        existing_episodes.sort(
                            key=lambda x: natural_sort_key(x["name"])
                        )
                    else:
                        existing["seasons"][season_name] = season_data
            else:
                library[series_name] = cleaned

            if callback:
                callback(library)

    if not cleanup and existing_library:
        for old_series_name, old_series_data in existing_library.items():
            if old_series_name not in library:
                logger.info(
                    f"Preserving missing series folder '{old_series_name}' (non-destructive)"
                )
                library[old_series_name] = old_series_data

    return library


def scan_series(
    series_directory: Path,
    tmdb_series: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, dict] | None = None,
    manual_jellyfin_id: str | None = None,
    existing_series_data: Dict[str, Any] | None = None,
    force_refresh: bool = False,
    cleanup: bool = False,
) -> Dict[str, Any]:
    """
    Scans a single series directory and fetches metadata from TMDB.
    If tmdb_series is provided (e.g. from a manual match), it uses that ID
    instead of searching.
    If manual_jellyfin_id is provided, it links to that Jellyfin item for watch sync.
    """
    series_name = series_directory.name

    series_metadata: Dict[str, Any] = {
        "tmdb_identifier": "",
        "overview": "",
        "poster_path": "",
        "tmdb_name": "",
        "first_air_date": "",
        "jellyfin_id": manual_jellyfin_id or "",
    }

    if not force_refresh and existing_series_data:
        ext_metadata = existing_series_data.get("metadata", {})
        for k, v in ext_metadata.items():
            if v:
                series_metadata[k] = v
        # Ensure manual_jellyfin_id takes precedence if provided
        if manual_jellyfin_id:
            series_metadata["jellyfin_id"] = manual_jellyfin_id

    # If we only have an ID (from manual match), fetch full metadata
    if tmdb_series and "name" not in tmdb_series and "id" in tmdb_series:
        full = tmdb_client.get_series_by_id(tmdb_series["id"])
        if full:
            tmdb_series = full

    if not tmdb_series:
        if series_metadata["tmdb_identifier"]:
            tmdb_series = {
                "id": series_metadata["tmdb_identifier"],
                "name": series_metadata["tmdb_name"],
                "overview": series_metadata["overview"],
                "poster_path": series_metadata["poster_path"],
                "first_air_date": series_metadata.get("first_air_date", ""),
            }
        else:
            tmdb_series = tmdb_client.search_series(series_name)

    # Pre-index existing episodes for reuse (e.g. watched status, metadata)
    existing_eps_by_path = {}
    if existing_series_data:
        for season in existing_series_data.get("seasons", {}).values():
            for ep in season.get("episodes", []):
                existing_eps_by_path[ep["path"]] = ep

    tmdb_seasons: list = []

    if tmdb_series:
        tmdb_identifier = str(tmdb_series.get("id") or "")
        series_metadata["tmdb_identifier"] = tmdb_identifier
        series_metadata["overview"] = tmdb_series.get("overview", "")
        series_metadata["tmdb_name"] = tmdb_series.get("name", "")
        series_metadata["first_air_date"] = tmdb_series.get("first_air_date", "")

        # Artwork — TMDB returns a poster_path fragment
        poster_path = tmdb_series.get("poster_path") or ""
        if poster_path:
            # If it's prefetched, poster_path might already be a local path
            if tmdb_series.get("_is_prefetched") and not poster_path.startswith("/"):
                series_metadata["poster_path"] = poster_path
            else:
                series_metadata["poster_path"] = tmdb_client.download_image(
                    poster_path, f"tmdb_series_{tmdb_identifier}"
                )
        else:
            series_metadata["poster_path"] = ""

        if tmdb_identifier:
            tmdb_seasons = tmdb_client.get_seasons(tmdb_identifier)

    # Initial Jellyfin ID lookup via TMDB ID
    if not series_metadata["jellyfin_id"] and jellyfin_data and tmdb_series:
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
        "_jellyfin_id": "",  # To be filled from first matched episode
    }

    for season_directory in series_directory.iterdir():
        if not season_directory.is_dir() or season_directory.name.startswith("."):
            continue

        season_name = season_directory.name
        season_metadata: Dict[str, Any] = {
            "jellyfin_id": "",
        }
        tmdb_episodes: list = []

        # Extract season number from directory name
        season_num_match = re.search(r"\d+", season_name)
        season_index = int(season_num_match.group()) if season_num_match else -1

        # Try to find matching season in tmdb_seasons
        matched_tmdb_season = None
        for tmdb_season in series_data["_tmdb_seasons"]:
            if (
                tmdb_season.get("season_number") == season_index
                or tmdb_season.get("name") == season_name
            ):
                matched_tmdb_season = tmdb_season
                break

        if matched_tmdb_season and series_data["_tmdb_series_id"]:
            season_tmdb_identifier = matched_tmdb_season.get("id")
            season_metadata["tmdb_identifier"] = (
                str(season_tmdb_identifier) if season_tmdb_identifier else ""
            )

            # Fetch artwork for the season (TMDB: poster_path fragment)
            artwork = matched_tmdb_season.get("poster_path") or ""
            if artwork and season_tmdb_identifier:
                season_metadata["poster_path"] = tmdb_client.download_image(
                    artwork, f"tmdb_season_{season_tmdb_identifier}"
                )
            else:
                season_metadata["poster_path"] = ""

            # Fetch episodes for this season number
            tmdb_episodes = tmdb_client.get_episodes(
                series_data["_tmdb_series_id"], season_index
            )

        series_data["seasons"][season_name] = {
            "metadata": season_metadata,
            "episodes": [],
            "_tmdb_episodes": tmdb_episodes,
        }

        for episode_file in season_directory.iterdir():
            if (
                episode_file.is_file()
                and episode_file.suffix.lower() in VIDEO_EXTENSIONS
            ):
                episode_path = str(episode_file.absolute())
                episode_name = episode_file.name

                tmdb_episode_identifier = None
                tmdb_name = None
                tmdb_number = None
                air_date = ""
                jellyfin_id = ""

                # Try to reuse existing metadata
                existing_ep = existing_eps_by_path.get(episode_path)
                if (
                    not force_refresh
                    and existing_ep
                    and existing_ep.get("tmdb_identifier")
                ):
                    tmdb_episode_identifier = existing_ep["tmdb_identifier"]
                    tmdb_name = existing_ep["tmdb_name"]
                    tmdb_number = existing_ep["tmdb_number"]
                    air_date = existing_ep.get("air_date", "")
                    jellyfin_id = existing_ep.get("jellyfin_id", "")
                    logger.debug(f"Reusing existing metadata for '{episode_name}'")
                else:
                    if existing_ep:
                        air_date = existing_ep.get("air_date", "")
                    # Match TMDB episode by S01E02 pattern in filename
                    parsed = _parse_episode_number(episode_name)
                    if parsed:
                        _, episode_number = parsed
                        for tmdb_episode in series_data["seasons"][season_name][
                            "_tmdb_episodes"
                        ]:
                            if tmdb_episode.get("episode_number") == episode_number:
                                tmdb_episode_identifier = str(
                                    tmdb_episode.get("id", "")
                                )
                                tmdb_name = tmdb_episode.get("name")
                                tmdb_number = tmdb_episode.get("episode_number")
                                air_date = tmdb_episode.get("air_date", "")
                                break
                    else:
                        # Fallback: Try to match by name if we can't parse SxxExx
                        lookup_name = episode_file.stem.lower()
                        for tmdb_episode in series_data["seasons"][season_name][
                            "_tmdb_episodes"
                        ]:
                            tmdb_ep_name = str(tmdb_episode.get("name") or "").lower()
                            if tmdb_ep_name and tmdb_ep_name in lookup_name:
                                tmdb_episode_identifier = str(
                                    tmdb_episode.get("id", "")
                                )
                                tmdb_name = tmdb_episode.get("name")
                                tmdb_number = tmdb_episode.get("episode_number")
                                air_date = tmdb_episode.get("air_date", "")
                                break

                try:
                    ctime = os.path.getctime(episode_path)
                except OSError:
                    ctime = 0

                jellyfin_path_map = (
                    jellyfin_data.get("path_map") if jellyfin_data else None
                )
                jellyfin_info = (
                    jellyfin_path_map.get(episode_path) if jellyfin_path_map else None
                )
                if not jellyfin_id and jellyfin_info:
                    jellyfin_id = jellyfin_info["id"]

                # Fallback correlation by TMDB Episode ID
                if not jellyfin_id and tmdb_episode_identifier and jellyfin_data:
                    jellyfin_id = jellyfin_data.get("tmdb_episode_map", {}).get(
                        str(tmdb_episode_identifier), ""
                    )

                # Fallback correlation by Series Name + Episode Name
                if not jellyfin_id and jellyfin_data:
                    name_map = jellyfin_data.get("name_map", {})
                    # Try matching by (Series Name, Episode Name)
                    # We use the cleaned TMDB names if available, otherwise file names
                    lookup_series = str(
                        tmdb_series.get("name")
                        if tmdb_series and tmdb_series.get("name")
                        else series_directory.name
                    ).lower()
                    lookup_episode = str(
                        tmdb_name if tmdb_name else episode_file.stem
                    ).lower()

                    jellyfin_id = name_map.get((lookup_series, lookup_episode), "")

                # Fallback correlation by Series ID + (Season, Episode) or Name
                if not jellyfin_id and series_metadata["jellyfin_id"] and jellyfin_data:
                    series_map = jellyfin_data.get("series_id_map", {}).get(
                        series_metadata["jellyfin_id"]
                    )
                    if series_map:
                        parsed = _parse_episode_number(episode_name)
                        s_num, e_num = (None, None)
                        if parsed:
                            s_num, e_num = parsed
                        elif tmdb_number is not None:
                            # Use TMDB episode number and try to parse season number from directory
                            e_num = tmdb_number
                            s_num = _parse_season_number(season_name)

                        if s_num is not None and e_num is not None:
                            jellyfin_id = series_map["episodes"].get((s_num, e_num), "")
                            if jellyfin_id:
                                logger.debug(
                                    f"Matched '{episode_name}' via Series ID map (S{s_num:02}E{e_num:02})"
                                )

                        if not jellyfin_id:
                            lookup_name = (tmdb_name or episode_file.stem).lower()
                            jellyfin_id = series_map["names"].get(lookup_name, "")
                            if jellyfin_id:
                                logger.debug(
                                    f"Matched '{episode_name}' via Series ID map name '{lookup_name}'"
                                )

                if jellyfin_id:
                    logger.info(
                        f"Matched Jellyfin ID for '{episode_name}': {jellyfin_id}"
                    )

                if jellyfin_info:
                    # Update series/season Jellyfin IDs from the episode's parent info
                    if not series_data["metadata"]["jellyfin_id"]:
                        series_data["metadata"]["jellyfin_id"] = (
                            jellyfin_info.get("series_id") or ""
                        )
                    if not season_metadata["jellyfin_id"]:
                        season_metadata["jellyfin_id"] = (
                            jellyfin_info.get("season_id") or ""
                        )

                # Fallback correlation for series by TMDB Series ID (already done at start, but kept for safety)
                if (
                    not series_metadata["jellyfin_id"]
                    and series_data["_tmdb_series_id"]
                    and jellyfin_data
                ):
                    series_metadata["jellyfin_id"] = jellyfin_data.get(
                        "tmdb_series_map", {}
                    ).get(str(series_data["_tmdb_series_id"]), "")

                series_data["seasons"][season_name]["episodes"].append(
                    {
                        "name": episode_name,
                        "path": episode_path,
                        "tmdb_identifier": tmdb_episode_identifier,
                        "tmdb_name": tmdb_name,
                        "tmdb_number": tmdb_number,
                        "air_date": air_date,
                        "jellyfin_id": jellyfin_id,
                        "watched": existing_ep.get("watched", False)
                        if existing_ep
                        else False,
                        "date_added": ctime,
                    }
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
                    ep["path"]
                    for ep in series_data["seasons"][old_season_name]["episodes"]
                }
                for old_ep in old_season_data.get("episodes", []):
                    if old_ep["path"] not in found_paths:
                        logger.info(
                            f"Preserving missing episode file '{old_ep['name']}' (non-destructive)"
                        )
                        series_data["seasons"][old_season_name]["episodes"].append(
                            old_ep
                        )
                series_data["seasons"][old_season_name]["episodes"].sort(
                    key=lambda x: natural_sort_key(x["name"])
                )

    return series_data
