import logging
from typing import List, Optional, Callable, Any

from lan_streamer import db
from lan_streamer.system.config import config as app_config

logger = logging.getLogger(__name__)


class SmartRowService:
    """Coordinates smart row cache rebuilds in response to application events.

    Handles incremental updates for watched events and full rebuilds for scans,
    ensuring the combined view cache stays fresh without blocking the UI thread.
    """

    def __init__(
        self,
        background_runner: Optional[Callable[[Callable[[], Any]], Any]] = None,
    ) -> None:
        self._background_runner = background_runner

    def on_scan_completed(self, affected_libraries: Optional[List[str]] = None) -> None:
        """Handle scan completion by rebuilding the smart row cache.

        If affected_libraries is provided, only rebuilds configs that reference
        those libraries. Otherwise rebuilds all enabled configs.
        """
        logger.info(
            f"SmartRowService: scan completed, rebuilding cache for "
            f"libraries={affected_libraries or 'all'}"
        )
        if self._background_runner:
            self._background_runner(lambda: self._rebuild(affected_libraries))
        else:
            self._rebuild(affected_libraries)

    def on_episode_watched(self, file_path: str) -> List[str]:
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

    def on_movie_watched(self, movie_name: str, library_name: str) -> List[str]:
        """Handle movie watched event by performing incremental cache update."""
        logger.debug(
            f"SmartRowService: movie '{movie_name}' watched in library "
            f"'{library_name}', performing incremental update"
        )
        return self._rebuild_affected_configs([library_name])

    def rebuild_for_libraries(self, library_names: List[str]) -> List[str]:
        """Rebuild smart row cache entries that reference the given libraries.

        Returns the list of config_hashes that were updated.
        """
        logger.info(f"SmartRowService: rebuilding cache for libraries {library_names}")
        return self._rebuild_affected_configs(library_names)

    def on_libraries_changed(self) -> None:
        """Rebuild all cache entries when library configuration changes."""
        logger.info(
            "SmartRowService: library configuration changed, rebuilding all cache"
        )
        if self._background_runner:
            self._background_runner(lambda: db.rebuild_all_cache())
        else:
            db.rebuild_all_cache()

    def _rebuild(self, affected_libraries: Optional[List[str]] = None) -> None:
        """Internal: rebuild cache, optionally scoped to specific libraries.

        Delegates to _rebuild_affected_configs which handles deduplication
        and scoping internally. For full rebuilds, calls rebuild_all_cache.
        """
        try:
            if affected_libraries:
                self._rebuild_affected_configs(affected_libraries)
            else:
                db.rebuild_all_cache()
        except Exception:
            logger.exception("SmartRowService: failed to rebuild cache")

    def _rebuild_affected_configs(self, library_names: List[str]) -> List[str]:
        """Rebuild only the smart row configs that reference the given libraries.

        Config is loaded by get_affected_config_hashes_for_libraries, so
        no explicit load() is needed here.
        """
        config_hashes = db.get_affected_config_hashes_for_libraries(library_names)
        if not config_hashes:
            logger.debug(
                f"SmartRowService: no configs found for libraries {library_names}"
            )
            return []

        for row_config in app_config.combined_views:
            if not row_config.get("enabled", True):
                continue
            row_libraries = row_config.get("libraries", [])
            if row_libraries and not any(lib in library_names for lib in row_libraries):
                continue
            libraries = row_config.get("libraries", [])
            sort_by = row_config.get("sort_by", "Alphabetical")
            filter_mode = row_config.get("filter_mode", "All")
            config_hash = db.compute_config_hash(libraries, sort_by, filter_mode)
            if config_hash in config_hashes:
                db.rebuild_cache_for_config(libraries, sort_by, filter_mode)

        return config_hashes

    def _resolve_libraries_for_path(self, file_path: str) -> List[str]:
        """Determine which libraries contain the given file path."""
        try:
            from lan_streamer.db.connection import get_session
            from lan_streamer.db.models import (
                MediaFile,
                MetadataFileMapping,
                Episode,
                Movie,
            )
            from sqlalchemy import select

            with get_session() as session:
                media_file = session.scalars(
                    select(MediaFile).where(MediaFile.path == file_path)
                ).first()
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
