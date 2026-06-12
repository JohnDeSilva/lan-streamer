# Backward-compatible queries module re-exporting split sub-modules.
from typing import Any

from lan_streamer.db.connection import get_session as _get_session
from lan_streamer.db.queries_file_discovery import (
    natural_sort_key,
    _build_episode_dict,
    _build_season_dict,
    _build_series_dict,
    _build_movie_dict,
    update_episode_path,
    is_movie,
    delete_series_record,
    delete_episode_record,
)
from lan_streamer.db.queries_technical_extraction import (
    get_items_missing_runtime,
    update_item_runtime,
    update_items_runtime_batch,
    has_tech_and_metadata,
)
from lan_streamer.db.queries_playback import (
    update_episode_watched_status,
    update_episode_playback_position,
    get_episode_playback_position,
    update_season_watched_status,
    update_series_watched_status,
    get_next_episode,
    get_combined_next_up,
    get_combined_recently_added,
    get_combined_smart_row,
    _trigger_mal_push_async,
)
from lan_streamer.db.queries_config import (
    get_app_config,
    set_app_config,
    get_all_app_configs,
    bulk_set_app_configs,
    get_secret,
    get_all_secrets,
    set_secret,
    get_series_pref,
    set_series_pref,
)


def get_session() -> Any:
    return _get_session()


__all__ = [
    "get_session",
    "natural_sort_key",
    "_build_episode_dict",
    "_build_season_dict",
    "_build_series_dict",
    "_build_movie_dict",
    "update_episode_path",
    "is_movie",
    "delete_series_record",
    "delete_episode_record",
    "get_items_missing_runtime",
    "update_item_runtime",
    "update_items_runtime_batch",
    "has_tech_and_metadata",
    "update_episode_watched_status",
    "update_episode_playback_position",
    "get_episode_playback_position",
    "update_season_watched_status",
    "update_series_watched_status",
    "get_next_episode",
    "get_combined_next_up",
    "get_combined_recently_added",
    "get_combined_smart_row",
    "_trigger_mal_push_async",
    "get_app_config",
    "set_app_config",
    "get_all_app_configs",
    "bulk_set_app_configs",
    "get_secret",
    "get_all_secrets",
    "set_secret",
    "get_series_pref",
    "set_series_pref",
]
