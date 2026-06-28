import copy
import json
import logging
from pathlib import Path
from typing import Dict, Any

CONFIG_FILE = Path.home() / ".config" / "lan-streamer" / "config.json"
logger: logging.Logger = logging.getLogger(__name__)


class Config:
    """Manages system configuration.

    Startup-critical settings (needed before the database is open) are read
    from and written to the JSON config file.  All other settings live in the
    database and are accessed via the ``db`` query helpers after
    :meth:`load_from_db` is called.

    Startup-only config-file keys
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    - ``database_path``
    - ``log_directory``
    - ``log_level``
    - ``config_backup_frequency``
    - ``database_backup_frequency``
    """

    # Single source of truth for all DB-backed setting defaults.
    # Referenced by both __init__ (to seed safe pre-DB values) and
    # load_from_db (to fill in missing rows on first run).
    _DB_DEFAULTS: Dict[str, Any] = {
        "libraries": {},
        "sync_history_on_start": True,
        "filter_out_watched": False,
        "sort_mode": "Alphabetical",
        "sort_descending": False,
        "divide_logs_by_service": False,
        "enable_caching": False,
        "watched_threshold": 0.95,
        "cache_directory": str(Path.home() / ".config" / "lan-streamer" / "cache"),
        "use_embedded_player": True,
        "fullscreen_control_bar_position": "Bottom",
        "enable_hw_accel": True,
        "vlc_extra_args": [],
        "vlc_buffer_ms": 3000,
        "player_overlay_opacity": 0.4,
        "player_overlay_color": "white",
        "max_cache_size_gb": 15.0,
        "enable_next_episode_popup": True,
        "max_log_retention_days": 7,
        "backup_directory": str(Path.home() / ".config" / "lan-streamer" / "backups"),
        "config_backup_retention": 7,
        "database_backup_retention": 7,
        "enable_combined_view": False,
        "combined_views": [
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
        "preferred_audio_device": "",
        "check_for_updates_on_startup": True,
        "database_write_timeout": 60.0,
    }

    def __init__(self) -> None:
        """Initialise startup-critical attributes and load them from the config file."""
        self._last_loaded_mtime: float = 0.0

        # --- Startup-critical (config-file backed) ---
        self.database_path: str = str(
            Path.home() / ".config" / "lan-streamer" / "library.db"
        )
        self.log_directory: str = str(Path.home() / ".config" / "lan-streamer" / "logs")
        self.log_level: str = "INFO"
        self.config_backup_frequency: int = 1
        self.database_backup_frequency: int = 1

        # --- DB-backed (seeded from _DB_DEFAULTS so the object is usable
        # before load_from_db() is called after DB initialisation) ---
        self.database_write_timeout: float = 60.0
        for key, val in copy.deepcopy(self._DB_DEFAULTS).items():
            setattr(self, key, val)

        # Convenience credential attributes — populated by load_from_db
        self.jellyfin_url: str = ""
        self.jellyfin_api_key: str = ""
        self.tmdb_api_key: str = ""
        self.myanimelist_client_id: str = ""
        self.myanimelist_client_secret: str = ""
        self.myanimelist_access_token: str = ""
        self.myanimelist_refresh_token: str = ""
        self.myanimelist_token_expires_at: float = 0.0
        self.opensubtitles_username: str = ""
        self.opensubtitles_password: str = ""
        self.opensubtitles_api_key: str = ""

        self._load_startup_config()

    # ------------------------------------------------------------------
    # Config-file loading/saving (startup-critical keys only)
    # ------------------------------------------------------------------

    def _load_startup_config(self, force: bool = False) -> None:
        """Read startup-critical settings from the config file."""
        logger.info(f"Attempting to load startup config from {CONFIG_FILE}")
        if not CONFIG_FILE.exists():
            logger.info(
                "Config file does not exist. Generating a new one with defaults."
            )
            self.save()
            return

        try:
            current_mtime = CONFIG_FILE.stat().st_mtime
            if not force and current_mtime == self._last_loaded_mtime:
                logger.debug("Config file has not changed on disk. Skipping load.")
                return

            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)

            self.database_path = str(
                Path(
                    data.get(
                        "database_path",
                        str(Path.home() / ".config" / "lan-streamer" / "library.db"),
                    )
                )
                .expanduser()
                .absolute()
            )
            self.log_directory = str(
                Path(
                    data.get(
                        "log_directory",
                        str(Path.home() / ".config" / "lan-streamer" / "logs"),
                    )
                )
                .expanduser()
                .absolute()
            )
            self.log_level = data.get("log_level", "INFO")
            self.config_backup_frequency = int(data.get("config_backup_frequency", 0))
            self.database_backup_frequency = int(
                data.get("database_backup_frequency", 0)
            )

            self._last_loaded_mtime = current_mtime
            logger.info("Startup config loaded successfully.")
        except Exception:
            logger.exception("Error loading startup config")

    def load(self, force: bool = False) -> None:
        """Reload startup-critical settings from the config file.

        DB-backed settings are loaded once at startup via :meth:`load_from_db`
        and do not need to be re-read on every call — the database is always
        the live source of truth for those values.  This method preserves the
        original public API used by callers such as
        :meth:`~lan_streamer.ui_views.controller.Controller.select_library`.
        """
        self._load_startup_config(force=force)

    def save(self) -> None:
        """Persist the startup-critical settings to the config file.

        Only the five startup keys are written; all other settings live in the
        database and are never serialised back to the file.
        """
        logger.debug(f"Attempting to save startup config to {CONFIG_FILE}")
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning(
                f"Could not create config directory {CONFIG_FILE.parent}: {exc}"
            )
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(
                    {
                        "database_path": self.database_path,
                        "log_directory": self.log_directory,
                        "log_level": self.log_level,
                        "config_backup_frequency": self.config_backup_frequency,
                        "database_backup_frequency": self.database_backup_frequency,
                    },
                    f,
                    indent=4,
                )
            if CONFIG_FILE.exists():
                self._last_loaded_mtime = CONFIG_FILE.stat().st_mtime
        except Exception:
            logger.exception("Error saving startup config")

    # ------------------------------------------------------------------
    # DB-backed settings loading/saving
    # ------------------------------------------------------------------

    def load_from_db(self) -> None:
        """Populate all DB-backed attributes from the database.

        Must be called after :func:`lan_streamer.db.init_db` has run so that
        the database is ready and migrations have been applied.
        """
        logger.debug("Loading DB-backed config settings from database.")
        try:
            from lan_streamer.db.queries_config import (
                get_all_app_configs,
                bulk_set_app_configs,
                get_all_secrets,
            )
            from lan_streamer.db.models import SecretType

            # 1. Fetch all rows from the database in a single query.
            config_dict = get_all_app_configs()
            for k, v in config_dict.items():
                logger.debug(f"Config from DB - Key: '{k}' Value: '{v}'")

            # 2. Fill in any keys missing from the DB using _DB_DEFAULTS.
            defaults = copy.deepcopy(self._DB_DEFAULTS)
            for key, default in defaults.items():
                if key not in config_dict:
                    logger.debug(f"Setting config key '{key}' to default '{default}'")
                    config_dict[key] = default
                else:
                    logger.debug(
                        f"Using config key '{key}' with value '{config_dict[key]}'"
                    )

            # Assign general settings from the fully populated dictionary
            self.libraries = config_dict["libraries"]
            self.sync_history_on_start = config_dict["sync_history_on_start"]
            self.filter_out_watched = config_dict["filter_out_watched"]
            self.sort_mode = config_dict["sort_mode"]
            self.sort_descending = config_dict["sort_descending"]
            self.divide_logs_by_service = config_dict["divide_logs_by_service"]
            self.enable_caching = config_dict["enable_caching"]
            self.watched_threshold = config_dict["watched_threshold"]
            self.cache_directory = config_dict["cache_directory"]
            self.use_embedded_player = config_dict["use_embedded_player"]
            self.fullscreen_control_bar_position = config_dict[
                "fullscreen_control_bar_position"
            ]
            self.enable_hw_accel = config_dict["enable_hw_accel"]
            self.vlc_extra_args = config_dict["vlc_extra_args"]
            self.vlc_buffer_ms = config_dict["vlc_buffer_ms"]
            self.player_overlay_opacity = config_dict["player_overlay_opacity"]
            self.player_overlay_color = config_dict["player_overlay_color"]
            self.max_cache_size_gb = config_dict["max_cache_size_gb"]
            self.enable_next_episode_popup = config_dict["enable_next_episode_popup"]
            self.max_log_retention_days = config_dict["max_log_retention_days"]
            self.backup_directory = config_dict["backup_directory"]
            self.config_backup_retention = config_dict["config_backup_retention"]
            self.database_backup_retention = config_dict["database_backup_retention"]
            self.enable_combined_view = config_dict["enable_combined_view"]
            self.combined_views = config_dict["combined_views"]
            self.preferred_audio_device = config_dict["preferred_audio_device"]
            self.check_for_updates_on_startup = config_dict[
                "check_for_updates_on_startup"
            ]
            self.database_write_timeout = float(config_dict["database_write_timeout"])

            # 3. After going through all the settings take the fully populated dictionary and write the contents back to the database
            bulk_set_app_configs(config_dict)

            # Secrets — convenience flat attributes
            secrets = get_all_secrets()

            jf = secrets.get(SecretType.JELLYFIN.value, {})
            self.jellyfin_url = jf.get("url", "")
            self.jellyfin_api_key = jf.get("api_key", "")

            tmdb = secrets.get(SecretType.TMDB.value, {})
            self.tmdb_api_key = tmdb.get("api_key", "")

            mal = secrets.get(SecretType.MYANIMELIST.value, {})
            self.myanimelist_client_id = mal.get("client_id", "")
            self.myanimelist_client_secret = mal.get("client_secret", "")
            self.myanimelist_access_token = mal.get("access_token", "")
            self.myanimelist_refresh_token = mal.get("refresh_token", "")
            self.myanimelist_token_expires_at = float(mal.get("token_expires_at", 0.0))

            os_creds = secrets.get(SecretType.OPENSUBTITLES.value, {})
            self.opensubtitles_username = os_creds.get("username", "")
            self.opensubtitles_password = os_creds.get("password", "")
            self.opensubtitles_api_key = os_creds.get("api_key", "")

            logger.debug("DB-backed config settings loaded successfully.")
        except Exception:
            logger.exception("Error loading DB-backed config settings")

    def save_to_db(self) -> None:
        """Persist all DB-backed attributes to the database.

        Callers that mutate a single attribute should prefer the targeted
        :func:`~lan_streamer.db.queries.set_app_config` / :func:`~lan_streamer.db.queries.set_secret`
        helpers directly for efficiency.  This method is provided as a
        convenience for saving the full in-memory state in one call (e.g.
        from the settings dialog).
        """
        logger.debug("Saving DB-backed config settings to database.")
        try:
            from lan_streamer.db.queries_config import set_app_config, set_secret
            from lan_streamer.db.models import SecretType

            # General settings
            set_app_config("libraries", self.libraries)
            set_app_config("sync_history_on_start", self.sync_history_on_start)
            set_app_config("filter_out_watched", self.filter_out_watched)
            set_app_config("sort_mode", self.sort_mode)
            set_app_config("sort_descending", self.sort_descending)
            set_app_config("divide_logs_by_service", self.divide_logs_by_service)
            set_app_config("enable_caching", self.enable_caching)
            set_app_config("watched_threshold", self.watched_threshold)
            set_app_config("cache_directory", self.cache_directory)
            set_app_config("use_embedded_player", self.use_embedded_player)
            set_app_config(
                "fullscreen_control_bar_position", self.fullscreen_control_bar_position
            )
            set_app_config("enable_hw_accel", self.enable_hw_accel)
            set_app_config("vlc_extra_args", self.vlc_extra_args)
            set_app_config("vlc_buffer_ms", self.vlc_buffer_ms)
            set_app_config("player_overlay_opacity", self.player_overlay_opacity)
            set_app_config("player_overlay_color", self.player_overlay_color)
            set_app_config("max_cache_size_gb", self.max_cache_size_gb)
            set_app_config("enable_next_episode_popup", self.enable_next_episode_popup)
            set_app_config("max_log_retention_days", self.max_log_retention_days)
            set_app_config("backup_directory", self.backup_directory)
            set_app_config("config_backup_retention", self.config_backup_retention)
            set_app_config("database_backup_retention", self.database_backup_retention)
            set_app_config("enable_combined_view", self.enable_combined_view)
            set_app_config("combined_views", self.combined_views)
            set_app_config("preferred_audio_device", self.preferred_audio_device)
            set_app_config(
                "check_for_updates_on_startup", self.check_for_updates_on_startup
            )
            set_app_config("database_write_timeout", self.database_write_timeout)

            # Secrets
            set_secret(
                SecretType.JELLYFIN,
                {"url": self.jellyfin_url, "api_key": self.jellyfin_api_key},
            )
            set_secret(SecretType.TMDB, {"api_key": self.tmdb_api_key})
            set_secret(
                SecretType.MYANIMELIST,
                {
                    "client_id": self.myanimelist_client_id,
                    "client_secret": self.myanimelist_client_secret,
                    "access_token": self.myanimelist_access_token,
                    "refresh_token": self.myanimelist_refresh_token,
                    "token_expires_at": self.myanimelist_token_expires_at,
                },
            )
            set_secret(
                SecretType.OPENSUBTITLES,
                {
                    "username": self.opensubtitles_username,
                    "password": self.opensubtitles_password,
                    "api_key": self.opensubtitles_api_key,
                },
            )

            logger.debug("DB-backed config settings saved successfully.")
        except Exception:
            logger.exception("Error saving DB-backed config settings")

    # ------------------------------------------------------------------
    # Series preferences (delegated to DB)
    # ------------------------------------------------------------------

    def get_series_preference(
        self, library_name: str, series_name: str, key: str, default: Any = None
    ) -> Any:
        """Return a per-series preference value from the database."""
        try:
            from lan_streamer.db.queries_config import get_series_pref

            return get_series_pref(library_name, series_name, key, default)
        except Exception:
            logger.exception(
                f"Error getting series preference '{key}' for "
                f"'{library_name}:{series_name}'"
            )
            return default

    def set_series_preference(
        self, library_name: str, series_name: str, key: str, value: Any
    ) -> None:
        """Persist a per-series preference value to the database."""
        try:
            from lan_streamer.db.queries_config import set_series_pref

            set_series_pref(library_name, series_name, key, value)
        except Exception:
            logger.exception(
                f"Error setting series preference '{key}' for "
                f"'{library_name}:{series_name}'"
            )

    @property
    def cache_directory(self) -> str:
        return self._cache_directory

    @cache_directory.setter
    def cache_directory(self, val: str) -> None:
        self._cache_directory = str(Path(val).expanduser().absolute())

    @property
    def backup_directory(self) -> str:
        return self._backup_directory

    @backup_directory.setter
    def backup_directory(self, val: str) -> None:
        self._backup_directory = str(Path(val).expanduser().absolute())


config = Config()
