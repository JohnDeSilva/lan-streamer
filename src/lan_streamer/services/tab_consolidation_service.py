"""
Service for consolidating media libraries assigned to a tab.

When multiple libraries are grouped together in a single tab, series appearing
across multiple libraries (matching on TMDB identifier or normalized title)
are consolidated into a single unified record with combined seasons, episodes,
and media file versions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

from lan_streamer.scanner.core import _merge_series_data

logger = logging.getLogger(__name__)


def _extract_series_merge_key(series_name: str, series_data: dict[str, Any]) -> str:
    metadata = series_data.get("metadata", {})
    tmdb_identifier = metadata.get("tmdb_identifier") or metadata.get("tmdb_id")
    if tmdb_identifier:
        return f"tmdb:{tmdb_identifier}"
    return f"title:{series_name.strip().lower()}"


def _extract_movie_merge_key(movie_name: str, movie_data: dict[str, Any]) -> str:
    tmdb_identifier = movie_data.get("tmdb_id") or movie_data.get("tmdb_identifier")
    if tmdb_identifier:
        return f"tmdb:{tmdb_identifier}"
    return f"title:{movie_name.strip().lower()}"


def _merge_movie_records(
    primary_movie: dict[str, Any], incoming_movie: dict[str, Any]
) -> dict[str, Any]:
    merged_movie = dict(primary_movie)

    existing_versions: list[dict[str, Any]] = list(primary_movie.get("versions", []))
    existing_paths: set[str] = {
        version.get("path", "")
        for version in existing_versions
        if isinstance(version, dict)
    }

    incoming_versions = incoming_movie.get("versions", [])
    if incoming_versions:
        for version_record in incoming_versions:
            if (
                isinstance(version_record, dict)
                and version_record.get("path")
                and version_record["path"] not in existing_paths
            ):
                existing_versions.append(version_record)
                existing_paths.add(version_record["path"])
    else:
        incoming_path = incoming_movie.get("path")
        if incoming_path and incoming_path not in existing_paths:
            existing_versions.append(
                {"path": incoming_path, "name": incoming_movie.get("name", "")}
            )

    merged_movie["versions"] = existing_versions
    if incoming_movie.get("watched") is True:
        merged_movie["watched"] = True

    return merged_movie


def consolidate_library_data(
    libraries_data: Sequence[tuple[str, dict[str, Any]] | dict[str, Any]],
) -> dict[str, Any]:
    """
    Consolidates data dictionaries from multiple libraries belonging to a tab.

    Arguments:
        libraries_data: List of (library_name, library_data_dictionary) pairs or dicts.

    Returns:
        Consolidated dictionary mapping item display names to unified media records.
    """
    consolidated_items: dict[str, Any] = {}
    key_to_item_name: dict[str, str] = {}

    for library_entry in libraries_data:
        if isinstance(library_entry, tuple) and len(library_entry) == 2:
            library_name, library_content = library_entry
        elif isinstance(library_entry, dict):
            library_name = ""
            library_content = library_entry
        else:
            continue

        if not isinstance(library_content, dict):
            continue

        for item_name, item_data in library_content.items():
            if not isinstance(item_data, dict):
                consolidated_items[item_name] = item_data
                continue

            # Determine whether this is a TV series or a Movie
            is_series = "seasons" in item_data or "metadata" in item_data

            if is_series:
                deduplication_key = _extract_series_merge_key(item_name, item_data)
                if deduplication_key in key_to_item_name:
                    primary_name = key_to_item_name[deduplication_key]
                    existing_series = consolidated_items[primary_name]
                    merged_series = _merge_series_data(existing_series, item_data)
                    origin_libraries = list(
                        existing_series.get("_origin_libraries", [])
                    )
                    if library_name not in origin_libraries:
                        origin_libraries.append(library_name)
                    merged_series["_origin_libraries"] = origin_libraries
                    consolidated_items[primary_name] = merged_series
                    logger.debug(
                        "Consolidated series '%s' from library '%s' into '%s'",
                        item_name,
                        library_name,
                        primary_name,
                    )
                else:
                    new_series = dict(item_data)
                    new_series["_origin_libraries"] = [library_name]
                    consolidated_items[item_name] = new_series
                    key_to_item_name[deduplication_key] = item_name
            else:
                deduplication_key = _extract_movie_merge_key(item_name, item_data)
                if deduplication_key in key_to_item_name:
                    primary_name = key_to_item_name[deduplication_key]
                    existing_movie = consolidated_items[primary_name]
                    merged_movie = _merge_movie_records(existing_movie, item_data)
                    origin_libraries = list(existing_movie.get("_origin_libraries", []))
                    if library_name not in origin_libraries:
                        origin_libraries.append(library_name)
                    merged_movie["_origin_libraries"] = origin_libraries
                    consolidated_items[primary_name] = merged_movie
                    logger.debug(
                        "Consolidated movie '%s' from library '%s' into '%s'",
                        item_name,
                        library_name,
                        primary_name,
                    )
                else:
                    new_movie = dict(item_data)
                    new_movie["_origin_libraries"] = [library_name]
                    consolidated_items[item_name] = new_movie
                    key_to_item_name[deduplication_key] = item_name

    return consolidated_items
