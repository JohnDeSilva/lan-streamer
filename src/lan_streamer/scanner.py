import os
import logging
import re
from pathlib import Path
from typing import Dict, List, Any
from .tmdb import tmdb_client

logger = logging.getLogger(__name__)

# Video file extensions we support
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"}

# Regex to extract S01E02 style episode numbers from filenames
_EPISODE_REGEX = re.compile(r"[Ss](\d+)[Ee](\d+)")


def _parse_episode_num(filename: str) -> tuple[int, int] | None:
    """Returns (season_num, episode_num) parsed from filename, or None."""
    match = _EPISODE_REGEX.search(filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def clean_series_data(series_data: Dict[str, Any]) -> Dict[str, Any]:
    """Cleans up temporary tmdb variables from series data."""
    clean_seasons = {}
    for season, season_data in series_data.get("seasons", {}).items():
        if season_data["episodes"]:
            # Sort episodes alphabetically
            season_data["episodes"].sort(key=lambda x: x["name"])
            season_data.pop("_tmdb_episodes", None)
            clean_seasons[season] = season_data

    if clean_seasons:
        series_data["seasons"] = clean_seasons
        series_data.pop("_tmdb_seasons", None)
        series_data.pop("_tmdb_series_id", None)
        return series_data
    return None


def scan_directories(
    root_dirs: List[str],
    existing_library: Dict[str, Any] = None,
    jellyfin_data: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Scans root directories and matches with TMDB to pull metadata.
    Watch history (watched status) is handled separately via Jellyfin sync.
    """
    library = {}
    existing_library = existing_library or {}

    logger.info(f"Starting directory scan. Root directories: {root_dirs}")

    for root_dir in root_dirs:
        logger.info(f"Scanning root directory: {root_dir}")
        root_path = Path(root_dir)
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

        for series_dir in series_dirs:
            series_name = series_dir.name

            # Check if we have an existing manual match for THIS SPECIFIC folder name
            existing_series = existing_library.get(series_name)
            tmdb_series = None
            is_locked = False

            if existing_series and existing_series.get("metadata", {}).get(
                "locked_metadata"
            ):
                tmdb_id = existing_series["metadata"].get("tmdb_id")
                if tmdb_id:
                    logger.info(
                        f"Using locked TMDB metadata for '{series_name}' (ID: {tmdb_id})"
                    )
                    # Use existing metadata exactly as is
                    tmdb_series = {
                        "id": tmdb_id,
                        "name": series_name,  # Avoid full metadata fetch in scan_series
                        "overview": existing_series["metadata"].get("overview", ""),
                        "poster_path": existing_series["metadata"].get(
                            "poster_path", ""
                        ),
                        "_is_prefetched": True,  # Signal to scan_series to not re-fetch
                    }
                    is_locked = True
                else:
                    is_locked = False
            else:
                is_locked = False

            series_data = scan_series(
                series_dir,
                tmdb_series=tmdb_series,
                jellyfin_data=jellyfin_data,
            )
            if is_locked:
                series_data["metadata"]["locked_metadata"] = True

            cleaned = clean_series_data(series_data)
            if not cleaned:
                continue

            # Identify if this series matches something already in our library
            match_key = None
            tmdb_id = cleaned["metadata"].get("tmdb_id")

            if tmdb_id:
                for key, existing in library.items():
                    if existing["metadata"].get("tmdb_id") == tmdb_id:
                        match_key = key
                        break

            if not match_key and series_name in library:
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

                        # Re-sort episodes
                        existing_episodes.sort(key=lambda x: x["name"])
                    else:
                        existing["seasons"][season_name] = season_data
            else:
                library[series_name] = cleaned

    return library


def scan_series(
    series_dir: Path,
    tmdb_series: Dict[str, Any] = None,
    jellyfin_data: Dict[str, dict] = None,
) -> Dict[str, Any]:
    """
    Scans a single series directory and fetches metadata from TMDB.
    If tmdb_series is provided (e.g. from a manual match), it uses that ID
    instead of searching.
    """
    series_name = series_dir.name

    # If we only have an ID (from manual match), fetch full metadata
    if tmdb_series and "name" not in tmdb_series and "id" in tmdb_series:
        full = tmdb_client.get_series_by_id(tmdb_series["id"])
        if full:
            tmdb_series = full

    if not tmdb_series:
        tmdb_series = tmdb_client.search_series(series_name)

    series_metadata: Dict[str, Any] = {
        "tmdb_id": "",
        "overview": "",
        "poster_path": "",
        "jellyfin_id": "",
    }
    tmdb_seasons: list = []

    if tmdb_series:
        tmdb_id = str(tmdb_series.get("id") or "")
        series_metadata["tmdb_id"] = tmdb_id
        series_metadata["overview"] = tmdb_series.get("overview", "")
        series_metadata["jellyfin_id"] = ""

        # Artwork — TMDB returns a poster_path fragment
        poster_path = tmdb_series.get("poster_path") or ""
        if poster_path:
            # If it's prefetched, poster_path might already be a local path
            if tmdb_series.get("_is_prefetched") and not poster_path.startswith("/"):
                series_metadata["poster_path"] = poster_path
            else:
                series_metadata["poster_path"] = tmdb_client.download_image(
                    poster_path, f"tmdb_series_{tmdb_id}"
                )
        else:
            series_metadata["poster_path"] = ""

        if tmdb_id:
            tmdb_seasons = tmdb_client.get_seasons(tmdb_id)

    series_data = {
        "metadata": series_metadata,
        "seasons": {},
        "_tmdb_seasons": tmdb_seasons,
        "_tmdb_series_id": series_metadata.get("tmdb_id"),
        "_jellyfin_id": "",  # To be filled from first matched episode
    }

    for season_dir in series_dir.iterdir():
        if not season_dir.is_dir() or season_dir.name.startswith("."):
            continue

        season_name = season_dir.name
        season_metadata: Dict[str, Any] = {
            "jellyfin_id": "",
        }
        tmdb_episodes: list = []

        # Extract season number from directory name
        season_num_match = re.search(r"\d+", season_name)
        season_idx = int(season_num_match.group()) if season_num_match else -1

        # Try to find matching season in tmdb_seasons
        matched_tmdb_season = None
        for tmdb_season in series_data["_tmdb_seasons"]:
            if (
                tmdb_season.get("season_number") == season_idx
                or tmdb_season.get("name") == season_name
            ):
                matched_tmdb_season = tmdb_season
                break

        if matched_tmdb_season and series_data["_tmdb_series_id"]:
            season_tmdb_id = matched_tmdb_season.get("id")
            season_metadata["tmdb_id"] = str(season_tmdb_id) if season_tmdb_id else ""

            # Fetch artwork for the season (TMDB: poster_path fragment)
            artwork = matched_tmdb_season.get("poster_path") or ""
            if artwork and season_tmdb_id:
                season_metadata["poster_path"] = tmdb_client.download_image(
                    artwork, f"tmdb_season_{season_tmdb_id}"
                )
            else:
                season_metadata["poster_path"] = ""

            # Fetch episodes for this season number
            tmdb_episodes = tmdb_client.get_episodes(
                series_data["_tmdb_series_id"], season_idx
            )

        series_data["seasons"][season_name] = {
            "metadata": season_metadata,
            "episodes": [],
            "_tmdb_episodes": tmdb_episodes,
        }

        for episode_file in season_dir.iterdir():
            if (
                episode_file.is_file()
                and episode_file.suffix.lower() in VIDEO_EXTENSIONS
            ):
                episode_path = str(episode_file.absolute())
                episode_name = episode_file.name

                tmdb_episode_id = None
                tmdb_name = None
                tmdb_number = None

                # Match TMDB episode by S01E02 pattern in filename
                parsed = _parse_episode_num(episode_name)
                if parsed:
                    _, ep_num = parsed
                    for tmdb_ep in series_data["seasons"][season_name][
                        "_tmdb_episodes"
                    ]:
                        if tmdb_ep.get("episode_number") == ep_num:
                            tmdb_episode_id = str(tmdb_ep.get("id", ""))
                            tmdb_name = tmdb_ep.get("name")
                            tmdb_number = tmdb_ep.get("episode_number")
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
                jellyfin_id = jellyfin_info["id"] if jellyfin_info else ""

                # Fallback correlation by TMDB Episode ID
                if not jellyfin_id and tmdb_episode_id and jellyfin_data:
                    jellyfin_id = jellyfin_data.get("tmdb_episode_map", {}).get(
                        str(tmdb_episode_id), ""
                    )

                # Fallback correlation by Series Name + Episode Name
                if not jellyfin_id and jellyfin_data:
                    name_map = jellyfin_data.get("name_map", {})
                    # Try matching by (Series Name, Episode Name)
                    # We use the cleaned TMDB names if available, otherwise file names
                    lookup_series = (
                        tmdb_series.get("name") if tmdb_series else series_dir.name
                    ).lower()
                    lookup_episode = (
                        tmdb_name if tmdb_name else episode_file.stem
                    ).lower()

                    jellyfin_id = name_map.get((lookup_series, lookup_episode), "")

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

                # Fallback correlation for series by TMDB Series ID
                if (
                    not series_data["metadata"]["jellyfin_id"]
                    and series_data["_tmdb_series_id"]
                    and jellyfin_data
                ):
                    series_data["metadata"]["jellyfin_id"] = jellyfin_data.get(
                        "tmdb_series_map", {}
                    ).get(str(series_data["_tmdb_series_id"]), "")

                series_data["seasons"][season_name]["episodes"].append(
                    {
                        "name": episode_name,
                        "path": episode_path,
                        "tmdb_id": tmdb_episode_id,
                        "tmdb_name": tmdb_name,
                        "tmdb_number": tmdb_number,
                        "jellyfin_id": jellyfin_id,
                        "watched": False,
                        "date_added": ctime,
                    }
                )

    return series_data
