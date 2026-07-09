# Season Detail Redesign

## Motivation

The original `SeasonDetailView` was a simple page that:
- Queried the database directly (no controller reference)
- Displayed a 4-column episode table (#, Title, Air Date, Runtime)
- Had a cast section showing series-level cast
- Showed "Series: {name}" under the poster
- Had no progress bars, no details buttons, no watched/unwatched styling
- Did not support TMDB display group re-ordering
- Was inconsistent with the SeriesDetailView's episode table

The redesign aligns the season detail page with the SeriesDetailView pattern and streamlines the experience.

## Changes Made

### 1. Controller Integration (`season_detail.py`)

**Before:** `SeasonDetailView()` - no controller, queried DB directly
**After:** `SeasonDetailView(controller_instance: Controller)` - reads from `controller.cached_library_data`

This ensures:
- Consistent data source with SeriesDetailView
- Watched status is available (it's not in the raw DB model directly)
- Display group preferences can be read
- No direct DB queries in the view layer

### 2. Episode Table Redesign

**Before:** 4 columns without interactivity:
| # | Title | Air Date | Runtime |

**After:** 6 columns matching SeriesDetailView:
| # | Episode Title | Air Date | Runtime | Progress | Details |

Key features:
- **Progress bars** (column 4): `QProgressBar` showing 0-100%, 100% for watched, calculated from `last_played_position` for partial
- **Details buttons** (column 5): "..." button opens `EpisodeDetailsDialog` via `episode_details_requested` signal
- **Color coding**:
  - Watched: gray (`#888888`) with checkmark (✓)
  - Unwatched available: blue (`#0e5296`) with dot (●)
  - Missing (aired past but no file): red (`#ef4444`) with X (✕)
  - Future (not yet aired): purple (`#a78bfa`) with lozenge (◊)
- **Title click to play**: Clicking the title column plays the episode
- **Context menu**: Right-click for "Mark as Watched/Unwatched" and "Remove Episode"

### 3. Cast Section Removal

The cast section (`_display_cast`, `_cast_scroll`, `_cast_grid`, `cast_member_clicked` signal) was removed because:
- The season detail page is focused on episode browsing, not cast browsing
- Cast is already available in the SeriesDetailView
- Simplifies the view and removes duplicate navigation paths

### 4. Season Summary Overhaul

**Before:**
- `_series_label`: "Series: {name}"
- `_episode_count_label`: "{n} episodes"

**After:**
- Season overview/summary text displayed under the poster
- Fetches from season metadata if available
- Falls back to TMDB API (`get_season_details`) if not cached
- Falls back to series overview if no season overview is available

### 5. TMDB Display Group Support

The season detail view now respects the series' `display_group_id` preference:

1. Reads `pref_display_group_id` from `config.get_series_preference()`
2. If a non-default group is set, fetches `tmdb_client.get_episode_group_details()`
3. Re-orders episodes using `_build_order_map()` which matches by `tmdb_episode_identifier` or `tmdb_number`
4. Season-only display — only shows episodes belonging to the current season after regrouping

### 6. Mark Season Watched/Unwatched

Added a toggle button that marks all local episodes in the season as watched or unwatched, matching the SeriesDetailView behavior.

### 7. TMDB `get_season_details()` Addition

Added a new method to both `TMDBClient` (sync) and `AsyncTMDBClient` (async):

```python
def get_season_details(self, tmdb_identifier, season_num) -> dict | None:
```

This fetches the full TMDB season response including `overview`, `name`, `air_date`, `poster_path`, `episodes`, etc. Previously only `get_episodes()` existed which discarded season-level data.

Also added `get_season_details` to `TMDBClientProtocol` in `controller.py`.

## Data Flow

```
SeasonDetailView.display_season(series_name, season_name)
  │
  ├─ controller.cached_library_data[series_name]
  │    ├─ metadata (series-level)
  │    └─ seasons[season_name]
  │         ├─ metadata (season-level)
  │         │    └─ overview? → display as season summary
  │         │    └─ (if no overview) → tmdb_client.get_season_details()
  │         └─ episodes[] → display in table
  │
  ├─ config.get_series_preference("display_group_id")
  │    └─ if non-default → tmdb_client.get_episode_group_details()
  │    └─ re-order episodes
  │
  └─ _build_episode_table(episodes)
       ├─ Sort by tmdb_number (default) or group order
       ├─ For each episode:
       │    ├─ Determine color/icon based on:
       │    │    ├─ path exists? → watched? (gray ✓) or unwatched (blue ●)
       │    │    └─ no path? → aired past? (red ✕) or future (purple ◊)
       │    ├─ Progress bar from last_played_position
       │    └─ Details button → episode_details_requested signal
       └─ Context menu on right-click
```

## Files Changed

| File | Change |
|------|--------|
| `src/lan_streamer/ui_views/season_detail.py` | Complete rewrite |
| `src/lan_streamer/main.py` | Pass controller to SeasonDetailView; remove cast_member_clicked wiring |
| `src/lan_streamer/providers/tmdb.py` | Added `get_season_details()` method |
| `src/lan_streamer/providers/tmdb_async.py` | Added async `get_season_details()` method |
| `src/lan_streamer/ui_views/controller.py` | Added `get_season_details` to TMDBClientProtocol |
| `tests/unit/ui_views/test_season_detail.py` | Rewritten with 6 tests covering all features |
| `tests/unit/ui_views/dialogs/test_poster_selector.py` | Updated to pass controller to SeasonDetailView |
| `AGENTS.md` | Updated SeasonDetailView section |

## Stack Layout Indices (Unchanged)

- 0: LibraryGridView
- 1: SeriesDetailView
- 2: MovieDetailView
- 3: SeasonDetailView
- 4: CastDetailView
- 5: VideoPlayerWidget (Player)

## SeasonDetailView Signals

| Signal | Signature | Purpose |
|--------|-----------|---------|
| `back_requested` | `()` | Navigate back to series detail |
| `episode_details_requested` | `(str, str)` | Open episode details dialog (series_name, episode_path) |

## Future Considerations

- The season overview could be persisted to the `Season` model and populated during scans (Pass 2) to avoid on-the-fly API calls
- Season-level cast could be added back in a future iteration if needed
- Poster selector dialog works unchanged (was preserved from original)
