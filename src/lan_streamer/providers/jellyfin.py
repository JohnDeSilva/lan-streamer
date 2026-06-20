"""
jellyfin.py — Jellyfin integration used exclusively for watch-history sync.

Metadata (series/season/episode info, artwork) is now pulled from TMDB.
Jellyfin is used only to:
  1. Pull played/unplayed state per episode (inbound sync on startup)
  2. Push played/unplayed state per episode (outbound sync when user marks an episode)
"""

import logging
import requests
import socket
from lan_streamer.system.config import config

logger = logging.getLogger(__name__)


class JellyfinClient:
    """Client for interacting with the Jellyfin server API to sync played/unplayed watched history states."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        if session is None:
            self.session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )
            self.session.trust_env = True
        self._cached_user_id: str | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(config.jellyfin_url and config.jellyfin_api_key)

    def _get_headers(self) -> dict:
        token = config.jellyfin_api_key.strip()
        auth = f'MediaBrowser Client="LanStreamer", Device="Desktop", DeviceId="lan-streamer-1", Version="1.0.0", Token="{token}"'
        return {
            "Authorization": auth,
            "Accept": "application/json",
        }

    def _get_base_url(self) -> str:
        url = config.jellyfin_url.strip().rstrip("/")
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
            if base_url.startswith("https://") and not config.jellyfin_url.startswith(
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

    def validate_credentials(self, url: str, api_key: str) -> tuple[bool, str]:
        """Tests connection with specific credentials without saving them."""
        url = url.strip().rstrip("/")
        if not url:
            return False, "URL is required."
        if not api_key:
            return False, "API Key is required."

        self.session.proxies = {"http": None, "https": None}  # type: ignore[dict-item]

        if not url.startswith("http"):
            import re

            is_ip = re.match(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$", url)
            if "." in url and not url.startswith("localhost") and not is_ip:
                url = f"https://{url}"
            else:
                url = f"http://{url}"

        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        # 1. Raw Socket Test
        try:
            logger.info(f"Step 1: Testing raw socket to {host}:{port}")
            s = socket.create_connection((host, port), timeout=5)
            s.close()
            logger.info("Raw socket connection successful!")
        except Exception as e:
            logger.exception("Raw socket failed")
            return (
                False,
                f"System-level connection failed (Socket Error): {e}\nThis usually means a firewall or VPN is blocking the application.",
            )

        # 2. Requests Test
        test_url = f"{url}/Users"
        token = api_key.strip()
        auth = f'MediaBrowser Client="LanStreamer", Device="Desktop", DeviceId="lan-streamer-1", Version="1.0.0", Token="{token}"'
        headers = {
            "Authorization": auth,
            "Accept": "application/json",
        }

        try:
            logger.info(f"Step 2: Testing HTTP request to {test_url}")
            response = self.session.get(test_url, headers=headers, timeout=10)
            response.raise_for_status()
            return True, "Connection successful!"
        except requests.exceptions.ConnectionError as e:
            logger.exception("HTTP connection failed")
            return False, f"HTTP connection failed: {e}"
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                return False, "Invalid API Key (Unauthorized)."
            return False, f"HTTP Error: {e}"
        except Exception as e:
            logger.exception(f"Unexpected error testing {test_url}")
            return False, f"Unexpected error: {e}"

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

    def mark_as_played(self, item_id: str) -> bool:
        """Marks an item as played in Jellyfin."""
        if not self.is_configured() or not item_id:
            return False

        user_id = self.get_current_user_id()
        if not user_id:
            return False

        logger.info(f"Marking item '{item_id}' as played in Jellyfin...")
        url = f"{self._get_base_url()}/Users/{user_id}/PlayedItems/{item_id}"
        try:
            response = self.session.post(url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()
            logger.info(f"Successfully marked item '{item_id}' as played.")
            return True
        except Exception:
            logger.exception(f"Failed to mark item {item_id} as played")
            return False

    def unmark_as_played(self, item_id: str) -> bool:
        """Marks an item as unplayed in Jellyfin."""
        if not self.is_configured() or not item_id:
            return False

        user_id = self.get_current_user_id()
        if not user_id:
            return False

        logger.info(f"Unmarking item '{item_id}' as played in Jellyfin...")
        url = f"{self._get_base_url()}/Users/{user_id}/PlayedItems/{item_id}"
        try:
            response = self.session.delete(url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()
            logger.info(f"Successfully unmarked item '{item_id}' as played.")
            return True
        except Exception:
            logger.exception(f"Failed to unmark item {item_id} as played")
            return False

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

    def get_series_episodes(self, series_id: str) -> list:
        """
        Fetches all episodes belonging to a specific Jellyfin series ID.
        Returns a list of episode items with Path and ProviderIds.
        """
        if not self.is_configured() or not series_id:
            return []

        user_id = self.get_current_user_id()
        if not user_id:
            return []

        url = f"{self._get_base_url()}/Users/{user_id}/Items"
        parameters = {
            "ParentId": series_id,
            "IncludeItemTypes": "Episode",
            "Recursive": "true",
            "Fields": "Path,ProviderIds,SeasonId,SeriesId,SeriesName,UserData",
        }
        try:
            response = self.session.get(
                url, headers=self._get_headers(), params=parameters, timeout=20
            )
            response.raise_for_status()
            data = response.json()
            return data.get("Items", [])
        except Exception:
            logger.exception(
                f"Failed to fetch episodes for Jellyfin series {series_id}"
            )
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
