import copy
import json
import logging
import threading
from pathlib import Path
from typing import Any, ClassVar


def _parse_config_path() -> Path:
    import sys

    try:
        arguments = sys.argv
        for index, argument in enumerate(arguments):
            if argument in ("--config", "-c"):
                if index + 1 < len(arguments):
                    return Path(arguments[index + 1]).expanduser().absolute()
            elif argument.startswith("--config="):
                path_part = argument.split("=", 1)[1]
                return Path(path_part).expanduser().absolute()
    except OSError, ValueError, TypeError:
        pass
    return Path.home() / ".config" / "lan-streamer" / "config.json"


CONFIG_FILE = _parse_config_path()
logger: logging.Logger = logging.getLogger(__name__)


def split_multi_root_libraries(
    libraries_dictionary: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str, str]]]:
    """Splits any library with multiple root directories into separate libraries.

    Each resulting library has at most one root directory in its 'paths' list.
    The first root directory keeps the original library name.
    Subsequent root directories are assigned separate libraries named:
    '{library_name} ({folder_name})' based on the directory folder name,
    falling back to '{library_name} ({number})' if collisions occur.

    Returns:
        A tuple of (normalized_libraries, split_records), where each split_record
        is a tuple of (old_library_name, new_library_name, root_path).
    """
    normalized_libraries: dict[str, dict[str, Any]] = {}
    split_records: list[tuple[str, str, str]] = []

    for library_name, library_configuration in libraries_dictionary.items():
        configuration_copy = dict(library_configuration)
        if configuration_copy.get("management_type") == "remote":
            normalized_libraries[library_name] = configuration_copy
            continue

        raw_paths = configuration_copy.get("paths", [])
        # Deduplicate paths while preserving order
        unique_paths: list[str] = list(dict.fromkeys(raw_paths))
        archive_paths: list[str] = configuration_copy.get("archive_paths", [])

        if len(unique_paths) <= 1:
            configuration_copy["paths"] = unique_paths
            normalized_libraries[library_name] = configuration_copy
            continue

        # Keep first path for original library
        first_path = unique_paths[0]
        configuration_copy["paths"] = [first_path]
        configuration_copy["archive_paths"] = [
            path for path in archive_paths if path == first_path
        ]
        normalized_libraries[library_name] = configuration_copy

        # Split remaining paths into separate libraries
        for index, path in enumerate(unique_paths[1:], start=2):
            folder_name = Path(path).name.strip()
            candidate_name = (
                f"{library_name} ({folder_name})"
                if folder_name
                else f"{library_name} ({index})"
            )
            if (
                candidate_name in normalized_libraries
                or candidate_name in libraries_dictionary
            ):
                candidate_name = f"{library_name} ({index})"

            counter = index
            while (
                candidate_name in normalized_libraries
                or candidate_name in libraries_dictionary
            ):
                counter += 1
                candidate_name = f"{library_name} ({counter})"

            new_configuration = dict(library_configuration)
            new_configuration["paths"] = [path]
            new_configuration["archive_paths"] = [
                archive_path for archive_path in archive_paths if archive_path == path
            ]
            normalized_libraries[candidate_name] = new_configuration
            split_records.append((library_name, candidate_name, path))

    return normalized_libraries, split_records


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
    _DB_DEFAULTS: ClassVar[dict[str, Any]] = {
        "libraries": {},
        "scan_agents": {},
        "sync_history_on_start": True,
        "filter_out_watched": False,
        "sort_mode": "Alphabetical",
        "sort_descending": False,
        "divide_logs_by_service": False,
        "enable_caching": False,
        "watched_threshold": 0.95,
        "cache_directory": str(CONFIG_FILE.parent / "cache"),
        "use_embedded_player": True,
        "fullscreen_control_bar_position": "Bottom",
        "subtitle_position": "Bottom",
        "enable_hw_accel": True,
        "vlc_extra_args": [],
        "vlc_buffer_ms": 3000,
        "player_overlay_opacity": 0.4,
        "player_overlay_color": "white",
        "max_cache_size_gb": 15.0,
        "enable_next_episode_popup": True,
        "max_log_retention_days": 7,
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
        "update_release_channel": "stable",
        "database_write_timeout": 60.0,
        "scan_interval_hours": 1,
        "auto_scan_enabled": True,
        "enable_async_scan": True,
        "scan_concurrency": 4,
        "default_video_aspect_mode": "fit",
        "tabs": [],
    }

    def __init__(self) -> None:
        """Initialise startup-critical attributes and load them from the config file."""
        self._last_loaded_mtime: float = 0.0

        # --- Startup-critical (config-file backed) ---
        self.database_path: str = str(CONFIG_FILE.parent / "library.db")
        self.log_directory: str = str(CONFIG_FILE.parent / "logs")
        self.backup_directory: str = str(CONFIG_FILE.parent / "backups")
        self.log_level: str = "INFO"
        self.config_backup_frequency: int = 1
        self.database_backup_frequency: int = 1

        # --- DB-backed (seeded from _DB_DEFAULTS so the object is usable
        # before load_from_db() is called after DB initialisation) ---
        self.database_write_timeout: float = 60.0
        self.libraries: dict[str, dict[str, Any]] = {}
        self.tabs: list[dict[str, Any]] = []
        for key, value in copy.deepcopy(self._DB_DEFAULTS).items():
            setattr(self, key, value)

        # Dynamic override based on current CONFIG_FILE path
        self.cache_directory = str(CONFIG_FILE.parent / "cache")

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

            with open(CONFIG_FILE) as file_handle:
                config_data = json.load(file_handle)

            self.database_path = str(
                Path(
                    config_data.get(
                        "database_path",
                        str(CONFIG_FILE.parent / "library.db"),
                    )
                )
                .expanduser()
                .absolute()
            )
            self.log_directory = str(
                Path(
                    config_data.get(
                        "log_directory",
                        str(CONFIG_FILE.parent / "logs"),
                    )
                )
                .expanduser()
                .absolute()
            )
            self.backup_directory = str(
                Path(
                    config_data.get(
                        "backup_directory",
                        str(CONFIG_FILE.parent / "backups"),
                    )
                )
                .expanduser()
                .absolute()
            )
            self.log_level = config_data.get("log_level", "INFO")
            self.config_backup_frequency = int(
                config_data.get("config_backup_frequency", 0)
            )
            self.database_backup_frequency = int(
                config_data.get("database_backup_frequency", 0)
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

        Only the startup keys are written; all other settings live in the
        database and are never serialised back to the file.
        """
        logger.debug(f"Attempting to save startup config to {CONFIG_FILE}")
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exception_instance:
            logger.warning(
                f"Could not create config directory {CONFIG_FILE.parent}: {exception_instance}"
            )
        try:
            with open(CONFIG_FILE, "w") as file_handle:
                json.dump(
                    {
                        "database_path": self.database_path,
                        "log_directory": self.log_directory,
                        "log_level": self.log_level,
                        "config_backup_frequency": self.config_backup_frequency,
                        "database_backup_frequency": self.database_backup_frequency,
                        "backup_directory": self.backup_directory,
                    },
                    file_handle,
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
            from lan_streamer.db.models import SecretType
            from lan_streamer.db.queries_config import (
                bulk_set_app_configs,
                get_all_app_configs,
                get_all_secrets,
            )

            # 1. Fetch all rows from the database in a single query.
            config_dict = get_all_app_configs()
            for k, v in config_dict.items():
                logger.debug(f"Config from DB - Key: '{k}' Value: '{v}'")

            # 2. Fill in any keys missing from the DB using _DB_DEFAULTS.
            defaults = copy.deepcopy(self._DB_DEFAULTS)
            defaults["cache_directory"] = str(CONFIG_FILE.parent / "cache")
            for key, default in defaults.items():
                if key not in config_dict:
                    logger.debug(f"Setting config key '{key}' to default '{default}'")
                    config_dict[key] = default
                else:
                    logger.debug(
                        f"Using config key '{key}' with value '{config_dict[key]}'"
                    )

            # Assign general settings from the fully populated dictionary
            raw_libraries = config_dict.get("libraries", {})
            normalized_libraries, split_records = split_multi_root_libraries(
                raw_libraries
            )
            for library_configuration in normalized_libraries.values():
                if "management_type" not in library_configuration:
                    library_configuration["management_type"] = "local"
            self.libraries = normalized_libraries

            # Reassign DB records if any library had multiple roots and was split
            if split_records:
                logger.info(
                    "Split %d multi-root libraries into separate single-root libraries",
                    len(split_records),
                )
                self._reassign_split_libraries(split_records)
            self.scan_agents = config_dict.get("scan_agents", {})
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
            self.subtitle_position = config_dict["subtitle_position"]
            self.enable_hw_accel = config_dict["enable_hw_accel"]
            self.vlc_extra_args = config_dict["vlc_extra_args"]
            self.vlc_buffer_ms = config_dict["vlc_buffer_ms"]
            self.player_overlay_opacity = config_dict["player_overlay_opacity"]
            self.player_overlay_color = config_dict["player_overlay_color"]
            self.max_cache_size_gb = config_dict["max_cache_size_gb"]
            self.enable_next_episode_popup = config_dict["enable_next_episode_popup"]
            self.max_log_retention_days = config_dict["max_log_retention_days"]
            self.config_backup_retention = config_dict["config_backup_retention"]
            self.database_backup_retention = config_dict["database_backup_retention"]
            self.enable_combined_view = config_dict["enable_combined_view"]
            self.combined_views = config_dict["combined_views"]
            self.preferred_audio_device = config_dict["preferred_audio_device"]
            self.check_for_updates_on_startup = config_dict[
                "check_for_updates_on_startup"
            ]
            self.update_release_channel = config_dict["update_release_channel"]
            self.database_write_timeout = float(config_dict["database_write_timeout"])
            self.scan_interval_hours = int(config_dict["scan_interval_hours"])
            self.auto_scan_enabled = bool(config_dict["auto_scan_enabled"])
            self.scan_concurrency = int(config_dict.get("scan_concurrency", 4))
            self.default_video_aspect_mode = str(
                config_dict.get("default_video_aspect_mode", "fit")
            )

            loaded_tabs = config_dict.get("tabs")
            if loaded_tabs is None or not loaded_tabs:
                self.tabs = [
                    {"name": library_name, "libraries": [library_name]}
                    for library_name in self.libraries
                ]
            else:
                self.tabs = [
                    {
                        "name": str(tab_entry.get("name", "")),
                        "libraries": list(tab_entry.get("libraries", [])),
                    }
                    for tab_entry in loaded_tabs
                    if isinstance(tab_entry, dict) and tab_entry.get("name")
                ]
            config_dict["tabs"] = self.tabs

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

    def _reassign_split_libraries(
        self, split_records: list[tuple[str, str, str]]
    ) -> None:
        """Handle a multi-root library split after config load or save.

        In-memory tab membership is updated synchronously (cheap), while the
        actual database record reassignment — which scans every series/movie
        row and rebuilds the smart-row cache — runs on a background daemon
        thread so the UI thread is never blocked by this one-time migration.
        """
        for old_name, new_name, _root_path in split_records:
            for tab_entry in self.tabs:
                if old_name in tab_entry.get(
                    "libraries", []
                ) and new_name not in tab_entry.get("libraries", []):
                    tab_entry["libraries"].append(new_name)

        def _perform_reassignment() -> None:
            try:
                from lan_streamer.db.library import (
                    reassign_library_items_by_root_path,
                )

                for old_name, new_name, root_path in split_records:
                    reassignment_counts = reassign_library_items_by_root_path(
                        old_name, new_name, root_path
                    )
                    logger.info(
                        "Reassigned records for library split '%s' -> '%s' at '%s': %s",
                        old_name,
                        new_name,
                        root_path,
                        reassignment_counts,
                    )
            except Exception:
                logger.exception("Database reassignment during library split failed")

        reassignment_thread = threading.Thread(
            target=_perform_reassignment,
            name="library-split-reassignment",
            daemon=True,
        )
        reassignment_thread.start()

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
            from lan_streamer.db.models import SecretType
            from lan_streamer.db.queries_config import set_app_config, set_secret

            normalized_libraries, split_records = split_multi_root_libraries(
                self.libraries
            )
            self.libraries = normalized_libraries
            if split_records:
                logger.info(
                    "Split %d multi-root libraries into separate single-root libraries during config save",
                    len(split_records),
                )
                self._reassign_split_libraries(split_records)

            # General settings
            set_app_config("libraries", self.libraries)
            set_app_config("tabs", self.tabs)
            set_app_config("scan_agents", self.scan_agents)
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
            set_app_config("subtitle_position", self.subtitle_position)
            set_app_config("enable_hw_accel", self.enable_hw_accel)
            set_app_config("vlc_extra_args", self.vlc_extra_args)
            set_app_config("vlc_buffer_ms", self.vlc_buffer_ms)
            set_app_config("player_overlay_opacity", self.player_overlay_opacity)
            set_app_config("player_overlay_color", self.player_overlay_color)
            set_app_config("max_cache_size_gb", self.max_cache_size_gb)
            set_app_config("enable_next_episode_popup", self.enable_next_episode_popup)
            set_app_config("max_log_retention_days", self.max_log_retention_days)
            set_app_config("config_backup_retention", self.config_backup_retention)
            set_app_config("database_backup_retention", self.database_backup_retention)
            set_app_config("enable_combined_view", self.enable_combined_view)
            set_app_config("combined_views", self.combined_views)
            set_app_config("preferred_audio_device", self.preferred_audio_device)
            set_app_config(
                "check_for_updates_on_startup", self.check_for_updates_on_startup
            )
            set_app_config("update_release_channel", self.update_release_channel)
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

    def get_local_libraries(self) -> dict[str, dict[str, Any]]:
        """Return subset of libraries that are locally managed."""
        return {
            library_name: library_configuration
            for library_name, library_configuration in self.libraries.items()
            if library_configuration.get("management_type", "local") == "local"
        }

    def get_remote_libraries(self) -> dict[str, dict[str, Any]]:
        """Return subset of libraries that are remotely managed by a scan agent."""
        return {
            library_name: library_configuration
            for library_name, library_configuration in self.libraries.items()
            if library_configuration.get("management_type", "local") == "remote"
        }

    def get_tab_libraries(self, tab_name: str) -> list[str]:
        """Return the list of library names associated with a tab."""
        for tab_entry in self.tabs:
            if tab_entry.get("name") == tab_name:
                return list(tab_entry.get("libraries", []))
        if tab_name in self.libraries:
            return [tab_name]
        return []

    def get_tab_names(self) -> list[str]:
        """Return all configured tab names, or library names if no tabs are defined."""
        if self.tabs:
            return [
                str(tab_entry["name"])
                for tab_entry in self.tabs
                if tab_entry.get("name")
            ]
        return list(self.libraries.keys())


config = Config()
