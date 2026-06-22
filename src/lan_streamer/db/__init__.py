import os
from pathlib import Path
from lan_streamer.system.config import config

from lan_streamer.db.connection import (
    get_engine,
    get_session_factory,
    get_session,
    init_db,
)
from lan_streamer.db.utils import natural_sort_key
from lan_streamer.db.orm_serialization import (
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
    get_parent_media_name_by_path,
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
from lan_streamer.db.library import (
    load_library,
    save_library,
    load_movie_library,
    save_movie_library,
    cleanup_library,
    _apply_movie_fields,
    _cleanup_movie_library,
    _cleanup_tv_library,
    save_season_data,
    save_movie_data,
)
from lan_streamer.db.sync import (
    sync_watched_from_jellyfin_data,
    get_all_episodes_with_jellyfin_id,
    _sync_watched_by_ids,
    _sync_watched_by_paths,
    _sync_watched_by_names,
)
from lan_streamer.db.models import (
    Base,
    Series,
    Season,
    Episode,
    Movie,
    AppConfig,
    AppSecret,
    SecretType,
)

DB_FILE = Path(os.getenv("LAN_STREAMER_DB", config.database_path))

# Shared connection state variables accessed directly by conftest.py
_engine = None
_SessionLocal = None
_db_initialized = False
