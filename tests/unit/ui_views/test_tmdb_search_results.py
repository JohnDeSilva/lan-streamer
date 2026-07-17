"""Tests for ui_views/dialogs/tmdb_search_results.py – _parse_season_number & TmdbSearchResultsDialog."""

from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QTableWidgetItem

from lan_streamer.ui_views.dialogs.tmdb_search_results import (
    TmdbSearchResultsDialog,
    _parse_season_number,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    result_id: int = 100,
    name: str = "Test Series",
    title: str | None = None,
    first_air_date: str = "2024-01-01",
    overview: str = "An overview.",
    poster_path: str = "",
) -> dict:
    item: dict = {
        "id": result_id,
        "name": name,
        "first_air_date": first_air_date,
        "overview": overview,
        "poster_path": poster_path,
    }
    if title is not None:
        item["title"] = title
    return item


# ===================================================================
# _parse_season_number
# ===================================================================


class TestParseSeasonNumber:
    def test_extracts_integer_from_name(self) -> None:
        assert _parse_season_number("Season 2") == 2

    def test_extracts_number_at_end(self) -> None:
        assert _parse_season_number("Part 10") == 10

    def test_returns_none_for_no_digits(self) -> None:
        assert _parse_season_number("Specials") is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _parse_season_number("") is None

    def test_extracts_first_number(self) -> None:
        assert _parse_season_number("Season 1 Episode 3") == 1

    def test_handles_leading_number(self) -> None:
        assert _parse_season_number("3 - Third Season") == 3

    def test_handles_pure_digit_string(self) -> None:
        assert _parse_season_number("5") == 5


# ===================================================================
# TmdbSearchResultsDialog – construction
# ===================================================================


class TestDialogConstruction:
    def test_construct_with_empty_results(self, qtbot) -> None:
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "TMDB Series Search Results"
        assert dialog._results_table.rowCount() == 0

    def test_construct_with_results_selects_first_row(self, qtbot) -> None:
        results = [_make_result(1, "Alpha"), _make_result(2, "Beta")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.rowCount() == 2
        selected = dialog._results_table.selectedItems()
        assert len(selected) > 0
        assert selected[0].row() == 0

    def test_five_columns(self, qtbot) -> None:
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog._results_table.columnCount() == 5


# ===================================================================
# _populate_table – cell content, UserRole, overview truncation
# ===================================================================


class TestExistingMappedIds:
    """Tests for the existing_mapped_ids parameter that shows ● on mapped entries."""

    def test_mapped_entry_shows_symbol(self, qtbot) -> None:
        results = [_make_result(42, "Mapped Series")]
        dialog = TmdbSearchResultsDialog(results=results, existing_mapped_ids={42})
        qtbot.addWidget(dialog)
        title_text = dialog._results_table.item(0, 1).text()
        assert title_text == "\u25cf Mapped Series"

    def test_mapped_entry_has_green_foreground(self, qtbot) -> None:
        results = [_make_result(42, "Green Title")]
        dialog = TmdbSearchResultsDialog(results=results, existing_mapped_ids={42})
        qtbot.addWidget(dialog)
        foreground = dialog._results_table.item(0, 1).foreground()
        assert foreground.color().name() == "#4caf50"

    def test_unmapped_entry_no_symbol(self, qtbot) -> None:
        results = [_make_result(42, "Plain Title")]
        dialog = TmdbSearchResultsDialog(results=results, existing_mapped_ids={99})
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 1).text() == "Plain Title"

    def test_no_existing_ids_no_symbol(self, qtbot) -> None:
        results = [_make_result(42, "No Indicator")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 1).text() == "No Indicator"

    def test_empty_existing_ids_no_symbol(self, qtbot) -> None:
        results = [_make_result(42, "Empty Set")]
        dialog = TmdbSearchResultsDialog(results=results, existing_mapped_ids=set())
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 1).text() == "Empty Set"


class TestPopulateTable:
    def test_user_role_data(self, qtbot) -> None:
        results = [_make_result(42, "My Title")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        thumb = dialog._results_table.item(0, 0)
        assert thumb.data(Qt.ItemDataRole.UserRole) == 42
        assert thumb.data(Qt.ItemDataRole.UserRole + 1) == "My Title"

    def test_title_fallback_to_unknown(self, qtbot) -> None:
        results = [{"id": 1, "first_air_date": "", "overview": "", "poster_path": ""}]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        title_item = dialog._results_table.item(0, 1)
        assert title_item.text() == "Unknown"

    def test_title_uses_name_key(self, qtbot) -> None:
        results = [_make_result(1, name="FromName")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 1).text() == "FromName"

    def test_title_prefers_name_over_title(self, qtbot) -> None:
        results = [_make_result(1, name="NameWins", title="TitleLoses")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 1).text() == "NameWins"

    def test_overview_truncated_to_200_chars(self, qtbot) -> None:
        long_overview = "x" * 250
        results = [_make_result(1, overview=long_overview)]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        text = dialog._results_table.item(0, 4).text()
        assert len(text) == 203  # 200 + "..."
        assert text.endswith("...")

    def test_overview_not_truncated_under_limit(self, qtbot) -> None:
        short_overview = "Short"
        results = [_make_result(1, overview=short_overview)]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 4).text() == "Short"

    def test_seasons_column_shows_question_mark(self, qtbot) -> None:
        results = [_make_result(1)]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 2).text() == "?"

    def test_date_column_populated(self, qtbot) -> None:
        results = [_make_result(1, first_air_date="2023-06-15")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 3).text() == "2023-06-15"

    def test_overview_tooltip_full_text(self, qtbot) -> None:
        long_overview = "y" * 300
        results = [_make_result(1, overview=long_overview)]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert dialog._results_table.item(0, 4).toolTip() == long_overview

    def test_thumbnail_pending_when_poster_path_set(self, qtbot) -> None:
        results = [_make_result(1, poster_path="/abc.jpg")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert len(dialog._pending_thumbnails) == 1
        row_index, poster_url = dialog._pending_thumbnails[0]
        assert row_index == 0
        assert poster_url.endswith("/abc.jpg")
        assert "/w185" in poster_url

    def test_no_thumbnail_pending_without_poster(self, qtbot) -> None:
        results = [_make_result(1, poster_path="")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        assert len(dialog._pending_thumbnails) == 0


# ===================================================================
# _capture_selection
# ===================================================================


class TestCaptureSelection:
    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    def test_captures_id_and_title(self, mock_tmdb, qtbot) -> None:
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 1, "name": "Season 1"},
        ]
        results = [_make_result(99, "Captured")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        item = dialog._results_table.item(0, 0)
        dialog._capture_selection(item)
        assert dialog.selected_id() == 99
        assert dialog.selected_title() == "Captured"

    def test_does_not_capture_when_no_id(self, qtbot) -> None:
        item = QTableWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, None)
        item.setData(Qt.ItemDataRole.UserRole + 1, "Ghost")
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._capture_selection(item)
        assert dialog.selected_id() is None


# ===================================================================
# _resolve_season_number
# ===================================================================


class TestResolveSeasonNumber:
    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    def test_returns_1_when_no_seasons(self, mock_tmdb, qtbot) -> None:
        mock_tmdb.get_seasons.return_value = []
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog._resolve_season_number(1) == 1

    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    def test_returns_1_on_exception(self, mock_tmdb, qtbot) -> None:
        mock_tmdb.get_seasons.side_effect = RuntimeError("api down")
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog._resolve_season_number(1) == 1

    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    def test_exact_number_match(self, mock_tmdb, qtbot) -> None:
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 1, "name": "Season 1"},
            {"season_number": 2, "name": "Season 2"},
        ]
        dialog = TmdbSearchResultsDialog(results=[], current_season_name="Season 2")
        qtbot.addWidget(dialog)
        assert dialog._resolve_season_number(1) == 2

    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    def test_fuzzy_name_match(self, mock_tmdb, qtbot) -> None:
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 1, "name": "The Beginning"},
            {"season_number": 2, "name": "Season 2 Special Edition"},
        ]
        dialog = TmdbSearchResultsDialog(results=[], current_season_name="Season 2")
        qtbot.addWidget(dialog)
        assert dialog._resolve_season_number(1) == 2

    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    def test_fallback_to_first_non_special(self, mock_tmdb, qtbot) -> None:
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 0, "name": "Specials"},
            {"season_number": 3, "name": "Season 3"},
        ]
        dialog = TmdbSearchResultsDialog(results=[], current_season_name="Season 99")
        qtbot.addWidget(dialog)
        assert dialog._resolve_season_number(1) == 3

    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    def test_fallback_to_1_when_all_specials(self, mock_tmdb, qtbot) -> None:
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 0, "name": "Specials"},
        ]
        dialog = TmdbSearchResultsDialog(results=[], current_season_name="")
        qtbot.addWidget(dialog)
        assert dialog._resolve_season_number(1) == 1

    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    def test_no_season_name_exact_match_then_fuzzy_fails(
        self, mock_tmdb, qtbot
    ) -> None:
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 1, "name": "Alpha"},
            {"season_number": 2, "name": "Beta"},
        ]
        dialog = TmdbSearchResultsDialog(results=[], current_season_name="Season 1")
        qtbot.addWidget(dialog)
        assert dialog._resolve_season_number(1) == 1


# ===================================================================
# _on_cell_double_clicked / _on_cell_clicked / _on_accept
# ===================================================================


class TestCellInteractions:
    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    def test_double_click_captures_and_accepts(self, mock_tmdb, qtbot) -> None:
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 1, "name": "Season 1"},
        ]
        results = [_make_result(10, "Double")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        dialog._on_cell_double_clicked(0, 0)
        assert dialog.selected_id() == 10
        assert dialog.result() == QDialog.DialogCode.Accepted

    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    def test_single_click_captures_without_accept(self, mock_tmdb, qtbot) -> None:
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 1, "name": "Season 1"},
        ]
        results = [_make_result(11, "Single")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        dialog._on_cell_clicked(0, 0)
        assert dialog.selected_id() == 11
        assert dialog.result() != QDialog.DialogCode.Accepted

    def test_on_accept_with_selection(self, qtbot) -> None:
        results = [_make_result(20, "Accept")]
        dialog = TmdbSearchResultsDialog(results=results)
        qtbot.addWidget(dialog)
        dialog._results_table.selectRow(0)
        dialog._on_accept()
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_on_accept_without_selection_does_not_accept(self, qtbot) -> None:
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._on_accept()
        assert dialog.result() != QDialog.DialogCode.Accepted


# ===================================================================
# Getter methods
# ===================================================================


class TestGetters:
    def test_default_id_is_none(self, qtbot) -> None:
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog.selected_id() is None

    def test_default_title_is_none(self, qtbot) -> None:
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog.selected_title() is None

    def test_default_season_number_is_1(self, qtbot) -> None:
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        assert dialog.selected_season_number() == 1


# ===================================================================
# _assign_thumbnail_icon
# ===================================================================


class TestAssignThumbnailIcon:
    @patch("requests.get")
    def test_cache_hit_uses_cached_icon(self, mock_get, qtbot) -> None:
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        from PySide6.QtGui import QIcon

        real_icon = QIcon()
        url = "https://example.invalid/t/p/w185/img.jpg"
        dialog._cached_thumbnails[url] = real_icon
        dialog._results_table.setRowCount(1)
        from PySide6.QtWidgets import QTableWidgetItem

        dialog._results_table.setItem(0, 0, QTableWidgetItem())
        dialog._assign_thumbnail_icon(0, url)
        mock_get.assert_not_called()
        assert (
            dialog._results_table.item(0, 0).icon().cacheKey() == real_icon.cacheKey()
        )

    @patch("requests.get")
    def test_http_failure_returns_without_setting_icon(self, mock_get, qtbot) -> None:
        mock_get.side_effect = ConnectionError("fail")
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._results_table.setRowCount(1)
        from PySide6.QtWidgets import QTableWidgetItem

        dialog._results_table.setItem(0, 0, QTableWidgetItem())
        dialog._assign_thumbnail_icon(0, "https://example.invalid/t/p/w185/img.jpg")
        assert dialog._results_table.item(0, 0).icon().isNull()

    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.QIcon")
    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.QPixmap")
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

        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._results_table.setRowCount(1)
        from PySide6.QtWidgets import QTableWidgetItem

        dialog._results_table.setItem(0, 0, QTableWidgetItem())

        dialog._assign_thumbnail_icon(0, "https://example.invalid/t/p/w185/pic.png")

        mock_qicon_cls.assert_called_with(mock_scaled)
        assert "https://example.invalid/t/p/w185/pic.png" in dialog._cached_thumbnails

    @patch("requests.get")
    def test_loadFromData_failure_returns(self, mock_get, qtbot) -> None:
        mock_response = MagicMock()
        mock_response.content = b"garbage"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._results_table.setRowCount(1)
        from PySide6.QtWidgets import QTableWidgetItem

        dialog._results_table.setItem(0, 0, QTableWidgetItem())

        with patch(
            "lan_streamer.ui_views.dialogs.tmdb_search_results.QPixmap"
        ) as mock_px:
            mock_pixmap = MagicMock()
            mock_pixmap.loadFromData.return_value = False
            mock_px.return_value = mock_pixmap
            dialog._assign_thumbnail_icon(0, "https://example.invalid/t/p/w185/bad.png")

        assert (
            "https://example.invalid/t/p/w185/bad.png" not in dialog._cached_thumbnails
        )


# ===================================================================
# _process_thumbnail_batch
# ===================================================================


class TestProcessThumbnailBatch:
    @patch("lan_streamer.ui_views.dialogs.tmdb_search_results.tmdb_client")
    @patch.object(TmdbSearchResultsDialog, "_assign_thumbnail_icon")
    def test_processes_up_to_3_items(self, mock_assign, mock_tmdb, qtbot) -> None:
        mock_tmdb.get_seasons.return_value = []
        results = [_make_result(i, f"S{i}", poster_path=f"/{i}.jpg") for i in range(5)]
        dialog = TmdbSearchResultsDialog(results=results)
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

    @patch.object(TmdbSearchResultsDialog, "_assign_thumbnail_icon")
    def test_processes_remaining_batch(self, mock_assign, qtbot) -> None:
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._pending_thumbnails = [(10, "url10"), (11, "url11")]
        dialog._process_thumbnail_batch()
        assert mock_assign.call_count == 2
        assert len(dialog._pending_thumbnails) == 0

    @patch.object(TmdbSearchResultsDialog, "_assign_thumbnail_icon")
    def test_empty_batch_does_nothing(self, mock_assign, qtbot) -> None:
        dialog = TmdbSearchResultsDialog(results=[])
        qtbot.addWidget(dialog)
        dialog._pending_thumbnails = []
        dialog._process_thumbnail_batch()
        mock_assign.assert_not_called()
