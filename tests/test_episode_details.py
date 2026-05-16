import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QMessageBox
from lan_streamer.ui_views import Controller, EpisodeDetailsDialog


@pytest.fixture
def mock_controller():
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


def test_episode_details_dialog_loading(mock_controller, qtbot):
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
            "Test Series", "/media/Test Series/S01E01.mkv", mock_controller
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


def test_episode_details_save_metadata(mock_controller, qtbot):
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
            "Test Series", "/media/Test Series/S01E01.mkv", mock_controller
        )
        qtbot.addWidget(dialog)

        dialog.title_edit.setText("New Title")
        dialog.runtime_edit.setText("50")
        dialog.locked_checkbox.setChecked(True)

        with patch("lan_streamer.db.save_library") as mock_save:
            dialog._on_save_clicked()
            mock_save.assert_called_once()

            ep = mock_controller.cached_library_data["Test Series"]["seasons"][
                "Season 1"
            ]["episodes"][0]
            assert ep["tmdb_name"] == "New Title"
            assert ep["runtime"] == 50
            assert ep["locked_metadata"] is True


def test_episode_details_merge_subtitles_trigger(mock_controller, qtbot):
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
            "Test Series", "/media/Test Series/S01E01.mkv", mock_controller
        )
        qtbot.addWidget(dialog)

        dialog._ext_subs = ["/media/Test Series/S01E01.en.srt"]

        with patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            with patch.object(mock_controller, "merge_subtitles") as mock_merge:
                dialog._on_merge_clicked()
                mock_merge.assert_called_once_with(
                    "/media/Test Series/S01E01.mkv",
                    ["/media/Test Series/S01E01.en.srt"],
                )
