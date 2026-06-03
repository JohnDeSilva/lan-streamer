# Expose PySide classes and pathlib for tests to patch on this module namespace
from PySide6.QtWidgets import QMessageBox, QFileDialog, QMenu
from PySide6.QtGui import QPixmap
from pathlib import Path

# Expose clients for tests to patch
from lan_streamer.providers.jellyfin import jellyfin_client
from lan_streamer.providers.tmdb import tmdb_client

# Expose backend workers
from lan_streamer.backend import (
    ScanWorker,
    CleanupWorker,
    JellyfinPullWorker,
    JellyfinPushWorker,
    ScanAllLibrariesWorker,
    RuntimeExtractionWorker,
)

# Expose core UI views components
from lan_streamer.ui_views.stylesheet import get_application_stylesheet
from lan_streamer.ui_views.progress_widgets import (
    SegmentedProgressBar,
    ScanProgressTree,
    LibraryScanProgressBar,
)
from lan_streamer.ui_views.controller import Controller
from lan_streamer.ui_views.library_grid import LibraryGridView
from lan_streamer.ui_views.series_detail import SeriesDetailView
from lan_streamer.ui_views.movie_detail import MovieDetailView
from lan_streamer.ui_views.dialogs import (
    MetadataMatchDialog,
    JellyfinMatchDialog,
    SubtitleSearchDialog,
    EpisodeDetailsDialog,
    MovieDetailsDialog,
    SeriesDetailsDialog,
    EpisodeMatchDialog,
    RenamePreviewDialog,
    SettingsDialog,
)

__all__ = [
    "QMessageBox",
    "QFileDialog",
    "QMenu",
    "Path",
    "QPixmap",
    "jellyfin_client",
    "tmdb_client",
    "ScanWorker",
    "CleanupWorker",
    "JellyfinPullWorker",
    "JellyfinPushWorker",
    "ScanAllLibrariesWorker",
    "RuntimeExtractionWorker",
    "get_application_stylesheet",
    "SegmentedProgressBar",
    "ScanProgressTree",
    "LibraryScanProgressBar",
    "Controller",
    "LibraryGridView",
    "SeriesDetailView",
    "MovieDetailView",
    "MetadataMatchDialog",
    "JellyfinMatchDialog",
    "SubtitleSearchDialog",
    "EpisodeDetailsDialog",
    "MovieDetailsDialog",
    "SeriesDetailsDialog",
    "EpisodeMatchDialog",
    "RenamePreviewDialog",
    "SettingsDialog",
]
