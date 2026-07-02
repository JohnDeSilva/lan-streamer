# Code Review: Metadata Enhancement Branch (`metadata_improvements`)

This document contains a thorough code review of the changes introduced in the `metadata_improvements` branch compared to the main release baseline (`v0.39.0`). It highlights potential bugs, architectural risks, design antipatterns, and suggested improvements across both application and test code.

---

## 🐛 Potential Bugs & Issues (Organized by Severity)

### Bug 1: UI Thread Safety Violation & Background Thread `QPixmap` Instantiation
- **Location:** [poster_selector.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/dialogs/poster_selector.py) — `_load_thumbnail_into_label()` / `_ThumbnailDownloader`
- **Description:**
  In `_load_thumbnail_into_label`, a local closure `on_downloaded` is connected to the `downloader.downloaded` signal. Since `on_downloaded` is a regular Python function (not a Slot on a QObject), PySide6 connects it using `DirectConnection`, meaning it executes in the emitter's thread. The emitter thread is the background Python `threading.Thread` spawned by `downloader.start_download()`.

  Within this background thread, `on_downloaded` performs two major Qt safety violations:
  1. Instantiates a `QPixmap` (`pixmap = QPixmap()`) and loads image data. In Qt, `QPixmap` is a GUI class tied to the windowing system and is strictly prohibited from being used outside the main thread.
  2. Modifies UI widget properties (`label.setPixmap(...)` and `label.setText("📷")`). Mutating Qt widgets from non-GUI threads triggers undefined behavior, which often manifests as segmentation faults (app crashes), visual corruption, or event loop deadlocks.
- **Danger level:** **High** (Will cause application crashes/segmentation faults, especially on Linux/X11/Wayland and macOS).
- **Likelihood:** **High** (Triggers every time the user fetches posters from TMDB).
- **Complexity of Fix:** **Medium** (Requires switching from `QPixmap` to `QImage` or raw bytes inside the thread, emitting a signal to a proper QObject slot on the GUI thread, and handling `QPixmap` conversion/UI rendering exclusively on the main GUI thread).
- **Pros of fixing:** Restores strict Qt thread safety, prevents random app crashes during poster fetches.
- **Cons of fixing:** Slightly increases the complexity of signal connection boilerplate.

### Bug 2: Version Update Logic Fails to Notify Release Candidate Users
- **Location:** [updater.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/system/updater.py) — `UpdateCheckWorker._check_rc`
- **Description:**
  The worker compares versions using `parse_base_version()`, which strips pre-release suffixes (e.g., `v0.39.0rc0` parses to `(0, 39, 0)`).
  If a user is running a release candidate (e.g., `v0.39.0rc0`) and the stable release (`v0.39.0`) or a newer release candidate (`v0.39.0rc1`) is published, the comparison evaluates to `(0, 39, 0) > (0, 39, 0)`, which is `False`.
- **Danger level:** **Medium** (Does not crash the app, but silently disables update notifications for release candidate users).
- **Likelihood:** **High** (Will always affect users running RC versions when stable versions or new RCs are published).
- **Complexity of Fix:** **Medium** (Requires implementing a proper version parser/comparator that accounts for pre-release suffixes, or importing `packaging.version.Version` to compare versions correctly).
- **Pros of fixing:** RC users will receive updates properly when stable builds are published.
- **Cons of fixing:** None.

### Bug 3: Database Write Locking Risk Under Parallel Scan
- **Location:** [scan_worker_all.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/backend/scan_worker_all.py) — `_season_callback` / `_movie_callback`
- **Description:**
  The scan callbacks run in separate folder-pool threads and call database write operations directly (`metadata_cast.fetch_and_store_series_credits` and `metadata_images.fetch_and_store_series_images` which internally call `session.commit()`).

  Although WAL mode and `busy_timeout = 5000` are configured, SQLite only permits a single writer transaction at any given time. If multiple background threads attempt to write credits/images concurrently, they may block each other. Under load (e.g. many series/movies processed at once), some threads will exceed the 5-second busy timeout, throwing `OperationalError: database is locked` and causing the scan worker to fail or log warnings.
- **Danger level:** **Medium** (Can cause database write timeouts, scanning aborted/interrupted).
- **Likelihood:** **Medium** (Happens during initial parallel library scans with multiple items).
- **Complexity of Fix:** **Medium** (Requires routing credits/images database writes through the `AsyncDatabaseWriter` serialized queue, similar to how seasons and movies are saved).
- **Pros of fixing:** Guarantees database write serialization, prevents lock contention and scanning errors.
- **Cons of fixing:** Requires defining new async database writer actions.

---

## 🎨 Recommended Improvements (Organized by Complexity)

### Low Complexity Improvements

#### 1. Redundant Database Commits
- **Location:** [queries_cast.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db/queries_cast.py) & [poster_selector.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/dialogs/poster_selector.py)
- **Description:** Many functions invoke `session.commit()` inside a `with get_session() as session:` block. The `get_session` context manager already commits automatically on successful block exit. Explicit commits inside the block are redundant.
- **Benefit:** Clean, idiomatic codebase matching existing SQLAlchemy query patterns.

#### 2. Test Filesystem Isolation
- **Location:** [test_cast_detail.py](file:///home/sadmin/antigravity/lan-streamer/tests/unit/ui_views/test_cast_detail.py) — `test_cast_detail_movie_filmography`
- **Description:** The test creates a hardcoded file in `/tmp/test_poster.jpg` directly rather than using pytest's built-in `tmp_path` fixture. This can cause permission collision errors on shared build machines.
- **Benefit:** Robust test execution.

---

### Medium Complexity Improvements

#### 1. Missing Unique Constraints for Seasons and Episodes
- **Location:** [models_cast.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/db/models_cast.py) — `MediaCast`
- **Description:** The `MediaCast` table features unique constraints for series (`uq_media_cast_person_series`) and movies (`uq_media_cast_person_movie`), but lacks them for season-level and episode-level cast roles. Although deduplicated in memory during scan runs, database-level integrity constraints should be added.
- **Benefit:** Prevents accidental duplicates in case of service or scanning failures.

#### 2. Circle Photo Clipping Stylesheet Incompatibility
- **Location:** [series_detail.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/series_detail.py) & [season_detail.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/ui_views/season_detail.py)
- **Description:** The code applies `border-radius: 30px` to `photo` QLabels. However, Qt stylesheets do not automatically crop QPixmaps painted over QLabels. As a result, profile images render as squares.
- **Benefit:** Programmatic masking (using `QPainter` with a circular clip path) should be used instead to ensure premium, circular rendering as designed.

#### 3. Navigation Stack Disruption on Back Actions
- **Location:** [main.py](file:///home/sadmin/antigravity/lan-streamer/src/lan_streamer/main.py)
- **Description:** Clicking "Back" on `CastDetailView` redirects the user to the series view (index 1) or movie view (index 2). If the user arrived at the cast view from `SeasonDetailView` (index 3), they are sent to the series view instead of returning to the season details they were looking at.
- **Benefit:** Preserves navigation context (improves UX flow).

---

## 🛠️ Resolution Plans

### Plan for Bug 1 (Threading Violation)
1. Modify `_ThumbnailDownloader` to download raw bytes (remains as is) but ensure it uses a slot/signal connection that triggers safe main-thread execution.
2. In `_load_thumbnail_into_label`, instead of a local closure connected to a Python callable, subclass `QLabel` (e.g. `LazyThumbnailLabel`) or connect `downloader.downloaded` to a thread-safe custom slot in `PosterSelectorDialog` that resolves which label needs the update.
3. Keep `QPixmap` instantiation and label modifications strictly in the receiving slot running on the GUI thread.

### Plan for Bug 2 (RC Version Update Logic)
1. Refactor `parse_version` and `parse_base_version` to support pre-release tag comparisons (e.g. comparing the suffix when base tuples match).
2. Alternatively, utilize `packaging.version.Version` to compare versions safely since the project already includes it in dependencies.

### Plan for Bug 3 (Lock Contention)
1. Create new actions `"save_series_credits"`, `"save_movie_credits"` in `AsyncDatabaseWriter`.
2. Move the database write calls out of `scan_worker_all.py` callbacks and route them through the `self._database_writer` queue.
