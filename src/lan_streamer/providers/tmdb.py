"""
tmdb.py — The Movie Database (TMDB) client for fetching TV series metadata.

Authentication: free API key from https://www.themoviedb.org/settings/api
No API key is required to run the app, but metadata fetching will silently
return None/empty if no key is set.
"""

import logging
import requests
from pathlib import Path
from lan_streamer.system.config import config

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
CACHE_DIR = Path.home() / ".config" / "lan-streamer" / "cache" / "images"


class TMDBClient:
    """Client for interacting with The Movie Database (TMDB) API to fetch movie and TV metadata."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        if session is None:
            self.session.headers.update(
                {
                    "User-Agent": "LanStreamer/1.0",
                    "Accept": "application/json",
                }
            )

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(config.tmdb_api_key)

    def _params(self, extra: dict | None = None) -> dict:
        """Returns base query params (api_key) merged with any extras."""
        parameters = {}
        if config.tmdb_api_key:
            parameters["api_key"] = config.tmdb_api_key.strip()
        if extra:
            parameters.update(extra)
        return parameters

    # ------------------------------------------------------------------
    # Credential validation
    # ------------------------------------------------------------------

    def validate_credentials(self, api_key: str) -> tuple[bool, str]:
        """Tests the given API key without persisting it."""
        if not api_key:
            return False, "API Key is required."
        logger.info("Validating TMDB API Key configuration...")
        try:
            response = self.session.get(
                f"{TMDB_BASE_URL}/configuration",
                params={"api_key": api_key.strip()},
                timeout=10,
            )
            response.raise_for_status()
            logger.info("TMDB API Key validation succeeded.")
            return True, "Connection successful!"
        except requests.exceptions.HTTPError as exception:
            if exception.response is not None and exception.response.status_code == 401:
                return False, "Invalid API Key (Unauthorized)."
            return False, f"HTTP Error: {exception}"
        except Exception as exception:
            return False, f"Connection failed: {exception}"

    # ------------------------------------------------------------------
    # Search helpers
    # ------------------------------------------------------------------

    def _clean_name(self, name: str) -> str:
        """Strips common release tags from folder names before searching."""
        import re

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

    def _is_similar(self, original: str, found: str, threshold: float = 0.7) -> bool:
        from difflib import SequenceMatcher

        a = self._clean_name(original).lower()
        b = self._clean_name(found).lower()
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

    def _do_search(self, query: str) -> list:
        """Raw TMDB TV search. Returns list of result dicts."""
        logger.debug(f"Executing raw TMDB TV search for query: '{query}'")
        try:
            resp = self.session.get(
                f"{TMDB_BASE_URL}/search/tv",
                params=self._params({"query": query, "page": 1}),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
        except Exception:
            logger.exception(f"TMDB search failed for '{query}'")
            return []

    def _do_movie_search(self, query: str, year: int | None = None) -> list:
        """Raw TMDB movie search. Returns list of result dicts."""
        logger.debug(
            f"Executing raw TMDB Movie search for query: '{query}' (Year={year})"
        )
        try:
            params = self._params({"query": query, "page": 1})
            if year:
                params["year"] = year
            resp = self.session.get(
                f"{TMDB_BASE_URL}/search/movie",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
        except Exception:
            logger.exception(f"TMDB movie search failed for '{query}'")
            return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _select_best_candidate(
        self, results_list: list, target_title: str, custom_threshold: float = 0.7
    ) -> dict | None:
        from difflib import SequenceMatcher

        target_clean = self._clean_name(target_title).lower()
        if not target_clean:
            return None

        scored_candidates = []
        for candidate_item in results_list:
            candidate_name = candidate_item.get("name") or candidate_item.get(
                "title", ""
            )
            candidate_clean = self._clean_name(candidate_name).lower()
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
                is_similar_result = self._is_similar(
                    target_title,
                    best_name,
                    threshold=custom_threshold,
                )
            else:
                is_similar_result = self._is_similar(target_title, best_name)
            if best_ratio >= custom_threshold or is_similar_result:
                return best_candidate

        return None

    def search_series(self, name: str) -> dict | None:
        """Searches TMDB for the best-matching TV series.
        Works without an API key — returns None gracefully if auth fails.
        """
        exact_name = name.replace(".", " ").replace("_", " ").strip()
        colon_name = exact_name.replace(" - ", ": ").replace("-", ":")
        cleaned_name = self._clean_name(name)

        logger.debug(
            f"Searching TMDB for: Exact='{exact_name}', Colon='{colon_name}', Cleaned='{cleaned_name}'"
        )

        for search_term in dict.fromkeys([exact_name, colon_name, cleaned_name]):
            results = self._do_search(search_term)
            if results:
                best_match = self._select_best_candidate(
                    results, name, custom_threshold=0.7
                )
                if best_match:
                    logger.info(
                        f"Found TMDB match for '{name}': {best_match.get('name')} (ID: {best_match.get('id')})"
                    )
                    return best_match

        # Fallback: first two words
        words = cleaned_name.split()
        if len(words) > 2:
            shorter = " ".join(words[:2])
            results = self._do_search(shorter)
            if results:
                best_match = self._select_best_candidate(
                    results, cleaned_name, custom_threshold=0.7
                )
                if best_match:
                    logger.info(
                        f"Found TMDB match for '{name}' (two-word fallback): {best_match.get('name')}"
                    )
                    return best_match

        # Fallback: first word only (strict)
        if len(words) > 1 and len(words[0]) > 3:
            first = words[0]
            if first.lower() not in ["the", "marvel", "star", "a", "an"]:
                results = self._do_search(first)
                if results:
                    best_match = self._select_best_candidate(
                        results, cleaned_name, custom_threshold=0.8
                    )
                    if best_match:
                        logger.info(
                            f"Found TMDB match for '{name}' (first-word fallback): {best_match.get('name')}"
                        )
                        return best_match

        logger.warning(f"No TMDB series found for: '{name}'")
        return None

    def search_series_full(self, query: str, limit: int = 10) -> list:
        """Returns multiple results for the manual-match dialog."""
        if not self.is_configured():
            return []
        results = self._do_search(query)
        return results[:limit]

    def search_movie(self, name: str, year: int | None = None) -> dict | None:
        """Searches TMDB for the best-matching movie."""
        exact_name = name.replace(".", " ").replace("_", " ").strip()
        cleaned_name = self._clean_name(name)

        logger.debug(
            f"Searching TMDB for Movie: Exact='{exact_name}', Cleaned='{cleaned_name}', Year={year}"
        )

        for search_term in dict.fromkeys([exact_name, cleaned_name]):
            results = self._do_movie_search(search_term, year)
            if results:
                best_match = self._select_best_candidate(
                    results, name, custom_threshold=0.7
                )
                if best_match:
                    logger.info(
                        f"Found TMDB movie match for '{name}': {best_match.get('title')} (ID: {best_match.get('id')})"
                    )
                    return best_match

        logger.warning(f"No TMDB movie found for: '{name}'")
        return None

    def search_movie_full(self, query: str, limit: int = 10) -> list:
        """Returns multiple movie results for the manual-match dialog."""
        if not self.is_configured():
            return []
        results = self._do_movie_search(query)
        return results[:limit]

    def get_series_by_id(self, tmdb_identifier: str | int) -> dict | None:
        """Fetches full series details from TMDB."""
        logger.info(f"Requesting TMDB series details for ID '{tmdb_identifier}'")
        try:
            resp = self.session.get(
                f"{TMDB_BASE_URL}/tv/{tmdb_identifier}",
                params=self._params(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.exception(f"TMDB get_series_by_id({tmdb_identifier}) failed")
            return None

    def get_movie_by_id(self, tmdb_identifier: str | int) -> dict | None:
        """Fetches full movie details from TMDB."""
        logger.info(f"Requesting TMDB movie details for ID '{tmdb_identifier}'")
        try:
            resp = self.session.get(
                f"{TMDB_BASE_URL}/movie/{tmdb_identifier}",
                params=self._params(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.exception(f"TMDB get_movie_by_id({tmdb_identifier}) failed")
            return None

    def get_seasons(self, tmdb_identifier: str | int) -> list:
        """Returns season list for a series (from the series detail response)."""
        data = self.get_series_by_id(tmdb_identifier)
        if not data:
            return []
        return data.get("seasons", [])

    def get_episodes(self, tmdb_identifier: str | int, season_num: int) -> list:
        """Returns episodes for a given season number."""
        logger.info(
            f"Requesting TMDB episodes list for series ID '{tmdb_identifier}', Season {season_num}"
        )
        try:
            resp = self.session.get(
                f"{TMDB_BASE_URL}/tv/{tmdb_identifier}/season/{season_num}",
                params=self._params(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("episodes", [])
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 404:
                logger.warning(
                    f"TMDB get_episodes({tmdb_identifier}, S{season_num}) failed: "
                    f"season {season_num} not found on TMDB (404). "
                    "This season may not yet exist in the TMDB database."
                )
            else:
                logger.exception(
                    f"TMDB get_episodes({tmdb_identifier}, S{season_num}) failed "
                    f"with HTTP {status_code}"
                )
            return []
        except Exception:
            logger.exception(
                f"TMDB get_episodes({tmdb_identifier}, S{season_num}) failed"
            )
            return []

    def get_episode_groups(self, tmdb_identifier: str | int) -> list:
        """Fetches TV episode groups for a series."""
        logger.info(f"Requesting TMDB episode groups for series ID '{tmdb_identifier}'")
        try:
            resp = self.session.get(
                f"{TMDB_BASE_URL}/tv/{tmdb_identifier}/episode_groups",
                params=self._params(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
        except Exception:
            logger.exception(f"TMDB get_episode_groups({tmdb_identifier}) failed")
            return []

    def get_episode_group_details(self, group_id: str) -> dict | None:
        """Fetches details for a specific episode group."""
        logger.info(f"Requesting TMDB episode group details for group ID '{group_id}'")
        try:
            resp = self.session.get(
                f"{TMDB_BASE_URL}/tv/episode_group/{group_id}",
                params=self._params(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.exception(f"TMDB get_episode_group_details({group_id}) failed")
            return None

    def get_season_based_episode_group(self, tmdb_identifier: str | int) -> dict | None:
        """Resolves the best season-based episode group for a series."""
        groups = self.get_episode_groups(tmdb_identifier)
        if not groups:
            return None

        # Prioritize:
        # 1. Name contains "season" or "tvdb" (case-insensitive)
        # 2. Type 7 (TV Order/TVDB seasons)
        # 3. Type 3 (DVD) or Type 4 (Digital)
        selected_group = None
        for g in groups:
            name_lower = (g.get("name") or "").lower()
            if "season" in name_lower or "tvdb" in name_lower:
                selected_group = g
                break
        if not selected_group:
            for g in groups:
                if g.get("type") == 7:
                    selected_group = g
                    break
        if not selected_group:
            for g in groups:
                if g.get("type") in (3, 4):
                    selected_group = g
                    break

        if selected_group:
            return self.get_episode_group_details(selected_group["id"])
        return None

    def get_cached_image(self, cache_key: str) -> str:
        """Checks the /cache/images directory first to see if a poster already exists for the given cache_key."""
        if not cache_key:
            return ""
        if CACHE_DIR.exists():
            for file_path in CACHE_DIR.glob(f"{cache_key}.*"):
                if file_path.is_file():
                    logger.debug(
                        f"Found existing cached poster for {cache_key}: {file_path}"
                    )
                    return str(file_path)
        return ""

    def download_image(self, poster_path: str, cache_key: str) -> str:
        """Downloads a poster image from the TMDB CDN and caches it locally.
        `poster_path` can be a bare TMDB path (/abc.jpg) or a full URL.
        Works without an API key (images are unauthenticated).
        """
        if not poster_path or not cache_key:
            return ""

        # If poster_path is already a local absolute file path (contains multiple slashes)
        # Bare TMDB path fragments have exactly one leading slash (e.g., /abc.jpg).
        if poster_path.startswith("/") and "/" in poster_path[1:]:
            logger.debug(
                f"download_image: Preserving existing absolute local poster path: {poster_path}"
            )
            return poster_path

        # Look in the /cache/images directory first to see if we already have the poster
        cached_existing = self.get_cached_image(cache_key)
        if cached_existing and isinstance(cached_existing, str):
            logger.debug(
                f"download_image: Found existing cached image for {cache_key}, skipping internet download."
            )
            return cached_existing

        # Build full URL if given a bare path
        if poster_path.startswith("/"):
            image_url = f"{TMDB_IMAGE_BASE}{poster_path}"
        else:
            image_url = poster_path

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(image_url.split("?")[0]).suffix or ".jpg"
        image_path = CACHE_DIR / f"{cache_key}{suffix}"

        if image_path.exists():
            return str(image_path)

        logger.info(f"Downloading poster image from: '{image_url}'")
        try:
            resp = self.session.get(image_url, timeout=15)
            if resp.status_code == 200:
                with open(image_path, "wb") as f:
                    f.write(resp.content)
                logger.info(f"Saved poster image locally to '{image_path}'")
                return str(image_path)
        except Exception:
            logger.exception(f"Failed to download image from '{image_url}'")
        return ""


tmdb_client = TMDBClient()
