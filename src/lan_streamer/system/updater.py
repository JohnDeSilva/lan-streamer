import os
import stat
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


def parse_comparable_version(
    version_string: str,
) -> tuple[int, int, int, int, int, int]:
    """Parses a version string into a comparable tuple:
    (major, minor, patch, release_weight, prerelease_number, build_number)

    where release_weight is:
        2: stable release
        1: release candidate (rc)
        0: other pre-releases (alpha, beta, dev, etc.)
    """
    import re

    cleaned_version = version_string.strip().lower().lstrip("v")
    regex_match = re.match(
        r"^(\d+)\.(\d+)\.(\d+)(?:-?(rc|a|b|alpha|beta|dev|post|preview)\.?(\d+))?(?:-(\d+))?$",
        cleaned_version,
    )
    if not regex_match:
        # Fallback to parse_version logic if regex does not match
        parts = []
        for part in cleaned_version.split("."):
            digits = "".join(c for c in part if c.isdigit())
            parts.append(int(digits) if digits else 0)
        while len(parts) < 3:
            parts.append(0)
        return (parts[0], parts[1], parts[2], 2, 0, 0)

    major_version = int(regex_match.group(1))
    minor_version = int(regex_match.group(2))
    patch_version = int(regex_match.group(3))
    prerelease_type = regex_match.group(4)
    prerelease_number_string = regex_match.group(5)
    build_number_string = regex_match.group(6)

    if not prerelease_type:
        release_weight = 2
        prerelease_number = 0
    elif prerelease_type == "rc":
        release_weight = 1
        prerelease_number = (
            int(prerelease_number_string) if prerelease_number_string else 0
        )
    else:
        release_weight = 0
        prerelease_number = (
            int(prerelease_number_string) if prerelease_number_string else 0
        )

    build_number = int(build_number_string) if build_number_string else 0

    return (
        major_version,
        minor_version,
        patch_version,
        release_weight,
        prerelease_number,
        build_number,
    )


def parse_base_version(version_string: str) -> tuple[int, int, int]:
    """Parse only the base version, stripping any pre-release suffix.

    E.g. 'v0.27.0-rc.1' -> (0, 27, 0)
    """
    major_version, minor_version, patch_version, _, _, _ = parse_comparable_version(
        version_string
    )
    return (major_version, minor_version, patch_version)


def is_prerelease_tag(tag_name: str) -> bool:
    """Return True if the tag name indicates a pre-release version."""
    _, _, _, release_weight, _, _ = parse_comparable_version(tag_name)
    return release_weight < 2


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

        logger.info(
            "UpdateCheckWorker: checking stable channel releases from GitHub API"
        )
        headers = {"User-Agent": "lan-streamer-updater"}
        response = requests.get(
            "https://api.github.com/repos/JohnDeSilva/lan-streamer/releases/latest",
            headers=headers,
            timeout=10,
        )
        logger.info(
            f"UpdateCheckWorker: GitHub API response status code: {response.status_code}"
        )
        if response.status_code != 200:
            self.finished.emit(False, {}, f"HTTP Error {response.status_code}")
            return

        data = response.json()
        tag_name = data.get("tag_name", "")
        if not tag_name:
            logger.error("UpdateCheckWorker: Invalid release format, missing tag_name")
            self.finished.emit(False, {}, "Invalid release format: missing tag_name")
            return

        logger.info(f"UpdateCheckWorker: found latest stable tag: '{tag_name}'")
        if parse_comparable_version(tag_name) > parse_comparable_version(__version__):
            logger.info(
                f"UpdateCheckWorker: stable version '{tag_name}' is newer than current '{__version__}'"
            )
            release_data = self._extract_release_data(data)
            if release_data and release_data["download_url"]:
                logger.info(
                    f"UpdateCheckWorker: stable update is available for download: {release_data['download_url']}"
                )
                self.finished.emit(True, release_data, "")
            else:
                logger.warning(
                    f"UpdateCheckWorker: newer version {tag_name} found, but no matching asset was found for current platform."
                )
                self.finished.emit(True, {}, "")
        else:
            logger.info(
                f"UpdateCheckWorker: current version '{__version__}' is up-to-date (latest stable: '{tag_name}')"
            )
            self.finished.emit(True, {}, "")

    def _check_rc(self) -> None:
        """Check all releases including pre-releases / release candidates.

        When the same base version exists as both stable and pre-release,
        the stable release is preferred.
        """
        from lan_streamer import __version__

        logger.info("UpdateCheckWorker: checking RC/all releases from GitHub API")
        headers = {"User-Agent": "lan-streamer-updater"}
        response = requests.get(
            "https://api.github.com/repos/JohnDeSilva/lan-streamer/releases",
            headers=headers,
            timeout=10,
        )
        logger.info(
            f"UpdateCheckWorker: GitHub API response status code: {response.status_code}"
        )
        if response.status_code != 200:
            self.finished.emit(False, {}, f"HTTP Error {response.status_code}")
            return

        releases = response.json()
        if not isinstance(releases, list) or not releases:
            logger.info("UpdateCheckWorker: no releases found in the repository.")
            self.finished.emit(True, {}, "")
            return

        logger.info(f"UpdateCheckWorker: found {len(releases)} releases in repository")
        # best_release_per_version[base_version] = (is_prerelease, release_data)
        best_release_per_version: dict[tuple[int, ...], tuple[bool, dict]] = {}

        for release in releases:
            if release.get("draft", False):
                continue
            tag_name = release.get("tag_name", "")
            if not tag_name:
                continue

            base_version = parse_base_version(tag_name)
            is_prerelease = is_prerelease_tag(tag_name)
            release_data = self._extract_release_data(release)
            if not release_data or not release_data["download_url"]:
                continue

            existing = best_release_per_version.get(base_version)
            if existing is None:
                best_release_per_version[base_version] = (is_prerelease, release_data)
            else:
                existing_prerelease, existing_data = existing
                if existing_prerelease and not is_prerelease:
                    # Prefer stable over pre-release
                    best_release_per_version[base_version] = (
                        is_prerelease,
                        release_data,
                    )
                elif existing_prerelease == is_prerelease:
                    # If both are stable or both are pre-releases, keep the newer one
                    if parse_comparable_version(tag_name) > parse_comparable_version(
                        existing_data["version"]
                    ):
                        best_release_per_version[base_version] = (
                            is_prerelease,
                            release_data,
                        )

        if not best_release_per_version:
            logger.info(
                "UpdateCheckWorker: no suitable releases with matching assets found."
            )
            self.finished.emit(True, {}, "")
            return

        best_release_data = None
        best_release_value = None

        for _, (is_prerelease, release_data) in best_release_per_version.items():
            comparable_value = parse_comparable_version(release_data["version"])
            if best_release_value is None or comparable_value > best_release_value:
                best_release_value = comparable_value
                best_release_data = release_data

        if best_release_data and best_release_value is not None:
            logger.info(
                f"UpdateCheckWorker: selected best release: '{best_release_data['version']}'"
            )
            current_version_value = parse_comparable_version(__version__)
            if best_release_value > current_version_value:
                logger.info(
                    f"UpdateCheckWorker: version '{best_release_data['version']}' is newer than current '{__version__}'"
                )
                self.finished.emit(True, best_release_data, "")
                return
            else:
                logger.info(
                    f"UpdateCheckWorker: current version '{__version__}' is up-to-date (best available: "
                    f"'{best_release_data['version']}')"
                )

        self.finished.emit(True, {}, "")

    def run(self) -> None:
        logger.info(
            f"UpdateCheckWorker: thread started checking channel: '{self.release_channel}'"
        )
        try:
            if self.release_channel == "rc":
                self._check_rc()
            else:
                self._check_stable()
        except Exception as exception:
            logger.exception("UpdateCheckWorker: Error checking for updates")
            self.finished.emit(False, {}, str(exception))


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
            logger.info(
                f"DownloadWorker: thread started downloading '{self.download_url}'"
            )
            logger.info(
                f"DownloadWorker: writing downloaded chunks to '{self.save_path}'"
            )
            headers = {"User-Agent": "lan-streamer-updater"}
            response = requests.get(
                self.download_url, headers=headers, stream=True, timeout=25
            )
            logger.info(
                f"DownloadWorker: HTTP response status code: {response.status_code}, "
                f"content-length: {response.headers.get('content-length')}"
            )
            if response.status_code != 200:
                logger.error(f"DownloadWorker: HTTP Error {response.status_code}")
                self.finished.emit(False, f"HTTP Error {response.status_code}")
                return

            total_size_bytes = int(response.headers.get("content-length", 0))
            bytes_downloaded = 0

            with open(self.save_path, "wb") as file_object:
                for chunk in response.iter_content(chunk_size=8192):
                    if self._is_cancelled:
                        logger.info(
                            "DownloadWorker: download cancelled by user request"
                        )
                        self.finished.emit(False, "Download cancelled")
                        return
                    if chunk:
                        file_object.write(chunk)
                        bytes_downloaded += len(chunk)
                        self.progress.emit(bytes_downloaded, total_size_bytes)

            logger.info(
                f"DownloadWorker: download successfully finished, file size: {bytes_downloaded} bytes"
            )
            self.finished.emit(True, str(self.save_path))
        except Exception as exception:
            logger.exception("DownloadWorker: Error downloading update")
            self.finished.emit(False, str(exception))

    def cancel(self) -> None:
        self._is_cancelled = True


class InstallWorker(QThread):
    """
    Background worker thread that atomically replaces the currently installed
    executable with a newly downloaded binary.

    The replacement is performed with ``os.replace()``, which is an atomic
    rename on POSIX systems and works even while the old binary is running
    (the kernel keeps the old inode open; only the directory entry changes).
    The replacement source and destination **must** reside on the same
    filesystem to avoid a cross-device ``OSError`` — callers should place the
    downloaded file in the same directory as the install target.

    After a successful replace the new file is made executable
    (``rwxr-xr-x`` permissions) so the OS can run it directly.

    Signals
    -------
    finished : Signal(bool, str)
        Emitted when the install attempt completes.
        First argument is ``True`` on success, ``False`` on failure.
        Second argument is an empty string on success or a human-readable
        error description on failure.
    """

    finished = Signal(bool, str)  # success, error_message

    def __init__(self, downloaded_path: str, install_target_path: str) -> None:
        super().__init__()
        self.downloaded_path = downloaded_path
        self.install_target_path = install_target_path

    def run(self) -> None:
        logger.info(
            "InstallWorker: thread started to replace '%s' with '%s'",
            self.install_target_path,
            self.downloaded_path,
        )
        try:
            if not os.path.isfile(self.downloaded_path):
                error_message = f"Downloaded binary not found: '{self.downloaded_path}'"
                logger.error(f"InstallWorker: {error_message}")
                self.finished.emit(False, error_message)
                return

            # chmod before replace so the new inode is executable immediately
            # after the directory entry is updated.
            executable_mode = (
                stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IXUSR
                | stat.S_IRGRP
                | stat.S_IXGRP
                | stat.S_IROTH
                | stat.S_IXOTH
            )
            logger.info(
                f"InstallWorker: setting permissions to 0o755 (rwxr-xr-x) for '{self.downloaded_path}'"
            )
            os.chmod(self.downloaded_path, executable_mode)

            logger.info(
                f"InstallWorker: performing atomic replacement of '{self.install_target_path}' "
                f"with '{self.downloaded_path}'"
            )
            os.replace(self.downloaded_path, self.install_target_path)

            logger.info(
                "InstallWorker: executable successfully replaced at '%s'",
                self.install_target_path,
            )
            self.finished.emit(True, "")
        except Exception as exception:
            error_message = str(exception)
            logger.exception(
                "InstallWorker: failed to replace executable — %s", error_message
            )
            self.finished.emit(False, error_message)
