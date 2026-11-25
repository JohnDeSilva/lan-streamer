"""Playback watch-event routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Path, status

from scan_agent.api.deps import get_database_session, get_progress_broker
from scan_agent.api.schemas import WatchEventWrite
from scan_agent.db.repository import (
    get_watch_state,
    list_watch_events,
    record_watch_event,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from scan_agent.scan.progress import ProgressBroker

watch_router = APIRouter(tags=["watch"])


def _dispatch_mal_updates(result: dict[str, Any]) -> None:
    """Trigger background MyAnimeList status updates for watched items if configured."""
    mal_updates = result.pop("mal_updates", None)
    if not isinstance(mal_updates, dict) or not mal_updates:
        return
    try:
        from lan_streamer.providers.myanimelist import trigger_mal_push_async

        for anime_id, watched_episodes in mal_updates.items():
            trigger_mal_push_async(int(anime_id), int(watched_episodes))
    except ImportError, RuntimeError, ValueError, TypeError:
        return


@watch_router.get("/watch/{media_type}/{media_identifier}/state")
def watch_state(
    media_type: str = Path(pattern="^(episode|movie|season|series)$"),
    media_identifier: int = Path(ge=1),
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Return cumulative watch state for an episode, movie, season, or series."""
    return get_watch_state(session, media_type, media_identifier)


@watch_router.get("/watch/{media_type}/{media_identifier}/events")
def watch_events(
    media_type: str = Path(pattern="^(episode|movie|season|series)$"),
    media_identifier: int = Path(ge=1),
    session: Session = Depends(get_database_session),
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return recent watch events for a media item."""
    return list_watch_events(
        session, media_type, media_identifier, limit=max(1, min(limit, 200))
    )


@watch_router.post("/watch/events", status_code=status.HTTP_201_CREATED)
def create_watch_event(
    event: WatchEventWrite,
    session: Session = Depends(get_database_session),
    progress_broker: ProgressBroker = Depends(get_progress_broker),
) -> dict[str, Any]:
    """Record a playback event and update the watched state."""
    result = record_watch_event(
        session,
        event.media_type,
        media_identifier=event.media_id,
        event=event.event,
        position_seconds=event.position_seconds,
        client_id=event.client_id,
        path=event.path,
        watched=event.watched,
    )
    _dispatch_mal_updates(result)
    progress_broker.publish("watch.updated", result)
    affected_episodes = result.get("affected_episodes")
    if isinstance(affected_episodes, list):
        for affected_episode in affected_episodes:
            if isinstance(affected_episode, dict):
                progress_broker.publish(
                    "watch.updated",
                    {
                        "media_type": "episode",
                        "media_id": affected_episode.get("id"),
                        "path": affected_episode.get("path"),
                        "watched": affected_episode.get("watched"),
                        "last_played_at": affected_episode.get("last_played_at"),
                        "position_seconds": affected_episode.get(
                            "resume_position_seconds"
                        ),
                        "client_id": event.client_id,
                    },
                )
    return result


@watch_router.post("/watch/sync")
def sync_watch_events(
    events: list[WatchEventWrite],
    session: Session = Depends(get_database_session),
    progress_broker: ProgressBroker = Depends(get_progress_broker),
) -> dict[str, Any]:
    """Bulk update or sync watch events from a desktop client."""
    updated_count = 0
    coalesced_mal_updates: dict[int, int] = {}
    for event_item in events:
        result = record_watch_event(
            session,
            event_item.media_type,
            media_identifier=event_item.media_id,
            event=event_item.event,
            position_seconds=event_item.position_seconds,
            client_id=event_item.client_id,
            path=event_item.path,
            watched=event_item.watched,
        )
        mal_updates = result.pop("mal_updates", None)
        if isinstance(mal_updates, dict):
            for anime_id, watched_episodes in mal_updates.items():
                parsed_id = int(anime_id)
                parsed_count = int(watched_episodes)
                if parsed_count > coalesced_mal_updates.get(parsed_id, 0):
                    coalesced_mal_updates[parsed_id] = parsed_count
        progress_broker.publish("watch.updated", result)
        updated_count += 1
    if coalesced_mal_updates:
        _dispatch_mal_updates({"mal_updates": coalesced_mal_updates})
    return {"status": "synced", "updated_count": updated_count}
