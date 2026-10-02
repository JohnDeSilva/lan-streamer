"""Playback watch-event routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Path, status

from scan_agent.api.deps import get_database_session
from scan_agent.api.schemas import WatchEventWrite
from scan_agent.db.repository import (
    get_watch_state,
    list_watch_events,
    record_watch_event,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

watch_router = APIRouter(tags=["watch"])


@watch_router.get("/watch/{media_type}/{media_identifier}/state")
def watch_state(
    media_type: str = Path(pattern="^(episode|movie)$"),
    media_identifier: int = Path(ge=1),
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Return cumulative watch state for an episode or movie."""
    return get_watch_state(session, media_type, media_identifier)


@watch_router.get("/watch/{media_type}/{media_identifier}/events")
def watch_events(
    media_type: str = Path(pattern="^(episode|movie)$"),
    media_identifier: int = Path(ge=1),
    session: Session = Depends(get_database_session),
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return recent watch events for an episode or movie."""
    return list_watch_events(
        session, media_type, media_identifier, limit=max(1, min(limit, 200))
    )


@watch_router.post("/watch/events", status_code=status.HTTP_201_CREATED)
def create_watch_event(
    event: WatchEventWrite,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Record a playback event and update the watched state."""
    return record_watch_event(
        session,
        event.media_type,
        media_identifier=event.media_id,
        event=event.event,
        position_seconds=event.position_seconds,
        client_id=event.client_id,
        path=event.path,
        watched=event.watched,
    )


@watch_router.post("/watch/sync")
def sync_watch_events(
    events: list[WatchEventWrite],
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Bulk update or sync watch events from a desktop client."""
    updated_count = 0
    for event_item in events:
        record_watch_event(
            session,
            event_item.media_type,
            media_identifier=event_item.media_id,
            event=event_item.event,
            position_seconds=event_item.position_seconds,
            client_id=event_item.client_id,
            path=event_item.path,
            watched=event_item.watched,
        )
        updated_count += 1
    return {"status": "synced", "updated_count": updated_count}
