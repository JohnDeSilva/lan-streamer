import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer.scanner import (
    LibraryDict,
    has_video_files,
)
from lan_streamer.backend.proxy import (
    config,
    jellyfin_client,
    scan_directories,
    discover_single_library_tree,
)

logger = logging.getLogger("lan_streamer.backend")


def _discover_single_library_tree_impl(
    root_directories: List[str], library_type: str
) -> Dict[str, List[str]]:
    """
    Pre-walks all library directories to count total folders and files
    for a single library so the UI can initialize the segmented progress bar
    before scanning begins. Returns a structure mapping root_dir -> list of folder names.
    """
    roots: Dict[str, List[str]] = {}
    for root_dir in root_directories:
        root_path = Path(root_dir)
        if not root_path.exists() or not root_path.is_dir():
            roots[root_dir] = []
            continue
        folders = []
        for series_path in sorted(
            [
                x
                for x in root_path.iterdir()
                if x.is_dir() and not x.name.startswith(".") and has_video_files(x)
            ],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            folders.append(series_path.name)
        roots[root_dir] = folders
    return roots


class ScanWorker(QThread):
    """Scans a single library directory using TMDB for metadata."""

    finished = Signal(dict)
    partial_result = Signal(dict)
    error = Signal(str)
    detail_progress = Signal(str, dict)

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

    def run(self) -> None:
        try:
            logger.info(
                f"ScanWorker starting run for directories: {self.root_directories}"
            )
            self.unavailable_directories = []

            # Pre-discover the library tree structure and emit init_library_scan
            tree_structure = discover_single_library_tree(
                self.root_directories, self.library_type
            )
            self.detail_progress.emit(
                "init_library_scan",
                {"roots": tree_structure, "roots_order": self.root_directories},
            )

            # Fetch Jellyfin correlation data if configured
            jellyfin_data: Optional[Dict[str, Any]] = None
            if jellyfin_client.is_configured():
                jellyfin_data = jellyfin_client.get_jellyfin_correlation_data()

            def _detail_callback(event: str, payload: Dict[str, Any]) -> None:
                self.detail_progress.emit(event, payload)

            library_config = config.libraries.get(self.library_name, {})
            show_future = library_config.get("show_future_episodes", True)

            # Pass 1: Offline local file scanner
            logger.info(
                f"Starting Pass 1 (Offline Scan) for library '{self.library_name}' on directories: {self.root_directories}"
            )
            self.detail_progress.emit(
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
            )
            logger.info(
                f"Finished Pass 1 (Offline Scan) for library '{self.library_name}'. Found {len(library)} stubs/entries."
            )
            # Emit the offline scan stubs so that UI shows files instantly
            self.partial_result.emit(library)

            # Pass 2: Online metadata matching & resolver
            logger.info(
                f"Starting Pass 2 (Online Metadata Resolution Scan) for library '{self.library_name}'"
            )
            self.detail_progress.emit(
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
            )
            self.unavailable_directories = library.unavailable_directories
            logger.info(
                f"Finished Pass 2 (Online Metadata Resolution Scan) for library '{self.library_name}'"
            )
            logger.info("ScanWorker finished successfully")
            self.finished.emit(library)
        except Exception as exc:
            logger.exception("ScanWorker failed")
            self.error.emit(str(exc))
