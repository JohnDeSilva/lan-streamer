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
from .config import config

logger = logging.getLogger(__name__)


class JellyfinClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        self.session.trust_env = True
        self._cached_user_id = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(config.jellyfin_url and config.jellyfin_api_key)

    def _get_headers(self):
        token = config.jellyfin_api_key.strip()
        auth = f'MediaBrowser Client="LanStreamer", Device="Desktop", DeviceId="lan-streamer-1", Version="1.0.0", Token="{token}"'
        return {
            "Authorization": auth,
            "Accept": "application/json",
        }

    def _get_base_url(self):
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

    def get_current_user_id(self):
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
        except requests.exceptions.ConnectionError as exception:
            logger.error(
                f"Connection error reaching Jellyfin at {base_url}: {exception}"
            )
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
                except Exception as retry_exception:
                    logger.error(f"Retry with http failed: {retry_exception}")
        except Exception as exception:
            logger.error(
                f"Unexpected error getting Jellyfin user: {exception}", exc_info=True
            )
        return None

    # ------------------------------------------------------------------
    # Credential validation
    # ------------------------------------------------------------------

    def validate_credentials(self, url: str, api_key: str):
        """Tests connection with specific credentials without saving them."""
        url = url.strip().rstrip("/")
        if not url:
            return False, "URL is required."
        if not api_key:
            return False, "API Key is required."

        self.session.proxies = {"http": None, "https": None}

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
            logger.error(f"Raw socket failed: {e}")
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
            logger.error(f"HTTP connection failed: {e}")
            return False, f"HTTP connection failed: {e}"
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                return False, "Invalid API Key (Unauthorized)."
            return False, f"HTTP Error: {e}"
        except Exception as e:
            logger.error(f"Unexpected error testing {test_url}: {e}")
            return False, f"Unexpected error: {e}"

    # ------------------------------------------------------------------
    # Watch history — inbound (pull from Jellyfin → local DB)
    # ------------------------------------------------------------------

    def fetch_watched_episode_paths(self) -> set:
        """
        Returns a set of file paths for episodes Jellyfin considers played.
        Used by the startup history sync to update local DB watched flags.
        """
        if not self.is_configured():
            return set()

        user_id = self.get_current_user_id()
        if not user_id:
            return set()

        watched_paths = set()
        url = f"{self._get_base_url()}/Users/{user_id}/Items"
        limit = 5000
        start_index = 0

        while True:
            params = {
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "Path",
                "Filters": "IsPlayed",
                "Limit": limit,
                "StartIndex": start_index,
            }
            try:
                resp = self.session.get(
                    url, headers=self._get_headers(), params=params, timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("Items", [])
                for item in items:
                    path = item.get("Path")
                    if path:
                        watched_paths.add(path)
                if len(items) < limit:
                    break
                start_index += limit
            except Exception as e:
                logger.error(f"Failed to fetch watched episodes from Jellyfin: {e}")
                break

        logger.info(
            f"Fetched {len(watched_paths)} watched episode paths from Jellyfin."
        )
        return watched_paths

    # ------------------------------------------------------------------
    # Watch history — outbound (push local state → Jellyfin)
    # ------------------------------------------------------------------

    def set_watched_status(self, item_id: str, watched: bool):
        """Pushes a played/unplayed status for a single episode to Jellyfin."""
        if not self.is_configured():
            return
        user_id = self.get_current_user_id()
        if not user_id:
            return

        try:
            if watched:
                url = f"{self._get_base_url()}/Users/{user_id}/PlayedItems/{item_id}"
                self.session.post(url, headers=self._get_headers(), timeout=5)
            else:
                url = f"{self._get_base_url()}/Users/{user_id}/PlayedItems/{item_id}"
                self.session.delete(url, headers=self._get_headers(), timeout=5)
        except Exception as e:
            logger.error(f"Error setting watched status for {item_id}: {e}")


jellyfin_client = JellyfinClient()
