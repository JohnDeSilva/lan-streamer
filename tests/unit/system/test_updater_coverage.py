"""Extended coverage tests for lan_streamer.system.updater.

Targets the 37 currently-uncovered lines to push coverage above 95%.
All tests mock network calls and filesystem access — no real I/O.
"""

from io import StringIO
from unittest.mock import MagicMock, patch

import requests

from lan_streamer.system.updater import (
    DownloadWorker,
    InstallWorker,
    UpdateCheckWorker,
    get_linux_distro,
    get_target_asset_name,
    is_prerelease_tag,
    parse_base_version,
    parse_comparable_version,
    parse_version,
)


# -----------------------------------------------------------------------
# parse_version
# -----------------------------------------------------------------------


class TestParseVersion:
    def test_standard_release(self):
        assert parse_version("0.26.0") == (0, 26, 0)

    def test_v_prefix(self):
        assert parse_version("v1.2.3") == (1, 2, 3)

    def test_uppercase_v(self):
        assert parse_version("V3.4.5") == (3, 4, 5)

    def test_strips_whitespace(self):
        assert parse_version("  v2.0.1  ") == (2, 0, 1)

    def test_non_digit_parts_become_zero(self):
        assert parse_version("invalid") == (0,)

    def test_single_number(self):
        assert parse_version("7") == (7,)

    def test_long_version(self):
        assert parse_version("v1.2.3.4") == (1, 2, 3, 4)

    def test_suffix_stripped_by_digit_extraction(self):
        assert parse_version("v1.0.0-rc.1") == (1, 0, 0, 1)

    def test_empty_string(self):
        assert parse_version("") == (0,)


# -----------------------------------------------------------------------
# get_linux_distro  (covers lines 36-40: ID_LIKE parsing with quotes)
# -----------------------------------------------------------------------


class TestGetLinuxDistro:
    def test_id_line_direct_match(self):
        release = 'ID=ubuntu\nVERSION="22.04"\n'
        with (
            patch("lan_streamer.system.updater.os.path.exists", return_value=True),
            patch("lan_streamer.system.updater.open", return_value=StringIO(release)),
        ):
            assert get_linux_distro() == "ubuntu"

    def test_id_line_with_quotes(self):
        release = 'ID="fedora"\n'
        with (
            patch("lan_streamer.system.updater.os.path.exists", return_value=True),
            patch("lan_streamer.system.updater.open", return_value=StringIO(release)),
        ):
            assert get_linux_distro() == "fedora"

    def test_id_like_fedora_rhel(self):
        """Covers lines 36-38: ID_LIKE containing fedora/rhel.
        ID_LIKE must appear before ID= so it is evaluated first.
        """
        release = 'ID_LIKE="rhel fedora"\nID=linuxmint\n'
        with (
            patch("lan_streamer.system.updater.os.path.exists", return_value=True),
            patch("lan_streamer.system.updater.open", return_value=StringIO(release)),
        ):
            assert get_linux_distro() == "fedora"

    def test_id_like_centos(self):
        """Covers line 37: centos in ID_LIKE."""
        release = 'ID_LIKE="centos"\n'
        with (
            patch("lan_streamer.system.updater.os.path.exists", return_value=True),
            patch("lan_streamer.system.updater.open", return_value=StringIO(release)),
        ):
            assert get_linux_distro() == "fedora"

    def test_id_like_ubuntu_debian(self):
        """Covers lines 39-40: ID_LIKE containing ubuntu/debian."""
        release = 'ID_LIKE="ubuntu debian"\n'
        with (
            patch("lan_streamer.system.updater.os.path.exists", return_value=True),
            patch("lan_streamer.system.updater.open", return_value=StringIO(release)),
        ):
            assert get_linux_distro() == "ubuntu"

    def test_no_id_no_id_like(self):
        """No ID= or ID_LIKE= lines at all."""
        release = 'NAME="Some OS"\nVERSION="1.0"\n'
        with (
            patch("lan_streamer.system.updater.os.path.exists", return_value=True),
            patch("lan_streamer.system.updater.open", return_value=StringIO(release)),
        ):
            assert get_linux_distro() == "ubuntu"

    def test_file_not_found(self):
        with patch("lan_streamer.system.updater.os.path.exists", return_value=False):
            assert get_linux_distro() == "ubuntu"

    def test_read_exception(self):
        with (
            patch("lan_streamer.system.updater.os.path.exists", return_value=True),
            patch("lan_streamer.system.updater.open", side_effect=IOError("denied")),
        ):
            assert get_linux_distro() == "ubuntu"


# -----------------------------------------------------------------------
# parse_comparable_version  (covers lines 66-72, 90-91)
# -----------------------------------------------------------------------


class TestParseComparableVersion:
    def test_stable_release(self):
        assert parse_comparable_version("v0.26.0") == (0, 26, 0, 2, 0, 0)

    def test_release_candidate(self):
        assert parse_comparable_version("v0.27.0-rc.1") == (0, 27, 0, 1, 1, 0)

    def test_rc_without_number_falls_to_fallback(self):
        """'1.0.0rc' doesn't match the regex (number required after type),
        so it falls through to the fallback path."""
        assert parse_comparable_version("1.0.0rc") == (1, 0, 0, 2, 0, 0)

    def test_alpha_suffix(self):
        """Covers lines 90-91: alpha branch."""
        assert parse_comparable_version("v1.0.0-alpha.2") == (1, 0, 0, 0, 2, 0)

    def test_alpha_short_suffix(self):
        """Covers lines 90-91: 'a' branch."""
        assert parse_comparable_version("v1.0.0a1") == (1, 0, 0, 0, 1, 0)

    def test_beta_suffix(self):
        """Covers lines 90-91: beta branch."""
        assert parse_comparable_version("v1.0.0-beta.3") == (1, 0, 0, 0, 3, 0)

    def test_beta_short_suffix(self):
        """Covers lines 90-91: 'b' branch."""
        assert parse_comparable_version("v1.0.0b1") == (1, 0, 0, 0, 1, 0)

    def test_dev_suffix(self):
        """Covers lines 90-91: dev branch."""
        assert parse_comparable_version("v2.0.0-dev.1") == (2, 0, 0, 0, 1, 0)

    def test_post_suffix(self):
        """Covers lines 90-91: post branch."""
        assert parse_comparable_version("v1.0.0-post.1") == (1, 0, 0, 0, 1, 0)

    def test_preview_suffix(self):
        """Covers lines 90-91: preview branch."""
        assert parse_comparable_version("v3.0.0-preview.5") == (3, 0, 0, 0, 5, 0)

    def test_build_number(self):
        assert parse_comparable_version("v0.44.0rc0-2") == (0, 44, 0, 1, 0, 2)

    def test_fallback_non_matching_string(self):
        """Covers lines 66-72: regex doesn't match, fallback path."""
        result = parse_comparable_version("something-weird")
        assert result[3] == 2
        assert result[4] == 0
        assert result[5] == 0

    def test_fallback_single_part(self):
        """Fallback with a single numeric part."""
        result = parse_comparable_version("42")
        assert result[:3] == (42, 0, 0)
        assert result[3] == 2

    def test_fallback_two_parts(self):
        """Fallback with two dot-separated parts."""
        result = parse_comparable_version("1.2")
        assert result[:3] == (1, 2, 0)
        assert result[3] == 2

    def test_no_prerelease_type_stable(self):
        assert parse_comparable_version("1.2.3") == (1, 2, 3, 2, 0, 0)


# -----------------------------------------------------------------------
# parse_base_version
# -----------------------------------------------------------------------


class TestParseBaseVersion:
    def test_strips_rc_suffix(self):
        assert parse_base_version("v0.27.0-rc.1") == (0, 27, 0)

    def test_stable_version(self):
        assert parse_base_version("0.26.0") == (0, 26, 0)

    def test_alpha_version(self):
        assert parse_base_version("v1.0.0-alpha.2") == (1, 0, 0)


# -----------------------------------------------------------------------
# is_prerelease_tag
# -----------------------------------------------------------------------


class TestIsPrereleaseTag:
    def test_stable_is_not_prerelease(self):
        assert is_prerelease_tag("v0.26.0") is False

    def test_rc_is_prerelease(self):
        assert is_prerelease_tag("v0.27.0-rc.1") is True

    def test_alpha_is_prerelease(self):
        assert is_prerelease_tag("v1.0.0-alpha.1") is True

    def test_beta_is_prerelease(self):
        assert is_prerelease_tag("v1.0.0-beta.2") is True

    def test_dev_is_prerelease(self):
        assert is_prerelease_tag("v2.0.0-dev.1") is True


# -----------------------------------------------------------------------
# get_target_asset_name  (covers Linux branches)
# -----------------------------------------------------------------------


class TestGetTargetAssetName:
    def test_windows(self):
        with patch("sys.platform", "win32"):
            assert get_target_asset_name() == "lan-streamer-windows.exe"

    def test_darwin(self):
        with patch("sys.platform", "darwin"):
            assert get_target_asset_name() == "lan-streamer-macos.dmg"

    def test_linux_fedora(self):
        with (
            patch("sys.platform", "linux"),
            patch(
                "lan_streamer.system.updater.get_linux_distro", return_value="fedora"
            ),
        ):
            assert get_target_asset_name() == "lan-streamer-fedora"

    def test_linux_rhel(self):
        with (
            patch("sys.platform", "linux"),
            patch("lan_streamer.system.updater.get_linux_distro", return_value="rhel"),
        ):
            assert get_target_asset_name() == "lan-streamer-fedora"

    def test_linux_centos(self):
        with (
            patch("sys.platform", "linux"),
            patch(
                "lan_streamer.system.updater.get_linux_distro", return_value="centos"
            ),
        ):
            assert get_target_asset_name() == "lan-streamer-fedora"

    def test_linux_ubuntu(self):
        with (
            patch("sys.platform", "linux"),
            patch(
                "lan_streamer.system.updater.get_linux_distro", return_value="ubuntu"
            ),
        ):
            assert get_target_asset_name() == "lan-streamer-ubuntu"

    def test_linux_unknown_distro(self):
        with (
            patch("sys.platform", "linux"),
            patch("lan_streamer.system.updater.get_linux_distro", return_value="arch"),
        ):
            assert get_target_asset_name() == "lan-streamer-ubuntu"


# -----------------------------------------------------------------------
# UpdateCheckWorker._extract_release_data
# -----------------------------------------------------------------------


class TestExtractReleaseData:
    def test_extracts_valid_release(self):
        release = {
            "tag_name": "v0.27.0",
            "body": "Release notes",
            "assets": [
                {
                    "name": "lan-streamer-ubuntu",
                    "browser_download_url": "https://example.invalid/dl",
                }
            ],
        }
        with patch(
            "lan_streamer.system.updater.get_target_asset_name",
            return_value="lan-streamer-ubuntu",
        ):
            result = UpdateCheckWorker._extract_release_data(release)
        assert result is not None
        assert result["version"] == "v0.27.0"
        assert result["release_notes"] == "Release notes"
        assert result["download_url"] == "https://example.invalid/dl"

    def test_empty_tag_name_returns_none(self):
        """Covers line 159: tag_name is empty."""
        release = {"tag_name": "", "assets": []}
        assert UpdateCheckWorker._extract_release_data(release) is None

    def test_missing_tag_name_returns_none(self):
        release = {"assets": []}
        assert UpdateCheckWorker._extract_release_data(release) is None

    def test_no_matching_asset(self):
        release = {
            "tag_name": "v1.0.0",
            "body": "",
            "assets": [{"name": "unrelated.exe", "browser_download_url": "x"}],
        }
        with patch(
            "lan_streamer.system.updater.get_target_asset_name",
            return_value="lan-streamer-ubuntu",
        ):
            result = UpdateCheckWorker._extract_release_data(release)
        assert result is not None
        assert result["download_url"] == ""

    def test_missing_assets_key(self):
        release = {"tag_name": "v1.0.0", "body": "Notes"}
        with patch(
            "lan_streamer.system.updater.get_target_asset_name",
            return_value="lan-streamer-ubuntu",
        ):
            result = UpdateCheckWorker._extract_release_data(release)
        assert result is not None
        assert result["download_url"] == ""


# -----------------------------------------------------------------------
# UpdateCheckWorker._check_stable  (covers lines 195-197, 211-214)
# -----------------------------------------------------------------------


class TestCheckStable:
    def test_missing_tag_name_in_response(self, qtbot):
        """Covers lines 195-197: response has no tag_name."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"tag_name": "", "body": "", "assets": []}

        with patch("requests.get", return_value=mock_response):
            worker = UpdateCheckWorker()
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, release_info, error_msg = blocker.args
            assert success is False
            assert "missing tag_name" in error_msg.lower()

    def test_newer_version_but_no_matching_asset(self, qtbot):
        """Covers lines 211-214: newer version found but no asset for platform."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v99.0.0",
            "body": "New",
            "assets": [
                {
                    "name": "unrelated-binary",
                    "browser_download_url": "https://example.invalid/x",
                }
            ],
        }

        with (
            patch("requests.get", return_value=mock_response),
            patch("lan_streamer.__version__", "0.1.0"),
            patch(
                "lan_streamer.system.updater.get_target_asset_name",
                return_value="lan-streamer-ubuntu",
            ),
        ):
            worker = UpdateCheckWorker()
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, release_info, error_msg = blocker.args
            assert success is True
            assert release_info == {}

    def test_http_error(self, qtbot):
        mock_response = MagicMock()
        mock_response.status_code = 500
        with patch("requests.get", return_value=mock_response):
            worker = UpdateCheckWorker()
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, _, error_msg = blocker.args
            assert success is False
            assert "500" in error_msg


# -----------------------------------------------------------------------
# UpdateCheckWorker._check_rc  (covers lines 240-241, 245-247, 258,
#   277-282, 315-320)
# -----------------------------------------------------------------------


class TestCheckRC:
    def test_http_error(self, qtbot):
        """Covers lines 240-241: non-200 status code."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        with patch("requests.get", return_value=mock_response):
            worker = UpdateCheckWorker(release_channel="rc")
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, _, error_msg = blocker.args
            assert success is False
            assert "403" in error_msg

    def test_non_list_response(self, qtbot):
        """Covers lines 245-247: response is not a list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"not_a_list": True}
        with patch("requests.get", return_value=mock_response):
            worker = UpdateCheckWorker(release_channel="rc")
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, release_info, error_msg = blocker.args
            assert success is True
            assert release_info == {}

    def test_empty_releases_list(self, qtbot):
        """Covers lines 245-247: empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        with patch("requests.get", return_value=mock_response):
            worker = UpdateCheckWorker(release_channel="rc")
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, release_info, _ = blocker.args
            assert success is True
            assert release_info == {}

    def test_skips_release_with_empty_tag(self, qtbot):
        """Covers line 258: release with empty tag_name is skipped."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "tag_name": "",
                "body": "",
                "draft": False,
                "assets": [
                    {
                        "name": "lan-streamer-windows.exe",
                        "browser_download_url": "https://example.invalid/x",
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
                        "browser_download_url": "https://example.invalid/stable",
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
            success, release_info, _ = blocker.args
            assert success is True
            assert release_info["version"] == "v0.26.0"

    def test_prefers_stable_over_prerelease_same_base(self, qtbot):
        """Covers lines 270-276: existing prerelease replaced by stable."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "tag_name": "v1.0.0-beta.1",
                "body": "Beta",
                "draft": False,
                "assets": [
                    {
                        "name": "lan-streamer-windows.exe",
                        "browser_download_url": "https://example.invalid/beta",
                    }
                ],
            },
            {
                "tag_name": "v1.0.0",
                "body": "Stable",
                "draft": False,
                "assets": [
                    {
                        "name": "lan-streamer-windows.exe",
                        "browser_download_url": "https://example.invalid/stable",
                    }
                ],
            },
        ]
        with (
            patch("requests.get", return_value=mock_response),
            patch("lan_streamer.__version__", "0.9.0"),
            patch("sys.platform", "win32"),
        ):
            worker = UpdateCheckWorker(release_channel="rc")
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, release_info, _ = blocker.args
            assert success is True
            assert release_info["version"] == "v1.0.0"
            assert "stable" in release_info["download_url"]

    def test_same_prerelease_type_keeps_newer(self, qtbot):
        """Covers lines 277-282: same pre-release type, keeps newer version."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "tag_name": "v2.0.0-rc.1",
                "body": "RC1",
                "draft": False,
                "assets": [
                    {
                        "name": "lan-streamer-windows.exe",
                        "browser_download_url": "https://example.invalid/rc1",
                    }
                ],
            },
            {
                "tag_name": "v2.0.0-rc.3",
                "body": "RC3",
                "draft": False,
                "assets": [
                    {
                        "name": "lan-streamer-windows.exe",
                        "browser_download_url": "https://example.invalid/rc3",
                    }
                ],
            },
        ]
        with (
            patch("requests.get", return_value=mock_response),
            patch("lan_streamer.__version__", "1.9.0"),
            patch("sys.platform", "win32"),
        ):
            worker = UpdateCheckWorker(release_channel="rc")
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, release_info, _ = blocker.args
            assert success is True
            assert release_info["version"] == "v2.0.0-rc.3"

    def test_no_asset_skips_release(self, qtbot):
        """Release without matching asset is skipped."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "tag_name": "v5.0.0",
                "body": "",
                "draft": False,
                "assets": [],
            }
        ]
        with (
            patch("requests.get", return_value=mock_response),
            patch("lan_streamer.__version__", "4.0.0"),
            patch("sys.platform", "win32"),
        ):
            worker = UpdateCheckWorker(release_channel="rc")
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, release_info, _ = blocker.args
            assert success is True
            assert release_info == {}

    def test_best_version_not_newer_than_current(self, qtbot):
        """Covers lines 315-320: best release is not newer than current."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "tag_name": "v0.25.0",
                "body": "Old",
                "draft": False,
                "assets": [
                    {
                        "name": "lan-streamer-windows.exe",
                        "browser_download_url": "https://example.invalid/old",
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
            success, release_info, _ = blocker.args
            assert success is True
            assert release_info == {}

    def test_draft_releases_skipped(self, qtbot):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "tag_name": "v99.0.0",
                "body": "",
                "draft": True,
                "assets": [
                    {
                        "name": "lan-streamer-windows.exe",
                        "browser_download_url": "https://example.invalid/x",
                    }
                ],
            }
        ]
        with (
            patch("requests.get", return_value=mock_response),
            patch("lan_streamer.__version__", "0.1.0"),
            patch("sys.platform", "win32"),
        ):
            worker = UpdateCheckWorker(release_channel="rc")
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, release_info, _ = blocker.args
            assert success is True
            assert release_info == {}


# -----------------------------------------------------------------------
# DownloadWorker  (covers lines 367-369, 376-381, 391-393)
# -----------------------------------------------------------------------


class TestDownloadWorker:
    def test_http_error_emits_failure(self, qtbot, tmp_path):
        """Covers lines 367-369: non-200 status during download."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {}
        mock_response.iter_content.return_value = []

        with patch("requests.get", return_value=mock_response):
            worker = DownloadWorker(
                "https://example.invalid/update", str(tmp_path / "out.bin")
            )
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, error_msg = blocker.args
            assert success is False
            assert "404" in error_msg

    def test_cancel_during_chunk_iteration(self, qtbot, tmp_path):
        """Covers lines 376-381: cancel flag checked between chunks."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-length": "16"}

        chunks = iter([b"first_chunk____"])

        def fake_iter_content(chunk_size=8192):
            yield from chunks

        mock_response.iter_content = fake_iter_content

        with patch("requests.get", return_value=mock_response):
            worker = DownloadWorker(
                "https://example.invalid/update", str(tmp_path / "out.bin")
            )
            worker.cancel()

            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, error_msg = blocker.args
            assert success is False
            assert "cancel" in error_msg.lower()

    def test_exception_during_download(self, qtbot, tmp_path):
        """Covers lines 391-393: exception handler in run()."""
        with patch("requests.get", side_effect=requests.ConnectionError("refused")):
            worker = DownloadWorker(
                "https://example.invalid/update", str(tmp_path / "out.bin")
            )
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, error_msg = blocker.args
            assert success is False
            assert "refused" in error_msg

    def test_successful_download(self, qtbot, tmp_path):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-length": "4"}
        mock_response.iter_content.return_value = [b"data"]

        with patch("requests.get", return_value=mock_response):
            worker = DownloadWorker(
                "https://example.invalid/update", str(tmp_path / "out.bin")
            )
            with qtbot.waitSignal(worker.finished) as blocker:
                worker.start()
            success, path_or_err = blocker.args
            assert success is True
            assert path_or_err == str(tmp_path / "out.bin")

    def test_cancel_sets_flag(self):
        worker = DownloadWorker("https://example.invalid/x", "/tmp/x")
        assert worker._is_cancelled is False
        worker.cancel()
        assert worker._is_cancelled is True


# -----------------------------------------------------------------------
# InstallWorker edge cases
# -----------------------------------------------------------------------


class TestInstallWorker:
    def test_missing_source(self, qtbot, tmp_path):
        worker = InstallWorker(
            downloaded_path=str(tmp_path / "missing"),
            install_target_path=str(tmp_path / "target"),
        )
        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()
        success, msg = blocker.args
        assert success is False
        assert "not found" in msg.lower()

    def test_successful_replace(self, qtbot, tmp_path):
        src = tmp_path / "new.bin"
        src.write_bytes(b"new")
        dst = tmp_path / "old.bin"
        dst.write_bytes(b"old")

        worker = InstallWorker(str(src), str(dst))
        with qtbot.waitSignal(worker.finished) as blocker:
            worker.start()
        success, msg = blocker.args
        assert success is True
        assert dst.read_bytes() == b"new"

    def test_os_replace_error(self, qtbot, tmp_path):
        src = tmp_path / "new.bin"
        src.write_bytes(b"new")
        dst = tmp_path / "old.bin"
        dst.write_bytes(b"old")

        worker = InstallWorker(str(src), str(dst))
        with (
            patch(
                "lan_streamer.system.updater.os.replace",
                side_effect=OSError("cross-device"),
            ),
            qtbot.waitSignal(worker.finished) as blocker,
        ):
            worker.start()
        success, msg = blocker.args
        assert success is False
        assert "cross-device" in msg

    def test_os_chmod_error(self, qtbot, tmp_path):
        src = tmp_path / "new.bin"
        src.write_bytes(b"new")
        dst = tmp_path / "old.bin"
        dst.write_bytes(b"old")

        worker = InstallWorker(str(src), str(dst))
        with (
            patch("lan_streamer.system.updater.os.chmod", side_effect=OSError("perm")),
            qtbot.waitSignal(worker.finished) as blocker,
        ):
            worker.start()
        success, msg = blocker.args
        assert success is False
        assert "perm" in msg
