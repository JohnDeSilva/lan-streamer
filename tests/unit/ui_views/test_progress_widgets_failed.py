from PySide6.QtCore import QRect
from PySide6.QtGui import QPaintEvent
from lan_streamer.ui_views.progress_widgets import (
    SegmentedProgressBar,
    ScanProgressTree,
)


def _fake_paint_event() -> QPaintEvent:
    return QPaintEvent(QRect(0, 0, 600, 60))


def test_segmented_progress_bar_failed_state(qtbot) -> None:
    bar = SegmentedProgressBar()
    qtbot.addWidget(bar)
    bar.resize(600, 60)

    tree = {"TV": {"type": "tv", "roots": {"/r": {"S1": {}}}}}
    bar.init_from_tree(tree, library_config_source={"TV": {"paths": ["/r"]}})
    bar.set_current_pass(1)

    # Initially pending
    assert bar._libraries["TV"]["state"] == SegmentedProgressBar.STATE_PENDING

    # Transition to failed
    bar.mark_library_failed("TV")
    assert bar._libraries["TV"]["state"] == SegmentedProgressBar.STATE_FAILED
    assert bar._root_states["/r"] == SegmentedProgressBar.STATE_FAILED

    # Paint event should execute without error
    bar.paintEvent(_fake_paint_event())


def test_scan_progress_tree_failed_state(qtbot) -> None:
    tree_widget = ScanProgressTree()
    qtbot.addWidget(tree_widget)

    tree = {
        "TV": {
            "type": "tv",
            "roots": {"/r": {"ShowA": {"seasons": {"Season 1": ["ep1.mp4"]}}}},
        }
    }
    tree_widget.init_from_tree(
        tree, library_order=["TV"], library_config_source={"TV": {"paths": ["/r"]}}
    )

    # Initial state
    tv_item = tree_widget._lib_nodes["TV"]
    assert "⏳" in tv_item.text(0)

    # Transition to failed
    tree_widget.mark_library_failed("TV")
    assert "✗" in tv_item.text(0)
    assert tv_item.foreground(0).color().name() == "#ef4444"
