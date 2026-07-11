"""Tests targeting uncovered lines in episode_details.py (lines 242, 270,
278-280, 300, 310, 318-319, 328, 338, 341-342, 345-346, 355-358, 367-370,
387-394, 406-408, 419-424, 430-434, 527-535)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from lan_streamer.ui_views.dialogs.episode_details import EpisodeDetailsDialog


@pytest.fixture(scope="module", autouse=True)
def qapp():
    """Ensure a QApplication exists for widget tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def mock_controller():
    ctrl = MagicMock()
    ctrl.cached_library_data = {}
    ctrl.update_episode_metadata = MagicMock()
    ctrl.refresh_episode_metadata = MagicMock()
    ctrl.episode_metadata_dialog_requested = MagicMock()
    ctrl.embed_metadata = MagicMock()
    ctrl.merge_subtitles = MagicMock()
    ctrl.delete_episode = MagicMock()
    return ctrl


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_episode_record(**overrides):
    base = {
        "path": "/media/tv/Test Show/Season 1/S01E01.mkv",
        "name": "Pilot",
        "tmdb_name": "Pilot",
        "tmdb_number": 1,
        "air_date": "2020-01-01",
        "runtime": 45,
        "video_codec": "h264",
        "resolution": "1920x1080",
        "bit_rate": 5000000,
        "file_runtime": 45,
        "audio_tracks": [
            {"index": 0, "codec": "aac", "language": "eng", "title": "English"}
        ],
        "subtitle_tracks": [
            {"index": 1, "codec": "srt", "language": "eng", "title": "English"}
        ],
    }
    base.update(overrides)
    return base


def _make_series_data(episode_record):
    return {
        "Test Show": {
            "metadata": {"tmdb_identifier": "12345"},
            "seasons": {
                "Season 1": {"episodes": [episode_record]},
            },
        }
    }


DEFAULT_FILE_INFO = {
    "video_codec": "h264",
    "resolution": "1920x1080",
    "bit_rate": 5000000,
    "size_bytes": 1024,
    "video_type": "Matroska",
    "runtime": 45,
    "audio_tracks": [
        {"index": 0, "codec": "aac", "language": "eng", "title": "English"}
    ],
    "subtitle_tracks": [
        {"index": 1, "codec": "srt", "language": "eng", "title": "English"}
    ],
}


def _build_dialog(mock_controller, episode_record, tmp_path, file_info=None):
    """Build an EpisodeDetailsDialog with all necessary patches.

    ``get_detailed_file_info`` is lazily imported inside
    ``_on_default_file_changed`` (``from lan_streamer.scanner import
    get_detailed_file_info``), so the correct patch target is the
    ``lan_streamer.scanner`` module namespace, not the
    ``episode_details`` module.
    """
    if file_info is None:
        file_info = dict(DEFAULT_FILE_INFO)

    fake_path = tmp_path / Path(episode_record["path"]).name
    fake_path.write_bytes(b"\x00" * 1024)

    patched_record = dict(episode_record)
    patched_record["path"] = str(fake_path)
    mock_controller.cached_library_data = _make_series_data(patched_record)

    with (
        patch(
            "lan_streamer.scanner.get_detailed_file_info",
            return_value=file_info,
        ),
        patch(
            "lan_streamer.scanner.SUBTITLE_EXTENSIONS",
            {".srt", ".ass", ".vtt"},
        ),
    ):
        dialog = EpisodeDetailsDialog(
            "Test Show",
            str(fake_path),
            mock_controller,
        )

    return dialog, fake_path


def _build_dialog_with_versions(
    mock_controller, episode_record, tmp_path, versions, file_info=None
):
    """Build a dialog where the episode has explicit versions.

    This ensures ``_on_default_file_changed`` finds the version in the
    versions list (lines 278-280) instead of falling back to DB info.
    """
    if file_info is None:
        file_info = dict(DEFAULT_FILE_INFO)

    fake_path = tmp_path / Path(episode_record["path"]).name
    fake_path.write_bytes(b"\x00" * 1024)

    patched_record = dict(episode_record)
    patched_record["path"] = str(fake_path)
    patched_record["versions"] = versions
    mock_controller.cached_library_data = _make_series_data(patched_record)

    with (
        patch(
            "lan_streamer.scanner.get_detailed_file_info",
            return_value=file_info,
        ),
        patch(
            "lan_streamer.scanner.SUBTITLE_EXTENSIONS",
            {".srt", ".ass", ".vtt"},
        ),
    ):
        dialog = EpisodeDetailsDialog(
            "Test Show",
            str(fake_path),
            mock_controller,
        )

    return dialog, fake_path


# ------------------------------------------------------------------
# 1. _refresh_file_info: version with no path -> continue (line 242)
# ------------------------------------------------------------------


class TestRefreshFileInfoVersionWithoutPath:
    def test_skips_version_with_no_path(self, mock_controller, tmp_path):
        ep = _make_episode_record(
            versions=[
                {"path": None, "video_codec": "h264", "resolution": "1920x1080"},
                {
                    "path": "/media/tv/Test Show/Season 1/S01E01.mkv",
                    "video_codec": "h264",
                    "resolution": "1920x1080",
                },
            ]
        )
        dialog, _ = _build_dialog(mock_controller, ep, tmp_path)

        combo_count = dialog.default_file_combo.count()
        assert combo_count == 1


# ------------------------------------------------------------------
# 2. _on_default_file_changed: empty path -> return (line 270)
# ------------------------------------------------------------------


class TestOnDefaultFileChangedEmptyPath:
    def test_returns_early_when_no_path_data(self, mock_controller, tmp_path):
        ep = _make_episode_record()
        dialog, _ = _build_dialog(mock_controller, ep, tmp_path)

        dialog.default_file_combo.clear()
        dialog.default_file_combo.setCurrentIndex(-1)

        dialog._on_default_file_changed()


# ------------------------------------------------------------------
# 3. _on_default_file_changed: version found in list (lines 278-280)
# ------------------------------------------------------------------


class TestOnDefaultFileChangedVersionFound:
    def test_uses_version_info_when_path_matches(self, mock_controller, tmp_path):
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)
        version_info = {
            "path": str(fake_path),
            "video_codec": "hevc",
            "resolution": "3840x2160",
            "bit_rate": 10000000,
            "audio_tracks": [],
            "subtitle_tracks": [],
            "runtime": 50,
        }
        ep = _make_episode_record(versions=[version_info])

        mock_controller.cached_library_data = _make_series_data(ep)

        with (
            patch(
                "lan_streamer.scanner.get_detailed_file_info", return_value=version_info
            ),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        assert dialog.codec_label.text() == "hevc"
        assert dialog.resolution_label.text() == "3840x2160"


# ------------------------------------------------------------------
# 4. safe_str: returns default for Mock objects (line 300)
# ------------------------------------------------------------------


class TestSafeStrForMock:
    def test_safe_str_returns_default_for_mock(self, mock_controller, tmp_path):
        ep = _make_episode_record()
        dialog, fake_path = _build_dialog(mock_controller, ep, tmp_path)

        mock_info = {
            "video_type": MagicMock(),
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 0,
            "audio_tracks": [],
            "subtitle_tracks": [],
            "runtime": None,
        }
        with patch(
            "lan_streamer.scanner.get_detailed_file_info",
            return_value=mock_info,
        ):
            dialog._on_default_file_changed()

        assert dialog.type_label.text() == "MKV"


# ------------------------------------------------------------------
# 5. _on_default_file_changed: size_bytes is Mock -> 0 (line 310)
# ------------------------------------------------------------------


class TestOnDefaultFileSizeBytesMock:
    def test_sets_size_to_zero_when_size_bytes_is_mock(self, mock_controller, tmp_path):
        ep = _make_episode_record()
        dialog, fake_path = _build_dialog(mock_controller, ep, tmp_path)

        mock_info = {
            "size_bytes": MagicMock(),
            "video_type": "mkv",
            "video_codec": "h264",
            "resolution": "1080p",
            "runtime": 45,
            "bit_rate": 5000000,
            "audio_tracks": [],
            "subtitle_tracks": [],
        }
        with patch(
            "lan_streamer.scanner.get_detailed_file_info",
            return_value=mock_info,
        ):
            dialog._on_default_file_changed()

        assert "0.00 MB" in dialog.size_label.text()


# ------------------------------------------------------------------
# 6. _on_default_file_changed: size_mb conversion exception (lines 318-319)
# ------------------------------------------------------------------


class TestOnDefaultFileSizeConversionError:
    def test_falls_back_to_zero_on_conversion_error(self, mock_controller, tmp_path):
        ep = _make_episode_record()
        dialog, fake_path = _build_dialog(mock_controller, ep, tmp_path)

        bad_info = {
            "size_bytes": "not_a_number",
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 0,
            "audio_tracks": [],
            "subtitle_tracks": [],
            "runtime": None,
        }
        with patch(
            "lan_streamer.scanner.get_detailed_file_info",
            return_value=bad_info,
        ):
            dialog._on_default_file_changed()

        assert "0.00 MB" in dialog.size_label.text()


# ------------------------------------------------------------------
# 7. _on_default_file_changed: file_runtime present -> shows value (line 328)
# ------------------------------------------------------------------


class TestOnDefaultFileRuntime:
    def test_shows_runtime_when_present(self, mock_controller, tmp_path):
        """Line 328: file_runtime_label shows runtime value when present."""
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)

        version = {
            "path": str(fake_path),
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 0,
            "audio_tracks": [],
            "subtitle_tracks": [],
            "runtime": 42,
        }
        _make_episode_record(versions=[version])

        with (
            patch("lan_streamer.scanner.get_detailed_file_info", return_value=version),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        assert dialog.file_runtime_label.text() == "42 min"

    def test_shows_unknown_when_no_runtime(self, mock_controller, tmp_path):
        """Line 330: file_runtime_label shows 'Unknown' when no runtime."""
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)

        version = {
            "path": str(fake_path),
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 0,
            "audio_tracks": [],
            "subtitle_tracks": [],
            "runtime": None,
        }
        _make_episode_record(versions=[version])

        with (
            patch("lan_streamer.scanner.get_detailed_file_info", return_value=version),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        assert dialog.file_runtime_label.text() == "Unknown"


# ------------------------------------------------------------------
# 8. _on_default_file_changed: bit_rate is Mock -> 0 (line 338)
# ------------------------------------------------------------------


class TestOnDefaultBitRateMock:
    def test_sets_bitrate_to_zero_when_mock(self, mock_controller, tmp_path):
        """Line 338: Mock bit_rate is coerced to 0, label shows 'Unknown'."""
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)

        version = {
            "path": str(fake_path),
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": MagicMock(),
            "audio_tracks": [],
            "subtitle_tracks": [],
            "runtime": None,
        }
        _make_episode_record(versions=[version])

        with (
            patch("lan_streamer.scanner.get_detailed_file_info", return_value=version),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        assert dialog.bit_rate_label.text() == "Unknown"


# ------------------------------------------------------------------
# 9. _on_default_file_changed: bit_rate conversion exception (lines 341-342)
# ------------------------------------------------------------------


class TestOnDefaultBitRateConversionError:
    def test_falls_back_to_zero_on_int_conversion_error(
        self, mock_controller, tmp_path
    ):
        """Lines 341-342: Non-numeric bit_rate falls back to 0."""
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)

        version = {
            "path": str(fake_path),
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": "invalid",
            "audio_tracks": [],
            "subtitle_tracks": [],
            "runtime": None,
        }
        _make_episode_record(versions=[version])

        with (
            patch("lan_streamer.scanner.get_detailed_file_info", return_value=version),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        assert dialog.bit_rate_label.text() == "Unknown"


# ------------------------------------------------------------------
# 10. _on_default_file_changed: valid bit_rate -> formatted label (lines 345-346)
# ------------------------------------------------------------------


class TestOnDefaultBitRateFormatted:
    def test_formats_bitrate_label_when_positive(self, mock_controller, tmp_path):
        """Lines 345-346: Valid bit_rate formatted as Mbps and bps."""
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)

        version = {
            "path": str(fake_path),
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 5000000,
            "audio_tracks": [],
            "subtitle_tracks": [],
            "runtime": None,
        }
        _make_episode_record(versions=[version])

        with (
            patch("lan_streamer.scanner.get_detailed_file_info", return_value=version),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        text = dialog.bit_rate_label.text()
        assert "5.00 Mbps" in text
        assert "5,000,000 bps" in text


# ------------------------------------------------------------------
# 11. _on_default_file_changed: audio_tracks as JSON string (lines 355-358)
# ------------------------------------------------------------------


class TestOnDefaultAudioTracksJsonString:
    def test_parses_audio_tracks_from_json_string(self, mock_controller, tmp_path):
        """Lines 355-358: JSON string audio_tracks is parsed via json.loads."""
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)

        tracks_json = json.dumps(
            [{"index": 0, "codec": "ac3", "language": "eng", "title": "Surround"}]
        )
        version = {
            "path": str(fake_path),
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 0,
            "audio_tracks": tracks_json,
            "subtitle_tracks": [],
            "runtime": None,
        }
        _make_episode_record(versions=[version])

        with (
            patch("lan_streamer.scanner.get_detailed_file_info", return_value=version),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        assert dialog.audio_list.count() == 1
        assert "ac3" in dialog.audio_list.item(0).text()

    def test_handles_invalid_json_audio_tracks(self, mock_controller, tmp_path):
        """Lines 355-358: Invalid JSON falls back to empty list."""
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)

        version = {
            "path": str(fake_path),
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 0,
            "audio_tracks": "not valid json{",
            "subtitle_tracks": [],
            "runtime": None,
        }
        _make_episode_record(versions=[version])

        with (
            patch("lan_streamer.scanner.get_detailed_file_info", return_value=version),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        assert dialog.audio_list.count() == 0


# ------------------------------------------------------------------
# 12. _on_default_file_changed: subtitle_tracks as JSON string (lines 367-370)
# ------------------------------------------------------------------


class TestOnDefaultSubtitleTracksJsonString:
    def test_parses_subtitle_tracks_from_json_string(self, mock_controller, tmp_path):
        """Lines 367-370: JSON string subtitle_tracks is parsed."""
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)

        tracks_json = json.dumps(
            [{"index": 1, "codec": "srt", "language": "fre", "title": "French"}]
        )
        version = {
            "path": str(fake_path),
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 0,
            "audio_tracks": [],
            "subtitle_tracks": tracks_json,
            "runtime": None,
        }
        _make_episode_record(versions=[version])

        with (
            patch("lan_streamer.scanner.get_detailed_file_info", return_value=version),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        assert dialog.subtitle_list.count() == 1
        assert "srt" in dialog.subtitle_list.item(0).text()

    def test_handles_invalid_json_subtitle_tracks(self, mock_controller, tmp_path):
        """Lines 367-370: Invalid JSON falls back to empty list."""
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)

        version = {
            "path": str(fake_path),
            "video_codec": "h264",
            "resolution": "1080p",
            "bit_rate": 0,
            "audio_tracks": [],
            "subtitle_tracks": "broken{{",
            "runtime": None,
        }
        _make_episode_record(versions=[version])

        with (
            patch("lan_streamer.scanner.get_detailed_file_info", return_value=version),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        assert dialog.subtitle_list.count() == 0


# ------------------------------------------------------------------
# 13. _refresh_external_subtitles: finds matching subtitle files (lines 387-394)
# ------------------------------------------------------------------


class TestRefreshExternalSubtitles:
    def test_populates_external_subtitles_when_files_exist(
        self, mock_controller, tmp_path
    ):
        """Lines 387-394: External subtitle files are found and listed."""
        fake_video = tmp_path / "S01E01.mkv"
        fake_video.write_bytes(b"\x00" * 1024)
        fake_sub = tmp_path / "S01E01.srt"
        fake_sub.write_text(
            "1\n00:00:01,000 --> 00:00:05,000\nHello\n", encoding="utf-8"
        )

        ep = _make_episode_record()
        ep["path"] = str(fake_video)
        mock_controller.cached_library_data = _make_series_data(ep)

        with (
            patch(
                "lan_streamer.scanner.get_detailed_file_info",
                return_value={
                    "video_codec": "h264",
                    "resolution": "1080p",
                    "bit_rate": 0,
                    "audio_tracks": [],
                    "subtitle_tracks": [],
                    "runtime": None,
                },
            ),
            patch(
                "lan_streamer.scanner.SUBTITLE_EXTENSIONS",
                {".srt", ".ass", ".vtt"},
            ),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_video), mock_controller)

        assert dialog.external_sub_list.count() == 1
        assert dialog.merge_button.isEnabled()


# ------------------------------------------------------------------
# 14. _on_save_clicked: selected_version found (lines 406-408, 429-434)
# ------------------------------------------------------------------


class TestOnSaveClickedSelectedVersion:
    def test_saves_with_selected_version_metadata(self, mock_controller, tmp_path):
        """Lines 406-408, 429-434: Version fields included when version matches."""
        fake_path = tmp_path / "S01E01.mkv"
        fake_path.write_bytes(b"\x00" * 1024)

        version = {
            "path": str(fake_path),
            "video_codec": "hevc",
            "resolution": "3840x2160",
            "bit_rate": 20000000,
            "audio_tracks": [
                {"index": 0, "codec": "dts", "language": "eng", "title": ""}
            ],
            "subtitle_tracks": [],
        }
        ep = _make_episode_record(versions=[version])
        ep["path"] = str(fake_path)
        mock_controller.cached_library_data = _make_series_data(ep)

        with (
            patch(
                "lan_streamer.scanner.get_detailed_file_info",
                return_value={
                    "video_codec": "hevc",
                    "resolution": "3840x2160",
                    "bit_rate": 20000000,
                    "audio_tracks": [],
                    "subtitle_tracks": [],
                    "runtime": 50,
                },
            ),
            patch("lan_streamer.scanner.SUBTITLE_EXTENSIONS", {".srt"}),
        ):
            dialog = EpisodeDetailsDialog("Test Show", str(fake_path), mock_controller)

        dialog.title_edit.setText("Updated Title")
        dialog.runtime_edit.setText("50")
        dialog.air_date_edit.setText("2020-06-15")

        dialog._on_save_clicked()

        mock_controller.update_episode_metadata.assert_called_once()
        saved_metadata = mock_controller.update_episode_metadata.call_args[0][2]
        assert saved_metadata["video_codec"] == "hevc"
        assert saved_metadata["resolution"] == "3840x2160"
        assert saved_metadata["bit_rate"] == 20000000


# ------------------------------------------------------------------
# 15. _on_save_clicked: runtime value error (lines 419-424)
# ------------------------------------------------------------------


class TestOnSaveClickedRuntimeValueError:
    def test_shows_warning_and_returns_on_invalid_runtime(
        self, mock_controller, tmp_path
    ):
        """Lines 419-424: Non-numeric runtime shows QMessageBox warning."""
        ep = _make_episode_record()
        dialog, fake_path = _build_dialog(mock_controller, ep, tmp_path)

        dialog.title_edit.setText("Title")
        dialog.runtime_edit.setText("not_a_number")
        dialog.air_date_edit.setText("2020-01-01")

        with patch(
            "lan_streamer.ui_views.dialogs.episode_details.QMessageBox"
        ) as mock_msgbox:
            mock_msgbox.warning = MagicMock()
            mock_msgbox.StandardButton = MagicMock()
            dialog._on_save_clicked()
            mock_msgbox.warning.assert_called_once()
            mock_controller.update_episode_metadata.assert_not_called()


# ------------------------------------------------------------------
# 16. _on_save_clicked: no matching version in list (lines 426-428, 403-408)
# ------------------------------------------------------------------


class TestOnSaveClickedNoMatchingVersion:
    def test_saves_metadata_without_version_fields(self, mock_controller, tmp_path):
        """Lines 403-408, 426-428: No version match means no codec fields saved."""
        ep = _make_episode_record(versions=[])
        dialog, fake_path = _build_dialog(mock_controller, ep, tmp_path)

        dialog.title_edit.setText("Title Only")
        dialog.runtime_edit.setText("30")
        dialog.air_date_edit.setText("2020-02-02")

        dialog._on_save_clicked()

        saved_metadata = mock_controller.update_episode_metadata.call_args[0][2]
        assert saved_metadata["tmdb_name"] == "Title Only"
        assert "video_codec" not in saved_metadata


# ------------------------------------------------------------------
# 17. _on_search_osub_clicked: opens SubtitleSearchDialog (lines 527-535)
# ------------------------------------------------------------------


class TestOnSearchOsubClicked:
    def test_opens_dialog_and_refreshes_on_accept(self, mock_controller, tmp_path):
        """Lines 527-535: SubtitleSearchDialog opens; file info refreshes on accept."""
        ep = _make_episode_record()
        dialog, fake_path = _build_dialog(mock_controller, ep, tmp_path)

        mock_dialog_instance = MagicMock()
        mock_dialog_instance.exec.return_value = True

        with (
            patch(
                "lan_streamer.ui_views.dialogs.episode_details.SubtitleSearchDialog",
                return_value=mock_dialog_instance,
            ),
            patch.object(dialog, "_refresh_file_info"),
        ):
            dialog._on_search_osub_clicked()

        mock_dialog_instance.exec.assert_called_once()

    def test_does_not_refresh_when_dialog_rejected(self, mock_controller, tmp_path):
        """Lines 527-535: No refresh when dialog is rejected."""
        ep = _make_episode_record()
        dialog, fake_path = _build_dialog(mock_controller, ep, tmp_path)

        mock_dialog_instance = MagicMock()
        mock_dialog_instance.exec.return_value = False

        with (
            patch(
                "lan_streamer.ui_views.dialogs.episode_details.SubtitleSearchDialog",
                return_value=mock_dialog_instance,
            ),
            patch.object(dialog, "_refresh_file_info") as mock_refresh,
        ):
            dialog._on_search_osub_clicked()

        mock_refresh.assert_not_called()
