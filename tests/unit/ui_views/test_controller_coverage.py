"""Tests targeting uncovered lines in controller.py (lines 202, 278-283, 373,
559, 584, 714, 762-763, 790-791, 835-836, 1076-1078, 1109-1110, 1113-1114,
1154-1155, 1392-1404)."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from lan_streamer.ui_views import Controller


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def controller_instance():
    """Minimal controller wired with mocks for fast unit tests."""
    mock_config = MagicMock()
    mock_config.libraries = {"test_lib": {"type": "tv", "paths": ["/media/tv"]}}
    mock_config.sort_mode = "Alphabetical"
    mock_config.sort_descending = False
    mock_config.filter_out_watched = False
    ctrl = Controller(
        config=mock_config,
        db=MagicMock(),
        jellyfin_client=MagicMock(),
        tmdb_client=MagicMock(),
    )
    ctrl.current_library_name = "test_lib"
    ctrl.cached_library_data = {
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
        }
    }
    ctrl.selected_series_name = ""
    return ctrl


# ------------------------------------------------------------------
# 1. _on_directory_changed (line 202)
# ------------------------------------------------------------------


class TestOnDirectoryChanged:
    def test_logs_directory_modification(self, controller_instance, caplog):
        with caplog.at_level(logging.INFO, logger="lan_streamer.ui_views.controller"):
            controller_instance._on_directory_changed("/media/tv")
        assert "Directory modification detected on '/media/tv'" in caplog.text


# ------------------------------------------------------------------
# 2. select_season_detail (lines 278-283)
# ------------------------------------------------------------------


class TestSelectSeasonDetail:
    def test_emits_season_detail_requested_signal(self, controller_instance):
        received = []
        controller_instance.season_detail_requested.connect(
            lambda series_name, season_name: received.append((series_name, season_name))
        )
        controller_instance.select_season_detail("Test Show", "Season 1")
        assert received == [("Test Show", "Season 1")]


# ------------------------------------------------------------------
# 3. trigger_jellyfin_pull guard (lines 762-763)
# ------------------------------------------------------------------


class TestTriggerJellyfinPullGuard:
    def test_skips_when_worker_already_running(self, controller_instance):
        controller_instance._jellyfin_client.is_configured.return_value = True
        controller_instance.worker_manager.jellyfin_pull._instance = MagicMock(
            spec=["is_running", "_is_async_worker"]
        )
        controller_instance.worker_manager.jellyfin_pull._instance._is_async_worker = (
            True
        )
        controller_instance.worker_manager.jellyfin_pull._instance.is_running = True

        status_messages = []
        controller_instance.status_changed.connect(status_messages.append)

        with patch("lan_streamer.ui_views.controller.JellyfinPullWorker") as mock_cls:
            controller_instance.trigger_jellyfin_pull()
            mock_cls.assert_not_called()

        assert not any("Pulling watch history" in m for m in status_messages)


# ------------------------------------------------------------------
# 4. trigger_jellyfin_push guard (lines 790-791)
# ------------------------------------------------------------------


class TestTriggerJellyfinPushGuard:
    def test_skips_when_worker_already_running(self, controller_instance):
        controller_instance._jellyfin_client.is_configured.return_value = True
        controller_instance.worker_manager.jellyfin_push._instance = MagicMock(
            spec=["is_running", "_is_async_worker"]
        )
        controller_instance.worker_manager.jellyfin_push._instance._is_async_worker = (
            True
        )
        controller_instance.worker_manager.jellyfin_push._instance.is_running = True

        status_messages = []
        controller_instance.status_changed.connect(status_messages.append)

        with patch("lan_streamer.ui_views.controller.JellyfinPushWorker") as mock_cls:
            controller_instance.trigger_jellyfin_push()
            mock_cls.assert_not_called()

        assert not any("Pushing local watch history" in m for m in status_messages)


# ------------------------------------------------------------------
# 5. _on_detail_progress_batch (lines 835-836)
# ------------------------------------------------------------------


class TestOnDetailProgressBatch:
    def test_iterates_events_and_emits_signals(self, controller_instance):
        received = []
        controller_instance.detail_progress_updated.connect(
            lambda event, payload: received.append((event, payload))
        )
        events = [
            {"event": "scan_start", "payload": {"library": "test_lib"}},
            {"event": "scan_progress", "payload": {"count": 5}},
        ]
        controller_instance._on_detail_progress_batch(events)
        assert len(received) == 2
        assert received[0] == ("scan_start", {"library": "test_lib"})
        assert received[1] == ("scan_progress", {"count": 5})

    def test_empty_events_emits_nothing(self, controller_instance):
        received = []
        controller_instance.detail_progress_updated.connect(
            lambda event, payload: received.append(event)
        )
        controller_instance._on_detail_progress_batch([])
        assert len(received) == 0


# ------------------------------------------------------------------
# 6. _on_post_scan_error emits scan_completed (line 559)
# ------------------------------------------------------------------


class TestOnPostScanError:
    def test_emits_scan_completed_when_conditions_met(self, controller_instance):
        """_on_post_scan_error (inner closure) emits scan_completed when
        _skip_scan_completed is False and _doing_scan_and_update is False."""
        controller_instance._doing_scan_and_update = False

        mock_worker_instance = MagicMock()
        mock_worker_instance.finished = MagicMock()
        mock_worker_instance.finished.connect = MagicMock()
        mock_worker_instance.error = MagicMock()
        mock_worker_instance.error.connect = MagicMock()

        mock_scan_worker = MagicMock()
        mock_scan_worker.changed_season_ids = set()
        mock_scan_worker.changed_movie_ids = set()
        mock_scan_worker.unavailable_directories = []
        controller_instance.worker_manager.scan._instance = mock_scan_worker

        mock_module = MagicMock()
        mock_module.PostScanWorker = MagicMock(return_value=mock_worker_instance)

        scan_completed_received = []
        controller_instance.scan_completed.connect(
            lambda: scan_completed_received.append(True)
        )

        with patch.dict(
            "sys.modules", {"lan_streamer.backend.post_scan_worker": mock_module}
        ):
            controller_instance._on_scan_finished(
                {"test_series": {}}, _skip_scan_completed=False
            )

        error_callback = mock_worker_instance.error.connect.call_args[0][0]
        error_callback("Simulated PostScanWorker error")

        assert len(scan_completed_received) == 1


# ------------------------------------------------------------------
# 7. _on_post_scan_finished chains to trigger_runtime_extraction (line 584)
# ------------------------------------------------------------------


class TestOnPostScanFinished:
    def test_chains_to_runtime_extraction_when_pass3_flag_set(
        self, controller_instance
    ):
        controller_instance._running_pass3_after_scan = True
        controller_instance._doing_scan_and_update = False
        controller_instance.trigger_runtime_extraction = MagicMock()

        controller_instance._on_post_scan_finished(
            {"changed_hashes": []}, {"season1"}, {"movie1"}
        )

        controller_instance.trigger_runtime_extraction.assert_called_once_with(
            {"season1"}, {"movie1"}
        )

    def test_emits_scan_completed_when_no_pass3(self, controller_instance):
        controller_instance._running_pass3_after_scan = False
        controller_instance._doing_scan_and_update = False

        received = []
        controller_instance.scan_completed.connect(lambda: received.append(True))

        controller_instance._on_post_scan_finished({"changed_hashes": []}, set(), set())

        assert len(received) == 1

    def test_emits_smart_rows_when_changed_hashes_nonempty(self, controller_instance):
        controller_instance._running_pass3_after_scan = False
        controller_instance._doing_scan_and_update = False

        received = []
        controller_instance.smart_rows_updated.connect(
            lambda hashes: received.extend(hashes)
        )

        controller_instance._on_post_scan_finished(
            {"changed_hashes": ["hash_a", "hash_b"]}, set(), set()
        )

        assert received == ["hash_a", "hash_b"]


# ------------------------------------------------------------------
# 8. _on_scan_and_update_scan_finished cleanup-skip path (line 714)
# ------------------------------------------------------------------


class TestOnScanAndUpdateCleanupSkip:
    def test_chains_runtime_extraction_on_unavailable_dirs(self, controller_instance):
        """Line 714: _on_scan_and_update_scan_finished chains to
        trigger_runtime_extraction when _running_pass3_after_scan is True
        and updated_library has unavailable_directories."""
        controller_instance._running_pass3_after_scan = True
        controller_instance._doing_scan_and_update = True
        controller_instance.trigger_runtime_extraction = MagicMock()

        # _on_scan_finished reads changed_season_ids from the scan worker instance
        mock_scan_worker = MagicMock()
        mock_scan_worker.changed_season_ids = {"s1"}
        mock_scan_worker.changed_movie_ids = {"m1"}
        mock_scan_worker.unavailable_directories = []
        controller_instance.worker_manager.scan._instance = mock_scan_worker

        # Use a dict subclass that allows arbitrary attribute assignment,
        # because getattr(updated_library, "unavailable_directories", []) is
        # used to detect unavailable root directories.
        class _LibDict(dict):
            unavailable_directories: list = []

        updated_library = _LibDict({"series": {}})
        updated_library.unavailable_directories = ["/unavail"]

        with (
            patch("lan_streamer.backend.post_scan_worker.PostScanWorker"),
            patch.object(controller_instance, "select_library"),
        ):
            controller_instance._on_scan_and_update_scan_finished(updated_library)

        controller_instance.trigger_runtime_extraction.assert_called_once_with(
            {"s1"}, {"m1"}
        )

    def test_emits_scan_completed_when_no_pass3(self, controller_instance):
        """Line 716: scan_completed emitted when _running_pass3_after_scan is False."""
        controller_instance._running_pass3_after_scan = False
        controller_instance._doing_scan_and_update = True

        mock_scan_worker = MagicMock()
        mock_scan_worker.changed_season_ids = None
        mock_scan_worker.changed_movie_ids = None
        mock_scan_worker.unavailable_directories = []
        controller_instance.worker_manager.scan._instance = mock_scan_worker

        class _LibDict(dict):
            unavailable_directories: list = []

        updated_library = _LibDict({"series": {}})
        updated_library.unavailable_directories = ["/unavail"]

        received = []
        controller_instance.scan_completed.connect(lambda: received.append(True))

        with (
            patch("lan_streamer.backend.post_scan_worker.PostScanWorker"),
            patch.object(controller_instance, "select_library"),
        ):
            controller_instance._on_scan_and_update_scan_finished(updated_library)

        assert len(received) == 1


# ------------------------------------------------------------------
# 9. apply_metadata_match no tmdb_identifier (lines 1076-1078)
# ------------------------------------------------------------------


class TestApplyMetadataMatchNoTmdbId:
    def test_finishes_early_when_no_tmdb_identifier_for_tv_series(
        self, controller_instance
    ):
        controller_instance._finish_metadata_match = MagicMock()
        controller_instance._download_provider_artwork = MagicMock()

        controller_instance.apply_metadata_match(
            "Test Show",
            {"id": "", "name": "Some Match", "first_air_date": "2020-01-01"},
        )

        controller_instance._finish_metadata_match.assert_called_once_with("Test Show")
        controller_instance._download_provider_artwork.assert_called_once()


# ------------------------------------------------------------------
# 10. apply_metadata_match series directory resolution (lines 1109-1110)
# ------------------------------------------------------------------


class TestApplyMetadataMatchDirectoryResolution:
    def test_resolves_series_directory_from_root_paths(
        self, controller_instance, tmp_path
    ):
        series_dir = tmp_path / "Test Show"
        series_dir.mkdir()
        controller_instance._config.libraries["test_lib"]["paths"] = [str(tmp_path)]
        controller_instance._finish_metadata_match = MagicMock()
        controller_instance.worker_manager.metadata_apply._instance = None

        mock_worker = MagicMock()
        mock_worker._is_async_worker = False

        with (
            patch("lan_streamer.ui_views.controller.MetadataApplyWorker") as mock_cls,
            patch("lan_streamer.backend.RefreshSeriesWorker", MagicMock()),
        ):
            mock_cls.return_value = mock_worker
            mock_worker.finished = MagicMock()
            mock_worker.finished.connect = MagicMock()
            mock_worker.error = MagicMock()
            mock_worker.error.connect = MagicMock()

            controller_instance.apply_metadata_match(
                "Test Show",
                {
                    "id": "99999",
                    "name": "Matched Title",
                    "first_air_date": "2020-01-01",
                },
            )

            call_kwargs = mock_cls.call_args
            assert call_kwargs[1]["series_directory"] == series_dir


# ------------------------------------------------------------------
# 11. MetadataApplyWorker already running guard (lines 1113-1114)
# ------------------------------------------------------------------


class TestMetadataApplyWorkerGuard:
    def test_skips_when_worker_already_running(self, controller_instance):
        from lan_streamer.system.threading_manager import WorkerSlot

        real_slot = WorkerSlot(parent=controller_instance)
        mock_running_worker = MagicMock(spec=["is_running", "_is_async_worker"])
        mock_running_worker._is_async_worker = True
        mock_running_worker.is_running = True
        real_slot._instance = mock_running_worker
        controller_instance.worker_manager.metadata_apply = real_slot

        controller_instance.apply_metadata_match(
            "Test Show",
            {"id": "99999", "name": "Matched Title", "first_air_date": "2020-01-01"},
        )

        assert real_slot._instance is mock_running_worker


# ------------------------------------------------------------------
# 12. _on_metadata_apply_error (lines 1154-1155)
# ------------------------------------------------------------------


class TestOnMetadataApplyError:
    def test_logs_error_and_finishes_metadata_match(self, controller_instance, caplog):
        controller_instance._finish_metadata_match = MagicMock()

        with caplog.at_level(logging.ERROR, logger="lan_streamer.ui_views.controller"):
            controller_instance._on_metadata_apply_error(
                "Test Show", "TMDB API timed out"
            )

        assert (
            "Metadata apply failed for 'Test Show': TMDB API timed out" in caplog.text
        )
        controller_instance._finish_metadata_match.assert_called_once_with("Test Show")


# ------------------------------------------------------------------
# 13. trigger_series_scan full body (lines 1392-1404)
# ------------------------------------------------------------------


class TestTriggerSeriesScan:
    def test_full_body_with_mocked_worker(self, controller_instance):
        with patch("lan_streamer.backend.ScanSingleSeriesWorker") as mock_cls:
            mock_worker = MagicMock()
            mock_worker.finished = MagicMock()
            mock_worker.finished.connect = MagicMock()
            mock_worker.error = MagicMock()
            mock_worker.error.connect = MagicMock()
            mock_cls.return_value = mock_worker

            status_messages = []
            controller_instance.status_changed.connect(status_messages.append)

            controller_instance.trigger_series_scan("Test Show")

            mock_cls.assert_called_once()
            assert any("Scanning folders for 'Test Show'" in m for m in status_messages)

    def test_returns_early_when_no_library_selected(self, controller_instance):
        controller_instance.current_library_name = ""
        status_messages = []
        controller_instance.status_changed.connect(status_messages.append)

        controller_instance.trigger_series_scan("Test Show")

        assert any("Select a library first" in m for m in status_messages)

    def test_returns_when_scan_worker_running(self, controller_instance):
        mock_scan_worker = MagicMock(spec=["is_running", "_is_async_worker"])
        mock_scan_worker._is_async_worker = True
        mock_scan_worker.is_running = True
        controller_instance.worker_manager.scan._instance = mock_scan_worker

        status_messages = []
        controller_instance.status_changed.connect(status_messages.append)

        controller_instance.trigger_series_scan("Test Show")

        assert any("A scan is already in progress" in m for m in status_messages)

    def test_returns_when_series_scan_worker_running(self, controller_instance):
        mock_series_worker = MagicMock(spec=["is_running", "_is_async_worker"])
        mock_series_worker._is_async_worker = True
        mock_series_worker.is_running = True
        controller_instance.worker_manager.scan_series._instance = mock_series_worker

        status_messages = []
        controller_instance.status_changed.connect(status_messages.append)

        controller_instance.trigger_series_scan("Test Show")

        assert any("A series scan is already in progress" in m for m in status_messages)
