"""
Async OpenSubtitles client.

Mirror of the synchronous :class:`OpenSubtitlesClient` but fully async,
using :class:`AsyncHTTPClient` instead of ``requests.Session``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from lan_streamer.providers.http_client import AsyncHTTPClient
from lan_streamer.system.config import config

logger = logging.getLogger(__name__)

OPENSUBTITLES_API_BASE = "https://api.opensubtitles.com/api/v1/"


class AsyncOpenSubtitlesClient:
    """Async client for interacting with the OpenSubtitles.com REST API."""

    def __init__(self) -> None:
        self._http_client = AsyncHTTPClient(requests_per_second=10.0, timeout=15.0)
        self._token: Optional[str] = None

    def _get_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Api-Key": config.opensubtitles_api_key,
            "User-Agent": "LAN-Streamer/0.14.1",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def login(self) -> bool:
        if not config.opensubtitles_username or not config.opensubtitles_password:
            logger.warning("OpenSubtitles credentials missing, skipping login.")
            return False

        logger.info("Attempting login to OpenSubtitles.com...")
        url = f"{OPENSUBTITLES_API_BASE}login"
        payload = {
            "username": config.opensubtitles_username,
            "password": config.opensubtitles_password,
        }
        try:
            response = await self._http_client.post(
                url, json_data=payload, headers=self._get_headers(), timeout=15
            )
            token = response.get("token")
            if token:
                self._token = str(token)
                logger.info("Successfully logged in to OpenSubtitles.com")
                return True
            logger.error(f"OpenSubtitles login response missing token: {response}")
        except Exception:
            logger.exception("Error logging in to OpenSubtitles")
        return False

    async def search_subtitles(
        self,
        query: Optional[str] = None,
        tmdb_identifier: Optional[int] = None,
        season_number: Optional[int] = None,
        episode_number: Optional[int] = None,
        languages: str = "en",
    ) -> list[dict[str, Any]]:
        if not config.opensubtitles_api_key:
            logger.warning("OpenSubtitles API Key missing.")
            return []

        url = f"{OPENSUBTITLES_API_BASE}subtitles"
        params: dict[str, Any] = {"languages": languages}

        if tmdb_identifier:
            params["tmdb_id"] = tmdb_identifier
            if season_number is not None:
                params["season_number"] = season_number
            if episode_number is not None:
                params["episode_number"] = episode_number
        elif query:
            params["query"] = query

        logger.info(f"Searching OpenSubtitles with parameters: {params}")
        try:
            response = await self._http_client.get(
                url, params=params, headers=self._get_headers(), timeout=15
            )
            results = list(response.get("data", []))
            logger.info(f"OpenSubtitles search returned {len(results)} results.")
            return results
        except Exception:
            logger.exception("Error searching OpenSubtitles")
            return []

    async def get_download_link(self, file_id: int) -> Optional[str]:
        if not self._token:
            logged_in = await self.login()
            if not logged_in:
                logger.warning("OpenSubtitles token missing, cannot download.")
                return None

        logger.info(
            f"Requesting download link from OpenSubtitles for file ID '{file_id}'"
        )
        url = f"{OPENSUBTITLES_API_BASE}download"
        payload = {"file_id": file_id}
        try:
            response = await self._http_client.post(
                url, json_data=payload, headers=self._get_headers(), timeout=15
            )
            link = response.get("link")
            if link:
                logger.info(
                    f"OpenSubtitles download link resolved successfully: {link}"
                )
                return str(link)
            logger.error(f"OpenSubtitles download response missing link: {response}")
        except Exception:
            logger.exception("Error getting OpenSubtitles download link")
        return None

    async def download_subtitle(self, download_url: str) -> Optional[bytes]:
        logger.info(
            f"Downloading subtitle content from OpenSubtitles URL: '{download_url}'"
        )
        try:
            return await self._http_client.get_bytes(download_url, timeout=30)
        except Exception:
            logger.exception("Error downloading subtitle content")
            return None

    async def close(self) -> None:
        await self._http_client.close()
