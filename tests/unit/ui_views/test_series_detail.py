from typing import Any
from unittest.mock import patch

from lan_streamer.system.config import config
from lan_streamer.ui_views import Controller, SeriesDetailView
from lan_streamer.ui_views.dialogs.series_details import SeriesDetailsDialog


def test_series_detail_view_hide_missing_future(qtbot: Any) -> None:
    controller = Controller()
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        "Breaking Bad": {
            "metadata": {
                "tmdb_name": "Breaking Bad",
                "overview": "A high school chemistry teacher...",
                "poster_path": "/path/to/poster.jpg",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Pilot",
                            "path": "/tv/Breaking Bad/S01E01.mkv",
                            "watched": True,
                            "air_date": "2008-01-20",
                            "runtime": 58,
                            "tmdb_number": 1,
                        },
                        {
                            "name": "Cat's in the Bag...",
                            "path": None,  # missing episode
                            "watched": False,
                            "air_date": "2008-01-27",
                            "runtime": 48,
                            "tmdb_number": 2,
                        },
                        {
                            "name": "Future Episode",
                            "path": None,  # future episode
                            "watched": False,
                            "air_date": "2050-01-01",
                            "runtime": 48,
                            "tmdb_number": 3,
                        },
                    ]
                }
            },
        }
    }

    # Setup database series row to store preferences
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import Series

    with get_session() as session:
        session.query(Series).delete()
        series = Series(library_name="TV", name="Breaking Bad")
        session.add(series)

    view = SeriesDetailView(controller)
    qtbot.addWidget(view)

    # Initial load: hide_missing_future should be False
    with (
        patch("lan_streamer.ui_views.series_detail.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.series_detail.QPixmap") as mock_pixmap,
        patch.object(view.poster_label, "setPixmap"),
    ):
        mock_pixmap.return_value.isNull.return_value = False
        view.populate_series_details("Breaking Bad")

    # Test trailers button click
    with patch("webbrowser.open") as mock_open:
        view.trailers_button.click()
        opened_url = mock_open.call_args.args[0]
        assert "search_query=Breaking%20Bad%20trailer" in opened_url
        assert opened_url.startswith("https://")

    # Season 1 should have 3 episodes in the table (1 local + 2 missing/future)
    season_table = view._season_tables["Season 1"]
    assert season_table.rowCount() == 3

    # Now open SeriesDetailsDialog
    dialog = SeriesDetailsDialog("Breaking Bad", controller)
    qtbot.addWidget(dialog)

    # Assert checkbox exists and is unchecked
    assert dialog.hide_missing_checkbox.isChecked() is False

    # Check the checkbox and save
    dialog.hide_missing_checkbox.setChecked(True)
    dialog._on_save_clicked()

    # Re-verify that the config is updated
    assert (
        config.get_series_preference("TV", "Breaking Bad", "hide_missing_future")
        is True
    )

    # Manually trigger reload to simulate main.py behavior on dialog accept
    with (
        patch("lan_streamer.ui_views.series_detail.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.series_detail.QPixmap") as mock_pixmap,
        patch.object(view.poster_label, "setPixmap"),
    ):
        mock_pixmap.return_value.isNull.return_value = False
        view.populate_series_details("Breaking Bad")

    # Re-fetch the new table reference after repopulation
    season_table = view._season_tables["Season 1"]
    assert season_table.rowCount() == 1
    # Check that it's the Pilot
    assert "Pilot" in season_table.item(0, 1).text()

    # Uncheck the checkbox via another dialog save and verify reload returns row count to 3
    dialog2 = SeriesDetailsDialog("Breaking Bad", controller)
    qtbot.addWidget(dialog2)
    assert dialog2.hide_missing_checkbox.isChecked() is True
    dialog2.hide_missing_checkbox.setChecked(False)
    dialog2._on_save_clicked()

    # Trigger reload
    with (
        patch("lan_streamer.ui_views.series_detail.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.series_detail.QPixmap") as mock_pixmap,
        patch.object(view.poster_label, "setPixmap"),
    ):
        mock_pixmap.return_value.isNull.return_value = False
        view.populate_series_details("Breaking Bad")

    season_table = view._season_tables["Season 1"]
    assert season_table.rowCount() == 3


def test_series_detail_view_alternate_display_groups(qtbot: Any) -> None:
    controller = Controller()
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        "Breaking Bad": {
            "metadata": {
                "tmdb_identifier": "1396",
                "tmdb_name": "Breaking Bad",
                "overview": "A high school chemistry teacher...",
                "poster_path": "/path/to/poster.jpg",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Pilot",
                            "path": "/tv/Breaking Bad/S01E01.mkv",
                            "watched": True,
                            "air_date": "2008-01-20",
                            "runtime": 58,
                            "tmdb_episode_identifier": "62085",
                            "tmdb_number": 1,
                        },
                        {
                            "name": "Cat's in the Bag...",
                            "path": "/tv/Breaking Bad/S01E02.mkv",
                            "watched": False,
                            "air_date": "2008-01-27",
                            "runtime": 48,
                            "tmdb_episode_identifier": "62086",
                            "tmdb_number": 2,
                        },
                    ]
                }
            },
        }
    }

    # Setup database series row to store preferences
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import Series

    with get_session() as session:
        session.query(Series).delete()
        series = Series(library_name="TV", name="Breaking Bad")
        session.add(series)

    # Mock tmdb_client calls
    mock_groups = [
        {
            "id": "alternate-group-1",
            "name": "DVD Order",
            "type": 3,
        }
    ]
    mock_group_details = {
        "id": "alternate-group-1",
        "name": "DVD Order",
        "type": 3,
        "groups": [
            {
                "name": "Beta Season",
                "order": 1,
                "episodes": [
                    {
                        "id": "62086",
                        "name": "Cat's in the Bag... (DVD Title)",
                        "order": 0,
                        "season_number": 1,
                        "episode_number": 2,
                        "air_date": "2008-01-27",
                        "runtime": 48,
                    }
                ],
            },
            {
                "name": "Alpha Season",
                "order": 2,
                "episodes": [
                    {
                        "id": "62085",
                        "name": "Pilot (DVD Title)",
                        "order": 0,
                        "season_number": 1,
                        "episode_number": 1,
                        "air_date": "2008-01-20",
                        "runtime": 58,
                    }
                ],
            },
        ],
    }

    view = SeriesDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.series_detail.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.series_detail.QPixmap") as mock_pixmap,
        patch.object(view.poster_label, "setPixmap"),
        patch("lan_streamer.ui_views.series_detail.tmdb_client") as mock_tmdb,
    ):
        mock_pixmap.return_value.isNull.return_value = False
        mock_tmdb.get_episode_groups.return_value = mock_groups
        mock_tmdb.get_episode_group_details.return_value = mock_group_details

        view.populate_series_details("Breaking Bad")

        # By default, TV Order (Default) should be selected (index 0)
        assert view.order_combo.count() == 2
        assert view.order_combo.itemText(0) == "TV Order (Default)"
        assert view.order_combo.itemText(1) == "DVD Order"
        assert view.order_combo.currentIndex() == 0

        # Change display order to DVD Order
        view.order_combo.setCurrentIndex(1)

        # Tabs should display "Beta Season" first, "Alpha Season" second (chronological order)
        # alphabetical order would put "Alpha Season" first.
        assert view.seasons_tab_widget.count() == 2
        assert view.seasons_tab_widget.tabText(0) == "Beta Season"
        assert view.seasons_tab_widget.tabText(1) == "Alpha Season"

        # Table Beta Season should display Cat's in the Bag
        table_beta = view._season_tables["Beta Season"]
        assert table_beta.rowCount() == 1
        assert "Cat's in the Bag..." in table_beta.item(0, 1).text()
        assert table_beta.item(0, 0).text() == "1"  # Relative number (order + 1)

        # Table Alpha Season should display Pilot
        table_alpha = view._season_tables["Alpha Season"]
        assert table_alpha.rowCount() == 1
        assert "Pilot" in table_alpha.item(0, 1).text()
        assert table_alpha.item(0, 0).text() == "1"  # Relative number (order + 1)


def test_series_details_dialog_lock_toggle(qtbot: Any) -> None:
    controller = Controller()
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        "Breaking Bad": {
            "metadata": {
                "tmdb_identifier": "1396",
                "tmdb_name": "Breaking Bad",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "01 - Pilot",
                            "path": "/tv/Breaking Bad/S01E01.mkv",
                            "watched": True,
                            "air_date": "2008-01-20",
                            "runtime": 58,
                            "tmdb_episode_identifier": "62085",
                            "tmdb_number": 1,
                        },
                    ]
                }
            },
        }
    }

    with patch("lan_streamer.ui_views.dialogs.series_details.db.save_library"):
        dialog = SeriesDetailsDialog("Breaking Bad", controller)
    qtbot.addWidget(dialog)

    assert dialog.tab_widget.count() == 2
    assert dialog.tab_widget.tabText(0) == "Series Info"
    assert dialog.tab_widget.tabText(1) == "Series Metadata"

    dialog.locked_checkbox.setChecked(True)
    with patch.object(controller, "toggle_series_lock") as mock_lock:
        dialog._on_save_clicked()
        mock_lock.assert_called_once_with("Breaking Bad", True)


def test_series_details_dialog_refresh_series(qtbot: Any) -> None:
    from lan_streamer.ui_views.proxy import QMessageBox

    controller = Controller()
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        "Breaking Bad": {
            "metadata": {
                "tmdb_identifier": "1396",
                "tmdb_name": "Breaking Bad",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "01 - Pilot",
                            "path": "/tv/Breaking Bad/S01E01.mkv",
                            "watched": True,
                            "air_date": "2008-01-20",
                            "runtime": 58,
                            "tmdb_episode_identifier": "62085",
                            "tmdb_number": 1,
                        },
                    ]
                }
            },
        }
    }

    with patch("lan_streamer.ui_views.dialogs.series_details.db.save_library"):
        dialog = SeriesDetailsDialog("Breaking Bad", controller)
    qtbot.addWidget(dialog)

    with (
        patch.object(controller, "trigger_series_refresh") as mock_refresh,
        patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ),
    ):
        dialog._on_refresh_clicked()
        mock_refresh.assert_called_once_with("Breaking Bad")


def test_series_detail_view_navigates_back_when_series_removed(qtbot: Any) -> None:
    controller = Controller()
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        "Active Show": {"metadata": {}, "seasons": {}},
    }

    view = SeriesDetailView(controller)
    qtbot.addWidget(view)
    view._current_series_name = "Deleted Show"

    back_requested = False

    def on_back_requested() -> None:
        nonlocal back_requested
        back_requested = True

    view.back_requested.connect(on_back_requested)

    # When library is reloaded without Deleted Show
    view.on_library_loaded()
    assert back_requested is True


def test_series_detail_view_handles_duplicate_series_records(qtbot: Any) -> None:
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import Series, SeriesLibrary

    controller = Controller()
    controller.current_library_name = "TV"

    # Insert two duplicate Series records in the database with the same name
    with get_session() as session:
        series_1 = Series(library_name="TV", name="Duplicate Show")
        series_2 = Series(library_name="TV", name="Duplicate Show")
        session.add_all([series_1, series_2])
        session.flush()
        junction_1 = SeriesLibrary(series_id=series_1.id, library_name="TV")
        junction_2 = SeriesLibrary(series_id=series_2.id, library_name="TV")
        session.add_all([junction_1, junction_2])
        session.commit()

    view = SeriesDetailView(controller)
    qtbot.addWidget(view)
    view._current_series_name = "Duplicate Show"

    # Should not raise MultipleResultsFound and should return one of the IDs
    series_identifier = view._lookup_series_id()
    assert series_identifier is not None

    fetched_id, cast_entries = view._fetch_series_db_and_cast("Duplicate Show")
    assert fetched_id is not None
    assert isinstance(cast_entries, list)


def test_series_detail_view_load_details_async_fault_tolerant(qtbot: Any) -> None:
    import asyncio

    controller = Controller()
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        "Failing Show": {
            "metadata": {
                "tmdb_identifier": "99999",
                "tmdb_name": "Failing Show",
                "overview": "Overview text",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": "/tv/Failing Show/S01E01.mkv",
                            "watched": False,
                            "tmdb_number": 1,
                        }
                    ]
                }
            },
        }
    }

    view = SeriesDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch.object(
            view,
            "_fetch_series_db_and_cast",
            side_effect=RuntimeError("Simulated DB error"),
        ),
        patch(
            "lan_streamer.ui_views.series_detail.tmdb_client.get_episode_groups",
            return_value=[],
        ),
    ):
        asyncio.run(view._load_details_async("Failing Show"))

    # UI update should still have executed despite background error
    assert view.seasons_tab_widget.count() == 1


def test_series_detail_view_mark_series_watched_toggle(qtbot: Any) -> None:
    controller = Controller()
    controller.selected_series_name = "Breaking Bad"
    controller.cached_library_data = {
        "Breaking Bad": {
            "metadata": {"tmdb_name": "Breaking Bad"},
            "metrics": {"total_episodes": 2, "watched_episodes": 0},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"name": "Pilot", "watched": False, "path": "/p1"},
                        {"name": "Ep2", "watched": False, "path": "/p2"},
                    ]
                }
            },
        }
    }

    view = SeriesDetailView(controller)
    qtbot.addWidget(view)
    view.populate_series_details("Breaking Bad")

    assert hasattr(view, "mark_series_button")
    assert view.mark_series_button.text() == "Mark Series as Watched"

    with patch.object(controller, "mark_series_watched") as mock_mark_series:
        view.mark_series_button.click()
        mock_mark_series.assert_called_once_with("Breaking Bad", True)

    # Now test with fully watched series
    controller.cached_library_data["Breaking Bad"]["metrics"]["watched_episodes"] = 2
    view.populate_series_details("Breaking Bad")
    assert view.mark_series_button.text() == "Mark Series as Unwatched"

    with patch.object(controller, "mark_series_watched") as mock_mark_series:
        view.mark_series_button.click()
        mock_mark_series.assert_called_once_with("Breaking Bad", False)
