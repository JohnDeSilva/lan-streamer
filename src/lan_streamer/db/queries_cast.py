"""Database queries for cast, crew, and person data."""

import logging
from typing import Optional, List, Any

from sqlalchemy import select, delete
from sqlalchemy.orm import joinedload

from lan_streamer.db.connection import get_session
from lan_streamer.db.models_cast import Person, MediaCast, MediaImage

logger = logging.getLogger(__name__)


def get_cast_for_series(series_id: str) -> List[MediaCast]:
    """Get all cast/crew entries for a series, ordered by sort_order.

    Args:
        series_id: The UUID of the series.

    Returns:
        List of MediaCast entries with eager-loaded person data.
    """
    with get_session() as session:
        statement = (
            select(MediaCast)
            .where(MediaCast.series_id == series_id)
            .options(joinedload(MediaCast.person))
            .order_by(MediaCast.sort_order)
        )
        result = session.execute(statement).unique().scalars().all()
        logger.debug("Retrieved %d cast entries for series %s", len(result), series_id)
        return list(result)


def get_cast_for_season(season_id: str) -> List[MediaCast]:
    """Get all cast/crew entries for a season.

    Args:
        season_id: The UUID of the season.

    Returns:
        List of MediaCast entries with eager-loaded person data.
    """
    with get_session() as session:
        statement = (
            select(MediaCast)
            .where(MediaCast.season_id == season_id)
            .options(joinedload(MediaCast.person))
            .order_by(MediaCast.sort_order)
        )
        result = session.execute(statement).unique().scalars().all()
        logger.debug("Retrieved %d cast entries for season %s", len(result), season_id)
        return list(result)


def get_cast_for_episode(episode_id: str) -> List[MediaCast]:
    """Get all cast/crew entries for an episode.

    Args:
        episode_id: The UUID of the episode.

    Returns:
        List of MediaCast entries with eager-loaded person data.
    """
    with get_session() as session:
        statement = (
            select(MediaCast)
            .where(MediaCast.episode_id == episode_id)
            .options(joinedload(MediaCast.person))
            .order_by(MediaCast.sort_order)
        )
        result = session.execute(statement).unique().scalars().all()
        logger.debug(
            "Retrieved %d cast entries for episode %s", len(result), episode_id
        )
        return list(result)


def get_cast_for_movie(movie_id: str) -> List[MediaCast]:
    """Get all cast/crew entries for a movie.

    Args:
        movie_id: The UUID of the movie.

    Returns:
        List of MediaCast entries with eager-loaded person data.
    """
    with get_session() as session:
        statement = (
            select(MediaCast)
            .where(MediaCast.movie_id == movie_id)
            .options(joinedload(MediaCast.person))
            .order_by(MediaCast.sort_order)
        )
        result = session.execute(statement).unique().scalars().all()
        logger.debug("Retrieved %d cast entries for movie %s", len(result), movie_id)
        return list(result)


def get_person_by_id(person_id: str) -> Optional[Person]:
    """Get a person by their ID.

    Args:
        person_id: The UUID of the person.

    Returns:
        The Person record, or None if not found.
    """
    with get_session() as session:
        statement = select(Person).where(Person.id == person_id)
        result = session.execute(statement).unique().scalar_one_or_none()
        logger.debug("Retrieved person by id %s: %s", person_id, result is not None)
        return result


def get_person_by_tmdb_id(tmdb_identifier: int) -> Optional[Person]:
    """Get a person by their TMDB identifier.

    Args:
        tmdb_identifier: The TMDB person identifier.

    Returns:
        The Person record, or None if not found.
    """
    with get_session() as session:
        statement = select(Person).where(Person.tmdb_identifier == tmdb_identifier)
        result = session.execute(statement).unique().scalar_one_or_none()
        logger.debug(
            "Retrieved person by tmdb id %s: %s",
            tmdb_identifier,
            result is not None,
        )
        return result


def get_or_create_person(
    tmdb_identifier: int,
    name: str,
    profile_path: Optional[str] = None,
    session: Optional[Any] = None,
) -> Person:
    """Get existing person by TMDB identifier or create a new one.

    Updates name and profile_path if person exists but data has changed.

    Args:
        tmdb_identifier: The TMDB person identifier.
        name: The person's display name.
        profile_path: Optional URL path to profile image.
        session: Optional SQLAlchemy session.

    Returns:
        The existing or newly created Person record.
    """
    if session is not None:
        return _get_or_create_person_impl(session, tmdb_identifier, name, profile_path)

    with get_session() as session_ctx:
        person = _get_or_create_person_impl(
            session_ctx, tmdb_identifier, name, profile_path
        )
        session_ctx.commit()
        # Access attributes to prevent DetachedInstanceError
        _ = person.id
        _ = person.name
        _ = person.profile_path
        return person


def _get_or_create_person_impl(
    session: Any,
    tmdb_identifier: int,
    name: str,
    profile_path: Optional[str] = None,
) -> Person:
    statement = select(Person).where(Person.tmdb_identifier == tmdb_identifier)
    person = session.execute(statement).unique().scalar_one_or_none()

    if person is not None:
        needs_update = False
        if person.name != name:
            person.name = name
            needs_update = True
        if profile_path and person.profile_path != profile_path:
            person.profile_path = profile_path
            needs_update = True
        if needs_update:
            logger.info("Updated person %s (%s)", person.name, tmdb_identifier)
    else:
        person = Person(
            tmdb_identifier=tmdb_identifier,
            name=name,
            profile_path=profile_path,
        )
        session.add(person)
        logger.info("Created new person %s (%s)", name, tmdb_identifier)

    session.flush()
    return person


def get_filmography(person_id: str) -> List[MediaCast]:
    """Get all media a person appears in, with eager-loaded media info.

    Args:
        person_id: The UUID of the person.

    Returns:
        List of MediaCast entries with joined media relationships loaded.
    """
    with get_session() as session:
        statement = (
            select(MediaCast)
            .where(MediaCast.person_id == person_id)
            .options(
                joinedload(MediaCast.series),
                joinedload(MediaCast.season),
                joinedload(MediaCast.episode),
                joinedload(MediaCast.movie),
                joinedload(MediaCast.person),
            )
            .order_by(MediaCast.sort_order)
        )
        result = session.execute(statement).unique().scalars().all()
        logger.debug(
            "Retrieved %d filmography entries for person %s",
            len(result),
            person_id,
        )
        return list(result)


def delete_cast_for_media(
    series_id: Optional[str] = None,
    season_id: Optional[str] = None,
    episode_id: Optional[str] = None,
    movie_id: Optional[str] = None,
) -> None:
    """Delete all cast entries for a specific series, season, episode, or movie (for re-fetch).

    Args:
        series_id: Optional UUID of the series to clear cast for.
        season_id: Optional UUID of the season to clear cast for.
        episode_id: Optional UUID of the episode to clear cast for.
        movie_id: Optional UUID of the movie to clear cast for.
    """
    if (
        series_id is None
        and season_id is None
        and episode_id is None
        and movie_id is None
    ):
        logger.warning("delete_cast_for_media called with no media identifier")
        return

    with get_session() as session:
        if series_id is not None:
            statement = delete(MediaCast).where(MediaCast.series_id == series_id)
            session.execute(statement)
            logger.info("Deleted cast entries for series %s", series_id)
        if season_id is not None:
            statement = delete(MediaCast).where(MediaCast.season_id == season_id)
            session.execute(statement)
            logger.info("Deleted cast entries for season %s", season_id)
        if episode_id is not None:
            statement = delete(MediaCast).where(MediaCast.episode_id == episode_id)
            session.execute(statement)
            logger.info("Deleted cast entries for episode %s", episode_id)
        if movie_id is not None:
            statement = delete(MediaCast).where(MediaCast.movie_id == movie_id)
            session.execute(statement)
            logger.info("Deleted cast entries for movie %s", movie_id)
        session.commit()


def get_images_for_media(
    series_id: Optional[str] = None,
    movie_id: Optional[str] = None,
    image_type: Optional[str] = None,
) -> List[MediaImage]:
    """Get all images for a series or movie, optionally filtered by type.

    Args:
        series_id: Optional UUID of the series.
        movie_id: Optional UUID of the movie.
        image_type: Optional image type filter (e.g. "poster", "backdrop").

    Returns:
        List of MediaImage records matching the criteria.
    """
    if series_id is None and movie_id is None:
        logger.warning("get_images_for_media called with no media identifier")
        return []

    with get_session() as session:
        conditions: list = []
        if series_id is not None:
            conditions.append(MediaImage.series_id == series_id)
        if movie_id is not None:
            conditions.append(MediaImage.movie_id == movie_id)
        if image_type is not None:
            conditions.append(MediaImage.image_type == image_type)

        statement = (
            select(MediaImage).where(*conditions).order_by(MediaImage.sort_order)
        )
        result = session.execute(statement).unique().scalars().all()
        logger.debug("Retrieved %d images for media", len(result))
        return list(result)


def set_selected_image(image_id: str) -> None:
    """Set a specific image as the selected poster/backdrop for its media.

    This will unselect all other images of the same type for the same media.

    Args:
        image_id: The UUID of the image to select.
    """
    with get_session() as session:
        statement = select(MediaImage).where(MediaImage.id == image_id)
        image = session.execute(statement).unique().scalar_one_or_none()
        if image is None:
            logger.warning("Image %s not found, cannot set as selected", image_id)
            return

        # Unselect all other images of same type for same media
        conditions: list = [
            MediaImage.image_type == image.image_type,
            MediaImage.is_selected,
        ]
        if image.series_id is not None:
            conditions.append(MediaImage.series_id == image.series_id)
        if image.movie_id is not None:
            conditions.append(MediaImage.movie_id == image.movie_id)

        unselect_statement = select(MediaImage).where(*conditions)
        existing = session.execute(unselect_statement).unique().scalars().all()
        for existing_image in existing:
            existing_image.is_selected = False

        image.is_selected = True
        session.commit()
        logger.info(
            "Set image %s as selected %s for media",
            image_id,
            image.image_type,
        )


def add_media_image(
    series_id: Optional[str] = None,
    movie_id: Optional[str] = None,
    image_type: str = "poster",
    source: str = "tmdb",
    remote_url: Optional[str] = None,
    local_path: Optional[str] = None,
) -> MediaImage:
    """Add a new image record for a series or movie.

    The first image added of a given type for a given media item is
    automatically marked as selected.

    Args:
        series_id: Optional UUID of the series.
        movie_id: Optional UUID of the movie.
        image_type: Type of image (default "poster").
        source: Source of the image (default "tmdb").
        remote_url: Optional remote URL for the image.
        local_path: Optional local file path for the image.

    Returns:
        The newly created MediaImage record.
    """
    with get_session() as session:
        # Check if the image already exists
        if remote_url:
            existing_check = select(MediaImage).where(
                MediaImage.image_type == image_type,
                MediaImage.remote_url == remote_url,
            )
            if series_id is not None:
                existing_check = existing_check.where(MediaImage.series_id == series_id)
            if movie_id is not None:
                existing_check = existing_check.where(MediaImage.movie_id == movie_id)

            existing_img = session.execute(existing_check).unique().scalar_one_or_none()
            if existing_img is not None:
                logger.debug("Image already exists: %s", remote_url)
                return existing_img

        # Count existing images of this type for sort order
        conditions: list = [MediaImage.image_type == image_type]
        if series_id is not None:
            conditions.append(MediaImage.series_id == series_id)
        if movie_id is not None:
            conditions.append(MediaImage.movie_id == movie_id)

        count_statement = select(MediaImage).where(*conditions)
        existing = session.execute(count_statement).unique().scalars().all()
        sort_order = len(existing)

        # First image added is automatically selected
        is_selected = len(existing) == 0

        image = MediaImage(
            series_id=series_id,
            movie_id=movie_id,
            image_type=image_type,
            source=source,
            remote_url=remote_url,
            local_path=local_path,
            is_selected=is_selected,
            sort_order=sort_order,
        )
        session.add(image)
        session.commit()
        logger.debug(
            "Added %s image for media (sort_order=%d, selected=%s)",
            image_type,
            sort_order,
            is_selected,
        )
        return image
