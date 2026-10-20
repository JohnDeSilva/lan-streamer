"""Scan orchestration routes and the SSE event stream."""

from __future__ import annotations

import asyncio
import contextlib
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


def _put_message_on_queue(
    queue: asyncio.Queue[dict[str, Any]], message: dict[str, Any]
) -> None:
    """Push a broker message onto the SSE client's bounded queue.

    Drops the oldest event when the consumer is behind so a slow or
    disconnected SSE client cannot accumulate an unbounded backlog.
    """
    if queue.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            queue.get_nowait()
    with contextlib.suppress(asyncio.QueueFull):
        queue.put_nowait(message)


def _enqueue_after_loop_close_safe(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[dict[str, Any]],
    message: dict[str, Any],
) -> None:
    """Schedule *message* onto *queue* from any thread, ignoring closed loops."""
    with contextlib.suppress(RuntimeError):
        # Event loop already closed (client disconnected) — ignore.
        loop.call_soon_threadsafe(_put_message_on_queue, queue, message)


@scan_router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
def start_scan(request: Request, payload: ScanRequest) -> dict[str, Any]:
    """Start a scan for one media source / library or all."""
    orchestrator = request.app.state.orchestrator
    try:
        job = orchestrator.start_scan(
            source_identifier=payload.target_identifier,
            pass_number=payload.pass_number,
            force_refresh=payload.force_refresh,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    logger.info(
        "API started scan job %s (target=%s pass=%s)",
        job.id,
        payload.target_identifier,
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


LOG_LEVEL_PRIORITIES: dict[str, int] = {
    "ALL": 0,
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


@scan_router.get("/scan/logs")
def get_scan_logs(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    level: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Return recent scan log entries, newest last."""
    broker: ProgressBroker = request.app.state.progress_broker
    log_entries: list[dict[str, Any]] = []
    level_threshold = 0
    if level:
        level_threshold = LOG_LEVEL_PRIORITIES.get(level.strip().upper(), 0)
    for message in broker.pending_since(0):
        if message.get("event") == "scan.log":
            payload_dict = dict(message.get("payload", {}))
            payload_dict.setdefault("sequence", message.get("sequence"))
            entry_level_name = str(payload_dict.get("level", "INFO")).upper()
            entry_level_value = LOG_LEVEL_PRIORITIES.get(entry_level_name, 20)
            if entry_level_value >= level_threshold:
                log_entries.append(payload_dict)
    if limit and len(log_entries) > limit:
        log_entries = log_entries[-limit:]
    return log_entries


@events_router.get("/events")
async def events_stream(
    request: Request,
    sequence: int | None = Query(default=None, ge=0),
) -> Any:
    """Stream scan progress/log events over Server-Sent Events.

    *sequence* (or the ``Last-Event-ID`` header value) resumes history after
    the given sequence number. With ``live=1`` and no explicit *sequence* or
    ``Last-Event-ID``, the stream starts at the broker's latest sequence so
    only newly published events are delivered (no history replay). With
    ``until_finished=1`` the stream ends once a ``scan.finished`` event is
    delivered. If the resume point predates the broker's retained history, a
    synthetic ``stream.gap`` event is emitted before the retained tail so the
    client can detect dropped events.
    """
    broker: ProgressBroker = request.app.state.progress_broker
    last_sequence = sequence if sequence is not None else 0
    last_event_id = request.headers.get("last-event-id")
    live_tail_requested = (
        sequence is None
        and last_event_id is None
        and request.query_params.get("live", "0") == "1"
    )
    if last_event_id is not None:
        try:
            last_sequence = int(last_event_id)
        except ValueError, TypeError:
            last_sequence = 0
    elif live_tail_requested:
        # Live-tail handshake: skip replaying buffered history for clients
        # (such as the desktop event listener) that only want new events.
        last_sequence = broker.latest_sequence
    end_on_finished = request.query_params.get("until_finished", "0") == "1"

    # A broker restart resets its sequence to 0. A client that reconnects with
    # a sequence from the previous process would otherwise wait forever because
    # every newly published event carries a lower sequence number.
    latest_sequence = broker.latest_sequence
    if last_sequence > latest_sequence:
        logger.warning(
            "SSE client requested resume after sequence %s but the broker only "
            "reached %s; assuming a broker restart and restarting from the "
            "oldest retained event.",
            last_sequence,
            latest_sequence,
        )
        last_sequence = 0

    # The bounded history may already have dropped events newer than the
    # client's resume point. Tell the client explicitly instead of silently
    # replaying the retained tail.
    oldest_sequence = broker.oldest_sequence
    gap_message: dict[str, Any] | None = None
    if last_sequence < oldest_sequence - 1:
        logger.warning(
            "SSE client requested resume after sequence %s but the oldest "
            "retained event is %s; events were dropped from the bounded "
            "history.",
            last_sequence,
            oldest_sequence,
        )
        gap_message = {
            "sequence": oldest_sequence - 1,
            "event": "stream.gap",
            "payload": {
                "last_sequence": last_sequence,
                "oldest_sequence": oldest_sequence,
                "latest_sequence": broker.latest_sequence,
            },
        }
        # Resume from just before the oldest retained event so the retained
        # history still replays and a reconnect with the gap id does not
        # report the same gap again.
        last_sequence = oldest_sequence - 1

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)

    subscription_id = broker.subscribe(
        lambda message: _enqueue_after_loop_close_safe(loop, queue, message)
    )

    async def _event_generator() -> Any:
        nonlocal last_sequence
        try:
            if live_tail_requested:
                # Hand the client the resume point immediately. Without this a
                # live-tail client that receives no events before a disconnect
                # would reconnect with ``live=1`` again and silently skip
                # everything published while it was away.
                yield f"id: {last_sequence}\n\n"
            if gap_message is not None:
                yield _format_sse_event(gap_message)
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
