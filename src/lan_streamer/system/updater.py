import os
import sys
import logging
import requests
from PySide6.QtCore import QThread, Signal

logger: logging.Logger = logging.getLogger(__name__)


def parse_version(version_str: str) -> tuple[int, ...]:
    """
    Parses a version string into a tuple of integers for clean comparison.
    E.g. 'v0.26.1' -> (0, 26, 1)
    """
    cleaned = version_str.strip().lower().lstrip("v")
    parts = []
    for part in cleaned.split("."):
        digits = "".join(c for c in part if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def get_linux_distro() -> str:
    """
    Detects the Linux distribution from /etc/os-release to differentiate
    between Ubuntu/Debian-like systems and Fedora/RedHat-like systems.
    """
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release", "r") as f:
                for line in f:
                    if line.startswith("ID="):
                        return line.strip().split("=")[1].strip('"').lower()
                    elif line.startswith("ID_LIKE="):
                        likes = line.strip().split("=")[1].strip('"').lower()
                        if "fedora" in likes or "rhel" in likes or "centos" in likes:
                            return "fedora"
                        if "ubuntu" in likes or "debian" in likes:
                            return "ubuntu"
    except Exception:
        logger.exception("Error reading /etc/os-release")
    return "ubuntu"


def get_target_asset_name() -> str:
    """
    Determines the release asset file name expected on GitHub for the current platform.
    """
    asset_name = ""
    if sys.platform == "win32":
        asset_name = "lan-streamer-windows.exe"
    elif sys.platform == "darwin":
        asset_name = "lan-streamer-macos.dmg"
    elif sys.platform.startswith("linux"):
        distro = get_linux_distro()
        if distro in ("fedora", "rhel", "centos"):
            asset_name = "lan-streamer-fedora"
        else:
            asset_name = "lan-streamer-ubuntu"
    return asset_name


class UpdateCheckWorker(QThread):
    """
    Background worker thread to check the GitHub repository for the latest release.
    """

    finished = Signal(bool, dict, str)  # success, release_info, error_msg

    def run(self) -> None:
        try:
            from lan_streamer import __version__

            headers = {"User-Agent": "lan-streamer-updater"}
            response = requests.get(
                "https://api.github.com/repos/JohnDeSilva/lan-streamer/releases/latest",
                headers=headers,
                timeout=10,
            )
            if response.status_code != 200:
                self.finished.emit(False, {}, f"HTTP Error {response.status_code}")
                return

            data = response.json()
            tag_name = data.get("tag_name", "")
            body = data.get("body", "")
            assets = data.get("assets", [])

            if not tag_name:
                self.finished.emit(
                    False, {}, "Invalid release format: missing tag_name"
                )
                return

            if parse_version(tag_name) > parse_version(__version__):
                target_asset_name = get_target_asset_name()
                download_url = ""
                for asset in assets:
                    if asset.get("name") == target_asset_name:
                        download_url = asset.get("browser_download_url", "")
                        break

                if download_url:
                    release_info = {
                        "version": tag_name,
                        "release_notes": body,
                        "download_url": download_url,
                    }
                    self.finished.emit(True, release_info, "")
                else:
                    logger.warning(
                        f"Newer version {tag_name} found, but no asset matching '{target_asset_name}' was found."
                    )
                    self.finished.emit(True, {}, "")
            else:
                self.finished.emit(True, {}, "")
        except Exception as e:
            logger.exception("Error checking for updates")
            self.finished.emit(False, {}, str(e))


class DownloadWorker(QThread):
    """
    Background worker thread to download the target update asset.
    """

    progress = Signal(int, int)  # bytes_downloaded, total_bytes
    finished = Signal(bool, str)  # success, error_msg_or_downloaded_path

    def __init__(self, download_url: str, save_path: str) -> None:
        super().__init__()
        self.download_url = download_url
        self.save_path = save_path
        self._is_cancelled = False

    def run(self) -> None:
        try:
            headers = {"User-Agent": "lan-streamer-updater"}
            response = requests.get(
                self.download_url, headers=headers, stream=True, timeout=25
            )
            if response.status_code != 200:
                self.finished.emit(False, f"HTTP Error {response.status_code}")
                return

            total_size = int(response.headers.get("content-length", 0))
            bytes_downloaded = 0

            with open(self.save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self._is_cancelled:
                        self.finished.emit(False, "Download cancelled")
                        return
                    if chunk:
                        f.write(chunk)
                        bytes_downloaded += len(chunk)
                        self.progress.emit(bytes_downloaded, total_size)

            self.finished.emit(True, str(self.save_path))
        except Exception as e:
            logger.exception("Error downloading update")
            self.finished.emit(False, str(e))

    def cancel(self) -> None:
        self._is_cancelled = True
