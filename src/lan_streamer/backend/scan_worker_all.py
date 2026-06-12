import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer.scanner import (
    LibraryDict,
    VIDEO_EXTENSIONS,
    has_video_files,
)
from lan_streamer.backend.proxy import db, config, jellyfin_client, scan_directories

logger = logging.getLogger("lan_streamer.backend")


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
                    if library_type in ("tv", "anime"):
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
                    # Pass 1: Offline local file scanner
                    logger.info(
                        f"Starting Pass 1 (Offline Scan) for empty library '{library_name}'"
                    )
                    updated_library_data: LibraryDict = scan_directories(
                        [],
                        library_type=library_type,
                        existing_library=existing_library_data,
                        jellyfin_data=None,
                        callback=None,
                        force_refresh=self.force_refresh,
                        cleanup=False,
                        detail_callback=_make_detail_callback(library_name),
                        show_future_episodes=show_future,
                        offline=True,
                    )
                    logger.info(
                        f"Finished Pass 1 (Offline Scan) for empty library '{library_name}'. Found {len(updated_library_data)} stubs/entries."
                    )
                    self.unavailable_directories.extend(
                        updated_library_data.unavailable_directories
                    )
                    existing_library_data = updated_library_data

                    if library_type == "movie":
                        db.save_movie_library(library_name, existing_library_data)
                    else:
                        db.save_library(library_name, existing_library_data)

                    # Pass 2: Online metadata matching & resolver
                    logger.info(
                        f"Starting Pass 2 (Online Metadata Resolution Scan) for empty library '{library_name}'"
                    )
                    updated_library_data = scan_directories(
                        [],
                        library_type=library_type,
                        existing_library=existing_library_data,
                        jellyfin_data=jellyfin_data,
                        callback=None,
                        force_refresh=self.force_refresh,
                        cleanup=False,
                        detail_callback=_make_detail_callback(library_name),
                        show_future_episodes=show_future,
                        offline=False,
                    )
                    logger.info(
                        f"Finished Pass 2 (Online Metadata Resolution Scan) for empty library '{library_name}'"
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

                        # Pass 1: Offline local file scanner
                        logger.info(
                            f"Starting Pass 1 (Offline Scan) for library '{library_name}', root: '{root_dir}'"
                        )
                        updated_library_data = scan_directories(
                            [root_dir],
                            library_type=library_type,
                            existing_library=existing_library_data,
                            jellyfin_data=None,
                            callback=None,
                            force_refresh=self.force_refresh,
                            cleanup=False,
                            detail_callback=_make_detail_callback(library_name),
                            show_future_episodes=show_future,
                            offline=True,
                        )
                        logger.info(
                            f"Finished Pass 1 (Offline Scan) for library '{library_name}', root: '{root_dir}'. Found {len(updated_library_data)} stubs/entries."
                        )
                        existing_library_data = updated_library_data

                        if library_type == "movie":
                            db.save_movie_library(library_name, existing_library_data)
                        else:
                            db.save_library(library_name, existing_library_data)

                        # Pass 2: Online metadata matching & resolver
                        logger.info(
                            f"Starting Pass 2 (Online Metadata Resolution Scan) for library '{library_name}', root: '{root_dir}'"
                        )
                        updated_library_data = scan_directories(
                            [root_dir],
                            library_type=library_type,
                            existing_library=existing_library_data,
                            jellyfin_data=jellyfin_data,
                            callback=None,
                            force_refresh=self.force_refresh,
                            cleanup=False,
                            detail_callback=_make_detail_callback(library_name),
                            show_future_episodes=show_future,
                            offline=False,
                        )
                        logger.info(
                            f"Finished Pass 2 (Online Metadata Resolution Scan) for library '{library_name}', root: '{root_dir}'"
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
