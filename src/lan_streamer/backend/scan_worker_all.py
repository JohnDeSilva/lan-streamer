import asyncio
import concurrent.futures
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal
from sqlalchemy.exc import SQLAlchemyError

from lan_streamer import db
from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.backend.database_writer import AsyncDatabaseWriter
from lan_streamer.backend.scan_worker_base import (
    create_empty_stats,
    log_db_write_error,
    log_issues_report,
    log_stats_breakdown,
    merge_stats_dicts,
    series_belongs_to_root,
)
from lan_streamer.providers.jellyfin import jellyfin_client
from lan_streamer.scanner import (
    VIDEO_EXTENSIONS,
    has_video_files,
    scan_directories,
)
from lan_streamer.system.async_utils import run_in_executor, run_in_fs_executor
from lan_streamer.system.config import config

if TYPE_CHECKING:
    from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger("lan_streamer.backend")

LIFECYCLE_EVENTS = frozenset(
    {
        "init_tree",
        "init_library_scan",
        "start_offline_scan",
        "start_metadata_resolution",
        "start_library",
        "fail_library",
        "finish_library",
        "start_root",
        "finish_root",
        "unavailable_root",
    }
)


@dataclass
class _ScanPassContext:
    """Thread-local accumulation state shared across per-item scan callbacks.

    Callbacks are invoked from thread-pool worker threads, so all mutable
    accumulators are protected by a single per-library lock.
    """

    library_name: str
    library_type: str
    writer: AsyncDatabaseWriter
    loop: asyncio.AbstractEventLoop
    stats: dict[str, int] = field(default_factory=create_empty_stats)
    problems: list[dict[str, Any]] = field(default_factory=list)
    changed_season_ids: set[str] = field(default_factory=set)
    changed_movie_ids: set[str] = field(default_factory=set)
    series_scanned: set[str] = field(default_factory=set)
    unavailable_directories: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ScanAllLibrariesWorker(AsyncWorkerBase):
    """Scans all configured libraries in parallel using TMDB for metadata.

    Libraries are scanned concurrently within each pass using a
    `ThreadPoolExecutor`.  Pass 1 performs offline file discovery; Pass 2
    resolves online metadata.  Results from each thread-pool task are merged
    into shared state under a lock.
    """

    library_progress = Signal(str, int, int)
    detail_progress = Signal(str, dict)  # (event_type, payload)
    detail_progress_batch = Signal(list)
    error = Signal(str)
    library_error = Signal(str, str)  # (library_name, error_message)

    def __init__(
        self,
        async_task_manager: AsyncTaskManager | None = None,
        force_refresh: bool = False,
        run_pass1: bool = True,
        run_pass2: bool = True,
        scan_archive_roots: bool = True,
        parent: QObject | None = None,
    ) -> None:
        """Initialise the scan-all-libraries worker."""
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.force_refresh: bool = force_refresh
        self.run_pass1: bool = run_pass1
        self.run_pass2: bool = run_pass2
        self.scan_archive_roots: bool = scan_archive_roots

        # Shared mutable state — protected by _lock when accessed from threads.
        self._lock = threading.Lock()
        self._detail_progress_buffer: list[dict[str, Any]] = []

        self.unavailable_directories: list[str] = []
        self.problems: list[dict[str, Any]] = []
        self.stats: dict[str, int] = create_empty_stats()
        self.changed_season_ids: set[str] = set()
        self.changed_movie_ids: set[str] = set()
        self.current_pass: int = 1

        # Per-pass statistics dict: self.pass_stats[1] = Pass 1 stats, [2] = Pass 2 stats.
        self.pass_stats: dict[int, dict[str, int]] = {}

        # Per-library per-pass statistics: self.pass_stats_per_library[name][1] = Pass 1 stats.
        self.pass_stats_per_library: dict[str, dict[int, dict[str, int]]] = {}

        # Libraries that had any add/update activity during the scan (for
        # incremental cache rebuild — Proposal H).
        self.changed_libraries: set[str] = set()

        # Database writer and event loop — created in run_async() for each scan.
        self._database_writer: AsyncDatabaseWriter | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None

    def emit_detail_progress(self, event: str, payload: dict[str, Any]) -> None:
        """Add a progress event to the thread-safe buffer and emit if full."""
        flush_needed = False
        with self._lock:
            self._detail_progress_buffer.append({"event": event, "payload": payload})
            if len(self._detail_progress_buffer) >= 20:
                flush_needed = True
        if flush_needed:
            self.flush_detail_progress()

    def flush_detail_progress(self) -> None:
        """Force flush all buffered detail-progress events to the UI."""
        with self._lock:
            if not self._detail_progress_buffer:
                return
            batch = list(self._detail_progress_buffer)
            self._detail_progress_buffer.clear()
        self.detail_progress_batch.emit(batch)

    def isInterruptionRequested(self) -> bool:
        return self._cancelled

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _log_per_library_scan_report(
        library_name: str,
        paths_str: str,
        stats_dict: dict[str, Any],
        status_notes: list[str] | None = None,
    ) -> None:
        """Log an individual library scan report with accumulated stats.

        Args:
            library_name: Name of the library being reported.
            paths_str: Comma-separated library paths.
            stats_dict: Accumulated statistics dictionary for this library.
            status_notes: Optional list of per-pass status messages
                (e.g. ``"Pass 1 FAILED"``).
        """
        logger.info(f"[SCAN_REPORT] --- Per-Library Report: {library_name} ---")
        logger.info(f"[SCAN_REPORT]   Paths=[{paths_str}]")
        if status_notes:
            for note in status_notes:
                logger.info(f"[SCAN_REPORT]   ** {note} **")
        logger.info(
            f"[SCAN_REPORT]   Series: Scanned={stats_dict.get('series_scanned', 0)} | "
            f"Added={stats_dict.get('series_added', 0)} | "
            f"Updated={stats_dict.get('series_updated', 0)} | "
            f"Removed={stats_dict.get('series_removed', 0)} | "
            f"Skipped={stats_dict.get('series_skipped', 0)}"
        )
        logger.info(
            f"[SCAN_REPORT]   Seasons: Scanned={stats_dict.get('seasons_scanned', 0)} | "
            f"Added={stats_dict.get('seasons_added', 0)} | "
            f"Updated={stats_dict.get('seasons_updated', 0)} | "
            f"Removed={stats_dict.get('seasons_removed', 0)} | "
            f"Skipped={stats_dict.get('seasons_skipped', 0)}"
        )
        logger.info(
            f"[SCAN_REPORT]   Episodes: Scanned={stats_dict.get('episodes_scanned', 0)} | "
            f"Added={stats_dict.get('episodes_added', 0)} | "
            f"Updated={stats_dict.get('episodes_updated', 0)} | "
            f"Removed={stats_dict.get('episodes_removed', 0)} | "
            f"Skipped={stats_dict.get('episodes_skipped', 0)}"
        )
        logger.info(
            f"[SCAN_REPORT]   Movies: Scanned={stats_dict.get('movies_scanned', 0)} | "
            f"Added={stats_dict.get('movies_added', 0)} | "
            f"Updated={stats_dict.get('movies_updated', 0)} | "
            f"Removed={stats_dict.get('movies_removed', 0)} | "
            f"Skipped={stats_dict.get('movies_skipped', 0)}"
        )

    def _log_scan_summary(
        self, duration: float, libraries_dictionary: dict[str, dict[str, Any]]
    ) -> None:
        """Log the combined scan summary with per-library and pass totals.

        Args:
            duration: Total elapsed scan time in seconds.
            libraries_dictionary: The full libraries configuration dict.
        """
        logger.info("[SCAN_REPORT] ===================================================")
        logger.info("[SCAN_REPORT]               SCAN RUN STATS REPORT")
        logger.info("[SCAN_REPORT] ===================================================")
        logger.info("")

        # Per-library reports (accumulated stats merged from both passes)
        for library_name, library_configuration in libraries_dictionary.items():
            paths_str = ", ".join(library_configuration.get("paths", []))
            per_lib = self.pass_stats_per_library.get(library_name, {})
            pass1_stats = per_lib.get(1, {})
            pass2_stats = per_lib.get(2, {})
            # Compute accumulated stats correctly: sum non-scanned/skipped keys,
            # use max for scanned/skipped keys (since they track unique entities)
            accumulated_stats = {}
            all_keys = set(pass1_stats.keys()) | set(pass2_stats.keys())
            for key in all_keys:
                if key.endswith(("_scanned", "_skipped")):
                    # Use max to avoid double-counting unique entities across passes
                    accumulated_stats[key] = max(
                        pass1_stats.get(key, 0), pass2_stats.get(key, 0)
                    )
                else:
                    # Sum other keys (added, updated, removed)
                    accumulated_stats[key] = pass1_stats.get(key, 0) + pass2_stats.get(
                        key, 0
                    )
            status_notes: list[str] = []
            if pass1_stats.get("_skipped"):
                status_notes.append("Pass 1 FAILED — no offline data")
            if pass2_stats.get("_skipped"):
                status_notes.append("Pass 2 FAILED — skipping metadata resolution")
            self._log_per_library_scan_report(
                library_name,
                paths_str,
                accumulated_stats,
                status_notes or None,
            )
        logger.info("[SCAN_REPORT] ---------------------------------------------------")

        logger.info(f"[SCAN_REPORT] Total Scan Duration: {duration:.2f} seconds")
        logger.info(f"[SCAN_REPORT] Libraries Scanned: {len(libraries_dictionary)}")
        if self.unavailable_directories:
            logger.info(
                "[SCAN_REPORT] Unavailable Root Directories: "
                f"{', '.join(self.unavailable_directories)}"
            )
        logger.info("[SCAN_REPORT] ---------------------------------------------------")

        # Combined pass totals
        log_stats_breakdown(
            "PASS 1: OFFLINE FILE DISCOVERY BREAKDOWN (PASS 1)",
            self.pass_stats.get(1, {}),
            logger,
        )
        logger.info("[SCAN_REPORT] ---------------------------------------------------")
        log_stats_breakdown(
            "PASS 2: ONLINE METADATA RESOLUTION BREAKDOWN (PASS 2)",
            self.pass_stats.get(2, {}),
            logger,
        )
        logger.info("[SCAN_REPORT] ---------------------------------------------------")
        log_stats_breakdown("TOTAL ACCUMULATED RUN STATS", self.stats, logger)
        logger.info("[SCAN_REPORT] ===================================================")

    # ------------------------------------------------------------------
    # Per-library scanning logic (runs inside thread pool workers)
    # ------------------------------------------------------------------

    def _scan_library_pass(
        self,
        library_name: str,
        library_configuration: dict[str, Any],
        existing_library_data: dict[str, Any],
        jellyfin_data: dict[str, Any] | None,
        pass_number: int,
        tmdb_prefetch_executor: concurrent.futures.ThreadPoolExecutor | None = None,
    ) -> dict[str, Any]:
        """Execute one scan pass for a single library inside a thread-pool worker.

        Args:
            library_name: Name of the library to scan.
            library_configuration: Configuration dict for the library.
            existing_library_data: Previously persisted library data.
            jellyfin_data: Jellyfin correlation data (``None`` for Pass 1).
            pass_number: Which pass (1, 2, or 3).
            tmdb_prefetch_executor: Shared thread-pool executor for TMDB
                pre-fetch calls (Pass 2 only).

        Returns:
            A dictionary with the following keys:
            ``library_name``, ``library_data``, ``pass_stats``, ``problems``,
            ``unavailable_directories``, ``changed_season_ids``, ``changed_movie_ids``.
        """
        all_root_directories: list[str] = list(library_configuration.get("paths", []))
        archive_root_directories: set[str] = set(
            library_configuration.get("archive_paths", [])
        )
        if not self.scan_archive_roots:
            root_directories: list[str] = [
                path
                for path in all_root_directories
                if path not in archive_root_directories
            ]
        else:
            root_directories = all_root_directories
        library_type: str = library_configuration.get("type", "tv")
        show_future_episodes: bool = library_configuration.get(
            "show_future_episodes", True
        )

        # _database_writer and _event_loop are set by run_async() before this method is called
        writer = self._database_writer
        loop = self._event_loop
        assert writer is not None
        assert loop is not None

        # Thread-local accumulators shared by the callback helpers below.
        # The lock protects them because folder-level parallel scan submits
        # scan_series/scan_movie as futures to the global executor, and those
        # futures invoke the callbacks from folder-pool threads.
        context = _ScanPassContext(
            library_name=library_name,
            library_type=library_type,
            writer=writer,
            loop=loop,
        )

        self.emit_detail_progress("start_library", {"library": library_name})

        # ------------------------------------------------------------------
        # Callback closures — delegate to thread-safe helper methods
        # ------------------------------------------------------------------

        def _detail_callback(event: str, payload: dict[str, Any]) -> None:
            enriched: dict[str, Any] = {"library": library_name, **payload}
            self.emit_detail_progress(event, enriched)

        def _season_callback(
            series_name: str,
            series_data: dict[str, Any],
            season_name: str,
            season_data: dict[str, Any],
        ) -> None:
            self._process_season_callback(
                context,
                series_name,
                series_data,
                season_name,
                season_data,
            )

        def _movie_callback(movie_name: str, movie_data: dict[str, Any]) -> None:
            self._process_movie_callback(context, movie_name, movie_data)

        def _save_library_data(library_data: dict[str, Any]) -> None:
            self._process_save_library(context, library_data)

        # ------------------------------------------------------------------
        # Execute the scan
        # ------------------------------------------------------------------

        if not root_directories:
            # No root directories — scan with empty path list to trigger
            # cleanup-only logic.
            updated_library_data = scan_directories(
                [],
                library_type=library_type,
                existing_library=existing_library_data,
                jellyfin_data=jellyfin_data if pass_number == 2 else None,
                force_refresh=self.force_refresh,
                detail_callback=_detail_callback,
                show_future_episodes=show_future_episodes,
                season_callback=_season_callback,
                movie_callback=_movie_callback,
                is_interrupted=self.isInterruptionRequested,
                tmdb_prefetch_executor=tmdb_prefetch_executor,
                pass_number=pass_number,
            )
            self._record_unavailable_directories(
                context, library_name, pass_number, updated_library_data
            )
            if self.isInterruptionRequested():
                raise InterruptedError("Scan interrupted.")
            _save_library_data(updated_library_data)
            current_library_data: dict[str, Any] = updated_library_data
        else:
            current_library_data = existing_library_data
            for root_dir in root_directories:
                if self.isInterruptionRequested():
                    logger.info(
                        "ScanAllLibrariesWorker: interruption requested. Stopping root directories loop."
                    )
                    break
                self.emit_detail_progress(
                    "start_root",
                    {"library": library_name, "root": root_dir},
                )
                updated_library_data = scan_directories(
                    [root_dir],
                    library_type=library_type,
                    existing_library=current_library_data,
                    jellyfin_data=jellyfin_data if pass_number == 2 else None,
                    force_refresh=self.force_refresh,
                    detail_callback=_detail_callback,
                    show_future_episodes=show_future_episodes,
                    season_callback=_season_callback,
                    movie_callback=_movie_callback,
                    is_interrupted=self.isInterruptionRequested,
                    tmdb_prefetch_executor=tmdb_prefetch_executor,
                    pass_number=pass_number,
                )
                if self.isInterruptionRequested():
                    raise InterruptedError("Scan interrupted.")
                self._record_unavailable_directories(
                    context, library_name, pass_number, updated_library_data
                )
                current_library_data = updated_library_data
                _save_library_data(updated_library_data)

                # Finish-root is only emitted in Pass 2 (metadata resolution).
                if pass_number == 2:
                    self.emit_detail_progress(
                        "finish_root",
                        {"library": library_name, "root": root_dir},
                    )

        return {
            "library_name": library_name,
            "library_data": current_library_data,
            "pass_stats": context.stats,
            "problems": context.problems,
            "unavailable_directories": context.unavailable_directories,
            "changed_season_ids": context.changed_season_ids,
            "changed_movie_ids": context.changed_movie_ids,
        }

    def _record_unavailable_directories(
        self,
        context: _ScanPassContext,
        library_name: str,
        pass_number: int,
        updated_library_data: Any,
    ) -> None:
        """Collect unavailable directories from a scan result and, in Pass 1,
        log them as scan issues once."""
        for root in updated_library_data.unavailable_directories:
            context.unavailable_directories.append(root)
            if pass_number == 1:
                error_message: str = (
                    f"Root directory '{root}' in library "
                    f"'{library_name}' is unavailable on filesystem."
                )
                logger.warning(
                    "[SCAN_ISSUE] Type=Unavailable Directory | "
                    f"Item={root} (Library: '{library_name}') | "
                    f"Error={error_message}"
                )
                context.problems.append(
                    {
                        "type": "Unavailable Directory",
                        "item": (f"{root} (Library: '{library_name}')"),
                        "error": error_message,
                    }
                )

    def _process_season_callback(
        self,
        context: _ScanPassContext,
        series_name: str,
        series_data: dict[str, Any],
        season_name: str,
        season_data: dict[str, Any],
    ) -> None:
        """Process a single season during scanning, persisting it to the
        database and accumulating local statistics."""
        logger.info(
            f"ScanAllLibrariesWorker writing season "
            f"'{season_name}' of series '{series_name}' to database..."
        )
        try:
            season_payload = {
                "library_name": context.library_name,
                "series_name": series_name,
                "series_data": series_data,
                "season_name": season_name,
                "season_data": season_data,
            }
            task = context.writer.sync_submit(
                "save_season", season_payload, context.loop
            )
            if task.error:
                raise task.error
            stats = task.result
            if stats:
                series_id = stats.get("series_id") or series_name
                is_new_series_scan = False

                with context.lock:
                    if "issues" in stats:
                        for issue in stats["issues"]:
                            context.problems.append(issue)

                    # Track series-level scan (first season encountered)
                    if series_name not in context.series_scanned:
                        context.series_scanned.add(series_name)
                        context.stats["series_scanned"] += 1
                        is_new_series_scan = True

                        any_changed = any(
                            season_data_item.get("_changed", True)
                            for season_data_item in series_data.get(
                                "seasons", {}
                            ).values()
                        )
                        if not any_changed:
                            context.stats["series_skipped"] += 1

                    context.stats["seasons_scanned"] += 1
                    episode_count: int = len(season_data.get("episodes", []))
                    context.stats["episodes_scanned"] += episode_count

                    if not season_data.get("_changed", True):
                        context.stats["seasons_skipped"] += 1
                        context.stats["episodes_skipped"] += episode_count
                    else:
                        added = stats.get("episodes_added", 0)
                        updated = stats.get("episodes_updated", 0)
                        skipped = max(0, episode_count - added - updated)
                        context.stats["episodes_skipped"] += skipped

                    # Add/update/remove counts from db return value
                    for key in context.stats:
                        if key in stats and not (
                            key.endswith(("_scanned", "_skipped"))
                        ):
                            context.stats[key] += stats[key]

                    if season_data.get("_changed", True) and "season_id" in stats:
                        context.changed_season_ids.add(stats["season_id"])

                # Fetch cast/crew and images for newly scanned series
                if is_new_series_scan and stats.get("series_id"):
                    self._fetch_series_cast_images(
                        context, series_name, series_data, series_id, stats
                    )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            SQLAlchemyError,
        ) as error:
            with context.lock:
                log_db_write_error(
                    context.problems,
                    f"Season '{season_name}' of series "
                    f"'{series_name}' (Library: '{context.library_name}')",
                    error,
                    logger,
                )

    def _fetch_series_cast_images(
        self,
        context: _ScanPassContext,
        series_name: str,
        series_data: dict[str, Any],
        series_id: str,
        stats: dict[str, Any],
    ) -> None:
        """Fetch cast/crew and images for a newly scanned series if needed."""
        tmdb_id = series_data.get("metadata", {}).get("tmdb_identifier")
        if not tmdb_id:
            return
        try:
            has_cast = len(db.get_cast_for_series(series_id)) > 0
            if self.force_refresh or stats.get("series_added", 0) > 0 or not has_cast:
                task_credits = context.writer.sync_submit(
                    "fetch_and_store_series_credits_and_images",
                    {
                        "series_id": series_id,
                        "tmdb_id": int(tmdb_id),
                    },
                    context.loop,
                )
                if task_credits.error:
                    raise task_credits.error
                logger.info(
                    "Fetched cast and images for series '%s'",
                    series_name,
                )
            else:
                logger.info(
                    "Skipping cast/image fetch for series '%s' (cached)",
                    series_name,
                )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            SQLAlchemyError,
        ) as fetch_error:
            logger.warning(
                "Failed to fetch cast/images for series '%s': %s",
                series_name,
                fetch_error,
            )

    def _process_movie_callback(
        self,
        context: _ScanPassContext,
        movie_name: str,
        movie_data: dict[str, Any],
    ) -> None:
        """Process a single movie during scanning, persisting it to the
        database and accumulating local statistics."""
        logger.info(
            f"ScanAllLibrariesWorker writing movie '{movie_name}' to database..."
        )
        try:
            movie_payload = {
                "library_name": context.library_name,
                "movie_name": movie_name,
                "movie_data": movie_data,
            }
            task = context.writer.sync_submit("save_movie", movie_payload, context.loop)
            if task.error:
                raise task.error
            stats = task.result
            if stats:
                with context.lock:
                    if "issues" in stats:
                        for issue in stats["issues"]:
                            context.problems.append(issue)

                    context.stats["movies_scanned"] += 1

                    if not movie_data.get("_changed", True):
                        context.stats["movies_skipped"] += 1

                    for key in context.stats:
                        if key in stats and not (
                            key.endswith(("_scanned", "_skipped"))
                        ):
                            context.stats[key] += stats[key]

                    if movie_data.get("_changed", True) and "movie_id" in stats:
                        context.changed_movie_ids.add(stats["movie_id"])

                # Fetch cast/crew and images for newly scanned movie
                if stats.get("movie_id"):
                    self._fetch_movie_cast_images(
                        context, movie_name, movie_data, stats
                    )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            SQLAlchemyError,
        ) as error:
            with context.lock:
                log_db_write_error(
                    context.problems,
                    f"Movie '{movie_name}' (Library: '{context.library_name}')",
                    error,
                    logger,
                )

    def _fetch_movie_cast_images(
        self,
        context: _ScanPassContext,
        movie_name: str,
        movie_data: dict[str, Any],
        stats: dict[str, Any],
    ) -> None:
        """Fetch cast/crew and images for a newly scanned movie if needed."""
        tmdb_id = movie_data.get("tmdb_identifier")
        if not tmdb_id:
            tmdb_id = movie_data.get("metadata", {}).get("tmdb_identifier")
        if not tmdb_id:
            return
        try:
            movie_id = stats["movie_id"]
            has_cast = len(db.get_cast_for_movie(movie_id)) > 0
            if self.force_refresh or stats.get("movies_added", 0) > 0 or not has_cast:
                task_credits = context.writer.sync_submit(
                    "fetch_and_store_movie_credits_and_images",
                    {
                        "movie_id": movie_id,
                        "tmdb_id": int(tmdb_id),
                    },
                    context.loop,
                )
                if task_credits.error:
                    raise task_credits.error
                logger.info(
                    "Fetched cast and images for movie '%s'",
                    movie_name,
                )
            else:
                logger.info(
                    "Skipping cast/image fetch for movie '%s' (cached)",
                    movie_name,
                )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            SQLAlchemyError,
        ) as fetch_error:
            logger.warning(
                "Failed to fetch cast/images for movie '%s': %s",
                movie_name,
                fetch_error,
            )

    def _process_save_library(
        self, context: _ScanPassContext, library_data: dict[str, Any]
    ) -> None:
        """Persist the full library data to the database.

        Only ``_removed`` and ``deleted`` keys from the return value are
        counted here since additions/updates are already accounted for in
        the per-item callbacks above.
        """
        try:
            action = (
                "save_movie_library"
                if context.library_type == "movie"
                else "save_library"
            )
            library_payload = {
                "library_name": context.library_name,
                "library_data": library_data,
            }
            task = context.writer.sync_submit(action, library_payload, context.loop)
            if task.error:
                raise task.error
            stats = task.result
            if stats:
                with context.lock:
                    if "issues" in stats:
                        for issue in stats["issues"]:
                            context.problems.append(issue)
                    for key in context.stats:
                        if key in stats and (
                            key.endswith("_removed") or key == "deleted"
                        ):
                            context.stats[key] += stats[key]
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            SQLAlchemyError,
        ) as error:
            with context.lock:
                log_db_write_error(
                    context.problems,
                    f"Library '{context.library_name}'",
                    error,
                    logger,
                )

    # ------------------------------------------------------------------
    # Tree discovery
    # ------------------------------------------------------------------

    def _discover_single_library_tree(
        self,
        library_name: str,
        library_configuration: dict[str, Any],
        existing_library_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Pre-walk directories of a single library to build its tree structure.

        Args:
            library_name: The name of the library.
            library_configuration: Configuration dictionary for the library.
            existing_library_data: Previously loaded library data to avoid I/O.

        Returns:
            A dictionary containing library type and its roots.
        """
        all_root_directories: list[str] = list(library_configuration.get("paths", []))
        archive_root_directories: set[str] = set(
            library_configuration.get("archive_paths", [])
        )
        if not self.scan_archive_roots:
            root_directories: list[str] = [
                path
                for path in all_root_directories
                if path not in archive_root_directories
            ]
        else:
            root_directories = all_root_directories
        library_type: str = library_configuration.get("type", "tv")
        # Build the detailed tree structure (with seasons/episodes) from the
        # existing library data if available; otherwise fall back to filesystem.
        detailed_roots: dict[str, Any] = {}
        for root_dir in root_directories:
            if existing_library_data:
                # Build from existing data
                detailed_roots[root_dir] = {}
                for series_name, series_data in existing_library_data.items():
                    if series_belongs_to_root(series_data, root_dir, library_type):
                        if library_type in ("tv", "anime"):
                            seasons: dict[str, list[str]] = {}
                            for season_name, season_data in series_data.get(
                                "seasons", {}
                            ).items():
                                episodes = [
                                    ep.get("name", "")
                                    for ep in season_data.get("episodes", [])
                                    if ep.get("name")
                                ]
                                seasons[season_name] = sorted(episodes)
                            detailed_roots[root_dir][series_name] = {"seasons": seasons}
                        else:
                            detailed_roots[root_dir][series_name] = {}
            else:
                # Fallback to filesystem
                root_path = Path(root_dir)
                if not root_path.exists() or not root_path.is_dir():
                    detailed_roots[root_dir] = {}
                    continue
                detailed_roots[root_dir] = {}
                for series_path in sorted(
                    [
                        x
                        for x in root_path.iterdir()
                        if x.is_dir()
                        and not x.name.startswith(".")
                        and has_video_files(x)
                    ],
                    key=lambda x: x.stat().st_mtime,
                    reverse=True,
                ):
                    series_name = series_path.name
                    if library_type in ("tv", "anime"):
                        seasons: dict[str, list[str]] = {}
                        for season_path in series_path.iterdir():
                            if season_path.is_dir() and not season_path.name.startswith(
                                "."
                            ):
                                episodes: list[str] = []
                                for episode_path in season_path.iterdir():
                                    if (
                                        episode_path.is_file()
                                        and episode_path.suffix.lower()
                                        in VIDEO_EXTENSIONS
                                    ):
                                        episodes.append(episode_path.name)
                                seasons[season_path.name] = sorted(episodes)
                        detailed_roots[root_dir][series_name] = {"seasons": seasons}
                    else:
                        detailed_roots[root_dir][series_name] = {}
        return {"type": library_type, "roots": detailed_roots}

    async def _discover_tree(
        self, library_data_by_name: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Pre-walk all library directories to count total folders and files in parallel.

        This allows the UI to initialise the tree and segmented progress bar
        before scanning begins.

        Args:
            library_data_by_name: Existing library data loaded from database.

        Returns:
            A nested dictionary keyed by library name.
        """
        libraries_dictionary: dict[str, dict[str, Any]] = config.libraries
        tasks = []
        for library_name, library_configuration in libraries_dictionary.items():
            existing_data = library_data_by_name.get(library_name, {})
            coro = run_in_fs_executor(
                self._discover_single_library_tree,
                library_name,
                library_configuration,
                existing_data,
            )
            tasks.append((asyncio.create_task(coro), library_name))

        tree: dict[str, Any] = {}
        for task, library_name in tasks:
            try:
                tree[library_name] = await task
            except Exception:
                logger.exception(f"Tree discovery failed for library: {library_name}")
                tree[library_name] = {
                    "type": config.libraries[library_name].get("type", "tv"),
                    "roots": {},
                }
        return tree

    # ------------------------------------------------------------------
    # Main execution entrypoint (runs as an asyncio task)
    # ------------------------------------------------------------------

    async def run_async(self) -> None:
        """Execute the full scan run with parallel library scanning."""
        start_time = time.time()
        self.problems = []
        self.stats = create_empty_stats()
        self.pass_stats = {1: create_empty_stats(), 2: create_empty_stats()}
        self.pass_stats_per_library = {}
        self.changed_libraries = set()
        self.changed_season_ids = set()
        self.changed_movie_ids = set()
        self.current_pass = 1

        # Create the database writer and capture event loop for sync_submit
        self._database_writer = AsyncDatabaseWriter()
        self._event_loop = asyncio.get_running_loop()

        # Create the TMDB pre-fetch executor for the duration of this scan run.
        # It is shared across all libraries in both passes to avoid creating and
        # destroying short-lived thread pools on every series scan.
        # Ownership is here: shut down in the finally block below.
        tmdb_prefetch_executor: concurrent.futures.ThreadPoolExecutor | None = None

        try:
            tmdb_prefetch_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="tmdb_prefetch"
            )
            logger.info(
                "ScanAllLibrariesWorker: created TMDB pre-fetch executor (max_workers=4)."
            )
            await self._database_writer.start()
            logger.info("ScanAllLibrariesWorker starting global scan run")
            libraries_dictionary: dict[str, dict[str, Any]] = config.libraries
            self.unavailable_directories = []

            # Load existing library data from the database FIRST, so tree discovery
            # can use it to avoid redundant filesystem I/O.
            library_data_by_name = self._load_library_data(libraries_dictionary)

            # Pre-discover tree structure and tell the UI to initialise it.
            tree_structure = await self._discover_tree(library_data_by_name)
            self.emit_detail_progress(
                "init_tree",
                {
                    "tree": tree_structure,
                    "library_order": list(config.libraries.keys()),
                },
            )
            self.flush_detail_progress()

            jellyfin_data: dict[str, Any] | None = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            failed_libraries: set[str] = set()

            # ------------------------------------------------------------------
            # PASS 1 — Offline file scan
            # ------------------------------------------------------------------
            if self.run_pass1:
                await self._run_scan_pass(
                    1,
                    libraries_dictionary,
                    library_data_by_name,
                    None,  # jellyfin_data is None for Pass 1
                    tmdb_prefetch_executor,
                    failed_libraries,
                )

            # ------------------------------------------------------------------
            # PASS 2 — Online metadata resolution
            # ------------------------------------------------------------------
            if self.run_pass2:
                await self._run_scan_pass(
                    2,
                    libraries_dictionary,
                    library_data_by_name,
                    jellyfin_data,
                    tmdb_prefetch_executor,
                    failed_libraries,
                )

            # Compute self.stats as the union of both passes: max for scanned/skipped (unique entities),
            # sum for added/updated/removed (cumulative actions).
            self.stats = create_empty_stats()
            for pass_num in [1, 2]:
                if pass_num in self.pass_stats:
                    for key, value in self.pass_stats[pass_num].items():
                        if key.endswith(("_scanned", "_skipped")):
                            self.stats[key] = max(self.stats.get(key, 0), value)
                        elif not key.startswith("_"):
                            self.stats[key] = self.stats.get(key, 0) + value

            duration = time.time() - start_time
            self._log_scan_summary(duration, libraries_dictionary)
            logger.info("[SCAN_REPORT] *** SCAN COMPLETED ***")
            log_issues_report(self.problems, logger)

            logger.info("ScanAllLibrariesWorker finished successfully")

        except Exception as exception_instance:
            logger.exception("ScanAllLibrariesWorker failed")
            self.error.emit(str(exception_instance))
        finally:
            self.flush_detail_progress()
            if self._database_writer is not None:
                await self._database_writer.stop()
            # Shut down the TMDB pre-fetch executor.  Use wait=False so that
            # any pending futures (e.g. after an interruption) are not waited
            # for — they will be abandoned but not block the scan teardown.
            if tmdb_prefetch_executor is not None:
                logger.info(
                    "ScanAllLibrariesWorker: shutting down TMDB pre-fetch executor."
                )
                tmdb_prefetch_executor.shutdown(wait=False)

    def _load_library_data(
        self, libraries_dictionary: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Load existing library data from the database for each library."""
        library_data_by_name: dict[str, dict[str, Any]] = {}
        for (
            library_name,
            library_configuration,
        ) in libraries_dictionary.items():
            library_type = library_configuration.get("type", "tv")
            if library_type == "movie":
                library_data_by_name[library_name] = db.load_movie_library(library_name)
            else:
                library_data_by_name[library_name] = db.load_library(library_name)
        return library_data_by_name

    async def _run_scan_pass(
        self,
        pass_number: int,
        libraries_dictionary: dict[str, dict[str, Any]],
        library_data_by_name: dict[str, dict[str, Any]],
        jellyfin_data: dict[str, Any] | None,
        tmdb_prefetch_executor: concurrent.futures.ThreadPoolExecutor | None,
        failed_libraries: set[str],
    ) -> int:
        """Run a single scan pass (1 = offline, 2 = metadata) across all
        libraries in parallel, merging results into shared state."""
        self.current_pass = pass_number
        pass_label = (
            "Offline Scan" if pass_number == 1 else "Online Metadata Resolution"
        )
        start_event = (
            "start_offline_scan" if pass_number == 1 else "start_metadata_resolution"
        )
        logger.info(
            f"ScanAllLibrariesWorker starting Pass {pass_number} ({pass_label})"
        )
        self.emit_detail_progress(start_event, {})

        library_task_map: dict[asyncio.Task, str] = {}
        for (
            library_name,
            library_configuration,
        ) in libraries_dictionary.items():
            if library_name in failed_libraries:
                continue
            coro = run_in_executor(
                self._scan_library_pass,
                library_name,
                library_configuration,
                library_data_by_name[library_name],
                jellyfin_data,
                pass_number,
                tmdb_prefetch_executor,
            )
            task = asyncio.create_task(coro)
            library_task_map[task] = library_name

        completed_count: int = 0
        pending = set(library_task_map.keys())
        while pending:
            if self.isInterruptionRequested():
                logger.info(
                    f"ScanAllLibrariesWorker: interruption requested during Pass {pass_number}. Cancelling remaining tasks."
                )
                for t in pending:
                    t.cancel()
                break

            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                if task not in library_task_map:
                    continue
                library_name = library_task_map[task]
                try:
                    result = await task
                except asyncio.CancelledError:
                    logger.info(
                        f"ScanAllLibrariesWorker: scan for library "
                        f"'{library_name}' was cancelled."
                    )
                    self.pass_stats_per_library.setdefault(library_name, {})[
                        pass_number
                    ] = {"_skipped": True}
                    continue
                except Exception as error:
                    if isinstance(error, InterruptedError):
                        logger.info(
                            f"ScanAllLibrariesWorker: scan for library '{library_name}' aborted due to interruption."
                        )
                    else:
                        logger.exception(
                            f"ScanAllLibrariesWorker Pass {pass_number} failed "
                            f"for library: {library_name}"
                        )
                        self.library_error.emit(library_name, str(error))
                        self.emit_detail_progress(
                            "fail_library",
                            {"library": library_name},
                        )
                        if pass_number == 1:
                            failed_libraries.add(library_name)
                    self.pass_stats_per_library.setdefault(library_name, {})[
                        pass_number
                    ] = {"_skipped": True}
                    continue

                if pass_number == 2:
                    completed_count += 1
                self._merge_pass_result(
                    pass_number,
                    library_name,
                    result,
                    library_data_by_name,
                )
                if pass_number == 2:
                    self.library_progress.emit(
                        library_name,
                        completed_count,
                        len(libraries_dictionary),
                    )

        self.flush_detail_progress()
        return completed_count

    def _merge_pass_result(
        self,
        pass_number: int,
        library_name: str,
        result: dict[str, Any],
        library_data_by_name: dict[str, dict[str, Any]],
    ) -> None:
        """Merge one library's pass result into combined shared state."""
        merge_stats_dicts(self.pass_stats[pass_number], result["pass_stats"])
        self.pass_stats_per_library.setdefault(library_name, {})[pass_number] = result[
            "pass_stats"
        ]
        pass_stats = result["pass_stats"]
        if (
            pass_stats.get("series_added", 0) > 0
            or pass_stats.get("movies_added", 0) > 0
            or pass_stats.get("series_updated", 0) > 0
            or pass_stats.get("movies_updated", 0) > 0
        ):
            self.changed_libraries.add(library_name)

        self.problems.extend(result["problems"])
        for root in result["unavailable_directories"]:
            if root not in self.unavailable_directories:
                self.unavailable_directories.append(root)
        self.changed_season_ids.update(result["changed_season_ids"])
        self.changed_movie_ids.update(result["changed_movie_ids"])

        library_data_by_name[library_name] = result["library_data"]

        self.emit_detail_progress(
            "finish_library",
            {"library": library_name},
        )
        self.flush_detail_progress()
