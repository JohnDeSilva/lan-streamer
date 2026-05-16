# LAN Streamer

**LAN Streamer** is a lightweight media library manager designed for local media playback with a metadata-rich browsing interface.

It manages local media libraries (e.g., NAS, External Drives) and provides optional **Jellyfin** and **OpenSubtitles** integration for watch history synchronization and subtitle management without server-side transcoding.

---

## 🚀 Key Features

*   **📺 Embedded Playback**: Uses **VLC** for playback directly within the application. Supports audio and subtitle track selection, seeking, and volume control.
*   **🎭 Theatre Mode**: Hides UI elements during fullscreen playback for an unobstructed view. A minimal control bar provides essential playback actions.
*   **💾 Local Caching**: Optional background caching of media files to local storage to reduce network latency during playback.
*   **🧠 Progress Tracking**: Automatically marks media as watched after reaching a **90% completion** threshold.
*   **⚡ Library Scanning**: Uses SQLite `UPSERT` logic for incremental scanning, preserving manual metadata corrections.
*   **🔍 Metadata Matching**: Multi-stage search strategy to link local media to TMDB and Jellyfin entries.
*   **📛 Naming Support**: Uses official Jellyfin episode names where available, with filename fallbacks.
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
Logs are rotated daily and stored in the configured log directory:
- `db.log`: Database operations.
- `ui.log`: Interface events.
- `scanner.log`: Library scanning.
- `jellyfin.log`: Jellyfin API interactions.
- `tmdb.log`: TMDB metadata fetching.
- `player.log`: Video playback and VLC details.
- `lan-streamer.log`: Global application log.

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

