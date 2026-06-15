"""
Comprehensive tests for ui_views/progress_widgets.py covering:
 - SegmentedProgressBar: mark_library_active, mark_library_done, advance_root, paintEvent
 - ScanProgressTree: mark_library_active/done, mark_folder_active/done,
   mark_season_active/done, mark_file_active/done, reset, expand/collapse slots,
   init_from_tree with movie library type
 - LibraryScanProgressBar: init_from_roots, mark_folder_active, mark_folder_done, paintEvent
"""

from lan_streamer.ui_views.progress_widgets import (
    SegmentedProgressBar,
    ScanProgressTree,
    LibraryScanProgressBar,
)


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _tv_tree():
    """Minimal TV-library pre-discovery tree."""
    return {
        "Shows": {
            "type": "tv",
            "roots": {
                "/shows": {
                    "My Show": {
                        "seasons": {
                            "Season 1": ["S01E01.mkv", "S01E02.mkv"],
                            "Season 2": ["S02E01.mkv"],
                        }
                    },
                    "Another Show": {"seasons": {}},
                }
            },
        }
    }


def _movie_tree():
    """Minimal movie-library pre-discovery tree."""
    return {
        "Movies": {
            "type": "movie",
            "roots": {
                "/movies": {
                    "Avatar (2009)": {},
                    "Inception (2010)": {},
                }
            },
        }
    }


_config_source = {
    "Shows": {"paths": ["/shows"]},
    "Movies": {"paths": ["/movies"]},
}


# ===========================================================================
# SegmentedProgressBar
# ===========================================================================


class TestSegmentedProgressBar:
    def test_init_empty(self, qtbot) -> None:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        assert bar._library_order == []
        assert bar._libraries == {}

    def test_init_from_tree_sets_state_pending(self, qtbot) -> None:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        tree = {
            "Shows": {"type": "tv", "roots": {"/shows": {"Folder": {}}}},
        }
        bar.init_from_tree(tree, library_config_source={"Shows": {"paths": ["/shows"]}})
        assert bar._library_order == ["Shows"]
        assert bar._libraries["Shows"]["state"] == SegmentedProgressBar.STATE_PENDING
        assert "/shows" in bar._root_states
        assert bar._root_states["/shows"] == SegmentedProgressBar.STATE_PENDING

    def test_mark_library_active(self, qtbot) -> None:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        bar.init_from_tree(
            {"Shows": {"type": "tv", "roots": {"/shows": {}}}},
            library_config_source={"Shows": {"paths": ["/shows"]}},
        )
        bar.mark_library_active("Shows")
        assert bar._libraries["Shows"]["state"] == SegmentedProgressBar.STATE_ACTIVE

    def test_mark_library_active_nonexistent(self, qtbot) -> None:
        """Should not crash for unknown library."""
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        bar.mark_library_active("Nonexistent")  # should not raise

    def test_mark_library_done(self, qtbot) -> None:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        bar.init_from_tree(
            {"Shows": {"type": "tv", "roots": {"/shows": {}}}},
            library_config_source={"Shows": {"paths": ["/shows"]}},
        )
        bar.mark_library_done("Shows")
        assert bar._libraries["Shows"]["state"] == SegmentedProgressBar.STATE_DONE
        assert bar._root_states["/shows"] == SegmentedProgressBar.STATE_DONE

    def test_advance_root_increments_counter(self, qtbot) -> None:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        tree = {
            "Shows": {
                "type": "tv",
                "roots": {"/shows": {"ShowA": {}, "ShowB": {}}},
            }
        }
        bar.init_from_tree(tree, library_config_source={"Shows": {"paths": ["/shows"]}})
        bar.mark_library_active("Shows")
        bar.advance_root("/shows")
        assert bar._libraries["Shows"]["root_done"]["/shows"] == 1

    def test_advance_root_clamped_to_total(self, qtbot) -> None:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        tree = {"Shows": {"type": "tv", "roots": {"/shows": {"S": {}}}}}
        bar.init_from_tree(tree, library_config_source={"Shows": {"paths": ["/shows"]}})
        bar.mark_library_active("Shows")
        # Advance many times beyond total
        for _ in range(10):
            bar.advance_root("/shows")
        # Should be clamped at total (1 folder)
        assert bar._libraries["Shows"]["root_done"]["/shows"] <= 1

    def test_advance_root_nonexistent(self, qtbot) -> None:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        bar.advance_root("/no/such/root")  # should not crash

    def test_paint_event_empty(self, qtbot) -> None:
        """paintEvent with empty library order should not crash."""
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        bar.resize(400, 60)
        bar.show()
        bar.repaint()

    def test_paint_event_with_libraries(self, qtbot) -> None:
        """paintEvent should not crash with real library data and all states."""
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        tree = {
            "Shows": {
                "type": "tv",
                "roots": {"/shows1": {"A": {}, "B": {}}, "/shows2": {"C": {}}},
            },
            "Movies": {
                "type": "movie",
                "roots": {"/movies": {}},
            },
        }
        bar.init_from_tree(
            tree,
            library_config_source={
                "Shows": {"paths": ["/shows1", "/shows2"]},
                "Movies": {"paths": ["/movies"]},
            },
        )
        bar.mark_library_active("Shows")
        bar.advance_root("/shows1")
        bar.mark_library_done("Movies")
        bar.resize(600, 60)
        bar.show()
        bar.repaint()  # Should not raise

    def test_init_uses_config_when_no_source(self, qtbot) -> None:
        """When no library_config_source passed, should read from config."""
        from lan_streamer.system.config import config

        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        tree = {"TestLib": {"type": "tv", "roots": {"/testroot": {}}}}
        config.libraries = {"TestLib": {"paths": ["/testroot"]}}
        try:
            bar.init_from_tree(tree)  # No library_config_source
            assert "TestLib" in bar._libraries
        finally:
            config.libraries = {}

    def test_set_pass3_progress_zero_total(self, qtbot) -> None:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        bar.set_pass3_progress(0, 0)
        assert bar._pass3_fraction == 1.0

    def test_paint_event_passes(self, qtbot) -> None:
        bar = SegmentedProgressBar()
        qtbot.addWidget(bar)
        tree = {
            "Shows": {
                "type": "tv",
                "roots": {"/shows1": {"A": {}}},
            }
        }
        bar.init_from_tree(
            tree, library_config_source={"Shows": {"paths": ["/shows1"]}}
        )
        bar.mark_library_active("Shows")
        bar.resize(400, 60)
        bar.show()

        # Pass 1
        bar.repaint()

        # Pass 2
        bar.set_current_pass(2)
        bar.repaint()

        # Pass 3
        bar.set_pass3_progress(1, 2)
        bar.repaint()


# ===========================================================================
# ScanProgressTree
# ===========================================================================


class TestScanProgressTree:
    def test_init_creates_lib_nodes(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        assert "Shows" in w._lib_nodes

    def test_init_movie_library_no_seasons_created(self, qtbot) -> None:
        """Movie libraries should not create season nodes."""
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_movie_tree(), library_config_source=_config_source)
        assert "Movies" in w._lib_nodes
        # No season nodes should be created for movie libraries
        assert len(w._season_nodes) == 0

    def test_init_tv_library_creates_seasons(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        # Season 1 and Season 2 nodes should exist for My Show
        keys = list(w._season_nodes.keys())
        assert any("Season 1" in k for k in keys)
        assert any("Season 2" in k for k in keys)

    def test_init_tv_library_creates_file_nodes(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        file_paths = list(w._file_nodes.keys())
        assert any("S01E01.mkv" in p for p in file_paths)
        assert any("S02E01.mkv" in p for p in file_paths)

    def test_mark_library_active(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.mark_library_active("Shows")
        node = w._lib_nodes["Shows"]
        assert ScanProgressTree._ICON_PROCESSING in node.text(0)

    def test_mark_library_done(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.mark_library_done("Shows")
        node = w._lib_nodes["Shows"]
        assert ScanProgressTree._ICON_DONE in node.text(0)

    def test_mark_library_active_nonexistent(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.mark_library_active("Nonexistent")  # should not crash

    def test_mark_folder_active(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.mark_folder_active("Shows", "/shows", "My Show")
        key = w._folder_key("Shows", "/shows", "My Show")
        node = w._folder_nodes[key]
        assert ScanProgressTree._ICON_PROCESSING in node.text(0)

    def test_mark_folder_done(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.mark_folder_done("Shows", "/shows", "My Show", skipped=False)
        key = w._folder_key("Shows", "/shows", "My Show")
        node = w._folder_nodes[key]
        assert ScanProgressTree._ICON_DONE in node.text(0)

    def test_mark_folder_done_skipped(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.mark_folder_done("Shows", "/shows", "My Show", skipped=True)
        key = w._folder_key("Shows", "/shows", "My Show")
        node = w._folder_nodes[key]
        assert ScanProgressTree._ICON_SKIPPED in node.text(0)

    def test_mark_folder_active_nonexistent(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.mark_folder_active("NonLib", "/root", "NonFolder")  # should not crash

    def test_mark_season_active_existing_node(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.mark_season_active("Shows", "My Show", "Season 1")
        key = w._season_key("Shows", "My Show", "Season 1")
        node = w._season_nodes.get(key)
        assert node is not None
        assert ScanProgressTree._ICON_PROCESSING in node.text(0)

    def test_mark_season_active_creates_new_node(self, qtbot) -> None:
        """When season node doesn't exist, it should be created dynamically."""
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        # Mark "Season 3" which doesn't exist in the initial tree
        w.mark_season_active("Shows", "My Show", "Season 3")
        key = w._season_key("Shows", "My Show", "Season 3")
        assert key in w._season_nodes

    def test_mark_season_active_no_parent_folder(self, qtbot) -> None:
        """When parent folder doesn't exist, mark_season_active should not crash."""
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.mark_season_active("Shows", "NonExistentFolder", "Season 1")  # no-op

    def test_mark_season_done(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.mark_season_done("Shows", "My Show", "Season 1")
        key = w._season_key("Shows", "My Show", "Season 1")
        node = w._season_nodes.get(key)
        assert node is not None
        assert ScanProgressTree._ICON_DONE in node.text(0)

    def test_mark_season_done_nonexistent(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.mark_season_done("Shows", "NonExist", "Season 99")  # should not crash

    def test_mark_file_active_updates_existing_node(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        ep_path = "/shows/My Show/Season 1/S01E01.mkv"
        w.mark_file_active(ep_path, "Shows", "My Show", "Season 1")
        node = w._file_nodes.get(ep_path)
        assert node is not None
        assert ScanProgressTree._ICON_PROCESSING in node.text(0)

    def test_mark_file_active_creates_new_node(self, qtbot) -> None:
        """For a new episode file not pre-populated, it should create a node."""
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        new_ep_path = "/shows/My Show/Season 1/S01E99.mkv"
        w.mark_file_active(new_ep_path, "Shows", "My Show", "Season 1")
        assert new_ep_path in w._file_nodes

    def test_mark_file_active_movie_library_is_noop(self, qtbot) -> None:
        """Movie libraries should not create file nodes."""
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_movie_tree(), library_config_source=_config_source)
        w.mark_file_active(
            "/movies/Avatar (2009)/avatar.mkv", "Movies", "Avatar (2009)"
        )
        # No file node should be created for movie library
        assert "/movies/Avatar (2009)/avatar.mkv" not in w._file_nodes

    def test_mark_file_done(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        ep_path = "/shows/My Show/Season 1/S01E01.mkv"
        w.mark_file_active(ep_path, "Shows", "My Show", "Season 1")
        w.mark_file_done(ep_path)
        node = w._file_nodes.get(ep_path)
        assert ScanProgressTree._ICON_DONE in node.text(0)

    def test_mark_file_done_nonexistent(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.mark_file_done("/nonexistent/path.mkv")  # should not crash

    def test_reset_clears_all(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.reset()
        assert len(w._lib_nodes) == 0
        assert len(w._folder_nodes) == 0
        assert len(w._season_nodes) == 0
        assert len(w._file_nodes) == 0

    def test_expand_all(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.show()
        w._on_expand_all()  # Should not crash

    def test_collapse_all(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.show()
        w._on_collapse_all()  # Should not crash

    def test_init_uses_config_when_no_source(self, qtbot) -> None:
        from lan_streamer.system.config import config

        w = ScanProgressTree()
        qtbot.addWidget(w)
        tree = {"TestLib": {"type": "tv", "roots": {"/testroot": {}}}}
        config.libraries = {"TestLib": {"paths": ["/testroot"]}}
        try:
            w.init_from_tree(tree)  # No library_config_source
            assert "TestLib" in w._lib_nodes
        finally:
            config.libraries = {}

    def test_mark_file_active_no_season_fallback_to_folder(self, qtbot) -> None:
        """When season='' mark_file_active should fall back to folder node."""
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        new_ep_path = "/shows/My Show/loose_ep.mkv"
        # No season given → should attach to folder node
        w.mark_file_active(new_ep_path, "Shows", "My Show", season="")
        assert new_ep_path in w._file_nodes

    def test_mark_file_active_no_parent(self, qtbot) -> None:
        w = ScanProgressTree()
        qtbot.addWidget(w)
        w.init_from_tree(_tv_tree(), library_config_source=_config_source)
        w.mark_file_active(
            "/shows/My Show/Season 1/nonexistent_file.mkv",
            "NonexistentLib",
            "NonexistentFolder",
            "Season 1",
        )
        assert "/shows/My Show/Season 1/nonexistent_file.mkv" not in w._file_nodes


# ===========================================================================
# LibraryScanProgressBar
# ===========================================================================


class TestLibraryScanProgressBar:
    def test_init_empty(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        assert bar._roots_order == []
        assert bar._roots == {}

    def test_init_from_roots(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        roots = {
            "/tv": ["ShowA", "ShowB"],
            "/movies": ["Movie1"],
        }
        bar.init_from_roots(roots, roots_order=["/tv", "/movies"])
        assert bar._roots_order == ["/tv", "/movies"]
        assert "/tv" in bar._roots
        assert bar._roots["/tv"]["state"] == LibraryScanProgressBar.STATE_PENDING

    def test_init_from_roots_ignores_unlisted(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        roots = {"/tv": ["ShowA"]}
        bar.init_from_roots(roots, roots_order=["/tv", "/nonexistent"])
        assert "/nonexistent" not in bar._roots_order

    def test_mark_folder_active(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        roots = {"/tv": ["ShowA", "ShowB"]}
        bar.init_from_roots(roots, ["/tv"])
        bar.mark_folder_active("/tv", "ShowA")
        assert bar._roots["/tv"]["state"] == LibraryScanProgressBar.STATE_ACTIVE
        assert (
            bar._roots["/tv"]["folder_states"]["ShowA"]
            == LibraryScanProgressBar.STATE_ACTIVE
        )

    def test_mark_folder_done_all_done_marks_root_done(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        roots = {"/tv": ["ShowA", "ShowB"]}
        bar.init_from_roots(roots, ["/tv"])
        bar.mark_folder_active("/tv", "ShowA")
        bar.mark_folder_done("/tv", "ShowA")
        # Only ShowA done, root still not done
        assert bar._roots["/tv"]["state"] == LibraryScanProgressBar.STATE_ACTIVE
        bar.mark_folder_done("/tv", "ShowB")
        # Now both done → root should be done
        assert bar._roots["/tv"]["state"] == LibraryScanProgressBar.STATE_DONE

    def test_mark_folder_done_nonexistent_root(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        bar.mark_folder_done("/nonexistent", "SomeFolder")  # should not crash

    def test_mark_folder_active_nonexistent_root(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        bar.mark_folder_active("/nonexistent", "SomeFolder")  # should not crash

    def test_paint_event_empty(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        bar.resize(400, 20)
        bar.show()
        bar.repaint()  # Should not crash

    def test_paint_event_with_roots(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        roots = {"/tv": ["ShowA", "ShowB", "ShowC"], "/movies": ["Movie1"]}
        bar.init_from_roots(roots, ["/tv", "/movies"])
        bar.mark_folder_active("/tv", "ShowA")
        bar.mark_folder_done("/tv", "ShowA")
        bar.mark_folder_active("/tv", "ShowB")
        bar.mark_folder_done("/movies", "Movie1")
        bar.resize(600, 20)
        bar.show()
        bar.repaint()  # Should not raise

    def test_paint_state_done(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        roots = {"/tv": ["Show"]}
        bar.init_from_roots(roots, ["/tv"])
        bar.mark_folder_done("/tv", "Show")
        bar.resize(400, 20)
        bar.show()
        bar.repaint()  # Should paint root in DONE state, no crash

    def test_set_pass3_progress_zero_total(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        bar.set_pass3_progress(0, 0)
        assert bar._pass3_fraction == 1.0

    def test_paint_event_empty_roots(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        bar.resize(400, 20)
        bar.show()
        bar.repaint()

    def test_paint_event_passes(self, qtbot) -> None:
        bar = LibraryScanProgressBar()
        qtbot.addWidget(bar)
        roots = {"/tv": ["ShowA"]}
        bar.init_from_roots(roots, ["/tv"])
        bar.mark_folder_active("/tv", "ShowA")
        bar.resize(400, 20)
        bar.show()

        # Pass 1
        bar.set_current_pass(1)
        bar.repaint()

        # Pass 2
        bar.set_current_pass(2)
        bar.repaint()

        # Pass 3
        bar.set_pass3_progress(1, 2)
        bar.repaint()
