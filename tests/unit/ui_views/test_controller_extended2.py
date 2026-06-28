"""
More extended Controller tests covering:
- apply_jellyfin_watch_match (TV, movie, unknown series)
- apply_episode_metadata_match (found, not found)
- update_episode_metadata
- trigger_series_refresh (no lib, running worker, starts worker)
- _on_refresh_finished
- merge_subtitles / embed_metadata / embed_metadata_series
- update_series_name
- apply_rename_batch
- set_video_playing
- delete_series / delete_episode edge cases
"""

import pytest
from unittest.mock import patch, MagicMock, ANY
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
def ctrl_tv(mock_db_save):
    c = Controller()
    c.current_library_name = "TVLib"
    c.cached_library_data = {
        "ShowA": {
            "metadata": {"tmdb_identifier": "111", "locked_metadata": False},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": "/tv/S01E01.mkv",
                            "watched": False,
                            "tmdb_number": 1,
                            "date_added": 1000,
                            "air_date": "2021-01-01",
                            "runtime": 45,
                        }
                    ]
                }
            },
        }
    }
    c.selected_series_name = "ShowA"
    config.libraries = {"TVLib": {"type": "tv", "paths": ["/tv"]}}
    return c


@pytest.fixture
def ctrl_movie(mock_db_save):
    c = Controller()
    c.current_library_name = "MovieLib"
    c.cached_library_data = {
        "Film": {
            "path": "/movies/Film.mkv",
            "tmdb_identifier": "999",
            "locked_metadata": False,
            "watched": False,
        }
    }
    c.selected_series_name = "Film"
    config.libraries = {"MovieLib": {"type": "movie", "paths": ["/movies"]}}
    return c


# ---------------------------------------------------------------------------
# apply_jellyfin_watch_match
# ---------------------------------------------------------------------------


def test_apply_jellyfin_watch_match_tv(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save
    received: List[str] = []
    ctrl_tv.series_selected.connect(received.append)

    ctrl_tv.apply_jellyfin_watch_match("ShowA", {"id": "jelly-001"})

    assert (
        ctrl_tv.cached_library_data["ShowA"]["metadata"]["jellyfin_id"] == "jelly-001"
    )
    mock_save.assert_called_once()
    assert "ShowA" in received


def test_apply_jellyfin_watch_match_movie(ctrl_movie, mock_db_save) -> None:
    _, mock_movie_save = mock_db_save
    received: List[str] = []
    ctrl_movie.movie_selected.connect(received.append)

    ctrl_movie.apply_jellyfin_watch_match("Film", {"id": "jelly-film-222"})

    assert ctrl_movie.cached_library_data["Film"]["jellyfin_id"] == "jelly-film-222"
    mock_movie_save.assert_called_once()
    assert "Film" in received


def test_apply_jellyfin_watch_match_unknown_series(ctrl_tv) -> None:
    """Should return early without crashing."""
    ctrl_tv.apply_jellyfin_watch_match("Unknown", {"id": "jelly-xyz"})  # No crash


# ---------------------------------------------------------------------------
# apply_episode_metadata_match
# ---------------------------------------------------------------------------


def test_apply_episode_metadata_match_found(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save
    received: List[str] = []
    ctrl_tv.series_selected.connect(received.append)

    ctrl_tv.apply_episode_metadata_match(
        "ShowA",
        "/tv/S01E01.mkv",
        {
            "id": "ep-tmdb-999",
            "name": "The Pilot",
            "episode_number": 1,
            "air_date": "2021-01-01",
            "runtime": 50,
        },
    )

    ep = ctrl_tv.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0]
    assert ep["tmdb_name"] == "The Pilot"
    assert ep["tmdb_number"] == 1
    assert ep["runtime"] == 50
    mock_save.assert_called_once()
    assert "ShowA" in received


def test_apply_episode_metadata_match_not_found_path(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save
    ctrl_tv.apply_episode_metadata_match(
        "ShowA", "/nonexistent/path.mkv", {"id": "whatever"}
    )
    mock_save.assert_not_called()


def test_apply_episode_metadata_match_unknown_series(ctrl_tv) -> None:
    ctrl_tv.apply_episode_metadata_match("Unknown", "/tv/S01E01.mkv", {"id": "xyz"})


# ---------------------------------------------------------------------------
# update_episode_metadata
# ---------------------------------------------------------------------------


def test_update_episode_metadata(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save
    ctrl_tv.update_episode_metadata(
        "ShowA", "/tv/S01E01.mkv", {"custom_tag": "special"}
    )
    ep = ctrl_tv.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0]
    assert ep["custom_tag"] == "special"
    mock_save.assert_called_once()


def test_update_episode_metadata_unknown_series(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save
    ctrl_tv.update_episode_metadata("Unknown", "/tv/X.mkv", {"foo": "bar"})
    mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# trigger_series_refresh
# ---------------------------------------------------------------------------


def test_trigger_series_refresh_no_library() -> None:
    c = Controller()
    c.current_library_name = ""
    statuses: List[str] = []
    c.status_changed.connect(statuses.append)

    with patch("lan_streamer.backend.RefreshSeriesWorker") as mock_cls:
        c.trigger_series_refresh("ShowA")
        mock_cls.assert_not_called()
    assert any("Select a library" in s for s in statuses)


def test_trigger_series_refresh_worker_already_running() -> None:
    c = Controller()
    c.current_library_name = "TVLib"
    config.libraries["TVLib"] = {"type": "tv", "paths": []}

    mock_worker = MagicMock()
    mock_worker._is_async_worker = True
    c.worker_manager.scan._instance = mock_worker

    statuses: List[str] = []
    c.status_changed.connect(statuses.append)

    with patch("lan_streamer.backend.RefreshSeriesWorker") as mock_cls:
        c.trigger_series_refresh("ShowA")
        mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# _on_refresh_finished
# ---------------------------------------------------------------------------


def test_on_refresh_finished_same_library(ctrl_tv, mock_db_save) -> None:
    updated_lib = {"ShowA": {"metadata": {}, "seasons": {}}}
    mock_refresh = MagicMock()
    mock_refresh.library_name = "TVLib"
    ctrl_tv.worker_manager.refresh._instance = mock_refresh

    signals: List[bool] = []
    ctrl_tv.library_loaded.connect(lambda: signals.append(True))
    ctrl_tv._on_refresh_finished(updated_lib)
    assert ctrl_tv.cached_library_data == updated_lib
    assert len(signals) == 1


def test_on_refresh_finished_different_library(ctrl_tv, mock_db_save) -> None:
    updated_lib = {"ShowA": {"metadata": {}, "seasons": {}}}
    mock_refresh = MagicMock()
    mock_refresh.library_name = "OtherLib"
    mock_refresh.item_name = "ShowA"
    ctrl_tv.worker_manager.refresh._instance = mock_refresh

    statuses: List[str] = []
    ctrl_tv.status_changed.connect(statuses.append)

    signals: List[bool] = []
    ctrl_tv.library_loaded.connect(lambda: signals.append(True))

    ctrl_tv._on_refresh_finished(updated_lib)
    assert len(signals) == 0
    assert any("Background refresh" in s for s in statuses)


# ---------------------------------------------------------------------------
# merge_subtitles
# ---------------------------------------------------------------------------


def test_merge_subtitles_starts_worker(ctrl_tv) -> None:
    with patch("lan_streamer.backend.SubtitleMergeWorker") as mock_cls:
        ctrl_tv.merge_subtitles("/video.mkv", ["/sub.srt"])
        mock_cls.assert_called_once_with(
            "/video.mkv", ["/sub.srt"], async_task_manager=ANY
        )
        mock_cls.return_value.start.assert_called_once()


def test_merge_subtitles_skips_if_running(ctrl_tv) -> None:
    mock_worker = MagicMock()
    mock_worker._is_async_worker = True
    ctrl_tv.worker_manager.subtitle_merge._instance = mock_worker

    statuses: List[str] = []
    ctrl_tv.status_changed.connect(statuses.append)

    with patch("lan_streamer.backend.SubtitleMergeWorker") as mock_cls:
        ctrl_tv.merge_subtitles("/video.mkv", ["/sub.srt"])
        mock_cls.assert_not_called()
    assert any("already in progress" in s for s in statuses)


# ---------------------------------------------------------------------------
# embed_metadata
# ---------------------------------------------------------------------------


def test_embed_metadata_starts_worker(ctrl_tv) -> None:
    with patch("lan_streamer.backend.MetadataEmbedWorker") as mock_cls:
        ctrl_tv.embed_metadata("/video.mkv", {"title": "Test"})
        mock_cls.assert_called_once()
        mock_cls.return_value.start.assert_called_once()


def test_embed_metadata_skips_if_running(ctrl_tv) -> None:
    mock_worker = MagicMock()
    mock_worker._is_async_worker = True
    ctrl_tv.worker_manager.metadata_embed._instance = mock_worker

    statuses: List[str] = []
    ctrl_tv.status_changed.connect(statuses.append)

    with patch("lan_streamer.backend.MetadataEmbedWorker") as mock_cls:
        ctrl_tv.embed_metadata("/video.mkv", {"title": "Test"})
        mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# embed_metadata_series
# ---------------------------------------------------------------------------


def test_embed_metadata_series_starts_worker(ctrl_tv) -> None:
    with patch("lan_streamer.backend.SeriesMetadataEmbedWorker") as mock_cls:
        ctrl_tv.embed_metadata_series("ShowA")
        mock_cls.assert_called_once()
        mock_cls.return_value.start.assert_called_once()


def test_embed_metadata_series_no_episodes(ctrl_tv) -> None:
    ctrl_tv.cached_library_data["EmptyShow"] = {
        "metadata": {},
        "seasons": {"S1": {"episodes": []}},
    }
    statuses: List[str] = []
    ctrl_tv.status_changed.connect(statuses.append)

    with patch("lan_streamer.backend.SeriesMetadataEmbedWorker") as mock_cls:
        ctrl_tv.embed_metadata_series("EmptyShow")
        mock_cls.assert_not_called()
    assert any("No episodes" in s for s in statuses)


def test_embed_metadata_series_unknown_series(ctrl_tv) -> None:
    with patch("lan_streamer.backend.SeriesMetadataEmbedWorker") as mock_cls:
        ctrl_tv.embed_metadata_series("NonExistent")
        mock_cls.assert_not_called()


def test_embed_metadata_series_skips_if_running(ctrl_tv) -> None:
    mock_worker = MagicMock()
    mock_worker._is_async_worker = True
    ctrl_tv.worker_manager.metadata_embed._instance = mock_worker

    statuses: List[str] = []
    ctrl_tv.status_changed.connect(statuses.append)

    with patch("lan_streamer.backend.SeriesMetadataEmbedWorker") as mock_cls:
        ctrl_tv.embed_metadata_series("ShowA")
        mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# update_series_name
# ---------------------------------------------------------------------------


def test_update_series_name_renames_and_emits(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save
    received: List[str] = []
    ctrl_tv.series_selected.connect(received.append)

    ctrl_tv.update_series_name("ShowA", "ShowRenamed")

    assert "ShowRenamed" in ctrl_tv.cached_library_data
    assert "ShowA" not in ctrl_tv.cached_library_data
    mock_save.assert_called_once()
    assert "ShowRenamed" in received


def test_update_series_name_unknown_old_name(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save
    ctrl_tv.update_series_name("NonExistent", "NewName")
    mock_save.assert_not_called()


def test_update_series_name_empty_new_name(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save
    ctrl_tv.update_series_name("ShowA", "")
    mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# apply_rename_batch
# ---------------------------------------------------------------------------


def test_apply_rename_batch_updates_paths(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save

    preview_results = [
        {
            "old_path": "/tv/S01E01.mkv",
            "new_path": "/tv/ShowA_S01E01_renamed.mkv",
        }
    ]

    with patch("lan_streamer.scanner.renamer.perform_rename") as mock_rename:
        # Simulate the rename callback
        def fake_rename(results, callback):
            for item in results:
                callback(item["old_path"], item["new_path"])

        mock_rename.side_effect = fake_rename
        ctrl_tv.apply_rename_batch(preview_results)

    ep = ctrl_tv.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0]
    assert ep["path"] == "/tv/ShowA_S01E01_renamed.mkv"
    mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# set_video_playing
# ---------------------------------------------------------------------------


def test_set_video_playing_true(ctrl_tv) -> None:
    ctrl_tv.set_video_playing(True)
    assert ctrl_tv.is_video_playing is True


def test_set_video_playing_false_emits_library_loaded(ctrl_tv) -> None:
    ctrl_tv.is_video_playing = True
    signals: List[bool] = []
    ctrl_tv.library_loaded.connect(lambda: signals.append(True))

    ctrl_tv.set_video_playing(False)
    assert len(signals) == 1


def test_set_video_playing_false_emits_series_selected(ctrl_tv) -> None:
    ctrl_tv.is_video_playing = True
    received: List[str] = []
    ctrl_tv.series_selected.connect(received.append)

    ctrl_tv.set_video_playing(False)
    assert "ShowA" in received


def test_set_video_playing_false_emits_movie_selected(ctrl_movie) -> None:
    ctrl_movie.is_video_playing = True
    received: List[str] = []
    ctrl_movie.movie_selected.connect(received.append)

    ctrl_movie.set_video_playing(False)
    assert "Film" in received


def test_set_video_playing_false_no_selected(ctrl_tv) -> None:
    ctrl_tv.is_video_playing = True
    ctrl_tv.selected_series_name = ""
    signals: List[bool] = []
    ctrl_tv.library_loaded.connect(lambda: signals.append(True))

    ctrl_tv.set_video_playing(False)
    assert len(signals) == 1  # library_loaded still emitted


# ---------------------------------------------------------------------------
# delete_series / delete_episode — error handling
# ---------------------------------------------------------------------------


def test_delete_series_handles_exception(ctrl_tv) -> None:
    with patch(
        "lan_streamer.db.delete_series_record", side_effect=RuntimeError("DB fail")
    ):
        with patch.object(ctrl_tv, "select_library") as mock_select:
            ctrl_tv.delete_series("ShowA")  # Should not raise
            mock_select.assert_called_once_with("TVLib", reset_selection=True)


def test_delete_episode_handles_exception(ctrl_tv) -> None:
    with patch(
        "lan_streamer.db.delete_episode_record", side_effect=RuntimeError("DB fail")
    ):
        with patch.object(ctrl_tv, "select_library") as mock_select:
            ctrl_tv.delete_episode("/tv/S01E01.mkv")  # Should not raise
            mock_select.assert_called_once_with("TVLib", reset_selection=False)


def test_delete_series_no_library() -> None:
    c = Controller()
    c.current_library_name = ""
    with patch("lan_streamer.db.delete_series_record") as mock_delete:
        c.delete_series("ShowA")
        mock_delete.assert_not_called()


# ---------------------------------------------------------------------------
# trigger_series_scan
# ---------------------------------------------------------------------------


def test_trigger_series_scan_no_library() -> None:
    c = Controller()
    c.current_library_name = ""
    statuses: List[str] = []
    c.status_changed.connect(statuses.append)

    with patch("lan_streamer.backend.ScanSingleSeriesWorker") as mock_cls:
        c.trigger_series_scan("ShowA")
        mock_cls.assert_not_called()
    assert any("Select a library" in s for s in statuses)


def test_trigger_series_scan_worker_already_running() -> None:
    c = Controller()
    c.current_library_name = "TVLib"
    config.libraries["TVLib"] = {"type": "tv", "paths": []}

    mock_worker = MagicMock()
    mock_worker._is_async_worker = True
    c.worker_manager.scan._instance = mock_worker

    statuses: List[str] = []
    c.status_changed.connect(statuses.append)

    with patch("lan_streamer.backend.ScanSingleSeriesWorker") as mock_cls:
        c.trigger_series_scan("ShowA")
        mock_cls.assert_not_called()


def test_on_series_scan_finished_same_library(ctrl_tv, mock_db_save) -> None:
    updated_library = {"ShowA": {"metadata": {}, "seasons": {}}}
    mock_scan = MagicMock()
    mock_scan.library_name = "TVLib"
    ctrl_tv.worker_manager.scan_series._instance = mock_scan

    signals: List[bool] = []
    ctrl_tv.library_loaded.connect(lambda: signals.append(True))
    ctrl_tv._on_series_scan_finished(updated_library)
    assert ctrl_tv.cached_library_data == updated_library
    assert len(signals) == 1


def test_on_series_scan_finished_different_library(ctrl_tv, mock_db_save) -> None:
    updated_library = {"ShowA": {"metadata": {}, "seasons": {}}}
    mock_scan = MagicMock()
    mock_scan.library_name = "OtherLib"
    mock_scan.series_name = "ShowA"
    ctrl_tv.worker_manager.scan_series._instance = mock_scan

    signals: List[bool] = []
    ctrl_tv.library_loaded.connect(lambda: signals.append(True))
    ctrl_tv._on_series_scan_finished(updated_library)
    assert ctrl_tv.cached_library_data != updated_library
    assert len(signals) == 0
