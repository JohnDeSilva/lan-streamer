# Logic Flows and Codepaths

This document details the main logic flows, execution paths, user choices, and decision gates within the `lan-streamer` codebase. It serves as a developer guide to how the system orchestrates metadata matching, background processing, media playback, and server synchronization.

---

## 1. Library Scanning Flow

The library scanning workflow consists of a decoupled multi-pass pipeline that separates filesystem crawling from metadata matching. This allows the online metadata resolution pass (Pass 2) to execute on the in-memory scanner results, bypassing redundant disk checks and filesystem walks.

### Multi-Pass Pipeline Steps
1. **File Scan (Pass 1)**: Crawls configured directories, discovers new/removed files, and registers them in the local database structure.
2. **Metadata Resolution (Pass 2)**: Resolves series, season, episode, and movie metadata from TMDb. The resolution logic is implemented in the [services/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services) package ([metadata_series.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/metadata_series.py) and [metadata_episode.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/metadata_episode.py) for TV, [metadata_movie.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/metadata_movie.py) for movies) and invoked by the scanner orchestration layer ([scanner/core.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner/core.py)). When executed as part of the pipeline (or individually), it runs with `metadata_only=True` to read files directly from the in-memory output of Pass 1, skipping physical disk checks and asset directory walks.
3. **Runtime Extraction (Pass 3)**: Discovers files with missing or empty metadata runtimes, then invokes `ffprobe` (or falls back to `libvlc`) in the background to extract codecs, dimensions, and streams.
4. **Garbage Cleanup**: Scans the database and purges orphaned media file records that are no longer linked to physical directories. *Note: If any root directory is detected as unavailable or offline during the scan phase, the cleanup pass is skipped to prevent accidental data loss.*

### Workflow Description & User Choices
From the "Library Management" tab in Settings, the user can choose:
* **Scan Files**: Sequentially runs the complete pipeline (Pass 1 -> Pass 2 -> Pass 3 -> Garbage Cleanup) across all libraries.
* **Individual Scan Passes**: Individually triggers **File Scan**, **Metadata Resolution**, **Runtime Extraction**, or **Garbage Cleanup**.
* **Force Refresh**: Ignores cached metadata states and re-queries external APIs for all items (excluding locked items).

### Logical Decision Gates
During execution, the scanner processes each media directory and evaluates the following logic gates:
- **Lock Check**: If a series or movie has its `locked_metadata` flag set to `True` in the database, the scanner skips online queries entirely, preserving all existing metadata.
- **Cache Match**: If incremental scanning is active and a folder's directory structure matches existing database records with valid metadata, online matching is bypassed.
- **TMDB Resolution**: Folder names are cleaned (removing tags like `1080p`, `x264`, `BluRay`) and matched against TMDB search endpoints (`search_series` or `search_movie`). If a match is found (similarity score >= 0.7), its ID is used; otherwise, it falls back to raw folder names.
- **TV vs. Movie Logic**:
  - **Movies**: Scanned directly, extracting runtime, year, and TMDB identifiers.
  - **TV Series**: Scanned recursively for season subdirectories. Video files are parsed via regular expressions (e.g. `S\d+E\d+`, `\d+x\d+`) to extract season and episode numbers, which are then matched to TMDB episode structures.

### Execution Path
1. **Scan Request**: The user triggers the scan (full or pass-specific) from the UI.
2. **Thread Offloading**: The `Controller` instantiates a `ScanAllLibrariesWorker` or `ScanWorker` (`QThread`), keeping the main UI responsive.
3. **Directory Discovery / Memory Loading**: Depending on configuration, the worker pre-walks directories (Pass 1) or accesses cached in-memory structures (Pass 2 under `metadata_only`).
4. **Metadata Loop**: The scanner orchestration layer ([scanner/core.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner/core.py)) walks the directory tree, delegating TMDB lookups and match resolution to the [services/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services) sub-modules. Progress updates are emitted to the UI via the worker's signal mechanism.
5. **Database Transaction**: Scanned results are saved to the database via SQLAlchemy.
6. **UI Refresh**: The worker emits a completion signal, updating the settings progress metrics and reloading posters/stats in the main view.

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
- **Audio Output Device Selection Flow**: During widget initialization and from the player controls context menu, the player widget queries VLC's `mediaplayer.audio_output_device_enum()` linked list to discover system output devices. It constructs a checkable sub-menu (including native PulseAudio support on Linux) for user selection. Selecting a device triggers `audio_output_device_set()`, writes the device identifier to `preferred_audio_device` in the local `config.json`, and updates the On-Screen Display (OSD). Subsequent playbacks read this preference and apply it automatically.
- **Automatic English Track Resolution**: During media loading, the widget queries VLC for the list of available audio tracks and subtitle (SPU) tracks. It evaluates track description strings and automatically calls `audio_set_track()` / `video_set_spu()` for tracks matching `"eng"`, `"english"`, or `"en"`. Subtitle track selection includes filtering logic to prioritize standard dialogue tracks by bypassing tracks containing signs, songs, or metadata tags (e.g. `[Signs]`, `Songs`).
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

## 4. Watch History Sync (Jellyfin & MyAnimeList)

Synchronizes watched history state between the local SQLite database and remote services (Jellyfin and/or MyAnimeList).

### Jellyfin Sync Workflows

#### Pull Synchronization Workflow
The `JellyfinPullWorker` fetches server watched states and applies them locally:
1. **API Fetch**: Queries the Jellyfin server API for the logged-in user's watch history.
2. **Identification Gate**: For each returned item, the pull worker attempts to match it against SQLite:
   - First, checks if the Jellyfin item ID matches a mapped Jellyfin ID in the database.
   - Second, falls back to path or name matching.
3. **Database Update**: If a local match is found, its watched flag is updated to `True` in SQLite. Unmapped items are skipped.

#### Push Synchronization Workflow
The `JellyfinPushWorker` pushes local watch states back to the server:
1. **Database Query**: Queries the SQLite database for episodes or movies marked as watched locally.
2. **Mapping Gate**: Evaluates if the watched item already has an associated Jellyfin ID:
   - *If mapped*: Directly sends a watch update request to the Jellyfin API.
   - *If unmapped*: Performs a search query on the Jellyfin server by name. If an ID is successfully retrieved, the mapping is saved to SQLite, and the watched status is posted. If search fails, the item is skipped.

### MyAnimeList Sync Workflow
Unlike Jellyfin's worker threads which run sync sweeps, watch history is pushed to MyAnimeList asynchronously on demand:
1. **Trigger Gates**: When an episode or movie is marked as watched (manually in the UI or by reaching the playback threshold), the query handler checks:
   - If the item has a mapped `myanimelist_anime_id` and `myanimelist_episode_number` (or is a mapped movie).
   - If the MyAnimeList client ID is configured and the user account is authenticated.
2. **Async Task Dispatch**: An asynchronous background thread is spawned (`_trigger_mal_push_async`) to handle the network request without blocking the UI.
3. **Status Update**: Pushes the progress to the MAL `my_list_status` API endpoint. If all episodes in the MAL entry are completed, the status is marked as `"completed"`; otherwise, it's set to `"watching"`.
4. **Token Refresh Gate**: If the current OAuth access token is expired or close to expiry, the client automatically requests a new access token using the stored refresh token before transmitting the status.

---

## 5. Manual Metadata Matching Workflow (TMDB & MyAnimeList)

Provides a way to override or correct automated TMDB catalog resolution results and map local season episodes to MyAnimeList entries.

### TMDB Catalog Matching
1. **Manual Match Trigger**: The user opens the details dialog and selects the match/search action.
2. **Keyword Input**: The search query is pre-populated with the folder/file name but can be manually modified by the user.
3. **API Query**: Queries TMDB search endpoints (`search_series_full` or `search_movie_full`) to retrieve a collection of matched title details.
4. **Applying the Match**:
   - Saves the new TMDB ID mapping to the database.
   - Triggers download and caching of the updated poster artwork.
   - Triggers background workers to re-scan seasons and episodes matching the new TMDB ID.
   - Refreshes UI grids and panels to show updated metadata and artwork immediately.

### MyAnimeList Mapping (Anime Libraries Only)
For libraries defined as `"anime"`, the **Series Details** dialog displays a dedicated **MyAnimeList Mapper** tab:
1. **Search MyAnimeList**: Users search by keyword, which queries MyAnimeList's `/anime` endpoint.
2. **Episode Alignment**: Selecting a search candidate pulls its detailed metadata and episode list from MAL. The UI matches local episodes to MAL episodes side-by-side.
3. **Commit Mappings**: Clicking "Apply MyAnimeList Mappings" saves the `myanimelist_id` to the local `Season` record, and updates individual `Episode` rows in the SQLite database with their corresponding `myanimelist_anime_id` and `myanimelist_episode_number`.

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

---

## 8. Application Updates Flow

Manages checking for updates on startup or manually, downloading updates in the background, making files executable, detaching the updater process, and terminating the parent process.

### Check Workflow
1. **Startup Check**: If `config.check_for_updates_on_startup` is enabled (and we are not running under Pytest), the application spawns an `UpdateCheckWorker` thread at startup.
2. **Manual Check**: Triggers when the user clicks "Check for Updates Now" in the Advanced settings tab.
3. **API Query**: Queries GitHub's `/repos/JohnDeSilva/lan-streamer/releases/latest` endpoint.
4. **Version Parsing and Selection**:
   - Parses versions into integer tuples to ensure correct semantic comparison.
   - Maps the system platform to expected target release asset names (`lan-streamer-windows.exe`, `lan-streamer-macos.dmg`, `lan-streamer-fedora`, or `lan-streamer-ubuntu`).
5. **Popup Dialog**: If a newer version exists with a valid matching platform asset, the system displays the `UpdateDialog` modal showing release notes and a "Download" button.

### Download & Launch Workflow
1. **Download Trigger**: When the user clicks "Download", the dialog layout transitions to a progress display.
2. **Background Download**: Spawns a `DownloadWorker` thread that fetches the asset from GitHub's CDN in 8KB chunks, updating the `QProgressBar` and labels.
3. **Execution**:
   - Once completed, the file is saved to the local updates folder.
   - On Unix/Linux platforms, it runs `os.chmod(path, 0o755)` to set the executable permission bit.
   - On macOS, it mounts the DMG via `QProcess.startDetached("open", [path])`.
   - On Linux/Windows, it spawns the binary directly using `QProcess.startDetached(path)`.
4. **Termination**: The current host application is immediately closed using `QApplication.quit()` and `sys.exit(0)`, allowing the new version to take over.
