"""Backward-compatibility re-export shim.

Prefer importing from the specific sub-modules:

* :mod:`lan_streamer.services.metadata_common` — shared helpers
* :mod:`lan_streamer.services.metadata_movie` — movie-only helpers
* :mod:`lan_streamer.services.metadata_tv` — TV-only helpers
"""

from lan_streamer.services.metadata_common import (  # noqa: F401
    _build_locked_movie_tmdb_stub,
    _build_locked_tv_tmdb_stub,
    _merge_season_episodes,
    _resolve_existing_jellyfin_id,
)
from lan_streamer.services.metadata_movie import (  # noqa: F401
    _apply_existing_movie_metadata,
    _apply_tmdb_movie_data,
    _build_movie_metadata_defaults,
    _resolve_movie_jellyfin_id,
    _resolve_movie_poster,
)
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
