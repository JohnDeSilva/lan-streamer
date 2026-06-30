import logging
import os
import re
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# Video file extensions we support
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"}

# Subtitle file extensions we support
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".vtt", ".sub", ".idx"}

# Regex to extract S01E02 style episode numbers from filenames
_EPISODE_REGEX = re.compile(r"[Ss](\d+)[Ee](\d+)")
# Regex to extract season number from folder names (e.g. "Season 1")
_SEASON_REGEX = re.compile(r"[Ss]eason\s*(\d+)", re.IGNORECASE)


def _parse_episode_number(filename: str) -> tuple[int, int] | None:
    """Returns (season_num, episode_num) parsed from filename, or None."""
    match = _EPISODE_REGEX.search(filename)
    if match:
        logger.debug(
            f"Parsed episode S{match.group(1)}E{match.group(2)} from '{filename}'"
        )
        return int(match.group(1)), int(match.group(2))
    return None


def _parse_season_number(season_name: str) -> int | None:
    """Returns season number parsed from folder name (e.g. 'Season 1'), or None."""
    if season_name.lower() == "specials":
        return 0
    match = _SEASON_REGEX.search(season_name)
    if match:
        logger.debug(f"Parsed season number {match.group(1)} from '{season_name}'")
        return int(match.group(1))
    return None


def _parse_movie_folder(folder_name: str) -> tuple[str, int | None]:
    """Returns (title, year) parsed from folder name like 'Avatar (2009)'."""
    match = re.search(r"\((\d{4})\)", folder_name)
    if match:
        year = int(match.group(1))
        title = folder_name[: match.start()].strip()
        return title, year
    return folder_name, None


def find_video_files(directory: Path) -> List[Path]:
    """
    Recursively finds all video files under directory using fast os.scandir traversal.
    Skips hidden folders/files starting with '.' to speed up scanning.
    """
    video_files = []
    stack = [str(directory)]
    while stack:
        curr_dir = stack.pop()
        try:
            with os.scandir(curr_dir) as it:
                for entry in it:
                    if entry.name.startswith("."):
                        continue
                    try:
                        if entry.is_file(follow_symlinks=True):
                            _, ext = os.path.splitext(entry.name)
                            if ext.lower() in VIDEO_EXTENSIONS:
                                video_files.append(Path(entry.path))
                        elif entry.is_dir(follow_symlinks=True):
                            stack.append(entry.path)
                    except OSError:
                        pass
        except OSError:
            pass
    return video_files


def has_video_files(directory: Path) -> bool:
    """Recursively checks if the directory contains any video files."""
    try:
        stack = [str(directory)]
        while stack:
            curr_dir = stack.pop()
            try:
                with os.scandir(curr_dir) as it:
                    for entry in it:
                        if entry.name.startswith("."):
                            continue
                        try:
                            if entry.is_file(follow_symlinks=True):
                                _, ext = os.path.splitext(entry.name)
                                if ext.lower() in VIDEO_EXTENSIONS:
                                    return True
                            elif entry.is_dir(follow_symlinks=True):
                                stack.append(entry.path)
                        except OSError:
                            pass
            except OSError:
                pass
    except Exception:
        pass
    return False
