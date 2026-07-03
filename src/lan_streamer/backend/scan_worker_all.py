import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import QObject, Signal

from lan_streamer import db
from lan_streamer.providers.jellyfin import jellyfin_client
from lan_streamer.scanner import (
    VIDEO_EXTENSIONS,
    has_video_files,
    scan_directories,
)
from lan_streamer.system.config import config
from lan_streamer.backend.scan_worker_base import (
    create_empty_stats,
    log_db_write_error,
    log_issues_report,
    log_stats_breakdown,
    merge_stats_dicts,
    series_belongs_to_root,
)
from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_task_manager import AsyncTaskManager
from lan_streamer.backend.database_writer import AsyncDatabaseWriter
from lan_streamer.system.async_utils import run_in_fs_executor, run_in_executor


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
        async_task_manager: Optional[AsyncTaskManager] = None,
        force_refresh: bool = False,
        run_pass1: bool = True,
        run_pass2: bool = True,
        parent: Optional[QObject] = None,
    ) -> None:
        """Initialise the scan-all-libraries worker."""
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.force_refresh: bool = force_refresh
        self.run_pass1: bool = run_pass1
        self.run_pass2: bool = run_pass2

        # Shared mutable state — protected by _lock when accessed from threads.
        self._lock = threading.Lock()
        self._detail_progress_buffer: List[Dict[str, Any]] = []

        self.unavailable_directories: List[str] = []
        self.problems: List[Dict[str, Any]] = []
        self.stats: Dict[str, int] = create_empty_stats()
        self.changed_season_ids: Set[str] = set()
        self.changed_movie_ids: Set[str] = set()
        self.current_pass: int = 1
        self.pass1_series_scanned: Set[str] = set()
        self.pass2_series_scanned: Set[str] = set()
        # Track unique series/movie IDs scanned across BOTH passes to avoid
        # double-counting in self.stats (which is the union of both passes).
        self._scanned_series_ids: Set[str] = set()
        self._scanned_movie_ids: Set[str] = set()
        # Track unique series/movie IDs skipped across BOTH passes to ensure
        # skipped counts are not lost.
        self._skipped_series_ids: Set[str] = set()
        self._skipped_movie_ids: Set[str] = set()

        self.pass1_stats: Dict[str, int] = create_empty_stats()
        self.pass2_stats: Dict[str, int] = create_empty_stats()

        # Per-library per-pass statistics.
        self.pass1_stats_per_library: Dict[str, Dict[str, int]] = {}
        self.pass2_stats_per_library: Dict[str, Dict[str, int]] = {}

        # Database writer and event loop — created in run_async() for each scan.
        self._database_writer: Optional[AsyncDatabaseWriter] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    def emit_detail_progress(self, event: str, payload: Dict[str, Any]) -> None:
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
        stats_dict: Dict[str, Any],
        status_notes: Optional[List[str]] = None,
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
        self, duration: float, libraries_dictionary: Dict[str, Dict[str, Any]]
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
            pass1_stats = self.pass1_stats_per_library.get(library_name, {})
            pass2_stats = self.pass2_stats_per_library.get(library_name, {})
            # Compute accumulated stats correctly: sum non-scanned/skipped keys,
            # use max for scanned/skipped keys (since they track unique entities)
            accumulated_stats = {}
            all_keys = set(pass1_stats.keys()) | set(pass2_stats.keys())
            for key in all_keys:
                if key.endswith("_scanned") or key.endswith("_skipped"):
                    # Use max to avoid double-counting unique entities across passes
                    accumulated_stats[key] = max(
                        pass1_stats.get(key, 0), pass2_stats.get(key, 0)
                    )
                else:
                    # Sum other keys (added, updated, removed)
                    accumulated_stats[key] = pass1_stats.get(key, 0) + pass2_stats.get(
                        key, 0
                    )
            status_notes: List[str] = []
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
            self.pass1_stats,
            logger,
        )
        logger.info("[SCAN_REPORT] ---------------------------------------------------")
        log_stats_breakdown(
            "PASS 2: ONLINE METADATA RESOLUTION BREAKDOWN (PASS 2)",
            self.pass2_stats,
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
        library_configuration: Dict[str, Any],
        existing_library_data: Dict[str, Any],
        jellyfin_data: Optional[Dict[str, Any]],
        is_pass1: bool,
    ) -> Dict[str, Any]:
        """Execute one scan pass for a single library inside a thread-pool worker.

        Args:
            library_name: Name of the library to scan.
            library_configuration: Configuration dict for the library
                (keys include ``paths``, ``type``, ``show_future_episodes``).
            existing_library_data: Previously persisted library data loaded
                from the database.
            jellyfin_data: Jellyfin correlation data (``None`` for Pass 1).
            is_pass1: ``True`` for the offline file-discovery pass,
                ``False`` for the online metadata-resolution pass.

        .. note::

           ``scan_directories`` is called **synchronously** inside this method.
           The callback closures close over this stack frame; they are valid
           because the frame stays alive for the full duration of the call.

        Returns:
            A dictionary with the following keys:

            - ``library_name`` (str)
            - ``library_data`` (dict) — updated LibraryDict from
              :func:`~lan_streamer.scanner.core.scan_directories`
            - ``pass_stats`` (Dict[str, int]) — per-pass statistics
            - ``problems`` (List[Dict]) — issues encountered during the pass
            - ``unavailable_directories`` (List[str]) — missing root directories
            - ``changed_season_ids`` (Set[str]) — season IDs that changed
            - ``changed_movie_ids`` (Set[str]) — movie IDs that changed
        """
        root_directories: List[str] = list(library_configuration.get("paths", []))
        library_type: str = library_configuration.get("type", "tv")
        show_future_episodes: bool = library_configuration.get(
            "show_future_episodes", True
        )

        # _database_writer and _event_loop are set by run_async() before this method is called
        writer = self._database_writer
        loop = self._event_loop
        assert writer is not None
        assert loop is not None

        # Local accumulators (thread-local, protected by local_lock)
        local_stats: Dict[str, int] = create_empty_stats()
        local_problems: List[Dict[str, Any]] = []
        local_changed_season_ids: Set[str] = set()
        local_changed_movie_ids: Set[str] = set()
        local_series_scanned: Set[str] = set()
        library_unavailable_directories: List[str] = []
        # Local lock protects local_stats/local_problems because folder-level
        # parallel scan (scan_directories) submits scan_series/scan_movie as
        # futures to the global executor, and those futures invoke
        # _season_callback/_movie_callback from folder-pool threads.
        local_lock = threading.Lock()

        self.emit_detail_progress("start_library", {"library": library_name})

        # ------------------------------------------------------------------
        # Callback closures — write to local accumulators
        # ------------------------------------------------------------------

        def _make_detail_callback(library_name_cb: str) -> Any:
            """Create a detail-progress callback that enriches events with the
            library name.

            NOTE: This callback is invoked from thread-pool workers and MUST
            remain thread-safe. It uses lock-buffered emit_detail_progress."""

            def _detail_callback(event: str, payload: Dict[str, Any]) -> None:
                enriched: Dict[str, Any] = {"library": library_name_cb, **payload}
                self.emit_detail_progress(event, enriched)

            return _detail_callback

        def _season_callback(
            series_name: str,
            series_data: Dict[str, Any],
            season_name: str,
            season_data: Dict[str, Any],
        ) -> None:
            """Process a single season during scanning, persisting it to the
            database and accumulating local statistics."""
            logger.info(
                f"ScanAllLibrariesWorker writing season "
                f"'{season_name}' of series '{series_name}' to database..."
            )
            try:
                season_payload = {
                    "library_name": library_name,
                    "series_name": series_name,
                    "series_data": series_data,
                    "season_name": season_name,
                    "season_data": season_data,
                }
                task = writer.sync_submit("save_season", season_payload, loop)
                if task.error:
                    raise task.error
                stats = task.result
                if stats:
                    series_id = stats.get("series_id") or series_name
                    is_new_series_scan = False
                    is_new_series_skip = False

                    with local_lock:
                        if "issues" in stats:
                            for issue in stats["issues"]:
                                local_problems.append(issue)

                        # Track series-level scan (first season encountered)
                        if series_name not in local_series_scanned:
                            local_series_scanned.add(series_name)
                            local_stats["series_scanned"] += 1
                            is_new_series_scan = True

                            any_changed = any(
                                season_data_item.get("_changed", True)
                                for season_data_item in series_data.get(
                                    "seasons", {}
                                ).values()
                            )
                            if not any_changed:
                                local_stats["series_skipped"] += 1
                                is_new_series_skip = True

                        local_stats["seasons_scanned"] += 1
                        episode_count: int = len(season_data.get("episodes", []))
                        local_stats["episodes_scanned"] += episode_count

                        if not season_data.get("_changed", True):
                            local_stats["seasons_skipped"] += 1
                            local_stats["episodes_skipped"] += episode_count

                        # Add/update/remove counts from db return value
                        for key in local_stats:
                            if key in stats and not (
                                key.endswith("_scanned") or key.endswith("_skipped")
                            ):
                                local_stats[key] += stats[key]

                        if season_data.get("_changed", True) and "season_id" in stats:
                            local_changed_season_ids.add(stats["season_id"])

                    # Update global stats outside local_lock to avoid nested locking
                    if is_new_series_scan:
                        with self._lock:
                            if series_id not in self._scanned_series_ids:
                                self._scanned_series_ids.add(series_id)
                                self.stats["series_scanned"] += 1

                    if is_new_series_skip:
                        with self._lock:
                            if series_id not in self._skipped_series_ids:
                                self._skipped_series_ids.add(series_id)
                                self.stats["series_skipped"] += 1

                    # Fetch cast/crew and images for newly scanned series
                    if is_new_series_scan and stats.get("series_id"):
                        tmdb_id = series_data.get("metadata", {}).get("tmdb_identifier")
                        if tmdb_id:
                            try:
                                has_cast = len(db.get_cast_for_series(series_id)) > 0
                                if (
                                    self.force_refresh
                                    or stats.get("series_added", 0) > 0
                                    or not has_cast
                                ):
                                    task_credits = writer.sync_submit(
                                        "fetch_and_store_series_credits_and_images",
                                        {
                                            "series_id": series_id,
                                            "tmdb_id": int(tmdb_id),
                                        },
                                        loop,
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
                            except Exception as fetch_error:
                                logger.warning(
                                    "Failed to fetch cast/images for series '%s': %s",
                                    series_name,
                                    fetch_error,
                                )
            except Exception as error:
                with local_lock:
                    log_db_write_error(
                        local_problems,
                        f"Season '{season_name}' of series "
                        f"'{series_name}' (Library: '{library_name}')",
                        error,
                        logger,
                    )

        # Callback invoked from thread-pool workers — must be thread-safe.
        # It acquires self._lock for shared-state access.
        def _movie_callback(movie_name: str, movie_data: Dict[str, Any]) -> None:
            """Process a single movie during scanning, persisting it to the
            database and accumulating local statistics."""
            logger.info(
                f"ScanAllLibrariesWorker writing movie '{movie_name}' to database..."
            )
            try:
                movie_payload = {
                    "library_name": library_name,
                    "movie_name": movie_name,
                    "movie_data": movie_data,
                }
                task = writer.sync_submit("save_movie", movie_payload, loop)
                if task.error:
                    raise task.error
                stats = task.result
                if stats:
                    movie_id = stats.get("movie_id") or movie_name
                    is_new_movie_scan = False
                    is_new_movie_skip = False

                    with local_lock:
                        if "issues" in stats:
                            for issue in stats["issues"]:
                                local_problems.append(issue)

                        local_stats["movies_scanned"] += 1
                        is_new_movie_scan = True

                        if not movie_data.get("_changed", True):
                            local_stats["movies_skipped"] += 1
                            is_new_movie_skip = True

                        for key in local_stats:
                            if key in stats and not (
                                key.endswith("_scanned") or key.endswith("_skipped")
                            ):
                                local_stats[key] += stats[key]

                        if movie_data.get("_changed", True) and "movie_id" in stats:
                            local_changed_movie_ids.add(stats["movie_id"])

                    # Update global stats outside local_lock to avoid nested locking
                    if is_new_movie_scan:
                        with self._lock:
                            if movie_id not in self._scanned_movie_ids:
                                self._scanned_movie_ids.add(movie_id)
                                self.stats["movies_scanned"] += 1

                    if is_new_movie_skip:
                        with self._lock:
                            if movie_id not in self._skipped_movie_ids:
                                self._skipped_movie_ids.add(movie_id)
                                self.stats["movies_skipped"] += 1

                    # Fetch cast/crew and images for newly scanned movie
                    if is_new_movie_scan and stats.get("movie_id"):
                        tmdb_id = movie_data.get("tmdb_identifier")
                        if not tmdb_id:
                            tmdb_id = movie_data.get("metadata", {}).get(
                                "tmdb_identifier"
                            )
                        if tmdb_id:
                            try:
                                has_cast = len(db.get_cast_for_movie(movie_id)) > 0
                                if (
                                    self.force_refresh
                                    or stats.get("movies_added", 0) > 0
                                    or not has_cast
                                ):
                                    task_credits = writer.sync_submit(
                                        "fetch_and_store_movie_credits_and_images",
                                        {
                                            "movie_id": movie_id,
                                            "tmdb_id": int(tmdb_id),
                                        },
                                        loop,
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
                            except Exception as fetch_error:
                                logger.warning(
                                    "Failed to fetch cast/images for movie '%s': %s",
                                    movie_name,
                                    fetch_error,
                                )
            except Exception as error:
                with local_lock:
                    log_db_write_error(
                        local_problems,
                        f"Movie '{movie_name}' (Library: '{library_name}')",
                        error,
                        logger,
                    )

        def _save_library_data(library_data: Dict[str, Any]) -> None:
            """Persist the full library data to the database.

            Only ``_removed`` and ``deleted`` keys from the return value are
            counted here since additions/updates are already accounted for in
            the per-item callbacks above.
            """
            try:
                action = (
                    "save_movie_library" if library_type == "movie" else "save_library"
                )
                library_payload = {
                    "library_name": library_name,
                    "library_data": library_data,
                }
                task = writer.sync_submit(action, library_payload, loop)
                if task.error:
                    raise task.error
                stats = task.result
                if stats:
                    with local_lock:
                        if "issues" in stats:
                            for issue in stats["issues"]:
                                local_problems.append(issue)
                        for key in local_stats:
                            if key in stats and (
                                key.endswith("_removed") or key == "deleted"
                            ):
                                local_stats[key] += stats[key]
            except Exception as error:
                with local_lock:
                    log_db_write_error(
                        local_problems,
                        f"Library '{library_name}'",
                        error,
                        logger,
                    )

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
                jellyfin_data=jellyfin_data if not is_pass1 else None,
                callback=None,
                force_refresh=self.force_refresh,
                cleanup=False,
                detail_callback=_make_detail_callback(library_name),
                show_future_episodes=show_future_episodes,
                offline=is_pass1,
                season_callback=_season_callback,
                movie_callback=_movie_callback,
                metadata_only=not is_pass1,
                is_interrupted=self.isInterruptionRequested,
            )
            # Collect unavailable directories from this scan.
            if updated_library_data.unavailable_directories:
                for root in updated_library_data.unavailable_directories:
                    library_unavailable_directories.append(root)
                    # Only log unavailable directory issues once (in Pass 1)
                    if is_pass1:
                        error_message: str = (
                            f"Root directory '{root}' in library "
                            f"'{library_name}' is unavailable on filesystem."
                        )
                        logger.warning(
                            "[SCAN_ISSUE] Type=Unavailable Directory | "
                            f"Item={root} (Library: '{library_name}') | "
                            f"Error={error_message}"
                        )
                        local_problems.append(
                            {
                                "type": "Unavailable Directory",
                                "item": (f"{root} (Library: '{library_name}')"),
                                "error": error_message,
                            }
                        )
            if self.isInterruptionRequested():
                raise InterruptedError("Scan interrupted.")
            _save_library_data(updated_library_data)
            current_library_data: Dict[str, Any] = updated_library_data
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
                    jellyfin_data=jellyfin_data if not is_pass1 else None,
                    callback=None,
                    force_refresh=self.force_refresh,
                    cleanup=False,
                    detail_callback=_make_detail_callback(library_name),
                    show_future_episodes=show_future_episodes,
                    offline=is_pass1,
                    season_callback=_season_callback,
                    movie_callback=_movie_callback,
                    metadata_only=not is_pass1,
                    is_interrupted=self.isInterruptionRequested,
                )
                if self.isInterruptionRequested():
                    raise InterruptedError("Scan interrupted.")
                # Collect unavailable directories from this root scan.
                if updated_library_data.unavailable_directories:
                    for root in updated_library_data.unavailable_directories:
                        library_unavailable_directories.append(root)
                        # Only log unavailable directory issues once (in Pass 1)
                        if is_pass1:
                            error_message = (
                                f"Root directory '{root}' in library "
                                f"'{library_name}' is unavailable on filesystem."
                            )
                            logger.warning(
                                "[SCAN_ISSUE] Type=Unavailable Directory | "
                                f"Item={root} (Library: '{library_name}') | "
                                f"Error={error_message}"
                            )
                            local_problems.append(
                                {
                                    "type": "Unavailable Directory",
                                    "item": (f"{root} (Library: '{library_name}')"),
                                    "error": error_message,
                                }
                            )
                current_library_data = updated_library_data
                _save_library_data(updated_library_data)

                # Finish-root is only emitted in Pass 2 (metadata resolution).
                if not is_pass1:
                    self.emit_detail_progress(
                        "finish_root",
                        {"library": library_name, "root": root_dir},
                    )

        return {
            "library_name": library_name,
            "library_data": current_library_data,
            "pass_stats": local_stats,
            "problems": local_problems,
            "unavailable_directories": library_unavailable_directories,
            "changed_season_ids": local_changed_season_ids,
            "changed_movie_ids": local_changed_movie_ids,
        }

    # ------------------------------------------------------------------
    # Tree discovery
    # ------------------------------------------------------------------

    def _discover_single_library_tree(
        self,
        library_name: str,
        library_configuration: Dict[str, Any],
        existing_library_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Pre-walk directories of a single library to build its tree structure.

        Args:
            library_name: The name of the library.
            library_configuration: Configuration dictionary for the library.
            existing_library_data: Previously loaded library data to avoid I/O.

        Returns:
            A dictionary containing library type and its roots.
        """
        root_directories: List[str] = list(library_configuration.get("paths", []))
        library_type: str = library_configuration.get("type", "tv")
        # Build the detailed tree structure (with seasons/episodes) from the
        # existing library data if available; otherwise fall back to filesystem.
        detailed_roots: Dict[str, Any] = {}
        for root_dir in root_directories:
            if existing_library_data:
                # Build from existing data
                detailed_roots[root_dir] = {}
                for series_name, series_data in existing_library_data.items():
                    if series_belongs_to_root(series_data, root_dir, library_type):
                        if library_type in ("tv", "anime"):
                            seasons: Dict[str, List[str]] = {}
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
                        seasons: Dict[str, List[str]] = {}
                        for season_path in series_path.iterdir():
                            if season_path.is_dir() and not season_path.name.startswith(
                                "."
                            ):
                                episodes: List[str] = []
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
        self, library_data_by_name: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Pre-walk all library directories to count total folders and files in parallel.

        This allows the UI to initialise the tree and segmented progress bar
        before scanning begins.

        Args:
            library_data_by_name: Existing library data loaded from database.

        Returns:
            A nested dictionary keyed by library name.
        """
        libraries_dictionary: Dict[str, Dict[str, Any]] = config.libraries
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

        tree: Dict[str, Any] = {}
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
        for key in self.pass1_stats:
            self.pass1_stats[key] = 0
            self.pass2_stats[key] = 0
        self.pass1_stats_per_library = {}
        self.pass2_stats_per_library = {}
        self.changed_season_ids = set()
        self.changed_movie_ids = set()
        self.current_pass = 1
        self.pass1_series_scanned.clear()
        self.pass2_series_scanned.clear()
        self._scanned_series_ids.clear()
        self._scanned_movie_ids.clear()
        self._skipped_series_ids.clear()
        self._skipped_movie_ids.clear()

        # Create the database writer and capture event loop for sync_submit
        self._database_writer = AsyncDatabaseWriter()
        self._event_loop = asyncio.get_running_loop()

        try:
            await self._database_writer.start()
            logger.info("ScanAllLibrariesWorker starting global scan run")
            libraries_dictionary: Dict[str, Dict[str, Any]] = config.libraries
            total_count: int = len(libraries_dictionary)
            self.unavailable_directories = []

            # Load existing library data from the database FIRST, so tree discovery
            # can use it to avoid redundant filesystem I/O.
            library_data_by_name: Dict[str, Dict[str, Any]] = {}
            for (
                library_name,
                library_configuration,
            ) in libraries_dictionary.items():
                library_type = library_configuration.get("type", "tv")
                if library_type == "movie":
                    library_data_by_name[library_name] = db.load_movie_library(
                        library_name
                    )
                else:
                    library_data_by_name[library_name] = db.load_library(library_name)

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

            jellyfin_data: Optional[Dict[str, Any]] = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            failed_libraries: set = set()

            # ------------------------------------------------------------------
            # PASS 1 — Offline file scan
            # ------------------------------------------------------------------
            if self.run_pass1:
                self.current_pass = 1
                logger.info("ScanAllLibrariesWorker starting Pass 1 (Offline Scan)")
                self.emit_detail_progress("start_offline_scan", {})

                library_task_map: Dict[str, asyncio.Task] = {}
                for (
                    library_name,
                    library_configuration,
                ) in libraries_dictionary.items():
                    coro = run_in_executor(
                        self._scan_library_pass,
                        library_name,
                        library_configuration,
                        library_data_by_name[library_name],
                        None,  # jellyfin_data is None for Pass 1
                        True,  # is_pass1
                    )
                    library_task_map[library_name] = asyncio.create_task(coro)

                pending = set(library_task_map.values())
                while pending:
                    if self.isInterruptionRequested():
                        logger.info(
                            "ScanAllLibrariesWorker: interruption requested during Pass 1. Cancelling remaining tasks."
                        )
                        for t in pending:
                            t.cancel()
                        break

                    done, pending = await asyncio.wait(
                        pending, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in done:
                        library_name = next(
                            name for name, t in library_task_map.items() if t == task
                        )
                        try:
                            result = await task
                        except Exception as error:
                            if isinstance(error, InterruptedError):
                                logger.info(
                                    f"ScanAllLibrariesWorker: scan for library '{library_name}' aborted due to interruption."
                                )
                            else:
                                logger.exception(
                                    f"ScanAllLibrariesWorker Pass 1 failed "
                                    f"for library: {library_name}"
                                )
                                self.library_error.emit(library_name, str(error))
                                self.emit_detail_progress(
                                    "fail_library",
                                    {"library": library_name},
                                )
                                failed_libraries.add(library_name)
                            self.pass1_stats_per_library[library_name] = {
                                "_skipped": True
                            }
                            continue

                        # Merge per-library stats into combined totals.
                        merge_stats_dicts(self.pass1_stats, result["pass_stats"])
                        for key, value in result["pass_stats"].items():
                            if not (
                                key.endswith("_scanned") or key.endswith("_skipped")
                            ):
                                with self._lock:
                                    self.stats[key] = self.stats.get(key, 0) + value
                        self.pass1_stats_per_library[library_name] = result[
                            "pass_stats"
                        ]

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

            self.flush_detail_progress()

            # ------------------------------------------------------------------
            # PASS 2 — Online metadata resolution
            # ------------------------------------------------------------------
            if self.run_pass2:
                self.current_pass = 2
                logger.info(
                    "ScanAllLibrariesWorker starting Pass 2 "
                    "(Online Metadata Resolution)"
                )
                self.emit_detail_progress("start_metadata_resolution", {})

                completed_count: int = 0
                library_task_map_pass2: Dict[str, asyncio.Task] = {}
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
                        False,  # is_pass1
                    )
                    library_task_map_pass2[library_name] = asyncio.create_task(coro)

                pending_pass2 = set(library_task_map_pass2.values())
                while pending_pass2:
                    if self.isInterruptionRequested():
                        logger.info(
                            "ScanAllLibrariesWorker: interruption requested during Pass 2. Cancelling remaining tasks."
                        )
                        for t in pending_pass2:
                            t.cancel()
                        break

                    done_pass2, pending_pass2 = await asyncio.wait(
                        pending_pass2, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in done_pass2:
                        library_name = next(
                            name
                            for name, t in library_task_map_pass2.items()
                            if t == task
                        )
                        try:
                            result = await task
                        except Exception as error:
                            if isinstance(error, InterruptedError):
                                logger.info(
                                    f"ScanAllLibrariesWorker: scan for library '{library_name}' aborted due to interruption."
                                )
                            else:
                                logger.exception(
                                    f"ScanAllLibrariesWorker Pass 2 failed "
                                    f"for library: {library_name}"
                                )
                                self.library_error.emit(library_name, str(error))
                                self.emit_detail_progress(
                                    "fail_library",
                                    {"library": library_name},
                                )
                            self.pass2_stats_per_library[library_name] = {
                                "_skipped": True
                            }
                            continue

                        completed_count += 1

                        merge_stats_dicts(self.pass2_stats, result["pass_stats"])
                        for key, value in result["pass_stats"].items():
                            if not (
                                key.endswith("_scanned") or key.endswith("_skipped")
                            ):
                                with self._lock:
                                    self.stats[key] = self.stats.get(key, 0) + value
                        self.pass2_stats_per_library[library_name] = result[
                            "pass_stats"
                        ]

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
                        self.library_progress.emit(
                            library_name,
                            completed_count,
                            total_count,
                        )

            self.flush_detail_progress()

            # ------------------------------------------------------------------
            # Final summary logging
            # ------------------------------------------------------------------
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
