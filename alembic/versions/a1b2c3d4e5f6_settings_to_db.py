"""settings_to_db

Revision ID: a1b2c3d4e5f6
Revises: 90c0fcb92ee7
Create Date: 2026-06-10 14:00:00.000000

Migrates settings from config.json into the database:
  - Creates app_secrets table (one row per external service, credentials as JSON)
  - Creates app_config table (key/value store for non-secret settings)
  - Adds pref_hide_missing_future and pref_display_group_id columns to series table
  - Seeds all three from the existing config.json values when present
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Sequence, Union, Any, Dict

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = ("dd91b65c745e", "90c0fcb92ee7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONFIG_FILE = Path.home() / ".config" / "lan-streamer" / "config.json"

_BOOL_KEYS = {
    "sync_history_on_start",
    "filter_out_watched",
    "sort_descending",
    "divide_logs_by_service",
    "enable_caching",
    "use_embedded_player",
    "enable_hw_accel",
    "enable_next_episode_popup",
    "enable_combined_view",
    "check_for_updates_on_startup",
}
_INT_KEYS = {
    "vlc_buffer_ms",
    "max_log_retention_days",
    "config_backup_retention",
    "database_backup_retention",
}
_FLOAT_KEYS = {
    "watched_threshold",
    "player_overlay_opacity",
    "max_cache_size_gb",
}
_JSON_KEYS = {
    "libraries",
    "vlc_extra_args",
    "combined_views",
}


def _type_hint(key: str) -> str:
    if key in _BOOL_KEYS:
        return "bool"
    if key in _INT_KEYS:
        return "int"
    if key in _FLOAT_KEYS:
        return "float"
    if key in _JSON_KEYS:
        return "json"
    return "str"


def _encode(key: str, value: Any) -> str:
    """Serialise a Python value to the TEXT representation stored in app_config."""
    hint = _type_hint(key)
    if hint == "json":
        return json.dumps(value)
    if hint == "bool":
        return "1" if value else "0"
    return str(value)


def _load_config() -> Dict[str, Any]:
    """Return the parsed config.json, or an empty dict if it doesn't exist."""
    try:
        from alembic import context

        config_file_path_str = context.config.get_main_option("x-config-file")
        if config_file_path_str:
            config_file = Path(config_file_path_str)
        else:
            config_file = CONFIG_FILE

        if config_file.exists():
            with open(config_file, "r") as file_handle:
                return json.load(file_handle)
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Upgrade schema."""

    # ------------------------------------------------------------------
    # 1. Create app_secrets table
    # ------------------------------------------------------------------
    op.create_table(
        "app_secrets",
        sa.Column("secret_uuid", sa.String(), nullable=False),
        sa.Column("secret_type", sa.String(), nullable=False),
        sa.Column("secret", sa.String(), nullable=True, server_default="{}"),
        sa.PrimaryKeyConstraint("secret_uuid"),
        sa.UniqueConstraint("secret_type", name="uq_app_secrets_type"),
    )

    # ------------------------------------------------------------------
    # 2. Create app_config table
    # ------------------------------------------------------------------
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False, server_default="str"),
        sa.PrimaryKeyConstraint("key"),
    )

    # ------------------------------------------------------------------
    # 3. Add per-series preference columns to series table
    # ------------------------------------------------------------------
    op.add_column(
        "series",
        sa.Column(
            "pref_hide_missing_future", sa.Boolean(), nullable=True, server_default="0"
        ),
    )
    op.add_column(
        "series",
        sa.Column("pref_display_group_id", sa.String(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 4. Seed data from config.json (best-effort; skipped if file absent)
    # ------------------------------------------------------------------
    cfg = _load_config()
    if not cfg:
        return

    bind = op.get_bind()

    # 4a. Seed app_secrets -------------------------------------------------
    # Jellyfin
    jellyfin_secret: Dict[str, Any] = {
        "url": cfg.get("jellyfin_url", ""),
        "api_key": cfg.get("jellyfin_api_key", ""),
    }
    bind.execute(
        text(
            "INSERT INTO app_secrets (secret_uuid, secret_type, secret) "
            "VALUES (:uuid, :stype, :secret)"
        ),
        {
            "uuid": str(uuid.uuid4()),
            "stype": "jellyfin",
            "secret": json.dumps(jellyfin_secret),
        },
    )

    # TMDB
    tmdb_secret: Dict[str, Any] = {
        "api_key": cfg.get("tmdb_api_key", cfg.get("tvdb_api_key", "")),
    }
    bind.execute(
        text(
            "INSERT INTO app_secrets (secret_uuid, secret_type, secret) "
            "VALUES (:uuid, :stype, :secret)"
        ),
        {
            "uuid": str(uuid.uuid4()),
            "stype": "tmdb",
            "secret": json.dumps(tmdb_secret),
        },
    )

    # MyAnimeList
    mal_secret: Dict[str, Any] = {
        "client_id": cfg.get("myanimelist_client_id", ""),
        "client_secret": cfg.get("myanimelist_client_secret", ""),
        "access_token": cfg.get("myanimelist_access_token", ""),
        "refresh_token": cfg.get("myanimelist_refresh_token", ""),
        "token_expires_at": float(cfg.get("myanimelist_token_expires_at", 0.0)),
    }
    bind.execute(
        text(
            "INSERT INTO app_secrets (secret_uuid, secret_type, secret) "
            "VALUES (:uuid, :stype, :secret)"
        ),
        {
            "uuid": str(uuid.uuid4()),
            "stype": "myanimelist",
            "secret": json.dumps(mal_secret),
        },
    )

    # OpenSubtitles
    os_secret: Dict[str, Any] = {
        "username": cfg.get("opensubtitles_username", ""),
        "password": cfg.get("opensubtitles_password", ""),
        "api_key": cfg.get("opensubtitles_api_key", ""),
    }
    bind.execute(
        text(
            "INSERT INTO app_secrets (secret_uuid, secret_type, secret) "
            "VALUES (:uuid, :stype, :secret)"
        ),
        {
            "uuid": str(uuid.uuid4()),
            "stype": "opensubtitles",
            "secret": json.dumps(os_secret),
        },
    )

    # 4b. Seed app_config --------------------------------------------------
    libraries_data = cfg.get("libraries", {})
    if not libraries_data and "root_dirs" in cfg:
        libraries_data = {
            "Default": {
                "type": "tv",
                "paths": cfg["root_dirs"],
                "show_future_episodes": True,
            }
        }
    elif isinstance(libraries_data, dict):
        libraries_data = dict(libraries_data)
        for lib_name, lib_val in list(libraries_data.items()):
            if isinstance(lib_val, list):
                libraries_data[lib_name] = {
                    "type": "tv",
                    "paths": lib_val,
                    "show_future_episodes": True,
                }

    app_config_keys = {
        "libraries": libraries_data,
        "sync_history_on_start": cfg.get(
            "sync_history_on_start", cfg.get("sync_on_start", True)
        ),
        "filter_out_watched": cfg.get(
            "filter_out_watched", cfg.get("filter_unwatched", False)
        ),
        "sort_mode": cfg.get("sort_mode", "Alphabetical"),
        "sort_descending": cfg.get("sort_descending", False),
        "divide_logs_by_service": cfg.get(
            "divide_logs_by_service",
            not cfg.get("enable_global_file_logging", True),
        ),
        "enable_caching": cfg.get("enable_caching", False),
        "watched_threshold": cfg.get("watched_threshold", 0.95),
        "cache_directory": cfg.get(
            "cache_directory",
            str(Path.home() / ".config" / "lan-streamer" / "cache"),
        ),
        "use_embedded_player": cfg.get("use_embedded_player", True),
        "enable_hw_accel": cfg.get("enable_hw_accel", True),
        "vlc_extra_args": cfg.get("vlc_extra_args", []),
        "vlc_buffer_ms": cfg.get("vlc_buffer_ms", 3000),
        "player_overlay_opacity": cfg.get("player_overlay_opacity", 0.4),
        "player_overlay_color": cfg.get("player_overlay_color", "white"),
        "max_cache_size_gb": cfg.get("max_cache_size_gb", 15.0),
        "enable_next_episode_popup": cfg.get("enable_next_episode_popup", True),
        "max_log_retention_days": cfg.get("max_log_retention_days", 7),
        "backup_directory": cfg.get(
            "backup_directory",
            str(Path.home() / ".config" / "lan-streamer" / "backups"),
        ),
        "config_backup_retention": cfg.get("config_backup_retention", 7),
        "database_backup_retention": cfg.get("database_backup_retention", 7),
        "enable_combined_view": cfg.get("enable_combined_view", False),
        "combined_views": cfg.get(
            "combined_views",
            [
                {
                    "name": "All Libraries - Next Up - All",
                    "enabled": True,
                    "libraries": [],
                    "sort_by": "Next Up",
                    "filter_mode": "All",
                },
                {
                    "name": "All Libraries - Recently Added - All",
                    "enabled": True,
                    "libraries": [],
                    "sort_by": "Recently Added",
                    "filter_mode": "All",
                },
            ],
        ),
        "preferred_audio_device": cfg.get("preferred_audio_device", ""),
        "check_for_updates_on_startup": cfg.get("check_for_updates_on_startup", True),
    }

    for key, value in app_config_keys.items():
        bind.execute(
            text(
                "INSERT INTO app_config (key, value, type) VALUES (:key, :value, :type)"
            ),
            {"key": key, "value": _encode(key, value), "type": _type_hint(key)},
        )

    # 4c. Back-fill series preference columns from series_preferences ------
    series_prefs: Dict[str, Dict[str, Any]] = cfg.get("series_preferences", {})
    if series_prefs:
        for pref_key, pref_dict in series_prefs.items():
            # pref_key format: "LibraryName:SeriesName"
            if ":" not in pref_key:
                continue
            library_name, series_name = pref_key.split(":", 1)
            hide_missing = pref_dict.get("hide_missing_future", None)
            display_group = pref_dict.get("display_group_id", None)

            updates = []
            params: Dict[str, Any] = {
                "lib": library_name,
                "name": series_name,
            }
            if hide_missing is not None:
                updates.append("pref_hide_missing_future = :hide_missing")
                params["hide_missing"] = 1 if hide_missing else 0
            if display_group is not None:
                updates.append("pref_display_group_id = :display_group")
                params["display_group"] = display_group

            if updates:
                bind.execute(
                    text(
                        f"UPDATE series SET {', '.join(updates)} "
                        "WHERE library_name = :lib AND name = :name"
                    ),
                    params,
                )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("series", "pref_display_group_id")
    op.drop_column("series", "pref_hide_missing_future")
    op.drop_table("app_config")
    op.drop_table("app_secrets")
