import os
import logging
import re
from pathlib import Path
from typing import Dict, List, Any
from .jellyfin import jellyfin_client

logger = logging.getLogger(__name__)

# Video file extensions we support
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"}


def scan_directories(root_dirs: List[str]) -> Dict[str, Any]:
    """
    Scans root directories and matches with Jellyfin to pull metadata and watched status.
    """
    library = {}

    logger.info(f"Starting directory scan. Root directories: {root_dirs}")

    for root_dir in root_dirs:
        logger.info(f"Scanning root directory: {root_dir}")
        root_path = Path(root_dir)
        if not root_path.exists():
            continue
        if not root_path.is_dir():
            continue

        for series_dir in root_path.iterdir():
            if not series_dir.is_dir() or series_dir.name.startswith("."):
                continue

            series_name = series_dir.name
            if series_name not in library:
                jellyfin_series = jellyfin_client.search_series(series_name)
                series_metadata = {}
                jellyfin_seasons = []
                if jellyfin_series:
                    series_id = jellyfin_series.get("Id")
                    series_metadata["jellyfin_id"] = series_id
                    series_metadata["overview"] = jellyfin_series.get("Overview", "")
                    series_metadata["poster_path"] = jellyfin_client.download_image(
                        series_id
                    )
                    jellyfin_seasons = jellyfin_client.get_seasons(series_id)

                library[series_name] = {
                    "metadata": series_metadata,
                    "seasons": {},
                    "_jellyfin_seasons": jellyfin_seasons,
                    "_jellyfin_series_id": series_metadata.get("jellyfin_id"),
                }

            for season_dir in series_dir.iterdir():
                if not season_dir.is_dir() or season_dir.name.startswith("."):
                    continue

                season_name = season_dir.name
                if season_name not in library[series_name]["seasons"]:
                    season_metadata = {}
                    jellyfin_episodes = []

                    # Try to find matching season in jellyfin
                    season_num_match = re.search(r"\d+", season_name)
                    season_idx = (
                        int(season_num_match.group()) if season_num_match else -1
                    )

                    for jellyfin_season in library[series_name]["_jellyfin_seasons"]:
                        if (
                            jellyfin_season.get("IndexNumber") == season_idx
                            or jellyfin_season.get("Name") == season_name
                        ):
                            season_id = jellyfin_season.get("Id")
                            season_metadata["jellyfin_id"] = season_id
                            season_metadata["poster_path"] = (
                                jellyfin_client.download_image(season_id)
                            )
                            if library[series_name]["_jellyfin_series_id"]:
                                jellyfin_episodes = jellyfin_client.get_episodes(
                                    library[series_name]["_jellyfin_series_id"],
                                    season_id,
                                )
                            break

                    library[series_name]["seasons"][season_name] = {
                        "metadata": season_metadata,
                        "episodes": [],
                        "_jellyfin_episodes": jellyfin_episodes,
                    }

                for episode_file in season_dir.iterdir():
                    if (
                        episode_file.is_file()
                        and episode_file.suffix.lower() in VIDEO_EXTENSIONS
                    ):
                        episode_path = str(episode_file.absolute())
                        episode_name = episode_file.name

                        jellyfin_episode_id = None
                        watched = False

                        matched_jellyfin_episode = None
                        for jellyfin_episode in library[series_name]["seasons"][
                            season_name
                        ]["_jellyfin_episodes"]:
                            jellyfin_episode_path = jellyfin_episode.get("Path")
                            if (
                                jellyfin_episode_path
                                and Path(jellyfin_episode_path).name == episode_name
                            ):
                                matched_jellyfin_episode = jellyfin_episode
                                break

                        if matched_jellyfin_episode:
                            jellyfin_episode_id = matched_jellyfin_episode.get("Id")
                            user_data = matched_jellyfin_episode.get("UserData", {})
                            watched = user_data.get("Played", False)

                        # Avoid duplicates
                        existing_paths = [
                            ep["path"]
                            for ep in library[series_name]["seasons"][season_name][
                                "episodes"
                            ]
                        ]
                        if episode_path not in existing_paths:
                            try:
                                ctime = os.path.getctime(episode_path)
                            except OSError:
                                ctime = 0

                            library[series_name]["seasons"][season_name][
                                "episodes"
                            ].append(
                                {
                                    "name": episode_name,
                                    "path": episode_path,
                                    "jellyfin_id": jellyfin_episode_id,
                                    "watched": watched,
                                    "date_added": ctime,
                                }
                            )

    # Clean up empty seasons and temporary jellyfin variables
    clean_library = {}
    for series, series_data in library.items():
        clean_seasons = {}
        for season, season_data in series_data["seasons"].items():
            if season_data["episodes"]:
                # Sort episodes alphabetically
                season_data["episodes"].sort(key=lambda x: x["name"])
                season_data.pop("_jellyfin_episodes", None)
                clean_seasons[season] = season_data

        if clean_seasons:
            series_data["seasons"] = clean_seasons
            series_data.pop("_jellyfin_seasons", None)
            series_data.pop("_jellyfin_series_id", None)
            clean_library[series] = series_data

    return clean_library
