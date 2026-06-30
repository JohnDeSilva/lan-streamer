import pytest
from unittest.mock import patch

from lan_streamer import db


@pytest.fixture
def _isolated_db(tmp_path):
    """Isolate DB test to a temp file so it never touches production data."""
    import lan_streamer.db as db_mod

    db_file = tmp_path / "test_new_episodes.db"
    with patch.object(db_mod, "DB_FILE", db_file):
        old_engine = db_mod._engine
        if old_engine is not None:
            old_engine.dispose()
        db_mod._engine = None
        db_mod._SessionLocal = None
        db_mod._db_initialized = False
        db_mod.init_db()
        yield
        if db_mod._engine is not None:
            db_mod._engine.dispose()


def test_placeholder_promotion_resets_watched_status(_isolated_db) -> None:
    # 1. Create a library with a placeholder episode (no path) that is marked as watched
    library_name = "Test TV Library"
    initial_lib = {
        "Test Series": {
            "metadata": {
                "jellyfin_id": "series123",
                "poster_path": "/img.jpg",
                "overview": "A test series",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "metadata": {"jellyfin_id": "season123", "poster_path": "/s1.jpg"},
                    "episodes": [
                        {
                            "name": "S01E01 - TBA",
                            "path": None,
                            "tmdb_number": 1,
                            "watched": True,
                        }
                    ],
                }
            },
        }
    }

    db.save_library(library_name, initial_lib)

    # Verify that the episode exists, has no path, and is watched
    loaded = db.load_library(library_name)
    episodes = loaded["Test Series"]["seasons"]["Season 1"]["episodes"]
    assert len(episodes) == 1
    assert episodes[0]["path"] is None
    assert episodes[0]["watched"] is True

    # 2. Simulate adding a new file for the episode (promoting it to a local path)
    # The new file metadata should have watched = False (as it is a new file)
    updated_lib = {
        "Test Series": {
            "metadata": {
                "jellyfin_id": "series123",
                "poster_path": "/img.jpg",
                "overview": "A test series",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "metadata": {"jellyfin_id": "season123", "poster_path": "/s1.jpg"},
                    "episodes": [
                        {
                            "name": "S01E01 - TBA",
                            "path": "/path/to/S01E01.mkv",
                            "tmdb_number": 1,
                            "watched": False,
                        }
                    ],
                }
            },
        }
    }

    db.save_library(library_name, updated_lib)

    # Verify that the episode now has a path and is unwatched (watched = False)
    loaded_updated = db.load_library(library_name)
    episodes_updated = loaded_updated["Test Series"]["seasons"]["Season 1"]["episodes"]
    assert len(episodes_updated) == 1
    assert episodes_updated[0]["path"] == "/path/to/S01E01.mkv"
    assert episodes_updated[0]["watched"] is False


def test_movie_new_file_resets_watched_status(_isolated_db) -> None:
    from lan_streamer.db.library_movie import save_movie_library, load_movie_library

    library_name = "Test Movie Library"

    # 1. Save movie library with a movie marked as watched
    initial_lib = {
        "Test Movie": {
            "tmdb_identifier": "movie123",
            "path": "/old/path/to/movie.mkv",
            "watched": True,
        }
    }

    save_movie_library(library_name, initial_lib)

    loaded = load_movie_library(library_name)
    assert "Test Movie" in loaded
    assert loaded["Test Movie"]["path"] == "/old/path/to/movie.mkv"
    assert loaded["Test Movie"]["watched"] is True

    # 2. Save again with a different path (a new file), watched = False
    updated_lib = {
        "Test Movie": {
            "tmdb_identifier": "movie123",
            "path": "/new/path/to/movie.mkv",
            "watched": False,
        }
    }

    save_movie_library(library_name, updated_lib)

    loaded_updated = load_movie_library(library_name)
    assert "Test Movie" in loaded_updated
    assert loaded_updated["Test Movie"]["path"] == "/new/path/to/movie.mkv"
    assert loaded_updated["Test Movie"]["watched"] is False
