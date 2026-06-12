import logging
from typing import List, Optional
from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer.backend.proxy import db

logger = logging.getLogger("lan_streamer.backend")


class CleanupWorker(QThread):
    """Removes missing series/seasons/episodes from the database."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        library_name: str,
        root_directories: List[str],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.library_name: str = library_name
        self.root_directories: List[str] = root_directories

    def run(self) -> None:
        try:
            logger.info(f"CleanupWorker starting for library {self.library_name}")
            results = db.cleanup_library(self.library_name, self.root_directories)
            logger.info(f"CleanupWorker finished with results: {results}")
            self.finished.emit(results)
        except Exception as exc:
            logger.exception("CleanupWorker failed")
            self.error.emit(str(exc))
