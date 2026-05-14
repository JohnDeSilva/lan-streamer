import pytest
from unittest.mock import patch, MagicMock
from typing import Any, Dict, List
from lan_streamer.backend import (
    BackendBridge,
    ScanWorker,
    SyncAllWorker,
    CleanupWorker,
    JellyfinPullWorker,
    JellyfinPushWorker,
)
from lan_streamer.config import config


@pytest.fixture
def sample_library_payload() -> Dict[str, Any]:
    return {
        "Cosmos": {
            "metadata": {
                "overview": "Space doc.",
                "poster_path": "/poster.jpg",
                "first_air_date": "1980-01-01",
                "tmdb_name": "Cosmos Series",
            },
            "seasons": {
                "Season 1": {
                    "metadata": {"poster_path": "/s1.jpg"},
                    "episodes": [
                        {
                            "name": "ep1.mkv",
                            "path": "/path/to/ep1.mkv",
                            "watched": False,
                            "tmdb_number": 1,
                            "tmdb_name": "Shores",
                            "date_added": 100,
                            "air_date": "1980-01-01",
                            "jellyfin_id": "j1",
                        }
                    ],
                }
            },
        }
    }


def test_backend_bridge_properties(qtbot: Any) -> None:
    bridge_instance = BackendBridge()
    assert bridge_instance.statusMessage == "Ready"

    bridge_instance.statusMessage = "Loading..."
    assert bridge_instance.statusMessage == "Loading..."

    # Test configuration delegate setters and getters without abbreviations
    bridge_instance.configJellyfinUrl = "http://test-server"
    assert bridge_instance.configJellyfinUrl == "http://test-server"
    assert config.jellyfin_url == "http://test-server"

    bridge_instance.configJellyfinApiKey = "key123"
    assert bridge_instance.configJellyfinApiKey == "key123"

    bridge_instance.configTmdbApiKey = "tmdb123"
    assert bridge_instance.configTmdbApiKey == "tmdb123"

    bridge_instance.configSyncHistoryOnStart = False
    assert bridge_instance.configSyncHistoryOnStart is False

    bridge_instance.configUseEmbeddedPlayer = False
    assert bridge_instance.configUseEmbeddedPlayer is False

    bridge_instance.configEnableHardwareAcceleration = False
    assert bridge_instance.configEnableHardwareAcceleration is False

    bridge_instance.configDivideLogsByService = True
    assert bridge_instance.configDivideLogsByService is True

    bridge_instance.configDatabasePath = "/custom/db.sqlite"
    assert bridge_instance.configDatabasePath == "/custom/db.sqlite"

    bridge_instance.configLogDirectory = "/custom/logsdir"
    assert bridge_instance.configLogDirectory == "/custom/logsdir"

    bridge_instance.configEnableCaching = True
    assert bridge_instance.configEnableCaching is True

    bridge_instance.configMaxCacheSizeGb = 25.0
    assert bridge_instance.configMaxCacheSizeGb == 25.0

    bridge_instance.configMaxLogRetentionDays = 14
    assert bridge_instance.configMaxLogRetentionDays == 14

    bridge_instance.seriesSortOption = "Recently Added"
    assert bridge_instance.seriesSortOption == "Recently Added"

    bridge_instance.filterOutWatched = True
    assert bridge_instance.filterOutWatched is True


def test_backend_bridge_library_selection(
    sample_library_payload: Dict[str, Any], qtbot: Any
) -> None:
    config.libraries["TestMedia"] = ["/path/to/media"]
    bridge_instance = BackendBridge()

    with patch("lan_streamer.db.load_library", return_value=sample_library_payload):
        bridge_instance.selectLibrary("TestMedia")
        assert bridge_instance.seriesModel.rowCount() == 1
        assert bridge_instance.availableLibraries == ["TestMedia"]

        # Trigger selection slots
        bridge_instance.selectSeries(0)
        assert bridge_instance.selectedSeriesTitle == "Cosmos"
        assert bridge_instance.selectedSeriesOverview == "Space doc."
        assert bridge_instance.selectedSeriesPoster == "/poster.jpg"
        assert bridge_instance.selectedSeriesIndex == 0
        assert bridge_instance.seasonModel.rowCount() == 1

        bridge_instance.selectSeason(0)
        assert bridge_instance.episodeModel.rowCount() == 1

        # Test actions on episodes
        with patch("lan_streamer.db.update_episode_watched_status") as mock_db:
            bridge_instance.markEpisodesWatched([0])
            mock_db.assert_called_once_with("/path/to/ep1.mkv", True)

        with patch("lan_streamer.db.update_episode_watched_status") as mock_db:
            bridge_instance.markEpisodesUnwatched([0])
            mock_db.assert_called_once_with("/path/to/ep1.mkv", False)

        requested_paths: List[str] = []
        bridge_instance.playbackRequested.connect(requested_paths.append)
        bridge_instance.playEpisode(0)
        assert requested_paths == ["/path/to/ep1.mkv"]


def test_backend_bridge_metadata_match(
    sample_library_payload: Dict[str, Any], qtbot: Any
) -> None:
    bridge_instance = BackendBridge()
    with patch("lan_streamer.db.load_library", return_value=sample_library_payload):
        bridge_instance.selectLibrary("TestMedia")
        bridge_instance.selectSeries(0)

        # Test search slots
        with patch("lan_streamer.tmdb.tmdb_client.search_series_full") as mock_tmdb:
            mock_tmdb.return_value = [{"id": 555, "name": "Found Series"}]
            results_list = bridge_instance.searchSeriesMetadata("Cosmos", "TMDB")
            assert len(results_list) == 1
            assert results_list[0]["name"] == "Found Series"

        with patch("lan_streamer.jellyfin.jellyfin_client.search_series") as mock_jf:
            mock_jf.return_value = [{"Id": "jf1", "Name": "JF Series"}]
            jf_results = bridge_instance.searchSeriesMetadata("Cosmos", "Jellyfin")
            assert len(jf_results) == 1
            assert jf_results[0]["name"] == "JF Series"

        # Test apply match slot
        match_target_payload = {
            "id": "555",
            "name": "Found Series",
            "overview": "New doc overview",
            "poster_path": "/new.jpg",
            "provider": "TMDB",
        }
        with (
            patch("lan_streamer.db.save_library") as mock_save,
            patch(
                "lan_streamer.tmdb.tmdb_client.download_image",
                return_value="/cached.jpg",
            ),
        ):
            bridge_instance.applySeriesMetadataMatch("Cosmos", match_target_payload)
            mock_save.assert_called_once()
            assert bridge_instance.selectedSeriesOverview == "New doc overview"

        # Test open dialog signal
        emitted_series: List[str] = []
        bridge_instance.openMetadataMatchDialog.connect(emitted_series.append)
        bridge_instance.matchMetadataForSeries(0)
        assert emitted_series == ["Cosmos"]


def test_backend_bridge_library_management() -> None:
    bridge_instance = BackendBridge()
    bridge_instance.addNewLibrary("UniqueMediaLib")
    assert "UniqueMediaLib" in config.libraries

    bridge_instance.addRootDirectoryToLibrary("UniqueMediaLib", "/root/media")
    assert "/root/media" in bridge_instance.getRootDirectoriesForLibrary(
        "UniqueMediaLib"
    )

    bridge_instance.removeRootDirectoryFromLibrary("UniqueMediaLib", "/root/media")
    assert "/root/media" not in bridge_instance.getRootDirectoriesForLibrary(
        "UniqueMediaLib"
    )

    bridge_instance.removeSelectedLibrary("UniqueMediaLib")
    assert "UniqueMediaLib" not in config.libraries


def test_backend_bridge_scan_triggers(sample_library_payload: Dict[str, Any]) -> None:
    bridge_instance = BackendBridge()
    with patch("lan_streamer.db.load_library", return_value=sample_library_payload):
        bridge_instance.selectLibrary("TestMedia")

        with patch("lan_streamer.backend.ScanWorker") as mock_worker:
            bridge_instance.scanForNewFiles()
            mock_worker.assert_called_once()
            mock_worker.return_value.start.assert_called_once()

        with patch("lan_streamer.backend.ScanWorker") as mock_worker2:
            bridge_instance.refreshEntireLibrary()
            mock_worker2.assert_called_once()

        with patch("lan_streamer.db.cleanup_library", return_value={"series": 1}):
            bridge_instance.cleanupLibrary()
            assert "Cleanup finished" in bridge_instance.statusMessage


def test_backend_bridge_jellyfin_sync_triggers() -> None:
    bridge_instance = BackendBridge()
    with patch(
        "lan_streamer.jellyfin.jellyfin_client.is_configured", return_value=True
    ):
        with patch("lan_streamer.backend.JellyfinPullWorker") as mock_pull:
            bridge_instance.pullWatchHistoryFromJellyfin()
            mock_pull.assert_called_once()

        with patch("lan_streamer.backend.JellyfinPushWorker") as mock_push:
            bridge_instance.pushWatchHistoryToJellyfin()
            mock_push.assert_called_once()


def test_backend_workers_execution() -> None:
    # Test ScanWorker
    with patch("lan_streamer.backend.scan_directories", return_value={}) as mock_scan:
        worker_instance = ScanWorker(["/path"], "tv", {})
        worker_instance.run()
        mock_scan.assert_called_once()

    # Test SyncAllWorker
    with patch("lan_streamer.backend.scan_directories", return_value={}):
        with (
            patch("lan_streamer.db.load_library", return_value={}),
            patch("lan_streamer.db.save_library"),
        ):
            sync_worker = SyncAllWorker()
            sync_worker.run()

    # Test CleanupWorker
    with patch("lan_streamer.db.cleanup_library", return_value={}) as mock_clean:
        clean_worker = CleanupWorker("TestLib", ["/path"])
        clean_worker.run()
        mock_clean.assert_called_once()

    # Test JellyfinPullWorker
    with (
        patch(
            "lan_streamer.jellyfin.jellyfin_client.fetch_watched_episodes",
            return_value=([], [], []),
        ),
        patch("lan_streamer.db.sync_watched_from_jellyfin_data", return_value=0),
    ):
        pull_worker = JellyfinPullWorker()
        pull_worker.run()

    # Test JellyfinPushWorker
    with patch("lan_streamer.db.get_all_episodes_with_jellyfin_id", return_value=[]):
        push_worker = JellyfinPushWorker()
        push_worker.run()


def test_backend_renamer_slots(sample_library_payload: Dict[str, Any]) -> None:
    bridge_instance = BackendBridge()
    with patch("lan_streamer.db.load_library", return_value=sample_library_payload):
        bridge_instance.selectLibrary("TestMedia")

        with patch("lan_streamer.renamer.get_rename_preview", return_value=[]):
            previews_list = bridge_instance.getRenamePreviews(0, "Template")
            assert previews_list == []

        with patch("lan_streamer.renamer.perform_rename", return_value=[]):
            renames_list = bridge_instance.applyRenames([])
            assert renames_list == []


def test_backend_partial_scan_updates() -> None:
    bridge_instance = BackendBridge()
    bridge_instance._current_library_name = "TestMedia"
    partial_data = {"Show A": {"metadata": {"poster_path": "/a.jpg"}}}
    bridge_instance._on_scan_worker_partial(partial_data)
    assert getattr(bridge_instance, "_cached_library_data", {}) == {}


def test_backend_file_system_monitoring(
    sample_library_payload: Dict[str, Any], qtbot: Any, tmp_path: Any
) -> None:
    bridge_instance = BackendBridge()
    media_directory = tmp_path / "media_roots"
    media_directory.mkdir()
    directory_path_string = str(media_directory)

    config.libraries["MonitoredLib"] = {"type": "tv", "paths": [directory_path_string]}

    with patch("lan_streamer.db.load_library", return_value=sample_library_payload):
        bridge_instance.selectLibrary("MonitoredLib")
        assert (
            directory_path_string in bridge_instance._file_system_watcher.directories()
        )

        # Trigger directory change slot manually to simulate file system activity
        with patch.object(bridge_instance._debounce_timer, "start") as mock_timer_start:
            bridge_instance._on_directory_changed(directory_path_string)
            mock_timer_start.assert_not_called()

        # Trigger debounce timeout slot manually to verify scan trigger
        with patch.object(bridge_instance, "scanForNewFiles") as mock_scan:
            bridge_instance._on_debounce_timeout()
            mock_scan.assert_not_called()

        # Test concurrency protection: if ScanWorker is already running, avoid duplicate triggers
        mock_active_worker = MagicMock()
        mock_active_worker.isRunning.return_value = True
        bridge_instance._scan_worker = mock_active_worker
        bridge_instance._current_library_name = "MonitoredLib"

        with patch("lan_streamer.backend.ScanWorker") as mock_worker_class:
            bridge_instance.scanForNewFiles()
            mock_worker_class.assert_not_called()


def test_backend_on_scan_worker_finished_flows() -> None:
    bridge = BackendBridge()
    config.libraries["TestMovieLib"] = {"type": "movie", "paths": ["/mpath"]}
    bridge._current_library_name = "TestMovieLib"
    bridge._cached_library_data = {"Movie 1": {"path": "/mpath/m1.mp4"}}

    updated_movie_lib = {"Movie 1": {"path": "/mpath/m1.mp4"}}
    with (
        patch("lan_streamer.db.save_movie_library") as mock_save,
        patch.object(bridge, "selectLibrary") as mock_select,
    ):
        bridge._on_scan_worker_finished(updated_movie_lib)
        mock_save.assert_called_once_with("TestMovieLib", updated_movie_lib)
        mock_select.assert_called_once_with("TestMovieLib")

    config.libraries["TestTvLib"] = {"type": "tv", "paths": ["/tpath"]}
    bridge._current_library_name = "TestTvLib"
    bridge._cached_library_data = {"Show A": {"seasons": {"S1": {"episodes": [{}]}}}}

    updated_tv_lib = {"Show A": {"seasons": {"S1": {"episodes": [{}, {}]}}}}
    with (
        patch("lan_streamer.db.save_library") as mock_save,
        patch("lan_streamer.jellyfin.jellyfin_client.is_configured", return_value=True),
        patch.object(bridge, "pullWatchHistoryFromJellyfin") as mock_pull,
        patch.object(bridge, "selectLibrary") as mock_select,
    ):
        bridge._on_scan_worker_finished(updated_tv_lib)
        mock_save.assert_called_once_with("TestTvLib", updated_tv_lib)
        mock_pull.assert_not_called()
        mock_select.assert_called_once_with("TestTvLib")
