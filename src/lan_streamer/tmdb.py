"""
tmdb.py — The Movie Database (TMDB) client for fetching TV series metadata.

Authentication: free API key from https://www.themoviedb.org/settings/api
No API key is required to run the app, but metadata fetching will silently
return None/empty if no key is set.
"""

import logging
import requests
from pathlib import Path
from .config import config

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
CACHE_DIR = Path.home() / ".config" / "lan-streamer" / "cache" / "images"


class TMDBClient:
    def __init__(self):
        self.session = requests.Session()
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

    def _params(self, extra: dict = None) -> dict:
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
        try:
            response = self.session.get(
                f"{TMDB_BASE_URL}/configuration",
                params={"api_key": api_key.strip()},
                timeout=10,
            )
            response.raise_for_status()
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
        try:
            resp = self.session.get(
                f"{TMDB_BASE_URL}/search/tv",
                params=self._params({"query": query, "page": 1}),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
        except Exception as e:
            logger.error(f"TMDB search failed for '{query}': {e}")
            return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
                top = results[0]
                if self._is_similar(name, top.get("name", "")):
                    logger.info(
                        f"Found TMDB match for '{name}': {top.get('name')} (ID: {top.get('id')})"
                    )
                    return top

        # Fallback: first two words
        words = cleaned_name.split()
        if len(words) > 2:
            shorter = " ".join(words[:2])
            results = self._do_search(shorter)
            if results:
                top = results[0]
                if self._is_similar(cleaned_name, top.get("name", "")):
                    logger.info(
                        f"Found TMDB match for '{name}' (two-word fallback): {top.get('name')}"
                    )
                    return top

        # Fallback: first word only (strict)
        if len(words) > 1 and len(words[0]) > 3:
            first = words[0]
            if first.lower() not in ["the", "marvel", "star", "a", "an"]:
                results = self._do_search(first)
                if results:
                    top = results[0]
                    if self._is_similar(
                        cleaned_name, top.get("name", ""), threshold=0.8
                    ):
                        logger.info(
                            f"Found TMDB match for '{name}' (first-word fallback): {top.get('name')}"
                        )
                        return top

        logger.warning(f"No TMDB series found for: '{name}'")
        return None

    def search_series_full(self, query: str, limit: int = 10) -> list:
        """Returns multiple results for the manual-match dialog."""
        if not self.is_configured():
            return []
        results = self._do_search(query)
        return results[:limit]

    def get_series_by_id(self, tmdb_id: str | int) -> dict | None:
        """Fetches full series details from TMDB."""
        try:
            resp = self.session.get(
                f"{TMDB_BASE_URL}/tv/{tmdb_id}",
                params=self._params(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"TMDB get_series_by_id({tmdb_id}) failed: {e}")
            return None

    def get_seasons(self, tmdb_id: str | int) -> list:
        """Returns season list for a series (from the series detail response)."""
        data = self.get_series_by_id(tmdb_id)
        if not data:
            return []
        seasons = data.get("seasons", [])
        # Filter out specials (season_number == 0) unless that's all there is
        official = [s for s in seasons if s.get("season_number", 0) > 0]
        return official if official else seasons

    def get_episodes(self, tmdb_id: str | int, season_num: int) -> list:
        """Returns episodes for a given season number."""
        try:
            resp = self.session.get(
                f"{TMDB_BASE_URL}/tv/{tmdb_id}/season/{season_num}",
                params=self._params(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("episodes", [])
        except Exception as e:
            logger.error(f"TMDB get_episodes({tmdb_id}, S{season_num}) failed: {e}")
            return []

    def download_image(self, poster_path: str, cache_key: str) -> str:
        """Downloads a poster image from the TMDB CDN and caches it locally.
        `poster_path` can be a bare TMDB path (/abc.jpg) or a full URL.
        Works without an API key (images are unauthenticated).
        """
        if not poster_path or not cache_key:
            return ""

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

        try:
            resp = self.session.get(image_url, timeout=15)
            if resp.status_code == 200:
                with open(image_path, "wb") as f:
                    f.write(resp.content)
                return str(image_path)
        except Exception as e:
            logger.error(f"Failed to download image from '{image_url}': {e}")
        return ""


tmdb_client = TMDBClient()
