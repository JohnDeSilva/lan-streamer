"""Tests for ui_views/dialogs/mal_search_results.py – _status_label, _build_alt_titles_text & MalSearchResultsDialog."""

from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QTableWidgetItem

from lan_streamer.ui_views.dialogs.mal_search_results import (
    MalSearchResultsDialog,
    _build_alt_titles_text,
    _status_label,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    result_id: int = 100,
    title: str = "Test Anime",
    start_date: str = "2024-01-01",
    num_episodes: int = 12,
    status: str = "finished_airing",
    synopsis: str = "A synopsis.",
    poster_path: str = "",
    english_title: str = "",
    alternative_titles: list | None = None,
    genres: list | None = None,
) -> dict:
    return {
        "id": result_id,
        "title": title,
        "start_date": start_date,
        "num_episodes": num_episodes,
        "status": status,
        "synopsis": synopsis,
        "poster_path": poster_path,
        "english_title": english_title,
        "alternative_titles": alternative_titles or [],
        "genres": genres or [],
    }


# ===================================================================
# _status_label
# ===================================================================


class TestStatusLabel:
    def test_finished_airing(self) -> None:
        assert _status_label("finished_airing") == "Finished"

    def test_currently_airing(self) -> None:
        assert _status_label("currently_airing") == "Airing"

    def test_not_yet_aired(self) -> None:
        assert _status_label("not_yet_aired") == "Upcoming"

    def test_unknown_status_title_cased(self) -> None:
        assert _status_label("on_hold") == "On Hold"

    def test_empty_string(self) -> None:
        assert _status_label("") == ""

    def test_single_word(self) -> None:
        assert _status_label("hiatus") == "Hiatus"

    def test_multi_underscore(self) -> None:
        assert _status_label("not_yet_started") == "Not Yet Started"


# ===================================================================
# _build_alt_titles_text
# ===================================================================


class TestBuildAltTitlesText:
    def test_all_fields_present(self) -> None:
        item = {
            "english_title": "English Title",
            "alternative_titles": ["AKA 1", "AKA 2"],
            "genres": ["Action", "Comedy"],
        }
        text = _build_alt_titles_text(item)
        assert "English: English Title" in text
        assert "Also known as: AKA 1, AKA 2" in text
        assert "Genres: Action, Comedy" in text
        assert "  |  " in text

    def test_english_only(self) -> None:
        item = {"english_title": "EN", "alternative_titles": [], "genres": []}
        assert _build_alt_titles_text(item) == "English: EN"

    def test_genres_only(self) -> None:
        item = {"english_title": "", "alternative_titles": [], "genres": ["Drama"]}
        assert _build_alt_titles_text(item) == "Genres: Drama"

    def test_synonyms_truncated_to_3(self) -> None:
        item = {
            "english_title": "",
            "alternative_titles": ["A", "B", "C", "D", "E"],
            "genres": [],
        }
        text = _build_alt_titles_text(item)
        assert "A, B, C" in text
        assert "D" not in text

    def test_all_empty(self) -> None:
        item = {"english_title": "", "alternative_titles": [], "genres": []}
        assert _build_alt_titles_text(item) == ""

    def test_none_values_treated_as_empty(self) -> None:
        item = {"english_title": None, "alternative_titles": None, "genres": None}
        assert _build_alt_titles_text(item) == ""

    def test_missing_keys(self) -> None:
        assert _build_alt_titles_text({}) == ""


# ===================================================================
# MalSearchResultsDialog – construction
# ===================================================================


class TestDialogConstruction:
    def test_construct_with_empty_results(self, qtbot) -> None:
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "MyAnimeList Search Results"
        assert dialog._results_table.rowCount() == 0

    def test_construct_with_results_selects_first_row(self, qtbot) -> None:
        results = [_make_result(1, "Alpha"), _make_result(2, "Beta")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.rowCount() == 2
        selected = dialog._results_table.selectedItems()
        assert len(selected) > 0
        assert selected[0].row() == 0

    def test_seven_columns(self, qtbot) -> None:
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog._results_table.columnCount() == 7


# ===================================================================
# _populate_table – cell content, defaults, synopsis truncation
# ===================================================================


class TestPopulateTable:
    def test_user_role_data(self, qtbot) -> None:
        results = [_make_result(42, "My Anime")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        thumb = dialog._results_table.item(0, 0)
        assert thumb.data(Qt.ItemDataRole.UserRole) == 42
        assert thumb.data(Qt.ItemDataRole.UserRole + 1) == "My Anime"

    def test_title_fallback_to_unknown(self, qtbot) -> None:
        results = [
            {
                "id": 1,
                "start_date": "",
                "num_episodes": 0,
                "status": "",
                "synopsis": "",
                "poster_path": "",
                "english_title": "",
                "alternative_titles": [],
                "genres": [],
            }
        ]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 1).text() == "Unknown"

    def test_synopsis_truncated_to_200_chars(self, qtbot) -> None:
        long_synopsis = "z" * 250
        results = [_make_result(1, synopsis=long_synopsis)]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        text = dialog._results_table.item(0, 5).text()
        assert len(text) == 203
        assert text.endswith("...")

    def test_synopsis_not_truncated_under_limit(self, qtbot) -> None:
        results = [_make_result(1, synopsis="Short")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 5).text() == "Short"

    def test_synopsis_tooltip_full_text(self, qtbot) -> None:
        long_synopsis = "w" * 300
        results = [_make_result(1, synopsis=long_synopsis)]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 5).toolTip() == long_synopsis

    def test_episodes_shows_question_mark_when_zero(self, qtbot) -> None:
        results = [_make_result(1, num_episodes=0)]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 3).text() == "?"

    def test_episodes_shows_number_when_nonzero(self, qtbot) -> None:
        results = [_make_result(1, num_episodes=24)]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 3).text() == "24"

    def test_status_column_populated(self, qtbot) -> None:
        results = [_make_result(1, status="currently_airing")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 4).text() == "Airing"

    def test_date_column_populated(self, qtbot) -> None:
        results = [_make_result(1, start_date="2023-07-01")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 2).text() == "2023-07-01"

    def test_alternate_titles_column(self, qtbot) -> None:
        results = [_make_result(1, english_title="EN", genres=["Action"])]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        alt_text = dialog._results_table.item(0, 6).text()
        assert "English: EN" in alt_text
        assert "Genres: Action" in alt_text

    def test_thumbnail_pending_when_poster_path_set(self, qtbot) -> None:
        results = [_make_result(1, poster_path="/poster.jpg")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert len(dialog._pending_thumbnails) == 1

    def test_no_thumbnail_pending_without_poster(self, qtbot) -> None:
        results = [_make_result(1, poster_path="")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert len(dialog._pending_thumbnails) == 0

    def test_episodes_shows_question_mark_when_falsy(self, qtbot) -> None:
        results = [_make_result(1, num_episodes=None)]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 3).text() == "?"


# ===================================================================
# _capture_selection
# ===================================================================


class TestCaptureSelection:
    def test_captures_id_and_title(self, qtbot) -> None:
        results = [_make_result(77, "Selected Anime")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        item = dialog._results_table.item(0, 0)
        dialog._capture_selection(item)
        assert dialog.selected_id() == 77
        assert dialog.selected_title() == "Selected Anime"

    def test_captures_none_when_no_data(self, qtbot) -> None:
        item = QTableWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, None)
        item.setData(Qt.ItemDataRole.UserRole + 1, None)
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._capture_selection(item)
        assert dialog.selected_id() is None
        assert dialog.selected_title() is None


# ===================================================================
# _on_cell_double_clicked / _on_cell_clicked / _on_accept
# ===================================================================


class TestCellInteractions:
    def test_double_click_captures_and_accepts(self, qtbot) -> None:
        results = [_make_result(10, "Double")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        dialog._on_cell_double_clicked(0, 0)
        assert dialog.selected_id() == 10
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_single_click_captures_without_accept(self, qtbot) -> None:
        results = [_make_result(11, "Single")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        dialog._on_cell_clicked(0, 0)
        assert dialog.selected_id() == 11
        assert dialog.result() != QDialog.DialogCode.Accepted

    def test_on_accept_with_selection(self, qtbot) -> None:
        results = [_make_result(20, "Accept")]
        dialog = MalSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        dialog._results_table.selectRow(0)
        dialog._on_accept()
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_on_accept_without_selection_does_not_accept(self, qtbot) -> None:
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._on_accept()
        assert dialog.result() != QDialog.DialogCode.Accepted


# ===================================================================
# Getter methods
# ===================================================================


class TestGetters:
    def test_default_id_is_none(self, qtbot) -> None:
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog.selected_id() is None

    def test_default_title_is_none(self, qtbot) -> None:
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog.selected_title() is None


# ===================================================================
# _assign_thumbnail_icon
# ===================================================================


class TestAssignThumbnailIcon:
    @patch("requests.get")
    def test_cache_hit_uses_cached_icon(self, mock_get, qtbot) -> None:
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        from PySide6.QtGui import QIcon

        real_icon = QIcon()
        dialog._cached_thumbnails["/img.jpg"] = real_icon
        dialog._results_table.setRowCount(1)
        from PySide6.QtWidgets import QTableWidgetItem

        dialog._results_table.setItem(0, 0, QTableWidgetItem())
        dialog._assign_thumbnail_icon(0, "/img.jpg")
        mock_get.assert_not_called()
        assert (
            dialog._results_table.item(0, 0).icon().cacheKey() == real_icon.cacheKey()
        )

    @patch("requests.get")
    def test_http_failure_returns_without_crash(self, mock_get, qtbot) -> None:
        mock_get.side_effect = ConnectionError("fail")
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._results_table.setRowCount(1)
        from PySide6.QtWidgets import QTableWidgetItem

        dialog._results_table.setItem(0, 0, QTableWidgetItem())
        dialog._assign_thumbnail_icon(0, "/img.jpg")
        assert dialog._results_table.item(0, 0).icon().isNull()

    @patch("lan_streamer.ui_views.dialogs.mal_search_results.QIcon")
    @patch("lan_streamer.ui_views.dialogs.mal_search_results.QPixmap")
    @patch("requests.get")
    def test_successful_load_caches_icon(
        self, mock_get, mock_qpx_cls, mock_qicon_cls, qtbot
    ) -> None:
        mock_response = MagicMock()
        mock_response.content = b"\x89PNG"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        mock_pixmap = MagicMock()
        mock_pixmap.loadFromData.return_value = True
        mock_scaled = MagicMock()
        mock_pixmap.scaled.return_value = mock_scaled
        mock_qpx_cls.return_value = mock_pixmap

        from PySide6.QtGui import QIcon as RealQIcon

        real_icon = RealQIcon()
        mock_qicon_cls.return_value = real_icon

        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._results_table.setRowCount(1)
        from PySide6.QtWidgets import QTableWidgetItem

        dialog._results_table.setItem(0, 0, QTableWidgetItem())

        dialog._assign_thumbnail_icon(0, "/pic.png")

        mock_qicon_cls.assert_called_with(mock_scaled)
        assert "/pic.png" in dialog._cached_thumbnails

    @patch("requests.get")
    def test_loadFromData_failure_returns(self, mock_get, qtbot) -> None:
        mock_response = MagicMock()
        mock_response.content = b"garbage"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._results_table.setRowCount(1)
        from PySide6.QtWidgets import QTableWidgetItem

        dialog._results_table.setItem(0, 0, QTableWidgetItem())

        with patch(
            "lan_streamer.ui_views.dialogs.mal_search_results.QPixmap"
        ) as mock_px:
            mock_pixmap = MagicMock()
            mock_pixmap.loadFromData.return_value = False
            mock_px.return_value = mock_pixmap
            dialog._assign_thumbnail_icon(0, "/bad.png")

        assert "/bad.png" not in dialog._cached_thumbnails


# ===================================================================
# _process_thumbnail_batch
# ===================================================================


class TestProcessThumbnailBatch:
    @patch.object(MalSearchResultsDialog, "_assign_thumbnail_icon")
    def test_processes_up_to_3_items(self, mock_assign, qtbot) -> None:
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._pending_thumbnails = [
            (0, "url0"),
            (1, "url1"),
            (2, "url2"),
            (3, "url3"),
            (4, "url4"),
        ]
        dialog._process_thumbnail_batch()
        assert mock_assign.call_count == 3
        assert len(dialog._pending_thumbnails) == 2

    @patch.object(MalSearchResultsDialog, "_assign_thumbnail_icon")
    def test_processes_remaining_batch(self, mock_assign, qtbot) -> None:
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._pending_thumbnails = [(10, "url10"), (11, "url11")]
        dialog._process_thumbnail_batch()
        assert mock_assign.call_count == 2
        assert len(dialog._pending_thumbnails) == 0

    @patch.object(MalSearchResultsDialog, "_assign_thumbnail_icon")
    def test_empty_batch_does_nothing(self, mock_assign, qtbot) -> None:
        dialog = MalSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._pending_thumbnails = []
        dialog._process_thumbnail_batch()
        mock_assign.assert_not_called()
