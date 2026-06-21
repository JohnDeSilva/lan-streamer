"""Metadata updates service — manages series/season metadata refresh, data cleaning, and change detection."""

import logging
import re
from pathlib import Path
from typing import Any, Dict

from lan_streamer.db.utils import natural_sort_key
from lan_streamer.scanner.parser import find_video_files

logger = logging.getLogger("lan_streamer.services.metadata_updates")


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


def build_existing_episodes_index(
    existing_series_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Builds a path → episode-dict lookup from an existing series data structure."""
    index: Dict[str, Any] = {}
    for season in existing_series_data.get("seasons", {}).values():
        for episode in season.get("episodes", []):
            index[episode["path"]] = episode
    return index


def detect_new_series_files(
    series_directory: Path,
    existing_episodes_by_path: Dict[str, Any],
) -> bool:
    """Returns True when at least one video file inside *series_directory* is not
    present in *existing_episodes_by_path*, indicating the library has grown."""
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
