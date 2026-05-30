import pytest
from unittest.mock import patch
from lan_streamer.playback.player import play_video


def test_play_video_success(tmp_path) -> None:
    video_file = tmp_path / "test.mkv"
    video_file.touch()

    with patch("subprocess.Popen") as mock_popen:
        play_video(str(video_file))
        mock_popen.assert_called_once()


def test_play_video_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        play_video("/nonexistent/file.mp4")


def test_play_video_win32(tmp_path) -> None:
    video_file = tmp_path / "test.mkv"
    video_file.touch()

    with patch("sys.platform", "win32"), patch("subprocess.Popen") as mock_popen:
        play_video(str(video_file))
        mock_popen.assert_called_once_with(["vlc", str(video_file)])


def test_play_video_darwin(tmp_path) -> None:
    video_file = tmp_path / "test.mkv"
    video_file.touch()

    with patch("sys.platform", "darwin"), patch("subprocess.Popen") as mock_popen:
        play_video(str(video_file))
        mock_popen.assert_called_once_with(["open", "-a", "VLC", str(video_file)])


def test_play_video_exception(tmp_path) -> None:
    video_file = tmp_path / "test.mkv"
    video_file.touch()

    with patch("subprocess.Popen", side_effect=Exception("Mocked error")) as mock_popen:
        # Should not raise exception
        play_video(str(video_file))
        mock_popen.assert_called_once()
