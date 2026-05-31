# Logic Flows and Codepaths

This document details the main logic flows, execution paths, user choices, and decision gates within the `lan-streamer` codebase. It serves as a developer guide to how the system orchestrates metadata matching, background processing, media playback, and server synchronization.

---

## 1. Library Scanning Flow

The library scanning workflow reads files in configured media directories, resolves metadata from online services, and populates the SQLite database.

### Workflow Description & User Choices
When initiating a scan, the user can choose to trigger a standard scan or a **Force Refresh**:
1. **Standard (Incremental) Scan**: The scanner only queries external APIs for directories or files that do not currently exist in the database, preserving existing metadata and manual corrections.
2. **Force Refresh**: The scanner ignores cached states and re-queries external APIs for all items, overwriting existing records unless metadata is explicitly locked.

### Logical Decision Gates
During execution, the scanner processes each media directory and evaluates the following logic gates:
- **Lock Check**: If a series or movie has its `locked_metadata` flag set to `True` in the database, the scanner skips online queries entirely, preserving all existing metadata.
- **Cache Match**: If incremental scanning is active and a folder's directory structure matches existing database records with valid metadata, online matching is bypassed.
- **TMDB Resolution**: Folder names are cleaned (removing tags like `1080p`, `x264`, `BluRay`) and matched against TMDB search endpoints (`search_series` or `search_movie`). If a match is found (similarity score >= 0.7), its ID is used; otherwise, it falls back to raw folder names.
- **TV vs. Movie Logic**:
  - **Movies**: Scanned directly, extracting runtime, year, and TMDB identifiers.
  - **TV Series**: Scanned recursively for season subdirectories. Video files are parsed via regular expressions (e.g. `S\d+E\d+`, `\d+x\d+`) to extract season and episode numbers, which are then matched to TMDB episode structures.

### Execution Path
1. **Scan Request**: The user triggers the scan from the UI.
2. **Thread Offloading**: The `Controller` instantiates a `ScanWorker` (`QThread`), keeping the main UI responsive.
3. **Directory Discovery**: The worker pre-walks directories to establish file counts, emitting `init_library_scan` to initialize progress bars.
4. **Metadata Loop**: The core scanner walks the tree, calling the TMDB API, resolving matches, and emitting partial progress updates to the UI.
5. **Database Transaction**: Scanned results are structured into model dictionaries and saved to the SQLite database via SQLAlchemy (`db.save_library`).
6. **UI Refresh**: The worker emits `finished`, triggering the main view to reload posters, titles, and stats.

---

## 2. Technical Metadata Extraction and Subtitle Merging

After library scanning, files are analyzed in the background to extract technical characteristics (codecs, runtimes, audio/subtitle tracks) and optionally embed metadata or merge external subtitles.

### Technical Metadata Extraction Flow
The extraction process operates automatically in the background via the `RuntimeExtractionWorker`:
1. **Database Query**: Queries the SQLite database for movies or episodes where the runtime is set to `0` or is missing.
2. **Target Evaluation**: For each missing item, the extractor attempts to retrieve file information:
   - **Path Resolution**: The worker uses `_get_ffprobe_command` to check for local system `ffprobe` binaries.
   - **Subprocess Execution**: It spawns an asynchronous `ffprobe` process requesting JSON-formatted details.
   - **Success Gate**:
     - *If ffprobe succeeds*: The system parses the output for exact runtime, resolution width/height, video codec, audio track languages, and subtitle tracks.
     - *If ffprobe fails*: The system falls back to a lightweight libvlc media parser instance to retrieve basic runtime duration.
   - **Database Update**: The extracted characteristics are updated in the SQLite table.

### Subtitle and Metadata Embedding Workflow
Users can choose to embed metadata or merge downloaded subtitle files directly into the video container from the details dialog:
1. **User Choice**: The user selects "Embed Metadata" or "Merge Subtitles" for an episode or movie.
2. **Offloading Worker**: The `Controller` launches a `MetadataEmbedWorker` or `SubtitleMergeWorker` thread.
3. **FFmpeg copy pipelines**: To avoid time-consuming and quality-degrading re-encoding, the worker invokes an `ffmpeg` command with the `-c copy` pipeline flag:
   - Example: `ffmpeg -i video.mp4 -i sub.srt -c copy -map 0 -map 1 temp.merged.mkv`
4. **Atomic File Replacement**: If the ffmpeg subprocess exits successfully (exit code `0`), the worker uses `os.replace` to atomically replace the original video file with the new container. If subtitle merging was requested, the external `.srt` file is cleaned up.
5. **UI Update**: Emits a `finished` signal, and the UI re-reads the file details to show embedded tracks.

---

## 3. Media Playback & Wakelocks

Manages the lifecycle of media playing in either embedded or external players, ensuring system power states are maintained and progress is tracked.

### Playback Decision Gates & User Choices
When a playback request is initiated, the system evaluates several logical decision gates and user choices:
- **Player Selection**: Evaluates the `enable_embedded_player` setting.
  - *External Player*: Spawns a separate process (e.g. VLC or MPV) and monitors its lifecycle.
  - *Embedded Player*: Instantiates PySide6 `VideoPlayerWidget` using `libvlc`.
- **Wakelock Inhibition**: Once playback starts, the system inhibits screen savers and power sleep modes. It uses D-Bus messages on Linux, `SetThreadExecutionState` on Windows, and `caffeinate` sub-processes on macOS.
- **Local Caching Check**: If caching is enabled and the media is stored on a high-latency network share, `CacheWorker` copies the file to the local directory, displaying a progress bar. Embedded playback then points to this cached path.
- **Resume Prompt**:
  - If the database has a saved playback position greater than 60 seconds, the user is prompted: *Resume playback or Start from Beginning?*
  - The player seeks to the selected position or starts playing from `0`.
- **UI & Autoplay Loop**: During playback, a QTimer triggers every second to update the seek bar slider and elapsed/remaining time labels.
  - **Autoplay decision**: If progress reaches 98% and a next episode is available, an overlay popup card appears with a 20-second countdown.
  - **Autoplay user choices**: The user can click **Play Next** (switches to the next file immediately), click **Ignore** (dismisses the card), or let the countdown expire (dismisses card).
- **Watched Threshold Check**: When the user exits playback or the video ends, the system checks:
  - If progress is >= `watched_threshold` (default 95%), it marks the file as `watched=True` in SQLite and resets the resume position.
  - Otherwise, if duration played is > 60 seconds, it saves the current position; if < 60 seconds, it clears any saved position.

---

## 4. Jellyfin Watch History Sync (Push/Pull)

Synchronizes watched history state between the local SQLite database and a remote Jellyfin server.

### Pull Synchronization Workflow
The `JellyfinPullWorker` fetches server watched states and applies them locally:
1. **API Fetch**: Queries the Jellyfin server API for the logged-in user's watch history.
2. **Identification Gate**: For each returned item, the pull worker attempts to match it against SQLite:
   - First, checks if the Jellyfin item ID matches a mapped Jellyfin ID in the database.
   - Second, falls back to path or name matching.
3. **Database Update**: If a local match is found, its watched flag is updated to `True` in SQLite. Unmapped items are skipped.

### Push Synchronization Workflow
The `JellyfinPushWorker` pushes local watch states back to the server:
1. **Database Query**: Queries the SQLite database for episodes or movies marked as watched locally.
2. **Mapping Gate**: Evaluates if the watched item already has an associated Jellyfin ID:
   - *If mapped*: Directly sends a watch update request to the Jellyfin API.
   - *If unmapped*: Performs a search query on the Jellyfin server by name. If an ID is successfully retrieved, the mapping is saved to SQLite, and the watched status is posted. If search fails, the item is skipped.

---

## 5. Manual Metadata Matching Workflow

Provides a way to override or correct automated TMDB catalog resolution results.

### User Choice & Search Execution
1. **Manual Match Trigger**: The user opens the details dialog and selects the match/search action.
2. **Keyword Input**: The search query is pre-populated with the folder/file name but can be manually modified by the user.
3. **API Query**: Queries TMDB search endpoints (`search_series_full` or `search_movie_full`) to retrieve a collection of matched title details (e.g. titles, release years, overviews, posters).

### Applying the Match
1. **Selection**: The user selects a specific TMDB item from the search result list.
2. **Controller updates**:
   - Saves the new TMDB ID mapping to the database.
   - Triggers download and caching of the updated poster artwork.
   - Triggers background workers to re-scan seasons and episodes matching the new TMDB ID.
   - Refreshes UI grids and panels to show updated metadata and artwork immediately.

---

## 6. File Renaming and Hygiene Workflow

Ensures files follow a clean, consistent naming structure for media players and scrapers.

### Preview and Safety Checks
1. **Hygiene Action**: User requests file renaming from the series details dialog.
2. **Template Evaluation**: The system generates proposed names using a token template (e.g. `{SeriesTitle} - S{SeasonNumber:02}E{EpisodeNumber:02} - {EpisodeTitle}`).
3. **Sanitization rules**:
   - Removes characters illegal across operating systems (`\ / : * ? " < > |`).
   - Ensures no reserved system namespaces (e.g. `CON`, `PRN`, `NUL`) are used.
   - Restricts total file name length to standard filesystem limits (max 255 bytes).
4. **Subtitle tracking**: Automatically finds separate subtitle files sharing the same file stem (e.g. `.srt`, `.en.srt`), and adds renaming previews for them to match the new video filename.
5. **Preview Panel**: Displays target filenames color-coded by safety status to the user.

### Execution
1. **Atomic Rename**: When the user approves, files are moved on the filesystem. Parent folders are created automatically if missing.
2. **Database Update**: SQLite is updated to point to the new absolute paths.
3. **UI Refresh**: Emits updates to redraw media cards and lists.

---

## 7. Subtitle Searching & Downloading Workflow

Retrieves and stores subtitle files for media playbacks automatically or interactively.

### Search Trigger
1. **Dialog Input**: The user opens the subtitle search interface from the media details panel.
2. **Automatic Query Formulator**:
   - For movies, sets defaults to `<Movie Title> <Year>`.
   - For TV episodes, sets defaults to `<Series Title> S<SeasonNumber>E<EpisodeNumber>`.
3. **OpenSubtitles Query**: Connects to OpenSubtitles.com REST API. Uses the associated TMDB ID if available to ensure exact catalog alignment, falling back to text queries.
4. **List Display**: Displays matched subtitle candidates alongside metadata (e.g. language, release name, rating, download counts).

### Download and Write
1. **Link Request**: Upon clicking "Download", requests a single-use download URL from OpenSubtitles.
2. **Payload Fetch**: Downloads raw subtitle data bytes.
3. **Adjacent File Write**: Saves the file in the exact media directory matching the video file's parent folder, appending language codes (e.g., `video_file.en.srt`).
4. **UI Update**: Signals details panel components to re-run ffprobe or refresh, showing the newly downloaded track option.
