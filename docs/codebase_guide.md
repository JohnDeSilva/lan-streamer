# Codebase Guide and Developer Standards

This document outlines the architecture, layout, tooling, and development standards of the `lan-streamer` codebase. AI assistants should read this document at the start of each session to gain immediate context without parsing the entire project.

---

## 🏛️ Codebase Structure & Organization

### 1. Source Directory ([src/](file:///home/sadmin/antigravity/lan-streamer/src))
All core application code resides in the `src/` directory:

*   **Entrypoint Script**:
    *   [src/entrypoint.py](file:///home/sadmin/antigravity/lan-streamer/src/entrypoint.py): The startup file used primarily for the PyInstaller build target.
*   **Main Application Package** ([src/lan_streamer/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer)):
    *   [src/lan_streamer/__init__.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/__init__.py): Specifies the current application version (`__version__`).
    *   [src/lan_streamer/main.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/main.py): Sets up the application GUI, controllers, and acts as the entrypoint for runtime execution.
    *   [src/lan_streamer/db/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db): Manages local database structure, database models ([models.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db/models.py)), queries (e.g., [queries_playback.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db/queries_playback.py), [queries_metadata_matching.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db/queries_metadata_matching.py)), connection setup, and database synchronization.
    *   [src/lan_streamer/backend/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend): Background thread workers (inheriting `QThread` or `QRunnable`) executing non-blocking operations. Includes workers for Jellyfin synchronization ([jellyfin_workers.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/jellyfin_workers.py)), file scanning ([scan_worker_all.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/scan_worker_all.py)), metadata embedding ([metadata_worker_embed.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/metadata_worker_embed.py)), and subtitles.
    *   [src/lan_streamer/scanner/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner): Filesystem scanning orchestration, filename parsing ([parser.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner/parser.py)), file property scanning ([file_property_scanner.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner/file_property_scanner.py)), bulk-renaming ([renamer.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner/renamer.py)), and version scoring ([versioning.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner/versioning.py)). Metadata resolution and media mapping logic have been extracted into the [services/](#services) package.
    *   [src/lan_streamer/services/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services): Business-logic services decoupled from scanner orchestration. Contains the following modules:
        *   [file_discovery.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/file_discovery.py): Filesystem scanning, change detection, and the `LibraryDict` container.
        *   [metadata_common.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/metadata_common.py): Shared helpers — locked-metadata TMDB stubs, Jellyfin ID resolution, season-episode merging.
        *   [metadata_movie.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/metadata_movie.py): Movie metadata resolution: defaults, existing-data application, poster download, TMDB data merging.
        *   [metadata_tv.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/metadata_tv.py): Series / season / episode metadata resolution: defaults, TMDB episode-group processing, episode-file matching.
        *   [metadata_updates.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/metadata_updates.py): Series-data cleaning, episode indexing, and post-scan change detection.
        *   [metadata_resolution.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/metadata_resolution.py): Backward-compatible re-export shim — re-exports all public helpers from the sub-modules above.
        *   [media_mapping.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/media_mapping.py): Jellyfin ID resolution and active-version selection for episodes.
        *   [mapping_updates.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/mapping_updates.py): File-path updates, record removal, and database cleanup when files are moved or deleted.
    *   [src/lan_streamer/playback/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/playback): Video player widget wrapped around `libvlc` ([player.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/playback/player.py), [widget.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/playback/widget.py)), wake-lock control to prevent system standby during playback ([wakelock.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/playback/wakelock.py)), and local pre-playback caching ([cache.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/playback/cache.py)).
    *   [src/lan_streamer/providers/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/providers): API integration wrappers for external services: TMDB API ([tmdb.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/providers/tmdb.py)), OpenSubtitles API ([opensubtitles.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/providers/opensubtitles.py)), MyAnimeList ([myanimelist.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/providers/myanimelist.py)), and Jellyfin API ([jellyfin.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/providers/jellyfin.py)).
    *   [src/lan_streamer/system/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system): Configuration manager ([config.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/config.py)), logging handler ([logging_handler.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/logging_handler.py)), database backup/restore ([backup.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/backup.py)), and self-updater ([updater.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/updater.py)).
    *   [src/lan_streamer/ui_views/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views): Desktop UI screens, dialogs, stylesheet themes, and controllers built using PySide6 QtWidgets.

### 2. Test Suite ([tests/](file:///home/sadmin/antigravity/lan-streamer/tests))
Automated tests are divided into structured subdirectories:
*   [tests/unit/](file:///home/sadmin/antigravity/lan-streamer/tests/unit): Core unit tests mapping component structures matching the source layouts (e.g., `tests/unit/ui_views/`, `tests/unit/db/`, `tests/unit/backend/`).
*   [tests/integration/](file:///home/sadmin/antigravity/lan-streamer/tests/integration): Integration testing paths.
*   [tests/e2e/](file:///home/sadmin/antigravity/lan-streamer/tests/e2e): Multi-component end-to-end user flow tests ([test_e2e_workflow.py](file:///home/sadmin/antigravity/lan-streamer/tests/e2e/test_e2e_workflow.py)).
*   [tests/load/](file:///home/sadmin/antigravity/lan-streamer/tests/load): Performance/load tests (marked with `@pytest.mark.load` and skipped during typical runs).

### 3. Documentation & Configurations
*   [docs/](file:///home/sadmin/antigravity/lan-streamer/docs): Contains architecture documents:
    *   [class_inheritance.md](file:///home/sadmin/antigravity/lan-streamer/docs/class_inheritance.md): Inheritance hierarchy.
    *   [logic_flows.md](file:///home/sadmin/antigravity/lan-streamer/docs/logic_flows.md): Key codepaths, decision gates, and workflows.
    *   [codebase_guide.md](file:///home/sadmin/antigravity/lan-streamer/docs/codebase_guide.md) (This document): Summary guide of directory structures and coding standards.
*   [Makefile](file:///home/sadmin/antigravity/lan-streamer/Makefile): Targets for local execution (`run`), formatting (`format`), check-linting (`check-lint`), full typecheck (`typecheck`), linting and pre-commits (`lint`), testing (`test`), local test suite run (`test-local`), PyInstaller building (`build`), and release tagging (`release`).
*   [pyproject.toml](file:///home/sadmin/antigravity/lan-streamer/pyproject.toml) / [uv.lock](file:///home/sadmin/antigravity/lan-streamer/uv.lock): Dependencies and environment specifications managed by `uv`.
*   [alembic.ini](file:///home/sadmin/antigravity/lan-streamer/alembic.ini) / [alembic/](file:///home/sadmin/antigravity/lan-streamer/alembic): Database migration configurations and version scripts.

---

## 🛠️ Technology Stack & Libraries

*   **Desktop UI Framework**: PySide6 (specifically Qt Widgets; QML is not used).
*   **Database Engine**: SQLite with SQLAlchemy ORM (Strictly SQLAlchemy 2.0 query syntax like `select()` and `update()` constructs instead of legacy `session.query()`).
*   **Migrations Engine**: Alembic.
*   **API Client / Network**: `requests`.
*   **Video Playback Engine**: `python-vlc` (requires a system-wide VLC installation).
*   **Package Manager**: `uv`.

---

## 📐 Development Rules & Coding Standards

### 1. Variable Naming: No Abbreviations
Do not use abbreviations in variable names. Use descriptive, full names:
*   ❌ `ep`, `ep_name`, `ep_num` ➔ ✅ `episode`, `episode_name`, `episode_number`
*   ❌ `jf_id`, `jf_client` ➔ ✅ `jellyfin_id`, `jellyfin_client`
*   ❌ `db`, `conn` ➔ ✅ `database`, `connection`
*   ❌ `tmdb_id` ➔ ✅ `tmdb_identifier` (or standard TMDB identifier field names)

### 2. Strict Type Checking & Code Style
*   **Static Type Checking**: Mandatory 100% strict `mypy` type checking for all production code in `src/lan_streamer/` (excluding the test files themselves, which are ignored by mypy rules in [pyproject.toml](file:///home/sadmin/antigravity/lan-streamer/pyproject.toml)).
*   **Code Linting & Formatting**: Enforced via `ruff`. Ensure code is formatted automatically before committing.

### 3. Responsiveness (Thread Safety)
To prevent the main Qt UI thread from freezing:
*   Never run long-lived, blocking, IO, or network operations directly in UI functions or controllers.
*   Use background threads via `QThread`/`QWorker` classes defined in [src/lan_streamer/backend/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend).

### 4. Database Migrations
*   **Alembic Revisions**: Generate migration scripts using `make revision name="migration_description"`.
*   **Version Matching**: Migration versions **MUST** be exactly equal to the current application version (`__version__` in [src/lan_streamer/__init__.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/__init__.py)).
*   Never bump the app version solely to trigger a database migration.
*   Always implement robust checks to ensure older databases migrate safely without data loss. Write unit tests verifying migrations handle existing records.

### 5. Logging and Code Organization Standards
To ensure the application remains easy for a human to debug, maintain, and follow, adhere to the following logging and clean code guidelines:

*   **Detailed Application-Wide Logging**:
    *   Implement verbose, descriptive logging across the entire application using Python's standard `logging` library.
    *   **Data Changes and Mutations**: Log all database writes, schema updates, cached config state changes, and filesystem renaming or deletion mutations.
    *   **User Actions**: Log all key user interactions, such as launching scans, opening views/dialogs, triggering metadata mappings, choosing playback devices, and initiating file embeds.
    *   **Long-Running Operations**: Track the lifecycle of background threads and workers (e.g., jellyfin synchronization, library crawling, subtitle merging) with clear startup, periodic progress, error, and final termination logs.
*   **Code Organization & Readability**:
    *   **Small, Single-Purpose Files**: Avoid creating massive monolithic files. Break logic down into small modules, each having a single, clearly defined purpose.
    *   **Folder Structure**: Group related modules into dedicated directories/packages (e.g., separating UI, database operations, background workers, and API providers).
    *   **Descriptive Naming**: Use explicit, unambiguous file names, function names, and class names that convey their precise responsibilities. Avoid generic names like `helper` or `utils` in favor of specific descriptive terms.

---

## 🔄 Mandatory Developer Workflow

Every single change or task implemented on this codebase MUST strictly adhere to the following workflow:

### Step 1: Write/Update Tests First (Test-First Iteration)
1.  **Define Goal**: Fully understand the requirement or issue.
2.  **Create/Update Tests**: Write automated unit or integration tests that cover the new feature or bug fix (expecting them to fail initially).
3.  **Implement**: Modify code in `src/` to satisfy the tests.
4.  **Refine**: Optimize code while maintaining a minimum code coverage threshold of **90%**.

### Step 2: Run Linting and Tests (Strict Verification)
After **every change**, run:
*   `make test` (or `make test-local` on non-Linux platforms) to run the full test suite and confirm 90% code coverage.
*   `make lint` as the final step to run Ruff formatter, checks, MyPy typechecking, and pre-commit checks.

> [!IMPORTANT]
> All linting issues, typecheck warnings, test errors, and failures **must** be resolved. Never commit code that breaks these verifications.

### Step 3: Update Documentation
Any change that alters functionality, UI elements, database schemas, configuration parameters, or commands **requires** corresponding updates in documentation:
*   [README.md](file:///home/sadmin/antigravity/lan-streamer/README.md)
*   Relevant guides under [docs/](file:///home/sadmin/antigravity/lan-streamer/docs), including updating this codebase guide ([docs/codebase_guide.md](file:///home/sadmin/antigravity/lan-streamer/docs/codebase_guide.md)) to reflect structural or layout modifications.

### Step 4: Incremental Commits
*   Changes should be incremental. Prefer multiple **small, focused commits** over large commits when possible.
*   Commits **must** adhere to the **Conventional Commit** standard (e.g., `feat(ui): ...`, `fix(db): ...`, `docs: ...`, `test: ...`).
