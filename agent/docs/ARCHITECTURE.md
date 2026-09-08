# LAN Streamer — Remote Scan Agent Architecture & Plan

Status: **Phase 1 Complete (Agent MVP)** · Updated: 2026-09-07

This document lays out the end-state architecture, the phased plan to get there,
and the reasoning behind every major decision. It is the contract the subagents
build against.

---

## 1. Context & Goals

Lan-streamer is today a monolithic PySide6 desktop app: it scans local media,
resolves TMDB metadata, probes files with ffprobe, downloads subtitles, renames
files, streams via VLC, tracks watch history, and syncs to Jellyfin / MyAnimeList.

The user wants to split this into two components:

- **A remote Scan Agent** (this repo, `agent/`) that lives next to the media
  storage in a Docker container. It owns **scanning, metadata resolution,
  subtitle management, file renaming, and ffprobe technical probing**, and is
  managed through a **web interface**.
- **The Desktop client** shrinks to be a thin streaming + watch-history client
  that reads library data and tells the agent what to watch.

The streaming model does **not** change: the desktop keeps playing via local
file paths, reached over **SMB/NFS mounts** (decided at the kickoff Q&A). The
agent ensures files exist at predictable paths and exposes metadata; the desktop
mounts the same share and plays directly.

> Why split at all? The scan/metadata pipeline is the heaviest, most network/
> IO-bound part of the app and runs poorly on the desktop machine (which may be
> sleeping, on Wi-Fi, or far from the storage). Running it beside the storage
> removes the bottleneck and centralizes one source of truth for the library.

---

## 2. Decisions (from kickoff) with rationale

| Decision | Choice | Rationale |
|---|---|---|
| Streaming | Keep local file paths over SMB/NFS mounts | Zero change to the VLC playback engine today; agent only guarantees filesystem layout. Follow-up phase can add HTTP range streaming later. |
| Agent location | New top-level `agent/` dir in this monorepo | Shared scanner/providers code is reused without a second repo; one build/test/Makefile story. |
| Watch-history sync | Agent owns the DB; desktop POSTs watch events to the agent REST API | Single source of truth; the client becomes stateless for library data. |
| Phase 1 scope | Agent + web UI MVP only (no desktop changes) | Matches "build the agent first, then deprecate desktop features". Lower risk, incremental. |
| Agent language | Python (FastAPI) backend; static JS web UI | Same language as the scan pipeline we reuse; FastAPI gives typed REST + OpenAPI + SSE for free. JS frontend is build-tool-free vanilla for the MVP. |

---

## 3. Reading of the current codebase (Phase 0 findings)

Measured: ~39k LOC source, ~66k LOC tests.

### 3.1 The scan pipeline is already reusable

`scanner/core.py::scan_directories()` runs the battle-tested 3-pass pipeline and
is **pure dict-in/dict-out**:

- Identifies data purely via `dict[str, Any]` (series/movie dicts, `seasons`,
  `episodes`, `versions`) and callbacks (`detail_callback`, `season_callback`,
  `movie_callback`, `is_interrupted`).
- Pass 1 (`pass1_file_discovery`) walks the FS, no TMDB.
- Pass 2 (`pass2_metadata`) resolves TMDB metadata, no FS walk.
- Pass 3 (`pass3_technical`) batch-ffprobes and cleans missing files.

Reusable helpers: `parser.py`, `renamer.py`, `file_property_scanner.py`,
`versioning.py`, and `services/metadata_{series,episode,movie,common,updates}.py`,
`services/file_discovery.py`.

### 3.2 Verified coupling points (what the agent must supply or avoid)

None of the scanner pipeline, reusable services, or `providers/tmdb.py` import
Qt. The coupling risks are:

1. **Global config singleton** — `providers/*` and `scanner/core.py` read
   `lan_streamer.system.config.config.<key>` at runtime for
   `tmdb_api_key`, OpenSubtitles creds, `scan_concurrency`, cache dirs, etc.
   The singleton is created at import time (`config = Config()` at
   `system/config.py:477`). **Strategy:** the agent builds its own config object
   with the same attribute names and installs it onto
   `lan_streamer.system.config.config` at startup, before any provider import.
   No desktop change required.
2. **DB-coupled services** — `services/metadata_cast.py`,
   `services/metadata_images.py`, and `services/smart_row_service.py` import
   `lan_streamer.db.*` (session/models/queries). **Strategy:** do NOT reuse in
   the agent's MVP; cast/image-populate is deferred (Phase 2 of the agent).
3. **`db.utils.natural_sort_key`** — imported by `pass2_metadata.py` and
   `metadata_updates.py`. Pure helper; verify it is Qt/DB-free and reuse as-is;
   if it drags in DB imports, vendor a copy in the agent.
4. **Provider cache paths** — `providers/tmdb.py` hardcodes
   `Path.home()/.config/lan-streamer/cache/images`. Acceptable in the container
   (set `HOME`); the agent config should allow overriding `cache_directory`.
5. **`get_scan_executor()`** with no arg defaults `scan_concurrency` from the
   config singleton — works once strategy (1) is in place.

Implication: **the agent does not touch the desktop source** in Phase 1 except
for *read-only* reuse over `PYTHONPATH`. Extraction/migration of the scanner
into the agent package (and later removal from the desktop) is a later phase.

---

## 4. Target architecture

```
┌───────────────┐   mounts SMB/NFS   ┌──────────────────────────────┐
│ Desktop app   │───────────────────▶│  Remote storage (agent host)  │
│ (stream/watch │   local file path  │  media/<library>/...          │
│  history/sync)│◀───────────────────┘                              │
└───────┬───────┘                     ┌──────────────────────────────┐
        │ REST + SSE (localhost or LAN)│  Scan Agent (Docker)        │
        └─────────────────────────────▶│  FastAPI + SQLite           │
                                       │  reusable scan pipeline     │
                                       │  web UI (static JS)         │
                                       └──────────────────────────────┘
```

### 4.1 Component responsibilities

| Capability | Owner (target) | Agent now? |
|---|---|---|
| FS crawling (pass 1) | Agent | ✅ (reuse) |
| TMDB metadata (pass 2) | Agent | ✅ (reuse) |
| ffprobe (pass 3) | Agent | ✅ (reuse) |
| Subtitle download/manage | Agent | ✅ (MVP: scan list; download endpoint) |
| Rename preview/apply | Agent | ✅ (reuse `renamer.py`) |
| Poster/backdrop images | Agent | ⏭ Phase 2 (DB-coupled service) |
| Cast & crew | Agent | ⏭ Phase 2 (DB-coupled service) |
| Library browser data | Agent (DB) + desktop reads via REST | ✅ (agent DB + REST) |
| Watch history / resume | Agent DB via REST POST | ✅ schema + endpoints (minimal) |
| Jellyfin / MAL sync | Desktop (outbound) | desktop stays |
| Playback | Desktop | desktop stays |

### 4.2 New agent package

```
agent/
  pyproject.toml            # fastapi, uvicorn, sqlalchemy, pydantic; reuses ../src via PYTHONPATH
  Dockerfile                # slim python:3.14, uv, ffprobe/ffmpeg, VLC not needed
  docker-compose.yml
  Makefile
  docs/
    ARCHITECTURE.md         # this file
  src/scan_agent/
    __init__.py
    main.py                 # FastAPI app factory + static mount
    config.py               # agent config (JSON file + env), installs lan_streamer config singleton
    logging_setup.py
    db/
      models.py             # SQLAlchemy 2.0 ORM, own agent schema (below)
      connection.py
      repository.py         # serialize scanner dicts ⇄ ORM rows
    scan/
      orchestrator.py       # wraps scanner.scan_directories for a library
      progress.py           # thread-safe progress/log broker → SSE
      task_queue.py         # background scan job management (single worker)
    api/
      routes_health.py
      routes_libraries.py
      routes_scan.py        # start/status/cancel + SSE events
      routes_library.py     # browse series/movies/episodes
      routes_metadata.py    # TMDB search + manual match apply
      routes_rename.py      # preview + apply
      routes_subtitles.py
      routes_config.py
    static/                 # vanilla JS SPA served by FastAPI
      index.html
      app.js  style.css  api.js
  tests/
    unit/      # models, config, repository, orchestrator (mocked TMDB)
    integration/  # API via TestClient + tmp sqlite, mocked TMDB/subtitles
```

### 4.3 Agent DB schema (SQLAlchemy 2.0, own models)

Kept intentionally lean; the desktop dict shape maps 1:1.

- `Library` (id, name, media_type tv|anime|movie, root_path, enabled, sort_order)
- `Series` (id, library_id FK, folder_name, name, overview, poster_path,
  backdrop_path, tmdb_identifier, year, status, air_date_first, air_date_last,
  locked_metadata bool, last_modified, date_added, watched_count, path)
- `Season` (id, series_id FK, season_number, name, overview, poster_path,
  tmdb_identifier, air_date, watched_episode_count, episode_count)
- `Episode` (id, season_id FK, episode_number, tmdb_number, name, overview,
  path, runtime_seconds, air_date, is_missing bool, watched bool,
  last_played_at, resume_position_seconds)
- `Movie` (id, library_id FK, folder_name, name, overview, poster_path,
  backdrop_path, tmdb_identifier, year, runtime_seconds, path,
  locked_metadata bool, last_modified, date_added, watched bool,
  last_played_at, resume_position_seconds)
- `MediaFile` (id, media_type, media_id, path, size_bytes, duration_seconds,
  codec, resolution, container, active bool) — one row per version.
- `Subtitle` (id, media_type, media_id, path, language, forced bool,
  default bool, provider, downloaded_at)
- `ScanJob` (id, library_id FK nullable, pass_number, status
  pending|running|cancelled|done|error, started_at, finished_at, stats_json,
  error_text)
- `WatchEvent` (id, media_type, media_id, event play|stop|complete,
  position_seconds, client_id, timestamp) — foundation for desktop sync.

> **Migration discipline:** the desktop project pins Alembic revision versions to
> the app version. The agent DB is a *separate* database; it gets its own simple
> Alembic environment under `agent/` OR a `SchemaVersion` row applied on boot for
> the MVP. Prefer a simple `SchemaVersion` table + idempotent DDL in Phase 1,
> promote to Alembic when the schema is stable.

### 4.4 REST API (v1, prefixed `/api/v1`)

Health/config:
- `GET /api/v1/health`
- `GET|PUT /api/v1/config`

Libraries:
- `GET /api/v1/libraries`
- `POST /api/v1/libraries` (name, media_type, root_path)
- `PATCH /api/v1/libraries/{library_id}`
- `DELETE /api/v1/libraries/{library_id}`

Scanning:
- `POST /api/v1/scan` (`{library_id?|all, pass_number, force_refresh}`)
- `GET /api/v1/scan/status`
- `POST /api/v1/scan/cancel`
- `GET /api/v1/events` (SSE: `scan.progress`, `scan.log`, `scan.finished`)
- `GET /api/v1/scan/jobs`

Library browser:
- `GET /api/v1/library/series?library_id=&query=&sort=`
- `GET /api/v1/library/series/{series_id}` (+ seasons/episodes nested)
- `GET /api/v1/library/series/{series_id}/episodes`
- `GET /api/v1/library/movies?library_id=&query=&sort=`
- `GET /api/v1/library/movie/{movie_id}`

Metadata (manual match):
- `GET /api/v1/metadata/search?query=&media_type=tv|movie`
- `POST /api/v1/metadata/series/{series_id}/match` `{tmdb_identifier}`
- `POST /api/v1/metadata/movie/{movie_id}/match` `{tmdb_identifier}`

Renaming:
- `POST /api/v1/rename/preview` `{media_type, media_id}`
- `POST /api/v1/rename/apply` `{media_type, media_id}`

Subtitles:
- `GET /api/v1/subtitles?media_type=&media_id=`
- `POST /api/v1/subtitles/download` `{media_type, media_id, language}`

Watch state (foundation for desktop sync):
- `GET /api/v1/watch/{media_type}/{media_id}`
- `POST /api/v1/watch` `{media_type, media_id, event, position_seconds, client_id}`

Images / Artwork:
- `GET /api/v1/images/poster?path=` (serves poster artwork from agent filesystem or cache directory)

### 4.5 Web UI (static vanilla JS SPA)

Pages (nav tabs; single `app.js` + `api.js` + `style.css`):
1. **Dashboard** — health, last scan status/job, counts per library.
2. **Libraries** — add/edit/remove roots with interactive server filesystem folder picker, trigger scan per library.
3. **Scan** — full scan control, SSE live progress + log tail.
4. **Browse** — series & movie lists, detail views (seasons/episodes, files,
   metadata match/refresh, subtitles, rename preview/apply).
5. **Config** — TMDB key, OpenSubtitles creds, scan concurrency, cache dir.

Interactive Folder Browser:
- Library creation/edit modal includes a "📁 Browse..." button opening a folder browser dialog (`#folderBrowserModal`).
- Driven by `GET /api/v1/filesystem/browse?path=...`, allowing navigation into directories, selecting storage folders, and quick-jumping via common mount roots (`/media`, `/data`, `/mnt`, etc.).

Data Directory Layout:
All agent runtime state is colocated inside a single unified data directory (`/data` in Docker, `agent/data` or `$SCAN_AGENT_DATA` on host):
- `<data>/config.json`: Agent configuration.
- `<data>/library.db`: SQLite database and write-ahead logs.
- `<data>/cache/`: Provider caches (e.g. `images/` and `people/` redirected from desktop providers).
- `<data>/logs/`: Scan agent logs.

No build tooling — served directly by FastAPI `StaticFiles`. This is the MVP
choice for a maintenance-light UI; a framework migration is trivial later.

### 4.6 Docker

`agent/Dockerfile`: `python:3.14-slim` + `uv` + `ffmpeg` (for ffprobe). Mounts:
`/media` (read-only roots), `/data` (config + DB). Image runs `uvicorn`.

`docker-compose.yml`: service `scan-agent`, volumes, env (`TMDB_API_KEY`,
`HOME=/data`), healthcheck on `/api/v1/health`.

---

## 5. Reuse strategy (the "don't reinvent" boundary)

**Reuse as-is (read-only) via `PYTHONPATH=../src`:**
`lan_streamer.scanner.*`, `lan_streamer.services.metadata_*` (DB-free ones),
`lan_streamer.services.file_discovery`, `lan_streamer.providers.tmdb`,
`lan_streamer.providers.opensubtitles{,_async}`.

**Do NOT reuse:** `lan_streamer.db.*` (agent has own models), all of
`ui_views/`, `backend/` Qt workers, `system/` desktop config/backup/updater,
`providers/jellyfin*`, `providers/myanimelist*` (stay on desktop for now),
`services/metadata_cast.py`, `services/metadata_images.py`,
`services/smart_row_service.py`.

**Config bridging (root cause of the whole strategy):**
1. Agent reads its JSON config (`/data/config.json`) into an agent `Config` with
   the same attribute names the providers expect: `tmdb_api_key`,
   `opensubtitles_username`, `opensubtitles_api_key`,
   `opensubtitles_user_agent`, `scan_concurrency`, `cache_directory`, …
2. At agent startup (`main.py`), do
   `import lan_streamer.system.config as lsc; lsc.config = agent_config` ***before***
   importing any provider/scanner module.
3. Set `HOME` to the agent data dir so provider `Path.home()` caches land inside
   the container mount.

This keeps the desktop code byte-for-byte untouched in Phase 1.

---

## 6. Desktop deprecation roadmap (post-MVP, NOT in Phase 1)

Order matters — the desktop must remain fully functional each step:

1. **Phase A (Local vs Remote Library Architecture & Read-Only Adoption):**
   - **Library `management_type`**: Each library configured on the desktop is explicitly designated as `"local"` (managed and scanned by the desktop filesystem scanner) or `"remote"` (managed by an agent). Existing libraries default to `"local"`.
   - **Multiple Scan Agents**: Desktop Settings ("Remote API's" tab) allows configuring 1 or more Scan Agent URLs, testing connectivity (`GET /api/v1/health`), and querying remote libraries (`GET /api/v1/libraries`).
   - **Path & Mount Point Mapping**: Remote libraries keep local mount paths (`paths` in SMB/NFS mount points) so local VLC playback continues without changing the streaming model.
   - **Decoupled Local Scanning**: Desktop scanner (`ScanAllLibrariesWorker`) skips local filesystem walks on remote libraries, preventing spurious inotify alerts and redundant local scans.
2. **Phase B (agent-authoritative scan):** Desktop defers all scans to the agent;
   local `scanner/` removed from the desktop path.
3. **Phase C (stream via agent):** optional HTTP range streaming from the agent
   (kept behind a config toggle) so SMB mounts are no longer required.
4. **Phase D (watch + sync on agent):** desktop POSTs watch events to the agent;
   agent syncs Jellyfin/MAL centrally; desktop drops those providers.
5. **Phase E (extraction):** move chosen `lan_streamer.Scanner*` modules into
   the `agent` package wholesale and delete from the desktop build (shrinks the
   PyInstaller artifact, drops Qt + VLC deps from the agent entirely).

Each phase re-runs the full 90% coverage suite on both sides and updates the
README/AGENTS.md docs.

---

## 7. Execution plan (Phase 1 — agent MVP)

Guided by AGENTS.md: **test-first** per feature, **verify
`make test` + `make lint`** after every change, update docs, commit with
Conventional Commits.

Ordered, each step run by a focused subagent (consumed only their summaries to
protect the driver context):

1. [DONE] Audit reuse surface (this doc's Section 3).
2. **Scaffold + backend core**
   - `agent/pyproject.toml` (FastAPI/uvicorn/SQLAlchemy deps; `agent` scripts),
     static mounts, config + logging, DB models/connection, repository mapping.
   - Wire the config singleton bridging (Section 5.2) and prove `scan_directories`
     import works in a non-Qt process.
   - Tests first: models, repository, config, orchestrator (TMDB fully mocked,
     local tmpdir media, no live URLs per AGENTS.md §8).
3. **Scan orchestration + REST API**
   - `task_queue` (one background scan at a time; job records), progress broker,
     SSE; routes: health, config, libraries, scan, library-browser, metadata
     match/search, rename preview/apply, subtitles, watch.
   - Integration tests via FastAPI `TestClient` against tmp sqlite + local
     media fixtures.
4. **Web UI** — static SPA pages (Section 4.5) wired to the API; minimal unit
   test (page loads, key fetch calls) or manual smoke via TestClient.
5. **Packaging + docs** — Dockerfile, compose, agent `Makefile` targets
   (`agent-test`, `agent-lint`, `agent-run`), `Makefile` top-level hooks, AGENTS.md
   and README updates describing the agent and deprecation plan.
6. **Verification** — agent tests green + coverage ≥90% (scoped to `scan_agent`);
   `make lint` clean across the repo; desktop suite still green (reuse did not
   alter desktop source).

### Phase 1 acceptance criteria

- [x] `uv run python -m scan_agent.serve` / `create_app` boots without Qt; health OK.
- [x] `POST /scan` on a fixture library completes all 3 passes end-to-end (mocked
      TMDB, real ffprobe if available), writing rows into agent SQLite.
- [x] SSE streams progress/log; web UI shows live scan + library browse + config.
- [x] Manual TMDB match + rename preview/apply + subtitle listing work over API.
- [x] Desktop `make test` and `make lint` remain green (untouched source).
- [x] New agent docs (this doc + README/AGENTS.md) are synced.

---

## 8. Key risks & mitigations

| Risk | Mitigation |
|---|---|
| `lan_streamer.*` global state mutates at import (config singleton) | Agent bridges config before imports; never mutates desktop code; proves with a headless import test. |
| `get_scan_executor` reads desktop config lazily | Config bridge covers it; executor created with agent `scan_concurrency`. |
| ffprobe missing in container | Dockerfile installs `ffmpeg`; pass 3 logs and continues non-fatally (desktop already tolerates). |
| DB-coupled services (`metadata_cast/images`) needed by users early | Explicitly deferred; search/match/browse still fully functional without them. |
| Vanilla JS UI grows unmaintainable | Small by design; swap for a framework later without API changes (API is the stable contract). |
| Coverage hard to hit on SSE/threaded code | Keep brokers testable: pure progress broker class with injected callbacks; TestClient with `anyio` supports SSE. |
| Desktop co-existence during deprecation | Desktop source untouched in Phase 1; later phases keep desktop functional at each step. |

---

## 9. Out of scope (Phase 1)

- Any change to the desktop app source or its build.
- HTTP range streaming from the agent (Phase C).
- Jellyfin / MyAnimeList sync from the agent.
- Cast & crew / poster-image population.
- Auth on the agent API/UI (LAN-only initially; add token auth in a follow-up).
- Alembic for the agent DB (SchemaVersion table for MVP).
- Multi-host agent fleet / clustering.

---

## 10. Immediate next actions

1. Dispatch backend-core subagent (Section 7.2) to scaffold `agent/` package,
   prove the config bridge + `scan_directories` reuse headlessly, and build
   models/repository with tests.
2. After backend contract is proven, dispatch API+orchestration subagent.
3. Then web-UI subagent; then packaging/docs subagent.
4. Final verification run (coverage + lint) before commit.
