from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication


def test_repro() -> None:
    print("repro test started")
    # Mock the modules before importing ui
    mocks = {
        "lan_streamer.db": MagicMock(),
        "lan_streamer.system.config": MagicMock(),
        "lan_streamer.scanner": MagicMock(),
        "lan_streamer.playback.player": MagicMock(),
        "lan_streamer.providers.jellyfin": MagicMock(),
        "lan_streamer.providers.tmdb": MagicMock(),
        "lan_streamer.delegates": MagicMock(),
    }
    with patch.dict("sys.modules", mocks):
        # This was previously an invalidly indented run method snippet
        pass


if __name__ == "__main__":
    app = QApplication([])
    test_repro()
