from unittest.mock import patch
from typing import Any
from PySide6.QtCore import QCoreApplication
from lan_streamer.ui_views import SeriesDetailView, Controller
from lan_streamer.ui_views.dialogs.series_details import SeriesDetailsDialog
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
        mock_open.assert_called_once_with(
            "https://www.youtube.com/results?search_query=Breaking%20Bad%20trailer"
        )

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


def test_series_details_dialog_manual_mapper(qtbot: Any) -> None:
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
                        {
                            "name": "02 - Cat's in the Bag...",
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

    mock_groups = [
        {
            "id": "group-123",
            "name": "Story Arcs",
            "type": 1,
        }
    ]
    mock_group_details = {
        "id": "group-123",
        "name": "Story Arcs",
        "type": 1,
        "groups": [
            {
                "name": "Arc 1",
                "order": 1,
                "episodes": [
                    {
                        "id": "new-ep-id-1",
                        "name": "Pilot (Arc Name)",
                        "order": 0,
                        "season_number": 1,
                        "episode_number": 1,
                        "air_date": "2008-01-20",
                        "runtime": 58,
                    },
                    {
                        "id": "new-ep-id-2",
                        "name": "Cat's in the Bag... (Arc Name)",
                        "order": 1,
                        "season_number": 1,
                        "episode_number": 2,
                        "air_date": "2008-01-27",
                        "runtime": 48,
                    },
                ],
            }
        ],
    }

    with (
        patch("lan_streamer.ui_views.dialogs.series_details.tmdb_client") as mock_tmdb,
        patch(
            "lan_streamer.ui_views.dialogs.series_details.db.save_library"
        ) as mock_save,
        patch(
            "lan_streamer.ui_views.dialogs.series_details.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch(
            "lan_streamer.ui_views.dialogs.series_details.QMessageBox.information"
        ) as mock_info,
    ):
        mock_tmdb.get_episode_groups.return_value = mock_groups
        mock_tmdb.get_episode_group_details.return_value = mock_group_details

        dialog = SeriesDetailsDialog("Breaking Bad", controller)
        qtbot.addWidget(dialog)
        QCoreApplication.processEvents()

        # Tab widget should have 3 tabs: "Series Info", "Series Metadata", "Manual Metadata Mapper"
        assert dialog.tab_widget.count() == 3
        assert dialog.tab_widget.tabText(0) == "Series Info"
        assert dialog.tab_widget.tabText(1) == "Series Metadata"
        assert dialog.tab_widget.tabText(2) == "Manual Metadata Mapper"

        # Check groups combo
        assert dialog.group_combo.count() == 3
        assert dialog.group_combo.itemText(2) == "Story Arcs"

        # Checkbox should be unchecked initially
        assert dialog.set_default_group_checkbox.isChecked() is False

        # Select Group
        dialog.group_combo.setCurrentIndex(2)

        # Checkbox should be enabled and unchecked
        assert dialog.set_default_group_checkbox.isEnabled() is True
        dialog.set_default_group_checkbox.setChecked(True)

        # Check subgroups combo
        assert dialog.subgroup_combo.count() == 2
        assert dialog.subgroup_combo.itemText(1) == "Arc 1"

        # Select Subgroup
        dialog.subgroup_combo.setCurrentIndex(1)

        # Table should be populated with 2 rows
        assert dialog.mapper_table.rowCount() == 2
        assert dialog.mapper_table.item(0, 0).text() == "E01 - Pilot (Arc Name)"
        assert (
            dialog.mapper_table.item(1, 0).text()
            == "E02 - Cat's in the Bag... (Arc Name)"
        )

        # Set combobox value for E01 to first file (/tv/Breaking Bad/S01E01.mkv)
        # "Unmapped / None" (index 0), S01E01.mkv (index 1), S01E02.mkv (index 2)
        combo_row_0 = dialog.mapper_table.cellWidget(0, 2)
        assert combo_row_0.count() == 3
        assert combo_row_0.itemText(1) == "S01E01.mkv"
        assert combo_row_0.itemText(2) == "S01E02.mkv"

        # Map row 0 to S01E01.mkv
        combo_row_0.setCurrentIndex(1)

        # Map row 1 to S01E02.mkv
        combo_row_1 = dialog.mapper_table.cellWidget(1, 2)
        combo_row_1.setCurrentIndex(2)

        # Click apply manual mappings
        dialog.apply_mapping_btn.click()

        # Check updates are applied in cache
        ep_0 = controller.cached_library_data["Breaking Bad"]["seasons"]["Season 1"][
            "episodes"
        ][0]
        assert ep_0["tmdb_episode_identifier"] == "new-ep-id-1"
        assert ep_0["tmdb_name"] == "Pilot (Arc Name)"

        ep_1 = controller.cached_library_data["Breaking Bad"]["seasons"]["Season 1"][
            "episodes"
        ][1]
        assert ep_1["tmdb_episode_identifier"] == "new-ep-id-2"
        assert ep_1["tmdb_name"] == "Cat's in the Bag... (Arc Name)"

        # Check default group ID is saved
        metadata = controller.cached_library_data["Breaking Bad"]["metadata"]
        assert metadata["tmdb_episode_group_id"] == "group-123"

        mock_save.assert_called_once()
        mock_info.assert_called_once()


def test_series_details_dialog_anime_mal_status(qtbot: Any) -> None:
    from lan_streamer.ui_views.proxy import QMessageBox

    controller = Controller()
    controller.current_library_name = "Anime"
    controller.cached_library_data = {
        "Frieren": {
            "metadata": {
                "tmdb_identifier": "209867",
                "tmdb_name": "Frieren",
            },
            "seasons": {
                "Season 1": {
                    "metadata": {
                        "myanimelist_id": 52991,
                    },
                    "episodes": [
                        {
                            "name": "01 - Journey's End",
                            "path": "/anime/Frieren/S01E01.mkv",
                            "watched": True,
                            "air_date": "2023-09-29",
                            "runtime": 24,
                            "tmdb_episode_identifier": "123",
                            "tmdb_number": 1,
                        }
                    ],
                },
                "Season 2": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "01 - Season 2 Episode 1",
                            "path": "/anime/Frieren/S02E01.mkv",
                            "watched": False,
                            "air_date": "2025-01-01",
                            "runtime": 24,
                            "tmdb_episode_identifier": "456",
                            "tmdb_number": 1,
                        }
                    ],
                },
            },
        }
    }

    # Setup the library config as anime type
    config.libraries = {"Anime": {"type": "anime", "paths": ["/anime"]}}

    with (
        patch(
            "lan_streamer.ui_views.dialogs.series_details.tmdb_client.get_episode_groups",
            return_value=[],
        ),
        patch(
            "lan_streamer.ui_views.dialogs.series_details.myanimelist_client"
        ) as mock_mal_client,
        patch(
            "lan_streamer.ui_views.dialogs.series_details.db.save_library"
        ) as mock_save,
        patch(
            "lan_streamer.ui_views.dialogs.series_details.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch(
            "lan_streamer.ui_views.dialogs.series_details.QMessageBox.information"
        ) as mock_info,
    ):
        mock_mal_client.is_configured.return_value = True
        mock_mal_client.get_anime_details.return_value = {
            "id": 52991,
            "title": "Sousou no Frieren",
            "num_episodes": 28,
        }

        dialog = SeriesDetailsDialog("Frieren", controller)
        qtbot.addWidget(dialog)
        QCoreApplication.processEvents()

        # 1. Verify that the MAL status labels are created in the Series Info tab
        assert hasattr(dialog, "mal_status_labels")
        assert "Season 1" in dialog.mal_status_labels
        assert "Season 2" in dialog.mal_status_labels

        assert "Mapped (MAL ID: 52991)" in dialog.mal_status_labels["Season 1"].text()
        assert dialog.mal_status_labels["Season 2"].text() == "Not Mapped"

        # 2. Simulate mapping Season 2 via the MyAnimeList mapper
        # First, set the combo box to Season 2
        season_idx = dialog.mal_season_combo.findText("Season 2")
        dialog.mal_season_combo.setCurrentIndex(season_idx)

        # Mock search results for mapping
        mock_mal_client.search_anime.return_value = [
            {"id": 99999, "title": "Frieren Season 2", "start_date": "2025-01-01"}
        ]
        dialog.mal_search_input.setText("Frieren Season 2")
        dialog._on_mal_search_clicked()

        # Check results are populated in combo
        assert dialog.mal_search_results_combo.count() == 2
        # Set to the searched result (index 1)
        mock_mal_client.get_anime_details.return_value = {
            "id": 99999,
            "title": "Frieren Season 2",
            "num_episodes": 12,
        }
        dialog.mal_search_results_combo.setCurrentIndex(1)

        # Apply mapping
        dialog.mal_apply_btn.click()

        # Check that it updated the season 2 status label in Series Info tab
        assert "Mapped (MAL ID: 99999)" in dialog.mal_status_labels["Season 2"].text()

        # Check cache updates
        season_2_meta = controller.cached_library_data["Frieren"]["seasons"][
            "Season 2"
        ]["metadata"]
        assert season_2_meta.get("myanimelist_id") == 99999

        mock_save.assert_called_once()
        mock_info.assert_called_once()
