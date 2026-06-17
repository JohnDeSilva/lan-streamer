"""
Additional targeted coverage tests for progress_widgets.py.

Specifically covers:
- Line 108: SegmentedProgressBar.init_from_tree when raw root not in config paths
- Line 383: ScanProgressTree.init_from_tree when raw root not in config paths
- Lines 148–261: SegmentedProgressBar.paintEvent (called directly)
- Lines 672–788: LibraryScanProgressBar.paintEvent (called directly)
"""

from PySide6.QtGui import QPaintEvent
from PySide6.QtCore import QRect

from lan_streamer.ui_views.progress_widgets import (
    SegmentedProgressBar,
    ScanProgressTree,
    LibraryScanProgressBar,
)


# ---------------------------------------------------------------------------
# Line 108: raw root not in config paths (fallback append branch)
# ---------------------------------------------------------------------------


class TestRawRootFallbackBranch:
    """Line 108 fires when a raw root dir is present in the tree but absent
    from the config paths list.  It gets appended after the config-ordered paths."""

    def test_segmented_bar_raw_root_appended(self, qtbot) -> None:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        # Config only lists /r1, but tree also has /r2
        tree = {
            "TV": {
                "type": "tv",
                "roots": {
                    "/r1": {"ShowA": {}},
                    "/r2": {"ShowB": {}},  # NOT in config paths
                },
            }
        }
        config_source = {"TV": {"paths": ["/r1"]}}  # /r2 omitted
        bar.init_from_tree(tree, library_config_source=config_source)
        # /r2 must still be present (appended via the fallback on line 108)
        assert "/r2" in bar._libraries["TV"]["roots"]
        # And it must come after /r1
        roots_list = bar._libraries["TV"]["roots"]
        assert roots_list.index("/r1") < roots_list.index("/r2")

    def test_scan_tree_raw_root_appended(self, qtbot) -> None:
        widget = ScanProgressTree()
        qtbot.addWidget(widget)
        tree = {
            "TV": {
                "type": "tv",
                "roots": {
                    "/r1": {"ShowA": {"seasons": {}}},
                    "/r2": {"ShowB": {"seasons": {}}},  # NOT in config paths
                },
            }
        }
        config_source = {"TV": {"paths": ["/r1"]}}
        widget.init_from_tree(tree, library_config_source=config_source)
        # Both roots should have produced folder nodes
        keys = list(widget._folder_nodes.keys())
        assert any("/r1|ShowA" in k for k in keys)
        assert any("/r2|ShowB" in k for k in keys)


# ---------------------------------------------------------------------------
# SegmentedProgressBar.paintEvent  (lines 148–261)
# ---------------------------------------------------------------------------


def _fake_paint_event() -> QPaintEvent:
    return QPaintEvent(QRect(0, 0, 600, 60))


class TestSegmentedProgressBarPaintEventDirect:
    """Call paintEvent() directly to exercise every branch without relying on
    the offscreen Qt platform actually painting."""

    def _make_bar(self, qtbot) -> SegmentedProgressBar:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        bar.resize(600, 60)
        return bar

    def test_paint_no_libraries(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        bar.paintEvent(_fake_paint_event())  # Should hit early return at line 163

    def test_paint_pass1_pending(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        tree = {"TV": {"type": "tv", "roots": {"/r": {"S1": {}}}}}
        bar.init_from_tree(tree, library_config_source={"TV": {"paths": ["/r"]}})
        bar.set_current_pass(1)
        bar.paintEvent(_fake_paint_event())

    def test_paint_pass1_active_single_root(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        tree = {"TV": {"type": "tv", "roots": {"/r": {"S1": {}}}}}
        bar.init_from_tree(tree, library_config_source={"TV": {"paths": ["/r"]}})
        bar.set_current_pass(1)
        bar.mark_library_active("TV")
        bar.advance_root("/r")
        bar.paintEvent(_fake_paint_event())

    def test_paint_pass1_done(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        tree = {"TV": {"type": "tv", "roots": {"/r": {"S1": {}}}}}
        bar.init_from_tree(tree, library_config_source={"TV": {"paths": ["/r"]}})
        bar.set_current_pass(1)
        bar.mark_library_done("TV")
        bar.paintEvent(_fake_paint_event())

    def test_paint_pass2(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        tree = {"TV": {"type": "tv", "roots": {"/r": {"S1": {}}}}}
        bar.init_from_tree(tree, library_config_source={"TV": {"paths": ["/r"]}})
        bar.set_current_pass(2)
        bar.mark_library_active("TV")
        bar.paintEvent(_fake_paint_event())

    def test_paint_pass3_zero_fill(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        tree = {"TV": {"type": "tv", "roots": {"/r": {"S1": {}}}}}
        bar.init_from_tree(tree, library_config_source={"TV": {"paths": ["/r"]}})
        bar.set_pass3_progress(0, 100)
        bar.paintEvent(_fake_paint_event())

    def test_paint_pass3_nonzero_fill(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        tree = {"TV": {"type": "tv", "roots": {"/r": {"S1": {}}}}}
        bar.init_from_tree(tree, library_config_source={"TV": {"paths": ["/r"]}})
        bar.set_pass3_progress(50, 100)
        bar.paintEvent(_fake_paint_event())

    def test_paint_multiple_roots_pass1(self, qtbot) -> None:
        """Multiple roots → draws root divider lines (ridx > 0 branch)."""
        bar = self._make_bar(qtbot)
        tree = {
            "TV": {
                "type": "tv",
                "roots": {
                    "/r1": {"S1": {}, "S2": {}},
                    "/r2": {"S3": {}},
                },
            }
        }
        bar.init_from_tree(
            tree, library_config_source={"TV": {"paths": ["/r1", "/r2"]}}
        )
        bar.set_current_pass(1)
        bar.mark_library_active("TV")
        bar.advance_root("/r1")
        bar.paintEvent(_fake_paint_event())

    def test_paint_root_done_inside_active_library(self, qtbot) -> None:
        """Line 218: root_state == STATE_DONE while library is STATE_ACTIVE."""
        bar = self._make_bar(qtbot)
        tree = {
            "TV": {
                "type": "tv",
                "roots": {
                    "/r1": {"S1": {}, "S2": {}},
                    "/r2": {"S3": {}},
                },
            }
        }
        bar.init_from_tree(
            tree, library_config_source={"TV": {"paths": ["/r1", "/r2"]}}
        )
        bar.set_current_pass(1)
        bar.mark_library_active("TV")
        # Mark the second root (r2) as DONE at the root_states level
        bar._root_states["/r2"] = SegmentedProgressBar.STATE_DONE
        bar.paintEvent(_fake_paint_event())

    def test_paint_multiple_libraries_separator(self, qtbot) -> None:
        """Multiple libraries → draws library separator line (idx > 0 branch)."""
        bar = self._make_bar(qtbot)
        tree = {
            "TV": {"type": "tv", "roots": {"/r1": {"S1": {}}}},
            "Movies": {"type": "movie", "roots": {"/m": {}}},
        }
        bar.init_from_tree(
            tree,
            library_config_source={
                "TV": {"paths": ["/r1"]},
                "Movies": {"paths": ["/m"]},
            },
        )
        bar.paintEvent(_fake_paint_event())


# ---------------------------------------------------------------------------
# LibraryScanProgressBar.paintEvent  (lines 672–788)
# ---------------------------------------------------------------------------


def _fake_lib_paint_event() -> QPaintEvent:
    return QPaintEvent(QRect(0, 0, 600, 20))


class TestLibraryScanProgressBarPaintEventDirect:
    def _make_bar(self, qtbot) -> LibraryScanProgressBar:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        bar.resize(600, 20)
        return bar

    def test_paint_no_roots(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        bar.paintEvent(_fake_lib_paint_event())  # early return at line 684

    def test_paint_pass1_pending(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        bar.init_from_roots({"/r": ["S1", "S2"]}, ["/r"])
        bar.set_current_pass(1)
        bar.paintEvent(_fake_lib_paint_event())

    def test_paint_pass1_active(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        bar.init_from_roots({"/r": ["S1", "S2"]}, ["/r"])
        bar.mark_folder_active("/r", "S1")
        bar.paintEvent(_fake_lib_paint_event())

    def test_paint_pass1_done(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        bar.init_from_roots({"/r": ["S1"]}, ["/r"])
        bar.mark_folder_active("/r", "S1")
        bar.mark_folder_done("/r", "S1")
        bar.paintEvent(_fake_lib_paint_event())

    def test_paint_pass2(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        bar.init_from_roots({"/r": ["S1"]}, ["/r"])
        bar.set_current_pass(2)
        bar.mark_folder_active("/r", "S1")
        bar.paintEvent(_fake_lib_paint_event())

    def test_paint_pass3_zero_fill(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        bar.init_from_roots({"/r": ["S1"]}, ["/r"])
        bar.set_pass3_progress(0, 100)
        bar.paintEvent(_fake_lib_paint_event())

    def test_paint_pass3_nonzero_fill(self, qtbot) -> None:
        bar = self._make_bar(qtbot)
        bar.init_from_roots({"/r": ["S1"]}, ["/r"])
        bar.set_pass3_progress(60, 100)
        bar.paintEvent(_fake_lib_paint_event())

    def test_paint_multiple_folders_mixed_states(self, qtbot) -> None:
        """Exercises the ordered_states construction (DONE, ACTIVE, PENDING)."""
        bar = self._make_bar(qtbot)
        bar.init_from_roots({"/r": ["F1", "F2", "F3", "F4"]}, ["/r"])
        bar.mark_folder_active("/r", "F1")
        bar.mark_folder_done("/r", "F1")
        bar.mark_folder_active("/r", "F2")
        bar.paintEvent(_fake_lib_paint_event())  # F1=DONE, F2=ACTIVE, F3/F4=PENDING

    def test_paint_multiple_folders_pass3_with_dividers(self, qtbot) -> None:
        """Pass 3 with multiple folders → draws folder divider lines (fidx > 0)."""
        bar = self._make_bar(qtbot)
        bar.init_from_roots({"/r": ["F1", "F2", "F3"]}, ["/r"])
        bar.set_pass3_progress(50, 100)
        bar.paintEvent(_fake_lib_paint_event())

    def test_paint_multiple_roots_separator(self, qtbot) -> None:
        """Multiple roots → draws root separator line (idx > 0 branch)."""
        bar = self._make_bar(qtbot)
        bar.init_from_roots({"/r1": ["S1", "S2"], "/r2": ["M1"]}, ["/r1", "/r2"])
        bar.mark_folder_active("/r1", "S1")
        bar.paintEvent(_fake_lib_paint_event())

    def test_paint_all_roots_done_state(self, qtbot) -> None:
        """When root state=DONE, folder sub-rects should be painted with color_done."""
        bar = self._make_bar(qtbot)
        bar.init_from_roots({"/r": ["S1", "S2"]}, ["/r"])
        bar.mark_folder_active("/r", "S1")
        bar.mark_folder_done("/r", "S1")
        bar.mark_folder_done("/r", "S2")
        # root is now STATE_DONE
        bar.paintEvent(_fake_lib_paint_event())
