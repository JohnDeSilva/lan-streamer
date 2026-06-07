import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QMessageBox, QLabel
from lan_streamer.ui_views import (
    Controller,
    EpisodeDetailsDialog,
    MovieDetailsDialog,
    SeriesDetailsDialog,
)


# ---------------------------------------------------------------------------
# Episode Details Dialog Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_episode_controller():
    controller = Controller()
    controller.cached_library_data = {
        "Test Series": {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "E01.mkv",
                            "path": "/media/Test Series/S01E01.mkv",
                            "tmdb_name": "Original Title",
                            "runtime": 45,
                            "air_date": "2023-01-01",
                            "locked_metadata": False,
                        }
                    ]
                }
            }
        }
    }
    controller.current_library_name = "TestLib"
    return controller


def test_episode_details_dialog_loading(mock_episode_controller, qtbot):
    with patch("lan_streamer.scanner.get_detailed_file_info") as mock_info:
        mock_info.return_value = {
            "path": "/media/Test Series/S01E01.mkv",
            "size_bytes": 1024 * 1024 * 100,
            "video_type": "MKV",
            "resolution": "1920x1080",
            "audio_tracks": [
                {"index": 1, "codec": "ac3", "language": "en", "title": "Surround"}
            ],
            "subtitle_tracks": [
                {"index": 2, "codec": "srt", "language": "en", "title": "English"}
            ],
        }

        dialog = EpisodeDetailsDialog(
            "Test Series", "/media/Test Series/S01E01.mkv", mock_episode_controller
        )
        qtbot.addWidget(dialog)

        assert dialog.title_edit.text() == "Original Title"
        assert dialog.runtime_edit.text() == "45"
        assert dialog.air_date_edit.text() == "2023-01-01"
        assert dialog.locked_checkbox.isChecked() is False

        assert "100.00 MB" in dialog.size_label.text()
        assert "1920x1080" in dialog.resolution_label.text()
        assert dialog.audio_list.count() == 1
        assert "ac3" in dialog.audio_list.item(0).text()


def test_episode_details_save_metadata(mock_episode_controller, qtbot):
    with patch("lan_streamer.scanner.get_detailed_file_info") as mock_info:
        mock_info.return_value = {
            "path": "/media/Test Series/S01E01.mkv",
            "size_bytes": 0,
            "video_type": "MKV",
            "resolution": "Unknown",
            "audio_tracks": [],
            "subtitle_tracks": [],
        }
        dialog = EpisodeDetailsDialog(
            "Test Series", "/media/Test Series/S01E01.mkv", mock_episode_controller
        )
        qtbot.addWidget(dialog)

        dialog.title_edit.setText("New Title")
        dialog.runtime_edit.setText("50")
        dialog.locked_checkbox.setChecked(True)

        with patch("lan_streamer.db.save_library") as mock_save:
            dialog._on_save_clicked()
            mock_save.assert_called_once()

            ep = mock_episode_controller.cached_library_data["Test Series"]["seasons"][
                "Season 1"
            ]["episodes"][0]
            assert ep["tmdb_name"] == "New Title"
            assert ep["runtime"] == 50
            assert ep["locked_metadata"] is True


def test_episode_details_merge_subtitles_trigger(mock_episode_controller, qtbot):
    with patch("lan_streamer.scanner.get_detailed_file_info") as mock_info:
        mock_info.return_value = {
            "path": "/media/Test Series/S01E01.mkv",
            "size_bytes": 0,
            "video_type": "MKV",
            "resolution": "Unknown",
            "audio_tracks": [],
            "subtitle_tracks": [],
        }
        dialog = EpisodeDetailsDialog(
            "Test Series", "/media/Test Series/S01E01.mkv", mock_episode_controller
        )
        qtbot.addWidget(dialog)

        dialog._ext_subs = ["/media/Test Series/S01E01.en.srt"]

        with patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            with patch.object(mock_episode_controller, "merge_subtitles") as mock_merge:
                dialog._on_merge_clicked()
                mock_merge.assert_called_once_with(
                    "/media/Test Series/S01E01.mkv",
                    ["/media/Test Series/S01E01.en.srt"],
                )


# ---------------------------------------------------------------------------
# Movie Details Dialog Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_movie_controller():
    controller = Controller()
    controller.cached_library_data = {
        "Test Movie": {
            "name": "Test Movie",
            "path": "/media/Movies/Test Movie.mkv",
            "tmdb_name": "Original Movie Title",
            "runtime": 120,
            "year": 2022,
            "rating": "8.5",
            "genre": "Sci-Fi",
            "locked_metadata": False,
        }
    }
    controller.current_library_name = "MoviesLib"
    return controller


def test_movie_details_dialog_loading(mock_movie_controller, qtbot):
    with patch("lan_streamer.scanner.get_detailed_file_info") as mock_info:
        mock_info.return_value = {
            "path": "/media/Movies/Test Movie.mkv",
            "size_bytes": 1024 * 1024 * 500,
            "video_type": "MKV",
            "resolution": "3840x2160",
            "audio_tracks": [
                {"index": 1, "codec": "dts", "language": "en", "title": "Master Audio"}
            ],
            "subtitle_tracks": [
                {"index": 2, "codec": "ass", "language": "en", "title": "Full Subs"}
            ],
        }

        dialog = MovieDetailsDialog(
            "Test Movie", "/media/Movies/Test Movie.mkv", mock_movie_controller
        )
        qtbot.addWidget(dialog)

        assert dialog.title_edit.text() == "Original Movie Title"
        assert dialog.runtime_edit.text() == "120"
        assert dialog.year_edit.text() == "2022"
        assert dialog.rating_edit.text() == "8.5"
        assert dialog.genre_edit.text() == "Sci-Fi"
        assert dialog.locked_checkbox.isChecked() is False

        assert "500.00 MB" in dialog.size_label.text()
        assert "3840x2160" in dialog.resolution_label.text()
        assert dialog.codec_label.text() == "Unknown"
        assert dialog.audio_list.count() == 1


def test_movie_details_save_metadata(mock_movie_controller, qtbot):
    with patch("lan_streamer.scanner.get_detailed_file_info") as mock_info:
        mock_info.return_value = {
            "path": "/media/Movies/Test Movie.mkv",
            "size_bytes": 0,
            "video_type": "MKV",
            "video_codec": "h264",
            "resolution": "Unknown",
            "audio_tracks": [],
            "subtitle_tracks": [],
        }
        dialog = MovieDetailsDialog(
            "Test Movie", "/media/Movies/Test Movie.mkv", mock_movie_controller
        )
        qtbot.addWidget(dialog)

        assert dialog.codec_label.text() == "h264"

        dialog.title_edit.setText("New Movie Title")
        dialog.runtime_edit.setText("130")
        dialog.year_edit.setText("2023")
        dialog.locked_checkbox.setChecked(True)

        with patch("lan_streamer.db.save_library") as mock_save:
            dialog._on_save_clicked()
            mock_save.assert_called_once()

            movie = mock_movie_controller.cached_library_data["Test Movie"]
            assert movie["tmdb_name"] == "New Movie Title"
            assert movie["runtime"] == 130
            assert movie["year"] == 2023
            assert movie["locked_metadata"] is True


def test_movie_details_embed_metadata_trigger(mock_movie_controller, qtbot):
    with patch("lan_streamer.scanner.get_detailed_file_info") as mock_info:
        mock_info.return_value = {
            "path": "/media/Movies/Test Movie.mkv",
            "size_bytes": 0,
            "video_type": "MKV",
            "resolution": "Unknown",
            "audio_tracks": [],
            "subtitle_tracks": [],
        }
        dialog = MovieDetailsDialog(
            "Test Movie", "/media/Movies/Test Movie.mkv", mock_movie_controller
        )
        qtbot.addWidget(dialog)

        with patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            with patch.object(mock_movie_controller, "embed_metadata") as mock_embed:
                dialog._on_embed_clicked()
                mock_embed.assert_called_once()
                args = mock_embed.call_args[0]
                assert args[0] == "/media/Movies/Test Movie.mkv"
                assert "title" in args[1]


def test_movie_details_merge_subtitles_trigger(mock_movie_controller, qtbot):
    with patch("lan_streamer.scanner.get_detailed_file_info") as mock_info:
        mock_info.return_value = {
            "path": "/media/Movies/Test Movie.mkv",
            "size_bytes": 0,
            "video_type": "MKV",
            "resolution": "Unknown",
            "audio_tracks": [],
            "subtitle_tracks": [],
        }
        dialog = MovieDetailsDialog(
            "Test Movie", "/media/Movies/Test Movie.mkv", mock_movie_controller
        )
        qtbot.addWidget(dialog)

        dialog._ext_subs = ["/media/Movies/Test Movie.en.srt"]

        with patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            with patch.object(mock_movie_controller, "merge_subtitles") as mock_merge:
                dialog._on_merge_clicked()
                mock_merge.assert_called_once_with(
                    "/media/Movies/Test Movie.mkv", ["/media/Movies/Test Movie.en.srt"]
                )


# ---------------------------------------------------------------------------
# Series Details Dialog Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_series_controller():
    controller = Controller()
    controller.cached_library_data = {
        "Cosmos": {
            "metadata": {"tmdb_name": "Cosmos", "locked_metadata": False},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": "/media/tv/Cosmos/S01E01.mkv",
                            "name": "Ep1",
                            "tmdb_number": 1,
                            "air_date": "1980-01-01",
                        },
                        {
                            "path": "/media/tv/Cosmos/S01E02.mkv",
                            "name": "Ep2",
                            "tmdb_number": 2,
                            "air_date": "1980-01-08",
                        },
                    ]
                }
            },
        }
    }
    controller.current_library_name = "TV"
    return controller


def test_series_details_dialog_loading(mock_series_controller, qtbot):
    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)

    assert dialog.name_edit.text() == "Cosmos"
    labels = dialog.findChildren(QLabel)
    path_found = any("/media/tv" in label.text() for label in labels)
    assert path_found is True


def test_series_details_save_name(mock_series_controller, qtbot):
    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)

    dialog.name_edit.setText("Cosmos (1980)")
    with patch.object(mock_series_controller, "update_series_name") as mock_update:
        dialog._on_save_clicked()
        mock_update.assert_called_once_with("Cosmos", "Cosmos (1980)")


def test_series_details_match_buttons(mock_series_controller, qtbot):
    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(
        mock_series_controller.metadata_dialog_requested, timeout=1000
    ):
        dialog._on_match_meta_clicked()

    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)
    with patch(
        "lan_streamer.ui_views.proxy.jellyfin_client.is_configured",
        return_value=True,
    ):
        with qtbot.waitSignal(
            mock_series_controller.jellyfin_dialog_requested, timeout=1000
        ):
            dialog._on_match_jellyfin_clicked()

    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(mock_series_controller.rename_dialog_requested, timeout=1000):
        dialog._on_rename_clicked()


def test_series_details_embed_bulk_trigger(mock_series_controller, qtbot):
    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        with patch.object(
            mock_series_controller, "embed_metadata_series"
        ) as mock_embed:
            dialog._on_embed_clicked()
            mock_embed.assert_called_once_with("Cosmos")


def test_series_details_mark_watched_trigger(mock_series_controller, qtbot):
    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)

    with patch.object(mock_series_controller, "mark_series_watched") as mock_mark:
        dialog._on_mark_watched_clicked()
        mock_mark.assert_called_once_with("Cosmos")


# ---------------------------------------------------------------------------
# Dialog Optimization Trigger Tests (from tests/test_metadata_optimization.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_opt_controller():
    controller = Controller()
    controller.cached_library_data = {
        "Test Show": {
            "metadata": {
                "tmdb_identifier": "12345",
                "tmdb_name": "Test Show",
                "overview": "Show overview",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": "/media/tv/Test Show/Season 1/S01E01.mkv",
                            "name": "Pilot",
                            "tmdb_number": 1,
                            "air_date": "2020-01-01",
                        }
                    ]
                }
            },
        },
        "Test Movie": {
            "path": "/media/movies/Test Movie.mkv",
            "tmdb_identifier": "54321",
            "tmdb_name": "Test Movie",
            "locked_metadata": False,
        },
    }
    controller.current_library_name = "test_lib"
    controller.selected_series_name = "Test Show"
    return controller


def test_series_details_dialog_lock(mock_opt_controller, qtbot):
    dialog = SeriesDetailsDialog("Test Show", mock_opt_controller)
    qtbot.addWidget(dialog)

    assert dialog.locked_checkbox.isChecked() is False
    dialog.locked_checkbox.setChecked(True)

    with patch.object(mock_opt_controller, "toggle_series_lock") as mock_toggle:
        dialog._on_save_clicked()
        mock_toggle.assert_called_once_with("Test Show", True)


def test_episode_details_dialog_refresh(mock_opt_controller, qtbot):
    dialog = EpisodeDetailsDialog(
        "Test Show", "/media/tv/Test Show/Season 1/S01E01.mkv", mock_opt_controller
    )
    qtbot.addWidget(dialog)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        with patch.object(
            mock_opt_controller, "refresh_episode_metadata"
        ) as mock_refresh:
            dialog._on_refresh_clicked()
            mock_refresh.assert_called_once_with(
                "Test Show", "/media/tv/Test Show/Season 1/S01E01.mkv"
            )


def test_series_details_dialog_refresh(mock_opt_controller, qtbot):
    dialog = SeriesDetailsDialog("Test Show", mock_opt_controller)
    qtbot.addWidget(dialog)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        with patch.object(
            mock_opt_controller, "trigger_series_refresh"
        ) as mock_refresh:
            dialog._on_refresh_clicked()
            mock_refresh.assert_called_once_with("Test Show")


def test_movie_details_dialog_refresh(mock_opt_controller, qtbot):
    dialog = MovieDetailsDialog(
        "Test Movie", "/media/movies/Test Movie.mkv", mock_opt_controller
    )
    qtbot.addWidget(dialog)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        with patch.object(
            mock_opt_controller, "trigger_series_refresh"
        ) as mock_refresh:
            dialog._on_refresh_clicked()
            mock_refresh.assert_called_once_with("Test Movie")


def test_series_details_dialog_manual_mapper_default_tv_order(
    mock_series_controller, qtbot
):
    # Setup metadata to not have a saved group, but have a TMDB identifier
    mock_series_controller.cached_library_data["Cosmos"]["metadata"][
        "tmdb_identifier"
    ] = "12345"
    mock_series_controller.cached_library_data["Cosmos"]["metadata"][
        "tmdb_episode_group_id"
    ] = None

    mock_seasons = [{"season_number": 1, "name": "Season 1"}]
    mock_episodes = [
        {
            "id": 999,
            "name": "Episode One Title",
            "episode_number": 1,
            "air_date": "1980-01-01",
            "runtime": 45,
        }
    ]

    with (
        patch(
            "lan_streamer.ui_views.dialogs.details.tmdb_client.get_episode_groups",
            return_value=[],
        ),
        patch(
            "lan_streamer.ui_views.dialogs.details.tmdb_client.get_seasons",
            return_value=mock_seasons,
        ),
        patch(
            "lan_streamer.ui_views.dialogs.details.tmdb_client.get_episodes",
            return_value=mock_episodes,
        ),
    ):
        dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
        qtbot.addWidget(dialog)

        # Check group combo contains "Default TV Order" and is selected by default
        assert dialog.group_combo.count() == 2  # Select Group..., Default TV Order
        assert dialog.group_combo.currentText() == "Default TV Order"
        assert dialog.group_combo.currentData() == "default"

        # Check subgroup combo contains Season 1
        assert dialog.subgroup_combo.count() == 2  # Select Subgroup..., Season 1
        dialog.subgroup_combo.setCurrentIndex(1)  # Select Season 1
        assert dialog.subgroup_combo.currentText() == "Season 1"

        # Check table contents
        assert dialog.mapper_table.rowCount() == 1
        assert dialog.mapper_table.item(0, 0).text() == "E01 - Episode One Title"
        assert dialog.mapper_table.item(0, 1).text() == "1980-01-01"

        combo = dialog.mapper_table.cellWidget(0, 2)
        assert combo.count() == 3  # Unmapped, S01E01, S01E02
        combo.setCurrentIndex(1)  # select S01E01.mkv

        with (
            patch(
                "PySide6.QtWidgets.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch("PySide6.QtWidgets.QMessageBox.information") as mock_info,
        ):
            dialog._on_apply_mappings_clicked()
            mock_info.assert_called_once()

        # Check mapped episode details saved
        ep = mock_series_controller.cached_library_data["Cosmos"]["seasons"][
            "Season 1"
        ]["episodes"][0]
        assert ep["tmdb_identifier"] == "999"
        assert ep["tmdb_episode_identifier"] == "999"
        assert ep["tmdb_name"] == "Episode One Title"
        assert ep["tmdb_number"] == 1
        assert ep["air_date"] == "1980-01-01"
        assert ep["runtime"] == 45


def test_series_details_dialog_manual_mapper_custom_group_order(
    mock_series_controller, qtbot
):
    # Setup identifier
    mock_series_controller.cached_library_data["Cosmos"]["metadata"][
        "tmdb_identifier"
    ] = "12345"

    mock_groups = [{"id": "dvd-group-99", "name": "DVD Order", "type": 3}]
    mock_group_details = {
        "id": "dvd-group-99",
        "name": "DVD Order",
        "groups": [
            {
                "name": "DVD Season 1",
                "episodes": [
                    {
                        "id": 9001,
                        "name": "DVD Ep One",
                        "order": 0,
                        "episode_number": 1,
                        "air_date": "1980-02-02",
                        "runtime": 50,
                    }
                ],
            }
        ],
    }

    with (
        patch(
            "lan_streamer.ui_views.dialogs.details.tmdb_client.get_episode_groups",
            return_value=mock_groups,
        ),
        patch(
            "lan_streamer.ui_views.dialogs.details.tmdb_client.get_episode_group_details",
            return_value=mock_group_details,
        ),
    ):
        dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
        qtbot.addWidget(dialog)

        # Combo should contain Select, Default TV Order, and DVD Order
        assert dialog.group_combo.count() == 3
        assert dialog.group_combo.itemText(2) == "DVD Order"

        # Select DVD Order
        dialog.group_combo.setCurrentIndex(2)

        # Subgroup combo should populate with "DVD Season 1"
        assert dialog.subgroup_combo.count() == 2
        assert dialog.subgroup_combo.itemText(1) == "DVD Season 1"

        dialog.subgroup_combo.setCurrentIndex(1)
        assert dialog.mapper_table.rowCount() == 1
        assert dialog.mapper_table.item(0, 0).text() == "E01 - DVD Ep One"

        # Map local file
        combo = dialog.mapper_table.cellWidget(0, 2)
        combo.setCurrentIndex(1)  # select S01E01.mkv

        with (
            patch(
                "PySide6.QtWidgets.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch("PySide6.QtWidgets.QMessageBox.information") as mock_info,
        ):
            dialog._on_apply_mappings_clicked()
            mock_info.assert_called_once()

        # Check mapped episode details saved
        ep = mock_series_controller.cached_library_data["Cosmos"]["seasons"][
            "Season 1"
        ]["episodes"][0]
        assert ep["tmdb_identifier"] == "9001"
        assert ep["tmdb_episode_identifier"] == "9001"
        assert ep["tmdb_name"] == "DVD Ep One"


def test_series_details_dialog_manual_mapper_unmapped_clearing(
    mock_series_controller, qtbot
):
    mock_series_controller.cached_library_data["Cosmos"]["metadata"][
        "tmdb_identifier"
    ] = "12345"

    # Pre-map S01E01 to TMDB ID 999
    ep = mock_series_controller.cached_library_data["Cosmos"]["seasons"]["Season 1"][
        "episodes"
    ][0]
    ep["tmdb_identifier"] = "999"
    ep["tmdb_episode_identifier"] = "999"

    mock_seasons = [{"season_number": 1, "name": "Season 1"}]
    mock_episodes = [
        {
            "id": 999,
            "name": "Episode One Title",
            "episode_number": 1,
            "air_date": "1980-01-01",
            "runtime": 45,
        }
    ]

    with (
        patch(
            "lan_streamer.ui_views.dialogs.details.tmdb_client.get_episode_groups",
            return_value=[],
        ),
        patch(
            "lan_streamer.ui_views.dialogs.details.tmdb_client.get_seasons",
            return_value=mock_seasons,
        ),
        patch(
            "lan_streamer.ui_views.dialogs.details.tmdb_client.get_episodes",
            return_value=mock_episodes,
        ),
    ):
        dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
        qtbot.addWidget(dialog)

        # Select Season 1
        dialog.subgroup_combo.setCurrentIndex(1)

        # S01E01.mkv is mapped by default (index 1)
        combo = dialog.mapper_table.cellWidget(0, 2)
        assert combo.currentIndex() == 1

        # Explicitly set combo box to "Unmapped / None" (index 0)
        combo.setCurrentIndex(0)

        with (
            patch(
                "PySide6.QtWidgets.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch("PySide6.QtWidgets.QMessageBox.information") as mock_info,
        ):
            dialog._on_apply_mappings_clicked()
            mock_info.assert_called_once()

        # Check mapped episode details cleared out
        ep = mock_series_controller.cached_library_data["Cosmos"]["seasons"][
            "Season 1"
        ]["episodes"][0]
        assert ep["tmdb_identifier"] == ""
        assert ep["tmdb_episode_identifier"] == ""
        assert ep["tmdb_name"] == ""
        assert ep["tmdb_number"] is None


def test_series_details_dialog_manual_mapper_missing_data_handling(
    mock_series_controller, qtbot
):
    mock_series_controller.cached_library_data["Cosmos"]["metadata"][
        "tmdb_identifier"
    ] = "12345"

    with (
        patch(
            "lan_streamer.ui_views.dialogs.details.tmdb_client.get_episode_groups",
            side_effect=Exception("API limit exceeded"),
        ),
        patch(
            "lan_streamer.ui_views.dialogs.details.tmdb_client.get_seasons",
            side_effect=Exception("JSON Decode Error"),
        ),
    ):
        # Initializing dialog should catch the get_episode_groups exception gracefully
        dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
        qtbot.addWidget(dialog)

        # Default TV Order is selected
        assert dialog.group_combo.currentText() == "Default TV Order"

        # Triggering group changed to default should handle the get_seasons exception gracefully
        dialog._on_group_changed()

        # No subgroups loaded due to exception
        assert dialog.subgroup_combo.count() == 1  # Select Subgroup...
