"""Unit tests for scanner performance optimizations (mtime fast-bypass and concurrency)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from lan_streamer.scanner.core import get_scan_executor, shutdown_scan_executor
from lan_streamer.scanner.pass1_file_discovery import (
    _check_season_unchanged,
    scan_movie_pass1,
    scan_series_pass1,
)
from lan_streamer.system.config import config


def test_check_season_unchanged_fast_bypass(tmp_path) -> None:
    """Verify that matching directory mtime returns True without calling exists on every episode."""
    season_dir = tmp_path / "Season 1"
    season_dir.mkdir()

    existing_season = {
        "name": "Season 1",
        "episodes": [
            {"name": "S01E01.mkv", "path": str(season_dir / "S01E01.mkv")},
            {"name": "S01E02.mkv", "path": str(season_dir / "S01E02.mkv")},
        ],
    }

    current_mtime = season_dir.stat().st_mtime

    with (
        patch(
            "lan_streamer.db.get_directory_mtime",
            return_value=current_mtime,
        ),
        patch.object(Path, "exists") as mock_exists,
    ):
        result = _check_season_unchanged(season_dir, existing_season)
        assert result is True
        # mock_exists should NOT have been called for individual episodes when mtimes match
        mock_exists.assert_not_called()


def test_scan_movie_pass1_fast_bypass(tmp_path) -> None:
    """Verify movie pass 1 returns unchanged data on mtime match without per-file exists checks."""
    movie_dir = tmp_path / "Inception (2010)"
    movie_dir.mkdir()
    movie_file = movie_dir / "Inception (2010).mkv"

    existing_movie_data = {
        "name": "Inception (2010)",
        "path": str(movie_file),
        "versions": [{"path": str(movie_file), "size": 1000}],
        "tmdb_identifier": "27205",
    }

    current_mtime = movie_dir.stat().st_mtime

    with (
        patch(
            "lan_streamer.db.get_directory_mtime",
            return_value=current_mtime,
        ),
        patch(
            "lan_streamer.scanner.pass1_file_discovery.find_video_files"
        ) as mock_find,
    ):
        result = scan_movie_pass1(movie_dir, existing_movie_data=existing_movie_data)
        assert result is not None
        assert result.get("_changed") is False
        # find_video_files should not have been called for an unchanged movie directory
        mock_find.assert_not_called()


def test_scan_series_pass1_unchanged_bypasses_deep_validation(tmp_path) -> None:
    """Verify unchanged series does not recursively walk directories for layout validation."""
    series_dir = tmp_path / "Breaking Bad"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()

    existing_series_data = {
        "name": "Breaking Bad",
        "path": str(series_dir),
        "metadata": {"name": "Breaking Bad", "tmdb_identifier": "1396"},
        "seasons": {
            "Season 1": {
                "name": "Season 1",
                "episodes": [
                    {
                        "name": "S01E01.mkv",
                        "path": str(season_dir / "S01E01.mkv"),
                        "season_number": 1,
                        "episode_number": 1,
                        "versions": [{"path": str(season_dir / "S01E01.mkv")}],
                    }
                ],
            }
        },
    }

    current_series_mtime = series_dir.stat().st_mtime
    current_season_mtime = season_dir.stat().st_mtime

    def mock_get_directory_mtime(path: str) -> float | None:
        if path == str(series_dir.absolute()):
            return current_series_mtime
        if path == str(season_dir.absolute()):
            return current_season_mtime
        return None

    with (
        patch(
            "lan_streamer.db.get_directory_mtime", side_effect=mock_get_directory_mtime
        ),
        patch(
            "lan_streamer.scanner.pass1_file_discovery.find_video_files"
        ) as mock_find,
        patch("lan_streamer.db.save_directory_mtime"),
    ):
        result = scan_series_pass1(
            series_dir, existing_series_data=existing_series_data
        )
        assert result is not None
        assert "Season 1" in result["seasons"]
        assert len(result["seasons"]["Season 1"]["episodes"]) == 1
        # find_video_files recursive walk should NOT have been called on unchanged series
        mock_find.assert_not_called()


def test_get_scan_executor_concurrency_configured() -> None:
    """Verify that get_scan_executor respects configured scan_concurrency."""
    shutdown_scan_executor()
    try:
        config.scan_concurrency = 3
        executor = get_scan_executor()
        assert executor._max_workers == 3
    finally:
        shutdown_scan_executor()


def test_settings_dialog_scan_concurrency(qtbot) -> None:
    """Verify SettingsDialog loads and saves scan_concurrency."""
    from lan_streamer.ui_views.dialogs.settings import SettingsDialog

    with patch.object(config, "scan_concurrency", 6):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)

        assert dialog.scan_concurrency_spinbox.value() == 6

        dialog.scan_concurrency_spinbox.setValue(2)
        with patch.object(config, "save"), patch.object(config, "save_to_db"):
            dialog.save_config()
            assert config.scan_concurrency == 2
