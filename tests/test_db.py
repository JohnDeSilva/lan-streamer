import pytest
from unittest.mock import patch
from lan_streamer import db
from lan_streamer.models import Series, Season, Episode


@pytest.fixture
def mock_db_file(tmp_path) -> None:
    # Already handled by conftest.py autouse fixture,
    # but kept here for tests that explicitly use it.
    return tmp_path / "library.db"


def test_init_db(mock_db_file) -> None:
    db._db_initialized = False
    db.init_db()
    assert mock_db_file.parent.exists()


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


def test_update_watched_status(mock_db_file) -> None:
    test_lib = {
        "Test Series": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
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

    db.update_episode_watched_status("/path/to/ep1.mkv", True)

    loaded = db.load_library("MyLib")
    eps = loaded["Test Series"]["seasons"]["Season 1"]["episodes"]
    assert eps[0]["watched"] is True


def test_db_error_handling(mock_db_file) -> None:
    # Mocking get_session to raise an exception
    with patch("lan_streamer.db.get_session") as mock_session:
        mock_session.side_effect = Exception("Mocked error")

        # These should catch the error and log it, not crash
        assert db.load_library("Lib") == {}
        db.save_library("Lib", {})
        db.update_episode_watched_status("path", True)


def test_sync_watched_from_paths(mock_db_file) -> None:
    from lan_streamer.db import sync_watched_from_jellyfin_data, get_session

    # Setup data using ORM
    with get_session() as session:
        series = Series(name="Show", library_name="Lib")
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()

        ep1 = Episode(season_id=season.id, name="Ep1", path="/path1", watched=False)
        ep2 = Episode(season_id=season.id, name="Ep2", path="/path2", watched=False)
        session.add(ep1)
        session.add(ep2)

    # Test with one path
    count = sync_watched_from_jellyfin_data(set(), {"/path1"}, set())
    assert count == 1

    loaded = db.load_library("Lib")
    eps = loaded["Show"]["seasons"]["Season 1"]["episodes"]
    # Episodes are sorted by name
    ep1_data = next(e for e in eps if e["path"] == "/path1")
    ep2_data = next(e for e in eps if e["path"] == "/path2")
    assert ep1_data["watched"] is True
    assert ep2_data["watched"] is False

    # Test with name-based match
    count = sync_watched_from_jellyfin_data(set(), set(), {("Show", "Ep2")})
    assert count == 1

    loaded = db.load_library("Lib")
    eps = loaded["Show"]["seasons"]["Season 1"]["episodes"]
    ep2_data = next(e for e in eps if e["path"] == "/path2")
    assert ep2_data["watched"] is True

    # Test with empty sets
    assert sync_watched_from_jellyfin_data(set(), set(), set()) == 0


def test_get_all_episodes_with_jellyfin_id(mock_db_file) -> None:
    test_lib = {
        "Show": {
            "seasons": {
                "S1": {
                    "episodes": [
                        {
                            "name": "E1",
                            "path": "/p1",
                            "jellyfin_id": "jf1",
                            "watched": True,
                        },
                        {
                            "name": "E2",
                            "path": "/p2",
                            "jellyfin_id": None,
                            "watched": True,
                        },
                    ]
                }
            }
        }
    }
    db.save_library("Lib", test_lib)
    eps = db.get_all_episodes_with_jellyfin_id()
    assert len(eps) == 1
    assert eps[0]["jellyfin_id"] == "jf1"


def test_update_season_watched_status(mock_db_file) -> None:
    test_lib = {
        "Test Series": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path1",
                            "watched": False,
                        },
                        {
                            "name": "Ep 2",
                            "path": "/path2",
                            "watched": False,
                        },
                    ],
                },
                "Season 2": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path3",
                            "watched": False,
                        }
                    ],
                },
            },
        }
    }
    db.save_library("MyLib", test_lib)

    db.update_season_watched_status("MyLib", "Test Series", "Season 1", True)

    loaded = db.load_library("MyLib")
    s1_eps = loaded["Test Series"]["seasons"]["Season 1"]["episodes"]
    assert all(ep["watched"] is True for ep in s1_eps)

    s2_eps = loaded["Test Series"]["seasons"]["Season 2"]["episodes"]
    assert all(ep["watched"] is False for ep in s2_eps)

    # Toggle back
    db.update_season_watched_status("MyLib", "Test Series", "Season 1", False)
    loaded = db.load_library("MyLib")
    s1_eps = loaded["Test Series"]["seasons"]["Season 1"]["episodes"]
    assert all(ep["watched"] is False for ep in s1_eps)


def test_update_series_watched_status(mock_db_file) -> None:
    test_lib = {
        "Test Series": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [{"name": "Ep 1", "path": "/path1", "watched": False}],
                },
                "Season 2": {
                    "metadata": {},
                    "episodes": [{"name": "Ep 1", "path": "/path2", "watched": False}],
                },
            },
        },
        "Other Series": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [{"name": "Ep 1", "path": "/path3", "watched": False}],
                }
            },
        },
    }
    db.save_library("MyLib", test_lib)

    db.update_series_watched_status("MyLib", "Test Series", True)

    loaded = db.load_library("MyLib")
    # Check Test Series (both seasons should be watched)
    for season in loaded["Test Series"]["seasons"].values():
        for ep in season["episodes"]:
            assert ep["watched"] is True

    # Check Other Series (should be untouched)
    for season in loaded["Other Series"]["seasons"].values():
        for ep in season["episodes"]:
            assert ep["watched"] is False

    # Toggle back
    db.update_series_watched_status("MyLib", "Test Series", False)
    loaded = db.load_library("MyLib")
    for season in loaded["Test Series"]["seasons"].values():
        for ep in season["episodes"]:
            assert ep["watched"] is False


def test_update_episode_path(mock_db_file) -> None:
    test_lib = {
        "Show": {
            "seasons": {"S1": {"episodes": [{"name": "E1", "path": "/old/path.mkv"}]}}
        }
    }
    db.save_library("Lib", test_lib)
    db.update_episode_path("/old/path.mkv", "/new/path.mkv")

    loaded = db.load_library("Lib")
    ep = loaded["Show"]["seasons"]["S1"]["episodes"][0]
    assert ep["path"] == "/new/path.mkv"


def test_update_episode_path_missing(mock_db_file) -> None:
    # Should not crash or error out
    db.update_episode_path("/missing/path.mkv", "/new/path.mkv")


def test_db_error_handling_extended(mock_db_file) -> None:
    with patch("lan_streamer.db.get_session") as mock_session:
        mock_session.side_effect = Exception("Mocked error")
        # Test get_all_episodes_with_jellyfin_id error path
        assert db.get_all_episodes_with_jellyfin_id() == []
        # Test cleanup_library error path
        with pytest.raises(Exception):
            db.cleanup_library("Lib", [])
        # Test playback position error paths
        assert db.update_episode_playback_position("path", 100) is False
        assert db.get_episode_playback_position("path") == 0


def test_update_and_get_playback_position(mock_db_file) -> None:
    from lan_streamer.db import get_session

    with get_session() as session:
        series = Series(name="ShowPos", library_name="LibPos")
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="S1")
        session.add(season)
        session.flush()

        ep = Episode(
            season_id=season.id, name="E1", path="/path/to/pos.mkv", watched=False
        )
        session.add(ep)
        session.commit()

    assert db.get_episode_playback_position("/path/to/pos.mkv") == 0
    assert db.update_episode_playback_position("/path/to/pos.mkv", 350) is True
    assert db.get_episode_playback_position("/path/to/pos.mkv") == 350
    assert db.update_episode_playback_position("/nonexistent/path.mkv", 10) is False


def test_runtime_management_functions(mock_db_file) -> None:
    from lan_streamer.db import get_session
    from lan_streamer.models import Movie

    with get_session() as session:
        series = Series(name="RuntimeShow", library_name="RuntimeLib")
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="S1")
        session.add(season)
        session.flush()

        episode_missing = Episode(
            season_id=season.id, name="E1", path="/path/to/missing_ep.mkv", runtime=0
        )
        episode_present = Episode(
            season_id=season.id, name="E2", path="/path/to/present_ep.mkv", runtime=25
        )
        movie_missing = Movie(
            name="MissingMovie",
            path="/path/to/missing_movie.mkv",
            library_name="Movies",
            runtime=None,
        )
        session.add_all([episode_missing, episode_present, movie_missing])
        session.commit()

    items = db.get_items_missing_runtime()
    assert len(items) == 2
    paths = {item["path"] for item in items}
    assert "/path/to/missing_ep.mkv" in paths
    assert "/path/to/missing_movie.mkv" in paths

    # Update runtime
    for item in items:
        db.update_item_runtime(item["id"], item["type"], 45)

    # Verify updates
    with get_session() as session:
        updated_episode = (
            session.query(Episode).filter_by(path="/path/to/missing_ep.mkv").first()
        )
        assert updated_episode is not None
        assert updated_episode.runtime == 45

        updated_movie = (
            session.query(Movie).filter_by(path="/path/to/missing_movie.mkv").first()
        )
        assert updated_movie is not None
        assert updated_movie.runtime == 45


# ---------------------------------------------------------------------------
# Granular unit tests for extracted db helper functions
# ---------------------------------------------------------------------------


def test_build_episode_dict(mock_db_file) -> None:
    from lan_streamer.db import _build_episode_dict, get_session
    from lan_streamer.models import Series, Season, Episode

    with get_session() as session:
        series = Series(name="S", library_name="L")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep = Episode(
            season_id=season.id,
            name="S01E01.mkv",
            path="/p/S01E01.mkv",
            watched=True,
            runtime=42,
            air_date="2022-01-01",
            tmdb_name="Pilot",
            tmdb_number=1,
            tmdb_episode_identifier="tmdb_ep_1",
            jellyfin_id="jf_ep_1",
        )
        session.add(ep)
        session.flush()
        result = _build_episode_dict(ep)

    assert result["name"] == "S01E01.mkv"
    assert result["path"] == "/p/S01E01.mkv"
    assert result["watched"] is True
    assert result["runtime"] == 42
    assert result["air_date"] == "2022-01-01"
    assert result["tmdb_name"] == "Pilot"
    assert result["tmdb_number"] == 1
    assert result["jellyfin_id"] == "jf_ep_1"


def test_build_episode_dict_defaults(mock_db_file) -> None:
    from lan_streamer.db import _build_episode_dict, get_session
    from lan_streamer.models import Series, Season, Episode

    with get_session() as session:
        series = Series(name="S", library_name="L")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep = Episode(season_id=season.id, name="ep.mkv", path="/p/ep.mkv")
        session.add(ep)
        session.flush()
        result = _build_episode_dict(ep)

    assert result["runtime"] == 0
    assert result["air_date"] == ""
    assert result["watched"] is False


def test_build_season_dict(mock_db_file) -> None:
    from lan_streamer.db import _build_season_dict, get_session
    from lan_streamer.models import Series, Season, Episode

    with get_session() as session:
        series = Series(name="S", library_name="L")
        session.add(series)
        session.flush()
        season = Season(
            series_id=series.id,
            name="Season 1",
            jellyfin_id="jf_s1",
            poster_path="/poster.jpg",
        )
        session.add(season)
        session.flush()
        ep1 = Episode(season_id=season.id, name="S01E02.mkv", path="/p2")
        ep2 = Episode(season_id=season.id, name="S01E01.mkv", path="/p1")
        session.add_all([ep1, ep2])
        session.flush()
        result = _build_season_dict(season)

    assert result["metadata"]["jellyfin_id"] == "jf_s1"
    assert result["metadata"]["poster_path"] == "/poster.jpg"
    # Episodes should be sorted naturally
    assert result["episodes"][0]["name"] == "S01E01.mkv"
    assert result["episodes"][1]["name"] == "S01E02.mkv"


def test_build_series_dict(mock_db_file) -> None:
    from lan_streamer.db import _build_series_dict, get_session
    from lan_streamer.models import Series, Season, Episode

    with get_session() as session:
        series = Series(
            name="MyShow",
            library_name="L",
            jellyfin_id="jf_s",
            tmdb_identifier="tmdb_s",
            poster_path="/sp.jpg",
            overview="Great show",
            tmdb_name="My Show",
            locked_metadata=True,
            first_air_date="2021-06-01",
        )
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep = Episode(season_id=season.id, name="S01E01.mkv", path="/p")
        session.add(ep)
        session.flush()
        result = _build_series_dict(series)

    assert result["metadata"]["jellyfin_id"] == "jf_s"
    assert result["metadata"]["tmdb_identifier"] == "tmdb_s"
    assert result["metadata"]["locked_metadata"] is True
    assert result["metadata"]["first_air_date"] == "2021-06-01"
    assert "Season 1" in result["seasons"]


def test_build_movie_dict(mock_db_file) -> None:
    from lan_streamer.db import _build_movie_dict, get_session
    from lan_streamer.models import Movie

    with get_session() as session:
        movie = Movie(
            name="Inception",
            library_name="Movies",
            path="/movies/inception.mkv",
            jellyfin_id="jf_m",
            tmdb_identifier="tt_inc",
            poster_path="/p.jpg",
            overview="Heist",
            tmdb_name="Inception",
            locked_metadata=False,
            date_added=1000,
            runtime=148,
            rating="8.8",
            genre="Thriller",
            year=2010,
            watched=True,
            last_played_position=60,
        )
        session.add(movie)
        session.flush()
        result = _build_movie_dict(movie)

    assert result["name"] == "Inception"
    assert result["runtime"] == 148
    assert result["rating"] == "8.8"
    assert result["genre"] == "Thriller"
    assert result["year"] == 2010
    assert result["watched"] is True
    assert result["last_played_position"] == 60


def test_apply_movie_fields_sets_all_values(mock_db_file) -> None:
    from lan_streamer.db import _apply_movie_fields, get_session
    from lan_streamer.models import Movie

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
    from lan_streamer.models import Movie

    with get_session() as session:
        movie = Movie(
            name="M", library_name="L", path="/keep.mkv", jellyfin_id="keep_jf"
        )
        session.add(movie)
        session.flush()
        _apply_movie_fields(movie, {"path": "", "jellyfin_id": ""})
        assert movie.path == "/keep.mkv"
        assert movie.jellyfin_id == "keep_jf"


def test_sync_watched_by_ids(mock_db_file) -> None:
    from lan_streamer.db import _sync_watched_by_ids, get_session
    from lan_streamer.models import Series, Season, Episode

    with get_session() as session:
        series = Series(name="S", library_name="L")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="S1")
        session.add(season)
        session.flush()
        ep1 = Episode(
            season_id=season.id,
            name="E1",
            path="/p1",
            jellyfin_id="jf_watched_1",
            watched=False,
        )
        ep2 = Episode(
            season_id=season.id,
            name="E2",
            path="/p2",
            jellyfin_id="jf_not_in_set",
            watched=False,
        )
        session.add_all([ep1, ep2])
        session.flush()

        count = _sync_watched_by_ids(session, {"jf_watched_1"})
        assert count == 1

    from lan_streamer.db import get_session

    with get_session() as session:
        ep = session.query(Episode).filter_by(path="/p1").first()
        assert ep is not None and ep.watched is True
        ep2 = session.query(Episode).filter_by(path="/p2").first()
        assert ep2 is not None and ep2.watched is False


def test_sync_watched_by_ids_empty(mock_db_file) -> None:
    from lan_streamer.db import _sync_watched_by_ids, get_session

    with get_session() as session:
        assert _sync_watched_by_ids(session, set()) == 0


def test_sync_watched_by_paths(mock_db_file) -> None:
    from lan_streamer.db import _sync_watched_by_paths, get_session
    from lan_streamer.models import Series, Season, Episode

    with get_session() as session:
        series = Series(name="S", library_name="L")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="S1")
        session.add(season)
        session.flush()
        ep = Episode(season_id=season.id, name="E1", path="/path/ep.mkv", watched=False)
        session.add(ep)
        session.flush()

        count = _sync_watched_by_paths(session, {"/path/ep.mkv"})
        assert count == 1


def test_sync_watched_by_paths_empty(mock_db_file) -> None:
    from lan_streamer.db import _sync_watched_by_paths, get_session

    with get_session() as session:
        assert _sync_watched_by_paths(session, set()) == 0


def test_sync_watched_by_names(mock_db_file) -> None:
    from lan_streamer.db import _sync_watched_by_names, get_session
    from lan_streamer.models import Series, Season, Episode

    with get_session() as session:
        series = Series(name="Cool Show", library_name="L")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="S1")
        session.add(season)
        session.flush()
        ep = Episode(season_id=season.id, name="The Pilot", path="/p", watched=False)
        session.add(ep)
        session.flush()

        count = _sync_watched_by_names(session, {("Cool Show", "The Pilot")})
        assert count == 1


def test_sync_watched_by_names_empty(mock_db_file) -> None:
    from lan_streamer.db import _sync_watched_by_names, get_session

    with get_session() as session:
        assert _sync_watched_by_names(session, set()) == 0


def test_cleanup_movie_library_removes_missing(mock_db_file, tmp_path) -> None:
    from lan_streamer.db import _cleanup_movie_library, get_session
    from lan_streamer.models import Movie

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
    from lan_streamer.models import Series, Season, Episode

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
    from lan_streamer.models import Series, Season, Episode

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


def test_db_edge_cases() -> None:
    # natural_sort_key with None
    assert db.natural_sort_key(None) == []

    # Reset initialized flag to test full init_db path
    db._db_initialized = False
    # init_db with mkdir exception
    with patch("pathlib.Path.mkdir", side_effect=OSError("Write error")):
        assert db.init_db() is False


def test_db_more_error_paths() -> None:
    with patch("lan_streamer.db.get_session") as mock_session:
        mock_session.side_effect = Exception("General DB Error")
        # Ensure these functions don't raise but log exceptions
        db.update_season_watched_status("Lib", "Show", "S1", True)
        db.update_series_watched_status("Lib", "Show", True)
        db.update_item_runtime(1, "episode", 30)
        db.sync_watched_from_jellyfin_data({"id1"}, {"/path1"}, {("Show", "Ep1")})


def test_get_session_rollback() -> None:
    from lan_streamer.db import get_session

    with pytest.raises(ValueError):
        with get_session():
            raise ValueError("Test rollback trigger")


def test_get_next_episode(mock_db_file) -> None:
    # 1. Setup a test library with 2 seasons, and 2 episodes each
    test_lib = {
        "Test Series": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path/s1e1.mkv",
                            "watched": False,
                            "tmdb_number": 1,
                            "tmdb_name": "S1E1",
                        },
                        {
                            "name": "Ep 2",
                            "path": "/path/s1e2.mkv",
                            "watched": False,
                            "tmdb_number": 2,
                            "tmdb_name": "S1E2",
                        },
                    ],
                },
                "Season 2": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path/s2e1.mkv",
                            "watched": False,
                            "tmdb_number": 1,
                            "tmdb_name": "S2E1",
                        },
                    ],
                },
            },
        }
    }
    db.save_library("MyLib", test_lib)

    # Test transitioning inside the same season (Ep 1 -> Ep 2)
    next_ep = db.get_next_episode("/path/s1e1.mkv")
    assert next_ep is not None
    assert next_ep["path"] == "/path/s1e2.mkv"
    assert next_ep["title"] == "S1E2"
    assert next_ep["season"] == "Season 1"
    assert next_ep["episode_number"] == 2

    # Test transitioning to the next season (Season 1 Ep 2 -> Season 2 Ep 1)
    next_ep = db.get_next_episode("/path/s1e2.mkv")
    assert next_ep is not None
    assert next_ep["path"] == "/path/s2e1.mkv"
    assert next_ep["title"] == "S2E1"
    assert next_ep["season"] == "Season 2"
    assert next_ep["episode_number"] == 1

    # Test last episode of the series (no next episode)
    next_ep = db.get_next_episode("/path/s2e1.mkv")
    assert next_ep is None

    # Test non-existent path
    assert db.get_next_episode("/path/nonexistent.mkv") is None


def test_get_next_episode_natural_sorting(mock_db_file) -> None:
    """Validate that natural sorting is used, so that Ep 2 comes before Ep 11."""
    test_lib = {
        "Test Series": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {"name": "Ep 11", "path": "/path/ep11.mkv", "watched": False},
                        {"name": "Ep 2", "path": "/path/ep2.mkv", "watched": False},
                    ],
                }
            },
        }
    }
    db.save_library("MyLib", test_lib)

    # In alphabetical sorting, "Ep 11" comes before "Ep 2", so next of "Ep 11" would be "Ep 2".
    # In natural sorting, "Ep 2" comes before "Ep 11", so next of "Ep 2" should be "Ep 11".
    next_ep = db.get_next_episode("/path/ep2.mkv")
    assert next_ep is not None
    assert next_ep["path"] == "/path/ep11.mkv"

    # Next of "Ep 11" should be None (as it is the last episode under natural sorting)
    assert db.get_next_episode("/path/ep11.mkv") is None


def test_combined_view_queries(mock_db_file) -> None:
    from lan_streamer.db import (
        get_session,
        get_combined_next_up,
        get_combined_recently_added,
        get_combined_smart_row,
    )
    from lan_streamer.models import Series, Season, Episode, Movie

    # 1. Setup a mix of TV libraries and Movie libraries
    with get_session() as session:
        # Series 1: TV library, watched some episodes (partially watched season 1)
        s1 = Series(name="TV Series 1", library_name="TV Lib")
        session.add(s1)
        session.flush()

        s1_se1 = Season(series_id=s1.id, name="Season 1")
        session.add(s1_se1)
        session.flush()

        ep1 = Episode(
            season_id=s1_se1.id,
            name="Ep 1",
            path="/tv1/s1e1.mkv",
            watched=True,
            date_added=100,
            last_played_at=1000,
        )
        ep2 = Episode(
            season_id=s1_se1.id,
            name="Ep 2",
            path="/tv1/s1e2.mkv",
            watched=False,
            date_added=110,
            last_played_at=0,
        )
        session.add_all([ep1, ep2])

        # Series 2: TV library, completely unwatched
        s2 = Series(name="TV Series 2", library_name="TV Lib")
        session.add(s2)
        session.flush()

        s2_se1 = Season(series_id=s2.id, name="Season 1")
        session.add(s2_se1)
        session.flush()

        ep3 = Episode(
            season_id=s2_se1.id,
            name="Ep 1",
            path="/tv2/s1e1.mkv",
            watched=False,
            date_added=200,
            last_played_at=0,
        )
        session.add(ep3)

        # Movie 1
        m1 = Movie(
            name="Movie 1",
            library_name="Movie Lib",
            path="/movies/m1.mkv",
            watched=True,
            date_added=300,
            year=2020,
        )
        # Movie 2
        m2 = Movie(
            name="Movie 2",
            library_name="Movie Lib",
            path="/movies/m2.mkv",
            watched=False,
            date_added=400,
            year=2021,
        )
        session.add_all([m1, m2])
        session.commit()

    # Test get_combined_next_up
    next_up = get_combined_next_up(["TV Lib"])
    assert len(next_up) == 1
    assert next_up[0]["series_name"] == "TV Series 1"
    assert next_up[0]["season_name"] == "Season 1"
    assert next_up[0]["last_played_at"] == 1000

    # Test get_combined_recently_added
    recently_added = get_combined_recently_added(["TV Lib", "Movie Lib"])
    assert len(recently_added) == 4
    assert recently_added[0]["name"] == "Movie 2"
    assert recently_added[1]["name"] == "Movie 1"
    assert recently_added[2]["name"] == "TV Series 2"
    assert recently_added[3]["name"] == "TV Series 1"

    # Test get_combined_smart_row
    unwatched = get_combined_smart_row(
        ["TV Lib", "Movie Lib"], "Alphabetical", "Unwatched"
    )
    assert len(unwatched) == 3
    names = [x["name"] for x in unwatched]
    assert "Movie 2" in names
    assert "TV Series 1" in names
    assert "TV Series 2" in names


def test_combined_view_queries_errors(mock_db_file) -> None:
    from lan_streamer.db import (
        get_combined_next_up,
        get_combined_recently_added,
        get_combined_smart_row,
    )

    with patch("lan_streamer.db.get_session", side_effect=Exception("Database error")):
        assert get_combined_next_up(["TV Lib"]) == []
        assert get_combined_recently_added(["TV Lib"]) == []
        assert get_combined_smart_row(["TV Lib"], "Alphabetical", "All") == []
