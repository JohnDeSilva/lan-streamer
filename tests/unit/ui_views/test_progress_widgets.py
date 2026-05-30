from PySide6.QtCore import Qt
from lan_streamer.ui_views.progress_widgets import SegmentedProgressBar, ScanProgressTree
from lan_streamer.system.config import config

def test_segmented_progress_bar_ordering(qtbot):
    bar = SegmentedProgressBar()
    qtbot.addWidget(bar)
    
    tree = {
        "Anime": {
            "type": "tv",
            "roots": {
                "/storage/anime": {}
            }
        },
        "tv": {
            "type": "tv",
            "roots": {
                "/storage/tv1": {},
                "/storage/tv2": {}
            }
        }
    }
    
    # Test ordering with explicit library_order
    library_order = ["tv", "Anime"]
    config_source = {
        "tv": {"paths": ["/storage/tv1", "/storage/tv2"]},
        "Anime": {"paths": ["/storage/anime"]}
    }
    
    bar.init_from_tree(tree, library_order=library_order, library_config_source=config_source)
    assert bar._library_order == ["tv", "Anime"]
    assert bar._libraries["tv"]["roots"] == ["/storage/tv1", "/storage/tv2"]
    
    # Test root directory ordering
    # Say config_source lists tv2 before tv1
    config_source_rev = {
        "tv": {"paths": ["/storage/tv2", "/storage/tv1"]},
        "Anime": {"paths": ["/storage/anime"]}
    }
    bar.init_from_tree(tree, library_order=library_order, library_config_source=config_source_rev)
    assert bar._libraries["tv"]["roots"] == ["/storage/tv2", "/storage/tv1"]


def test_scan_progress_tree_ordering(qtbot):
    tree_widget = ScanProgressTree()
    qtbot.addWidget(tree_widget)
    
    tree = {
        "Anime": {
            "type": "tv",
            "roots": {
                "/storage/anime": {}
            }
        },
        "tv": {
            "type": "tv",
            "roots": {
                "/storage/tv1": {},
                "/storage/tv2": {}
            }
        }
    }
    
    library_order = ["tv", "Anime"]
    config_source = {
        "tv": {"paths": ["/storage/tv2", "/storage/tv1"]},
        "Anime": {"paths": ["/storage/anime"]}
    }
    
    tree_widget.init_from_tree(tree, library_order=library_order, library_config_source=config_source)
    assert tree_widget._library_order == ["tv", "Anime"]
    
    # Verify that the root items under TV are in the config order: tv2 first, then tv1
    tv_item = tree_widget._lib_nodes["tv"]
    assert tv_item.childCount() == 2
    assert tv_item.child(0).data(0, Qt.ItemDataRole.UserRole) == "/storage/tv2"
    assert tv_item.child(1).data(0, Qt.ItemDataRole.UserRole) == "/storage/tv1"
