"""Shared utility functions for the db package."""

import logging
import re
from typing import Any

logger = logging.getLogger("lan_streamer.db")


def natural_sort_key(s: str | None) -> list[Any]:
    """
    Key function for natural sorting (e.g., "Season 2" < "Season 10").
    """
    if s is None:
        return []
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split("([0-9]+)", str(s))
    ]
