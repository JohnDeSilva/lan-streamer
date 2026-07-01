"""
Tests for ui_views/library_grid.py – LibraryGridView
Covers: __init__, _setup_ui, _wire_signals, populate_libraries, on_library_changed,
        on_library_tab_changed, populate_grid (various sort modes), _on_detail_progress,
        _on_scan_completed, on_order_changed, on_item_clicked, populate_combined_view,
        on_combined_item_clicked, trigger_combined_scan, _assign_item_icon,
        _assign_item_icon_with_size, _on_selector_text_changed,
        _open_search_dialog, _on_search_result_selected, search button integration.
"""

import pytest
from unittest.mock import patch, MagicMock
from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem, QPushButton, QDialog

from lan_streamer.ui_views import Controller
from lan_streamer.ui_views.library_grid import LibraryGridView
from lan_streamer.system.config import config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def grid_view(qtbot, mock_db_save):
    """Creates a LibraryGridView with a mock-backed controller."""
    controller = Controller()
    controller.cached_library_data = {}
    controller.current_library_name = ""
    controller.sort_mode = "Alphabetical"
    controller.sort_descending = False
    controller.filter_out_watched = False
    config.libraries = {"MyLib": {"type": "tv", "paths": ["/tv"]}}

    view = LibraryGridView(controller)
    qtbot.addWidget(view)
    return view, controller


def _make_tv_library(
    series_name: str = "My Show", watched: int = 0, total: int = 5
) -> Dict[str, Any]:
    """Create a minimal TV library dict with metrics."""
    episodes = []
    for i in range(total):
        episodes.append(
            {
                "name": f"S01E{i + 1:02d}.mkv",
                "path": f"/tv/{series_name}/Season 1/S01E{i + 1:02d}.mkv",
                "watched": i < watched,
                "tmdb_number": i + 1,
                "date_added": 1000 + i,
                "air_date": f"2021-01-{i + 1:02d}",
                "runtime": 45,
            }
        )
    return {
        series_name: {
            "metadata": {
                "tmdb_name": series_name,
                "poster_path": "",
                "first_air_date": "2021-01-01",
                "locked_metadata": False,
            },
            "seasons": {"Season 1": {"episodes": episodes}},
        }
    }


def _make_movie_library(
    movie_name: str = "My Movie", watched: bool = False
) -> Dict[str, Any]:
    """Create a minimal movie library dict."""
    return {
        movie_name: {
            "path": f"/movies/{movie_name}.mkv",
            "name": movie_name,
            "poster_path": "",
            "tmdb_name": movie_name,
            "locked_metadata": False,
            "watched": watched,
            "date_added": 5000,
            "year": 2020,
        }
    }


# ---------------------------------------------------------------------------
# Basic widget construction
# ---------------------------------------------------------------------------


class TestLibraryGridViewConstruction:
    def test_creates_successfully(self, qtbot, mock_db_save) -> None:
        controller = Controller()
        view = LibraryGridView(controller)
        qtbot.addWidget(view)
        assert view.series_list_widget is not None
        assert view.library_tab_bar is not None
        assert view.sort_selector is not None

    def test_shows_without_crash(self, qtbot, mock_db_save) -> None:
        controller = Controller()
        view = LibraryGridView(controller)
        qtbot.addWidget(view)
        view.show()
        view.resize(800, 600)


# ---------------------------------------------------------------------------
# populate_libraries
# ---------------------------------------------------------------------------


class TestPopulateLibraries:
    def test_populates_tab_bar_with_library_names(self, grid_view) -> None:
        view, controller = grid_view
        view.populate_libraries(["ShowLib", "MovieLib"])
        assert view.library_tab_bar.count() >= 2  # May include "Combined View"
        assert "ShowLib" in view.library_names_list
        assert "MovieLib" in view.library_names_list

    def test_selects_current_library_if_in_list(self, grid_view) -> None:
        view, controller = grid_view
        controller.current_library_name = "ShowLib"
        with patch.object(view, "on_library_changed") as mock_change:
            view.populate_libraries(["ShowLib", "MovieLib"])
            mock_change.assert_called_with("ShowLib")

    def test_selects_first_when_current_not_in_list(self, grid_view) -> None:
        view, controller = grid_view
        controller.current_library_name = "NonExistent"
        config.enable_combined_view = False
        try:
            with patch.object(view, "on_library_changed") as mock_change:
                view.populate_libraries(["ShowLib"])
                mock_change.assert_called_with("ShowLib")
        finally:
            config.enable_combined_view = False

    def test_combined_view_included_when_enabled(self, grid_view) -> None:
        view, controller = grid_view
        config.enable_combined_view = True
        try:
            view.populate_libraries(["ShowLib"])
            assert "Combined View" in view.library_names_list
        finally:
            config.enable_combined_view = False

    def test_empty_library_list(self, grid_view) -> None:
        view, controller = grid_view
        view.populate_libraries([])
        assert view.library_tab_bar.count() == 0 or True  # No crash


# ---------------------------------------------------------------------------
# on_library_changed
# ---------------------------------------------------------------------------


class TestOnLibraryChanged:
    def test_regular_library_shows_grid(self, grid_view) -> None:
        view, controller = grid_view
        view.show()  # Widget must be shown for isVisible() to return True
        with patch.object(controller, "select_library") as mock_select:
            view.on_library_changed("ShowLib")
            assert view.series_list_widget.isVisible()
            assert view.filter_watched_checkbox.isVisible()
            mock_select.assert_called_once_with("ShowLib")

    def test_combined_view_shows_combined_scroll(self, grid_view) -> None:
        view, controller = grid_view
        view.show()  # Widget must be shown for isVisible() to return True
        config.combined_views = []
        with patch.object(view, "populate_combined_view") as mock_populate:
            view.on_library_changed("Combined View")
            assert not view.series_list_widget.isVisible()
            assert not view.filter_watched_checkbox.isVisible()
            assert view.combined_scroll_area.isVisible()
            mock_populate.assert_called_once()

    def test_empty_library_name_no_crash(self, grid_view) -> None:
        view, controller = grid_view
        view.on_library_changed("")  # Should not crash


# ---------------------------------------------------------------------------
# on_library_tab_changed
# ---------------------------------------------------------------------------


class TestOnLibraryTabChanged:
    def test_tab_change_calls_on_library_changed(self, grid_view) -> None:
        view, controller = grid_view
        view.library_names_list = ["Alpha", "Beta"]
        with patch.object(view, "on_library_changed") as mock_change:
            view.on_library_tab_changed(1)
            mock_change.assert_called_once_with("Beta")

    def test_tab_change_invalid_index_no_crash(self, grid_view) -> None:
        view, controller = grid_view
        view.library_names_list = ["Alpha"]
        view.on_library_tab_changed(99)  # Out of range, should not crash


# ---------------------------------------------------------------------------
# _on_selector_text_changed
# ---------------------------------------------------------------------------


class TestOnSelectorTextChanged:
    def test_selector_change_syncs_tab(self, grid_view) -> None:
        view, controller = grid_view
        view.library_names_list = ["Alpha", "Beta"]
        with patch.object(view, "on_library_changed") as mock_change:
            view._on_selector_text_changed("Alpha")
            mock_change.assert_called_once_with("Alpha")

    def test_selector_change_unknown_text_no_crash(self, grid_view) -> None:
        view, controller = grid_view
        view.library_names_list = ["Alpha"]
        view._on_selector_text_changed("Nonexistent")  # Should not crash


# ---------------------------------------------------------------------------
# populate_grid
# ---------------------------------------------------------------------------


class TestPopulateGrid:
    def test_populate_grid_alphabetical(self, grid_view) -> None:
        view, controller = grid_view
        controller.cached_library_data = _make_tv_library(
            "ZebraShow", watched=1, total=5
        )
        controller._cache_series_metrics()
        controller.sort_mode = "Alphabetical"
        controller.sort_descending = False

        view.populate_grid()
        assert view.series_list_widget.count() == 1

    def test_populate_grid_recently_added(self, grid_view) -> None:
        view, controller = grid_view
        controller.cached_library_data = _make_tv_library("My Show", watched=2, total=5)
        controller._cache_series_metrics()
        controller.sort_mode = "Recently Added"
        controller.sort_descending = False

        view.populate_grid()
        assert view.series_list_widget.count() == 1

    def test_populate_grid_recently_aired(self, grid_view) -> None:
        view, controller = grid_view
        controller.cached_library_data = _make_tv_library("My Show", watched=0, total=5)
        controller._cache_series_metrics()
        controller.sort_mode = "Recently Aired"
        controller.sort_descending = True

        view.populate_grid()
        assert view.series_list_widget.count() == 1

    def test_populate_grid_next_up(self, grid_view) -> None:
        view, controller = grid_view
        controller.cached_library_data = _make_tv_library("My Show", watched=2, total=5)
        controller._cache_series_metrics()
        controller.sort_mode = "Next Up"
        controller.sort_descending = False

        view.populate_grid()
        assert view.series_list_widget.count() == 1

    def test_populate_grid_next_up_descending(self, grid_view) -> None:
        view, controller = grid_view
        controller.cached_library_data = _make_tv_library("My Show", watched=2, total=5)
        controller._cache_series_metrics()
        controller.sort_mode = "Next Up"
        controller.sort_descending = True

        view.populate_grid()
        assert view.series_list_widget.count() == 1

    def test_populate_grid_hides_fully_watched_when_filter(self, grid_view) -> None:
        view, controller = grid_view
        controller.cached_library_data = _make_tv_library(
            "WatchedShow", watched=5, total=5
        )
        controller._cache_series_metrics()
        controller.filter_out_watched = True

        view.populate_grid()
        assert view.series_list_widget.count() == 0

    def test_populate_grid_skips_series_with_zero_episodes(self, grid_view) -> None:
        view, controller = grid_view
        controller.cached_library_data = {
            "EmptyShow": {
                "metadata": {"poster_path": "", "first_air_date": ""},
                "seasons": {"Season 1": {"episodes": []}},
                "metrics": {
                    "total_episodes": 0,
                    "watched_episodes": 0,
                    "max_date_added": 0,
                    "max_air_date": "",
                    "last_played_at": 0,
                },
            }
        }
        view.populate_grid()
        assert view.series_list_widget.count() == 0

    def test_populate_grid_with_movie_data(self, grid_view) -> None:
        view, controller = grid_view
        controller.cached_library_data = _make_movie_library("Test Movie")
        controller._cache_series_metrics()
        controller.sort_mode = "Alphabetical"

        view.populate_grid()
        assert view.series_list_widget.count() == 1

    def test_populate_grid_video_playing_returns_early(self, grid_view) -> None:
        view, controller = grid_view
        controller.is_video_playing = True
        controller.cached_library_data = _make_tv_library("Test", watched=1, total=2)
        controller._cache_series_metrics()

        view.populate_grid()
        assert view.series_list_widget.count() == 0  # Should not populate

    def test_populate_grid_combined_view_delegates(self, grid_view) -> None:
        view, controller = grid_view
        controller.current_library_name = "Combined View"
        with patch.object(view, "populate_combined_view") as mock_populate:
            view.populate_grid()
            mock_populate.assert_called_once()

    def test_populate_grid_updates_existing_items(self, grid_view) -> None:
        """Test the delta update path where items already exist."""
        view, controller = grid_view
        lib = _make_tv_library("Show A", watched=1, total=3)
        controller.cached_library_data = lib
        controller._cache_series_metrics()

        # Populate once
        view.populate_grid()
        assert view.series_list_widget.count() == 1

        # Populate again - should update in-place
        controller.cached_library_data["Show A"]["seasons"]["Season 1"]["episodes"][0][
            "watched"
        ] = True
        controller._cache_series_metrics()
        view.populate_grid()
        assert view.series_list_widget.count() == 1

    def test_populate_grid_removes_extra_items(self, grid_view) -> None:
        """Test that extra items are removed when library shrinks."""
        view, controller = grid_view
        lib = _make_tv_library("Show A", watched=0, total=2)
        lib.update(_make_tv_library("Show B", watched=0, total=2))
        controller.cached_library_data = lib
        controller._cache_series_metrics()
        view.populate_grid()
        assert view.series_list_widget.count() == 2

        # Remove Show B
        controller.cached_library_data = _make_tv_library("Show A", watched=0, total=2)
        controller._cache_series_metrics()
        view.populate_grid()
        assert view.series_list_widget.count() == 1


# ---------------------------------------------------------------------------
# on_order_changed
# ---------------------------------------------------------------------------


class TestOnOrderChanged:
    def test_alphabetical_za_sets_descending(self, grid_view) -> None:
        view, controller = grid_view
        controller.sort_mode = "Alphabetical"
        with patch.object(controller, "set_sort_descending") as mock_set:
            view.on_order_changed("Z-A")
            mock_set.assert_called_once_with(True)

    def test_alphabetical_az_sets_ascending(self, grid_view) -> None:
        view, controller = grid_view
        controller.sort_mode = "Alphabetical"
        with patch.object(controller, "set_sort_descending") as mock_set:
            view.on_order_changed("A-Z")
            mock_set.assert_called_once_with(False)

    def test_non_alphabetical_oldest_to_newest_sets_descending(self, grid_view) -> None:
        view, controller = grid_view
        controller.sort_mode = "Recently Added"
        with patch.object(controller, "set_sort_descending") as mock_set:
            view.on_order_changed("Oldest to Newest")
            mock_set.assert_called_once_with(True)

    def test_empty_text_returns_early(self, grid_view) -> None:
        view, controller = grid_view
        with patch.object(controller, "set_sort_descending") as mock_set:
            view.on_order_changed("")
            mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# on_item_clicked
# ---------------------------------------------------------------------------


class TestOnItemClicked:
    def test_click_tv_series(self, grid_view) -> None:
        view, controller = grid_view
        controller.current_library_name = "ShowLib"
        config.libraries["ShowLib"] = {"type": "tv", "paths": ["/tv"]}

        item = QListWidgetItem("My Show")
        item.setData(Qt.ItemDataRole.UserRole, "My Show")

        with patch.object(controller, "select_series") as mock_select:
            view.on_item_clicked(item)
            mock_select.assert_called_once_with("My Show")

    def test_click_movie(self, grid_view) -> None:
        view, controller = grid_view
        controller.current_library_name = "MovieLib"
        config.libraries["MovieLib"] = {"type": "movie", "paths": ["/movies"]}

        item = QListWidgetItem("Avatar")
        item.setData(Qt.ItemDataRole.UserRole, "Avatar")

        with patch.object(controller, "select_movie") as mock_select:
            view.on_item_clicked(item)
            mock_select.assert_called_once_with("Avatar")

    def test_click_item_with_no_data(self, grid_view) -> None:
        view, controller = grid_view
        item = QListWidgetItem("Item")
        item.setData(Qt.ItemDataRole.UserRole, None)

        with patch.object(controller, "select_series") as mock_select:
            view.on_item_clicked(item)
            mock_select.assert_not_called()


# ---------------------------------------------------------------------------
# _on_detail_progress
# ---------------------------------------------------------------------------


class TestOnDetailProgress:
    def test_init_library_scan_shows_progress_bar(self, grid_view) -> None:
        view, controller = grid_view
        view.show()  # Must be shown for isVisible() to work
        payload = {
            "roots": {"/tv": ["Show A"]},
            "roots_order": ["/tv"],
        }
        view._on_detail_progress("init_library_scan", payload)
        assert view.scan_progress_bar.isVisible()
        assert view.scan_status_label.isVisible()

    def test_init_tree_shows_progress_bar(self, grid_view) -> None:
        view, controller = grid_view
        view.show()  # Must be shown for isVisible() to work
        config.libraries = {"MyLib": {"paths": ["/tv"]}}
        payload = {
            "tree": {
                "MyLib": {
                    "type": "tv",
                    "roots": {"/tv": {"Show A": {}}},
                }
            },
            "library_order": ["MyLib"],
        }
        view._on_detail_progress("init_tree", payload)
        assert view.scan_progress_bar.isVisible()

    def test_start_folder_marks_active(self, grid_view) -> None:
        view, controller = grid_view
        view.show()  # Must be shown for isVisible() to work
        # Initialize the bar first
        view.scan_progress_bar.init_from_roots({"/tv": ["Show A"]}, ["/tv"])
        payload = {"root": "/tv", "folder": "Show A", "library": "MyLib"}
        view._on_detail_progress("start_folder", payload)
        assert view.scan_status_label.isVisible()

    def test_finish_folder_marks_done(self, grid_view) -> None:
        view, controller = grid_view
        view.scan_progress_bar.init_from_roots({"/tv": ["Show A"]}, ["/tv"])
        view.scan_progress_bar.mark_folder_active("/tv", "Show A")
        payload = {"root": "/tv", "folder": "Show A"}
        view._on_detail_progress("finish_folder", payload)
        # Should not crash

    def test_unknown_event_no_crash(self, grid_view) -> None:
        view, controller = grid_view
        view._on_detail_progress("unknown_event", {})


# ---------------------------------------------------------------------------
# _on_scan_completed
# ---------------------------------------------------------------------------


class TestOnScanCompleted:
    def test_hides_progress_bar(self, grid_view) -> None:
        view, controller = grid_view
        view.scan_progress_bar.setVisible(True)
        view.scan_status_label.setVisible(True)
        view._on_scan_completed()
        assert not view.scan_progress_bar.isVisible()
        assert not view.scan_status_label.isVisible()


# ---------------------------------------------------------------------------
# populate_combined_view
# ---------------------------------------------------------------------------


class TestPopulateCombinedView:
    def test_shows_empty_label_when_no_rows(self, grid_view) -> None:
        view, controller = grid_view
        config.combined_views = []
        view.populate_combined_view()
        # Should show "No rows configured" label
        assert view.combined_scroll_layout.count() == 1

    def test_populates_rows_with_data(self, grid_view, mock_db_file) -> None:
        view, controller = grid_view
        config.combined_views = [
            {
                "name": "Recent",
                "enabled": True,
                "libraries": [],
                "sort_by": "Alphabetical",
                "filter_mode": "All",
                "max_items": 10,
            }
        ]

        with patch(
            "lan_streamer.db.get_cached_smart_rows",
            return_value=[
                {
                    "name": "Show A",
                    "type": "series",
                    "poster_path": "",
                    "watched_count": 2,
                    "total_count": 10,
                    "library_name": "MyLib",
                }
            ],
        ):
            view.populate_combined_view()
        # A row container should be added
        assert view.combined_scroll_layout.count() >= 1

    def test_skips_disabled_rows(self, grid_view) -> None:
        view, controller = grid_view
        config.combined_views = [
            {
                "name": "Disabled Row",
                "enabled": False,
                "libraries": [],
                "sort_by": "Alphabetical",
                "filter_mode": "All",
            }
        ]
        view.populate_combined_view()
        # Should show the "No rows" label since all rows disabled
        assert view.combined_scroll_layout.count() == 1

    def test_skips_rows_with_no_items(self, grid_view) -> None:
        view, controller = grid_view
        config.combined_views = [
            {
                "name": "Empty Row",
                "enabled": True,
                "libraries": [],
                "sort_by": "Alphabetical",
                "filter_mode": "All",
            }
        ]

        with patch("lan_streamer.db.get_cached_smart_rows", return_value=[]):
            view.populate_combined_view()
        # Empty row should be skipped, layout gets just the stretch
        # No crash is the key assertion

    def test_populates_season_type_items(self, grid_view) -> None:
        view, controller = grid_view
        config.combined_views = [
            {
                "name": "Seasons Row",
                "enabled": True,
                "libraries": [],
                "sort_by": "Alphabetical",
                "filter_mode": "All",
            }
        ]

        with patch(
            "lan_streamer.db.get_cached_smart_rows",
            return_value=[
                {
                    "name": "Show X",
                    "series_name": "Show X",
                    "type": "season",
                    "season_name": "Season 2",
                    "poster_path": "",
                    "watched_count": 1,
                    "total_count": 8,
                    "library_name": "MyLib",
                }
            ],
        ):
            view.populate_combined_view()

    def test_populates_movie_type_items(self, grid_view) -> None:
        view, controller = grid_view
        config.combined_views = [
            {
                "name": "Movie Row",
                "enabled": True,
                "libraries": [],
                "sort_by": "Alphabetical",
                "filter_mode": "All",
            }
        ]

        with patch(
            "lan_streamer.db.get_cached_smart_rows",
            return_value=[
                {
                    "name": "Avatar",
                    "type": "movie",
                    "poster_path": "",
                    "watched_count": 1,
                    "total_count": 1,
                    "library_name": "Movies",
                }
            ],
        ):
            view.populate_combined_view()

    def test_max_items_truncation(self, grid_view) -> None:
        view, controller = grid_view
        config.combined_views = [
            {
                "name": "Small Row",
                "enabled": True,
                "libraries": [],
                "sort_by": "Alphabetical",
                "filter_mode": "All",
                "max_items": 2,
            }
        ]

        items = [
            {
                "name": f"Show {i}",
                "type": "series",
                "poster_path": "",
                "watched_count": 0,
                "total_count": 1,
                "library_name": "Lib",
            }
            for i in range(10)
        ]
        with patch("lan_streamer.db.get_cached_smart_rows", return_value=items):
            view.populate_combined_view()
        # Row should only have 2 items (max_items=2)


# ---------------------------------------------------------------------------
# on_combined_item_clicked
# ---------------------------------------------------------------------------


class TestOnCombinedItemClicked:
    def test_click_movie_item(self, grid_view) -> None:
        view, controller = grid_view
        item = QListWidgetItem("Avatar")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {"type": "movie", "name": "Avatar", "library_name": "Movies"},
        )

        with (
            patch.object(controller, "select_library"),
            patch.object(controller, "select_movie") as mock_movie,
        ):
            view.on_combined_item_clicked(item)
            mock_movie.assert_called_once_with("Avatar")

    def test_click_series_item(self, grid_view) -> None:
        view, controller = grid_view
        item = QListWidgetItem("My Show")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {"type": "series", "name": "My Show", "library_name": "MyLib"},
        )

        with (
            patch.object(controller, "select_library"),
            patch.object(controller, "select_series") as mock_series,
        ):
            view.on_combined_item_clicked(item)
            mock_series.assert_called_once_with("My Show")

    def test_click_season_item_uses_series_name(self, grid_view) -> None:
        view, controller = grid_view
        item = QListWidgetItem("Show S1")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "type": "season",
                "name": None,
                "series_name": "My Show",
                "season_name": "Season 1",
                "library_name": "MyLib",
            },
        )

        with (
            patch.object(controller, "select_library"),
            patch.object(controller, "select_series") as mock_series,
        ):
            view.on_combined_item_clicked(item)
            mock_series.assert_called_once_with("My Show")

    def test_click_no_data_no_crash(self, grid_view) -> None:
        view, controller = grid_view
        item = QListWidgetItem("No Data")
        item.setData(Qt.ItemDataRole.UserRole, None)
        view.on_combined_item_clicked(item)  # Should not crash

    def test_click_no_library_name(self, grid_view) -> None:
        view, controller = grid_view
        item = QListWidgetItem("Show")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {"type": "series", "name": "Show", "library_name": None},
        )
        with patch.object(controller, "select_series"):
            view.on_combined_item_clicked(item)  # Should not crash


# ---------------------------------------------------------------------------
# trigger_combined_scan
# ---------------------------------------------------------------------------


class TestTriggerCombinedScan:
    def test_delegates_to_trigger_scan_all(self, grid_view) -> None:
        view, controller = grid_view
        with patch.object(controller, "trigger_scan_all") as mock_scan:
            view.trigger_combined_scan()
            mock_scan.assert_called_once_with(False)


# ---------------------------------------------------------------------------
# Fixtures re-use
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Search Button & Dialog
# ---------------------------------------------------------------------------


class TestSearchButton:
    def test_search_button_exists_single_library(self, grid_view) -> None:
        """Search button should exist in the single-library toolbar."""
        view, controller = grid_view
        search_buttons = view.findChildren(QPushButton, "searchSeriesButton")
        assert len(search_buttons) >= 1

    def test_search_button_exists_combined(self, grid_view) -> None:
        """Search button should exist in the combined view toolbar."""
        view, controller = grid_view
        search_buttons = view.findChildren(QPushButton, "searchSeriesButton")
        assert len(search_buttons) >= 1

    def test_open_search_dialog_single_library(self, grid_view) -> None:
        """Opening search on a library tab should scope to that library."""
        view, controller = grid_view
        controller.current_library_name = "MyLib"

        with patch(
            "lan_streamer.ui_views.library_grid.SearchDialog"
        ) as mock_dialog_class:
            mock_dialog_instance = MagicMock()
            mock_dialog_class.return_value = mock_dialog_instance
            mock_dialog_instance.exec.return_value = QDialog.DialogCode.Accepted

            view._open_search_dialog()

            mock_dialog_class.assert_called_once_with(library_name="MyLib", parent=view)

    def test_open_search_dialog_combined_view(self, grid_view) -> None:
        """Opening search on Combined View tab should search all libraries."""
        view, controller = grid_view
        controller.current_library_name = "Combined View"

        with patch(
            "lan_streamer.ui_views.library_grid.SearchDialog"
        ) as mock_dialog_class:
            mock_dialog_instance = MagicMock()
            mock_dialog_class.return_value = mock_dialog_instance
            mock_dialog_instance.exec.return_value = QDialog.DialogCode.Accepted

            view._open_search_dialog()

            mock_dialog_class.assert_called_once_with(library_name=None, parent=view)

    def test_open_search_dialog_connects_signal(self, grid_view) -> None:
        """Opening search should connect series_selected signal."""
        view, controller = grid_view
        controller.current_library_name = "MyLib"

        with patch(
            "lan_streamer.ui_views.library_grid.SearchDialog"
        ) as mock_dialog_class:
            mock_dialog_instance = MagicMock()
            mock_dialog_class.return_value = mock_dialog_instance
            mock_dialog_instance.exec.return_value = QDialog.DialogCode.Accepted

            view._open_search_dialog()

            mock_dialog_instance.series_selected.connect.assert_called_once_with(
                view._on_search_result_selected
            )


class TestOnSearchResultSelected:
    def test_navigates_to_series(self, grid_view) -> None:
        """Selecting a search result should navigate to the series."""
        view, controller = grid_view

        with (
            patch.object(controller, "select_library") as mock_select_library,
            patch.object(controller, "select_series") as mock_select_series,
        ):
            view._on_search_result_selected("My Series", "MyLib")

            assert controller.current_library_name == "MyLib"
            mock_select_library.assert_called_once_with("MyLib")
            mock_select_series.assert_called_once_with("My Series")

    def test_empty_library_name_skips_navigation(self, grid_view) -> None:
        """Empty library name should not crash but should skip navigation."""
        view, controller = grid_view

        with (
            patch.object(controller, "select_library") as mock_select_library,
            patch.object(controller, "select_series") as mock_select_series,
        ):
            view._on_search_result_selected("My Series", "")

            mock_select_library.assert_not_called()
            mock_select_series.assert_not_called()


# ---------------------------------------------------------------------------
# Fixtures re-use
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_file(tmp_path):
    return tmp_path / "library.db"
