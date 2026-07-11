"""Targeted tests for SeasonDetailView uncovered lines."""

from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QDialog

from lan_streamer.ui_views import SeasonDetailView
from lan_streamer.ui_views.controller import Controller


def _make_controller_with_data(
    series_name: str,
    season_name: str,
    episodes: list[Dict[str, Any]],
    *,
    metadata: dict | None = None,
) -> MagicMock:
    """Build a mock Controller with cached_library_data."""
    controller = MagicMock(spec=Controller)
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        series_name: {
            "metadata": metadata
            or {
                "tmdb_name": "Test Series",
                "overview": "A series overview.",
                "poster_path": "",
            },
            "seasons": {
                season_name: {
                    "metadata": {},
                    "episodes": episodes,
                }
            },
        }
    }
    return controller


def _make_empty_controller() -> MagicMock:
    """Build a mock Controller with empty cached data."""
    controller = MagicMock(spec=Controller)
    controller.current_library_name = "TV"
    controller.cached_library_data = {}
    return controller


def _make_real_pixmap(*args: Any, **kwargs: Any) -> MagicMock:
    """Return a mock QPixmap that is not null and has scaled() returning non-null."""
    mock = MagicMock()
    mock.isNull.return_value = False
    mock.scaled.return_value = MagicMock()
    return mock


# ── Series not found guard ──────────────────────────────────────────


class TestSeriesNotFound:
    def test_display_season_with_missing_series(self, qtbot: Any) -> None:
        """Lines 236-238: series not in cached data."""
        controller = _make_empty_controller()
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view.display_season("Nonexistent Series", "Season 1")
        assert "not found" in view._title_label.text().lower()


# ── Season not found guard ──────────────────────────────────────────


class TestSeasonNotFound:
    def test_display_season_with_missing_season(self, qtbot: Any) -> None:
        """Lines 330-334: season not in series data."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view.display_season("Test Series", "Nonexistent Season")
        assert "not found" in view._title_label.text().lower()


# ── Poster loaded from real file path ───────────────────────────────


class TestPosterLoading:
    def test_poster_loaded_from_real_file(self, qtbot: Any, tmp_path: Path) -> None:
        """Lines 345-355: QPixmap loading with real file on disk."""
        poster_file = tmp_path / "poster.jpg"
        poster_file.write_bytes(b"\xff\xd8\xff\xe0")

        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        metadata = {
            "tmdb_name": "Test Series",
            "overview": "Overview.",
            "poster_path": str(poster_file),
        }
        controller = _make_controller_with_data(
            "Test Series", "Season 1", episodes, metadata=metadata
        )
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with (
            patch(
                "lan_streamer.ui_views.season_detail.QPixmap",
                side_effect=_make_real_pixmap,
            ),
            patch.object(view._poster_label, "setPixmap"),
        ):
            view.display_season("Test Series", "Season 1")

    def test_poster_null_pixmap_shows_no_poster(
        self, qtbot: Any, tmp_path: Path
    ) -> None:
        """Lines 356-358: when pixmap is null, shows 'No Poster'."""
        poster_file = tmp_path / "poster.jpg"
        poster_file.write_bytes(b"\xff\xd8\xff\xe0")

        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        metadata = {
            "tmdb_name": "Test Series",
            "overview": "Overview.",
            "poster_path": str(poster_file),
        }
        controller = _make_controller_with_data(
            "Test Series", "Season 1", episodes, metadata=metadata
        )
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = True
        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", return_value=mock_pixmap
        ):
            view.display_season("Test Series", "Season 1")
        assert "No Poster" in view._poster_label.text()


# ── Context menu actions ────────────────────────────────────────────


class TestContextMenuActions:
    def test_context_menu_no_item_clicked(self, qtbot: Any) -> None:
        """Line 456: context menu on empty area returns early."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", side_effect=_make_real_pixmap
        ):
            view.display_season("Test Series", "Season 1")

        mock_table = MagicMock()
        mock_table.itemAt.return_value = None
        with patch.object(view, "_episode_table", mock_table):
            view._episode_table.customContextMenuRequested.emit(QPoint(0, 0))

    def test_context_menu_episode_without_path(self, qtbot: Any) -> None:
        """Lines 459-460: episode with no path, menu does not open."""
        episodes = [
            {
                "name": "Missing",
                "tmdb_number": 1,
                "path": None,
                "watched": False,
                "air_date": "2099-01-01",
            }
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", side_effect=_make_real_pixmap
        ):
            view.display_season("Test Series", "Season 1")

        mock_item = MagicMock()
        mock_item.row.return_value = 0
        mock_table = MagicMock()
        mock_table.itemAt.return_value = mock_item
        with (
            patch.object(view, "_episode_table", mock_table),
            patch("lan_streamer.ui_views.season_detail.QMenu") as mock_menu_cls,
        ):
            mock_menu_instance = MagicMock()
            mock_menu_cls.return_value = mock_menu_instance
            view._episode_table.customContextMenuRequested.emit(QPoint(0, 0))
            # No path => menu should not be created/executed
            mock_menu_cls.assert_not_called()


# ── Shared file rendering ───────────────────────────────────────────


class TestSharedFileRendering:
    def test_shared_file_amber_color(self, qtbot: Any) -> None:
        """Lines 524-525: shared file uses amber color."""
        shared_path = "/media/Shared.mkv"
        episodes = [
            {
                "name": "Episode 1",
                "tmdb_number": 1,
                "path": shared_path,
                "watched": False,
            },
            {
                "name": "Episode 2",
                "tmdb_number": 2,
                "path": shared_path,
                "watched": False,
            },
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", side_effect=_make_real_pixmap
        ):
            view.display_season("Test Series", "Season 1")

        title_item = view._episode_table.item(0, 1)
        assert title_item is not None
        assert "\u29c9" in title_item.text()

    def test_shared_file_tooltip_shows_episode_numbers(self, qtbot: Any) -> None:
        """Lines 561-567: tooltip shows shared episode numbers."""
        shared_path = "/media/Shared.mkv"
        episodes = [
            {
                "name": "Episode 1",
                "tmdb_number": 1,
                "path": shared_path,
                "watched": False,
            },
            {
                "name": "Episode 2",
                "tmdb_number": 2,
                "path": shared_path,
                "watched": False,
            },
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", side_effect=_make_real_pixmap
        ):
            view.display_season("Test Series", "Season 1")

        title_item = view._episode_table.item(0, 1)
        assert title_item is not None
        tooltip = title_item.toolTip()
        assert "Shared" in tooltip or "2" in tooltip


# ── Missing episode non-ISO date fallback ───────────────────────────


class TestMissingEpisodeNonISODate:
    def test_missing_episode_with_invalid_date_format(self, qtbot: Any) -> None:
        """Lines 539-541: ValueError fallback for non-ISO air_date."""
        past_str = "2020/01/01"
        episodes = [
            {
                "name": "Bad Date Ep",
                "tmdb_number": 1,
                "path": None,
                "watched": False,
                "air_date": past_str,
            }
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", side_effect=_make_real_pixmap
        ):
            view.display_season("Test Series", "Season 1")

        title_item = view._episode_table.item(0, 1)
        assert title_item is not None
        assert "\u2715" in title_item.text()


# ── Mark season watched ─────────────────────────────────────────────


class TestMarkSeasonWatched:
    def test_mark_season_watched_no_data_returns_early(self, qtbot: Any) -> None:
        """Lines 665-666: early return when no series/season selected."""
        controller = _make_empty_controller()
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)
        view._on_mark_season_watched()

    def test_mark_season_watched_toggles_all(self, qtbot: Any) -> None:
        """Lines 663-676: mark season watched toggles all episodes."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            },
            {
                "name": "Ep 2",
                "tmdb_number": 2,
                "path": "/media/Ep2.mkv",
                "watched": False,
            },
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", side_effect=_make_real_pixmap
        ):
            view.display_season("Test Series", "Season 1")

        view._on_mark_season_watched()
        controller.mark_season_watched.assert_called_once_with(
            "Test Series", "Season 1", True
        )

    def test_mark_season_unwatched_when_all_watched(self, qtbot: Any) -> None:
        """Lines 671-674: when all watched, toggles to unwatched."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": True,
            },
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", side_effect=_make_real_pixmap
        ):
            view.display_season("Test Series", "Season 1")

        view._on_mark_season_watched()
        controller.mark_season_watched.assert_called_once_with(
            "Test Series", "Season 1", False
        )


# ── Poster context menu ─────────────────────────────────────────────


class TestPosterContextMenu:
    def test_poster_context_menu_opens(self, qtbot: Any) -> None:
        """Lines 684-688: right-click shows Change Poster menu."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", side_effect=_make_real_pixmap
        ):
            view.display_season("Test Series", "Season 1")

        with patch("lan_streamer.ui_views.season_detail.QMenu") as mock_menu_cls:
            mock_menu_instance = MagicMock()
            mock_menu_cls.return_value = mock_menu_instance
            view._on_poster_context_menu(QPoint(10, 10))
            mock_menu_instance.addAction.assert_called_once()
            mock_menu_instance.exec.assert_called_once()

    def test_open_poster_selector_no_season_name(self, qtbot: Any) -> None:
        """Lines 692-693: early return when no season selected."""
        controller = _make_empty_controller()
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)
        view._current_season_name = None
        view._open_poster_selector()

    def test_open_poster_selector_creates_dialog(self, qtbot: Any) -> None:
        """Lines 694-706: PosterSelectorDialog is opened."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", side_effect=_make_real_pixmap
        ):
            view.display_season("Test Series", "Season 1")

        mock_dialog = MagicMock()
        with patch(
            "lan_streamer.ui_views.dialogs.poster_selector.PosterSelectorDialog",
            return_value=mock_dialog,
        ):
            view._open_poster_selector()
            mock_dialog.exec.assert_called_once()

    def test_on_poster_updated_sets_pixmap(self, qtbot: Any, tmp_path: Path) -> None:
        """Lines 710-712: _on_poster_updated sets new pixmap."""
        poster_file = tmp_path / "new_poster.jpg"
        poster_file.write_bytes(b"\xff\xd8\xff\xe0")

        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with (
            patch(
                "lan_streamer.ui_views.season_detail.QPixmap",
                side_effect=_make_real_pixmap,
            ),
            patch.object(view._poster_label, "setPixmap"),
        ):
            view.display_season("Test Series", "Season 1")
            view._on_poster_updated(str(poster_file))

    def test_on_poster_updated_null_pixmap(self, qtbot: Any, tmp_path: Path) -> None:
        """Lines 710-712: null pixmap does not set."""
        poster_file = tmp_path / "bad_poster.jpg"
        poster_file.write_bytes(b"\xff\xd8\xff\xe0")

        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        null_pixmap = MagicMock()
        null_pixmap.isNull.return_value = True
        with patch(
            "lan_streamer.ui_views.season_detail.QPixmap", return_value=null_pixmap
        ):
            view.display_season("Test Series", "Season 1")
            view._on_poster_updated(str(poster_file))


# ── TMDB auto-search and dialog ─────────────────────────────────────


class TestTMDbAutoSearch:
    def test_auto_search_with_results_and_dialog_accepted(self, qtbot: Any) -> None:
        """Lines 992-1010: auto-search finds results, user accepts."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        metadata = {
            "tmdb_name": "Test Series",
            "overview": "Overview.",
            "poster_path": "",
            "tmdb_identifier": None,
        }
        controller = _make_controller_with_data(
            "Test Series", "Season 1", episodes, metadata=metadata
        )
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        mock_dialog = MagicMock()
        mock_dialog.exec.return_value = QDialog.DialogCode.Accepted
        mock_dialog.selected_id.return_value = 12345
        mock_dialog.selected_title.return_value = "Found Series"
        mock_dialog.selected_season_number.return_value = 1

        with (
            patch(
                "lan_streamer.ui_views.season_detail.QPixmap",
                side_effect=_make_real_pixmap,
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.is_configured",
                return_value=True,
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.get_episodes",
                return_value=[{"id": 100, "name": "Ep 1", "episode_number": 1}],
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.get_episode_groups",
                return_value=[],
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.search_series_full",
                return_value=[{"id": 12345, "name": "Found Series"}],
            ),
            patch(
                "lan_streamer.ui_views.dialogs.tmdb_search_results.TmdbSearchResultsDialog",
                return_value=mock_dialog,
            ),
        ):
            view.display_season("Test Series", "Season 1")

    def test_auto_search_exception_falls_through(self, qtbot: Any) -> None:
        """Lines 992-993: search_series_full raises exception, results empty."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        metadata = {
            "tmdb_name": "Test Series",
            "overview": "Overview.",
            "poster_path": "",
            "tmdb_identifier": None,
        }
        controller = _make_controller_with_data(
            "Test Series", "Season 1", episodes, metadata=metadata
        )
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with (
            patch(
                "lan_streamer.ui_views.season_detail.QPixmap",
                side_effect=_make_real_pixmap,
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.is_configured",
                return_value=True,
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.get_episodes",
                return_value=[],
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.get_episode_groups",
                return_value=[],
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.search_series_full",
                side_effect=Exception("network error"),
            ),
        ):
            view.display_season("Test Series", "Season 1")
            assert view._tmdb_entries == []


class TestTMDbSearch:
    def test_search_tmdb_no_results(self, qtbot: Any) -> None:
        """Lines 1032-1038: no results found for query."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._tmdb_search_input.setText("Nonexistent Show XYZ 999")
        with (
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.search_series_full",
                return_value=[],
            ),
            patch(
                "lan_streamer.ui_views.season_detail.QMessageBox.information"
            ) as mock_info,
        ):
            view._on_search_tmdb()
        mock_info.assert_called_once()

    def test_search_tmdb_exception(self, qtbot: Any) -> None:
        """Lines 1021-1030: exception during search."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._tmdb_search_input.setText("Test")
        with (
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.search_series_full",
                side_effect=Exception("network error"),
            ),
            patch(
                "lan_streamer.ui_views.season_detail.QMessageBox.warning"
            ) as mock_warn,
        ):
            view._on_search_tmdb()
        mock_warn.assert_called_once()

    def test_add_tmdb_entry_no_query(self, qtbot: Any) -> None:
        """Lines 1054-1061: no query entered."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._tmdb_search_input.setText("")
        with patch(
            "lan_streamer.ui_views.season_detail.QMessageBox.information"
        ) as mock_info:
            view._on_add_tmdb_entry()
        mock_info.assert_called_once()

    def test_add_tmdb_entry_no_results(self, qtbot: Any) -> None:
        """Lines 1070-1076: no results found."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._tmdb_search_input.setText("Unknown Show")
        with (
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.search_series_full",
                return_value=[],
            ),
            patch(
                "lan_streamer.ui_views.season_detail.QMessageBox.information"
            ) as mock_info,
        ):
            view._on_add_tmdb_entry()
        mock_info.assert_called_once()

    def test_add_tmdb_entry_exception(self, qtbot: Any) -> None:
        """Lines 1063-1068: exception during search."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._tmdb_search_input.setText("Test")
        with (
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.search_series_full",
                side_effect=Exception("fail"),
            ),
            patch(
                "lan_streamer.ui_views.season_detail.QMessageBox.warning"
            ) as mock_warn,
        ):
            view._on_add_tmdb_entry()
        mock_warn.assert_called_once()

    def test_search_tmdb_with_results_and_accepted(self, qtbot: Any) -> None:
        """Lines 1044-1050: dialog accepted with selected entry."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)
        view._tmdb_local_episodes = []

        mock_dialog = MagicMock()
        mock_dialog.exec.return_value = QDialog.DialogCode.Accepted
        mock_dialog.selected_id.return_value = 99999
        mock_dialog.selected_title.return_value = "Found It"
        mock_dialog.selected_season_number.return_value = 1

        view._tmdb_search_input.setText("Test")
        with (
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.search_series_full",
                return_value=[{"id": 99999, "name": "Found It"}],
            ),
            patch(
                "lan_streamer.ui_views.dialogs.tmdb_search_results.TmdbSearchResultsDialog",
                return_value=mock_dialog,
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.get_episodes",
                return_value=[{"id": 100, "name": "Ep 1", "episode_number": 1}],
            ),
            patch("lan_streamer.ui_views.season_detail.QMessageBox.information"),
        ):
            view._on_search_tmdb()

    def test_add_tmdb_entry_with_results_and_accepted(self, qtbot: Any) -> None:
        """Lines 1082-1088: append accepted entry."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)
        view._tmdb_local_episodes = []

        mock_dialog = MagicMock()
        mock_dialog.exec.return_value = QDialog.DialogCode.Accepted
        mock_dialog.selected_id.return_value = 88888
        mock_dialog.selected_title.return_value = "Another Series"
        mock_dialog.selected_season_number.return_value = 2

        view._tmdb_search_input.setText("Test")
        with (
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.search_series_full",
                return_value=[{"id": 88888, "name": "Another Series"}],
            ),
            patch(
                "lan_streamer.ui_views.dialogs.tmdb_search_results.TmdbSearchResultsDialog",
                return_value=mock_dialog,
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.get_episodes",
                return_value=[{"id": 200, "name": "Ep 1", "episode_number": 1}],
            ),
            patch("lan_streamer.ui_views.season_detail.QMessageBox.information"),
        ):
            view._on_add_tmdb_entry()


# ── MAL search ──────────────────────────────────────────────────────


class TestMALSearch:
    def test_search_mal_no_query(self, qtbot: Any) -> None:
        """Lines 1577-1578: empty query returns early."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._mal_search_input.setText("")
        view._on_search_mal()

    def test_search_mal_exception(self, qtbot: Any) -> None:
        """Lines 1582-1589: exception during search."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._mal_search_input.setText("Test")
        with (
            patch(
                "lan_streamer.ui_views.season_detail.myanimelist_client.search_anime",
                side_effect=Exception("fail"),
            ),
            patch(
                "lan_streamer.ui_views.season_detail.QMessageBox.warning"
            ) as mock_warn,
        ):
            view._on_search_mal()
        mock_warn.assert_called_once()

    def test_search_mal_no_results(self, qtbot: Any) -> None:
        """Lines 1591-1597: no results found."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._mal_search_input.setText("Unknown Show")
        with (
            patch(
                "lan_streamer.ui_views.season_detail.myanimelist_client.search_anime",
                return_value=[],
            ),
            patch(
                "lan_streamer.ui_views.season_detail.QMessageBox.information"
            ) as mock_info,
        ):
            view._on_search_mal()
        mock_info.assert_called_once()

    def test_add_mal_entry_no_query(self, qtbot: Any) -> None:
        """Lines 1612-1618: no query entered."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._mal_search_input.setText("")
        with patch(
            "lan_streamer.ui_views.season_detail.QMessageBox.information"
        ) as mock_info:
            view._on_add_mal_entry()
        mock_info.assert_called_once()

    def test_add_mal_entry_no_results(self, qtbot: Any) -> None:
        """Lines 1629-1635: no results found."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._mal_search_input.setText("Unknown")
        with (
            patch(
                "lan_streamer.ui_views.season_detail.myanimelist_client.search_anime",
                return_value=[],
            ),
            patch(
                "lan_streamer.ui_views.season_detail.QMessageBox.information"
            ) as mock_info,
        ):
            view._on_add_mal_entry()
        mock_info.assert_called_once()

    def test_add_mal_entry_exception(self, qtbot: Any) -> None:
        """Lines 1620-1627: exception during search."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._mal_search_input.setText("Test")
        with (
            patch(
                "lan_streamer.ui_views.season_detail.myanimelist_client.search_anime",
                side_effect=Exception("fail"),
            ),
            patch(
                "lan_streamer.ui_views.season_detail.QMessageBox.warning"
            ) as mock_warn,
        ):
            view._on_add_mal_entry()
        mock_warn.assert_called_once()


class TestMALEntrySelected:
    def test_mal_entry_selected_fetch_error(self, qtbot: Any) -> None:
        """Lines 1660-1665: get_anime_details raises exception."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with (
            patch(
                "lan_streamer.ui_views.season_detail.myanimelist_client.get_anime_details",
                side_effect=Exception("network error"),
            ),
            patch(
                "lan_streamer.ui_views.season_detail.QMessageBox.warning"
            ) as mock_warn,
        ):
            view._on_mal_entry_selected(12345)
        mock_warn.assert_called_once()

    def test_append_mal_entry_fetch_error(self, qtbot: Any) -> None:
        """Lines 1677-1682: get_anime_details raises exception."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        controller = _make_controller_with_data("Test Series", "Season 1", episodes)
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        with (
            patch(
                "lan_streamer.ui_views.season_detail.myanimelist_client.get_anime_details",
                side_effect=Exception("network error"),
            ),
            patch(
                "lan_streamer.ui_views.season_detail.QMessageBox.warning"
            ) as mock_warn,
        ):
            view._append_mal_entry(12345, "Test Anime")
        mock_warn.assert_called_once()

    def test_mal_entry_selected_zero_id(self, qtbot: Any) -> None:
        """Lines 1655-1656: early return when anime_id is 0."""
        controller = _make_controller_with_data("Test Series", "Season 1", [])
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        view._on_mal_entry_selected(0)
        assert view._mal_selected_anime_id == 0
        assert view._mal_entries == []


# ── Display group re-ordering fallback ──────────────────────────────


class TestDisplayGroupFallback:
    def test_no_subgroup_matched_logs_warning(self, qtbot: Any) -> None:
        """Lines 884-892: when no subgroup matched by season number or name."""
        episodes = [
            {
                "name": "Pilot",
                "tmdb_number": 1,
                "path": "/media/Pilot.mkv",
                "watched": False,
            }
        ]
        metadata = {
            "tmdb_name": "Test Series",
            "overview": "Overview.",
            "poster_path": "",
            "tmdb_identifier": "12345",
        }
        controller = _make_controller_with_data(
            "Test Series", "Season 1", episodes, metadata=metadata
        )
        view = SeasonDetailView(controller)
        qtbot.addWidget(view)

        fake_group = {
            "groups": [
                {
                    "id": "group1",
                    "name": "Arc 1",
                    "episodes": [
                        {
                            "id": 99999,
                            "name": "Missing Ep",
                            "episode_number": 1,
                            "season_number": 99,
                            "order": 0,
                            "air_date": "2020-01-01",
                            "runtime": 30,
                        }
                    ],
                }
            ]
        }

        with (
            patch(
                "lan_streamer.ui_views.season_detail.QPixmap",
                side_effect=_make_real_pixmap,
            ),
            patch(
                "lan_streamer.ui_views.season_detail.config.get_series_preference",
                return_value="group_1",
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.get_episode_group_details",
                return_value=fake_group,
            ),
            patch(
                "lan_streamer.ui_views.season_detail.tmdb_client.get_episode_groups",
                return_value=[],
            ),
        ):
            view.display_season("Test Series", "Season 1")
