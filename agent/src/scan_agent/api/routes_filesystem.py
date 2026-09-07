"""Filesystem directory browsing route for library storage folder selection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

filesystem_router = APIRouter(tags=["filesystem"])


def _get_system_roots() -> list[str]:
    """Return common mount roots and drive paths for quick navigation."""
    system_roots: list[str] = []
    # Common container and Unix mounts
    for candidate in ("/media", "/data", "/mnt", "/home", "/"):
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_dir():
            system_roots.append(str(candidate_path))
    # Windows drive letters if running on Windows
    if os.name == "nt":
        import string

        for letter in string.ascii_uppercase:
            drive_path = Path(f"{letter}:\\")
            if drive_path.exists():
                system_roots.append(str(drive_path))
    return system_roots


@filesystem_router.get("/filesystem/browse")
def browse_filesystem(
    directory_path: str | None = Query(default=None, alias="path", max_length=1024),
) -> dict[str, Any]:
    """List subdirectories in the specified server directory for folder picking.

    If *directory_path* is omitted or invalid, defaults to /media (if present),
    /data, or the system root.
    """
    if directory_path and directory_path.strip():
        target_directory = Path(directory_path.strip()).expanduser().resolve()
    else:
        target_directory = Path("/").resolve()
        for candidate in ("/media", "/data", str(Path.home()), "/"):
            candidate_path = Path(candidate)
            if candidate_path.exists() and candidate_path.is_dir():
                target_directory = candidate_path.resolve()
                break

    if not target_directory.exists() or not target_directory.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Directory does not exist: {target_directory}",
        )

    parent_path = (
        str(target_directory.parent)
        if target_directory.parent != target_directory
        else None
    )

    directories: list[dict[str, Any]] = []
    try:
        entries = sorted(
            os.scandir(target_directory), key=lambda entry: entry.name.lower()
        )
        for filesystem_entry in entries:
            if filesystem_entry.name.startswith("."):
                continue  # Skip hidden directories
            try:
                if filesystem_entry.is_dir(follow_symlinks=True):
                    directories.append(
                        {
                            "name": filesystem_entry.name,
                            "path": str(Path(filesystem_entry.path).resolve()),
                        }
                    )
            except OSError, PermissionError:
                continue
    except (OSError, PermissionError) as error:
        raise HTTPException(
            status_code=403, detail=f"Permission denied: {error}"
        ) from error

    return {
        "current_path": str(target_directory),
        "parent_path": parent_path,
        "directories": directories,
        "shortcuts": _get_system_roots(),
    }
