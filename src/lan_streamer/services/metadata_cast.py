"""Service layer for fetching and storing cast/crew metadata from TMDB."""

import logging
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Series, Movie
from lan_streamer.db.models_cast import MediaCast
from lan_streamer.db.queries_cast import (
    get_or_create_person,
    delete_cast_for_media,
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


def _map_tmdb_role(job: str, department: str) -> str:
    """Map TMDB job/department to our role field."""
    if department == "Acting":
        return "actor"
    job_lower = job.lower()
    if job_lower == "director":
        return "director"
    if job_lower in ("writer", "screenplay", "story"):
        return "writer"
    if job_lower in ("producer", "executive producer", "co-producer"):
        return "producer"
    return job_lower


def _fetch_and_store_credits_for_media(
    media_id: str,
    credits_data: Dict[str, Any],
    series_id: Optional[str] = None,
    season_id: Optional[str] = None,
    episode_id: Optional[str] = None,
    movie_id: Optional[str] = None,
) -> None:
    """Store TMDB credits data into the media_cast table."""
    cast_list: List[Dict[str, Any]] = credits_data.get("cast", [])
    crew_list: List[Dict[str, Any]] = credits_data.get("crew", [])

    stored_count = 0
    inserted_keys = set()

    with get_session() as session:
        for credit in cast_list:
            tmdb_person_id = credit.get("id")
            if not tmdb_person_id:
                continue
            person_name = credit.get("name", "Unknown")
            profile_path = credit.get("profile_path", "") or ""
            character = credit.get("character", "") or ""
            credit_id = credit.get("credit_id", "") or ""
            sort_order = credit.get("order", 0)

            if profile_path:
                local_profile = tmdb_client.download_and_cache_profile(
                    profile_path, tmdb_person_id
                )
            else:
                local_profile = ""

            person = get_or_create_person(
                tmdb_identifier=tmdb_person_id,
                name=person_name,
                profile_path=local_profile or None,
                session=session,
            )

            # Deduplicate within the same run/media
            key = (person.id, "actor", credit_id or "")
            if key in inserted_keys:
                continue
            inserted_keys.add(key)

            cast_entry = MediaCast(
                person_id=person.id,
                series_id=series_id,
                season_id=season_id,
                episode_id=episode_id,
                movie_id=movie_id,
                role="actor",
                character=character or None,
                department="Acting",
                sort_order=sort_order,
                tmdb_credit_id=credit_id or None,
            )
            session.add(cast_entry)
            stored_count += 1

        for credit in crew_list:
            tmdb_person_id = credit.get("id")
            if not tmdb_person_id:
                continue
            person_name = credit.get("name", "Unknown")
            profile_path = credit.get("profile_path", "") or ""
            job = credit.get("job", "") or ""
            department = credit.get("department", "") or ""
            credit_id = credit.get("credit_id", "") or ""

            if profile_path:
                local_profile = tmdb_client.download_and_cache_profile(
                    profile_path, tmdb_person_id
                )
            else:
                local_profile = ""

            person = get_or_create_person(
                tmdb_identifier=tmdb_person_id,
                name=person_name,
                profile_path=local_profile or None,
                session=session,
            )

            role = _map_tmdb_role(job, department)

            # Deduplicate within the same run/media
            key = (person.id, role, credit_id or "")
            if key in inserted_keys:
                continue
            inserted_keys.add(key)

            cast_entry = MediaCast(
                person_id=person.id,
                series_id=series_id,
                season_id=season_id,
                episode_id=episode_id,
                movie_id=movie_id,
                role=role,
                job=job or None,
                department=department or None,
                sort_order=999,
                tmdb_credit_id=credit_id or None,
            )
            session.add(cast_entry)
            stored_count += 1

        session.commit()

    logger.info(
        "Stored %d cast/crew entries for media (series=%s, movie=%s)",
        stored_count,
        series_id,
        movie_id,
    )


def fetch_and_store_series_credits(series_id: str, tmdb_identifier: int) -> None:
    """Fetch series credits from TMDB and store in database."""
    logger.info(
        "Fetching series credits for TMDB ID %s (DB series %s)",
        tmdb_identifier,
        series_id,
    )
    delete_cast_for_media(series_id=series_id)
    credits_data = tmdb_client.get_series_credits(tmdb_identifier)
    if not credits_data:
        logger.warning("No credits data returned for series %s", tmdb_identifier)
        return
    _fetch_and_store_credits_for_media(
        media_id=series_id,
        credits_data=credits_data,
        series_id=series_id,
    )


def fetch_and_store_movie_credits(movie_id: str, tmdb_identifier: int) -> None:
    """Fetch movie credits from TMDB and store in database."""
    logger.info(
        "Fetching movie credits for TMDB ID %s (DB movie %s)",
        tmdb_identifier,
        movie_id,
    )
    delete_cast_for_media(movie_id=movie_id)
    credits_data = tmdb_client.get_movie_credits(tmdb_identifier)
    if not credits_data:
        logger.warning("No credits data returned for movie %s", tmdb_identifier)
        return
    _fetch_and_store_credits_for_media(
        media_id=movie_id,
        credits_data=credits_data,
        movie_id=movie_id,
    )


def fetch_and_store_episode_credits(
    episode_id: str,
    series_tmdb_id: int,
    season_number: int,
    episode_number: int,
) -> None:
    """Fetch episode credits from TMDB and store in database."""
    logger.info(
        "Fetching episode credits for S%02dE%02d of series %s (DB episode %s)",
        season_number,
        episode_number,
        series_tmdb_id,
        episode_id,
    )
    credits_data = tmdb_client.get_episode_credits(
        series_tmdb_id, season_number, episode_number
    )
    if not credits_data:
        logger.debug("No credits data for episode %s", episode_id)
        return
    delete_cast_for_media(episode_id=episode_id)
    _fetch_and_store_credits_for_media(
        media_id=episode_id,
        credits_data=credits_data,
        episode_id=episode_id,
    )
