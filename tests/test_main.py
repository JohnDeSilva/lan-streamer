import pytest
from unittest.mock import MagicMock, patch
from typing import Callable, Any
from lan_streamer import main


@pytest.fixture(autouse=True)
def cleanup_logging_handlers() -> Any:
    import logging

    def close_all() -> None:
        for logger_name in [
            "",
            "lan_streamer.db",
            "lan_streamer.backend",
            "lan_streamer.scanner",
            "lan_streamer.jellyfin",
            "lan_streamer.tmdb",
            "lan_streamer.player_widget",
            "lan_streamer.backup",
        ]:
            target_logger = (
                logging.getLogger(logger_name) if logger_name else logging.getLogger()
            )
            for handler_object in target_logger.handlers[:]:
                handler_object.close()
                target_logger.removeHandler(handler_object)

    close_all()
    yield
    close_all()


def test_setup_dark_theme(qtbot: Any) -> None:
    from PySide6.QtWidgets import QApplication

    application_instance = QApplication.instance() or QApplication([])
    if isinstance(application_instance, QApplication):
        main.setup_dark_theme(application_instance)
        assert application_instance.palette() is not None


def test_main_execution() -> None:
    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()) as mock_application_class,
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.Controller", MagicMock()),
        patch("lan_streamer.main.LibraryGridView", MagicMock()) as mock_grid_class,
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch(
            "lan_streamer.backup.perform_scheduled_backups", MagicMock()
        ) as mock_backup,
    ):
        mock_application_instance = mock_application_class.return_value
        mock_grid_instance = mock_grid_class.return_value

        main.main()

        mock_backup.assert_called_once()
        mock_grid_instance.populate_libraries.assert_called_once()
        mock_application_instance.exec.assert_called_once()


def test_main_logging_setup(tmp_path: Any) -> None:
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
            patch("lan_streamer.main.Controller", MagicMock()),
            patch("lan_streamer.main.LibraryGridView", MagicMock()),
            patch("lan_streamer.main.SeriesDetailView", MagicMock()),
            patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
            patch("lan_streamer.main.db.init_db", MagicMock()),
            patch("lan_streamer.backup.perform_scheduled_backups", MagicMock()),
            patch("sys.exit", MagicMock()),
        ):
            root_logger = logging.getLogger()
            for handler_object in root_logger.handlers[:]:
                root_logger.removeHandler(handler_object)

            from lan_streamer.config import config

            config.divide_logs_by_service = False
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

            for handler_object in root_logger.handlers[:]:
                handler_object.close()
                root_logger.removeHandler(handler_object)

            # Test divided service logging mode
            config.divide_logs_by_service = True
            db_logger = logging.getLogger("lan_streamer.db")
            for handler_object in db_logger.handlers[:]:
                handler_object.close()
                db_logger.removeHandler(handler_object)

            main.main()
            db_log_path = os.path.join(config.log_directory, "db.log")
            assert os.path.exists(db_log_path)
    finally:
        os.chdir(old_current_working_directory)


def test_main_logging_failure() -> None:
    def mock_file_handler(*args: Any, **kwargs: Any) -> None:
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
        patch("lan_streamer.main.Controller", MagicMock()),
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.backup.perform_scheduled_backups", MagicMock()),
        patch("sys.exit", lambda exit_code: None),
    ):
        main.main()
        mock_error_target.assert_called()


def test_main_proactive_log_cleanup(tmp_path: Any) -> None:
    import time
    from lan_streamer.config import config

    config.log_directory = str(tmp_path / "logs")
    log_directory_object = tmp_path / "logs"
    log_directory_object.mkdir(parents=True, exist_ok=True)

    old_file_object = log_directory_object / "old_app.log.2026-05-01"
    new_file_object = log_directory_object / "new_app.log"
    old_file_object.touch()
    new_file_object.touch()

    old_time_value = time.time() - (config.max_log_retention_days + 3) * 86400
    import os

    os.utime(old_file_object, (old_time_value, old_time_value))

    with (
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.Controller", MagicMock()),
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.backup.perform_scheduled_backups", MagicMock()),
        patch("sys.exit", MagicMock()),
    ):
        main.main()

    assert not old_file_object.exists()
    assert new_file_object.exists()


def test_main_signal_routing() -> None:
    from lan_streamer.config import config

    config.use_embedded_player = True
    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()) as mock_layout_class,
        patch("lan_streamer.main.Controller", MagicMock()) as mock_controller_class,
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()) as mock_detail_class,
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()) as mock_player_class,
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.backup.perform_scheduled_backups", MagicMock()),
        patch("lan_streamer.main.MetadataMatchDialog", MagicMock()) as mock_meta_dialog,
        patch(
            "lan_streamer.main.RenamePreviewDialog", MagicMock()
        ) as mock_rename_dialog,
    ):
        main.main()

        mock_controller_instance = mock_controller_class.return_value
        mock_detail_instance = mock_detail_class.return_value
        mock_player_instance = mock_player_class.return_value
        mock_layout_instance = mock_layout_class.return_value

        # Test series_selected callback routes to detail view (index 1)
        series_selected_slot: Callable[[str], None] = (
            mock_controller_instance.series_selected.connect.call_args[0][0]
        )
        series_selected_slot("Cosmos")
        mock_layout_instance.setCurrentIndex.assert_called_with(1)

        # Test detail view back button routes to grid view (index 0)
        grid_back_slot: Callable[[], None] = (
            mock_detail_instance.back_requested.connect.call_args[0][0]
        )
        grid_back_slot()
        mock_layout_instance.setCurrentIndex.assert_called_with(0)

        # Test playback requested callback triggers player embedded and switches to index 2
        playback_slot: Callable[[str], None] = (
            mock_controller_instance.playback_requested.connect.call_args[0][0]
        )
        playback_slot("/path/to/vid.mkv")
        mock_player_instance.play_video.assert_called_once_with("/path/to/vid.mkv")
        mock_layout_instance.setCurrentIndex.assert_called_with(2)

        # Test player back button routes to detail view (index 1)
        player_back_slot: Callable[[], None] = (
            mock_player_instance.back_requested.connect.call_args[0][0]
        )
        player_back_slot()
        mock_layout_instance.setCurrentIndex.assert_called_with(1)

        # Test metadata dialog connection
        meta_slot: Callable[[str], None] = (
            mock_controller_instance.metadata_dialog_requested.connect.call_args[0][0]
        )
        meta_slot("Cosmos")
        mock_meta_dialog.return_value.exec.assert_called_once()

        # Test rename dialog connection
        rename_slot: Callable[[str], None] = (
            mock_controller_instance.rename_dialog_requested.connect.call_args[0][0]
        )
        rename_slot("Cosmos")
        mock_rename_dialog.return_value.exec.assert_called_once()


def test_main_playback_requested_external() -> None:
    from lan_streamer.config import config

    config.use_embedded_player = False
    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.Controller", MagicMock()) as mock_controller_class,
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()) as mock_player_class,
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.backup.perform_scheduled_backups", MagicMock()),
        patch("lan_streamer.main.play_video", MagicMock()) as mock_external_play,
    ):
        main.main()
        mock_controller_instance = mock_controller_class.return_value
        mock_player_instance = mock_player_class.return_value

        playback_slot: Callable[[str], None] = (
            mock_controller_instance.playback_requested.connect.call_args[0][0]
        )
        playback_slot("/path/to/video.mkv")

        mock_player_instance.play_video.assert_not_called()
        mock_external_play.assert_called_once_with("/path/to/video.mkv")


def test_main_playback_requested_external_exception() -> None:
    from lan_streamer.config import config

    config.use_embedded_player = False
    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.Controller", MagicMock()) as mock_controller_class,
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.backup.perform_scheduled_backups", MagicMock()),
        patch(
            "lan_streamer.main.play_video",
            side_effect=Exception("External player launch fault"),
        ) as mock_external_play,
        patch("logging.error", MagicMock()) as mock_log_error,
    ):
        main.main()
        mock_controller_instance = mock_controller_class.return_value

        playback_slot: Callable[[str], None] = (
            mock_controller_instance.playback_requested.connect.call_args[0][0]
        )
        playback_slot("/path/to/video.mkv")

        mock_external_play.assert_called_once_with("/path/to/video.mkv")
        mock_log_error.assert_called()
