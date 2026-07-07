"""File discovery service — filesystem scanning, file detection, and change detection."""

import logging
import re
from pathlib import Path

logger = logging.getLogger("lan_streamer.services.file_discovery")


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
