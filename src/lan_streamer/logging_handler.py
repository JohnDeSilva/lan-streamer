import logging
from collections import deque
from typing import Deque, List, Tuple
from PySide6.QtCore import QObject, Signal


class LogSignalEmitter(QObject):
    """QObject that emits a signal when a log record is processed."""

    log_emitted: Signal = Signal(str, str)


class QtLogHandler(logging.Handler):
    """
    Custom logging handler that collects log records in a rolling buffer
    and broadcasts them using a thread-safe Qt signal.
    """

    def __init__(self, capacity: int = 1000) -> None:
        super().__init__()
        self.emitter: LogSignalEmitter = LogSignalEmitter()
        self.buffer: Deque[Tuple[str, str]] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            formatted_message: str = self.format(record)
            level_name: str = record.levelname
            self.buffer.append((formatted_message, level_name))
            self.emitter.log_emitted.emit(formatted_message, level_name)
        except Exception:
            self.handleError(record)


# Global handler instance accessible from anywhere in the application
qt_log_handler: QtLogHandler = QtLogHandler()


# Global list of service loggers configured in the application
SERVICE_LOGGERS: List[str] = [
    "lan_streamer.db",
    "lan_streamer.backend",
    "lan_streamer.scanner",
    "lan_streamer.jellyfin",
    "lan_streamer.tmdb",
    "lan_streamer.player_widget",
    "lan_streamer.player",
    "lan_streamer.backup",
    "lan_streamer.opensubtitles",
    "lan_streamer.wakelock",
    "lan_streamer.ui_views",
    "lan_streamer.main",
    "lan_streamer.renamer",
]


def setup_qt_logging(formatter: logging.Formatter) -> None:
    """
    Registers the global QtLogHandler to the root logger and service loggers
    so that all application logs can be monitored in real-time.
    """
    qt_log_handler.setFormatter(formatter)

    root_logger: logging.Logger = logging.getLogger()
    if qt_log_handler not in root_logger.handlers:
        root_logger.addHandler(qt_log_handler)

    from .config import config

    if config.divide_logs_by_service:
        for logger_name in SERVICE_LOGGERS:
            srv_logger: logging.Logger = logging.getLogger(logger_name)
            if qt_log_handler not in srv_logger.handlers:
                srv_logger.addHandler(qt_log_handler)


def set_application_log_level(level_name: str) -> None:
    """
    Updates the log level of the root logger and all service loggers dynamically.
    """
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.getLogger().setLevel(level)
    for logger_name in SERVICE_LOGGERS:
        logging.getLogger(logger_name).setLevel(level)
