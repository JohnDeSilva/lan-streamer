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
