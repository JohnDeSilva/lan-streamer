# LAN Streamer

**LAN Streamer** is a lightweight media library manager designed for local media playback with a metadata-rich browsing interface.

It manages local media libraries (e.g., NAS, External Drives) and provides optional **Jellyfin** and **OpenSubtitles** integration for watch history synchronization and subtitle management without server-side transcoding.

---

## 🚀 Key Features

*   **📺 Embedded Playback**: Uses **VLC** for playback directly within the application. Supports audio and subtitle track selection, seeking, and volume control.
*   **🎭 Theatre Mode**: Hides UI elements during fullscreen playback for an unobstructed view. A minimal control bar provides essential playback actions.
*   **💾 Local Caching**: Optional pre-playback caching of media files to local storage to eliminate network-related buffering.
*   **🧠 Progress Tracking**: Automatically marks media as watched based on a configurable threshold and supports resuming playback from saved positions.
*   **⚡ Library Scanning**: Uses SQLite `UPSERT` logic for incremental scanning, preserving manual metadata corrections.
*   **🔍 Metadata Matching**: Multi-stage search strategy to link local media to TMDB and Jellyfin entries.
*   **📛 Naming Support**: Uses official **TMDB** episode and series names, with filename fallbacks for unmatched items.
*   **🔄 Bidirectional Sync**: 
    *   Downloads posters and overviews from TMDB.
    *   Syncs "Watched" status with Jellyfin servers in real-time.
*   **🗨️ Subtitle Integration**: Integrated **OpenSubtitles.com** support for searching and downloading subtitles directly within the app.
*   **📁 Multi-Library Support**: Organize content into multiple libraries with support for multiple root directories per library.
*   **📅 Air Date Sorting**: Uses TMDB air dates for "Recently Aired" library sorting.
*   **🏷️ Media Renamer**: Utility to rename local files to match official metadata standards.
*   **🧹 Library Cleanup**: Tool to remove missing files and stale database entries while maintaining metadata integrity.
*   **🎨 Responsive UI**: Native dark mode interface built with PySide6 (QtWidgets).

---

## 🏛️ Architecture & Stability

*   **Database Migrations**: Managed via **Alembic** to ensure schema consistency across updates.
*   **Asynchronous Operations**: Library scanning, cleanup, and synchronization run in background threads to maintain UI responsiveness.
*   **🛡️ Code Quality**: Enforces **90% minimum code coverage** and **100% strict static type checking** (`mypy`). All warnings are treated as errors in the test suite.

---

## 🛠️ Requirements

*   **Python**: 3.14+
*   **VLC**: System-wide VLC installation required.
*   **TMDB API Key**: Required for metadata (free from [The Movie Database](https://www.themoviedb.org/)).
*   **Jellyfin**: (Optional) For watch history synchronization.
*   **OpenSubtitles**: (Optional) For subtitle downloads (requires API key and credentials).

---

## 📦 Installation

This project uses `uv` for package management.

```bash
# Clone the repository
git clone https://github.com/JohnDeSilva/lan-streamer.git
cd lan-streamer

# Install dependencies
uv sync
```

---

## 🖥️ Usage

### Running the App
```bash
make run
```

> [!NOTE]
> **Linux / Wayland**: On Wayland sessions, the application uses `QT_QPA_PLATFORM=xcb` for stable VLC window embedding.

> [!IMPORTANT]
> **MacOS (Apple Silicon)**: Ensure the **Apple Silicon** version of VLC is installed. The Intel version cannot be loaded by a native ARM64 Python process.

### Setup Guide
1.  **Configure TMDB**: Go to **Metadata > TMDB Settings...** and enter your API Key.
2.  **Configure Jellyfin (Optional)**: In **Watch History > Jellyfin Settings**, enter your Server URL and API Key.
3.  **Configure OpenSubtitles (Optional)**: In the **Remote APIs** settings tab, enter your OpenSubtitles credentials and API Key.
4.  **Add Libraries**: Define media roots in **Settings > Manage Libraries...**.
5.  **Scan Library**: Trigger initial scanning in **Metadata > Check for New Files and Fetch Metadata**.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| **`Space`** | Toggle Play/Pause |
| **`F`** | Toggle Fullscreen |
| **`Esc`** | Exit Fullscreen |
| **`Double-Click`** | Toggle Fullscreen (Video area) |
| **`Up`** | Increase volume |
| **`Down`** | Decrease volume |
| **`M`** | Toggle Mute |
| **`←` (Back)** | Stop playback and return to details view |

---

## ⚙️ Configuration

Configuration is managed via **Settings > General Settings** and stored in `~/.config/lan-streamer/config.json`.

### Logging System
Logs are stored in the configured `log_directory` (default: `~/.config/lan-streamer/logs`).

#### Configuration Keys
- `log_level`: Sets the verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Default: `INFO`.
- `divide_logs_by_service`: Boolean to toggle between unified and granular logging.
- `max_log_retention_days`: Number of days to keep log files before auto-deletion. Default: `7`.

#### Logging Modes
1.  **Unified Mode** (`divide_logs_by_service: false`):
    - All application events are logged to a single `lan-streamer.log` file.
2.  **Divided Mode** (`divide_logs_by_service: true`):
    - Logs are split into service-specific files for easier debugging:
        - `db.log`: Database operations.
        - `backend.log`: Background task management.
        - `scanner.log`: Library scanning and file discovery.
        - `jellyfin.log`: Jellyfin API synchronization.
        - `tmdb.log`: TMDB metadata fetching.
        - `player.log`: Video playback and VLC engine details.
        - `backup.log`: Database and configuration backups.
        - `opensubtitles.log`: Subtitle search and downloads.
        - `wakelock.log`: System sleep prevention events.
        - `ui.log`: User interface events and view state transitions.
        - `renamer.log`: Batch file renaming operations.

All logs are rotated daily at midnight. On application startup, the system automatically purges log files older than the retention threshold.

### Local Caching
To minimize network latency and buffering when streaming from remote sources (e.g., NAS over Wi-Fi), LAN Streamer can cache media files to local storage before playback.

#### Configuration Keys
- `enable_caching`: Toggles background caching. Default: `false`.
- `cache_directory`: Path where cached files are stored (default: `~/.config/lan-streamer/cache`).
- `max_cache_size_gb`: Maximum disk space allocated for the cache. Default: `15.0` GB.

#### Behavior
- **Pre-playback Copy**: When enabled, the application copies the entire media file to the local cache before the player starts. A progress bar is displayed during this process.
- **Auto-Reuse**: If a file is already in the cache and its size matches the source, playback starts immediately.
- **LRU Cleanup**: The system automatically removes the oldest cached files when the `max_cache_size_gb` limit is reached or when files are older than 24 hours.

### Progress Tracking
The application automatically tracks your playback progress and maintains a "watched" state across your library.

#### Configuration Keys
- `watched_threshold`: The completion percentage required to mark an item as watched. Default: `0.95` (95%).
- `sync_history_on_start`: Automatically pulls watch history from Jellyfin on application startup (if configured).

#### Features
- **Resume Playback**: If you stop a video after at least 60 seconds of playback, your position is saved. The next time you play the same file, you will be prompted to resume from where you left off.
- **Automatic "Watched" Status**: Once playback exceeds the `watched_threshold`, the item is marked as watched in the local database. If Jellyfin integration is enabled, this status is immediately synchronized to your Jellyfin server.
- **Threshold Logic**: If a video is marked as watched (either manually or by reaching the threshold), any saved playback position is cleared.

---

## 🧪 Development

### Technical Stack
*   **UI**: PySide6 (Qt 6)
*   **Database**: SQLite with SQLAlchemy ORM
*   **Migrations**: Alembic
*   **Testing**: pytest, pytest-cov, pytest-qt
*   **Linting**: Ruff
*   **Type Checking**: mypy

### Testing
```bash
make test
```

### Releases
Uses [Conventional Commits](https://www.conventionalcommits.org/) for versioning.
```bash
make release
```

---

## 📜 License
MIT License. See [LICENSE](LICENSE) for details.

