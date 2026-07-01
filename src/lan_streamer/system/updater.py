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


def parse_base_version(version_str: str) -> tuple[int, ...]:
    """Parse only the base version, stripping any pre-release suffix.

    E.g. 'v0.27.0-rc.1' -> (0, 27, 0)
    """
    base = version_str.strip().lower().lstrip("v").split("-")[0]
    parts = []
    for part in base.split("."):
        digits = "".join(c for c in part if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_prerelease_tag(tag_name: str) -> bool:
    """Return True if the tag name indicates a pre-release version."""
    stripped = tag_name.strip().lower().lstrip("v")
    return "-" in stripped


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
    Supports \"stable\" (main releases only) and \"rc\" (includes release candidates).
    """

    finished = Signal(bool, dict, str)  # success, release_info, error_msg

    def __init__(self, release_channel: str = "stable") -> None:
        super().__init__()
        self.release_channel = release_channel

    @staticmethod
    def _extract_release_data(release: dict) -> dict | None:
        """Extract version, body, and download url from a release dict."""
        tag_name = release.get("tag_name", "")
        if not tag_name:
            return None
        target_asset_name = get_target_asset_name()
        download_url = ""
        for asset in release.get("assets", []):
            if asset.get("name") == target_asset_name:
                download_url = asset.get("browser_download_url", "")
                break
        return {
            "version": tag_name,
            "release_notes": release.get("body", ""),
            "download_url": download_url,
        }

    def _check_stable(self) -> None:
        """Check the latest stable (non-prerelease) release."""
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
        if not tag_name:
            self.finished.emit(False, {}, "Invalid release format: missing tag_name")
            return

        if parse_version(tag_name) > parse_version(__version__):
            release_data = self._extract_release_data(data)
            if release_data and release_data["download_url"]:
                self.finished.emit(True, release_data, "")
            else:
                logger.warning(
                    f"Newer version {tag_name} found, but no matching asset was found."
                )
                self.finished.emit(True, {}, "")
        else:
            self.finished.emit(True, {}, "")

    def _check_rc(self) -> None:
        """Check all releases including pre-releases / release candidates.

        When the same base version exists as both stable and pre-release,
        the stable release is preferred.
        """
        from lan_streamer import __version__

        headers = {"User-Agent": "lan-streamer-updater"}
        response = requests.get(
            "https://api.github.com/repos/JohnDeSilva/lan-streamer/releases",
            headers=headers,
            timeout=10,
        )
        if response.status_code != 200:
            self.finished.emit(False, {}, f"HTTP Error {response.status_code}")
            return

        releases = response.json()
        if not isinstance(releases, list) or not releases:
            self.finished.emit(True, {}, "")
            return

        # best_release_per_version[base_version] = (is_prerelease, release_data)
        best_release_per_version: dict[tuple[int, ...], tuple[bool, dict]] = {}

        for release in releases:
            if release.get("draft", False):
                continue
            tag_name = release.get("tag_name", "")
            if not tag_name:
                continue

            base_version = parse_base_version(tag_name)
            prerelease = is_prerelease_tag(tag_name)
            release_data = self._extract_release_data(release)
            if not release_data or not release_data["download_url"]:
                continue

            existing = best_release_per_version.get(base_version)
            if existing is None:
                best_release_per_version[base_version] = (prerelease, release_data)
            elif existing[0] and not prerelease:
                # Prefer stable over pre-release at the same base version
                best_release_per_version[base_version] = (prerelease, release_data)

        if not best_release_per_version:
            self.finished.emit(True, {}, "")
            return

        best_base_version = max(best_release_per_version.keys())
        _, best_release_data = best_release_per_version[best_base_version]

        current_base_version = parse_base_version(__version__)
        if best_base_version > current_base_version:
            self.finished.emit(True, best_release_data, "")
        else:
            self.finished.emit(True, {}, "")

    def run(self) -> None:
        try:
            if self.release_channel == "rc":
                self._check_rc()
            else:
                self._check_stable()
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
