## v0.30.4 (2026-06-21)

### Fix

- **db**: handle counter-suffixed episode names in name-based fallback
- **scanner**: fix dedupe bug
- **scanner**: use TMDB metadata as episode name, not filenames
- **jellyfin**: only push watched episodes to jellyfin
- **logging**: improved Logging depth

### Refactor

- **services**: remove unused media_mapping and mapping_updates modules
- **services**: remove dead code and unused re-exports
- **services**: split metadata_tv.py into metadata_series and metadata_episode
- **services**: split metadata_resolution.py into domain-specific modules
- **wiring**: wire services into callers and remove proxies
- **services**: add file_discovery, metadata_resolution, media_mapping, mapping_updates, and metadata_updates services
- **services**: create services package
- **scanner**: extract versioning to break circular imports
- **db**: extract MAL push side-effect from queries_playback
- **db**: remove empty queries_metadata_matching placeholder
- **db**: rename queries_file_discovery to orm_serialization
- **db**: extract natural_sort_key to db/utils.py
- simplify client constructors and consolidate mock session fixture
- add Protocols, fix hasattr guards, achieve 100% controller coverage
- implement constructor-based dependency injection for providers and controller
- **providers**: apply setdefault to retain headers in injected sessions
- **providers**: implement constructor-based dependency injection for clients
- Add missing __init__.py files
- splits db, scanner, and dialog code into smaller easier to read files

## v0.30.3 (2026-06-16)

### Fix

- **db**: removes episode records without tmdb id or media file path

## v0.30.2 (2026-06-15)

### Fix

- **db**: resolve unique constraint and placeholder delete errors
- **db**: resolve manual metadata remapping issues and uniqueness violations

## v0.30.1 (2026-06-15)

### Fix

- **dev-dependency**: bump ruff from 0.15.16 to 0.15.17
- restore vlc mock in test_playback_init.py to prevent test hang
- **scanner**: fix poster download skip

### Perf

- optimize database queries and filesystem directory scanning

## v0.30.0 (2026-06-15)

### Feat

- **scanner**: Decouple scanning pipeline into Pass 1 (Offline) and Pass 2 (Online Metadata-Only)

### Fix

- **scan**: flush deletes immediatly to minimize unique constraint errors
- improve next up filtering
- **ui**: updaet UI to reflect multipass scan
- **db**: implement Plex/Jellyfin-style "Next Up" continuation and sorting rules
- **db**: cleanup deleted and renamed files

### Refactor

- **db**: couple playback and watch states to creative metadata records
- **db**: decouple physical media files and playback states from metadata

### Perf

- **db**: optimize join performance on large libraries

## v0.29.0 (2026-06-12)

### Feat

- **scan**: implement selective scan passes based on file changes
- implement multi-pass color-coded library scans and settings report UI
- **scanner**: implement progressive database writes, metadata protection, and scan issues reporting

### Refactor

- remove compatibility wrappers and __all__ re-exports, and fix episodes UNIQUE constraint
- split scan/metadata workers, modularize queries, and add detailed logging

## v0.28.0 (2026-06-11)

### Feat

- add runtime metadata support for media files and update related components
- **db**: support UUID primary/foreign keys as strings in application code
- **db**: add alembic migration and tests for multiple media files support
- Add multiple file support

### Fix

- add size_bytes parameter to runtime update functions and related tests
- fix creation or temp records
- enhance error handling and logging in get_detailed_file_info function

## v0.27.2 (2026-06-11)

### Fix

- **config**: Implement database backup before migrations and update backup frequency defaults
- **config**: Enhance configuration handling with new app config methods and default seeding

### Refactor

- **db**: replaces primary key for tables with UUID stored as BLOB

## v0.27.1 (2026-06-10)

### Fix

- Add remove episode and series functionality with confirmation dialogs
- Implement config loading on library actions and add tests for auto-scan functionality
- Add MyAnimeList status labels for seasons in SeriesDetailsDialog

### Refactor

- **config,db**: Refactor configuration handling and migrate settings to database
- Rename settings tab to Series Info and update tab structure in SeriesDetailsDialog

## v0.27.0 (2026-06-09)

### Feat

- Implement automatic updates feature
- add audio output device selection menu and persistent configuration with Linux PulseAudio support

### Fix

- **dev-dependency**: bump ruff from 0.15.15 to 0.15.16

## v0.26.0 (2026-06-08)

### Feat

- implement automatic selection logic for English audio tracks in playback widget
- implement automatic MyAnimeList episode mapping based on season metadata

### Refactor

- add comprehensive logging instrumentation across UI views and dialogs

## v0.25.0 (2026-06-06)

### Feat

- add MyAnimeList integration for metadata mapping and anime library support
- implement database deletion for series and episodes with UI controls and refined scanner cleanup logic

### Fix

- adds missing sync history on startup toggle to settings dialog

## v0.24.3 (2026-06-05)

### Fix

- add support for Default TV Order episode grouping in manual mapper and scanner
- sanitize dictionary data retrieval with fallback defaults and expand unit test coverage for dialog components.

## v0.24.2 (2026-06-05)

### Fix

- add support for Default TV Order episode grouping in manual mapper and scanner

## v0.24.1 (2026-06-05)

### Refactor

- replace rename preview table with a hierarchical tree view and add support for selective episode renaming

## v0.24.0 (2026-06-05)

### Feat

- add configurable VLC buffer size settings to optimize playback performance

## v0.23.1 (2026-06-04)

### Fix

- **dev-dependency**: bump commitizen from 4.16.2 to 4.16.3
- **dev-dependency**: bump ruff from 0.15.14 to 0.15.15

### Refactor

- rename Scan & Update action to Scan Library throughout the UI and documentation
- remove CleanupAllLibrariesWorker and associated UI functionality

## v0.23.0 (2026-06-03)

### Feat

- add TMDB episode group mapping support with UI dialog and metadata persistence
- adds support for alternate TMDB episode display groups in series detail view as well as handling for series that use absolute ordering

## v0.22.3 (2026-06-02)

### Fix

- fixes Next Up sort bug in combined view, exclude placeholder episodes from library queries, and improve logging

## v0.22.2 (2026-06-02)

### Fix

- add persistent per-series preference to toggle visibility of missing and future episodes

## v0.22.1 (2026-06-02)

### Fix

- update library cleanup to nullify missing episode paths instead of deleting records and implement forced TMDB metadata refresh

## v0.22.0 (2026-06-02)

### Feat

- make future episode placeholders configurable per library and update UI
- show missing/future episodes in season view with robust date validation and a highly-compatible lozenge icon

## v0.21.2 (2026-05-31)

### Fix

- **player**: replace player back button with stop button next to play & fix details cell background

## v0.21.1 (2026-05-31)

### Refactor

- **playback**: update player widget controls and layout

## v0.21.0 (2026-05-31)

### Feat

- **playback**: align controls, toggle next/prev on movies, restore playback speed, and update skip symbols

## v0.20.1 (2026-05-30)

### Fix

- **scanner**: auto-resolve ffprobe path with caching/logging and add tests

## v0.20.0 (2026-05-30)

### Feat

- **ui**: implement library scan order and fix progress bar segment ordering

### Refactor

- Restructure codebase to sub-packages and update absolute imports (Option B)

## v0.19.0 (2026-05-28)

### Feat

- extract and store technical video metadata (codec, audio tracks, subtitles) during video runtime extraction

### Fix

- **dependency**: bump sqlalchemy from 2.0.49 to 2.0.50
- **ui**: prevent view transitions/jumps during or after scans

## v0.18.2 (2026-05-27)

### Fix

- **dependency**: bump idna from 3.13 to 3.15
- **ui**: adds Scan New Files button to combined view
- **logging**: resolves bug where alembic overrode logging config

### Refactor

- **ui**: re-order settings tabs

## v0.18.1 (2026-05-26)

### Fix

- **executables**: fix missed alembic migrations in executables

## v0.18.0 (2026-05-26)

### Feat

- **ui,scanner**: display progress bar on libraray view when scanning library and refreshing metadata
- **ui**: hide sort and order dropdowns in Combined View
- **ui**: add bidirectional sort order with contextual labels
- **ui**: add next up sorting to library grid
- **ui**: add combined library view and settings
- **config**: add combined view and sort direction settings
- **db**: add combined view query functions
- **db**: add last_played_at column to episodes and movies

### Fix

- **dev-dependency**: bump ruff from 0.15.13 to 0.15.14
- **dev-dependency**: bump types-requests
- **player**: make next playing popup window configurable in settings
- **player**: moves next playing popup to bottom right corner and adds countdown/dismissal behavior

### Refactor

- improve efficiency in order selector and combined views

## v0.17.0 (2026-05-22)

### Feat

- implement real-time segmented progress bar and collapsible scan tree dashboard
- implement database metadata locking and manual refresh TMDB optimization
- **settings**: reorganize advanced settings, implement days-based retention, and add validation warning
- **logging**: add export logs to ZIP in home directory
- **entrypoint**: improve environment variable and startup logging
- **ui**: adds a play next video popup when a video being watched hits 95%
- **ui**: adds real time log viewing tab to settings

### Fix

- ignore folders in season folders and log warnings for them
- add debug logging for unindexed files and warnings for deeply nested season files
- log warning when video files are detected outside season or specials/extras folders
- **settings**: group advanced settings into database, log, and config sections
- **logging**: implement comprehensive diagnostic logging across services
- **scanner**: report unavailable root directories during scan

### Perf

- skip empty library folders and optimize TV season metadata TMDB query efficiency

## v0.16.5 (2026-05-20)

### Fix

- **macos**: adds common plugin paths for vlc on mac
- **ui**: displays watched status by text color instead of checkbox
- **dev-dependency**: bump commitizen from 4.16.0 to 4.16.2
- **dependency**: bump requests from 2.34.0 to 2.34.2

### Refactor

- **db**: updates queries to use sqlalchemy 2.0 syntax

## v0.16.4 (2026-05-19)

### Fix

- **build**: generates github release_notes with releases
- **build**: creates a dmg artifact for macos

## v0.16.3 (2026-05-19)

### Fix

- **build**: Fixes executable extension for mac app
- **ui**: handle ui issues found in wayland environments

## v0.16.2 (2026-05-19)

### Fix

- **vlc**: make plugin support for vlc more forgiving
- **linting**: fixes linting errors
- **build**: re-add missing mac app

## v0.16.1 (2026-05-19)

### Fix

- **dependency**: bump pyside6 from 6.11.0 to 6.11.1
- **dev-dependency**: bump ruff from 0.15.12 to 0.15.13
- **release**: updaets release to use v prefix

## v0.16.0 (2026-05-19)

### Fix

- **macos**: updates mac executable to run in windowed mode and have the correct extension

## v0.15.2 (2026-05-19)

### Feat

- **subtitles**: Adds search opensubtitles functionality
- **ui**: Adds season and episode detail view.
- **player**: automatically enables english subtitles
- **library**: adds movie Libraries
- **backup**: adds backup and restore for config and DB
- **ui**: changes UI back to pure PySide6
- **player**: resume video playback
- **ui**: updates UI to use QML
- **renamer**: Adds file renamer
- **player**: adds volume controls
- moved video playback into embedded player rather than launching VLC
- adds library cleanup task to remove references to missing files from DB
- **ui**: splits settings metadata and watch history into multiple dropdowns
- **db**: moves db to sqlalchemy for ORM and Alembic for migrations
- **jellyfin**: adds match to jellyfin optino to sync watch history auto match does not work
- **ui**: adds mark season as watched feature
- **ui**: adds lock metadata checkbox to series view to stop metadata overwrite
- **logging**: update logging to rotate logs daily
- **ui**: display tmdb names for episodes instead of file names
- **ui**: changes Series view from tree to column style
- **tmdb**: use TMDB directly to get metadata and posters instead of jellyfin
- **ui**: makes sort and filter persist across application restarts
- **scanner**: updates application to sync all libraries on startup
- **ui**: uses multithreading to stop application from freezing during library scan
- initial commit

### Fix

- **macos**: handle missing VLC env var
- **dev-dependency**: bump commitizen from 4.15.1 to 4.16.0
- **dev-dependency**: bump types-requests
- **dependency**: bump requests from 2.33.1 to 2.34.0
- **dependency**: bump urllib3 from 2.6.3 to 2.7.0
- **logs**: adds divided logs for opensubtiles,wakelock,ui, and renamer
- **player**: makes cache size configurable
- **player**: fixes bug where controls stayed on screen after pausing
- **scanner**: refresh series metadata after manual match
- **ui,metdata**: adds per episode metadata search
- **ui**: adds makr season/series as watched buttons to series view
- **scanner**: moves runtime calculator into separate process
- **scanner**: updates scanner to calculate runtime for videos
- **UI**: adds runtime and air date to episodes in series view
- **player**: fixes bug where marking a episode as watched would kick you out of the player
- **scanner,jellyfin,tmdb**: removes automaticscanning,syncing,and new file search
- **jellyfin**: splits jellyfin sync from tmdb sync and makes it more clear when a series is not matched on jellyfin
- **logging**: improves logging coverage and makes logging more configurable
- **tmdb**: when metadata for a series is set manually do not overwrite when refreshing library
- **scanner**: fixes bug where series with similar names would be combined
- **ui**: fixed metadata match window
- **player**: handle stuttering
- **player**: fixes embedded vs vlc playback
- **logs**: makes log retention configurable
- **player**: cleanup cached video files and set size limit to video cache
- **player**: handle release exception from wakelock
- **ui**: updates title bar
- **ui**: resize window and buttons to avoid cutoffs
- **ui**: adds missing settings for DB and log location
- **build**: run lint and tests before cutting release
- **ui**: updates UI to open to most recent unwatched season
- **scanner,ui**: adds check for new files button to ui
- **jellyfin**: improves logic around correlating episodes with jellyfin ID's for watch history sync
- **ui**: adds mark series as watched dropdown
- **scanner**: makes file sync non destructive to preserve watch history
- **player**: cleanup and organize fullscreen player controls
- **player**: improvements to quality and adds playback statistics
- **player**: adds on screen controls when in fullscreen
- **player**: adds additional commands to player to fast foward and skip forward and back
- **player**: stops screen from sleeping or dimming while a video is playing
- **player**: improves video quality and allows passing additional arguments via config
- **player**: adds fullscreen
- **player**: return to series page when playback is stopped
- **player**: make playing videos in VLC vs in application a setting
- **player**: handle VLC errors due to architecture mismatch gracefully
- makes db and log location configurable
- **db**: persist watch status when set on lan streamer
- **ui**: fix season sort to be numeric
- **ui**: uses TMDB Series name in the UI
- **scanner,jellyfin**: fixes jellyfin watched sync
- **ui**: cleans up settings drop down
- **db**: update db migration pattern to versioned steps
- **scanner**: fixes merging series sith multiple seasons spread across multiple directories
- **db**: sets DB_VERSION based on application version instead of hardcoding
- **db**: adds database versioning to simplify migration logic
- **db**: adds unique constraints to allow for upsert instead of delete + insert
- **scanner**: improves scan worker lifecycle handling
- **scanner**: ensures that manually matched series are not overwritten on subsequent scans
- **scan**: search improvements and manual series match

### Refactor

- splits larger functions into smaller help function to improve readbility and testability
- **ui,scanner**: improve ui updates during scan
- **jellyfin**: makes batch calls to jellyfin to get metadata instead of individual calls

### Perf

- **db**: db efficeincy updates
