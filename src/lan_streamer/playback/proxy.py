import sys
from typing import Any, Callable


class PatchedAttribute:
    def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None:
        self.attr_name = attr_name
        self.default_factory = default_factory

    def _get_target(self) -> Any:
        player_module = sys.modules.get("lan_streamer.playback")
        if player_module and hasattr(player_module, self.attr_name):
            return getattr(player_module, self.attr_name)
        return self.default_factory()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._get_target(), item)

    def __bool__(self) -> bool:
        return self._get_target() is not None


class PatchedCallable:
    def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None:
        self.attr_name = attr_name
        self.default_factory = default_factory

    def _get_target(self) -> Any:
        player_module = sys.modules.get("lan_streamer.playback")
        if player_module and hasattr(player_module, self.attr_name):
            return getattr(player_module, self.attr_name)
        return self.default_factory()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_target()(*args, **kwargs)


def _get_vlc() -> Any:
    try:
        import vlc

        return vlc
    except ImportError, OSError:
        return None


def _get_cache_worker() -> Any:
    from lan_streamer.playback.cache import CacheWorker

    return CacheWorker


vlc = PatchedAttribute("vlc", _get_vlc)
CacheWorker = PatchedCallable("CacheWorker", _get_cache_worker)
