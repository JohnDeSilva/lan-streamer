import importlib
import os
from unittest.mock import patch

# Pre-import entrypoint to ensure all dependencies like vlc/ctypes are loaded while sys.platform is native Linux
# This avoids ctypes.util trying to load macOS dynamic linker functions on Linux when sys.platform is mocked.
import entrypoint


def test_entrypoint_macos_frozen_fallback() -> None:
    # Test fallback path when none of the paths exist
    with (
        patch("sys.platform", "darwin"),
        patch("sys.frozen", True, create=True),
        patch.dict(os.environ, {}, clear=True),
        patch("os.path.isdir", return_value=False),
        patch("lan_streamer.main.main"),
    ):
        importlib.reload(entrypoint)

        assert (
            os.environ.get("VLC_PLUGIN_PATH")
            == "/Applications/VLC.app/Contents/MacOS/plugins"
        )


def test_entrypoint_macos_frozen_homebrew() -> None:
    # Test path detection when one of the paths exists
    def mock_isdir(path: str) -> bool:
        return path == "/opt/homebrew/lib/vlc/plugins"

    with (
        patch("sys.platform", "darwin"),
        patch("sys.frozen", True, create=True),
        patch.dict(os.environ, {}, clear=True),
        patch("os.path.isdir", side_effect=mock_isdir),
        patch("lan_streamer.main.main"),
    ):
        importlib.reload(entrypoint)

        assert os.environ.get("VLC_PLUGIN_PATH") == "/opt/homebrew/lib/vlc/plugins"


def test_entrypoint_macos_frozen_user_applications() -> None:
    # Test path detection for user-specific Applications folder
    user_app_path = os.path.expanduser("~/Applications/VLC.app/Contents/MacOS/plugins")

    def mock_isdir(path: str) -> bool:
        return path == user_app_path

    with (
        patch("sys.platform", "darwin"),
        patch("sys.frozen", True, create=True),
        patch.dict(
            os.environ, {"HOME": os.environ.get("HOME", "/home/username")}, clear=True
        ),
        patch("os.path.isdir", side_effect=mock_isdir),
        patch("lan_streamer.main.main"),
    ):
        importlib.reload(entrypoint)

        assert os.environ.get("VLC_PLUGIN_PATH") == user_app_path
