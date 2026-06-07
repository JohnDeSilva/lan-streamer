"""
Extended Controller tests to push controller.py coverage higher.
Targeting lines: 97, 105, 148, 160, 171-173, 176-178, 189-196, 218-222, 230-246,
249-259, 263-264, 315, 345-346, 376-412, 418-435, 439-446, 450-451, 468-469,
505-526, 538, 543, 549-561, 564, 569-573, 587-596, and more.
"""

import pytest
from unittest.mock import patch, MagicMock
from typing import List

from lan_streamer.ui_views import Controller
from lan_streamer.system.config import config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_save():
    with (
        patch("lan_streamer.db.save_library") as mock_save,
        patch("lan_streamer.db.save_movie_library") as mock_movie_save,
    ):
        yield mock_save, mock_movie_save


@pytest.fixture
def ctrl(mock_db_save):
    """A controller with a simple TV library and config set up."""
    c = Controller()
    c.current_library_name = "TestLib"
    c.cached_library_data = {
        "ShowA": {
            "metadata": {"tmdb_identifier": "111", "locked_metadata": False},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": "/tv/ShowA/S01E01.mkv",
                            "watched": False,
                            "tmdb_number": 1,
                            "date_added": 1000,
                            "air_date": "2021-01-01",
                            "runtime": 45,
                        }
                    ]
                }
            },
        },
        "MovieX": {
            "path": "/movies/MovieX.mkv",
            "tmdb_identifier": "222",
            "locked_metadata": False,
            "watched": False,
        },
    }
    config.libraries = {
        "TestLib": {"type": "tv", "paths": ["/tv"]},
        "MovieLib": {"type": "movie", "paths": ["/movies"]},
    }
    c.selected_series_name = "ShowA"
    return c


# ---------------------------------------------------------------------------
# select_library — movie library type
# ---------------------------------------------------------------------------


def test_select_library_movie_type() -> None:
    controller = Controller()
    config.libraries["MovieLib"] = {"type": "movie", "paths": []}

    with patch(
        "lan_streamer.db.load_movie_library", return_value={"Film1": {"path": "/f"}}
    ) as mock_load:
        controller.select_library("MovieLib")
        mock_load.assert_called_once_with("MovieLib")
        assert "Film1" in controller.cached_library_data


def test_select_library_removes_existing_watcher_paths(tmp_path) -> None:
    controller = Controller()
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    controller.file_system_watcher.addPath(str(fake_dir))
    assert str(fake_dir) in controller.file_system_watcher.directories()

    config.libraries["WatchLib"] = {"type": "tv", "paths": []}
    with patch("lan_streamer.db.load_library", return_value={}):
        controller.select_library("WatchLib")
    assert str(fake_dir) not in controller.file_system_watcher.directories()


def test_select_library_no_reset_keeps_selection() -> None:
    controller = Controller()
    controller.selected_series_name = "OldShow"
    config.libraries["Lib2"] = {"type": "tv", "paths": []}

    with patch("lan_streamer.db.load_library", return_value={}):
        controller.select_library("Lib2", reset_selection=False)

    assert controller.selected_series_name == "OldShow"


# ---------------------------------------------------------------------------
# _cache_series_metrics — placeholder episodes (no path) not counted
# ---------------------------------------------------------------------------


def test_cache_series_metrics_excludes_placeholder_episodes() -> None:
    c = Controller()
    c.cached_library_data = {
        "ShowP": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": "/tv/s01e01.mkv",
                            "watched": True,
                            "date_added": 100,
                            "air_date": "2021-01-01",
                        },
                        {
                            "name": "S01E02.mkv",
                            "path": None,
                            "watched": False,
                        },  # placeholder
                    ]
                }
            },
        }
    }
    c._cache_series_metrics()
    # Only the local-path episode should count
    assert c.cached_library_data["ShowP"]["metrics"]["total_episodes"] == 1
    assert c.cached_library_data["ShowP"]["metrics"]["watched_episodes"] == 1


# ---------------------------------------------------------------------------
# select_series / select_movie
# ---------------------------------------------------------------------------


def test_select_series_emits_signal(ctrl) -> None:
    received: List[str] = []
    ctrl.series_selected.connect(received.append)
    ctrl.select_series("ShowA")
    assert received == ["ShowA"]
    assert ctrl.selected_series_name == "ShowA"


def test_select_series_ignores_unknown(ctrl) -> None:
    received: List[str] = []
    ctrl.series_selected.connect(received.append)
    ctrl.select_series("NonExistent")
    assert received == []


def test_select_movie_emits_signal(ctrl) -> None:
    received: List[str] = []
    ctrl.movie_selected.connect(received.append)
    ctrl.select_movie("MovieX")
    assert received == ["MovieX"]


def test_select_movie_ignores_unknown(ctrl) -> None:
    received: List[str] = []
    ctrl.movie_selected.connect(received.append)
    ctrl.select_movie("NonExistent")
    assert received == []


# ---------------------------------------------------------------------------
# set_sort_descending
# ---------------------------------------------------------------------------


def test_set_sort_descending_emits_library_loaded(ctrl) -> None:
    ctrl.sort_descending = False
    signals: List[bool] = []
    ctrl.library_loaded.connect(lambda: signals.append(True))
    ctrl.set_sort_descending(True)
    assert ctrl.sort_descending is True
    assert len(signals) == 1


def test_set_sort_descending_same_value_no_emit(ctrl) -> None:
    ctrl.sort_descending = True
    signals: List[bool] = []
    ctrl.library_loaded.connect(lambda: signals.append(True))
    ctrl.set_sort_descending(True)
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# mark_episode_watched / mark_season_watched / mark_series_watched
# ---------------------------------------------------------------------------


def test_mark_episode_watched_updates_cache_tv(ctrl) -> None:
    with patch("lan_streamer.db.update_episode_watched_status"):
        ctrl.mark_episode_watched("/tv/ShowA/S01E01.mkv", True)

    ep = ctrl.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0]
    assert ep["watched"] is True


def test_mark_episode_watched_updates_cache_movie(ctrl) -> None:
    ctrl.cached_library_data["MovieX"]["path"] = "/movies/MovieX.mkv"
    with patch("lan_streamer.db.update_episode_watched_status"):
        ctrl.mark_episode_watched("/movies/MovieX.mkv", True)

    assert ctrl.cached_library_data["MovieX"]["watched"] is True


def test_mark_episode_watched_emits_library_loaded(ctrl) -> None:
    signals: List[bool] = []
    ctrl.library_loaded.connect(lambda: signals.append(True))
    with patch("lan_streamer.db.update_episode_watched_status"):
        ctrl.mark_episode_watched("/tv/ShowA/S01E01.mkv", True)
    assert len(signals) == 1


def test_mark_episode_watched_suppressed_during_playback(ctrl) -> None:
    ctrl.is_video_playing = True
    signals: List[bool] = []
    ctrl.library_loaded.connect(lambda: signals.append(True))
    with patch("lan_streamer.db.update_episode_watched_status"):
        ctrl.mark_episode_watched("/tv/ShowA/S01E01.mkv", True)
    assert len(signals) == 0


def test_mark_season_watched(ctrl) -> None:
    with patch("lan_streamer.db.update_season_watched_status"):
        ctrl.mark_season_watched("ShowA", "Season 1")

    ep = ctrl.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0]
    assert ep["watched"] is True


def test_mark_season_watched_suppressed_during_playback(ctrl) -> None:
    ctrl.is_video_playing = True
    signals: List[bool] = []
    ctrl.library_loaded.connect(lambda: signals.append(True))
    with patch("lan_streamer.db.update_season_watched_status"):
        ctrl.mark_season_watched("ShowA", "Season 1")
    assert len(signals) == 0


def test_mark_series_watched(ctrl) -> None:
    with patch("lan_streamer.db.update_series_watched_status"):
        ctrl.mark_series_watched("ShowA")

    ep = ctrl.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0]
    assert ep["watched"] is True


def test_mark_series_watched_suppressed_during_playback(ctrl) -> None:
    ctrl.is_video_playing = True
    signals: List[bool] = []
    ctrl.library_loaded.connect(lambda: signals.append(True))
    with patch("lan_streamer.db.update_series_watched_status"):
        ctrl.mark_series_watched("ShowA")
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# trigger_scan — no library name path
# ---------------------------------------------------------------------------


def test_trigger_scan_no_library_name() -> None:
    c = Controller()
    c.current_library_name = ""
    statuses: List[str] = []
    c.status_changed.connect(statuses.append)

    with patch("lan_streamer.ui_views.controller.ScanWorker") as mock_cls:
        c.trigger_scan()
        mock_cls.assert_not_called()
    assert any("Select a library" in s for s in statuses)


# ---------------------------------------------------------------------------
# trigger_scan_and_update
# ---------------------------------------------------------------------------


def test_trigger_scan_and_update_no_library() -> None:
    c = Controller()
    c.current_library_name = ""
    statuses: List[str] = []
    c.status_changed.connect(statuses.append)

    with patch("lan_streamer.ui_views.controller.ScanWorker") as mock_cls:
        c.trigger_scan_and_update()
        mock_cls.assert_not_called()
    assert any("Select a library" in s for s in statuses)


def test_trigger_scan_and_update_starts_worker(ctrl) -> None:
    with patch("lan_streamer.ui_views.controller.ScanWorker") as mock_cls:
        ctrl.trigger_scan_and_update(False)
        mock_cls.assert_called_once()
        mock_cls.return_value.start.assert_called_once()


def test_trigger_scan_and_update_skips_if_already_running(ctrl) -> None:
    mock_worker = MagicMock()
    mock_worker.isRunning.return_value = True
    ctrl.scan_worker_instance = mock_worker

    with patch("lan_streamer.ui_views.controller.ScanWorker") as mock_cls:
        ctrl.trigger_scan_and_update()
        mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# _on_scan_and_update_scan_finished / _on_scan_and_update_cleanup_finished
# ---------------------------------------------------------------------------


def test_on_scan_and_update_scan_finished_chains_cleanup(ctrl, mock_db_save) -> None:
    updated = ctrl.cached_library_data.copy()

    with patch("lan_streamer.ui_views.controller.CleanupWorker") as mock_cleanup:
        ctrl._on_scan_and_update_scan_finished(updated)
        mock_cleanup.assert_called_once()
        mock_cleanup.return_value.start.assert_called_once()


def test_on_scan_and_update_cleanup_finished_selects_library(
    ctrl, mock_db_save
) -> None:
    with patch.object(ctrl, "select_library") as mock_select:
        ctrl._on_scan_and_update_cleanup_finished({"series": 1, "episodes": 3})
        mock_select.assert_called_once_with("TestLib", reset_selection=False)


# ---------------------------------------------------------------------------
# trigger_cleanup — no library name
# ---------------------------------------------------------------------------


def test_trigger_cleanup_no_library_name() -> None:
    c = Controller()
    c.current_library_name = ""
    statuses: List[str] = []
    c.status_changed.connect(statuses.append)

    with patch("lan_streamer.ui_views.controller.CleanupWorker") as mock_cls:
        c.trigger_cleanup()
        mock_cls.assert_not_called()
    assert any("Select a library" in s for s in statuses)


# ---------------------------------------------------------------------------
# trigger_jellyfin_pull / push — not configured
# ---------------------------------------------------------------------------


def test_trigger_jellyfin_pull_not_configured() -> None:
    c = Controller()
    statuses: List[str] = []
    c.status_changed.connect(statuses.append)

    with patch(
        "lan_streamer.ui_views.controller.jellyfin_client.is_configured",
        return_value=False,
    ):
        c.trigger_jellyfin_pull()
    assert any("not configured" in s for s in statuses)


def test_trigger_jellyfin_push_not_configured() -> None:
    c = Controller()
    statuses: List[str] = []
    c.status_changed.connect(statuses.append)

    with patch(
        "lan_streamer.ui_views.controller.jellyfin_client.is_configured",
        return_value=False,
    ):
        c.trigger_jellyfin_push()
    assert any("not configured" in s for s in statuses)


# ---------------------------------------------------------------------------
# _on_scan_all_detail_progress
# ---------------------------------------------------------------------------


def test_on_scan_all_detail_progress_finish_root_tv(ctrl) -> None:
    ctrl.current_library_name = "TestLib"
    signals: List[bool] = []
    ctrl.library_loaded.connect(lambda: signals.append(True))

    with patch("lan_streamer.db.load_library", return_value={}) as mock_load:
        ctrl._on_scan_all_detail_progress("finish_root", {"library": "TestLib"})
        mock_load.assert_called_once()
    assert len(signals) == 1


def test_on_scan_all_detail_progress_finish_root_movie(ctrl) -> None:
    ctrl.current_library_name = "MovieLib"
    signals: List[bool] = []
    ctrl.library_loaded.connect(lambda: signals.append(True))

    with patch("lan_streamer.db.load_movie_library", return_value={}) as mock_load:
        ctrl._on_scan_all_detail_progress("finish_root", {"library": "MovieLib"})
        mock_load.assert_called_once()
    assert len(signals) == 1


def test_on_scan_all_detail_progress_finish_root_combined_view(ctrl) -> None:
    ctrl.current_library_name = "Combined View"
    signals: List[bool] = []
    ctrl.library_loaded.connect(lambda: signals.append(True))

    ctrl._on_scan_all_detail_progress("finish_root", {"library": "TestLib"})
    assert len(signals) == 1


def test_on_scan_all_detail_progress_non_finish_root(ctrl) -> None:
    """Other events should not trigger library_loaded."""
    signals: List[bool] = []
    ctrl.library_loaded.connect(lambda: signals.append(True))

    ctrl._on_scan_all_detail_progress(
        "start_folder", {"root": "/tv", "folder": "ShowA"}
    )
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# _on_scan_all_finished — combined view path
# ---------------------------------------------------------------------------


def test_on_scan_all_finished_combined_view() -> None:
    c = Controller()
    c.current_library_name = "Combined View"
    signals: List[bool] = []
    c.library_loaded.connect(lambda: signals.append(True))

    with patch.object(c, "select_library") as mock_select:
        c._on_scan_all_finished()
        mock_select.assert_not_called()
    assert len(signals) == 1


# ---------------------------------------------------------------------------
# trigger_runtime_extraction
# ---------------------------------------------------------------------------


def test_trigger_runtime_extraction_starts_worker() -> None:
    c = Controller()
    with patch("lan_streamer.ui_views.controller.RuntimeExtractionWorker") as mock_cls:
        c.trigger_runtime_extraction()
        mock_cls.assert_called_once()
        mock_cls.return_value.start.assert_called_once()


def test_trigger_runtime_extraction_skips_if_running() -> None:
    c = Controller()
    mock_worker = MagicMock()
    mock_worker.isRunning.return_value = True
    c.runtime_worker_instance = mock_worker

    with patch("lan_streamer.ui_views.controller.RuntimeExtractionWorker") as mock_cls:
        c.trigger_runtime_extraction()
        mock_cls.assert_not_called()


def test_on_runtime_progress_emits_global_progress() -> None:
    c = Controller()
    received: List[tuple] = []
    c.global_progress_updated.connect(
        lambda label, done, total: received.append((label, done, total))
    )
    c._on_runtime_progress(3, 10)
    assert received == [("Extracting Runtimes", 3, 10)]


def test_on_runtime_finished_selects_library() -> None:
    c = Controller()
    c.current_library_name = "SomeLib"

    with patch.object(c, "select_library") as mock_select:
        c._on_runtime_finished(5)
        mock_select.assert_called_once_with("SomeLib", reset_selection=False)


def test_on_runtime_finished_no_library_no_crash() -> None:
    c = Controller()
    c.current_library_name = ""
    with patch.object(c, "select_library") as mock_select:
        c._on_runtime_finished(5)
        mock_select.assert_not_called()


# ---------------------------------------------------------------------------
# _download_provider_artwork
# ---------------------------------------------------------------------------


def test_download_provider_artwork_downloads_when_configured(ctrl) -> None:
    target = {"tmdb_identifier": "999"}
    match = {"poster_path": "/p/image.jpg"}

    with patch(
        "lan_streamer.ui_views.controller.tmdb_client.download_image",
        return_value="/cached/img.jpg",
    ):
        ctrl._download_provider_artwork(target, match, is_movie=False)

    assert target["poster_path"] == "/cached/img.jpg"


def test_download_provider_artwork_fallback_when_no_download(ctrl) -> None:
    target = {"tmdb_identifier": "999"}
    match = {"poster_path": "/p/image.jpg"}

    with patch(
        "lan_streamer.ui_views.controller.tmdb_client.download_image", return_value=None
    ):
        ctrl._download_provider_artwork(target, match, is_movie=False)

    assert target["poster_path"] == "/p/image.jpg"


def test_download_provider_artwork_no_poster_no_crash(ctrl) -> None:
    target = {}
    match = {}
    ctrl._download_provider_artwork(target, match, is_movie=False)


# ---------------------------------------------------------------------------
# apply_metadata_match — Jellyfin provider / movie type / year parsing
# ---------------------------------------------------------------------------


def test_apply_metadata_match_jellyfin_provider(ctrl, mock_db_save) -> None:
    match = {
        "provider": "Jellyfin",
        "id": "jelly-abc",
        "tmdb_id": "tmdb-789",
        "name": "ShowA",
    }
    with patch("lan_streamer.ui_views.controller.tmdb_client"):
        ctrl.apply_metadata_match("ShowA", match)

    meta = ctrl.cached_library_data["ShowA"]["metadata"]
    assert meta["jellyfin_id"] == "jelly-abc"
    assert meta["tmdb_identifier"] == "tmdb-789"


def test_apply_metadata_match_movie_year_parsing(mock_db_save) -> None:
    c = Controller()
    c.current_library_name = "MovieLib"
    config.libraries["MovieLib"] = {"type": "movie", "paths": []}
    c.cached_library_data = {
        "Film": {"path": "/movies/Film.mkv", "locked_metadata": False}
    }

    match = {
        "id": "555",
        "name": "Film",
        "first_air_date": "2019-07-04",
    }
    with patch("lan_streamer.db.save_movie_library"):
        c.apply_metadata_match("Film", match)

    assert c.cached_library_data["Film"]["year"] == 2019


def test_apply_metadata_match_movie_bad_date_no_crash(mock_db_save) -> None:
    c = Controller()
    c.current_library_name = "MovieLib"
    config.libraries["MovieLib"] = {"type": "movie", "paths": []}
    c.cached_library_data = {
        "Film": {"path": "/movies/Film.mkv", "locked_metadata": False}
    }

    match = {
        "id": "555",
        "name": "Film",
        "first_air_date": "not-a-date",
    }
    with patch("lan_streamer.db.save_movie_library"):
        c.apply_metadata_match("Film", match)  # Should not crash


def test_apply_metadata_match_emits_movie_selected(mock_db_save) -> None:
    c = Controller()
    c.current_library_name = "MovieLib"
    config.libraries["MovieLib"] = {"type": "movie", "paths": []}
    c.cached_library_data = {
        "Film": {"path": "/movies/Film.mkv", "locked_metadata": False}
    }
    c.selected_series_name = "Film"

    received: List[str] = []
    c.movie_selected.connect(received.append)

    match = {"id": "555", "name": "Film"}
    with patch("lan_streamer.db.save_movie_library"):
        c.apply_metadata_match("Film", match)

    assert "Film" in received


def test_apply_metadata_match_emits_series_selected(ctrl, mock_db_save) -> None:
    ctrl.selected_series_name = "ShowA"
    received: List[str] = []
    ctrl.series_selected.connect(received.append)

    match = {"id": "111", "name": "ShowA"}
    with patch("lan_streamer.ui_views.controller.tmdb_client"):
        ctrl.apply_metadata_match("ShowA", match)

    assert "ShowA" in received


def test_apply_metadata_match_unknown_series_no_crash(ctrl, mock_db_save) -> None:
    match = {"id": "111", "name": "Unknown"}
    ctrl.apply_metadata_match("NonExistent", match)  # Should not crash
