import logging
import sys
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PatchedAttribute:
    def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None:
        self.attr_name = attr_name
        self.default_factory = default_factory

    def _get_target(self) -> Any:
        backend_module = sys.modules.get("lan_streamer.backend")
        if backend_module and hasattr(backend_module, self.attr_name):
            return getattr(backend_module, self.attr_name)
        return self.default_factory()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._get_target(), item)


class PatchedCallable:
    def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None:
        self.attr_name = attr_name
        self.default_factory = default_factory

    def _get_target(self) -> Any:
        backend_module = sys.modules.get("lan_streamer.backend")
        if backend_module and hasattr(backend_module, self.attr_name):
            return getattr(backend_module, self.attr_name)
        return self.default_factory()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_target()(*args, **kwargs)


def _get_db() -> Any:
    from lan_streamer import db

    return db


def _get_config() -> Any:
    from lan_streamer.system.config import config

    return config


def _get_jellyfin_client() -> Any:
    from lan_streamer.providers.jellyfin import jellyfin_client

    return jellyfin_client


def _get_scan_directories() -> Any:
    from lan_streamer.scanner import scan_directories

    return scan_directories


def _get_discover_single_library_tree() -> Any:
    from lan_streamer.backend.scan_worker_single import (
        _discover_single_library_tree_impl,
    )

    return _discover_single_library_tree_impl


logger.debug("backend.proxy: initialising lazy proxy objects")

db = PatchedAttribute("db", _get_db)
config = PatchedAttribute("config", _get_config)
jellyfin_client = PatchedAttribute("jellyfin_client", _get_jellyfin_client)
scan_directories = PatchedCallable("scan_directories", _get_scan_directories)
discover_single_library_tree = PatchedCallable(
    "discover_single_library_tree", _get_discover_single_library_tree
)


class PatchedScannerCallable:
    def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None:
        self.attr_name = attr_name
        self.default_factory = default_factory

    def _get_target(self) -> Any:
        scanner_module = sys.modules.get("lan_streamer.scanner")
        if scanner_module and hasattr(scanner_module, self.attr_name):
            return getattr(scanner_module, self.attr_name)
        return self.default_factory()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_target()(*args, **kwargs)


def _get_detailed_file_info() -> Any:
    from lan_streamer.scanner import get_detailed_file_info

    return get_detailed_file_info


get_detailed_file_info = PatchedScannerCallable(
    "get_detailed_file_info", _get_detailed_file_info
)


def _get_scan_series() -> Any:
    from lan_streamer.scanner import scan_series

    return scan_series


def _get_scan_movie() -> Any:
    from lan_streamer.scanner import scan_movie

    return scan_movie


def _get_clean_series_data() -> Any:
    from lan_streamer.scanner import clean_series_data

    return clean_series_data


scan_series = PatchedCallable("scan_series", _get_scan_series)
scan_movie = PatchedCallable("scan_movie", _get_scan_movie)
clean_series_data = PatchedCallable("clean_series_data", _get_clean_series_data)
