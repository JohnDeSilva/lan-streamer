import logging
import sys
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PatchedAttribute:
    def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None:
        self.attr_name = attr_name
        self.default_factory = default_factory

    def _get_target(self) -> Any:
        scanner_module = sys.modules.get("lan_streamer.scanner")
        if scanner_module and hasattr(scanner_module, self.attr_name):
            return getattr(scanner_module, self.attr_name)
        return self.default_factory()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._get_target(), item)


class PatchedCallable:
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


def _get_tmdb_client() -> Any:
    from lan_streamer.providers.tmdb import tmdb_client

    return tmdb_client


def _get_parse_episode_number() -> Any:
    from lan_streamer.scanner.parser import _parse_episode_number

    return _parse_episode_number


def _get_clean_series_data() -> Any:
    from lan_streamer.scanner.metadata import clean_series_data

    return clean_series_data


def _get_scan_movie() -> Any:
    from lan_streamer.scanner.core import scan_movie

    return scan_movie


logger.debug("scanner.proxy: initialising lazy proxy objects")

tmdb_client = PatchedAttribute("tmdb_client", _get_tmdb_client)
_parse_episode_number = PatchedCallable(
    "_parse_episode_number", _get_parse_episode_number
)
clean_series_data = PatchedCallable("clean_series_data", _get_clean_series_data)
scan_movie = PatchedCallable("scan_movie", _get_scan_movie)


class ScannerProxy:
    def __getattr__(self, name: str) -> Any:
        scanner_module = sys.modules.get("lan_streamer.scanner")
        if scanner_module and hasattr(scanner_module, name):
            return getattr(scanner_module, name)

        # Dynamic fallback to avoid circular imports at import time
        if name == "tmdb_client":
            return tmdb_client
        if name == "_parse_episode_number":
            return _parse_episode_number
        if name == "clean_series_data":
            return clean_series_data
        if name == "scan_movie":
            return scan_movie
        raise AttributeError(f"ScannerProxy has no attribute '{name}'")


scanner_proxy = ScannerProxy()
