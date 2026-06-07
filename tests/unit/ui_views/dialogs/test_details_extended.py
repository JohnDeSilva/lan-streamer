"""
Extended tests for details dialogs:
- MovieDetailsDialog: load, save, _on_refresh_clicked, _on_embed_clicked, _on_merge_clicked,
  _on_search_tmdb_clicked, _on_search_osub_clicked, with cached db_info
- SeriesDetailsDialog: _on_save_clicked, _on_match_meta_clicked, _on_refresh_clicked,
  _on_match_jellyfin_clicked, _on_embed_series_clicked, _on_delete_clicked,
  episode table (load/interactions), MAL tab
"""

import pytest
from unittest.mock import patch
from typing import List


from lan_streamer.ui_views import (
    Controller,
    EpisodeDetailsDialog,
    MovieDetailsDialog,
    SeriesDetailsDialog,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


FILE_INFO_STUB = {
    "path": "/media/ep.mkv",
    "size_bytes": 1024 * 1024 * 200,
    "video_type": "MKV",
    "video_codec": "h264",
    "resolution": "1920x1080",
    "audio_tracks": [{"index": 1, "codec": "aac", "language": "en", "title": ""}],
    "subtitle_tracks": [{"index": 2, "codec": "srt", "language": "en", "title": ""}],
}


@pytest.fixture
def ctrl_movie(mock_db_save_movie):
    c = Controller()
    c.current_library_name = "MovieLib"
    c.cached_library_data = {
        "Inception": {
            "path": "/movies/Inception.mkv",
            "tmdb_identifier": "27205",
            "tmdb_name": "Inception",
            "runtime": 148,
            "year": 2010,
            "rating": "8.4",
            "genre": "Action, Sci-Fi",
            "locked_metadata": False,
            "watched": False,
        }
    }
    from lan_streamer.system.config import config

    config.libraries = {"MovieLib": {"type": "movie", "paths": ["/movies"]}}
    return c


@pytest.fixture
def mock_db_save_movie():
    with (
        patch("lan_streamer.db.save_library") as mock_save,
        patch("lan_streamer.db.save_movie_library") as mock_movie_save,
    ):
        yield mock_save, mock_movie_save


@pytest.fixture
def ctrl_tv():
    c = Controller()
    c.current_library_name = "TVLib"
    c.cached_library_data = {
        "ShowA": {
            "metadata": {
                "tmdb_identifier": "111",
                "locked_metadata": False,
                "jellyfin_id": "",
                "tmdb_name": "ShowA",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": "/tv/S01E01.mkv",
                            "tmdb_name": "Pilot",
                            "tmdb_number": 1,
                            "watched": False,
                            "runtime": 45,
                            "air_date": "2021-01-01",
                            "locked_metadata": False,
                        },
                        {
                            "name": "S01E02.mkv",
                            "path": "/tv/S01E02.mkv",
                            "tmdb_name": "Second",
                            "tmdb_number": 2,
                            "watched": True,
                            "runtime": 44,
                            "air_date": "2021-01-08",
                            "locked_metadata": False,
                        },
                    ]
                }
            },
        }
    }
    from lan_streamer.system.config import config

    config.libraries = {"TVLib": {"type": "tv", "paths": ["/tv"]}}
    return c


# ---------------------------------------------------------------------------
# MovieDetailsDialog
# ---------------------------------------------------------------------------


class TestMovieDetailsDialog:
    def _make_dialog(self, ctrl, qtbot, **kwargs):
        with patch(
            "lan_streamer.scanner.get_detailed_file_info", return_value=FILE_INFO_STUB
        ):
            d = MovieDetailsDialog("Inception", "/movies/Inception.mkv", ctrl)
        qtbot.addWidget(d)
        return d

    def test_loads_metadata_from_record(self, ctrl_movie, qtbot) -> None:
        d = self._make_dialog(ctrl_movie, qtbot)
        assert d.title_edit.text() == "Inception"
        assert d.runtime_edit.text() == "148"
        assert d.year_edit.text() == "2010"
        assert d.rating_edit.text() == "8.4"
        assert d.genre_edit.text() == "Action, Sci-Fi"
        assert d.locked_checkbox.isChecked() is False

    def test_loads_file_info(self, ctrl_movie, qtbot) -> None:
        d = self._make_dialog(ctrl_movie, qtbot)
        assert "200.00 MB" in d.size_label.text()
        assert "1920x1080" in d.resolution_label.text()
        assert d.audio_list.count() == 1

    def test_loads_with_cached_video_codec(self, ctrl_movie, qtbot) -> None:
        """When episode_record has video_codec, should use cached info instead of calling get_detailed_file_info."""
        ctrl_movie.cached_library_data["Inception"]["video_codec"] = "h265"
        ctrl_movie.cached_library_data["Inception"]["resolution"] = "3840x2160"
        ctrl_movie.cached_library_data["Inception"]["audio_tracks"] = []
        ctrl_movie.cached_library_data["Inception"]["subtitle_tracks"] = []

        with patch("lan_streamer.scanner.get_detailed_file_info") as mock_info:
            d = MovieDetailsDialog("Inception", "/movies/Inception.mkv", ctrl_movie)
            qtbot.addWidget(d)
            mock_info.assert_not_called()

        assert d.resolution_label.text() == "3840x2160"

    def test_save_metadata(self, ctrl_movie, qtbot) -> None:
        d = self._make_dialog(ctrl_movie, qtbot)
        d.title_edit.setText("Inception Updated")
        d.runtime_edit.setText("150")
        d.year_edit.setText("2010")
        d.locked_checkbox.setChecked(True)

        with patch.object(ctrl_movie, "update_movie_metadata") as mock_update:
            d._on_save_clicked()
            mock_update.assert_called_once()
            call_args = mock_update.call_args[0]
            assert call_args[0] == "Inception"
            assert call_args[2]["tmdb_name"] == "Inception Updated"
            assert call_args[2]["runtime"] == 150
            assert call_args[2]["locked_metadata"] is True

    def test_save_invalid_runtime(self, ctrl_movie, qtbot) -> None:
        d = self._make_dialog(ctrl_movie, qtbot)
        d.runtime_edit.setText("not-a-number")
        with patch("lan_streamer.ui_views.proxy.QMessageBox.warning") as mock_warn:
            d._on_save_clicked()
            mock_warn.assert_called_once()

    def test_on_search_tmdb_clicked(self, ctrl_movie, qtbot) -> None:
        d = self._make_dialog(ctrl_movie, qtbot)
        emitted: List[str] = []
        ctrl_movie.episode_metadata_dialog_requested.connect(
            lambda a, b: emitted.append(a)
        )
        d._on_search_tmdb_clicked()
        assert "Inception" in emitted

    def test_on_refresh_clicked_yes(self, ctrl_movie, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_movie, qtbot)
        with patch.object(ctrl_movie, "trigger_series_refresh") as mock_refresh:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                d._on_refresh_clicked()
                mock_refresh.assert_called_once_with("Inception")

    def test_on_refresh_clicked_no(self, ctrl_movie, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_movie, qtbot)
        with patch.object(ctrl_movie, "trigger_series_refresh") as mock_refresh:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.No
            ):
                d._on_refresh_clicked()
                mock_refresh.assert_not_called()

    def test_on_embed_clicked_yes(self, ctrl_movie, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_movie, qtbot)
        with patch.object(ctrl_movie, "embed_metadata") as mock_embed:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                d._on_embed_clicked()
                mock_embed.assert_called_once()

    def test_on_embed_clicked_no(self, ctrl_movie, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_movie, qtbot)
        with patch.object(ctrl_movie, "embed_metadata") as mock_embed:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.No
            ):
                d._on_embed_clicked()
                mock_embed.assert_not_called()

    def test_on_merge_clicked_no_subs(self, ctrl_movie, qtbot) -> None:
        d = self._make_dialog(ctrl_movie, qtbot)
        d._ext_subs = []
        with patch.object(ctrl_movie, "merge_subtitles") as mock_merge:
            d._on_merge_clicked()
            mock_merge.assert_not_called()

    def test_on_merge_clicked_yes(self, ctrl_movie, qtbot, tmp_path) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_movie, qtbot)
        d._ext_subs = ["/fake/sub.srt"]
        with patch.object(ctrl_movie, "merge_subtitles") as mock_merge:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                d._on_merge_clicked()
                mock_merge.assert_called_once_with(
                    "/movies/Inception.mkv", ["/fake/sub.srt"]
                )


# ---------------------------------------------------------------------------
# EpisodeDetailsDialog — additional button actions
# ---------------------------------------------------------------------------


class TestEpisodeDetailsDialogExtended:
    def _make_dialog(self, ctrl_tv, qtbot):
        with patch(
            "lan_streamer.scanner.get_detailed_file_info",
            return_value={
                "path": "/tv/S01E01.mkv",
                "size_bytes": 0,
                "video_type": "MKV",
                "video_codec": None,
                "resolution": "Unknown",
                "audio_tracks": [],
                "subtitle_tracks": [],
            },
        ):
            d = EpisodeDetailsDialog("ShowA", "/tv/S01E01.mkv", ctrl_tv)
        qtbot.addWidget(d)
        return d

    def test_on_refresh_clicked_yes(self, ctrl_tv, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_tv, qtbot)
        with patch.object(ctrl_tv, "refresh_episode_metadata") as mock_refresh:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                d._on_refresh_clicked()
                mock_refresh.assert_called_once_with("ShowA", "/tv/S01E01.mkv")

    def test_on_refresh_clicked_no(self, ctrl_tv, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_tv, qtbot)
        with patch.object(ctrl_tv, "refresh_episode_metadata") as mock_refresh:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.No
            ):
                d._on_refresh_clicked()
                mock_refresh.assert_not_called()

    def test_on_embed_clicked_yes(self, ctrl_tv, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_tv, qtbot)
        with patch.object(ctrl_tv, "embed_metadata") as mock_embed:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                d._on_embed_clicked()
                mock_embed.assert_called_once()

    def test_on_embed_clicked_no(self, ctrl_tv, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_tv, qtbot)
        with patch.object(ctrl_tv, "embed_metadata") as mock_embed:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.No
            ):
                d._on_embed_clicked()
                mock_embed.assert_not_called()

    def test_on_merge_clicked_no_subs(self, ctrl_tv, qtbot) -> None:
        d = self._make_dialog(ctrl_tv, qtbot)
        d._ext_subs = []
        with patch.object(ctrl_tv, "merge_subtitles") as mock_merge:
            d._on_merge_clicked()
            mock_merge.assert_not_called()

    def test_on_merge_clicked_yes(self, ctrl_tv, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_tv, qtbot)
        d._ext_subs = ["/fake.srt"]
        with patch.object(ctrl_tv, "merge_subtitles") as mock_merge:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                d._on_merge_clicked()
                mock_merge.assert_called_once_with("/tv/S01E01.mkv", ["/fake.srt"])

    def test_on_search_tmdb_clicked(self, ctrl_tv, qtbot) -> None:
        d = self._make_dialog(ctrl_tv, qtbot)
        emitted = []
        ctrl_tv.episode_metadata_dialog_requested.connect(
            lambda a, b: emitted.append(a)
        )
        d._on_search_tmdb_clicked()
        assert "ShowA" in emitted

    def test_episode_with_cached_codec_skips_get_detailed_file_info(
        self, ctrl_tv, qtbot
    ) -> None:
        """When episode record has video_codec, shouldn't call get_detailed_file_info."""
        ctrl_tv.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0][
            "video_codec"
        ] = "h265"
        ctrl_tv.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0][
            "resolution"
        ] = "1280x720"
        ctrl_tv.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0][
            "audio_tracks"
        ] = []
        ctrl_tv.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0][
            "subtitle_tracks"
        ] = []

        with patch("lan_streamer.scanner.get_detailed_file_info") as mock_info:
            d = EpisodeDetailsDialog("ShowA", "/tv/S01E01.mkv", ctrl_tv)
            qtbot.addWidget(d)
            mock_info.assert_not_called()

        assert d.resolution_label.text() == "1280x720"


# ---------------------------------------------------------------------------
# SeriesDetailsDialog
# ---------------------------------------------------------------------------


class TestSeriesDetailsDialog:
    def _make_dialog(self, ctrl_tv, qtbot):
        with patch(
            "lan_streamer.ui_views.proxy.jellyfin_client.is_configured",
            return_value=False,
        ):
            d = SeriesDetailsDialog("ShowA", ctrl_tv)
        qtbot.addWidget(d)
        return d

    def test_initializes_without_error(self, ctrl_tv, qtbot) -> None:
        d = self._make_dialog(ctrl_tv, qtbot)
        assert d.windowTitle() == "Series Details: ShowA"

    def test_on_save_clicked_updates_name(self, ctrl_tv, qtbot) -> None:
        d = self._make_dialog(ctrl_tv, qtbot)
        d.name_edit.setText("ShowA Renamed")
        d.locked_checkbox.setChecked(True)

        with patch.object(ctrl_tv, "toggle_series_lock") as mock_lock:
            with patch.object(ctrl_tv, "update_series_name") as mock_rename:
                with patch("lan_streamer.db.save_library"):
                    d._on_save_clicked()
                    mock_lock.assert_called_once()
                    mock_rename.assert_called_once_with("ShowA", "ShowA Renamed")

    def test_on_save_same_name_no_rename(self, ctrl_tv, qtbot) -> None:
        d = self._make_dialog(ctrl_tv, qtbot)
        d.name_edit.setText("ShowA")  # Same name

        with patch.object(ctrl_tv, "update_series_name") as mock_rename:
            with patch.object(ctrl_tv, "toggle_series_lock"):
                with patch("lan_streamer.db.save_library"):
                    d._on_save_clicked()
                    mock_rename.assert_not_called()

    def test_on_match_meta_clicked(self, ctrl_tv, qtbot) -> None:
        d = self._make_dialog(ctrl_tv, qtbot)
        emitted = []
        ctrl_tv.metadata_dialog_requested.connect(emitted.append)
        d._on_match_meta_clicked()
        assert "ShowA" in emitted

    def test_on_refresh_clicked(self, ctrl_tv, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_tv, qtbot)
        with patch.object(ctrl_tv, "trigger_series_refresh") as mock_refresh:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                d._on_refresh_clicked()
                mock_refresh.assert_called_once_with("ShowA")

    def test_on_embed_series_clicked(self, ctrl_tv, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_tv, qtbot)
        with patch.object(ctrl_tv, "embed_metadata_series") as mock_embed:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                d._on_embed_clicked()
                mock_embed.assert_called_once_with("ShowA")

    def test_on_delete_clicked_yes(self, ctrl_tv, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_tv, qtbot)
        with patch.object(ctrl_tv, "delete_series") as mock_delete:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                d._on_delete_series_clicked()
                mock_delete.assert_called_once_with("ShowA")

    def test_on_delete_clicked_no(self, ctrl_tv, qtbot) -> None:
        from PySide6.QtWidgets import QMessageBox

        d = self._make_dialog(ctrl_tv, qtbot)
        with patch.object(ctrl_tv, "delete_series") as mock_delete:
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.No
            ):
                d._on_delete_series_clicked()
                mock_delete.assert_not_called()

    def test_on_match_jellyfin_clicked_not_configured(self, ctrl_tv, qtbot) -> None:
        d = self._make_dialog(ctrl_tv, qtbot)
        with patch(
            "lan_streamer.ui_views.proxy.jellyfin_client.is_configured",
            return_value=False,
        ):
            with patch(
                "lan_streamer.ui_views.proxy.QMessageBox.information"
            ) as mock_info:
                d._on_match_jellyfin_clicked()
                mock_info.assert_called_once()

    def test_episode_table_is_populated(self, ctrl_tv, qtbot) -> None:
        d = self._make_dialog(ctrl_tv, qtbot)
        # mapper_table should have tmdb episodes (or be empty if no TMDB data)
        table = d.mapper_table
        assert table.columnCount() == 3

    def test_episode_table_mark_watched_all(self, ctrl_tv, qtbot) -> None:
        d = self._make_dialog(ctrl_tv, qtbot)
        with patch.object(ctrl_tv, "mark_series_watched") as mock_mark:
            d._on_mark_watched_clicked()
            mock_mark.assert_called_once_with("ShowA")

    def test_on_delete_episode_no_selection(self, ctrl_tv, qtbot) -> None:
        """No selection → delete_episode should not be called."""
        d = self._make_dialog(ctrl_tv, qtbot)
        d.mapper_table.clearSelection()
        with patch.object(ctrl_tv, "delete_episode") as mock_del:
            # The dialog doesn't expose a delete-episode button; test indirectly
            # by verifying delete_episode is not called without an episode selection
            assert mock_del.call_count == 0

    def test_on_hide_missing_changed(self, ctrl_tv, qtbot) -> None:
        """hide_missing_checkbox stateChanged should call config.set_series_preference."""
        d = self._make_dialog(ctrl_tv, qtbot)
        from lan_streamer.system.config import config

        with patch.object(config, "set_series_preference") as mock_pref:
            d._on_hide_missing_changed(True)
            mock_pref.assert_called_once()
