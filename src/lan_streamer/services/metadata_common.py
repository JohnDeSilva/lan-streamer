"""Shared/common metadata resolution helpers used by both movie and TV paths.

This module contains small utility functions that do not require TMDB access
and can be safely imported by both :mod:`~.metadata_movie` and
:mod:`~.metadata_tv`.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger("lan_streamer.services.metadata_common")


def _build_locked_tv_tmdb_stub(existing_series: Dict[str, Any]) -> Dict[str, Any]:
    """Builds a minimal prefetched TMDB stub for a locked TV series so the
    scanner can skip a network round-trip while still carrying the right ID.

    Args:
        existing_series: The existing series data dictionary containing
            metadata with TMDB identifiers.

    Returns:
        A dictionary with TMDB-like keys (``id``, ``name``, ``overview``,
        ``poster_path``, ``first_air_date``) and a ``_is_prefetched`` flag.
    """
    metadata = existing_series.get("metadata", {})
    return {
        "id": metadata.get("tmdb_identifier"),
        "name": metadata.get("tmdb_name", ""),
        "overview": metadata.get("overview", ""),
        "poster_path": metadata.get("poster_path", ""),
        "first_air_date": metadata.get("first_air_date", ""),
        "_is_prefetched": True,
    }


def _build_locked_movie_tmdb_stub(
    existing_movie: Dict[str, Any],
    folder_name: str,
) -> Dict[str, Any]:
    """Builds a minimal prefetched TMDB stub for a locked movie entry so the
    scanner can skip a network round-trip while still carrying the right ID.

    Args:
        existing_movie: The existing movie data dictionary.
        folder_name: Fallback movie title when no TMDB name is stored.

    Returns:
        A dictionary with TMDB-like keys (``id``, ``title``, ``overview``,
        ``poster_path``) and a ``_is_prefetched`` flag.
    """
    return {
        "id": existing_movie.get("tmdb_identifier"),
        "title": existing_movie.get("tmdb_name", folder_name),
        "overview": existing_movie.get("overview", ""),
        "poster_path": existing_movie.get("poster_path", ""),
        "_is_prefetched": True,
    }


def _resolve_existing_jellyfin_id(
    existing_item: Dict[str, Any], library_type: str
) -> str | None:
    """Reads the stored Jellyfin ID from *existing_item* for either library type.

    Args:
        existing_item: The existing series or movie data dictionary.
        library_type: Either ``"movie"`` or ``"tv"``.

    Returns:
        The Jellyfin ID string, or ``None`` when absent.
    """
    if library_type == "movie":
        return existing_item.get("jellyfin_id") or None
    return existing_item.get("metadata", {}).get("jellyfin_id") or None


def _merge_season_episodes(
    existing_episodes: List[Any],
    new_episodes: List[Any],
    season_name: str,
) -> None:
    """Merges *new_episodes* into *existing_episodes* in-place, skipping
    duplicates by path (exact copy) or by name (different path same title).

    Args:
        existing_episodes: The list of existing episode dictionaries to
            mutate.
        new_episodes: New episode dictionaries to merge in.
        season_name: Human-readable season name used in log messages.
    """
    existing_paths: set[str] = {ep["path"] for ep in existing_episodes}
    existing_names: set[str] = {ep["name"] for ep in existing_episodes}
    for episode in new_episodes:
        if (
            episode["path"] not in existing_paths
            and episode["name"] not in existing_names
        ):
            logger.debug(f"Adding episode '{episode['name']}' from '{episode['path']}'")
            existing_episodes.append(episode)
        elif episode["path"] not in existing_paths:
            logger.warning(
                f"Skipping episode '{episode['name']}' from '{episode['path']}' "
                f"because an episode with the same name already exists in {season_name}."
            )
        else:
            logger.debug(f"Skipping exact duplicate path: {episode['path']}")
