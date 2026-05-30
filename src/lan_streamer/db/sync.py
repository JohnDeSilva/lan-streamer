import logging
import time
from typing import Set, Tuple, Any

from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from lan_streamer.db.models import Series, Season, Episode, Movie


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


logger = logging.getLogger(__name__)


def _sync_watched_by_ids(session: Session, watched_ids: Set[str]) -> int:
    """
    Marks all Episodes and Movies whose Jellyfin ID is in *watched_ids* as watched.
    Returns the combined update count.
    """
    if not watched_ids:
        return 0
    logger.debug(f"Syncing watched status by ID for {len(watched_ids)} items")
    count = int(
        session.execute(
            update(Episode)
            .where(Episode.jellyfin_id.in_(watched_ids))
            .values(watched=True)
        ).rowcount  # type: ignore[attr-defined]
        or 0
    )
    count += int(
        session.execute(
            update(Movie).where(Movie.jellyfin_id.in_(watched_ids)).values(watched=True)
        ).rowcount  # type: ignore[attr-defined]
        or 0
    )
    logger.debug(f"Synced by ID: marked {count} items as watched")
    return count


def _sync_watched_by_paths(session: Session, watched_paths: Set[str]) -> int:
    """
    Marks all Episodes and Movies whose file path is in *watched_paths* as watched.
    Returns the combined update count.
    """
    if not watched_paths:
        return 0
    logger.debug(f"Syncing watched status by path for {len(watched_paths)} items")
    count = int(
        session.execute(
            update(Episode)
            .where(Episode.watched.is_(False), Episode.path.in_(watched_paths))
            .values(watched=True)
        ).rowcount  # type: ignore[attr-defined]
        or 0
    )
    count += int(
        session.execute(
            update(Movie)
            .where(Movie.watched.is_(False), Movie.path.in_(watched_paths))
            .values(watched=True)
        ).rowcount  # type: ignore[attr-defined]
        or 0
    )
    logger.debug(f"Synced by path: marked {count} items as watched")
    return count


def _sync_watched_by_names(
    session: Session, watched_names: Set[Tuple[str, str]]
) -> int:
    """
    Marks Episodes whose (series_name, episode_name) pair is in *watched_names* as watched.
    Returns the total update count.
    """
    if not watched_names:
        return 0
    logger.debug(f"Syncing watched status by names for {len(watched_names)} pairs")
    count = 0
    for series_name, episode_name in watched_names:
        episode_ids = list(
            session.scalars(
                select(Episode.id)
                .join(Season)
                .join(Series)
                .where(
                    Episode.watched.is_(False),
                    func.lower(Series.name) == series_name.lower(),
                    func.lower(Episode.name) == episode_name.lower(),
                )
            ).all()
        )
        if episode_ids:
            logger.debug(
                f"Found match: series '{series_name}', episode '{episode_name}' -> Episode IDs: {episode_ids}"
            )
            count += int(
                session.execute(
                    update(Episode)
                    .where(Episode.id.in_(episode_ids))
                    .values(watched=True)
                ).rowcount  # type: ignore[attr-defined]
                or 0
            )
    logger.debug(f"Synced by names: marked {count} items as watched")
    return count


def sync_watched_from_jellyfin_data(
    watched_ids: Set[str],
    watched_paths: Set[str],
    watched_names: Set[Tuple[str, str]] | None = None,
) -> int:
    """
    Bulk-updates watched=True for all episodes whose Jellyfin ID is in watched_ids
    OR whose file path is in watched_paths
    OR whose (series_name, episode_name) is in watched_names.
    Returns the total number of rows updated.
    """
    pass

    if not watched_ids and not watched_paths and not watched_names:
        logger.info("No watched IDs, paths, or names provided for Jellyfin sync.")
        return 0

    start_time = time.time()
    logger.info(
        f"Starting bulk watched status sync: {len(watched_ids)} IDs, "
        f"{len(watched_paths)} paths, {len(watched_names or [])} names."
    )
    updated_count = 0
    try:
        with get_session() as session:
            updated_count += _sync_watched_by_ids(session, watched_ids)
            updated_count += _sync_watched_by_paths(session, watched_paths)
            updated_count += _sync_watched_by_names(session, watched_names or set())

        duration = time.time() - start_time
        logger.info(
            f"sync_watched_from_jellyfin_data: marked {updated_count} episodes as "
            f"watched in {duration:.3f}s."
        )
    except Exception:
        logger.exception("Error in sync_watched_from_jellyfin_data")

    return updated_count


def get_all_episodes_with_jellyfin_id() -> list:
    """Returns a list of all episodes and movies that have a Jellyfin ID associated."""
    pass

    items: list = []
    try:
        with get_session() as session:
            model: type[Episode] | type[Movie]
            for model in (Episode, Movie):
                rows = session.scalars(
                    select(model).where(
                        model.jellyfin_id.is_not(None),
                        model.jellyfin_id != "",
                    )
                ).all()
                for row in rows:
                    items.append(
                        {
                            "name": row.name,
                            "path": row.path,
                            "jellyfin_id": row.jellyfin_id,
                            "watched": row.watched,
                        }
                    )
    except Exception:
        logger.exception("Error fetching episodes/movies with Jellyfin ID")
    return items
