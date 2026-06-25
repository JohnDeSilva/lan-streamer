import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from lan_streamer.scanner import has_video_files

logger = logging.getLogger("lan_streamer.backend")


def create_empty_stats() -> Dict[str, int]:
    """Return a fresh zeroed stats dictionary with all 20 keys."""
    return {
        "series_scanned": 0,
        "series_added": 0,
        "series_updated": 0,
        "series_removed": 0,
        "series_skipped": 0,
        "seasons_scanned": 0,
        "seasons_added": 0,
        "seasons_updated": 0,
        "seasons_removed": 0,
        "seasons_skipped": 0,
        "episodes_scanned": 0,
        "episodes_added": 0,
        "episodes_updated": 0,
        "episodes_removed": 0,
        "episodes_skipped": 0,
        "movies_scanned": 0,
        "movies_added": 0,
        "movies_updated": 0,
        "movies_removed": 0,
        "movies_skipped": 0,
    }


def merge_stats_dicts(target: Dict[str, int], source: Dict[str, int]) -> None:
    """Merge all values from *source* into *target* in-place."""
    for key, value in source.items():
        if key in target:
            target[key] += value


def merge_stats_dicts_for_report(
    stats_a: Dict[str, int], stats_b: Dict[str, int]
) -> Dict[str, int]:
    """Merge two stats dicts, returning a new dict with summed values.

    Unlike :func:`merge_stats_dicts`, this includes keys from both inputs
    (handles the case where keys like ``_skipped`` only appear in one dict).
    """
    merged = dict(stats_a)
    for key, value in stats_b.items():
        merged[key] = merged.get(key, 0) + value
    return merged


def log_stats_breakdown(
    label: str,
    stats_dict: Dict[str, int],
    log_target: logging.Logger = logger,
) -> None:
    """Log a single stats breakdown section.

    Args:
        label: Section heading for the log output.
        stats_dict: Statistics dictionary to log.
        log_target: Logger to write to (defaults to module logger).
    """
    log_target.info(f"[SCAN_REPORT] {label}")
    log_target.info(
        f"[SCAN_REPORT]   Series: Scanned={stats_dict.get('series_scanned', 0)} | "
        f"Added={stats_dict.get('series_added', 0)} | "
        f"Updated={stats_dict.get('series_updated', 0)} | "
        f"Removed={stats_dict.get('series_removed', 0)} | "
        f"Skipped={stats_dict.get('series_skipped', 0)}"
    )
    log_target.info(
        f"[SCAN_REPORT]   Seasons: Scanned={stats_dict.get('seasons_scanned', 0)} | "
        f"Added={stats_dict.get('seasons_added', 0)} | "
        f"Updated={stats_dict.get('seasons_updated', 0)} | "
        f"Removed={stats_dict.get('seasons_removed', 0)} | "
        f"Skipped={stats_dict.get('seasons_skipped', 0)}"
    )
    log_target.info(
        f"[SCAN_REPORT]   Episodes: Scanned={stats_dict.get('episodes_scanned', 0)} | "
        f"Added={stats_dict.get('episodes_added', 0)} | "
        f"Updated={stats_dict.get('episodes_updated', 0)} | "
        f"Removed={stats_dict.get('episodes_removed', 0)} | "
        f"Skipped={stats_dict.get('episodes_skipped', 0)}"
    )
    log_target.info(
        f"[SCAN_REPORT]   Movies: Scanned={stats_dict.get('movies_scanned', 0)} | "
        f"Added={stats_dict.get('movies_added', 0)} | "
        f"Updated={stats_dict.get('movies_updated', 0)} | "
        f"Removed={stats_dict.get('movies_removed', 0)} | "
        f"Skipped={stats_dict.get('movies_skipped', 0)}"
    )


def log_issues_report(
    problems: List[Dict[str, Any]],
    log_target: logging.Logger = logger,
) -> None:
    """Log grouped issues from the scan run.

    Args:
        problems: List of problem dicts with keys ``type``, ``error``, ``item``.
        log_target: Logger to write to (defaults to module logger).
    """
    if not problems:
        return

    grouped: Dict[str, Dict[str, List[str]]] = {}
    for prob in problems:
        problem_type = prob["type"]
        problem_error = prob["error"]
        problem_item = prob["item"]
        if problem_type not in grouped:
            grouped[problem_type] = {}
        if problem_error not in grouped[problem_type]:
            grouped[problem_type][problem_error] = []
        grouped[problem_type][problem_error].append(problem_item)

    log_target.info("[SCAN_REPORT] ===================================================")
    log_target.info("[SCAN_REPORT]               SCAN RUN ISSUES REPORT")
    log_target.info("[SCAN_REPORT] ===================================================")
    for problem_type, errors in grouped.items():
        log_target.info(f"[SCAN_REPORT] Type: {problem_type}")
        for problem_error, items in errors.items():
            log_target.info(f"[SCAN_REPORT]   Error: {problem_error}")
            for item in items:
                log_target.info(f"[SCAN_REPORT]     - {item}")
        log_target.info(
            "[SCAN_REPORT] ---------------------------------------------------"
        )
    log_target.info("[SCAN_REPORT] ===================================================")


def log_db_write_error(
    problems_list: List[Dict[str, Any]],
    item_description: str,
    error: Exception,
    log_target: logging.Logger = logger,
) -> None:
    """Log and record a database write failure.

    Args:
        problems_list: List to append the problem dict to.
        item_description: Human-readable item identifier for the log.
        error: The exception that was raised.
        log_target: Logger to write to (defaults to module logger).
    """
    error_message: str = str(error)
    clean_message: str = error_message.split("\n")[0].strip()
    if "\n" in error_message:
        log_target.debug(f"Database write failure detailed error: {error_message}")
    log_target.warning(
        "[SCAN_ISSUE] Type=Database Write Failure | "
        f"Item={item_description} | "
        f"Error={clean_message}"
    )
    problems_list.append(
        {
            "type": "Database Write Failure",
            "item": item_description,
            "error": clean_message,
        }
    )


def discover_single_library_tree_impl(
    root_directories: List[str],
    library_type: str,
    existing_library: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[str]]:
    """
    Pre-walks all library directories to count total folders and files
    for a single library so the UI can initialize the segmented progress bar
    before scanning begins. Returns a structure mapping root_dir -> list of folder names.

    If ``existing_library`` is provided, the folder structure is extracted from it
    to avoid redundant filesystem I/O (especially important for network shares).
    """
    roots: Dict[str, List[str]] = {}

    if existing_library:
        # Build roots from existing library data — no filesystem I/O needed.
        for root_dir in root_directories:
            folders = [
                series_name
                for series_name, series_data in existing_library.items()
                if _series_belongs_to_root(series_data, root_dir, library_type)
            ]
            roots[root_dir] = sorted(folders)
        return roots

    # Fallback: no existing data (first scan) — walk the filesystem.
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


def _series_belongs_to_root(
    series_data: Dict[str, Any], root_dir: str, library_type: str
) -> bool:
    """Check if a series belongs to a specific root directory."""
    try:
        resolved_root = str(Path(root_dir).resolve())
    except Exception:
        resolved_root = root_dir

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
            p_path = Path(p).resolve()
            if p_path.is_relative_to(resolved_root):
                return True
        except Exception:
            pass
    return False
