# Backward-compatible scan_workers module re-exporting split sub-modules.
from lan_streamer.backend.proxy import (
    db,
    config,
    jellyfin_client,
    scan_directories,
    discover_single_library_tree,
)
from lan_streamer.backend.scan_worker_single import (
    _discover_single_library_tree_impl,
    ScanWorker,
)
from lan_streamer.backend.scan_worker_all import ScanAllLibrariesWorker
from lan_streamer.backend.scan_worker_cleanup import CleanupWorker

# Keep original name _discover_single_library_tree_impl for references
_discover_single_library_tree_impl = _discover_single_library_tree_impl

__all__ = [
    "_discover_single_library_tree_impl",
    "ScanWorker",
    "ScanAllLibrariesWorker",
    "CleanupWorker",
    "db",
    "config",
    "jellyfin_client",
    "scan_directories",
    "discover_single_library_tree",
]
