from unittest.mock import patch, MagicMock
import sys

# Mock ctypes before importing WakeLock to avoid issues on non-Windows platforms
mock_ctypes = MagicMock()
sys.modules["ctypes"] = mock_ctypes

from lan_streamer.wakelock import WakeLock  # noqa: E402


def test_wakelock_linux_gdbus() -> None:
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


def test_wakelock_windows() -> None:
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


def test_wakelock_macos() -> None:
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


def test_wakelock_inhibit_already_active_is_a_noop() -> None:
    """Calling inhibit twice must not re-enter the underlying platform call."""
    wakelock = WakeLock()
    with patch("sys.platform", "linux"):
        with patch("subprocess.check_output", return_value="(uint32 1,)") as mock_check:
            wakelock.inhibit("first")
            assert wakelock.active is True
            call_count_after_first = mock_check.call_count

            # Second inhibit — should be a no-op
            wakelock.inhibit("second")
            assert mock_check.call_count == call_count_after_first


def test_wakelock_uninhibit_when_not_active_is_a_noop() -> None:
    """Calling uninhibit when not active must not call any platform API."""
    wakelock = WakeLock()
    with patch("subprocess.run") as mock_run:
        wakelock.uninhibit()
        mock_run.assert_not_called()
    assert wakelock.active is False


def test_wakelock_linux_xdg_fallback() -> None:
    """When gdbus fails, _inhibit_linux must fall back to xdg-screensaver."""
    wakelock = WakeLock()
    with patch("sys.platform", "linux"):
        with (
            patch("subprocess.check_output", side_effect=FileNotFoundError("no gdbus")),
            patch("subprocess.Popen") as mock_popen,
        ):
            wakelock.inhibit("test fallback")
            mock_popen.assert_called_once()
            assert "xdg-screensaver" in mock_popen.call_args[0][0]


def test_wakelock_linux_uninhibit_no_cookie() -> None:
    """Uninhibiting without a gdbus cookie should still run xdg-screensaver resume."""
    wakelock = WakeLock()
    wakelock.active = True
    wakelock._cookie = None  # No cookie was stored

    with patch("sys.platform", "linux"):
        with patch("subprocess.run") as mock_run:
            wakelock.uninhibit()
            # gdbus UnInhibit must NOT have been called (no cookie)
            for call_args in mock_run.call_args_list:
                cmd = call_args[0][0] if call_args[0] else []
                assert "UnInhibit" not in " ".join(cmd)
            # xdg-screensaver resume must have been called
            assert any(
                "xdg-screensaver" in " ".join(c[0][0] if c[0] else [])
                for c in mock_run.call_args_list
            )
    assert wakelock.active is False


def test_wakelock_macos_kill_on_terminate_timeout() -> None:
    """If terminate raises an exception, uninhibit must attempt kill."""
    wakelock = WakeLock()
    mock_process = MagicMock()
    mock_process.terminate.side_effect = Exception("terminate failed")

    wakelock._process = mock_process
    wakelock.active = True

    with patch("sys.platform", "darwin"):
        wakelock.uninhibit()

    mock_process.kill.assert_called_once()
    assert wakelock._process is None
    assert wakelock.active is False


def test_wakelock_inhibit_exception_catch() -> None:
    wakelock = WakeLock()
    with patch("sys.platform", "linux"):
        with patch.object(
            wakelock, "_inhibit_linux", side_effect=Exception("mock error")
        ):
            wakelock.inhibit()
            assert wakelock.active is False


def test_wakelock_uninhibit_exception_catch() -> None:
    wakelock = WakeLock()
    wakelock.active = True
    with patch("sys.platform", "linux"):
        with patch.object(
            wakelock, "_uninhibit_linux", side_effect=Exception("mock error")
        ):
            wakelock.uninhibit()
            # It logs and catches, active is not unset if it completely failed before setting active=False
            assert wakelock.active is True


def test_wakelock_linux_xdg_exception() -> None:
    wakelock = WakeLock()
    with patch("sys.platform", "linux"):
        with patch("subprocess.check_output", side_effect=FileNotFoundError()):
            with patch("subprocess.Popen", side_effect=Exception("xdg failed")):
                wakelock.inhibit()
                assert wakelock.active is True


def test_wakelock_linux_uninhibit_exceptions() -> None:
    wakelock = WakeLock()
    wakelock._cookie = "123"
    with patch("sys.platform", "linux"):
        # both gdbus and xdg-screensaver fail
        with patch("subprocess.run", side_effect=Exception("fail")):
            wakelock._uninhibit_linux()
            assert wakelock._cookie is None


def test_wakelock_windows_exceptions() -> None:
    wakelock = WakeLock()
    with patch("sys.platform", "win32"):
        mock_ctypes.windll.kernel32.SetThreadExecutionState.side_effect = Exception(
            "win fail"
        )
        wakelock._inhibit_windows()
        wakelock._uninhibit_windows()
        mock_ctypes.windll.kernel32.SetThreadExecutionState.side_effect = None


def test_wakelock_macos_exceptions() -> None:
    wakelock = WakeLock()
    with patch("sys.platform", "darwin"):
        with patch("subprocess.Popen", side_effect=Exception("mac fail")):
            wakelock._inhibit_macos("test")
            assert wakelock._process is None

        mock_process = MagicMock()
        mock_process.terminate.side_effect = Exception("term fail")
        mock_process.kill.side_effect = Exception("kill fail")
        wakelock._process = mock_process
        wakelock._uninhibit_macos()
        assert wakelock._process is None
