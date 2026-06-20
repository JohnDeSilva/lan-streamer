import logging
import requests
import time
from typing import List, Dict, Any, Optional, Tuple
from lan_streamer.system.config import config

logger = logging.getLogger(__name__)


class MyAnimeListClient:
    """
    Client for interacting with the MyAnimeList API v2.
    Handles OAuth2 authentication with PKCE and syncs watch history.
    """

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        if hasattr(self.session, "headers") and hasattr(
            self.session.headers, "setdefault"
        ):
            self.session.headers.setdefault(
                "User-Agent",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
        if session is None:
            self.session.trust_env = True

    def is_configured(self) -> bool:
        """Checks if Client ID is configured."""
        return bool(config.myanimelist_client_id.strip())

    def is_authenticated(self) -> bool:
        """Checks if the user has authenticated and we have an access token."""
        return bool(config.myanimelist_access_token.strip())

    def get_auth_headers(self) -> Dict[str, str]:
        """
        Returns headers for authenticated MAL API requests.
        Refreshes token automatically if expired.
        """
        if not self.is_authenticated():
            # Fallback to Client ID for public endpoints
            return {"X-MAL-CLIENT-ID": config.myanimelist_client_id.strip()}

        # Check for expiry (with 5-minute buffer)
        if time.time() + 300 >= config.myanimelist_token_expires_at:
            logger.info("MAL Access token expired or close to expiry. Refreshing...")
            self.refresh_access_token()

        return {
            "Authorization": f"Bearer {config.myanimelist_access_token.strip()}",
            "Accept": "application/json",
        }

    def generate_auth_url(self, code_verifier: str) -> str:
        """
        Generates the MAL authorization URL using PKCE with 'plain' method.
        """
        client_id = config.myanimelist_client_id.strip()
        # MAL OAuth requires code_challenge_method=plain, meaning challenge is identical to verifier
        return (
            f"https://myanimelist.net/v1/oauth2/authorize"
            f"?response_type=code"
            f"&client_id={client_id}"
            f"&code_challenge={code_verifier}"
            f"&code_challenge_method=plain"
            f"&redirect_uri=http://localhost/"
        )

    def exchange_auth_code(self, code: str, code_verifier: str) -> Tuple[bool, str]:
        """
        Exchanges the authorization code for access and refresh tokens.
        """
        logger.info("Exchanging MAL authorization code for tokens...")
        url = "https://myanimelist.net/v1/oauth2/token"
        data = {
            "client_id": config.myanimelist_client_id.strip(),
            "grant_type": "authorization_code",
            "code": code.strip(),
            "code_verifier": code_verifier.strip(),
            "redirect_uri": "http://localhost/",
        }
        if config.myanimelist_client_secret.strip():
            data["client_secret"] = config.myanimelist_client_secret.strip()

        try:
            response = self.session.post(url, data=data, timeout=15)
            if response.status_code != 200:
                try:
                    err_json = response.json()
                    error_msg = (
                        err_json.get("error_description")
                        or err_json.get("message")
                        or err_json.get("error")
                    )
                except Exception:
                    error_msg = None
                if not error_msg:
                    error_msg = response.text
                logger.error(
                    f"MyAnimeList token exchange failed ({response.status_code}): {error_msg}"
                )
                return (
                    False,
                    f"Authentication failed ({response.status_code}): {error_msg}",
                )

            response.raise_for_status()
            token_data = response.json()

            config.myanimelist_access_token = token_data.get("access_token", "")
            config.myanimelist_refresh_token = token_data.get("refresh_token", "")
            expires_in = token_data.get("expires_in", 2419200)  # Default 28 days
            config.myanimelist_token_expires_at = time.time() + expires_in
            config.save_to_db()

            logger.info("Successfully authenticated with MyAnimeList.")
            return True, "Authentication successful!"
        except Exception as e:
            logger.exception("Failed to exchange MyAnimeList auth code")
            return False, f"Authentication failed: {e}"

    def refresh_access_token(self) -> bool:
        """
        Uses the refresh token to obtain a new access token.
        """
        if not config.myanimelist_refresh_token:
            logger.error("No MyAnimeList refresh token available.")
            return False

        logger.info("Refreshing MyAnimeList access token...")
        url = "https://myanimelist.net/v1/oauth2/token"
        data = {
            "client_id": config.myanimelist_client_id.strip(),
            "grant_type": "refresh_token",
            "refresh_token": config.myanimelist_refresh_token.strip(),
        }
        if config.myanimelist_client_secret.strip():
            data["client_secret"] = config.myanimelist_client_secret.strip()

        try:
            response = self.session.post(url, data=data, timeout=15)
            response.raise_for_status()
            token_data = response.json()

            config.myanimelist_access_token = token_data.get("access_token", "")
            config.myanimelist_refresh_token = token_data.get("refresh_token", "")
            expires_in = token_data.get("expires_in", 2419200)
            config.myanimelist_token_expires_at = time.time() + expires_in
            config.save_to_db()

            logger.info("Successfully refreshed MyAnimeList access token.")
            return True
        except Exception:
            logger.exception("Failed to refresh MyAnimeList access token")
            return False

    def remove_connection(self) -> None:
        """Clears all MyAnimeList authentication tokens."""
        config.myanimelist_access_token = ""
        config.myanimelist_refresh_token = ""
        config.myanimelist_token_expires_at = 0.0
        config.save_to_db()
        logger.info("Removed MyAnimeList connection credentials.")

    def search_anime(self, query: str) -> List[Dict[str, Any]]:
        """
        Searches MyAnimeList for anime matching the given query string.
        """
        if not self.is_configured():
            logger.warning("MAL is not configured; cannot search.")
            return []

        logger.debug(f"Searching MyAnimeList for: '{query}'")
        url = "https://api.myanimelist.net/v2/anime"
        params: Dict[str, Any] = {
            "q": query,
            "limit": 50,
            "fields": "id,title,main_picture,num_episodes,alternative_titles,start_date",
        }

        try:
            headers = self.get_auth_headers()
            response = self.session.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = []
            for node in data.get("data", []):
                anime = node.get("node", {})
                pic_dict = anime.get("main_picture") or {}
                results.append(
                    {
                        "id": anime.get("id"),
                        "title": anime.get("title") or "",
                        "num_episodes": anime.get("num_episodes") or 0,
                        "poster_path": pic_dict.get("medium")
                        or pic_dict.get("large")
                        or "",
                        "start_date": anime.get("start_date") or "",
                    }
                )
            return results
        except Exception:
            logger.exception(f"Failed to search MyAnimeList for '{query}'")
            return []

    def get_anime_details(self, anime_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetches full details of a specific MyAnimeList entry.
        """
        if not self.is_configured():
            return None

        url = f"https://api.myanimelist.net/v2/anime/{anime_id}"
        params = {
            "fields": "id,title,main_picture,num_episodes,alternative_titles,start_date",
        }

        try:
            headers = self.get_auth_headers()
            response = self.session.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception:
            logger.exception(f"Failed to fetch MAL details for ID: {anime_id}")
            return None

    def update_watched_status(
        self, anime_id: int, num_watched_episodes: int, total_episodes: int = 0
    ) -> bool:
        """
        Updates the watched status of a specific anime on MAL.
        """
        if not self.is_configured() or not self.is_authenticated():
            logger.warning(
                "MAL is not configured or not authenticated; cannot update status."
            )
            return False

        logger.info(
            f"Updating MAL ID {anime_id} status: watched {num_watched_episodes} episodes"
        )
        url = f"https://api.myanimelist.net/v2/anime/{anime_id}/my_list_status"

        status = "watching"
        if total_episodes > 0 and num_watched_episodes >= total_episodes:
            status = "completed"

        data = {
            "status": status,
            "num_watched_episodes": int(num_watched_episodes),
        }

        try:
            headers = self.get_auth_headers()
            response = self.session.put(url, headers=headers, data=data, timeout=10)
            if response.status_code != 200:
                logger.error(
                    f"Failed to update MAL status for ID {anime_id} (HTTP {response.status_code}): {response.text}"
                )
                return False
            logger.info(f"Successfully updated MAL status for ID {anime_id}.")
            return True
        except Exception:
            logger.exception(f"Failed to update MAL watched status for ID {anime_id}")
            return False


myanimelist_client = MyAnimeListClient()
