import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Any

from lan_streamer.scanner.proxy import tmdb_client, _parse_episode_number
from lan_streamer.db import natural_sort_key
from lan_streamer.scanner.parser import (
    _is_video_file,
    _parse_season_number,
)

logger = logging.getLogger("lan_streamer.scanner")


def clean_series_data(series_data: Dict[str, Any]) -> Dict[str, Any] | None:
    """Cleans up temporary tmdb variables from series data."""
    clean_seasons = {}
    for season, season_data in series_data.get("seasons", {}).items():
        if season_data["episodes"]:
            # Sort episodes naturally
            season_data["episodes"].sort(key=lambda x: natural_sort_key(x["name"]))
            season_data.pop("_tmdb_episodes", None)
            clean_seasons[season] = season_data

    if clean_seasons:
        series_data["seasons"] = clean_seasons
        series_data.pop("_tmdb_seasons", None)
        series_data.pop("_tmdb_series_id", None)
        return series_data
    return None


def _build_locked_tv_tmdb_stub(existing_series: Dict[str, Any]) -> Dict[str, Any]:
    """
    Builds a minimal prefetched TMDB stub for a locked TV series so the
    scanner can skip a network round-trip while still carrying the right ID.
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
    """
    Builds a minimal prefetched TMDB stub for a locked movie entry so the
    scanner can skip a network round-trip while still carrying the right ID.
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
    """
    Reads the stored Jellyfin ID from *existing_item* for either library type.
    Returns the ID string or None when absent.
    """
    if library_type == "movie":
        return existing_item.get("jellyfin_id") or None
    return existing_item.get("metadata", {}).get("jellyfin_id") or None


def _merge_season_episodes(
    existing_episodes: List[Any],
    new_episodes: List[Any],
    season_name: str,
) -> None:
    """
    Merges *new_episodes* into *existing_episodes* in-place, skipping
    duplicates by path (exact copy) or by name (different path same title).
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


def _build_movie_metadata_defaults() -> Dict[str, Any]:
    """Returns a blank movie metadata dictionary with all expected keys."""
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
    """
    Copies non-empty scalar fields from *existing* movie data into *metadata*,
    then overrides the Jellyfin ID when a manual one is supplied.
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
    """
    Three-step Jellyfin ID resolution for a movie:
    1. Direct path match via path_map.
    2. TMDB ID match via tmdb_episode_map.
    Returns the resolved ID string (may be empty).
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
) -> str:
    """
    Three-step poster resolution for a movie:
    1. Cached local image.
    2. Existing valid local file.
    3. Download from TMDB CDN.
    Returns the local file path string (may be empty).
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
        return tmdb_client.download_image(poster_path, f"tmdb_movie_{tmdb_id}")

    return ""


def _apply_tmdb_movie_data(
    movie_metadata: Dict[str, Any],
    tmdb_movie: Dict[str, Any],
    existing_movie_data: Dict[str, Any] | None,
) -> None:
    """
    Fills *movie_metadata* with TMDB fields including poster, runtime,
    rating, and genre.  Fetches the full TMDB record when runtime is absent.
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
        tmdb_movie, tmdb_id, existing_movie_data
    )

    # Fetch full details for runtime / rating / genre when not already present
    if "runtime" not in tmdb_movie:
        full = tmdb_client.get_movie_by_id(tmdb_id)
        if full:
            tmdb_movie = full

    movie_metadata["runtime"] = tmdb_movie.get("runtime", 0)
    movie_metadata["rating"] = str(tmdb_movie.get("vote_average", ""))
    genres = tmdb_movie.get("genres", [])
    movie_metadata["genre"] = (
        ", ".join([genre.get("name", "") for genre in genres]) if genres else ""
    )


def _build_existing_episodes_index(
    existing_series_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Builds a path → episode-dict lookup from an existing series data structure.
    """
    index: Dict[str, Any] = {}
    for season in existing_series_data.get("seasons", {}).values():
        for episode in season.get("episodes", []):
            index[episode["path"]] = episode
    return index


def _detect_new_series_files(
    series_directory: Path,
    existing_episodes_by_path: Dict[str, Any],
) -> bool:
    """
    Returns True when at least one video file inside *series_directory* is not
    present in *existing_episodes_by_path*, indicating the library has grown.
    """
    for file_path in series_directory.rglob("*"):
        if _is_video_file(file_path):
            try:
                rel_path = file_path.relative_to(series_directory)
                parts = rel_path.parts
                if len(parts) > 2:
                    first_dir = parts[0]
                    first_dir_lower = first_dir.lower()
                    is_valid_season = (
                        "season" in first_dir_lower
                        or "special" in first_dir_lower
                        or "extra" in first_dir_lower
                        or "featurette" in first_dir_lower
                        or "bonus" in first_dir_lower
                        or "shorts" in first_dir_lower
                        or bool(re.search(r"\d+", first_dir))
                    )
                    if is_valid_season:
                        continue
            except Exception:
                pass

            abs_path = str(file_path.absolute())
            if abs_path not in existing_episodes_by_path:
                logger.debug(
                    f"New/unindexed file detected in '{series_directory.name}': '{abs_path}'"
                )
                return True
    return False


def _build_series_metadata_defaults(
    manual_jellyfin_id: str | None,
) -> Dict[str, Any]:
    """Returns a blank series metadata dictionary with all expected keys."""
    return {
        "tmdb_identifier": "",
        "overview": "",
        "poster_path": "",
        "tmdb_name": "",
        "first_air_date": "",
        "jellyfin_id": manual_jellyfin_id or "",
    }


def _resolve_series_poster(
    tmdb_series: Dict[str, Any],
    tmdb_identifier: str,
    existing_series_data: Dict[str, Any] | None,
) -> str:
    """
    Three-step poster resolution for a TV series:
    1. Cached local image.
    2. Existing valid local file.
    3. Download from TMDB CDN.
    Returns the local file path string (may be empty).
    """
    cached = tmdb_client.get_cached_image(f"tmdb_series_{tmdb_identifier}")
    if cached and isinstance(cached, str):
        return cached

    if existing_series_data:
        existing_poster = existing_series_data.get("metadata", {}).get(
            "poster_path", ""
        )
        if existing_poster and Path(existing_poster).is_file():
            return existing_poster

    poster_path = tmdb_series.get("poster_path") or ""
    if poster_path:
        if tmdb_series.get("_is_prefetched") and not poster_path.startswith("/"):
            return poster_path
        return tmdb_client.download_image(poster_path, f"tmdb_series_{tmdb_identifier}")

    return ""


def _resolve_episode_jellyfin_id(
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
    """
    Multi-strategy Jellyfin ID resolution for a single episode file.
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


def _process_series_metadata(
    series_directory: Path,
    tmdb_series: Dict[str, Any] | None,
    jellyfin_data: Dict[str, Any] | None,
    manual_jellyfin_id: str | None,
    existing_series_data: Dict[str, Any] | None,
    force_refresh: bool,
    cleanup: bool,
    single_item_refresh: bool = False,
) -> tuple[Dict[str, Any], bool, Dict[str, Any] | None, Dict[str, Any]]:
    series_name = series_directory.name

    existing_episodes_by_path: Dict[str, Any] = {}
    is_locked = False
    existing_tmdb_identifier = ""
    if existing_series_data:
        ext_metadata = existing_series_data.get("metadata", {})
        is_locked = ext_metadata.get("locked_metadata", False)
        existing_tmdb_identifier = ext_metadata.get("tmdb_identifier", "")
        existing_episodes_by_path = _build_existing_episodes_index(existing_series_data)

    has_new_files = (
        _detect_new_series_files(series_directory, existing_episodes_by_path)
        if existing_series_data
        else False
    )

    if has_new_files and not is_locked:
        logger.info(
            f"New files detected in series '{series_name}'. Automatically pulling fresh metadata."
        )
        force_refresh = True
        if existing_tmdb_identifier and not tmdb_series:
            full = tmdb_client.get_series_by_id(existing_tmdb_identifier)
            if full:
                tmdb_series = full

    series_metadata: Dict[str, Any] = _build_series_metadata_defaults(
        manual_jellyfin_id
    )

    if existing_series_data:
        ext_metadata = existing_series_data.get("metadata", {})
        for key, value in ext_metadata.items():
            if value:
                series_metadata[key] = value
        if manual_jellyfin_id:
            series_metadata["jellyfin_id"] = manual_jellyfin_id

    if not force_refresh and not cleanup and existing_series_data:
        series_data = existing_series_data.copy()
        meta = series_data.get("metadata", {})
        if (
            not meta.get("jellyfin_id")
            and jellyfin_data
            and meta.get("tmdb_identifier")
        ):
            meta["jellyfin_id"] = jellyfin_data.get("tmdb_series_map", {}).get(
                meta["tmdb_identifier"], ""
            )
        if manual_jellyfin_id:
            meta["jellyfin_id"] = manual_jellyfin_id
        path_map = jellyfin_data.get("path_map", {}) if jellyfin_data else {}
        tmdb_map = jellyfin_data.get("tmdb_episode_map", {}) if jellyfin_data else {}
        for season in series_data.get("seasons", {}).values():
            for episode in season.get("episodes", []):
                if jellyfin_data and not episode.get("jellyfin_id"):
                    if episode.get("path") in path_map:
                        episode["jellyfin_id"] = path_map[episode["path"]]["id"]
                    elif episode.get("tmdb_identifier") in tmdb_map:
                        episode["jellyfin_id"] = tmdb_map[episode["tmdb_identifier"]]
                    elif episode.get("tmdb_episode_identifier") in tmdb_map:
                        episode["jellyfin_id"] = tmdb_map[
                            episode["tmdb_episode_identifier"]
                        ]
                if not episode.get("runtime"):
                    episode["runtime"] = 0
        return series_data, True, tmdb_series, existing_episodes_by_path

    if tmdb_series and "name" not in tmdb_series and "id" in tmdb_series:
        if single_item_refresh or not series_metadata.get("tmdb_name"):
            full = tmdb_client.get_series_by_id(tmdb_series["id"])
            if full:
                tmdb_series = full

    if not tmdb_series:
        if series_metadata["tmdb_identifier"]:
            tmdb_series = {
                "id": series_metadata["tmdb_identifier"],
                "name": series_metadata["tmdb_name"],
                "overview": series_metadata["overview"],
                "poster_path": series_metadata["poster_path"],
                "first_air_date": series_metadata.get("first_air_date", ""),
            }
        elif not is_locked and (
            single_item_refresh
            or not existing_series_data
            or not existing_tmdb_identifier
        ):
            tmdb_series = tmdb_client.search_series(series_name)

    tmdb_seasons: list[Any] = []

    if tmdb_series:
        tmdb_identifier = str(tmdb_series.get("id") or "")
        series_metadata["tmdb_identifier"] = tmdb_identifier
        series_metadata["overview"] = tmdb_series.get("overview", "")
        series_metadata["tmdb_name"] = tmdb_series.get("name", "")
        series_metadata["first_air_date"] = tmdb_series.get("first_air_date", "")

        if tmdb_identifier:
            series_metadata["poster_path"] = _resolve_series_poster(
                tmdb_series, tmdb_identifier, existing_series_data
            )
        else:
            if not series_metadata.get("poster_path"):
                series_metadata["poster_path"] = ""

        if tmdb_identifier and not is_locked:
            if force_refresh or single_item_refresh or not existing_series_data:
                if tmdb_series and "seasons" in tmdb_series:
                    tmdb_seasons = tmdb_series["seasons"]
                else:
                    tmdb_seasons = tmdb_client.get_seasons(tmdb_identifier)

    if not series_metadata["jellyfin_id"] and jellyfin_data and tmdb_series:
        tmdb_id = str(tmdb_series.get("id") or "")
        if tmdb_id:
            series_metadata["jellyfin_id"] = jellyfin_data.get(
                "tmdb_series_map", {}
            ).get(tmdb_id, "")

    series_data: Dict[str, Any] = {
        "metadata": series_metadata,
        "seasons": {},
        "_tmdb_seasons": tmdb_seasons,
        "_tmdb_series_id": series_metadata.get("tmdb_identifier"),
        "_jellyfin_id": "",
    }

    return series_data, False, tmdb_series, existing_episodes_by_path


def _process_season_metadata(
    season_directory: Path,
    series_data: Dict[str, Any],
    existing_series_data: Dict[str, Any] | None,
    existing_episodes_by_path: Dict[str, Any],
    force_refresh: bool = False,
    single_item_refresh: bool = False,
) -> tuple[str, int, Dict[str, Any], list[Any]]:
    season_name = season_directory.name
    season_metadata: Dict[str, Any] = {
        "jellyfin_id": "",
    }
    tmdb_episodes: list[Any] = []

    if season_name.lower() == "specials":
        season_index = 0
    else:
        season_number_match = re.search(r"\d+", season_name)
        season_index = int(season_number_match.group()) if season_number_match else -1

    logger.debug(
        f"Processing season directory: '{season_name}' (Season index: {season_index})"
    )
    matched_tmdb_season = None
    for tmdb_season in series_data.get("_tmdb_seasons", []):
        if (
            tmdb_season.get("season_number") == season_index
            or tmdb_season.get("name") == season_name
        ):
            matched_tmdb_season = tmdb_season
            break

    existing_season_id = ""
    existing_season_poster = ""
    if existing_series_data and season_name in existing_series_data.get("seasons", {}):
        old_season_metadata = existing_series_data["seasons"][season_name].get(
            "metadata", {}
        )
        existing_season_id = old_season_metadata.get("tmdb_identifier", "")
        existing_season_poster = old_season_metadata.get("poster_path", "")

    if matched_tmdb_season and series_data["_tmdb_series_id"]:
        season_tmdb_identifier = matched_tmdb_season.get("id")
        season_metadata["tmdb_identifier"] = (
            str(season_tmdb_identifier) if season_tmdb_identifier else ""
        )

        cached_season_poster = (
            tmdb_client.get_cached_image(f"tmdb_season_{season_tmdb_identifier}")
            if season_tmdb_identifier
            else ""
        )
        if cached_season_poster and isinstance(cached_season_poster, str):
            season_metadata["poster_path"] = cached_season_poster
        elif existing_season_poster:
            season_metadata["poster_path"] = existing_season_poster
        else:
            artwork = matched_tmdb_season.get("poster_path") or ""
            if artwork and season_tmdb_identifier:
                season_metadata["poster_path"] = tmdb_client.download_image(
                    artwork, f"tmdb_season_{season_tmdb_identifier}"
                )
            else:
                season_metadata["poster_path"] = ""
    else:
        season_metadata["tmdb_identifier"] = existing_season_id
        season_metadata["poster_path"] = existing_season_poster

    is_locked = bool(series_data.get("metadata", {}).get("locked_metadata", False))
    season_already_has_episodes = False
    if existing_series_data and season_name in existing_series_data.get("seasons", {}):
        season_already_has_episodes = (
            len(existing_series_data["seasons"][season_name].get("episodes", [])) > 0
        )

    needs_episode_search = not is_locked and (
        force_refresh or single_item_refresh or not season_already_has_episodes
    )

    tmdb_episodes = []
    if needs_episode_search and series_data["_tmdb_series_id"]:
        logger.info(
            f"Fetching TMDB episodes list for series ID '{series_data['_tmdb_series_id']}', season index '{season_index}'"
        )
        tmdb_episodes = tmdb_client.get_episodes(
            series_data["_tmdb_series_id"], season_index
        )

    return season_name, season_index, season_metadata, tmdb_episodes


def _process_episode_file(
    episode_file: Path,
    season_name: str,
    series_directory: Path,
    series_data: Dict[str, Any],
    season_metadata: Dict[str, Any],
    tmdb_episodes: list[Any],
    tmdb_series: Dict[str, Any] | None,
    jellyfin_data: Dict[str, dict] | None,
    existing_episodes_by_path: Dict[str, Any],
    existing_series_data: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    episode_path = str(episode_file.absolute())
    episode_name = episode_file.name

    tmdb_episode_identifier = None
    tmdb_name = None
    tmdb_number = None
    air_date = ""
    runtime = 0
    jellyfin_id = ""

    existing_episode = existing_episodes_by_path.get(episode_path)
    cached_tmdb_episode_identifier = (
        existing_episode.get("tmdb_episode_identifier")
        or existing_episode.get("tmdb_identifier")
        if existing_episode
        else None
    )
    if existing_episode:
        tmdb_episode_identifier = cached_tmdb_episode_identifier or ""
        tmdb_name = existing_episode.get("tmdb_name")
        tmdb_number = existing_episode.get("tmdb_number")
        air_date = existing_episode.get("air_date", "")
        runtime = existing_episode.get("runtime", 0)
        jellyfin_id = existing_episode.get("jellyfin_id", "")
        logger.debug(f"Reusing existing metadata for '{episode_name}'")
        if tmdb_number is None:
            if cached_tmdb_episode_identifier and tmdb_episodes:
                for tmdb_ep in tmdb_episodes:
                    if str(tmdb_ep.get("id")) == str(cached_tmdb_episode_identifier):
                        tmdb_number = tmdb_ep.get("episode_number")
                        if not tmdb_name:
                            tmdb_name = tmdb_ep.get("name")
                        if not air_date:
                            air_date = tmdb_ep.get("air_date", "")
                        if not runtime:
                            runtime = tmdb_ep.get("runtime", 0)
                        break
            if tmdb_number is None:
                parsed = _parse_episode_number(episode_name)
                if parsed:
                    _, parsed_num = parsed
                    tmdb_number = parsed_num
                    if tmdb_episodes:
                        for tmdb_ep in tmdb_episodes:
                            if tmdb_ep.get("episode_number") == tmdb_number:
                                if not tmdb_episode_identifier:
                                    tmdb_episode_identifier = str(tmdb_ep.get("id", ""))
                                if not tmdb_name:
                                    tmdb_name = tmdb_ep.get("name")
                                if not air_date:
                                    air_date = tmdb_ep.get("air_date", "")
                                if not runtime:
                                    runtime = tmdb_ep.get("runtime", 0)
                                break
    else:
        # Check if there is an existing placeholder in this season in existing_series_data
        placeholder_episode = None
        parsed = _parse_episode_number(episode_name)
        if (
            parsed
            and existing_series_data
            and season_name in existing_series_data.get("seasons", {})
        ):
            _, episode_number = parsed
            for ep in existing_series_data["seasons"][season_name].get("episodes", []):
                if not ep.get("path") and ep.get("tmdb_number") == episode_number:
                    placeholder_episode = ep
                    break

        if placeholder_episode:
            tmdb_episode_identifier = placeholder_episode.get(
                "tmdb_episode_identifier"
            ) or placeholder_episode.get("tmdb_identifier")
            tmdb_name = placeholder_episode.get("tmdb_name")
            tmdb_number = placeholder_episode.get("tmdb_number")
            air_date = placeholder_episode.get("air_date", "")
            runtime = placeholder_episode.get("runtime", 0)
            jellyfin_id = placeholder_episode.get("jellyfin_id", "")
            logger.info(
                f"Matched '{episode_name}' to existing placeholder episode S{season_name} E{tmdb_number}"
            )
        elif parsed:
            _, episode_number = parsed
            for tmdb_episode in tmdb_episodes:
                if tmdb_episode.get("episode_number") == episode_number:
                    tmdb_episode_identifier = str(tmdb_episode.get("id", ""))
                    tmdb_name = tmdb_episode.get("name")
                    tmdb_number = tmdb_episode.get("episode_number")
                    air_date = tmdb_episode.get("air_date", "")
                    runtime = tmdb_episode.get("runtime", 0)
                    logger.debug(
                        f"Matched '{episode_name}' by parsed episode number: "
                        f"{episode_number} -> TMDB Name: '{tmdb_name}'"
                    )
                    break
        else:
            lookup_name = episode_file.stem.lower()
            for tmdb_episode in tmdb_episodes:
                tmdb_episode_name = str(tmdb_episode.get("name") or "").lower()
                if tmdb_episode_name and tmdb_episode_name in lookup_name:
                    tmdb_episode_identifier = str(tmdb_episode.get("id", ""))
                    tmdb_name = tmdb_episode.get("name")
                    tmdb_number = tmdb_episode.get("episode_number")
                    air_date = tmdb_episode.get("air_date", "")
                    runtime = tmdb_episode.get("runtime", 0)
                    logger.debug(
                        f"Matched '{episode_name}' by parsed substring: "
                        f"'{tmdb_episode_name}' -> TMDB Name: '{tmdb_name}'"
                    )
                    break

    try:
        ctime = os.path.getctime(episode_path)
    except OSError as error_instance:
        logger.debug(f"Could not read ctime for {episode_path}: {error_instance}")
        ctime = 0

    jellyfin_id, new_series_jf_id, new_season_jf_id = _resolve_episode_jellyfin_id(
        episode_path=episode_path,
        episode_name=episode_name,
        episode_file=episode_file,
        tmdb_episode_identifier=tmdb_episode_identifier,
        tmdb_name=tmdb_name,
        tmdb_number=tmdb_number,
        season_name=season_name,
        series_directory=series_directory,
        series_data=series_data,
        season_metadata=season_metadata,
        tmdb_series=tmdb_series,
        jellyfin_data=jellyfin_data,
    )

    if new_series_jf_id and not series_data["metadata"].get("jellyfin_id"):
        series_data["metadata"]["jellyfin_id"] = new_series_jf_id
    if new_season_jf_id and not season_metadata.get("jellyfin_id"):
        season_metadata["jellyfin_id"] = new_season_jf_id

    series_metadata = series_data["metadata"]
    if (
        not series_metadata.get("jellyfin_id")
        and series_data.get("_tmdb_series_id")
        and jellyfin_data
    ):
        series_metadata["jellyfin_id"] = jellyfin_data.get("tmdb_series_map", {}).get(
            str(series_data["_tmdb_series_id"]), ""
        )

    res = {
        "name": episode_name,
        "path": episode_path,
        "tmdb_identifier": tmdb_episode_identifier,
        "tmdb_episode_identifier": tmdb_episode_identifier,
        "tmdb_name": tmdb_name,
        "tmdb_number": tmdb_number,
        "air_date": air_date,
        "runtime": runtime or 0,
        "jellyfin_id": jellyfin_id,
        "watched": existing_episode.get("watched", False)
        if existing_episode
        else False,
        "date_added": ctime,
    }

    if existing_episode:
        res["video_codec"] = existing_episode.get("video_codec")
        res["resolution"] = existing_episode.get("resolution")
        res["audio_tracks"] = existing_episode.get("audio_tracks")
        res["subtitle_tracks"] = existing_episode.get("subtitle_tracks")

    return res
