# LAN  Streamer

**LAN Streamer** is a premium, lightweight media library manager built for users who demand the best local playback experience while maintaining a modern, metadata-rich browsing interface.

It bridges the gap between local file storage (e.g., NAS, External Drives) and optional **Jellyfin** integration, ensuring your library stays beautiful and synchronized without the overhead or quality loss of server-side transcoding.

---

## 🚀 Key Features

*   **📺 Embedded Playback**: Integrated **VLC** player for a seamless bit-perfect streaming experience directly within the app. Includes full support for **audio and subtitle track selection**, seeking, and volume control.
*   **🎭 Theatre Mode (Fullscreen)**: Immersive, distraction-free viewing. Going fullscreen automatically hides the library, filters, status bars, and menus. A minimal, floating control bar provides essential playback actions without cluttering the screen.
*   **💾 Local Caching**: Optional background caching of media files to local storage to eliminate network stutters on high-bitrate content.
*   **🧠 Intelligent Progress Tracking**: Automatically marks episodes as watched only after reaching a **90% completion** threshold.
*   **⚡ High-Performance Scanning**: Engineered with an incremental scanning engine using SQLite `UPSERT` logic. Minimize disk I/O while preserving manual corrections and user metadata.
*   **🔍 Advanced Metadata Matching**: Implements a robust, multi-stage search strategy (Exact, Colon-aware, Fuzzy, and Word-based fallbacks) to reliably link local folders to Jellyfin entries.
*   **📛 Official Naming**: Prioritizes official Jellyfin episode names (e.g., *"01 - Pilot"*) for a clean, professional library look, with filename fallbacks for unmatched content.
*   **🔄 Bidirectional Sync**: 
    *   Automatically downloads high-quality posters and overviews.
    *   Syncs "Watched" status back to your Jellyfin server in real-time.
*   **📁 Multi-Library Organization**: Group your content into logical libraries (e.g., "Main", "Archive", "Anime") with support for multiple root directories per library.
*   **📅 Air Date Awareness**: Leverages TMDB episode and series air dates to enable accurate "Recently Aired" library sorting.
*   **🏷️ Media Renamer**: Built-in utility to safely and consistently rename local files to match official metadata (e.g., standardizing S01E01 naming).
*   **🧹 Library Cleanup**: Deep cleanup tool that removes missing files, seasons, and series from the database while maintaining metadata integrity.
*   **🛠️ Manual Corrections**: Effortlessly fix incorrect matches via the "Match Series..." context menu, or bulk-mark seasons as watched.
*   **🎨 Premium Dark UI**: A sleek, high-contrast hybrid interface built with PySide6 (QWidget) and QML for a smooth, fluid, and responsive desktop experience.

---

## 🏛️ Architecture & Stability

*   **Versioned Schema**: Managed via **Alembic** migrations. Database schema updates are handled automatically through the `make migrate` target, ensuring metadata consistency across all releases.
*   **Background Workers**: Library scanning, cleanup, and synchronization occur in dedicated background threads, keeping the UI fluid even during massive updates.
*   **🛡️ Quality Enforcement**: Maintains a strict **90% minimum code coverage** threshold and enforces a **zero-warning** policy. The local test suite treats all warnings as errors to ensure maximum reliability.

---

## 🛠️ Requirements

*   **Python**: 3.14+
*   **VLC**: A VLC installation is required on the system.
*   **python-vlc**: Python bindings for libvlc (included in project dependencies).
*   **TMDB**: A free API key from [The Movie Database](https://www.themoviedb.org/) (Required for metadata).
*   **Jellyfin**: (Optional) A running Jellyfin server and an API key for watch history synchronization.

---

## 📦 Installation

This project uses `uv` for ultra-fast, reliable package management.

```bash
# Clone the repository
git clone https://github.com/JohnDeSilva/lan-streamer.git
cd lan-streamer

# Install dependencies and create virtual environment
uv sync
```

---

## 🖥️ Usage

### Running the App
```bash
make run
```

> [!NOTE]
> **Linux / Wayland Support**: On Wayland-based desktops (Fedora, Ubuntu, etc.), the application automatically detects the session and uses XWayland (`QT_QPA_PLATFORM=xcb`) to ensure stable VLC window embedding and prevent playback issues.

> [!IMPORTANT]
> **MacOS Compatibility (Apple Silicon)**: If you are on an M1/M2/M3 Mac, you **must** ensure you have the **Apple Silicon** version of VLC installed. 
> 
> If you see an `OSError` or "VLC library could not be loaded" message, it is likely because you have the Intel (x86_64) version of VLC, which cannot be loaded by a native ARM64 Python process. Download the correct version from [VideoLAN.org](https://www.videolan.org/vlc/download-macosx.html).

### Setup Guide
1.  **Configure Connectivity**: Navigate to **Watch History > Jellyfin Settings** to enter your Server URL and API Key. Use "Test Connection" to verify.
2.  **Configure Metadata**: Navigate to **Metadata > TMDB Settings...** to enter your TMDB API Key.
3.  **Add Libraries**: Go to **Settings > Manage Libraries...** to define your media roots and library names.
4.  **Fetch Metadata**: Go to **Metadata > Check for New Files and Fetch Metadata** to trigger the initial scanning and poster downloads.
5.  **Cleanup Library**: If you move or delete files on your drive, use **Metadata > Cleanup Library (Remove Missing Files)** to prune stale entries.
6.  **Sync Watch History**: Use the **Watch History** menu to Pull or Push your watched status.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| **`Space`** | Toggle Play/Pause |
| **`F`** | Toggle Fullscreen |
| **`Esc`** | Exit Fullscreen |
| **`Double-Click`** | Toggle Fullscreen (Video area) |
| **`Up`** | Increase volume (up to 200%) |
| **`Down`** | Decrease volume |
| **`M`** | Toggle Mute |
| **`←` (Back)** | Stop playback and return to series view |

---

## ⚙️ Configuration

Lan Streamer configuration is managed through the **Settings > General Settings** menu and persisted in `~/.config/lan-streamer/config.json`.

### Path Customization
- **Database Path**: The location of the SQLite database file.
- **Log Directory**: The directory where rotated logs are stored.
- **Enable Global Log File**: Toggle generation of `lan-streamer.log`. (Default: Off, console only).
- **Enable Local Caching**: Toggle background copying of remote files to local disk before playback. (Default: Off).
- **Use Embedded Video Player**: Toggle between the integrated player and launching an external VLC window. (Default: On).

### Environment Variables
- `LAN_STREAMER_DB`: Override the database file location for portability or testing.

### Logging System
Logs are automatically organized and rotated daily within the configured log directory:
- `db.log`: Database operations and migrations.
- `ui.log`: Interface events and errors.
- `scanner.log`: Library scanning and metadata matching details.
- `jellyfin.log`: API interactions and history synchronization.
- `tmdb.log`: Metadata fetching from TMDB.
- `player.log`: Video playback, caching, and VLC interaction details.
- `lan-streamer.log`: Global application log (if enabled).

---

## 🧪 Development

### Technical Stack
*   **UI Framework**: [PySide6](https://doc.qt.io/qtforpython/) (Qt 6) with QML
*   **Database**: [SQLite 3](https://www.sqlite.org/) with [SQLAlchemy](https://www.sqlalchemy.org/) ORM and [Alembic](https://alembic.sqlalchemy.org/) migrations
*   **Package Manager**: [uv](https://github.com/astral-sh/uv)
*   **Linting/Formatting**: [Ruff](https://github.com/astral-sh/ruff)

### Testing
We use `pytest` with `pytest-cov` and `pytest-qt` for comprehensive UI and logic testing.
```bash
make test
```

### Releases
We follow [Conventional Commits](https://www.conventionalcommits.org/) for automated versioning and changelog generation.
```bash
make release
```

---

## 📜 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
