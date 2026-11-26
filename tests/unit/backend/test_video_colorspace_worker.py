"""Unit tests for VideoColorSpaceWorker and UI color-space re-encode actions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox

from lan_streamer.backend.video_colorspace_worker import (
    VideoColorSpaceError,
    VideoColorSpaceWorker,
)
from lan_streamer.ui_views.dialogs.episode_details import EpisodeDetailsDialog
from lan_streamer.ui_views.dialogs.movie_details import MovieDetailsDialog

if TYPE_CHECKING:
    from pathlib import Path


def test_video_colorspace_worker_uses_libplacebo_and_replaces_file(
    tmp_path: Path,
) -> None:
    video_file = tmp_path / "movie.mkv"
    video_file.write_bytes(b"original-uhd-bytes")
    temp_output = tmp_path / "movie.bt709.mkv"

    async def fake_subprocess(command: list[str]) -> SimpleNamespace:
        if "-filters" in command:
            return SimpleNamespace(
                returncode=0, stdout=" ... libplacebo ... ", stderr=""
            )
        temp_output.write_bytes(b"reencoded-sdr-bytes")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    worker = VideoColorSpaceWorker(str(video_file))
    with (
        patch(
            "lan_streamer.backend.video_colorspace_worker._get_ffmpeg_command",
            return_value="ffmpeg",
        ),
        patch(
            "lan_streamer.backend.video_colorspace_worker.async_run_subprocess",
            side_effect=fake_subprocess,
        ) as mock_run,
    ):
        result_path = asyncio.run(worker.run_async())

    assert result_path == str(video_file)
    assert video_file.read_bytes() == b"reencoded-sdr-bytes"
    assert not temp_output.exists()

    encode_cmd = mock_run.call_args_list[1].args[0]
    assert "-vf" in encode_cmd
    assert "libplacebo=" in encode_cmd[encode_cmd.index("-vf") + 1]
    assert "bt709" in encode_cmd


def test_video_colorspace_worker_falls_back_to_zscale_and_cleans_up_on_error(
    tmp_path: Path,
) -> None:
    video_file = tmp_path / "episode.mkv"
    video_file.write_bytes(b"original-uhd-bytes")
    temp_output = tmp_path / "episode.bt709.mkv"

    async def fake_subprocess(command: list[str]) -> SimpleNamespace:
        if "-filters" in command:
            return SimpleNamespace(returncode=0, stdout="zscale tonemap", stderr="")
        temp_output.write_bytes(b"partial-bytes")
        return SimpleNamespace(returncode=1, stdout="", stderr="encoder error")

    worker = VideoColorSpaceWorker(str(video_file))
    with (
        patch(
            "lan_streamer.backend.video_colorspace_worker._get_ffmpeg_command",
            return_value="ffmpeg",
        ),
        patch(
            "lan_streamer.backend.video_colorspace_worker.async_run_subprocess",
            side_effect=fake_subprocess,
        ) as mock_run,
        pytest.raises(VideoColorSpaceError, match="encoder error"),
    ):
        asyncio.run(worker.run_async())

    encode_cmd = mock_run.call_args_list[1].args[0]
    assert "zscale=" in encode_cmd[encode_cmd.index("-vf") + 1]
    assert video_file.read_bytes() == b"original-uhd-bytes"
    assert not temp_output.exists()


def test_episode_and_movie_details_dialogs_trigger_reencode(
    qtbot, tmp_path: Path
) -> None:
    ep_file = tmp_path / "ep.mkv"
    ep_file.write_bytes(b"ep")
    movie_file = tmp_path / "movie.mkv"
    movie_file.write_bytes(b"mv")

    controller = MagicMock()
    controller.cached_library_data = {
        "Show A": {
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": str(ep_file),
                            "name": "Ep 1",
                            "versions": [{"path": str(ep_file)}],
                        }
                    ]
                }
            }
        },
        "Movie A": {
            "path": str(movie_file),
            "name": "Movie A",
            "versions": [{"path": str(movie_file)}],
        },
    }

    with patch(
        "lan_streamer.ui_views.dialogs.episode_details.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        ep_dialog = EpisodeDetailsDialog("Show A", str(ep_file), controller)
        qtbot.addWidget(ep_dialog)
        ep_dialog.reencode_colorspace_button.click()
        controller.reencode_video_colorspace.assert_called_once_with(str(ep_file))

    controller.reencode_video_colorspace.reset_mock()

    with patch(
        "lan_streamer.ui_views.dialogs.movie_details.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        movie_dialog = MovieDetailsDialog("Movie A", str(movie_file), controller)
        qtbot.addWidget(movie_dialog)
        movie_dialog.reencode_colorspace_button.click()
        controller.reencode_video_colorspace.assert_called_once_with(str(movie_file))
