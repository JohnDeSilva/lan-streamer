# Lan Streamer

**Lan Streamer** is a lightweight, desktop media library manager designed for users who store their media locally (e.g., on a NAS) and want a beautiful UI for browsing and playing their content via VLC, while keeping metadata and watched status in sync with **Jellyfin**.

Unlike standard Jellyfin clients, Lan Streamer focuses on **local playback**, launching VLC directly to ensure bit-perfect streaming with zero transcoding and maximum compatibility.

## 🚀 Key Features

*   **📺 High-Fidelity Playback**: Launches VLC directly to play local files, ensuring original quality without server-side transcoding.
*   **🔍 Robust Metadata Matching**: Implements a multi-stage search strategy (Exact, Colon-replaced, Fuzzy, and Word-based fallbacks) to reliably link local folders to Jellyfin series.
*   **🛠️ Manual Correction**: If automated matching fails, use the "Match Series..." context menu to manually search and link the correct Jellyfin entry.
*   **🔄 Bidirectional Sync**:
    *   Pulls posters and overviews from Jellyfin.
    *   Syncs "Watched" status back to your Jellyfin server.
*   **📁 Multi-Library Support**: Organize your content into different libraries (e.g., "Current", "Archive") across multiple root directories.
*   **🎨 Premium UI**: A modern, dark-themed interface built with PySide6 (Qt for Python).
*   **🛡️ Battle-Tested**: Comprehensive test suite with ~95% code coverage.

## 🛠️ Requirements

*   **Python**: 3.14+
*   **VLC**: Must be installed and available in your system's PATH.
*   **Jellyfin**: A running Jellyfin server and an API key.

## 📦 Installation

This project uses `uv` for fast, reliable package management.

```bash
# Clone the repository
git clone https://github.com/JohnDeSilva/lan-streamer.git
cd lan-streamer

# Install dependencies
uv sync
```

## 🖥️ Usage

### Running Locally
```bash
make run
```

### Configuration
1.  Open the **Jellyfin Settings** from the gear icon.
2.  Enter your Jellyfin URL and API Key.
3.  Use **Library Settings** to add your local TV series folders.
4.  Click **Force Scan** to sync metadata and posters.

## 🧪 Development

### Running Tests
```bash
make test
```

### Linting
```bash
make lint
```

### Versioning & Releases
We use **Commitizen** for conventional commits and automated changelogs.
```bash
# To create a new release (bumps version, updates CHANGELOG.md, tags and pushes)
make release
```

## 📜 License
This project is licensed under the MIT License - see the LICENSE file for details.
