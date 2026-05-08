import sys
import logging
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

from .ui import MainWindow
from . import db
from .config import config


def setup_dark_theme(app: QApplication):
    app.setStyle("Fusion")

    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)

    app.setPalette(dark_palette)

    app.setStyleSheet(
        "QToolTip { color: #ffffff; background-color: #2a82da; border: 1px solid white; }"
    )


def main():
    log_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    # Timed Rotating File handler (rotates daily at midnight, keeps 7 days)
    def add_file_handler(logger_obj, filename, formatter, info_msg=None):
        try:
            from logging.handlers import TimedRotatingFileHandler

            handler = TimedRotatingFileHandler(
                filename, when="midnight", interval=1, backupCount=7
            )
            handler.suffix = "%Y-%m-%d"
            handler.namer = lambda name: name.replace(".log.", "_") + ".log"
            handler.setFormatter(formatter)
            logger_obj.addHandler(handler)
            # Prevent propagation to root logger to keep console clean (only Global log in console)
            if logger_obj != logging.getLogger():
                logger_obj.propagate = False
            if info_msg:
                logging.info(info_msg)
        except Exception as e:
            logging.error(f"Could not create log file {filename}: {e}")

    # Ensure log directory exists
    log_dir = Path(config.log_directory)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Global log (Optional file logging, always to console)
    if config.enable_global_file_logging:
        add_file_handler(
            root_logger,
            str(log_dir / "lan-streamer.log"),
            log_formatter,
            f"Logging to {log_dir / 'lan-streamer.log'} (rotated daily)",
        )
    else:
        logging.info(
            "Global logging to console only (file logging disabled in settings)"
        )

    # Component-specific logs
    add_file_handler(
        logging.getLogger("lan_streamer.db"), str(log_dir / "db.log"), log_formatter
    )
    add_file_handler(
        logging.getLogger("lan_streamer.ui"), str(log_dir / "ui.log"), log_formatter
    )
    add_file_handler(
        logging.getLogger("lan_streamer.scanner"),
        str(log_dir / "scanner.log"),
        log_formatter,
    )
    add_file_handler(
        logging.getLogger("lan_streamer.jellyfin"),
        str(log_dir / "jellyfin.log"),
        log_formatter,
    )
    add_file_handler(
        logging.getLogger("lan_streamer.tmdb"),
        str(log_dir / "tmdb.log"),
        log_formatter,
    )

    recreated = db.init_db()
    app = QApplication(sys.argv)
    setup_dark_theme(app)

    window = MainWindow(recreated_db=recreated)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
