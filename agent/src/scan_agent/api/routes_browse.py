"""Library browsing routes: series, episodes, and movies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from scan_agent.api.deps import get_database_session
from scan_agent.db.repository import (
    get_movie,
    get_series,
    list_episodes,
    list_movies,
    list_series,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

browse_router = APIRouter(tags=["browse"])


@browse_router.get("/library/series")
def browse_series(
    request: Request,
    session: Session = Depends(get_database_session),
    library_id: str | None = Query(default=None),
    library_type: str | None = Query(default=None),
    query: str | None = Query(default=None),
    sort: str = Query(
        default="name",
        pattern="^(name|name_desc|date_added|date_added_desc|year|year_desc)$",
    ),
) -> list[dict[str, Any]]:
    """List series, optionally filtered by library, library type, and query text."""
    sort_column = {
        "name": "name",
        "name_desc": "name",
        "date_added": "date_added",
        "date_added_desc": "date_added",
        "year": "year",
        "year_desc": "year",
    }.get(sort, "name")
    results = list_series(
        connection=session,
        library_identifier=library_id,
        library_type=library_type,
        query=query,
        sort=sort_column,
    )
    if sort in ("name_desc", "date_added_desc", "year_desc"):
        results = list(reversed(results))
    return results


@browse_router.get("/library/episodes")
def browse_episodes(
    request: Request,
    session: Session = Depends(get_database_session),
    library_type: str | None = Query(default=None),
    library_id: str | None = Query(default=None),
    query: str | None = Query(default=None),
    watched: bool | None = Query(default=None),
    sort: str = Query(
        default="name",
        pattern="^(name|name_desc|air_date_desc|date_added_desc)$",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """List episodes, optionally filtered by library type, library ID, query, and watched state."""
    return list_episodes(
        connection=session,
        library_type=library_type,
        library_identifier=library_id,
        query=query,
        watched=watched,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@browse_router.get("/library/series/{series_identifier}")
def browse_series_detail(
    series_identifier: int,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Return a series with nested seasons, episodes, and file versions."""
    detail = get_series(session, series_identifier)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown series identifier")
    return detail


@browse_router.get("/library/series/{series_identifier}/episodes")
def browse_series_episodes(
    series_identifier: int,
    session: Session = Depends(get_database_session),
) -> list[dict[str, Any]]:
    """Return a flattened list of episodes across all seasons."""
    detail = get_series(session, series_identifier)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown series identifier")
    flattened: list[dict[str, Any]] = []
    for season in detail["seasons"]:
        for episode in season["episodes"]:
            episode["season_number"] = season["season_number"]
            flattened.append(episode)
    return flattened


@browse_router.get("/library/movies")
def browse_movies(
    request: Request,
    session: Session = Depends(get_database_session),
    library_id: str | None = Query(default=None),
    query: str | None = Query(default=None),
    sort: str = Query(
        default="name",
        pattern="^(name|name_desc|date_added|date_added_desc|year|year_desc)$",
    ),
) -> list[dict[str, Any]]:
    """List movies, optionally filtered by library and query text."""
    sort_column = {
        "name": "name",
        "name_desc": "name",
        "date_added": "date_added",
        "date_added_desc": "date_added",
        "year": "year",
        "year_desc": "year",
    }.get(sort, "name")
    results = list_movies(session, library_id, query, sort_column)
    if sort in ("name_desc", "date_added_desc", "year_desc"):
        results = list(reversed(results))
    return results


@browse_router.get("/library/movie/{movie_identifier}")
@browse_router.get("/library/movies/{movie_identifier}")
def browse_movie_detail(
    movie_identifier: int,
    session: Session = Depends(get_database_session),
) -> dict[str, Any]:
    """Return a single movie with its media file versions."""
    detail = get_movie(session, movie_identifier)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown movie identifier")
    return detail
