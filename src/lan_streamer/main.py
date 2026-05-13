import sys
import logging
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QStackedLayout
from PySide6.QtGui import QPalette, QColor, QFont
from PySide6.QtCore import Qt

from . import db, __version__
from .config import config
from .ui_views import (
    Controller,
    LibraryGridView,
    SeriesDetailView,
    MovieDetailView,
    MetadataMatchDialog,
    RenamePreviewDialog,
    get_application_stylesheet,
)
from .player_widget import VideoPlayerWidget
from .player import play_video


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


def main() -> None:
    log_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    root_logger = logging.getLogger()

    # Map string log level to logging constant
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    root_logger.setLevel(log_level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    def add_file_handler(
        logger_object: logging.Logger,
        filename: str,
        formatter: logging.Formatter,
        info_message: Optional[str] = None,
    ) -> None:
        try:
            from logging.handlers import TimedRotatingFileHandler

            handler = TimedRotatingFileHandler(
                filename,
                when="midnight",
                interval=1,
                backupCount=config.max_log_retention_days,
            )
            handler.suffix = "%Y-%m-%d"
            handler.namer = lambda name: name.replace(".log.", "_") + ".log"
            handler.setFormatter(formatter)
            logger_object.addHandler(handler)
            if logger_object != logging.getLogger():
                logger_object.propagate = False
            if info_message:
                logging.info(info_message)
        except Exception as exc:
            logging.error(f"Could not create log file {filename}: {exc}")

    log_directory = Path(config.log_directory)
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

    if not config.divide_logs_by_service:
        add_file_handler(
            root_logger,
            str(log_directory / "lan-streamer.log"),
            log_formatter,
            f"Logging to {log_directory / 'lan-streamer.log'} (rotated daily)",
        )
    else:
        logging.info("Logging divided into individual service log files")
        add_file_handler(
            logging.getLogger("lan_streamer.db"),
            str(log_directory / "db.log"),
            log_formatter,
        )
        add_file_handler(
            logging.getLogger("lan_streamer.backend"),
            str(log_directory / "backend.log"),
            log_formatter,
        )
        add_file_handler(
            logging.getLogger("lan_streamer.scanner"),
            str(log_directory / "scanner.log"),
            log_formatter,
        )
        add_file_handler(
            logging.getLogger("lan_streamer.jellyfin"),
            str(log_directory / "jellyfin.log"),
            log_formatter,
        )
        add_file_handler(
            logging.getLogger("lan_streamer.tmdb"),
            str(log_directory / "tmdb.log"),
            log_formatter,
        )
        add_file_handler(
            logging.getLogger("lan_streamer.player_widget"),
            str(log_directory / "player.log"),
            log_formatter,
        )
        add_file_handler(
            logging.getLogger("lan_streamer.backup"),
            str(log_directory / "backup.log"),
            log_formatter,
        )

    from .backup import perform_scheduled_backups

    perform_scheduled_backups()

    db.init_db()
    application_instance = QApplication(sys.argv)
    setup_dark_theme(application_instance)

    application_instance.setFont(QFont("Inter", 14))

    main_window = QMainWindow()
    main_window.setWindowTitle(f"LAN Streamer v{__version__}")
    main_window.resize(1600, 1000)
    main_window.setMinimumSize(1200, 800)

    central_widget = QWidget()
    stacked_layout = QStackedLayout(central_widget)
    main_window.setCentralWidget(central_widget)

    controller = Controller()
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
        stacked_layout.setCurrentIndex(1)

    controller.series_selected.connect(on_series_selected)

    def on_movie_selected(movie_name: str) -> None:
        stacked_layout.setCurrentIndex(2)

    controller.movie_selected.connect(on_movie_selected)

    def on_grid_back_requested() -> None:
        stacked_layout.setCurrentIndex(0)

    series_detail_view.back_requested.connect(on_grid_back_requested)
    movie_detail_view.back_requested.connect(on_grid_back_requested)

    def on_playback_requested(file_path: str) -> None:
        if config.use_embedded_player:
            player_view.play_video(file_path)
            stacked_layout.setCurrentIndex(3)
        else:
            try:
                play_video(file_path)
            except Exception as exception_instance:
                logging.error(f"Failed to launch external player: {exception_instance}")

    controller.playback_requested.connect(on_playback_requested)

    def on_player_back_requested() -> None:
        # Determine whether to go back to movie or series detail view
        library_config = config.libraries.get(controller.current_library_name, {})
        if library_config.get("type") == "movie":
            stacked_layout.setCurrentIndex(2)
        else:
            stacked_layout.setCurrentIndex(1)

    player_view.back_requested.connect(on_player_back_requested)

    def on_metadata_dialog_requested(series_name: str) -> None:
        dialog_instance = MetadataMatchDialog(series_name, controller, main_window)
        dialog_instance.exec()

    controller.metadata_dialog_requested.connect(on_metadata_dialog_requested)

    def on_rename_dialog_requested(series_name: str) -> None:
        dialog_instance = RenamePreviewDialog(series_name, controller, main_window)
        dialog_instance.exec()

    controller.rename_dialog_requested.connect(on_rename_dialog_requested)

    controller.status_changed.connect(main_window.statusBar().showMessage)

    # Initialize library dropdown entries
    library_names_list = list(config.libraries.keys())
    library_grid_view.populate_libraries(library_names_list)

    main_window.show()
    sys.exit(application_instance.exec())


if __name__ == "__main__":
    main()
