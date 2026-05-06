import sys
import logging
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

from .ui import MainWindow
from . import db


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

    # File handler in the current working directory
    try:
        file_handler = logging.FileHandler("lan-streamer.log")
        file_handler.setFormatter(log_formatter)
        root_logger.addHandler(file_handler)
        logging.info("Logging to lan-streamer.log in current directory")
    except Exception as e:
        logging.error(f"Could not create log file: {e}")

    recreated = db.init_db()
    app = QApplication(sys.argv)
    setup_dark_theme(app)

    window = MainWindow(recreated_db=recreated)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
