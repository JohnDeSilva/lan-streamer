import logging
import requests
from typing import List, Dict, Any, Optional
from .config import config

logger = logging.getLogger(__name__)

OPENSUBTITLES_API_BASE = "https://api.opensubtitles.com/api/v1/"
USER_AGENT = "LAN-Streamer/0.14.1"


class OpenSubtitlesClient:
    def __init__(self) -> None:
        self.token: Optional[str] = None

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Api-Key": config.opensubtitles_api_key,
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def login(self) -> bool:
        """Log in to OpenSubtitles.com to get an authentication token."""
        if not config.opensubtitles_username or not config.opensubtitles_password:
            logger.warning("OpenSubtitles credentials missing, skipping login.")
            return False

        url = f"{OPENSUBTITLES_API_BASE}login"
        payload = {
            "username": config.opensubtitles_username,
            "password": config.opensubtitles_password,
        }
        try:
            response = requests.post(
                url, json=payload, headers=self._get_headers(), timeout=15
            )
            if response.status_code == 200:
                self.token = response.json().get("token")
                logger.info("Successfully logged in to OpenSubtitles.com")
                return True
            else:
                logger.error(
                    f"OpenSubtitles login failed: {response.status_code} {response.text}"
                )
        except Exception as e:
            logger.exception(f"Error logging in to OpenSubtitles: {e}")
        return False

    def search_subtitles(
        self,
        query: Optional[str] = None,
        tmdb_id: Optional[int] = None,
        season_number: Optional[int] = None,
        episode_number: Optional[int] = None,
        languages: str = "en",
    ) -> List[Dict[str, Any]]:
        """Search for subtitles on OpenSubtitles.com."""
        if not config.opensubtitles_api_key:
            logger.warning("OpenSubtitles API Key missing.")
            return []

        url = f"{OPENSUBTITLES_API_BASE}subtitles"
        params: Dict[str, Any] = {"languages": languages}

        if tmdb_id:
            params["tmdb_id"] = tmdb_id
            if season_number is not None:
                params["season_number"] = season_number
            if episode_number is not None:
                params["episode_number"] = episode_number
        elif query:
            params["query"] = query

        try:
            response = requests.get(
                url, params=params, headers=self._get_headers(), timeout=15
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("data", [])
            else:
                logger.error(
                    f"OpenSubtitles search failed: {response.status_code} {response.text}"
                )
        except Exception as e:
            logger.exception(f"Error searching OpenSubtitles: {e}")
        return []

    def get_download_link(self, file_id: int) -> Optional[str]:
        """Request a download link for a specific subtitle file."""
        if not self.token:
            self.login()

        if not self.token:
            logger.warning("OpenSubtitles token missing, cannot download.")
            # Note: anonymous download might be possible but requires different flow or is restricted
            return None

        url = f"{OPENSUBTITLES_API_BASE}download"
        payload = {"file_id": file_id}
        try:
            response = requests.post(
                url, json=payload, headers=self._get_headers(), timeout=15
            )
            if response.status_code == 200:
                return response.json().get("link")
            else:
                logger.error(
                    f"OpenSubtitles download request failed: {response.status_code} {response.text}"
                )
        except Exception as e:
            logger.exception(f"Error getting OpenSubtitles download link: {e}")
        return None

    def download_subtitle(self, download_url: str) -> Optional[bytes]:
        """Download the actual subtitle content."""
        try:
            response = requests.get(download_url, timeout=30)
            if response.status_code == 200:
                return response.content
            else:
                logger.error(
                    f"Failed to download subtitle from {download_url}: {response.status_code}"
                )
        except Exception as e:
            logger.exception(f"Error downloading subtitle content: {e}")
        return None


opensubtitles_client = OpenSubtitlesClient()
