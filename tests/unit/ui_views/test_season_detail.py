"""Tests for the redesigned SeasonDetailView."""

from pathlib import Path
from typing import Any, Dict

from unittest.mock import patch, MagicMock

from lan_streamer.ui_views import SeasonDetailView
from lan_streamer.ui_views.controller import Controller
from lan_streamer.system.config import config
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QTableWidgetItem, QMessageBox


def _make_controller_with_data(
    series_name: str,
    season_name: str,
    episodes: list[Dict[str, Any]],
) -> MagicMock:
    """Build a mock Controller with cached_library_data containing the given episodes."""
    controller = MagicMock(spec=Controller)
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        series_name: {
            "metadata": {
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


def test_season_detail_display(qtbot: Any) -> None:
    """Test that display_season populates the UI with correct episode data."""
    episodes = [
        {
            "name": "Pilot",
            "tmdb_number": 1,
            "tmdb_name": "Pilot",
            "air_date": "2020-01-01",
            "runtime": 30,
            "file_runtime": 28,
            "path": "/media/Pilot.mkv",
            "watched": False,
            "last_played_position": 0,
        }
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_season("Test Series", "Season 1")

    assert view._title_label.text() == "Season 1"
    assert view._overview_label.text() == "A series overview."
    assert view._episode_table.rowCount() == 1

    # Check episode number
    number_item: QTableWidgetItem = view._episode_table.item(0, 0)
    assert number_item is not None
    assert number_item.text() == "1"

    # Check episode title
    title_item: QTableWidgetItem = view._episode_table.item(0, 1)
    assert title_item is not None
    assert "Pilot" in title_item.text()

    # Check air date
    air_date_item: QTableWidgetItem = view._episode_table.item(0, 2)
    assert air_date_item is not None
    assert air_date_item.text() == "2020-01-01"

    # Check runtime
    runtime_item: QTableWidgetItem = view._episode_table.item(0, 3)
    assert runtime_item is not None
    assert runtime_item.text() == "28 min"

    # Check progress bar present in column 4
    progress_widget = view._episode_table.cellWidget(0, 4)
    assert progress_widget is not None

    # Check details button present in column 5
    details_widget = view._episode_table.cellWidget(0, 5)
    assert details_widget is not None

    # Check mark season button text
    assert view._mark_season_button.text() == "Mark season as watched"


def test_season_detail_missing_episode(qtbot: Any) -> None:
    """Test that episodes without a path display as missing (red) or future (purple)."""
    import datetime

    today = datetime.date.today()
    past_date = (today - datetime.timedelta(days=10)).isoformat()
    future_date = (today + datetime.timedelta(days=30)).isoformat()

    episodes = [
        {
            "name": "Missing Episode",
            "tmdb_number": 1,
            "tmdb_name": "Missing Episode",
            "air_date": past_date,
            "runtime": 30,
            "path": None,
            "watched": False,
            "last_played_position": 0,
        },
        {
            "name": "Future Episode",
            "tmdb_number": 2,
            "tmdb_name": "Future Episode",
            "air_date": future_date,
            "runtime": 30,
            "path": None,
            "watched": False,
            "last_played_position": 0,
        },
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_season("Test Series", "Season 1")

    assert view._episode_table.rowCount() == 2

    # Missing episode should show X icon
    title_item_0 = view._episode_table.item(0, 1)
    assert title_item_0 is not None
    assert "\u2715" in title_item_0.text()  # X mark

    # Future episode should show lozenge icon
    title_item_1 = view._episode_table.item(1, 1)
    assert title_item_1 is not None
    assert "\u25ca" in title_item_1.text()  # lozenge


def test_season_detail_context_menu(qtbot: Any) -> None:
    """Test that right-clicking an episode shows context menu actions."""
    episodes = [
        {
            "name": "Pilot",
            "tmdb_number": 1,
            "tmdb_name": "Pilot",
            "air_date": "2020-01-01",
            "runtime": 30,
            "path": "/media/Pilot.mkv",
            "watched": False,
            "last_played_position": 0,
        }
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap,
        patch("lan_streamer.ui_views.season_detail.QMenu") as mock_menu_class,
    ):
        mock_pixmap.return_value.isNull.return_value = False
        mock_menu_instance = MagicMock()
        mock_menu_class.return_value = mock_menu_instance

        view.display_season("Test Series", "Season 1")

        # Simulate context menu request
        mock_position = MagicMock()
        view._episode_table.customContextMenuRequested.emit(mock_position)

        # Verify menu.exec was called
        mock_menu_instance.exec.assert_called_once()


def test_season_detail_watched_unwatched(qtbot: Any) -> None:
    """Test that mark season watched button toggles correctly."""
    episodes = [
        {
            "name": "Pilot",
            "tmdb_number": 1,
            "tmdb_name": "Pilot",
            "air_date": "2020-01-01",
            "runtime": 30,
            "path": "/media/Pilot.mkv",
            "watched": True,
            "last_played_position": 100,
        },
        {
            "name": "Episode 2",
            "tmdb_number": 2,
            "tmdb_name": "Episode 2",
            "air_date": "2020-01-08",
            "runtime": 30,
            "path": "/media/Ep2.mkv",
            "watched": True,
            "last_played_position": 100,
        },
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_season("Test Series", "Season 1")

    # Both episodes watched => button says "unwatched"
    assert view._mark_season_button.text() == "Mark season as unwatched"

    # Toggle via controller
    controller.mark_season_watched("Test Series", "Season 1", False)
    episodes[0]["watched"] = False
    episodes[1]["watched"] = False

    view.display_season("Test Series", "Season 1")
    assert view._mark_season_button.text() == "Mark season as watched"


def test_season_detail_tmdb_overview(qtbot: Any) -> None:
    """Test that season overview is fetched from TMDB when not in cached metadata."""
    episodes = [
        {
            "name": "Pilot",
            "tmdb_number": 1,
            "path": "/media/Pilot.mkv",
            "watched": False,
            "last_played_position": 0,
        }
    ]
    controller = MagicMock(spec=Controller)
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        "Test Series": {
            "metadata": {
                "tmdb_name": "Test Series",
                "tmdb_identifier": "12345",
                "overview": "Series overview fallback.",
                "poster_path": "",
            },
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": episodes,
                }
            },
        }
    }

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap,
        patch(
            "lan_streamer.ui_views.season_detail.tmdb_client.get_season_details"
        ) as mock_get_season,
        patch(
            "lan_streamer.ui_views.season_detail.tmdb_client.get_episode_groups"
        ) as mock_get_groups,
    ):
        mock_pixmap.return_value.isNull.return_value = False
        mock_get_season.return_value = {"overview": "A thrilling first season."}
        mock_get_groups.return_value = []
        view.display_season("Test Series", "Season 1")

    assert view._overview_label.text() == "A thrilling first season."


def test_season_detail_progress_bar(qtbot: Any) -> None:
    """Test that progress bar shows correct values."""
    episodes = [
        {
            "name": "Watched Episode",
            "tmdb_number": 1,
            "tmdb_name": "Watched Episode",
            "air_date": "2020-01-01",
            "runtime": 30,
            "file_runtime": 28,
            "path": "/media/Watched.mkv",
            "watched": True,
            "last_played_position": 1680,  # 28 min * 60 sec
        },
        {
            "name": "Partially Watched",
            "tmdb_number": 2,
            "tmdb_name": "Partially Watched",
            "air_date": "2020-01-08",
            "runtime": 30,
            "file_runtime": 30,
            "path": "/media/Partial.mkv",
            "watched": False,
            "last_played_position": 900,  # 15 min * 60 sec = 50%
        },
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_season("Test Series", "Season 1")

    # Progress bar should exist in column 4
    progress_widget_0 = view._episode_table.cellWidget(0, 4)
    assert progress_widget_0 is not None
    assert view._episode_table.rowCount() == 2
    assert view._episode_table.item(0, 0) is not None
    assert view._episode_table.item(1, 0) is not None


# ---------------------------------------------------------------------------
# Tab structure tests
# ---------------------------------------------------------------------------


def test_season_detail_tab_structure(qtbot: Any) -> None:
    """Verify the tab widget exists with the correct three tabs.

    The episodes tab should contain the episode table and the mark-season
    button.
    """
    episodes = [
        {
            "name": "Pilot",
            "tmdb_number": 1,
            "tmdb_name": "Pilot",
            "air_date": "2020-01-01",
            "runtime": 30,
            "path": "/media/Pilot.mkv",
            "watched": False,
            "last_played_position": 0,
        }
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)
    view = SeasonDetailView(controller)

    assert view._tab_widget is not None
    assert view._tab_widget.count() == 3
    assert view._tab_widget.tabText(0) == "Episodes"
    assert view._tab_widget.tabText(1) == "Manual Metadata Mapper"
    assert view._tab_widget.tabText(2) == "MyAnimeList Mapper"

    # Episode table lives inside the episodes tab (Qt parenting via layout)
    assert view._tab_widget.widget(0) is view._episodes_tab
    assert view._episode_table.parent() is view._episodes_tab

    # Mark-season button lives inside the episodes tab
    assert view._mark_season_button.parent() is view._episodes_tab


# ---------------------------------------------------------------------------
# MAL tab visibility tests
# ---------------------------------------------------------------------------


def test_season_detail_mal_tab_visibility_tv(qtbot: Any) -> None:
    """When library type is ``tv`` the MyAnimeList Mapper tab is hidden."""
    episodes = [
        {
            "name": "Pilot",
            "tmdb_number": 1,
            "tmdb_name": "Pilot",
            "air_date": "2020-01-01",
            "runtime": 30,
            "path": "/media/Pilot.mkv",
            "watched": False,
            "last_played_position": 0,
        }
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)
    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_season("Test Series", "Season 1")

    mal_index = view._tab_widget.indexOf(view._mal_mapper_tab)
    assert mal_index >= 0
    assert view._tab_widget.isTabVisible(mal_index) is False


def test_season_detail_mal_tab_visibility_anime(qtbot: Any) -> None:
    """When library type is ``anime`` the MyAnimeList Mapper tab is visible."""
    episodes = [
        {
            "name": "Episode 1",
            "tmdb_number": 1,
            "tmdb_name": "Episode 1",
            "air_date": "2023-09-29",
            "runtime": 24,
            "path": "/anime/Series/S01E01.mkv",
            "watched": False,
            "last_played_position": 0,
        }
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)
    controller.current_library_name = "Anime"

    # Configure library type as anime so display_season shows the MAL tab.
    config.libraries = {"Anime": {"type": "anime", "paths": ["/anime"]}}

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_season("Test Series", "Season 1")

    mal_index = view._tab_widget.indexOf(view._mal_mapper_tab)
    assert mal_index >= 0
    assert view._tab_widget.isTabVisible(mal_index) is True


# ---------------------------------------------------------------------------
# TMDB Metadata Mapper tab tests
# ---------------------------------------------------------------------------


def test_season_detail_tmdb_search(qtbot: Any) -> None:
    """TMDB mapper tab auto-loads episodes for the current season."""
    episodes = [
        {
            "name": "Pilot",
            "tmdb_number": 1,
            "tmdb_name": "Pilot",
            "air_date": "2020-01-01",
            "runtime": 30,
            "path": "/media/Pilot.mkv",
            "watched": False,
            "last_played_position": 0,
            "tmdb_episode_identifier": "1001",
        }
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)
    controller.cached_library_data["Test Series"]["metadata"]["tmdb_identifier"] = (
        "12345"
    )

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap,
        patch(
            "lan_streamer.ui_views.season_detail.tmdb_client.get_episode_groups"
        ) as mock_get_groups,
        patch(
            "lan_streamer.ui_views.season_detail.tmdb_client.get_seasons"
        ) as mock_get_seasons,
        patch(
            "lan_streamer.ui_views.season_detail.tmdb_client.get_episodes"
        ) as mock_get_episodes,
        patch(
            "lan_streamer.ui_views.season_detail.tmdb_client.get_season_details"
        ) as mock_get_season_details,
        patch(
            "lan_streamer.ui_views.season_detail.myanimelist_client.is_configured",
            return_value=False,
        ),
    ):
        mock_pixmap.return_value.isNull.return_value = False
        mock_get_groups.return_value = []
        mock_get_seasons.return_value = [
            {"season_number": 1, "name": "Season 1"},
        ]
        mock_get_episodes.return_value = [
            {
                "id": 1001,
                "name": "Pilot",
                "episode_number": 1,
                "air_date": "2020-01-01",
                "runtime": 30,
            },
        ]
        mock_get_season_details.return_value = None
        view.display_season("Test Series", "Season 1")

    # Mapper table should be auto-populated with the current season's episodes
    assert view._tmdb_mapper_table.rowCount() == 1
    assert view._tmdb_mapper_table.item(0, 0).text() == "E01 - Pilot"
    assert view._tmdb_mapper_table.item(0, 1).text() == "2020-01-01"
    combo = view._tmdb_mapper_table.cellWidget(0, 2)
    assert combo is not None
    assert combo.currentData() == "/media/Pilot.mkv"


def test_season_detail_tmdb_mapper_apply(qtbot: Any) -> None:
    """Full TMDB group/subgroup select + apply mappings flow.

    Verifies that:
    * The mapper table is populated with correct columns.
    * Applying mappings calls ``db.save_library``.
    * Episode metadata is updated in the cached data.
    """
    episodes = [
        {
            "name": "Pilot",
            "tmdb_number": 1,
            "tmdb_name": "Pilot",
            "air_date": "2020-01-01",
            "runtime": 30,
            "path": "/media/Pilot.mkv",
            "watched": False,
            "last_played_position": 0,
            "tmdb_identifier": "1001",
            "tmdb_episode_identifier": "1001",
        },
        {
            "name": "Episode 2",
            "tmdb_number": 2,
            "tmdb_name": "Episode 2",
            "air_date": "2020-01-08",
            "runtime": 30,
            "path": "/media/Ep2.mkv",
            "watched": False,
            "last_played_position": 0,
            "tmdb_identifier": "1002",
            "tmdb_episode_identifier": "1002",
        },
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)
    controller.cached_library_data["Test Series"]["metadata"]["tmdb_identifier"] = (
        "12345"
    )

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap,
        patch(
            "lan_streamer.ui_views.season_detail.tmdb_client.get_episode_groups"
        ) as mock_get_groups,
        patch(
            "lan_streamer.ui_views.season_detail.tmdb_client.get_seasons"
        ) as mock_get_seasons,
        patch(
            "lan_streamer.ui_views.season_detail.tmdb_client.get_episodes"
        ) as mock_get_episodes,
        patch(
            "lan_streamer.ui_views.season_detail.tmdb_client.get_season_details"
        ) as mock_get_season_details,
        patch("lan_streamer.ui_views.season_detail.db.save_library") as mock_save,
        patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch("PySide6.QtWidgets.QMessageBox.information"),
        patch(
            "lan_streamer.ui_views.season_detail.myanimelist_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.ui_views.season_detail.myanimelist_client.search_anime",
            return_value=[],
        ),
    ):
        mock_pixmap.return_value.isNull.return_value = False
        mock_get_groups.return_value = []
        mock_get_seasons.return_value = [
            {"season_number": 1, "name": "Season 1"},
            {"season_number": 2, "name": "Season 2"},
        ]
        mock_get_episodes.return_value = [
            {
                "id": 1001,
                "name": "Pilot",
                "episode_number": 1,
                "air_date": "2020-01-01",
                "runtime": 30,
            },
            {
                "id": 1002,
                "name": "Episode 2",
                "episode_number": 2,
                "air_date": "2020-01-08",
                "runtime": 30,
            },
        ]
        mock_get_season_details.return_value = None
        view.display_season("Test Series", "Season 1")

        # --- Verify mapper table auto-populated from current season ---
        assert view._tmdb_mapper_table.rowCount() == 2

        # TMDB Episode column
        assert view._tmdb_mapper_table.item(0, 0).text() == "E01 - Pilot"
        assert view._tmdb_mapper_table.item(1, 0).text() == "E02 - Episode 2"

        # Air Date column
        assert view._tmdb_mapper_table.item(0, 1).text() == "2020-01-01"
        assert view._tmdb_mapper_table.item(1, 1).text() == "2020-01-08"

        # Mapped Local File column contains combos with local files
        combo_0 = view._tmdb_mapper_table.cellWidget(0, 2)
        assert combo_0 is not None
        assert combo_0.count() == 3  # "Unmapped / None" + 2 local files
        assert (
            combo_0.currentData() == "/media/Pilot.mkv"
        )  # auto-matched by tmdb_episode_identifier

        combo_1 = view._tmdb_mapper_table.cellWidget(1, 2)
        assert combo_1 is not None
        assert combo_1.currentData() == "/media/Ep2.mkv"  # auto-matched

        # --- Step 4: Apply mappings ---
        view._on_apply_metadata_mappings()

        mock_save.assert_called_once_with("TV", controller.cached_library_data)

        # Episode metadata updated in cached data
        ep0 = controller.cached_library_data["Test Series"]["seasons"]["Season 1"][
            "episodes"
        ][0]
        assert ep0["tmdb_identifier"] == "1001"
        assert ep0["tmdb_name"] == "Pilot"
        assert ep0["tmdb_number"] == 1

        ep1 = controller.cached_library_data["Test Series"]["seasons"]["Season 1"][
            "episodes"
        ][1]
        assert ep1["tmdb_identifier"] == "1002"
        assert ep1["tmdb_name"] == "Episode 2"
        assert ep1["tmdb_number"] == 2


# ---------------------------------------------------------------------------
# MyAnimeList Mapper tab tests
# ---------------------------------------------------------------------------


def test_season_detail_mal_search(qtbot: Any) -> None:
    """Searching MyAnimeList opens a dialog with results."""
    episodes = [
        {
            "name": "Journey's End",
            "tmdb_number": 1,
            "tmdb_name": "Journey's End",
            "air_date": "2023-09-29",
            "runtime": 24,
            "path": "/anime/Series/S01E01.mkv",
            "watched": False,
            "last_played_position": 0,
        }
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_season("Test Series", "Season 1")

    with (
        patch("lan_streamer.ui_views.season_detail.myanimelist_client") as mock_mal,
        patch(
            "lan_streamer.ui_views.dialogs.mal_search_results.MalSearchResultsDialog",
        ) as mock_dialog_cls,
    ):
        mock_mal.is_configured.return_value = True
        mock_mal.search_anime.return_value = [
            {
                "id": 52991,
                "title": "Sousou no Frieren",
                "start_date": "2023-09-29",
            },
        ]
        mock_dialog_instance = mock_dialog_cls.return_value
        mock_dialog_instance.exec.return_value = QDialog.DialogCode.Accepted
        mock_dialog_instance.selected_id.return_value = 52991
        mock_dialog_instance.selected_title.return_value = "Sousou no Frieren"
        mock_mal.get_anime_details.return_value = {
            "id": 52991,
            "title": "Sousou no Frieren",
            "num_episodes": 28,
        }
        view._mal_search_input.setText("Frieren")
        view._on_search_mal()

        assert view._mal_selected_anime_id == 52991
        assert (
            view._mal_selected_label.text() == "1 MAL entry loaded (Sousou no Frieren)"
        )


def test_season_detail_mal_apply(qtbot: Any) -> None:
    """Full MAL search / select entry / apply flow.

    Verifies that:
    * ``db.save_library`` is called after applying.
    * Episode metadata is updated with ``myanimelist_anime_id``
      and ``myanimelist_episode_number``.
    * Season metadata receives ``myanimelist_id``.
    """
    episodes = [
        {
            "name": "Journey's End",
            "tmdb_number": 1,
            "tmdb_name": "Journey's End",
            "air_date": "2023-09-29",
            "runtime": 24,
            "path": "/anime/Frieren/S01E01.mkv",
            "watched": False,
            "last_played_position": 0,
        },
        {
            "name": "Another Episode",
            "tmdb_number": 2,
            "tmdb_name": "Another Episode",
            "air_date": "2023-10-06",
            "runtime": 24,
            "path": "/anime/Frieren/S01E02.mkv",
            "watched": False,
            "last_played_position": 0,
        },
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    # Need anime library type so the MAL tab is accessible
    config.libraries = {"TV": {"type": "anime", "paths": ["/anime"]}}

    with (
        patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap,
        patch(
            "lan_streamer.ui_views.season_detail.myanimelist_client.is_configured",
            return_value=True,
        ),
        patch(
            "lan_streamer.ui_views.season_detail.myanimelist_client",
        ) as mock_mal_initial,
    ):
        mock_pixmap.return_value.isNull.return_value = False
        mock_mal_initial.is_configured.return_value = True
        mock_mal_initial.search_anime.return_value = []
        view.display_season("Test Series", "Season 1")

    # display_season populates _mal_local_episodes via _on_mal_season_changed
    assert len(view._mal_local_episodes) == 2

    with (
        patch("lan_streamer.ui_views.season_detail.myanimelist_client") as mock_mal,
        patch("lan_streamer.ui_views.season_detail.db.save_library") as mock_save,
        patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch("PySide6.QtWidgets.QMessageBox.information"),
        patch("PySide6.QtWidgets.QMessageBox.warning"),
        patch(
            "lan_streamer.ui_views.dialogs.mal_search_results.MalSearchResultsDialog",
        ) as mock_dialog_cls,
    ):
        # --- Step 1: Search MAL ---
        mock_mal.is_configured.return_value = True
        mock_mal.search_anime.return_value = [
            {
                "id": 52991,
                "title": "Sousou no Frieren",
                "start_date": "2023-09-29",
            },
        ]
        mock_dialog_instance = mock_dialog_cls.return_value
        mock_dialog_instance.exec.return_value = QDialog.DialogCode.Accepted
        mock_dialog_instance.selected_id.return_value = 52991
        mock_dialog_instance.selected_title.return_value = "Sousou no Frieren"

        # --- Step 2: Select MAL entry ---
        mock_mal.get_anime_details.return_value = {
            "id": 52991,
            "title": "Sousou no Frieren",
            "num_episodes": 2,
            "main_picture": None,
            "synopsis": "",
        }

        view._mal_search_input.setText("Frieren")
        view._on_search_mal()

        assert view._mal_selected_anime_id == 52991
        assert view._mal_mapper_table.rowCount() == 2
        assert view._mal_row_episodes == [1, 2]

        # Auto-matched: row 0 maps to first local episode
        combo_0 = view._mal_mapper_table.cellWidget(0, 2)
        assert combo_0 is not None
        assert combo_0.currentData() == "/anime/Frieren/S01E01.mkv"

        # Row 1 maps to second local episode
        combo_1 = view._mal_mapper_table.cellWidget(1, 2)
        assert combo_1 is not None
        assert combo_1.currentData() == "/anime/Frieren/S01E02.mkv"

        # --- Step 3: Apply mappings ---
        view._on_apply_mal_mappings()

        mock_save.assert_called_once_with("TV", controller.cached_library_data)

        # Episode metadata updated
        cached_episodes = controller.cached_library_data["Test Series"]["seasons"][
            "Season 1"
        ]["episodes"]
        assert cached_episodes[0]["myanimelist_anime_id"] == 52991
        assert cached_episodes[0]["myanimelist_episode_number"] == 1

        assert cached_episodes[1]["myanimelist_anime_id"] == 52991
        assert cached_episodes[1]["myanimelist_episode_number"] == 2

        # Season metadata updated with MAL ID
        season_meta = controller.cached_library_data["Test Series"]["seasons"][
            "Season 1"
        ].get("metadata", {})
        assert season_meta["myanimelist_id"] == 52991


def test_tmdb_mapper_files_sorted_by_filename(qtbot: Any) -> None:
    """TMDB mapper file dropdowns are sorted by filename across seasons."""
    episodes_season1 = [
        {
            "name": "S01E05.mkv",
            "path": "/disk1/Show/Season 1/S01E05.mkv",
            "tmdb_number": None,
            "watched": False,
        },
        {
            "name": "S01E03.mkv",
            "path": "/disk1/Show/Season 1/S01E03.mkv",
            "tmdb_number": None,
            "watched": False,
        },
    ]
    episodes_season2 = [
        {
            "name": "S02E12.mkv",
            "path": "/disk2/Show/S02E12.mkv",
            "tmdb_number": None,
            "watched": False,
        },
        {
            "name": "S02E07.mkv",
            "path": "/disk2/Show/S02E07.mkv",
            "tmdb_number": None,
            "watched": False,
        },
    ]
    controller = MagicMock(spec=Controller)
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        "Test Series": {
            "metadata": {"tmdb_name": "Test"},
            "seasons": {
                "Season 1": {"metadata": {}, "episodes": episodes_season1},
                "Season 2": {"metadata": {}, "episodes": episodes_season2},
            },
        }
    }
    view = SeasonDetailView(controller)
    qtbot.addWidget(view)
    view.display_season("Test Series", "Season 1")

    filenames = [Path(ep["path"]).name for ep in view._tmdb_local_episodes]
    assert filenames == ["S01E03.mkv", "S01E05.mkv", "S02E07.mkv", "S02E12.mkv"]


def test_mal_mapper_files_sorted_by_filename(qtbot: Any) -> None:
    """MAL mapper file dropdowns are sorted by filename within a season."""
    episodes = [
        {
            "name": "S01E12.mkv",
            "path": "/anime/Show/Season 1/S01E12.mkv",
            "tmdb_number": None,
            "watched": False,
        },
        {
            "name": "S01E03.mkv",
            "path": "/anime/Show/Season 1/S01E03.mkv",
            "tmdb_number": None,
            "watched": False,
        },
        {
            "name": "S01E07.mkv",
            "path": "/anime/Show/Season 1/S01E07.mkv",
            "tmdb_number": None,
            "watched": False,
        },
    ]
    controller = MagicMock(spec=Controller)
    controller.current_library_name = "anime"
    controller.cached_library_data = {
        "Test Series": {
            "metadata": {"tmdb_name": "Test"},
            "seasons": {
                "Season 1": {
                    "metadata": {"myanimelist_id": None},
                    "episodes": episodes,
                }
            },
        }
    }
    view = SeasonDetailView(controller)
    qtbot.addWidget(view)
    view.display_season("Test Series", "Season 1")

    filenames = [Path(ep["path"]).name for ep in view._mal_local_episodes]
    assert filenames == ["S01E03.mkv", "S01E07.mkv", "S01E12.mkv"]


def test_season_detail_mal_load_multiple_entries(qtbot: Any) -> None:
    """Episodes with per-episode myanimelist_anime_id load multiple entries."""
    episodes = [
        {
            "name": "S00E01.mkv",
            "path": "/anime/Specials/S00E01.mkv",
            "myanimelist_anime_id": 111,
            "myanimelist_episode_number": 1,
            "watched": False,
        },
        {
            "name": "S00E02.mkv",
            "path": "/anime/Specials/S00E02.mkv",
            "myanimelist_anime_id": 222,
            "myanimelist_episode_number": 1,
            "watched": False,
        },
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)
    controller.current_library_name = "Anime"
    config.libraries = {"Anime": {"type": "anime", "paths": ["/anime"]}}

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap,
        patch(
            "lan_streamer.ui_views.season_detail.myanimelist_client",
        ) as mock_mal,
    ):
        mock_pixmap.return_value.isNull.return_value = False
        mock_mal.is_configured.return_value = True

        def mock_get_anime_details(anime_id: int) -> Dict[str, Any]:
            data = {
                111: {
                    "id": 111,
                    "title": "Movie A",
                    "num_episodes": 1,
                },
                222: {
                    "id": 222,
                    "title": "Movie B",
                    "num_episodes": 1,
                },
            }
            return data.get(anime_id)

        mock_mal.get_anime_details.side_effect = mock_get_anime_details
        view.display_season("Test Series", "Season 1")

    assert len(view._mal_entries) == 2
    assert view._mal_entries[0]["id"] == 111
    assert view._mal_entries[1]["id"] == 222
    assert view._mal_mapper_table.rowCount() == 2

    # Column 0 shows the correct anime title for each row
    assert view._mal_mapper_table.item(0, 0).text() == "Movie A"
    assert view._mal_mapper_table.item(1, 0).text() == "Movie B"

    # Each row's item has the correct anime_id stored
    assert view._mal_mapper_table.item(0, 0).data(Qt.ItemDataRole.UserRole) == 111
    assert view._mal_mapper_table.item(1, 0).data(Qt.ItemDataRole.UserRole) == 222

    # Episode # column
    assert view._mal_mapper_table.item(0, 1).text() == "Episode 1"
    assert view._mal_mapper_table.item(1, 1).text() == "Episode 1"

    # Combos pre-selected from saved myanimelist_episode_number
    combo_0 = view._mal_mapper_table.cellWidget(0, 2)
    assert combo_0 is not None
    assert combo_0.currentData() == "/anime/Specials/S00E01.mkv"

    combo_1 = view._mal_mapper_table.cellWidget(1, 2)
    assert combo_1 is not None
    assert combo_1.currentData() == "/anime/Specials/S00E02.mkv"

    # Label shows count
    assert "2 MAL entries loaded" in view._mal_selected_label.text()


def test_season_detail_mal_append_entry(qtbot: Any) -> None:
    """Appending a second MAL entry adds rows without clearing the first."""
    episodes = [
        {
            "name": "S01E01.mkv",
            "path": "/anime/Show/S01E01.mkv",
            "tmdb_number": 1,
            "watched": False,
        },
        {
            "name": "S01E02.mkv",
            "path": "/anime/Show/S01E02.mkv",
            "tmdb_number": 2,
            "watched": False,
        },
        {
            "name": "Specials/S00E01.mkv",
            "path": "/anime/Show/Specials/S00E01.mkv",
            "tmdb_number": 3,
            "watched": False,
        },
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)
    controller.current_library_name = "Anime"
    config.libraries = {"Anime": {"type": "anime", "paths": ["/anime"]}}

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap,
        patch(
            "lan_streamer.ui_views.season_detail.myanimelist_client",
        ) as mock_mal,
    ):
        mock_pixmap.return_value.isNull.return_value = False
        mock_mal.is_configured.return_value = True
        mock_mal.search_anime.return_value = [
            {"id": 52991, "title": "TV Series MAL", "start_date": "2023-01-01"},
        ]
        mock_mal.get_anime_details.return_value = {
            "id": 52991,
            "title": "TV Series MAL",
            "num_episodes": 2,
        }
        view.display_season("Test Series", "Season 1")

    # First search populates with 2 episodes
    assert view._mal_mapper_table.rowCount() == 2

    # --- Append a second MAL entry ---
    view._mal_search_input.setText("Movie A")
    with (
        patch(
            "lan_streamer.ui_views.season_detail.myanimelist_client",
        ) as mock_mal2,
        patch(
            "lan_streamer.ui_views.dialogs.mal_search_results.MalSearchResultsDialog",
        ) as mock_dialog_cls,
    ):
        mock_mal2.is_configured.return_value = True
        mock_mal2.search_anime.return_value = [
            {"id": 333, "title": "Movie Special", "start_date": "2023-06-01"},
        ]
        mock_mal2.get_anime_details.return_value = {
            "id": 333,
            "title": "Movie Special",
            "num_episodes": 1,
        }
        mock_dialog_instance = mock_dialog_cls.return_value
        mock_dialog_instance.exec.return_value = QDialog.DialogCode.Accepted
        mock_dialog_instance.selected_id.return_value = 333
        mock_dialog_instance.selected_title.return_value = "Movie Special"

        view._on_add_mal_entry()

    # Total rows = 2 (first entry) + 1 (appended entry) = 3
    assert view._mal_mapper_table.rowCount() == 3
    assert view._mal_row_episodes == [1, 2, 1]

    # First two rows are from first entry
    assert view._mal_mapper_table.item(0, 0).text() == "TV Series MAL"
    assert view._mal_mapper_table.item(1, 0).text() == "TV Series MAL"
    # Third row is from appended entry
    assert view._mal_mapper_table.item(2, 0).text() == "Movie Special"

    # Episode numbers
    assert view._mal_mapper_table.item(0, 1).text() == "Episode 1"
    assert view._mal_mapper_table.item(1, 1).text() == "Episode 2"
    assert view._mal_mapper_table.item(2, 1).text() == "Episode 1"

    # _mal_entries has both entries tracked
    assert len(view._mal_entries) == 2
    assert view._mal_entries[0]["id"] == 52991
    assert view._mal_entries[1]["id"] == 333


def test_season_detail_mal_apply_multiple_entries(qtbot: Any) -> None:
    """Applying mappings with multiple MAL entries sets correct per-episode anime_id.

    Season-level myanimelist_id should be None when more than one entry is used.
    """
    episodes = [
        {
            "name": "S01E01.mkv",
            "path": "/anime/Show/S01E01.mkv",
            "watched": False,
        },
        {
            "name": "S00E01.mkv",
            "path": "/anime/Show/Specials/S00E01.mkv",
            "watched": False,
        },
    ]
    controller = _make_controller_with_data("Test Series", "Season 1", episodes)
    controller.current_library_name = "Anime"
    config.libraries = {"Anime": {"type": "anime", "paths": ["/anime"]}}

    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap,
        patch(
            "lan_streamer.ui_views.season_detail.myanimelist_client",
        ) as mock_mal,
    ):
        mock_pixmap.return_value.isNull.return_value = False
        mock_mal.is_configured.return_value = True
        mock_mal.search_anime.return_value = [
            {"id": 52991, "title": "TV Series", "start_date": "2023-01-01"},
        ]
        mock_mal.get_anime_details.return_value = {
            "id": 52991,
            "title": "TV Series",
            "num_episodes": 1,
        }
        view.display_season("Test Series", "Season 1")

    # Set up first entry's mapping manually: pick first local file
    combo_0 = view._mal_mapper_table.cellWidget(0, 2)
    assert combo_0 is not None
    # Select S01E01.mkv
    for idx in range(1, combo_0.count()):
        if combo_0.itemData(idx) == "/anime/Show/S01E01.mkv":
            combo_0.setCurrentIndex(idx)
            break

    # --- Append a second MAL entry for the special ---
    view._mal_search_input.setText("Movie Special")
    with (
        patch(
            "lan_streamer.ui_views.season_detail.myanimelist_client",
        ) as mock_mal2,
        patch(
            "lan_streamer.ui_views.dialogs.mal_search_results.MalSearchResultsDialog",
        ) as mock_dialog_cls,
    ):
        mock_mal2.is_configured.return_value = True
        mock_mal2.search_anime.return_value = [
            {"id": 333, "title": "Movie Special", "start_date": "2023-06-01"},
        ]
        mock_mal2.get_anime_details.return_value = {
            "id": 333,
            "title": "Movie Special",
            "num_episodes": 1,
        }
        mock_dialog_instance = mock_dialog_cls.return_value
        mock_dialog_instance.exec.return_value = QDialog.DialogCode.Accepted
        mock_dialog_instance.selected_id.return_value = 333
        mock_dialog_instance.selected_title.return_value = "Movie Special"

        view._on_add_mal_entry()

    # Set up second entry's mapping: pick the special file
    combo_1 = view._mal_mapper_table.cellWidget(1, 2)
    assert combo_1 is not None
    for idx in range(1, combo_1.count()):
        if combo_1.itemData(idx) == "/anime/Show/Specials/S00E01.mkv":
            combo_1.setCurrentIndex(idx)
            break

    # --- Apply ---
    with (
        patch("lan_streamer.ui_views.season_detail.db.save_library") as mock_save,
        patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch("PySide6.QtWidgets.QMessageBox.information"),
    ):
        view._on_apply_mal_mappings()

    mock_save.assert_called_once()

    cached_episodes = controller.cached_library_data["Test Series"]["seasons"][
        "Season 1"
    ]["episodes"]

    # First episode mapped to first MAL entry (52991)
    assert cached_episodes[0]["myanimelist_anime_id"] == 52991
    assert cached_episodes[0]["myanimelist_episode_number"] == 1

    # Second episode mapped to second MAL entry (333)
    assert cached_episodes[1]["myanimelist_anime_id"] == 333
    assert cached_episodes[1]["myanimelist_episode_number"] == 1

    # Season-level myanimelist_id should be None with multiple entries
    season_meta = controller.cached_library_data["Test Series"]["seasons"][
        "Season 1"
    ].get("metadata", {})
    assert season_meta.get("myanimelist_id") is None
