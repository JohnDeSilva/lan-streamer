"""
Pass 3 — technical metadata enrichment and missing-file cleanup.

Batch ffprobe scan for episodes/movies with stub (Unknown) technical data and
cleanup of records whose video files no longer exist on disk.  No TMDB calls or
filesystem walking for discovery.
"""

import logging
from pathlib import Path
from typing import Any, Dict

from lan_streamer.scanner.file_property_scanner import get_detailed_file_info

logger = logging.getLogger("lan_streamer.scanner.pass3_technical")

_UPGRADE_FIELDS = (
    "resolution",
    "video_codec",
    "bit_rate",
    "audio_tracks",
    "subtitle_tracks",
    "runtime",
    "size_bytes",
    "video_type",
)


def _upgrade_episode_metadata(
    episode: Dict[str, Any],
    force_refresh: bool,
) -> Dict[str, Any]:
    """Upgrade technical metadata via ffprobe when codec is stub or forced."""
    video_path: str | None = episode.get("path")
    current_codec: str | None = episode.get("video_codec")

    is_stub: bool = current_codec is None or current_codec == "Unknown"

    if (not is_stub and not force_refresh) or not video_path:
        return episode

    file_path = Path(video_path)
    if not file_path.exists():
        logger.warning(
            "Cannot upgrade '%s': file gone at '%s'.",
            episode.get("name", "unknown"),
            video_path,
        )
        return episode

    logger.info(
        "Upgrading technical metadata for '%s' (stub=%s, force=%s).",
        episode.get("name", "unknown"),
        is_stub,
        force_refresh,
    )
    detailed: Dict[str, Any] = get_detailed_file_info(video_path)

    for field in _UPGRADE_FIELDS:
        value = detailed.get(field)
        if value is not None:
            episode[field] = value

    for version in episode.get("versions", []):
        if version.get("path") == video_path:
            for field in _UPGRADE_FIELDS:
                value = detailed.get(field)
                if value is not None:
                    version[field] = value

    return episode


def _handle_missing_file(episode: Dict[str, Any]) -> Dict[str, Any]:
    """Set path to ``None`` when the underlying file no longer exists."""
    video_path: str | None = episode.get("path")
    if not video_path:
        return episode
    if Path(video_path).exists():
        return episode

    logger.warning(
        "Episode '%s' — file gone at '%s'; clearing path.",
        episode.get("name", "unknown"),
        video_path,
    )
    episode["path"] = None
    for version in episode.get("versions", []):
        if version.get("path") == video_path:
            version["path"] = None
    return episode


def _upgrade_orphan_versions(movie_data: Dict[str, Any], movie_name: str) -> None:
    """Upgrade or clean up version entries with a different path than active."""
    active_path: str | None = movie_data.get("path")
    for version in movie_data.get("versions", []):
        version_path: str | None = version.get("path")
        if not version_path or version_path == active_path:
            continue
        version_file = Path(version_path)
        if version_file.exists():
            if version.get("video_codec") == "Unknown":
                detailed = get_detailed_file_info(version_path)
                for field in _UPGRADE_FIELDS:
                    value = detailed.get(field)
                    if value is not None:
                        version[field] = value
        else:
            logger.warning(
                "Orphan version '%s' for '%s' gone; clearing path.",
                version_path,
                movie_name,
            )
            version["path"] = None


def scan_series_pass3(
    series_directory: Path,
    existing_series_data: Dict[str, Any],
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Pass 3 for series — upgrade stubs and mark missing files.

    Args:
        series_directory: Series folder (used for logging context).
        existing_series_data: Series dict with seasons → episodes.
        force_refresh: Re-scan every episode even if codec is known.

    Returns:
        Updated *existing_series_data* (mutated in-place).
    """
    series_name: str = existing_series_data.get("name", series_directory.name)
    logger.info(
        "Pass 3 (technical) for '%s' (force_refresh=%s).",
        series_name,
        force_refresh,
    )

    seasons: Dict[str, Any] = existing_series_data.get("seasons", {})
    for season_data in seasons.values():
        episodes: list[Dict[str, Any]] = season_data.get("episodes", [])
        for index, episode in enumerate(episodes):
            _upgrade_episode_metadata(episode, force_refresh)
            _handle_missing_file(episode)

    logger.info("Pass 3 (technical) finished for '%s'.", series_name)
    return existing_series_data


def scan_movie_pass3(
    series_directory: Path,
    existing_movie_data: Dict[str, Any],
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Pass 3 for movies — upgrade stub and clean missing files.

    Args:
        series_directory: Movie folder (used for logging context).
        existing_movie_data: Movie dictionary.
        force_refresh: Re-scan even if codec is known.

    Returns:
        Updated *existing_movie_data* (mutated in-place).
    """
    movie_name: str = existing_movie_data.get("name", series_directory.name)
    logger.info(
        "Pass 3 (technical) for movie '%s' (force_refresh=%s).",
        movie_name,
        force_refresh,
    )

    _upgrade_episode_metadata(existing_movie_data, force_refresh)
    _handle_missing_file(existing_movie_data)
    _upgrade_orphan_versions(existing_movie_data, movie_name)

    logger.info("Pass 3 (technical) finished for movie '%s'.", movie_name)
    return existing_movie_data
