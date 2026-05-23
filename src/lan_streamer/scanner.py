import os
import logging
import re
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
from .tmdb import tmdb_client
from .db import natural_sort_key

logger = logging.getLogger(__name__)


def get_detailed_file_info(file_path: str) -> Dict[str, Any]:
    """
    Extracts exhaustive technical metadata from a video file using ffprobe.
    Returns a dictionary containing resolution, codecs, and track listings.
    """
    info: Dict[str, Any] = {
        "path": file_path,
        "size_bytes": 0,
        "video_type": "Unknown",
        "resolution": "Unknown",
        "audio_tracks": [],
        "subtitle_tracks": [],
    }

    if not file_path or not os.path.exists(file_path):
        return info

    path_obj = Path(file_path)
    info["size_bytes"] = path_obj.stat().st_size
    info["video_type"] = path_obj.suffix.upper().replace(".", "")

    try:
        process_result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if process_result.returncode == 0:
            data = json.loads(process_result.stdout)
            streams = data.get("streams", [])

            for stream in streams:
                codec_type = stream.get("codec_type")
                codec_name = stream.get("codec_name", "unknown")
                tags = stream.get("tags", {})
                language = tags.get("language", "und")
                title = tags.get("title", "")

                track_info = {
                    "index": stream.get("index"),
                    "codec": codec_name,
                    "language": language,
                    "title": title,
                }

                if codec_type == "video":
                    width = stream.get("width")
                    height = stream.get("height")
                    if width and height:
                        info["resolution"] = f"{width}x{height}"
                    if not info.get("video_codec"):
                        info["video_codec"] = codec_name
                elif codec_type == "audio":
                    info["audio_tracks"].append(track_info)
                elif codec_type == "subtitle":
                    info["subtitle_tracks"].append(track_info)

    except Exception as exc:
        logger.error(f"Failed to extract detailed info for {file_path}: {exc}")

    return info


# Video file extensions we support
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"}

# Subtitle file extensions we support
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".vtt", ".sub", ".idx"}

# Regex to extract S01E02 style episode numbers from filenames
_EPISODE_REGEX = re.compile(r"[Ss](\d+)[Ee](\d+)")
# Regex to extract season number from folder names (e.g. "Season 1")
_SEASON_REGEX = re.compile(r"[Ss]eason\s*(\d+)", re.IGNORECASE)


def _parse_episode_number(filename: str) -> tuple[int, int] | None:
    """Returns (season_num, episode_num) parsed from filename, or None."""
    match = _EPISODE_REGEX.search(filename)
    if match:
        logger.debug(
            f"Parsed episode S{match.group(1)}E{match.group(2)} from '{filename}'"
        )
        return int(match.group(1)), int(match.group(2))
    return None


def _parse_season_number(season_name: str) -> int | None:
    """Returns season number parsed from folder name (e.g. 'Season 1'), or None."""
    if season_name.lower() == "specials":
        return 0
    match = _SEASON_REGEX.search(season_name)
    if match:
        logger.debug(f"Parsed season number {match.group(1)} from '{season_name}'")
        return int(match.group(1))
    return None


def _extract_video_runtime(file_path: str) -> int:
    """
    Extracts video runtime in minutes directly from the video file itself.
    First attempts using ffprobe via subprocess for clean offline parsing,
    falling back to libvlc media parsing if ffprobe is unavailable.
    Untyped definitions and abbreviations are strictly prohibited.
    """
    if not file_path or not os.path.exists(file_path):
        return 0

    try:
        process_result: subprocess.CompletedProcess[str] = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if process_result.returncode == 0 and process_result.stdout.strip():
            duration_seconds: float = float(process_result.stdout.strip())
            return int(round(duration_seconds / 60.0))
    except Exception as error_instance:
        logger.debug(f"ffprobe extraction failed for '{file_path}': {error_instance}")

    try:
        import vlc

        vlc_instance: Any = vlc.Instance("--quiet")
        media_object: Any = vlc_instance.media_new(file_path)
        media_object.parse()
        duration_milliseconds: int = media_object.get_duration()
        if duration_milliseconds > 0:
            return int(round(duration_milliseconds / 60000.0))
    except Exception as error_instance:
        logger.debug(f"vlc extraction failed for '{file_path}': {error_instance}")

    return 0


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


# ---------------------------------------------------------------------------
# Pure helper functions — each represents a single logical step extracted
# from the larger scan_* functions for readability and unit testability.
# ---------------------------------------------------------------------------


def _is_video_file(file_path: "Path") -> bool:
    """Returns True when *file_path* has a recognised video extension."""
    return file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS


def _build_locked_tv_tmdb_stub(existing_series: "Dict[str, Any]") -> "Dict[str, Any]":
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
    existing_movie: "Dict[str, Any]",
    folder_name: str,
) -> "Dict[str, Any]":
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
    existing_item: "Dict[str, Any]", library_type: str
) -> "str | None":
    """
    Reads the stored Jellyfin ID from *existing_item* for either library type.
    Returns the ID string or None when absent.
    """
    if library_type == "movie":
        return existing_item.get("jellyfin_id") or None
    return existing_item.get("metadata", {}).get("jellyfin_id") or None


def _merge_season_episodes(
    existing_episodes: "List[Any]",
    new_episodes: "List[Any]",
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


def _build_movie_metadata_defaults() -> "Dict[str, Any]":
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
    metadata: "Dict[str, Any]",
    existing: "Dict[str, Any]",
    manual_jellyfin_id: "str | None",
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
    movie_metadata: "Dict[str, Any]",
    video_path: str,
    jellyfin_data: "Dict[str, Any] | None",
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
    tmdb_movie: "Dict[str, Any]",
    tmdb_id: str,
    existing_movie_data: "Dict[str, Any] | None",
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
    movie_metadata: "Dict[str, Any]",
    tmdb_movie: "Dict[str, Any]",
    existing_movie_data: "Dict[str, Any] | None",
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
    existing_series_data: "Dict[str, Any]",
) -> "Dict[str, Any]":
    """
    Builds a path → episode-dict lookup from an existing series data structure.
    Used to quickly determine which files already have cached metadata.
    """
    index: "Dict[str, Any]" = {}
    for season in existing_series_data.get("seasons", {}).values():
        for episode in season.get("episodes", []):
            index[episode["path"]] = episode
    return index


def _detect_new_series_files(
    series_directory: "Path",
    existing_episodes_by_path: "Dict[str, Any]",
) -> bool:
    """
    Returns True when at least one video file inside *series_directory* is not
    present in *existing_episodes_by_path*, indicating the library has grown.
    """
    for file_path in series_directory.rglob("*"):
        if _is_video_file(file_path):
            if str(file_path.absolute()) not in existing_episodes_by_path:
                return True
    return False


def _build_series_metadata_defaults(
    manual_jellyfin_id: "str | None",
) -> "Dict[str, Any]":
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
    tmdb_series: "Dict[str, Any]",
    tmdb_identifier: str,
    existing_series_data: "Dict[str, Any] | None",
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
    episode_file: "Path",
    tmdb_episode_identifier: "str | None",
    tmdb_name: "str | None",
    tmdb_number: "int | None",
    season_name: str,
    series_directory: "Path",
    series_data: "Dict[str, Any]",
    season_metadata: "Dict[str, Any]",
    tmdb_series: "Dict[str, Any] | None",
    jellyfin_data: "Dict[str, Any] | None",
) -> "tuple[str, str, str]":
    """
    Multi-strategy Jellyfin ID resolution for a single episode file.

    Tries (in order):
    1. Direct file path match via path_map.
    2. TMDB episode ID match via tmdb_episode_map.
    3. Episode name match via name_map.
    4. Series-ID map — SxxExx then name.

    Returns a tuple of (jellyfin_id, resolved_series_jellyfin_id, resolved_season_jellyfin_id).
    The last two are non-empty only when newly discovered via jellyfin_info.
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
            season_num: "int | None" = None
            episode_num: "int | None" = None
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


class LibraryDict(dict[str, Any]):
    """
    Custom dictionary subclass to hold library contents and track
    any root directories that were unavailable during scanning.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.unavailable_directories: List[str] = []


def scan_directories(
    root_directories: List[str],
    library_type: str = "tv",
    existing_library: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, Any] | None = None,
    callback: Any = None,
    force_refresh: bool = False,
    cleanup: bool = False,
    single_item_refresh: bool = False,
    detail_callback: Any = None,
    root_directory_label: str = "",
) -> LibraryDict:
    """
    Scans root directories and matches with TMDB to pull metadata.
    Watch history (watched status) is handled separately via Jellyfin sync.
    """
    library = LibraryDict()
    existing_library = existing_library or {}

    logger.info(f"Starting directory scan. Root directories: {root_directories}")

    for root_directory in root_directories:
        logger.info(f"Scanning root directory: {root_directory}")
        root_path = Path(root_directory)
        if not root_path.exists() or not root_path.is_dir():
            logger.warning(f"Root directory '{root_directory}' is unavailable")
            library.unavailable_directories.append(root_directory)
            if detail_callback:
                detail_callback("unavailable_root", {"root": root_directory})
            continue

        # Sort series directories by mtime (newest first)
        series_dirs = sorted(
            [
                directory
                for directory in root_path.iterdir()
                if directory.is_dir() and not directory.name.startswith(".")
            ],
            key=lambda directory: directory.stat().st_mtime,
            reverse=True,
        )

        if detail_callback:
            detail_callback(
                "root_total",
                {"root": root_directory, "total": len(series_dirs)},
            )

        for series_directory in series_dirs:
            series_name = series_directory.name
            if detail_callback:
                detail_callback(
                    "start_folder",
                    {"root": root_directory, "folder": series_name},
                )

            # Check if we have an existing manual match for THIS SPECIFIC folder name
            existing_series = existing_library.get(series_name)
            tmdb_series = None
            is_locked = False
            existing_jellyfin_id = None
            has_meta = False

            if existing_series:
                existing_jellyfin_id = _resolve_existing_jellyfin_id(
                    existing_series, library_type
                )
                if library_type == "movie":
                    is_locked = bool(existing_series.get("locked_metadata", False))
                    has_meta = bool(existing_series.get("tmdb_identifier"))
                    if is_locked:
                        logger.info(
                            f"Using locked TMDB metadata for movie '{series_name}' "
                            f"(ID: {existing_series['tmdb_identifier']})"
                        )
                        tmdb_series = _build_locked_movie_tmdb_stub(
                            existing_series, series_name
                        )
                else:
                    is_locked = bool(
                        existing_series.get("metadata", {}).get(
                            "locked_metadata", False
                        )
                    )
                    has_meta = bool(
                        existing_series.get("metadata", {}).get("tmdb_identifier")
                    )
                    if is_locked:
                        logger.info(
                            f"Using locked TMDB metadata for '{series_name}' "
                            f"(ID: {existing_series['metadata']['tmdb_identifier']})"
                        )
                        tmdb_series = _build_locked_tv_tmdb_stub(existing_series)

            series_force_refresh = (
                force_refresh
                if not is_locked and (single_item_refresh or not has_meta)
                else False
            )
            cleaned: Optional[Dict[str, Any]] = None
            if library_type == "movie":
                series_data = scan_movie(
                    series_directory,
                    tmdb_movie=tmdb_series,
                    jellyfin_data=jellyfin_data,
                    manual_jellyfin_id=existing_jellyfin_id,
                    existing_movie_data=existing_series,
                    force_refresh=series_force_refresh,
                    cleanup=cleanup,
                    single_item_refresh=single_item_refresh,
                    detail_callback=detail_callback,
                )
                if not series_data:
                    if detail_callback:
                        detail_callback(
                            "finish_folder",
                            {
                                "root": root_directory,
                                "folder": series_name,
                                "skipped": True,
                            },
                        )
                    continue
                cleaned = series_data
            else:
                series_data = scan_series(
                    series_directory,
                    tmdb_series=tmdb_series,
                    jellyfin_data=jellyfin_data,
                    manual_jellyfin_id=existing_jellyfin_id,
                    existing_series_data=existing_series,
                    force_refresh=series_force_refresh,
                    cleanup=cleanup,
                    single_item_refresh=single_item_refresh,
                    detail_callback=detail_callback,
                )
                if is_locked:
                    series_data["metadata"]["locked_metadata"] = True

                cleaned = clean_series_data(series_data)
                if not cleaned:
                    if detail_callback:
                        detail_callback(
                            "finish_folder",
                            {
                                "root": root_directory,
                                "folder": series_name,
                                "skipped": True,
                            },
                        )
                    continue

            # Identify if this series matches something already in our library
            match_key = None
            if series_name in library:
                match_key = series_name

            if match_key:
                # Merge into existing entry
                existing = library[match_key]
                logger.info(
                    f"Merging '{series_name}' into existing entry '{match_key}'"
                )

                if library_type == "movie":
                    pass  # We just keep existing movie for now, no complex merge
                else:
                    for season_name, season_data in cleaned.get("seasons", {}).items():
                        if season_name in existing.get("seasons", {}):
                            existing_episodes = existing["seasons"][season_name][
                                "episodes"
                            ]
                            _merge_season_episodes(
                                existing_episodes, season_data["episodes"], season_name
                            )
                            existing_episodes.sort(
                                key=lambda x: natural_sort_key(x["name"])
                            )
                        else:
                            existing.setdefault("seasons", {})[season_name] = (
                                season_data
                            )
            else:
                library[series_name] = cleaned

            if detail_callback:
                detail_callback(
                    "finish_folder",
                    {"root": root_directory, "folder": series_name, "skipped": False},
                )

            if callback:
                callback(library)

    if not cleanup and existing_library:
        for old_series_name, old_series_data in existing_library.items():
            if old_series_name not in library:
                logger.info(
                    f"Preserving missing folder '{old_series_name}' (non-destructive)"
                )
                library[old_series_name] = old_series_data

    return library


def _parse_movie_folder(folder_name: str) -> tuple[str, int | None]:
    """Returns (title, year) parsed from folder name like 'Avatar (2009)'."""
    match = re.search(r"\((\d{4})\)", folder_name)
    if match:
        year = int(match.group(1))
        title = folder_name[: match.start()].strip()
        return title, year
    return folder_name, None


def scan_movie(
    movie_directory: Path,
    tmdb_movie: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, dict] | None = None,
    manual_jellyfin_id: str | None = None,
    existing_movie_data: Dict[str, Any] | None = None,
    force_refresh: bool = False,
    cleanup: bool = False,
    single_item_refresh: bool = False,
    detail_callback: Any = None,
) -> Dict[str, Any] | None:
    folder_name = movie_directory.name
    title, year = _parse_movie_folder(folder_name)

    # Find the first video file
    video_file = None
    for file in movie_directory.rglob("*"):
        if file.is_file() and file.suffix.lower() in VIDEO_EXTENSIONS:
            video_file = file
            break

    if not video_file:
        return None

    if detail_callback:
        detail_callback(
            "start_file", {"file": str(video_file), "folder": movie_directory.name}
        )

    try:
        ctime = os.path.getctime(video_file)
    except OSError:
        ctime = 0

    video_path = str(video_file.absolute())
    is_locked = (
        existing_movie_data.get("locked_metadata", False)
        if existing_movie_data
        else False
    )
    existing_tmdb_id = (
        existing_movie_data.get("tmdb_identifier", "") if existing_movie_data else ""
    )

    # Detect if this is a newly found file path
    has_new_file = (
        not existing_movie_data or existing_movie_data.get("path") != video_path
    )
    if has_new_file and not is_locked:
        logger.info(
            f"New file detected for movie '{folder_name}'. Automatically pulling fresh metadata."
        )
        force_refresh = True
        if existing_tmdb_id and not tmdb_movie:
            full = tmdb_client.get_movie_by_id(existing_tmdb_id)
            if full:
                tmdb_movie = full

    movie_metadata = _build_movie_metadata_defaults()
    movie_metadata["jellyfin_id"] = manual_jellyfin_id or ""

    if existing_movie_data:
        _apply_existing_movie_metadata(
            movie_metadata, existing_movie_data, manual_jellyfin_id
        )

    if not force_refresh and not cleanup and existing_movie_data:
        movie_data = existing_movie_data.copy()
        if video_path:
            movie_data["path"] = video_path
        if not movie_data.get("jellyfin_id") and jellyfin_data:
            path_map = jellyfin_data.get("path_map", {})
            if video_path in path_map:
                movie_data["jellyfin_id"] = path_map[video_path]["id"]
            elif movie_data.get("tmdb_identifier"):
                tmdb_map = jellyfin_data.get("tmdb_episode_map", {})
                if movie_data["tmdb_identifier"] in tmdb_map:
                    movie_data["jellyfin_id"] = tmdb_map[movie_data["tmdb_identifier"]]
        if manual_jellyfin_id:
            movie_data["jellyfin_id"] = manual_jellyfin_id
        if not movie_data.get("runtime"):
            movie_data["runtime"] = 0
        return movie_data

    if tmdb_movie and "title" not in tmdb_movie and "id" in tmdb_movie:
        if single_item_refresh or not movie_metadata.get("tmdb_name"):
            full = tmdb_client.get_movie_by_id(tmdb_movie["id"])
            if full:
                tmdb_movie = full

    if not tmdb_movie:
        if movie_metadata["tmdb_identifier"]:
            tmdb_movie = {
                "id": movie_metadata["tmdb_identifier"],
                "title": movie_metadata["tmdb_name"],
                "overview": movie_metadata["overview"],
                "poster_path": movie_metadata["poster_path"],
                "release_date": f"{movie_metadata['year']}-01-01"
                if movie_metadata["year"]
                else "",
            }
        elif not is_locked and (
            single_item_refresh or not existing_movie_data or not existing_tmdb_id
        ):
            tmdb_movie = tmdb_client.search_movie(title, year)

    if tmdb_movie:
        _apply_tmdb_movie_data(movie_metadata, tmdb_movie, existing_movie_data)

    movie_metadata["jellyfin_id"] = _resolve_movie_jellyfin_id(
        movie_metadata, video_path, jellyfin_data
    )

    movie_data = {
        "name": folder_name,
        "path": video_path,
        "jellyfin_id": movie_metadata["jellyfin_id"],
        "tmdb_identifier": movie_metadata["tmdb_identifier"],
        "poster_path": movie_metadata["poster_path"],
        "overview": movie_metadata["overview"],
        "tmdb_name": movie_metadata["tmdb_name"],
        "locked_metadata": existing_movie_data.get("locked_metadata", False)
        if existing_movie_data
        else False,
        "date_added": ctime,
        "runtime": movie_metadata["runtime"] or 0,
        "rating": movie_metadata["rating"],
        "genre": movie_metadata["genre"],
        "year": movie_metadata["year"],
        "watched": existing_movie_data.get("watched", False)
        if existing_movie_data
        else False,
        "last_played_position": existing_movie_data.get("last_played_position", 0)
        if existing_movie_data
        else 0,
    }

    if detail_callback:
        detail_callback(
            "finish_file", {"file": str(video_file), "folder": movie_directory.name}
        )

    return movie_data


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

    needs_episode_search = False
    is_locked = bool(series_data.get("metadata", {}).get("locked_metadata", False))
    if not is_locked:
        for episode_file in season_directory.iterdir():
            if (
                episode_file.is_file()
                and episode_file.suffix.lower() in VIDEO_EXTENSIONS
            ):
                if str(episode_file.absolute()) not in existing_episodes_by_path:
                    needs_episode_search = True
                    break

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
    else:
        parsed = _parse_episode_number(episode_name)
        if parsed:
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

    return {
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


def scan_series(
    series_directory: Path,
    tmdb_series: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, dict] | None = None,
    manual_jellyfin_id: str | None = None,
    existing_series_data: Dict[str, Any] | None = None,
    force_refresh: bool = False,
    cleanup: bool = False,
    single_item_refresh: bool = False,
    detail_callback: Any = None,
) -> Dict[str, Any]:
    """
    Scans a single series directory and fetches metadata from TMDB.
    If tmdb_series is provided (e.g. from a manual match), it uses that ID
    instead of searching.
    If manual_jellyfin_id is provided, it links to that Jellyfin item for watch sync.
    """
    series_data, is_early_return, tmdb_series, existing_episodes_by_path = (
        _process_series_metadata(
            series_directory,
            tmdb_series,
            jellyfin_data,
            manual_jellyfin_id,
            existing_series_data,
            force_refresh,
            cleanup,
            single_item_refresh,
        )
    )
    if is_early_return:
        return series_data

    for season_directory in series_directory.iterdir():
        if not season_directory.is_dir() or season_directory.name.startswith("."):
            continue

        season_name, season_index, season_metadata, tmdb_episodes = (
            _process_season_metadata(
                season_directory,
                series_data,
                existing_series_data,
                existing_episodes_by_path,
                single_item_refresh,
            )
        )

        if detail_callback:
            detail_callback(
                "start_season",
                {"folder": series_directory.name, "season": season_name},
            )

        series_data["seasons"][season_name] = {
            "metadata": season_metadata,
            "episodes": [],
            "_tmdb_episodes": tmdb_episodes,
        }

        for episode_file in season_directory.iterdir():
            if (
                episode_file.is_file()
                and episode_file.suffix.lower() in VIDEO_EXTENSIONS
            ):
                if detail_callback:
                    detail_callback(
                        "start_file",
                        {
                            "file": str(episode_file),
                            "folder": series_directory.name,
                            "season": season_name,
                        },
                    )
                episode_record = _process_episode_file(
                    episode_file,
                    season_name,
                    series_directory,
                    series_data,
                    season_metadata,
                    tmdb_episodes,
                    tmdb_series,
                    jellyfin_data,
                    existing_episodes_by_path,
                )
                series_data["seasons"][season_name]["episodes"].append(episode_record)
                if detail_callback:
                    detail_callback(
                        "finish_file",
                        {
                            "file": str(episode_file),
                            "folder": series_directory.name,
                            "season": season_name,
                        },
                    )

        if detail_callback:
            detail_callback(
                "finish_season",
                {"folder": series_directory.name, "season": season_name},
            )

    if not cleanup and existing_series_data:
        for old_season_name, old_season_data in existing_series_data.get(
            "seasons", {}
        ).items():
            if old_season_name not in series_data["seasons"]:
                logger.info(
                    f"Preserving missing season folder '{old_season_name}' (non-destructive)"
                )
                series_data["seasons"][old_season_name] = old_season_data
            else:
                found_paths = {
                    episode["path"]
                    for episode in series_data["seasons"][old_season_name]["episodes"]
                }
                for old_episode in old_season_data.get("episodes", []):
                    if old_episode["path"] not in found_paths:
                        logger.info(
                            f"Preserving missing episode file '{old_episode['name']}' (non-destructive)"
                        )
                        series_data["seasons"][old_season_name]["episodes"].append(
                            old_episode
                        )
                series_data["seasons"][old_season_name]["episodes"].sort(
                    key=lambda x: natural_sort_key(x["name"])
                )

    logger.info(
        f"Completed scan for series '{series_directory.name}', found {len(series_data['seasons'])} seasons."
    )
    return series_data
