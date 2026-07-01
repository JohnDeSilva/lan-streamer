"""Service layer for fetching and managing media images from TMDB."""

import logging
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Series, Movie
from lan_streamer.db.queries_cast import (
    add_media_image,
)
from lan_streamer.providers.tmdb import tmdb_client

logger = logging.getLogger(__name__)


def _lookup_series_id(tmdb_identifier: str) -> Optional[str]:
    """Look up the DB UUID for a series by its TMDB identifier."""
    with get_session() as session:
        stmt = select(Series).where(Series.tmdb_identifier == tmdb_identifier)
        series = session.execute(stmt).unique().scalar_one_or_none()
        if series is None:
            logger.warning("Series with TMDB ID '%s' not found in DB", tmdb_identifier)
            return None
        return series.id


def _lookup_movie_id(tmdb_identifier: str) -> Optional[str]:
    """Look up the DB UUID for a movie by its TMDB identifier."""
    with get_session() as session:
        stmt = select(Movie).where(Movie.tmdb_identifier == tmdb_identifier)
        movie = session.execute(stmt).unique().scalar_one_or_none()
        if movie is None:
            logger.warning("Movie with TMDB ID '%s' not found in DB", tmdb_identifier)
            return None
        return movie.id


def fetch_and_store_series_images(series_id: str, tmdb_identifier: int) -> None:
    """Fetch all images for a series from TMDB and store in media_images."""
    logger.info(
        "Fetching series images for TMDB ID %s (DB series %s)",
        tmdb_identifier,
        series_id,
    )
    images_data = tmdb_client.get_series_images(tmdb_identifier)
    if not images_data:
        logger.warning("No images data returned for series %s", tmdb_identifier)
        return
    _store_images_from_tmdb(images_data, series_id=series_id)


def fetch_and_store_movie_images(movie_id: str, tmdb_identifier: int) -> None:
    """Fetch all images for a movie from TMDB and store in media_images."""
    logger.info(
        "Fetching movie images for TMDB ID %s (DB movie %s)",
        tmdb_identifier,
        movie_id,
    )
    images_data = tmdb_client.get_movie_images(tmdb_identifier)
    if not images_data:
        logger.warning("No images data returned for movie %s", tmdb_identifier)
        return
    _store_images_from_tmdb(images_data, movie_id=movie_id)


def _store_images_from_tmdb(
    images_data: Dict[str, Any],
    series_id: Optional[str] = None,
    movie_id: Optional[str] = None,
) -> None:
    """Process TMDB images response and store in media_images table."""
    stored_count = 0

    for image_type, tmdb_key in [
        ("poster", "posters"),
        ("backdrop", "backdrops"),
        ("logo", "logos"),
    ]:
        images_list: List[Dict[str, Any]] = images_data.get(tmdb_key, [])
        for image_info in images_list:
            file_path = image_info.get("file_path", "")
            if not file_path:
                continue

            remote_url = f"https://image.tmdb.org/t/p/original{file_path}"

            local_path = tmdb_client.download_and_cache_image(
                file_path,
                size="w1280" if image_type == "backdrop" else "w500",
            )

            add_media_image(
                series_id=series_id,
                movie_id=movie_id,
                image_type=image_type,
                source="tmdb",
                remote_url=remote_url,
                local_path=local_path or None,
            )
            stored_count += 1

    logger.info(
        "Stored %d images for %s",
        stored_count,
        f"series {series_id}" if series_id else f"movie {movie_id}",
    )
