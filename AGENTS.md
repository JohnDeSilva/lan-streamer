# 🤖 Developer Guidelines & AI Agent Rules

This document establishes the repository-wide standards, architectural constraints, layout structure, and development workflows for AI agents.

---

## 🛠️ Tech Stack & Constraints

- **UI Framework**: PySide6 (`QtWidgets` strictly; QML is prohibited).
- **Database Engine**: SQLite with SQLAlchemy ORM. Use strictly SQLAlchemy 2.0 style queries (`select()`, `update()`, etc.). Legacy `session.query()` is prohibited.
- **Migrations Engine**: Alembic.
  - Generate revisions via `make revision name="description"`.
  - Apply revisions via `make migrate`.
  - Revision versions **must** exactly match the application version (`__version__` in [__init__.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/__init__.py)). Do not create future-version migrations or bump versions solely for migrations.
  - Implement and write test cases verifying that database migrations handle existing data correctly without data loss.
- **APIs & Networking**: `requests` library for Jellyfin and TMDB integrations.
- **Build & Executables**: `uv` package manager (`uv run`, `uv add`, `uv lock`). All quality controls, testing, and building targets are wrapped via the [Makefile](file:///home/sadmin/antigravity/lan-streamer/Makefile).
- **Video Playback Engine**: `python-vlc` (requires a system-wide VLC player installation).

---

## 📂 Repository Layout

- [src/entrypoint.py](file:///home/sadmin/antigravity/lan-streamer/src/entrypoint.py): Startup file for compiled PyInstaller target.
- [src/lan_streamer/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/):
  - [main.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/main.py): Sets up the application GUI and controller runtime.
  - [db/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db): ORM schemas ([models.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db/models.py)), queries ([queries_playback.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db/queries_playback.py), [queries_ui.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db/queries_ui.py), [smart_row_cache.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db/smart_row_cache.py)), serialization, and database setup.
  - [backend/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend): Background thread workers (`QThread`/`QWorker`) for non-blocking file scanning, Jellyfin sync, and metadata updates.
    - [scan_worker_base.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/scan_worker_base.py): Shared scan helpers (`create_empty_stats`, `merge_stats_dicts`, `log_stats_breakdown`, `log_issues_report`, `discover_single_library_tree_impl`).
    - [scan_worker_all.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/scan_worker_all.py): `ScanAllLibrariesWorker` — parallel multi-library scan via `ThreadPoolExecutor`.
    - [scan_worker_single.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/scan_worker_single.py): `ScanSingleLibraryWorker` — single-library scan.
  - [scanner/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner): Library crawler, filename parser, and bulk-renamer.
  - [services/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services): Business-logic services (discovery, TMDB/Jellyfin metadata merging, [smart_row_service.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/services/smart_row_service.py) — combined view cache coordination).
  - [playback/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/playback): Video player widget wrapper around `libvlc` and OS wake-lock controller.
  - [providers/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/providers): External client wrappers (TMDB, Jellyfin, OpenSubtitles, MyAnimeList).
  - [system/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system): Config manager, logging handler, backups, updater, and [threading_manager.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/threading_manager.py) — centralized `WorkerManager`/`WorkerSlot` lifecycle manager.
  - [ui_views/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views): Desktop PySide6 QtWidgets view screens, stylesheet themes, and controllers.
    - [dialogs/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/dialogs): Dialog windows including settings, details views, and [search.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/dialogs/search.py) — `SearchDialog` with debounced autocomplete for series discovery.
- [tests/](file:///home/sadmin/antigravity/lan-streamer/tests): Structured unit, integration, and end-to-end tests (minimum 90% code coverage target).

---

## 📐 Code Standards & Style

### 1. Variable Naming (Strict No-Abbreviation Rule)
Do not abbreviate variable names. Use full, descriptive names:
- ❌ `ep`, `ep_name`, `ep_num` ➔ ✅ `episode`, `episode_name`, `episode_number`
- ❌ `jf_id`, `jf_client` ➔ ✅ `jellyfin_id`, `jellyfin_client`
- ❌ `db`, `conn` ➔ ✅ `database`, `connection`
- ❌ `tmdb_id` ➔ ✅ `tmdb_identifier`

### 2. UI Thread Safety (Responsiveness)
- The main Qt UI thread must never freeze.
- Run all blocking IO, filesystem crawling, DB writes, and network requests in background workers (`QThread`/`QWorker`) under `src/lan_streamer/backend/`.

### 3. Detailed Logging
- Use standard Python `logging`.
- Log all database writes, schema updates, config state changes, and filesystem mutations (renaming/deletion).
- Log key user interactions (scan initiation, view transitions, metadata mappings).
- Log background thread lifecycles (startup, progress, errors, termination).

### 4. Smart Row Cache Architecture

The combined view (smart rows) uses a pre-computed cache table (`SmartRowCache` in `smart_row_cache` table) for fast rendering:

- **Cache table** (`db/models.py:SmartRowCache`): Stores pre-computed smart row items with FK references to `Series` and `Movie` tables. Display data (name, poster_path, library_name) is resolved via joined FK relationships. Computed aggregation fields (watched_count, date_added, etc.) avoid expensive recalculations.
- **Cache queries** (`db/smart_row_cache.py`): Provides `get_cached_smart_rows()` (read with fallback), `rebuild_cache_for_config()` (full rebuild), `clear_cache_for_config_hashes()` (targeted clear), and `rebuild_all_cache()` (complete rebuild).
- **Service layer** (`services/smart_row_service.py`): `SmartRowService` coordinates cache rebuilds on scan completion and watched events. Incremental updates for watched events only rebuild affected config hashes.
- **Controller signal** (`ui_views/controller.py:Controller.smart_rows_updated`): Emits a `list` of changed config hashes. The `LibraryGridView` listens for targeted row updates.
- **UI rendering** (`ui_views/library_grid.py`): `_build_smart_row_widget()` reads from cache. `_on_smart_rows_updated()` handles targeted row replacement without full re-render.

### 5. Code Organization
- Keep modules small, single-purpose, and grouped under descriptive directories.
- Avoid generic filenames like `helper.py` or `utils.py` in favor of specific functional terms.
- **Static Typing**: Enforce 100% strict `mypy` type checking for all production code in `src/lan_streamer/`.

### 6. Testing URL Constraints (Strict Mock URL Rule)
- Do not use actual, live external URLs in unit, integration, or e2e tests.
- Always use mock/local domains (e.g. `example.invalid`, `localhost`, `127.0.0.1`, or `jellyfin.local`) to avoid external network dependencies and prevent accidental network request execution during test runs.

---

## 🔄 Mandatory Developer Workflow

Every single change or task implemented on this codebase MUST strictly adhere to the following workflow in order:

### Step 1: Test-First Iteration
1. **Define Goal**: Fully understand requirements and impacts on existing features.
2. **Create/Update Tests**: Write automated tests that cover the new feature/bugfix first (expecting them to fail initially).
3. **Implement**: Modify application code in `src/` to satisfy the tests.
4. **Refine**: Maintain a minimum code coverage threshold of **90%**.

### Step 2: Verification Sequence
After **every change**, run:
1. `make test` (or `make test-local` on non-Linux) to verify tests pass and check coverage.
2. `make lint` as the **FINAL** step to check style, Ruff format/rules, MyPy typechecking, and pre-commit conformity. Resolving all warnings and errors is mandatory.

### Step 3: Documentation Synchronicity
- Instantly update `README.md`, `docs/codebase_guide.md`, and other guides when changing features, database schemas, UI elements, or configuration options.

### Step 4: Commits
- Commit incrementally with small, focused diffs using the Conventional Commits specification (e.g. `feat(ui): ...`, `fix(db): ...`, `docs: ...`, `test: ...`).
