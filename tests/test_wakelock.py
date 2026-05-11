from unittest.mock import patch, MagicMock
import sys

# Mock ctypes before importing WakeLock to avoid issues on non-Windows platforms
mock_ctypes = MagicMock()
sys.modules["ctypes"] = mock_ctypes

from lan_streamer.wakelock import WakeLock  # noqa: E402


def test_wakelock_linux_gdbus():
    wakelock = WakeLock()
    with patch("sys.platform", "linux"):
        with patch("subprocess.check_output") as mock_check:
            mock_check.return_value = "(uint32 12345,)"
            wakelock.inhibit("test")
            assert wakelock.active is True
            assert wakelock._cookie == "12345"

            with patch("subprocess.run") as mock_run:
                wakelock.uninhibit()
                assert wakelock.active is False
                assert wakelock._cookie is None
                mock_run.assert_called()


def test_wakelock_windows():
    wakelock = WakeLock()
    with patch("sys.platform", "win32"):
        # Reset mock to ensure a clean state
        mock_ctypes.windll.kernel32.SetThreadExecutionState.reset_mock()

        wakelock.inhibit()
        assert wakelock.active is True
        mock_ctypes.windll.kernel32.SetThreadExecutionState.assert_called_with(
            0x80000003
        )

        wakelock.uninhibit()
        assert wakelock.active is False
        mock_ctypes.windll.kernel32.SetThreadExecutionState.assert_called_with(
            0x80000000
        )


def test_wakelock_macos():
    wakelock = WakeLock()
    with patch("sys.platform", "darwin"):
        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_popen.return_value = mock_process

            wakelock.inhibit()
            assert wakelock.active is True
            mock_popen.assert_called()

            wakelock.uninhibit()
            assert wakelock.active is False
            mock_process.terminate.assert_called()
