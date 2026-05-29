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
