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


def test_episode_details_remove_episode_yes(mock_episode_controller, qtbot):
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

        with patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            with patch.object(mock_episode_controller, "delete_episode") as mock_delete:
                dialog._on_remove_episode_clicked()
                mock_delete.assert_called_once_with("/media/Test Series/S01E01.mkv")


def test_episode_details_remove_episode_no(mock_episode_controller, qtbot):
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

        with patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            with patch.object(mock_episode_controller, "delete_episode") as mock_delete:
                dialog._on_remove_episode_clicked()
                mock_delete.assert_not_called()


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


def test_movie_details_multiple_versions(mock_movie_controller, qtbot):
    # Setup controller with multiple versions
    mock_movie_controller.cached_library_data["Test Movie"]["versions"] = [
        {
            "path": "/media/Movies/Test Movie 1080p.mkv",
            "video_codec": "h264",
            "resolution": "1920x1080",
            "bit_rate": 5000000,
            "audio_tracks": [
                {"index": 1, "codec": "ac3", "language": "en", "title": ""}
            ],
            "subtitle_tracks": [],
        },
        {
            "path": "/media/Movies/Test Movie 2160p.mkv",
            "video_codec": "hevc",
            "resolution": "3840x2160",
            "bit_rate": 15000000,
            "audio_tracks": [
                {"index": 1, "codec": "truehd", "language": "en", "title": ""}
            ],
            "subtitle_tracks": [],
        },
    ]
    mock_movie_controller.cached_library_data["Test Movie"]["default_path"] = (
        "/media/Movies/Test Movie 1080p.mkv"
    )

    with patch("lan_streamer.scanner.get_detailed_file_info"):
        dialog = MovieDetailsDialog(
            "Test Movie", "/media/Movies/Test Movie 1080p.mkv", mock_movie_controller
        )
        qtbot.addWidget(dialog)

        # Check default selection
        assert dialog.default_file_combo.count() == 2
        assert (
            dialog.default_file_combo.currentData()
            == "/media/Movies/Test Movie 1080p.mkv"
        )
        assert dialog.resolution_label.text() == "1920x1080"
        assert dialog.codec_label.text() == "h264"

        # Switch version in UI
        dialog.default_file_combo.setCurrentIndex(1)
        assert (
            dialog.default_file_combo.currentData()
            == "/media/Movies/Test Movie 2160p.mkv"
        )
        assert dialog.resolution_label.text() == "3840x2160"
        assert dialog.codec_label.text() == "hevc"

        # Save and verify persistence of new version details
        with patch("lan_streamer.db.save_library") as mock_save:
            dialog._on_save_clicked()
            mock_save.assert_called_once()

            movie = mock_movie_controller.cached_library_data["Test Movie"]
            assert movie["default_path"] == "/media/Movies/Test Movie 2160p.mkv"
            assert movie["path"] == "/media/Movies/Test Movie 2160p.mkv"
            assert movie["video_codec"] == "hevc"
            assert movie["resolution"] == "3840x2160"


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


def test_series_details_dialog_save_checkbox_persistence(mock_series_controller, qtbot):
    mock_series_controller.cached_library_data["Cosmos"]["metadata"][
        "tmdb_identifier"
    ] = "12345"

    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)

    assert dialog.locked_checkbox.isChecked() is False
    assert dialog.hide_missing_checkbox.isChecked() is False

    dialog.locked_checkbox.setChecked(True)
    dialog.hide_missing_checkbox.setChecked(True)

    with (
        patch.object(mock_series_controller, "toggle_series_lock") as mock_lock,
        patch("lan_streamer.db.save_library"),
    ):
        dialog._on_save_clicked()
        mock_lock.assert_called_once_with("Cosmos", True)


def test_series_details_dialog_save_lock_metadata(mock_series_controller, qtbot):
    mock_series_controller.cached_library_data["Cosmos"]["metadata"][
        "tmdb_identifier"
    ] = "12345"

    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)

    assert dialog.name_edit.text() == "Cosmos"
    dialog.locked_checkbox.setChecked(True)

    with (
        patch.object(mock_series_controller, "toggle_series_lock") as mock_lock,
        patch("lan_streamer.db.save_library"),
    ):
        dialog._on_save_clicked()
        mock_lock.assert_called_once()


def test_series_details_dialog_match_and_refresh(mock_series_controller, qtbot):
    mock_series_controller.cached_library_data["Cosmos"]["metadata"][
        "tmdb_identifier"
    ] = "12345"

    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(
        mock_series_controller.metadata_dialog_requested, timeout=1000
    ):
        dialog._on_match_meta_clicked()


def test_series_details_dialog_name_and_save(mock_series_controller, qtbot):
    mock_series_controller.cached_library_data["Cosmos"]["metadata"][
        "tmdb_identifier"
    ] = "12345"

    dialog = SeriesDetailsDialog("Cosmos", mock_series_controller)
    qtbot.addWidget(dialog)

    assert dialog.name_edit.text() == "Cosmos"
    dialog.name_edit.setText("Cosmos (1980)")

    with patch.object(mock_series_controller, "update_series_name") as mock_update:
        dialog._on_save_clicked()
        mock_update.assert_called_once_with("Cosmos", "Cosmos (1980)")


def test_manual_mapping_remapping_and_unmapping_db(mock_series_controller):
    from lan_streamer.db.library import save_library, load_library
    from lan_streamer.db import get_session
    from lan_streamer.db.models import Episode

    # 1. Setup initial library state in memory
    library_data = {
        "Cosmos": {
            "metadata": {
                "tmdb_name": "Cosmos",
                "tmdb_identifier": "12345",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": "/media/tv/Cosmos/S01E01.mkv",
                            "name": "S01E01 - Episode 1",
                            "tmdb_number": 1,
                            "tmdb_episode_identifier": "101",
                            "tmdb_identifier": "101",
                            "air_date": "1980-01-01",
                            "runtime": 45,
                        },
                        {
                            "path": "/media/tv/Cosmos/S01E02.mkv",
                            "name": "S01E02 - Episode 2",
                            "tmdb_number": 2,
                            "tmdb_episode_identifier": "102",
                            "tmdb_identifier": "102",
                            "air_date": "1980-01-08",
                            "runtime": 45,
                        },
                    ]
                }
            },
        }
    }

    # Save initial state to the database
    save_library("TV", library_data)

    # Verify initial database state
    with get_session() as session:
        episodes = session.query(Episode).all()
        assert len(episodes) == 2
        ep1 = [e for e in episodes if e.tmdb_number == 1][0]
        ep2 = [e for e in episodes if e.tmdb_number == 2][0]
        assert ep1.default_path == "/media/tv/Cosmos/S01E01.mkv"
        assert ep2.default_path == "/media/tv/Cosmos/S01E02.mkv"
        assert len(ep1.media_files) == 1
        assert ep1.media_files[0].path == "/media/tv/Cosmos/S01E01.mkv"

    # 2. Simulate Remapping: Map S01E01.mkv to Episode 2, and S01E02.mkv to Unmapped
    # This leaves Episode 1 completely unmapped.
    updated_library_data = {
        "Cosmos": {
            "metadata": {
                "tmdb_name": "Cosmos",
                "tmdb_identifier": "12345",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            # S01E01.mkv now remapped to Episode 2 (tmdb_number=2, identifier="102")
                            "path": "/media/tv/Cosmos/S01E01.mkv",
                            "name": "S01E01 - Episode 1",
                            "tmdb_number": 2,
                            "tmdb_episode_identifier": "102",
                            "tmdb_identifier": "102",
                            "air_date": "1980-01-08",
                            "runtime": 45,
                        },
                        {
                            # S01E02.mkv now unmapped (tmdb_number=None, identifier="")
                            "path": "/media/tv/Cosmos/S01E02.mkv",
                            "name": "S01E02 - Episode 2",
                            "tmdb_number": None,
                            "tmdb_episode_identifier": "",
                            "tmdb_identifier": "",
                            "air_date": "",
                            "runtime": 0,
                        },
                    ]
                }
            },
        }
    }

    # Save the updated state (which simulates applying manual mapping changes)
    save_library("TV", updated_library_data)

    # Verify updated database state
    with get_session() as session:
        episodes = session.query(Episode).all()

        ep_num_1 = [e for e in episodes if e.tmdb_number == 1]
        assert (
            len(ep_num_1) == 0
        )  # Episode 1 is deleted as stale placeholder because it has no path

        ep_num_2 = [e for e in episodes if e.tmdb_number == 2]
        assert len(ep_num_2) == 1
        assert ep_num_2[0].default_path == "/media/tv/Cosmos/S01E01.mkv"
        assert len(ep_num_2[0].media_files) == 1
        assert ep_num_2[0].media_files[0].path == "/media/tv/Cosmos/S01E01.mkv"

        ep_unmapped = [e for e in episodes if e.tmdb_number is None]
        assert len(ep_unmapped) == 1
        assert ep_unmapped[0].default_path == "/media/tv/Cosmos/S01E02.mkv"
        assert len(ep_unmapped[0].media_files) == 1
        assert ep_unmapped[0].media_files[0].path == "/media/tv/Cosmos/S01E02.mkv"

    # Also verify by loading library from the DB
    loaded = load_library("TV")
    cosmos_eps = loaded["Cosmos"]["seasons"]["Season 1"]["episodes"]
    # Check that S01E01.mkv is mapped to tmdb_number=2
    ep_s01e01 = [e for e in cosmos_eps if e["path"] == "/media/tv/Cosmos/S01E01.mkv"][0]
    assert ep_s01e01["tmdb_number"] == 2
    assert ep_s01e01["tmdb_episode_identifier"] == "102"

    # Check that S01E02.mkv is unmapped (tmdb_number=None)
    ep_s01e02 = [e for e in cosmos_eps if e["path"] == "/media/tv/Cosmos/S01E02.mkv"][0]
    assert ep_s01e02["tmdb_number"] is None
    assert ep_s01e02["tmdb_episode_identifier"] in (None, "")
