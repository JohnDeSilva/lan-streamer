"""Direct unit tests for shared helpers in scan_worker_base.py."""

import logging
from unittest.mock import patch


class TestCreateEmptyStats:
    def test_returns_all_keys_zeroed(self) -> None:
        from lan_streamer.backend.scan_worker_base import create_empty_stats

        stats = create_empty_stats()
        expected_keys = {
            "series_scanned",
            "series_added",
            "series_updated",
            "series_removed",
            "series_skipped",
            "seasons_scanned",
            "seasons_added",
            "seasons_updated",
            "seasons_removed",
            "seasons_skipped",
            "episodes_scanned",
            "episodes_added",
            "episodes_updated",
            "episodes_removed",
            "episodes_skipped",
            "movies_scanned",
            "movies_added",
            "movies_updated",
            "movies_removed",
            "movies_skipped",
        }
        assert set(stats.keys()) == expected_keys
        assert all(v == 0 for v in stats.values())

    def test_returns_new_dict_each_call(self) -> None:
        from lan_streamer.backend.scan_worker_base import create_empty_stats

        a = create_empty_stats()
        b = create_empty_stats()
        assert a is not b
        a["series_scanned"] = 5
        assert b["series_scanned"] == 0


class TestMergeStatsDicts:
    def test_in_place_merge(self) -> None:
        from lan_streamer.backend.scan_worker_base import merge_stats_dicts

        target = {"a": 1, "b": 2}
        source = {"a": 3, "b": 4}
        merge_stats_dicts(target, source)
        assert target == {"a": 4, "b": 6}

    def test_source_keys_not_in_target_ignored(self) -> None:
        from lan_streamer.backend.scan_worker_base import merge_stats_dicts

        target = {"a": 1}
        source = {"a": 2, "missing_key": 99}
        merge_stats_dicts(target, source)
        assert target == {"a": 3}
        assert "missing_key" not in target

    def test_empty_source_no_change(self) -> None:
        from lan_streamer.backend.scan_worker_base import merge_stats_dicts

        target = {"a": 1}
        merge_stats_dicts(target, {})
        assert target == {"a": 1}

    def test_empty_target_gets_source_values(self) -> None:
        from lan_streamer.backend.scan_worker_base import merge_stats_dicts

        target = {"a": 0, "b": 0}
        source = {"a": 5, "b": 3}
        merge_stats_dicts(target, source)
        assert target == {"a": 5, "b": 3}


class TestMergeStatsDictsForReport:
    def test_merges_disjoint_keys(self) -> None:
        from lan_streamer.backend.scan_worker_base import merge_stats_dicts_for_report

        result = merge_stats_dicts_for_report({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_sums_overlapping_keys(self) -> None:
        from lan_streamer.backend.scan_worker_base import merge_stats_dicts_for_report

        result = merge_stats_dicts_for_report({"a": 3, "b": 1}, {"a": 2, "c": 4})
        assert result == {"a": 5, "b": 1, "c": 4}

    def test_does_not_mutate_inputs(self) -> None:
        from lan_streamer.backend.scan_worker_base import merge_stats_dicts_for_report

        a = {"x": 1}
        b = {"x": 2}
        result = merge_stats_dicts_for_report(a, b)
        assert a == {"x": 1}
        assert b == {"x": 2}
        assert result == {"x": 3}

    def test_empty_first_dict(self) -> None:
        from lan_streamer.backend.scan_worker_base import merge_stats_dicts_for_report

        result = merge_stats_dicts_for_report({}, {"a": 5})
        assert result == {"a": 5}

    def test_empty_second_dict(self) -> None:
        from lan_streamer.backend.scan_worker_base import merge_stats_dicts_for_report

        result = merge_stats_dicts_for_report({"a": 5}, {})
        assert result == {"a": 5}

    def test_both_empty(self) -> None:
        from lan_streamer.backend.scan_worker_base import merge_stats_dicts_for_report

        result = merge_stats_dicts_for_report({}, {})
        assert result == {}


class TestLogStatsBreakdown:
    def test_logs_all_sections(self) -> None:
        from lan_streamer.backend.scan_worker_base import log_stats_breakdown

        stats = {
            "series_scanned": 1,
            "series_added": 2,
            "series_updated": 3,
            "series_removed": 4,
            "series_skipped": 5,
            "seasons_scanned": 6,
            "seasons_added": 7,
            "seasons_updated": 8,
            "seasons_removed": 9,
            "seasons_skipped": 10,
            "episodes_scanned": 11,
            "episodes_added": 12,
            "episodes_updated": 13,
            "episodes_removed": 14,
            "episodes_skipped": 15,
            "movies_scanned": 16,
            "movies_added": 17,
            "movies_updated": 18,
            "movies_removed": 19,
            "movies_skipped": 20,
        }

        mock_target = logging.getLogger("test_logger")
        with patch.object(mock_target, "info") as mock_info:
            log_stats_breakdown("TEST LABEL", stats, mock_target)

        logged = [call.args[0] for call in mock_info.call_args_list]
        assert "[SCAN_REPORT] TEST LABEL" in logged
        assert (
            "[SCAN_REPORT]   Series: Scanned=1 | Added=2 | Updated=3 | Removed=4 | Skipped=5"
            in logged
        )
        assert (
            "[SCAN_REPORT]   Seasons: Scanned=6 | Added=7 | Updated=8 | Removed=9 | Skipped=10"
            in logged
        )
        assert (
            "[SCAN_REPORT]   Episodes: Scanned=11 | Added=12 | Updated=13 | Removed=14 | Skipped=15"
            in logged
        )
        assert (
            "[SCAN_REPORT]   Movies: Scanned=16 | Added=17 | Updated=18 | Removed=19 | Skipped=20"
            in logged
        )

    def test_empty_stats_dict_defaults_to_zero(self) -> None:
        from lan_streamer.backend.scan_worker_base import log_stats_breakdown

        mock_target = logging.getLogger("test_logger")
        with patch.object(mock_target, "info") as mock_info:
            log_stats_breakdown("EMPTY", {}, mock_target)

        logged = [call.args[0] for call in mock_info.call_args_list]
        assert "Scanned=0 | Added=0 | Updated=0 | Removed=0 | Skipped=0" in logged[1]


class TestLogIssuesReport:
    def test_empty_problems_no_output(self) -> None:
        from lan_streamer.backend.scan_worker_base import log_issues_report

        mock_target = logging.getLogger("test_logger")
        with patch.object(mock_target, "info") as mock_info:
            log_issues_report([], mock_target)

        mock_info.assert_not_called()

    def test_groups_by_type_and_error(self) -> None:
        from lan_streamer.backend.scan_worker_base import log_issues_report

        problems = [
            {"type": "Type A", "error": "Error X", "item": "Item 1"},
            {"type": "Type A", "error": "Error X", "item": "Item 2"},
            {"type": "Type A", "error": "Error Y", "item": "Item 3"},
            {"type": "Type B", "error": "Error Z", "item": "Item 4"},
        ]
        mock_target = logging.getLogger("test_logger")
        with patch.object(mock_target, "info") as mock_info:
            log_issues_report(problems, mock_target)

        logged = [call.args[0] for call in mock_info.call_args_list]
        assert "[SCAN_REPORT]               SCAN RUN ISSUES REPORT" in logged
        assert "[SCAN_REPORT] Type: Type A" in logged
        assert "[SCAN_REPORT] Type: Type B" in logged
        assert "[SCAN_REPORT]   Error: Error X" in logged
        assert "[SCAN_REPORT]   Error: Error Y" in logged
        assert "[SCAN_REPORT]   Error: Error Z" in logged
        assert "[SCAN_REPORT]     - Item 1" in logged
        assert "[SCAN_REPORT]     - Item 2" in logged
        assert "[SCAN_REPORT]     - Item 3" in logged
        assert "[SCAN_REPORT]     - Item 4" in logged

    def test_custom_log_target(self) -> None:
        """Verify log_issues_report uses the provided log_target."""
        from lan_streamer.backend.scan_worker_base import log_issues_report

        problems = [{"type": "X", "error": "Y", "item": "Z"}]
        mock_target = logging.getLogger("custom")

        with patch.object(mock_target, "info") as mock_info:
            log_issues_report(problems, mock_target)

        mock_info.assert_called()


class TestLogDbWriteError:
    def test_single_line_error_no_debug(self) -> None:
        from lan_streamer.backend.scan_worker_base import log_db_write_error

        problems: list = []
        mock_target = logging.getLogger("test_logger")
        with patch.object(mock_target, "info") as mock_info:
            with patch.object(mock_target, "warning") as mock_warning:
                with patch.object(mock_target, "debug") as mock_debug:
                    log_db_write_error(
                        problems, "Item X", Exception("Simple error"), mock_target
                    )

        mock_debug.assert_not_called()
        mock_warning.assert_called_once()
        assert "Simple error" in mock_warning.call_args[0][0]
        assert mock_info.call_count == 0
        assert len(problems) == 1
        assert problems[0]["type"] == "Database Write Failure"
        assert problems[0]["item"] == "Item X"
        assert problems[0]["error"] == "Simple error"

    def test_multiline_error_logs_debug(self) -> None:
        from lan_streamer.backend.scan_worker_base import log_db_write_error

        problems: list = []
        mock_target = logging.getLogger("test_logger")
        with patch.object(mock_target, "debug") as mock_debug:
            with patch.object(mock_target, "warning") as mock_warning:
                log_db_write_error(
                    problems,
                    "Item Y",
                    RuntimeError("First line\nSecond line\nThird line"),
                    mock_target,
                )

        mock_debug.assert_called_once()
        assert "detailed error" in mock_debug.call_args[0][0]
        mock_warning.assert_called_once()
        assert "First line" in mock_warning.call_args[0][0]
        assert "Second line" not in mock_warning.call_args[0][0]
        assert len(problems) == 1
        assert problems[0]["error"] == "First line"

    def test_uses_default_logger(self) -> None:
        from lan_streamer.backend.scan_worker_base import log_db_write_error, logger

        original = logger.warning
        called = False

        def _fake_warning(msg: str, *args, **kwargs) -> None:
            nonlocal called
            called = True

        logger.warning = _fake_warning
        try:
            log_db_write_error([], "Test", Exception("err"))
            assert called
        finally:
            logger.warning = original


class TestDiscoverSingleLibraryTreeImpl:
    def test_hidden_directories_excluded(self, tmp_path) -> None:
        from lan_streamer.backend.scan_worker_base import (
            discover_single_library_tree_impl,
        )

        root = tmp_path / "root"
        root.mkdir()
        (root / ".hidden_series").mkdir()
        (root / ".hidden_series" / "ep.mkv").write_bytes(b"\x00")
        (root / "Visible Show").mkdir()
        (root / "Visible Show" / "ep.mkv").write_bytes(b"\x00")

        result = discover_single_library_tree_impl([str(root)], "tv")
        assert ".hidden_series" not in result[str(root)]
        assert "Visible Show" in result[str(root)]

    def test_directories_without_video_excluded(self, tmp_path) -> None:
        from lan_streamer.backend.scan_worker_base import (
            discover_single_library_tree_impl,
        )

        root = tmp_path / "root"
        root.mkdir()
        (root / "No Video").mkdir()
        (root / "No Video" / "readme.txt").write_bytes(b"hello")
        (root / "Has Video").mkdir()
        (root / "Has Video" / "movie.mp4").write_bytes(b"\x00")

        result = discover_single_library_tree_impl([str(root)], "tv")
        assert "No Video" not in result[str(root)]
        assert "Has Video" in result[str(root)]

    def test_multiple_root_directories(self, tmp_path) -> None:
        from lan_streamer.backend.scan_worker_base import (
            discover_single_library_tree_impl,
        )

        root1 = tmp_path / "tv_shows"
        root1.mkdir()
        (root1 / "Show A").mkdir()
        (root1 / "Show A" / "ep.mkv").write_bytes(b"\x00")

        root2 = tmp_path / "more_tv"
        root2.mkdir()
        (root2 / "Show B").mkdir()
        (root2 / "Show B" / "ep.mkv").write_bytes(b"\x00")

        result = discover_single_library_tree_impl([str(root1), str(root2)], "tv")
        assert str(root1) in result
        assert str(root2) in result
        assert "Show A" in result[str(root1)]
        assert "Show B" in result[str(root2)]

    def test_mixed_existing_and_nonexistent_roots(self, tmp_path) -> None:
        from lan_streamer.backend.scan_worker_base import (
            discover_single_library_tree_impl,
        )

        existing_root = tmp_path / "existing"
        existing_root.mkdir()
        (existing_root / "Series X").mkdir()
        (existing_root / "Series X" / "ep.mkv").write_bytes(b"\x00")

        result = discover_single_library_tree_impl(
            [str(existing_root), "/nonexistent/xyz"], "tv"
        )
        assert str(existing_root) in result
        assert "Series X" in result[str(existing_root)]
        assert "/nonexistent/xyz" in result
        assert result["/nonexistent/xyz"] == []
