"""Scan orchestration routes and the SSE event stream."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from scan_agent.api.deps import get_database_session
from scan_agent.api.schemas import ScanRequest
from scan_agent.db.repository import list_scan_jobs
from scan_agent.db.serializers import scan_job_to_dict

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from scan_agent.scan.progress import ProgressBroker

logger = logging.getLogger(__name__)

scan_router = APIRouter(tags=["scan"])
events_router = APIRouter(tags=["events"])

_PING_INTERVAL_SECONDS = 15.0


def _format_sse_event(message: dict[str, Any]) -> str:
    """Render one broker message as a Server-Sent Events frame."""
    payload_dict = dict(message.get("payload", {}))
    payload_dict.setdefault("sequence", message["sequence"])
    payload = json.dumps(payload_dict, default=str)
    return f"id: {message['sequence']}\nevent: {message['event']}\ndata: {payload}\n\n"


@scan_router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
def start_scan(request: Request, payload: ScanRequest) -> dict[str, Any]:
    """Start a scan for one library or all libraries."""
    orchestrator = request.app.state.orchestrator
    try:
        job = orchestrator.start_scan(
            library_identifier=payload.library_id,
            pass_number=payload.pass_number,
            force_refresh=payload.force_refresh,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    logger.info(
        "API started scan job %s (library=%s pass=%s)",
        job.id,
        payload.library_id,
        payload.pass_number,
    )
    return {"job": scan_job_to_dict(job)}


@scan_router.get("/scan/status")
def scan_status(request: Request) -> dict[str, Any]:
    """Return the current running scan and the last finished job."""
    return request.app.state.orchestrator.status()


@scan_router.post("/scan/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_scan(request: Request) -> dict[str, str]:
    """Request cancellation of the running scan (idempotent)."""
    request.app.state.orchestrator.cancel()
    return {"status": "cancellation_requested"}


@scan_router.get("/scan/jobs")
def scan_jobs(
    session: Session = Depends(get_database_session),
    limit: int = Query(default=20, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Return recent scan jobs, newest first."""
    return list_scan_jobs(session, limit=limit)


@events_router.get("/events")
async def events_stream(
    request: Request,
    sequence: int | None = Query(default=None, ge=0),
) -> Any:
    """Stream scan progress/log events over Server-Sent Events.

    *sequence* (or the ``Last-Event-ID`` header value) resumes history after
    the given sequence number. With ``until_finished=1`` the stream ends once
    a ``scan.finished`` event is delivered.
    """
    broker: ProgressBroker = request.app.state.progress_broker
    last_sequence = sequence if sequence is not None else 0
    last_event_id = request.headers.get("last-event-id")
    if last_event_id is not None:
        try:
            last_sequence = int(last_event_id)
        except ValueError, TypeError:
            last_sequence = 0
    end_on_finished = request.query_params.get("until_finished", "0") == "1"

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def _enqueue(message: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, message)

    subscription_id = broker.subscribe(_enqueue)

    async def _event_generator() -> Any:
        nonlocal last_sequence
        try:
            for message in broker.pending_since(last_sequence):
                last_sequence = message["sequence"]
                yield _format_sse_event(message)
                if end_on_finished and message["event"] == "scan.finished":
                    return

            while True:
                if await request.is_disconnected():
                    return
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue

                if message["sequence"] > last_sequence:
                    last_sequence = message["sequence"]
                    yield _format_sse_event(message)
                    if end_on_finished and message["event"] == "scan.finished":
                        return
        finally:
            broker.unsubscribe(subscription_id)

    from fastapi.responses import StreamingResponse

    return StreamingResponse(_event_generator(), media_type="text/event-stream")
