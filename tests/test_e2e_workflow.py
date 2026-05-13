import pytest
from unittest.mock import patch
from typing import Any, Dict, List, Optional
from PySide6.QtWidgets import (
    QCheckBox,
    QPushButton,
    QTableWidget,
    QListWidgetItem,
)

from lan_streamer.ui_views import (
    Controller,
    LibraryGridView,
    SeriesDetailView,
    MetadataMatchDialog,
    RenamePreviewDialog,
    SettingsDialog,
    get_application_stylesheet,
)
from lan_streamer.config import config


@pytest.fixture
def sample_library_dictionary() -> Dict[str, Any]:
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
                            "name": "ep1.mkv",
                            "path": "/media/Cosmos/Season 1/ep1.mkv",
                            "watched": False,
                            "tmdb_number": 1,
                            "tmdb_name": "The Shores of the Cosmic Ocean",
                            "date_added": 1000,
                            "air_date": "1980-09-28",
                        },
                        {
                            "name": "ep2.mkv",
                            "path": "/media/Cosmos/Season 1/ep2.mkv",
                            "watched": True,
                            "tmdb_number": 2,
                            "tmdb_name": "One Voice in the Cosmic Fugue",
                            "date_added": 2000,
                            "air_date": "1980-10-05",
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
    config.libraries["Test Lib"] = ["/path/to/media"]

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

    detail_view.populate_series_details("Cosmos")

    assert detail_view.title_label.text() == "Cosmos: A Personal Voyage"
    assert "Space exploration" in detail_view.overview_label.text()
    assert detail_view.seasons_tab_widget.count() == 1
    assert detail_view.seasons_tab_widget.tabText(0) == "Season 1"

    # Verify table row properties
    table_widget: Optional[Any] = detail_view.seasons_tab_widget.widget(0)
    assert isinstance(table_widget, QTableWidget)
    assert table_widget.rowCount() == 2
    table_item = table_widget.item(0, 1)
    assert table_item is not None
    assert table_item.text() == "The Shores of the Cosmic Ocean"


def test_e2e_checkbox_toggled_marks_watched(
    sample_library_dictionary: Dict[str, Any], qtbot: Any
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance._cache_series_metrics()

    detail_view = SeriesDetailView(controller_instance)
    qtbot.addWidget(detail_view)
    detail_view.populate_series_details("Cosmos")

    table_widget: Optional[Any] = detail_view.seasons_tab_widget.widget(0)
    assert isinstance(table_widget, QTableWidget)

    # Locate inner checkbox widget cleanly
    container_widget: Optional[Any] = table_widget.cellWidget(0, 2)
    assert container_widget is not None
    checkbox_instance: Optional[QCheckBox] = container_widget.findChild(QCheckBox)
    assert checkbox_instance is not None

    with patch("lan_streamer.db.update_episode_watched_status") as mock_db:
        checkbox_instance.setChecked(True)
        mock_db.assert_called_once_with("/media/Cosmos/Season 1/ep1.mkv", True)
        assert (
            controller_instance.cached_library_data["Cosmos"]["seasons"]["Season 1"][
                "episodes"
            ][0]["watched"]
            is True
        )


def test_e2e_play_button_triggers_playback(
    sample_library_dictionary: Dict[str, Any], qtbot: Any
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance._cache_series_metrics()

    detail_view = SeriesDetailView(controller_instance)
    qtbot.addWidget(detail_view)
    detail_view.populate_series_details("Cosmos")

    play_button_instance: Optional[QPushButton] = detail_view.get_play_button_by_row(
        season_tab_index=0, row_index=0
    )
    assert play_button_instance is not None

    requested_paths_emitted: List[str] = []
    controller_instance.playback_requested.connect(requested_paths_emitted.append)

    play_button_instance.click()
    assert requested_paths_emitted == ["/media/Cosmos/Season 1/ep1.mkv"]


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


def test_rename_preview_dialog_workflow(
    sample_library_dictionary: Dict[str, Any], qtbot: Any
) -> None:
    controller_instance = Controller()
    controller_instance.cached_library_data = sample_library_dictionary
    controller_instance.current_library_name = "Test Lib"

    with patch("lan_streamer.renamer.get_rename_preview") as mock_preview:
        mock_preview.return_value = [
            {
                "old_name": "ep1.mkv",
                "new_name": "Cosmos S01E01 - The Shores of the Cosmic Ocean.mkv",
                "old_path": "/media/Cosmos/Season 1/ep1.mkv",
                "new_path": "/media/Cosmos/Season 1/Cosmos S01E01 - The Shores of the Cosmic Ocean.mkv",
            }
        ]

        dialog_instance = RenamePreviewDialog("Cosmos", controller_instance)
        qtbot.addWidget(dialog_instance)

        assert dialog_instance.preview_table.rowCount() == 1
        preview_item = dialog_instance.preview_table.item(0, 0)
        assert preview_item is not None
        assert preview_item.text() == "ep1.mkv"

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
    dialog_instance.save_config()

    assert config.jellyfin_url == "http://localhost:8096"
    assert config.use_embedded_player is False
    assert config.enable_caching is True
    assert config.enable_hw_accel is False
    assert config.database_path == "/custom/lib.db"
    assert config.log_directory == "/custom/logs"
    assert config.max_log_retention_days == 14

    # Test ValueError fallback coverage
    dialog_instance.log_retention_input.setText("invalid_days")
    dialog_instance.save_config()
    assert config.max_log_retention_days == 14


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
            in dialog_instance.staged_libraries["UniqueTestCinematicLib999"]
        )

        # Test Remove Directory
        dialog_instance.directory_list_widget.setCurrentRow(0)
        dialog_instance.remove_staged_directory()
        assert (
            "/media/cinematic"
            not in dialog_instance.staged_libraries["UniqueTestCinematicLib999"]
        )

        # Test Remove Library
        dialog_instance.remove_staged_library()
        assert "UniqueTestCinematicLib999" not in dialog_instance.staged_libraries
