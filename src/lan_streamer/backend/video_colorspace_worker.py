"""Background worker for re-encoding HDR/Dolby Vision video to SDR BT.709."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_utils import async_run_subprocess

if TYPE_CHECKING:
    from lan_streamer.system.async_task_manager import AsyncTaskManager

logger = logging.getLogger("lan_streamer.backend")

_LIBPLACEBO_FILTER = (
    "libplacebo=tonemapping=hable:colorspace=bt709:"
    "color_primaries=bt709:color_trc=bt709:format=yuv420p"
)
_ZSCALE_TONEMAP_FILTER = (
    "zscale=t=linear:npl=100,format=gbrpf32le,"
    "zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
    "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)


class VideoColorSpaceError(RuntimeError):
    """Raised when ffmpeg fails to re-encode a video to BT.709 SDR."""


def _get_ffmpeg_command() -> str:
    """Resolve the ffmpeg executable path across PATH and standard Unix locations."""
    resolved = shutil.which("ffmpeg")
    if resolved:
        return resolved
    for fallback_path in (
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
        Path("/opt/local/bin/ffmpeg"),
    ):
        if fallback_path.is_file():
            return str(fallback_path)
    return "ffmpeg"


async def _ffmpeg_supports_libplacebo(ffmpeg_command: str) -> bool:
    """Return True when the local ffmpeg build includes the ``libplacebo`` filter."""
    try:
        result = await async_run_subprocess(
            [ffmpeg_command, "-hide_banner", "-filters"]
        )
        return result.returncode == 0 and "libplacebo" in result.stdout
    except OSError:
        return False


class VideoColorSpaceWorker(AsyncWorkerBase):
    """Re-encodes HDR/Dolby Vision video streams to standard BT.709 SDR using ffmpeg."""

    finished = Signal(str)  # resulting file path
    error = Signal(str)

    def __init__(
        self,
        video_path: str,
        async_task_manager: AsyncTaskManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.video_path: str = video_path

    async def run_async(self) -> str:
        """Execute ffmpeg color-space conversion and atomically replace the source file."""
        logger.info("VideoColorSpaceWorker starting for %s", self.video_path)
        video_path_object = Path(self.video_path)
        if not await asyncio.to_thread(video_path_object.is_file):
            raise VideoColorSpaceError(f"Video file does not exist: {self.video_path}")

        ffmpeg_command = _get_ffmpeg_command()
        use_libplacebo = await _ffmpeg_supports_libplacebo(ffmpeg_command)
        video_filter = _LIBPLACEBO_FILTER if use_libplacebo else _ZSCALE_TONEMAP_FILTER

        suffix = video_path_object.suffix or ".mkv"
        output_path = str(
            video_path_object.with_name(f"{video_path_object.stem}.bt709{suffix}")
        )
        command = [
            ffmpeg_command,
            "-y",
            "-i",
            self.video_path,
            "-map",
            "0",
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-c:a",
            "copy",
            "-c:s",
            "copy",
            output_path,
        ]
        logger.info(
            "Re-encoding '%s' to BT.709 SDR using %s",
            self.video_path,
            "libplacebo" if use_libplacebo else "zscale+tonemap",
        )
        logger.debug("Running ffmpeg command: %s", " ".join(command))

        try:
            result = await async_run_subprocess(command)
            if result.returncode != 0:
                stderr_text = result.stderr.strip() or "Unknown ffmpeg error"
                raise VideoColorSpaceError(
                    f"ffmpeg color-space re-encode failed: {stderr_text}"
                )

            await asyncio.to_thread(os.replace, output_path, self.video_path)
        except Exception:
            if await asyncio.to_thread(os.path.exists, output_path):
                try:
                    await asyncio.to_thread(os.remove, output_path)
                except OSError:
                    logger.warning(
                        "Failed to clean up temporary output file: %s", output_path
                    )
            raise

        logger.info(
            "VideoColorSpaceWorker finished successfully for %s", self.video_path
        )
        return self.video_path
