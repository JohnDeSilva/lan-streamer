"""Shared FastAPI dependencies for the agent API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from scan_agent.db.connection import get_session

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

    from scan_agent.scan.progress import ProgressBroker


def get_database_session(request: Request) -> Iterator[Session]:
    """Yield a database session bound to the app's engine for the request."""
    with get_session(request.app.state.engine) as session:
        yield session


def get_progress_broker(request: Request) -> ProgressBroker:
    """Return the progress and event broker singleton."""
    return request.app.state.progress_broker
