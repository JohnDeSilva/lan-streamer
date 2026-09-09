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
        "database_path": config.database_path,
        "log_directory": config.log_directory,
        "cache_directory": config.cache_directory,
        "log_level": config.log_level,
        "libraries": config.libraries,
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
    password = changes.get("opensubtitles_password")
    if password in (None, "", _MASKED_PASSWORD):
        changes.pop("opensubtitles_password", None)
    for key, value in changes.items():
        config.set(key, value)
        if key == "log_level" and isinstance(value, str):
            apply_agent_log_level(value)
        logger.info("API config key '%s' updated", key)
    return _serialize_config(config)


@libraries_router.get("/libraries")
def list_libraries(
    request: Request,
    session: Session = Depends(get_database_session),
) -> list[dict[str, Any]]:
    """Return configured libraries augmented with database item counts."""
    config = request.app.state.agent_config
    counts_by_name = count_items_per_library(session)
    result: list[dict[str, Any]] = []
    for identifier, definition in config.libraries.items():
        entry = dict(definition)
        entry["id"] = identifier
        entry["counts"] = counts_by_name.get(
            str(definition.get("name", "")),
            {"series": 0, "movies": 0, "episodes": 0},
        )
        result.append(entry)
    return result


@libraries_router.post("/libraries", status_code=status.HTTP_201_CREATED)
def create_library(
    request: Request,
    library: LibraryWrite,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Create or replace a library definition in the agent config."""
    config = request.app.state.agent_config
    identifier = _slugify_library_identifier(library.name)
    config.libraries[identifier] = {
        "name": library.name,
        "media_type": library.media_type,
        "root_path": library.root_path,
        "enabled": library.enabled,
    }
    config.save()
    logger.info("API created library '%s' at %s", library.name, library.root_path)
    entry = dict(config.libraries[identifier])
    entry["id"] = identifier
    entry["counts"] = count_items_per_library(session).get(
        library.name, {"series": 0, "movies": 0, "episodes": 0}
    )
    return entry


@libraries_router.patch("/libraries/{library_identifier}")
def update_library(
    request: Request,
    library_identifier: str,
    patch: LibraryPatch,
) -> dict[str, Any]:
    """Partially update a library definition."""
    config = request.app.state.agent_config
    if library_identifier not in config.libraries:
        raise HTTPException(status_code=404, detail="Unknown library identifier")
    merged = dict(config.libraries[library_identifier])
    merged.update(patch.model_dump(exclude_unset=True))
    config.libraries[library_identifier] = merged
    config.save()
    logger.info("API updated library '%s'", library_identifier)
    entry = dict(config.libraries[library_identifier])
    entry["id"] = library_identifier
    return entry


@libraries_router.delete(
    "/libraries/{library_identifier}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_library(request: Request, library_identifier: str) -> None:
    """Remove a library definition from the agent config."""
    config = request.app.state.agent_config
    if library_identifier not in config.libraries:
        raise HTTPException(status_code=404, detail="Unknown library identifier")
    deleted = config.libraries.pop(library_identifier)
    config.save()
    logger.info(
        "API removed library '%s' (%s)", deleted.get("name"), library_identifier
    )


@libraries_router.get("/libraries/{library_identifier}/items")
def export_library_items(
    request: Request,
    library_identifier: str,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Return full scanner-shaped library items dict for desktop sync."""
    agent_config = request.app.state.agent_config
    library_name = library_identifier
    if library_identifier in agent_config.libraries:
        library_name = agent_config.libraries[library_identifier].get(
            "name", library_identifier
        )
    forwarded_client = request.headers.get("x-forwarded-for")
    if forwarded_client:
        client_address = forwarded_client.split(",")[0].strip()
    elif request.client and request.client.host:
        client_address = request.client.host
    else:
        client_address = "unknown"

    library_row = get_library(session, library_name)
    if library_row is None and library_identifier != library_name:
        library_row = get_library(session, library_identifier)
    if library_row is None:
        if library_identifier in agent_config.libraries or any(
            configured_library.get("name") == library_name
            for configured_library in agent_config.libraries.values()
        ):
            logger.info(
                "Desktop sync: client '%s' requested unscanned library '%s' (served 0 items)",
                client_address,
                library_name,
            )
            return {}
        raise HTTPException(status_code=404, detail="Unknown library identifier")
    items = load_library_dict(session, library_row.id)
    logger.info(
        "Desktop sync: exporting %d items for library '%s' (%s) to client '%s'",
        len(items),
        library_name,
        library_identifier,
        client_address,
    )
    return items
