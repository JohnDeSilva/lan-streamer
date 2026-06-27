from __future__ import annotations

from typing import Any

from lan_streamer.providers.jellyfin import JellyfinClient
from lan_streamer.providers.tmdb import TMDBClient
from lan_streamer.providers.opensubtitles import OpenSubtitlesClient
from lan_streamer.providers.myanimelist import MyAnimeListClient
from lan_streamer.providers.http_client import AsyncHTTPClient
from lan_streamer.providers.tmdb_async import AsyncTMDBClient
from lan_streamer.providers.jellyfin_async import AsyncJellyfinClient
from lan_streamer.providers.opensubtitles_async import AsyncOpenSubtitlesClient
from lan_streamer.providers.myanimelist_async import AsyncMyAnimeListClient


# ---------------------------------------------------------------------------
# Factory functions — Dual-Provider Pattern
# ---------------------------------------------------------------------------


def get_tmdb_client(
    async_mode: bool = False, **kwargs: Any
) -> TMDBClient | AsyncTMDBClient:
    """Return TMDB client in the requested mode.

    Parameters
    ----------
    async_mode:
        ``True`` for :class:`AsyncTMDBClient`, ``False`` (default) for
        :class:`TMDBClient`.
    kwargs:
        Forwarded to the client constructor.
    """
    if async_mode:
        return AsyncTMDBClient(**kwargs)
    return TMDBClient(**kwargs)


def get_jellyfin_client(
    async_mode: bool = False, **kwargs: Any
) -> JellyfinClient | AsyncJellyfinClient:
    """Return Jellyfin client in the requested mode."""
    if async_mode:
        return AsyncJellyfinClient(**kwargs)
    return JellyfinClient(**kwargs)


def get_opensubtitles_client(
    async_mode: bool = False, **kwargs: Any
) -> OpenSubtitlesClient | AsyncOpenSubtitlesClient:
    """Return OpenSubtitles client in the requested mode."""
    if async_mode:
        return AsyncOpenSubtitlesClient(**kwargs)
    return OpenSubtitlesClient(**kwargs)


def get_myanimelist_client(async_mode: bool = False, **kwargs: Any) -> Any:
    """Return MyAnimeList client in the requested mode."""
    if async_mode:
        return AsyncMyAnimeListClient(**kwargs)
    return MyAnimeListClient(**kwargs)
