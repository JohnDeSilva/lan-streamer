import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer.scanner import (
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
        self.problems: List[Dict[str, Any]] = []
        self.stats: Dict[str, int] = {}
        self.changed_season_ids: Set[str] = set()
        self.changed_movie_ids: Set[str] = set()

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
            logger.info("ScanAllLibrariesWorker starting global scan run")
            libraries_dictionary = config.libraries
            total_count: int = len(libraries_dictionary)
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

            # Helper dictionary to persist the intermediate library state from Pass 1 to Pass 2
            library_data_by_name: Dict[str, Dict[str, Any]] = {}
            for library_name, library_configuration in libraries_dictionary.items():
                library_type = library_configuration.get("type", "tv")
                if library_type == "movie":
                    library_data_by_name[library_name] = db.load_movie_library(
                        library_name
                    )
                else:
                    library_data_by_name[library_name] = db.load_library(library_name)

            # --- PASS 1: OFFLINE FILE SCAN ---
            logger.info("ScanAllLibrariesWorker starting Pass 1 (Offline Scan)")
            self.detail_progress.emit("start_offline_scan", {})

            for library_name, library_configuration in libraries_dictionary.items():
                logger.info(
                    f"ScanAllLibrariesWorker Pass 1 scanning library: {library_name}"
                )
                root_directories = list(library_configuration.get("paths", []))
                library_type = library_configuration.get("type", "tv")
                show_future = library_configuration.get("show_future_episodes", True)
                existing_library_data = library_data_by_name[library_name]

                self.detail_progress.emit("start_library", {"library": library_name})

                def _make_detail_callback(lib_name: str) -> Any:
                    worker_self = self

                    def _detail_callback(event: str, payload: Dict[str, Any]) -> None:
                        enriched = {"library": lib_name, **payload}
                        worker_self.detail_progress.emit(event, enriched)

                    return _detail_callback

                def _season_callback(
                    series_name: str,
                    series_data: Dict[str, Any],
                    season_name: str,
                    season_data: Dict[str, Any],
                ) -> None:
                    logger.info(
                        f"ScanAllLibrariesWorker writing season '{season_name}' of series '{series_name}' to database..."
                    )
                    try:
                        stats = db.save_season_data(
                            library_name,
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
                            if (
                                season_data.get("_changed", True)
                                and "season_id" in stats
                            ):
                                self.changed_season_ids.add(stats["season_id"])
                    except Exception as e:
                        err_msg = str(e)
                        clean_msg = err_msg.split("\n")[0].strip()
                        if "\n" in err_msg:
                            logger.debug(
                                f"Database write failure detailed error: {err_msg}"
                            )
                        logger.warning(
                            f"[SCAN_ISSUE] Type=Database Write Failure | Item=Season '{season_name}' of series '{series_name}' (Library: '{library_name}') | Error={clean_msg}"
                        )
                        self.problems.append(
                            {
                                "type": "Database Write Failure",
                                "item": f"Season '{season_name}' of series '{series_name}' (Library: '{library_name}')",
                                "error": clean_msg,
                            }
                        )

                def _movie_callback(
                    movie_name: str, movie_data: Dict[str, Any]
                ) -> None:
                    logger.info(
                        f"ScanAllLibrariesWorker writing movie '{movie_name}' to database..."
                    )
                    try:
                        stats = db.save_movie_data(library_name, movie_name, movie_data)
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
                            f"[SCAN_ISSUE] Type=Database Write Failure | Item=Movie '{movie_name}' (Library: '{library_name}') | Error={clean_msg}"
                        )
                        self.problems.append(
                            {
                                "type": "Database Write Failure",
                                "item": f"Movie '{movie_name}' (Library: '{library_name}')",
                                "error": clean_msg,
                            }
                        )

                def _save_lib_data(lib_data: Dict[str, Any]) -> None:
                    try:
                        if library_type == "movie":
                            stats = db.save_movie_library(library_name, lib_data)
                        else:
                            stats = db.save_library(library_name, lib_data)
                        if stats:
                            if "issues" in stats:
                                for issue in stats["issues"]:
                                    self.problems.append(issue)
                            for key in self.stats:
                                if key in stats:
                                    self.stats[key] += stats[key]
                    except Exception as e:
                        err_msg = str(e)
                        clean_msg = err_msg.split("\n")[0].strip()
                        if "\n" in err_msg:
                            logger.debug(
                                f"Database write failure detailed error: {err_msg}"
                            )
                        logger.warning(
                            f"[SCAN_ISSUE] Type=Database Write Failure | Item=Library '{library_name}' | Error={clean_msg}"
                        )
                        self.problems.append(
                            {
                                "type": "Database Write Failure",
                                "item": f"Library '{library_name}'",
                                "error": clean_msg,
                            }
                        )

                if not root_directories:
                    updated_library_data = scan_directories(
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
                        season_callback=_season_callback,
                        movie_callback=_movie_callback,
                    )
                    if updated_library_data.unavailable_directories:
                        for root in updated_library_data.unavailable_directories:
                            if root not in self.unavailable_directories:
                                self.unavailable_directories.append(root)
                                err_msg = f"Root directory '{root}' in library '{library_name}' is unavailable on filesystem."
                                logger.warning(
                                    f"[SCAN_ISSUE] Type=Unavailable Directory | Item={root} (Library: '{library_name}') | Error={err_msg}"
                                )
                                self.problems.append(
                                    {
                                        "type": "Unavailable Directory",
                                        "item": f"{root} (Library: '{library_name}')",
                                        "error": err_msg,
                                    }
                                )
                    library_data_by_name[library_name] = updated_library_data
                    _save_lib_data(updated_library_data)
                else:
                    for root_dir in root_directories:
                        self.detail_progress.emit(
                            "start_root", {"library": library_name, "root": root_dir}
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
                            season_callback=_season_callback,
                            movie_callback=_movie_callback,
                        )
                        if updated_library_data.unavailable_directories:
                            for root in updated_library_data.unavailable_directories:
                                if root not in self.unavailable_directories:
                                    self.unavailable_directories.append(root)
                                    err_msg = f"Root directory '{root}' in library '{library_name}' is unavailable on filesystem."
                                    logger.warning(
                                        f"[SCAN_ISSUE] Type=Unavailable Directory | Item={root} (Library: '{library_name}') | Error={err_msg}"
                                    )
                                    self.problems.append(
                                        {
                                            "type": "Unavailable Directory",
                                            "item": f"{root} (Library: '{library_name}')",
                                            "error": err_msg,
                                        }
                                    )
                        existing_library_data = updated_library_data
                        library_data_by_name[library_name] = updated_library_data
                        _save_lib_data(updated_library_data)
                self.detail_progress.emit("finish_library", {"library": library_name})

            # --- PASS 2: ONLINE METADATA RESOLUTION ---
            logger.info(
                "ScanAllLibrariesWorker starting Pass 2 (Online Metadata Resolution)"
            )
            self.detail_progress.emit("start_metadata_resolution", {})

            completed_count = 0
            for library_name, library_configuration in libraries_dictionary.items():
                logger.info(
                    f"ScanAllLibrariesWorker Pass 2 resolving library: {library_name}"
                )
                root_directories = list(library_configuration.get("paths", []))
                library_type = library_configuration.get("type", "tv")
                show_future = library_configuration.get("show_future_episodes", True)
                existing_library_data = library_data_by_name[library_name]

                self.detail_progress.emit("start_library", {"library": library_name})

                def _make_detail_callback(lib_name: str) -> Any:
                    worker_self = self

                    def _detail_callback(event: str, payload: Dict[str, Any]) -> None:
                        enriched = {"library": lib_name, **payload}
                        worker_self.detail_progress.emit(event, enriched)

                    return _detail_callback

                def _season_callback(
                    series_name: str,
                    series_data: Dict[str, Any],
                    season_name: str,
                    season_data: Dict[str, Any],
                ) -> None:
                    logger.info(
                        f"ScanAllLibrariesWorker writing season '{season_name}' of series '{series_name}' to database..."
                    )
                    try:
                        stats = db.save_season_data(
                            library_name,
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
                            if (
                                season_data.get("_changed", True)
                                and "season_id" in stats
                            ):
                                self.changed_season_ids.add(stats["season_id"])
                    except Exception as e:
                        err_msg = str(e)
                        clean_msg = err_msg.split("\n")[0].strip()
                        if "\n" in err_msg:
                            logger.debug(
                                f"Database write failure detailed error: {err_msg}"
                            )
                        logger.warning(
                            f"[SCAN_ISSUE] Type=Database Write Failure | Item=Season '{season_name}' of series '{series_name}' (Library: '{library_name}') | Error={clean_msg}"
                        )
                        self.problems.append(
                            {
                                "type": "Database Write Failure",
                                "item": f"Season '{season_name}' of series '{series_name}' (Library: '{library_name}')",
                                "error": clean_msg,
                            }
                        )

                def _movie_callback(
                    movie_name: str, movie_data: Dict[str, Any]
                ) -> None:
                    logger.info(
                        f"ScanAllLibrariesWorker writing movie '{movie_name}' to database..."
                    )
                    try:
                        stats = db.save_movie_data(library_name, movie_name, movie_data)
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
                            f"[SCAN_ISSUE] Type=Database Write Failure | Item=Movie '{movie_name}' (Library: '{library_name}') | Error={clean_msg}"
                        )
                        self.problems.append(
                            {
                                "type": "Database Write Failure",
                                "item": f"Movie '{movie_name}' (Library: '{library_name}')",
                                "error": clean_msg,
                            }
                        )

                def _save_lib_data(lib_data: Dict[str, Any]) -> None:
                    try:
                        if library_type == "movie":
                            stats = db.save_movie_library(library_name, lib_data)
                        else:
                            stats = db.save_library(library_name, lib_data)
                        if stats:
                            if "issues" in stats:
                                for issue in stats["issues"]:
                                    self.problems.append(issue)
                            for key in self.stats:
                                if key in stats:
                                    self.stats[key] += stats[key]
                    except Exception as e:
                        err_msg = str(e)
                        clean_msg = err_msg.split("\n")[0].strip()
                        if "\n" in err_msg:
                            logger.debug(
                                f"Database write failure detailed error: {err_msg}"
                            )
                        logger.warning(
                            f"[SCAN_ISSUE] Type=Database Write Failure | Item=Library '{library_name}' | Error={clean_msg}"
                        )
                        self.problems.append(
                            {
                                "type": "Database Write Failure",
                                "item": f"Library '{library_name}'",
                                "error": clean_msg,
                            }
                        )

                if not root_directories:
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
                        season_callback=_season_callback,
                        movie_callback=_movie_callback,
                        metadata_only=True,
                    )
                    if updated_library_data.unavailable_directories:
                        for root in updated_library_data.unavailable_directories:
                            if root not in self.unavailable_directories:
                                self.unavailable_directories.append(root)
                                err_msg = f"Root directory '{root}' in library '{library_name}' is unavailable on filesystem."
                                logger.warning(
                                    f"[SCAN_ISSUE] Type=Unavailable Directory | Item={root} (Library: '{library_name}') | Error={err_msg}"
                                )
                                self.problems.append(
                                    {
                                        "type": "Unavailable Directory",
                                        "item": f"{root} (Library: '{library_name}')",
                                        "error": err_msg,
                                    }
                                )
                    library_data_by_name[library_name] = updated_library_data
                    _save_lib_data(updated_library_data)
                else:
                    for root_dir in root_directories:
                        self.detail_progress.emit(
                            "start_root", {"library": library_name, "root": root_dir}
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
                            season_callback=_season_callback,
                            movie_callback=_movie_callback,
                            metadata_only=True,
                        )
                        if updated_library_data.unavailable_directories:
                            for root in updated_library_data.unavailable_directories:
                                if root not in self.unavailable_directories:
                                    self.unavailable_directories.append(root)
                                    err_msg = f"Root directory '{root}' in library '{library_name}' is unavailable on filesystem."
                                    logger.warning(
                                        f"[SCAN_ISSUE] Type=Unavailable Directory | Item={root} (Library: '{library_name}') | Error={err_msg}"
                                    )
                                    self.problems.append(
                                        {
                                            "type": "Unavailable Directory",
                                            "item": f"{root} (Library: '{library_name}')",
                                            "error": err_msg,
                                        }
                                    )
                        existing_library_data = updated_library_data
                        library_data_by_name[library_name] = updated_library_data
                        _save_lib_data(updated_library_data)
                        self.detail_progress.emit(
                            "finish_root", {"library": library_name, "root": root_dir}
                        )
                completed_count += 1
                self.detail_progress.emit("finish_library", {"library": library_name})
                self.library_progress.emit(library_name, completed_count, total_count)

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

            logger.info("ScanAllLibrariesWorker finished successfully")
            self.finished.emit()
        except Exception as exception_instance:
            logger.exception("ScanAllLibrariesWorker failed")
            self.error.emit(str(exception_instance))
