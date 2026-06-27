"""
Async Jellyfin client for watch-history sync.

Mirror of the synchronous :class:`JellyfinClient` but fully async,
using :class:`AsyncHTTPClient` instead of ``requests.Session``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from lan_streamer.providers.http_client import AsyncHTTPClient
from lan_streamer.system.config import config

logger = logging.getLogger(__name__)


class AsyncJellyfinClient:
    """Async client for interacting with the Jellyfin server API.

    Used exclusively for watch-history sync (played/unplayed states).
    All network calls go through :class:`AsyncHTTPClient`.
    """

    def __init__(
        self,
        jellyfin_url: str | None = None,
        jellyfin_api_key: str | None = None,
    ) -> None:
        self._http_client = AsyncHTTPClient(requests_per_second=30.0, timeout=30.0)
        self._jellyfin_url = jellyfin_url
        self._jellyfin_api_key = jellyfin_api_key
        self._cached_user_id: str | None = None

    @property
    def _effective_url(self) -> str:
        return (
            self._jellyfin_url
            if self._jellyfin_url is not None
            else config.jellyfin_url
        )

    @property
    def _effective_api_key(self) -> str:
        return (
            self._jellyfin_api_key
            if self._jellyfin_api_key is not None
            else config.jellyfin_api_key
        )

    def is_configured(self) -> bool:
        return bool(self._effective_url and self._effective_api_key)

    def _get_headers(self) -> dict[str, str]:
        token = self._effective_api_key.strip()
        auth = (
            f'MediaBrowser Client="LanStreamer", Device="Desktop", '
            f'DeviceId="lan-streamer-1", Version="1.0.0", Token="{token}"'
        )
        return {
            "Authorization": auth,
            "Accept": "application/json",
        }

    def _get_base_url(self) -> str:
        url = self._effective_url.strip().rstrip("/")
        if not url:
            return ""
        if not url.startswith("http"):
            is_ip_address = bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$", url))
            if "." in url and not url.startswith("localhost") and not is_ip_address:
                url = f"https://{url}"
            else:
                url = f"http://{url}"
        return url

    async def get_current_user_id(self) -> str | None:
        if not self.is_configured():
            return None
        if self._cached_user_id:
            return self._cached_user_id

        base_url = self._get_base_url()
        url = f"{base_url}/Users"
        try:
            logger.debug(f"Fetching Jellyfin user from: {url}")
            users = await self._http_client.get_json(
                url, headers=self._get_headers(), timeout=10
            )
            if isinstance(users, list) and len(users) > 0:
                first_user = users[0]
                if isinstance(first_user, dict):
                    self._cached_user_id = first_user.get("Id")
                    return self._cached_user_id
        except Exception:
            logger.exception(f"Connection error reaching Jellyfin at {base_url}")

        # Retry with http if https failed
        if base_url.startswith("https://") and not self._effective_url.startswith(
            "https://"
        ):
            http_url = url.replace("https://", "http://")
            try:
                http_users = await self._http_client.get_json(
                    http_url, headers=self._get_headers(), timeout=10
                )
                if isinstance(http_users, list) and len(http_users) > 0:
                    self._cached_user_id = http_users[0].get("Id")
                    return self._cached_user_id
            except Exception:
                logger.exception("Retry with http failed")
        return None

    async def fetch_watched_episodes(
        self,
    ) -> tuple[set[str], set[str], set[tuple[str, str]]]:
        if not self.is_configured():
            return set(), set(), set()

        user_id = await self.get_current_user_id()
        if not user_id:
            return set(), set(), set()

        watched_ids: set[str] = set()
        watched_paths: set[str] = set()
        watched_names: set[tuple[str, str]] = set()
        url = f"{self._get_base_url()}/Users/{user_id}/Items"
        limit = 5000
        start_index = 0

        while True:
            parameters: dict[str, Any] = {
                "IncludeItemTypes": "Episode,Movie",
                "Recursive": "true",
                "Fields": "Path,SeriesName",
                "Filters": "IsPlayed",
                "Limit": limit,
                "StartIndex": start_index,
            }
            try:
                response = await self._http_client.get(
                    url, headers=self._get_headers(), params=parameters, timeout=30
                )
                items = list(response.get("Items", []))
                for item in items:
                    item_id = item.get("Id")
                    path = item.get("Path")
                    if item_id:
                        watched_ids.add(str(item_id))
                    if path:
                        watched_paths.add(str(path))
                    series_name = item.get("SeriesName")
                    episode_name = item.get("Name")
                    if series_name and episode_name:
                        watched_names.add(
                            (str(series_name).lower(), str(episode_name).lower())
                        )
                if len(items) < limit:
                    break
                start_index += limit
            except Exception:
                logger.exception("Failed to fetch watched episodes from Jellyfin")
                break

        logger.info(
            f"Fetched {len(watched_ids)} watched IDs, {len(watched_paths)} paths, "
            f"and {len(watched_names)} names from Jellyfin."
        )
        return watched_ids, watched_paths, watched_names

    async def get_jellyfin_correlation_data(self) -> dict[str, Any]:
        if not self.is_configured():
            return {}

        user_id = await self.get_current_user_id()
        if not user_id:
            return {}

        path_map: dict[str, dict[str, Any]] = {}
        tmdb_episode_map: dict[str, str] = {}
        tmdb_series_map: dict[str, str] = {}
        name_map: dict[tuple[str, str], str] = {}
        series_id_map: dict[str, dict[str, dict]] = {}
        url = f"{self._get_base_url()}/Users/{user_id}/Items"
        limit = 5000
        start_index = 0

        # Fetch episodes
        while True:
            parameters: dict[str, Any] = {
                "IncludeItemTypes": "Episode,Movie",
                "Recursive": "true",
                "Fields": "Path,SeriesId,SeasonId,ProviderIds,SeriesName",
                "Limit": limit,
                "StartIndex": start_index,
            }
            try:
                response = await self._http_client.get(
                    url, headers=self._get_headers(), params=parameters, timeout=30
                )
                items = list(response.get("Items", []))
                for item in items:
                    path = item.get("Path")
                    item_id = item.get("Id")
                    if path and item_id:
                        path_map[str(path)] = {
                            "id": str(item_id),
                            "series_id": item.get("SeriesId"),
                            "season_id": item.get("SeasonId"),
                        }

                    provider_ids = item.get("ProviderIds", {})
                    tmdb_identifier = provider_ids.get("Tmdb")
                    if tmdb_identifier and item_id:
                        tmdb_episode_map[str(tmdb_identifier)] = str(item_id)

                    series_name = item.get("SeriesName")
                    episode_name = item.get("Name")
                    if series_name and episode_name and item_id:
                        name_map[
                            (str(series_name).lower(), str(episode_name).lower())
                        ] = str(item_id)

                    series_id = item.get("SeriesId")
                    if series_id and item_id:
                        if series_id not in series_id_map:
                            series_id_map[series_id] = {"episodes": {}, "names": {}}
                        season_num = item.get("ParentIndexNumber")
                        ep_num = item.get("IndexNumber")
                        if season_num is not None and ep_num is not None:
                            series_id_map[series_id]["episodes"][
                                (season_num, ep_num)
                            ] = str(item_id)
                        if episode_name:
                            series_id_map[series_id]["names"][episode_name.lower()] = (
                                str(item_id)
                            )

                if len(items) < limit:
                    break
                start_index += limit
            except Exception:
                logger.exception("Failed to fetch episode mapping from Jellyfin")
                break

        # Fetch series
        start_index = 0
        while True:
            search_params: dict[str, Any] = {
                "IncludeItemTypes": "Series,Movie",
                "Recursive": "true",
                "Fields": "ProviderIds",
                "Limit": limit,
                "StartIndex": start_index,
            }
            try:
                response = await self._http_client.get(
                    url, headers=self._get_headers(), params=search_params, timeout=30
                )
                items = list(response.get("Items", []))
                for item in items:
                    item_id = item.get("Id")
                    provider_ids = item.get("ProviderIds", {})
                    tmdb_identifier = provider_ids.get("Tmdb")
                    if tmdb_identifier and item_id:
                        tmdb_series_map[str(tmdb_identifier)] = str(item_id)
                if len(items) < limit:
                    break
                start_index += limit
            except Exception:
                logger.exception("Failed to fetch series mapping from Jellyfin")
                break

        logger.info(
            f"Jellyfin correlation data: {len(path_map)} paths, "
            f"{len(tmdb_episode_map)} episode TMDB IDs, "
            f"{len(name_map)} episode names, "
            f"{len(tmdb_series_map)} series TMDB IDs, "
            f"{len(series_id_map)} manual series maps."
        )
        return {
            "path_map": path_map,
            "tmdb_episode_map": tmdb_episode_map,
            "tmdb_series_map": tmdb_series_map,
            "name_map": name_map,
            "series_id_map": series_id_map,
        }

    async def search_series(self, name: str) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []

        user_id = await self.get_current_user_id()
        if not user_id:
            return []

        logger.debug(f"Searching Jellyfin for series: '{name}'")
        url = f"{self._get_base_url()}/Users/{user_id}/Items"
        parameters: dict[str, Any] = {
            "SearchTerm": name,
            "IncludeItemTypes": "Series",
            "Recursive": "true",
            "Fields": "Path,ProviderIds,ProductionYear,Overview",
        }
        try:
            response = await self._http_client.get(
                url, headers=self._get_headers(), params=parameters, timeout=10
            )
            return list(response.get("Items", []))
        except Exception:
            logger.exception(f"Failed to search Jellyfin for series '{name}'")
            return []

    async def search_movie(self, name: str) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []

        user_id = await self.get_current_user_id()
        if not user_id:
            return []

        logger.debug(f"Searching Jellyfin for movie: '{name}'")
        url = f"{self._get_base_url()}/Users/{user_id}/Items"
        parameters: dict[str, Any] = {
            "SearchTerm": name,
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": "Path,ProviderIds,ProductionYear,Overview",
        }
        try:
            response = await self._http_client.get(
                url, headers=self._get_headers(), params=parameters, timeout=10
            )
            return list(response.get("Items", []))
        except Exception:
            logger.exception(f"Failed to search Jellyfin for movie '{name}'")
            return []

    async def set_watched_status(self, item_id: str, watched: bool) -> None:
        if not self.is_configured():
            return
        user_id = await self.get_current_user_id()
        if not user_id:
            return

        logger.info(
            f"Setting watched status of item '{item_id}' to {watched} in Jellyfin..."
        )
        try:
            url = f"{self._get_base_url()}/Users/{user_id}/PlayedItems/{item_id}"
            if watched:
                await self._http_client.post(
                    url, headers=self._get_headers(), timeout=5
                )
            else:
                await self._http_client.delete(
                    url, headers=self._get_headers(), timeout=5
                )
            logger.info(
                f"Successfully updated watched status for item '{item_id}' in Jellyfin."
            )
        except Exception:
            logger.exception(f"Error setting watched status for {item_id}")

    async def close(self) -> None:
        await self._http_client.close()
