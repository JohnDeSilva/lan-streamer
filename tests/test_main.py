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


def test_main_proactive_log_cleanup(tmp_path) -> None:
    import time
    from lan_streamer.config import config

    config.log_directory = str(tmp_path / "logs")
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create old log file and new log file
    old_file = log_dir / "old_app.log.2026-05-01"
    new_file = log_dir / "new_app.log"
    old_file.touch()
    new_file.touch()

    # Backdate old_file modification time beyond max_log_retention_days (e.g. 10 days ago)
    old_time = time.time() - (config.max_log_retention_days + 3) * 86400
    import os

    os.utime(old_file, (old_time, old_time))

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
        main.main()

    assert not old_file.exists()
    assert new_file.exists()


def test_main_on_playback_requested_embedded() -> None:
    from lan_streamer.config import config

    config.use_embedded_player = True
    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()) as mock_layout_class,
        patch("lan_streamer.main.QQuickWidget", MagicMock()),
        patch("lan_streamer.main.BackendBridge", MagicMock()) as mock_bridge_class,
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()) as mock_player_class,
        patch("lan_streamer.main.db.init_db", MagicMock()),
    ):
        main.main()
        mock_bridge_instance = mock_bridge_class.return_value
        mock_player_instance = mock_player_class.return_value
        mock_layout_instance = mock_layout_class.return_value

        mock_bridge_instance.playbackRequested.connect.assert_called_once()
        callback_function = mock_bridge_instance.playbackRequested.connect.call_args[0][
            0
        ]

        callback_function("/path/to/video.mkv")

        mock_player_instance.play_video.assert_called_once_with("/path/to/video.mkv")
        mock_layout_instance.setCurrentIndex.assert_called_with(1)


def test_main_on_playback_requested_external() -> None:
    from lan_streamer.config import config

    config.use_embedded_player = False
    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.QQuickWidget", MagicMock()),
        patch("lan_streamer.main.BackendBridge", MagicMock()) as mock_bridge_class,
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()) as mock_player_class,
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.main.play_video", MagicMock()) as mock_external_play,
    ):
        main.main()
        mock_bridge_instance = mock_bridge_class.return_value
        mock_player_instance = mock_player_class.return_value

        mock_bridge_instance.playbackRequested.connect.assert_called_once()
        callback_function = mock_bridge_instance.playbackRequested.connect.call_args[0][
            0
        ]

        callback_function("/path/to/video.mkv")

        mock_player_instance.play_video.assert_not_called()
        mock_external_play.assert_called_once_with("/path/to/video.mkv")


def test_main_on_playback_requested_external_exception() -> None:
    from lan_streamer.config import config

    config.use_embedded_player = False
    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.QQuickWidget", MagicMock()),
        patch("lan_streamer.main.BackendBridge", MagicMock()) as mock_bridge_class,
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch(
            "lan_streamer.main.play_video",
            side_effect=Exception("External player launch fault"),
        ) as mock_external_play,
        patch("logging.error", MagicMock()) as mock_log_error,
    ):
        main.main()
        mock_bridge_instance = mock_bridge_class.return_value

        callback_function = mock_bridge_instance.playbackRequested.connect.call_args[0][
            0
        ]
        callback_function("/path/to/video.mkv")

        mock_external_play.assert_called_once_with("/path/to/video.mkv")
        mock_log_error.assert_called()
