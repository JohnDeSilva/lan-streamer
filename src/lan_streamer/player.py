import subprocess
from pathlib import Path
import sys
import logging

logger = logging.getLogger(__name__)


def play_video(file_path: str) -> None:
    """
    Launches VLC to play the given video file.
    Uses subprocess to pass the file path directly to VLC, ensuring no compression.
    """
    logger.info(f"Launching external VLC for: {file_path}")
    path = Path(file_path)
    if not path.exists():
        logger.error(f"Video file not found: {file_path}")
        raise FileNotFoundError(f"Video file not found: {file_path}")

    try:
        # We just launch VLC in the background and detach
        if sys.platform == "win32":
            subprocess.Popen(["vlc", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "VLC", str(path)])
        else:
            subprocess.Popen(["vlc", str(path)])
    except Exception as exception_instance:
        logger.exception("Error launching VLC")
