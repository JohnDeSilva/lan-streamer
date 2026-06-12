# Backward-compatible metadata_workers module re-exporting split sub-modules.
from lan_streamer.backend.proxy import (
    db,
    config,
    jellyfin_client,
    get_detailed_file_info,
    scan_series,
    scan_movie,
    clean_series_data,
)
from lan_streamer.backend.metadata_worker_property import FilePropertyExtractionWorker
from lan_streamer.backend.metadata_worker_subtitle import SubtitleMergeWorker
from lan_streamer.backend.metadata_worker_embed import (
    MetadataEmbedWorker,
    SeriesMetadataEmbedWorker,
)
from lan_streamer.backend.metadata_worker_refresh import RefreshSeriesWorker

__all__ = [
    "FilePropertyExtractionWorker",
    "SubtitleMergeWorker",
    "MetadataEmbedWorker",
    "SeriesMetadataEmbedWorker",
    "RefreshSeriesWorker",
    "db",
    "config",
    "jellyfin_client",
    "get_detailed_file_info",
    "scan_series",
    "scan_movie",
    "clean_series_data",
]
