# LAN Streamer
[![Lint](https://github.com/JohnDeSilva/lan-streamer/actions/workflows/lint.yml/badge.svg)](https://github.com/JohnDeSilva/lan-streamer/actions/workflows/lint.yml)
[![Test](https://github.com/JohnDeSilva/lan-streamer/actions/workflows/test.yml/badge.svg)](https://github.com/JohnDeSilva/lan-streamer/actions/workflows/test.yml)

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

> [!WARNING]
> **MacOS Gatekeeper**: The downloaded macOS artifact contains an unsigned `.app` bundle. You may see a "cannot be verified" or "malware" warning. To open it, either **Right-Click -> Open** the `LanStreamer.app` to bypass the warning, or clear the quarantine attribute by running `xattr -cr /path/to/LanStreamer.app` in your terminal.

> [!TIP]
> **Standalone Executables**: The pre-compiled Linux and Windows executables feature **smart VLC plugin discovery**. They will automatically scan your system for native VLC plugins upon startup, allowing advanced rendering flags (like `--swscale-mode=2`) to function natively without any manual `VLC_PLUGIN_PATH` configuration. If plugins are completely missing, the player gracefully falls back to default settings to prevent crashes.

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

## 🧪 Development & Quality Assurance

### Technical Stack
*   **UI**: PySide6 (Qt 6)
*   **Database**: SQLite with SQLAlchemy ORM (using strictly 2.0 query syntax)
*   **Migrations**: Alembic
*   **Testing**: pytest, pytest-cov, pytest-qt
*   **Linting**: Ruff
*   **Type Checking**: mypy

### Local Testing & Linting
Run unit tests with coverage validation (90% minimum threshold):
```bash
make test
```

Check formatting, lint rules, types, and validate all non-Python files (YAML, Dockerfiles, etc) via `pre-commit`:
```bash
make lint
```
Or run individual checks:
```bash
make check-lint  # Verify styling without fixing
make typecheck   # Run static type analysis
```

### 🤝 Git Hooks
The repository includes pre-commit hooks to automate quality checks before committing or pushing code:
1.  **Installation**:
    ```bash
    make setup-git-hooks
    ```
2.  **Hook Execution**:
    -   **`commit-msg`**: Validates that commit messages follow the [Conventional Commits](https://www.conventionalcommits.org/) specification using `commitizen`.
    -   **`pre-commit`**: Automatically runs type-checking (`make typecheck`) and style checks (`make check-lint`).
    -   **`pre-push`**: Ensures type-checking, style checks, and commit range conformity (`commitizen check branch`) pass before pushing remote branches.

### 🐳 Local Containerized Testing
To ensure binary build stability and dependency compatibility across different Linux distributions, all Linux testing is centralized via Docker/Podman using the `TEST_OS` and `TEST_OS_VERSION` environment variables.

*   **Test in Container**: Builds the container for the specified OS and runs the test suite inside it. Defaults to `fedora:latest`.
    ```bash
    make test                                      # Runs fedora:latest
    TEST_OS=ubuntu make test                       # Runs ubuntu:latest
    TEST_OS=ubuntu TEST_OS_VERSION=22.04 make test # Runs ubuntu:22.04
    ```
    > [!TIP]
    > When testing non-latest OS versions, the `TEST_OS_VERSION` argument is passed dynamically to the base Dockerfile. If the older OS version requires significantly different system dependencies or package names, you can create a version-specific Dockerfile (e.g., `docker/Dockerfile.ubuntu-22.04`), and the `Makefile` will automatically detect and use it instead!

*   **Validate Executable**: Builds the container, tests the compiled PyInstaller executable within the container, and extracts the binary to your host machine's `./dist/` directory.
    ```bash
    make validate-executable
    TEST_OS=ubuntu make validate-executable
    ```

---

## 🛡️ Continuous Integration & Repository Operations

All code pushed or submitted via Pull Request is automatically validated through GitHub Actions workflows:

### GitHub Workflows
1.  **Lint & Typecheck (`lint.yml`)**:
    -   Triggered on push and pull requests targeting `main`.
    -   Automatically checks formatting, executes Ruff linting, runs Mypy type-checking, and verifies commit message compliance for branch revisions.
    -   Executes all `pre-commit` hooks (`hadolint`, `yamllint`, `actionlint`, etc.) across the entire codebase.
2.  **Cross-Platform Verification (`test.yml`)**:
    -   Runs a multi-operating system matrix validating all code paths:
        -   **Linux (Ubuntu/Fedora)**: Leverages Docker containers via `TEST_OS` in the `Makefile` to securely build, test, and validate binaries without requiring system-level dependencies on the GitHub runner.
        -   **macOS**: Configures macOS-latest with brew-installed VLC, runs tests, and compiles/validates the executable with target-specific VLC library pathing.
        -   **Windows**: Deploys Windows-latest, installs VLC/FFmpeg, applies schema migrations, runs tests, and compiles/verifies the executable.
3.  **Build Executables & Release (`executable.yml`)**:
    -   Triggered on pushes to `main` and on version tag creations (`v*`).
    -   Compiles and packages standalone applications for **Ubuntu**, **Fedora**, **macOS** (as a `.app` bundle), and **Windows**.
    -   Automatically generates GitHub Releases and attaches the executables as downloadable release assets whenever a new version tag is pushed.

### Repository Management
-   **Dependabot**: Configured (`.github/dependabot.yml`) to perform daily updates on the `uv` package ecosystem to ensure dependencies remain secure and up-to-date.
-   **Code Ownership**: Configured (`.github/CODEOWNERS`) to assign ownership of all project files to `@JohnDeSilva`.
-   **Releases**: Automatic version bumps and changelog management are handled through:
    ```bash
    make release
    ```
    This validates linting, runs the test suite, bumps the project version via `cz bump`, regenerates `uv.lock`, commits, and pushes the code and new version tags to GitHub.

---


[![Ubuntu](https://img.shields.io/github/actions/workflow/status/JohnDeSilva/lan-streamer/executable.yml?label=Build%20Executable%20Ubuntu)](https://github.com/JohnDeSilva/lan-streamer/actions/workflows/executable.yml)

[![Fedora](https://img.shields.io/github/actions/workflow/status/JohnDeSilva/lan-streamer/executable.yml?label=Build%20Executable%20Fedora)](https://github.com/JohnDeSilva/lan-streamer/actions/workflows/executable.yml)

[![macOS](https://img.shields.io/github/actions/workflow/status/JohnDeSilva/lan-streamer/executable.yml?label=Build%20Executable%20macOS)](https://github.com/JohnDeSilva/lan-streamer/actions/workflows/executable.yml)

[![Windows](https://img.shields.io/github/actions/workflow/status/JohnDeSilva/lan-streamer/executable.yml?label=Build%20Executable%20Windows)](https://github.com/JohnDeSilva/lan-streamer/actions/workflows/executable.yml)

## 📜 License
MIT License. See [LICENSE](LICENSE) for details.
