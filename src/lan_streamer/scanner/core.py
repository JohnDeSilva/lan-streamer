"""
Core scanner — dispatches to pass-specific implementations.

The 3-pass architecture:

- **Pass 1** (``pass1_file_discovery``): Walk filesystem, find video files,
  create stub episode/movie records. No TMDB calls, no ffprobe.
- **Pass 2** (``pass2_metadata``): Resolve TMDB metadata for series, seasons,
  episodes, and movies. No filesystem walking.
- **Pass 3** (``pass3_technical``): Batch ffprobe scan to fill in technical
  metadata and cleanup missing files.
"""

import atexit
import concurrent.futures
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lan_streamer.scanner.parser import has_video_files

logger = logging.getLogger("lan_streamer.scanner")

_global_scan_executor: Optional[ThreadPoolExecutor] = None
_global_scan_executor_lock = threading.Lock()


def get_scan_executor() -> ThreadPoolExecutor:
    """Return the global shared ThreadPoolExecutor instance."""
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
    """Shut down the global scan executor, cancelling queued futures."""
    global _global_scan_executor
    with _global_scan_executor_lock:
        executor = _global_scan_executor
        if executor is not None:
            logger.info("Shutting down global scan executor...")
            executor.shutdown(wait=False, cancel_futures=True)
            _global_scan_executor = None
            logger.info("Global scan executor shut down.")


atexit.register(shutdown_scan_executor)


class LibraryDict(dict[str, Any]):
    """Custom dict subclass that tracks unavailable root directories."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.unavailable_directories: List[str] = []

    def __repr__(self) -> str:
        return f"LibraryDict({len(self)} items, unavailable={self.unavailable_directories})"


def scan_directories(
    root_directories: List[str],
    library_type: str = "tv",
    existing_library: Optional[Dict[str, Any]] = None,
    jellyfin_data: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
    single_item_refresh: bool = False,
    detail_callback: Optional[Callable] = None,
    show_future_episodes: bool = True,
    season_callback: Optional[Callable] = None,
    movie_callback: Optional[Callable] = None,
    is_interrupted: Optional[Callable] = None,
    tmdb_prefetch_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None,
    pass_number: int = 0,
) -> LibraryDict:
    """Dispatch to the appropriate pass implementation.

    Args:
        root_directories: Filesystem roots to scan.
        library_type: ``"tv"`` (default) or ``"movie"``.
        existing_library: Previously-persisted library data (from DB).
        jellyfin_data: Jellyfin correlation data (Pass 2 only).
        force_refresh: Re-scan even when mtimes match.
        single_item_refresh: Force-refresh metadata for a single item.
        detail_callback: Progress callback ``(event, payload)``.
        show_future_episodes: Include future-dated TMDB placeholders.
        season_callback: Called for each season scanned (Pass 1/2).
        movie_callback: Called for each movie scanned (Pass 1/2).
        is_interrupted: Callable returning True if scan should abort.
        tmdb_prefetch_executor: Shared executor for TMDB pre-fetch (Pass 2).
        pass_number: Which pass to execute (0 = all, 1 = discovery, 2 = metadata, 3 = technical).

    Returns:
        A :class:`LibraryDict` with discovered / resolved series/movie data.
    """
    existing_library = existing_library or {}

    if pass_number == 0:
        lib = _scan_pass1(
            root_directories=root_directories,
            library_type=library_type,
            existing_library=existing_library,
            force_refresh=force_refresh,
            detail_callback=detail_callback,
            season_callback=season_callback,
            movie_callback=movie_callback,
            is_interrupted=is_interrupted,
        )
        unavailable = list(lib.unavailable_directories)
        lib = _scan_pass2(
            root_directories=root_directories,
            library_type=library_type,
            existing_library=lib,
            jellyfin_data=jellyfin_data,
            force_refresh=force_refresh,
            single_item_refresh=single_item_refresh,
            detail_callback=detail_callback,
            show_future_episodes=show_future_episodes,
            season_callback=season_callback,
            movie_callback=movie_callback,
            is_interrupted=is_interrupted,
            tmdb_prefetch_executor=tmdb_prefetch_executor,
        )
        result = _scan_pass3(
            root_directories=root_directories,
            library_type=library_type,
            existing_library=lib,
            force_refresh=force_refresh,
            is_interrupted=is_interrupted,
        )
        result.unavailable_directories = unavailable
        return result
    elif pass_number == 1:
        return _scan_pass1(
            root_directories=root_directories,
            library_type=library_type,
            existing_library=existing_library,
            force_refresh=force_refresh,
            detail_callback=detail_callback,
            season_callback=season_callback,
            movie_callback=movie_callback,
            is_interrupted=is_interrupted,
        )
    elif pass_number == 2:
        return _scan_pass2(
            root_directories=root_directories,
            library_type=library_type,
            existing_library=existing_library,
            jellyfin_data=jellyfin_data,
            force_refresh=force_refresh,
            single_item_refresh=single_item_refresh,
            detail_callback=detail_callback,
            show_future_episodes=show_future_episodes,
            season_callback=season_callback,
            movie_callback=movie_callback,
            is_interrupted=is_interrupted,
            tmdb_prefetch_executor=tmdb_prefetch_executor,
        )
    elif pass_number == 3:
        return _scan_pass3(
            root_directories=root_directories,
            library_type=library_type,
            existing_library=existing_library,
            force_refresh=force_refresh,
            is_interrupted=is_interrupted,
        )
    else:
        raise ValueError(
            f"Invalid pass_number: {pass_number!r} (expected 0, 1, 2, or 3)"
        )


# =============================================================================
#  Pass 1 — File discovery
# =============================================================================


def _scan_pass1(
    root_directories: List[str],
    library_type: str,
    existing_library: Dict[str, Any],
    force_refresh: bool,
    detail_callback: Optional[Callable],
    season_callback: Optional[Callable],
    movie_callback: Optional[Callable],
    is_interrupted: Optional[Callable],
) -> LibraryDict:
    """Walk filesystem, discover files, create stub records.

    Each series/movie directory is scanned in parallel via the global executor.
    """
    from lan_streamer.scanner.pass1_file_discovery import (
        scan_movie_pass1,
        scan_series_pass1,
    )

    library = LibraryDict()

    # For TV libraries, also check directories that have season subdirectories.
    from lan_streamer.services.file_discovery import (
        has_season_subdirectories as _has_season_subdirs,
    )

    for root_directory in root_directories:
        if is_interrupted and is_interrupted():
            logger.info("Pass 1: interruption detected, stopping.")
            break

        root_path = Path(root_directory)
        if not root_path.exists() or not root_path.is_dir():
            logger.warning("Root directory '%s' is unavailable.", root_directory)
            library.unavailable_directories.append(root_directory)
            if detail_callback:
                detail_callback("unavailable_root", {"root": root_directory})
            continue

        # Sort series directories by mtime (newest first).
        series_dirs = sorted(
            [
                Path(root_path / entry.name)
                for entry in os.scandir(root_path)
                if entry.is_dir()
                and not entry.name.startswith(".")
                and (
                    has_video_files(Path(root_path / entry.name))
                    or _has_season_subdirs(Path(root_path / entry.name))
                )
            ],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )

        if detail_callback:
            detail_callback(
                "root_total", {"root": root_directory, "total": len(series_dirs)}
            )

        # Parallel scan via executor.
        executor = get_scan_executor()
        futures = {}
        for series_dir in series_dirs:
            if is_interrupted and is_interrupted():
                break
            series_name = series_dir.name
            if detail_callback:
                detail_callback(
                    "start_folder", {"root": root_directory, "folder": series_name}
                )

            existing = existing_library.get(series_name)
            if library_type == "movie":
                future = executor.submit(
                    scan_movie_pass1,
                    series_dir,
                    existing_movie_data=existing,
                    force_refresh=force_refresh,
                    detail_callback=detail_callback,
                )
            else:
                future = executor.submit(
                    scan_series_pass1,
                    series_dir,
                    existing_series_data=existing,
                    force_refresh=force_refresh,
                    detail_callback=detail_callback,
                )
            futures[future] = (series_name, series_dir)

        for future in concurrent.futures.as_completed(futures):
            if is_interrupted and is_interrupted():
                for f in futures:
                    f.cancel()
                break
            series_name, series_dir = futures[future]
            try:
                series_data = future.result()
            except Exception:
                logger.exception("Pass 1: error scanning '%s'", series_name)
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

            if series_data is None:
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

            # Merge with existing entry when a series spans multiple root directories
            if series_name in library:
                series_data = _merge_series_data(library[series_name], series_data)
            library[series_name] = series_data

            if library_type == "movie":
                if movie_callback and series_data:
                    movie_callback(series_name, series_data)
            else:
                if season_callback and series_data:
                    for season_name, season_data in series_data.get(
                        "seasons", {}
                    ).items():
                        season_callback(
                            series_name, series_data, season_name, season_data
                        )

            if detail_callback:
                detail_callback(
                    "finish_folder",
                    {"root": root_directory, "folder": series_name, "skipped": False},
                )

    # Merge seasons from existing_library for series found on disk
    # (e.g., when a series spans root directories not all scanned in this pass).
    if existing_library:
        for series_name in list(library.keys()):
            existing_data = existing_library.get(series_name)
            if existing_data and existing_data.get("seasons"):
                library[series_name] = _merge_series_data(
                    existing_data, library[series_name]
                )

    # Non-destructive: preserve entries not found on disk.
    if existing_library:
        for old_name, old_data in existing_library.items():
            if old_name not in library:
                library[old_name] = old_data

    return library


# =============================================================================
#  Pass 2 — Metadata resolution
# =============================================================================


def _scan_pass2(
    root_directories: List[str],
    library_type: str,
    existing_library: Dict[str, Any],
    jellyfin_data: Optional[Dict[str, Any]],
    force_refresh: bool,
    single_item_refresh: bool,
    detail_callback: Optional[Callable],
    show_future_episodes: bool,
    season_callback: Optional[Callable],
    movie_callback: Optional[Callable],
    is_interrupted: Optional[Callable],
    tmdb_prefetch_executor: Optional[concurrent.futures.ThreadPoolExecutor],
) -> LibraryDict:
    """Resolve TMDB metadata for all items in *existing_library*.

    No filesystem walking — operates entirely on previously-discovered data.
    """
    from lan_streamer.scanner.pass2_metadata import scan_movie_pass2, scan_series_pass2

    library = LibraryDict()

    # Group items by root directory for progress reporting.
    items_by_root: Dict[str, List[tuple[str, Any]]] = {}
    resolved_roots = (
        [str(Path(r).resolve()) for r in root_directories] if root_directories else [""]
    )

    for series_name, existing_series in existing_library.items():
        m_root = _resolve_item_root(
            series_name, existing_series, library_type, resolved_roots
        )
        items_by_root.setdefault(m_root, []).append((series_name, existing_series))

    for m_root, items in items_by_root.items():
        if is_interrupted and is_interrupted():
            break
        if detail_callback:
            detail_callback("root_total", {"root": m_root, "total": len(items)})

        executor = get_scan_executor()
        futures = {}
        for series_name, existing in items:
            if is_interrupted and is_interrupted():
                break
            if detail_callback:
                detail_callback("start_folder", {"root": m_root, "folder": series_name})

            series_dir = Path(series_name)  # dummy path; not used for fs walking
            if library_type == "movie":
                future = executor.submit(
                    scan_movie_pass2,
                    series_dir,
                    existing_movie_data=existing,
                    jellyfin_data=jellyfin_data,
                    force_refresh=force_refresh,
                    single_item_refresh=single_item_refresh,
                    detail_callback=detail_callback,
                )
            else:
                # Find the actual series directory.
                actual_dir = _find_series_dir(series_name, root_directories)
                if actual_dir is None:
                    logger.warning(
                        "Pass 2: could not find directory for series '%s'", series_name
                    )
                    if detail_callback:
                        detail_callback(
                            "finish_folder",
                            {"root": m_root, "folder": series_name, "skipped": True},
                        )
                    continue
                future = executor.submit(
                    scan_series_pass2,
                    actual_dir,
                    existing_series_data=existing,
                    tmdb_series=None,
                    jellyfin_data=jellyfin_data,
                    force_refresh=force_refresh,
                    single_item_refresh=single_item_refresh,
                    show_future_episodes=show_future_episodes,
                    detail_callback=detail_callback,
                    season_callback=season_callback,
                    tmdb_prefetch_executor=tmdb_prefetch_executor,
                )
            futures[future] = (series_name, m_root)

        for future in concurrent.futures.as_completed(futures):
            if is_interrupted and is_interrupted():
                for f in futures:
                    f.cancel()
                break
            series_name, m_root = futures[future]
            try:
                result = future.result()
            except Exception:
                logger.exception(
                    "Pass 2: error resolving metadata for '%s'", series_name
                )
                if detail_callback:
                    detail_callback(
                        "finish_folder",
                        {"root": m_root, "folder": series_name, "skipped": True},
                    )
                continue

            if result is not None:
                library[series_name] = result
                if library_type == "movie":
                    if movie_callback:
                        movie_callback(series_name, result)
            if detail_callback:
                detail_callback(
                    "finish_folder",
                    {"root": m_root, "folder": series_name, "skipped": False},
                )

    # Preserve items that didn't get metadata resolved.
    for old_name, old_data in existing_library.items():
        if old_name not in library:
            library[old_name] = old_data

    return library


# =============================================================================
#  Pass 3 — Technical metadata + cleanup
# =============================================================================


def _scan_pass3(
    root_directories: List[str],
    library_type: str,
    existing_library: Dict[str, Any],
    force_refresh: bool,
    is_interrupted: Optional[Callable],
) -> LibraryDict:
    """Batch ffprobe scan and cleanup for all items in *existing_library*."""
    from lan_streamer.scanner.pass3_technical import scan_movie_pass3, scan_series_pass3

    library = LibraryDict()

    resolved_roots = (
        [str(Path(r).resolve()) for r in root_directories] if root_directories else [""]
    )
    items_by_root: Dict[str, List[tuple[str, Any]]] = {}
    for series_name, existing_series in existing_library.items():
        m_root = _resolve_item_root(
            series_name, existing_series, library_type, resolved_roots
        )
        items_by_root.setdefault(m_root, []).append((series_name, existing_series))

    for _m_root, items in items_by_root.items():
        if is_interrupted and is_interrupted():
            break
        for series_name, existing in items:
            if is_interrupted and is_interrupted():
                break
            if library_type == "movie":
                result = scan_movie_pass3(
                    Path(series_name),
                    existing,
                    force_refresh=force_refresh,
                )
            else:
                actual_dir = _find_series_dir(series_name, root_directories) or Path(
                    series_name
                )
                result = scan_series_pass3(
                    actual_dir,
                    existing,
                    force_refresh=force_refresh,
                )
            if result is not None:
                library[series_name] = result

    for old_name, old_data in existing_library.items():
        if old_name not in library:
            library[old_name] = old_data

    return library


# =============================================================================
#  Helpers
# =============================================================================


def _resolve_item_root(
    series_name: str,
    series_data: Dict[str, Any],
    library_type: str,
    resolved_roots: List[str],
) -> str:
    """Determine which root directory an item belongs to."""
    for root in resolved_roots:
        root_path = Path(root)
        paths: List[str] = []
        if library_type == "movie":
            if series_data.get("path"):
                paths.append(series_data["path"])
            if series_data.get("default_path"):
                paths.append(series_data["default_path"])
            for version in series_data.get("versions", []):
                if version.get("path"):
                    paths.append(version["path"])
        else:
            for season in series_data.get("seasons", {}).values():
                for episode in season.get("episodes", []):
                    if episode.get("path"):
                        paths.append(episode["path"])

        for p in paths:
            try:
                Path(p).resolve().relative_to(root_path)
                return root
            except ValueError:
                continue
            except Exception:
                continue
        if (root_path / series_name).exists():
            return root
    return resolved_roots[0] if resolved_roots else ""


def _find_series_dir(series_name: str, root_directories: List[str]) -> Optional[Path]:
    """Find the actual filesystem directory for a series."""
    for root in root_directories:
        candidate = Path(root) / series_name
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _merge_series_data(
    existing: Dict[str, Any], incoming: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge two series data dicts, combining seasons from both.

    The *incoming* (freshly scanned) data takes precedence for metadata
    fields; seasons from both dicts are combined (incoming overwrites
    existing for same-named seasons). Additional keys from *existing*
    (e.g. ``metrics``, ``watched``) are preserved.
    """
    merged = {**existing, **incoming}
    existing_seasons = existing.get("seasons", {})
    incoming_seasons = incoming.get("seasons", {})
    merged["seasons"] = {**existing_seasons, **incoming_seasons}
    return merged
