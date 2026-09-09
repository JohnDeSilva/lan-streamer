"""Metadata search/match, rename, and subtitle routes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from scan_agent.api.deps import get_database_session
from scan_agent.api.schemas import (
    ManualMetadataMappingRequest,
    MetadataMatch,
    RenameRequest,
    SubtitleDownload,
)
from scan_agent.db.repository import (
    add_subtitle,
    apply_manual_metadata_mappings,
    get_episode_media_path,
    get_episode_meta,
    get_movie_media_path,
    get_movie_meta,
    get_rename_source,
    list_subtitles,
    set_movie_metadata_match,
    set_series_metadata_match,
)

if TYPE_CHECKING:
    import pathlib

    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

metadata_router = APIRouter(tags=["metadata"])
rename_router = APIRouter(tags=["rename"])
subtitles_router = APIRouter(tags=["subtitles"])

_DEFAULT_TEMPLATE = (
    "{SeriesTitle} - S{SeasonNumber:02d}E{EpisodeNumber:02d} - {EpisodeTitle}"
)


def _tmdb_client() -> Any:
    """Return the desktop TMDB client singleton (installed by the bridge)."""
    from lan_streamer.providers.tmdb import tmdb_client

    return tmdb_client


def _series_enrichment(tmdb_item: dict[str, Any]) -> dict[str, Any]:
    """Extract display fields from a TMDB series payload."""
    first_air = tmdb_item.get("first_air_date") or ""
    last_air = tmdb_item.get("last_air_date") or ""
    year = None
    if first_air:
        try:
            year = int(first_air[:4])
        except ValueError:
            year = None
    return {
        "name": tmdb_item.get("name"),
        "overview": tmdb_item.get("overview"),
        "poster_path": tmdb_item.get("poster_path"),
        "backdrop_path": tmdb_item.get("backdrop_path"),
        "year": year,
        "status": tmdb_item.get("status"),
        "air_date_first": first_air or None,
        "air_date_last": last_air or None,
    }


def _movie_enrichment(tmdb_item: dict[str, Any]) -> dict[str, Any]:
    """Extract display fields from a TMDB movie payload."""
    release = tmdb_item.get("release_date") or ""
    year = None
    if release:
        try:
            year = int(release[:4])
        except ValueError:
            year = None
    runtime = tmdb_item.get("runtime")
    return {
        "name": tmdb_item.get("title"),
        "overview": tmdb_item.get("overview"),
        "poster_path": tmdb_item.get("poster_path"),
        "backdrop_path": tmdb_item.get("backdrop_path"),
        "year": year,
        "runtime_seconds": int(runtime) * 60 if runtime else None,
    }


@metadata_router.get("/services/metadata/search")
def metadata_search(
    query: str = Query(min_length=1, max_length=200),
    media_type: str | None = Query(default=None, pattern="^(series|movie|tv)$"),
    type_name: str | None = Query(
        default=None, alias="type", pattern="^(series|movie|tv)$"
    ),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Search TMDB for candidate series or movie matches."""
    resolved_media_type = type_name or media_type
    if not resolved_media_type:
        raise HTTPException(
            status_code=422,
            detail="Query parameter 'type' or 'media_type' is required",
        )
    if resolved_media_type == "tv":
        resolved_media_type = "series"
    client = _tmdb_client()
    if not client.is_configured():
        raise HTTPException(status_code=502, detail="TMDB API key is not configured")
    if resolved_media_type == "series":
        matches = client.search_series_full(query, limit=limit)
    else:
        matches = client.search_movie_full(query, limit=limit)
    return {"type": resolved_media_type, "query": query, "matches": matches}


@metadata_router.post(
    "/services/metadata/{media_type}/{media_identifier}/match",
    status_code=status.HTTP_202_ACCEPTED,
)
def metadata_match(
    media_type: str = Path(pattern="^(series|movie|tv)$"),
    media_identifier: int = Path(ge=1),
    payload: MetadataMatch = ...,  # type: ignore[assignment]
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Point a series/movie at a TMDB identifier.

    The series and its episodes are immediately synchronized with the
    matched TMDB metadata, and metadata is locked upon completion.
    """
    resolved_media_type = "series" if media_type == "tv" else media_type
    client = _tmdb_client()
    if not client.is_configured():
        raise HTTPException(status_code=502, detail="TMDB API key is not configured")
    enrichment: dict[str, Any] = {}
    if resolved_media_type == "series":
        details = client.get_series_by_id(payload.tmdb_identifier)
        if details:
            enrichment = _series_enrichment(details)
        result = set_series_metadata_match(
            session,
            media_identifier,
            payload.tmdb_identifier,
            enrichment,
            tmdb_client=client,
            tmdb_details=details,
        )
    elif resolved_media_type == "movie":
        details = client.get_movie_by_id(payload.tmdb_identifier)
        if details:
            enrichment = _movie_enrichment(details)
        result = set_movie_metadata_match(
            session, media_identifier, payload.tmdb_identifier, enrichment
        )
    else:
        raise HTTPException(status_code=400, detail="media_type must be series/movie")
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown media identifier")
    return {
        "status": "accepted",
        "rescan_required": False,
        "media": result,
    }


@metadata_router.get("/services/metadata/tmdb/series/{tmdb_identifier}/seasons")
def tmdb_series_seasons(
    tmdb_identifier: str = Path(min_length=1),
) -> dict[str, Any]:
    """Return TMDB seasons for a series."""
    client = _tmdb_client()
    if not client.is_configured():
        raise HTTPException(status_code=502, detail="TMDB API key is not configured")
    series_details = client.get_series_by_id(tmdb_identifier)
    if not series_details:
        raise HTTPException(status_code=404, detail="TMDB series not found")
    seasons = series_details.get("seasons", [])
    return {"tmdb_identifier": tmdb_identifier, "seasons": seasons}


@metadata_router.get("/services/metadata/tmdb/series/{tmdb_identifier}/episodes")
def tmdb_series_episodes(
    tmdb_identifier: str = Path(min_length=1),
    season_number: int = Query(default=1, ge=0),
) -> dict[str, Any]:
    """Return TMDB episodes for a series and season number."""
    client = _tmdb_client()
    if not client.is_configured():
        raise HTTPException(status_code=502, detail="TMDB API key is not configured")
    try:
        numeric_tmdb_identifier = int(tmdb_identifier)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid TMDB identifier") from None
    episodes = client.get_episodes(numeric_tmdb_identifier, season_number)
    return {
        "tmdb_identifier": tmdb_identifier,
        "season_number": season_number,
        "episodes": episodes or [],
    }


@metadata_router.post("/services/metadata/series/{series_identifier}/manual-map")
def manual_metadata_map(
    series_identifier: int = Path(ge=1),
    payload: ManualMetadataMappingRequest = ...,  # type: ignore[assignment]
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Apply manual episode mappings to a series and lock metadata."""
    updated_series = apply_manual_metadata_mappings(
        session, series_identifier, payload.episode_mappings
    )
    if updated_series is None:
        raise HTTPException(status_code=404, detail="Unknown series identifier")
    return {
        "status": "applied",
        "series": updated_series,
    }


@rename_router.get("/services/rename/preview")
def rename_preview(
    session: Session = Depends(get_database_session),
    media_type: str = Query(default="series", pattern="^(series|movie)$"),
    media_id: int = Query(),
    template: str | None = Query(default=None, max_length=500),
) -> list[dict[str, Any]]:
    """Preview rename operations for a series without touching the disk."""
    if media_type != "series":
        raise HTTPException(
            status_code=501, detail="Movie renames are not supported yet"
        )
    source = get_rename_source(session, "series", media_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Unknown series identifier")
    series_dict, _title = source
    file_template = template or _DEFAULT_TEMPLATE
    from lan_streamer.scanner.renamer import get_rename_preview

    return get_rename_preview(series_dict, file_template)


@rename_router.post("/services/rename/apply")
def rename_apply(
    payload: RenameRequest,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Apply (or dry-run) a rename operation for a series."""
    if payload.media_type != "series":
        raise HTTPException(
            status_code=501, detail="Movie renames are not supported yet"
        )
    source = get_rename_source(session, "series", payload.media_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Unknown series identifier")
    series_dict, _title = source
    file_template = payload.template or _DEFAULT_TEMPLATE
    from lan_streamer.scanner.renamer import (
        get_rename_preview,
        perform_rename,
    )

    previews = get_rename_preview(series_dict, file_template)
    if payload.dry_run:
        return {"dry_run": True, "previews": previews}
    results = perform_rename(previews)
    logger.info(
        "API applied rename for series %s (%s rename attempts)",
        payload.media_id,
        len(results),
    )
    return {"dry_run": False, "results": results}


@subtitles_router.get("/services/subtitles")
def get_subtitles(
    session: Session = Depends(get_database_session),
    media_type: str = Query(pattern="^(episode|movie)$"),
    media_id: int = Query(),
) -> list[dict[str, Any]]:
    """Return stored subtitle entries for an episode or movie."""
    return list_subtitles(session, media_type, media_id)


@subtitles_router.get("/services/subtitles/search")
def search_subtitles(
    session: Session = Depends(get_database_session),
    media_type: str = Query(pattern="^(episode|movie)$"),
    media_id: int = Query(),
    language: str = Query(default="en", max_length=10),
) -> list[dict[str, Any]]:
    """Search OpenSubtitles for an episode/movie by its TMDB identifier."""
    tmdb_identifier, season_number, episode_number, display_name = _subtitle_context(
        session, media_type, media_id
    )
    if tmdb_identifier is None:
        raise HTTPException(status_code=404, detail="Media item has no TMDB identifier")
    from lan_streamer.providers.opensubtitles import (
        OpenSubtitlesClient,
    )

    client = OpenSubtitlesClient()
    numeric_tmdb_identifier = (
        int(tmdb_identifier) if str(tmdb_identifier).isdigit() else None
    )
    results = client.search_subtitles(
        tmdb_id=numeric_tmdb_identifier,
        query=display_name if numeric_tmdb_identifier is None else None,
        season_number=season_number,
        episode_number=episode_number,
        languages=language,
    )
    for result in results:
        result["media_type"] = media_type
        result["media_id"] = media_id
    return results


@subtitles_router.post("/services/subtitles/{file_identifier}/download")
def download_subtitle(
    file_identifier: int,
    payload: SubtitleDownload,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Download a subtitle file next to the media item and store its row."""
    media_path = _media_path(session, payload.media_type, payload.media_id)
    if media_path is None:
        raise HTTPException(status_code=404, detail="Media item has no file on disk")
    from lan_streamer.providers.opensubtitles import (
        OpenSubtitlesClient,
    )

    client = OpenSubtitlesClient()
    if not client.login() and not client.token:
        raise HTTPException(status_code=502, detail="OpenSubtitles login failed")
    download_url = client.get_download_link(file_identifier)
    if download_url is None:
        raise HTTPException(
            status_code=502, detail="OpenSubtitles download link failed"
        )
    content = client.download_subtitle(download_url)
    if not content:
        raise HTTPException(status_code=502, detail="OpenSubtitles download failed")
    subtitle_path = media_path.with_name(f"{media_path.stem}.{payload.language}.srt")
    subtitle_path.write_bytes(content)
    logger.info("API wrote subtitle file %s", subtitle_path)
    return add_subtitle(
        session,
        payload.media_type,
        payload.media_id,
        str(subtitle_path),
        payload.language,
        "opensubtitles",
        forced=payload.forced,
    )


def _subtitle_context(
    session: Session,
    media_type: str,
    media_identifier: int,
) -> tuple[str | None, int | None, int | None, str | None]:
    """Resolve TMDB context needed to search subtitles.

    Returns ``(tmdb_identifier, season_number, episode_number, display_name)``.
    """
    if media_type == "episode":
        return get_episode_meta(session, media_identifier)
    return get_movie_meta(session, media_identifier)


def _media_path(
    session: Session, media_type: str, media_identifier: int
) -> pathlib.Path | None:
    """Return the primary media file Path for an episode or movie."""
    if media_type == "episode":
        return get_episode_media_path(session, media_identifier)
    return get_movie_media_path(session, media_identifier)
