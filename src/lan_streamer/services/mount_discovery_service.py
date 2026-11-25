"""Automatic local network mount discovery for remote scan-agent libraries."""

from __future__ import annotations

import logging
import os
import sys
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)

_DEFAULT_MAX_SCAN_DEPTH: int = 5
_DEFAULT_MAX_DIRECTORIES_PER_MOUNT: int = 500
_IGNORED_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        "@eaDir",
        "#recycle",
        "$RECYCLE.BIN",
        "System Volume Information",
        ".Trashes",
        ".Spotlight-V100",
        ".fseventsd",
    }
)

_NETWORK_FILESYSTEM_TYPES: frozenset[str] = frozenset(
    {
        "cifs",
        "smb3",
        "smbfs",
        "nfs",
        "nfs4",
        "fuse.sshfs",
        "fuse.rclone",
        "davfs",
        "9p",
        "virtiofs",
    }
)


def _collect_subdirectories(
    parent_directory: Path, add_candidate: Callable[[str | Path], None]
) -> None:
    """Add non-hidden immediate subdirectories of *parent_directory*."""
    if not parent_directory.is_dir():
        return
    try:
        for entry in sorted(parent_directory.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                add_candidate(entry)
    except OSError:
        pass


def _discover_darwin_mounts(add_candidate: Callable[[str | Path], None]) -> None:
    """Discover mounted volumes under /Volumes on macOS."""
    volumes_root = Path("/Volumes")
    if not volumes_root.is_dir():
        return
    try:
        for entry in sorted(volumes_root.iterdir()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_symlink() and os.path.realpath(entry) == "/":
                    continue
            except OSError:
                pass
            if entry.is_dir():
                add_candidate(entry)
    except OSError as error_instance:
        logger.debug("Could not enumerate /Volumes: %s", error_instance)


def _discover_linux_mounts(add_candidate: Callable[[str | Path], None]) -> None:
    """Discover network and removable mounts on Linux."""
    proc_mounts = Path("/proc/mounts")
    if proc_mounts.is_file():
        try:
            for line in proc_mounts.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2].lower() in _NETWORK_FILESYSTEM_TYPES:
                    add_candidate(parts[1].replace("\\040", " "))
        except OSError as error_instance:
            logger.debug("Could not read /proc/mounts: %s", error_instance)

    for parent_directory in (Path("/mnt"), Path("/media")):
        _collect_subdirectories(parent_directory, add_candidate)

    user_name = os.environ.get("USER", "")
    if user_name:
        _collect_subdirectories(Path("/media") / user_name, add_candidate)
        _collect_subdirectories(Path("/run/media") / user_name, add_candidate)

    uid = os.getuid() if hasattr(os, "getuid") else None
    if uid is not None:
        _collect_subdirectories(Path(f"/run/user/{uid}/gvfs"), add_candidate)


def _discover_windows_mounts(add_candidate: Callable[[str | Path], None]) -> None:
    """Discover mapped remote network drives on Windows."""
    import string

    drive_type_remote = 4
    kernel32 = None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError, OSError:
        kernel32 = None

    for drive_letter in string.ascii_uppercase:
        drive_root = f"{drive_letter}:\\"
        if kernel32 is not None:
            try:
                if kernel32.GetDriveTypeW(drive_root) == drive_type_remote:
                    add_candidate(drive_root)
                    continue
            except OSError:
                pass
        if drive_letter not in ("A", "B", "C") and os.path.isdir(drive_root):
            add_candidate(drive_root)


def _collect_subdirectories(
    parent_directory: Path, add_candidate: Callable[[str | Path], None]
) -> None:
    """Add non-hidden immediate subdirectories of *parent_directory*."""
    if not parent_directory.is_dir():
        return
    try:
        for entry in sorted(parent_directory.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                add_candidate(entry)
    except OSError:
        pass


def _discover_darwin_mounts(add_candidate: Callable[[str | Path], None]) -> None:
    """Discover mounted volumes under /Volumes on macOS."""
    volumes_root = Path("/Volumes")
    if not volumes_root.is_dir():
        return
    try:
        for entry in sorted(volumes_root.iterdir()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_symlink() and os.path.realpath(entry) == "/":
                    continue
            except OSError:
                pass
            if entry.is_dir():
                add_candidate(entry)
    except OSError as error_instance:
        logger.debug("Could not enumerate /Volumes: %s", error_instance)


def _discover_linux_mounts(add_candidate: Callable[[str | Path], None]) -> None:
    """Discover network and removable mounts on Linux."""
    proc_mounts = Path("/proc/mounts")
    if proc_mounts.is_file():
        try:
            for line in proc_mounts.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2].lower() in _NETWORK_FILESYSTEM_TYPES:
                    add_candidate(parts[1].replace("\\040", " "))
        except OSError as error_instance:
            logger.debug("Could not read /proc/mounts: %s", error_instance)

    for parent_directory in (Path("/mnt"), Path("/media")):
        _collect_subdirectories(parent_directory, add_candidate)

    user_name = os.environ.get("USER", "")
    if user_name:
        _collect_subdirectories(Path("/media") / user_name, add_candidate)
        _collect_subdirectories(Path("/run/media") / user_name, add_candidate)

    uid = os.getuid() if hasattr(os, "getuid") else None
    if uid is not None:
        _collect_subdirectories(Path(f"/run/user/{uid}/gvfs"), add_candidate)


def _discover_windows_mounts(add_candidate: Callable[[str | Path], None]) -> None:
    """Discover mapped remote network drives on Windows."""
    import string

    drive_type_remote = 4
    kernel32 = None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError, OSError:
        kernel32 = None

    for drive_letter in string.ascii_uppercase:
        drive_root = f"{drive_letter}:\\"
        if kernel32 is not None:
            try:
                if kernel32.GetDriveTypeW(drive_root) == drive_type_remote:
                    add_candidate(drive_root)
                    continue
            except OSError:
                pass
        if drive_letter not in ("A", "B", "C") and os.path.isdir(drive_root):
            add_candidate(drive_root)


def discover_local_mount_candidates() -> list[str]:
    """Return candidate local mount point directories for the current OS."""
    candidates: list[str] = []
    seen: set[str] = set()

    def _add_candidate(path_value: str | Path) -> None:
        try:
            resolved = str(Path(path_value))
        except OSError, ValueError:
            return
        if not resolved or resolved in seen:
            return
        if os.path.isdir(resolved):
            seen.add(resolved)
            candidates.append(resolved)

    if sys.platform == "darwin":
        _discover_darwin_mounts(_add_candidate)
    elif sys.platform.startswith("linux"):
        _discover_linux_mounts(_add_candidate)
    elif os.name == "nt":
        _discover_windows_mounts(_add_candidate)

    return candidates


def extract_sample_relative_paths(
    remote_root: str,
    items_dictionary: dict[str, Any],
    library_type: str = "tv",
    max_samples: int = 12,
) -> list[str]:
    """Extract sample relative file paths belonging to *remote_root* from agent items."""
    normalized_root = remote_root.replace("\\", "/").rstrip("/")
    if not normalized_root:
        return []

    prefix = normalized_root + "/"
    samples: list[str] = []
    seen: set[str] = set()

    def _maybe_collect(candidate_path: Any) -> bool:
        if not candidate_path or not isinstance(candidate_path, str):
            return False
        normalized_candidate = candidate_path.replace("\\", "/")
        if not normalized_candidate.startswith(prefix):
            return False
        relative_path = normalized_candidate[len(prefix) :].lstrip("/")
        if relative_path and relative_path not in seen:
            seen.add(relative_path)
            samples.append(relative_path)
        return len(samples) >= max_samples

    for item_data in items_dictionary.values():
        if not isinstance(item_data, dict):
            continue
        is_movie = library_type == "movie" or (
            "seasons" not in item_data and "path" in item_data
        )
        if is_movie:
            if _maybe_collect(item_data.get("path")):
                return samples
            for version in item_data.get("versions", []) or []:
                if isinstance(version, dict) and _maybe_collect(version.get("path")):
                    return samples
        else:
            for season_data in (item_data.get("seasons") or {}).values():
                if not isinstance(season_data, dict):
                    continue
                for episode in season_data.get("episodes", []) or []:
                    if not isinstance(episode, dict):
                        continue
                    if _maybe_collect(episode.get("path")):
                        return samples
                    for version in episode.get("versions", []) or []:
                        if isinstance(version, dict) and _maybe_collect(
                            version.get("path")
                        ):
                            return samples

    return samples


def _iter_local_base_candidates(
    mount_root: str,
    remote_root: str,
    max_depth: int = _DEFAULT_MAX_SCAN_DEPTH,
    max_directories: int = _DEFAULT_MAX_DIRECTORIES_PER_MOUNT,
) -> Iterator[str]:
    """Lazily yield local base directory candidates under *mount_root*.

    Yields direct/tail-matched paths first, then performs a bounded
    breadth-first directory scan up to *max_depth* levels deep so nested SMB
    subpaths (e.g. ``/Volumes/storage/current/video/tv`` for ``/media/tv``)
    are discovered and scanning stops as soon as a match is verified.
    """
    normalized_remote = remote_root.replace("\\", "/").strip("/")
    remote_parts = [part for part in normalized_remote.split("/") if part]
    target_leaf_name = remote_parts[-1].lower() if remote_parts else ""

    seen: set[str] = {mount_root}
    yield mount_root

    if remote_parts:
        leaf_candidate = os.path.join(mount_root, remote_parts[-1])
        if leaf_candidate not in seen and os.path.isdir(leaf_candidate):
            seen.add(leaf_candidate)
            yield leaf_candidate
    if len(remote_parts) >= 2:
        tail_candidate = os.path.join(mount_root, remote_parts[-2], remote_parts[-1])
        if tail_candidate not in seen and os.path.isdir(tail_candidate):
            seen.add(tail_candidate)
            yield tail_candidate

    queue: deque[tuple[str, int]] = deque([(mount_root, 0)])
    visited_count = 0

    while queue and visited_count < max_directories:
        current_directory, depth = queue.popleft()
        if depth >= max_depth:
            continue
        try:
            subdirectories = [
                entry
                for entry in os.scandir(current_directory)
                if entry.is_dir(follow_symlinks=True)
                and not entry.name.startswith(".")
                and entry.name not in _IGNORED_DIRECTORY_NAMES
            ]
        except OSError:
            continue

        # Prefer directories matching the remote root's leaf name first
        subdirectories.sort(
            key=lambda entry: (
                0 if target_leaf_name and entry.name.lower() == target_leaf_name else 1,
                entry.name.lower(),
            )
        )
        for entry in subdirectories:
            visited_count += 1
            if entry.path not in seen:
                seen.add(entry.path)
                yield entry.path
            if depth + 1 < max_depth and visited_count < max_directories:
                queue.append((entry.path, depth + 1))


def auto_detect_mount_for_remote_root(
    remote_root: str,
    sample_relative_paths: list[str],
    mount_candidates: list[str] | None = None,
    max_depth: int = _DEFAULT_MAX_SCAN_DEPTH,
) -> str | None:
    """Find the local mount directory corresponding to *remote_root* by checking sample files."""
    if not remote_root or not sample_relative_paths:
        return None

    parsed_samples = [
        [part for part in relative_path.split("/") if part]
        for relative_path in sample_relative_paths
    ]
    parsed_samples = [parts for parts in parsed_samples if parts]
    if not parsed_samples:
        return None

    local_mounts = (
        mount_candidates
        if mount_candidates is not None
        else discover_local_mount_candidates()
    )
    if not local_mounts:
        return None

    # Precompute unique top-level directory names (e.g. show/movie folder names)
    # to quickly reject non-matching directories before checking all sample files.
    top_level_names = list(
        dict.fromkeys(parts[0] for parts in parsed_samples if len(parts) > 1)
    )

    best_base_path: str | None = None
    best_match_count = 0

    for mount_root in local_mounts:
        if not os.path.isdir(mount_root):
            continue
        for candidate_base in _iter_local_base_candidates(
            mount_root, remote_root, max_depth=max_depth
        ):
            if top_level_names and not any(
                os.path.isdir(os.path.join(candidate_base, top_name))
                for top_name in top_level_names
            ):
                continue

            match_count = 0
            for relative_parts in parsed_samples:
                local_file_candidate = os.path.join(candidate_base, *relative_parts)
                if os.path.exists(local_file_candidate):
                    match_count += 1
            if match_count > best_match_count:
                best_match_count = match_count
                best_base_path = candidate_base
                if best_match_count == len(parsed_samples):
                    logger.info(
                        "Auto-detected local mount '%s' for remote root '%s' (%d/%d samples matched)",
                        best_base_path,
                        remote_root,
                        best_match_count,
                        len(parsed_samples),
                    )
                    return best_base_path

    if best_base_path is not None:
        logger.info(
            "Auto-detected local mount '%s' for remote root '%s' (%d/%d samples matched)",
            best_base_path,
            remote_root,
            best_match_count,
            len(parsed_samples),
        )
    return best_base_path


def auto_detect_mount_mappings_for_items(
    remote_roots: list[str],
    items_dictionary: dict[str, Any],
    library_type: str = "tv",
    existing_mappings: dict[str, str] | None = None,
    mount_candidates: list[str] | None = None,
    max_depth: int = _DEFAULT_MAX_SCAN_DEPTH,
) -> dict[str, str]:
    """Auto-detect missing or broken local mount mappings for a list of remote roots."""
    detected_mappings: dict[str, str] = {}
    existing = existing_mappings or {}

    resolved_candidates = (
        mount_candidates
        if mount_candidates is not None
        else discover_local_mount_candidates()
    )

    for remote_root in remote_roots:
        if not remote_root:
            continue
        existing_local = existing.get(remote_root, "")
        if existing_local and os.path.isdir(existing_local):
            continue

        sample_paths = extract_sample_relative_paths(
            remote_root,
            items_dictionary,
            library_type=library_type,
        )
        if not sample_paths:
            continue

        detected_local = auto_detect_mount_for_remote_root(
            remote_root,
            sample_paths,
            mount_candidates=resolved_candidates,
            max_depth=max_depth,
        )
        if detected_local:
            detected_mappings[remote_root] = detected_local

    return detected_mappings
