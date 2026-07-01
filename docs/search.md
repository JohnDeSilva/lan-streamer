# Search Feature Design

## Overview

Add a search button to each tab in the LibraryGridView. Clicking opens a SearchDialog that autocompletes series names as the user types. Searching on a library tab scopes results to that library; searching on the Combined View tab searches all libraries.

## Architecture

### Data Flow

```
User types in QLineEdit
       |
       v
  QTimer (300ms debounce)
       |
       v
  db.search_series_names(query, library_names)
       |
       v
  SQLAlchemy: Series.name.ilike(f'%{query}%')
       |
       v
  Results displayed in QListWidget
       |
       v
  User clicks result
       |
       v
  Dialog emits series_selected(series_name, library_name)
       |
       v
  LibraryGridView handler:
    controller.select_library(library_name)
    controller.select_series(series_name)
```

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│  LibraryGridView                                         │
│  ┌───────────────────────────────────────────────────┐   │
│  │  Toolbar: [Tabs] [Sort...] [Hide]  [Search] [Settings] │
│  └───────────────────────────────────────────────────┘   │
│  ┌───────────────────────────────────────────────────┐   │
│  │  Series Grid / Combined View                       │   │
│  └───────────────────────────────────────────────────┘   │
│                                                           │
│  ┌─ SearchDialog (modal) ─────────────────────────────┐  │
│  │  [Search series...__________________]              │  │
│  │  ┌─────────────────────────────────────────────┐   │  │
│  │  │ 🔍 Series Name 1     (Library: Anime)      │   │  │
│  │  │ 🔍 Series Name 2     (Library: TV)         │   │  │
│  │  │ 🔍 Series Name 3     (Library: Anime)      │   │  │
│  │  └─────────────────────────────────────────────┘   │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Search Query Logic

```sql
SELECT id, name, library_name, poster_path
FROM series
WHERE name ILIKE '%<query>%'
  [AND library_name IN (<library_names>)]
ORDER BY
  CASE
    WHEN name ILIKE '<query>' THEN 0        -- exact match first
    WHEN name ILIKE '<query>%' THEN 1       -- starts with
    ELSE 2                                    -- contains
  END,
  name ASC
LIMIT 50
```

### Search Result Structure

```python
{
    "name": "Attack on Titan",
    "library_name": "Anime",
    "poster_path": "/path/to/poster.jpg",
}
```

## Files Changed

### New Files
- `src/lan_streamer/ui_views/dialogs/search.py` — SearchDialog widget

### Modified Files
- `src/lan_streamer/db/queries_ui.py` — Add `search_series_names()` function
- `src/lan_streamer/db/__init__.py` — Export `search_series_names`
- `src/lan_streamer/ui_views/dialogs/__init__.py` — Export `SearchDialog`
- `src/lan_streamer/ui_views/__init__.py` — Export `SearchDialog` (for proxy/test mocking)
- `src/lan_streamer/ui_views/library_grid.py` — Add search button and open_search_dialog()

### Test Files
- `tests/unit/db/test_search.py` — Tests for search_series_names
- `tests/unit/ui_views/dialogs/test_search.py` — Tests for SearchDialog
- Update `tests/unit/ui_views/test_library_grid.py` — Test search button integration

## Implementation Details

### SearchDialog (`search.py`)

```
class SearchDialog(QDialog):
    series_selected = Signal(str, str)  # series_name, library_name

    def __init__(self, controller, library_name=None, parent=None):
        - self.library_name = library_name (None = all libraries)
        - self.search_input = QLineEdit with placeholder "Search series..."
        - self.results_list = QListWidget
        - self.debounce_timer = QTimer(interval=300, singleShot=True)
        - Setup UI, wire signals

    def _on_text_changed(self):
        - Restart debounce timer
        - Timer fires -> _execute_search()

    def _execute_search(self):
        - Get query text
        - If len(query) >= 2, call db.search_series_names(query, library_names)
        - Clear and repopulate results_list
        - Each item stores (series_name, library_name) in UserRole data

    def _on_item_clicked(self, item):
        - Extract data from item
        - Emit series_selected(series_name, library_name)
        - Accept dialog

Navigation on Enter: _on_item_activated via QListWidget.itemActivated
```

### LibraryGridView Changes

Add search button to both toolbar areas:
- Single library toolbar: before Settings button
- Combined view toolbar: at the right

```python
search_button = QPushButton("Search")
search_button.clicked.connect(self._open_search_dialog)

@Slot()
def _open_search_dialog(self):
    library_name = None
    if self.controller.current_library_name != "Combined View":
        library_name = self.controller.current_library_name

    dialog = SearchDialog(self.controller, library_name, self)
    dialog.series_selected.connect(self._on_search_result_selected)
    dialog.exec()

@Slot(str, str)
def _on_search_result_selected(self, series_name, library_name):
    if library_name:
        self.controller.current_library_name = library_name
        self.controller.select_library(library_name)
        self.controller.select_series(series_name)
```

## Event Sequence

```
1. User clicks "Search" button on Anime tab
2. LibraryGridView._open_search_dialog() creates SearchDialog(library_name="Anime")
3. User types "Attack"
4. QTimer fires after 300ms
5. SearchDialog._execute_search() calls db.search_series_names("Attack", ["Anime"])
6. DB returns 3 matching series
7. Results list populates with series names
8. User clicks "Attack on Titan"
9. Dialog emits series_selected("Attack on Titan", "Anime")
10. Dialog closes
11. LibraryGridView navigates to Attack on Titan detail view
```

## Testing Strategy

### DB Tests (`test_search.py`)
- Test search returns exact matches first
- Test search filters by library_names
- Test search with empty query returns empty list
- Test search with no matches returns empty list
- Test search is case-insensitive
- Test search with None library_names searches all libraries

### Dialog Tests (`test_search.py` in dialogs)
- Test dialog opens with correct title
- Test typing triggers debounced search
- Test clicking result emits series_selected signal
- Test library_name is passed correctly from grid

### LibraryGrid Tests (`test_library_grid.py`)
- Test search button exists in toolbar
- Test search button opens dialog
- Test dialog gets correct library_name from current tab
