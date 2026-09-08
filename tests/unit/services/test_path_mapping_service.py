"""Unit tests for path mapping and playback path resolution for remote libraries."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from lan_streamer.services.path_mapping_service import (
    map_remote_path_to_local,
    resolve_playback_path,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_map_remote_path_to_local_exact_prefix(tmp_path: Path) -> None:
    local_mount = tmp_path / "mount_tv"
    local_mount.mkdir()
    episode_file = local_mount / "ShowName" / "Season 1" / "S01E01.mkv"
    episode_file.parent.mkdir(parents=True)
    episode_file.write_text("sample video")

    remote_root = "/media/tv"
    remote_file_path = "/media/tv/ShowName/Season 1/S01E01.mkv"

    resolved = map_remote_path_to_local(
        remote_file_path=remote_file_path,
        mount_mappings={remote_root: str(local_mount)},
    )
    assert resolved == str(episode_file)


def test_map_remote_path_to_local_fallback_when_file_missing() -> None:
    remote_root = "/media/tv"
    local_mount = "/mnt/nas/tv"
    remote_file_path = "/media/tv/ShowName/Season 1/S01E02.mkv"

    resolved = map_remote_path_to_local(
        remote_file_path=remote_file_path,
        mount_mappings={remote_root: local_mount},
    )
    expected_suffix = os.path.join("ShowName", "Season 1", "S01E02.mkv")
    assert resolved.endswith(expected_suffix)
    assert resolved.startswith(local_mount)


def test_resolve_playback_path_prefers_existing_local_file(tmp_path: Path) -> None:
    local_file = tmp_path / "local_video.mp4"
    local_file.write_text("local")

    resolved = resolve_playback_path(
        file_path=str(local_file),
        libraries_configuration={},
    )
    assert resolved == str(local_file)


def test_resolve_playback_path_with_library_mount_mappings(tmp_path: Path) -> None:
    local_mount = tmp_path / "nas_movies"
    local_mount.mkdir()
    movie_file = local_mount / "Inception (2010)" / "Inception.mkv"
    movie_file.parent.mkdir(parents=True)
    movie_file.write_text("movie")

    libraries_configuration = {
        "NAS Movies": {
            "type": "movie",
            "management_type": "remote",
            "mount_mappings": {"/storage/movies": str(local_mount)},
        }
    }

    resolved = resolve_playback_path(
        file_path="/storage/movies/Inception (2010)/Inception.mkv",
        libraries_configuration=libraries_configuration,
        current_library_name="NAS Movies",
    )
    assert resolved == str(movie_file)


def test_resolve_playback_path_no_match_returns_original() -> None:
    original_path = "/unknown/storage/path/video.mkv"
    resolved = resolve_playback_path(
        file_path=original_path,
        libraries_configuration={},
    )
    assert resolved == original_path


def test_map_remote_path_to_local_empty_mappings() -> None:
    assert map_remote_path_to_local("/any/path", {}) == "/any/path"


def test_map_remote_path_to_local_exact_root_match() -> None:
    assert map_remote_path_to_local("/media/tv", {"/media/tv": "/mnt/tv"}) == "/mnt/tv"


def test_map_remote_path_to_local_empty_root_in_mapping() -> None:
    assert (
        map_remote_path_to_local("/media/tv/file.mkv", {"": "/mnt/tv"})
        == "/media/tv/file.mkv"
    )


def test_resolve_playback_path_finds_in_any_library_existing(tmp_path: Path) -> None:
    local_mount = tmp_path / "mount_anime"
    local_mount.mkdir()
    anime_file = local_mount / "Frieren" / "S01E01.mkv"
    anime_file.parent.mkdir(parents=True)
    anime_file.write_text("anime")

    libraries_configuration = {
        "Other Library": {"mount_mappings": {}},
        "Anime": {
            "management_type": "remote",
            "mount_mappings": {"/agent/anime": str(local_mount)},
        },
    }

    resolved = resolve_playback_path(
        file_path="/agent/anime/Frieren/S01E01.mkv",
        libraries_configuration=libraries_configuration,
    )
    assert resolved == str(anime_file)


def test_resolve_playback_path_fallback_candidate_when_file_not_on_disk() -> None:
    libraries_configuration = {
        "Remote Movies": {
            "management_type": "remote",
            "mount_mappings": {"/agent/movies": "/mnt/movies"},
        },
    }

    resolved = resolve_playback_path(
        file_path="/agent/movies/NonExistent.mkv",
        libraries_configuration=libraries_configuration,
    )
    assert resolved == "/mnt/movies/NonExistent.mkv"
