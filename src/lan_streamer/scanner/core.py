import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

from lan_streamer.db.utils import natural_sort_key
from lan_streamer.scanner.versioning import get_version_score_key, choose_active_version  # noqa: F401
from lan_streamer.scanner.parser import (
    has_video_files,
    _parse_movie_folder,  # noqa: F401
)
from lan_streamer.services.file_discovery import (
    has_season_subdirectories as _has_season_subdirs,
)
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
            if detail_callback:
                detail_callback(
                    "root_total",
                    {"root": m_root, "total": len(items)},
                )
            for series_name, existing_series in items:
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
                cleaned = None
                dummy_path = Path(series_name)

                if library_type == "movie":
                    series_data = scan_movie(
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
                    series_data = scan_series(
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
                    )
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
        series_dirs = sorted(
            [
                directory
                for directory in root_path.iterdir()
                if directory.is_dir()
                and not directory.name.startswith(".")
                and (has_video_files(directory) or _has_season_subdirs(directory))
            ],
            key=lambda directory: directory.stat().st_mtime,
            reverse=True,
        )

        if detail_callback:
            detail_callback(
                "root_total",
                {"root": root_directory, "total": len(series_dirs)},
            )

        for series_directory in series_dirs:
            series_name = series_directory.name
            logger.debug(f"Scanning folder '{series_name}' in root '{root_directory}'")
            if detail_callback:
                detail_callback(
                    "start_folder",
                    {"root": root_directory, "folder": series_name},
                )

            # Check if we have an existing manual match for THIS SPECIFIC folder name
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
            cleaned: Optional[Dict[str, Any]] = None
            if library_type == "movie":
                series_data = scan_movie(
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
                series_data = scan_series(
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
                )
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

                if library_type == "movie":
                    pass  # We just keep existing movie for now, no complex merge
                else:
                    for season_name, season_data in cleaned.get("seasons", {}).items():
                        if season_name in existing.get("seasons", {}):
                            existing_episodes = existing["seasons"][season_name][
                                "episodes"
                            ]
                            _merge_season_episodes(
                                existing_episodes, season_data["episodes"], season_name
                            )
                            existing_episodes.sort(
                                key=lambda x: natural_sort_key(x["name"])
                            )
                        else:
                            existing.setdefault("seasons", {})[season_name] = (
                                season_data
                            )
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
