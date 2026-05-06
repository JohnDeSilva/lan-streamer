# Lan Streamer

**Lan Streamer** is a premium, lightweight media library manager built for users who demand the best local playback experience while maintaining a modern, metadata-rich browsing interface.

It bridges the gap between local file storage (e.g., NAS, External Drives) and **Jellyfin**, ensuring your library stays beautiful and synchronized without the overhead or quality loss of server-side transcoding.

---

## 🚀 Key Features

*   **📺 Local-First Playback**: Launches **VLC** directly for bit-perfect streaming. Support for HDR, high-bitrate 4K, and all advanced codecs with zero transcoding.
*   **⚡ High-Performance Scanning**: Engineered with an incremental scanning engine using SQLite `UPSERT` logic. Minimize disk I/O while preserving manual corrections and user metadata.
*   **🔍 Advanced Metadata Matching**: Implements a robust, multi-stage search strategy (Exact, Colon-aware, Fuzzy, and Word-based fallbacks) to reliably link local folders to Jellyfin entries.
*   **📛 Official Naming**: Prioritizes official Jellyfin episode names (e.g., *"01 - Pilot"*) for a clean, professional library look, with filename fallbacks for unmatched content.
*   **🔄 Bidirectional Sync**: 
    *   Automatically downloads high-quality posters and overviews.
    *   Syncs "Watched" status back to your Jellyfin server in real-time.
*   **📁 Multi-Library Organization**: Group your content into logical libraries (e.g., "Main", "Archive", "Anime") with support for multiple root directories per library.
*   **🛠️ Manual Corrections**: Effortlessly fix incorrect matches via the "Match Series..." context menu.
*   **🎨 Premium Dark UI**: A sleek, high-contrast interface built with PySide6 (Qt) for a smooth and responsive desktop experience.

---

## 🏛️ Architecture & Stability

*   **Versioned Schema**: Formal database versioning tracks application updates and handles migrations automatically. The database version is strictly synchronized with the application version, ensuring metadata consistency across all releases.
*   **Background Workers**: Library scanning and synchronization occur in dedicated background threads, keeping the UI fluid even during massive library updates.
*   **🛡️ Quality Enforcement**: Maintains a strict **90% minimum code coverage** threshold. The CI pipeline and local test suite ensure regression-free development.

---

## 🛠️ Requirements

*   **Python**: 3.14+
*   **VLC**: Must be installed and available in your system's PATH.
*   **Jellyfin**: A running Jellyfin server and an API key.

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

### Setup Guide
1.  **Configure Jellyfin**: Click the gear icon to enter your Server URL and API Key. Use the "Test Connection" button to verify networking.
2.  **Add Libraries**: Open "Library Settings" to define your media roots.
3.  **Sync Data**: Click the refresh icon (Force Scan) to trigger the initial metadata and poster download.

---

## 🧪 Development

### Technical Stack
*   **UI Framework**: [PySide6](https://doc.qt.io/qtforpython/) (Qt 6)
*   **Database**: [SQLite 3](https://www.sqlite.org/) with UPSERT support
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
