"""Path mapping service for translating remote agent paths to local mount points."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def map_remote_path_to_local(
    remote_file_path: str,
    mount_mappings: dict[str, str],
) -> str:
    """Map a remote file path to a local mount path using configured directory mappings.

    Sorts mappings by longest remote path first to ensure most specific prefix matches.
    """
    if not mount_mappings:
        return remote_file_path

    # Sort by longest remote root prefix descending to match most specific path first
    sorted_mappings = sorted(
        mount_mappings.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    normalized_remote = remote_file_path.replace("\\", "/")

    for remote_root, local_mount in sorted_mappings:
        normalized_root = remote_root.replace("\\", "/").rstrip("/")
        if not normalized_root:
            continue

        if normalized_remote == normalized_root:
            return local_mount

        if normalized_remote.startswith(normalized_root + "/"):
            relative_suffix = normalized_remote[len(normalized_root) :].lstrip("/")
            # Construct path using local filesystem separator
            parts = relative_suffix.split("/")
            mapped_path = os.path.join(local_mount, *parts)
            logger.debug(
                "Mapped remote path '%s' to local path '%s' via prefix '%s'",
                remote_file_path,
                mapped_path,
                remote_root,
            )
            return mapped_path

    return remote_file_path


def resolve_playback_path(
    file_path: str,
    libraries_configuration: dict[str, dict[str, Any]],
    current_library_name: str | None = None,
) -> str:
    """Resolve a playback path for an episode or movie.

    If the file exists locally at the given path, returns it immediately.
    Otherwise, inspects library mount mappings to translate remote paths.
    """
    if os.path.exists(file_path):
        return file_path

    # First check the specified current library if provided
    if current_library_name and current_library_name in libraries_configuration:
        library_data = libraries_configuration[current_library_name]
        mount_mappings: dict[str, str] = library_data.get("mount_mappings", {})
        mapped_path = map_remote_path_to_local(file_path, mount_mappings)
        if mapped_path != file_path:
            return mapped_path

    # Next, search all libraries that have mount mappings
    fallback_candidate: str | None = None
    for library_name, library_data in libraries_configuration.items():
        mount_mappings = library_data.get("mount_mappings", {})
        if not mount_mappings:
            continue

        mapped_path = map_remote_path_to_local(file_path, mount_mappings)
        if mapped_path != file_path:
            if os.path.exists(mapped_path):
                logger.info(
                    "Resolved playback path '%s' -> '%s' via library '%s'",
                    file_path,
                    mapped_path,
                    library_name,
                )
                return mapped_path
            if fallback_candidate is None:
                fallback_candidate = mapped_path

    if fallback_candidate is not None:
        logger.warning(
            "Resolved remote path '%s' -> '%s' via mount mappings, but file does not exist locally",
            file_path,
            fallback_candidate,
        )
        return fallback_candidate

    return file_path
