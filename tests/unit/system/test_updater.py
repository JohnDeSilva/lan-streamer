import stat
from unittest.mock import patch, mock_open, MagicMock
import requests

from lan_streamer.system.updater import (
    parse_version,
    get_linux_distro,
    get_target_asset_name,
    UpdateCheckWorker,
    DownloadWorker,
    InstallWorker,
)


def test_parse_version() -> None:
    assert parse_version("0.26.0") == (0, 26, 0)
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("V3.4.5-alpha") == (3, 4, 5)
    assert parse_version("  v2.0.1  ") == (2, 0, 1)
    assert parse_version("invalid") == (0,)


def test_get_linux_distro() -> None:
    # Test Fedora matching
    fedora_release = 'ID="fedora"\nID_LIKE="rhel centos"'
    with (
        patch("lan_streamer.system.updater.os.path.exists", return_value=True),
        patch("lan_streamer.system.updater.open", mock_open(read_data=fedora_release)),
    ):
        assert get_linux_distro() == "fedora"

    # Test Ubuntu matching via ID_LIKE
    ubuntu_like = 'ID="linuxmint"\nID_LIKE="ubuntu debian"'
    with (
        patch("lan_streamer.system.updater.os.path.exists", return_value=True),
        patch("lan_streamer.system.updater.open", mock_open(read_data=ubuntu_like)),
    ):
        assert get_linux_distro() == "linuxmint"

    # Test non-existent file fallback
    with patch("lan_streamer.system.updater.os.path.exists", return_value=False):
        assert get_linux_distro() == "ubuntu"

    # Test Exception fallback
    with (
        patch("lan_streamer.system.updater.os.path.exists", return_value=True),
        patch("lan_streamer.system.updater.open", side_effect=PermissionError),
    ):
        assert get_linux_distro() == "ubuntu"


def test_get_target_asset_name() -> None:
    # Test Windows
    with patch("sys.platform", "win32"):
        assert get_target_asset_name() == "lan-streamer-windows.exe"

    # Test Darwin/Mac
    with patch("sys.platform", "darwin"):
        assert get_target_asset_name() == "lan-streamer-macos.dmg"

    # Test Linux Fedora
    with (
        patch("sys.platform", "linux"),
        patch("lan_streamer.system.updater.get_linux_distro", return_value="fedora"),
    ):
        assert get_target_asset_name() == "lan-streamer-fedora"

    # Test Linux Ubuntu
    with (
        patch("sys.platform", "linux"),
        patch("lan_streamer.system.updater.get_linux_distro", return_value="ubuntu"),
    ):
        assert get_target_asset_name() == "lan-streamer-ubuntu"


def test_update_check_worker_no_update(qtbot) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "tag_name": "v0.26.0",
        "body": "No changes",
        "assets": [],
    }

    with (
        patch("requests.get", return_value=mock_response),
        patch("lan_streamer.__version__", "0.26.0"),
    ):
        worker = UpdateCheckWorker()

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, release_info, error_msg = blocker.args
        assert success is True
        assert release_info == {}
        assert error_msg == ""


def test_update_check_worker_has_update(qtbot) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "tag_name": "v0.27.0",
        "body": "Cool release notes",
        "assets": [
            {
                "name": "lan-streamer-windows.exe",
                "browser_download_url": "https://example.invalid/download/win.exe",
            }
        ],
    }

    with (
        patch("requests.get", return_value=mock_response),
        patch("lan_streamer.__version__", "0.26.0"),
        patch("sys.platform", "win32"),
    ):
        worker = UpdateCheckWorker()

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, release_info, error_msg = blocker.args
        assert success is True
        assert release_info["version"] == "v0.27.0"
        assert release_info["release_notes"] == "Cool release notes"
        assert (
            release_info["download_url"] == "https://example.invalid/download/win.exe"
        )
        assert error_msg == ""


def test_update_check_worker_http_error(qtbot) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("requests.get", return_value=mock_response):
        worker = UpdateCheckWorker()

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, release_info, error_msg = blocker.args
        assert success is False
        assert "HTTP Error 404" in error_msg


def test_update_check_worker_exception(qtbot) -> None:
    with patch("requests.get", side_effect=requests.RequestException("Timeout")):
        worker = UpdateCheckWorker()

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, release_info, error_msg = blocker.args
        assert success is False
        assert "Timeout" in error_msg


def test_download_worker_success(qtbot, tmp_path) -> None:
    save_path = tmp_path / "update.exe"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-length": "16"}
    mock_response.iter_content.return_value = [b"chunk1__", b"chunk2__"]

    with patch("requests.get", return_value=mock_response):
        worker = DownloadWorker("https://example.invalid/update.exe", str(save_path))

        progress_signals = []
        worker.progress.connect(
            lambda cur, total: progress_signals.append((cur, total))
        )

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, path_or_err = blocker.args
        assert success is True
        assert path_or_err == str(save_path)
        assert save_path.read_bytes() == b"chunk1__chunk2__"
        assert len(progress_signals) == 2
        assert progress_signals[0] == (8, 16)
        assert progress_signals[1] == (16, 16)


def test_download_worker_cancelled(qtbot, tmp_path) -> None:
    save_path = tmp_path / "update.exe"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-length": "8"}

    # Yield first chunk, then worker will be cancelled
    def chunk_generator(*args, **kwargs):
        yield b"chunk1__"
        worker.cancel()
        yield b"chunk2__"

    mock_response.iter_content = chunk_generator

    with patch("requests.get", return_value=mock_response):
        worker = DownloadWorker("https://example.invalid/update.exe", str(save_path))

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, path_or_err = blocker.args
        assert success is False
        assert "cancelled" in path_or_err.lower()


def test_update_check_worker_rc_no_update(qtbot) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "tag_name": "v0.26.0",
            "body": "Stable",
            "draft": False,
            "assets": [],
        }
    ]

    with (
        patch("requests.get", return_value=mock_response),
        patch("lan_streamer.__version__", "0.26.0"),
    ):
        worker = UpdateCheckWorker(release_channel="rc")

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, release_info, error_msg = blocker.args
        assert success is True
        assert release_info == {}
        assert error_msg == ""


def test_update_check_worker_rc_has_update(qtbot) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "tag_name": "v0.27.0-rc.1",
            "body": "RC release notes",
            "draft": False,
            "assets": [
                {
                    "name": "lan-streamer-windows.exe",
                    "browser_download_url": "https://example.invalid/download/rc.exe",
                }
            ],
        }
    ]

    with (
        patch("requests.get", return_value=mock_response),
        patch("lan_streamer.__version__", "0.26.0"),
        patch("sys.platform", "win32"),
    ):
        worker = UpdateCheckWorker(release_channel="rc")

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, release_info, error_msg = blocker.args
        assert success is True
        assert release_info["version"] == "v0.27.0-rc.1"
        assert release_info["release_notes"] == "RC release notes"
        assert release_info["download_url"] == "https://example.invalid/download/rc.exe"
        assert error_msg == ""


def test_update_check_worker_rc_picks_newest(qtbot) -> None:
    """RC channel should pick the newest version across all releases."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "tag_name": "v0.27.0-rc.1",
            "body": "RC",
            "draft": False,
            "assets": [
                {
                    "name": "lan-streamer-windows.exe",
                    "browser_download_url": "https://example.invalid/download/rc.exe",
                }
            ],
        },
        {
            "tag_name": "v0.26.0",
            "body": "Stable",
            "draft": False,
            "assets": [
                {
                    "name": "lan-streamer-windows.exe",
                    "browser_download_url": "https://example.invalid/download/stable.exe",
                }
            ],
        },
    ]

    with (
        patch("requests.get", return_value=mock_response),
        patch("lan_streamer.__version__", "0.25.0"),
        patch("sys.platform", "win32"),
    ):
        worker = UpdateCheckWorker(release_channel="rc")

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, release_info, error_msg = blocker.args
        assert success is True
        assert release_info["version"] == "v0.27.0-rc.1"
        assert release_info["download_url"] == "https://example.invalid/download/rc.exe"


def test_update_check_worker_rc_skips_drafts(qtbot) -> None:
    """RC channel should skip draft releases."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "tag_name": "v99.0.0-draft",
            "body": "Draft",
            "draft": True,
            "assets": [
                {
                    "name": "lan-streamer-windows.exe",
                    "browser_download_url": "https://example.invalid/download/draft.exe",
                }
            ],
        },
        {
            "tag_name": "v0.26.0",
            "body": "Stable",
            "draft": False,
            "assets": [
                {
                    "name": "lan-streamer-windows.exe",
                    "browser_download_url": "https://example.invalid/download/stable.exe",
                }
            ],
        },
    ]

    with (
        patch("requests.get", return_value=mock_response),
        patch("lan_streamer.__version__", "0.25.0"),
        patch("sys.platform", "win32"),
    ):
        worker = UpdateCheckWorker(release_channel="rc")

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, release_info, error_msg = blocker.args
        assert success is True
        assert release_info["version"] == "v0.26.0"
        assert (
            release_info["download_url"]
            == "https://example.invalid/download/stable.exe"
        )


def test_update_check_worker_rc_prefers_stable_over_prerelease(qtbot) -> None:
    """RC channel should prefer stable over prerelease at the same base version."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "tag_name": "v0.27.0-rc.1",
            "body": "RC release",
            "draft": False,
            "assets": [
                {
                    "name": "lan-streamer-windows.exe",
                    "browser_download_url": "https://example.invalid/download/rc.exe",
                }
            ],
        },
        {
            "tag_name": "v0.27.0",
            "body": "Stable release",
            "draft": False,
            "assets": [
                {
                    "name": "lan-streamer-windows.exe",
                    "browser_download_url": "https://example.invalid/download/stable.exe",
                }
            ],
        },
    ]

    with (
        patch("requests.get", return_value=mock_response),
        patch("lan_streamer.__version__", "0.26.0"),
        patch("sys.platform", "win32"),
    ):
        worker = UpdateCheckWorker(release_channel="rc")

        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()

        success, release_info, error_msg = blocker.args
        assert success is True
        assert release_info["version"] == "v0.27.0"
        assert (
            release_info["download_url"]
            == "https://example.invalid/download/stable.exe"
        )


# ---------------------------------------------------------------------------
# InstallWorker tests
# ---------------------------------------------------------------------------


def test_install_worker_success(qtbot, tmp_path) -> None:
    """Downloaded binary is atomically moved to the target path and made executable."""
    downloaded_binary = tmp_path / "lan-streamer-ubuntu.new"
    downloaded_binary.write_bytes(b"new-binary-content")

    install_target = tmp_path / "lan-streamer-ubuntu"
    install_target.write_bytes(b"old-binary-content")

    worker = InstallWorker(
        downloaded_path=str(downloaded_binary),
        install_target_path=str(install_target),
    )

    with qtbot.waitSignal(worker.finished) as blocker:
        worker.start()

    success, error_message = blocker.args
    assert success is True
    assert error_message == ""

    # Target should contain the new content after atomic replace
    assert install_target.read_bytes() == b"new-binary-content"

    # Target must be executable by owner, group, and other
    mode = install_target.stat().st_mode
    assert mode & stat.S_IXUSR, "Owner execute bit must be set"
    assert mode & stat.S_IXGRP, "Group execute bit must be set"
    assert mode & stat.S_IXOTH, "Other execute bit must be set"


def test_install_worker_downloaded_file_missing(qtbot, tmp_path) -> None:
    """Emits failure when the downloaded file does not exist."""
    install_target = tmp_path / "lan-streamer-ubuntu"
    install_target.write_bytes(b"old-binary-content")

    worker = InstallWorker(
        downloaded_path=str(tmp_path / "nonexistent.bin"),
        install_target_path=str(install_target),
    )

    with qtbot.waitSignal(worker.finished) as blocker:
        worker.start()

    success, error_message = blocker.args
    assert success is False
    assert "not found" in error_message.lower()

    # Original target must be untouched
    assert install_target.read_bytes() == b"old-binary-content"


def test_install_worker_replace_raises_os_error(qtbot, tmp_path) -> None:
    """Emits failure when os.replace raises an OSError."""
    downloaded_binary = tmp_path / "lan-streamer-ubuntu.new"
    downloaded_binary.write_bytes(b"new-binary-content")

    install_target = tmp_path / "lan-streamer-ubuntu"
    install_target.write_bytes(b"old-binary-content")

    worker = InstallWorker(
        downloaded_path=str(downloaded_binary),
        install_target_path=str(install_target),
    )

    with (
        patch(
            "lan_streamer.system.updater.os.replace",
            side_effect=OSError("cross-device link"),
        ),
        qtbot.waitSignal(worker.finished) as blocker,
    ):
        worker.start()

    success, error_message = blocker.args
    assert success is False
    assert "cross-device link" in error_message


def test_install_worker_chmod_raises_os_error(qtbot, tmp_path) -> None:
    """Emits failure when os.chmod raises an OSError after the replace."""
    downloaded_binary = tmp_path / "lan-streamer-ubuntu.new"
    downloaded_binary.write_bytes(b"new-binary-content")

    install_target = tmp_path / "lan-streamer-ubuntu"
    install_target.write_bytes(b"old-binary-content")

    worker = InstallWorker(
        downloaded_path=str(downloaded_binary),
        install_target_path=str(install_target),
    )

    with (
        patch(
            "lan_streamer.system.updater.os.chmod",
            side_effect=OSError("permission denied"),
        ),
        qtbot.waitSignal(worker.finished) as blocker,
    ):
        worker.start()

    success, error_message = blocker.args
    assert success is False
    assert "permission denied" in error_message
