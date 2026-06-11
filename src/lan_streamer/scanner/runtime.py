import logging
import os
import shutil
import functools
import json
import subprocess
from pathlib import Path
from typing import Dict, Any


logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _get_ffprobe_command() -> str:
    """
    Resolves the ffprobe command or path, checking standard PATH and typical fallback locations.
    """
    logger.debug("Resolving ffprobe command path...")
    # 1. Check standard PATH
    path_resolved = shutil.which("ffprobe")
    if path_resolved:
        logger.info(f"Resolved ffprobe command in system PATH: '{path_resolved}'")
        return path_resolved

    # 2. Check common installation directories on macOS/Linux
    common_paths = [
        "/opt/homebrew/bin/ffprobe",  # Apple Silicon Homebrew
        "/usr/local/bin/ffprobe",  # Intel Homebrew / standard Unix install
        "/opt/local/bin/ffprobe",  # MacPorts
    ]
    for path_str in common_paths:
        if os.path.exists(path_str) and os.access(path_str, os.X_OK):
            logger.info(f"Resolved ffprobe command via fallback path: '{path_str}'")
            return path_str

    # 3. Default back to 'ffprobe' and let the system attempt to resolve it
    logger.warning(
        "ffprobe command not found in PATH or standard installation locations. Defaulting to 'ffprobe'."
    )
    return "ffprobe"


def _extract_video_runtime(file_path: str) -> int:
    """
    Extracts video runtime in minutes directly from the video file itself.
    First attempts using ffprobe via subprocess for clean offline parsing,
    falling back to libvlc media parsing if ffprobe is unavailable.
    """
    if not file_path or not os.path.exists(file_path):
        return 0

    try:
        process_result: subprocess.CompletedProcess[str] = subprocess.run(
            [
                _get_ffprobe_command(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if process_result.returncode == 0 and process_result.stdout.strip():
            duration_seconds: float = float(process_result.stdout.strip())
            return int(round(duration_seconds / 60.0))
    except Exception as error_instance:
        logger.debug(f"ffprobe extraction failed for '{file_path}': {error_instance}")

    try:
        import vlc

        vlc_instance: Any = vlc.Instance("--quiet")
        media_object: Any = vlc_instance.media_new(file_path)
        media_object.parse()
        duration_milliseconds: int = media_object.get_duration()
        if duration_milliseconds > 0:
            return int(round(duration_milliseconds / 60000.0))
    except Exception as error_instance:
        logger.debug(f"vlc extraction failed for '{file_path}': {error_instance}")

    return 0


def get_detailed_file_info(file_path: str) -> Dict[str, Any]:
    """
    Extracts exhaustive technical metadata from a video file using ffprobe.
    Returns a dictionary containing resolution, codecs, track listings, and runtime.
    """
    info: Dict[str, Any] = {
        "path": file_path,
        "size_bytes": 0,
        "video_type": "Unknown",
        "resolution": "Unknown",
        "video_codec": "Unknown",
        "bit_rate": 0,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "runtime": 0,
    }

    if not file_path or not os.path.exists(file_path):
        return info

    path_obj = Path(file_path)
    info["size_bytes"] = path_obj.stat().st_size
    info["video_type"] = path_obj.suffix.upper().replace(".", "")

    try:
        process_result = subprocess.run(
            [
                _get_ffprobe_command(),
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if process_result.returncode == 0:
            data = json.loads(process_result.stdout)
            streams = data.get("streams", [])
            format_data = data.get("format", {})

            # Extract runtime from duration
            duration_str = format_data.get("duration")
            if duration_str:
                try:
                    duration_seconds = float(duration_str)
                    info["runtime"] = int(round(duration_seconds / 60.0))
                except ValueError:
                    pass

            bit_rate_str = format_data.get("bit_rate")
            if bit_rate_str:
                try:
                    info["bit_rate"] = int(bit_rate_str)
                except ValueError:
                    pass
            if not info.get("bit_rate") and duration_str:
                try:
                    dur = float(duration_str)
                    if dur > 0:
                        info["bit_rate"] = int(round((info["size_bytes"] * 8) / dur))
                except Exception:
                    pass

            for stream in streams:
                codec_type = stream.get("codec_type")
                codec_name = stream.get("codec_name", "unknown")
                tags = stream.get("tags", {})
                language = tags.get("language", "und")
                title = tags.get("title", "")

                track_info = {
                    "index": stream.get("index"),
                    "codec": codec_name,
                    "language": language,
                    "title": title,
                }

                if codec_type == "video":
                    width = stream.get("width")
                    height = stream.get("height")
                    if width and height:
                        info["resolution"] = f"{width}x{height}"
                    if info["video_codec"] == "Unknown" or not info.get("video_codec"):
                        info["video_codec"] = codec_name
                elif codec_type == "audio":
                    info["audio_tracks"].append(track_info)
                elif codec_type == "subtitle":
                    info["subtitle_tracks"].append(track_info)

    except Exception as exc:
        logger.error(f"Failed to extract detailed info for {file_path}: {exc}")

    if info["runtime"] == 0:
        info["runtime"] = _extract_video_runtime(file_path)

    return info
