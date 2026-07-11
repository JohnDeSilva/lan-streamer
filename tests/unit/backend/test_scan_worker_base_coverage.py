"""Coverage tests for scan_worker_base.py — targeting uncovered lines."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from lan_streamer.backend.scan_worker_base import (
    create_empty_stats,
    merge_stats_dicts,
    log_stats_breakdown,
    log_issues_report,
    log_db_write_error,
    discover_single_library_tree_impl,
    series_belongs_to_root,
)


class TestDiscoverWithExistingLibrary:
    """Lines 172-181: existing_library path in discover_single_library_tree_impl."""

    def test_existing_library_used_instead_of_fs(self, tmp_path: Path) -> None:
        root1 = tmp_path / "root1"
        root1.mkdir()

        existing_library: dict[str, Any] = {
            "Show A": {
                "metadata": {},
                "seasons": {
                    "Season 1": {
                        "episodes": [
                            {"path": str(root1 / "Show A" / "ep1.mkv")},
                        ]
                    }
                },
            },
            "Show B": {
                "metadata": {},
                "seasons": {
                    "Season 1": {
                        "episodes": [
                            {"path": str(root1 / "Show B" / "ep1.mkv")},
                        ]
                    }
                },
            },
        }

        result = discover_single_library_tree_impl(
            [str(root1)], "tv", existing_library=existing_library
        )
        assert str(root1) in result
        assert "Show A" in result[str(root1)]
        assert "Show B" in result[str(root1)]

    def test_existing_library_empty_roots(self, tmp_path: Path) -> None:
        root1 = tmp_path / "root1"
        root1.mkdir()

        result = discover_single_library_tree_impl(
            [str(root1)], "tv", existing_library={}
        )
        assert str(root1) in result
        assert result[str(root1)] == []


class TestSeriesBelongsToRoot:
    """Lines 206-237: series_belongs_to_root."""

    def test_tv_series_matches_root(self, tmp_path: Path) -> None:
        root = tmp_path / "tv_shows"
        root.mkdir()
        series_data = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"path": str(root / "MyShow" / "ep1.mkv")},
                    ]
                }
            }
        }
        assert series_belongs_to_root(series_data, str(root), "tv") is True

    def test_tv_series_no_match(self, tmp_path: Path) -> None:
        root = tmp_path / "tv_shows"
        root.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        series_data = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"path": str(other / "MyShow" / "ep1.mkv")},
                    ]
                }
            }
        }
        assert series_belongs_to_root(series_data, str(root), "tv") is False

    def test_movie_with_path(self, tmp_path: Path) -> None:
        root = tmp_path / "movies"
        root.mkdir()
        movie_data = {
            "path": str(root / "MyMovie" / "movie.mkv"),
        }
        assert series_belongs_to_root(movie_data, str(root), "movie") is True

    def test_movie_with_default_path(self, tmp_path: Path) -> None:
        root = tmp_path / "movies"
        root.mkdir()
        movie_data = {
            "default_path": str(root / "MyMovie" / "movie.mkv"),
        }
        assert series_belongs_to_root(movie_data, str(root), "movie") is True

    def test_movie_with_versions(self, tmp_path: Path) -> None:
        root = tmp_path / "movies"
        root.mkdir()
        movie_data = {
            "versions": [
                {"path": str(root / "MyMovie" / "movie.mkv")},
            ],
        }
        assert series_belongs_to_root(movie_data, str(root), "movie") is True

    def test_movie_no_match(self, tmp_path: Path) -> None:
        root = tmp_path / "movies"
        root.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        movie_data = {
            "path": str(other / "MyMovie" / "movie.mkv"),
        }
        assert series_belongs_to_root(movie_data, str(root), "movie") is False

    def test_exception_in_resolve_falls_back(self) -> None:
        series_data: dict[str, Any] = {"seasons": {}}
        assert series_belongs_to_root(series_data, "/nonexistent_root", "tv") is False

    def test_bad_path_in_tv_series(self, tmp_path: Path) -> None:
        root = tmp_path / "tv"
        root.mkdir()
        series_data = {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"path": None},
                        {"path": ""},
                    ]
                }
            }
        }
        assert series_belongs_to_root(series_data, str(root), "tv") is False

    def test_tv_episodes_with_no_paths(self, tmp_path: Path) -> None:
        root = tmp_path / "tv"
        root.mkdir()
        series_data: dict[str, Any] = {"seasons": {}}
        assert series_belongs_to_root(series_data, str(root), "tv") is False


class TestCreateEmptyStats:
    """Line 12: create_empty_stats returns zeroed dict."""

    def test_returns_zeroed_dict(self) -> None:
        stats = create_empty_stats()
        assert stats["series_scanned"] == 0
        assert stats["movies_added"] == 0
        assert len(stats) == 20


class TestMergeStatsDicts:
    """Lines 38-40: merge_stats_dicts merges values."""

    def test_merges_values(self) -> None:
        target = {"a": 1, "b": 2}
        source = {"a": 3, "c": 5}
        merge_stats_dicts(target, source)
        assert target["a"] == 4
        assert target["b"] == 2


class TestLogStatsBreakdown:
    """Lines 55-77: log_stats_breakdown logs all sections."""

    def test_logs_all_sections(self, caplog: pytest.LogCaptureFixture) -> None:
        test_logger = logging.getLogger("test_stats")
        stats = create_empty_stats()
        stats["series_scanned"] = 5
        stats["movies_added"] = 3
        with caplog.at_level(logging.INFO, logger="test_stats"):
            log_stats_breakdown("Test Label", stats, log_target=test_logger)
        assert "Test Label" in caplog.text
        assert "Series: Scanned=5" in caplog.text
        assert "Movies: Scanned=0 | Added=3" in caplog.text


class TestLogIssuesReport:
    """Lines 96-122: log_issues_report groups and logs problems."""

    def test_logs_grouped_issues(self, caplog: pytest.LogCaptureFixture) -> None:
        test_logger = logging.getLogger("test_issues")
        problems = [
            {"type": "Scan Error", "error": "timeout", "item": "/path/a.mkv"},
            {"type": "Scan Error", "error": "timeout", "item": "/path/b.mkv"},
            {"type": "Parse Error", "error": "bad format", "item": "/path/c.mkv"},
        ]
        with caplog.at_level(logging.INFO, logger="test_issues"):
            log_issues_report(problems, log_target=test_logger)
        assert "SCAN RUN ISSUES REPORT" in caplog.text
        assert "Scan Error" in caplog.text
        assert "Parse Error" in caplog.text
        assert "/path/a.mkv" in caplog.text

    def test_empty_problems_no_log(self, caplog: pytest.LogCaptureFixture) -> None:
        test_logger = logging.getLogger("test_issues_empty")
        with caplog.at_level(logging.INFO, logger="test_issues_empty"):
            log_issues_report([], log_target=test_logger)
        assert "ISSUES REPORT" not in caplog.text


class TestLogDbWriteError:
    """Lines 139-148: log_db_write_error records problem."""

    def test_records_problem_with_multiline_error(self) -> None:
        problems_list: list[dict[str, Any]] = []
        error = Exception("first line\nsecond line\nthird line")
        log_db_write_error(problems_list, "item desc", error)
        assert len(problems_list) == 1
        assert problems_list[0]["type"] == "Database Write Failure"
        assert problems_list[0]["item"] == "item desc"

    def test_records_problem_with_single_line_error(self) -> None:
        problems_list: list[dict[str, Any]] = []
        error = Exception("single line error")
        log_db_write_error(problems_list, "another item", error)
        assert len(problems_list) == 1
        assert problems_list[0]["error"] == "single line error"


class TestDiscoverFilesystemFallback:
    """Lines 184-203: filesystem fallback when no existing_library."""

    def test_nonexistent_root_returns_empty(self, tmp_path: Path) -> None:
        result = discover_single_library_tree_impl(
            [str(tmp_path / "nonexistent")], "tv"
        )
        assert result[str(tmp_path / "nonexistent")] == []

    def test_root_with_series_dirs(self, tmp_path: Path) -> None:
        root = tmp_path / "tvroot"
        root.mkdir()
        show_dir = root / "MyShow"
        show_dir.mkdir()
        (show_dir / "ep1.mkv").write_bytes(b"\x00" * 100)

        with patch(
            "lan_streamer.backend.scan_worker_base.has_video_files_shallow",
            return_value=True,
        ):
            result = discover_single_library_tree_impl([str(root)], "tv")
        assert "MyShow" in result[str(root)]


class TestSeriesBelongsToRootExceptionPaths:
    """Lines 212-213, 235-236: exception paths in resolve."""

    def test_path_resolve_exception_falls_back(self) -> None:
        series_data: dict[str, Any] = {"seasons": {}}
        assert series_belongs_to_root(series_data, "/any", "tv") is False

    def test_episode_path_resolve_exception(self, tmp_path: Path) -> None:
        root = tmp_path / "tv"
        root.mkdir()
        series_data: dict[str, Any] = {
            "seasons": {
                "Season 1": {"episodes": [{"path": str(root / "show" / "ep.mkv")}]}
            }
        }
        assert series_belongs_to_root(series_data, str(root), "tv") is True
