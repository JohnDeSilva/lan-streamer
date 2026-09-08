"""Background scan orchestration wrapping the reused desktop scanner."""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from typing import TYPE_CHECKING, Any

from scan_agent.config import AgentConfig, install_into_lan_streamer
from scan_agent.db.connection import get_session
from scan_agent.db.models import ScanJob
from scan_agent.db.repository import (
    get_or_create_library,
    load_library_dict,
    record_missing_files,
    upsert_library,
)
from scan_agent.db.serializers import scan_job_to_dict

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from scan_agent.scan.progress import ProgressBroker

logger = logging.getLogger(__name__)


class _BrokerLogHandler(logging.Handler):
    """Forward formatted log records from the scanner to the progress broker."""

    def __init__(self, broker: ProgressBroker) -> None:
        """Initialise the handler at INFO level with a compact formatter."""
        super().__init__(level=logging.INFO)
        self._broker = broker
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Publish the formatted record as a ``scan.log`` event."""
        try:
            self._broker.publish_log(self.format(record))
        except ValueError, TypeError, RuntimeError:
            self.handleError(record)


class ScanOrchestrator:
    """Runs the reused ``lan_streamer.scanner.scan_directories`` pipeline.

    One scan runs at a time in a background thread; progress and log lines
    are bridged into a :class:`ProgressBroker` for SSE consumers. Results are
    written into the agent database via the repository.
    """

    def __init__(
        self,
        agent_config: AgentConfig,
        engine: Engine,
        progress_broker: ProgressBroker,
    ) -> None:
        """Initialise the orchestrator and install the agent config bridge.

        The desktop config singleton is replaced *before* any scanner import
        so the reused providers read our keys dynamically.
        """
        self._agent_config = agent_config
        self._engine = engine
        self._progress_broker = progress_broker
        self._is_interrupted = threading.Event()
        self._state_lock = threading.Lock()
        self._running_job_id: int | None = None
        self._last_job_id: int | None = None
        install_into_lan_streamer(agent_config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_scan(
        self,
        library_identifier: str | int | None = None,
        pass_number: int = 0,
        force_refresh: bool = False,
    ) -> ScanJob:
        """Start a background scan and return the pending :class:`ScanJob`.

        Args:
            library_identifier: Config library id or name; ``None`` scans all
                configured libraries.
            pass_number: Scanner pass to run (0 = all, 1 = discovery,
                2 = metadata, 3 = technical).
            force_refresh: Re-scan even when directory mtimes match.

        Raises:
            RuntimeError: When another scan is already running.
            ValueError: When no libraries are configured or the identifier is
                unknown.
        """
        with self._state_lock:
            if self._running_job_id is not None:
                raise RuntimeError("A scan is already running")
            self._is_interrupted.clear()
            target_libraries = self._resolve_target_libraries(library_identifier)
            job = self._create_job(library_identifier, pass_number, target_libraries)
            self._running_job_id = job.id
        thread = threading.Thread(
            target=self._run_scan,
            args=(job.id, target_libraries, pass_number, force_refresh),
            name="scan-agent-scan",
            daemon=True,
        )
        try:
            thread.start()
        except Exception as error:
            with self._state_lock:
                self._running_job_id = None
            self._mark_job_failed(job.id, error)
            raise
        logger.info("Scan job %s started (%d libraries)", job.id, len(target_libraries))
        return job

    def cancel(self) -> None:
        """Request cancellation of the running scan.

        The scanner pipeline checks the interruption flag between items; the
        current item completes before the scan stops.
        """
        self._is_interrupted.set()
        logger.info("Scan cancellation requested")

    def status(self) -> dict[str, Any]:
        """Return running and last job information as plain dicts."""
        with self._state_lock:
            running_job_id = self._running_job_id
            last_job_id = self._last_job_id
        running_job: dict[str, Any] | None = None
        last_job: dict[str, Any] | None = None
        with get_session(self._engine) as session:
            if running_job_id is not None:
                job = session.get(ScanJob, running_job_id)
                running_job = scan_job_to_dict(job) if job is not None else None
            if last_job_id is not None:
                job = session.get(ScanJob, last_job_id)
                last_job = scan_job_to_dict(job) if job is not None else None
        return {
            "running": running_job,
            "last_job": last_job,
            "is_interrupted": self._is_interrupted.is_set(),
        }

    # ------------------------------------------------------------------
    # Background execution
    # ------------------------------------------------------------------

    def _run_scan(
        self,
        job_id: int,
        target_libraries: list[dict[str, Any]],
        pass_number: int,
        force_refresh: bool,
    ) -> None:
        """Execute the scan pipeline for every target library."""
        self._mark_job_running(job_id)
        log_handler = _BrokerLogHandler(self._progress_broker)
        lan_streamer_logger = logging.getLogger("lan_streamer")
        scan_agent_logger = logging.getLogger("scan_agent")
        lan_streamer_logger.addHandler(log_handler)
        scan_agent_logger.addHandler(log_handler)
        if (
            lan_streamer_logger.level > logging.INFO
            or lan_streamer_logger.level == logging.NOTSET
        ):
            lan_streamer_logger.setLevel(logging.INFO)
        if (
            scan_agent_logger.level > logging.INFO
            or scan_agent_logger.level == logging.NOTSET
        ):
            scan_agent_logger.setLevel(logging.INFO)
        pass_description = (
            "all passes (1+2+3)" if pass_number == 0 else f"pass {pass_number}"
        )
        self._progress_broker.publish_log(
            f"Scan job #{job_id} started for {len(target_libraries)} libraries ({pass_description})"
        )
        try:
            if pass_number in (0, 3) and shutil.which("ffprobe") is None:
                logger.warning(
                    "ffprobe not found on PATH; pass 3 technical metadata "
                    "will be skipped (files keep stub info)"
                )
            aggregate_stats: dict[str, Any] = {
                "series": 0,
                "seasons": 0,
                "episodes": 0,
                "movies": 0,
                "media_files": 0,
                "missing_files": 0,
                "unavailable_directories": [],
                "libraries": 0,
            }
            for library_definition in target_libraries:
                if self._is_interrupted.is_set():
                    logger.info("Scan job %s interrupted; stopping", job_id)
                    break
                library_stats = self._scan_single_library(
                    library_definition, pass_number, force_refresh
                )
                for key in (
                    "series",
                    "seasons",
                    "episodes",
                    "movies",
                    "media_files",
                    "missing_files",
                ):
                    aggregate_stats[key] += int(library_stats.get(key, 0))
                aggregate_stats["unavailable_directories"].extend(
                    library_stats.get("unavailable_directories", [])
                )
                aggregate_stats["libraries"] += 1
            if self._is_interrupted.is_set():
                self._mark_job_finished(job_id, "cancelled", aggregate_stats)
            else:
                self._mark_job_finished(job_id, "done", aggregate_stats)
        except Exception as error:
            logger.exception("Scan job %s failed", job_id)
            self._mark_job_failed(job_id, error)
        finally:
            logging.getLogger("lan_streamer").removeHandler(log_handler)
            logging.getLogger("scan_agent").removeHandler(log_handler)
            with self._state_lock:
                self._running_job_id = None
                self._last_job_id = job_id
            self._progress_broker.publish(
                "scan.finished",
                {"job_id": job_id, "status": self._load_job_status(job_id)},
            )
            logger.info("Scan job %s finished", job_id)

    def _scan_single_library(
        self,
        library_definition: dict[str, Any],
        pass_number: int,
        force_refresh: bool,
    ) -> dict[str, Any]:
        """Scan one library root and persist the results."""
        library_name = str(library_definition["name"])
        media_type = str(library_definition["media_type"])
        root_path = str(library_definition["root_path"])
        with get_session(self._engine) as session:
            library_row = get_or_create_library(
                session, library_name, media_type, root_path
            )
            existing_library = load_library_dict(session, library_row.id)
        # Lazy import: the desktop scanner must only be imported after the
        # config bridge has installed our agent config.
        from lan_streamer.scanner.core import scan_directories

        self._progress_broker.publish(
            "scan.progress",
            {
                "type": "library_start",
                "library": library_name,
                "root": root_path,
            },
        )
        self._progress_broker.publish_log(
            f"Scanning library '{library_name}' ({media_type}) at {root_path}..."
        )
        result = scan_directories(
            root_directories=[root_path],
            library_type=media_type,
            existing_library=existing_library,
            force_refresh=force_refresh,
            pass_number=pass_number,
            detail_callback=self._detail_callback,
            movie_callback=self._movie_callback,
            season_callback=self._season_callback,
            is_interrupted=self._is_interrupted.is_set,
        )
        with get_session(self._engine) as session:
            stats = upsert_library(
                session,
                {
                    "name": library_name,
                    "media_type": media_type,
                    "root_path": root_path,
                    "items": result,
                },
            )
            missing_count = record_missing_files(session, library_row.id, result)
        stats["missing_files"] = missing_count
        stats["unavailable_directories"] = list(result.unavailable_directories)
        self._progress_broker.publish(
            "scan.progress",
            {
                "type": "library_finished",
                "library": library_name,
                "stats": stats,
            },
        )
        self._progress_broker.publish_log(
            f"Library '{library_name}' finished: {stats.get('series', 0)} series, "
            f"{stats.get('episodes', 0)} episodes, {stats.get('movies', 0)} movies."
        )
        return stats

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _detail_callback(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Bridge scanner detail events into ``scan.progress`` events and logs."""
        self._progress_broker.publish(
            "scan.progress", {"type": event_type, **event_data}
        )
        if event_type == "start_offline_scan" or (
            event_type == "pass_start" and event_data.get("pass") == 1
        ):
            self._progress_broker.publish_log("--- Starting Pass 1: File Discovery ---")
        elif event_type == "start_metadata_resolution" or (
            event_type == "pass_start" and event_data.get("pass") == 2
        ):
            self._progress_broker.publish_log(
                "--- Starting Pass 2: TMDB Metadata Resolution ---"
            )
        elif event_type == "start_technical_probe" or (
            event_type == "pass_start" and event_data.get("pass") == 3
        ):
            self._progress_broker.publish_log(
                "--- Starting Pass 3: Technical Probing (ffprobe) ---"
            )

    def _movie_callback(self, movie_name: str, movie_data: dict[str, Any]) -> None:
        """Bridge scanner movie completion into a progress event."""
        self._progress_broker.publish(
            "scan.progress", {"type": "movie_finished", "movie": movie_name}
        )
        self._progress_broker.publish_log(f"Processed movie: '{movie_name}'")

    def _season_callback(
        self,
        series_name: str,
        series_data: dict[str, Any],
        season_name: str,
        season_data: dict[str, Any],
    ) -> None:
        """Bridge scanner season completion into a progress event."""
        self._progress_broker.publish(
            "scan.progress",
            {
                "type": "season_finished",
                "series": series_name,
                "season": season_name,
            },
        )
        self._progress_broker.publish_log(
            f"Processed season '{season_name}' of series '{series_name}'"
        )

    # ------------------------------------------------------------------
    # Job bookkeeping
    # ------------------------------------------------------------------

    def _resolve_target_libraries(
        self, library_identifier: str | int | None
    ) -> list[dict[str, Any]]:
        """Resolve config library definitions for a scan request."""
        libraries = self._agent_config.libraries
        if not libraries:
            raise ValueError("No libraries configured; add one before scanning")
        if library_identifier is None:
            return list(libraries.values())
        for identifier, definition in libraries.items():
            if str(identifier) == str(library_identifier) or definition.get(
                "name"
            ) == str(library_identifier):
                return [definition]
        raise ValueError(f"Unknown library identifier: {library_identifier}")

    def _create_job(
        self,
        library_identifier: str | int | None,
        pass_number: int,
        target_libraries: list[dict[str, Any]],
    ) -> ScanJob:
        """Persist a pending :class:`ScanJob` row and return it."""
        library_id: int | None = None
        if library_identifier is not None:
            definition = target_libraries[0]
            with get_session(self._engine) as session:
                library_row = get_or_create_library(
                    session,
                    str(definition["name"]),
                    str(definition["media_type"]),
                    str(definition["root_path"]),
                )
                library_id = library_row.id
        with get_session(self._engine) as session:
            job = ScanJob(
                library_id=library_id,
                pass_number=pass_number,
                status="pending",
                started_at=time.time(),
            )
            session.add(job)
            session.flush()
            session.refresh(job)
            return job

    def _mark_job_running(self, job_id: int) -> None:
        """Set the job status to ``running``."""
        with get_session(self._engine) as session:
            job = session.get(ScanJob, job_id)
            if job is not None:
                job.status = "running"

    def _mark_job_finished(
        self, job_id: int, status: str, stats: dict[str, Any]
    ) -> None:
        """Record a completed (done or cancelled) job with its stats."""
        with get_session(self._engine) as session:
            job = session.get(ScanJob, job_id)
            if job is not None:
                job.status = status
                job.finished_at = time.time()
                job.stats_json = json.dumps(stats)

    def _mark_job_failed(self, job_id: int, error: Exception) -> None:
        """Record a failed job with its error text."""
        with get_session(self._engine) as session:
            job = session.get(ScanJob, job_id)
            if job is not None:
                job.status = "error"
                job.finished_at = time.time()
                job.error_text = str(error)

    def _load_job_status(self, job_id: int) -> str:
        """Return the persisted status string for *job_id*."""
        with get_session(self._engine) as session:
            job = session.get(ScanJob, job_id)
            return job.status if job is not None else "unknown"
