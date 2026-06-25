import logging
import queue
import time
import threading
from typing import List, Dict, Any, Optional, Set
from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer.scanner import LibraryDict
from lan_streamer.system.config import config
from lan_streamer.providers.jellyfin import jellyfin_client
from lan_streamer.scanner import scan_directories
from lan_streamer.backend.scan_worker_base import (
    create_empty_stats,
    discover_single_library_tree_impl,
    log_db_write_error,
    log_issues_report,
    log_stats_breakdown,
    wait_for_database_write_task,
)
from lan_streamer.backend.database_writer import DatabaseWriteTask, DatabaseWriterThread

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


class ScanWorker(QThread):
    """Scans a single library directory using TMDB for metadata."""

    finished = Signal(dict)
    partial_result = Signal(dict)
    error = Signal(str)
    library_error = Signal(str, str)
    detail_progress = Signal(str, dict)
    detail_progress_batch = Signal(list)

    def __init__(
        self,
        root_directories: List[str],
        library_type: str,
        existing_library: Dict[str, Any],
        force_refresh: bool = False,
        cleanup: bool = False,
        parent: Optional[QObject] = None,
        library_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.root_directories: List[str] = root_directories
        self.library_type: str = library_type
        self.existing_library: Dict[str, Any] = existing_library
        self.force_refresh: bool = force_refresh
        self.cleanup: bool = cleanup
        self.unavailable_directories: List[str] = []
        self.library_name: str = library_name
        self.problems: List[Dict[str, Any]] = []
        self.stats: Dict[str, int] = {}
        self.changed_season_ids: Set[str] = set()
        self.changed_movie_ids: Set[str] = set()
        self.current_pass: int = 1
        # Track unique series/movie IDs scanned across BOTH passes to avoid
        # double-counting in self.stats (which is the union of both passes).
        self._scanned_series_ids: Set[str] = set()
        self._scanned_movie_ids: Set[str] = set()

        self.pass1_stats: Dict[str, int] = create_empty_stats()
        self.pass2_stats: Dict[str, int] = create_empty_stats()
        self.scan_lock: threading.Lock = threading.Lock()

        # Database write queue variables.
        self.database_queue: queue.Queue = queue.Queue()
        self.database_writer: Optional[DatabaseWriterThread] = None

        # Signal batching buffer — thread-safe via _detail_progress_lock.
        self._detail_progress_buffer: List[Dict[str, Any]] = []
        self._detail_progress_lock: threading.Lock = threading.Lock()

    def emit_detail_progress(self, event: str, payload: Dict[str, Any]) -> None:
        """Buffers a progress event for batched emission from the QThread.

        Events are accumulated in a thread-safe buffer and flushed by
        :meth:`flush_detail_progress`, which must only be called from the
        QThread's own thread (typically via the internal flush timer).
        """
        with self._detail_progress_lock:
            self._detail_progress_buffer.append({"event": event, "payload": payload})

    def flush_detail_progress(self) -> None:
        """Drains buffered progress events and emits them via Qt signals.

        Must only be called from the QThread's own thread.
        """
        with self._detail_progress_lock:
            if not self._detail_progress_buffer:
                return
            batch = list(self._detail_progress_buffer)
            self._detail_progress_buffer.clear()
        self.detail_progress_batch.emit(batch)

    def run(self) -> None:
        start_time = time.time()
        self.problems = []
        self.stats = create_empty_stats()
        self.pass1_series_scanned = set()
        self.pass2_series_scanned = set()
        for key in self.pass1_stats:
            self.pass1_stats[key] = 0
            self.pass2_stats[key] = 0
        self.changed_season_ids = set()
        self.changed_movie_ids = set()
        self.current_pass = 1
        self._scanned_series_ids.clear()
        self._scanned_movie_ids.clear()

        # Create and start the database writer thread
        self.database_queue = queue.Queue()
        self.database_writer = DatabaseWriterThread(self.database_queue)
        self.database_writer.start()

        try:
            logger.info(
                f"ScanWorker starting run for directories: {self.root_directories}"
            )
            self.unavailable_directories = []

            # Pre-discover the library tree structure and emit init_library_scan
            tree_structure = discover_single_library_tree_impl(
                self.root_directories, self.library_type, self.existing_library
            )
            self.emit_detail_progress(
                "init_library_scan",
                {"roots": tree_structure, "roots_order": self.root_directories},
            )
            self.flush_detail_progress()

            # Fetch Jellyfin correlation data if configured
            jellyfin_data: Optional[Dict[str, Any]] = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            def _detail_callback(event: str, payload: Dict[str, Any]) -> None:
                self.emit_detail_progress(event, payload)

            def _season_callback(
                series_name: str,
                series_data: Dict[str, Any],
                season_name: str,
                season_data: Dict[str, Any],
            ) -> None:
                logger.info(
                    f"ScanWorker writing season '{season_name}' of series '{series_name}' to database..."
                )
                try:
                    task = DatabaseWriteTask(
                        action="save_season",
                        payload={
                            "library_name": self.library_name,
                            "series_name": series_name,
                            "series_data": series_data,
                            "season_name": season_name,
                            "season_data": season_data,
                        },
                    )
                    self.database_queue.put(task)
                    wait_for_database_write_task(
                        task,
                        f"season '{season_name}' of series '{series_name}'",
                        timeout=config.database_write_timeout,
                    )
                    if task.error:
                        raise task.error
                    stats = task.result
                    if stats:
                        with self.scan_lock:
                            if "issues" in stats:
                                for issue in stats["issues"]:
                                    self.problems.append(issue)
                            target_stats = (
                                self.pass1_stats
                                if self.current_pass == 1
                                else self.pass2_stats
                            )
                            series_scanned_set = (
                                self.pass1_series_scanned
                                if self.current_pass == 1
                                else self.pass2_series_scanned
                            )
                            if series_name not in series_scanned_set:
                                series_scanned_set.add(series_name)
                                target_stats["series_scanned"] += 1
                                # Track in global set to avoid double-counting across passes
                                series_id = stats.get("series_id") or series_name
                                if series_id not in self._scanned_series_ids:
                                    self._scanned_series_ids.add(series_id)
                                    self.stats["series_scanned"] += 1
                                any_changed = any(
                                    s.get("_changed", True)
                                    for s in series_data.get("seasons", {}).values()
                                )
                                if not any_changed:
                                    target_stats["series_skipped"] += 1
                                    # Track skipped in global set
                                    if series_id not in self._scanned_series_ids:
                                        # This is a skipped series, track separately if needed
                                        pass
                                    self.stats["series_skipped"] += 1

                            target_stats["seasons_scanned"] += 1
                            self.stats["seasons_scanned"] += 1

                            episode_count = len(season_data.get("episodes", []))
                            target_stats["episodes_scanned"] += episode_count
                            self.stats["episodes_scanned"] += episode_count

                            if not season_data.get("_changed", True):
                                target_stats["seasons_skipped"] += 1
                                self.stats["seasons_skipped"] += 1
                                target_stats["episodes_skipped"] += episode_count
                                self.stats["episodes_skipped"] += episode_count

                            for key in self.stats:
                                if key in stats and not (
                                    key.endswith("_scanned") or key.endswith("_skipped")
                                ):
                                    self.stats[key] += stats[key]
                                    target_stats[key] += stats[key]
                            if (
                                season_data.get("_changed", True)
                                and "season_id" in stats
                            ):
                                self.changed_season_ids.add(stats["season_id"])
                except Exception as error:
                    with self.scan_lock:
                        log_db_write_error(
                            self.problems,
                            f"Season '{season_name}' of series '{series_name}'",
                            error,
                            logger,
                        )

            def _movie_callback(movie_name: str, movie_data: Dict[str, Any]) -> None:
                logger.info(f"ScanWorker writing movie '{movie_name}' to database...")
                try:
                    task = DatabaseWriteTask(
                        action="save_movie",
                        payload={
                            "library_name": self.library_name,
                            "movie_name": movie_name,
                            "movie_data": movie_data,
                        },
                    )
                    self.database_queue.put(task)
                    wait_for_database_write_task(
                        task,
                        f"movie '{movie_name}'",
                        timeout=config.database_write_timeout,
                    )
                    if task.error:
                        raise task.error
                    stats = task.result
                    if stats:
                        with self.scan_lock:
                            if "issues" in stats:
                                for issue in stats["issues"]:
                                    self.problems.append(issue)
                            target_stats = (
                                self.pass1_stats
                                if self.current_pass == 1
                                else self.pass2_stats
                            )
                            target_stats["movies_scanned"] += 1
                            # Track in global set to avoid double-counting across passes
                            movie_id = stats.get("movie_id") or movie_name
                            if movie_id not in self._scanned_movie_ids:
                                self._scanned_movie_ids.add(movie_id)
                                self.stats["movies_scanned"] += 1
                            if not movie_data.get("_changed", True):
                                target_stats["movies_skipped"] += 1
                                self.stats["movies_skipped"] += 1

                            for key in self.stats:
                                if key in stats and not (
                                    key.endswith("_scanned") or key.endswith("_skipped")
                                ):
                                    self.stats[key] += stats[key]
                                    target_stats[key] += stats[key]
                            if movie_data.get("_changed", True) and "movie_id" in stats:
                                self.changed_movie_ids.add(stats["movie_id"])
                except Exception as error:
                    with self.scan_lock:
                        log_db_write_error(
                            self.problems,
                            f"Movie '{movie_name}'",
                            error,
                            logger,
                        )

            library_config = config.libraries.get(self.library_name, {})
            show_future = library_config.get("show_future_episodes", True)

            # Pass 1: Offline local file scanner
            self.current_pass = 1
            logger.info(
                f"Starting Pass 1 (Offline Scan) for library '{self.library_name}' on directories: {self.root_directories}"
            )
            self.emit_detail_progress(
                "start_offline_scan", {"library": self.library_name}
            )
            library: LibraryDict = scan_directories(
                self.root_directories,
                library_type=self.library_type,
                existing_library=self.existing_library,
                jellyfin_data=None,
                callback=None,
                force_refresh=self.force_refresh,
                cleanup=self.cleanup,
                detail_callback=_detail_callback,
                show_future_episodes=show_future,
                offline=True,
                season_callback=_season_callback,
                movie_callback=_movie_callback,
                database_queue=self.database_queue,
            )
            logger.info(
                f"Finished Pass 1 (Offline Scan) for library '{self.library_name}'. Found {len(library)} stubs/entries."
            )
            # Emit the offline scan stubs so that UI shows files instantly
            self.partial_result.emit(library)
            self.flush_detail_progress()

            # Pass 2: Online metadata matching & resolver
            self.current_pass = 2
            logger.info(
                f"Starting Pass 2 (Online Metadata Resolution Scan) for library '{self.library_name}'"
            )
            self.emit_detail_progress(
                "start_metadata_resolution", {"library": self.library_name}
            )
            library = scan_directories(
                self.root_directories,
                library_type=self.library_type,
                existing_library=library,
                jellyfin_data=jellyfin_data,
                callback=self.partial_result.emit,
                force_refresh=self.force_refresh,
                cleanup=self.cleanup,
                detail_callback=_detail_callback,
                show_future_episodes=show_future,
                offline=False,
                season_callback=_season_callback,
                movie_callback=_movie_callback,
                metadata_only=True,
                database_queue=self.database_queue,
            )
            self.unavailable_directories = library.unavailable_directories
            if self.unavailable_directories:
                for root in self.unavailable_directories:
                    err_msg = f"Root directory '{root}' is unavailable on filesystem."
                    logger.warning(
                        f"[SCAN_ISSUE] Type=Unavailable Directory | Item={root} | Error={err_msg}"
                    )
                    self.problems.append(
                        {
                            "type": "Unavailable Directory",
                            "item": root,
                            "error": err_msg,
                        }
                    )

            logger.info(
                f"Finished Pass 2 (Online Metadata Resolution Scan) for library '{self.library_name}'"
            )
            self.flush_detail_progress()

            duration = time.time() - start_time
            logger.info(
                "[SCAN_REPORT] ==================================================="
            )
            logger.info("[SCAN_REPORT]               SCAN RUN STATS REPORT")
            logger.info(
                "[SCAN_REPORT] ==================================================="
            )
            logger.info(f"[SCAN_REPORT] Library Name: {self.library_name}")
            logger.info(f"[SCAN_REPORT] Library Type: {self.library_type}")
            logger.info(f"[SCAN_REPORT] Root Paths: {', '.join(self.root_directories)}")
            logger.info(f"[SCAN_REPORT] Total Scan Duration: {duration:.2f} seconds")
            if self.unavailable_directories:
                logger.info(
                    f"[SCAN_REPORT] Unavailable Root Directories: {', '.join(self.unavailable_directories)}"
                )
            logger.info(
                "[SCAN_REPORT] ---------------------------------------------------"
            )

            log_stats_breakdown(
                "PASS 1: OFFLINE FILE DISCOVERY BREAKDOWN", self.pass1_stats, logger
            )
            logger.info(
                "[SCAN_REPORT] ---------------------------------------------------"
            )
            log_stats_breakdown(
                "PASS 2: ONLINE METADATA RESOLUTION BREAKDOWN", self.pass2_stats, logger
            )
            logger.info(
                "[SCAN_REPORT] ---------------------------------------------------"
            )
            log_stats_breakdown("TOTAL ACCUMULATED RUN STATS", self.stats, logger)
            logger.info(
                "[SCAN_REPORT] ==================================================="
            )

            log_issues_report(self.problems, logger)

            logger.info("ScanWorker finished successfully")
            self.finished.emit(library)
        except Exception as exception:
            logger.exception("ScanWorker failed")
            exception_message = str(exception)
            self.error.emit(exception_message)
            self.library_error.emit(self.library_name, exception_message)
            self.emit_detail_progress("fail_library", {"library": self.library_name})
        finally:
            self.flush_detail_progress()
            if self.database_writer is not None:
                self.database_queue.put(None)
                self.database_writer.stop()
                self.database_writer.join()
