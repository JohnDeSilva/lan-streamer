import sys
import importlib
import builtins
from unittest.mock import patch


def test_playback_init_import_error() -> None:
    # Remove vlc from sys.modules and force ImportError
    try:
        with patch.dict(sys.modules, {"vlc": None}):
            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "vlc":
                    raise ImportError("mocked ImportError")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                import lan_streamer.playback

                importlib.reload(lan_streamer.playback)
                assert lan_streamer.playback.vlc is None
    finally:
        import lan_streamer.playback

        importlib.reload(lan_streamer.playback)


def test_playback_init_os_error() -> None:
    # Remove vlc from sys.modules and force OSError
    try:
        with patch.dict(sys.modules, {"vlc": None}):
            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "vlc":
                    raise OSError("mocked OSError")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                import lan_streamer.playback

                importlib.reload(lan_streamer.playback)
                assert lan_streamer.playback.vlc is None
    finally:
        import lan_streamer.playback

        importlib.reload(lan_streamer.playback)
