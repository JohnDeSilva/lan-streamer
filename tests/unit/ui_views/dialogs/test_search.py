"""
Tests for ui_views/dialogs/search.py – SearchDialog
"""

from unittest.mock import MagicMock, create_autospec
from typing import List, Dict, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from lan_streamer.ui_views.dialogs.search import SearchDialog


def _make_mock_controller() -> MagicMock:
    """Create a mock controller with a ``search_media`` method."""
    controller = MagicMock()
    controller.search_media = create_autospec(lambda query_text, library_names=None: [])
    return controller


def _make_fake_results(
    count: int = 3, item_type: str = "series"
) -> List[Dict[str, Any]]:
    """Generate fake search results for testing."""
    return [
        {
            "name": f"Test Item {i}",
            "library_name": "TV Shows",
            "poster_path": "",
            "type": item_type,
        }
        for i in range(count)
    ]


def _make_fake_movie_results(count: int = 2) -> List[Dict[str, Any]]:
    """Generate fake movie search results."""
    return [
        {
            "name": f"Test Movie {i}",
            "library_name": "Movies",
            "poster_path": "",
            "type": "movie",
        }
        for i in range(count)
    ]


class TestSearchDialogInit:
    """Tests for SearchDialog initialization."""

    def test_init_with_library_name(self, qtbot) -> None:
        """Dialog title should include library name when specified."""
        controller = _make_mock_controller()
        dialog = SearchDialog(controller=controller, library_name="Anime")
        qtbot.addWidget(dialog)
        assert "Anime" in dialog.windowTitle()
        assert dialog._library_name == "Anime"

    def test_init_without_library_name(self, qtbot) -> None:
        """Dialog title should be generic when no library is specified."""
        controller = _make_mock_controller()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        assert dialog._library_name is None
        assert "Search" in dialog.windowTitle()

    def test_init_with_parent(self, qtbot) -> None:
        """Dialog should accept an optional parent widget."""
        from PySide6.QtWidgets import QWidget

        controller = _make_mock_controller()
        parent = QWidget()
        qtbot.addWidget(parent)
        dialog = SearchDialog(
            controller=controller, library_name="Movies", parent=parent
        )
        qtbot.addWidget(dialog)
        assert dialog.parent() is parent

    def test_search_input_placeholder(self, qtbot) -> None:
        """Search input should have placeholder text."""
        controller = _make_mock_controller()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        assert dialog.search_input.placeholderText() == "Search..."

    def test_debounce_timer_configured(self, qtbot) -> None:
        """Debounce timer should be single-shot with 300ms interval."""
        controller = _make_mock_controller()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        assert dialog.debounce_timer.isSingleShot()
        assert dialog.debounce_timer.interval() == 300


class TestSearchDialogSearch:
    """Tests for SearchDialog search behavior."""

    def test_short_query_clears_list(self, qtbot) -> None:
        """Typing fewer than 2 characters should clear the results list."""
        controller = _make_mock_controller()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog._execute_search = MagicMock()

        dialog.search_input.setText("a")
        assert dialog.results_list.count() == 0
        dialog._execute_search.assert_not_called()

    def test_debounce_starts_on_longer_text(self, qtbot) -> None:
        """Typing 2+ characters should start debounce timer."""
        controller = _make_mock_controller()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.debounce_timer = MagicMock()

        dialog.search_input.setText("ab")
        dialog.debounce_timer.start.assert_called_once()

    def test_text_changed_stops_timer(self, qtbot) -> None:
        """Each text change should restart debounce timer."""
        controller = _make_mock_controller()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.debounce_timer = MagicMock()

        dialog.search_input.setText("abc")
        dialog.debounce_timer.stop.assert_called_once()
        dialog.debounce_timer.start.assert_called_once()

        dialog.debounce_timer.reset_mock()
        dialog.search_input.setText("abcd")
        dialog.debounce_timer.stop.assert_called_once()
        dialog.debounce_timer.start.assert_called_once()

    def test_execute_search_populates_results(self, qtbot) -> None:
        """Search should populate results list from controller response."""
        controller = _make_mock_controller()
        controller.search_media.return_value = _make_fake_results(3)

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Test")
        dialog._execute_search()

        assert dialog.results_list.count() == 3
        for i in range(3):
            item = dialog.results_list.item(i)
            assert f"Test Item {i}" in item.text()

    def test_execute_search_movie_results(self, qtbot) -> None:
        """Search should display movie results with type label."""
        controller = _make_mock_controller()
        controller.search_media.return_value = _make_fake_movie_results(1)

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Movie")
        dialog._execute_search()

        assert dialog.results_list.count() == 1
        item = dialog.results_list.item(0)
        assert "Movie" in item.text()
        assert item.data(Qt.ItemDataRole.UserRole + 2) == "movie"

    def test_execute_search_no_results(self, qtbot) -> None:
        """Search with no matches should show placeholder."""
        controller = _make_mock_controller()
        controller.search_media.return_value = []

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Ghost")
        dialog._execute_search()

        assert dialog.results_list.count() == 1
        placeholder = dialog.results_list.item(0)
        assert "No results found" in placeholder.text()
        assert not (placeholder.flags() & Qt.ItemFlag.ItemIsSelectable)

    def test_execute_search_scoped_to_library(self, qtbot) -> None:
        """Search should scope to library when library_name is provided."""
        controller = _make_mock_controller()
        controller.search_media.return_value = _make_fake_results(1)

        dialog = SearchDialog(controller=controller, library_name="Anime")
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Test")
        dialog._execute_search()

        controller.search_media.assert_called_once_with("Test", ["Anime"])

    def test_execute_search_all_libraries(self, qtbot) -> None:
        """Search without library_name should search all libraries."""
        controller = _make_mock_controller()
        controller.search_media.return_value = _make_fake_results(2)

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Test")
        dialog._execute_search()

        controller.search_media.assert_called_once_with("Test", None)

    def test_execute_search_controller_raises_shows_no_results(self, qtbot) -> None:
        """When controller.search_media raises, dialog should show placeholder."""
        controller = _make_mock_controller()
        controller.search_media.side_effect = RuntimeError("Unexpected failure")

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Crash")
        dialog._execute_search()

        assert dialog.results_list.count() == 1
        placeholder = dialog.results_list.item(0)
        assert "No results found" in placeholder.text()

    def test_execute_search_short_query_noop(self, qtbot) -> None:
        """Execute search with short query should not call DB."""
        controller = _make_mock_controller()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("a")
        dialog._execute_search()

        controller.search_media.assert_not_called()


class TestSearchDialogInteraction:
    """Tests for SearchDialog user interaction."""

    def test_item_click_emits_signal(self, qtbot) -> None:
        """Clicking a result should emit item_selected signal."""
        controller = _make_mock_controller()
        controller.search_media.return_value = _make_fake_results(1)

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Test")
        dialog._execute_search()

        with qtbot.waitSignal(dialog.item_selected, timeout=1000) as blocker:
            item = dialog.results_list.item(0)
            dialog.results_list.itemClicked.emit(item)
        assert blocker.args == ["Test Item 0", "TV Shows", "series"]

    def test_item_click_movie_emits_type(self, qtbot) -> None:
        """Clicking a movie result should emit item_selected with movie type."""
        controller = _make_mock_controller()
        controller.search_media.return_value = _make_fake_movie_results(1)

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Movie")
        dialog._execute_search()

        with qtbot.waitSignal(dialog.item_selected, timeout=1000) as blocker:
            item = dialog.results_list.item(0)
            dialog.results_list.itemClicked.emit(item)
        assert blocker.args == ["Test Movie 0", "Movies", "movie"]

    def test_item_activated_emits_signal(self, qtbot) -> None:
        """Activating a result (Enter/double-click) should emit item_selected."""
        controller = _make_mock_controller()
        controller.search_media.return_value = _make_fake_results(1)

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Test")
        dialog._execute_search()

        with qtbot.waitSignal(dialog.item_selected, timeout=1000) as blocker:
            item = dialog.results_list.item(0)
            dialog.results_list.itemActivated.emit(item)

        assert blocker.args == ["Test Item 0", "TV Shows", "series"]

    def test_click_no_data_no_crash(self, qtbot) -> None:
        """Clicking with missing data should not crash."""
        controller = _make_mock_controller()
        controller.search_media.return_value = _make_fake_results(1)

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Test")
        dialog._execute_search()

        dialog.item_selected.connect(lambda *args: None)

        item = dialog.results_list.item(0)
        item.setData(Qt.ItemDataRole.UserRole, None)
        item.setData(Qt.ItemDataRole.UserRole + 1, None)
        dialog._on_item_clicked(item)  # Should not crash

    def test_dialog_accepts_after_selection(self, qtbot) -> None:
        """Dialog should accept (close) after a selection is made."""
        controller = _make_mock_controller()
        controller.search_media.return_value = _make_fake_results(1)

        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Test")
        dialog._execute_search()

        item = dialog.results_list.item(0)
        dialog._on_item_clicked(item)

        assert dialog.result() == QDialog.DialogCode.Accepted


class TestSearchDialogThumbnail:
    """Tests for SearchDialog thumbnail icon loading."""

    def test_thumbnail_missing_file_does_not_crash(self, qtbot, tmp_path) -> None:
        """Non-existent poster file should not crash."""
        controller = _make_mock_controller()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)

        from PySide6.QtWidgets import QListWidgetItem

        item = QListWidgetItem("Test")
        dialog._assign_thumbnail_icon(item, str(tmp_path / "nonexistent.jpg"))
        # Should not crash, icon should be missing

    def test_thumbnail_loading_cached(self, qtbot, tmp_path) -> None:
        """Thumbnail loading should cache results and reuse on subsequent calls."""
        controller = _make_mock_controller()
        dialog = SearchDialog(controller=controller)
        qtbot.addWidget(dialog)

        # Create a small valid image file
        from PySide6.QtGui import QPixmap

        pixmap = QPixmap(32, 48)
        pixmap.fill(Qt.GlobalColor.red)
        image_path = tmp_path / "test_poster.jpg"
        pixmap.save(str(image_path))

        from PySide6.QtWidgets import QListWidgetItem

        item1 = QListWidgetItem("Test")
        dialog._assign_thumbnail_icon(item1, str(image_path))

        cache_key = f"search_{image_path}"
        assert cache_key in dialog._cached_icons

        # Delete the source file; second call must use the in-memory cache
        image_path.unlink()

        item2 = QListWidgetItem("Test")
        dialog._assign_thumbnail_icon(item2, str(image_path))

        # Cache should have been hit — icon should be non-null even though
        # the source file no longer exists
        assert cache_key in dialog._cached_icons
        assert not item2.icon().isNull()
