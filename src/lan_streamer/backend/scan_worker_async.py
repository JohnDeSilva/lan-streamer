"""Async-native scan worker for a single library.

Runs the synchronous ``scan_directories`` scanner in the dedicated
filesystem executor (``run_in_fs_executor``) while using
``AsyncDatabaseWriter`` for database writes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import QObject, Signal

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.backend.database_writer import AsyncDatabaseWriter
from lan_streamer.backend.scan_worker_base import (
    create_empty_stats,
    discover_single_library_tree_impl,
    log_db_write_error,
    log_issues_report,
    log_stats_breakdown,
)
from lan_streamer.scanner import LibraryDict, scan_directories
from lan_streamer.system.async_task_manager import AsyncTaskManager
from lan_streamer.system.async_utils import run_in_fs_executor
from lan_streamer.system.config import config

logger = logging.getLogger("lan_streamer.backend")


class AsyncScanWorker(AsyncWorkerBase):
    """Async version of :class:`~lan_streamer.backend.scan_worker_single.ScanWorker`.

    Uses ``AsyncDatabaseWriter`` for DB writes and runs the synchronous
    scanner via ``run_in_fs_executor`` in the dedicated filesystem pool.
    """

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
        async_task_manager: Optional[AsyncTaskManager] = None,
        force_refresh: bool = False,
        cleanup: bool = False,
        parent: Optional[QObject] = None,
        library_name: str = "",
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.root_directories: List[str] = root_directories
        self.library_type: str = library_type
        self.existing_library: Dict[str, Any] = existing_library
        self.force_refresh: bool = force_refresh
        self.cleanup: bool = cleanup
        self.library_name: str = library_name

        # Result state — readable after finished signal.
        self.unavailable_directories: List[str] = []
        self.problems: List[Dict[str, Any]] = []
        self.stats: Dict[str, int] = create_empty_stats()
        self.changed_season_ids: Set[str] = set()
        self.changed_movie_ids: Set[str] = set()

        # Pass tracking
        self.current_pass: int = 1
        self.pass1_stats: Dict[str, int] = create_empty_stats()
        self.pass2_stats: Dict[str, int] = create_empty_stats()
        self._scanned_series_ids: Set[str] = set()
        self._scanned_movie_ids: Set[str] = set()
        self._skipped_series_ids: Set[str] = set()
        self._skipped_movie_ids: Set[str] = set()

        # Async database writer — created in run_async
        self.database_writer: Optional[AsyncDatabaseWriter] = None

        # Detail-progress buffer (thread-safe, lock-free by design: only
        # mutated in the run_async coroutine, not from scanner threads).
        self._detail_progress_buffer: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API — overrides AsyncWorkerBase
    # ------------------------------------------------------------------

    async def run_async(self) -> Dict[str, Any]:
        """Execute the two-pass scan (offline + metadata resolution)."""
        start_time = time.time()
        self.problems = []
        self.stats = create_empty_stats()
        self._reset_pass_stats()
        self.changed_season_ids = set()
        self.changed_movie_ids = set()
        self.current_pass = 1
        self._scanned_series_ids.clear()
        self._scanned_movie_ids.clear()
        self._skipped_series_ids.clear()
        self._skipped_movie_ids.clear()

        # Create and start the async database writer
        self.database_writer = AsyncDatabaseWriter()
        await self.database_writer.start()

        loop = asyncio.get_running_loop()

        try:
            self.unavailable_directories = []

            # Pre-discover tree structure
            tree_structure = discover_single_library_tree_impl(
                self.root_directories, self.library_type, self.existing_library
            )
            self._emit_detail_progress(
                "init_library_scan",
                {"roots": tree_structure, "roots_order": self.root_directories},
            )
            self._flush_detail_progress()

            # Fetch jellyfin correlation data (sync call for now; could be
            # replaced with async client in a follow-up).
            jellyfin_data: Optional[Dict[str, Any]] = None
            from lan_streamer.providers.jellyfin import jellyfin_client

            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            library_config = config.libraries.get(self.library_name, {})
            show_future = library_config.get("show_future_episodes", True)

            # Callbacks for the sync scanner
            def _detail_callback(event: str, payload: Dict[str, Any]) -> None:
                # This runs inside the scanner thread; queue for flush later.
                self._detail_progress_buffer.append(
                    {"event": event, "payload": payload}
                )

            def _season_callback(
                series_name: str,
                series_data: Dict[str, Any],
                season_name: str,
                season_data: Dict[str, Any],
            ) -> None:
                assert self.database_writer is not None
                logger.info(
                    "AsyncScanWorker writing season '%s' of series '%s' to database...",
                    season_name,
                    series_name,
                )
                try:
                    task = self.database_writer.sync_submit(
                        "save_season",
                        {
                            "library_name": self.library_name,
                            "series_name": series_name,
                            "series_data": series_data,
                            "season_name": season_name,
                            "season_data": season_data,
                        },
                        loop,
                    )
                    if task.error:
                        raise task.error
                    self._merge_season_result(
                        task.result,
                        series_name,
                        series_data,
                        season_name,
                        season_data,
                    )
                except Exception as error:
                    log_db_write_error(
                        self.problems,
                        f"Season '{season_name}' of series '{series_name}'",
                        error,
                        logger,
                    )

            def _movie_callback(movie_name: str, movie_data: Dict[str, Any]) -> None:
                assert self.database_writer is not None
                logger.info(
                    "AsyncScanWorker writing movie '%s' to database...",
                    movie_name,
                )
                try:
                    task = self.database_writer.sync_submit(
                        "save_movie",
                        {
                            "library_name": self.library_name,
                            "movie_name": movie_name,
                            "movie_data": movie_data,
                        },
                        loop,
                    )
                    if task.error:
                        raise task.error
                    self._merge_movie_result(task.result, movie_name, movie_data)
                except Exception as error:
                    log_db_write_error(
                        self.problems,
                        f"Movie '{movie_name}'",
                        error,
                        logger,
                    )

            # ------------------------------------------------------------------
            # Pass 1: Offline local file scanner
            # ------------------------------------------------------------------
            self.current_pass = 1
            logger.info(
                "AsyncScanWorker Pass 1 starting for library '%s'",
                self.library_name,
            )
            self._emit_detail_progress(
                "start_offline_scan", {"library": self.library_name}
            )

            library: LibraryDict = await run_in_fs_executor(
                scan_directories,
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
                database_queue=None,
                is_interrupted=lambda: self._cancelled,
            )
            if self._cancelled:
                logger.info("AsyncScanWorker cancelled during Pass 1.")
                return {}

            logger.info(
                "Pass 1 finished for '%s': %d entries.",
                self.library_name,
                len(library),
            )
            self.partial_result.emit(library)
            self._flush_detail_progress()

            # ------------------------------------------------------------------
            # Pass 2: Online metadata resolution
            # ------------------------------------------------------------------
            self.current_pass = 2
            logger.info(
                "AsyncScanWorker Pass 2 starting for library '%s'",
                self.library_name,
            )
            self._emit_detail_progress(
                "start_metadata_resolution", {"library": self.library_name}
            )

            library = await run_in_fs_executor(
                scan_directories,
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
                database_queue=None,
                is_interrupted=lambda: self._cancelled,
            )
            if self._cancelled:
                logger.info("AsyncScanWorker cancelled during Pass 2.")
                return {}

            self.unavailable_directories = library.unavailable_directories
            self._log_unavailable_directories()

            self._flush_detail_progress()

            # ------------------------------------------------------------------
            # Log final stats
            # ------------------------------------------------------------------
            duration = time.time() - start_time
            self._log_scan_summary(duration)

            logger.info("AsyncScanWorker finished successfully.")
            return library

        except Exception as exception:
            logger.exception(
                "AsyncScanWorker failed for library '%s'",
                self.library_name,
            )
            self.library_error.emit(self.library_name, str(exception))
            self._emit_detail_progress("fail_library", {"library": self.library_name})
            raise
        finally:
            self._flush_detail_progress()
            if self.database_writer is not None:
                await self.database_writer.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reset_pass_stats(self) -> None:
        for key in self.pass1_stats:
            self.pass1_stats[key] = 0
            self.pass2_stats[key] = 0

    def _emit_detail_progress(self, event: str, payload: Dict[str, Any]) -> None:
        self._detail_progress_buffer.append({"event": event, "payload": payload})
        if len(self._detail_progress_buffer) >= 20:
            self._flush_detail_progress()

    def _flush_detail_progress(self) -> None:
        if not self._detail_progress_buffer:
            return
        batch = list(self._detail_progress_buffer)
        self._detail_progress_buffer.clear()
        self.detail_progress_batch.emit(batch)

    def _merge_season_result(
        self,
        stats: Optional[Dict[str, Any]],
        series_name: str,
        series_data: Dict[str, Any],
        season_name: str,
        season_data: Dict[str, Any],
    ) -> None:
        if not stats:
            return
        if "issues" in stats:
            for issue in stats["issues"]:
                self.problems.append(issue)

        target_stats = self.pass1_stats if self.current_pass == 1 else self.pass2_stats

        series_id = stats.get("series_id") or series_name
        if series_id not in self._scanned_series_ids:
            self._scanned_series_ids.add(series_id)
            self.stats["series_scanned"] += 1
        target_stats["series_scanned"] += 1

        any_changed = any(
            s.get("_changed", True) for s in series_data.get("seasons", {}).values()
        )
        if not any_changed:
            target_stats["series_skipped"] += 1
            if series_id not in self._skipped_series_ids:
                self._skipped_series_ids.add(series_id)
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

        if season_data.get("_changed", True) and "season_id" in stats:
            self.changed_season_ids.add(stats["season_id"])

    def _merge_movie_result(
        self,
        stats: Optional[Dict[str, Any]],
        movie_name: str,
        movie_data: Dict[str, Any],
    ) -> None:
        if not stats:
            return
        if "issues" in stats:
            for issue in stats["issues"]:
                self.problems.append(issue)

        target_stats = self.pass1_stats if self.current_pass == 1 else self.pass2_stats
        target_stats["movies_scanned"] += 1

        movie_id = stats.get("movie_id") or movie_name
        if movie_id not in self._scanned_movie_ids:
            self._scanned_movie_ids.add(movie_id)
            self.stats["movies_scanned"] += 1

        if not movie_data.get("_changed", True):
            target_stats["movies_skipped"] += 1
            if movie_id not in self._skipped_movie_ids:
                self._skipped_movie_ids.add(movie_id)
                self.stats["movies_skipped"] += 1

        for key in self.stats:
            if key in stats and not (
                key.endswith("_scanned") or key.endswith("_skipped")
            ):
                self.stats[key] += stats[key]
                target_stats[key] += stats[key]

        if movie_data.get("_changed", True) and "movie_id" in stats:
            self.changed_movie_ids.add(stats["movie_id"])

    def _log_unavailable_directories(self) -> None:
        for root in self.unavailable_directories:
            msg = f"Root directory '{root}' is unavailable on filesystem."
            logger.warning(
                "[SCAN_ISSUE] Type=Unavailable Directory | Item=%s | Error=%s",
                root,
                msg,
            )
            self.problems.append(
                {"type": "Unavailable Directory", "item": root, "error": msg}
            )

    def _log_scan_summary(self, duration: float) -> None:
        logger.info("[SCAN_REPORT] ===================================================")
        logger.info("[SCAN_REPORT]               SCAN RUN STATS REPORT")
        logger.info("[SCAN_REPORT] ===================================================")
        logger.info("[SCAN_REPORT] Library Name: %s", self.library_name)
        logger.info("[SCAN_REPORT] Library Type: %s", self.library_type)
        logger.info(
            "[SCAN_REPORT] Root Paths: %s",
            ", ".join(self.root_directories),
        )
        logger.info("[SCAN_REPORT] Total Scan Duration: %.2f seconds", duration)
        if self.unavailable_directories:
            logger.info(
                "[SCAN_REPORT] Unavailable Root Directories: %s",
                ", ".join(self.unavailable_directories),
            )
        logger.info("[SCAN_REPORT] ---------------------------------------------------")
        log_stats_breakdown(
            "PASS 1: OFFLINE FILE DISCOVERY BREAKDOWN",
            self.pass1_stats,
            logger,
        )
        logger.info("[SCAN_REPORT] ---------------------------------------------------")
        log_stats_breakdown(
            "PASS 2: ONLINE METADATA RESOLUTION BREAKDOWN",
            self.pass2_stats,
            logger,
        )
        logger.info("[SCAN_REPORT] ---------------------------------------------------")
        log_stats_breakdown("TOTAL ACCUMULATED RUN STATS", self.stats, logger)
        logger.info("[SCAN_REPORT] ===================================================")
        log_issues_report(self.problems, logger)
