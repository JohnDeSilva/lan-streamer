"""Health, configuration, and library management routes."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from scan_agent.api.deps import get_database_session
from scan_agent.api.schemas import ConfigUpdate, LibraryPatch, LibraryWrite
from scan_agent.config import apply_agent_log_level
from scan_agent.db.repository import (
    count_items_per_library,
    get_library,
    load_library_dict,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from scan_agent.config import AgentConfig

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])
config_router = APIRouter(tags=["config"])
libraries_router = APIRouter(tags=["libraries"])
sources_router = APIRouter(tags=["sources"])

_MASKED_PASSWORD = "*****"
_LIBRARY_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slugify_library_identifier(name: str) -> str:
    """Derive a stable config key from a library name."""
    return _LIBRARY_SLUG_RE.sub("_", name.strip().lower()).strip("_") or "library"


def _serialize_config(config: AgentConfig) -> dict[str, Any]:
    """Return the config with the subtitle password masked for display."""
    return {
        "tmdb_api_key": config.tmdb_api_key,
        "scan_concurrency": config.scan_concurrency,
        "opensubtitles_api_key": config.opensubtitles_api_key,
        "opensubtitles_username": config.opensubtitles_username,
        "opensubtitles_password": (
            _MASKED_PASSWORD if config.opensubtitles_password else ""
        ),
        "myanimelist_client_id": config.myanimelist_client_id,
        "myanimelist_client_secret": (
            _MASKED_PASSWORD if config.myanimelist_client_secret else ""
        ),
        "myanimelist_authenticated": bool(config.myanimelist_access_token.strip()),
        "database_path": config.database_path,
        "log_directory": config.log_directory,
        "cache_directory": config.cache_directory,
        "log_level": config.log_level,
        "sources": config.sources,
        "libraries": config.libraries,
        "scheduled_scan_enabled": config.scheduled_scan_enabled,
        "scheduled_scan_interval_hours": config.scheduled_scan_interval_hours,
        "filesystem_watching_enabled": config.filesystem_watching_enabled,
        "filesystem_watching_debounce_seconds": config.filesystem_watching_debounce_seconds,
    }


@health_router.get("/health")
def health(request: Request) -> dict[str, Any]:
    """Report process health and provider configuration state."""
    config = request.app.state.agent_config
    tmdb_configured = False
    try:
        from lan_streamer.services.metadata_series import tmdb_client

        tmdb_configured = bool(tmdb_client.is_configured())
    except ImportError, AttributeError, RuntimeError:
        tmdb_configured = False
    return {
        "status": "ok",
        "version": "0.1.0",
        "tmdb_configured": tmdb_configured,
        "database": config.database_path,
        "sources": len(config.sources),
        "libraries": len(config.libraries),
    }


@config_router.get("/config")
def read_config(request: Request) -> dict[str, Any]:
    """Return the current agent configuration (password masked)."""
    return _serialize_config(request.app.state.agent_config)


@config_router.put("/config")
def update_config(request: Request, update: ConfigUpdate) -> dict[str, Any]:
    """Update selectable config keys and persist them."""
    config = request.app.state.agent_config
    changes = update.model_dump(exclude_unset=True)
    if changes.get("clear_opensubtitles_password"):
        config.set("opensubtitles_password", "")
        changes.pop("clear_opensubtitles_password", None)
        logger.info("OpenSubtitles password cleared via API")
    password = changes.get("opensubtitles_password")
    if password in (None, "", _MASKED_PASSWORD):
        changes.pop("opensubtitles_password", None)
    if changes.get("clear_myanimelist_client_secret"):
        config.set("myanimelist_client_secret", "")
        changes.pop("clear_myanimelist_client_secret", None)
        logger.info("MyAnimeList client secret cleared via API")
    mal_secret = changes.get("myanimelist_client_secret")
    if mal_secret in (None, "", _MASKED_PASSWORD):
        changes.pop("myanimelist_client_secret", None)
    for key, value in changes.items():
        config.set(key, value)
        if key == "log_level" and isinstance(value, str):
            apply_agent_log_level(value)
        logger.info("API config key '%s' updated", key)
    return _serialize_config(config)


def _normalize_source_roots(entry: dict[str, Any]) -> None:
    """Ensure *entry* has synchronized ``root_path`` and ``root_paths`` fields."""
    cleaned_roots: list[str] = []
    for raw_path in entry.get("root_paths") or []:
        stripped = str(raw_path).strip()
        if stripped and stripped not in cleaned_roots:
            cleaned_roots.append(stripped)
    primary = str(entry.get("root_path") or "").strip()
    if primary and primary not in cleaned_roots:
        cleaned_roots.insert(0, primary)
    if cleaned_roots:
        entry["root_paths"] = cleaned_roots
        entry["root_path"] = cleaned_roots[0]


def _list_sources(
    request: Request,
    session: Session,
) -> list[dict[str, Any]]:
    config = request.app.state.agent_config
    counts_by_name = count_items_per_library(session)
    result: list[dict[str, Any]] = []
    for identifier, definition in config.sources.items():
        entry = dict(definition)
        _normalize_source_roots(entry)
        entry["id"] = identifier
        entry["counts"] = counts_by_name.get(
            str(definition.get("name", "")),
            {"series": 0, "movies": 0, "episodes": 0},
        )
        result.append(entry)
    return result


@sources_router.get("/sources")
def list_sources(
    request: Request,
    session: Session = Depends(get_database_session),
) -> list[dict[str, Any]]:
    """Return configured media sources augmented with database item counts."""
    return _list_sources(request, session)


@libraries_router.get("/libraries")
def list_libraries(
    request: Request,
    session: Session = Depends(get_database_session),
) -> list[dict[str, Any]]:
    """Return configured libraries augmented with database item counts (legacy alias)."""
    return _list_sources(request, session)


def _create_source(
    request: Request,
    source: LibraryWrite,
    session: Session,
) -> dict[str, Any]:
    config = request.app.state.agent_config
    identifier = _slugify_library_identifier(source.name)
    config.sources[identifier] = {
        "name": source.name,
        "media_type": source.media_type,
        "root_path": source.root_path,
        "root_paths": list(
            source.root_paths or ([source.root_path] if source.root_path else [])
        ),
        "enabled": source.enabled,
    }
    config.save()
    logger.info("API created media source '%s' at %s", source.name, source.root_path)
    entry = dict(config.sources[identifier])
    entry["id"] = identifier
    entry["counts"] = count_items_per_library(session).get(
        source.name, {"series": 0, "movies": 0, "episodes": 0}
    )
    return entry


@sources_router.post("/sources", status_code=status.HTTP_201_CREATED)
def create_source(
    request: Request,
    source: LibraryWrite,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Create or replace a media source definition in the agent config."""
    return _create_source(request, source, session)


@libraries_router.post("/libraries", status_code=status.HTTP_201_CREATED)
def create_library(
    request: Request,
    library: LibraryWrite,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Create or replace a library definition in the agent config (legacy alias)."""
    return _create_source(request, library, session)


def _update_source(
    request: Request,
    identifier: str,
    patch: LibraryPatch,
) -> dict[str, Any]:
    config = request.app.state.agent_config
    if identifier not in config.sources:
        raise HTTPException(status_code=404, detail="Unknown source identifier")
    merged = dict(config.sources[identifier])
    updates = patch.model_dump(exclude_unset=True)
    if "root_paths" in updates and updates["root_paths"] is not None:
        cleaned = [
            str(raw_path).strip()
            for raw_path in updates["root_paths"]
            if str(raw_path).strip()
        ]
        if not cleaned:
            raise HTTPException(
                status_code=422, detail="root_paths must contain at least one path"
            )
        updates["root_paths"] = list(dict.fromkeys(cleaned))
        if "root_path" not in updates or not updates["root_path"]:
            updates["root_path"] = updates["root_paths"][0]
    elif updates.get("root_path"):
        updates["root_path"] = str(updates["root_path"]).strip()
        updates["root_paths"] = [updates["root_path"]]
    merged.update(updates)
    _normalize_source_roots(merged)
    config.sources[identifier] = merged
    config.save()
    logger.info("API updated media source '%s'", identifier)
    entry = dict(config.sources[identifier])
    entry["id"] = identifier
    return entry


@sources_router.patch("/sources/{source_identifier}")
def update_source(
    request: Request,
    source_identifier: str,
    patch: LibraryPatch,
) -> dict[str, Any]:
    """Partially update a media source definition."""
    return _update_source(request, source_identifier, patch)


@libraries_router.patch("/libraries/{library_identifier}")
def update_library(
    request: Request,
    library_identifier: str,
    patch: LibraryPatch,
) -> dict[str, Any]:
    """Partially update a library definition (legacy alias)."""
    return _update_source(request, library_identifier, patch)


def _delete_source(
    request: Request,
    identifier: str,
) -> None:
    config = request.app.state.agent_config
    if identifier not in config.sources:
        raise HTTPException(status_code=404, detail="Unknown source identifier")
    deleted = config.sources.pop(identifier)
    config.save()
    logger.info("API removed media source '%s' (%s)", deleted.get("name"), identifier)


@sources_router.delete(
    "/sources/{source_identifier}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_source(request: Request, source_identifier: str) -> None:
    """Remove a media source definition from the agent config."""
    _delete_source(request, source_identifier)


@libraries_router.delete(
    "/libraries/{library_identifier}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_library(request: Request, library_identifier: str) -> None:
    """Remove a library definition from the agent config (legacy alias)."""
    _delete_source(request, library_identifier)


def _export_source_items(
    request: Request,
    identifier: str,
    session: Session,
) -> dict[str, Any]:
    agent_config = request.app.state.agent_config
    source_name = identifier
    if identifier in agent_config.sources:
        source_name = agent_config.sources[identifier].get("name", identifier)
    forwarded_client = request.headers.get("x-forwarded-for")
    if forwarded_client:
        client_address = forwarded_client.split(",")[0].strip()
    elif request.client and request.client.host:
        client_address = request.client.host
    else:
        client_address = "unknown"

    library_row = get_library(session, source_name)
    if library_row is None and identifier != source_name:
        library_row = get_library(session, identifier)
    if library_row is None:
        if identifier in agent_config.sources or any(
            configured_source.get("name") == source_name
            for configured_source in agent_config.sources.values()
        ):
            logger.info(
                "Desktop sync: client '%s' requested unscanned source '%s' (served 0 items)",
                client_address,
                source_name,
            )
            return {}
        raise HTTPException(status_code=404, detail="Unknown source identifier")
    items = load_library_dict(session, library_row.id)
    logger.info(
        "Desktop sync: exporting %d items for media source '%s' (%s) to client '%s'",
        len(items),
        source_name,
        identifier,
        client_address,
    )
    return items


@sources_router.get("/sources/{source_identifier}/items")
def export_source_items(
    request: Request,
    source_identifier: str,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Return full scanner-shaped source items dict for desktop sync."""
    return _export_source_items(request, source_identifier, session)


@libraries_router.get("/libraries/{library_identifier}/items")
def export_library_items(
    request: Request,
    library_identifier: str,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Return full scanner-shaped library items dict for desktop sync (legacy alias)."""
    return _export_source_items(request, library_identifier, session)
