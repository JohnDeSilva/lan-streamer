import sys
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication

# Mock the modules before importing ui
sys.modules["lan_streamer.db"] = MagicMock()
sys.modules["lan_streamer.config"] = MagicMock()
sys.modules["lan_streamer.scanner"] = MagicMock()
sys.modules["lan_streamer.player"] = MagicMock()
sys.modules["lan_streamer.jellyfin"] = MagicMock()
sys.modules["lan_streamer.tmdb"] = MagicMock()
sys.modules["lan_streamer.delegates"] = MagicMock()


def test_repro() -> None:
    print("repro test started")
    # This was previously an invalidly indented run method snippet
    pass


if __name__ == "__main__":
    app = QApplication([])
    test_repro()
