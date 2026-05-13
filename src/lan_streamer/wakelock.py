import sys
import subprocess
import logging
import threading
import os
from typing import Any

logger = logging.getLogger(__name__)


class WakeLock:
    """Prevents the system from sleeping or starting the screensaver."""

    def __init__(self) -> None:
        self.active = False
        self._lock = threading.Lock()
        self._process: Any = None
        self._cookie: Any = None  # Used for dbus inhibit

    def inhibit(self, reason: str = "Video playback") -> None:
        with self._lock:
            if self.active:
                return

            logger.info(f"Inhibiting screen sleep: {reason}")
            try:
                if sys.platform == "linux":
                    self._inhibit_linux(reason)
                elif sys.platform == "win32":
                    self._inhibit_windows()
                elif sys.platform == "darwin":
                    self._inhibit_macos(reason)
                self.active = True
            except Exception as e:
                logger.exception("Failed to inhibit sleep")

    def uninhibit(self) -> None:
        with self._lock:
            if not self.active:
                return

            logger.info("Releasing screen sleep inhibition")
            try:
                if sys.platform == "linux":
                    self._uninhibit_linux()
                elif sys.platform == "win32":
                    self._uninhibit_windows()
                elif sys.platform == "darwin":
                    self._uninhibit_macos()
                self.active = False
            except Exception as e:
                logger.exception("Failed to release sleep inhibition")

    def _inhibit_linux(self, reason: str) -> None:
        # Try gdbus first (standard for GNOME/KDE)
        try:
            cmd = [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.freedesktop.ScreenSaver",
                "--object-path",
                "/org/freedesktop/ScreenSaver",
                "--method",
                "org.freedesktop.ScreenSaver.Inhibit",
                "lan-streamer",
                reason,
            ]
            result = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            # Result is usually something like "(uint32 12345,)"
            import re

            match = re.search(r"uint32\s+(\d+)", result)
            if match:
                self._cookie = match.group(1)
                logger.info(f"Linux sleep inhibition active (cookie: {self._cookie})")
                return
        except Exception as e:
            logger.debug(f"gdbus inhibition failed: {e}")

        # Fallback to xdg-screensaver suspend (less reliable for some WMs)
        try:
            subprocess.Popen(
                ["xdg-screensaver", "suspend", "0x0"]
            )  # 0x0 is a dummy window id
            logger.info("Linux sleep inhibition active (xdg-screensaver)")
        except Exception as e:
            logger.debug(f"xdg-screensaver failed: {e}")

    def _uninhibit_linux(self) -> None:
        if self._cookie:
            try:
                cmd = [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.freedesktop.ScreenSaver",
                    "--object-path",
                    "/org/freedesktop/ScreenSaver",
                    "--method",
                    "org.freedesktop.ScreenSaver.UnInhibit",
                    self._cookie,
                ]
                subprocess.run(cmd, check=True, capture_output=True)
            except Exception as e:
                logger.debug(
                    f"gdbus uninhibit failed (lock likely auto-released by session): {e}"
                )
            finally:
                self._cookie = None

        # Always try to resume xdg-screensaver just in case
        try:
            subprocess.run(["xdg-screensaver", "resume", "0x0"], capture_output=True)
        except Exception:
            pass

    def _inhibit_windows(self) -> None:
        import ctypes

        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        # 0x80000000 | 0x00000001 | 0x00000002 = 0x80000003
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)  # type: ignore[attr-defined]
        except Exception as e:
            logger.exception("Windows SetThreadExecutionState failed")

    def _uninhibit_windows(self) -> None:
        import ctypes

        # ES_CONTINUOUS = 0x80000000
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _inhibit_macos(self, reason: str) -> None:
        try:
            # caffeinate -d inhibits display sleep
            self._process = subprocess.Popen(
                ["caffeinate", "-d", "-i", "-s", "-w", str(os.getpid())]
            )
        except Exception as e:
            logger.exception("macOS caffeinate failed")

    def _uninhibit_macos(self) -> None:
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=1)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
