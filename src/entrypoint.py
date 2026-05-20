import os
import sys

# macOS PyInstaller compatibility for system VLC
if sys.platform == "darwin" and getattr(sys, "frozen", False):
    import ctypes

    vlc_lib_path = os.environ.get("PYTHON_VLC_LIB_PATH")
    if vlc_lib_path and "libvlc.dylib" in vlc_lib_path:
        # Pre-load libvlccore so libvlc can find its dependencies when frozen
        core_path = vlc_lib_path.replace("libvlc.dylib", "libvlccore.dylib")
        try:
            ctypes.CDLL(core_path)
        except Exception:
            pass
    # Also set VLC_PLUGIN_PATH if not set, as plugins are needed for actual playback
    if "VLC_PLUGIN_PATH" not in os.environ:
        os.environ["VLC_PLUGIN_PATH"] = "/Applications/VLC.app/Contents/MacOS/plugins"

# Linux/Windows PyInstaller compatibility for system VLC plugins
elif getattr(sys, "frozen", False) and "VLC_PLUGIN_PATH" not in os.environ:
    if sys.platform == "linux":
        common_plugin_paths = [
            "/usr/lib/x86_64-linux-gnu/vlc/plugins",
            "/usr/lib/aarch64-linux-gnu/vlc/plugins",
            "/usr/lib64/vlc/plugins",
            "/usr/lib/vlc/plugins",
        ]
        for path in common_plugin_paths:
            if os.path.isdir(path):
                os.environ["VLC_PLUGIN_PATH"] = path
                break
    elif sys.platform == "win32":
        common_plugin_paths = [
            r"C:\Program Files\VideoLAN\VLC\plugins",
            r"C:\Program Files (x86)\VideoLAN\VLC\plugins",
        ]
        for path in common_plugin_paths:
            if os.path.isdir(path):
                os.environ["VLC_PLUGIN_PATH"] = path
                break

from lan_streamer.main import main

if __name__ == "__main__":
    main()
