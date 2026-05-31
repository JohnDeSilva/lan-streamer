# Logic Flows and Codepaths

This document details the main logic flows and execution paths within the `lan-streamer` codebase, using Mermaid.js diagrams to visualize the control flow.

---

## 1. Library Scanning Flow

The library scanning flow updates the local SQLite database with information about files in the configured media directories, linking them to TMDB metadata.

### Mermaid Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant GridView as LibraryGridView
    participant Control as Controller
    participant Worker as ScanWorker
    participant Core as scan_directories (core.py)
    participant TMDB as TMDBClient
    participant DB as db (models/SQLAlchemy)

    User->>GridView: Clicks Scan / Force Refresh
    GridView->>Control: trigger_scan(force_refresh)
    Control->>Worker: Instantiate ScanWorker
    Control->>Worker: start()
    Note over Worker: Runs run() in QThread
    Worker->>Control: Emit init_library_scan (pre-walk directory tree)
    Worker->>Core: scan_directories()

    loop For each Series/Movie Directory
        Core->>DB: Check for existing metadata & lock status
        alt Locked Metadata or Local Cache Valid
            Note over Core: Reuse cached data
        else Not Locked & (Force Refresh or Missing Metadata)
            Core->>TMDB: search_series() or search_movie()
            TMDB-->>Core: Return Metadata (ID, poster_path, overview)
        end

        loop For each Season & Episode (TV library only)
            Core->>TMDB: get_episodes() for Season
            Core->>Core: Parse episode numbers from filename
            Core->>Core: Match with TMDB episode record
        end

        Core->>Control: Emit partial_result (for real-time UI updates)
    end

    Core-->>Worker: Returns scanned LibraryDict
    Worker->>DB: save_library() / save_movie_library()
    Worker->>Control: Emit finished(updated_library)
    Control->>GridView: Emit library_loaded() signal
    GridView->>User: Re-render UI with new posters and info
```

### Steps in the Flow

1. **Triggering the Scan**: The user requests a scan from the UI (e.g. `LibraryGridView` or `SettingsDialog`).
2. **Worker Instantiation**: The `Controller` instantiates a `ScanWorker` (which inherits from `QThread`) to run the scanning loop in the background and prevent UI lockups.
3. **Directory Pre-Walk**: The worker calls `discover_single_library_tree` to pre-walk folders. It emits `init_library_scan` to initialize the `LibraryScanProgressBar` and `ScanProgressTree`.
4. **Metadata Resolution & Matching**:
   - `scan_directories` walks each subdirectory.
   - If a series has `locked_metadata=True`, scanning is skipped, and the existing entry is preserved.
   - Otherwise, `TMDBClient` is queried to match the folder name with online records.
   - In TV libraries, season folders are scanned for video files, matched with TMDB episode numbers via regex (`_parse_episode_number`), and metadata (name, air date, runtime) is gathered.
5. **Database Updates**: Scanned records are written to the database using SQLAlchemy sessions in `db.save_library()` or `db.save_movie_library()`.
6. **UI Refresh**: Once finished, the worker emits the `finished` signal, and the `Controller` triggers `library_loaded` to update view templates.

---

## 2. Technical Metadata Extraction and Subtitle Merging

When files are scanned, they may have missing runtimes, resolutions, or subtitles. Background processes extract technical info and run `ffmpeg` to embed assets.

### Mermaid Diagram

```mermaid
flowchart TD
    A[Start Runtime Extraction] --> B[Retrieve item paths missing runtime from DB]
    B --> C{For each item}
    C -->|Has items| D[Call get_detailed_file_info]
    C -->|Finished| I[Emit finished & refresh UI]

    D --> E[Resolve ffprobe location via _get_ffprobe_command]
    E --> F[Run ffprobe subprocess with JSON format parameters]
    F --> G{ffprobe success?}
    G -->|Yes| H[Parse runtime, resolution, codec, audio/subtitle tracks]
    G -->|No| J[Fall back to libvlc media parser]
    H --> K[Update episode/movie record in SQLite]
    J --> K
    K --> C
```

### Subtitle and Metadata Embedding Sequence

```mermaid
sequenceDiagram
    autonumber
    participant UI as EpisodeDetailsDialog
    participant Control as Controller
    participant Worker as SubtitleMergeWorker / MetadataEmbedWorker
    participant Shell as ffmpeg / Subprocess
    participant Disk as File System

    UI->>Control: Request Subtitle Merge / Metadata Embed
    Control->>Worker: Instantiate QThread worker
    Control->>Worker: start()
    Note over Worker: Runs run() in background thread
    Worker->>Shell: Run ffmpeg command copy pipeline
    Note over Shell: e.g., ffmpeg -i video.mp4 -i sub.srt -c copy -map 0 -map 1 temp.merged.mkv
    Shell-->>Worker: Success (exit code 0)
    Worker->>Disk: Atomically replace original video with merged container (os.replace)
    Worker->>Disk: Delete external subtitle file (if merging subtitles)
    Worker->>Control: Emit finished() signal
    Control->>UI: Refresh episode detail panel
```

### Technical Details

- **`ffprobe` Resolution**: The `_get_ffprobe_command` helper in `src/lan_streamer/scanner/runtime.py` checks the system path and falls back to macOS homebrew paths (`/opt/homebrew/bin/ffprobe`) or Unix standard bin paths.
- **FFmpeg copy pipelines**: To avoid re-encoding, technical workers always invoke ffmpeg using the `-c copy` flag. This allows swift embedding of tracks and metadata tags without consuming high CPU cycles or degrading video quality.

---

## 3. Media Playback & Wakelocks

This flow manages the lifecycle of video playback, ensuring files are cached locally if needed, system sleep is inhibited, and playback positions are tracked.

### Mermaid Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Library View / Details View
    participant Control as Controller
    participant Player as VideoPlayerWidget
    participant WL as WakeLock
    participant Cache as CacheWorker
    participant VLC as libvlc instance

    User->>UI: Clicks Play Video
    UI->>Control: Emit playback_requested(file_path)

    alt Embedded Player enabled
        Control->>Player: play_video(file_path)
        Player->>WL: inhibit() (Disable screensaver / system sleep)
        Note over WL: Platform-specific calls (dbus on Linux, caffeinate on macOS, etc.)

        alt Cache Enabled & File is Network Share
            Player->>Cache: Start CacheWorker
            Cache->>Cache: Copy media file chunk to local directory
            Cache-->>Player: Emit finished / chunk ready
        end

        Player->>VLC: Load file path
        Player->>VLC: Set position / Resume playback if requested

        loop During Playback
            VLC->>Player: Emit position change events
            Player->>Player: Update stats overlay and save position
        end

        User->>Player: Closes Player or Video Reaches End
        Player->>Control: mark_episode_watched(file_path, watched=True)
        Player->>WL: uninhibit() (Re-enable system sleep)
        Player->>Player: _cleanup_cache()
        Player->>UI: Return to details screen
    else External Player enabled
        Control->>Control: Spawn external VLC or MPV process
    end
```

### Steps in the Flow

1. **Playback Request**: The `Controller` listens to view clicks and routes the selected video path.
2. **Wakelock Activation**: To prevent screensavers or system sleep from interrupting movies, `WakeLock.inhibit()` is called. It supports Linux (`org.freedesktop.ScreenSaver` dbus), Windows (`SetThreadExecutionState`), and macOS (`caffeinate` sub-processes).
3. **Local Caching**: The `CacheWorker` runs in a separate thread to copy media files locally to speed up seek times when playing files over high-latency networks (e.g. SMB/NFS mounts).
4. **VLC Playback Control**: Playback state, track selection, volume, and playback speed are controlled via libvlc.
5. **Watched State Sync**: When a threshold is met or the video ends, the local DB updates `watched=True` and resets the saved resume position.

---

## 4. Jellyfin Watch History Sync (Push/Pull)

Syncs local watch status with a central Jellyfin server.

### Mermaid Diagram

```mermaid
flowchart LR
    subgraph Pull Sync
        A[Pull worker starts] --> B[Fetch watched items list from Jellyfin]
        B --> C[Match TMDB/Jellyfin IDs in SQLite]
        C --> D[Update local watched state flags]
        D --> E[Sync Complete]
    end

    subgraph Push Sync
        F[Push worker starts] --> G[Query local SQLite for watched episodes]
        G --> H[Check mapped Jellyfin IDs]
        H --> I[Post status changes to Jellyfin server]
        I --> J[Sync Complete]
    end
```

### Synchronizing Rules

- **Pull Process**: `JellyfinPullWorker` calls `fetch_watched_episodes` which queries the Jellyfin user library database, resolves the items using local DB models, and marks matches as watched.
- **Push Process**: `JellyfinPushWorker` identifies which items were watched locally but remain unwatched on Jellyfin, sending watch/unwatch requests through Jellyfin HTTP APIs.
