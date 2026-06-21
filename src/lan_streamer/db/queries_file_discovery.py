"""
Backward-compatibility shim for ``lan_streamer.db.queries_file_discovery``.

This module has been renamed to ``lan_streamer.db.orm_serialization``.
All public symbols are re-exported from the new location.  New code should
import directly from ``lan_streamer.db.orm_serialization``.
"""

from lan_streamer.db.orm_serialization import (  # noqa: F401
    _build_episode_dict,
    _build_season_dict,
    _build_series_dict,
    _build_movie_dict,
    update_episode_path,
    is_movie,
    delete_series_record,
    delete_episode_record,
)
