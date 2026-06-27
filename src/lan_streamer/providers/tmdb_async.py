"""
tmdb_async.py — Async TMDB client for fetching TV series and movie metadata.

Mirrors the synchronous :class:`TMDBClient` interface but all network I/O is
async via :class:`AsyncHTTPClient`.  Pure-text helpers (:meth:`_clean_name`,
:meth:`_is_similar`, :meth:`_select_best_candidate`) remain synchronous since
they perform no I/O.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from difflib import SequenceMatcher
from typing import Any, Optional

from lan_streamer.providers.http_client import AsyncHTTPClient
from lan_streamer.system.config import config

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
CACHE_DIR = Path.home() / ".config" / "lan-streamer" / "cache" / "images"


class AsyncTMDBClient:
    """Async TMDB client with the same public API as :class:`TMDBClient`.

    All network calls use ``AsyncHTTPClient`` with built-in rate limiting and
    retry.  File-based image caching remains synchronous and is offloaded to
    the default executor.
    """

    def __init__(
        self,
        http_client: Optional[AsyncHTTPClient] = None,
        api_key: Optional[str] = None,
        cache_dir: Optional[str | Path] = None,
    ) -> None:
        self._http_client = http_client or AsyncHTTPClient(
            requests_per_second=10.0,
        )
        self._api_key = api_key
        self._cache_dir = Path(cache_dir) if cache_dir else None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def _effective_api_key(self) -> str:
        return self._api_key if self._api_key is not None else config.tmdb_api_key

    @property
    def _effective_cache_dir(self) -> Path:
        return self._cache_dir if self._cache_dir is not None else CACHE_DIR

    def is_configured(self) -> bool:
        return bool(self._effective_api_key)

    async def close(self) -> None:
        await self._http_client.close()

    def _params(self, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        parameters: dict[str, Any] = {}
        api_key = self._effective_api_key
        if api_key:
            parameters["api_key"] = api_key.strip()
        if extra:
            parameters.update(extra)
        return parameters

    async def _make_get(
        self, url: str, extra_params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Thin helper: GET with auth params, return parsed JSON."""
        params = self._params(extra_params)
        return await self._http_client.get(url, params=params)

    async def _make_get_list(
        self, url: str, extra_params: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """GET returning JSON and extracting the 'results' key as a list."""
        data = await self._make_get(url, extra_params=extra_params)
        return list(data.get("results", []))

    # ------------------------------------------------------------------
    # Search helpers (pure text — no I/O)
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_name(name: str) -> str:
        """Strip common release tags and formatting from folder names."""
        name = name.replace(".", " ").replace("_", " ")
        name = re.sub(r"[\(\{\[]\d{4}[\)\}\]]", "", name)
        name = re.sub(r"\b(19|20)\d{2}\b", "", name)
        name = re.sub(
            r"(?i)\b(720p|1080p|2160p|4k|bluray|hdtv|web[- ]dl|x264|x265|hevc|aac|dts|dd5\.1|dual[- ]audio|multi|sub|dub)\b",
            "",
            name,
        )
        name = re.sub(r"(?i)\b(S\d+|Season\s*\d+)\b", "", name)
        name = name.replace("-", " ")
        name = re.sub(r"\s+", " ", name).strip()
        return name

    @staticmethod
    def _is_similar(original: str, found: str, threshold: float = 0.7) -> bool:
        """Check if two names are similar using sequence matching."""
        a = AsyncTMDBClient._clean_name(original).lower()
        b = AsyncTMDBClient._clean_name(found).lower()
        if not a or not b:
            return False
        if a in b or b in a:
            return True
        ratio = SequenceMatcher(None, a, b).ratio()
        if ratio >= threshold:
            return True
        a_words = [
            w
            for w in a.split()
            if len(w) > 3 and w not in ["marvel", "star", "the", "wars"]
        ]
        b_words = b.split()
        for w in a_words:
            if w in b_words:
                return True
        return False

    @staticmethod
    def _select_best_candidate(
        results_list: list[dict[str, Any]],
        target_title: str,
        custom_threshold: float = 0.7,
    ) -> Optional[dict[str, Any]]:
        """Pick the best-matching result from a list of TMDB results."""
        target_clean = AsyncTMDBClient._clean_name(target_title).lower()
        if not target_clean:
            return None

        scored_candidates: list[tuple[float, dict[str, Any]]] = []
        for candidate_item in results_list:
            candidate_name = candidate_item.get("name") or candidate_item.get(
                "title", ""
            )
            candidate_clean = AsyncTMDBClient._clean_name(candidate_name).lower()
            if not candidate_clean:
                continue

            if candidate_clean == target_clean:
                return candidate_item

            similarity_ratio = SequenceMatcher(
                None, target_clean, candidate_clean
            ).ratio()
            scored_candidates.append((similarity_ratio, candidate_item))

        if scored_candidates:
            scored_candidates.sort(key=lambda item: item[0], reverse=True)
            best_ratio, best_candidate = scored_candidates[0]
            best_name = best_candidate.get("name") or best_candidate.get("title", "")
            if custom_threshold != 0.7:
                is_similar_result = AsyncTMDBClient._is_similar(
                    target_title, best_name, threshold=custom_threshold
                )
            else:
                is_similar_result = AsyncTMDBClient._is_similar(target_title, best_name)
            if best_ratio >= custom_threshold or is_similar_result:
                return best_candidate

        return None

    async def _do_search(self, query: str) -> list[dict[str, Any]]:
        """Raw TMDB TV search."""
        logger.debug("Executing async TMDB TV search for query: '%s'", query)
        try:
            return await self._make_get_list(
                f"{TMDB_BASE_URL}/search/tv",
                extra_params={"query": query, "page": 1},
            )
        except Exception:
            logger.exception("Async TMDB TV search failed for '%s'", query)
            return []

    async def _do_movie_search(
        self, query: str, year: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Raw TMDB movie search."""
        logger.debug("Executing async TMDB Movie search for query: '%s'", query)
        try:
            extra: dict[str, Any] = {"query": query, "page": 1}
            if year:
                extra["year"] = year
            return await self._make_get_list(
                f"{TMDB_BASE_URL}/search/movie",
                extra_params=extra,
            )
        except Exception:
            logger.exception("Async TMDB movie search failed for '%s'", query)
            return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_series(self, name: str) -> Optional[dict[str, Any]]:
        """Search TMDB for the best-matching TV series."""
        exact_name = name.replace(".", " ").replace("_", " ").strip()
        colon_name = exact_name.replace(" - ", ": ").replace("-", ":")
        cleaned_name = self._clean_name(name)

        logger.debug(
            "Searching TMDB (async) for: Exact='%s', Colon='%s', Cleaned='%s'",
            exact_name,
            colon_name,
            cleaned_name,
        )

        for search_term in dict.fromkeys([exact_name, colon_name, cleaned_name]):
            results = await self._do_search(search_term)
            if results:
                best_match = self._select_best_candidate(
                    results, name, custom_threshold=0.7
                )
                if best_match:
                    logger.info(
                        "Found TMDB (async) match for '%s': %s (ID: %s)",
                        name,
                        best_match.get("name"),
                        best_match.get("id"),
                    )
                    return best_match

        # Fallback: first two words
        words = cleaned_name.split()
        if len(words) > 2:
            shorter = " ".join(words[:2])
            results = await self._do_search(shorter)
            if results:
                best_match = self._select_best_candidate(
                    results, cleaned_name, custom_threshold=0.7
                )
                if best_match:
                    logger.info(
                        "Found TMDB (async) match for '%s' (two-word fallback): %s",
                        name,
                        best_match.get("name"),
                    )
                    return best_match

        # Fallback: first word only (strict)
        if len(words) > 1 and len(words[0]) > 3:
            first = words[0]
            if first.lower() not in ["the", "marvel", "star", "a", "an"]:
                results = await self._do_search(first)
                if results:
                    best_match = self._select_best_candidate(
                        results, cleaned_name, custom_threshold=0.8
                    )
                    if best_match:
                        logger.info(
                            "Found TMDB (async) match for '%s' (first-word fallback): %s",
                            name,
                            best_match.get("name"),
                        )
                        return best_match

        logger.warning("No TMDB (async) series found for: '%s'", name)
        return None

    async def search_series_full(
        self, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return multiple results for the manual-match dialog."""
        if not self.is_configured():
            return []
        results = await self._do_search(query)
        return results[:limit]

    async def search_movie(
        self, name: str, year: Optional[int] = None
    ) -> Optional[dict[str, Any]]:
        """Search TMDB for the best-matching movie."""
        exact_name = name.replace(".", " ").replace("_", " ").strip()
        cleaned_name = self._clean_name(name)

        logger.debug(
            "Searching TMDB (async) for Movie: Exact='%s', Cleaned='%s', Year=%s",
            exact_name,
            cleaned_name,
            year,
        )

        for search_term in dict.fromkeys([exact_name, cleaned_name]):
            results = await self._do_movie_search(search_term, year)
            if results:
                best_match = self._select_best_candidate(
                    results, name, custom_threshold=0.7
                )
                if best_match:
                    logger.info(
                        "Found TMDB (async) movie match for '%s': %s (ID: %s)",
                        name,
                        best_match.get("title"),
                        best_match.get("id"),
                    )
                    return best_match

        logger.warning("No TMDB (async) movie found for: '%s'", name)
        return None

    async def search_movie_full(
        self, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return multiple movie results for the manual-match dialog."""
        if not self.is_configured():
            return []
        results = await self._do_movie_search(query)
        return results[:limit]

    async def get_series_by_id(
        self, tmdb_identifier: str | int
    ) -> Optional[dict[str, Any]]:
        """Fetch full series details from TMDB."""
        logger.info(
            "Requesting TMDB (async) series details for ID '%s'", tmdb_identifier
        )
        try:
            return await self._make_get(f"{TMDB_BASE_URL}/tv/{tmdb_identifier}")
        except Exception:
            logger.exception("Async TMDB get_series_by_id(%s) failed", tmdb_identifier)
            return None

    async def get_movie_by_id(
        self, tmdb_identifier: str | int
    ) -> Optional[dict[str, Any]]:
        """Fetch full movie details from TMDB."""
        logger.info(
            "Requesting TMDB (async) movie details for ID '%s'", tmdb_identifier
        )
        try:
            return await self._make_get(f"{TMDB_BASE_URL}/movie/{tmdb_identifier}")
        except Exception:
            logger.exception("Async TMDB get_movie_by_id(%s) failed", tmdb_identifier)
            return None

    async def get_seasons(self, tmdb_identifier: str | int) -> list[dict[str, Any]]:
        """Return season list for a series (from the series detail response)."""
        data = await self.get_series_by_id(tmdb_identifier)
        if not data:
            return []
        return list(data.get("seasons", []))

    async def get_episodes(
        self, tmdb_identifier: str | int, season_num: int
    ) -> list[dict[str, Any]]:
        """Return episodes for a given season number."""
        logger.info(
            "Requesting TMDB (async) episodes for ID '%s', Season %s",
            tmdb_identifier,
            season_num,
        )
        try:
            from aiohttp import ClientResponseError

            data = await self._make_get(
                f"{TMDB_BASE_URL}/tv/{tmdb_identifier}/season/{season_num}"
            )
            return list(data.get("episodes", []))
        except ClientResponseError as exc:
            if exc.status == 404:
                logger.warning(
                    "Async TMDB get_episodes(%s, S%s) failed: season not found (404).",
                    tmdb_identifier,
                    season_num,
                )
            else:
                logger.exception(
                    "Async TMDB get_episodes(%s, S%s) failed with HTTP %s",
                    tmdb_identifier,
                    season_num,
                    exc.status,
                )
            return []
        except Exception:
            logger.exception(
                "Async TMDB get_episodes(%s, S%s) failed",
                tmdb_identifier,
                season_num,
            )
            return []

    async def get_episode_groups(
        self, tmdb_identifier: str | int
    ) -> list[dict[str, Any]]:
        """Fetch TV episode groups for a series."""
        logger.info(
            "Requesting TMDB (async) episode groups for series ID '%s'",
            tmdb_identifier,
        )
        try:
            return await self._make_get_list(
                f"{TMDB_BASE_URL}/tv/{tmdb_identifier}/episode_groups"
            )
        except Exception:
            logger.exception(
                "Async TMDB get_episode_groups(%s) failed", tmdb_identifier
            )
            return []

    async def get_episode_group_details(
        self, group_id: str
    ) -> Optional[dict[str, Any]]:
        """Fetch details for a specific episode group."""
        logger.info(
            "Requesting TMDB (async) episode group details for group ID '%s'",
            group_id,
        )
        try:
            return await self._make_get(f"{TMDB_BASE_URL}/tv/episode_group/{group_id}")
        except Exception:
            logger.exception(
                "Async TMDB get_episode_group_details(%s) failed", group_id
            )
            return None

    async def get_season_based_episode_group(
        self, tmdb_identifier: str | int
    ) -> Optional[dict[str, Any]]:
        """Resolve the best season-based episode group for a series."""
        groups = await self.get_episode_groups(tmdb_identifier)
        if not groups:
            return None

        selected_group = None
        for group in groups:
            name_lower = (group.get("name") or "").lower()
            if "season" in name_lower or "tvdb" in name_lower:
                selected_group = group
                break
        if not selected_group:
            for group in groups:
                if group.get("type") == 7:
                    selected_group = group
                    break
        if not selected_group:
            for group in groups:
                if group.get("type") in (3, 4):
                    selected_group = group
                    break

        if selected_group:
            return await self.get_episode_group_details(selected_group["id"])
        return None

    # ------------------------------------------------------------------
    # Image caching (sync file I/O)
    # ------------------------------------------------------------------

    def get_cached_image(self, cache_key: str) -> str:
        """Check the local image cache for an existing poster."""
        if not cache_key:
            return ""
        cache_dir = self._effective_cache_dir
        if cache_dir.exists():
            for file_path in cache_dir.glob(f"{cache_key}.*"):
                if file_path.is_file():
                    logger.debug(
                        "Found existing cached poster for %s: %s",
                        cache_key,
                        file_path,
                    )
                    return str(file_path)
        return ""

    async def download_image(self, poster_path: str, cache_key: str) -> str:
        """Download a poster image from the TMDB CDN and cache it locally."""
        if not poster_path or not cache_key:
            return ""

        if poster_path.startswith("/") and "/" in poster_path[1:]:
            logger.debug(
                "download_image: Preserving existing absolute local poster path: %s",
                poster_path,
            )
            return poster_path

        cached_existing = self.get_cached_image(cache_key)
        if cached_existing and isinstance(cached_existing, str):
            logger.debug(
                "download_image: Found existing cached image for %s, skipping download.",
                cache_key,
            )
            return cached_existing

        if poster_path.startswith("/"):
            image_url = f"{TMDB_IMAGE_BASE}{poster_path}"
        else:
            image_url = poster_path

        cache_dir = self._effective_cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(image_url.split("?")[0]).suffix or ".jpg"
        image_path = cache_dir / f"{cache_key}{suffix}"

        if image_path.exists():
            return str(image_path)

        logger.info("Downloading poster image from: '%s'", image_url)
        try:
            data = await self._http_client.get_bytes(image_url, timeout=15.0)
            import asyncio as _asyncio

            def _write_bytes() -> None:
                with open(image_path, "wb") as f:
                    f.write(data)

            await _asyncio.to_thread(_write_bytes)
            logger.info("Saved poster image locally to '%s'", image_path)
            return str(image_path)
        except Exception:
            logger.exception("Failed to download image from '%s'", image_url)
            return ""
