import hashlib
import json
import logging
import time
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload

from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Movie, Series, SmartRowCache
from lan_streamer.db.queries_ui import get_combined_smart_row as compute_smart_row
from lan_streamer.system.config import config as app_config

logger = logging.getLogger(__name__)


def compute_config_hash(
    library_names: list[str], sort_by: str, filter_mode: str
) -> str:
    """Create a deterministic hash from smart row configuration parameters."""
    raw = (
        json.dumps(sorted(library_names), sort_keys=True)
        + "|"
        + sort_by
        + "|"
        + filter_mode
    )
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def get_cached_smart_rows(
    library_names: list[str], sort_by: str, filter_mode: str
) -> list[dict[str, Any]]:
    """Read smart row results from cache, falling back to live computation."""
    config_hash = compute_config_hash(library_names, sort_by, filter_mode)
    try:
        with get_session() as session:
            cached_rows = (
                session.execute(
                    select(SmartRowCache)
                    .options(
                        joinedload(SmartRowCache.series),
                        joinedload(SmartRowCache.movie),
                    )
                    .where(SmartRowCache.config_hash == config_hash)
                    .order_by(SmartRowCache.sort_order)
                )
                .unique()
                .scalars()
                .all()
            )
            if cached_rows:
                logger.debug(
                    f"Smart row cache HIT for config_hash={config_hash} "
                    f"({len(cached_rows)} items)"
                )
                return [_row_to_dict(row) for row in cached_rows]

            logger.debug(
                f"Smart row cache MISS for config_hash={config_hash}, "
                f"falling back to live computation"
            )
    except Exception:
        logger.exception(f"Error reading smart row cache for config_hash={config_hash}")

    return compute_smart_row(library_names, sort_by, filter_mode)


def rebuild_cache_for_config(
    library_names: list[str], sort_by: str, filter_mode: str
) -> None:
    """Compute a single smart row configuration and cache the results."""
    config_hash = compute_config_hash(library_names, sort_by, filter_mode)
    logger.info(
        f"Rebuilding smart row cache for config_hash={config_hash} "
        f"(libraries={library_names}, sort_by='{sort_by}', "
        f"filter_mode='{filter_mode}')"
    )
    try:
        items = compute_smart_row(library_names, sort_by, filter_mode)
    except Exception:
        logger.exception(f"Failed to compute smart row for config_hash={config_hash}")
        return

    series_ids = _resolve_series_ids(items)
    movie_ids = _resolve_movie_ids(items)
    current_time = int(time.time())

    try:
        with get_session() as session:
            session.execute(
                delete(SmartRowCache).where(SmartRowCache.config_hash == config_hash)
            )
            for sort_order, item in enumerate(items):
                item_type = item.get("type", "series")
                cache_entry = SmartRowCache(
                    config_hash=config_hash,
                    sort_order=sort_order,
                    item_type=item_type,
                    series_id=_lookup_series_id(item, series_ids, item_type),
                    movie_id=_lookup_movie_id(item, movie_ids, item_type),
                    season_name=item.get("season_name"),
                    date_added=item.get("date_added") or 0,
                    air_date=item.get("air_date"),
                    watched_count=item.get("watched_count") or 0,
                    total_count=item.get("total_count") or 1,
                    last_played_at=item.get("last_played_at") or 0,
                    updated_at=current_time,
                )
                session.add(cache_entry)
            session.commit()
        logger.info(
            f"Smart row cache rebuilt for config_hash={config_hash} "
            f"with {len(items)} items"
        )
    except Exception:
        logger.exception(
            f"Failed to write smart row cache for config_hash={config_hash}"
        )


def rebuild_all_cache() -> None:
    """Rebuild cache entries for all enabled smart row configurations."""
    app_config.load()
    configs = [row for row in app_config.combined_views if row.get("enabled", True)]
    if not configs:
        logger.info("No enabled smart row configurations to cache")
        return

    logger.info(f"Rebuilding smart row cache for {len(configs)} configurations")
    for row_config in configs:
        libraries = row_config.get("libraries", [])
        sort_by = row_config.get("sort_by", "Alphabetical")
        filter_mode = row_config.get("filter_mode", "All")
        rebuild_cache_for_config(libraries, sort_by, filter_mode)


def get_affected_config_hashes_for_libraries(
    library_names: list[str],
) -> list[str]:
    """Return config hashes for all enabled rows that include the given
    libraries. An empty library list (all libraries) always matches."""
    config_hashes: set[str] = set()
    app_config.load()
    for row_config in app_config.combined_views:
        if not row_config.get("enabled", True):
            continue
        row_libraries = row_config.get("libraries", [])
        if not row_libraries or any(lib in library_names for lib in row_libraries):
            config_hashes.add(
                compute_config_hash(
                    row_libraries,
                    row_config.get("sort_by", "Alphabetical"),
                    row_config.get("filter_mode", "All"),
                )
            )
    return list(config_hashes)


def _row_to_dict(row: SmartRowCache) -> dict[str, Any]:
    """Convert a cached row back to the dict format expected by the UI.

    Display data (name, poster_path, library_name) is resolved via FK
    relationships to Series / Movie. Computed aggregation fields come
    directly from the cache.
    """
    result: dict[str, Any] = {
        "type": row.item_type,
        "date_added": row.date_added,
        "air_date": row.air_date or "",
        "watched_count": row.watched_count,
        "total_count": row.total_count,
        "last_played_at": row.last_played_at,
    }

    series = row.series
    movie = row.movie

    if series is not None:
        result["name"] = series.name or ""
        result["series_name"] = series.name or ""
        result["poster_path"] = series.poster_path or ""
        result["library_name"] = series.library_name or ""
        if not result["air_date"]:
            result["air_date"] = series.first_air_date or ""
    elif movie is not None:
        result["name"] = movie.name or ""
        result["poster_path"] = movie.poster_path or ""
        result["library_name"] = movie.library_name or ""
        if not result["air_date"]:
            result["air_date"] = str(movie.year or "")
    else:
        result["name"] = ""
        result["series_name"] = ""
        result["poster_path"] = ""
        result["library_name"] = ""
        logger.warning(
            f"SmartRowCache entry {row.id} has no FK resolution "
            f"(type={row.item_type}, config_hash={row.config_hash})"
        )

    if row.item_type == "season":
        result["season_name"] = row.season_name or ""
        if series is not None:
            result["series_name"] = series.name or ""
            result["name"] = series.name or ""

    return result


def _resolve_series_ids(items: list[dict[str, Any]]) -> dict[str, str]:
    """Build a map of series identifiers for all items.

    Maps (library_name|name), (junction_library|name), and name to series.id.
    """
    names_to_lookup: set[str] = set()
    for item in items:
        item_type = item.get("type")
        if item_type in ("series", "season"):
            key = item.get("name") or item.get("series_name") or ""
            if key:
                names_to_lookup.add(key)
        elif item_type == "movie":
            key = item.get("name") or ""
            if key:
                names_to_lookup.add(key)

    if not names_to_lookup:
        return {}

    result: dict[str, str] = {}
    try:
        with get_session() as session:
            from sqlalchemy.orm import selectinload

            series_list = session.scalars(
                select(Series)
                .where(Series.name.in_(names_to_lookup))
                .options(selectinload(Series.libraries))
            ).all()
            for series in series_list:
                if series.name:
                    if series.library_name:
                        result[f"{series.library_name}|{series.name}"] = series.id
                    for series_library in series.libraries:
                        result[f"{series_library.library_name}|{series.name}"] = (
                            series.id
                        )
                    result[series.name] = series.id
                    result[f"|{series.name}"] = series.id
    except Exception:
        logger.exception("Failed to resolve series IDs for cache rebuild")

    return result


def _resolve_movie_ids(items: list[dict[str, Any]]) -> dict[str, str]:
    """Build a map of movie identifiers for all items.

    Maps (library_name|name), (junction_library|name), and name to movie.id.
    """
    names_to_lookup: set[str] = set()
    for item in items:
        if item.get("type") == "movie":
            key = item.get("name") or ""
            if key:
                names_to_lookup.add(key)

    if not names_to_lookup:
        return {}

    result: dict[str, str] = {}
    try:
        with get_session() as session:
            from sqlalchemy.orm import selectinload

            movie_list = session.scalars(
                select(Movie)
                .where(Movie.name.in_(names_to_lookup))
                .options(selectinload(Movie.libraries))
            ).all()
            for movie in movie_list:
                if movie.name:
                    if movie.library_name:
                        result[f"{movie.library_name}|{movie.name}"] = movie.id
                    for movie_library in movie.libraries:
                        result[f"{movie_library.library_name}|{movie.name}"] = movie.id
                    result[movie.name] = movie.id
                    result[f"|{movie.name}"] = movie.id
    except Exception:
        logger.exception("Failed to resolve movie IDs for cache rebuild")

    return result


def _lookup_series_id(
    item: dict[str, Any], series_ids: dict[str, str], item_type: str
) -> str | None:
    """Look up the series ID for an item from the pre-built map."""
    if item_type == "movie":
        return None
    library_name = item.get("library_name", "")
    item_name = item.get("name") or item.get("series_name") or ""
    return series_ids.get(f"{library_name}|{item_name}") or series_ids.get(item_name)


def _lookup_movie_id(
    item: dict[str, Any], movie_ids: dict[str, str], item_type: str
) -> str | None:
    """Look up the movie ID for an item from the pre-built map."""
    if item_type != "movie":
        return None
    library_name = item.get("library_name", "")
    item_name = item.get("name") or ""
    return movie_ids.get(f"{library_name}|{item_name}") or movie_ids.get(item_name)
