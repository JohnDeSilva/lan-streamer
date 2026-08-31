"""Unit tests for archive root skipping in ScanAllLibrariesWorker."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from lan_streamer.backend.scan_worker_all import ScanAllLibrariesWorker
from lan_streamer.scanner.core import LibraryDict


def test_scan_all_libraries_skips_archive_roots_when_flag_is_false(tmp_path) -> None:
    """Verify that when scan_archive_roots is False, only active roots are scanned."""
    active_root = tmp_path / "tv_active"
    archive_root = tmp_path / "tv_archive"
    active_root.mkdir()
    archive_root.mkdir()

    scanned_roots: list[str] = []

    def fake_scan_directories(
        root_directories: list[str],
        *args: Any,
        **kwargs: Any,
    ) -> LibraryDict:
        scanned_roots.extend(root_directories)
        return LibraryDict({})

    mock_libraries = {
        "TV Shows": {
            "type": "tv",
            "paths": [str(active_root), str(archive_root)],
            "archive_paths": [str(archive_root)],
            "show_future_episodes": True,
        }
    }

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=fake_scan_directories,
        ),
    ):
        mock_config.libraries = mock_libraries

        worker = ScanAllLibrariesWorker(
            scan_archive_roots=False,
            run_pass1=True,
            run_pass2=False,
        )
        asyncio.run(worker.run_async())

        # Assert only the active root was scanned
        assert str(active_root) in scanned_roots
        assert str(archive_root) not in scanned_roots


def test_scan_all_libraries_scans_archive_roots_when_flag_is_true(tmp_path) -> None:
    """Verify that when scan_archive_roots is True, all roots (including archive) are scanned."""
    active_root = tmp_path / "tv_active"
    archive_root = tmp_path / "tv_archive"
    active_root.mkdir()
    archive_root.mkdir()

    scanned_roots: list[str] = []

    def fake_scan_directories(
        root_directories: list[str],
        *args: Any,
        **kwargs: Any,
    ) -> LibraryDict:
        scanned_roots.extend(root_directories)
        return LibraryDict({})

    mock_libraries = {
        "TV Shows": {
            "type": "tv",
            "paths": [str(active_root), str(archive_root)],
            "archive_paths": [str(archive_root)],
            "show_future_episodes": True,
        }
    }

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=fake_scan_directories,
        ),
    ):
        mock_config.libraries = mock_libraries

        worker = ScanAllLibrariesWorker(
            scan_archive_roots=True,
            run_pass1=True,
            run_pass2=False,
        )
        asyncio.run(worker.run_async())

        # Assert both active and archive roots were scanned
        assert str(active_root) in scanned_roots
        assert str(archive_root) in scanned_roots


def test_scan_all_libraries_tree_discovery_filters_archive_roots(tmp_path) -> None:
    """Verify tree discovery only walks active roots when scan_archive_roots is False."""
    active_root = tmp_path / "movies_active"
    archive_root = tmp_path / "movies_archive"
    active_root.mkdir()
    archive_root.mkdir()

    (active_root / "Movie 1").mkdir()
    ((active_root / "Movie 1") / "movie.mkv").write_bytes(b"\x00")
    (archive_root / "Movie 2").mkdir()
    ((archive_root / "Movie 2") / "movie.mkv").write_bytes(b"\x00")

    mock_libraries = {
        "Movies": {
            "type": "movie",
            "paths": [str(active_root), str(archive_root)],
            "archive_paths": [str(archive_root)],
        }
    }

    with patch("lan_streamer.backend.scan_worker_all.config") as mock_config:
        mock_config.libraries = mock_libraries

        worker_active_only = ScanAllLibrariesWorker(scan_archive_roots=False)
        tree_active = asyncio.run(worker_active_only._discover_tree({}))
        assert str(active_root) in tree_active["Movies"]["roots"]
        assert str(archive_root) not in tree_active["Movies"]["roots"]

        worker_all = ScanAllLibrariesWorker(scan_archive_roots=True)
        tree_all = asyncio.run(worker_all._discover_tree({}))
        assert str(active_root) in tree_all["Movies"]["roots"]
        assert str(archive_root) in tree_all["Movies"]["roots"]
