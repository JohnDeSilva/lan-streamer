import pytest
from unittest.mock import patch
from lan_streamer.ui_views import Controller
from lan_streamer.ui_views.dialogs.subtitle_search import SubtitleSearchDialog


@pytest.fixture
def mock_subtitle_controller():
    controller = Controller()
    controller.cached_library_data = {
        "Cosmos": {
            "metadata": {
                "tmdb_name": "Cosmos",
                "tmdb_id": "12345",
            }
        }
    }
    controller.current_library_name = "TV"
    return controller


def test_subtitle_search_dialog_init_tv(mock_subtitle_controller, qtbot):
    media_record = {
        "path": "/media/tv/Cosmos/Season 1/S01E01.mkv",
        "season_number": 1,
        "tmdb_number": 2,
    }

    dialog = SubtitleSearchDialog(
        "Cosmos", media_record, mock_subtitle_controller, is_movie=False
    )
    qtbot.addWidget(dialog)

    # Verify default query construction for TV show episode: "Cosmos S01E02"
    assert dialog.query_edit.text() == "Cosmos S01E02"
    assert dialog.lang_edit.text() == "en"
    assert dialog.download_btn.isEnabled() is False


def test_subtitle_search_dialog_init_movie(mock_subtitle_controller, qtbot):
    media_record = {
        "path": "/media/movies/Interstellar.mkv",
        "tmdb_name": "Interstellar",
        "year": "2014",
        "tmdb_id": "54321",
    }

    dialog = SubtitleSearchDialog(
        "Interstellar", media_record, mock_subtitle_controller, is_movie=True
    )
    qtbot.addWidget(dialog)

    # Verify default query construction for Movie: "Interstellar 2014"
    assert dialog.query_edit.text() == "Interstellar 2014"
    assert dialog.lang_edit.text() == "en"
    assert dialog.download_btn.isEnabled() is False


def test_subtitle_search_dialog_movie_search(mock_subtitle_controller, qtbot):
    media_record = {
        "path": "/media/movies/Interstellar.mkv",
        "tmdb_name": "Interstellar",
        "year": "2014",
        "tmdb_id": "54321",
    }

    with patch(
        "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.search_subtitles",
        return_value=[],
    ) as mock_search:
        dialog = SubtitleSearchDialog(
            "Interstellar", media_record, mock_subtitle_controller, is_movie=True
        )
        qtbot.addWidget(dialog)

        with patch(
            "lan_streamer.ui_views.dialogs.subtitle_search.QMessageBox.information"
        ) as mock_info:
            dialog._on_search_clicked()
            mock_info.assert_called_once()
            mock_search.assert_called_once_with(
                query=None,
                tmdb_id=54321,
                season_number=None,
                episode_number=None,
                languages="en",
            )


def test_subtitle_search_dialog_search_results_and_download(
    mock_subtitle_controller, tmp_path, qtbot
):
    # Setup temporary file path next to which subtitle will be saved
    video_path = tmp_path / "test_video.mkv"
    video_path.write_bytes(b"dummy video data")

    media_record = {
        "path": str(video_path),
        "season_number": 1,
        "tmdb_number": 1,
    }

    mock_subtitles = [
        {
            "attributes": {
                "language": "en",
                "release": "Cosmos.S01E01.1080p.WebRip.x264",
                "ratings": 4.5,
                "download_count": 120,
                "files": [{"file_id": 98765}],
            }
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.search_subtitles",
        return_value=mock_subtitles,
    ) as mock_search:
        dialog = SubtitleSearchDialog(
            "Cosmos", media_record, mock_subtitle_controller, is_movie=False
        )
        qtbot.addWidget(dialog)

        # Trigger search
        dialog._on_search_clicked()
        mock_search.assert_called_once_with(
            query=None,
            tmdb_id=12345,
            season_number=1,
            episode_number=1,
            languages="en",
        )

        # Verify results table population
        assert dialog.results_table.rowCount() == 1
        assert dialog.results_table.item(0, 0).text() == "en"
        assert (
            dialog.results_table.item(0, 1).text() == "Cosmos.S01E01.1080p.WebRip.x264"
        )
        assert dialog.results_table.item(0, 2).text() == "4.5"
        assert dialog.results_table.item(0, 3).text() == "120"

        # Select row, which should enable the download button
        dialog.results_table.selectRow(0)
        assert dialog.download_btn.isEnabled() is True

        with (
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.get_download_link",
                return_value="http://example.com/sub.srt",
            ) as mock_get_link,
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.download_subtitle",
                return_value=b"subtitle file contents",
            ) as mock_download,
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.QMessageBox.information"
            ) as mock_info,
        ):
            dialog._on_download_clicked()

            mock_get_link.assert_called_once_with(98765)
            mock_download.assert_called_once_with("http://example.com/sub.srt")
            mock_info.assert_called_once()

            # Subtitle file should be saved next to the video path
            sub_path = tmp_path / "test_video.en.srt"
            assert sub_path.exists()
            assert sub_path.read_bytes() == b"subtitle file contents"


def test_subtitle_search_dialog_search_no_results(mock_subtitle_controller, qtbot):
    media_record = {
        "path": "/media/tv/Cosmos/Season 1/S01E01.mkv",
        "season_number": 1,
        "tmdb_number": 1,
    }

    with (
        patch(
            "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.search_subtitles",
            return_value=[],
        ),
        patch(
            "lan_streamer.ui_views.dialogs.subtitle_search.QMessageBox.information"
        ) as mock_info,
    ):
        dialog = SubtitleSearchDialog(
            "Cosmos", media_record, mock_subtitle_controller, is_movie=False
        )
        qtbot.addWidget(dialog)

        dialog._on_search_clicked()
        mock_info.assert_called_once()


def test_subtitle_search_dialog_download_edge_cases(
    mock_subtitle_controller, tmp_path, qtbot
):
    video_path = tmp_path / "test_video.mkv"
    video_path.write_bytes(b"dummy video data")

    media_record = {
        "path": str(video_path),
        "season_number": 1,
        "tmdb_number": 1,
    }

    mock_subtitles = [
        # 1. Valid subtitle structure but with no file_id
        {
            "attributes": {
                "language": "en",
                "release": "Release 1",
                "ratings": 4.0,
                "download_count": 50,
                "files": [{}],
            }
        },
        # 2. Subtitle with file_id for other tests
        {
            "attributes": {
                "language": "en",
                "release": "Release 2",
                "ratings": 4.5,
                "download_count": 100,
                "files": [{"file_id": 123}],
            }
        },
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.search_subtitles",
        return_value=mock_subtitles,
    ):
        dialog = SubtitleSearchDialog(
            "Cosmos", media_record, mock_subtitle_controller, is_movie=False
        )
        qtbot.addWidget(dialog)
        dialog._on_search_clicked()

        # A. Click download with no selection (selected row out of range)
        dialog._on_download_clicked()  # should return early without warnings because row is -1

        # B. Select row 0 (no file_id) -> warning dialog
        dialog.results_table.selectRow(0)
        with patch(
            "lan_streamer.ui_views.dialogs.subtitle_search.QMessageBox.warning"
        ) as mock_warning:
            dialog._on_download_clicked()
            mock_warning.assert_called_once_with(
                dialog, "Download", "No file ID found for this subtitle."
            )

        # C. Select row 1 (has file_id, but get_download_link returns None)
        dialog.results_table.selectRow(1)
        with (
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.get_download_link",
                return_value=None,
            ),
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.QMessageBox.warning"
            ) as mock_warning,
        ):
            dialog._on_download_clicked()
            mock_warning.assert_called_once_with(
                dialog,
                "Download",
                "Could not get download link. Check your credentials in Settings.",
            )

        # D. Select row 1 (has download link, but download_subtitle returns None)
        with (
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.get_download_link",
                return_value="http://example.com/sub.srt",
            ),
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.download_subtitle",
                return_value=None,
            ),
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.QMessageBox.warning"
            ) as mock_warning,
        ):
            dialog._on_download_clicked()
            mock_warning.assert_called_once_with(
                dialog, "Download", "Failed to download subtitle content."
            )

        # E. Select row 1 (has download content, but video file does not exist)
        non_existent_record = {
            "path": "/non/existent/path.mkv",
            "season_number": 1,
            "tmdb_number": 1,
        }
        dialog_no_file = SubtitleSearchDialog(
            "Cosmos", non_existent_record, mock_subtitle_controller, is_movie=False
        )
        qtbot.addWidget(dialog_no_file)
        dialog_no_file.results = mock_subtitles
        dialog_no_file.results_table.setRowCount(2)
        dialog_no_file.results_table.selectRow(1)

        with (
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.get_download_link",
                return_value="http://example.com/sub.srt",
            ),
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.download_subtitle",
                return_value=b"srt contents",
            ),
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.QMessageBox.warning"
            ) as mock_warning,
        ):
            dialog_no_file._on_download_clicked()
            mock_warning.assert_called_once_with(
                dialog_no_file, "Download", "Video file not found on disk."
            )

        # F. Select row 1 (writing fails and raises Exception)
        with (
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.get_download_link",
                return_value="http://example.com/sub.srt",
            ),
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.opensubtitles_client.download_subtitle",
                return_value=b"srt contents",
            ),
            patch("builtins.open", side_effect=PermissionError("Permission denied")),
            patch(
                "lan_streamer.ui_views.dialogs.subtitle_search.QMessageBox.critical"
            ) as mock_critical,
        ):
            dialog._on_download_clicked()
            mock_critical.assert_called_once()
            args = mock_critical.call_args[0]
            assert "Error saving subtitle" in args[2]
