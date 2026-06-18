"""
Backward-compatible shim for ui_views/dialogs/details.py.

The three dialog classes have been split into focused modules:
  - episode_details.py  → EpisodeDetailsDialog
  - movie_details.py    → MovieDetailsDialog
  - series_details.py   → SeriesDetailsDialog

All names are re-exported from here so existing import sites continue to work.
"""

from lan_streamer.ui_views.dialogs.episode_details import EpisodeDetailsDialog
from lan_streamer.ui_views.dialogs.movie_details import MovieDetailsDialog
from lan_streamer.ui_views.dialogs.series_details import SeriesDetailsDialog

__all__ = [
    "EpisodeDetailsDialog",
    "MovieDetailsDialog",
    "SeriesDetailsDialog",
]
