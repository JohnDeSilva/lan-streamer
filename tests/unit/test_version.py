import runpy
import sys
import pytest
from unittest.mock import patch
from lan_streamer import __version__


@pytest.mark.parametrize("flag", ["--version", "-v", "-V"])
def test_entrypoint_version_flags(capsys, flag):
    """Test that entrypoint.py exits with the correct version string for all supported flags."""
    with patch.object(sys, "argv", ["src/entrypoint.py", flag]):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path("src/entrypoint.py", run_name="__main__")
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == f"lan-streamer {__version__}"


@pytest.mark.parametrize("flag", ["--version", "-v", "-V"])
def test_main_version_flags(capsys, flag):
    """Test that main() in main.py exits with the correct version string for all supported flags."""
    from lan_streamer.main import main

    with patch.object(sys, "argv", ["lan_streamer/main.py", flag]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == f"lan-streamer {__version__}"
