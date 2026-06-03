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

    # Series 1: Will remain with some episode paths nulled
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
    # The series folder still exists → episode path should be set to None, not deleted
    ep_file1b.unlink()

    stats = db.cleanup_library(library_name, [str(root_dir)])
    assert stats["episodes"] == 1  # one path nulled
    assert stats["seasons"] == 0
    assert stats["series"] == 0

    loaded = db.load_library(library_name)
    eps = loaded["Series 1"]["seasons"]["Season 1"]["episodes"]
    # Both episode records remain; the missing one has path=None
    assert len(eps) == 2
    paths = {ep["name"]: ep["path"] for ep in eps}
    assert paths["ep1a.mkv"] == str(ep_file1a.absolute())
    assert paths["ep1b.mkv"] is None

    # TEST 2: Delete Series 2 folder → Series 2 record + all its children deleted
    shutil.rmtree(series_dir2)

    stats = db.cleanup_library(library_name, [str(root_dir)])
    assert stats["series"] == 1
    assert stats["seasons"] == 1  # counted from cascaded seasons
    assert stats["episodes"] == 1  # counted from cascaded episodes

    loaded = db.load_library(library_name)
    assert "Series 2" not in loaded
    assert "Series 1" in loaded

    # TEST 3: Delete remaining episode file of Series 1
    # Series folder still exists → path is nulled, record is NOT deleted
    ep_file1a.unlink()
    stats = db.cleanup_library(library_name, [str(root_dir)])
    assert stats["episodes"] == 1  # path nulled
    assert stats["seasons"] == 0  # season NOT deleted
    assert stats["series"] == 0  # series NOT deleted

    loaded = db.load_library(library_name)
    # Series 1 still present with its season and both episodes (paths both None)
    assert "Series 1" in loaded
    eps = loaded["Series 1"]["seasons"]["Season 1"]["episodes"]
    assert len(eps) == 2
    assert all(ep["path"] is None for ep in eps)

    # TEST 4: Delete the series folder itself → now Series 1 record IS deleted
    shutil.rmtree(series_dir1)
    stats = db.cleanup_library(library_name, [str(root_dir)])
    assert stats["series"] == 1

    loaded = db.load_library(library_name)
    assert len(loaded) == 0


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
        # MissingShow folder doesn't exist in tmp_path → series deleted (cascade counts seasons+episodes)
        assert stats["series"] >= 1
        assert stats["seasons"] >= 1
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
        # Series folder exists → episode record is kept but path set to None
        assert stats["episodes"] >= 1
        assert ep_missing.path is None
        # Season and series records must NOT be deleted
        assert stats["seasons"] == 0
        assert stats["series"] == 0


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
    loaded: dict[str, Any] = db.load_movie_library(library_name)
    assert "Movie TargetName" in loaded
    assert loaded["Movie TargetName"]["path"] == "/path/target.mkv"
    assert "Movie OldName" not in loaded


# ---------------------------------------------------------------------------
# Structural permutation tests — series / season / episode presence
# ---------------------------------------------------------------------------


class TestSeriesStructuralPermutations:
    """
    Covers every structural shape of series data in save_library / load_library
    and cleanup_library:

      - Series with no seasons
      - Series with seasons that have no episodes
      - Series with seasons that have only placeholder (path=None) episodes
      - Series with seasons that have a mix of real + placeholder episodes
      - Series with seasons that all have at least one real episode

    All checked through the public save/load/cleanup API so that DB ↔ dict
    round-trip behaviour is fully exercised.
    """

    LIBRARY = "StructuralPermutations"

    # ------------------------------------------------------------------
    # save_library / load_library round-trip permutations
    # ------------------------------------------------------------------

    def test_series_with_no_seasons_round_trips(self) -> None:
        """A series record with an empty seasons dict is saved and loaded intact."""
        db.save_library(
            self.LIBRARY,
            {
                "Bare Series": {
                    "metadata": {"overview": "no seasons yet"},
                    "seasons": {},
                }
            },
        )
        loaded = db.load_library(self.LIBRARY)
        assert "Bare Series" in loaded
        assert loaded["Bare Series"]["seasons"] == {}

    def test_series_with_season_but_no_episodes_round_trips(self) -> None:
        """A season that carries no episodes at all is preserved in the DB."""
        db.save_library(
            self.LIBRARY,
            {
                "Empty Season Show": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {"metadata": {}, "episodes": []},
                    },
                }
            },
        )
        loaded = db.load_library(self.LIBRARY)
        assert "Empty Season Show" in loaded
        s1 = loaded["Empty Season Show"]["seasons"]["Season 1"]
        assert s1["episodes"] == []

    def test_series_with_placeholder_only_episodes_round_trips(self) -> None:
        """A season where every episode has path=None is saved and loaded intact."""
        db.save_library(
            self.LIBRARY,
            {
                "Placeholder Show": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [
                                {"name": "S01E01", "path": None, "tmdb_number": 1},
                                {"name": "S01E02", "path": None, "tmdb_number": 2},
                            ],
                        }
                    },
                }
            },
        )
        loaded = db.load_library(self.LIBRARY)
        eps = loaded["Placeholder Show"]["seasons"]["Season 1"]["episodes"]
        assert len(eps) == 2
        assert all(ep["path"] is None for ep in eps)
        assert {ep["name"] for ep in eps} == {"S01E01", "S01E02"}

    def test_series_with_mixed_real_and_placeholder_episodes_round_trips(
        self,
    ) -> None:
        """A season with some real paths and some None paths round-trips correctly."""
        db.save_library(
            self.LIBRARY,
            {
                "Mixed Show": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [
                                {
                                    "name": "S01E01",
                                    "path": "/tv/mixed/s01e01.mkv",
                                    "tmdb_number": 1,
                                },
                                {
                                    "name": "S01E02",
                                    "path": None,
                                    "tmdb_number": 2,
                                },
                            ],
                        }
                    },
                }
            },
        )
        loaded = db.load_library(self.LIBRARY)
        eps = loaded["Mixed Show"]["seasons"]["Season 1"]["episodes"]
        assert len(eps) == 2
        paths = {ep["name"]: ep["path"] for ep in eps}
        assert paths["S01E01"] == "/tv/mixed/s01e01.mkv"
        assert paths["S01E02"] is None

    def test_series_with_multiple_seasons_mixed_episode_presence(self) -> None:
        """
        Multiple seasons on one series:
          - Season 1: two real episodes
          - Season 2: no episodes at all
          - Season 3: one real + one placeholder
        """
        db.save_library(
            self.LIBRARY,
            {
                "Multi-Season Show": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [
                                {"name": "S01E01", "path": "/tv/ms/s01e01.mkv"},
                                {"name": "S01E02", "path": "/tv/ms/s01e02.mkv"},
                            ],
                        },
                        "Season 2": {
                            "metadata": {},
                            "episodes": [],
                        },
                        "Season 3": {
                            "metadata": {},
                            "episodes": [
                                {"name": "S03E01", "path": "/tv/ms/s03e01.mkv"},
                                {"name": "S03E02", "path": None},
                            ],
                        },
                    },
                }
            },
        )
        loaded = db.load_library(self.LIBRARY)
        seasons = loaded["Multi-Season Show"]["seasons"]
        assert len(seasons) == 3

        assert len(seasons["Season 1"]["episodes"]) == 2
        assert all(ep["path"] for ep in seasons["Season 1"]["episodes"])

        assert seasons["Season 2"]["episodes"] == []

        s3_eps = seasons["Season 3"]["episodes"]
        assert len(s3_eps) == 2
        paths_s3 = {ep["name"]: ep["path"] for ep in s3_eps}
        assert paths_s3["S03E01"] == "/tv/ms/s03e01.mkv"
        assert paths_s3["S03E02"] is None

    def test_multiple_series_with_varied_structures_in_one_library(self) -> None:
        """
        Saves four series with different structures and verifies each
        is loaded back independently with the correct shape.
        """
        db.save_library(
            self.LIBRARY,
            {
                "No Seasons": {"metadata": {}, "seasons": {}},
                "Empty Season": {
                    "metadata": {},
                    "seasons": {"Season 1": {"metadata": {}, "episodes": []}},
                },
                "All Placeholders": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [{"name": "E1", "path": None}],
                        }
                    },
                },
                "Has Real File": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [{"name": "E1", "path": "/tv/real/s01e01.mkv"}],
                        }
                    },
                },
            },
        )
        loaded = db.load_library(self.LIBRARY)
        assert loaded["No Seasons"]["seasons"] == {}
        assert loaded["Empty Season"]["seasons"]["Season 1"]["episodes"] == []
        ph_eps = loaded["All Placeholders"]["seasons"]["Season 1"]["episodes"]
        assert len(ph_eps) == 1 and ph_eps[0]["path"] is None
        real_eps = loaded["Has Real File"]["seasons"]["Season 1"]["episodes"]
        assert len(real_eps) == 1 and real_eps[0]["path"] == "/tv/real/s01e01.mkv"

    # ------------------------------------------------------------------
    # cleanup_library permutations — structural survival rules
    # ------------------------------------------------------------------

    def test_cleanup_series_with_no_seasons_survives_when_folder_exists(
        self, tmp_path
    ) -> None:
        """A no-season series is preserved as long as its folder exists."""
        series_dir = tmp_path / "Bare Series"
        series_dir.mkdir()

        db.save_library(
            self.LIBRARY,
            {"Bare Series": {"metadata": {}, "seasons": {}}},
        )

        stats = db.cleanup_library(self.LIBRARY, [str(tmp_path)])
        assert stats["series"] == 0
        assert "Bare Series" in db.load_library(self.LIBRARY)

    def test_cleanup_series_with_no_seasons_deleted_when_folder_gone(
        self, tmp_path
    ) -> None:
        """A no-season series is deleted when its folder is absent from all roots."""
        db.save_library(
            self.LIBRARY,
            {"Ghost Series": {"metadata": {}, "seasons": {}}},
        )
        # No ghost series folder created → root is empty
        stats = db.cleanup_library(self.LIBRARY, [str(tmp_path)])
        assert stats["series"] >= 1
        assert "Ghost Series" not in db.load_library(self.LIBRARY)

    def test_cleanup_empty_season_survives_when_series_folder_exists(
        self, tmp_path
    ) -> None:
        """A season with no episodes is never deleted as long as series folder exists."""
        series_dir = tmp_path / "Empty Season Show"
        series_dir.mkdir()

        db.save_library(
            self.LIBRARY,
            {
                "Empty Season Show": {
                    "metadata": {},
                    "seasons": {"Season 1": {"metadata": {}, "episodes": []}},
                }
            },
        )
        stats = db.cleanup_library(self.LIBRARY, [str(tmp_path)])
        assert stats["seasons"] == 0
        loaded = db.load_library(self.LIBRARY)
        assert "Season 1" in loaded["Empty Season Show"]["seasons"]

    def test_cleanup_placeholder_episodes_survive_when_series_folder_exists(
        self, tmp_path
    ) -> None:
        """Placeholder episodes (path=None) are left untouched by cleanup."""
        series_dir = tmp_path / "Placeholder Show"
        series_dir.mkdir()

        db.save_library(
            self.LIBRARY,
            {
                "Placeholder Show": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [
                                {"name": "S01E01", "path": None},
                                {"name": "S01E02", "path": None},
                            ],
                        }
                    },
                }
            },
        )
        stats = db.cleanup_library(self.LIBRARY, [str(tmp_path)])
        # Nothing to null/delete — all paths already None
        assert stats["episodes"] == 0
        assert stats["seasons"] == 0
        assert stats["series"] == 0

        eps = db.load_library(self.LIBRARY)["Placeholder Show"]["seasons"]["Season 1"][
            "episodes"
        ]
        assert len(eps) == 2
        assert all(ep["path"] is None for ep in eps)

    def test_cleanup_real_episode_file_gone_path_nulled_not_deleted(
        self, tmp_path
    ) -> None:
        """
        When a real episode file disappears but its series folder still exists,
        the episode record stays and its path becomes None.
        """
        series_dir = tmp_path / "Real Show"
        series_dir.mkdir()
        ep_file = series_dir / "s01e01.mkv"
        ep_file.write_text("data")

        db.save_library(
            self.LIBRARY,
            {
                "Real Show": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [
                                {"name": "S01E01", "path": str(ep_file)},
                                {"name": "S01E02", "path": None},
                            ],
                        }
                    },
                }
            },
        )

        # Remove the real file
        ep_file.unlink()

        stats = db.cleanup_library(self.LIBRARY, [str(tmp_path)])
        assert stats["episodes"] == 1  # one path nulled
        assert stats["seasons"] == 0
        assert stats["series"] == 0

        eps = db.load_library(self.LIBRARY)["Real Show"]["seasons"]["Season 1"][
            "episodes"
        ]
        assert len(eps) == 2  # both records preserved
        assert all(ep["path"] is None for ep in eps)

    def test_cleanup_series_with_mixed_seasons_all_survive_while_folder_exists(
        self, tmp_path
    ) -> None:
        """
        A series with seasons of varying episode presence keeps ALL seasons
        (including empty ones) as long as the series folder exists.
        """
        series_dir = tmp_path / "Multi-Season Show"
        series_dir.mkdir()
        ep_file = series_dir / "s01e01.mkv"
        ep_file.write_text("data")

        db.save_library(
            self.LIBRARY,
            {
                "Multi-Season Show": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [{"name": "S01E01", "path": str(ep_file)}],
                        },
                        "Season 2": {"metadata": {}, "episodes": []},
                        "Season 3": {
                            "metadata": {},
                            "episodes": [{"name": "S03E01", "path": None}],
                        },
                    },
                }
            },
        )

        stats = db.cleanup_library(self.LIBRARY, [str(tmp_path)])
        assert stats["series"] == 0
        assert stats["seasons"] == 0
        assert stats["episodes"] == 0

        seasons = db.load_library(self.LIBRARY)["Multi-Season Show"]["seasons"]
        assert set(seasons.keys()) == {"Season 1", "Season 2", "Season 3"}


# ---------------------------------------------------------------------------
# Multi-root-directory tests
# ---------------------------------------------------------------------------


class TestMultiRootDirectoryCleanup:
    """
    Verifies that cleanup_library correctly handles libraries whose series
    folders may live in any of several root directories.  A series is only
    deleted when its folder is absent from *every* root.
    """

    LIBRARY = "MultiRootLib"

    def test_series_in_first_root_survives_when_second_root_is_empty(
        self, tmp_path
    ) -> None:
        root_a = tmp_path / "rootA"
        root_b = tmp_path / "rootB"
        root_a.mkdir()
        root_b.mkdir()
        (root_a / "Show Alpha").mkdir()

        db.save_library(
            self.LIBRARY,
            {"Show Alpha": {"metadata": {}, "seasons": {}}},
        )
        stats = db.cleanup_library(self.LIBRARY, [str(root_a), str(root_b)])
        assert stats["series"] == 0
        assert "Show Alpha" in db.load_library(self.LIBRARY)

    def test_series_in_second_root_survives_when_first_root_is_empty(
        self, tmp_path
    ) -> None:
        root_a = tmp_path / "rootA"
        root_b = tmp_path / "rootB"
        root_a.mkdir()
        root_b.mkdir()
        (root_b / "Show Beta").mkdir()

        db.save_library(
            self.LIBRARY,
            {"Show Beta": {"metadata": {}, "seasons": {}}},
        )
        stats = db.cleanup_library(self.LIBRARY, [str(root_a), str(root_b)])
        assert stats["series"] == 0
        assert "Show Beta" in db.load_library(self.LIBRARY)

    def test_series_absent_from_all_roots_is_deleted(self, tmp_path) -> None:
        root_a = tmp_path / "rootA"
        root_b = tmp_path / "rootB"
        root_a.mkdir()
        root_b.mkdir()
        # No folder for "Ghost Show" in either root

        db.save_library(
            self.LIBRARY,
            {"Ghost Show": {"metadata": {}, "seasons": {}}},
        )
        stats = db.cleanup_library(self.LIBRARY, [str(root_a), str(root_b)])
        assert stats["series"] >= 1
        assert "Ghost Show" not in db.load_library(self.LIBRARY)

    def test_series_spread_across_two_roots_both_survive(self, tmp_path) -> None:
        """Two different series, one in each root, both survive cleanup."""
        root_a = tmp_path / "rootA"
        root_b = tmp_path / "rootB"
        root_a.mkdir()
        root_b.mkdir()
        (root_a / "Show Alpha").mkdir()
        (root_b / "Show Beta").mkdir()

        db.save_library(
            self.LIBRARY,
            {
                "Show Alpha": {"metadata": {}, "seasons": {}},
                "Show Beta": {"metadata": {}, "seasons": {}},
            },
        )
        stats = db.cleanup_library(self.LIBRARY, [str(root_a), str(root_b)])
        assert stats["series"] == 0
        loaded = db.load_library(self.LIBRARY)
        assert "Show Alpha" in loaded
        assert "Show Beta" in loaded

    def test_one_series_deleted_other_survives_in_multi_root(self, tmp_path) -> None:
        """One series folder gone, another present — only the absent one is deleted."""
        root_a = tmp_path / "rootA"
        root_b = tmp_path / "rootB"
        root_a.mkdir()
        root_b.mkdir()
        (root_a / "Alive Show").mkdir()
        # "Dead Show" folder intentionally absent

        db.save_library(
            self.LIBRARY,
            {
                "Alive Show": {"metadata": {}, "seasons": {}},
                "Dead Show": {"metadata": {}, "seasons": {}},
            },
        )
        stats = db.cleanup_library(self.LIBRARY, [str(root_a), str(root_b)])
        assert stats["series"] == 1
        loaded = db.load_library(self.LIBRARY)
        assert "Alive Show" in loaded
        assert "Dead Show" not in loaded

    def test_episode_path_nulled_regardless_of_which_root_holds_series(
        self, tmp_path
    ) -> None:
        """
        Even when a series lives in root_b (not root_a), a missing episode file
        in that series is nulled — not treated as a series-folder-absent case.
        """
        root_a = tmp_path / "rootA"
        root_b = tmp_path / "rootB"
        root_a.mkdir()
        root_b.mkdir()
        series_dir = root_b / "Beta Show"
        series_dir.mkdir()

        ep_file = series_dir / "s01e01.mkv"
        ep_file.write_text("data")

        db.save_library(
            self.LIBRARY,
            {
                "Beta Show": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [{"name": "S01E01", "path": str(ep_file)}],
                        }
                    },
                }
            },
        )

        ep_file.unlink()

        stats = db.cleanup_library(self.LIBRARY, [str(root_a), str(root_b)])
        # Series folder exists in root_b → episode path nulled, nothing deleted
        assert stats["episodes"] == 1
        assert stats["seasons"] == 0
        assert stats["series"] == 0

        eps = db.load_library(self.LIBRARY)["Beta Show"]["seasons"]["Season 1"][
            "episodes"
        ]
        assert len(eps) == 1
        assert eps[0]["path"] is None

    def test_three_roots_series_in_middle_root_survives(self, tmp_path) -> None:
        """Series in the second of three roots is found and preserved."""
        root_a = tmp_path / "rootA"
        root_b = tmp_path / "rootB"
        root_c = tmp_path / "rootC"
        for r in (root_a, root_b, root_c):
            r.mkdir()
        (root_b / "Middle Show").mkdir()

        db.save_library(
            self.LIBRARY,
            {"Middle Show": {"metadata": {}, "seasons": {}}},
        )
        stats = db.cleanup_library(
            self.LIBRARY, [str(root_a), str(root_b), str(root_c)]
        )
        assert stats["series"] == 0
        assert "Middle Show" in db.load_library(self.LIBRARY)

    def test_series_with_episodes_spread_info_across_multiple_roots(
        self, tmp_path
    ) -> None:
        """
        Two separate series each live in a different root.  One has a missing
        episode file (path nulled), the other's episode file still exists.
        Verifies both cleanup outcomes independently.
        """
        root_a = tmp_path / "rootA"
        root_b = tmp_path / "rootB"
        root_a.mkdir()
        root_b.mkdir()

        # Series A in root_a: episode file will be deleted
        series_a_dir = root_a / "Series Alpha"
        series_a_dir.mkdir()
        ep_a = series_a_dir / "s01e01.mkv"
        ep_a.write_text("a")

        # Series B in root_b: episode file stays on disk
        series_b_dir = root_b / "Series Beta"
        series_b_dir.mkdir()
        ep_b = series_b_dir / "s01e01.mkv"
        ep_b.write_text("b")

        db.save_library(
            self.LIBRARY,
            {
                "Series Alpha": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [{"name": "S01E01", "path": str(ep_a)}],
                        }
                    },
                },
                "Series Beta": {
                    "metadata": {},
                    "seasons": {
                        "Season 1": {
                            "metadata": {},
                            "episodes": [{"name": "S01E01", "path": str(ep_b)}],
                        }
                    },
                },
            },
        )

        ep_a.unlink()  # Simulate Series Alpha losing its episode file

        stats = db.cleanup_library(self.LIBRARY, [str(root_a), str(root_b)])
        assert stats["episodes"] == 1  # Alpha's episode path nulled
        assert stats["series"] == 0  # both series folders still present
        assert stats["seasons"] == 0

        loaded = db.load_library(self.LIBRARY)
        alpha_eps = loaded["Series Alpha"]["seasons"]["Season 1"]["episodes"]
        beta_eps = loaded["Series Beta"]["seasons"]["Season 1"]["episodes"]

        assert len(alpha_eps) == 1 and alpha_eps[0]["path"] is None
        assert len(beta_eps) == 1 and beta_eps[0]["path"] == str(ep_b)

    def test_no_roots_provided_deletes_all_series(self) -> None:
        """
        Passing an empty root list means no series folder can exist anywhere,
        so every series in the library is deleted.
        """
        db.save_library(
            self.LIBRARY,
            {
                "Show A": {"metadata": {}, "seasons": {}},
                "Show B": {"metadata": {}, "seasons": {}},
            },
        )
        stats = db.cleanup_library(self.LIBRARY, [])
        assert stats["series"] >= 2
        assert db.load_library(self.LIBRARY) == {}
