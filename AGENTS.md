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
  - [scanner/](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner): Library crawler, filename parser, and bulk-renamer.
    - [core.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner/core.py): 3-pass dispatcher — `scan_directories()` with `pass_number` parameter (0=all, 1=discovery, 2=metadata, 3=technical).
    - [pass1_file_discovery.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner/pass1_file_discovery.py): Filesystem walk, stub creation (no TMDB).
    - [pass2_metadata.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner/pass2_metadata.py): TMDB metadata resolution, TMDB-only season placeholders.
    - [pass3_technical.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/scanner/pass3_technical.py): Batch ffprobe + missing-file cleanup.
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

### 5. Cast & Crew UI Architecture

The detail views display cast/crew metadata via a dedicated DB backend:

- **DB models** (`db/models_cast.py`): `Person` (biography, birth/death, profile), `MediaCast` (polymorphic FK to series/season/episode/movie), `MediaImage` (posters/backdrops at multiple resolutions).
- **Cast queries** (`db/queries_cast.py`): `get_cast_for_series()`, `get_cast_for_season()`, `get_cast_for_episode()`, `get_cast_for_movie()`, `get_filmography()`, `get_person_by_id()`.
- **Service layer** (`services/metadata_cast.py`, `services/metadata_images.py`): Coordinates TMDB API calls, role mapping (actor/director/writer/producer), dedup, and batch DB storage.
- **Scan pipeline**: Cast/image fetch integrated into scan worker callbacks (`_season_callback`, `_movie_callback` in `scan_worker_all.py`).
- **Cast cards in detail views**: `SeriesDetailView._display_cast_section()` and `MovieDetailView._display_cast_section()` render horizontal scrollable cast grids; clicking a card emits `controller.cast_member_selected`.
- **SeasonDetailView** (`ui_views/season_detail.py`): Full-page view with poster, season overview, and a 6-column episode table (matching SeriesDetailView). Receives a `Controller` instance. Reads data from `controller.cached_library_data`. Supports TMDB display group re-ordering. Episodes have progress bars, details buttons, and watched/unwatched/missing/future color coding. Signals: `back_requested`, `episode_details_requested`. No cast section.
- **CastDetailView** (`ui_views/cast_detail.py`): Full-page view with photo, biography, birth/death info, filmography. Signals: `back_requested`, `media_item_clicked`.
- **PosterSelectorDialog** (`ui_views/dialogs/poster_selector.py`): Dialog for selecting posters/backdrops from TMDB images.
- **Wiring** (`main.py`): Stacked layout indices — 0: grid, 1: series_detail, 2: movie_detail, 3: season_detail, 4: cast_detail, 5: player. Navigation signals wire between views.

### 6. Scanner 3-Pass Architecture

The library scanner uses a 3-pass pipeline for clean separation of concerns:

- **Pass 1 — File Discovery** (`scanner/pass1_file_discovery.py`): Walks the filesystem, discovers video files, creates stub episode/movie records. No TMDB calls, no ffprobe. Returns series data with stub metadata and seasons.
- **Pass 2 — Metadata Resolution** (`scanner/pass2_metadata.py`): Resolves TMDB metadata for series, seasons, episodes, and movies. Operates entirely on data from Pass 1 (no filesystem walking). Adds TMDB-only seasons (placeholder entries for seasons not on disk).
- **Pass 3 — Technical Metadata** (`scanner/pass3_technical.py`): Batch ffprobe scan for codec/resolution info + cleanup of missing-file entries.

**Dispatcher** (`scanner/core.py`):
- `scan_directories()` accepts `pass_number` parameter (0 = all 3 passes, 1, 2, or 3 for individual passes).
- Each pass is implemented in a separate `_scan_pass{N}` function.
- Results flow sequentially: Pass 1 → Pass 2 → Pass 3.
- `_merge_series_data()` handles series spanning multiple root directories (combines seasons from different roots).
- Existing library entries not found on disk are preserved (non-destructive).

**Pattern for tests**: When testing Pass 2 metadata resolution, three TMDB client paths must be patched:
```python
patch("lan_streamer.services.metadata_series.tmdb_client", mock)
patch("lan_streamer.services.metadata_episode.tmdb_client", mock)
patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock)
```

**Critical locked_metadata invariant (manual-match-flow only):** Pass 2 of the scanner pipeline (`scan_series_pass2` in `pass2_metadata.py`) checks `locked_metadata` in the series metadata at line ~294 and **returns early without fetching any TMDB episode data** when it is `True`. This gate exists to preserve manually matched metadata during normal library scans — normal scans never clear the flag, so the lock is effective in production.

The only flow that temporarily sets `locked_metadata = False` is the **manual metadata match flow** (`apply_metadata_match()` → MetadataApplyWorker), because Pass 2 needs to fetch TMDB episodes for the freshly matched series. Any code path in that flow **must** ensure `locked_metadata` is `False` on the dict passed to the worker. It is re-set to `True` after the worker completes (in `_on_metadata_apply_finished`). The most common mistake is passing a reference to an old metadata dict that still has `locked_metadata: True` from a prior match — this causes all episode names to remain as raw filenames.

- Keep modules small, single-purpose, and grouped under descriptive directories.
- Avoid generic filenames like `helper.py` or `utils.py` in favor of specific functional terms.
- **Static Typing**: Enforce 100% strict `mypy` type checking for all production code in `src/lan_streamer/`.

### 7. MediaFile Version Preservation (Critical)

When multiple video files exist for the same episode (e.g. `S01E01.mkv` + `S01E01.mp4` from different root directories, or within the same season directory), all file paths **must** be preserved as `versions` entries. Users rely on these to select which file to play.

**Critical invariant:** Every episode in the scan pipeline dict **and** every `Episode` DB record **must** have a `versions` list containing all file paths for that episode.

**Code paths that must never strip `versions`:**
- `services/metadata_episode.py:_process_episode_file()`: Returns an episode dict **without** a `versions` key by default. When the existing episode has a `versions` list, it **must** be carried forward explicitly: `res["versions"] = list(existing_episode["versions"])`. This is the most commonly missed path.
- `scanner/pass2_metadata.py:scan_series_pass2()`: Iterates existing episodes by path and calls `_process_episode_file()`. The returned `matched` list replaces the season's episodes — versions from pre-merge data must survive through `_process_episode_file()`.
- `db/library_tv.py:_save_episode_record()`: Calls `_sync_media_files(session, episode, versions)`. When `versions` is `None`, it falls back to a single-entry list from top-level fields, silently dropping multi-file data. The fallback is a safety net, **not** a substitute for passing the real versions list.
- `scanner/core.py:_merge_series_data()`: **Must** use `_merge_episodes_by_number()` (never `{**existing_seasons, **incoming_seasons}`) to merge episodes within same-named seasons across root directories, combining their `versions` lists.
- `scanner/core.py:_merge_episodes_by_number()`: Merges version lists by deduplicating on path. When the same episode number exists in both inputs, version dicts with new paths are appended to the existing entry's versions list.

**Testing invariant:** Any change to the scan pipeline must be verified with a test that creates 2+ files for one episode number and asserts 2+ versions survive to the final library dict and/or DB.

### 8. Testing URL Constraints (Strict Mock URL Rule)
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
- Instantly update `README.md` and other guides when changing features, database schemas, UI elements, or configuration options.

### Step 4: Commits
- Commit incrementally with small, focused diffs using the Conventional Commits specification (e.g. `feat(ui): ...`, `fix(db): ...`, `docs: ...`, `test: ...`).
