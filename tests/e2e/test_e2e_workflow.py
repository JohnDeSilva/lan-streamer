import pytest
from unittest.mock import patch, MagicMock, ANY
from typing import Any, Dict, List, Optional
from PySide6.QtWidgets import (
    QPushButton,
    QTableWidget,
    QListWidgetItem,
    QMessageBox,
    QCheckBox,
)

from lan_streamer.ui_views import (
    Controller,
    LibraryGridView,
    SeriesDetailView,
    MetadataMatchDialog,
    JellyfinMatchDialog,
    EpisodeMatchDialog,
    RenamePreviewDialog,
    SettingsDialog,
)
from lan_streamer.system.config import config
from lan_streamer.backend import MetadataApplyWorker as MetadataApplyWorker_real


@pytest.fixture
def sample_library_dictionary(generated_video_asset: str) -> Dict[str, Any]:
    return {
        "Cosmos": {
            "metadata": {
                "overview": "Space exploration documentary.",
                "poster_path": "/path/to/poster.jpg",
                "first_air_date": "1980-09-28",
                "tmdb_name": "Cosmos: A Personal Voyage",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "test_video.mkv",
                            "path": generated_video_asset,
                            "watched": False,
                            "tmdb_number": 1,
                            "tmdb_name": "The Shores of the Cosmic Ocean",
                            "date_added": 1000,
                            "air_date": "1980-09-28",
                            "runtime": 60,
                        },
                        {
                            "name": "ep2.mkv",
                            "path": "/media/Cosmos/Season 1/ep2.mkv",
                            "watched": True,
                            "tmdb_number": 2,
                            "tmdb_name": "One Voice in the Cosmic Fugue",
                            "date_added": 2000,
                            "air_date": "1980-10-05",
                            "runtime": 59,
                        },
                    ]
                }
            },
        }
    }


def test_library_grid_view_rendering(
    sample_library_dictionary: Dict[str, Any], qtbot: Any
) -> None:
    from lan_streamer.system.config import config

    config.enable_combined_view = True
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance._cache_series_metrics()

    with patch("lan_streamer.db.load_library", return_value=sample_library_dictionary):
        grid_view = LibraryGridView(controller_instance)
        qtbot.addWidget(grid_view)

        grid_view.populate_libraries(["Test Lib 1", "Test Lib 2"])
        assert grid_view.library_selector.count() == 3

        # Populate items
        grid_view.library_selector.setCurrentText("Test Lib 1")
        assert grid_view.sort_order_container.isHidden() is False
        grid_view.populate_grid()
        assert grid_view.series_list_widget.count() == 1

        list_item: Optional[QListWidgetItem] = grid_view.series_list_widget.item(0)
        assert list_item is not None
        assert "Cosmos" in list_item.text()
        assert "(1/2)" in list_item.text()

        # Trigger click
        selected_series_emitted: List[str] = []
        controller_instance.series_selected.connect(selected_series_emitted.append)

        grid_view.on_item_clicked(list_item)
        assert selected_series_emitted == ["Cosmos"]

        # Trigger open settings button
        settings_button_instance: Optional[QPushButton] = grid_view.findChild(
            QPushButton, "openSettingsButton"
        )
        assert settings_button_instance is not None

        with patch("lan_streamer.ui_views.SettingsDialog.exec") as mock_exec:
            settings_button_instance.click()
            mock_exec.assert_called_once()


def test_library_grid_view_combined_view(qtbot: Any) -> None:
    from PySide6.QtWidgets import QLabel, QListWidget
    from lan_streamer.system.config import config

    controller_instance = Controller()

    # Configure combined views
    config.enable_combined_view = True
    config.combined_views = [
        {
            "name": "My Next Up",
            "enabled": True,
            "libraries": ["Test Lib 1"],
            "sort_by": "Next Up",
            "filter_mode": "All",
            "max_items": 10,
        },
        {
            "name": "My Recently Added",
            "enabled": True,
            "libraries": ["Test Lib 1"],
            "sort_by": "Recently Added",
            "filter_mode": "All",
            "max_items": 10,
        },
    ]

    import tempfile
    from pathlib import Path

    # Write a tiny valid GIF file
    gif_data = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    temp_dir = tempfile.mkdtemp()
    valid_img_path = str(Path(temp_dir) / "test.gif")
    with open(valid_img_path, "wb") as f:
        f.write(gif_data)

    next_up_mock = [
        {
            "type": "season",
            "series_name": "Cosmos",
            "season_name": "Season 1",
            "poster_path": valid_img_path,
            "library_name": "Test Lib 1",
            "last_played_at": 1000,
            "watched_count": 1,
            "total_count": 5,
        }
    ]

    recently_added_mock = [
        {
            "type": "movie",
            "name": "Avatar",
            "poster_path": "invalid_path.jpg",  # should fall back
            "library_name": "Test Lib 1",
            "date_added": 2000,
            "watched_count": 1,
            "total_count": 1,
        },
        {
            "type": "series",
            "name": "Breaking Bad",
            "poster_path": "",  # empty path fallback
            "library_name": "Test Lib 1",
            "date_added": 1500,
            "watched_count": 0,
            "total_count": 10,
        },
    ]

    def mock_get_combined_smart_row(libraries, sort_by, filter_mode):
        if sort_by == "Next Up":
            return next_up_mock
        elif sort_by == "Recently Added":
            return recently_added_mock
        return []

    with (
        patch(
            "lan_streamer.db.get_combined_smart_row",
            side_effect=mock_get_combined_smart_row,
        ),
        patch("lan_streamer.db.load_library", return_value={}),
    ):
        grid_view = LibraryGridView(controller_instance)
        qtbot.addWidget(grid_view)

        grid_view.populate_libraries(["Test Lib 1"])

        # Verify Combined View is selected and visible
        assert grid_view.library_selector.currentText() == "Combined View"
        assert grid_view.combined_scroll_area.isHidden() is False
        assert grid_view.series_list_widget.isHidden() is True
        assert grid_view.sort_order_container.isHidden() is True

        # Test switching library back to a normal one shows the sort/order container
        grid_view.library_selector.setCurrentText("Test Lib 1")
        assert grid_view.sort_order_container.isHidden() is False

        # Switch back to Combined View for the remainder of the test
        grid_view.library_selector.setCurrentText("Combined View")
        assert grid_view.sort_order_container.isHidden() is True

        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()

        # We should find two headers and lists rendered
        headers = grid_view.combined_scroll_content.findChildren(QLabel)
        header_texts = [h.text() for h in headers]
        assert "<b>My Next Up</b>" in header_texts
        assert "<b>My Recently Added</b>" in header_texts

        list_widgets = grid_view.combined_scroll_content.findChildren(QListWidget)
        assert len(list_widgets) == 2

        # Next Up list should have 1 item
        next_up_list = list_widgets[0]
        assert next_up_list.count() == 1
        item_season = next_up_list.item(0)
        assert "Cosmos\nSeason 1 (1/5)" in item_season.text()

        # Recently Added list should have 2 items
        rec_added_list = list_widgets[1]
        assert rec_added_list.count() == 2
        item_movie = rec_added_list.item(0)
        assert "Avatar\n(Watched)" in item_movie.text()
        item_series = rec_added_list.item(1)
        assert "Breaking Bad\n(0/10)" in item_series.text()

        # Test item clicks
        selected_series_emitted = []
        selected_movies_emitted = []
        controller_instance.series_selected.connect(selected_series_emitted.append)
        controller_instance.movie_selected.connect(selected_movies_emitted.append)

        # 1. Season click (shows series detail)
        config.libraries["Test Lib 1"] = {"type": "tv"}
        with patch("lan_streamer.db.load_library", return_value={"Cosmos": {}}):
            next_up_list.itemClicked.emit(item_season)
            assert controller_instance.current_library_name == "Test Lib 1"
            assert selected_series_emitted == ["Cosmos"]

        # 2. Movie click (shows movie detail)
        selected_series_emitted.clear()
        selected_movies_emitted.clear()
        config.libraries["Test Lib 1"] = {"type": "movie"}
        with patch("lan_streamer.db.load_movie_library", return_value={"Avatar": {}}):
            rec_added_list.itemClicked.emit(item_movie)
            assert controller_instance.current_library_name == "Test Lib 1"
            assert selected_movies_emitted == ["Avatar"]

        # 3. Series click (shows series detail)
        selected_series_emitted.clear()
        selected_movies_emitted.clear()
        config.libraries["Test Lib 1"] = {"type": "tv"}
        with patch("lan_streamer.db.load_library", return_value={"Breaking Bad": {}}):
            rec_added_list.itemClicked.emit(item_series)
            assert controller_instance.current_library_name == "Test Lib 1"
            assert selected_series_emitted == ["Breaking Bad"]

        # Test icon caching (calling _assign_item_icon_with_size again with same cache key)
        from PySide6.QtWidgets import QListWidgetItem

        test_item = QListWidgetItem("Test Cache")
        grid_view._assign_item_icon_with_size(test_item, valid_img_path, 120, 165)
        # Verify icon has been assigned from cache
        assert test_item.icon() is not None

    # Clean up temp dir
    try:
        Path(valid_img_path).unlink()
        Path(temp_dir).rmdir()
    except Exception:
        pass


def test_series_detail_view_rendering(
    sample_library_dictionary: Dict[str, Any], qtbot: Any
) -> None:
    import copy
    import datetime

    today = datetime.date.today()
    future_date = (today + datetime.timedelta(days=10)).isoformat()
    past_date = (today - datetime.timedelta(days=10)).isoformat()

    local_dict = copy.deepcopy(sample_library_dictionary)
    local_dict["Cosmos"]["seasons"]["Season 1"]["episodes"].extend(
        [
            {
                "name": "S01E03 - Missing Episode",
                "path": None,  # Missing
                "watched": False,
                "tmdb_number": 3,
                "tmdb_name": "Missing Episode",
                "date_added": 0,
                "air_date": past_date,
                "runtime": 45,
            },
            {
                "name": "S01E04 - Future Episode",
                "path": None,  # Future
                "watched": False,
                "tmdb_number": 4,
                "tmdb_name": "Future Episode",
                "date_added": 0,
                "air_date": future_date,
                "runtime": 50,
            },
        ]
    )

    controller_instance = Controller()
    controller_instance.cached_library_data = local_dict
    controller_instance._cache_series_metrics()

    detail_view = SeriesDetailView(controller_instance)
    qtbot.addWidget(detail_view)

    with patch(
        "lan_streamer.ui_views.jellyfin_client.is_configured", return_value=True
    ):
        detail_view.populate_series_details("Cosmos")

        assert detail_view.title_label.text() == "Cosmos: A Personal Voyage"
        assert "Space exploration" in detail_view.overview_label.text()
        assert detail_view.seasons_tab_widget.count() == 1
        assert detail_view.seasons_tab_widget.tabText(0) == "Season 1"

    # Verify table row properties
    page_widget: Optional[Any] = detail_view.seasons_tab_widget.widget(0)
    assert page_widget is not None
    table_widget: Optional[Any] = page_widget.findChild(QTableWidget)
    assert isinstance(table_widget, QTableWidget)
    assert table_widget.columnCount() == 5
    assert table_widget.rowCount() == 4

    # Unwatched local episode
    table_item = table_widget.item(0, 1)
    assert table_item is not None
    assert table_item.text() == "●  The Shores of the Cosmic Ocean"
    air_date_item = table_widget.item(0, 2)
    assert air_date_item is not None
    assert air_date_item.text() == "1980-09-28"
    runtime_item = table_widget.item(0, 3)
    assert runtime_item is not None
    assert runtime_item.text() == "60 min"

    # Watched local episode
    table_item_watched = table_widget.item(1, 1)
    assert table_item_watched is not None
    assert table_item_watched.text() == "✓  One Voice in the Cosmic Fugue"

    # Missing episode placeholder
    table_item_missing = table_widget.item(2, 1)
    assert table_item_missing is not None
    assert table_item_missing.text() == "✕  Missing Episode"

    # Future episode placeholder
    table_item_future = table_widget.item(3, 1)
    assert table_item_future is not None
    assert table_item_future.text() == "◊  Future Episode"

    # Verify that disabling show_future_episodes hides the future episode
    controller_instance.current_library_name = "Test Lib"
    config.libraries["Test Lib"] = {
        "type": "tv",
        "paths": [],
        "show_future_episodes": False,
    }

    try:
        detail_view.populate_series_details("Cosmos")

        page_widget_filtered = detail_view.seasons_tab_widget.widget(0)
        assert page_widget_filtered is not None
        table_widget_filtered = page_widget_filtered.findChild(QTableWidget)
        assert isinstance(table_widget_filtered, QTableWidget)
        assert table_widget_filtered.rowCount() == 3
    finally:
        if "Test Lib" in config.libraries:
            del config.libraries["Test Lib"]


def test_series_detail_view_play_next_button(
    sample_library_dictionary: Dict[str, Any], qtbot: Any
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance._cache_series_metrics()

    detail_view = SeriesDetailView(controller_instance)
    qtbot.addWidget(detail_view)

    # Initially, episode 1 is unwatched (watched=False) and episode 2 is watched (watched=True)
    # The first unwatched episode in natural order should be S1:E1.
    detail_view.populate_series_details("Cosmos")

    # Assert play next button is visible and formatted correctly
    assert detail_view.play_next_button.isHidden() is False
    assert detail_view.play_next_button.text() == "▶ PLAY S1:E1"
    assert (
        detail_view._next_episode_path
        == sample_library_dictionary["Cosmos"]["seasons"]["Season 1"]["episodes"][0][
            "path"
        ]
    )

    # Trigger play next button click and assert playback is requested
    playback_paths = []
    controller_instance.playback_requested.connect(playback_paths.append)
    detail_view.play_next_button.click()
    assert playback_paths == [detail_view._next_episode_path]

    # Now let's mark episode 1 as watched, so next unwatched is none (since ep 2 is already watched)
    sample_library_dictionary["Cosmos"]["seasons"]["Season 1"]["episodes"][0][
        "watched"
    ] = True
    detail_view.populate_series_details("Cosmos")
    assert detail_view.play_next_button.isHidden() is True
    assert detail_view._next_episode_path == ""

    # Now let's make episode 2 unwatched, so next unwatched is S1:E2
    sample_library_dictionary["Cosmos"]["seasons"]["Season 1"]["episodes"][1][
        "watched"
    ] = False
    detail_view.populate_series_details("Cosmos")
    assert detail_view.play_next_button.isHidden() is False
    assert detail_view.play_next_button.text() == "▶ PLAY S1:E2"
    assert (
        detail_view._next_episode_path
        == sample_library_dictionary["Cosmos"]["seasons"]["Season 1"]["episodes"][1][
            "path"
        ]
    )


def test_e2e_right_click_marks_watched(
    sample_library_dictionary: Dict[str, Any], qtbot: Any, generated_video_asset: str
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance._cache_series_metrics()

    detail_view = SeriesDetailView(controller_instance)
    qtbot.addWidget(detail_view)
    detail_view.populate_series_details("Cosmos")

    page_widget: Optional[Any] = detail_view.seasons_tab_widget.widget(0)
    assert page_widget is not None
    table_widget: Optional[Any] = page_widget.findChild(QTableWidget)
    assert isinstance(table_widget, QTableWidget)

    from unittest.mock import patch

    with patch("lan_streamer.ui_views.QMenu") as mock_qmenu_class:
        mock_menu_instance = MagicMock()
        mock_qmenu_class.return_value = mock_menu_instance

        item = table_widget.item(0, 1)
        assert item is not None
        pos = table_widget.visualItemRect(item).center()
        table_widget.customContextMenuRequested.emit(pos)

        assert mock_menu_instance.exec.called
        assert mock_menu_instance.addAction.called
        action = None
        for call in mock_menu_instance.addAction.call_args_list:
            act = call[0][0]
            if "Mark as Watched" in act.text():
                action = act
                break
        assert action is not None
        action.trigger()

    assert (
        controller_instance.cached_library_data["Cosmos"]["seasons"]["Season 1"][
            "episodes"
        ][0]["watched"]
        is True
    )

    # The episode in row 1 is watched, let's mark it as unwatched
    with patch("lan_streamer.ui_views.QMenu") as mock_qmenu_class:
        mock_menu_instance = MagicMock()
        mock_qmenu_class.return_value = mock_menu_instance

        item = table_widget.item(1, 1)
        assert item is not None
        pos = table_widget.visualItemRect(item).center()
        table_widget.customContextMenuRequested.emit(pos)

        assert mock_menu_instance.exec.called
        assert mock_menu_instance.addAction.called
        action = None
        for call in mock_menu_instance.addAction.call_args_list:
            act = call[0][0]
            if "Mark as Unwatched" in act.text():
                action = act
                break
        assert action is not None
        action.trigger()

    assert (
        controller_instance.cached_library_data["Cosmos"]["seasons"]["Season 1"][
            "episodes"
        ][1]["watched"]
        is False
    )


def test_e2e_title_click_triggers_playback(
    sample_library_dictionary: Dict[str, Any], qtbot: Any, generated_video_asset: str
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance._cache_series_metrics()

    detail_view = SeriesDetailView(controller_instance)
    qtbot.addWidget(detail_view)
    detail_view.populate_series_details("Cosmos")

    requested_paths_emitted: List[str] = []
    controller_instance.playback_requested.connect(requested_paths_emitted.append)

    detail_view.trigger_episode_playback_by_row(season_tab_index=0, row_index=0)
    assert requested_paths_emitted == [generated_video_asset]


def test_series_detail_view_bulk_actions_and_tab_selection(qtbot: Any) -> None:
    multi_season_library: Dict[str, Any] = {
        "Cosmos": {
            "metadata": {"tmdb_name": "Cosmos"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {"path": "/p1", "watched": True},
                        {"path": "/p2", "watched": True},
                    ]
                },
                "Season 2": {
                    "episodes": [
                        {"path": "/p3", "watched": False},
                        {"path": "/p4", "watched": False},
                    ]
                },
            },
        }
    }

    controller_instance = Controller()
    controller_instance.current_library_name = "Test Lib"
    controller_instance.cached_library_data = multi_season_library
    controller_instance.selected_series_name = "Cosmos"
    controller_instance._cache_series_metrics()

    detail_view = SeriesDetailView(controller_instance)
    qtbot.addWidget(detail_view)

    # Test auto selection of latest unwatched season tab on opening
    detail_view.populate_series_details("Cosmos")
    assert detail_view.seasons_tab_widget.currentIndex() == 1  # Season 2 has unwatched

    # Test Mark season as watched button
    with patch("lan_streamer.db.update_season_watched_status") as mock_db_season:
        season_button: Optional[QPushButton] = detail_view.findChild(
            QPushButton, "markSeasonWatchedButton_Season 2"
        )
        assert season_button is not None
        season_button.click()
        mock_db_season.assert_called_once_with("Test Lib", "Cosmos", "Season 2", True)
        assert (
            multi_season_library["Cosmos"]["seasons"]["Season 2"]["episodes"][0][
                "watched"
            ]
            is True
        )

    # Test Mark Series as Watched logic via controller directly as button moved to dialog
    with patch("lan_streamer.db.update_series_watched_status") as mock_db_series:
        controller_instance.mark_series_watched("Cosmos")
        mock_db_series.assert_called_once_with("Test Lib", "Cosmos", True)


def test_metadata_match_dialog_workflow(
    sample_library_dictionary: Dict[str, Any], qtbot: Any
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance.current_library_name = "Test Lib"

    dialog_instance = MetadataMatchDialog("Cosmos", controller_instance)
    qtbot.addWidget(dialog_instance)

    with patch("lan_streamer.ui_views.tmdb_client.search_series_full") as mock_search:
        mock_search.return_value = [
            {
                "id": 999,
                "name": "Cosmos Remastered",
                "first_air_date": "2020-01-01",
                "overview": "Modern overview.",
                "poster_path": "/remastered.jpg",
            }
        ]

        dialog_instance.execute_search()
        assert dialog_instance.results_table.rowCount() == 1
        result_item = dialog_instance.results_table.item(0, 1)
        assert result_item is not None
        assert result_item.text() == "Cosmos Remastered"

        # Select row and apply
        dialog_instance.results_table.selectRow(0)

        with (
            patch("lan_streamer.db.save_library") as mock_save,
            patch.object(MetadataApplyWorker_real, "start", lambda self: self.run()),
        ):
            dialog_instance.apply_selected()
            mock_save.assert_called_once()

            metadata_dictionary: Dict[str, Any] = (
                controller_instance.cached_library_data["Cosmos"]["metadata"]
            )
            assert metadata_dictionary["tmdb_identifier"] == "999"
            assert metadata_dictionary["tmdb_name"] == "Cosmos Remastered"
            assert metadata_dictionary["locked_metadata"] is True


def test_jellyfin_match_dialog_workflow(
    sample_library_dictionary: Dict[str, Any], qtbot: Any
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance.current_library_name = "Test Lib"

    dialog_instance = JellyfinMatchDialog("Cosmos", controller_instance)
    qtbot.addWidget(dialog_instance)

    with patch("lan_streamer.ui_views.jellyfin_client.search_series") as mock_search:
        mock_search.return_value = [
            {
                "Id": "jellyfin_id_123",
                "Name": "Cosmos Series",
                "ProductionYear": 1980,
                "Overview": "Overview test.",
            }
        ]

        dialog_instance.execute_search()
        assert dialog_instance.results_table.rowCount() == 1
        result_item = dialog_instance.results_table.item(0, 1)
        assert result_item is not None
        assert result_item.text() == "Cosmos Series"

        dialog_instance.results_table.selectRow(0)

        with patch("lan_streamer.db.save_library") as mock_save:
            with patch.object(controller_instance, "trigger_scan") as mock_scan:
                dialog_instance.apply_selected()
                mock_save.assert_called_once()
                mock_scan.assert_not_called()

            metadata_dictionary: Dict[str, Any] = (
                controller_instance.cached_library_data["Cosmos"]["metadata"]
            )
            assert metadata_dictionary["jellyfin_id"] == "jellyfin_id_123"


def test_rename_preview_dialog_workflow(
    sample_library_dictionary: Dict[str, Any], qtbot: Any, generated_video_asset: str
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance.current_library_name = "Test Lib"

    with patch("lan_streamer.scanner.renamer.get_rename_preview") as mock_preview:
        mock_preview.return_value = [
            {
                "old_name": "test_video.mkv",
                "new_name": "Cosmos S01E01 - The Shores of the Cosmic Ocean.mkv",
                "old_path": generated_video_asset,
                "new_path": generated_video_asset.replace(
                    "test_video.mkv",
                    "Cosmos S01E01 - The Shores of the Cosmic Ocean.mkv",
                ),
            }
        ]

        dialog_instance = RenamePreviewDialog("Cosmos", controller_instance)
        qtbot.addWidget(dialog_instance)

        assert dialog_instance.preview_tree.topLevelItemCount() == 1
        season_item = dialog_instance.preview_tree.topLevelItem(0)
        assert season_item.childCount() == 1
        child_item = season_item.child(0)
        assert child_item.text(0) == "test_video.mkv"

        def side_effect_perform(
            preview_results: List[Dict[str, Any]], success_callback: Any
        ) -> None:
            for item_dictionary in preview_results:
                success_callback(
                    item_dictionary["old_path"], item_dictionary["new_path"]
                )

        with patch(
            "lan_streamer.scanner.renamer.perform_rename",
            side_effect=side_effect_perform,
        ) as mock_perform:
            dialog_instance.apply_renames()
            mock_perform.assert_called_once()


def test_settings_dialog_lifecycle(qtbot: Any) -> None:
    dialog_instance = SettingsDialog()
    qtbot.addWidget(dialog_instance)

    # Initialize backup options to valid, non-warning defaults to avoid blocking dialogs
    dialog_instance.config_backup_frequency_input.setText("0")
    dialog_instance.config_backup_retention_input.setText("7")
    dialog_instance.database_backup_frequency_input.setText("0")
    dialog_instance.database_backup_retention_input.setText("7")

    dialog_instance.jellyfin_url_input.setText("http://localhost:8096")
    dialog_instance.use_embedded_checkbox.setChecked(False)
    dialog_instance.enable_caching_checkbox.setChecked(True)
    dialog_instance.enable_hw_accel_checkbox.setChecked(False)
    dialog_instance.watched_threshold_input.setText("98")

    # Test Advanced options
    with patch(
        "lan_streamer.ui_views.QFileDialog.getSaveFileName",
        return_value=("/custom/lib.db", ""),
    ):
        dialog_instance.browse_database_path()
        assert dialog_instance.db_path_input.text() == "/custom/lib.db"

    with patch(
        "lan_streamer.ui_views.QFileDialog.getExistingDirectory",
        return_value="/custom/logs",
    ):
        dialog_instance.browse_log_directory()
        assert dialog_instance.log_dir_input.text() == "/custom/logs"

    dialog_instance.log_retention_input.setText("14")
    dialog_instance.log_saving_mode_selector.setCurrentText("Divided Service Logs")
    dialog_instance.save_config()

    assert config.jellyfin_url == "http://localhost:8096"
    assert config.use_embedded_player is False
    assert config.enable_caching is True
    assert config.enable_hw_accel is False
    assert config.watched_threshold == 0.98
    assert config.database_path == "/custom/lib.db"
    assert config.log_directory == "/custom/logs"
    assert config.max_log_retention_days == 14
    assert config.divide_logs_by_service is True

    # Test ValueError fallback coverage
    dialog_instance.log_retention_input.setText("invalid_days")
    dialog_instance.watched_threshold_input.setText("invalid_threshold")
    dialog_instance.log_saving_mode_selector.setCurrentText("Single Global File")
    dialog_instance.save_config()
    assert config.max_log_retention_days == 14
    assert config.watched_threshold == 0.98
    assert config.divide_logs_by_service is False


def test_settings_dialog_libraries_management(qtbot: Any) -> None:
    dialog_instance = SettingsDialog()
    qtbot.addWidget(dialog_instance)

    with (
        patch("lan_streamer.ui_views.QMessageBox.warning") as mock_warning,
        patch(
            "lan_streamer.ui_views.QFileDialog.getExistingDirectory",
            return_value="/media/cinematic",
        ),
    ):
        # Test Add Library
        dialog_instance.library_name_input.setText("UniqueTestCinematicLib999")
        dialog_instance.add_staged_library()
        assert "UniqueTestCinematicLib999" in dialog_instance.staged_libraries

        # Test Duplicate warning trigger
        dialog_instance.library_name_input.setText("UniqueTestCinematicLib999")
        dialog_instance.add_staged_library()
        mock_warning.assert_called_once()

        # Test Add Directory with no library selected
        dialog_instance.library_selector.clear()
        dialog_instance.add_staged_directory()
        assert mock_warning.call_count == 2

        # Test Add Directory successfully
        dialog_instance._refresh_library_selector()
        dialog_instance.library_selector.setCurrentText("UniqueTestCinematicLib999")
        dialog_instance.add_staged_directory()
        assert (
            "/media/cinematic"
            in dialog_instance.staged_libraries["UniqueTestCinematicLib999"]["paths"]
        )

        # Test Remove Directory
        dialog_instance.directory_list_widget.setCurrentRow(0)
        dialog_instance.remove_staged_directory()
        assert (
            "/media/cinematic"
            not in dialog_instance.staged_libraries["UniqueTestCinematicLib999"][
                "paths"
            ]
        )

        # Test Remove Library
        dialog_instance.remove_staged_library()
        assert "UniqueTestCinematicLib999" not in dialog_instance.staged_libraries


def test_settings_dialog_backup_options(qtbot: Any) -> None:
    dialog_instance = SettingsDialog()
    qtbot.addWidget(dialog_instance)

    with patch(
        "lan_streamer.ui_views.QFileDialog.getExistingDirectory",
        return_value="/custom/ui_backups",
    ):
        dialog_instance.browse_backup_directory()
        assert dialog_instance.backup_directory_input.text() == "/custom/ui_backups"

    dialog_instance.config_backup_frequency_input.setText("5")
    dialog_instance.database_backup_frequency_input.setText("10")
    dialog_instance.config_backup_retention_input.setText("15")
    dialog_instance.database_backup_retention_input.setText("20")

    dialog_instance.save_config()

    assert config.backup_directory == "/custom/ui_backups"
    assert config.config_backup_frequency == 5
    assert config.database_backup_frequency == 10
    assert config.config_backup_retention == 15
    assert config.database_backup_retention == 20

    # Test Restore Triggers coverage
    with (
        patch(
            "lan_streamer.ui_views.QFileDialog.getOpenFileName",
            return_value=("/path/to/backup.json", ""),
        ),
        patch("lan_streamer.system.backup.restore_config_backup", return_value=True),
        patch("lan_streamer.ui_views.QMessageBox.information") as mock_info,
    ):
        dialog_instance.trigger_restore_config()
        mock_info.assert_called_once()

    with (
        patch(
            "lan_streamer.ui_views.QFileDialog.getOpenFileName",
            return_value=("/path/to/backup.db", ""),
        ),
        patch("lan_streamer.system.backup.restore_database_backup", return_value=True),
        patch("lan_streamer.ui_views.QMessageBox.information") as mock_info,
    ):
        dialog_instance.trigger_restore_database()
        mock_info.assert_called_once()


def test_settings_dialog_backup_options_warning(qtbot: Any) -> None:
    dialog_instance = SettingsDialog()
    qtbot.addWidget(dialog_instance)

    # 1. Retention less than frequency, user selects No -> should NOT save
    dialog_instance.config_backup_frequency_input.setText("10")
    dialog_instance.config_backup_retention_input.setText("5")  # 5 < 10 (warning!)
    dialog_instance.database_backup_frequency_input.setText("10")
    dialog_instance.database_backup_retention_input.setText("20")

    original_config_val = config.config_backup_retention

    with patch(
        "lan_streamer.ui_views.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ) as mock_question:
        dialog_instance.save_config()
        mock_question.assert_called_once()
        assert config.config_backup_retention == original_config_val

    # 2. Retention less than frequency, user selects Yes -> should save
    with patch(
        "lan_streamer.ui_views.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ) as mock_question:
        dialog_instance.save_config()
        mock_question.assert_called_once()
        assert config.config_backup_retention == 5
        assert config.config_backup_frequency == 10


def test_settings_dialog_global_actions(qtbot: Any) -> None:
    controller_instance = Controller()
    dialog_instance = SettingsDialog(controller_instance)
    qtbot.addWidget(dialog_instance)

    with patch.object(controller_instance, "trigger_scan_all") as mock_scan_all:
        dialog_instance.trigger_full_scan_files()
        mock_scan_all.assert_called_once_with(
            force_refresh=False,
            run_pass1=True,
            run_pass2=True,
            chain_pass3=True,
            chain_cleanup=True,
        )

        mock_scan_all.reset_mock()
        dialog_instance.trigger_pass1_scan()
        mock_scan_all.assert_called_once_with(
            force_refresh=False,
            run_pass1=True,
            run_pass2=False,
            chain_pass3=False,
            chain_cleanup=False,
        )

        mock_scan_all.reset_mock()
        dialog_instance.trigger_pass2_scan()
        mock_scan_all.assert_called_once_with(
            force_refresh=False,
            run_pass1=False,
            run_pass2=True,
            chain_pass3=False,
            chain_cleanup=False,
        )

    with patch.object(
        controller_instance, "trigger_runtime_extraction"
    ) as mock_runtime:
        dialog_instance.trigger_pass3_scan()
        mock_runtime.assert_called_once()

    with patch.object(controller_instance, "trigger_global_cleanup") as mock_cleanup:
        dialog_instance.trigger_garbage_cleanup()
        mock_cleanup.assert_called_once()

    with patch.object(controller_instance, "trigger_jellyfin_pull") as mock_pull:
        dialog_instance.trigger_global_jellyfin_pull()
        mock_pull.assert_called_once()

    with patch.object(controller_instance, "trigger_jellyfin_push") as mock_push:
        dialog_instance.trigger_global_jellyfin_push()
        mock_push.assert_called_once()

    # Test _on_global_progress slot marks library done on the segmented bar
    dialog_instance.global_progress_bar.init_from_tree(
        {
            "TV_Lib": {
                "type": "tv",
                "roots": {
                    "/tmp": {"SeriesA": {"seasons": {"Season 1": ["S01E01.mkv"]}}}
                },
            }
        }
    )
    dialog_instance._on_global_progress("TV_Lib", 1, 1)
    # Progress was marked done without raising

    # Verify ScanProgressTree handles TV season collapse states & Movie node skipping
    dialog_instance.scan_progress_tree.init_from_tree(
        {
            "TV_Lib": {
                "type": "tv",
                "roots": {
                    "/tmp": {"SeriesA": {"seasons": {"Season 1": ["S01E01.mkv"]}}}
                },
            },
            "Movie_Lib": {"type": "movie", "roots": {"/tmp2": {"MovieA": {}}}},
        }
    )
    # Check that the TV season node exists and is collapsed
    season_key = dialog_instance.scan_progress_tree._season_key(
        "TV_Lib", "SeriesA", "Season 1"
    )
    season_node = dialog_instance.scan_progress_tree._season_nodes.get(season_key)
    assert season_node is not None
    assert not season_node.isExpanded()

    # Episode file node should exist
    ep_path = "/tmp/SeriesA/Season 1/S01E01.mkv"
    assert ep_path in dialog_instance.scan_progress_tree._file_nodes

    # Try marking a file active for a Movie library (should be a no-op / skip)
    dialog_instance.scan_progress_tree.mark_file_active(
        "/tmp2/MovieA/MovieA.mkv", "Movie_Lib", "MovieA"
    )
    assert (
        "/tmp2/MovieA/MovieA.mkv" not in dialog_instance.scan_progress_tree._file_nodes
    )

    # _complete_jellyfin_progress is a no-op; just verify it doesn't raise
    dialog_instance._complete_jellyfin_progress("Complete Message")

    # Test no controller instance handles safely
    dialog_no_controller = SettingsDialog(None)
    dialog_no_controller.trigger_full_scan_files()
    dialog_no_controller.trigger_pass1_scan()
    dialog_no_controller.trigger_pass2_scan()
    dialog_no_controller.trigger_pass3_scan()
    dialog_no_controller.trigger_garbage_cleanup()
    dialog_no_controller.trigger_global_jellyfin_pull()
    dialog_no_controller.trigger_global_jellyfin_push()


def test_episode_metadata_match_dialog_workflow(
    sample_library_dictionary: Dict[str, Any], qtbot: Any, generated_video_asset: str
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance.current_library_name = "Test Lib"

    # Pre-assign tmdb_identifier to series metadata to enable episode fetching
    sample_library_dictionary["Cosmos"]["metadata"]["tmdb_identifier"] = "888"

    episode_target_path: str = generated_video_asset

    with patch("lan_streamer.ui_views.tmdb_client.get_seasons") as mock_seasons:
        mock_seasons.return_value = [{"season_number": 1, "name": "Season 1"}]
        with patch("lan_streamer.ui_views.tmdb_client.get_episodes") as mock_episodes:
            mock_episodes.return_value = [
                {
                    "id": 777,
                    "episode_number": 1,
                    "name": "Matched Episode Title",
                    "air_date": "1980-09-28",
                    "overview": "Episode overview text.",
                    "runtime": 62,
                }
            ]

            dialog_instance = EpisodeMatchDialog(
                "Cosmos", episode_target_path, controller_instance
            )
            qtbot.addWidget(dialog_instance)

            # Trigger season changed explicitly to populate results
            dialog_instance.on_season_changed("Season 1")
            assert dialog_instance.results_table.rowCount() == 1
            result_item = dialog_instance.results_table.item(0, 1)
            assert result_item is not None
            assert result_item.text() == "Matched Episode Title"

            # Select row and apply
            dialog_instance.results_table.selectRow(0)

            with patch("lan_streamer.db.save_library") as mock_save:
                dialog_instance.apply_selected()
                mock_save.assert_called_once()

                episode_record: Dict[str, Any] = (
                    controller_instance.cached_library_data["Cosmos"]["seasons"][
                        "Season 1"
                    ]["episodes"][0]
                )
                assert episode_record["tmdb_identifier"] == "777"
                assert episode_record["tmdb_episode_identifier"] == "777"
                assert episode_record["tmdb_name"] == "Matched Episode Title"
                assert episode_record["runtime"] == 62

            # Test empty selection alert
            dialog_instance.results_table.clearSelection()
            with patch("lan_streamer.ui_views.QMessageBox.warning") as mock_warning:
                dialog_instance.apply_selected()
                mock_warning.assert_called_once()


def test_series_detail_view_episode_match_button(
    sample_library_dictionary: Dict[str, Any], qtbot: Any, generated_video_asset: str
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance._cache_series_metrics()

    detail_view = SeriesDetailView(controller_instance)
    qtbot.addWidget(detail_view)
    detail_view.populate_series_details("Cosmos")

    emitted_signals: List[Any] = []

    def slot(series_name: str, path_string: str) -> None:
        emitted_signals.append((series_name, path_string))

    controller_instance.episode_details_requested.connect(slot)

    match_button: Optional[QPushButton] = detail_view.findChild(
        QPushButton, "detailsEpisodeButton_0"
    )
    assert match_button is not None
    match_button.click()

    assert emitted_signals == [("Cosmos", generated_video_asset)]


def test_apply_metadata_match_refreshes_episodes() -> None:
    controller_instance = Controller()
    controller_instance.current_library_name = "tv"
    controller_instance.cached_library_data = {
        "RefreshShow": {
            "metadata": {"tmdb_identifier": "old_id"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": "/path/to/S01E01.mkv",
                            "tmdb_identifier": "",
                        },
                        {
                            "name": "Pilot Part 2.mkv",
                            "path": "/path/to/Pilot Part 2.mkv",
                            "tmdb_identifier": "",
                        },
                    ]
                }
            },
        }
    }

    mock_episodes_list = [
        {
            "id": "ep_999",
            "episode_number": 1,
            "name": "Pilot Part 1",
            "air_date": "2021-01-01",
            "runtime": 45,
        },
        {
            "id": "ep_888",
            "episode_number": 2,
            "name": "Pilot Part 2",
            "air_date": "2021-01-08",
            "runtime": 50,
        },
    ]

    with (
        patch(
            "lan_streamer.ui_views.tmdb_client.get_episodes",
            return_value=mock_episodes_list,
        ),
        patch("lan_streamer.db.save_library") as mock_save,
        patch.object(MetadataApplyWorker_real, "start", lambda self: self.run()),
    ):
        controller_instance.apply_metadata_match(
            "RefreshShow", {"id": "new_tmdb_id", "name": "Refreshed Show Title"}
        )
        mock_save.assert_called_once()

    episodes_result = controller_instance.cached_library_data["RefreshShow"]["seasons"][
        "Season 1"
    ]["episodes"]
    assert episodes_result[0]["tmdb_identifier"] == "ep_999"
    assert episodes_result[0]["tmdb_number"] == 1
    assert episodes_result[0]["runtime"] == 45

    assert episodes_result[1]["tmdb_identifier"] == "ep_888"
    assert episodes_result[1]["tmdb_name"] == "Pilot Part 2"


def test_controller_additional_coverage() -> None:
    controller_instance = Controller()

    # 1. trigger_scan when not current_library_name
    controller_instance.current_library_name = ""
    status_msg = []
    controller_instance.status_changed.connect(status_msg.append)
    controller_instance.trigger_scan()
    assert "Select a library first." in status_msg

    # 2. trigger_cleanup when not current_library_name
    status_msg.clear()
    controller_instance.trigger_cleanup()
    assert "Select a library first." in status_msg

    # 3. trigger_jellyfin_pull & push when not configured
    status_msg.clear()
    with patch(
        "lan_streamer.ui_views.jellyfin_client.is_configured", return_value=False
    ):
        controller_instance.trigger_jellyfin_pull()
        assert "Jellyfin is not configured." in status_msg

        status_msg.clear()
        controller_instance.trigger_jellyfin_push()
        assert "Jellyfin is not configured." in status_msg
    # 4. select_library with movie type and removing existing directories
    config.libraries["MovieLib"] = {"type": "movie", "paths": ["/media/movies"]}
    with (
        patch(
            "lan_streamer.db.load_movie_library",
            return_value={"Movie1": {"path": "/media/movies/m1.mkv"}},
        ) as mock_load_movie,
        patch("pathlib.Path.is_dir", return_value=True),
        patch.object(
            controller_instance.file_system_watcher,
            "directories",
            return_value=["/media/movies"],
        ),
        patch.object(
            controller_instance.file_system_watcher, "removePaths"
        ) as mock_remove_paths,
    ):
        controller_instance.select_library("MovieLib")
        assert controller_instance.current_library_name == "MovieLib"
        mock_load_movie.assert_called_once_with("MovieLib")
        mock_remove_paths.assert_called_once_with(["/media/movies"])

    # 5. select_movie
    movie_selected_emitted = []
    controller_instance.movie_selected.connect(movie_selected_emitted.append)
    controller_instance.select_movie("Movie1")
    assert controller_instance.selected_series_name == "Movie1"
    assert movie_selected_emitted == ["Movie1"]

    # 6. trigger_runtime_extraction, _on_runtime_progress, _on_runtime_finished
    with patch(
        "lan_streamer.ui_views.FilePropertyExtractionWorker"
    ) as mock_worker_class:
        controller_instance.trigger_runtime_extraction()
        mock_worker_class.assert_called_once()
        mock_worker_instance = mock_worker_class.return_value
        mock_worker_instance.start.assert_called_once()

        # concurrency check
        controller_instance.worker_manager.file_property._instance = (
            mock_worker_instance
        )
        mock_worker_instance.isRunning.return_value = True
        controller_instance.trigger_runtime_extraction()
        assert mock_worker_class.call_count == 1

        # progress callback
        progress_emitted = []
        controller_instance.global_progress_updated.connect(
            lambda name, c, t: progress_emitted.append((name, c, t))
        )
        controller_instance._on_runtime_progress(5, 10)
        assert progress_emitted == [("Extracting Runtimes", 5, 10)]

        # finished callback
        with patch.object(controller_instance, "select_library") as mock_select:
            controller_instance._on_runtime_finished(3)
            mock_select.assert_called_once_with("MovieLib", reset_selection=False)

    # 7. update_movie_metadata
    controller_instance.cached_library_data = {
        "Movie1": {"path": "/media/movies/m1.mkv"}
    }
    with patch("lan_streamer.db.save_library") as mock_save:
        controller_instance.update_movie_metadata(
            "Movie1", "/media/movies/m1.mkv", {"tmdb_name": "New Movie Name"}
        )
        assert (
            controller_instance.cached_library_data["Movie1"]["tmdb_name"]
            == "New Movie Name"
        )
        mock_save.assert_called_once()

    # 8. merge_subtitles, _on_subtitle_merge_finished
    with patch("lan_streamer.backend.SubtitleMergeWorker") as mock_merge_class:
        controller_instance.merge_subtitles("/video.mkv", ["/sub.srt"])
        mock_merge_class.assert_called_once_with(
            "/video.mkv", ["/sub.srt"], async_task_manager=ANY
        )
        mock_merge_instance = mock_merge_class.return_value
        mock_merge_instance.start.assert_called_once()

        # concurrency check
        controller_instance.worker_manager.subtitle_merge._instance = (
            mock_merge_instance
        )
        mock_merge_instance.isRunning.return_value = True
        controller_instance.merge_subtitles("/video.mkv", ["/sub.srt"])
        assert mock_merge_class.call_count == 1

        # finished callback
        with patch.object(controller_instance, "trigger_scan") as mock_scan:
            controller_instance._on_subtitle_merge_finished("/video.mkv")
            mock_scan.assert_called_once_with(force_refresh=False)

    # 9. embed_metadata, _on_metadata_embed_finished
    with patch("lan_streamer.backend.MetadataEmbedWorker") as mock_embed_class:
        controller_instance.embed_metadata("/video.mkv", {"title": "Title"})
        mock_embed_class.assert_called_once_with(
            "/video.mkv", {"title": "Title"}, async_task_manager=ANY
        )
        mock_embed_instance = mock_embed_class.return_value
        mock_embed_instance.start.assert_called_once()

        # concurrency check
        controller_instance.worker_manager.metadata_embed._instance = (
            mock_embed_instance
        )
        mock_embed_instance.isRunning.return_value = True
        controller_instance.embed_metadata("/video.mkv", {"title": "Title"})
        assert mock_embed_class.call_count == 1

        # finished callback
        with patch.object(controller_instance, "trigger_scan") as mock_scan:
            controller_instance._on_metadata_embed_finished("/video.mkv")
            mock_scan.assert_called_once_with(force_refresh=False)

    # 10. embed_metadata_series
    controller_instance.cached_library_data = {
        "Show1": {"seasons": {"Season 1": {"episodes": [{"path": "/ep1.mkv"}]}}}
    }
    with patch(
        "lan_streamer.backend.SeriesMetadataEmbedWorker"
    ) as mock_series_embed_class:
        # concurrency check when running
        mock_embed_instance.isRunning.return_value = True
        controller_instance.worker_manager.metadata_embed._instance = (
            mock_embed_instance
        )
        controller_instance.embed_metadata_series("Show1")
        mock_series_embed_class.assert_not_called()

        # normal case
        controller_instance.worker_manager.metadata_embed.stop()
        controller_instance.embed_metadata_series("Show1")
        mock_series_embed_class.assert_called_once_with(
            "Show1", [{"path": "/ep1.mkv"}], async_task_manager=ANY
        )

        # no episodes case
        controller_instance.worker_manager.metadata_embed.stop()
        controller_instance.cached_library_data["Show1"]["seasons"]["Season 1"][
            "episodes"
        ] = []
        status_msg.clear()
        controller_instance.embed_metadata_series("Show1")
        assert "No episodes found in series." in status_msg

    # 11. update_series_name
    controller_instance.cached_library_data = {"Show1": {}}
    controller_instance.update_series_name("Show1", "")  # empty new name
    assert "Show1" in controller_instance.cached_library_data

    # 12. apply_metadata_match with movie type library (parsing year from first_air_date)
    controller_instance.current_library_name = "MovieLib"
    controller_instance.cached_library_data = {
        "Movie1": {"path": "/media/movies/m1.mkv"}
    }
    config.libraries["MovieLib"] = {"type": "movie", "paths": ["/media/movies"]}
    with (
        patch("lan_streamer.db.save_movie_library") as mock_save_movie,
        patch("lan_streamer.ui_views.tmdb_client.download_image", return_value=None),
    ):
        controller_instance.apply_metadata_match(
            "Movie1",
            {
                "id": "tmdb_movie_123",
                "name": "Avatar 2",
                "first_air_date": "2022-12-16",
                "overview": "Overview of Avatar 2",
                "poster_path": "/avatar2.jpg",
            },
        )
        mock_save_movie.assert_called_once()
        movie_record = controller_instance.cached_library_data["Movie1"]
        assert movie_record["year"] == 2022
        assert movie_record["tmdb_identifier"] == "tmdb_movie_123"
        assert movie_record["poster_path"] == "/avatar2.jpg"

    # 13. apply_jellyfin_watch_match with movie type library
    with patch("lan_streamer.db.save_movie_library") as mock_save_movie:
        controller_instance.apply_jellyfin_watch_match("Movie1", {"id": "jf_movie_999"})
        mock_save_movie.assert_called_once()
        assert (
            controller_instance.cached_library_data["Movie1"]["jellyfin_id"]
            == "jf_movie_999"
        )


def test_library_grid_view_additional_coverage(qtbot: Any, tmp_path: Any) -> None:
    controller_instance = Controller()
    config.libraries["MovieLib"] = {"type": "movie", "paths": ["/media/movies"]}
    config.libraries["TVLib"] = {"type": "tv", "paths": ["/media/tv"]}

    with patch("lan_streamer.db.load_movie_library", return_value={}):
        grid_view = LibraryGridView(controller_instance)
        qtbot.addWidget(grid_view)

        # 1. populate_libraries when current library name is selected
        controller_instance.current_library_name = "MovieLib"
        grid_view.populate_libraries(["MovieLib", "TVLib"])
        assert grid_view.library_selector.currentText() == "MovieLib"

        # 2. on_library_changed Slot
        with patch.object(controller_instance, "select_library") as mock_select:
            grid_view.on_library_changed("TVLib")
            mock_select.assert_called_once_with("TVLib")

        # 3. populate_grid early return if video is playing
        controller_instance.is_video_playing = True
        grid_view.populate_grid()  # should return early
        assert grid_view.series_list_widget.count() == 0
        controller_instance.is_video_playing = False

        # Create dummy poster image
        poster_file = tmp_path / "avatar_poster.png"
        from PySide6.QtGui import QImage

        img = QImage(10, 10, QImage.Format.Format_RGB32)
        img.fill(0)
        img.save(str(poster_file))

        # Setup cached library data
        controller_instance.cached_library_data = {
            "Avatar": {
                "path": "/media/movies/avatar.mkv",
                "watched": True,
                "metrics": {
                    "total_episodes": 1,
                    "watched_episodes": 1,
                    "max_date_added": 1000,
                    "max_air_date": "2009-12-18",
                },
                "poster_path": str(poster_file),
            },
            "Inception": {
                "path": "/media/movies/inception.mkv",
                "watched": False,
                "metrics": {
                    "total_episodes": 1,
                    "watched_episodes": 0,
                    "max_date_added": 2000,
                    "max_air_date": "2010-07-16",
                },
                "poster_path": "",
            },
        }

        # 4. filter_out_watched
        controller_instance.filter_out_watched = True
        grid_view.populate_grid()
        # Only Inception (unwatched) should be present
        assert grid_view.series_list_widget.count() == 1
        assert "Inception" in grid_view.series_list_widget.item(0).text()

        # Disable filter
        controller_instance.filter_out_watched = False

        # 5. sort_mode: Recently Aired
        controller_instance.sort_mode = "Recently Aired"
        grid_view.populate_grid()
        assert grid_view.series_list_widget.count() == 2
        # Inception (2010) > Avatar (2009), so Inception is first
        assert "Inception" in grid_view.series_list_widget.item(0).text()
        assert "Avatar" in grid_view.series_list_widget.item(1).text()

        # 6. sort_mode: Alphabetical / Default
        controller_instance.sort_mode = "Alphabetical"
        grid_view.populate_grid()
        # Avatar (A) < Inception (I)
        assert "Avatar" in grid_view.series_list_widget.item(0).text()
        assert "Inception" in grid_view.series_list_widget.item(1).text()

        # 7. Updating existing item (text, tooltips, poster path) in populate_grid
        controller_instance.cached_library_data["Avatar"]["watched"] = False
        controller_instance.cached_library_data["Avatar"]["metrics"][
            "watched_episodes"
        ] = 0
        grid_view.populate_grid()
        assert "Unwatched" in grid_view.series_list_widget.item(0).text()

        # 8. takeItem when count decreases
        controller_instance.cached_library_data.pop("Inception")
        grid_view.populate_grid()
        assert grid_view.series_list_widget.count() == 1

        # 9. assign icon cached hit
        # Avatar poster_path is str(poster_file), let's call _assign_item_icon again
        grid_view._assign_item_icon(
            grid_view.series_list_widget.item(0), str(poster_file)
        )

        # 10. Click movie item (calls select_movie)
        with patch.object(controller_instance, "select_movie") as mock_select_movie:
            controller_instance.current_library_name = "MovieLib"
            grid_view.on_item_clicked(grid_view.series_list_widget.item(0))
            mock_select_movie.assert_called_once_with("Avatar")


def test_subtitle_search_dialog_workflow(qtbot: Any, tmp_path: Any) -> None:
    from lan_streamer.ui_views import SubtitleSearchDialog

    controller_instance = Controller()
    controller_instance.cached_library_data = {
        "Show1": {
            "metadata": {"tmdb_name": "Show One", "tmdb_id": "12345"},
            "seasons": {"Season 1": {"episodes": []}},
        }
    }

    # 1. Series Search Dialog initialization and search click
    media_rec = {
        "season_number": 1,
        "tmdb_number": 2,
        "path": str(tmp_path / "ep2.mkv"),
    }
    dialog = SubtitleSearchDialog(
        "Show1", media_rec, controller_instance, is_movie=False
    )
    qtbot.addWidget(dialog)
    assert "Show One S01E02" in dialog.query_edit.text()

    # Search with no results
    with (
        patch(
            "lan_streamer.providers.opensubtitles.opensubtitles_client.search_subtitles",
            return_value=[],
        ) as mock_search,
        patch("lan_streamer.ui_views.QMessageBox.information") as mock_info,
    ):
        dialog._on_search_clicked()
        mock_search.assert_called_once()
        mock_info.assert_called_once()

    # 2. Movie Search Dialog initialization
    movie_rec = {
        "tmdb_name": "Movie One",
        "year": "2024",
        "path": str(tmp_path / "movie.mkv"),
        "tmdb_id": "67890",
    }
    movie_dialog = SubtitleSearchDialog(
        "Movie One", movie_rec, controller_instance, is_movie=True
    )
    qtbot.addWidget(movie_dialog)
    assert "Movie One 2024" in movie_dialog.query_edit.text()

    # Search with results
    sub_results = [
        {
            "attributes": {
                "language": "en",
                "release": "Movie.One.2024.1080p.SRT",
                "ratings": 4.5,
                "download_count": 100,
                "files": [{"file_id": 9999}],
            }
        }
    ]
    with patch(
        "lan_streamer.providers.opensubtitles.opensubtitles_client.search_subtitles",
        return_value=sub_results,
    ):
        movie_dialog._on_search_clicked()
        assert movie_dialog.results_table.rowCount() == 1
        assert movie_dialog.download_btn.isEnabled() is False
        movie_dialog.results_table.selectRow(0)
        assert movie_dialog.download_btn.isEnabled() is True

    # 3. Download clicked errors & successes
    # A. No file ID
    no_file_id_results = [
        {"attributes": {"language": "en", "release": "NoFileId", "files": [{}]}}
    ]
    with patch(
        "lan_streamer.providers.opensubtitles.opensubtitles_client.search_subtitles",
        return_value=no_file_id_results,
    ):
        movie_dialog._on_search_clicked()
        movie_dialog.results_table.selectRow(0)
        with patch("lan_streamer.ui_views.QMessageBox.warning") as mock_warn:
            movie_dialog._on_download_clicked()
            mock_warn.assert_called_once_with(
                movie_dialog, "Download", "No file ID found for this subtitle."
            )

    # Restore valid results
    with patch(
        "lan_streamer.providers.opensubtitles.opensubtitles_client.search_subtitles",
        return_value=sub_results,
    ):
        movie_dialog._on_search_clicked()
        movie_dialog.results_table.selectRow(0)

        # B. No download URL
        with (
            patch(
                "lan_streamer.providers.opensubtitles.opensubtitles_client.get_download_link",
                return_value=None,
            ) as mock_link,
            patch("lan_streamer.ui_views.QMessageBox.warning") as mock_warn,
        ):
            movie_dialog._on_download_clicked()
            mock_link.assert_called_once_with(9999)
            mock_warn.assert_called_once()

        # C. Failed to download content
        with (
            patch(
                "lan_streamer.providers.opensubtitles.opensubtitles_client.get_download_link",
                return_value="http://download.url",
            ) as mock_link,
            patch(
                "lan_streamer.providers.opensubtitles.opensubtitles_client.download_subtitle",
                return_value=None,
            ),
            patch("lan_streamer.ui_views.QMessageBox.warning") as mock_warn,
        ):
            movie_dialog._on_download_clicked()
            mock_warn.assert_called_once_with(
                movie_dialog, "Download", "Failed to download subtitle content."
            )

        # D. Video file not found on disk
        with (
            patch(
                "lan_streamer.providers.opensubtitles.opensubtitles_client.get_download_link",
                return_value="http://download.url",
            ),
            patch(
                "lan_streamer.providers.opensubtitles.opensubtitles_client.download_subtitle",
                return_value=b"subtitle data",
            ),
            patch("lan_streamer.ui_views.QMessageBox.warning") as mock_warn,
        ):
            movie_dialog._on_download_clicked()
            mock_warn.assert_called_once_with(
                movie_dialog, "Download", "Video file not found on disk."
            )

        # E. Successful download and save
        video_file = tmp_path / "movie.mkv"
        video_file.touch()
        with (
            patch(
                "lan_streamer.providers.opensubtitles.opensubtitles_client.get_download_link",
                return_value="http://download.url",
            ),
            patch(
                "lan_streamer.providers.opensubtitles.opensubtitles_client.download_subtitle",
                return_value=b"subtitle data",
            ),
            patch("lan_streamer.ui_views.QMessageBox.information") as mock_info,
        ):
            movie_dialog._on_download_clicked()
            mock_info.assert_called_once()
            expected_sub = tmp_path / "movie.en.srt"
            assert expected_sub.exists()
            assert expected_sub.read_bytes() == b"subtitle data"

        # F. Error saving (file write exception)
        with (
            patch(
                "lan_streamer.providers.opensubtitles.opensubtitles_client.get_download_link",
                return_value="http://download.url",
            ),
            patch(
                "lan_streamer.providers.opensubtitles.opensubtitles_client.download_subtitle",
                return_value=b"subtitle data",
            ),
            patch("builtins.open", side_effect=IOError("Write permission denied")),
            patch("lan_streamer.ui_views.QMessageBox.critical") as mock_crit,
        ):
            movie_dialog._on_download_clicked()
            mock_crit.assert_called_once()


def test_settings_dialog_combined_views(qtbot: Any) -> None:
    from lan_streamer.system.config import config
    from lan_streamer.ui_views import SettingsDialog

    config.enable_combined_view = False
    controller_instance = Controller()
    dialog_instance = SettingsDialog(controller_instance)
    qtbot.addWidget(dialog_instance)

    # 1. Initial State Checks
    assert not dialog_instance.enable_combined_view_checkbox.isChecked()

    # 2. Toggle Combined View Checkbox
    dialog_instance.enable_combined_view_checkbox.setChecked(True)
    assert dialog_instance.enable_combined_view_checkbox.isChecked()

    # 3. Add and Configure Combined View Row
    initial_row_count = len(dialog_instance.staged_combined_views)
    dialog_instance.add_combined_view_row()
    assert len(dialog_instance.staged_combined_views) == initial_row_count + 1

    # Get the added row index
    new_row_idx = len(dialog_instance.staged_combined_views) - 1
    dialog_instance.combined_views_list_widget.setCurrentRow(new_row_idx)

    # Modify properties
    dialog_instance.row_name_input.setText("Custom Row Name")
    dialog_instance.row_enabled_checkbox.setChecked(True)
    dialog_instance.row_sort_selector.setCurrentText("Next Up")
    dialog_instance.row_filter_selector.setCurrentText("Unwatched")
    dialog_instance.row_max_items_spinbox.setValue(15)

    # Trigger property change logic
    dialog_instance._on_row_property_changed()

    # Check updated row values
    row = dialog_instance.staged_combined_views[new_row_idx]
    assert row["name"] == "Custom Row Name"
    assert row["enabled"] is True
    assert row["sort_by"] == "Next Up"
    assert row["filter_mode"] == "Unwatched"
    assert row["max_items"] == 15

    # 4. Save Config
    with (
        patch("lan_streamer.system.config.config.save") as mock_save,
        patch(
            "lan_streamer.ui_views.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
    ):
        dialog_instance.save_config()
        mock_save.assert_called_once()
        assert config.enable_combined_view is True
        assert config.combined_views[-1]["name"] == "Custom Row Name"
        assert config.combined_views[-1]["max_items"] == 15


def test_library_grid_view_next_up_sorting(qtbot: Any) -> None:
    # 1. Prepare sample data with different watched/play status
    # Cosmos: Partially Watched (watched_episodes=1, total=2, last_played_at=3000) -> Candidate!
    # Star Trek: Fully Watched (watched_episodes=1, total=1, last_played_at=5000) -> Non-candidate!
    # Doctor Who: Unwatched (watched_episodes=0, total=1, last_played_at=0) -> Non-candidate!
    library_data: Dict[str, Any] = {
        "Cosmos": {
            "metadata": {
                "first_air_date": "1980-09-28",
                "poster_path": "/cosmos.jpg",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": "/tv/cosmos/s01e01.mkv",
                            "watched": False,
                            "last_played_at": 3000,
                            "date_added": 1000,
                        },
                        {
                            "path": "/tv/cosmos/s01e02.mkv",
                            "watched": True,
                            "last_played_at": 1000,
                            "date_added": 1000,
                        },
                    ]
                }
            },
        },
        "Star Trek": {
            "metadata": {
                "first_air_date": "1966-09-08",
                "poster_path": "/trek.jpg",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": "/tv/trek/s01e01.mkv",
                            "watched": True,
                            "last_played_at": 5000,
                            "date_added": 1000,
                        },
                    ]
                }
            },
        },
        "Doctor Who": {
            "metadata": {
                "first_air_date": "1963-11-23",
                "poster_path": "/who.jpg",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": "/tv/who/s01e01.mkv",
                            "watched": False,
                            "last_played_at": 0,
                            "date_added": 1000,
                        },
                    ]
                }
            },
        },
    }

    controller_instance = Controller()
    controller_instance.cached_library_data = library_data
    controller_instance._cache_series_metrics()

    # Verify that metrics caching correctly extracted last_played_at
    assert library_data["Cosmos"]["metrics"]["last_played_at"] == 3000
    assert library_data["Star Trek"]["metrics"]["last_played_at"] == 5000
    assert library_data["Doctor Who"]["metrics"]["last_played_at"] == 0

    with patch("lan_streamer.db.load_library", return_value=library_data):
        grid_view = LibraryGridView(controller_instance)
        qtbot.addWidget(grid_view)

        # Set sort mode to Next Up
        controller_instance.filter_out_watched = False
        controller_instance.sort_mode = "Next Up"
        grid_view.populate_grid()

        # Check results in list widget
        # Candidate (Cosmos) should be first
        # Non-candidate (Star Trek, last_played_at=5000) should be second
        # Non-candidate (Doctor Who, last_played_at=0) should be third
        assert grid_view.series_list_widget.count() == 3
        assert "Cosmos" in grid_view.series_list_widget.item(0).text()
        assert "Star Trek" in grid_view.series_list_widget.item(1).text()
        assert "Doctor Who" in grid_view.series_list_widget.item(2).text()


def test_library_grid_view_bidirectional_sorting(qtbot: Any) -> None:
    library_data = {
        "A Series": {
            "metadata": {"first_air_date": "2020-01-01"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": "/tv/aseries/s01e01.mkv",
                            "watched": False,
                            "last_played_at": 1000,
                            "date_added": 1000,
                        },
                    ]
                }
            },
        },
        "Z Series": {
            "metadata": {"first_air_date": "2021-01-01"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": "/tv/zseries/s01e01.mkv",
                            "watched": False,
                            "last_played_at": 2000,
                            "date_added": 2000,
                        },
                    ]
                }
            },
        },
    }

    controller_instance = Controller()
    controller_instance.cached_library_data = library_data
    controller_instance._cache_series_metrics()

    with patch("lan_streamer.db.load_library", return_value=library_data):
        grid_view = LibraryGridView(controller_instance)
        qtbot.addWidget(grid_view)
        grid_view.populate_grid()

        # 1. Alphabetical sorting
        grid_view.sort_selector.setCurrentText("Alphabetical")
        assert not grid_view.order_label.isHidden()
        assert not grid_view.order_selector.isHidden()

        # Ascending (A-Z)
        grid_view.order_selector.setCurrentText("A-Z")
        assert controller_instance.sort_descending is False
        assert "A Series" in grid_view.series_list_widget.item(0).text()
        assert "Z Series" in grid_view.series_list_widget.item(1).text()

        # Descending (Z-A)
        grid_view.order_selector.setCurrentText("Z-A")
        assert controller_instance.sort_descending is True
        assert "Z Series" in grid_view.series_list_widget.item(0).text()
        assert "A Series" in grid_view.series_list_widget.item(1).text()

        # 2. Recently Added sorting
        grid_view.sort_selector.setCurrentText("Recently Added")
        assert not grid_view.order_label.isHidden()
        assert not grid_view.order_selector.isHidden()

        # Descending (Newest first, Z Series is 2000, A Series is 1000)
        grid_view.order_selector.setCurrentText("Newest to Oldest")
        assert (
            controller_instance.sort_descending is False
        )  # mapped from "Newest to Oldest" for Recently Added
        assert "Z Series" in grid_view.series_list_widget.item(0).text()
        assert "A Series" in grid_view.series_list_widget.item(1).text()

        # Ascending (Oldest first, A Series is 1000, Z Series is 2000)
        grid_view.order_selector.setCurrentText("Oldest to Newest")
        assert (
            controller_instance.sort_descending is True
        )  # mapped from "Oldest to Newest" for Recently Added
        assert "A Series" in grid_view.series_list_widget.item(0).text()
        assert "Z Series" in grid_view.series_list_widget.item(1).text()

        # 3. Next Up sorting
        grid_view.sort_selector.setCurrentText("Next Up")
        assert grid_view.order_label.isHidden()
        assert grid_view.order_selector.isHidden()


def test_controller_set_sort_descending(qtbot: Any) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = {}

    # Initial state
    assert controller_instance.sort_descending is False

    # Set to descending
    with patch("lan_streamer.system.config.config.save"):
        controller_instance.set_sort_descending(True)
    assert controller_instance.sort_descending is True

    # Set to same value (no-op, should not emit)
    with patch("lan_streamer.system.config.config.save") as mock_save:
        controller_instance.set_sort_descending(True)
    mock_save.assert_not_called()

    # Set back to ascending
    with patch("lan_streamer.system.config.config.save"):
        controller_instance.set_sort_descending(False)
    assert controller_instance.sort_descending is False


def test_on_order_changed_empty_text(qtbot: Any) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = {}

    with patch("lan_streamer.db.load_library", return_value={}):
        grid_view = LibraryGridView(controller_instance)
        qtbot.addWidget(grid_view)

        # Empty text should not change sort direction
        original_descending = controller_instance.sort_descending
        grid_view.on_order_changed("")
        assert controller_instance.sort_descending == original_descending


def test_library_grid_view_recently_aired_sorting(qtbot: Any) -> None:
    library_data = {
        "Old Show": {
            "metadata": {"first_air_date": "2000-01-01"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "watched": False,
                            "last_played_at": 0,
                            "date_added": 1000,
                            "air_date": "2000-06-15",
                            "path": "/old_show_s01e01.mkv",
                        },
                    ]
                }
            },
        },
        "New Show": {
            "metadata": {"first_air_date": "2024-01-01"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "watched": False,
                            "last_played_at": 0,
                            "date_added": 2000,
                            "air_date": "2024-06-15",
                            "path": "/new_show_s01e01.mkv",
                        },
                    ]
                }
            },
        },
    }

    controller_instance = Controller()
    controller_instance.cached_library_data = library_data
    controller_instance._cache_series_metrics()

    with patch("lan_streamer.db.load_library", return_value=library_data):
        grid_view = LibraryGridView(controller_instance)
        qtbot.addWidget(grid_view)
        grid_view.populate_grid()

        # Sort by Recently Aired
        grid_view.sort_selector.setCurrentText("Recently Aired")

        # Default: Newest to Oldest
        grid_view.order_selector.setCurrentText("Newest to Oldest")
        assert "New Show" in grid_view.series_list_widget.item(0).text()
        assert "Old Show" in grid_view.series_list_widget.item(1).text()

        # Reversed: Oldest to Newest
        grid_view.order_selector.setCurrentText("Oldest to Newest")
        assert "Old Show" in grid_view.series_list_widget.item(0).text()
        assert "New Show" in grid_view.series_list_widget.item(1).text()


def test_combined_view_row_management(qtbot: Any) -> None:
    controller_instance = Controller()
    config.libraries["TestLib"] = {"type": "tv", "paths": ["/test"]}

    with patch("lan_streamer.db.load_movie_library", return_value={}):
        dialog_instance = SettingsDialog(controller_instance)
        qtbot.addWidget(dialog_instance)

        # Start with default rows
        initial_count = len(dialog_instance.staged_combined_views)

        # Add a row
        dialog_instance.add_combined_view_row()
        assert len(dialog_instance.staged_combined_views) == initial_count + 1

        # Add another row
        dialog_instance.add_combined_view_row()
        assert len(dialog_instance.staged_combined_views) == initial_count + 2

        last_idx = len(dialog_instance.staged_combined_views) - 1
        second_last_idx = last_idx - 1

        # Save the names for move verification
        name_before_last = dialog_instance.staged_combined_views[second_last_idx][
            "name"
        ]
        name_last = dialog_instance.staged_combined_views[last_idx]["name"]

        # Move last row up
        dialog_instance.combined_views_list_widget.setCurrentRow(last_idx)
        dialog_instance.move_combined_view_row_up()
        assert (
            dialog_instance.staged_combined_views[second_last_idx]["name"] == name_last
        )
        assert (
            dialog_instance.staged_combined_views[last_idx]["name"] == name_before_last
        )

        # Move it back down
        dialog_instance.combined_views_list_widget.setCurrentRow(second_last_idx)
        dialog_instance.move_combined_view_row_down()
        assert (
            dialog_instance.staged_combined_views[second_last_idx]["name"]
            == name_before_last
        )
        assert dialog_instance.staged_combined_views[last_idx]["name"] == name_last

        # Move at boundary (first row can't go up)
        dialog_instance.combined_views_list_widget.setCurrentRow(0)
        dialog_instance.move_combined_view_row_up()  # should be no-op
        assert len(dialog_instance.staged_combined_views) == initial_count + 2

        # Move at boundary (last row can't go down)
        dialog_instance.combined_views_list_widget.setCurrentRow(
            len(dialog_instance.staged_combined_views) - 1
        )
        dialog_instance.move_combined_view_row_down()  # should be no-op
        assert len(dialog_instance.staged_combined_views) == initial_count + 2

        # Delete a row
        dialog_instance.combined_views_list_widget.setCurrentRow(last_idx)
        dialog_instance.delete_combined_view_row()
        assert len(dialog_instance.staged_combined_views) == initial_count + 1

        # Delete with invalid selection (no-op)
        dialog_instance.combined_views_list_widget.setCurrentRow(-1)
        dialog_instance.delete_combined_view_row()
        assert len(dialog_instance.staged_combined_views) == initial_count + 1

        # Test library toggle
        if dialog_instance.staged_combined_views:
            dialog_instance.combined_views_list_widget.setCurrentRow(0)
            dialog_instance._on_combined_view_selected()

            # Toggle a library checkbox if any exist
            for layout_index in range(dialog_instance.row_libraries_layout.count()):
                layout_item = dialog_instance.row_libraries_layout.itemAt(layout_index)
                if layout_item is not None:
                    widget = layout_item.widget()
                    if isinstance(widget, QCheckBox):
                        widget.setChecked(True)
                        break

            dialog_instance._on_row_library_toggled()
            row = dialog_instance.staged_combined_views[0]
            assert isinstance(row.get("libraries"), list)


def test_combined_view_scan_button(qtbot: Any) -> None:
    config.enable_combined_view = True
    controller_instance = Controller()

    with patch("lan_streamer.db.get_combined_smart_row", return_value=[]):
        grid_view = LibraryGridView(controller_instance)
        grid_view.populate_libraries(["TV Library"])
        qtbot.addWidget(grid_view)

        # 1. Switch to Combined View
        grid_view.library_selector.setCurrentText("Combined View")
        # Verify combined actions toolbar is visible and standard actions toolbar is hidden
        assert grid_view.combined_actions_toolbar_widget.isHidden() is False
        assert grid_view.actions_toolbar_widget.isHidden() is True

        # 2. Click the Scan New Files button in Combined View
        with patch.object(controller_instance, "trigger_scan_all") as mock_scan_all:
            combined_scan_button = grid_view.combined_actions_toolbar_widget.findChild(
                QPushButton
            )
            assert combined_scan_button is not None
            assert combined_scan_button.text() == "Scan Library"
            combined_scan_button.click()
            mock_scan_all.assert_called_once_with(False)

        # 3. Simulate scan progress signals
        tree_payload = {
            "tree": {
                "TV Library": {"type": "tv", "roots": {"/media/tv": {"Cosmos": {}}}}
            }
        }
        controller_instance.detail_progress_updated.emit("init_tree", tree_payload)
        # Check that progress bar and label became visible
        assert grid_view.scan_progress_bar.isHidden() is False
        assert grid_view.scan_status_label.isHidden() is False
        assert grid_view.scan_status_label.text() == "Starting global library scan..."

        # Emit start_folder signal
        folder_payload = {
            "library": "TV Library",
            "root": "/media/tv",
            "folder": "Cosmos",
        }
        controller_instance.detail_progress_updated.emit("start_folder", folder_payload)
        assert (
            grid_view.scan_status_label.text()
            == "Scanning [TV Library]: /media/tv > Cosmos"
        )

        # Emit scan_completed signal
        controller_instance.scan_completed.emit()
        assert grid_view.scan_progress_bar.isHidden() is True
        assert grid_view.scan_status_label.isHidden() is True

        # 4. Simulate _on_scan_all_finished when in Combined View
        controller_instance.current_library_name = "Combined View"
        with patch.object(controller_instance, "select_library") as mock_select:
            with patch.object(grid_view, "populate_combined_view") as mock_populate:
                controller_instance._on_scan_all_finished()
                mock_select.assert_not_called()
                mock_populate.assert_called_once()
