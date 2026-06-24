import logging
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import QObject, QThread, Signal

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
    merge_stats_dicts_for_report,
)
from lan_streamer.backend.database_writer import DatabaseWriteTask, DatabaseWriterThread

logger = logging.getLogger("lan_streamer.backend")


class ScanAllLibrariesWorker(QThread):
    """Scans all configured libraries in parallel using TMDB for metadata.

    Libraries are scanned concurrently within each pass using a
    ``ThreadPoolExecutor``.  Pass 1 performs offline file discovery; Pass 2
    resolves online metadata.  Results from each thread-pool task are merged
    into shared state under a lock.
    """

    library_progress = Signal(str, int, int)
    detail_progress = Signal(str, dict)  # (event_type, payload)
    finished = Signal()
    error = Signal(str)
    library_error = Signal(str, str)  # (library_name, error_message)

    def __init__(
        self,
        force_refresh: bool = False,
        run_pass1: bool = True,
        run_pass2: bool = True,
        parent: Optional[QObject] = None,
    ) -> None:
        """Initialise the scan-all-libraries worker.

        Args:
            force_refresh: If True, re-resolve metadata even for unchanged items.
            run_pass1: If True, execute offline file-discovery pass.
            run_pass2: If True, execute online metadata-resolution pass.
            parent: Optional QObject parent.
        """
        super().__init__(parent)
        self.force_refresh: bool = force_refresh
        self.run_pass1: bool = run_pass1
        self.run_pass2: bool = run_pass2

        # Shared mutable state — protected by _lock when accessed from threads.
        self._lock: threading.Lock = threading.Lock()
        self.unavailable_directories: List[str] = []
        self.problems: List[Dict[str, Any]] = []
        self.stats: Dict[str, int] = {}
        self.changed_season_ids: Set[str] = set()
        self.changed_movie_ids: Set[str] = set()
        self.current_pass: int = 1

        self.pass1_stats: Dict[str, int] = create_empty_stats()
        self.pass2_stats: Dict[str, int] = create_empty_stats()

        # Per-library per-pass statistics.
        self.pass1_stats_per_library: Dict[str, Dict[str, int]] = {}
        self.pass2_stats_per_library: Dict[str, Dict[str, int]] = {}

        # Database write queue variables.
        self.database_queue: queue.Queue = queue.Queue()
        self.database_writer: Optional[DatabaseWriterThread] = None

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
            accumulated_stats = merge_stats_dicts_for_report(pass1_stats, pass2_stats)
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

        # Local accumulators (thread-local, not shared)
        local_stats: Dict[str, int] = create_empty_stats()
        local_problems: List[Dict[str, Any]] = []
        local_changed_season_ids: Set[str] = set()
        local_changed_movie_ids: Set[str] = set()
        local_series_scanned: Set[str] = set()
        library_unavailable_directories: List[str] = []

        self.detail_progress.emit("start_library", {"library": library_name})

        # ------------------------------------------------------------------
        # Callback closures — write to local accumulators
        # ------------------------------------------------------------------

        def _make_detail_callback(library_name_cb: str) -> Any:
            """Create a detail-progress callback that enriches events with the
            library name."""

            def _detail_callback(event: str, payload: Dict[str, Any]) -> None:
                enriched: Dict[str, Any] = {"library": library_name_cb, **payload}
                self.detail_progress.emit(event, enriched)

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
                task = DatabaseWriteTask(
                    action="save_season",
                    payload={
                        "library_name": library_name,
                        "series_name": series_name,
                        "series_data": series_data,
                        "season_name": season_name,
                        "season_data": season_data,
                    },
                )
                self.database_queue.put(task)
                task.event.wait()
                if task.error:
                    raise task.error
                stats = task.result
                if stats:
                    if "issues" in stats:
                        for issue in stats["issues"]:
                            local_problems.append(issue)

                    # Track series-level scan (first season encountered)
                    if series_name not in local_series_scanned:
                        local_series_scanned.add(series_name)
                        local_stats["series_scanned"] += 1
                        any_changed = any(
                            season_data_item.get("_changed", True)
                            for season_data_item in series_data.get(
                                "seasons", {}
                            ).values()
                        )
                        if not any_changed:
                            local_stats["series_skipped"] += 1

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
            except Exception as error:
                log_db_write_error(
                    local_problems,
                    f"Season '{season_name}' of series "
                    f"'{series_name}' (Library: '{library_name}')",
                    error,
                    logger,
                )

        def _movie_callback(movie_name: str, movie_data: Dict[str, Any]) -> None:
            """Process a single movie during scanning, persisting it to the
            database and accumulating local statistics."""
            logger.info(
                f"ScanAllLibrariesWorker writing movie '{movie_name}' to database..."
            )
            try:
                task = DatabaseWriteTask(
                    action="save_movie",
                    payload={
                        "library_name": library_name,
                        "movie_name": movie_name,
                        "movie_data": movie_data,
                    },
                )
                self.database_queue.put(task)
                task.event.wait()
                if task.error:
                    raise task.error
                stats = task.result
                if stats:
                    if "issues" in stats:
                        for issue in stats["issues"]:
                            local_problems.append(issue)

                    local_stats["movies_scanned"] += 1
                    if not movie_data.get("_changed", True):
                        local_stats["movies_skipped"] += 1

                    for key in local_stats:
                        if key in stats and not (
                            key.endswith("_scanned") or key.endswith("_skipped")
                        ):
                            local_stats[key] += stats[key]

                    if movie_data.get("_changed", True) and "movie_id" in stats:
                        local_changed_movie_ids.add(stats["movie_id"])
            except Exception as error:
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
                task = DatabaseWriteTask(
                    action=action,
                    payload={
                        "library_name": library_name,
                        "library_data": library_data,
                    },
                )
                self.database_queue.put(task)
                task.event.wait()
                if task.error:
                    raise task.error
                stats = task.result
                if stats:
                    if "issues" in stats:
                        for issue in stats["issues"]:
                            local_problems.append(issue)
                    for key in local_stats:
                        if key in stats and (
                            key.endswith("_removed") or key == "deleted"
                        ):
                            local_stats[key] += stats[key]
            except Exception as error:
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
            _save_library_data(updated_library_data)
            current_library_data: Dict[str, Any] = updated_library_data
        else:
            current_library_data = existing_library_data
            for root_dir in root_directories:
                self.detail_progress.emit(
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
                )
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
                    self.detail_progress.emit(
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

    def _discover_tree(self) -> Dict[str, Any]:
        """Pre-walk all library directories to count total folders and files.

        This allows the UI to initialise the tree and segmented progress bar
        before scanning begins.

        Returns:
            A nested dictionary keyed by library name.
        """
        tree: Dict[str, Any] = {}
        for library_name, library_configuration in config.libraries.items():
            root_directories: List[str] = list(library_configuration.get("paths", []))
            library_type: str = library_configuration.get("type", "tv")
            roots: Dict[str, Any] = {}
            for root_dir in root_directories:
                root_path = Path(root_dir)
                if not root_path.exists() or not root_path.is_dir():
                    roots[root_dir] = {}
                    continue
                folders: Dict[str, Any] = {}
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
                        folders[series_name] = {"seasons": seasons}
                    else:
                        folders[series_name] = {}
                roots[root_dir] = folders
            tree[library_name] = {"type": library_type, "roots": roots}
        return tree

    # ------------------------------------------------------------------
    # Main execution entrypoint (runs in the QThread)
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute the full scan run with parallel library scanning."""
        import time

        start_time = time.time()
        self.problems = []
        self.stats = create_empty_stats()
        self.pass1_series_scanned: Set[str] = set()
        self.pass2_series_scanned: Set[str] = set()
        for key in self.pass1_stats:
            self.pass1_stats[key] = 0
            self.pass2_stats[key] = 0
        self.pass1_stats_per_library = {}
        self.pass2_stats_per_library = {}
        self.changed_season_ids = set()
        self.changed_movie_ids = set()
        self.current_pass = 1

        # Start the database writer thread
        self.database_queue = queue.Queue()
        self.database_writer = DatabaseWriterThread(self.database_queue)
        self.database_writer.start()

        try:
            logger.info("ScanAllLibrariesWorker starting global scan run")
            libraries_dictionary: Dict[str, Dict[str, Any]] = config.libraries
            total_count: int = len(libraries_dictionary)
            self.unavailable_directories = []

            # Pre-discover tree structure and tell the UI to initialise it.
            tree_structure = self._discover_tree()
            self.detail_progress.emit(
                "init_tree",
                {
                    "tree": tree_structure,
                    "library_order": list(config.libraries.keys()),
                },
            )

            jellyfin_data: Optional[Dict[str, Any]] = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            # Load existing library data from the database.
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

            max_workers: int = max(
                1,
                min(
                    len(libraries_dictionary),
                    (os.cpu_count() or 4),
                ),
            )

            failed_libraries: set = set()

            # ------------------------------------------------------------------
            # PASS 1 — Offline file scan
            # ------------------------------------------------------------------
            if self.run_pass1:
                self.current_pass = 1
                logger.info("ScanAllLibrariesWorker starting Pass 1 (Offline Scan)")
                self.detail_progress.emit("start_offline_scan", {})

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_library: Dict[Any, str] = {}
                    for (
                        library_name,
                        library_configuration,
                    ) in libraries_dictionary.items():
                        future = executor.submit(
                            self._scan_library_pass,
                            library_name,
                            library_configuration,
                            library_data_by_name[library_name],
                            None,  # jellyfin_data is None for Pass 1
                            True,  # is_pass1
                        )
                        future_to_library[future] = library_name
                    for future in as_completed(future_to_library):
                        library_name = future_to_library[future]
                        try:
                            result: Dict[str, Any] = future.result()
                        except Exception as error:
                            logger.exception(
                                f"ScanAllLibrariesWorker Pass 1 failed "
                                f"for library: {library_name}"
                            )
                            self.library_error.emit(library_name, str(error))
                            self.detail_progress.emit(
                                "fail_library",
                                {"library": library_name},
                            )
                            failed_libraries.add(library_name)
                            self.pass1_stats_per_library[library_name] = {
                                "_skipped": True
                            }
                            continue

                        # Merge per-library stats into combined totals
                        # (single-threaded section — no lock needed).
                        merge_stats_dicts(self.pass1_stats, result["pass_stats"])
                        merge_stats_dicts(self.stats, result["pass_stats"])
                        self.pass1_stats_per_library[library_name] = result[
                            "pass_stats"
                        ]

                        # Merge shared state under lock.
                        with self._lock:
                            self.problems.extend(result["problems"])
                            for root in result["unavailable_directories"]:
                                if root not in self.unavailable_directories:
                                    self.unavailable_directories.append(root)
                            self.changed_season_ids.update(result["changed_season_ids"])
                            self.changed_movie_ids.update(result["changed_movie_ids"])

                        # Persist the updated library data for Pass 2.
                        library_data_by_name[library_name] = result["library_data"]

                        # notify UI that this library finished this pass
                        self.detail_progress.emit(
                            "finish_library",
                            {"library": library_name},
                        )

            # ------------------------------------------------------------------
            # PASS 2 — Online metadata resolution
            # ------------------------------------------------------------------
            if self.run_pass2:
                self.current_pass = 2
                logger.info(
                    "ScanAllLibrariesWorker starting Pass 2 "
                    "(Online Metadata Resolution)"
                )
                self.detail_progress.emit("start_metadata_resolution", {})

                completed_count: int = 0
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_library = {}
                    for (
                        library_name,
                        library_configuration,
                    ) in libraries_dictionary.items():
                        if library_name in failed_libraries:
                            continue
                        future = executor.submit(
                            self._scan_library_pass,
                            library_name,
                            library_configuration,
                            library_data_by_name[library_name],
                            jellyfin_data,
                            False,  # is_pass1
                        )
                        future_to_library[future] = library_name

                    for future in as_completed(future_to_library):
                        library_name = future_to_library[future]
                        try:
                            result = future.result()
                        except Exception as error:
                            logger.exception(
                                f"ScanAllLibrariesWorker Pass 2 failed "
                                f"for library: {library_name}"
                            )
                            self.library_error.emit(library_name, str(error))
                            self.detail_progress.emit(
                                "fail_library",
                                {"library": library_name},
                            )
                            self.pass2_stats_per_library[library_name] = {
                                "_skipped": True
                            }
                            continue

                        completed_count += 1

                        # Merge per-library stats into combined totals.
                        merge_stats_dicts(self.pass2_stats, result["pass_stats"])
                        merge_stats_dicts(self.stats, result["pass_stats"])
                        self.pass2_stats_per_library[library_name] = result[
                            "pass_stats"
                        ]

                        # Merge shared state under lock.
                        with self._lock:
                            self.problems.extend(result["problems"])
                            for root in result["unavailable_directories"]:
                                if root not in self.unavailable_directories:
                                    self.unavailable_directories.append(root)
                            self.changed_season_ids.update(result["changed_season_ids"])
                            self.changed_movie_ids.update(result["changed_movie_ids"])

                        library_data_by_name[library_name] = result["library_data"]

                        self.detail_progress.emit(
                            "finish_library",
                            {"library": library_name},
                        )
                        self.library_progress.emit(
                            library_name,
                            completed_count,
                            total_count,
                        )

            # ------------------------------------------------------------------
            # Final summary logging
            # ------------------------------------------------------------------
            duration = time.time() - start_time
            self._log_scan_summary(duration, libraries_dictionary)
            logger.info("[SCAN_REPORT] *** SCAN COMPLETED ***")
            log_issues_report(self.problems, logger)

            logger.info("ScanAllLibrariesWorker finished successfully")
            self.finished.emit()

        except Exception as exception_instance:
            logger.exception("ScanAllLibrariesWorker failed")
            self.error.emit(str(exception_instance))
        finally:
            if self.database_writer is not None:
                self.database_queue.put(None)
                self.database_writer.join()
