import logging
import threading
from typing import Any

from lan_streamer import db
from lan_streamer.system.config import config as app_config

logger = logging.getLogger(__name__)


def _compute_next_up_from_memory(
    library_items_by_name: dict[str, dict[str, Any]],
    library_configs: dict[str, dict[str, Any]],
    target_libraries: list[str],
) -> list[dict[str, Any]]:
    """Compute 'Next Up' smart row items from in-memory remote library dictionaries."""
    results: list[dict[str, Any]] = []
    for library_name in target_libraries:
        items_dict = library_items_by_name.get(library_name, {})
        library_config = library_configs.get(library_name, {})
        if not isinstance(items_dict, dict) or library_config.get("type", "tv") == "movie":
            continue
        for series_name, series_data in items_dict.items():
            if not isinstance(series_data, dict):
                continue
            metadata = series_data.get("metadata", {})
            poster_path = metadata.get("poster_path", "")
            last_played_max = 0
            next_unwatched_episode: dict[str, Any] | None = None
            has_watched = False

            seasons = series_data.get("seasons", {})
            for season_name in sorted(seasons.keys()):
                season_data = seasons[season_name]
                if not isinstance(season_data, dict):
                    continue
                for episode in season_data.get("episodes", []) or []:
                    if not isinstance(episode, dict):
                        continue
                    has_files = bool(episode.get("path") or episode.get("versions"))
                    if not has_files:
                        continue
                    last_played = int(episode.get("last_played_at") or 0)
                    last_played_max = max(last_played_max, last_played)
                    if episode.get("watched"):
                        has_watched = True
                    elif next_unwatched_episode is None:
                        next_unwatched_episode = episode

            if has_watched and next_unwatched_episode is not None:
                results.append(
                    {
                        "type": "series",
                        "name": series_name,
                        "poster_path": poster_path,
                        "library_name": library_name,
                        "date_added": int(next_unwatched_episode.get("date_added") or 0),
                        "air_date": str(next_unwatched_episode.get("air_date") or ""),
                        "watched_count": 0,
                        "total_count": 1,
                        "last_played_at": last_played_max,
                    }
                )
    results.sort(key=lambda item: int(item.get("last_played_at") or 0), reverse=True)
    return results


def compute_smart_rows_from_memory(
    library_items_by_name: dict[str, dict[str, Any]],
    library_configs: dict[str, dict[str, Any]],
    library_names: list[str],
    sort_by: str,
    filter_mode: str,
) -> list[dict[str, Any]]:
    """Compute smart row items directly from in-memory remote library snapshots."""
    target_libraries = (
        list(library_names) if library_names else list(library_items_by_name.keys())
    )
    if sort_by == "Next Up":
        return _compute_next_up_from_memory(
            library_items_by_name, library_configs, target_libraries
        )

    results: list[dict[str, Any]] = []
    for library_name in target_libraries:
        items_dict = library_items_by_name.get(library_name, {})
        if not isinstance(items_dict, dict):
            continue
        library_config = library_configs.get(library_name, {})
        is_movie_library = library_config.get("type", "tv") == "movie"

        for item_name, item_data in items_dict.items():
            if not isinstance(item_data, dict):
                continue
            is_movie = is_movie_library or (
                item_data.get("type") == "movie" or "seasons" not in item_data
            )
            if is_movie:
                movie_watched = bool(item_data.get("watched"))
                keep = True
                if filter_mode == "Watched":
                    keep = movie_watched
                elif filter_mode == "Unwatched":
                    keep = not movie_watched
                if keep:
                    results.append(
                        {
                            "type": "movie",
                            "name": item_name,
                            "poster_path": item_data.get("poster_path", ""),
                            "library_name": library_name,
                            "date_added": int(item_data.get("date_added") or 0),
                            "air_date": str(item_data.get("year") or ""),
                            "watched_count": 1 if movie_watched else 0,
                            "total_count": 1,
                        }
                    )
            else:
                total_episodes = 0
                watched_episodes = 0
                max_date_added = 0
                max_air_date = ""
                for season_data in (item_data.get("seasons") or {}).values():
                    if not isinstance(season_data, dict):
                        continue
                    for episode in season_data.get("episodes", []) or []:
                        if not isinstance(episode, dict):
                            continue
                        if not (episode.get("path") or episode.get("versions")):
                            continue
                        total_episodes += 1
                        if episode.get("watched"):
                            watched_episodes += 1
                        max_date_added = max(
                            max_date_added, int(episode.get("date_added") or 0)
                        )
                        air_value = str(episode.get("air_date") or "")
                        if air_value > max_air_date:
                            max_air_date = air_value

                if total_episodes == 0:
                    continue

                keep = True
                if filter_mode == "Watched":
                    keep = watched_episodes == total_episodes
                elif filter_mode == "Unwatched":
                    keep = watched_episodes < total_episodes
                if keep:
                    metadata = item_data.get("metadata", {})
                    results.append(
                        {
                            "type": "series",
                            "name": item_name,
                            "poster_path": metadata.get("poster_path", ""),
                            "library_name": library_name,
                            "date_added": max_date_added,
                            "air_date": max_air_date
                            or str(metadata.get("first_air_date") or ""),
                            "watched_count": watched_episodes,
                            "total_count": total_episodes,
                        }
                    )

    _sort_smart_row_items(results, sort_by)
    return results


def _sort_smart_row_items(items: list[dict[str, Any]], sort_by: str) -> None:
    """Sort smart row items in place using the configured sort mode."""
    if sort_by == "Next Up":
        items.sort(key=lambda item: int(item.get("last_played_at") or 0), reverse=True)
    elif sort_by == "Recently Added":
        items.sort(key=lambda item: int(item.get("date_added") or 0), reverse=True)
    elif sort_by == "Recently Aired":
        items.sort(key=lambda item: str(item.get("air_date") or ""), reverse=True)
    else:
        items.sort(key=lambda item: str(item.get("name") or "").lower())


def get_combined_smart_row_with_remote(
    library_names: list[str],
    sort_by: str,
    filter_mode: str,
    remote_library_data: dict[str, dict[str, Any]],
    library_configs: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Combine local cached smart rows with live in-memory remote library items."""
    configs = library_configs if library_configs is not None else app_config.libraries
    effective_libraries = (
        list(library_names) if library_names else list(configs.keys())
    )
    remote_libraries = [
        name
        for name in effective_libraries
        if configs.get(name, {}).get("management_type") == "remote"
    ]
    local_libraries = [
        name for name in effective_libraries if name not in remote_libraries
    ]

    combined_items: list[dict[str, Any]] = []
    if local_libraries:
        combined_items.extend(
            db.get_cached_smart_rows(local_libraries, sort_by, filter_mode)
        )
    if remote_libraries:
        combined_items.extend(
            compute_smart_rows_from_memory(
                library_items_by_name=remote_library_data,
                library_configs=configs,
                library_names=remote_libraries,
                sort_by=sort_by,
                filter_mode=filter_mode,
            )
        )

    if local_libraries and remote_libraries:
        _sort_smart_row_items(combined_items, sort_by)
    return combined_items


class SmartRowService:
    """Coordinates smart row cache rebuilds in response to application events.

    Handles incremental updates for watched events and full rebuilds for scans,
    ensuring the combined view cache stays fresh without blocking the UI thread.
    """

    def __init__(
        self,
    ) -> None:
        self._cache_lock: threading.Lock = threading.Lock()

    def on_episode_watched(self, file_path: str) -> list[str]:
        """Handle episode watched event by performing incremental cache update.

        Returns the list of config_hashes that were updated, so the caller
        can emit targeted signals for UI updates.
        """
        logger.debug(
            f"SmartRowService: episode watched at '{file_path}', "
            f"performing incremental update"
        )
        affected_libraries = self._resolve_libraries_for_path(file_path)
        if affected_libraries:
            return self._rebuild_affected_configs(affected_libraries)
        return []

    def rebuild_for_libraries(self, library_names: list[str]) -> list[str]:
        """Rebuild smart row cache entries that reference the given libraries.

        Returns the list of config_hashes that were updated.
        """
        logger.info(f"SmartRowService: rebuilding cache for libraries {library_names}")
        return self._rebuild_affected_configs(library_names)

    def _rebuild_affected_configs(self, library_names: list[str]) -> list[str]:
        """Rebuild only the smart row configs that reference the given libraries.

        Config is loaded by get_affected_config_hashes_for_libraries, so
        no explicit load() is needed here.

        Thread-safe — serializes cache rebuild operations via a lock so that
        background PostScanWorker invocations do not race with main-thread
        watched-event updates or settings changes.
        """
        with self._cache_lock:
            config_hashes = db.get_affected_config_hashes_for_libraries(library_names)
            if not config_hashes:
                logger.debug(
                    f"SmartRowService: no configs found for libraries {library_names}"
                )
                return []

            local_library_names = [
                name
                for name in library_names
                if app_config.libraries.get(name, {}).get("management_type") != "remote"
            ]
            if not local_library_names:
                return config_hashes

            for row_config in app_config.combined_views:
                if not row_config.get("enabled", True):
                    continue
                row_libraries = row_config.get("libraries", [])
                if row_libraries and not any(
                    lib in local_library_names for lib in row_libraries
                ):
                    continue
                libraries = row_config.get("libraries", [])
                sort_by = row_config.get("sort_by", "Alphabetical")
                filter_mode = row_config.get("filter_mode", "All")
                config_hash = db.compute_config_hash(libraries, sort_by, filter_mode)
                if config_hash in config_hashes:
                    local_row_libraries = [
                        lib
                        for lib in (libraries or local_library_names)
                        if app_config.libraries.get(lib, {}).get("management_type")
                        != "remote"
                    ]
                    if local_row_libraries or not libraries:
                        db.rebuild_cache_for_config(libraries, sort_by, filter_mode)

            return config_hashes

    def _resolve_libraries_for_path(self, file_path: str) -> list[str]:
        """Determine which libraries contain the given file path."""
        try:
            from sqlalchemy import select

            from lan_streamer.db.connection import get_session
            from lan_streamer.db.models import (
                Episode,
                MediaFile,
                MetadataFileMapping,
                Movie,
            )

            with get_session() as session:
                media_file = session.scalars(
                    select(MediaFile).where(MediaFile.path == file_path)
                ).first()

                if not media_file:
                    try:
                        from lan_streamer.services.path_mapping_service import (
                            map_local_path_to_remote,
                            map_remote_path_to_local,
                        )
                        from lan_streamer.system.config import (
                            config,
                            get_library_sources,
                        )

                        for library_configuration in config.libraries.values():
                            mount_mappings = dict(
                                library_configuration.get("mount_mappings", {})
                            )
                            for source_entry in get_library_sources(
                                library_configuration
                            ):
                                if "mount_mappings" in source_entry:
                                    mount_mappings.update(
                                        source_entry.get("mount_mappings", {})
                                    )
                            if not mount_mappings:
                                continue

                            remote_candidate = map_local_path_to_remote(
                                file_path, mount_mappings
                            )
                            if remote_candidate != file_path:
                                media_file = session.scalars(
                                    select(MediaFile).where(
                                        MediaFile.path == remote_candidate
                                    )
                                ).first()
                                if media_file:
                                    break

                            local_candidate = map_remote_path_to_local(
                                file_path, mount_mappings
                            )
                            if local_candidate != file_path:
                                media_file = session.scalars(
                                    select(MediaFile).where(
                                        MediaFile.path == local_candidate
                                    )
                                ).first()
                                if media_file:
                                    break
                    except KeyError, ValueError, TypeError, OSError, AttributeError:
                        logger.debug(
                            "Failed checking mount mappings in smart row service for '%s'",
                            file_path,
                        )

                if not media_file:
                    return []

                libraries = set()
                mapping = session.scalars(
                    select(MetadataFileMapping).where(
                        MetadataFileMapping.media_file_id == media_file.id
                    )
                ).first()
                if not mapping:
                    return []

                if mapping.episode_id:
                    episode = session.get(Episode, mapping.episode_id)
                    if episode and episode.season and episode.season.series:
                        series = episode.season.series
                        if series.library_name:
                            libraries.add(series.library_name)

                if mapping.movie_id:
                    movie = session.get(Movie, mapping.movie_id)
                    if movie and movie.library_name:
                        libraries.add(movie.library_name)

                return list(libraries)
        except Exception:
            logger.exception(
                f"SmartRowService: failed to resolve libraries for path '{file_path}'"
            )
            return []
