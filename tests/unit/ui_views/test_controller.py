import pytest
from unittest.mock import patch, MagicMock, ANY
from typing import Any, Dict, List

from lan_streamer.ui_views import Controller
from lan_streamer.backend import MetadataApplyWorker as MetadataApplyWorker_real


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
def mock_controller(mock_db_save):
    mock_config = MagicMock()
    mock_config.libraries = {"test_lib": {"type": "tv", "paths": ["/media/tv"]}}
    mock_config.sort_mode = "Alphabetical"
    mock_config.sort_descending = False
    mock_config.filter_out_watched = False
    from lan_streamer import db as _real_db

    controller = Controller(
        config=mock_config,
        db=_real_db,
        jellyfin_client=MagicMock(),
        tmdb_client=MagicMock(),
    )
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


def test_controller_metrics_caching(sample_library_dictionary: Dict[str, Any]) -> None:
    controller_instance = Controller(
        config=MagicMock(),
        db=MagicMock(),
        jellyfin_client=MagicMock(),
        tmdb_client=MagicMock(),
    )
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
    mock_config = MagicMock()
    mock_config.sort_mode = "Alphabetical"
    mock_config.sort_descending = False
    mock_config.filter_out_watched = False
    controller_instance = Controller(
        config=mock_config,
        db=MagicMock(),
        jellyfin_client=MagicMock(),
        tmdb_client=MagicMock(),
    )
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
    assert mock_config.sort_mode == target_mode
    assert len(loaded_signals_emitted) == 1

    initial_filter: bool = controller_instance.filter_out_watched
    controller_instance.set_filter_out_watched(not initial_filter)
    assert controller_instance.filter_out_watched is not initial_filter
    assert mock_config.filter_out_watched is not initial_filter
    assert len(loaded_signals_emitted) == 2


def test_controller_triggers() -> None:
    mock_config = MagicMock()
    mock_config.libraries = {"Test Lib": {"type": "tv", "paths": ["/path/to/media"]}}
    controller_instance = Controller(
        config=mock_config,
        db=MagicMock(),
        jellyfin_client=MagicMock(),
        tmdb_client=MagicMock(),
    )
    controller_instance.current_library_name = "Test Lib"

    with patch("lan_streamer.ui_views.controller.AsyncScanWorker") as mock_scan:
        controller_instance.trigger_scan(force_refresh=True)
        mock_scan.assert_called_once()
        mock_scan.return_value.start.assert_called_once()


def test_controller_jellyfin_sync_triggers() -> None:
    mock_jellyfin = MagicMock()
    mock_jellyfin.is_configured.return_value = True
    controller_instance = Controller(
        config=MagicMock(),
        db=MagicMock(),
        jellyfin_client=mock_jellyfin,
        tmdb_client=MagicMock(),
    )
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
    controller_instance.worker_manager.scan._instance = mock_scan_worker

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
    controller_instance.worker_manager.scan_all._instance = mock_scan_all_worker

    status_emitted: List[str] = []
    controller_instance.status_changed.connect(status_emitted.append)

    with patch.object(controller_instance, "select_library"):
        controller_instance._on_scan_all_finished()

    assert status_emitted == [
        "root directory /unavailable/all/1 is unavailable check connection to /unavailable/all/1",
    ]


def test_controller_scan_all_uses_changed_libraries() -> None:
    """_on_scan_all_finished passes changed_libraries to rebuild_for_libraries."""
    controller_instance = Controller()
    controller_instance.current_library_name = "Cosmos"

    mock_scan_all_worker = MagicMock()
    mock_scan_all_worker.unavailable_directories = []
    mock_scan_all_worker.changed_libraries = {"Cosmos", "TV Shows"}
    controller_instance.worker_manager.scan_all._instance = mock_scan_all_worker

    controller_instance._config.libraries = {
        "Movies": {},
        "Cosmos": {},
        "TV Shows": {},
        "Anime": {},
    }

    with (
        patch.object(controller_instance, "select_library"),
        patch.object(
            controller_instance._smart_row_service,
            "rebuild_for_libraries",
            return_value=[],
        ) as mock_rebuild,
    ):
        controller_instance._on_scan_all_finished()

    # Only changed libraries should be passed, not all 4 config libraries
    mock_rebuild.assert_called_once()
    rebuild_arg = mock_rebuild.call_args[0][0]
    assert set(rebuild_arg) == {"Cosmos", "TV Shows"}


def test_controller_scan_all_fallback_to_all_when_no_changed_libraries() -> None:
    """When changed_libraries is empty, _on_scan_all_finished falls back to all config libraries."""
    controller_instance = Controller()
    controller_instance.current_library_name = "Cosmos"

    mock_scan_all_worker = MagicMock()
    mock_scan_all_worker.unavailable_directories = []
    mock_scan_all_worker.changed_libraries = set()
    controller_instance.worker_manager.scan_all._instance = mock_scan_all_worker

    controller_instance._config.libraries = {
        "Movies": {},
        "Cosmos": {},
        "TV Shows": {},
        "Anime": {},
    }

    with (
        patch.object(controller_instance, "select_library"),
        patch.object(
            controller_instance._smart_row_service,
            "rebuild_for_libraries",
            return_value=[],
        ) as mock_rebuild,
    ):
        controller_instance._on_scan_all_finished()

    mock_rebuild.assert_called_once()
    rebuild_arg = mock_rebuild.call_args[0][0]
    assert set(rebuild_arg) == {"Movies", "Cosmos", "TV Shows", "Anime"}


def test_controller_scan_all_fallback_to_all_when_worker_missing_attr() -> None:
    """When worker lacks changed_libraries attr (old worker), fall back to all config libraries."""
    controller_instance = Controller()
    controller_instance.current_library_name = "Cosmos"

    # Worker without changed_libraries attribute (simulates old worker code)
    class MockWorkerWithoutChangedLibraries:
        unavailable_directories = []

    mock_scan_all_worker = MockWorkerWithoutChangedLibraries()
    controller_instance.worker_manager.scan_all._instance = mock_scan_all_worker  # type: ignore[assignment]

    controller_instance._config.libraries = {
        "Movies": {},
        "Cosmos": {},
    }

    with (
        patch.object(controller_instance, "select_library"),
        patch.object(
            controller_instance._smart_row_service,
            "rebuild_for_libraries",
            return_value=[],
        ) as mock_rebuild,
    ):
        controller_instance._on_scan_all_finished()

    mock_rebuild.assert_called_once()
    rebuild_arg = mock_rebuild.call_args[0][0]
    assert set(rebuild_arg) == {"Movies", "Cosmos"}


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
    mock_config = MagicMock()
    mock_config.libraries = {}
    controller_instance = Controller(
        config=mock_config,
        db=MagicMock(),
        jellyfin_client=MagicMock(),
        tmdb_client=MagicMock(),
    )
    media_directory = tmp_path / "cinematic_roots"
    media_directory.mkdir()
    directory_path_string = str(media_directory)

    mock_config.libraries["ActiveMonitoredLib"] = {
        "type": "tv",
        "paths": [directory_path_string],
    }

    with patch("lan_streamer.db.load_library", return_value=sample_library_dictionary):
        controller_instance.select_library("ActiveMonitoredLib")
        assert (
            directory_path_string
            in controller_instance.file_system_watcher.directories()
        )

        # Test concurrency protection
        mock_scan = MagicMock()
        mock_scan._is_async_worker = True
        controller_instance.worker_manager.scan._instance = mock_scan
        controller_instance.current_library_name = "ActiveMonitoredLib"

        with patch(
            "lan_streamer.ui_views.controller.AsyncScanWorker"
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
        mock_scan_all.assert_called_once_with(
            async_task_manager=ANY,
            force_refresh=True,
            run_pass1=True,
            run_pass2=True,
        )
        mock_scan_all.return_value.start.assert_called_once()

        # Test concurrency protection
        mock_worker = MagicMock()
        mock_worker._is_async_worker = True
        controller_instance.worker_manager.scan_all._instance = mock_worker
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
    mock_controller._config.libraries["test_lib"]["type"] = "movie"
    mock_controller.toggle_series_lock("Test Movie", True)
    assert mock_controller.cached_library_data["Test Movie"]["locked_metadata"] is True
    mock_movie_save.assert_called_once()


def test_controller_trigger_series_refresh(mock_controller):
    with patch("lan_streamer.backend.RefreshSeriesWorker") as mock_worker_class:
        mock_controller.trigger_series_refresh("Test Show")
        mock_worker_class.return_value.start.assert_called_once()


def test_controller_refresh_episode_metadata(mock_controller, mock_db_save):
    mock_save, _ = mock_db_save

    mock_tmdb = mock_controller._tmdb_client
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

    mock_tmdb = mock_controller._tmdb_client
    mock_tmdb.get_season_based_episode_group.return_value = mock_group_details

    with patch.object(MetadataApplyWorker_real, "start", lambda self: self.run()):
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


# ------------------------------------------------------------------
# Constructor fallback tests
# ------------------------------------------------------------------


def test_controller_fallback_to_default_clients() -> None:
    """When dependencies are None, Controller falls back to default globals."""
    c = Controller(tmdb_client=None, jellyfin_client=None, config=None, db=None)
    assert c._tmdb_client is not None
    assert c._jellyfin_client is not None
    assert c._config is not None
    assert c._db is not None
    assert callable(getattr(c._tmdb_client, "get_episodes", None))
    assert callable(getattr(c._jellyfin_client, "is_configured", None))


def test_controller_scan_and_update_flow_isolation(mock_controller) -> None:
    """Verify that scan_and_update chain passes flow-local data through callbacks."""
    mock_controller.trigger_runtime_extraction = MagicMock()
    mock_controller._running_pass3_after_scan = True

    seasons = {"season1"}
    movies = {"movie1"}
    mock_controller._on_scan_and_update_cleanup_finished({}, seasons, movies)

    mock_controller.trigger_runtime_extraction.assert_called_once_with(seasons, movies)


class TestControllerSearchMedia:
    """Tests for Controller.search_media."""

    def test_search_media_delegates_to_db(self, mock_controller) -> None:
        """search_media should delegate to db.search_media_names."""
        controller = mock_controller
        controller._db.search_media_names = MagicMock(
            return_value=[{"name": "Result", "type": "series"}]
        )

        result = controller.search_media("Test Query", ["MyLib"])

        controller._db.search_media_names.assert_called_once_with(
            "Test Query", ["MyLib"]
        )
        assert result == [{"name": "Result", "type": "series"}]

    def test_search_media_returns_empty_on_db_error(self, mock_controller) -> None:
        """search_media should return [] when the db call raises."""
        controller = mock_controller
        controller._db.search_media_names = MagicMock(
            side_effect=Exception("DB connection lost")
        )

        result = controller.search_media("Bad Query")

        assert result == []

    def test_search_media_calls_with_none_libraries(self, mock_controller) -> None:
        """search_media should pass library_names=None when searching all."""
        controller = mock_controller
        controller._db.search_media_names = MagicMock(return_value=[])

        controller.search_media("Any")

        controller._db.search_media_names.assert_called_once_with("Any", None)
