"""
Async versions of key library persistence read operations.

These functions use :class:`AsyncSession` backed by ``aiosqlite``
and mirror the sync counterparts in ``library_tv.py`` / ``library_movie.py``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from lan_streamer.db.async_session import get_async_session
from lan_streamer.db.models import Series, Season, Episode, Movie
from lan_streamer.db.orm_serialization import (
    _build_series_dict,
    _build_movie_dict,
)

logger = logging.getLogger(__name__)


async def async_load_library(library_name: str) -> dict[str, Any]:
    """Async version of :func:`lan_streamer.db.library_tv.load_library`."""
    from lan_streamer.db.library_tv import _COUNTER_SUFFIX_RE

    start_time = time.time()
    library_data: dict[str, Any] = {}
    stats = {"series": 0, "seasons": 0, "episodes": 0}

    try:
        async with get_async_session() as session:
            result = await session.scalars(
                select(Series)
                .where(Series.library_name == library_name)
                .options(
                    selectinload(Series.seasons)
                    .selectinload(Season.episodes)
                    .selectinload(Episode.media_files),
                    selectinload(Series.seasons)
                    .selectinload(Season.episodes)
                    .selectinload(Episode.playback_state),
                )
                .order_by(Series.name)
            )
            series_list = result.all()

            for series in series_list:
                stats["series"] += 1
                stats["seasons"] += len(series.seasons)
                for season in series.seasons:
                    stats["episodes"] += len(season.episodes)
                if series.name is not None:
                    cleaned_name = _COUNTER_SUFFIX_RE.sub("", series.name)
                    library_data[cleaned_name or series.name] = _build_series_dict(
                        series
                    )
    except Exception:
        logger.exception(
            f"Error loading library '{library_name}' from database (async)"
        )
        return {}

    duration = time.time() - start_time
    logger.info(
        f"[async] Loaded library '{library_name}' in {duration:.3f}s: "
        f"{stats['series']} series, {stats['seasons']} seasons, "
        f"{stats['episodes']} episodes."
    )
    return library_data


async def async_load_movie_library(library_name: str) -> dict[str, Any]:
    """Async version of :func:`lan_streamer.db.library_movie.load_movie_library`."""

    start_time = time.time()
    library_data: dict[str, Any] = {}
    stats = {"movies": 0}

    try:
        async with get_async_session() as session:
            result = await session.scalars(
                select(Movie)
                .where(Movie.library_name == library_name)
                .options(
                    selectinload(Movie.media_files),
                    selectinload(Movie.playback_state),
                )
                .order_by(Movie.name)
            )
            movies = result.all()

            for movie in movies:
                stats["movies"] += 1
                if movie.name is not None:
                    library_data[movie.name] = _build_movie_dict(movie)
    except Exception:
        logger.exception(
            f"Error loading movie library '{library_name}' from database (async)"
        )
        return {}

    duration = time.time() - start_time
    logger.info(
        f"[async] Loaded movie library '{library_name}' in {duration:.3f}s: "
        f"{stats['movies']} movies."
    )
    return library_data
