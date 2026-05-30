import pytest
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox

from lan_streamer.scanner import scan_directories
from lan_streamer.backend import RefreshSeriesWorker
from lan_streamer.ui_views import (
    Controller,
    SeriesDetailsDialog,
    EpisodeDetailsDialog,
    MovieDetailsDialog,
)
from lan_streamer.system.config import config


@pytest.fixture
def mock_db_save():
    with (
        patch("lan_streamer.db.save_library") as mock_save,
        patch("lan_streamer.db.save_movie_library") as mock_movie_save,
    ):
        yield mock_save, mock_movie_save


@pytest.fixture
def mock_controller(mock_db_save):
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
    config.libraries = {"test_lib": {"type": "tv", "paths": ["/media/tv"]}}
    return controller


# 1. Scanner Respects locked_metadata and single_item_refresh
def test_scanner_respects_lock_metadata(tmp_path):
    series_dir = tmp_path / "Locked Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Locked Show": {
            "metadata": {
                "tmdb_identifier": "locked_id",
                "tmdb_name": "Locked Title",
                "locked_metadata": True,
            },
            "seasons": {},
        }
    }

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
        mock_tmdb.get_seasons.return_value = []
        res = scan_directories(
            [str(tmp_path)], existing_library=existing_library, force_refresh=True
        )

        assert res["Locked Show"]["metadata"]["tmdb_name"] == "Locked Title"
        mock_tmdb.search_series.assert_not_called()
        mock_tmdb.get_series_by_id.assert_not_called()


def test_scanner_skips_tmdb_during_global_scan(tmp_path):
    series_dir = tmp_path / "Existing Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Existing Show": {
            "metadata": {
                "tmdb_identifier": "existing_id",
                "tmdb_name": "Existing Title",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": str(season_dir / "S01E01.mkv"),
                        }
                    ]
                }
            },
        }
    }

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
        # Should bypass TMDB because there are no new files and single_item_refresh is False
        res = scan_directories(
            [str(tmp_path)],
            existing_library=existing_library,
            force_refresh=True,
            single_item_refresh=False,
        )

        assert res["Existing Show"]["metadata"]["tmdb_name"] == "Existing Title"
        mock_tmdb.search_series.assert_not_called()
        mock_tmdb.get_series_by_id.assert_not_called()


def test_scanner_queries_tmdb_when_single_item_refresh_true(tmp_path):
    series_dir = tmp_path / "Refresh Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Refresh Show": {
            "metadata": {
                "tmdb_identifier": "refresh_id",
                "tmdb_name": "Old Title",
                "locked_metadata": False,
            },
            "seasons": {},
        }
    }

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
        mock_tmdb.get_series_by_id.return_value = {
            "id": "refresh_id",
            "name": "Fresh Title",
            "overview": "Fresh overview",
        }
        mock_tmdb.get_seasons.return_value = []
        # Since single_item_refresh is True, it should force TMDB lookups
        res = scan_directories(
            [str(tmp_path)],
            existing_library=existing_library,
            force_refresh=True,
            single_item_refresh=True,
        )

        assert res["Refresh Show"]["metadata"]["tmdb_name"] == "Fresh Title"
        mock_tmdb.get_series_by_id.assert_called_once_with("refresh_id")


# 2. RefreshSeriesWorker tests
def test_refresh_series_worker_success(tmp_path, mock_db_save):
    mock_save, _ = mock_db_save
    series_dir = tmp_path / "Refresh Show"
    series_dir.mkdir()

    existing = {
        "Refresh Show": {"metadata": {"tmdb_identifier": "id_123"}, "seasons": {}}
    }

    worker = RefreshSeriesWorker(
        library_name="TV",
        item_name="Refresh Show",
        library_type="tv",
        root_directories=[str(tmp_path)],
        existing_library=existing,
    )

    with (
        patch("lan_streamer.backend.scan_series") as mock_scan,
        patch("lan_streamer.backend.clean_series_data", lambda x: x),
    ):
        mock_scan.return_value = {
            "metadata": {"tmdb_identifier": "id_123", "tmdb_name": "Fresh Show"},
            "seasons": {},
        }

        # Catch finished signal
        finished_data = None

        def on_finished(d):
            nonlocal finished_data
            finished_data = d

        worker.finished.connect(on_finished)
        worker.run()

        assert finished_data is not None
        assert finished_data["Refresh Show"]["metadata"]["tmdb_name"] == "Fresh Show"
        mock_save.assert_called_once()
        mock_scan.assert_called_once_with(
            series_dir,
            tmdb_series=None,
            jellyfin_data=None,
            manual_jellyfin_id=None,
            existing_series_data=existing["Refresh Show"],
            force_refresh=True,
            cleanup=False,
            single_item_refresh=True,
        )


def test_refresh_series_worker_not_found(tmp_path):
    worker = RefreshSeriesWorker(
        library_name="TV",
        item_name="Missing Show",
        library_type="tv",
        root_directories=[str(tmp_path)],
        existing_library={},
    )

    error_msg = None

    def on_error(msg):
        nonlocal error_msg
        error_msg = msg

    worker.error.connect(on_error)
    worker.run()
    assert error_msg is not None
    assert "Could not find directory" in error_msg


# 3. Controller lock and refresh methods
def test_controller_toggle_series_lock(mock_controller, mock_db_save):
    mock_save, mock_movie_save = mock_db_save

    # Test TV lock
    mock_controller.toggle_series_lock("Test Show", True)
    assert (
        mock_controller.cached_library_data["Test Show"]["metadata"]["locked_metadata"]
        is True
    )
    mock_save.assert_called_once()

    # Test TV unlock
    mock_controller.toggle_series_lock("Test Show", False)
    assert (
        mock_controller.cached_library_data["Test Show"]["metadata"]["locked_metadata"]
        is False
    )

    # Test Movie lock (type="movie")
    config.libraries["test_lib"]["type"] = "movie"
    mock_controller.toggle_series_lock("Test Movie", True)
    assert mock_controller.cached_library_data["Test Movie"]["locked_metadata"] is True
    mock_movie_save.assert_called_once()


def test_controller_trigger_series_refresh(mock_controller):
    with patch("lan_streamer.backend.RefreshSeriesWorker.start") as mock_start:
        mock_controller.trigger_series_refresh("Test Show")
        mock_start.assert_called_once()


def test_controller_refresh_episode_metadata(mock_controller, mock_db_save):
    mock_save, _ = mock_db_save

    with patch("lan_streamer.ui_views.tmdb_client") as mock_tmdb:
        mock_tmdb.get_episodes.return_value = [
            {
                "episode_number": 1,
                "name": "Fresh Episode Title",
                "overview": "Fresh Episode Overview",
                "air_date": "2020-01-01",
                "runtime": 45,
            }
        ]

        mock_controller.refresh_episode_metadata(
            "Test Show", "/media/tv/Test Show/Season 1/S01E01.mkv"
        )

        ep = mock_controller.cached_library_data["Test Show"]["seasons"]["Season 1"][
            "episodes"
        ][0]
        assert ep["name"] == "Fresh Episode Title"
        assert ep["overview"] == "Fresh Episode Overview"
        assert ep["runtime"] == 45
        mock_save.assert_called_once()


def test_series_details_dialog_lock(mock_controller, qtbot):
    dialog = SeriesDetailsDialog("Test Show", mock_controller)
    qtbot.addWidget(dialog)

    assert dialog.locked_checkbox.isChecked() is False
    dialog.locked_checkbox.setChecked(True)

    with patch.object(mock_controller, "toggle_series_lock") as mock_toggle:
        dialog._on_save_clicked()
        mock_toggle.assert_called_once_with("Test Show", True)


def test_episode_details_dialog_refresh(mock_controller, qtbot):
    dialog = EpisodeDetailsDialog(
        "Test Show", "/media/tv/Test Show/Season 1/S01E01.mkv", mock_controller
    )
    qtbot.addWidget(dialog)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        with patch.object(mock_controller, "refresh_episode_metadata") as mock_refresh:
            dialog._on_refresh_clicked()
            mock_refresh.assert_called_once_with(
                "Test Show", "/media/tv/Test Show/Season 1/S01E01.mkv"
            )


def test_series_details_dialog_refresh(mock_controller, qtbot):
    dialog = SeriesDetailsDialog("Test Show", mock_controller)
    qtbot.addWidget(dialog)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        with patch.object(mock_controller, "trigger_series_refresh") as mock_refresh:
            dialog._on_refresh_clicked()
            mock_refresh.assert_called_once_with("Test Show")


def test_movie_details_dialog_refresh(mock_controller, qtbot):
    dialog = MovieDetailsDialog(
        "Test Movie", "/media/movies/Test Movie.mkv", mock_controller
    )
    qtbot.addWidget(dialog)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        with patch.object(mock_controller, "trigger_series_refresh") as mock_refresh:
            dialog._on_refresh_clicked()
            mock_refresh.assert_called_once_with("Test Movie")
