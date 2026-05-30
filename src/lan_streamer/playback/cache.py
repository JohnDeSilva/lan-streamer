import logging
from pathlib import Path
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("lan_streamer.player_widget")


class CacheWorker(QThread):
    """Thread for copying media files to local cache."""

    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, src_path: str, dest_path: str) -> None:
        super().__init__()
        self.src_path = Path(src_path)
        self.dest_path = Path(dest_path)

    def run(self) -> None:
        logger.info(f"Starting cache of {self.src_path} to {self.dest_path}")
        try:
            self.dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Use a simple copy for now, could be improved with progress
            total_size = self.src_path.stat().st_size
            copied = 0
            chunk_size = 1024 * 1024  # 1MB

            with open(self.src_path, "rb") as fsrc:
                with open(self.dest_path, "wb") as fdst:
                    while True:
                        buf = fsrc.read(chunk_size)
                        if not buf:
                            break
                        fdst.write(buf)
                        copied += len(buf)
                        self.progress.emit(int((copied / total_size) * 100))

            self.finished.emit(str(self.dest_path))
            logger.info(f"Caching finished: {self.dest_path}")
        except Exception as e:
            logger.exception("Caching failed")
            self.error.emit(str(e))
