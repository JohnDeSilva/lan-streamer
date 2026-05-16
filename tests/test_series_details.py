import pytest
from unittest.mock import patch, MagicMock
from PySide6.QtWidgets import QMessageBox, QLabel
from lan_streamer.ui_views import Controller, SeriesDetailsDialog


@pytest.fixture
def mock_controller():
    controller = Controller()
    controller.cached_library_data = {
        "Cosmos": {
            "metadata": {"tmdb_name": "Cosmos"},
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


def test_series_details_dialog_loading(mock_controller, qtbot):
    dialog = SeriesDetailsDialog("Cosmos", mock_controller)
    qtbot.addWidget(dialog)

    assert dialog.name_edit.text() == "Cosmos"
    labels = dialog.findChildren(QLabel)
    path_found = any("/media/tv" in label.text() for label in labels)
    assert path_found is True


def test_series_details_save_name(mock_controller, qtbot):
    dialog = SeriesDetailsDialog("Cosmos", mock_controller)
    qtbot.addWidget(dialog)

    dialog.name_edit.setText("Cosmos (1980)")
    with patch.object(mock_controller, "update_series_name") as mock_update:
        dialog._on_save_clicked()
        mock_update.assert_called_once_with("Cosmos", "Cosmos (1980)")


def test_series_details_match_buttons(mock_controller, qtbot):
    dialog = SeriesDetailsDialog("Cosmos", mock_controller)
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(mock_controller.metadata_dialog_requested, timeout=1000):
        dialog._on_match_meta_clicked()

    dialog = SeriesDetailsDialog("Cosmos", mock_controller)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(mock_controller.jellyfin_dialog_requested, timeout=1000):
        dialog._on_match_jellyfin_clicked()

    dialog = SeriesDetailsDialog("Cosmos", mock_controller)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(mock_controller.rename_dialog_requested, timeout=1000):
        dialog._on_rename_clicked()


def test_series_details_embed_bulk_trigger(mock_controller, qtbot):
    dialog = SeriesDetailsDialog("Cosmos", mock_controller)
    qtbot.addWidget(dialog)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        with patch.object(mock_controller, "embed_metadata_series") as mock_embed:
            dialog._on_embed_clicked()
            mock_embed.assert_called_once_with("Cosmos")


def test_series_details_mark_watched_trigger(mock_controller, qtbot):
    dialog = SeriesDetailsDialog("Cosmos", mock_controller)
    qtbot.addWidget(dialog)

    with patch.object(mock_controller, "mark_series_watched") as mock_mark:
        dialog._on_mark_watched_clicked()
        mock_mark.assert_called_once_with("Cosmos")


def test_series_metadata_embed_worker(mock_controller, qtbot):
    from lan_streamer.backend import SeriesMetadataEmbedWorker

    episodes = mock_controller.cached_library_data["Cosmos"]["seasons"]["Season 1"][
        "episodes"
    ]

    worker = SeriesMetadataEmbedWorker("Cosmos", episodes)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("os.replace"):
            worker.run()
            assert mock_run.call_count == 2


def test_controller_embed_metadata_series_trigger(mock_controller):
    with patch("lan_streamer.backend.SeriesMetadataEmbedWorker.start") as mock_start:
        mock_controller.embed_metadata_series("Cosmos")
        mock_start.assert_called_once()


def test_controller_update_series_name(mock_controller):
    with patch("lan_streamer.db.save_library") as mock_save:
        mock_controller.update_series_name("Cosmos", "New Cosmos")
        mock_save.assert_called_once()
        assert "New Cosmos" in mock_controller.cached_library_data
        assert "Cosmos" not in mock_controller.cached_library_data


def test_controller_update_movie_metadata(mock_controller):
    mock_controller.cached_library_data["Movie 1"] = {"path": "/m1"}
    with patch("lan_streamer.db.save_library") as mock_save:
        mock_controller.update_movie_metadata(
            "Movie 1", "/m1", {"tmdb_name": "New Movie"}
        )
        mock_save.assert_called_once()
        assert (
            mock_controller.cached_library_data["Movie 1"]["tmdb_name"] == "New Movie"
        )


def test_subtitle_merge_worker(mock_controller):
    from lan_streamer.backend import SubtitleMergeWorker

    worker = SubtitleMergeWorker(
        "/media/tv/Cosmos/S01E01.mkv", ["/media/tv/Cosmos/S01E01.en.srt"]
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("os.replace"):
            with patch("os.remove"):
                worker.run()
                assert mock_run.call_count == 1
