import logging
import requests
import socket
from pathlib import Path
from .config import config

# Log networking setup
logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".config" / "lan-streamer" / "cache" / "images"


class JellyfinClient:
    def __init__(self):
        self.session = requests.Session()

        # Add browser-like User-Agent to avoid being blocked by WAFs/Firewalls
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )

        # Re-enable trust_env (default) because browsers often work BECAUSE of system proxies
        self.session.trust_env = True
        self._cached_user_id = None

    def validate_credentials(self, url: str, api_key: str):
        """Tests connection with specific credentials without saving them to config."""
        url = url.strip().rstrip("/")
        if not url:
            return False, "URL is required."
        if not api_key:
            return False, "API Key is required."

        # Explicitly ignore system proxies for this test to avoid environment-related 'No route to host'
        self.session.proxies = {"http": None, "https": None}

        if not url.startswith("http"):
            import re

            is_ip = re.match(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$", url)
            if "." in url and not url.startswith("localhost") and not is_ip:
                url = f"https://{url}"
            else:
                url = f"http://{url}"

        # Parse host and port for raw socket test
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        # 1. Raw Socket Test
        try:
            logger.info(f"Step 1: Testing raw socket connection to {host}:{port}")
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

    def _get_headers(self):
        token = config.jellyfin_api_key.strip()
        authorization_string = f'MediaBrowser Client="LanStreamer", Device="Desktop", DeviceId="lan-streamer-1", Version="1.0.0", Token="{token}"'
        return {
            "Authorization": authorization_string,
            "Accept": "application/json",
        }

    def _get_base_url(self):
        url = config.jellyfin_url.strip().rstrip("/")
        if not url:
            return ""
        if not url.startswith("http"):
            # Default to https if it looks like a domain, otherwise http
            # Avoid https for IP addresses (including with ports) and localhost
            import re

            # Improved regex to handle IPs with optional port numbers
            is_ip = re.match(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$", url)
            if "." in url and not url.startswith("localhost") and not is_ip:
                url = f"https://{url}"
            else:
                url = f"http://{url}"
        return url

    def is_configured(self) -> bool:
        return bool(config.jellyfin_url and config.jellyfin_api_key)

    def get_current_user_id(self):
        if not self.is_configured():
            return None
        if self._cached_user_id:
            return self._cached_user_id

        base_url = self._get_base_url()
        url = f"{base_url}/Users"
        try:
            logger.debug(f"Attempting to connect to Jellyfin at: {url}")
            response = self.session.get(url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()
            users = response.json()
            if users and len(users) > 0:
                self._cached_user_id = users[0].get("Id")
                return self._cached_user_id
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error reaching Jellyfin at {base_url}: {e}")
            # If https failed, maybe try http if not explicitly specified?
            # But only if we were the ones who added https://
            if base_url.startswith("https://") and not config.jellyfin_url.startswith(
                "https://"
            ):
                logger.info("Retrying with http...")
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
                except Exception as retry_e:
                    logger.error(f"Retry with http failed: {retry_e}")
        except Exception as e:
            logger.error(f"Unexpected error getting current user: {e}", exc_info=True)
        return None

    def search_series(self, name: str):
        if not self.is_configured():
            return None
        url = f"{self._get_base_url()}/Items"
        parameters = {
            "SearchTerm": name,
            "IncludeItemTypes": "Series",
            "Limit": 1,
            "Recursive": "true",
        }
        try:
            response = self.session.get(
                url, headers=self._get_headers(), params=parameters, timeout=5
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("Items", [])
            if items:
                return items[0]
        except Exception as e:
            logger.error(f"Error searching for series '{name}': {e}")
        return None

    def get_seasons(self, series_id: str):
        if not self.is_configured():
            return []
        user_id = self.get_current_user_id()
        url = f"{self._get_base_url()}/Shows/{series_id}/Seasons"
        parameters = {}
        if user_id:
            parameters["UserId"] = user_id

        try:
            response = self.session.get(
                url, headers=self._get_headers(), params=parameters, timeout=5
            )
            response.raise_for_status()
            return response.json().get("Items", [])
        except Exception as e:
            logger.error(f"Error getting seasons for series {series_id}: {e}")
        return []

    def get_episodes(self, series_id: str, season_id: str):
        if not self.is_configured():
            return []
        user_id = self.get_current_user_id()
        url = f"{self._get_base_url()}/Shows/{series_id}/Episodes"
        parameters = {"SeasonId": season_id, "Fields": "Path,Overview"}
        if user_id:
            parameters["UserId"] = user_id

        try:
            response = self.session.get(
                url, headers=self._get_headers(), params=parameters, timeout=5
            )
            response.raise_for_status()
            return response.json().get("Items", [])
        except Exception as e:
            logger.error(f"Error getting episodes for season {season_id}: {e}")
        return []

    def download_image(self, item_id: str) -> str:
        """Downloads primary image for item and returns local path."""
        if not self.is_configured() or not item_id:
            return ""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        image_path = CACHE_DIR / f"{item_id}.jpg"

        if image_path.exists():
            return str(image_path)

        url = f"{self._get_base_url()}/Items/{item_id}/Images/Primary"
        try:
            response = self.session.get(url, timeout=5)
            if response.status_code == 200:
                with open(image_path, "wb") as f:
                    f.write(response.content)
                return str(image_path)
        except Exception as e:
            logger.error(f"Error downloading image for {item_id}: {e}")
        return ""

    def set_watched_status(self, item_id: str, watched: bool):
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
