from unittest.mock import MagicMock
from lan_streamer import main


def test_setup_dark_theme(qtbot):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    main.setup_dark_theme(app)
    assert app.palette() is not None


def test_main_execution(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "exit", MagicMock())

    mock_app = MagicMock()
    mock_window = MagicMock()

    monkeypatch.setattr(
        "lan_streamer.main.QApplication", MagicMock(return_value=mock_app)
    )
    monkeypatch.setattr(
        "lan_streamer.main.MainWindow", MagicMock(return_value=mock_window)
    )
    monkeypatch.setattr("lan_streamer.main.db.init_db", MagicMock())

    main.main()

    mock_window.show.assert_called_once()
    mock_app.exec.assert_called_once()


def test_main_logging_setup(monkeypatch, tmp_path):
    import logging
    import os

    # Change CWD to tmp_path to test log file creation
    monkeypatch.chdir(tmp_path)

    # Mock components to avoid side effects
    monkeypatch.setattr("lan_streamer.main.QApplication", MagicMock())
    monkeypatch.setattr("lan_streamer.main.MainWindow", MagicMock())
    monkeypatch.setattr("lan_streamer.main.db.init_db", MagicMock())

    # Clear existing handlers
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)

    # Mock sys.exit to prevent test from exiting
    import sys

    monkeypatch.setattr(sys, "exit", MagicMock())

    main.main()

    # Verify log file exists
    assert os.path.exists("lan-streamer.log")

    # Verify handlers
    handlers = root.handlers
    assert any(isinstance(h, logging.FileHandler) for h in handlers)
    assert any(isinstance(h, logging.StreamHandler) for h in handlers)


def test_main_logging_failure(monkeypatch):
    # Test lines 54-55 of main.py
    import logging

    def mock_file_handler(*args, **kwargs):
        raise Exception("Log failure")

    monkeypatch.setattr(logging, "FileHandler", mock_file_handler)
    mock_error = MagicMock()
    monkeypatch.setattr(logging, "error", mock_error)

    # Mock other things to avoid execution
    monkeypatch.setattr("lan_streamer.main.db.init_db", lambda: False)
    monkeypatch.setattr("lan_streamer.main.QApplication", MagicMock())
    monkeypatch.setattr("lan_streamer.main.MainWindow", MagicMock())

    import sys

    monkeypatch.setattr(sys, "exit", lambda x: None)

    main.main()
    mock_error.assert_called()
