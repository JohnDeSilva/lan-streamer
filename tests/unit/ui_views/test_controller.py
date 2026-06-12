import pytest
from unittest.mock import patch, MagicMock
from typing import Any, Dict, List

from lan_streamer.ui_views import Controller
from lan_streamer.system.config import config


@pytest.fixture
def sample_library_dictionary() -> Dict[str, Any]:
    return {
        "Cosmos": {
            "metadata": {
                "overview": "Space exploration documentary.",
                "poster_path": "/path/to/poster.jpg",
                "first_air_date": "1980-09-28",
                "tmdb_name": "Cosmos: A Personal Voyage",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "test_video.mkv",
                            "path": "/path/to/test_video.mkv",
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


def test_controller_triggers() -> None:
    controller_instance = Controller()
    controller_instance.current_library_name = "Test Lib"
    config.libraries["Test Lib"] = {"type": "tv", "paths": ["/path/to/media"]}

    with patch("lan_streamer.ui_views.controller.ScanWorker") as mock_scan:
        controller_instance.trigger_scan(force_refresh=True)
        mock_scan.assert_called_once()
        mock_scan.return_value.start.assert_called_once()

    with patch("lan_streamer.ui_views.controller.CleanupWorker") as mock_cleanup:
        controller_instance.trigger_cleanup()
        mock_cleanup.assert_called_once()
        mock_cleanup.return_value.start.assert_called_once()


def test_controller_jellyfin_sync_triggers() -> None:
    controller_instance = Controller()
    with patch(
        "lan_streamer.ui_views.controller.jellyfin_client.is_configured",
        return_value=True,
    ):
        with patch("lan_streamer.ui_views.controller.JellyfinPullWorker") as mock_pull:
            controller_instance.trigger_jellyfin_pull()
            mock_pull.assert_called_once()

        with patch("lan_streamer.ui_views.controller.JellyfinPushWorker") as mock_push:
            controller_instance.trigger_jellyfin_push()
            mock_push.assert_called_once()


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
        mock_select.assert_called_once_with("Cosmos", reset_selection=False)

    with patch("lan_streamer.ui_views.Controller.select_library") as mock_select:
        controller_instance._on_pull_finished(5)
        mock_select.assert_called_once_with("Cosmos", reset_selection=False)

    controller_instance._on_push_finished(10)
    controller_instance._on_worker_error("Test Worker Exception")


def test_controller_scan_unavailable_directories(
    sample_library_dictionary: Dict[str, Any],
) -> None:
    controller_instance = Controller()
    controller_instance.current_library_name = "Cosmos"
    controller_instance.selected_series_name = "Cosmos"
    controller_instance.cached_library_data = sample_library_dictionary

    # Mock ScanWorker
    mock_scan_worker = MagicMock()
    mock_scan_worker.unavailable_directories = [
        "/unavailable/path/1",
        "/unavailable/path/2",
    ]
    controller_instance.scan_worker_instance = mock_scan_worker

    status_emitted: List[str] = []
    controller_instance.status_changed.connect(status_emitted.append)

    with patch("lan_streamer.db.save_library"):
        controller_instance._on_scan_finished(sample_library_dictionary)

    assert status_emitted == [
        "root directory /unavailable/path/1 is unavailable check connection to /unavailable/path/1",
        "root directory /unavailable/path/2 is unavailable check connection to /unavailable/path/2",
    ]


def test_controller_scan_all_unavailable_directories() -> None:
    controller_instance = Controller()
    controller_instance.current_library_name = "Cosmos"

    mock_scan_all_worker = MagicMock()
    mock_scan_all_worker.unavailable_directories = ["/unavailable/all/1"]
    controller_instance.scan_all_worker_instance = mock_scan_all_worker

    status_emitted: List[str] = []
    controller_instance.status_changed.connect(status_emitted.append)

    with patch.object(controller_instance, "select_library"):
        controller_instance._on_scan_all_finished()

    assert status_emitted == [
        "root directory /unavailable/all/1 is unavailable check connection to /unavailable/all/1",
    ]


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
    sample_library_dictionary: Dict[str, Any], tmp_path: Any
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

        with patch(
            "lan_streamer.ui_views.controller.ScanWorker"
        ) as mock_worker_constructor:
            controller_instance.trigger_scan(force_refresh=False)
            mock_worker_constructor.assert_not_called()


def test_controller_global_triggers() -> None:
    controller_instance = Controller()
    controller_instance.current_library_name = "CosmosLib"

    with patch(
        "lan_streamer.ui_views.controller.ScanAllLibrariesWorker"
    ) as mock_scan_all:
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
        with (
            patch.object(controller_instance, "select_library") as mock_select,
            patch.object(
                controller_instance, "trigger_runtime_extraction"
            ) as mock_extract,
        ):
            controller_instance._on_scan_all_finished()
            mock_select.assert_called_once_with("CosmosLib", reset_selection=False)
            mock_extract.assert_called_once()


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
    with patch("lan_streamer.backend.RefreshSeriesWorker") as mock_worker_class:
        mock_controller.trigger_series_refresh("Test Show")
        mock_worker_class.return_value.start.assert_called_once()


def test_controller_refresh_episode_metadata(mock_controller, mock_db_save):
    mock_save, _ = mock_db_save

    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
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


def test_controller_embed_metadata_series_trigger(mock_controller):
    with patch("lan_streamer.backend.SeriesMetadataEmbedWorker") as mock_worker_class:
        mock_controller.embed_metadata_series("Test Show")
        mock_worker_class.return_value.start.assert_called_once()


def test_controller_update_series_name(mock_controller):
    mock_controller.cached_library_data["Cosmos"] = {
        "metadata": {"tmdb_name": "Cosmos"},
        "seasons": {},
    }
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


def test_controller_update_metadata_match_syncs_with_episode_groups(
    mock_controller, mock_db_save
) -> None:
    mock_save, _ = mock_db_save

    # Make the episode name/path parseable as S01E01
    ep = mock_controller.cached_library_data["Test Show"]["seasons"]["Season 1"][
        "episodes"
    ][0]
    ep["name"] = "S01E01.mkv"

    # Mock TV Episode Group details
    mock_group_details = {
        "id": "group-id-123",
        "name": "TVDB Seasons",
        "groups": [
            {
                "name": "Season 1",
                "order": 1,
                "episodes": [
                    {
                        "id": "ep-sync-999",
                        "name": "Synced Episode Name",
                        "order": 0,  # Group order is 0 (first ep)
                        "season_number": 1,
                        "episode_number": 10,  # Absolute number
                        "air_date": "2020-01-02",
                        "runtime": 50,
                    }
                ],
            }
        ],
    }

    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_season_based_episode_group.return_value = mock_group_details

        mock_controller.apply_metadata_match(
            "Test Show",
            {"id": "999", "name": "Matched Show Title", "first_air_date": "2020-01-01"},
        )

        mock_tmdb.get_season_based_episode_group.assert_called_once_with("999")
        mock_tmdb.get_episodes.assert_not_called()

        updated_ep = mock_controller.cached_library_data["Test Show"]["seasons"][
            "Season 1"
        ]["episodes"][0]
        assert updated_ep["tmdb_episode_identifier"] == "ep-sync-999"
        assert updated_ep["tmdb_name"] == "Synced Episode Name"
        assert updated_ep["runtime"] == 50
        assert updated_ep["tmdb_number"] == 1
        mock_save.assert_called_once()


def test_controller_delete_series(mock_controller) -> None:
    mock_controller.cached_library_data = {"DeleteShow": {}}
    mock_controller.current_library_name = "test_lib"

    with (
        patch("lan_streamer.db.delete_series_record") as mock_db_delete,
        patch.object(mock_controller, "select_library") as mock_select,
    ):
        mock_controller.delete_series("DeleteShow")
        mock_db_delete.assert_called_once_with("test_lib", "DeleteShow")
        mock_select.assert_called_once_with("test_lib", reset_selection=True)


def test_controller_delete_episode(mock_controller) -> None:
    mock_controller.current_library_name = "test_lib"

    with (
        patch("lan_streamer.db.delete_episode_record") as mock_db_delete,
        patch.object(mock_controller, "select_library") as mock_select,
    ):
        mock_controller.delete_episode("/path/to/ep.mkv")
        mock_db_delete.assert_called_once_with("/path/to/ep.mkv")
        mock_select.assert_called_once_with("test_lib", reset_selection=False)
