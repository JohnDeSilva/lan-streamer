from unittest.mock import MagicMock, patch
from lan_streamer import main


def test_setup_dark_theme(qtbot):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    main.setup_dark_theme(app)
    assert app.palette() is not None


def test_main_execution():

    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()) as mock_app_class,
        patch("lan_streamer.main.MainWindow", MagicMock()) as mock_window_class,
        patch("lan_streamer.main.db.init_db", MagicMock()),
    ):
        mock_app = mock_app_class.return_value
        mock_window = mock_window_class.return_value

        main.main()

        mock_window.show.assert_called_once()
        mock_app.exec.assert_called_once()


def test_main_logging_setup(tmp_path):
    import logging
    import os

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        # Mock components to avoid side effects
        with (
            patch("lan_streamer.main.QApplication", MagicMock()),
            patch("lan_streamer.main.MainWindow", MagicMock()),
            patch("lan_streamer.main.db.init_db", MagicMock()),
            patch("sys.exit", MagicMock()),
        ):
            # Clear existing handlers
            root = logging.getLogger()
            for h in root.handlers[:]:
                root.removeHandler(h)

            main.main()

            # Verify log file exists
            assert os.path.exists("lan-streamer.log")

            # Verify handlers
            handlers = root.handlers
            from logging.handlers import TimedRotatingFileHandler

            assert any(isinstance(h, TimedRotatingFileHandler) for h in handlers)
            assert any(isinstance(h, logging.StreamHandler) for h in handlers)
    finally:
        os.chdir(old_cwd)


def test_main_logging_failure():
    # Test lines 54-55 of main.py

    def mock_file_handler(*args, **kwargs):
        raise Exception("Log failure")

    mock_error = MagicMock()

    with (
        patch("logging.handlers.TimedRotatingFileHandler", mock_file_handler),
        patch("logging.error", mock_error),
        patch("lan_streamer.main.db.init_db", lambda: False),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.MainWindow", MagicMock()),
        patch("sys.exit", lambda x: None),
    ):
        main.main()
        mock_error.assert_called()
