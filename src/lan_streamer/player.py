import subprocess
from pathlib import Path
import sys


def play_video(file_path: str):
    """
    Launches VLC to play the given video file.
    Uses subprocess to pass the file path directly to VLC, ensuring no compression.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {file_path}")

    try:
        # We just launch VLC in the background and detach
        if sys.platform == "win32":
            subprocess.Popen(["vlc", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "VLC", str(path)])
        else:
            subprocess.Popen(["vlc", str(path)])
    except Exception as e:
        print(f"Error launching VLC: {e}")
