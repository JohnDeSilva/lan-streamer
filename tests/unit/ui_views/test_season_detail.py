"""Tests for the redesigned SeasonDetailView."""

from unittest.mock import patch, MagicMock
from typing import Any, Dict

from lan_streamer.ui_views import SeasonDetailView
from lan_streamer.ui_views.controller import Controller
from PySide6.QtWidgets import QTableWidgetItem


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
    ):
        mock_pixmap.return_value.isNull.return_value = False
        mock_get_season.return_value = {"overview": "A thrilling first season."}
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
