"""Filesystem event watcher triggering debounced library scans."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scan_agent.config import AgentConfig
    from scan_agent.scan.orchestrator import ScanOrchestrator

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".ts",
    ".iso",
}

SUBTITLE_EXTENSIONS = {
    ".srt",
    ".sub",
    ".idx",
    ".vtt",
    ".ass",
    ".ssa",
}

MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS

IGNORED_EXTENSIONS = {
    ".part",
    ".crdownload",
    ".!ut",
    ".tmp",
    ".temp",
    ".aria2",
    ".download",
    ".swp",
    ".swo",
}

IGNORED_FILENAMES = {
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
}


def is_relevant_filesystem_path(path_string: str) -> bool:
    """Return True if the changed path is a relevant media file or directory."""
    path_object = Path(path_string)
    file_name = path_object.name.lower()

    if file_name in IGNORED_FILENAMES:
        return False

    for directory_part in path_object.parts:
        if directory_part.startswith(".") and directory_part != ".":
            return False

    suffix = path_object.suffix.lower()
    if suffix in IGNORED_EXTENSIONS:
        return False
    if suffix in MEDIA_EXTENSIONS:
        return True
    return bool(not suffix)


def match_library_for_path(
    path_string: str, libraries: dict[str, dict[str, Any]]
) -> str | None:
    """Find the configured enabled library matching the changed filesystem path."""
    target_path = os.path.abspath(path_string)
    for library_identifier, library_data in libraries.items():
        if not library_data.get("enabled", True):
            continue
        library_root = library_data.get("root_path")
        if not library_root:
            continue
        library_root_path = os.path.abspath(library_root)
        if target_path == library_root_path or target_path.startswith(
            library_root_path + os.sep
        ):
            return library_identifier
    return None


class FilesystemWatcher:
    """Monitors library root paths and triggers scans after a debounce delay."""

    def __init__(
        self,
        agent_config: AgentConfig,
        scan_orchestrator: ScanOrchestrator,
    ) -> None:
        self._agent_config = agent_config
        self._orchestrator = scan_orchestrator
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.pending_scans: dict[str, float] = {}

    @property
    def is_running(self) -> bool:
        """Return True if the background watcher thread is running."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def debounce_seconds(self) -> int:
        """Return the configured debounce delay in seconds."""
        return max(1, self._agent_config.filesystem_watching_debounce_seconds)

    def start(self) -> None:
        """Start the background filesystem watcher thread."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="scan-agent-watcher",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Filesystem watcher started (debounce: %d seconds)",
            self.debounce_seconds,
        )

    def stop(self) -> None:
        """Stop the background filesystem watcher thread and join it."""
        if not self.is_running or self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        self._thread = None
        logger.info("Filesystem watcher stopped")

    def record_change(self, path_string: str) -> None:
        """Record a filesystem change and reset the debounce window."""
        if not self._agent_config.filesystem_watching_enabled:
            return
        if not is_relevant_filesystem_path(path_string):
            return
        library_identifier = match_library_for_path(
            path_string, self._agent_config.libraries
        )
        if library_identifier is None:
            return

        with self._lock:
            debounce_duration = self.debounce_seconds
            self.pending_scans[library_identifier] = (
                time.monotonic() + debounce_duration
            )
            logger.debug(
                "Change recorded for library '%s' (%s). Debouncing for %d seconds",
                library_identifier,
                path_string,
                debounce_duration,
            )

    def _process_pending_scans(self) -> None:
        """Check pending library scans and trigger those whose debounce expired."""
        with self._lock:
            if not self.pending_scans:
                return
            current_monotonic = time.monotonic()
            for library_identifier, trigger_time in list(self.pending_scans.items()):
                if current_monotonic >= trigger_time:
                    status_dict = self._orchestrator.status()
                    if status_dict.get("running") is not None:
                        logger.debug(
                            "Scan for library '%s' deferred: orchestrator is busy",
                            library_identifier,
                        )
                        continue
                    try:
                        self._orchestrator.start_scan(
                            library_identifier=library_identifier,
                            pass_number=0,
                            force_refresh=False,
                        )
                        del self.pending_scans[library_identifier]
                        logger.info(
                            "Filesystem watcher initiated scan for library '%s'",
                            library_identifier,
                        )
                    except RuntimeError as runtime_error:
                        logger.debug(
                            "Orchestrator busy when triggering scan for '%s': %s",
                            library_identifier,
                            runtime_error,
                        )
                    except ValueError, OSError:
                        logger.exception(
                            "Filesystem watcher failed to trigger scan for '%s'",
                            library_identifier,
                        )
                        del self.pending_scans[library_identifier]

    def _run_loop(self) -> None:
        """Background thread monitoring directories using watchfiles."""
        from watchfiles import watch

        while not self._stop_event.is_set():
            if not self._agent_config.filesystem_watching_enabled:
                self._stop_event.wait(timeout=2.0)
                continue

            valid_paths: list[str] = [
                os.path.abspath(library_data["root_path"])
                for library_data in self._agent_config.libraries.values()
                if library_data.get("enabled", True)
                and library_data.get("root_path")
                and os.path.exists(library_data["root_path"])
            ]

            if not valid_paths:
                self._stop_event.wait(timeout=2.0)
                continue

            try:
                for changes in watch(
                    *valid_paths,
                    stop_event=self._stop_event,
                    rust_timeout=1000,
                    yield_on_timeout=True,
                    ignore_permission_denied=True,
                ):
                    if self._stop_event.is_set():
                        break

                    for _change_type, path_string in changes:
                        self.record_change(path_string)

                    self._process_pending_scans()

                    current_valid_paths = [
                        os.path.abspath(library_data["root_path"])
                        for library_data in self._agent_config.libraries.values()
                        if library_data.get("enabled", True)
                        and library_data.get("root_path")
                        and os.path.exists(library_data["root_path"])
                    ]
                    if (
                        set(current_valid_paths) != set(valid_paths)
                        or not self._agent_config.filesystem_watching_enabled
                    ):
                        break
            except (OSError, RuntimeError) as watch_error:
                logger.warning(
                    "Filesystem watcher encountered an unexpected error: %s",
                    watch_error,
                )
                self._stop_event.wait(timeout=2.0)

            self._process_pending_scans()
