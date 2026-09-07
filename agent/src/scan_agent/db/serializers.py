"""Plain-dict serialization of agent ORM rows for API responses."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scan_agent.db.models import (
        Episode,
        Library,
        MediaFile,
        Movie,
        ScanJob,
        Season,
        Series,
        Subtitle,
        WatchEvent,
    )


def media_file_to_dict(media_file: MediaFile) -> dict[str, Any]:
    """Serialize a single :class:`MediaFile` row."""
    return {
        "id": media_file.id,
        "media_type": media_file.media_type,
        "media_id": media_file.media_id,
        "path": media_file.path,
        "size_bytes": media_file.size_bytes,
        "duration_seconds": media_file.duration_seconds,
        "codec": media_file.codec,
        "resolution": media_file.resolution,
        "container": media_file.container,
        "active": media_file.active,
    }


def episode_to_dict(episode: Episode) -> dict[str, Any]:
    """Serialize an :class:`Episode` row including its media file versions."""
    return {
        "id": episode.id,
        "season_id": episode.season_id,
        "episode_number": episode.episode_number,
        "tmdb_number": episode.tmdb_number,
        "name": episode.name,
        "overview": episode.overview,
        "path": episode.path,
        "runtime_seconds": episode.runtime_seconds,
        "air_date": episode.air_date,
        "is_missing": episode.is_missing,
        "watched": episode.watched,
        "last_played_at": episode.last_played_at,
        "resume_position_seconds": episode.resume_position_seconds,
        "versions": [media_file_to_dict(mf) for mf in episode.media_files],
    }


def season_to_dict(season: Season, include_episodes: bool = True) -> dict[str, Any]:
    """Serialize a :class:`Season` row, optionally with nested episodes."""
    result: dict[str, Any] = {
        "id": season.id,
        "series_id": season.series_id,
        "season_number": season.season_number,
        "name": season.name,
        "overview": season.overview,
        "poster_path": season.poster_path,
        "tmdb_identifier": season.tmdb_identifier,
        "air_date": season.air_date,
        "watched_episode_count": season.watched_episode_count,
        "episode_count": season.episode_count,
    }
    if include_episodes:
        result["episodes"] = [episode_to_dict(episode) for episode in season.episodes]
    return result


def series_to_dict(series: Series, include_seasons: bool = True) -> dict[str, Any]:
    """Serialize a :class:`Series` row, optionally with nested seasons."""
    result: dict[str, Any] = {
        "id": series.id,
        "library_id": series.library_id,
        "folder_name": series.folder_name,
        "name": series.name,
        "overview": series.overview,
        "poster_path": series.poster_path,
        "backdrop_path": series.backdrop_path,
        "tmdb_identifier": series.tmdb_identifier,
        "year": series.year,
        "status": series.status,
        "air_date_first": series.air_date_first,
        "air_date_last": series.air_date_last,
        "locked_metadata": series.locked_metadata,
        "last_modified": series.last_modified,
        "date_added": series.date_added,
        "watched_count": series.watched_count,
        "path": series.path,
    }
    if include_seasons:
        result["seasons"] = [season_to_dict(season) for season in series.seasons]
    return result


def movie_to_dict(movie: Movie) -> dict[str, Any]:
    """Serialize a :class:`Movie` row including its media file versions."""
    return {
        "id": movie.id,
        "library_id": movie.library_id,
        "folder_name": movie.folder_name,
        "name": movie.name,
        "overview": movie.overview,
        "poster_path": movie.poster_path,
        "backdrop_path": movie.backdrop_path,
        "tmdb_identifier": movie.tmdb_identifier,
        "year": movie.year,
        "runtime_seconds": movie.runtime_seconds,
        "path": movie.path,
        "locked_metadata": movie.locked_metadata,
        "last_modified": movie.last_modified,
        "date_added": movie.date_added,
        "watched": movie.watched,
        "last_played_at": movie.last_played_at,
        "resume_position_seconds": movie.resume_position_seconds,
        "versions": [media_file_to_dict(mf) for mf in movie.media_files],
    }


def library_to_dict(library: Library) -> dict[str, Any]:
    """Serialize a :class:`Library` row."""
    return {
        "id": library.id,
        "name": library.name,
        "media_type": library.media_type,
        "root_path": library.root_path,
        "enabled": library.enabled,
        "sort_order": library.sort_order,
    }


def scan_job_to_dict(scan_job: ScanJob) -> dict[str, Any]:
    """Serialize a :class:`ScanJob` row."""
    return {
        "id": scan_job.id,
        "library_id": scan_job.library_id,
        "pass_number": scan_job.pass_number,
        "status": scan_job.status,
        "started_at": scan_job.started_at,
        "finished_at": scan_job.finished_at,
        "stats_json": scan_job.stats_json,
        "error_text": scan_job.error_text,
    }


def subtitle_to_dict(subtitle: Subtitle) -> dict[str, Any]:
    """Serialize a :class:`Subtitle` row."""
    return {
        "id": subtitle.id,
        "media_type": subtitle.media_type,
        "media_id": subtitle.media_id,
        "path": subtitle.path,
        "language": subtitle.language,
        "forced": subtitle.forced,
        "default": subtitle.default,
        "provider": subtitle.provider,
        "downloaded_at": subtitle.downloaded_at,
    }


def watch_event_to_dict(watch_event: WatchEvent) -> dict[str, Any]:
    """Serialize a :class:`WatchEvent` row."""
    return {
        "id": watch_event.id,
        "media_type": watch_event.media_type,
        "media_id": watch_event.media_id,
        "event": watch_event.event,
        "position_seconds": watch_event.position_seconds,
        "client_id": watch_event.client_id,
        "timestamp": watch_event.timestamp,
    }
