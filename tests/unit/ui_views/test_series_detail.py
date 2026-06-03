from unittest.mock import patch
from typing import Any
from lan_streamer.ui_views import SeriesDetailView, Controller
from lan_streamer.ui_views.dialogs.details import SeriesDetailsDialog
from lan_streamer.system.config import config


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

    # Force clear config preferences to start fresh
    config.series_preferences = {}

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
