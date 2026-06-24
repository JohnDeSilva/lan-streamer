"""
jellyfin.py — Jellyfin integration used exclusively for watch-history sync.

Metadata (series/season/episode info, artwork) is now pulled from TMDB.
Jellyfin is used only to:
  1. Pull played/unplayed state per episode (inbound sync on startup)
  2. Push played/unplayed state per episode (outbound sync when user marks an episode)
"""

import logging
import requests
from lan_streamer.system.config import config

logger = logging.getLogger(__name__)


class JellyfinClient:
    """Client for interacting with the Jellyfin server API to sync played/unplayed watched history states."""

    def __init__(
        self,
        session: requests.Session | None = None,
        jellyfin_url: str | None = None,
        jellyfin_api_key: str | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self._jellyfin_url = jellyfin_url
        self._jellyfin_api_key = jellyfin_api_key
        self.session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        if session is None:
            self.session.trust_env = True
        self._cached_user_id: str | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

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

    def _get_headers(self) -> dict:
        token = self._effective_api_key.strip()
        auth = f'MediaBrowser Client="LanStreamer", Device="Desktop", DeviceId="lan-streamer-1", Version="1.0.0", Token="{token}"'
        return {
            "Authorization": auth,
            "Accept": "application/json",
        }

    def _get_base_url(self) -> str:
        url = self._effective_url.strip().rstrip("/")
        if not url:
            return ""
        if not url.startswith("http"):
            import re

            is_ip_address = re.match(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$", url)
            if "." in url and not url.startswith("localhost") and not is_ip_address:
                url = f"https://{url}"
            else:
                url = f"http://{url}"
        return url

    # ------------------------------------------------------------------
    # User identity
    # ------------------------------------------------------------------

    def get_current_user_id(self) -> str | None:
        if not self.is_configured():
            return None
        if self._cached_user_id:
            return self._cached_user_id

        base_url = self._get_base_url()
        url = f"{base_url}/Users"
        try:
            logger.debug(f"Fetching Jellyfin user from: {url}")
            response = self.session.get(url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()
            users = response.json()
            if users and len(users) > 0:
                self._cached_user_id = users[0].get("Id")
                return self._cached_user_id
        except requests.exceptions.ConnectionError:
            logger.exception(f"Connection error reaching Jellyfin at {base_url}")
            if base_url.startswith("https://") and not self._effective_url.startswith(
                "https://"
            ):
                logger.info("Retrying Jellyfin with http...")
                try:
                    url = url.replace("https://", "http://")
                    response = self.session.get(
                        url, headers=self._get_headers(), timeout=10
                    )
                    response.raise_for_status()
                    users = response.json()
                    if users and len(users) > 0:
                        self._cached_user_id = users[0].get("Id")
                        return self._cached_user_id
                except Exception:
                    logger.exception("Retry with http failed")
        except Exception:
            logger.exception("Unexpected error getting Jellyfin user")
        return None

    # ------------------------------------------------------------------
    # Credential validation
    # ------------------------------------------------------------------
    # Watch history — inbound (pull from Jellyfin → local DB)
    # ------------------------------------------------------------------

    def fetch_watched_episodes(self) -> tuple:
        """
        Fetches all watched episodes for the current user.
        Returns (watched_ids, watched_paths, watched_names).
        """
        if not self.is_configured():
            return set(), set(), set()

        user_id = self.get_current_user_id()
        if not user_id:
            return set(), set(), set()

        watched_ids = set()
        watched_paths = set()
        watched_names = set()
        url = f"{self._get_base_url()}/Users/{user_id}/Items"
        limit = 5000
        start_index = 0

        while True:
            parameters: dict[str, str | int] = {
                "IncludeItemTypes": "Episode,Movie",
                "Recursive": "true",
                "Fields": "Path,SeriesName",
                "Filters": "IsPlayed",
                "Limit": limit,
                "StartIndex": start_index,
            }
            try:
                response = self.session.get(
                    url, headers=self._get_headers(), params=parameters, timeout=30
                )
                response.raise_for_status()
                data = response.json()
                items = data.get("Items", [])
                for item in items:
                    item_id = item.get("Id")
                    path = item.get("Path")
                    if item_id:
                        watched_ids.add(item_id)
                    if path:
                        watched_paths.add(path)

                    series_name = item.get("SeriesName")
                    episode_name = item.get("Name")
                    if series_name and episode_name:
                        watched_names.add((series_name.lower(), episode_name.lower()))
                if len(items) < limit:
                    break
                start_index += limit
            except Exception:
                logger.exception("Failed to fetch watched episodes from Jellyfin")
                break

        logger.info(
            f"Fetched {len(watched_ids)} watched IDs, {len(watched_paths)} paths, and {len(watched_names)} names from Jellyfin."
        )
        return watched_ids, watched_paths, watched_names

    def get_jellyfin_correlation_data(self) -> dict:
        """
        Fetches all episodes, series, and seasons from Jellyfin to build correlation maps.
        Returns a dict containing:
          - path_map: {file_path: {id, series_id, season_id}}
          - tmdb_episode_map: {tmdb_episode_identifier: jellyfin_id}
          - tmdb_series_map: {tmdb_series_id: jellyfin_id}
          - name_map: {(series_name, episode_name): jellyfin_id}
        """
        if not self.is_configured():
            return {}

        user_id = self.get_current_user_id()
        if not user_id:
            return {}

        path_map = {}
        tmdb_episode_map = {}
        tmdb_series_map = {}
        name_map = {}
        series_id_map: dict[
            str, dict[str, dict]
        ] = {}  # {series_id: { episodes: {(season_num, ep_num): id}, names: {name: id} }}

        # 1. Fetch Episodes for Path and TMDB mapping
        url = f"{self._get_base_url()}/Users/{user_id}/Items"
        limit = 5000
        start_index = 0

        while True:
            parameters: dict[str, str | int] = {
                "IncludeItemTypes": "Episode,Movie",
                "Recursive": "true",
                "Fields": "Path,SeriesId,SeasonId,ProviderIds,SeriesName",
                "Limit": limit,
                "StartIndex": start_index,
            }
            try:
                response = self.session.get(
                    url, headers=self._get_headers(), params=parameters, timeout=30
                )
                response.raise_for_status()
                data = response.json()
                items = data.get("Items", [])
                for item in items:
                    path = item.get("Path")
                    item_id = item.get("Id")
                    if path and item_id:
                        path_map[path] = {
                            "id": item_id,
                            "series_id": item.get("SeriesId"),
                            "season_id": item.get("SeasonId"),
                        }

                    provider_ids = item.get("ProviderIds", {})
                    tmdb_identifier = provider_ids.get("Tmdb")
                    if tmdb_identifier and item_id:
                        tmdb_episode_map[str(tmdb_identifier)] = item_id

                    # Name-based mapping
                    series_name = item.get("SeriesName")
                    episode_name = item.get("Name")
                    if series_name and episode_name and item_id:
                        name_map[(series_name.lower(), episode_name.lower())] = item_id

                    # Series ID based mapping for manual links
                    series_id = item.get("SeriesId")
                    if series_id and item_id:
                        if series_id not in series_id_map:
                            series_id_map[series_id] = {"episodes": {}, "names": {}}

                        # Store by SxxExx if possible
                        # Jellyfin doesn't always provide SxxExx in a clean way in this API,
                        # but it has ParentIndexNumber (Season) and IndexNumber (Episode)
                        season_num = item.get("ParentIndexNumber")
                        ep_num = item.get("IndexNumber")
                        if season_num is not None and ep_num is not None:
                            series_id_map[series_id]["episodes"][
                                (season_num, ep_num)
                            ] = item_id

                        if episode_name:
                            series_id_map[series_id]["names"][episode_name.lower()] = (
                                item_id
                            )

                if len(items) < limit:
                    break
                start_index += limit
            except Exception:
                logger.exception("Failed to fetch episode mapping from Jellyfin")
                break

        # 2. Fetch Series for TMDB mapping
        start_index = 0
        while True:
            search_params: dict[str, str | int] = {
                "IncludeItemTypes": "Series,Movie",
                "Recursive": "true",
                "Fields": "ProviderIds",
                "Limit": limit,
                "StartIndex": start_index,
            }
            try:
                response = self.session.get(
                    url, headers=self._get_headers(), params=search_params, timeout=30
                )
                response.raise_for_status()
                data = response.json()
                items = data.get("Items", [])
                for item in items:
                    item_id = item.get("Id")
                    provider_ids = item.get("ProviderIds", {})
                    tmdb_identifier = provider_ids.get("Tmdb")
                    if tmdb_identifier and item_id:
                        tmdb_series_map[str(tmdb_identifier)] = item_id
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

    # ------------------------------------------------------------------
    # Series Matching — manual link support
    # ------------------------------------------------------------------

    def search_series(self, name: str) -> list:
        """
        Searches Jellyfin for series matching the given name.
        Returns a list of series items.
        """
        if not self.is_configured():
            return []

        user_id = self.get_current_user_id()
        if not user_id:
            return []

        logger.debug(f"Searching Jellyfin for series: '{name}'")

        url = f"{self._get_base_url()}/Users/{user_id}/Items"
        parameters = {
            "SearchTerm": name,
            "IncludeItemTypes": "Series",
            "Recursive": "true",
            "Fields": "Path,ProviderIds,ProductionYear,Overview",
        }
        try:
            response = self.session.get(
                url, headers=self._get_headers(), params=parameters, timeout=10
            )
            response.raise_for_status()
            data = response.json()
            return data.get("Items", [])
        except Exception:
            logger.exception(f"Failed to search Jellyfin for series '{name}'")
            return []

    def search_movie(self, name: str) -> list:
        """
        Searches Jellyfin for movies matching the given name.
        Returns a list of movie items.
        """
        if not self.is_configured():
            return []

        user_id = self.get_current_user_id()
        if not user_id:
            return []

        logger.debug(f"Searching Jellyfin for movie: '{name}'")

        url = f"{self._get_base_url()}/Users/{user_id}/Items"
        parameters = {
            "SearchTerm": name,
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": "Path,ProviderIds,ProductionYear,Overview",
        }
        try:
            response = self.session.get(
                url, headers=self._get_headers(), params=parameters, timeout=10
            )
            response.raise_for_status()
            data = response.json()
            return data.get("Items", [])
        except Exception:
            logger.exception(f"Failed to search Jellyfin for movie '{name}'")
            return []

    # ------------------------------------------------------------------
    # Watch history — outbound (push local state → Jellyfin)
    # ------------------------------------------------------------------

    def set_watched_status(self, item_id: str, watched: bool) -> None:
        """Pushes a played/unplayed status for a single episode to Jellyfin."""
        if not self.is_configured():
            return
        user_id = self.get_current_user_id()
        if not user_id:
            return

        logger.info(
            f"Setting watched status of item '{item_id}' to {watched} in Jellyfin..."
        )
        try:
            if watched:
                url = f"{self._get_base_url()}/Users/{user_id}/PlayedItems/{item_id}"
                self.session.post(url, headers=self._get_headers(), timeout=5)
            else:
                url = f"{self._get_base_url()}/Users/{user_id}/PlayedItems/{item_id}"
                self.session.delete(url, headers=self._get_headers(), timeout=5)
            logger.info(
                f"Successfully updated watched status for item '{item_id}' in Jellyfin."
            )
        except Exception:
            logger.exception(f"Error setting watched status for {item_id}")


jellyfin_client = JellyfinClient()
