import json
from pathlib import Path
from typing import List, Dict, Any

CONFIG_FILE = Path.home() / ".config" / "lan-streamer" / "config.json"


class Config:
    def __init__(self) -> None:
        self.libraries: Dict[str, Dict[str, Any]] = {}
        self.jellyfin_url: str = ""
        self.jellyfin_api_key: str = ""
        self.tmdb_api_key: str = ""
        # sync_history_on_start: auto-sync Jellyfin watch history every startup
        self.sync_history_on_start: bool = True
        self.filter_out_watched: bool = False
        self.sort_mode: str = "Alphabetical"
        self.database_path: str = str(
            Path.home() / ".config" / "lan-streamer" / "library.db"
        )
        self.log_directory: str = str(Path.home() / ".config" / "lan-streamer" / "logs")
        self.log_level: str = "INFO"
        self.divide_logs_by_service: bool = False
        self.enable_caching: bool = False
        self.watched_threshold: float = 0.95
        self.cache_directory: str = str(
            Path.home() / ".config" / "lan-streamer" / "cache"
        )
        self.use_embedded_player: bool = True
        self.enable_hw_accel: bool = True
        self.vlc_extra_args: List[str] = []
        self.player_overlay_opacity: float = 0.4
        self.player_overlay_color: str = "white"
        self.max_cache_size_gb: float = 15.0
        self.max_log_retention_days: int = 7
        self.backup_directory: str = str(
            Path.home() / ".config" / "lan-streamer" / "backups"
        )
        self.config_backup_frequency: int = 0
        self.database_backup_frequency: int = 0
        self.config_backup_retention: int = 7
        self.database_backup_retention: int = 7
        self.load()

    def load(self) -> None:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)

                    self.jellyfin_url = data.get("jellyfin_url", "")
                    self.jellyfin_api_key = data.get("jellyfin_api_key", "")
                    self.tmdb_api_key = data.get(
                        "tmdb_api_key",
                        data.get("tvdb_api_key", ""),  # backwards compat
                    )
                    # Support old key name for backwards compatibility
                    self.sync_history_on_start = data.get(
                        "sync_history_on_start",
                        data.get("sync_on_start", True),
                    )
                    self.filter_out_watched = data.get(
                        "filter_out_watched",
                        data.get("filter_unwatched", False),
                    )
                    self.sort_mode = data.get("sort_mode", "Alphabetical")
                    self.database_path = data.get(
                        "database_path",
                        str(Path.home() / ".config" / "lan-streamer" / "library.db"),
                    )
                    self.log_directory = data.get(
                        "log_directory",
                        str(Path.home() / ".config" / "lan-streamer" / "logs"),
                    )
                    self.log_level = data.get("log_level", "INFO")
                    self.divide_logs_by_service = data.get(
                        "divide_logs_by_service",
                        not data.get("enable_global_file_logging", True),
                    )
                    self.enable_caching = data.get("enable_caching", False)
                    self.watched_threshold = data.get("watched_threshold", 0.95)
                    self.cache_directory = data.get(
                        "cache_directory",
                        str(Path.home() / ".config" / "lan-streamer" / "cache"),
                    )
                    self.use_embedded_player = data.get("use_embedded_player", True)
                    self.enable_hw_accel = data.get("enable_hw_accel", True)
                    self.vlc_extra_args = data.get("vlc_extra_args", [])
                    self.player_overlay_opacity = data.get(
                        "player_overlay_opacity", 0.4
                    )
                    self.player_overlay_color = data.get(
                        "player_overlay_color", "white"
                    )
                    self.max_cache_size_gb = data.get("max_cache_size_gb", 15.0)
                    self.max_log_retention_days = data.get("max_log_retention_days", 7)
                    self.backup_directory = data.get(
                        "backup_directory",
                        str(Path.home() / ".config" / "lan-streamer" / "backups"),
                    )
                    self.config_backup_frequency = data.get(
                        "config_backup_frequency", 0
                    )
                    self.database_backup_frequency = data.get(
                        "database_backup_frequency", 0
                    )
                    self.config_backup_retention = data.get(
                        "config_backup_retention", 7
                    )
                    self.database_backup_retention = data.get(
                        "database_backup_retention", 7
                    )

                    if "libraries" in data:
                        raw_libraries = data["libraries"]
                        # Migrate old format if needed
                        for lib_name, lib_val in raw_libraries.items():
                            if isinstance(lib_val, list):
                                self.libraries[lib_name] = {
                                    "type": "tv",
                                    "paths": lib_val,
                                }
                            else:
                                self.libraries[lib_name] = lib_val
                        if any(isinstance(val, list) for val in raw_libraries.values()):
                            self.save()
                    elif "root_dirs" in data:
                        # Migrate very old format
                        self.libraries = {
                            "Default": {
                                "type": "tv",
                                "paths": data.get("root_dirs", []),
                            }
                        }
                        self.save()
                    else:
                        self.libraries = {}
            except Exception as e:
                print(f"Error loading config: {e}")
                self.libraries = {}
        else:
            self.libraries = {}

    def save(self) -> None:
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            print(f"Could not create config directory {CONFIG_FILE.parent}: {exc}")
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(
                    {
                        "libraries": self.libraries,
                        "jellyfin_url": self.jellyfin_url,
                        "jellyfin_api_key": self.jellyfin_api_key,
                        "tmdb_api_key": self.tmdb_api_key,
                        "sync_history_on_start": self.sync_history_on_start,
                        "filter_out_watched": self.filter_out_watched,
                        "sort_mode": self.sort_mode,
                        "database_path": self.database_path,
                        "log_directory": self.log_directory,
                        "log_level": self.log_level,
                        "divide_logs_by_service": self.divide_logs_by_service,
                        "enable_caching": self.enable_caching,
                        "watched_threshold": self.watched_threshold,
                        "cache_directory": self.cache_directory,
                        "use_embedded_player": self.use_embedded_player,
                        "enable_hw_accel": self.enable_hw_accel,
                        "vlc_extra_args": self.vlc_extra_args,
                        "player_overlay_opacity": self.player_overlay_opacity,
                        "player_overlay_color": self.player_overlay_color,
                        "max_cache_size_gb": self.max_cache_size_gb,
                        "max_log_retention_days": self.max_log_retention_days,
                        "backup_directory": self.backup_directory,
                        "config_backup_frequency": self.config_backup_frequency,
                        "database_backup_frequency": self.database_backup_frequency,
                        "config_backup_retention": self.config_backup_retention,
                        "database_backup_retention": self.database_backup_retention,
                    },
                    f,
                    indent=4,
                )
        except Exception as e:
            print(f"Error saving config: {e}")

    def add_library(self, name: str, library_type: str = "tv") -> None:
        if name not in self.libraries:
            self.libraries[name] = {"type": library_type, "paths": []}
            self.save()

    def remove_library(self, name: str) -> None:
        if name in self.libraries:
            del self.libraries[name]
            self.save()

    def add_root_dir(self, library_name: str, path: str) -> None:
        if library_name in self.libraries:
            paths = self.libraries[library_name].get("paths", [])
            if path not in paths:
                paths.append(path)
                self.libraries[library_name]["paths"] = paths
                self.save()

    def remove_root_dir(self, library_name: str, path: str) -> None:
        if library_name in self.libraries:
            paths = self.libraries[library_name].get("paths", [])
            if path in paths:
                paths.remove(path)
                self.libraries[library_name]["paths"] = paths
                self.save()


config = Config()
