import os
from pathlib import Path

from lan_streamer.db.connection import (
    get_engine,
    get_session,
    get_session_factory,
    init_db,
)
from lan_streamer.db.library import (
    cleanup_library,
    get_directory_mtime,
    load_library,
    load_movie_library,
    save_directory_mtime,
    save_library,
    save_movie_data,
    save_movie_library,
    save_season_data,
)
from lan_streamer.db.models import (
    AppConfig,
    AppSecret,
    Base,
    Episode,
    Movie,
    ScannedDirectory,
    Season,
    SecretType,
    Series,
    SmartRowCache,
)
from lan_streamer.db.models_cast import (
    MediaCast,
    MediaImage,
    Person,
)
from lan_streamer.db.orm_serialization import (
    _build_episode_dict,
    _build_movie_dict,
    _build_season_dict,
    _build_series_dict,
    delete_episode_record,
    delete_series_record,
    is_movie,
    update_episode_path,
)
from lan_streamer.db.queries_cast import (
    add_media_image,
    delete_cast_for_media,
    get_cast_for_episode,
    get_cast_for_movie,
    get_cast_for_season,
    get_cast_for_series,
    get_filmography,
    get_images_for_media,
    get_or_create_person,
    get_person_by_id,
    get_person_by_tmdb_id,
    set_selected_image,
)
from lan_streamer.db.queries_config import (
    bulk_set_app_configs,
    get_all_app_configs,
    get_all_secrets,
    get_series_pref,
    set_app_config,
    set_secret,
    set_series_pref,
)
from lan_streamer.db.queries_playback import (
    get_episode_playback_position,
    update_episode_playback_position,
    update_episode_watched_status,
    update_season_watched_status,
    update_series_watched_status,
)
from lan_streamer.db.queries_technical_extraction import (
    get_all_media_items,
    get_items_missing_runtime,
    update_items_runtime_batch,
)
from lan_streamer.db.queries_ui import (
    get_combined_next_up,
    get_combined_smart_row,
    get_next_episode,
    search_media_names,
)
from lan_streamer.db.smart_row_cache import (
    compute_config_hash,
    get_affected_config_hashes_for_libraries,
    get_cached_smart_rows,
    rebuild_all_cache,
    rebuild_cache_for_config,
)
from lan_streamer.db.sync import (
    get_all_episodes_with_jellyfin_id,
    sync_watched_from_jellyfin_data,
)
from lan_streamer.db.utils import natural_sort_key
from lan_streamer.system.config import config

DB_FILE = Path(os.getenv("LAN_STREAMER_DB", config.database_path))

# Shared connection state variables accessed directly by conftest.py
_engine = None
_SessionLocal = None
_db_initialized = False
