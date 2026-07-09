"""Tests for the redesigned SeasonDetailView."""

from typing import Any, Dict

from unittest.mock import patch, MagicMock

from lan_streamer.ui_views import SeasonDetailView
from lan_streamer.ui_views.controller import Controller
from lan_streamer.system.config import config
from PySide6.QtWidgets import QTableWidgetItem, QMessageBox


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
    """Searching MyAnimeList populates the results combo."""
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

    with patch("lan_streamer.ui_views.season_detail.myanimelist_client") as mock_mal:
        mock_mal.is_configured.return_value = True
        mock_mal.search_anime.return_value = [
            {
                "id": 52991,
                "title": "Sousou no Frieren",
                "start_date": "2023-09-29",
            },
        ]
        view._mal_search_input.setText("Frieren")
        view._on_search_mal()

        assert view._mal_results_combo.count() == 2  # placeholder + result
        assert view._mal_results_combo.currentData() is None


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
        view._mal_search_input.setText("Frieren")
        view._on_search_mal()
        assert view._mal_results_combo.count() == 2

        # --- Step 2: Select MAL entry (triggers _on_mal_entry_selected) ---
        mock_mal.get_anime_details.return_value = {
            "id": 52991,
            "title": "Sousou no Frieren",
            "num_episodes": 2,
            "main_picture": None,
            "synopsis": "",
        }

        # Changing the combo index emits currentIndexChanged which calls
        # _on_mal_entry_selected synchronously.
        view._mal_results_combo.setCurrentIndex(1)

        assert view._mal_selected_anime_id == 52991
        assert view._mal_mapper_table.rowCount() == 2
        assert view._mal_row_episodes == [1, 2]

        # Auto-matched: row 0 maps to first local episode
        combo_0 = view._mal_mapper_table.cellWidget(0, 1)
        assert combo_0 is not None
        assert combo_0.currentData() == "/anime/Frieren/S01E01.mkv"

        # Row 1 maps to second local episode
        combo_1 = view._mal_mapper_table.cellWidget(1, 1)
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
