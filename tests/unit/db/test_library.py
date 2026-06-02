import shutil
from typing import Any
from unittest.mock import patch

import pytest

from lan_streamer import db


@pytest.fixture
def mock_db_file(tmp_path) -> None:
    return tmp_path / "library.db"


def test_save_and_load_library(mock_db_file) -> None:
    test_lib = {
        "Test Series": {
            "metadata": {
                "jellyfin_id": "series123",
                "poster_path": "/img.jpg",
                "overview": "A test series",
                "locked_metadata": True,
            },
            "seasons": {
                "Season 1": {
                    "metadata": {"jellyfin_id": "season123", "poster_path": "/s1.jpg"},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path/to/ep1.mkv",
                            "jellyfin_id": "ep123",
                            "watched": False,
                        }
                    ],
                }
            },
        }
    }

    db.save_library("MyLib", test_lib)

    loaded = db.load_library("MyLib")

    assert "Test Series" in loaded
    series = loaded["Test Series"]
    assert series["metadata"]["jellyfin_id"] == "series123"
    assert series["metadata"]["poster_path"] == "/img.jpg"
    assert series["metadata"]["overview"] == "A test series"
    assert series["metadata"]["locked_metadata"] is True

    assert "Season 1" in series["seasons"]
    season = series["seasons"]["Season 1"]
    assert season["metadata"]["jellyfin_id"] == "season123"

    eps = season["episodes"]
    assert len(eps) == 1
    assert eps[0]["name"] == "Ep 1"
    assert eps[0]["path"] == "/path/to/ep1.mkv"
    assert eps[0]["jellyfin_id"] == "ep123"
    assert eps[0]["watched"] is False


def test_save_library_upsert() -> None:
    library_name = "TestLib"

    # Initial data
    initial_library = {
        "Series 1": {
            "metadata": {"jellyfin_id": "s1", "poster_path": "p1", "overview": "o1"},
            "seasons": {
                "Season 1": {
                    "metadata": {"jellyfin_id": "ss1", "poster_path": "pp1"},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path/1",
                            "jellyfin_id": "e1",
                            "watched": False,
                        }
                    ],
                }
            },
        }
    }

    db.save_library(library_name, initial_library)

    # Verify initial save
    loaded = db.load_library(library_name)
    assert "Series 1" in loaded
    assert loaded["Series 1"]["metadata"]["jellyfin_id"] == "s1"
    assert loaded["Series 1"]["seasons"]["Season 1"]["episodes"][0]["watched"] is False

    # Update data (Upsert)
    updated_library = {
        "Series 1": {
            "metadata": {
                "jellyfin_id": "s1_new",
                "poster_path": "p1_new",
                "overview": "o1_new",
            },
            "seasons": {
                "Season 1": {
                    "metadata": {"jellyfin_id": "ss1_new", "poster_path": "pp1_new"},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path/1",
                            "jellyfin_id": "e1_new",
                            "watched": True,
                        },
                        {
                            "name": "Ep 2",
                            "path": "/path/2",
                            "jellyfin_id": "e2",
                            "watched": False,
                        },
                    ],
                }
            },
        },
        "Series 2": {
            "metadata": {"jellyfin_id": "s2", "poster_path": "p2", "overview": "o2"},
            "seasons": {},
        },
    }

    db.save_library(library_name, updated_library)

    # Verify updates
    loaded = db.load_library(library_name)
    assert len(loaded) == 2
    assert loaded["Series 1"]["metadata"]["jellyfin_id"] == "s1_new"
    assert loaded["Series 1"]["metadata"]["overview"] == "o1_new"
    assert len(loaded["Series 1"]["seasons"]["Season 1"]["episodes"]) == 2
    assert loaded["Series 1"]["seasons"]["Season 1"]["episodes"][0]["watched"] is True
    assert loaded["Series 1"]["seasons"]["Season 1"]["episodes"][1]["name"] == "Ep 2"
    assert "Series 2" in loaded

    # Deletion test
    final_library = {
        "Series 2": {
            "metadata": {"jellyfin_id": "s2", "poster_path": "p2", "overview": "o2"},
            "seasons": {},
        }
    }

    db.save_library(library_name, final_library)
    loaded = db.load_library(library_name)
    assert len(loaded) == 2  # Non-destructive: Series 1 is still there
    assert "Series 1" in loaded
    assert "Series 2" in loaded

    # Now use explicit cleanup
    db.cleanup_library(library_name, [])  # Empty root dirs -> removes everything
    loaded = db.load_library(library_name)
    assert len(loaded) == 0


def test_upsert_preserves_ids_across_libraries() -> None:
    # Verify that upserting one library doesn't affect another
    db.save_library("Lib1", {"Series A": {"metadata": {}, "seasons": {}}})
    db.save_library("Lib2", {"Series A": {"metadata": {}, "seasons": {}}})

    loaded1 = db.load_library("Lib1")
    loaded2 = db.load_library("Lib2")

    assert "Series A" in loaded1
    assert "Series A" in loaded2

    # Update Lib1 (Non-destructive)
    db.save_library("Lib1", {"Series B": {"metadata": {}, "seasons": {}}})

    assert "Series A" in db.load_library("Lib1")  # Preserved
    assert "Series B" in db.load_library("Lib1")
    assert "Series A" in db.load_library("Lib2")


def test_cleanup_library(tmp_path) -> None:
    library_name = "CleanupTest"
    root_dir = tmp_path / "TV"
    root_dir.mkdir()

    # Series 1: Will remain partially intact then fully removed
    series_dir1 = root_dir / "Series 1"
    series_dir1.mkdir()
    season_dir1 = series_dir1 / "Season 1"
    season_dir1.mkdir()
    ep_file1a = season_dir1 / "ep1a.mkv"
    ep_file1a.write_text("dummy")
    ep_file1b = season_dir1 / "ep1b.mkv"
    ep_file1b.write_text("dummy")

    # Series 2: Will be removed by deleting folder
    series_dir2 = root_dir / "Series 2"
    series_dir2.mkdir()
    season_dir2 = series_dir2 / "Season 1"
    season_dir2.mkdir()
    ep_file2 = season_dir2 / "ep2.mkv"
    ep_file2.write_text("dummy")

    initial_library = {
        "Series 1": {
            "metadata": {"jellyfin_id": "s1"},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {"name": "ep1a.mkv", "path": str(ep_file1a.absolute())},
                        {"name": "ep1b.mkv", "path": str(ep_file1b.absolute())},
                    ],
                }
            },
        },
        "Series 2": {
            "metadata": {"jellyfin_id": "s2"},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [{"name": "ep2.mkv", "path": str(ep_file2.absolute())}],
                }
            },
        },
    }

    db.save_library(library_name, initial_library)

    # Verify initial state
    loaded = db.load_library(library_name)
    assert len(loaded) == 2

    # TEST 1: Delete one episode file from Series 1
    ep_file1b.unlink()

    stats = db.cleanup_library(library_name, [str(root_dir)])
    assert stats["episodes"] == 1
    assert stats["seasons"] == 0
    assert stats["series"] == 0

    loaded = db.load_library(library_name)
    assert len(loaded["Series 1"]["seasons"]["Season 1"]["episodes"]) == 1
    assert (
        loaded["Series 1"]["seasons"]["Season 1"]["episodes"][0]["name"] == "ep1a.mkv"
    )

    # TEST 2: Delete Series 2 folder
    shutil.rmtree(series_dir2)

    stats = db.cleanup_library(library_name, [str(root_dir)])
    assert stats["series"] == 1
    assert stats["seasons"] == 1
    assert stats["episodes"] == 1

    loaded = db.load_library(library_name)
    assert "Series 2" not in loaded
    assert "Series 1" in loaded

    # TEST 3: Delete remaining episode of Series 1 -> Series 1 should be removed as empty
    ep_file1a.unlink()
    stats = db.cleanup_library(library_name, [str(root_dir)])
    assert stats["episodes"] == 1
    assert stats["seasons"] == 1  # Empty season removed
    assert stats["series"] == 1  # Empty series removed

    loaded = db.load_library(library_name)
    assert len(loaded) == 0

    # TEST 4: Missing season folder but series folder exists
    ep_file1a.write_text("dummy")
    initial_library = {
        "Series 1": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {"name": "ep1a.mkv", "path": str(ep_file1a.absolute())}
                    ],
                },
                "Season 2": {
                    "metadata": {},
                    "episodes": [{"name": "ep2.mkv", "path": "/missing/path/ep2.mkv"}],
                },
            },
        }
    }
    db.save_library(library_name, initial_library)

    stats = db.cleanup_library(library_name, [str(root_dir)])
    assert stats["seasons"] == 1
    assert stats["episodes"] == 1


def test_cleanup_movie_library_removes_missing(mock_db_file, tmp_path) -> None:
    from lan_streamer.db import _cleanup_movie_library, get_session
    from lan_streamer.db.models import Movie

    real_file = tmp_path / "present.mkv"
    real_file.touch()

    with get_session() as session:
        movie_present = Movie(
            name="Present", library_name="Movies", path=str(real_file)
        )
        movie_missing = Movie(
            name="Missing", library_name="Movies", path="/nonexistent/missing.mkv"
        )
        session.add_all([movie_present, movie_missing])
        session.flush()

        stats = {"movies": 0}
        _cleanup_movie_library(session, "Movies", stats)
        assert stats["movies"] == 1

    with get_session() as session:
        remaining = session.query(Movie).filter_by(library_name="Movies").all()
        assert len(remaining) == 1
        assert remaining[0].name == "Present"


def test_cleanup_tv_library_removes_missing_series(mock_db_file, tmp_path) -> None:
    from lan_streamer.db import _cleanup_tv_library, get_session
    from lan_streamer.db.models import Series, Season, Episode

    real_series_dir = tmp_path / "ActiveShow"
    season_dir = real_series_dir / "Season 1"
    season_dir.mkdir(parents=True)

    with get_session() as session:
        active = Series(name="ActiveShow", library_name="L")
        missing = Series(name="MissingShow", library_name="L")
        session.add_all([active, missing])
        session.flush()
        season = Season(series_id=missing.id, name="Season 1")
        session.add(season)
        session.flush()
        ep = Episode(season_id=season.id, name="E1", path="/p/E1.mkv")
        session.add(ep)
        session.flush()

        stats = {"series": 0, "seasons": 0, "episodes": 0, "movies": 0}
        _cleanup_tv_library(session, "L", [str(tmp_path)], stats)
        assert stats["series"] >= 1
        assert stats["episodes"] >= 1


def test_cleanup_tv_library_removes_missing_episode(mock_db_file, tmp_path) -> None:
    from lan_streamer.db import _cleanup_tv_library, get_session
    from lan_streamer.db.models import Series, Season, Episode

    series_dir = tmp_path / "ShowWithMissingEp"
    season_dir = series_dir / "Season 1"
    season_dir.mkdir(parents=True)

    with get_session() as session:
        series = Series(name="ShowWithMissingEp", library_name="L")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep_missing = Episode(season_id=season.id, name="E1", path="/nonexistent/ep.mkv")
        session.add(ep_missing)
        session.flush()

        stats = {"series": 0, "seasons": 0, "episodes": 0, "movies": 0}
        _cleanup_tv_library(session, "L", [str(tmp_path)], stats)
        assert stats["episodes"] >= 1


def test_load_library_correctness_complex() -> None:
    db.init_db()

    test_lib = {
        "Show A": {
            "metadata": {
                "jellyfin_id": "sid_a",
                "poster_path": "pa",
                "overview": "oa",
                "tmdb_name": "ta",
                "locked_metadata": True,
            },
            "seasons": {
                "Season 1": {
                    "metadata": {"jellyfin_id": "s1id", "poster_path": "s1p"},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path/a11",
                            "jellyfin_id": "e11id",
                            "watched": True,
                            "date_added": 100,
                        },
                        {
                            "name": "Ep 2",
                            "path": "/path/a12",
                            "jellyfin_id": "e12id",
                            "watched": False,
                            "date_added": 200,
                        },
                    ],
                },
                "Season 2": {
                    "metadata": {"jellyfin_id": "s2id", "poster_path": "s2p"},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path/a21",
                            "jellyfin_id": "e21id",
                            "watched": False,
                            "date_added": 300,
                        }
                    ],
                },
            },
        },
        "Show B": {
            "metadata": {
                "jellyfin_id": "sid_b",
                "poster_path": "pb",
                "overview": "ob",
                "tmdb_name": "tb",
                "locked_metadata": False,
            },
            "seasons": {},
        },
    }

    db.save_library("LibP", test_lib)

    loaded = db.load_library("LibP")

    assert len(loaded) == 2
    assert "Show A" in loaded
    assert "Show B" in loaded

    show_a = loaded["Show A"]
    assert show_a["metadata"]["jellyfin_id"] == "sid_a"
    assert show_a["metadata"]["locked_metadata"] is True
    assert len(show_a["seasons"]) == 2

    s1 = show_a["seasons"]["Season 1"]
    assert len(s1["episodes"]) == 2
    assert s1["episodes"][0]["name"] == "Ep 1"
    assert s1["episodes"][0]["watched"] is True
    assert s1["episodes"][0]["date_added"] == 100

    show_b = loaded["Show B"]
    assert len(show_b["seasons"]) == 0


def test_apply_movie_fields_sets_all_values(mock_db_file) -> None:
    from lan_streamer.db import _apply_movie_fields, get_session
    from lan_streamer.db.models import Movie

    with get_session() as session:
        movie = Movie(name="EmptyMovie", library_name="L", path="/old.mkv")
        session.add(movie)
        session.flush()

        movie_data = {
            "path": "/new.mkv",
            "jellyfin_id": "jf_new",
            "tmdb_identifier": "tmdb_new",
            "poster_path": "/new_p.jpg",
            "overview": "New overview",
            "tmdb_name": "New Name",
            "locked_metadata": True,
            "date_added": 2000,
            "runtime": 90,
            "rating": "7.5",
            "genre": "Drama",
            "year": 2023,
            "watched": True,
            "last_played_position": 30,
        }
        _apply_movie_fields(movie, movie_data)

        assert movie.path == "/new.mkv"
        assert movie.jellyfin_id == "jf_new"
        assert movie.runtime == 90
        assert movie.rating == "7.5"
        assert movie.watched is True


def test_apply_movie_fields_does_not_overwrite_with_falsy(mock_db_file) -> None:
    from lan_streamer.db import _apply_movie_fields, get_session
    from lan_streamer.db.models import Movie

    with get_session() as session:
        movie = Movie(
            name="M", library_name="L", path="/keep.mkv", jellyfin_id="keep_jf"
        )
        session.add(movie)
        session.flush()
        _apply_movie_fields(movie, {"path": "", "jellyfin_id": ""})
        assert movie.path == "/keep.mkv"
        assert movie.jellyfin_id == "keep_jf"


def test_db_movie_operations() -> None:
    library_name = "Cinematic Movies"
    movie_data = {
        "The Godfather (1972)": {
            "name": "The Godfather (1972)",
            "path": "/movies/Godfather/video.mkv",
            "jellyfin_id": "jf_godfather",
            "tmdb_identifier": "238",
            "poster_path": "/posters/godfather.jpg",
            "overview": "Spanning the years 1945 to 1955...",
            "tmdb_name": "The Godfather",
            "locked_metadata": False,
            "date_added": 12345,
            "runtime": 175,
            "rating": "8.7",
            "genre": "Crime, Drama",
            "year": 1972,
            "watched": False,
            "last_played_position": 0,
        }
    }

    db.save_movie_library(library_name, movie_data)

    loaded = db.load_movie_library(library_name)
    assert "The Godfather (1972)" in loaded
    item = loaded["The Godfather (1972)"]
    assert item["tmdb_name"] == "The Godfather"
    assert item["runtime"] == 175
    assert item["watched"] is False

    target_path = "/movies/Godfather/video.mkv"
    db.update_episode_watched_status(target_path, True)

    assert db.update_episode_playback_position(target_path, 1200) is True
    assert db.get_episode_playback_position(target_path) == 1200

    reloaded = db.load_movie_library(library_name)
    assert reloaded["The Godfather (1972)"]["watched"] is True
    assert reloaded["The Godfather (1972)"]["last_played_position"] == 1200


def test_db_movie_exceptions() -> None:
    with patch(
        "lan_streamer.db.connection.get_session", side_effect=Exception("DB Fault")
    ):
        assert db.load_movie_library("Cinematic Movies") == {}
        db.save_movie_library("Cinematic Movies", {"m": {}})


def test_db_movie_save_path_upsert() -> None:
    library_name: str = "Cinematic Movies"
    target_path: str = "/movies/Unique/video_remux.mkv"
    initial_data: dict[str, Any] = {
        "Unique Movie": {
            "name": "Unique Movie",
            "path": target_path,
            "tmdb_name": "Unique Movie",
        }
    }
    db.save_movie_library(library_name, initial_data)

    updated_data: dict[str, Any] = {
        "Unique Movie (2026)": {
            "name": "Unique Movie (2026)",
            "path": target_path,
            "tmdb_name": "Unique Movie",
        }
    }
    db.save_movie_library(library_name, updated_data)

    loaded: dict[str, Any] = db.load_movie_library(library_name)
    assert "Unique Movie (2026)" in loaded
    assert loaded["Unique Movie (2026)"]["path"] == target_path


def test_db_movie_save_stale_name_collision() -> None:
    library_name: str = "Cinematic Movies"
    db.save_movie_library(
        library_name,
        {
            "Movie OldName": {"name": "Movie OldName", "path": "/path/target.mkv"},
            "Movie TargetName": {
                "name": "Movie TargetName",
                "path": "/path/other.mkv",
            },
        },
    )

    db.save_movie_library(
        library_name,
        {
            "Movie TargetName": {
                "name": "Movie TargetName",
                "path": "/path/new_other.mkv",
            }
        },
    )
    loaded: dict[str, Any] = db.load_movie_library(library_name)
    assert loaded["Movie TargetName"]["path"] == "/path/new_other.mkv"

    # Re-seed
    db.save_movie_library(
        library_name,
        {
            "Movie OldName": {"name": "Movie OldName", "path": "/path/target.mkv"},
            "Movie TargetName": {
                "name": "Movie TargetName",
                "path": "/path/stale.mkv",
            },
        },
    )

    db.save_movie_library(
        library_name,
        {
            "Movie TargetName": {
                "name": "Movie TargetName",
                "path": "/path/target.mkv",
            }
        },
    )
    reloaded: dict[str, Any] = db.load_movie_library(library_name)
    assert "Movie TargetName" in reloaded
    assert reloaded["Movie TargetName"]["path"] == "/path/target.mkv"
    assert "Movie OldName" not in reloaded


def test_save_library_deletes_placeholder_episodes(mock_db_file) -> None:
    """Ensure placeholder episodes (path=None) are removed without raising errors."""
    lib_name = "PlaceholderLib"
    library = {
        "Series X": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "Ep Placeholder",
                            "tmdb_number": 1,
                            "path": None,
                            "watched": False,
                        },
                        {
                            "name": "Ep Real",
                            "tmdb_number": 2,
                            "path": "/tmp/real.mkv",
                            "watched": False,
                        },
                    ],
                }
            },
        }
    }
    # Save library should not raise and should delete the placeholder episode
    db.save_library(lib_name, library)
    loaded = db.load_library(lib_name)
    episodes = loaded["Series X"]["seasons"]["Season 1"]["episodes"]
    # Only the real episode should remain
    assert len(episodes) == 1
    assert episodes[0]["name"] == "Ep Real"
    assert episodes[0]["path"] == "/tmp/real.mkv"
