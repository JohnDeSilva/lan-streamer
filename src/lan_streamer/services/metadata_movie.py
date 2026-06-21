"""Movie-specific metadata resolution helpers.

Provides functions for building movie metadata defaults, applying existing
data, resolving Jellyfin IDs, downloading posters, and merging TMDB results
into the movie metadata dictionary.
"""

import logging
from pathlib import Path
from typing import Any, Dict

from lan_streamer.providers.tmdb import tmdb_client

logger = logging.getLogger("lan_streamer.services.metadata_movie")


def _build_movie_metadata_defaults() -> Dict[str, Any]:
    """Returns a blank movie metadata dictionary with all expected keys.

    Returns:
        A dictionary with keys ``tmdb_identifier``, ``overview``,
        ``poster_path``, ``tmdb_name``, ``jellyfin_id``, ``runtime``,
        ``rating``, ``genre``, and ``year``.
    """
    return {
        "tmdb_identifier": "",
        "overview": "",
        "poster_path": "",
        "tmdb_name": "",
        "jellyfin_id": "",
        "runtime": 0,
        "rating": "",
        "genre": "",
        "year": 0,
    }


def _apply_existing_movie_metadata(
    metadata: Dict[str, Any],
    existing: Dict[str, Any],
    manual_jellyfin_id: str | None,
) -> None:
    """Copies non-empty scalar fields from *existing* movie data into *metadata*,
    then overrides the Jellyfin ID when a manual one is supplied.

    Args:
        metadata: The target metadata dictionary (mutated in-place).
        existing: The source existing movie data.
        manual_jellyfin_id: Optional manual Jellyfin ID override.
    """
    for key, value in existing.items():
        if value and key in metadata:
            metadata[key] = value
    if manual_jellyfin_id:
        metadata["jellyfin_id"] = manual_jellyfin_id


def _resolve_movie_jellyfin_id(
    movie_metadata: Dict[str, Any],
    video_path: str,
    jellyfin_data: Dict[str, Any] | None,
) -> str:
    """Three-step Jellyfin ID resolution for a movie.

    1. Direct path match via path_map.
    2. TMDB ID match via tmdb_episode_map.
    Falls back to the existing value on the metadata dictionary.

    Args:
        movie_metadata: Movie metadata dict with a potential existing
            ``jellyfin_id``.
        video_path: Absolute path to the movie file.
        jellyfin_data: Jellyfin sync data or ``None``.

    Returns:
        The resolved Jellyfin ID string (may be empty).
    """
    if not jellyfin_data:
        return movie_metadata.get("jellyfin_id", "")

    if not movie_metadata.get("jellyfin_id"):
        path_map = jellyfin_data.get("path_map", {})
        if video_path in path_map:
            return path_map[video_path]["id"]

    if not movie_metadata.get("jellyfin_id") and movie_metadata.get("tmdb_identifier"):
        tmdb_map = jellyfin_data.get("tmdb_episode_map", {})
        if movie_metadata["tmdb_identifier"] in tmdb_map:
            return tmdb_map[movie_metadata["tmdb_identifier"]]

    return movie_metadata.get("jellyfin_id", "")


def _resolve_movie_poster(
    tmdb_movie: Dict[str, Any],
    tmdb_id: str,
    existing_movie_data: Dict[str, Any] | None,
    offline: bool = False,
) -> str:
    """Three-step poster resolution for a movie.

    1. Cached local image.
    2. Existing valid local file.
    3. Download from TMDB CDN.

    Args:
        tmdb_movie: TMDB movie data.
        tmdb_id: TMDB identifier string.
        existing_movie_data: Previously stored movie data (may be ``None``).
        offline: When ``True``, skip network downloads.

    Returns:
        Local file path string (may be empty).
    """
    cached = tmdb_client.get_cached_image(f"tmdb_movie_{tmdb_id}")
    if cached and isinstance(cached, str):
        return cached

    if (
        existing_movie_data
        and existing_movie_data.get("poster_path")
        and Path(existing_movie_data["poster_path"]).is_file()
    ):
        return existing_movie_data["poster_path"]

    poster_path = tmdb_movie.get("poster_path", "")
    if poster_path:
        if tmdb_movie.get("_is_prefetched") and not poster_path.startswith("/"):
            return poster_path
        if not offline:
            return tmdb_client.download_image(poster_path, f"tmdb_movie_{tmdb_id}")

    return ""


def _apply_tmdb_movie_data(
    movie_metadata: Dict[str, Any],
    tmdb_movie: Dict[str, Any],
    existing_movie_data: Dict[str, Any] | None,
    offline: bool = False,
    metadata_only: bool = False,
) -> None:
    """Fills *movie_metadata* with TMDB fields including poster, runtime,
    rating, and genre.  Fetches the full TMDB record when runtime is absent.

    Args:
        movie_metadata: Target metadata dict (mutated in-place).
        tmdb_movie: TMDB movie data (may be a stub).
        existing_movie_data: Previously stored movie data (may be ``None``).
        offline: When ``True``, skip network downloads.
        metadata_only: Unused in this function (reserved for interface
            compatibility).
    """
    tmdb_id = str(tmdb_movie.get("id", ""))
    movie_metadata["tmdb_identifier"] = tmdb_id
    movie_metadata["overview"] = tmdb_movie.get("overview", "")
    movie_metadata["tmdb_name"] = tmdb_movie.get("title", "")

    release_date = tmdb_movie.get("release_date", "")
    if release_date:
        movie_metadata["year"] = int(release_date.split("-")[0])
    else:
        movie_metadata["year"] = movie_metadata.get("year") or 0

    movie_metadata["poster_path"] = _resolve_movie_poster(
        tmdb_movie, tmdb_id, existing_movie_data, offline
    )

    # Fetch full details for runtime / rating / genre when not already present
    if "runtime" not in tmdb_movie and not offline:
        full = tmdb_client.get_movie_by_id(tmdb_id)
        if full:
            tmdb_movie = full

    movie_metadata["runtime"] = tmdb_movie.get("runtime", 0)
    movie_metadata["rating"] = str(tmdb_movie.get("vote_average", ""))
    genres = tmdb_movie.get("genres", [])
    movie_metadata["genre"] = (
        ", ".join([genre.get("name", "") for genre in genres]) if genres else ""
    )
