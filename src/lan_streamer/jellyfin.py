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
        self._cache = None

    def preload_library(self):
        """Preloads all Series, Seasons, and Episodes into memory with pagination."""
        if not self.is_configured():
            return

        user_id = self.get_current_user_id()
        if not user_id:
            return

        self._cache = {"series": [], "seasons": {}, "episodes": {}}

        # 1. Fetch Series
        series_items = self._fetch_all_items_paginated("Series", fields="")
        self._cache["series"] = series_items

        # 2. Fetch Seasons
        season_items = self._fetch_all_items_paginated("Season", fields="")
        for season in season_items:
            series_id = season.get("SeriesId")
            if series_id:
                if series_id not in self._cache["seasons"]:
                    self._cache["seasons"][series_id] = []
                self._cache["seasons"][series_id].append(season)

        # 3. Fetch Episodes with UserData
        episode_items = self._fetch_all_items_paginated(
            "Episode", fields="Path,Overview"
        )
        for ep in episode_items:
            season_id = ep.get("SeasonId")
            if season_id:
                if season_id not in self._cache["episodes"]:
                    self._cache["episodes"][season_id] = []
                self._cache["episodes"][season_id].append(ep)

        logger.info(
            f"Preloaded library: {len(self._cache['series'])} series, {sum(len(s) for s in self._cache['seasons'].values())} seasons, {sum(len(e) for e in self._cache['episodes'].values())} episodes."
        )

    def clear_cache(self):
        """Frees the preloaded memory cache."""
        self._cache = None

    def _fetch_all_items_paginated(self, item_type: str, fields: str) -> list:
        user_id = self.get_current_user_id()
        url = f"{self._get_base_url()}/Users/{user_id}/Items"

        all_items = []
        limit = 5000
        start_index = 0

        while True:
            parameters = {
                "IncludeItemTypes": item_type,
                "Recursive": "true",
                "Fields": fields,
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
                all_items.extend(items)

                # If we received fewer items than requested, we've reached the end
                if len(items) < limit:
                    break

                start_index += limit
            except Exception as e:
                logger.error(
                    f"Failed paginated fetch for {item_type} at offset {start_index}: {e}"
                )
                break

        return all_items

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

    def _clean_name(self, name: str) -> str:
        """Cleans folder names by removing common release tags and technical specs."""
        import re

        # Replace dots and underscores with spaces (leave hyphens for now to match tags like web-dl)
        name = name.replace(".", " ").replace("_", " ")

        # Remove common year patterns (2024), [2024], or standalone years
        name = re.sub(r"[\(\{\[]\d{4}[\)\}\]]", "", name)
        name = re.sub(r"\b(19|20)\d{2}\b", "", name)

        # Remove resolution and quality tags (now handles hyphens/spaces)
        name = re.sub(
            r"(?i)\b(720p|1080p|2160p|4k|bluray|hdtv|web[- ]dl|x264|x265|hevc|aac|dts|dd5\.1|dual[- ]audio|multi|sub|dub)\b",
            "",
            name,
        )

        # Remove Season patterns (S01, Season 1, etc.)
        name = re.sub(r"(?i)\b(S\d+|Season\s*\d+)\b", "", name)

        # Now replace hyphens with spaces
        name = name.replace("-", " ")

        # Remove trailing/leading whitespace and normalize spaces
        name = re.sub(r"\s+", " ", name).strip()

        # Remove empty parentheses/brackets that might be left over
        name = re.sub(r"\(\s*\)", "", name)
        name = re.sub(r"\[\s*\]", "", name)
        name = re.sub(r"\{\s*\}", "", name)

        # Final trim
        name = re.sub(r"\s+", " ", name).strip()
        return name

    def _do_search(self, search_term: str):
        """Internal helper to perform the actual Jellyfin search request or cache lookup."""
        if self._cache is not None:
            search_term_lower = search_term.lower()
            # First, try an exact case-insensitive match on the clean name
            for item in self._cache["series"]:
                if item.get("Name", "").lower() == search_term_lower:
                    return item

            # Next, try a substring match since jellyfin's SearchTerm does substring matching
            for item in self._cache["series"]:
                if search_term_lower in item.get("Name", "").lower():
                    return item

            return None

        url = f"{self._get_base_url()}/Items"
        parameters = {
            "SearchTerm": search_term,
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
            logger.error(f"Search request failed for '{search_term}': {e}")
        return None

    def _is_similar(self, original: str, found: str, threshold: float = 0.7) -> bool:
        """Checks if the found name is sufficiently similar to the original."""
        from difflib import SequenceMatcher

        # Clean both for comparison
        a = self._clean_name(original).lower()
        b = self._clean_name(found).lower()

        if not a or not b:
            return False

        # Simple containment check is often enough for "looser" searches
        if a in b or b in a:
            return True

        # Fuzzy ratio check
        ratio = SequenceMatcher(None, a, b).ratio()
        if ratio >= threshold:
            return True

        # Word-based check: at least one significant word (length > 3) must match
        # and not be a common prefix
        a_words = [
            w
            for w in a.split()
            if len(w) > 3 and w not in ["marvel", "marvel's", "star", "the", "wars"]
        ]
        b_words = b.split()
        for w in a_words:
            if w in b_words:
                return True

        return False

    def search_series(self, name: str):
        if not self.is_configured():
            return None

        # Minimal cleaning for the "exact" search (dots/underscores to spaces)
        exact_name = name.replace(".", " ").replace("_", " ").strip()

        # Try replacing hyphens with colons (often used for subtitles in Jellyfin)
        colon_name = exact_name.replace(" - ", ": ").replace("-", ":")

        cleaned_name = self._clean_name(name)

        logger.debug(
            f"Searching Jellyfin for series. Strategies: Exact='{exact_name}', Colon='{colon_name}', Fuzzy='{cleaned_name}'"
        )

        # Strategy 1: Exact (minimal cleaning)
        result = self._do_search(exact_name)
        if result:
            logger.info(
                f"Found exact Jellyfin match for '{name}': {result.get('Name')} (ID: {result.get('Id')})"
            )
            return result

        # Strategy 2: Colon-replacement
        if colon_name != exact_name:
            result = self._do_search(colon_name)
            if result:
                logger.info(
                    f"Found colon-replaced Jellyfin match for '{name}': {result.get('Name')} (ID: {result.get('Id')})"
                )
                return result

        # Strategy 3: Full cleaned name
        if cleaned_name != exact_name:
            result = self._do_search(cleaned_name)
            if result:
                # Still verify fuzzy match
                if self._is_similar(cleaned_name, result.get("Name", "")):
                    logger.info(
                        f"Found fuzzy Jellyfin match for '{name}': {result.get('Name')} (ID: {result.get('Id')})"
                    )
                    return result

        # Strategy 3: Try first two words
        words = cleaned_name.split()
        if len(words) > 2:
            shorter_name = " ".join(words[:2])
            logger.info(f"Fallback search: Trying first two words '{shorter_name}'")
            result = self._do_search(shorter_name)
            if result and self._is_similar(cleaned_name, result.get("Name", "")):
                logger.info(
                    f"Found Jellyfin match for '{name}' via fallback: {result.get('Name')} (ID: {result.get('Id')})"
                )
                return result

        # Strategy 4: Try first word (more strict similarity check)
        if len(words) > 1 and len(words[0]) > 3:
            first_word = words[0]
            # Skip common prefixes that lead to bad matches
            if first_word.lower() not in [
                "the",
                "marvel",
                "marvel's",
                "star",
                "a",
                "an",
            ]:
                logger.info(f"Fallback search: Trying first word '{first_word}'")
                result = self._do_search(first_word)
                if result and self._is_similar(
                    cleaned_name, result.get("Name", ""), threshold=0.8
                ):
                    logger.info(
                        f"Found Jellyfin match for '{name}' via first-word fallback: {result.get('Name')} (ID: {result.get('Id')})"
                    )
                    return result

        logger.warning(
            f"No Jellyfin series found matching: '{exact_name}' or its variants."
        )
        return None

    def search_series_full(self, name: str, limit: int = 10):
        """Returns multiple results for manual matching."""
        if not self.is_configured():
            return []

        cleaned_name = self._clean_name(name)
        url = f"{self._get_base_url()}/Items"
        parameters = {
            "SearchTerm": cleaned_name,
            "IncludeItemTypes": "Series",
            "Limit": limit,
            "Recursive": "true",
            "Fields": "PrimaryImageAspectRatio,CanDelete,CanDownload,CustomRating,DateCreated,DateLastMediaAdded,DisplayPreferencesId,ExternalUrls,Genres,HomePageUrl,ItemCounts,MediaSourceCount,MediaSources,OriginalTitle,Overview,ParentId,Path,People,PlayAccess,ProductionYear,RemoteTrailers,ScreenshotImageCount,SortName,Status,Taglines,Tags,UserData,VoteCount,CumulativeRunTimeTicks,Metascore,AirDays,IsPosterViewer,ListOrder,LookupInfo,OfficialRating,Resolution,SeriesId,SeriesName,SeriesTimerId,Tagline",
        }
        try:
            response = self.session.get(
                url, headers=self._get_headers(), params=parameters, timeout=5
            )
            response.raise_for_status()
            return response.json().get("Items", [])
        except Exception as e:
            logger.error(f"Full search failed for '{name}': {e}")
        return []

    def get_seasons(self, series_id: str):
        if not self.is_configured():
            return []

        if self._cache is not None:
            return self._cache["seasons"].get(series_id, [])

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

        if self._cache is not None:
            return self._cache["episodes"].get(season_id, [])

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
            response = self.session.get(url, headers=self._get_headers(), timeout=5)
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
