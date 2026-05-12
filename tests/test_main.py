from unittest.mock import MagicMock, patch
from lan_streamer import main


def test_setup_dark_theme(qtbot) -> None:
    from PySide6.QtWidgets import QApplication

    application_instance = QApplication.instance() or QApplication([])
    main.setup_dark_theme(application_instance)
    assert application_instance.palette() is not None


def test_main_execution() -> None:
    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()) as mock_application_class,
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.QQuickWidget", MagicMock()) as mock_engine_class,
        patch("lan_streamer.main.BackendBridge", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
    ):
        mock_application_instance = mock_application_class.return_value
        mock_engine_instance = mock_engine_class.return_value
        mock_engine_instance.status.return_value = 1  # Not Error

        main.main()

        mock_engine_instance.setSource.assert_called_once()
        mock_application_instance.exec.assert_called_once()


def test_main_execution_empty_root_objects() -> None:
    with (
        patch("sys.exit", MagicMock()) as mock_exit,
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.QQuickWidget", MagicMock()) as mock_engine_class,
        patch("lan_streamer.main.BackendBridge", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
    ):
        mock_engine_instance = mock_engine_class.return_value
        # Simulate QQuickWidget Status Error
        import lan_streamer.main

        mock_engine_instance.status.return_value = (
            lan_streamer.main.QQuickWidget.Status.Error
        )

        main.main()

        mock_exit.assert_called_with(-1)


def test_main_logging_setup(tmp_path) -> None:
    import logging
    import os

    old_current_working_directory = os.getcwd()
    os.chdir(tmp_path)
    try:
        with (
            patch("lan_streamer.main.QApplication", MagicMock()),
            patch("lan_streamer.main.QMainWindow", MagicMock()),
            patch("lan_streamer.main.QWidget", MagicMock()),
            patch("lan_streamer.main.QStackedLayout", MagicMock()),
            patch("lan_streamer.main.QQuickWidget", MagicMock()),
            patch("lan_streamer.main.BackendBridge", MagicMock()),
            patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
            patch("lan_streamer.main.db.init_db", MagicMock()),
            patch("sys.exit", MagicMock()),
        ):
            root_logger = logging.getLogger()
            for handler_object in root_logger.handlers[:]:
                root_logger.removeHandler(handler_object)

            from lan_streamer.config import config

            config.enable_global_file_logging = True
            main.main()

            log_file_path = os.path.join(config.log_directory, "lan-streamer.log")
            assert os.path.exists(log_file_path)

            handlers_list = root_logger.handlers
            from logging.handlers import TimedRotatingFileHandler

            assert any(
                isinstance(handler, TimedRotatingFileHandler)
                for handler in handlers_list
            )
            assert any(
                isinstance(handler, logging.StreamHandler) for handler in handlers_list
            )
    finally:
        os.chdir(old_current_working_directory)


def test_main_logging_failure() -> None:
    def mock_file_handler(*args, **kwargs) -> None:
        raise Exception("Log failure")

    mock_error_target = MagicMock()

    with (
        patch("logging.handlers.TimedRotatingFileHandler", mock_file_handler),
        patch("logging.error", mock_error_target),
        patch("lan_streamer.main.db.init_db", lambda: False),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.QQuickWidget", MagicMock()),
        patch("lan_streamer.main.BackendBridge", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("sys.exit", lambda exit_code: None),
    ):
        main.main()
        mock_error_target.assert_called()
