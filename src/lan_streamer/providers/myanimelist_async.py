"""
Async MyAnimeList client.

Mirror of the synchronous :class:`MyAnimeListClient` but fully async,
using :class:`AsyncHTTPClient` instead of ``requests.Session``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import aiohttp

from lan_streamer.providers.http_client import AsyncHTTPClient
from lan_streamer.system.config import config

logger = logging.getLogger(__name__)


class AsyncMyAnimeListClient:
    """Async client for interacting with the MyAnimeList API v2.

    Handles OAuth2 authentication with PKCE and syncs watch history.
    All network calls go through :class:`AsyncHTTPClient`.
    """

    def __init__(self) -> None:
        self._http_client = AsyncHTTPClient(requests_per_second=10.0, timeout=10.0)

    def is_configured(self) -> bool:
        return bool(config.myanimelist_client_id.strip())

    def is_authenticated(self) -> bool:
        return bool(config.myanimelist_access_token.strip())

    async def _get_auth_headers(self) -> dict[str, str]:
        if not self.is_authenticated():
            return {"X-MAL-CLIENT-ID": config.myanimelist_client_id.strip()}

        if time.time() + 300 >= config.myanimelist_token_expires_at:
            logger.info("MAL Access token expired or close to expiry. Refreshing...")
            await self.refresh_access_token()

        return {
            "Authorization": f"Bearer {config.myanimelist_access_token.strip()}",
            "Accept": "application/json",
        }

    def generate_auth_url(self, code_verifier: str) -> str:
        client_id = config.myanimelist_client_id.strip()
        return (
            f"https://myanimelist.net/v1/oauth2/authorize"
            f"?response_type=code"
            f"&client_id={client_id}"
            f"&code_challenge={code_verifier}"
            f"&code_challenge_method=plain"
            f"&redirect_uri=http://localhost/"
        )

    async def exchange_auth_code(
        self, code: str, code_verifier: str
    ) -> tuple[bool, str]:
        logger.info("Exchanging MAL authorization code for tokens...")
        url = "https://myanimelist.net/v1/oauth2/token"
        data: dict[str, Any] = {
            "client_id": config.myanimelist_client_id.strip(),
            "grant_type": "authorization_code",
            "code": code.strip(),
            "code_verifier": code_verifier.strip(),
            "redirect_uri": "http://localhost/",
        }
        if config.myanimelist_client_secret.strip():
            data["client_secret"] = config.myanimelist_client_secret.strip()

        try:
            session = await self._http_client._get_session()
            async with session.post(
                url, data=data, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    try:
                        error_data = await response.json()
                        error_msg = (
                            error_data.get("error_description")
                            or error_data.get("message")
                            or error_data.get("error")
                            or str(error_data)
                        )
                    except Exception:
                        error_msg = await response.text()
                    logger.error(
                        f"MyAnimeList token exchange failed ({response.status}): {error_msg}"
                    )
                    return (
                        False,
                        f"Authentication failed ({response.status}): {error_msg}",
                    )

                token_data = await response.json()
                config.myanimelist_access_token = token_data.get("access_token", "")
                config.myanimelist_refresh_token = token_data.get("refresh_token", "")
                expires_in = token_data.get("expires_in", 2419200)
                config.myanimelist_token_expires_at = time.time() + expires_in
                config.save_to_db()

                logger.info("Successfully authenticated with MyAnimeList.")
                return True, "Authentication successful!"
        except Exception as exception:
            logger.exception("Failed to exchange MyAnimeList auth code")
            return False, f"Authentication failed: {exception}"

    async def refresh_access_token(self) -> bool:
        if not config.myanimelist_refresh_token:
            logger.error("No MyAnimeList refresh token available.")
            return False

        logger.info("Refreshing MyAnimeList access token...")
        url = "https://myanimelist.net/v1/oauth2/token"
        data: dict[str, Any] = {
            "client_id": config.myanimelist_client_id.strip(),
            "grant_type": "refresh_token",
            "refresh_token": config.myanimelist_refresh_token.strip(),
        }
        if config.myanimelist_client_secret.strip():
            data["client_secret"] = config.myanimelist_client_secret.strip()

        try:
            session = await self._http_client._get_session()
            async with session.post(
                url, data=data, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                resp.raise_for_status()
                token_data = await resp.json()

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
        config.myanimelist_access_token = ""
        config.myanimelist_refresh_token = ""
        config.myanimelist_token_expires_at = 0.0
        config.save_to_db()
        logger.info("Removed MyAnimeList connection credentials.")

    async def search_anime(self, query: str) -> list[dict[str, Any]]:
        if not self.is_configured():
            logger.warning("MAL is not configured; cannot search.")
            return []

        logger.debug(f"Searching MyAnimeList for: '{query}'")
        url = "https://api.myanimelist.net/v2/anime"
        params: dict[str, Any] = {
            "q": query,
            "limit": 50,
            "fields": (
                "id,title,main_picture,num_episodes,alternative_titles,"
                "start_date,end_date,synopsis,mean,media_type,status,genres"
            ),
        }

        try:
            headers = await self._get_auth_headers()
            response = await self._http_client.get(
                url, headers=headers, params=params, timeout=10
            )
            results = []
            for node in list(response.get("data", [])):
                anime = node.get("node", {})
                pic_dict = anime.get("main_picture") or {}
                alt_titles = anime.get("alternative_titles") or {}
                alt_list = alt_titles.get("synonyms") or []
                en_title = alt_titles.get("en") or ""
                genre_list = anime.get("genres") or []
                results.append(
                    {
                        "id": anime.get("id"),
                        "title": anime.get("title") or "",
                        "num_episodes": anime.get("num_episodes") or 0,
                        "poster_path": pic_dict.get("medium")
                        or pic_dict.get("large")
                        or "",
                        "start_date": anime.get("start_date") or "",
                        "end_date": anime.get("end_date") or "",
                        "synopsis": anime.get("synopsis") or "",
                        "score": anime.get("mean"),
                        "media_type": anime.get("media_type") or "",
                        "status": anime.get("status") or "",
                        "alternative_titles": alt_list,
                        "english_title": en_title,
                        "genres": [g.get("name", "") for g in genre_list],
                    }
                )
            return results
        except Exception:
            logger.exception(f"Failed to search MyAnimeList for '{query}'")
            return []

    async def get_anime_details(self, anime_id: int) -> Optional[dict[str, Any]]:
        if not self.is_configured():
            return None

        url = f"https://api.myanimelist.net/v2/anime/{anime_id}"
        params = {
            "fields": "id,title,main_picture,num_episodes,alternative_titles,start_date",
        }

        try:
            headers = await self._get_auth_headers()
            return await self._http_client.get(
                url, headers=headers, params=params, timeout=10
            )
        except Exception:
            logger.exception(f"Failed to fetch MAL details for ID: {anime_id}")
            return None

    async def update_watched_status(
        self, anime_id: int, num_watched_episodes: int, total_episodes: int = 0
    ) -> bool:
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
            session = await self._http_client._get_session()
            headers = await self._get_auth_headers()
            async with session.put(
                url, headers=headers, data=data, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        f"Failed to update MAL status for ID {anime_id} "
                        f"(HTTP {resp.status}): {error_text}"
                    )
                    return False
                logger.info(f"Successfully updated MAL status for ID {anime_id}.")
                return True
        except Exception:
            logger.exception(f"Failed to update MAL watched status for ID {anime_id}")
            return False

    async def close(self) -> None:
        await self._http_client.close()
