from __future__ import annotations

import asyncio
import sys
import logging
from pathlib import Path
from typing import Dict, Optional, cast
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QStackedLayout
from PySide6.QtGui import QPalette, QColor, QFont
from PySide6.QtCore import Qt

from lan_streamer import db, __version__
from lan_streamer.system.config import config
from lan_streamer.ui_views import (
    Controller,
    LibraryGridView,
    SeriesDetailView,
    MovieDetailView,
    MetadataMatchDialog,
    JellyfinMatchDialog,
    EpisodeMatchDialog,
    EpisodeDetailsDialog,
    MovieDetailsDialog,
    SeriesDetailsDialog,
    RenamePreviewDialog,
    get_application_stylesheet,
)
from lan_streamer.playback import VideoPlayerWidget
from lan_streamer.playback import play_video

logger: logging.Logger = logging.getLogger(__name__)


def setup_dark_theme(application_instance: QApplication) -> None:
    application_instance.setStyle("Fusion")

    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(40, 40, 40))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(42, 42, 42))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)

    application_instance.setPalette(dark_palette)
    application_instance.setStyleSheet(get_application_stylesheet())


async def main() -> None:
    import os

    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-v", "-V"):
        print(f"lan-streamer {__version__}")
        sys.exit(0)

    if os.environ.get("LAN_STREAMER_DRY_RUN") == "1":
        if not os.environ.get("QT_QPA_PLATFORM"):
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
        app_inst = QApplication.instance()
        if app_inst is None:
            app_inst = QApplication(sys.argv)
        print(
            "LAN Streamer: Dry run verification successful. Qt application successfully initialized."
        )
        os._exit(0)

    if sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM"):
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            os.environ["QT_QPA_PLATFORM"] = "xcb"

    log_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    root_logger = logging.getLogger()

    from lan_streamer.system.logging_handler import set_application_log_level

    set_application_log_level(config.log_level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    file_handlers: Dict[str, logging.Handler] = {}

    def add_file_handler(
        logger_object: logging.Logger,
        filename: str,
        formatter: logging.Formatter,
        info_message: Optional[str] = None,
    ) -> None:
        try:
            from logging.handlers import TimedRotatingFileHandler

            handler: logging.Handler
            if filename not in file_handlers:
                handler = TimedRotatingFileHandler(
                    filename,
                    when="midnight",
                    interval=1,
                    backupCount=config.max_log_retention_days,
                )
                handler.suffix = "%Y-%m-%d"
                handler.namer = lambda name: name.replace(".log.", "_") + ".log"
                handler.setFormatter(formatter)
                file_handlers[filename] = handler
            else:
                handler = file_handlers[filename]

            logger_object.addHandler(handler)
            if logger_object != logging.getLogger():
                logger_object.propagate = False
            if info_message:
                logging.info(info_message)
        except Exception as exc:
            logging.error(f"Could not create log file {filename}: {exc}")

    log_directory = Path(config.log_directory).expanduser().absolute()
    try:
        log_directory.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logging.warning(f"Could not create log directory {log_directory}: {exc}")

    try:
        import time

        cutoff = time.time() - (config.max_log_retention_days * 86400)
        for path_item in log_directory.glob("*.log*"):
            if path_item.is_file() and path_item.stat().st_mtime < cutoff:
                try:
                    path_item.unlink()
                except Exception:
                    pass
    except Exception as exc:
        logging.debug(f"Error cleaning old logs: {exc}")

    from lan_streamer.system.logging_handler import SERVICE_LOGGERS, setup_qt_logging

    if not config.divide_logs_by_service:
        add_file_handler(
            root_logger,
            str(log_directory / "lan-streamer.log"),
            log_formatter,
            f"Logging to {log_directory / 'lan-streamer.log'} (rotated daily)",
        )
    else:
        logging.info("Logging divided into individual service log files")
        # Map logger names to their respective file names
        logger_to_filename = {
            "lan_streamer.db": "db.log",
            "lan_streamer.backend": "backend.log",
            "lan_streamer.scanner": "scanner.log",
            "lan_streamer.jellyfin": "jellyfin.log",
            "lan_streamer.tmdb": "tmdb.log",
            "lan_streamer.player_widget": "player.log",
            "lan_streamer.player": "player.log",
            "lan_streamer.backup": "backup.log",
            "lan_streamer.opensubtitles": "opensubtitles.log",
            "lan_streamer.wakelock": "wakelock.log",
            "lan_streamer.ui_views": "ui.log",
            "lan_streamer.main": "ui.log",
            "lan_streamer.renamer": "renamer.log",
        }
        for logger_name in SERVICE_LOGGERS:
            filename = logger_to_filename.get(logger_name, "app.log")
            add_file_handler(
                logging.getLogger(logger_name),
                str(log_directory / filename),
                log_formatter,
            )

    setup_qt_logging(log_formatter)

    from lan_streamer.system.backup import perform_scheduled_backups

    perform_scheduled_backups()

    logger.info("Initializing database...")
    db.init_db()
    logger.info("Loading settings from database...")
    config.load_from_db()
    logger.info("Initializing Qt Application...")
    app_inst = QApplication.instance()
    if app_inst is None:
        app_inst = QApplication(sys.argv)
    application_instance = cast(QApplication, app_inst)
    setup_dark_theme(application_instance)

    application_instance.setFont(QFont("Inter", 14))

    main_window = QMainWindow()
    main_window.setWindowTitle(f"LAN Streamer v{__version__}")
    main_window.resize(1600, 1000)
    main_window.setMinimumSize(1200, 800)

    central_widget = QWidget()
    stacked_layout = QStackedLayout(central_widget)
    main_window.setCentralWidget(central_widget)

    logger.debug("Instantiating Controller and UI views...")
    controller = Controller()
    application_instance.aboutToQuit.connect(controller.worker_manager.stop_all)
    application_instance.aboutToQuit.connect(controller.async_task_manager.stop_all)
    library_grid_view = LibraryGridView(controller)
    series_detail_view = SeriesDetailView(controller)
    movie_detail_view = MovieDetailView(controller)
    player_view = VideoPlayerWidget()

    stacked_layout.addWidget(library_grid_view)
    stacked_layout.addWidget(series_detail_view)
    stacked_layout.addWidget(movie_detail_view)
    stacked_layout.addWidget(player_view)

    # Wire view routing and modal display signals
    def on_series_selected(series_name: str) -> None:
        logger.info(f"Navigating to Series Detail View for series: '{series_name}'")
        if not getattr(controller, "is_video_playing", False):
            stacked_layout.setCurrentIndex(1)

    controller.series_selected.connect(on_series_selected)

    def on_movie_selected(movie_name: str) -> None:
        logger.info(f"Navigating to Movie Detail View for movie: '{movie_name}'")
        if not getattr(controller, "is_video_playing", False):
            stacked_layout.setCurrentIndex(2)

    controller.movie_selected.connect(on_movie_selected)

    def on_grid_back_requested() -> None:
        logger.info("Navigating back to Library Grid View")
        stacked_layout.setCurrentIndex(0)
        # If we navigated from the Combined View, restore it
        nav_flag = getattr(library_grid_view, "_navigate_back_to_combined", False)
        logger.info(
            f"Back-navigation: current_library='{controller.current_library_name}', "
            f"_navigate_back_to_combined={nav_flag}"
        )
        if nav_flag:
            logger.info("Restoring Combined View after back-navigation")
            controller.current_library_name = "Combined View"
            library_grid_view.populate_combined_view()
            library_grid_view._sync_library_selector("Combined View")
            library_grid_view._navigate_back_to_combined = False

    series_detail_view.back_requested.connect(on_grid_back_requested)
    movie_detail_view.back_requested.connect(on_grid_back_requested)

    previous_layout_index: list[Optional[int]] = [None]

    def on_playback_requested(file_path: str) -> None:
        logger.info(
            f"Playback requested for: '{file_path}' (Embedded Player: {config.use_embedded_player})"
        )
        if config.use_embedded_player:
            if hasattr(controller, "set_video_playing"):
                controller.set_video_playing(True)
            previous_layout_index[0] = stacked_layout.currentIndex()
            player_view.play_video(file_path)
            stacked_layout.setCurrentIndex(3)
        else:
            try:
                play_video(file_path)
            except Exception:
                logger.exception(f"Failed to launch external player for '{file_path}'")

    controller.playback_requested.connect(on_playback_requested)

    def on_player_back_requested() -> None:
        logger.info("Playback exit requested, returning to previous details view")
        if hasattr(controller, "set_video_playing"):
            controller.set_video_playing(False)

        index = previous_layout_index[0]
        if not isinstance(index, int):
            library_config = config.libraries.get(controller.current_library_name, {})
            if library_config.get("type") == "movie":
                index = 2
            else:
                index = 1
        stacked_layout.setCurrentIndex(index)

    player_view.back_requested.connect(on_player_back_requested)

    def on_watched_marked(file_path: str) -> None:
        logger.info(f"Signal received: marking watched status on '{file_path}'")
        controller.mark_episode_watched(file_path, True)

    player_view.watched_marked.connect(on_watched_marked)

    def on_metadata_dialog_requested(series_name: str) -> None:
        logger.info(f"Opening Metadata Match Dialog for series: '{series_name}'")
        dialog_instance = MetadataMatchDialog(series_name, controller, main_window)
        dialog_instance.exec()

    controller.metadata_dialog_requested.connect(on_metadata_dialog_requested)

    def on_rename_dialog_requested(series_name: str) -> None:
        logger.info(f"Opening Rename Preview Dialog for series: '{series_name}'")
        dialog_instance = RenamePreviewDialog(series_name, controller, main_window)
        dialog_instance.exec()

    controller.rename_dialog_requested.connect(on_rename_dialog_requested)

    def on_jellyfin_dialog_requested(series_name: str) -> None:
        logger.info(f"Opening Jellyfin Match Dialog for series: '{series_name}'")
        dialog_instance = JellyfinMatchDialog(series_name, controller, main_window)
        dialog_instance.exec()

    controller.jellyfin_dialog_requested.connect(on_jellyfin_dialog_requested)

    def on_episode_metadata_dialog_requested(
        series_name: str, episode_path: str
    ) -> None:
        logger.info(
            f"Opening Episode Match Dialog for series '{series_name}', episode: '{episode_path}'"
        )
        dialog_instance = EpisodeMatchDialog(
            series_name, episode_path, controller, main_window
        )
        dialog_instance.exec()

    controller.episode_metadata_dialog_requested.connect(
        on_episode_metadata_dialog_requested
    )

    def on_episode_details_requested(series_name: str, episode_path: str) -> None:
        logger.info(
            f"Opening Episode Details Dialog for series '{series_name}', episode: '{episode_path}'"
        )
        dialog_instance = EpisodeDetailsDialog(
            series_name, episode_path, controller, main_window
        )
        dialog_instance.exec()

    controller.episode_details_requested.connect(on_episode_details_requested)

    def on_movie_details_requested(movie_name: str, movie_path: str) -> None:
        logger.info(
            f"Opening Movie Details Dialog for movie '{movie_name}', path: '{movie_path}'"
        )
        dialog_instance = MovieDetailsDialog(
            movie_name, movie_path, controller, main_window
        )
        dialog_instance.exec()

    controller.movie_details_requested.connect(on_movie_details_requested)

    def on_series_details_requested(series_name: str) -> None:
        logger.info(f"Opening Series Details Dialog for series: '{series_name}'")
        dialog_instance = SeriesDetailsDialog(series_name, controller, main_window)
        if dialog_instance.exec():
            if controller.selected_series_name == "":
                stacked_layout.setCurrentIndex(0)
            else:
                series_detail_view.populate_series_details(series_name)

    controller.series_details_requested.connect(on_series_details_requested)

    controller.status_changed.connect(main_window.statusBar().showMessage)

    # Initialize library dropdown entries
    library_names_list = list(config.libraries.keys())
    logger.debug(f"Populating Library Grid View libraries: {library_names_list}")
    library_grid_view.populate_libraries(library_names_list)

    logger.info("Displaying Main Window. Starting Qt event loop.")
    main_window.show()

    if os.environ.get("LAN_STREAMER_TEST_RUN") == "1":
        logger.info(
            "Test run mode active. Scheduling automatic shutdown in 3 seconds..."
        )

        async def auto_shutdown() -> None:
            await asyncio.sleep(3.0)
            logger.info(
                "Automatic shutdown timer fired. Hiding window to trigger shutdown..."
            )
            main_window.hide()

        asyncio.create_task(auto_shutdown())

    if config.check_for_updates_on_startup and "pytest" not in sys.modules:
        logger.info("Checking for application updates on startup...")
        from lan_streamer.system.updater import UpdateCheckWorker
        from lan_streamer.ui_views.dialogs.update_dialog import UpdateDialog

        # Keep reference to prevent GC
        setattr(main_window, "startup_update_worker", UpdateCheckWorker())
        worker = getattr(main_window, "startup_update_worker")

        def on_startup_check_finished(
            success: bool, release_info: dict, error_msg: str
        ) -> None:
            if success and release_info:
                logger.info(f"Update available on startup: {release_info['version']}")
                dialog = UpdateDialog(
                    current_version=__version__,
                    new_version=release_info["version"],
                    release_notes=release_info["release_notes"],
                    download_url=release_info["download_url"],
                    parent=main_window,
                )
                dialog.exec()
            elif not success:
                logger.warning(f"Startup update check failed: {error_msg}")
            else:
                logger.info("Application is up to date.")

        worker.finished.connect(on_startup_check_finished)
        worker.start()

    # If running under a unit test (mocked QApplication), exit early to avoid blocking/hanging.
    if "mock" in type(application_instance).__name__.lower():
        logger.info(
            "Mock QApplication detected. Exiting main function immediately for testing."
        )
        return

    try:
        import qasync  # noqa: F401

        logger.info("Starting Qt event loop with asyncio integration via qasync.")
        # Prevent Qt from auto-quitting when the window is hidden, giving async teardown time to run.
        application_instance.setQuitOnLastWindowClosed(False)

        # Under qasync, the event loop is already running. We just wait until the app exits.
        app_close_event = asyncio.Event()
        application_instance.aboutToQuit.connect(app_close_event.set)
        while main_window.isVisible() and not app_close_event.is_set():
            await asyncio.sleep(0.1)

        # Await any pending background tasks to ensure they shut down cleanly before loop closes
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pending:
            logger.info(f"Awaiting shutdown of {len(pending)} pending tasks...")
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True), timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for pending tasks to shut down.")
            logger.info("All pending tasks shut down.")
        logger.info("Application teardown complete. Exiting process.")
        os._exit(0)

    except ImportError:
        logger.warning("qasync not available, falling back to synchronous event loop.")
        sys.exit(application_instance.exec())


def run_main() -> None:
    """Synchronous entry point for the async main function.

    Attempts to use qasync for asyncio-Qt event loop integration.
    Falls back to :func:`asyncio.run` if qasync is not available.
    """
    import os
    from PySide6.QtWidgets import QApplication

    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-v", "-V"):
        print(f"lan-streamer {__version__}")
        sys.exit(0)

    if os.environ.get("LAN_STREAMER_DRY_RUN") == "1":
        if not os.environ.get("QT_QPA_PLATFORM"):
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
        app_inst = QApplication.instance()
        if app_inst is None:
            app_inst = QApplication(sys.argv)
        print(
            "LAN Streamer: Dry run verification successful. Qt application successfully initialized."
        )
        os._exit(0)

    try:
        import qasync

        logger.info("Using qasync for asyncio-Qt event loop integration.")
        qasync.run(main())
    except ImportError:
        logger.warning("qasync not available; falling back to :func:`asyncio.run`.")
        asyncio.run(main())


if __name__ == "__main__":
    run_main()
