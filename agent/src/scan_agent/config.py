"""Agent configuration management.

The :class:`AgentConfig` persists to a JSON file and exposes the same
attribute names the reused desktop code reads from
``lan_streamer.system.config.config`` (``tmdb_api_key``,
``opensubtitles_*``, ``scan_concurrency``, ``database_path``,
``log_directory``, ``cache_directory``, ``libraries``).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_SCAN_CONCURRENCY = 4


class AgentConfig:
    """JSON-file-backed configuration for the scan agent.

    Attributes:
        tmdb_api_key: TMDB API key consumed by ``lan_streamer.providers.tmdb``.
        scan_concurrency: Number of parallel scan workers.
        opensubtitles_api_key: OpenSubtitles API key.
        opensubtitles_username: OpenSubtitles username.
        opensubtitles_password: OpenSubtitles password.
        database_path: SQLite database file path.
        log_directory: Directory for agent log files.
        cache_directory: Directory for provider image caches.
        libraries: Mapping of library identifier to a definition dict with
            ``name``, ``media_type`` (``"tv"``, ``"anime"``, or ``"movie"``) and
            ``root_path`` keys.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        data_directory: str | Path | None = None,
    ) -> None:
        """Initialise the config and load (or seed) the JSON file.

        When *data_directory* is provided, configs, databases, logs, and caches
        are rooted within it. When only *path* is given, its parent directory
        serves as the data directory. When neither is given, the default data
        directory is resolved via :func:`resolve_default_data_directory`.
        """
        if data_directory is not None:
            self.data_directory = Path(data_directory).expanduser().absolute()
            self._path = (
                Path(path).expanduser().absolute()
                if path is not None
                else self.data_directory / "config.json"
            )
        elif path is not None:
            self._path = Path(path).expanduser().absolute()
            self.data_directory = self._path.parent
        else:
            self._path = resolve_default_config_path()
            self.data_directory = self._path.parent

        self.tmdb_api_key: str = ""
        self.scan_concurrency: int = _DEFAULT_SCAN_CONCURRENCY
        self.opensubtitles_api_key: str = ""
        self.opensubtitles_username: str = ""
        self.opensubtitles_password: str = ""
        self.database_path: str = str(self.data_directory / "library.db")
        self.log_directory: str = str(self.data_directory / "logs")
        self.cache_directory: str = str(self.data_directory / "cache")
        self.libraries: dict[str, dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------

    def _defaults(self) -> dict[str, Any]:
        """Return the default values for every persisted top-level key."""
        return {
            "tmdb_api_key": "",
            "scan_concurrency": _DEFAULT_SCAN_CONCURRENCY,
            "opensubtitles_api_key": "",
            "opensubtitles_username": "",
            "opensubtitles_password": "",
            "database_path": str(self.data_directory / "library.db"),
            "log_directory": str(self.data_directory / "logs"),
            "cache_directory": str(self.data_directory / "cache"),
            "libraries": {},
        }

    def _load(self) -> None:
        """Load persisted values, falling back to defaults for missing keys.

        On first run (no file on disk) the defaults file is written.
        """
        if not self._path.exists():
            logger.info(
                "Config file does not exist; writing defaults to %s", self._path
            )
            self.save()
            return
        try:
            with self._path.open(encoding="utf-8") as file_handle:
                persisted = json.load(file_handle)
        except (OSError, ValueError) as error:
            logger.warning("Could not read config file %s: %s", self._path, error)
            persisted = {}
        for key, default_value in self._defaults().items():
            setattr(self, key, persisted.get(key, default_value))

    def save(self) -> None:
        """Persist all top-level keys to the JSON file atomically."""
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        Path(self.cache_directory).mkdir(parents=True, exist_ok=True)
        Path(self.log_directory).mkdir(parents=True, exist_ok=True)
        payload = {
            "tmdb_api_key": self.tmdb_api_key,
            "scan_concurrency": self.scan_concurrency,
            "opensubtitles_api_key": self.opensubtitles_api_key,
            "opensubtitles_username": self.opensubtitles_username,
            "opensubtitles_password": self.opensubtitles_password,
            "database_path": self.database_path,
            "log_directory": self.log_directory,
            "cache_directory": self.cache_directory,
            "libraries": self.libraries,
        }
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=self._path.parent, prefix=".config-", suffix=".tmp"
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as file_handle:
                json.dump(payload, file_handle, indent=4)
            os.replace(temporary_name, self._path)
        except Exception:
            with suppress(OSError):
                os.unlink(temporary_name)
            raise
        logger.debug("Saved agent config to %s", self._path)

    # ------------------------------------------------------------------
    # Key access
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the attribute named *key*, or *default* when absent."""
        return getattr(self, key, default)

    def set(self, key: str, value: Any) -> None:
        """Set the attribute named *key* to *value* and persist immediately."""
        setattr(self, key, value)
        self.save()
        logger.info("Agent config key '%s' updated", key)


_module_singleton: AgentConfig | None = None


def resolve_default_data_directory() -> Path:
    """Resolve the default data directory where configs, databases, and caches live.

    Precedence:
    1. Environment variable ``SCAN_AGENT_DATA`` if set.
    2. Parent directory of environment variable ``SCAN_AGENT_CONFIG`` if set.
    3. Container volume ``/data`` if ``/data`` exists and is writable.
    4. Local package ``agent/data`` directory within repository if writable.
    5. User data directory ``~/.local/share/lan-streamer-agent``.
    """
    environment_data_directory = os.environ.get("SCAN_AGENT_DATA")
    if environment_data_directory:
        return Path(environment_data_directory).expanduser().absolute()

    environment_config_path = os.environ.get("SCAN_AGENT_CONFIG")
    if environment_config_path:
        return Path(environment_config_path).expanduser().absolute().parent

    container_data_directory = Path("/data")
    try:
        if container_data_directory.exists() and os.access(
            container_data_directory, os.W_OK
        ):
            return container_data_directory
    except OSError, PermissionError:
        pass

    package_data_directory = Path(__file__).resolve().parents[2] / "data"
    try:
        package_data_directory.mkdir(parents=True, exist_ok=True)
        if os.access(package_data_directory, os.W_OK):
            return package_data_directory
    except OSError, PermissionError:
        pass

    return Path.home() / ".local" / "share" / "lan-streamer-agent"


def resolve_default_config_path() -> Path:
    """Resolve the default configuration file path."""
    environment_config_path = os.environ.get("SCAN_AGENT_CONFIG")
    if environment_config_path:
        return Path(environment_config_path).expanduser().absolute()
    return resolve_default_data_directory() / "config.json"


def reset_agent_config() -> None:
    """Reset the module-level singleton (useful in test teardown)."""
    global _module_singleton  # noqa: PLW0603
    _module_singleton = None


def get_agent_config(
    path: str | Path | None = None,
    data_directory: str | Path | None = None,
) -> AgentConfig:
    """Return the module-level singleton :class:`AgentConfig`.

    The instance is cached; parameters are only honoured on the first call.
    """
    global _module_singleton  # noqa: PLW0603
    if _module_singleton is None:
        _module_singleton = AgentConfig(path=path, data_directory=data_directory)
    return _module_singleton


def install_into_lan_streamer(config: AgentConfig) -> None:
    """Install *config* as the desktop ``lan_streamer.system.config.config``.

    The reused scanner/providers read configuration dynamically from that
    module-level singleton, so swapping it for our agent object requires no
    desktop source changes. The ``LAN_STREAMER_DB`` environment variable is
    set as well because ``lan_streamer.db.DB_FILE`` is resolved at import
    time from it (falling back to ``config.database_path``).

    The desktop ``lan_streamer.system`` package ``__init__`` imports Qt
    (``async_task_manager``), so in a headless process we load only the real
    ``config.py`` source file via :mod:`importlib` and register a lightweight
    ``lan_streamer.system`` package shim in :data:`sys.modules`. When the real
    desktop package is already imported (QApplication present), we simply swap
    the module attribute in place.

    Note: ``_parse_config_path()`` in the loaded module scans ``sys.argv`` for
    a ``--config`` flag; callers must never pass ``--config`` in tests.
    """
    import importlib.util
    import sys
    import types

    import lan_streamer  # light package __init__ (version only)

    desktop_system = sys.modules.get("lan_streamer.system")
    if desktop_system is not None and not getattr(
        desktop_system, "_agent_bridged", False
    ):
        desktop_system.config = config  # type: ignore[attr-defined]  # real desktop package loaded
    else:
        package_directory = None
        for entry in lan_streamer.__path__:
            candidate = Path(entry) / "system"
            if (candidate / "config.py").exists():
                package_directory = candidate
                break
        if package_directory is None:
            raise RuntimeError(
                "Could not locate lan_streamer.system.config source on PYTHONPATH"
            )

        system_package = types.ModuleType("lan_streamer.system")
        system_package.__path__ = [str(package_directory)]
        system_package._agent_bridged = True  # type: ignore[attr-defined]
        sys.modules["lan_streamer.system"] = system_package

        config_module_name = "lan_streamer.system.config"
        loaded_config_module = sys.modules.get(config_module_name)
        if loaded_config_module is None:
            module_spec = importlib.util.spec_from_file_location(
                config_module_name, package_directory / "config.py"
            )
            if module_spec is None or module_spec.loader is None:
                raise RuntimeError(
                    f"Could not build import spec for {config_module_name}"
                )
            loaded_config_module = importlib.util.module_from_spec(module_spec)
            sys.modules[config_module_name] = loaded_config_module
            module_spec.loader.exec_module(loaded_config_module)
        loaded_config_module.config = config  # type: ignore[attr-defined]

    loaded_config_mod = sys.modules.get("lan_streamer.system.config")
    if loaded_config_mod is not None:
        loaded_config_mod.config = config  # type: ignore[attr-defined]

    agent_cache_directory = Path(config.cache_directory)
    images_cache_directory = agent_cache_directory / "images"
    people_cache_directory = agent_cache_directory / "people"
    images_cache_directory.mkdir(parents=True, exist_ok=True)
    people_cache_directory.mkdir(parents=True, exist_ok=True)

    for module_name in [
        "lan_streamer.providers.tmdb",
        "lan_streamer.providers.tmdb_async",
        "lan_streamer.providers.opensubtitles",
        "lan_streamer.providers.opensubtitles_async",
        "lan_streamer.scanner.core",
    ]:
        loaded_module = sys.modules.get(module_name)
        if loaded_module is not None:
            if hasattr(loaded_module, "config"):
                loaded_module.config = config  # type: ignore[attr-defined]
            if hasattr(loaded_module, "CACHE_DIR"):
                loaded_module.CACHE_DIR = images_cache_directory  # type: ignore[attr-defined]
            if hasattr(loaded_module, "PERSON_CACHE_DIR"):
                loaded_module.PERSON_CACHE_DIR = people_cache_directory  # type: ignore[attr-defined]
            client = getattr(loaded_module, "tmdb_client", None)
            if client is not None:
                client._cache_dir = images_cache_directory

    try:
        import lan_streamer.providers.tmdb as tmdb_module

        tmdb_module.CACHE_DIR = images_cache_directory
        tmdb_module.PERSON_CACHE_DIR = people_cache_directory
        tmdb_module.tmdb_client._cache_dir = images_cache_directory
    except ImportError, AttributeError:
        pass

    os.environ["LAN_STREAMER_DB"] = config.database_path
    os.environ["HOME"] = str(config.data_directory)
    logger.info(
        "Installed agent config into lan_streamer.system.config (database=%s, cache=%s)",
        config.database_path,
        config.cache_directory,
    )
