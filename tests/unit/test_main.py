import asyncio
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
            "lan_streamer.providers.jellyfin",
            "lan_streamer.providers.tmdb",
            "lan_streamer.playback",
            "lan_streamer.playback.player",
            "lan_streamer.system.backup",
            "lan_streamer.providers.opensubtitles",
            "lan_streamer.playback.wakelock",
            "lan_streamer.ui_views",
            "lan_streamer.scanner.renamer",
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
    from lan_streamer.system.config import config

    config.sync_history_on_start = True
    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()) as mock_application_class,
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.Controller", MagicMock()) as mock_controller_class,
        patch("lan_streamer.main.LibraryGridView", MagicMock()) as mock_grid_class,
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.SeasonDetailView", MagicMock()),
        patch("lan_streamer.main.CastDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch(
            "lan_streamer.system.backup.perform_scheduled_backups", MagicMock()
        ) as mock_backup,
    ):
        mock_application_class.instance.return_value = None
        mock_grid_instance = mock_grid_class.return_value
        mock_controller_instance = mock_controller_class.return_value

        asyncio.run(main.main())

        mock_backup.assert_called_once()
        mock_grid_instance.populate_libraries.assert_called_once()
        mock_controller_instance.trigger_jellyfin_pull.assert_not_called()


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
            patch("lan_streamer.main.MovieDetailView", MagicMock()),
            patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
            patch("lan_streamer.main.db.init_db", MagicMock()),
            patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
            patch("sys.exit", MagicMock()),
        ):
            root_logger = logging.getLogger()
            for handler_object in root_logger.handlers[:]:
                root_logger.removeHandler(handler_object)

            from lan_streamer.system.config import config

            config.divide_logs_by_service = False
            asyncio.run(main.main())

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

            asyncio.run(main.main())
            db_log_path = os.path.join(config.log_directory, "db.log")
            assert os.path.exists(db_log_path)
            assert os.path.exists(
                os.path.join(config.log_directory, "opensubtitles.log")
            )
            assert os.path.exists(os.path.join(config.log_directory, "wakelock.log"))
            assert os.path.exists(os.path.join(config.log_directory, "ui.log"))
            assert os.path.exists(os.path.join(config.log_directory, "renamer.log"))
            assert os.path.exists(os.path.join(config.log_directory, "player.log"))
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
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.SeasonDetailView", MagicMock()),
        patch("lan_streamer.main.CastDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
        patch("sys.exit", lambda exit_code: None),
    ):
        asyncio.run(main.main())
        mock_error_target.assert_called()


def test_main_proactive_log_cleanup(tmp_path: Any) -> None:
    import time
    from lan_streamer.system.config import config

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
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.SeasonDetailView", MagicMock()),
        patch("lan_streamer.main.CastDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
        patch("sys.exit", MagicMock()),
    ):
        asyncio.run(main.main())

    assert not old_file_object.exists()
    assert new_file_object.exists()


def test_main_signal_routing() -> None:
    from lan_streamer.system.config import config

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
        patch(
            "lan_streamer.main.MovieDetailView", MagicMock()
        ) as mock_movie_detail_class,
        patch("lan_streamer.main.SeasonDetailView", MagicMock()),
        patch("lan_streamer.main.CastDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()) as mock_player_class,
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
        patch("lan_streamer.main.MetadataMatchDialog", MagicMock()) as mock_meta_dialog,
        patch(
            "lan_streamer.main.RenamePreviewDialog", MagicMock()
        ) as mock_rename_dialog,
    ):
        asyncio.run(main.main())

        mock_controller_instance = mock_controller_class.return_value
        mock_detail_instance = mock_detail_class.return_value
        mock_movie_detail_instance = mock_movie_detail_class.return_value
        mock_player_instance = mock_player_class.return_value
        mock_layout_instance = mock_layout_class.return_value
        mock_controller_instance.is_video_playing = False

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

        # Test movie_selected callback routes to movie detail view (index 2)
        movie_selected_slot: Callable[[str], None] = (
            mock_controller_instance.movie_selected.connect.call_args[0][0]
        )
        movie_selected_slot("Avatar")
        mock_layout_instance.setCurrentIndex.assert_called_with(2)

        # Test movie detail view back button routes to grid view (index 0)
        movie_back_slot: Callable[[], None] = (
            mock_movie_detail_instance.back_requested.connect.call_args[0][0]
        )
        movie_back_slot()
        mock_layout_instance.setCurrentIndex.assert_called_with(0)

        # Test playback requested callback triggers player embedded and switches to index 3
        playback_slot: Callable[[str], None] = (
            mock_controller_instance.playback_requested.connect.call_args[0][0]
        )
        playback_slot("/path/to/vid.mkv")
        mock_controller_instance.set_video_playing.assert_called_once_with(True)
        mock_player_instance.play_video.assert_called_once_with("/path/to/vid.mkv")
        mock_layout_instance.setCurrentIndex.assert_called_with(5)

        # Test player back button routes to detail view (index 1)
        player_back_slot: Callable[[], None] = (
            mock_player_instance.back_requested.connect.call_args[0][0]
        )
        player_back_slot()
        mock_controller_instance.set_video_playing.assert_called_with(False)
        mock_layout_instance.setCurrentIndex.assert_called_with(1)

        # Test watched marked callback routes to controller mark_episode_watched
        watched_marked_slot: Callable[[str], None] = (
            mock_player_instance.watched_marked.connect.call_args[0][0]
        )
        watched_marked_slot("/path/to/vid.mkv")
        mock_controller_instance.mark_episode_watched.assert_called_once_with(
            "/path/to/vid.mkv", True
        )

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
    from lan_streamer.system.config import config

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
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()) as mock_player_class,
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
        patch("lan_streamer.main.play_video", MagicMock()) as mock_external_play,
        patch.object(config, "load_from_db", MagicMock()),
    ):
        asyncio.run(main.main())
        mock_controller_instance = mock_controller_class.return_value
        mock_player_instance = mock_player_class.return_value

        playback_slot: Callable[[str], None] = (
            mock_controller_instance.playback_requested.connect.call_args[0][0]
        )
        playback_slot("/path/to/video.mkv")

        mock_player_instance.play_video.assert_not_called()
        mock_external_play.assert_called_once_with("/path/to/video.mkv")


def test_main_playback_requested_external_exception() -> None:
    from lan_streamer.system.config import config

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
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.SeasonDetailView", MagicMock()),
        patch("lan_streamer.main.CastDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
        patch(
            "lan_streamer.main.play_video",
            side_effect=Exception("External player launch fault"),
        ) as mock_external_play,
        patch("lan_streamer.main.logger") as mock_logger,
        patch.object(config, "load_from_db", MagicMock()),
    ):
        asyncio.run(main.main())
        mock_controller_instance = mock_controller_class.return_value

        playback_slot: Callable[[str], None] = (
            mock_controller_instance.playback_requested.connect.call_args[0][0]
        )
        playback_slot("/path/to/video.mkv")

        mock_external_play.assert_called_once_with("/path/to/video.mkv")
        mock_logger.exception.assert_called_once_with(
            "Failed to launch external player for '/path/to/video.mkv'"
        )


def test_main_dry_run() -> None:
    import os

    def exit_side_effect(code=0):
        raise SystemExit(code)

    with (
        patch.dict(os.environ, {"LAN_STREAMER_DRY_RUN": "1", "QT_QPA_PLATFORM": ""}),
        patch("PySide6.QtWidgets.QApplication", MagicMock()),
        patch("os._exit", side_effect=exit_side_effect),
    ):
        with pytest.raises(SystemExit) as excinfo:
            main.run_main()
        assert excinfo.value.code == 0


def test_main_dry_run_with_existing_qapp() -> None:
    import os
    from unittest.mock import MagicMock

    def exit_side_effect(code=0):
        raise SystemExit(code)

    mock_qapp_class = MagicMock()
    mock_qapp_class.instance.return_value = MagicMock()  # Mock existing instance

    with (
        patch.dict(os.environ, {"LAN_STREAMER_DRY_RUN": "1", "QT_QPA_PLATFORM": ""}),
        patch("PySide6.QtWidgets.QApplication", mock_qapp_class),
        patch("os._exit", side_effect=exit_side_effect),
    ):
        with pytest.raises(SystemExit) as excinfo:
            main.run_main()
        assert excinfo.value.code == 0
        mock_qapp_class.assert_not_called()  # Should not create new QApplication instance


def test_main_log_cleanup_unlink_exception() -> None:
    import pathlib

    with (
        patch("pathlib.Path.unlink", side_effect=OSError("Access denied")),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.Controller", MagicMock()),
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.SeasonDetailView", MagicMock()),
        patch("lan_streamer.main.CastDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
        patch("sys.exit", MagicMock()),
    ):
        # We need a dummy log file that looks old to trigger unlink
        # Let's mock stat return value to have an old mtime
        mock_stat = MagicMock()
        mock_stat.st_mtime = 0
        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat", return_value=mock_stat),
            patch("pathlib.Path.glob", return_value=[pathlib.Path("old_log.log")]),
        ):
            asyncio.run(main.main())


def test_main_wayland_platform() -> None:
    import os

    with (
        patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "QT_QPA_PLATFORM": ""}),
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.Controller", MagicMock()),
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.SeasonDetailView", MagicMock()),
        patch("lan_streamer.main.CastDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
    ):
        asyncio.run(main.main())
        assert os.environ.get("QT_QPA_PLATFORM") == "xcb"


def test_main_log_directory_creation_failure() -> None:
    with (
        patch("pathlib.Path.mkdir", side_effect=OSError("Write block")),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.Controller", MagicMock()),
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.SeasonDetailView", MagicMock()),
        patch("lan_streamer.main.CastDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
        patch("sys.exit", MagicMock()),
    ):
        asyncio.run(main.main())


def test_main_log_cleanup_exception() -> None:
    with (
        patch("pathlib.Path.glob", side_effect=Exception("Glob failed")),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()),
        patch("lan_streamer.main.Controller", MagicMock()),
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.SeasonDetailView", MagicMock()),
        patch("lan_streamer.main.CastDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
        patch("sys.exit", MagicMock()),
    ):
        asyncio.run(main.main())


def test_main_more_signal_routings() -> None:
    from lan_streamer.system.config import config

    config.libraries = {"LibMovie": {"type": "movie"}}

    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()) as mock_layout_class,
        patch("lan_streamer.main.Controller", MagicMock()) as mock_controller_class,
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()) as mock_player_class,
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
        # Dialog patches
        patch("lan_streamer.main.JellyfinMatchDialog", MagicMock()) as mock_jf_dialog,
        patch(
            "lan_streamer.main.EpisodeMatchDialog", MagicMock()
        ) as mock_ep_match_dialog,
        patch(
            "lan_streamer.main.EpisodeDetailsDialog", MagicMock()
        ) as mock_ep_detail_dialog,
        patch(
            "lan_streamer.main.MovieDetailsDialog", MagicMock()
        ) as mock_movie_detail_dialog,
        patch(
            "lan_streamer.main.SeriesDetailsDialog", MagicMock()
        ) as mock_series_detail_dialog,
        patch.object(config, "load_from_db", MagicMock()),
    ):
        asyncio.run(main.main())
        mock_controller_instance = mock_controller_class.return_value
        mock_player_instance = mock_player_class.return_value
        mock_layout_instance = mock_layout_class.return_value

        # 1. on_player_back_requested (library type = movie) -> index 2
        mock_controller_instance.current_library_name = "LibMovie"
        player_back_slot = mock_player_instance.back_requested.connect.call_args[0][0]
        player_back_slot()
        mock_layout_instance.setCurrentIndex.assert_called_with(2)

        # 2. Jellyfin dialog routing
        jf_dialog_slot = (
            mock_controller_instance.jellyfin_dialog_requested.connect.call_args[0][0]
        )
        jf_dialog_slot("Show")
        mock_jf_dialog.return_value.exec.assert_called_once()

        # 3. Episode metadata dialog routing
        ep_match_slot = mock_controller_instance.episode_metadata_dialog_requested.connect.call_args[
            0
        ][0]
        ep_match_slot("Show", "/path/to/ep")
        mock_ep_match_dialog.return_value.exec.assert_called_once()

        # 4. Episode details dialog routing
        ep_detail_slot = (
            mock_controller_instance.episode_details_requested.connect.call_args[0][0]
        )
        ep_detail_slot("Show", "/path/to/ep")
        mock_ep_detail_dialog.return_value.exec.assert_called_once()

        # 5. Movie details dialog routing
        movie_detail_slot = (
            mock_controller_instance.movie_details_requested.connect.call_args[0][0]
        )
        movie_detail_slot("Movie", "/path/to/movie")
        mock_movie_detail_dialog.return_value.exec.assert_called_once()

        # 6. Series details dialog routing
        series_detail_slot = (
            mock_controller_instance.series_details_requested.connect.call_args[0][0]
        )
        series_detail_slot("Show")
        mock_series_detail_dialog.return_value.exec.assert_called_once()


def test_main_cast_detail_navigation_and_back_stack() -> None:
    """Verify that back button on cast details preserves navigation source view index."""
    from lan_streamer import main

    with (
        patch("sys.exit", MagicMock()),
        patch("lan_streamer.main.QApplication", MagicMock()),
        patch("lan_streamer.main.QMainWindow", MagicMock()),
        patch("lan_streamer.main.QWidget", MagicMock()),
        patch("lan_streamer.main.QStackedLayout", MagicMock()) as mock_layout_class,
        patch("lan_streamer.main.Controller", MagicMock()) as mock_controller_class,
        patch("lan_streamer.main.LibraryGridView", MagicMock()),
        patch("lan_streamer.main.SeriesDetailView", MagicMock()),
        patch("lan_streamer.main.MovieDetailView", MagicMock()),
        patch("lan_streamer.main.SeasonDetailView", MagicMock()),
        patch(
            "lan_streamer.main.CastDetailView", MagicMock()
        ) as mock_cast_detail_class,
        patch("lan_streamer.main.VideoPlayerWidget", MagicMock()),
        patch("lan_streamer.main.db.init_db", MagicMock()),
        patch("lan_streamer.system.backup.perform_scheduled_backups", MagicMock()),
    ):
        asyncio.run(main.main())

        mock_controller_instance = mock_controller_class.return_value
        mock_layout_instance = mock_layout_class.return_value
        mock_cast_detail_instance = mock_cast_detail_class.return_value

        # Emulate starting from Season Detail View (index 3)
        mock_layout_instance.currentIndex.return_value = 3

        # Trigger cast member selection
        cast_selected_slot: Callable[[str], None] = (
            mock_controller_instance.cast_member_selected.connect.call_args[0][0]
        )
        cast_selected_slot("person-123")

        mock_cast_detail_instance.display_person.assert_called_with("person-123")
        mock_layout_instance.setCurrentIndex.assert_called_with(4)

        # Trigger cast detail back button
        cast_back_slot: Callable[[], None] = (
            mock_cast_detail_instance.back_requested.connect.call_args[0][0]
        )
        cast_back_slot()

        # It should switch back to the index it came from (index 3)
        mock_layout_instance.setCurrentIndex.assert_called_with(3)
