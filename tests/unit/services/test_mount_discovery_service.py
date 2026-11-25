"""Unit tests for automatic OS network mount discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from lan_streamer.services.mount_discovery_service import (
    auto_detect_mount_for_remote_root,
    auto_detect_mount_mappings_for_items,
    extract_sample_relative_paths,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_extract_sample_relative_paths_for_tv_and_movies() -> None:
    tv_items: dict[str, Any] = {
        "Show A": {
            "seasons": {
                "Season 01": {
                    "episodes": [
                        {
                            "path": "/media/tv/Show A/Season 01/S01E01.mkv",
                            "versions": [
                                {"path": "/media/tv/Show A/Season 01/S01E01.mp4"}
                            ],
                        }
                    ]
                }
            }
        }
    }
    tv_samples = extract_sample_relative_paths("/media/tv", tv_items, library_type="tv")
    assert tv_samples == [
        "Show A/Season 01/S01E01.mkv",
        "Show A/Season 01/S01E01.mp4",
    ]

    movie_items: dict[str, Any] = {
        "Movie A": {
            "path": "/media/movies/Movie A (2024)/Movie A.mkv",
            "versions": [{"path": "/other/root/Movie A.mkv"}],
        }
    }
    movie_samples = extract_sample_relative_paths(
        "/media/movies", movie_items, library_type="movie"
    )
    assert movie_samples == ["Movie A (2024)/Movie A.mkv"]


def test_auto_detect_mount_for_remote_root_direct_and_nested(tmp_path: Path) -> None:
    volumes_dir = tmp_path / "Volumes"
    direct_mount = volumes_dir / "tv"
    nested_root = volumes_dir / "NAS"
    nested_tv = nested_root / "tv"
    (direct_mount / "Show A").mkdir(parents=True)
    (direct_mount / "Show A" / "S01E01.mkv").write_bytes(b"video")

    (nested_tv / "Show B").mkdir(parents=True)
    (nested_tv / "Show B" / "S01E01.mkv").write_bytes(b"video")

    detected_direct = auto_detect_mount_for_remote_root(
        "/media/tv",
        ["Show A/S01E01.mkv"],
        mount_candidates=[str(direct_mount), str(nested_root)],
    )
    assert detected_direct == str(direct_mount)

    detected_nested = auto_detect_mount_for_remote_root(
        "/media/tv",
        ["Show B/S01E01.mkv"],
        mount_candidates=[str(direct_mount), str(nested_root)],
    )
    assert detected_nested == str(nested_tv)


def test_auto_detect_mount_for_deeply_nested_smb_share(tmp_path: Path) -> None:
    storage_mount = tmp_path / "Volumes" / "storage"
    deep_tv = storage_mount / "current" / "video" / "tv"
    (deep_tv / "Breaking Bad" / "Season 01").mkdir(parents=True)
    (deep_tv / "Breaking Bad" / "Season 01" / "S01E01.mkv").write_bytes(b"video")

    detected = auto_detect_mount_for_remote_root(
        "/media/tv",
        ["Breaking Bad/Season 01/S01E01.mkv"],
        mount_candidates=[str(storage_mount)],
    )
    assert detected == str(deep_tv)


def test_auto_detect_mount_mappings_skips_valid_existing_mounts(
    tmp_path: Path,
) -> None:
    existing_valid = tmp_path / "existing_mount"
    existing_valid.mkdir()
    new_mount = tmp_path / "Volumes" / "NAS"
    target_movies = new_mount / "movies"
    (target_movies / "Inception").mkdir(parents=True)
    (target_movies / "Inception" / "Inception.mkv").write_bytes(b"video")

    items: dict[str, Any] = {
        "Inception": {"path": "/media/movies/Inception/Inception.mkv"}
    }
    detected = auto_detect_mount_mappings_for_items(
        remote_roots=["/media/tv", "/media/movies"],
        items_dictionary=items,
        library_type="movie",
        existing_mappings={
            "/media/tv": str(existing_valid),
            "/media/movies": str(tmp_path / "missing_mount"),
        },
        mount_candidates=[str(new_mount)],
    )
    assert detected == {"/media/movies": str(target_movies)}
