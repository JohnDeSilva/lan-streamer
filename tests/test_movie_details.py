import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QMessageBox
from lan_streamer.ui_views import Controller, MovieDetailsDialog


@pytest.fixture
def mock_controller():
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


def test_movie_details_dialog_loading(mock_controller, qtbot):
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
            "Test Movie", "/media/Movies/Test Movie.mkv", mock_controller
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
        assert dialog.codec_label.text() == "Unknown"  # Or update mock
        assert dialog.audio_list.count() == 1


def test_movie_details_save_metadata(mock_controller, qtbot):
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
            "Test Movie", "/media/Movies/Test Movie.mkv", mock_controller
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

            movie = mock_controller.cached_library_data["Test Movie"]
            assert movie["tmdb_name"] == "New Movie Title"
            assert movie["runtime"] == 130
            assert movie["year"] == 2023
            assert movie["locked_metadata"] is True


def test_movie_details_embed_metadata_trigger(mock_controller, qtbot):
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
            "Test Movie", "/media/Movies/Test Movie.mkv", mock_controller
        )
        qtbot.addWidget(dialog)

        with patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            with patch.object(mock_controller, "embed_metadata") as mock_embed:
                dialog._on_embed_clicked()
                mock_embed.assert_called_once()
                args = mock_embed.call_args[0]
                assert args[0] == "/media/Movies/Test Movie.mkv"
                assert "title" in args[1]


def test_movie_details_merge_subtitles_trigger(mock_controller, qtbot):
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
            "Test Movie", "/media/Movies/Test Movie.mkv", mock_controller
        )
        qtbot.addWidget(dialog)

        dialog._ext_subs = ["/media/Movies/Test Movie.en.srt"]

        with patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            with patch.object(mock_controller, "merge_subtitles") as mock_merge:
                dialog._on_merge_clicked()
                mock_merge.assert_called_once_with(
                    "/media/Movies/Test Movie.mkv", ["/media/Movies/Test Movie.en.srt"]
                )
