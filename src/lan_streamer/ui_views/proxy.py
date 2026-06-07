import logging
import sys
from typing import Any, Callable
from PySide6.QtWidgets import (
    QMessageBox as QMessageBox_real,
    QFileDialog as QFileDialog_real,
    QMenu as QMenu_real,
)
from PySide6.QtGui import QPixmap as QPixmap_real
from lan_streamer.backend import (
    ScanWorker as ScanWorker_real,
    CleanupWorker as CleanupWorker_real,
    JellyfinPullWorker as JellyfinPullWorker_real,
    JellyfinPushWorker as JellyfinPushWorker_real,
    ScanAllLibrariesWorker as ScanAllLibrariesWorker_real,
    RuntimeExtractionWorker as RuntimeExtractionWorker_real,
)
from lan_streamer.providers.jellyfin import jellyfin_client as jellyfin_client_real
from lan_streamer.providers.tmdb import tmdb_client as tmdb_client_real
from lan_streamer.providers.myanimelist import (
    myanimelist_client as myanimelist_client_real,
)

logger = logging.getLogger(__name__)


class PatchedClass:
    def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None:
        self.attr_name = attr_name
        self.default_factory = default_factory

    def _get_target(self) -> Any:
        module = sys.modules.get("lan_streamer.ui_views")
        if module and hasattr(module, self.attr_name):
            return getattr(module, self.attr_name)
        return self.default_factory()

    def __getattr__(self, item: str) -> Any:
        attr = getattr(self._get_target(), item)
        if (
            self.attr_name in ("QMessageBox", "QFileDialog")
            and callable(attr)
            and not isinstance(attr, type)
        ):

            def wrapper(*args: Any, **kwargs: Any) -> Any:
                logger.info(
                    f"UI Dialog Prompt: {self.attr_name}.{item} called with args={args}, kwargs={kwargs}"
                )
                return attr(*args, **kwargs)

            return wrapper
        return attr

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.attr_name in ("QMessageBox", "QFileDialog"):
            logger.info(
                f"UI Dialog Prompt: Instantiating {self.attr_name} with args={args}, kwargs={kwargs}"
            )
        return self._get_target()(*args, **kwargs)


# Proxies
QMessageBox = PatchedClass("QMessageBox", lambda: QMessageBox_real)
QFileDialog = PatchedClass("QFileDialog", lambda: QFileDialog_real)
QMenu = PatchedClass("QMenu", lambda: QMenu_real)
QPixmap = PatchedClass("QPixmap", lambda: QPixmap_real)

ScanWorker = PatchedClass("ScanWorker", lambda: ScanWorker_real)
CleanupWorker = PatchedClass("CleanupWorker", lambda: CleanupWorker_real)
JellyfinPullWorker = PatchedClass("JellyfinPullWorker", lambda: JellyfinPullWorker_real)
JellyfinPushWorker = PatchedClass("JellyfinPushWorker", lambda: JellyfinPushWorker_real)
ScanAllLibrariesWorker = PatchedClass(
    "ScanAllLibrariesWorker", lambda: ScanAllLibrariesWorker_real
)
RuntimeExtractionWorker = PatchedClass(
    "RuntimeExtractionWorker", lambda: RuntimeExtractionWorker_real
)

jellyfin_client = PatchedClass("jellyfin_client", lambda: jellyfin_client_real)
tmdb_client = PatchedClass("tmdb_client", lambda: tmdb_client_real)
myanimelist_client = PatchedClass("myanimelist_client", lambda: myanimelist_client_real)
