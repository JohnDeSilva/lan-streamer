# Class Structure and Inheritance Reference

This document details the classes, inheritance trees, docstrings, and detailed method signatures within the `lan-streamer` codebase. It serves as a developer guide to understanding the object-oriented structure of the application.

---

## 🌳 Class Inheritance Paths

Below is the structured textual representation of all major class inheritance paths in the `lan-streamer` codebase:

### 1. Database Models (`SQLAlchemy`)
- `DeclarativeBase`
  - `Base`
    - `Series` (represents a television series)
    - `Season` (represents a television season)
    - `Episode` (represents a single television episode)
    - `Movie` (represents a single movie)

### 2. Background Thread Workers (`QThread`)
- `QThread` (PySide6)
  - `CacheWorker` (copies network share media locally)
  - `CleanupWorker` (cleans up a single media library)
  - `JellyfinPullWorker` (pulls watch history from Jellyfin user database)
  - `JellyfinPushWorker` (syncs watched episodes/movies to Jellyfin server)
  - `MetadataEmbedWorker` (embeds movie/episode metadata tags using ffmpeg copy pipelines)
  - `RefreshSeriesWorker` (re-scans folder metadata for a specific series/movie)
  - `RuntimeExtractionWorker` (extracts runtimes, codec, audio/subtitle tracks via ffprobe)
  - `ScanAllLibrariesWorker` (runs sequential scans on all libraries)
  - `ScanWorker` (scans a specific TV or movie library directory using TMDB clients)
  - `SeriesMetadataEmbedWorker` (recursively embeds metadata for all episodes in a series)
  - `SubtitleMergeWorker` (merges downloaded `.srt` subtitles into a video container)

### 3. User Interface Dialogs (`QDialog`)
- `QDialog` (PySide6)
  - `EpisodeDetailsDialog` (detailed view with metadata edit, remote search, and ffmpeg embedding options)
  - `EpisodeMatchDialog` (custom matching for a single episode)
  - `JellyfinMatchDialog` (modal search mapping Jellyfin watch history IDs)
  - `MetadataMatchDialog` (modal search mapping TMDB series/movie metadata IDs)
  - `MovieDetailsDialog` (detailed movie properties and actions)
  - `RenamePreviewDialog` (preview interface displaying proposed file rename operations)
  - `SeriesDetailsDialog` (overview of series attributes and locking toggle)
  - `SettingsDialog` (tabbed dialog for general, logging, caching, and library path preferences)
  - `SubtitleSearchDialog` (search results and remote subtitle download options)

### 4. User Interface Widgets (`QWidget`)
- `QWidget` (PySide6)
  - `LibraryGridView` (responsive list view displaying parsed library assets)
  - `LibraryScanProgressBar` (main segmented library scanning bar)
  - `MovieDetailView` (expanded detailed view of a selected movie)
  - `ScanProgressTree` (collapsible execution tree detail during scanning)
  - `SegmentedProgressBar` (base segmented progress bar component)
  - `SeriesDetailView` (split view of poster, episodes, and next episode trigger)
  - `VideoPlayerWidget` (embedded libvlc media player containing all sliders, speed selectors, and overlays)
  - `VerticalMediaButton` (nested layout widget for vertical player buttons)

---

## Table of Contents
- [Database Models](#database-models)
- [Background Workers (QThread)](#background-workers-qthread)
- [User Interface Views (QWidget / QDialog)](#user-interface-views-qwidget--qdialog)
- [System Configuration & Logging](#system-configuration-&-logging)
- [Provider Clients](#provider-clients)
- [Dynamic Proxies & Monkey Patching](#dynamic-proxies-&-monkey-patching)
- [Other Helper Classes](#other-helper-classes)

## Database Models

### `Base`
- **Defined in**: [models.py](../src/lan_streamer/db/models.py#L18) (line 18)
- **Inherits from**: `DeclarativeBase`

> SQLAlchemy declarative base class for database models.

---

### `Episode`
- **Defined in**: [models.py](../src/lan_streamer/db/models.py#L81) (line 81)
- **Inherits from**: `Base`

> Database model representing a single television show episode, including technical video characteristics and watch status.

---

### `Movie`
- **Defined in**: [models.py](../src/lan_streamer/db/models.py#L118) (line 118)
- **Inherits from**: `Base`

> Database model representing a movie, including technical properties and watch status.

---

### `Season`
- **Defined in**: [models.py](../src/lan_streamer/db/models.py#L52) (line 52)
- **Inherits from**: `Base`

> Database model representing a specific season of a television series.

---

### `Series`
- **Defined in**: [models.py](../src/lan_streamer/db/models.py#L24) (line 24)
- **Inherits from**: `Base`

> Database model representing a television series, containing references to seasons and metadata.

---

## Background Workers (QThread)

### `CacheWorker`
- **Defined in**: [cache.py](../src/lan_streamer/playback/cache.py#L8) (line 8)
- **Inherits from**: `QThread`

> Thread for copying media files to local cache.

**Methods**:
- `def __init__(self, src_path: str, dest_path: str) -> None`

- `def run(self) -> None`

---

### `CleanupWorker`
- **Defined in**: [scan_workers.py](../src/lan_streamer/backend/scan_workers.py#L120) (line 120)
- **Inherits from**: `QThread`

> Removes missing series/seasons/episodes from the database.

**Methods**:
- `def __init__(self, library_name: str, root_directories: List[str], parent: Optional[QObject]=None) -> None`

- `def run(self) -> None`

---

### `JellyfinPullWorker`
- **Defined in**: [jellyfin_workers.py](../src/lan_streamer/backend/jellyfin_workers.py#L10) (line 10)
- **Inherits from**: `QThread`

> Pulls watch history from Jellyfin and syncs it to the local DB.

**Methods**:
- `def run(self) -> None`

---

### `JellyfinPushWorker`
- **Defined in**: [jellyfin_workers.py](../src/lan_streamer/backend/jellyfin_workers.py#L34) (line 34)
- **Inherits from**: `QThread`

> Pushes all local watched state to Jellyfin.

**Methods**:
- `def run(self) -> None`

---

### `MetadataEmbedWorker`
- **Defined in**: [metadata_workers.py](../src/lan_streamer/backend/metadata_workers.py#L147) (line 147)
- **Inherits from**: `QThread`

> Background worker that uses ffmpeg to embed metadata into a video container.
> Typed with static typing.

**Methods**:
- `def __init__(self, video_path: str, metadata: Dict[str, str], parent: Optional[QObject]=None) -> None`

- `def run(self) -> None`

---

### `RefreshSeriesWorker`
- **Defined in**: [metadata_workers.py](../src/lan_streamer/backend/metadata_workers.py#L283) (line 283)
- **Inherits from**: `QThread`

> Refreshes metadata for a single series or movie by scanning its folder directly.

**Methods**:
- `def __init__(self, library_name: str, item_name: str, library_type: str, root_directories: List[str], existing_library: Dict[str, Any], parent: Optional[QObject]=None) -> None`

- `def run(self) -> None`

---

### `RuntimeExtractionWorker`
- **Defined in**: [metadata_workers.py](../src/lan_streamer/backend/metadata_workers.py#L20) (line 20)
- **Inherits from**: `QThread`

> Processes videos sequentially in the background to extract missing runtimes and technical metadata.

**Methods**:
- `def run(self) -> None`

---

### `ScanAllLibrariesWorker`
- **Defined in**: [scan_workers.py](../src/lan_streamer/backend/scan_workers.py#L149) (line 149)
- **Inherits from**: `QThread`

> Scans all configured libraries sequentially using TMDB for metadata.

**Methods**:
- `def __init__(self, force_refresh: bool=False, parent: Optional[QObject]=None) -> None`

- `def _discover_tree(self) -> Dict[str, Any]`
  > Pre-walks all library directories to count total folders and files
  > so the UI can initialise the tree and segmented progress bar before
  > scanning begins.  Returns a structure keyed by library name.

- `def run(self) -> None`

---

### `ScanWorker`
- **Defined in**: [scan_workers.py](../src/lan_streamer/backend/scan_workers.py#L51) (line 51)
- **Inherits from**: `QThread`

> Scans a single library directory using TMDB for metadata.

**Methods**:
- `def __init__(self, root_directories: List[str], library_type: str, existing_library: Dict[str, Any], force_refresh: bool=False, cleanup: bool=False, parent: Optional[QObject]=None, library_name: str='') -> None`

- `def run(self) -> None`

---

### `SeriesMetadataEmbedWorker`
- **Defined in**: [metadata_workers.py](../src/lan_streamer/backend/metadata_workers.py#L202) (line 202)
- **Inherits from**: `QThread`

> Background worker that embeds metadata for all episodes in a series.
> Typed with static typing.

**Methods**:
- `def __init__(self, series_name: str, episodes: List[Dict[str, Any]], parent: Optional[QObject]=None) -> None`

- `def run(self) -> None`

---

### `SubtitleMergeWorker`
- **Defined in**: [metadata_workers.py](../src/lan_streamer/backend/metadata_workers.py#L64) (line 64)
- **Inherits from**: `QThread`

> Merges external subtitle files into a video container using ffmpeg.

**Methods**:
- `def __init__(self, video_path: str, subtitle_paths: List[str], parent: Optional[QObject]=None) -> None`

- `def run(self) -> None`

---

## User Interface Views (QWidget / QDialog)

### `EpisodeDetailsDialog`
- **Defined in**: [details.py](../src/lan_streamer/ui_views/dialogs/details.py#L29) (line 29)
- **Inherits from**: `QDialog`

> Comprehensive multi-tab interface for viewing/editing episode metadata
> and inspecting technical file characteristics.

**Methods**:
- `def __init__(self, series_name: str, episode_path: str, controller_instance: 'Controller', parent: Optional[QWidget]=None) -> None`

- `def _create_file_info_tab(self) -> QWidget`

- `def _create_metadata_tab(self) -> QWidget`

- `def _load_data(self) -> None`

- `def _on_embed_clicked(self) -> None`
  > Collects current UI metadata and triggers embedding.

- `def _on_merge_clicked(self) -> None`

- `def _on_refresh_clicked(self) -> None`

- `def _on_save_clicked(self) -> None`

- `def _on_search_osub_clicked(self) -> None`

- `def _on_search_tmdb_clicked(self) -> None`

- `def _refresh_file_info(self) -> None`

- `def _setup_ui(self) -> None`

---

### `EpisodeMatchDialog`
- **Defined in**: [rename.py](../src/lan_streamer/ui_views/dialogs/rename.py#L25) (line 25)
- **Inherits from**: `QDialog`

> Modal dialog allowing users to match metadata on TMDB for an individual episode of a show.
> Conforms to static typing standards.

**Methods**:
- `def __init__(self, series_name: str, episode_path: str, controller_instance: 'Controller', parent: Optional[QWidget]=None) -> None`

- `def _populate_seasons(self) -> None`

- `def _setup_ui(self) -> None`

- `def apply_selected(self) -> None`

- `def on_season_changed(self, season_text: str) -> None`

---

### `JellyfinMatchDialog`
- **Defined in**: [metadata_match.py](../src/lan_streamer/ui_views/dialogs/metadata_match.py#L178) (line 178)
- **Inherits from**: `QDialog`

> Search modal to retrieve series or movie IDs specifically from Jellyfin for watch history correlation.
> Typed with static typing.

**Methods**:
- `def __init__(self, series_name: str, controller_instance: 'Controller', parent: Optional[QWidget]=None) -> None`

- `def _setup_ui(self) -> None`

- `def apply_selected(self) -> None`

- `def execute_search(self) -> None`

---

### `LibraryGridView`
- **Defined in**: [library_grid.py](../src/lan_streamer/ui_views/library_grid.py#L32) (line 32)
- **Inherits from**: `QWidget`

> Responsive Grid View displaying series items using custom layout sizing.
> Conforms to typing requirements.

**Methods**:
- `def __init__(self, controller_instance: Controller, parent: Optional[QWidget]=None) -> None`

- `def _assign_item_icon(self, item_target: QListWidgetItem, poster_path_value: str) -> None`

- `def _assign_item_icon_with_size(self, item_target: QListWidgetItem, poster_path_value: str, width: int, height: int) -> None`

- `def _on_detail_progress(self, event: str, payload: Dict[str, Any]) -> None`

- `def _on_scan_completed(self) -> None`

- `def _setup_ui(self) -> None`

- `def _wire_signals(self) -> None`

- `def on_combined_item_clicked(self, item_target: QListWidgetItem) -> None`

- `def on_item_clicked(self, item_target: QListWidgetItem) -> None`

- `def on_library_changed(self, library_name: str) -> None`

- `def on_library_tab_changed(self, index: int) -> None`

- `def on_order_changed(self, text: str) -> None`

- `def open_settings_dialog(self) -> None`

- `def populate_combined_view(self) -> None`

- `def populate_grid(self) -> None`

- `def populate_libraries(self, library_names: List[str]) -> None`

- `def trigger_combined_scan(self) -> None`

---

### `LibraryScanProgressBar`
- **Defined in**: [progress_widgets.py](../src/lan_streamer/ui_views/progress_widgets.py#L536) (line 536)
- **Inherits from**: `QWidget`

> A custom progress bar divided into labelled root directory segments.
> Within each root directory segment, series/movie folders are drawn as sub-segments.
> Progress is filled independently as series/movies are processed.

**Methods**:
- `def __init__(self, parent: Optional[QWidget]=None) -> None`

- `def init_from_roots(self, roots: Dict[str, List[str]], roots_order: List[str]) -> None`
  > Called with the initial discovery {root_dir: [folder1, folder2, ...]}.

- `def mark_folder_active(self, root_dir: str, folder_name: str) -> None`

- `def mark_folder_done(self, root_dir: str, folder_name: str) -> None`

- `def paintEvent(self, event: Any) -> None`

---

### `MetadataMatchDialog`
- **Defined in**: [metadata_match.py](../src/lan_streamer/ui_views/dialogs/metadata_match.py#L24) (line 24)
- **Inherits from**: `QDialog`

> Search modal to retrieve metadata from external matching provider APIs.
> Typed with static typing.

**Methods**:
- `def __init__(self, series_name: str, controller_instance: 'Controller', parent: Optional[QWidget]=None) -> None`

- `def _setup_ui(self) -> None`

- `def apply_selected(self) -> None`

- `def execute_search(self) -> None`

---

### `MovieDetailView`
- **Defined in**: [movie_detail.py](../src/lan_streamer/ui_views/movie_detail.py#L23) (line 23)
- **Inherits from**: `QWidget`

> Presents movie details, overview, artwork, and direct playback controls.
> Enforces strict typing and zero-abbreviation naming standard.

**Methods**:
- `def __init__(self, controller_instance: Controller, parent: Optional[QWidget]=None) -> None`

- `def _on_play_clicked(self) -> None`

- `def _setup_ui(self) -> None`

- `def on_library_loaded(self) -> None`

- `def populate_movie_details(self, movie_name: str) -> None`

---

### `MovieDetailsDialog`
- **Defined in**: [details.py](../src/lan_streamer/ui_views/dialogs/details.py#L357) (line 357)
- **Inherits from**: `QDialog`

> Comprehensive multi-tab interface for viewing/editing movie metadata
> and inspecting technical file characteristics.

**Methods**:
- `def __init__(self, movie_name: str, movie_path: str, controller_instance: 'Controller', parent: Optional[QWidget]=None) -> None`

- `def _create_file_info_tab(self) -> QWidget`

- `def _create_metadata_tab(self) -> QWidget`

- `def _on_embed_clicked(self) -> None`
  > Collects current UI metadata and triggers embedding.

- `def _on_merge_clicked(self) -> None`

- `def _on_refresh_clicked(self) -> None`

- `def _on_save_clicked(self) -> None`

- `def _on_search_osub_clicked(self) -> None`

- `def _on_search_tmdb_clicked(self) -> None`

- `def _refresh_file_info(self) -> None`

- `def _setup_ui(self) -> None`

---

### `RenamePreviewDialog`
- **Defined in**: [rename.py](../src/lan_streamer/ui_views/dialogs/rename.py#L209) (line 209)
- **Inherits from**: `QDialog`

> Dialog displaying generated file renaming mapping previews for consistent file hygiene.
> Conforms to static typing constraints.

**Methods**:
- `def __init__(self, series_name: str, controller_instance: 'Controller', parent: Optional[QWidget]=None) -> None`

- `def _setup_ui(self) -> None`

- `def apply_renames(self) -> None`

- `def generate_preview(self) -> None`

---

### `ScanProgressTree`
- **Defined in**: [progress_widgets.py](../src/lan_streamer/ui_views/progress_widgets.py#L211) (line 211)
- **Inherits from**: `QWidget`

> Scrollable, collapsible tree showing the real-time scan progress.
>
> Hierarchy:
>   Library  →  Root directory  →  Series/Movie folder
>     (TV only)  →  Season  →  Episode file
>
> Movie libraries do NOT show individual file nodes.
> Each node carries a status icon: ⏳ pending · ⚙ processing · ✓ done · ⊘ skipped.

**Methods**:
- `def __init__(self, parent: Optional[QWidget]=None) -> None`

- `def _find_folder_node(self, library: str, folder: str) -> Optional[QTreeWidgetItem]`
  > Return the folder node for the first matching root key.

- `def _folder_key(self, library: str, root: str, folder: str) -> str`

- `def _on_collapse_all(self) -> None`

- `def _on_expand_all(self) -> None`

- `def _season_key(self, library: str, folder: str, season: str) -> str`

- `def init_from_tree(self, tree: Dict[str, Any], library_order: Optional[List[str]]=None, library_config_source: Optional[Dict[str, Dict[str, Any]]]=None) -> None`
  > Builds the initial tree with all folder, season, and file nodes in pending state.

- `def mark_file_active(self, file_path: str, library: str, folder: str, season: str='') -> None`
  > Add an episode file node.  For movie libraries this is a no-op.

- `def mark_file_done(self, file_path: str) -> None`

- `def mark_folder_active(self, library: str, root: str, folder: str) -> None`

- `def mark_folder_done(self, library: str, root: str, folder: str, skipped: bool=False) -> None`

- `def mark_library_active(self, library_name: str) -> None`

- `def mark_library_done(self, library_name: str) -> None`

- `def mark_season_active(self, library: str, folder: str, season: str) -> None`
  > Create the season node under its parent series folder if not yet present.

- `def mark_season_done(self, library: str, folder: str, season: str) -> None`

- `def reset(self) -> None`

---

### `SegmentedProgressBar`
- **Defined in**: [progress_widgets.py](../src/lan_streamer/ui_views/progress_widgets.py#L21) (line 21)
- **Inherits from**: `QWidget`

> A custom progress bar divided into labelled library segments.
> Within each library segment, root-directory sub-segments are drawn as
> darker shaded inner regions.  Progress is filled from left to right within
> each segment independently.

**Methods**:
- `def __init__(self, parent: Optional[QWidget]=None) -> None`

- `def advance_root(self, root_dir: str) -> None`
  > Increment the done counter for a root directory.

- `def init_from_tree(self, tree: Dict[str, Any], library_order: Optional[List[str]]=None, library_config_source: Optional[Dict[str, Dict[str, Any]]]=None) -> None`
  > Called once with the pre-discovery tree structure.

- `def mark_library_active(self, library_name: str) -> None`

- `def mark_library_done(self, library_name: str) -> None`

- `def paintEvent(self, event: Any) -> None`

---

### `SeriesDetailView`
- **Defined in**: [series_detail.py](../src/lan_streamer/ui_views/series_detail.py#L34) (line 34)
- **Inherits from**: `QWidget`

> Presents exhaustive series structure tabs, season tables, and direct execution actions.
> Enforces strict typing and zero-abbreviation naming standard.

**Methods**:
- `def __init__(self, controller_instance: Controller, parent: Optional[QWidget]=None) -> None`

- `def _on_mark_season_watched(self, season_name: str) -> None`

- `def _on_mark_series_watched(self) -> None`

- `def _on_play_next_clicked(self) -> None`

- `def _setup_ui(self) -> None`

- `def on_library_loaded(self) -> None`

- `def populate_series_details(self, series_name: str) -> None`

- `def trigger_episode_playback_by_row(self, season_tab_index: int, row_index: int) -> None`
  > Test Helper triggering playback by simulating a click on the episode title cell.

---

### `SeriesDetailsDialog`
- **Defined in**: [details.py](../src/lan_streamer/ui_views/dialogs/details.py#L678) (line 678)
- **Inherits from**: `QDialog`

> Comprehensive dialog for managing series-level metadata and bulk actions.

**Methods**:
- `def __init__(self, series_name: str, controller_instance: 'Controller', parent: Optional[QWidget]=None) -> None`

- `def _on_embed_clicked(self) -> None`

- `def _on_mark_watched_clicked(self) -> None`

- `def _on_match_jellyfin_clicked(self) -> None`

- `def _on_match_meta_clicked(self) -> None`

- `def _on_refresh_clicked(self) -> None`

- `def _on_rename_clicked(self) -> None`

- `def _on_save_clicked(self) -> None`

- `def _setup_ui(self) -> None`

---

### `SettingsDialog`
- **Defined in**: [settings.py](../src/lan_streamer/ui_views/dialogs/settings.py#L44) (line 44)
- **Inherits from**: `QDialog`

> Configuration modal encapsulating system directory management and operational behaviors.

**Methods**:
- `def __init__(self, controller_instance: Optional['Controller']=None, parent: Optional[QWidget]=None) -> None`

- `def _clear_log_view(self) -> None`

- `def _complete_jellyfin_progress(self, message_text: str) -> None`

- `def _copy_logs_to_clipboard(self) -> None`

- `def _create_header_with_info(self, text: str, info_text: str) -> QWidget`

- `def _disconnect_logging(self) -> None`

- `def _export_logs(self) -> None`

- `def _format_log_to_html(self, message: str, level_name: str) -> str`

- `def _get_default_row_name(self, row: Dict[str, Any]) -> str`

- `def _get_level_value(self, level_name: str) -> int`

- `def _load_config(self) -> None`

- `def _on_combined_view_selected(self) -> None`

- `def _on_detail_progress(self, event: str, payload: Dict[str, Any]) -> None`
  > Routes granular scan events to the SegmentedProgressBar and ScanProgressTree.

- `def _on_global_progress(self, library_name: str, completed_count: int, total_count: int) -> None`

- `def _on_library_selected(self, library_name: str) -> None`

- `def _on_log_emitted(self, formatted_message: str, level_name: str) -> None`

- `def _on_log_filter_changed(self, text: str) -> None`

- `def _on_row_library_toggled(self) -> None`

- `def _on_row_property_changed(self) -> None`

- `def _refresh_combined_views_list(self) -> None`

- `def _refresh_directory_list(self) -> None`

- `def _refresh_library_order_list(self) -> None`

- `def _refresh_library_selector(self) -> None`

- `def _refresh_log_display(self) -> None`

- `def _scroll_to_bottom(self) -> None`

- `def _setup_ui(self) -> None`

- `def _show_scan_progress_widgets(self) -> None`

- `def accept(self) -> None`

- `def add_combined_view_row(self) -> None`

- `def add_staged_directory(self) -> None`

- `def add_staged_library(self) -> None`

- `def browse_backup_directory(self) -> None`

- `def browse_database_path(self) -> None`

- `def browse_log_directory(self) -> None`

- `def closeEvent(self, event: QCloseEvent) -> None`

- `def delete_combined_view_row(self) -> None`

- `def move_combined_view_row_down(self) -> None`

- `def move_combined_view_row_up(self) -> None`

- `def move_library_order_down(self) -> None`

- `def move_library_order_up(self) -> None`

- `def reject(self) -> None`

- `def remove_staged_directory(self) -> None`

- `def remove_staged_library(self) -> None`

- `def save_config(self) -> None`

- `def trigger_global_jellyfin_pull(self) -> None`

- `def trigger_global_jellyfin_push(self) -> None`

- `def trigger_global_refresh_metadata(self) -> None`

- `def trigger_global_runtime_extraction(self) -> None`

- `def trigger_global_scan_files(self) -> None`

- `def trigger_restore_config(self) -> None`

- `def trigger_restore_database(self) -> None`

---

### `SubtitleSearchDialog`
- **Defined in**: [subtitle_search.py](../src/lan_streamer/ui_views/dialogs/subtitle_search.py#L24) (line 24)
- **Inherits from**: `QDialog`

> Search and download subtitles from OpenSubtitles.com.

**Methods**:
- `def __init__(self, media_name: str, media_record: Dict[str, Any], controller_instance: 'Controller', is_movie: bool=False, parent: Optional[QWidget]=None) -> None`

- `def _on_download_clicked(self) -> None`

- `def _on_search_clicked(self) -> None`

- `def _setup_ui(self) -> None`

---

### `VideoPlayerWidget`
- **Defined in**: [widget.py](../src/lan_streamer/playback/widget.py#L33) (line 33)
- **Inherits from**: `QWidget`

> Embedded VLC media player widget with caching and advanced controls.

**Methods**:
- `def __init__(self, parent: Any=None) -> None`

- `def _apply_fullscreen_styles(self) -> None`
  > Applies styling to fullscreen overlay based on config.

- `def _apply_pending_resume(self) -> None`

- `def _ask_resume_playback(self, formatted_time: str) -> bool`
  > Prompts the user with custom buttons to resume or restart.

- `def _cleanup_cache(self) -> None`

- `def _format_time(self, seconds: int) -> str`

- `def _handle_mouse_move(self) -> None`

- `def _handle_playback_finished(self) -> None`
  > Handles the end of playback on the UI thread.

- `def _hide_fullscreen_controls(self) -> None`

- `def _load_and_play(self, file_path: str) -> None`

- `def _mark_as_watched(self) -> None`

- `def _on_caching_error(self, error_msg: str) -> None`

- `def _on_caching_finished(self, cached_path: str) -> None`

- `def _on_playback_finished(self, event: Any) -> None`
  > Called by VLC thread when video ends.

- `def _on_popup_countdown_tick(self) -> None`

- `def _on_stop_clicked(self) -> None`
  > Called when user clicks the stop button.

- `def _refresh_tracks(self) -> None`

- `def _reposition_overlays(self) -> None`

- `def _setup_ui(self) -> None`

- `def _show_fullscreen_controls(self) -> None`

- `def _show_osd(self, text: str) -> None`

- `def _show_volume_osd(self, volume: int, muted: bool=False) -> None`

- `def _start_caching(self, file_path: str) -> None`

- `def _update_mute_ui(self) -> None`

- `def _update_stats(self) -> None`

- `def change_audio_track(self, index: int) -> None`

- `def change_subtitle_track(self, index: int) -> None`

- `def closeEvent(self, event: Any) -> None`

- `def decrease_volume(self) -> None`

- `def eventFilter(self, watched: Any, event: Any) -> bool`

- `def ignore_next_episode(self) -> None`
  > Dismisses the next episode popup overlay and continues playing.

- `def increase_volume(self) -> None`

- `def keyPressEvent(self, event: Any) -> None`

- `def on_back_clicked(self) -> None`

- `def play_next_episode(self) -> None`
  > Plays the next episode immediately, preserving fullscreen state.

- `def play_pause(self) -> None`

- `def play_video(self, file_path: str) -> None`
  > Starts the playback process (caching if enabled).

- `def resizeEvent(self, event: Any) -> None`

- `def set_position(self, position: int) -> None`

- `def set_volume(self, volume: int) -> None`

- `def show_next_episode_popup(self) -> None`
  > Shows the next episode popup overlay with next episode details.

- `def skip_backward(self, seconds: int) -> None`

- `def skip_forward(self, seconds: int) -> None`

- `def stop(self) -> None`

- `def toggle_fast_forward(self) -> None`

- `def toggle_fullscreen(self) -> None`

- `def toggle_mute(self) -> None`

- `def toggle_stats(self) -> None`

- `def update_ui(self) -> None`

---

### `VerticalMediaButton`
- **Defined in**: [widget.py](../src/lan_streamer/playback/widget.py#L31) (line 31)
- **Inherits from**: `QWidget`

> Custom widget wrapper containing a QPushButton and QLabel.

**Attributes**:
- `button: QPushButton`
- `label: QLabel`

---

## System Configuration & Logging

### `Config`
- **Defined in**: [config.py](../src/lan_streamer/system/config.py#L10) (line 10)
- **Inherits from**: *None (Base Class)*

> Manages system configurations, loads preferences from, and saves settings to
> the user's config directory JSON file.

**Methods**:
- `def __init__(self) -> None`
  > Initialize the configuration with default values and load from file.

- `def add_library(self, name: str, library_type: str='tv') -> None`

- `def add_root_dir(self, library_name: str, path: str) -> None`

- `def load(self) -> None`

- `def remove_library(self, name: str) -> None`

- `def remove_root_dir(self, library_name: str, path: str) -> None`

- `def save(self) -> None`

---

### `LogSignalEmitter`
- **Defined in**: [logging_handler.py](../src/lan_streamer/system/logging_handler.py#L7) (line 7)
- **Inherits from**: `QObject`

> QObject that emits a signal when a log record is processed.

---

### `QtLogHandler`
- **Defined in**: [logging_handler.py](../src/lan_streamer/system/logging_handler.py#L13) (line 13)
- **Inherits from**: `logging.Handler`

> Custom logging handler that collects log records in a rolling buffer
> and broadcasts them using a thread-safe Qt signal.

**Methods**:
- `def __init__(self, capacity: int=1000) -> None`

- `def emit(self, record: logging.LogRecord) -> None`

---

## Provider Clients

### `JellyfinClient`
- **Defined in**: [jellyfin.py](../src/lan_streamer/providers/jellyfin.py#L18) (line 18)
- **Inherits from**: *None (Base Class)*

> Client for interacting with the Jellyfin server API to sync played/unplayed watched history states.

**Methods**:
- `def __init__(self) -> None`

- `def _get_base_url(self) -> str`

- `def _get_headers(self) -> dict`

- `def fetch_watched_episodes(self) -> tuple`
  > Fetches all watched episodes for the current user.
  > Returns (watched_ids, watched_paths, watched_names).

- `def get_current_user_id(self) -> str | None`

- `def get_jellyfin_correlation_data(self) -> dict`
  > Fetches all episodes, series, and seasons from Jellyfin to build correlation maps.
  > Returns a dict containing:
  >   - path_map: {file_path: {id, series_id, season_id}}
  >   - tmdb_episode_map: {tmdb_episode_identifier: jellyfin_id}
  >   - tmdb_series_map: {tmdb_series_id: jellyfin_id}
  >   - name_map: {(series_name, episode_name): jellyfin_id}

- `def get_series_episodes(self, series_id: str) -> list`
  > Fetches all episodes belonging to a specific Jellyfin series ID.
  > Returns a list of episode items with Path and ProviderIds.

- `def is_configured(self) -> bool`

- `def mark_as_played(self, item_id: str) -> bool`
  > Marks an item as played in Jellyfin.

- `def search_movie(self, name: str) -> list`
  > Searches Jellyfin for movies matching the given name.
  > Returns a list of movie items.

- `def search_series(self, name: str) -> list`
  > Searches Jellyfin for series matching the given name.
  > Returns a list of series items.

- `def set_watched_status(self, item_id: str, watched: bool) -> None`
  > Pushes a played/unplayed status for a single episode to Jellyfin.

- `def unmark_as_played(self, item_id: str) -> bool`
  > Marks an item as unplayed in Jellyfin.

- `def validate_credentials(self, url: str, api_key: str) -> tuple[bool, str]`
  > Tests connection with specific credentials without saving them.

---

### `OpenSubtitlesClient`
- **Defined in**: [opensubtitles.py](../src/lan_streamer/providers/opensubtitles.py#L12) (line 12)
- **Inherits from**: *None (Base Class)*

> Client for interacting with the OpenSubtitles.com REST API.

**Methods**:
- `def __init__(self) -> None`
  > Initialize the OpenSubtitles client with no active token.

- `def _get_headers(self) -> Dict[str, str]`
  > Generate API headers including authentication token and API Key.

- `def download_subtitle(self, download_url: str) -> Optional[bytes]`
  > Download the actual subtitle content.

- `def get_download_link(self, file_id: int) -> Optional[str]`
  > Request a download link for a specific subtitle file.

- `def login(self) -> bool`
  > Log in to OpenSubtitles.com to get an authentication token.

- `def search_subtitles(self, query: Optional[str]=None, tmdb_id: Optional[int]=None, season_number: Optional[int]=None, episode_number: Optional[int]=None, languages: str='en') -> List[Dict[str, Any]]`
  > Search for subtitles on OpenSubtitles.com.

---

### `TMDBClient`
- **Defined in**: [tmdb.py](../src/lan_streamer/providers/tmdb.py#L21) (line 21)
- **Inherits from**: *None (Base Class)*

> Client for interacting with The Movie Database (TMDB) API to fetch movie and TV metadata.

**Methods**:
- `def __init__(self) -> None`

- `def _clean_name(self, name: str) -> str`
  > Strips common release tags from folder names before searching.

- `def _do_movie_search(self, query: str, year: int | None=None) -> list`
  > Raw TMDB movie search. Returns list of result dicts.

- `def _do_search(self, query: str) -> list`
  > Raw TMDB TV search. Returns list of result dicts.

- `def _is_similar(self, original: str, found: str, threshold: float=0.7) -> bool`

- `def _params(self, extra: dict | None=None) -> dict`
  > Returns base query params (api_key) merged with any extras.

- `def _select_best_candidate(self, results_list: list, target_title: str, custom_threshold: float=0.7) -> dict | None`

- `def download_image(self, poster_path: str, cache_key: str) -> str`
  > Downloads a poster image from the TMDB CDN and caches it locally.
  > `poster_path` can be a bare TMDB path (/abc.jpg) or a full URL.
  > Works without an API key (images are unauthenticated).

- `def get_cached_image(self, cache_key: str) -> str`
  > Checks the /cache/images directory first to see if a poster already exists for the given cache_key.

- `def get_episodes(self, tmdb_identifier: str | int, season_num: int) -> list`
  > Returns episodes for a given season number.

- `def get_movie_by_id(self, tmdb_identifier: str | int) -> dict | None`
  > Fetches full movie details from TMDB.

- `def get_seasons(self, tmdb_identifier: str | int) -> list`
  > Returns season list for a series (from the series detail response).

- `def get_series_by_id(self, tmdb_identifier: str | int) -> dict | None`
  > Fetches full series details from TMDB.

- `def is_configured(self) -> bool`

- `def search_movie(self, name: str, year: int | None=None) -> dict | None`
  > Searches TMDB for the best-matching movie.

- `def search_movie_full(self, query: str, limit: int=10) -> list`
  > Returns multiple movie results for the manual-match dialog.

- `def search_series(self, name: str) -> dict | None`
  > Searches TMDB for the best-matching TV series.
  > Works without an API key — returns None gracefully if auth fails.

- `def search_series_full(self, query: str, limit: int=10) -> list`
  > Returns multiple results for the manual-match dialog.

- `def validate_credentials(self, api_key: str) -> tuple[bool, str]`
  > Tests the given API key without persisting it.

---

## Dynamic Proxies & Monkey Patching

### `PatchedAttribute`
- **Defined in**: [proxy.py](../src/lan_streamer/scanner/proxy.py#L5) (line 5)
- **Inherits from**: *None (Base Class)*

> *No class-level docstring provided.*

**Methods**:
- `def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None`

- `def _get_target(self) -> Any`

---

### `PatchedAttribute`
- **Defined in**: [proxy.py](../src/lan_streamer/backend/proxy.py#L5) (line 5)
- **Inherits from**: *None (Base Class)*

> *No class-level docstring provided.*

**Methods**:
- `def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None`

- `def _get_target(self) -> Any`

---

### `PatchedAttribute`
- **Defined in**: [proxy.py](../src/lan_streamer/playback/proxy.py#L5) (line 5)
- **Inherits from**: *None (Base Class)*

> *No class-level docstring provided.*

**Methods**:
- `def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None`

- `def _get_target(self) -> Any`

---

### `PatchedCallable`
- **Defined in**: [proxy.py](../src/lan_streamer/scanner/proxy.py#L20) (line 20)
- **Inherits from**: *None (Base Class)*

> *No class-level docstring provided.*

**Methods**:
- `def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None`

- `def _get_target(self) -> Any`

---

### `PatchedCallable`
- **Defined in**: [proxy.py](../src/lan_streamer/backend/proxy.py#L20) (line 20)
- **Inherits from**: *None (Base Class)*

> *No class-level docstring provided.*

**Methods**:
- `def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None`

- `def _get_target(self) -> Any`

---

### `PatchedCallable`
- **Defined in**: [proxy.py](../src/lan_streamer/playback/proxy.py#L23) (line 23)
- **Inherits from**: *None (Base Class)*

> *No class-level docstring provided.*

**Methods**:
- `def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None`

- `def _get_target(self) -> Any`

---

### `PatchedClass`
- **Defined in**: [proxy.py](../src/lan_streamer/ui_views/proxy.py#L22) (line 22)
- **Inherits from**: *None (Base Class)*

> *No class-level docstring provided.*

**Methods**:
- `def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None`

- `def _get_target(self) -> Any`

---

### `PatchedScannerCallable`
- **Defined in**: [proxy.py](../src/lan_streamer/backend/proxy.py#L74) (line 74)
- **Inherits from**: *None (Base Class)*

> *No class-level docstring provided.*

**Methods**:
- `def __init__(self, attr_name: str, default_factory: Callable[[], Any]) -> None`

- `def _get_target(self) -> Any`

---

### `ScannerProxy`
- **Defined in**: [proxy.py](../src/lan_streamer/scanner/proxy.py#L67) (line 67)
- **Inherits from**: *None (Base Class)*

> *No class-level docstring provided.*

---

## Other Helper Classes

### `Controller`
- **Defined in**: [controller.py](../src/lan_streamer/ui_views/controller.py#L39) (line 39)
- **Inherits from**: `QObject`

> Core Application Logic Controller managing native UI synchronization and persistence layer interactions.
> Enforces strict zero-abbreviation variable naming standard.

**Methods**:
- `def __init__(self, parent: Optional[QObject]=None) -> None`

- `def _cache_series_metrics(self) -> None`

- `def _download_provider_artwork(self, target_dict: Dict[str, Any], match_dictionary: Dict[str, Any], is_movie: bool) -> None`

- `def _on_cleanup_finished(self, statistics: Dict[str, Any]) -> None`

- `def _on_debounce_timeout(self) -> None`

- `def _on_directory_changed(self, path_string: str) -> None`

- `def _on_metadata_embed_finished(self, final_path: str) -> None`

- `def _on_pull_finished(self, updated_count: int) -> None`

- `def _on_push_finished(self, pushed_count: int) -> None`

- `def _on_refresh_finished(self, updated_library: Dict[str, Any]) -> None`

- `def _on_runtime_finished(self, updated_count: int) -> None`

- `def _on_runtime_progress(self, completed_count: int, total_count: int) -> None`

- `def _on_scan_all_detail_progress(self, event: str, payload: Dict[str, Any]) -> None`

- `def _on_scan_all_finished(self) -> None`

- `def _on_scan_finished(self, updated_library: Dict[str, Any]) -> None`

- `def _on_scan_partial(self, partial_library: Dict[str, Any]) -> None`

- `def _on_subtitle_merge_finished(self, final_path: str) -> None`

- `def _on_worker_error(self, error_message: str) -> None`

- `def _sync_tmdb_episodes_for_series(self, series_record: Dict[str, Any], new_tmdb_identifier: str) -> None`

- `def apply_episode_metadata_match(self, series_name: str, episode_path: str, match_dictionary: Dict[str, Any]) -> None`

- `def apply_jellyfin_watch_match(self, series_name: str, match_dictionary: Dict[str, Any]) -> None`

- `def apply_metadata_match(self, series_name: str, match_dictionary: Dict[str, Any]) -> None`

- `def apply_rename_batch(self, preview_results: List[Dict[str, Any]]) -> None`

- `def embed_metadata(self, video_path: str, metadata: Dict[str, str]) -> None`
  > Triggers background ffmpeg worker to embed metadata into video file.

- `def embed_metadata_series(self, series_name: str) -> None`
  > Triggers background worker to embed metadata for all episodes in a series.

- `def mark_episode_watched(self, absolute_path: str, watched: bool) -> None`

- `def mark_season_watched(self, series_name: str, season_name: str) -> None`

- `def mark_series_watched(self, series_name: str) -> None`

- `def merge_subtitles(self, video_path: str, subtitle_paths: List[str]) -> None`
  > Triggers background ffmpeg worker to merge external subtitles into video file.

- `def refresh_episode_metadata(self, series_name: str, episode_path: str) -> None`
  > Queries TMDB directly for the specific episode's metadata and updates it,
  > bypassing lock status (since targeted).

- `def select_library(self, library_name: str, reset_selection: bool=True) -> None`

- `def select_movie(self, movie_name: str) -> None`

- `def select_series(self, series_name: str) -> None`

- `def set_filter_out_watched(self, enabled: bool) -> None`

- `def set_sort_descending(self, descending: bool) -> None`

- `def set_sort_mode(self, mode: str) -> None`

- `def set_video_playing(self, is_playing: bool) -> None`

- `def toggle_series_lock(self, series_name: str, locked: bool) -> None`
  > Updates the locked_metadata flag for a series or movie and persists it to the database.

- `def trigger_cleanup(self) -> None`

- `def trigger_jellyfin_pull(self) -> None`

- `def trigger_jellyfin_push(self) -> None`

- `def trigger_runtime_extraction(self) -> None`

- `def trigger_scan(self, force_refresh: bool=False) -> None`

- `def trigger_scan_all(self, force_refresh: bool=False) -> None`

- `def trigger_series_refresh(self, series_name: str) -> None`
  > Triggers a background RefreshSeriesWorker for the specified series or movie.

- `def update_episode_metadata(self, series_name: str, episode_path: str, metadata_dictionary: Dict[str, Any]) -> None`
  > Persists manual metadata overrides for a specific episode.

- `def update_movie_metadata(self, movie_name: str, movie_path: str, metadata: Dict[str, Any]) -> None`
  > Updates movie metadata in the database and refreshes local cache.
  > Typed with static typing.

- `def update_series_name(self, old_name: str, new_name: str) -> None`
  > Renames a series in the database and updates cache.

---

### `LibraryDict`
- **Defined in**: [core.py](../src/lan_streamer/scanner/core.py#L32) (line 32)
- **Inherits from**: `dict`

> Custom dictionary subclass to hold library contents and track
> any root directories that were unavailable during scanning.

**Methods**:
- `def __init__(self, *args: Any, **kwargs: Any) -> None`

---

### `WakeLock`
- **Defined in**: [wakelock.py](../src/lan_streamer/playback/wakelock.py#L11) (line 11)
- **Inherits from**: *None (Base Class)*

> Prevents the system from sleeping or starting the screensaver.

**Methods**:
- `def __init__(self) -> None`

- `def _inhibit_linux(self, reason: str) -> None`

- `def _inhibit_macos(self, reason: str) -> None`

- `def _inhibit_windows(self) -> None`

- `def _uninhibit_linux(self) -> None`

- `def _uninhibit_macos(self) -> None`

- `def _uninhibit_windows(self) -> None`

- `def inhibit(self, reason: str='Video playback') -> None`

- `def uninhibit(self) -> None`

---
