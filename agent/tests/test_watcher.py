"""Unit tests for the filesystem watcher."""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock

from scan_agent.scan.watcher import (
    FilesystemWatcher,
    is_relevant_filesystem_path,
    match_library_for_path,
)


def test_is_relevant_filesystem_path() -> None:
    # Video files
    assert is_relevant_filesystem_path("/media/Shows/Show/S01E01.mkv") is True
    assert is_relevant_filesystem_path("/media/Shows/Show/S01E01.mp4") is True
    assert is_relevant_filesystem_path("/media/Movies/Movie.2024.avi") is True
    assert is_relevant_filesystem_path("/media/Movies/Movie.webm") is True

    # Subtitles
    assert is_relevant_filesystem_path("/media/Shows/Show/S01E01.en.srt") is True
    assert is_relevant_filesystem_path("/media/Shows/Show/S01E01.vtt") is True
    assert is_relevant_filesystem_path("/media/Shows/Show/S01E01.ass") is True

    # Directories
    assert is_relevant_filesystem_path("/media/Shows/New Show") is True
    assert is_relevant_filesystem_path("/media/Shows/New Show/Season 01") is True

    # Ignored temporary / system files
    assert is_relevant_filesystem_path("/media/Shows/Show/S01E01.mkv.part") is False
    assert (
        is_relevant_filesystem_path("/media/Shows/Show/S01E01.mkv.crdownload") is False
    )
    assert is_relevant_filesystem_path("/media/Shows/Show/S01E01.mkv.!ut") is False
    assert is_relevant_filesystem_path("/media/Shows/Show/file.tmp") is False
    assert is_relevant_filesystem_path("/media/Shows/.DS_Store") is False
    assert is_relevant_filesystem_path("/media/Shows/.git/HEAD") is False
    assert is_relevant_filesystem_path("/media/Shows/Thumbs.db") is False


def test_match_library_for_path(agent_config) -> None:
    tv_root = agent_config.libraries["tv"]["root_path"]
    movie_root = agent_config.libraries["movie"]["root_path"]

    tv_file = os.path.join(tv_root, "Test Show", "Season 01", "S01E01.mkv")
    movie_file = os.path.join(movie_root, "Some Movie (2020)", "movie.mkv")
    outside_file = "/completely/different/path/file.mkv"

    assert match_library_for_path(tv_file, agent_config.libraries) == "tv"
    assert match_library_for_path(movie_file, agent_config.libraries) == "movie"
    assert match_library_for_path(outside_file, agent_config.libraries) is None

    # Disabled library should be ignored
    agent_config.libraries["tv"]["enabled"] = False
    assert match_library_for_path(tv_file, agent_config.libraries) is None


def test_watcher_initialization(agent_config) -> None:
    orchestrator = MagicMock()
    watcher = FilesystemWatcher(agent_config, orchestrator)
    assert watcher.is_running is False
    assert watcher.debounce_seconds == 30


def test_watcher_debouncing_and_trigger(agent_config) -> None:
    orchestrator = MagicMock()
    orchestrator.status.return_value = {"running": None}
    agent_config.filesystem_watching_debounce_seconds = 1
    watcher = FilesystemWatcher(agent_config, orchestrator)

    tv_root = agent_config.libraries["tv"]["root_path"]
    tv_file = os.path.join(tv_root, "Test Show", "S01E01.mkv")

    # Record change
    watcher.record_change(tv_file)
    assert "tv" in watcher.pending_scans

    # Check pending scans before debounce period has passed
    watcher._process_pending_scans()
    orchestrator.start_scan.assert_not_called()

    # Fast-forward debounce timer
    watcher.pending_scans["tv"] = time.monotonic() - 1.0

    watcher._process_pending_scans()
    orchestrator.start_scan.assert_called_once_with(
        library_identifier="tv",
        pass_number=0,
        force_refresh=False,
    )
    assert "tv" not in watcher.pending_scans


def test_watcher_defers_scan_when_orchestrator_busy(agent_config) -> None:
    orchestrator = MagicMock()
    orchestrator.status.return_value = {"running": {"id": 123}}
    agent_config.filesystem_watching_debounce_seconds = 1
    watcher = FilesystemWatcher(agent_config, orchestrator)

    tv_root = agent_config.libraries["tv"]["root_path"]
    tv_file = os.path.join(tv_root, "Test Show", "S01E01.mkv")

    watcher.record_change(tv_file)
    watcher.pending_scans["tv"] = time.monotonic() - 1.0

    # Orchestrator is busy, scan should not be started and tv remains pending
    watcher._process_pending_scans()
    orchestrator.start_scan.assert_not_called()
    assert "tv" in watcher.pending_scans

    # Now orchestrator becomes idle
    orchestrator.status.return_value = {"running": None}
    watcher._process_pending_scans()
    orchestrator.start_scan.assert_called_once_with(
        library_identifier="tv",
        pass_number=0,
        force_refresh=False,
    )
    assert "tv" not in watcher.pending_scans


def test_watcher_lifecycle_start_and_stop(agent_config) -> None:
    orchestrator = MagicMock()
    watcher = FilesystemWatcher(agent_config, orchestrator)

    watcher.start()
    assert watcher.is_running is True

    # Idempotent start
    watcher.start()
    assert watcher.is_running is True

    watcher.stop()
    assert watcher.is_running is False

    # Idempotent stop
    watcher.stop()
    assert watcher.is_running is False
