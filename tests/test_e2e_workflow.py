import pytest
from unittest.mock import patch, MagicMock
from typing import Any, Dict, List, Optional
from PySide6.QtWidgets import (
    QPushButton,
    QTableWidget,
    QListWidgetItem,
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
    get_application_stylesheet,
)
from lan_streamer.config import config


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


def test_stylesheet_validity() -> None:
    css_content: str = get_application_stylesheet()
    assert "background-color" in css_content
    assert "border-radius" in css_content


def test_controller_metrics_caching(sample_library_dictionary: Dict[str, Any]) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance._cache_series_metrics()

    metrics_dictionary: Dict[str, Any] = sample_library_dictionary["Cosmos"]["metrics"]
    assert metrics_dictionary["total_episodes"] == 2
    assert metrics_dictionary["watched_episodes"] == 1
    assert metrics_dictionary["max_date_added"] == 2000
    assert metrics_dictionary["max_air_date"] == "1980-10-05"


def test_controller_library_selection(
    sample_library_dictionary: Dict[str, Any],
) -> None:
    controller_instance = Controller()
    with patch("lan_streamer.db.load_library", return_value=sample_library_dictionary):
        loaded_signals_emitted: List[bool] = []
        controller_instance.library_loaded.connect(
            lambda: loaded_signals_emitted.append(True)
        )

        controller_instance.select_library("Main Media")
        assert controller_instance.current_library_name == "Main Media"
        assert len(loaded_signals_emitted) == 1
        assert "Cosmos" in controller_instance.cached_library_data


def test_controller_sorting_and_filtering() -> None:
    controller_instance = Controller()
    loaded_signals_emitted: List[bool] = []
    controller_instance.library_loaded.connect(
        lambda: loaded_signals_emitted.append(True)
    )

    target_mode: str = (
        "Recently Aired"
        if controller_instance.sort_mode == "Recently Added"
        else "Recently Added"
    )
    controller_instance.set_sort_mode(target_mode)
    assert controller_instance.sort_mode == target_mode
    assert config.sort_mode == target_mode
    assert len(loaded_signals_emitted) == 1

    initial_filter: bool = controller_instance.filter_out_watched
    controller_instance.set_filter_out_watched(not initial_filter)
    assert controller_instance.filter_out_watched is not initial_filter
    assert config.filter_out_watched is not initial_filter
    assert len(loaded_signals_emitted) == 2


def test_controller_triggers(qtbot: Any) -> None:
    controller_instance = Controller()
    controller_instance.current_library_name = "Test Lib"
    config.libraries["Test Lib"] = {"type": "tv", "paths": ["/path/to/media"]}

    with patch("lan_streamer.ui_views.ScanWorker") as mock_scan:
        controller_instance.trigger_scan(force_refresh=True)
        mock_scan.assert_called_once()
        mock_scan.return_value.start.assert_called_once()

    with patch("lan_streamer.ui_views.CleanupWorker") as mock_cleanup:
        controller_instance.trigger_cleanup()
        mock_cleanup.assert_called_once()
        mock_cleanup.return_value.start.assert_called_once()


def test_controller_jellyfin_sync_triggers() -> None:
    controller_instance = Controller()
    with patch(
        "lan_streamer.ui_views.jellyfin_client.is_configured", return_value=True
    ):
        with patch("lan_streamer.ui_views.JellyfinPullWorker") as mock_pull:
            controller_instance.trigger_jellyfin_pull()
            mock_pull.assert_called_once()

        with patch("lan_streamer.ui_views.JellyfinPushWorker") as mock_push:
            controller_instance.trigger_jellyfin_push()
            mock_push.assert_called_once()


def test_library_grid_view_rendering(
    sample_library_dictionary: Dict[str, Any], qtbot: Any
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance._cache_series_metrics()

    with patch("lan_streamer.db.load_library", return_value=sample_library_dictionary):
        grid_view = LibraryGridView(controller_instance)
        qtbot.addWidget(grid_view)

        grid_view.populate_libraries(["Test Lib 1", "Test Lib 2"])
        assert grid_view.library_selector.count() == 2

        # Populate items
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


def test_series_detail_view_rendering(
    sample_library_dictionary: Dict[str, Any], qtbot: Any
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
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
    assert table_widget.rowCount() == 2
    table_item = table_widget.item(0, 2)
    assert table_item is not None
    assert table_item.text() == "The Shores of the Cosmic Ocean"
    air_date_item = table_widget.item(0, 3)
    assert air_date_item is not None
    assert air_date_item.text() == "1980-09-28"
    runtime_item = table_widget.item(0, 4)
    assert runtime_item is not None
    assert runtime_item.text() == "60 min"


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

    from unittest.mock import patch, MagicMock

    with patch("lan_streamer.ui_views.QMenu") as mock_qmenu_class:
        mock_menu_instance = MagicMock()
        mock_qmenu_class.return_value = mock_menu_instance

        item = table_widget.item(0, 2)
        assert item is not None
        pos = table_widget.visualItemRect(item).center()
        table_widget.customContextMenuRequested.emit(pos)

        assert mock_menu_instance.exec.called
        assert mock_menu_instance.addAction.called
        action = mock_menu_instance.addAction.call_args[0][0]
        assert "Mark as Watched" in action.text()
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

        item = table_widget.item(1, 2)
        assert item is not None
        pos = table_widget.visualItemRect(item).center()
        table_widget.customContextMenuRequested.emit(pos)

        assert mock_menu_instance.exec.called
        assert mock_menu_instance.addAction.called
        action = mock_menu_instance.addAction.call_args[0][0]
        assert "Mark as Unwatched" in action.text()
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

        with patch("lan_streamer.db.save_library") as mock_save:
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

    with patch("lan_streamer.renamer.get_rename_preview") as mock_preview:
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

        assert dialog_instance.preview_table.rowCount() == 1
        preview_item = dialog_instance.preview_table.item(0, 0)
        assert preview_item is not None
        assert preview_item.text() == "test_video.mkv"

        def side_effect_perform(
            preview_results: List[Dict[str, Any]], success_callback: Any
        ) -> None:
            for item_dictionary in preview_results:
                success_callback(
                    item_dictionary["old_path"], item_dictionary["new_path"]
                )

        with patch(
            "lan_streamer.renamer.perform_rename", side_effect=side_effect_perform
        ) as mock_perform:
            dialog_instance.apply_renames()
            mock_perform.assert_called_once()


def test_settings_dialog_lifecycle(qtbot: Any) -> None:
    dialog_instance = SettingsDialog()
    qtbot.addWidget(dialog_instance)

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


def test_controller_worker_slots(sample_library_dictionary: Dict[str, Any]) -> None:
    controller_instance = Controller()
    controller_instance.current_library_name = "Cosmos"
    controller_instance.selected_series_name = "Cosmos"
    controller_instance.cached_library_data = sample_library_dictionary

    with patch("lan_streamer.db.save_library") as mock_save:
        controller_instance._on_scan_finished(sample_library_dictionary)
        mock_save.assert_called_once()

    with patch("lan_streamer.ui_views.Controller.select_library") as mock_select:
        controller_instance._on_cleanup_finished({"series": 1})
        mock_select.assert_called_once_with("Cosmos")

    with patch("lan_streamer.ui_views.Controller.select_library") as mock_select:
        controller_instance._on_pull_finished(5)
        mock_select.assert_called_once_with("Cosmos")

    controller_instance._on_push_finished(10)
    controller_instance._on_worker_error("Test Worker Exception")


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
        patch("lan_streamer.backup.restore_config_backup", return_value=True),
        patch("lan_streamer.ui_views.QMessageBox.information") as mock_info,
    ):
        dialog_instance.trigger_restore_config()
        mock_info.assert_called_once()

    with (
        patch(
            "lan_streamer.ui_views.QFileDialog.getOpenFileName",
            return_value=("/path/to/backup.db", ""),
        ),
        patch("lan_streamer.backup.restore_database_backup", return_value=True),
        patch("lan_streamer.ui_views.QMessageBox.information") as mock_info,
    ):
        dialog_instance.trigger_restore_database()
        mock_info.assert_called_once()


def test_controller_partial_scan_updates() -> None:
    controller_instance = Controller()
    controller_instance.current_library_name = "TestCinematic"
    partial_library = {"Avatar": {"metadata": {"poster_path": "/avatar.jpg"}}}
    mock_slot = MagicMock()
    controller_instance.library_loaded.connect(mock_slot)
    controller_instance._on_scan_partial(partial_library)
    assert controller_instance.cached_library_data == partial_library
    mock_slot.assert_called_once()


def test_controller_file_system_monitoring(
    sample_library_dictionary: Dict[str, Any], qtbot: Any, tmp_path: Any
) -> None:
    controller_instance = Controller()
    media_directory = tmp_path / "cinematic_roots"
    media_directory.mkdir()
    directory_path_string = str(media_directory)

    config.libraries["ActiveMonitoredLib"] = {
        "type": "tv",
        "paths": [directory_path_string],
    }

    with patch("lan_streamer.db.load_library", return_value=sample_library_dictionary):
        controller_instance.select_library("ActiveMonitoredLib")
        assert (
            directory_path_string
            in controller_instance.file_system_watcher.directories()
        )

        with patch.object(controller_instance.debounce_timer, "start") as mock_start:
            controller_instance._on_directory_changed(directory_path_string)
            mock_start.assert_not_called()

        with patch.object(controller_instance, "trigger_scan") as mock_trigger:
            controller_instance._on_debounce_timeout()
            mock_trigger.assert_not_called()

        # Test concurrency protection
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        controller_instance.scan_worker_instance = mock_worker
        controller_instance.current_library_name = "ActiveMonitoredLib"

        with patch("lan_streamer.ui_views.ScanWorker") as mock_worker_constructor:
            controller_instance.trigger_scan(force_refresh=False)
            mock_worker_constructor.assert_not_called()


def test_controller_global_triggers() -> None:
    controller_instance = Controller()
    controller_instance.current_library_name = "CosmosLib"

    with patch("lan_streamer.ui_views.ScanAllLibrariesWorker") as mock_scan_all:
        controller_instance.trigger_scan_all(force_refresh=True)
        mock_scan_all.assert_called_once_with(force_refresh=True)
        mock_scan_all.return_value.start.assert_called_once()

        # Test concurrency protection
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        controller_instance.scan_all_worker_instance = mock_worker
        controller_instance.trigger_scan_all(force_refresh=False)
        assert mock_scan_all.call_count == 1

        # Test finished callback
        with patch.object(controller_instance, "select_library") as mock_select:
            controller_instance._on_scan_all_finished()
            mock_select.assert_called_once_with("CosmosLib")

    with patch("lan_streamer.ui_views.CleanupAllLibrariesWorker") as mock_cleanup_all:
        controller_instance.trigger_cleanup_all()
        mock_cleanup_all.assert_called_once()
        mock_cleanup_all.return_value.start.assert_called_once()

        # Test concurrency protection
        mock_worker_clean = MagicMock()
        mock_worker_clean.isRunning.return_value = True
        controller_instance.cleanup_all_worker_instance = mock_worker_clean
        controller_instance.trigger_cleanup_all()
        assert mock_cleanup_all.call_count == 1

        # Test finished callback
        with patch.object(controller_instance, "select_library") as mock_select:
            controller_instance._on_cleanup_all_finished()
            mock_select.assert_called_once_with("CosmosLib")


def test_settings_dialog_global_actions(qtbot: Any) -> None:
    controller_instance = Controller()
    dialog_instance = SettingsDialog(controller_instance)
    qtbot.addWidget(dialog_instance)

    with patch.object(controller_instance, "trigger_scan_all") as mock_scan_all:
        dialog_instance.trigger_global_scan_files()
        mock_scan_all.assert_called_once_with(False)
        assert (
            dialog_instance.global_progress_bar.format()
            == "Starting global file scan..."
        )

        dialog_instance.force_refresh_checkbox.setChecked(True)
        dialog_instance.trigger_global_refresh_metadata()
        mock_scan_all.assert_called_with(True)

    with patch.object(controller_instance, "trigger_cleanup_all") as mock_clean_all:
        dialog_instance.trigger_global_cleanup()
        mock_clean_all.assert_called_once()

    with patch.object(controller_instance, "trigger_jellyfin_pull") as mock_pull:
        dialog_instance.trigger_global_jellyfin_pull()
        mock_pull.assert_called_once()

    with patch.object(controller_instance, "trigger_jellyfin_push") as mock_push:
        dialog_instance.trigger_global_jellyfin_push()
        mock_push.assert_called_once()

    # Test progress slot
    dialog_instance._on_global_progress("TV_Lib", 1, 5)
    assert dialog_instance.global_progress_bar.maximum() == 5
    assert dialog_instance.global_progress_bar.value() == 1
    assert "TV_Lib" in dialog_instance.global_progress_bar.format()

    # Test jellyfin progress callback
    dialog_instance._complete_jellyfin_progress("Complete Message")
    assert dialog_instance.global_progress_bar.value() == 100
    assert dialog_instance.global_progress_bar.format() == "Complete Message"

    # Test no controller instance handles safely
    dialog_no_controller = SettingsDialog(None)
    dialog_no_controller.trigger_global_scan_files()
    dialog_no_controller.trigger_global_cleanup()
    dialog_no_controller.trigger_global_refresh_metadata()
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
    with patch("lan_streamer.ui_views.RuntimeExtractionWorker") as mock_worker_class:
        controller_instance.trigger_runtime_extraction()
        mock_worker_class.assert_called_once()
        mock_worker_instance = mock_worker_class.return_value
        mock_worker_instance.start.assert_called_once()

        # concurrency check
        controller_instance.runtime_worker_instance = mock_worker_instance
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
            mock_select.assert_called_once_with("MovieLib")

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
        mock_merge_class.assert_called_once_with("/video.mkv", ["/sub.srt"])
        mock_merge_instance = mock_merge_class.return_value
        mock_merge_instance.start.assert_called_once()

        # concurrency check
        controller_instance.merge_subtitle_worker_instance = mock_merge_instance
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
        mock_embed_class.assert_called_once_with("/video.mkv", {"title": "Title"})
        mock_embed_instance = mock_embed_class.return_value
        mock_embed_instance.start.assert_called_once()

        # concurrency check
        controller_instance.embed_metadata_worker_instance = mock_embed_instance
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
        controller_instance.embed_metadata_worker_instance = mock_embed_instance
        controller_instance.embed_metadata_series("Show1")
        mock_series_embed_class.assert_not_called()

        # normal case
        controller_instance.embed_metadata_worker_instance = None
        controller_instance.embed_metadata_series("Show1")
        mock_series_embed_class.assert_called_once_with("Show1", [{"path": "/ep1.mkv"}])

        # no episodes case
        controller_instance.embed_metadata_worker_instance = None
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
            "lan_streamer.opensubtitles.opensubtitles_client.search_subtitles",
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
        "lan_streamer.opensubtitles.opensubtitles_client.search_subtitles",
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
        "lan_streamer.opensubtitles.opensubtitles_client.search_subtitles",
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
        "lan_streamer.opensubtitles.opensubtitles_client.search_subtitles",
        return_value=sub_results,
    ):
        movie_dialog._on_search_clicked()
        movie_dialog.results_table.selectRow(0)

        # B. No download URL
        with (
            patch(
                "lan_streamer.opensubtitles.opensubtitles_client.get_download_link",
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
                "lan_streamer.opensubtitles.opensubtitles_client.get_download_link",
                return_value="http://download.url",
            ) as mock_link,
            patch(
                "lan_streamer.opensubtitles.opensubtitles_client.download_subtitle",
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
                "lan_streamer.opensubtitles.opensubtitles_client.get_download_link",
                return_value="http://download.url",
            ),
            patch(
                "lan_streamer.opensubtitles.opensubtitles_client.download_subtitle",
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
                "lan_streamer.opensubtitles.opensubtitles_client.get_download_link",
                return_value="http://download.url",
            ),
            patch(
                "lan_streamer.opensubtitles.opensubtitles_client.download_subtitle",
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
                "lan_streamer.opensubtitles.opensubtitles_client.get_download_link",
                return_value="http://download.url",
            ),
            patch(
                "lan_streamer.opensubtitles.opensubtitles_client.download_subtitle",
                return_value=b"subtitle data",
            ),
            patch("builtins.open", side_effect=IOError("Write permission denied")),
            patch("lan_streamer.ui_views.QMessageBox.critical") as mock_crit,
        ):
            movie_dialog._on_download_clicked()
            mock_crit.assert_called_once()
