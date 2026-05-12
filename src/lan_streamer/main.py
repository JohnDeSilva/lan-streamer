import sys
import logging
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QStackedLayout
from PySide6.QtGui import QPalette, QColor, QFont
from PySide6.QtCore import Qt, QUrl
from PySide6.QtQuickWidgets import QQuickWidget

from . import db, __version__
from .config import config
from .backend import BackendBridge
from .player_widget import VideoPlayerWidget


def setup_dark_theme(application_instance: QApplication) -> None:
    application_instance.setStyle("Fusion")

    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)

    application_instance.setPalette(dark_palette)

    application_instance.setStyleSheet(
        "QToolTip { color: #ffffff; background-color: #2a82da; border: 1px solid white; }"
    )


def main() -> None:
    log_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    def add_file_handler(
        logger_object: logging.Logger,
        filename: str,
        formatter: logging.Formatter,
        info_message: str | None = None,
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
        for p in log_directory.glob("*.log*"):
            if p.is_file() and p.stat().st_mtime < cutoff:
                try:
                    p.unlink()
                except Exception:
                    pass
    except Exception as exc:
        logging.debug(f"Error cleaning old logs: {exc}")

    if config.enable_global_file_logging:
        add_file_handler(
            root_logger,
            str(log_directory / "lan-streamer.log"),
            log_formatter,
            f"Logging to {log_directory / 'lan-streamer.log'} (rotated daily)",
        )
    else:
        logging.info(
            "Global logging to console only (file logging disabled in settings)"
        )

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

    qml_view = QQuickWidget(main_window)
    qml_view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)

    backend_bridge = BackendBridge()
    qml_view.rootContext().setContextProperty("backendBridge", backend_bridge)

    qml_file_path = Path(__file__).parent / "assets" / "main.qml"
    qml_view.setSource(QUrl.fromLocalFile(str(qml_file_path)))

    player_view = VideoPlayerWidget()

    stacked_layout.addWidget(qml_view)
    stacked_layout.addWidget(player_view)

    def on_playback_requested(file_path: str) -> None:
        player_view.play_video(file_path)
        stacked_layout.setCurrentIndex(1)

    backend_bridge.playbackRequested.connect(on_playback_requested)

    def on_back_requested() -> None:
        stacked_layout.setCurrentIndex(0)

    player_view.back_requested.connect(on_back_requested)

    main_window.show()

    if qml_view.status() == QQuickWidget.Status.Error:
        sys.exit(-1)
        return

    sys.exit(application_instance.exec())


if __name__ == "__main__":
    main()
