import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer.backend.proxy import (
    db,
    config,
    jellyfin_client,
    scan_directories,
    discover_single_library_tree,
)
from lan_streamer.scanner import (
    LibraryDict,
    VIDEO_EXTENSIONS,
    has_video_files,
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

            library: LibraryDict = scan_directories(
                self.root_directories,
                library_type=self.library_type,
                existing_library=self.existing_library,
                jellyfin_data=jellyfin_data,
                callback=self.partial_result.emit,
                force_refresh=self.force_refresh,
                cleanup=self.cleanup,
                detail_callback=_detail_callback,
                show_future_episodes=show_future,
            )
            self.unavailable_directories = library.unavailable_directories
            logger.info("ScanWorker finished successfully")
            self.finished.emit(library)
        except Exception as exc:
            logger.exception("ScanWorker failed")
            self.error.emit(str(exc))


class CleanupWorker(QThread):
    """Removes missing series/seasons/episodes from the database."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        library_name: str,
        root_directories: List[str],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.library_name: str = library_name
        self.root_directories: List[str] = root_directories

    def run(self) -> None:
        try:
            logger.info(f"CleanupWorker starting for library {self.library_name}")
            results: Dict[str, Any] = db.cleanup_library(
                self.library_name, self.root_directories
            )
            logger.info(f"CleanupWorker finished with results: {results}")
            self.finished.emit(results)
        except Exception as exc:
            logger.exception("CleanupWorker failed")
            self.error.emit(str(exc))


class ScanAllLibrariesWorker(QThread):
    """Scans all configured libraries sequentially using TMDB for metadata."""

    library_progress = Signal(str, int, int)
    detail_progress = Signal(str, dict)  # (event_type, payload)
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        force_refresh: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.force_refresh: bool = force_refresh
        self.unavailable_directories: List[str] = []

    def _discover_tree(self) -> Dict[str, Any]:
        """
        Pre-walks all library directories to count total folders and files
        so the UI can initialise the tree and segmented progress bar before
        scanning begins.  Returns a structure keyed by library name.
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
                    if library_type == "tv":
                        seasons: Dict[str, List[str]] = {}
                        for season_path in series_path.iterdir():
                            if season_path.is_dir() and not season_path.name.startswith(
                                "."
                            ):
                                episodes: List[str] = []
                                for ep_path in season_path.iterdir():
                                    if (
                                        ep_path.is_file()
                                        and ep_path.suffix.lower() in VIDEO_EXTENSIONS
                                    ):
                                        episodes.append(ep_path.name)
                                seasons[season_path.name] = sorted(episodes)
                        folders[series_name] = {"seasons": seasons}
                    else:
                        folders[series_name] = {}
                roots[root_dir] = folders
            tree[library_name] = {"type": library_type, "roots": roots}
        return tree

    def run(self) -> None:
        try:
            logger.info("ScanAllLibrariesWorker starting global scan run")
            libraries_dictionary = config.libraries
            total_count: int = len(libraries_dictionary)
            completed_count: int = 0
            self.unavailable_directories = []

            # Pre-discover tree structure and tell the UI to initialise it
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

            for library_name, library_configuration in libraries_dictionary.items():
                logger.info(f"ScanAllLibrariesWorker scanning library: {library_name}")
                root_directories: List[str] = list(
                    library_configuration.get("paths", [])
                )
                library_type: str = library_configuration.get("type", "tv")
                show_future: bool = library_configuration.get(
                    "show_future_episodes", True
                )

                self.detail_progress.emit("start_library", {"library": library_name})

                existing_library_data: Dict[str, Any] = {}
                if library_type == "movie":
                    existing_library_data = db.load_movie_library(library_name)
                else:
                    existing_library_data = db.load_library(library_name)

                def _make_detail_callback(lib_name: str) -> Any:
                    worker_self = self

                    def _detail_callback(event: str, payload: Dict[str, Any]) -> None:
                        enriched = {"library": lib_name, **payload}
                        worker_self.detail_progress.emit(event, enriched)

                    return _detail_callback

                # Scan root directories one by one
                if not root_directories:
                    updated_library_data: LibraryDict = scan_directories(
                        [],
                        library_type=library_type,
                        existing_library=existing_library_data,
                        jellyfin_data=jellyfin_data,
                        callback=None,
                        force_refresh=self.force_refresh,
                        cleanup=False,
                        detail_callback=_make_detail_callback(library_name),
                        show_future_episodes=show_future,
                    )
                    self.unavailable_directories.extend(
                        updated_library_data.unavailable_directories
                    )
                    existing_library_data = updated_library_data

                    if library_type == "movie":
                        db.save_movie_library(library_name, existing_library_data)
                    else:
                        db.save_library(library_name, existing_library_data)
                else:
                    for root_dir in root_directories:
                        self.detail_progress.emit(
                            "start_root", {"library": library_name, "root": root_dir}
                        )

                        updated_library_data: LibraryDict = scan_directories(
                            [root_dir],
                            library_type=library_type,
                            existing_library=existing_library_data,
                            jellyfin_data=jellyfin_data,
                            callback=None,
                            force_refresh=self.force_refresh,
                            cleanup=False,
                            detail_callback=_make_detail_callback(library_name),
                            show_future_episodes=show_future,
                        )
                        self.unavailable_directories.extend(
                            updated_library_data.unavailable_directories
                        )
                        existing_library_data = updated_library_data

                        if library_type == "movie":
                            db.save_movie_library(library_name, existing_library_data)
                        else:
                            db.save_library(library_name, existing_library_data)

                        self.detail_progress.emit(
                            "finish_root", {"library": library_name, "root": root_dir}
                        )

                completed_count += 1
                self.detail_progress.emit("finish_library", {"library": library_name})
                self.library_progress.emit(library_name, completed_count, total_count)

            logger.info("ScanAllLibrariesWorker finished successfully")
            self.finished.emit()
        except Exception as exception_instance:
            logger.exception("ScanAllLibrariesWorker failed")
            self.error.emit(str(exception_instance))
