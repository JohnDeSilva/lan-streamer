"""Media mapping service — maps files to episodes/movies, resolves Jellyfin IDs, selects best versions."""

import logging
from pathlib import Path
from typing import Any, Dict

from lan_streamer.scanner.parser import _parse_season_number
from lan_streamer.scanner.proxy import _parse_episode_number

logger = logging.getLogger("lan_streamer.services.media_mapping")


def resolve_episode_jellyfin_id(
    episode_path: str,
    episode_name: str,
    episode_file: Path,
    tmdb_episode_identifier: str | None,
    tmdb_name: str | None,
    tmdb_number: int | None,
    season_name: str,
    series_directory: Path,
    series_data: Dict[str, Any],
    season_metadata: Dict[str, Any],
    tmdb_series: Dict[str, Any] | None,
    jellyfin_data: Dict[str, Any] | None,
) -> tuple[str, str, str]:
    """Resolve the Jellyfin ID for a single episode file using a multi-strategy approach.

    Attempts four strategies in order of precedence:

    1. **Path map** — direct match via ``jellyfin_data["path_map"]``.
    2. **TMDB episode map** — match via ``jellyfin_data["tmdb_episode_map"]``
       using the TMDB episode identifier.
    3. **Name map** — match via ``jellyfin_data["name_map"]`` using a
       ``(series_name, episode_name)`` tuple.
    4. **Series-ID map** — match via ``jellyfin_data["series_id_map"]``
       by season/episode number or by episode name fallback.

    Parameters
    ----------
    episode_path : str
        Absolute filesystem path of the episode file.
    episode_name : str
        Filename (including extension) of the episode.
    episode_file : Path
        :class:`pathlib.Path` object for the episode file.
    tmdb_episode_identifier : str | None
        TMDB episode identifier, if known.
    tmdb_name : str | None
        TMDB episode title, if known.
    tmdb_number : int | None
        TMDB episode number, if known.
    season_name : str
        Name of the season directory (e.g. ``"Season 1"``).
    series_directory : Path
        Root directory of the TV series.
    series_data : Dict[str, Any]
        Aggregated series data structure (includes ``metadata`` key).
    season_metadata : Dict[str, Any]
        Metadata dictionary for the current season.
    tmdb_series : Dict[str, Any] | None
        TMDB series data, or ``None`` if unavailable.
    jellyfin_data : Dict[str, Any] | None
        Pre-fetched Jellyfin lookup maps, or ``None``.

    Returns
    -------
    tuple[str, str, str]
        A three-tuple of ``(jellyfin_id, new_series_jellyfin_id,
        new_season_jellyfin_id)``.  Each value may be an empty string
        when no match was found.
    """
    jellyfin_id = ""
    new_series_jellyfin_id = ""
    new_season_jellyfin_id = ""

    if not jellyfin_data:
        return jellyfin_id, new_series_jellyfin_id, new_season_jellyfin_id

    # 1. Path map
    path_map = jellyfin_data.get("path_map") or {}
    jellyfin_info = path_map.get(episode_path)
    if jellyfin_info:
        jellyfin_id = jellyfin_info["id"]
        new_series_jellyfin_id = jellyfin_info.get("series_id") or ""
        new_season_jellyfin_id = jellyfin_info.get("season_id") or ""

    # 2. TMDB episode map
    if not jellyfin_id and tmdb_episode_identifier:
        jellyfin_id = jellyfin_data.get("tmdb_episode_map", {}).get(
            str(tmdb_episode_identifier), ""
        )

    # 3. Name map
    if not jellyfin_id:
        name_map = jellyfin_data.get("name_map", {})
        lookup_series = str(
            tmdb_series.get("name")
            if tmdb_series and tmdb_series.get("name")
            else series_directory.name
        ).lower()
        lookup_episode = str(tmdb_name if tmdb_name else episode_file.stem).lower()
        jellyfin_id = name_map.get((lookup_series, lookup_episode), "")

    # 4. Series-ID map — SxxExx then episode name
    series_metadata = series_data["metadata"]
    if not jellyfin_id and series_metadata.get("jellyfin_id"):
        series_map = jellyfin_data.get("series_id_map", {}).get(
            series_metadata["jellyfin_id"]
        )
        if series_map:
            parsed = _parse_episode_number(episode_name)
            season_num: int | None = None
            episode_num: int | None = None
            if parsed:
                season_num, episode_num = parsed
            elif tmdb_number is not None:
                episode_num = tmdb_number
                season_num = _parse_season_number(season_name)

            if season_num is not None and episode_num is not None:
                jellyfin_id = series_map["episodes"].get((season_num, episode_num), "")
                if jellyfin_id:
                    logger.debug(
                        f"Matched '{episode_name}' via Series ID map "
                        f"(S{season_num:02}E{episode_num:02})"
                    )

            if not jellyfin_id:
                lookup_name = (tmdb_name or episode_file.stem).lower()
                jellyfin_id = series_map["names"].get(lookup_name, "")
                if jellyfin_id:
                    logger.debug(
                        f"Matched '{episode_name}' via Series ID map name '{lookup_name}'"
                    )

    if jellyfin_id:
        logger.info(f"Matched Jellyfin ID for '{episode_name}': {jellyfin_id}")

    return jellyfin_id, new_series_jellyfin_id, new_season_jellyfin_id


def resolve_movie_jellyfin_id(
    movie_metadata: Dict[str, Any],
    video_path: str,
    jellyfin_data: Dict[str, Any] | None,
) -> str:
    """Resolve the Jellyfin ID for a movie using a three-step strategy.

    Steps attempted in order:

    1. **Path map** — direct match via ``jellyfin_data["path_map"]``.
    2. **TMDB ID map** — match via ``jellyfin_data["tmdb_episode_map"]``
       (reused for movies) using the TMDB identifier.
    3. **Fallback** — returns the ``jellyfin_id`` already stored in
       *movie_metadata* (which may be an empty string).

    Parameters
    ----------
    movie_metadata : Dict[str, Any]
        Metadata dictionary for the movie.  Must contain the key
        ``"jellyfin_id"`` and optionally ``"tmdb_identifier"``.
    video_path : str
        Absolute filesystem path of the movie file.
    jellyfin_data : Dict[str, Any] | None
        Pre-fetched Jellyfin lookup maps, or ``None``.

    Returns
    -------
    str
        The resolved Jellyfin ID, or an empty string if no match was found.
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
