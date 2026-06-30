import atexit
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from lan_streamer.db.utils import natural_sort_key
from lan_streamer.scanner.parser import has_video_files
from lan_streamer.services.metadata_common import (
    _resolve_existing_jellyfin_id,
    _build_locked_movie_tmdb_stub,
    _build_locked_tv_tmdb_stub,
    _merge_season_episodes,
)
from lan_streamer.services.metadata_updates import clean_series_data
from lan_streamer.scanner.scan_movie import scan_movie
from lan_streamer.scanner.scan_tv import scan_series

logger = logging.getLogger("lan_streamer.scanner")

_global_scan_executor: Optional[ThreadPoolExecutor] = None
_global_scan_executor_lock = threading.Lock()


def get_scan_executor() -> ThreadPoolExecutor:
    """Returns the global, shared ThreadPoolExecutor instance for directory scanning.

    The returned executor is a process-lifetime singleton — it is created on
    first call and automatically shut down (with in-flight futures cancelled)
    when the interpreter exits via the ``atexit`` handler registered below.
    Call :func:`shutdown_scan_executor` explicitly to shut it down earlier,
    e.g. when a scan is cancelled by the user.
    """
    global _global_scan_executor
    if _global_scan_executor is None:
        with _global_scan_executor_lock:
            if _global_scan_executor is None:
                max_workers = min(12, (os.cpu_count() or 4) * 2)
                _global_scan_executor = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix="scan_worker",
                )
    return _global_scan_executor


def shutdown_scan_executor() -> None:
    """Shut down the global scan executor, cancelling any queued futures.

    Safe to call multiple times.  After this call a new executor will be
    created on the next :func:`get_scan_executor` call, so active scans
    should be stopped before invoking this.
    """
    global _global_scan_executor
    with _global_scan_executor_lock:
        executor = _global_scan_executor
        if executor is not None:
            logger.info(
                "Shutting down global scan executor (cancelling queued futures)..."
            )
            executor.shutdown(wait=False, cancel_futures=True)
            _global_scan_executor = None
            logger.info("Global scan executor shut down.")


atexit.register(shutdown_scan_executor)


class LibraryDict(dict[str, Any]):
    """
    Custom dictionary subclass to hold library contents and track
    any root directories that were unavailable during scanning.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.unavailable_directories: List[str] = []


def scan_directories(
    root_directories: List[str],
    library_type: str = "tv",
    existing_library: Dict[str, Any] | None = None,
    jellyfin_data: Dict[str, Any] | None = None,
    callback: Any = None,
    force_refresh: bool = False,
    cleanup: bool = False,
    single_item_refresh: bool = False,
    detail_callback: Any = None,
    root_directory_label: str = "",
    show_future_episodes: bool = True,
    offline: bool = False,
    season_callback: Any = None,
    movie_callback: Any = None,
    metadata_only: bool = False,
    database_queue: Optional[Any] = None,
    disregard_mtimes: bool = False,
    is_interrupted: Optional[Any] = None,
) -> LibraryDict:
    """
    Scans root directories and matches with TMDB to pull metadata.
    Watch history (watched status) is handled separately via Jellyfin sync.
    """
    library = LibraryDict()
    existing_library = existing_library or {}

    if metadata_only:
        items_by_root: Dict[str, List[tuple[str, Any]]] = {}
        if not root_directories:
            items_by_root[root_directory_label or "Library"] = list(
                existing_library.items()
            )
        else:
            resolved_roots = []
            for r in root_directories:
                try:
                    resolved_roots.append(str(Path(r).resolve()))
                except Exception:
                    resolved_roots.append(r)
            for series_name, existing_series in existing_library.items():
                m_root = None
                paths = []
                if library_type == "movie":
                    if existing_series.get("path"):
                        paths.append(existing_series["path"])
                    if existing_series.get("default_path"):
                        paths.append(existing_series["default_path"])
                    for version in existing_series.get("versions", []):
                        if version.get("path"):
                            paths.append(version["path"])
                else:
                    for season in existing_series.get("seasons", {}).values():
                        for episode in season.get("episodes", []):
                            if episode.get("path"):
                                paths.append(episode["path"])
                for p in paths:
                    p_path = Path(p)
                    for root in resolved_roots:
                        root_path = Path(root)
                        try:
                            p_path.resolve().relative_to(root_path)
                            m_root = root
                            break
                        except ValueError:
                            pass
                        except Exception:
                            pass
                    if m_root:
                        break
                if not m_root:
                    for root in resolved_roots:
                        root_path = Path(root)
                        if (root_path / series_name).exists():
                            m_root = root
                            break
                if not m_root:
                    if resolved_roots:
                        m_root = resolved_roots[0]
                    else:
                        m_root = root_directory_label or "Library"
                if m_root not in items_by_root:
                    items_by_root[m_root] = []
                items_by_root[m_root].append((series_name, existing_series))

        for m_root, items in items_by_root.items():
            if is_interrupted and is_interrupted():
                logger.info("scan_directories: interruption detected in metadata path.")
                break
            if detail_callback:
                detail_callback(
                    "root_total",
                    {"root": m_root, "total": len(items)},
                )

            scan_results = []
            executor = get_scan_executor()
            future_to_item = {}
            for series_name, existing_series in items:
                if is_interrupted and is_interrupted():
                    logger.info(
                        "scan_directories: interruption detected, skipping further items."
                    )
                    break
                if detail_callback:
                    detail_callback(
                        "start_folder",
                        {"root": m_root, "folder": series_name},
                    )

                tmdb_series = None
                is_locked = False
                existing_jellyfin_id = None
                has_meta = False

                existing_jellyfin_id = _resolve_existing_jellyfin_id(
                    existing_series, library_type
                )
                if library_type == "movie":
                    is_locked = bool(existing_series.get("locked_metadata", False))
                    has_meta = bool(existing_series.get("tmdb_identifier"))
                    if is_locked:
                        tmdb_series = _build_locked_movie_tmdb_stub(
                            existing_series, series_name
                        )
                else:
                    is_locked = bool(
                        existing_series.get("metadata", {}).get(
                            "locked_metadata", False
                        )
                    )
                    has_meta = bool(
                        existing_series.get("metadata", {}).get("tmdb_identifier")
                    )
                    if is_locked:
                        tmdb_series = _build_locked_tv_tmdb_stub(existing_series)

                series_force_refresh = (
                    (force_refresh or single_item_refresh or not has_meta)
                    if not is_locked
                    else False
                )
                dummy_path = Path(series_name)

                if library_type == "movie":
                    future = executor.submit(
                        scan_movie,
                        dummy_path,
                        tmdb_movie=tmdb_series,
                        jellyfin_data=jellyfin_data,
                        manual_jellyfin_id=existing_jellyfin_id,
                        existing_movie_data=existing_series,
                        force_refresh=series_force_refresh,
                        cleanup=cleanup,
                        single_item_refresh=single_item_refresh,
                        detail_callback=detail_callback,
                        offline=offline,
                        metadata_only=True,
                    )
                else:
                    future = executor.submit(
                        scan_series,
                        dummy_path,
                        tmdb_series=tmdb_series,
                        jellyfin_data=jellyfin_data,
                        manual_jellyfin_id=existing_jellyfin_id,
                        existing_series_data=existing_series,
                        force_refresh=series_force_refresh,
                        cleanup=cleanup,
                        single_item_refresh=single_item_refresh,
                        detail_callback=detail_callback,
                        show_future_episodes=show_future_episodes,
                        offline=offline,
                        season_callback=season_callback,
                        metadata_only=True,
                        database_queue=database_queue,
                    )
                future_to_item[future] = (series_name, is_locked)

            for future in as_completed(future_to_item):
                if is_interrupted and is_interrupted():
                    logger.info(
                        "scan_directories: interruption detected. Cancelling remaining metadata tasks."
                    )
                    for f in future_to_item:
                        f.cancel()
                    break
                series_name, is_locked = future_to_item[future]
                try:
                    series_data = future.result()
                    scan_results.append((series_name, is_locked, series_data))
                except Exception:
                    logger.exception(
                        f"Error during parallel metadata scan of '{series_name}'"
                    )
                    if detail_callback:
                        detail_callback(
                            "finish_folder",
                            {
                                "root": m_root,
                                "folder": series_name,
                                "skipped": True,
                            },
                        )

            for series_name, is_locked, series_data in scan_results:
                cleaned = None
                if library_type == "movie":
                    if not series_data:
                        if detail_callback:
                            detail_callback(
                                "finish_folder",
                                {
                                    "root": m_root,
                                    "folder": series_name,
                                    "skipped": True,
                                },
                            )
                        continue
                    cleaned = series_data
                    if movie_callback and cleaned:
                        movie_callback(series_name, cleaned)
                else:
                    if not series_data:
                        if detail_callback:
                            detail_callback(
                                "finish_folder",
                                {
                                    "root": m_root,
                                    "folder": series_name,
                                    "skipped": True,
                                },
                            )
                        continue
                    if is_locked:
                        series_data["metadata"]["locked_metadata"] = True

                    cleaned = clean_series_data(series_data)
                    if not cleaned:
                        if detail_callback:
                            detail_callback(
                                "finish_folder",
                                {
                                    "root": m_root,
                                    "folder": series_name,
                                    "skipped": True,
                                },
                            )
                        continue

                library[series_name] = cleaned

                if detail_callback:
                    detail_callback(
                        "finish_folder",
                        {
                            "root": m_root,
                            "folder": series_name,
                            "skipped": False,
                        },
                    )

                if callback:
                    callback(library)

        return library

    logger.info(f"Starting directory scan. Root directories: {root_directories}")

    for root_directory in root_directories:
        if is_interrupted and is_interrupted():
            logger.info(
                "scan_directories: interruption detected. Stopping directory scan."
            )
            break
        logger.info(f"Scanning root directory: {root_directory}")
        root_path = Path(root_directory)
        if not root_path.exists() or not root_path.is_dir():
            logger.warning(f"Root directory '{root_directory}' is unavailable")
            library.unavailable_directories.append(root_directory)
            if detail_callback:
                detail_callback("unavailable_root", {"root": root_directory})
            continue

        # Sort series directories by mtime (newest first).
        # Include a directory if it contains video files OR season-style subdirs,
        # so series with only TMDB placeholder episodes are still indexed.
        from lan_streamer.services.file_discovery import (
            has_season_subdirectories as _has_season_subdirs,
        )

        with os.scandir(root_path) as scan_entries:
            scanned_directories = [
                (entry.name, entry)
                for entry in scan_entries
                if entry.is_dir() and not entry.name.startswith(".")
            ]
        series_dirs = sorted(
            [
                Path(root_path / name)
                for name, entry in scanned_directories
                if has_video_files(Path(root_path / name))
                or _has_season_subdirs(Path(root_path / name))
            ],
            key=lambda directory: directory.stat().st_mtime,
            reverse=True,
        )

        if detail_callback:
            detail_callback(
                "root_total",
                {"root": root_directory, "total": len(series_dirs)},
            )

        scan_results = []
        executor = get_scan_executor()
        future_to_series_directory = {}
        for series_directory in series_dirs:
            if is_interrupted and is_interrupted():
                logger.info(
                    "scan_directories: interruption detected, skipping further series directories."
                )
                break
            series_name = series_directory.name
            logger.debug(f"Scanning folder '{series_name}' in root '{root_directory}'")
            if detail_callback:
                detail_callback(
                    "start_folder",
                    {"root": root_directory, "folder": series_name},
                )

            # Check if we have an existing manual match for THIS SPECIFIC folder name
            if disregard_mtimes:
                existing_series = existing_library.get(series_name)
                # When disregard_mtimes is True, skip the series-level mtime
                # early-exit block below by clearing has_meta temporarily.
                # We still need existing_series for data, so set it first.
                has_meta = False  # force full re-scan
            else:
                existing_series = existing_library.get(series_name)
            tmdb_series = None
            is_locked = False
            existing_jellyfin_id = None
            has_meta = False

            if existing_series:
                existing_jellyfin_id = _resolve_existing_jellyfin_id(
                    existing_series, library_type
                )
                if library_type == "movie":
                    is_locked = bool(existing_series.get("locked_metadata", False))
                    has_meta = bool(existing_series.get("tmdb_identifier"))
                    if is_locked:
                        logger.info(
                            f"Using locked TMDB metadata for movie '{series_name}' "
                            f"(ID: {existing_series['tmdb_identifier']})"
                        )
                        tmdb_series = _build_locked_movie_tmdb_stub(
                            existing_series, series_name
                        )
                else:
                    is_locked = bool(
                        existing_series.get("metadata", {}).get(
                            "locked_metadata", False
                        )
                    )
                    has_meta = bool(
                        existing_series.get("metadata", {}).get("tmdb_identifier")
                    )
                    if is_locked:
                        logger.info(
                            f"Using locked TMDB metadata for '{series_name}' "
                            f"(ID: {existing_series['metadata']['tmdb_identifier']})"
                        )
                        tmdb_series = _build_locked_tv_tmdb_stub(existing_series)

            series_force_refresh = (
                (force_refresh or single_item_refresh or not has_meta)
                if not is_locked
                else False
            )

            # --- Series-level mtime early-exit (TV only) ---
            # If the series directory mtime matches what we recorded after the last
            # successful scan, *and* we have valid existing data with metadata, *and*
            # no forced refresh is requested, we can skip the entire scan_series /
            # scan_directories call and reuse the existing data.  This avoids all
            # season subdirectory I/O on a network share when nothing has changed.
            #
            # The `offline` flag is NOT a guard here: mtime equality is a filesystem
            # fact that holds regardless of whether we are in the offline discovery
            # pass or the online metadata pass.  The previous `not offline` guard
            # caused this optimisation to be dead code for Pass 1 (the only path
            # that reaches this code block in the standard ScanWorker flow).
            if (
                library_type != "movie"
                and not series_force_refresh
                and existing_series
                and has_meta
            ):
                series_directory_path = str(series_directory.absolute())
                try:
                    current_series_mtime = series_directory.stat().st_mtime
                except OSError:
                    current_series_mtime = None

                if current_series_mtime is not None and current_series_mtime > 0:
                    from lan_streamer import db as _db  # Deferred: circular import

                    cached_series_mtime = _db.get_directory_mtime(series_directory_path)
                    if (
                        cached_series_mtime is not None
                        and current_series_mtime == cached_series_mtime
                    ):
                        logger.info(
                            f"Series '{series_name}' directory mtime unchanged "
                            f"(mtime={current_series_mtime}); skipping full scan."
                        )
                        scan_results.append((series_name, is_locked, existing_series))
                        if detail_callback:
                            detail_callback(
                                "finish_folder",
                                {
                                    "root": root_directory,
                                    "folder": series_name,
                                    "skipped": True,
                                },
                            )
                        continue
            # --- End series-level mtime early-exit ---

            if library_type == "movie":
                future = executor.submit(
                    scan_movie,
                    series_directory,
                    tmdb_movie=tmdb_series,
                    jellyfin_data=jellyfin_data,
                    manual_jellyfin_id=existing_jellyfin_id,
                    existing_movie_data=existing_series,
                    force_refresh=series_force_refresh,
                    cleanup=cleanup,
                    single_item_refresh=single_item_refresh,
                    detail_callback=detail_callback,
                    offline=offline,
                )
            else:
                future = executor.submit(
                    scan_series,
                    series_directory,
                    tmdb_series=tmdb_series,
                    jellyfin_data=jellyfin_data,
                    manual_jellyfin_id=existing_jellyfin_id,
                    existing_series_data=existing_series,
                    force_refresh=series_force_refresh,
                    cleanup=cleanup,
                    single_item_refresh=single_item_refresh,
                    detail_callback=detail_callback,
                    show_future_episodes=show_future_episodes,
                    offline=offline,
                    season_callback=season_callback,
                    database_queue=database_queue,
                )
            future_to_series_directory[future] = (series_name, is_locked)

        for future in as_completed(future_to_series_directory):
            if is_interrupted and is_interrupted():
                logger.info(
                    "scan_directories: interruption detected. Cancelling remaining directory scan tasks."
                )
                for f in future_to_series_directory:
                    f.cancel()
                break
            series_name, is_locked = future_to_series_directory[future]
            try:
                series_data = future.result()
                scan_results.append((series_name, is_locked, series_data))
            except Exception:
                logger.exception(
                    f"Error during parallel directory scan of '{series_name}'"
                )
                if detail_callback:
                    detail_callback(
                        "finish_folder",
                        {
                            "root": root_directory,
                            "folder": series_name,
                            "skipped": True,
                        },
                    )

        for series_name, is_locked, series_data in scan_results:
            cleaned: Optional[Dict[str, Any]] = None
            if library_type == "movie":
                if not series_data:
                    if detail_callback:
                        detail_callback(
                            "finish_folder",
                            {
                                "root": root_directory,
                                "folder": series_name,
                                "skipped": True,
                            },
                        )
                    continue
                cleaned = series_data
                if movie_callback and cleaned:
                    movie_callback(series_name, cleaned)
            else:
                if not series_data:
                    if detail_callback:
                        detail_callback(
                            "finish_folder",
                            {
                                "root": root_directory,
                                "folder": series_name,
                                "skipped": True,
                            },
                        )
                    continue
                if is_locked:
                    series_data["metadata"]["locked_metadata"] = True

                cleaned = clean_series_data(series_data)
                if not cleaned:
                    if detail_callback:
                        detail_callback(
                            "finish_folder",
                            {
                                "root": root_directory,
                                "folder": series_name,
                                "skipped": True,
                            },
                        )
                    continue

            # Identify if this series matches something already in our library
            match_key = None
            if series_name in library:
                match_key = series_name

            if match_key:
                # Merge into existing entry
                existing = library[match_key]
                logger.info(
                    f"Merging '{series_name}' into existing entry '{match_key}'"
                )

                for season_name, season_data in cleaned.get("seasons", {}).items():
                    if season_name in existing.get("seasons", {}):
                        existing_episodes = existing["seasons"][season_name]["episodes"]
                        _merge_season_episodes(
                            existing_episodes, season_data["episodes"], season_name
                        )
                        existing_episodes.sort(
                            key=lambda x: natural_sort_key(x["name"])
                        )
                    else:
                        existing.setdefault("seasons", {})[season_name] = season_data
            else:
                library[series_name] = cleaned

            if detail_callback:
                detail_callback(
                    "finish_folder",
                    {"root": root_directory, "folder": series_name, "skipped": False},
                )

            if callback:
                callback(library)

    if not cleanup and existing_library:
        for old_series_name, old_series_data in existing_library.items():
            if old_series_name not in library:
                logger.info(
                    f"Preserving missing folder '{old_series_name}' (non-destructive)"
                )
                library[old_series_name] = old_series_data

    return library
