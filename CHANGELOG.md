## 0.11.2 (2026-05-12)

### Fix

- **player**: fixes embedded vs vlc playback

## 0.11.1 (2026-05-12)

### Fix

- **logs**: makes log retention configurable

## 0.11.0 (2026-05-12)

### Feat

- **player**: resume video playback

### Fix

- **player**: cleanup cached video files and set size limit to video cache
- **player**: handle release exception from wakelock
- **ui**: updates title bar

## 0.10.0 (2026-05-12)

### Feat

- **ui**: updates UI to use QML

### Fix

- **ui**: resize window and buttons to avoid cutoffs
- **ui**: adds missing settings for DB and log location

## 0.9.0 (2026-05-11)

### Feat

- **renamer**: Adds file renamer

### Fix

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

## 0.8.0 (2026-05-09)

### Feat

- **player**: adds volume controls

## 0.7.2 (2026-05-08)

### Fix

- **player**: adds fullscreen
- **player**: return to series page when playback is stopped
- **player**: make playing videos in VLC vs in application a setting

## 0.7.1 (2026-05-08)

### Fix

- **player**: handle VLC errors due to architecture mismatch gracefully

## 0.7.0 (2026-05-08)

### Feat

- moved video playback into embedded player rather than launching VLC

## 0.6.0 (2026-05-08)

### Feat

- adds library cleanup task to remove references to missing files from DB
- **ui**: splits settings metadata and watch history into multiple dropdowns
- **db**: moves db to sqlalchemy for ORM and Alembic for migrations

### Fix

- makes db and log location configurable

## 0.5.1 (2026-05-08)

### Fix

- **db**: persist watch status when set on lan streamer

## 0.5.0 (2026-05-08)

### Feat

- **jellyfin**: adds match to jellyfin optino to sync watch history auto match does not work
- **ui**: adds mark season as watched feature

### Fix

- **ui**: fix season sort to be numeric

### Refactor

- **ui,scanner**: improve ui updates during scan

### Perf

- **db**: db efficeincy updates

## 0.4.1 (2026-05-07)

### Fix

- **ui**: uses TMDB Series name in the UI
- **scanner,jellyfin**: fixes jellyfin watched sync

## 0.4.0 (2026-05-07)

### Feat

- **ui**: adds lock metadata checkbox to series view to stop metadata overwrite
- **logging**: update logging to rotate logs daily
- **ui**: display tmdb names for episodes instead of file names
- **ui**: changes Series view from tree to column style
- **tmdb**: use TMDB directly to get metadata and posters instead of jellyfin
- **ui**: makes sort and filter persist across application restarts
- **scanner**: updates application to sync all libraries on startup

### Fix

- **ui**: cleans up settings drop down
- **db**: update db migration pattern to versioned steps

## 0.3.1 (2026-05-06)

### Fix

- **scanner**: fixes merging series sith multiple seasons spread across multiple directories

## 0.3.0 (2026-05-06)

### Feat

- **ui**: uses multithreading to stop application from freezing during library scan

### Fix

- **db**: sets DB_VERSION based on application version instead of hardcoding
- **db**: adds database versioning to simplify migration logic
- **db**: adds unique constraints to allow for upsert instead of delete + insert
- **scanner**: improves scan worker lifecycle handling

### Refactor

- **jellyfin**: makes batch calls to jellyfin to get metadata instead of individual calls

## 0.2.1 (2026-05-06)

### Fix

- **scanner**: ensures that manually matched series are not overwritten on subsequent scans
- **scan**: search improvements and manual series match

## 0.2.0 (2026-05-06)

### Feat

- initial commit
