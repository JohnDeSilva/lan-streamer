"""Backward-compatibility re-export shim.

Prefer importing from:

* :mod:`lan_streamer.services.metadata_series` — series-level helpers
* :mod:`lan_streamer.services.metadata_episode` — season/episode processing
"""

from lan_streamer.services.metadata_series import (  # noqa: F401
    _build_existing_episodes_index,
    _build_series_metadata_defaults,
    _detect_new_series_files,
    _process_series_metadata,
    _resolve_episode_jellyfin_id,
    _resolve_series_poster,
)
from lan_streamer.services.metadata_episode import (  # noqa: F401
    _process_episode_file,
    _process_season_metadata,
)
