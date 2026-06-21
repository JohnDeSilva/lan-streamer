"""File discovery service — filesystem scanning, file detection, and change detection."""

import logging
import re
from pathlib import Path
from typing import Any

from lan_streamer.scanner.parser import VIDEO_EXTENSIONS, find_video_files

logger = logging.getLogger("lan_streamer.services.file_discovery")


class LibraryDict(dict[str, Any]):
    """Dictionary subclass to hold library contents and track unavailable directories.

    This is used as the return type for library scans, carrying both the
    discovered media items and a record of any root directories that could
    not be accessed during the scan.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the LibraryDict and set up unavailable directories tracking.

        Args:
            *args: Positional arguments forwarded to ``dict``.
            **kwargs: Keyword arguments forwarded to ``dict``.
        """
        super().__init__(*args, **kwargs)
        self.unavailable_directories: list[str] = []


def has_season_subdirectories(directory: Path) -> bool:
    """Check if a directory contains season-like subdirectories.

    Returns ``True`` if *directory* contains at least one subdirectory whose
    name looks like a season folder (contains ``'season'``, ``'special'``,
    ``'extra'``, ``'featurette'``, ``'bonus'``, ``'shorts'``, or any digit
    sequence). This allows series folders with no local video files to still
    be indexed so that placeholder episodes can be seeded into the database.

    Args:
        directory: The directory to scan for season-like subdirectories.

    Returns:
        ``True`` if a season-like subdirectory is found, ``False`` otherwise.
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


def detect_tv_file_changes(
    season_dir: Path,
    existing_season_data: dict[str, Any],
) -> bool:
    """Compare disk video files against existing episode data to detect changes.

    Checks if files have been added, modified, or removed in a season folder
    by comparing local paths and file sizes to the pre-existing season metadata
    stored in the database.

    Args:
        season_dir: The season directory on disk to inspect.
        existing_season_data: The existing season metadata from the database,
            containing episode entries with ``path`` and ``size_bytes`` keys.

    Returns:
        ``True`` if changes are detected (files added, removed, or modified),
        ``False`` if the season appears unchanged.
    """
    existing_episodes = existing_season_data.get("episodes", [])
    existing_by_path = {
        episode["path"]: episode for episode in existing_episodes if episode.get("path")
    }

    try:
        disk_files = [
            file_path
            for file_path in season_dir.iterdir()
            if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS
        ]
    except PermissionError, FileNotFoundError:
        return True

    # Filter out episodes without paths (e.g., placeholder episodes).
    existing_physical_episodes = [
        episode for episode in existing_episodes if episode.get("path")
    ]
    if len(disk_files) != len(existing_physical_episodes):
        return True

    for disk_file in disk_files:
        path_str = str(disk_file.absolute())
        if path_str not in existing_by_path:
            return True

        # Check for size difference.
        existing_entry = existing_by_path[path_str]
        sizes: list[int] = [existing_entry.get("size_bytes")]
        if existing_entry.get("versions"):
            for version in existing_entry["versions"]:
                if version.get("path") == path_str:
                    sizes.append(version.get("size_bytes"))
        sizes = [size for size in sizes if size is not None]

        try:
            disk_size = disk_file.stat().st_size
        except Exception:
            return True

        if not any(size == disk_size for size in sizes):
            return True

    return False


def detect_movie_file_changes(
    movie_dir: Path,
    existing_movie_data: dict[str, Any],
) -> bool:
    """Compare disk video files against existing movie data to detect changes.

    Checks if files for a movie have been added, removed, or modified in its
    folder by comparing paths and file sizes to existing version metadata.

    Args:
        movie_dir: The movie directory on disk to inspect.
        existing_movie_data: The existing movie metadata from the database,
            containing version entries with ``path`` and ``size_bytes`` keys.

    Returns:
        ``True`` if changes are detected, ``False`` if the movie appears
        unchanged.
    """
    try:
        disk_files = find_video_files(movie_dir)
    except Exception:
        return True

    existing_versions = existing_movie_data.get("versions", [])
    existing_by_path = {
        version["path"]: version for version in existing_versions if version.get("path")
    }
    if not existing_by_path and existing_movie_data.get("path"):
        existing_by_path[existing_movie_data["path"]] = existing_movie_data

    if len(disk_files) != len(existing_by_path):
        return True

    for disk_file in disk_files:
        path_str = str(disk_file.absolute())
        if path_str not in existing_by_path:
            return True

        existing_entry = existing_by_path[path_str]
        sizes = [existing_entry.get("size_bytes")]
        sizes = [size for size in sizes if size is not None]

        try:
            disk_size = disk_file.stat().st_size
        except Exception:
            return True

        if not any(size == disk_size for size in sizes):
            return True

    return False
