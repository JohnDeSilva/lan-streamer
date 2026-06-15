import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer.scanner import (
    LibraryDict,
    has_video_files,
)
from lan_streamer.backend.proxy import (
    db,
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
        self.problems: List[Dict[str, Any]] = []
        self.stats: Dict[str, int] = {}
        self.changed_season_ids: Set[str] = set()
        self.changed_movie_ids: Set[str] = set()

    def run(self) -> None:
        self.problems = []
        self.stats = {
            "series_added": 0,
            "series_removed": 0,
            "seasons_added": 0,
            "seasons_removed": 0,
            "episodes_added": 0,
            "episodes_removed": 0,
            "movies_added": 0,
            "movies_removed": 0,
        }
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
                    stats = db.save_season_data(
                        self.library_name,
                        series_name,
                        series_data,
                        season_name,
                        season_data,
                    )
                    if stats:
                        if "issues" in stats:
                            for issue in stats["issues"]:
                                self.problems.append(issue)
                        for key in self.stats:
                            if key in stats:
                                self.stats[key] += stats[key]
                        if season_data.get("_changed", True) and "season_id" in stats:
                            self.changed_season_ids.add(stats["season_id"])
                except Exception as e:
                    err_msg = str(e)
                    clean_msg = err_msg.split("\n")[0].strip()
                    if "\n" in err_msg:
                        logger.debug(
                            f"Database write failure detailed error: {err_msg}"
                        )
                    logger.warning(
                        f"[SCAN_ISSUE] Type=Database Write Failure | Item=Season '{season_name}' of series '{series_name}' | Error={clean_msg}"
                    )
                    self.problems.append(
                        {
                            "type": "Database Write Failure",
                            "item": f"Season '{season_name}' of series '{series_name}'",
                            "error": clean_msg,
                        }
                    )

            def _movie_callback(movie_name: str, movie_data: Dict[str, Any]) -> None:
                logger.info(f"ScanWorker writing movie '{movie_name}' to database...")
                try:
                    stats = db.save_movie_data(
                        self.library_name, movie_name, movie_data
                    )
                    if stats:
                        if "issues" in stats:
                            for issue in stats["issues"]:
                                self.problems.append(issue)
                        for key in self.stats:
                            if key in stats:
                                self.stats[key] += stats[key]
                        if movie_data.get("_changed", True) and "movie_id" in stats:
                            self.changed_movie_ids.add(stats["movie_id"])
                except Exception as e:
                    err_msg = str(e)
                    clean_msg = err_msg.split("\n")[0].strip()
                    if "\n" in err_msg:
                        logger.debug(
                            f"Database write failure detailed error: {err_msg}"
                        )
                    logger.warning(
                        f"[SCAN_ISSUE] Type=Database Write Failure | Item=Movie '{movie_name}' | Error={clean_msg}"
                    )
                    self.problems.append(
                        {
                            "type": "Database Write Failure",
                            "item": f"Movie '{movie_name}'",
                            "error": clean_msg,
                        }
                    )

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
                season_callback=_season_callback,
                movie_callback=_movie_callback,
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
                season_callback=_season_callback,
                movie_callback=_movie_callback,
                metadata_only=True,
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

            logger.info(
                "[SCAN_REPORT] ==================================================="
            )
            logger.info("[SCAN_REPORT]               SCAN RUN STATS REPORT")
            logger.info(
                "[SCAN_REPORT] ==================================================="
            )
            logger.info(
                f"[SCAN_REPORT] Series Added: {self.stats.get('series_added', 0)}"
            )
            logger.info(
                f"[SCAN_REPORT] Series Removed: {self.stats.get('series_removed', 0)}"
            )
            logger.info(
                f"[SCAN_REPORT] Seasons Added: {self.stats.get('seasons_added', 0)}"
            )
            logger.info(
                f"[SCAN_REPORT] Seasons Removed: {self.stats.get('seasons_removed', 0)}"
            )
            logger.info(
                f"[SCAN_REPORT] Episodes Added: {self.stats.get('episodes_added', 0)}"
            )
            logger.info(
                f"[SCAN_REPORT] Episodes Removed: {self.stats.get('episodes_removed', 0)}"
            )
            if (
                self.stats.get("movies_added", 0) > 0
                or self.stats.get("movies_removed", 0) > 0
            ):
                logger.info(
                    f"[SCAN_REPORT] Movies Added: {self.stats.get('movies_added', 0)}"
                )
                logger.info(
                    f"[SCAN_REPORT] Movies Removed: {self.stats.get('movies_removed', 0)}"
                )
            logger.info(
                "[SCAN_REPORT] ==================================================="
            )

            if self.problems:
                grouped = {}
                for prob in self.problems:
                    t = prob["type"]
                    e = prob["error"]
                    item = prob["item"]
                    if t not in grouped:
                        grouped[t] = {}
                    if e not in grouped[t]:
                        grouped[t][e] = []
                    grouped[t][e].append(item)

                logger.info(
                    "[SCAN_REPORT] ==================================================="
                )
                logger.info("[SCAN_REPORT]               SCAN RUN ISSUES REPORT")
                logger.info(
                    "[SCAN_REPORT] ==================================================="
                )
                for t, errors in grouped.items():
                    logger.info(f"[SCAN_REPORT] Type: {t}")
                    for err, items in errors.items():
                        logger.info(f"[SCAN_REPORT]   Error: {err}")
                        for item in items:
                            logger.info(f"[SCAN_REPORT]     - {item}")
                    logger.info(
                        "[SCAN_REPORT] ---------------------------------------------------"
                    )
                logger.info(
                    "[SCAN_REPORT] ==================================================="
                )

            logger.info("ScanWorker finished successfully")
            self.finished.emit(library)
        except Exception as exc:
            logger.exception("ScanWorker failed")
            self.error.emit(str(exc))
