# Expose PySide classes and pathlib for tests to patch on this module namespace
from pathlib import Path

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox

# Expose backend workers
from lan_streamer.backend import (
    CleanupWorker,
    FilePropertyExtractionWorker,
    JellyfinPullWorker,
    JellyfinPushWorker,
    ScanAllLibrariesWorker,
)

# Expose clients for tests to patch
from lan_streamer.providers.jellyfin import jellyfin_client
from lan_streamer.providers.tmdb import tmdb_client
from lan_streamer.ui_views.cast_detail import CastDetailView
from lan_streamer.ui_views.controller import Controller
from lan_streamer.ui_views.dialogs import (
    EpisodeDetailsDialog,
    EpisodeMatchDialog,
    JellyfinMatchDialog,
    MetadataMatchDialog,
    MovieDetailsDialog,
    RenamePreviewDialog,
    SearchDialog,
    SeriesDetailsDialog,
    SettingsDialog,
    SubtitleSearchDialog,
    UpdateDialog,
)
from lan_streamer.ui_views.library_grid import LibraryGridView
from lan_streamer.ui_views.movie_detail import MovieDetailView
from lan_streamer.ui_views.progress_widgets import (
    LibraryScanProgressBar,
    ScanProgressTree,
    SegmentedProgressBar,
)
from lan_streamer.ui_views.season_detail import SeasonDetailView
from lan_streamer.ui_views.series_detail import SeriesDetailView

# Expose core UI views components
from lan_streamer.ui_views.stylesheet import get_application_stylesheet
