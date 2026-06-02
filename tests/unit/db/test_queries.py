import pytest
from unittest.mock import patch

from lan_streamer import db
from lan_streamer.db.models import Series, Season, Episode


@pytest.fixture
def mock_db_file(tmp_path) -> None:
    return tmp_path / "library.db"


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
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("Mocked error")

        # These should catch the error and log it, not crash
        assert db.load_library("Lib") == {}
        db.save_library("Lib", {})
        db.update_episode_watched_status("path", True)


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
    for season in loaded["Test Series"]["seasons"].values():
        for ep in season["episodes"]:
            assert ep["watched"] is True

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
    with patch("lan_streamer.db.connection.get_session") as mock_session:
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
    from lan_streamer.db.models import Movie

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


def test_build_episode_dict(mock_db_file) -> None:
    from lan_streamer.db import _build_episode_dict, get_session

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
    assert result["episodes"][0]["name"] == "S01E01.mkv"
    assert result["episodes"][1]["name"] == "S01E02.mkv"


def test_build_series_dict(mock_db_file) -> None:
    from lan_streamer.db import _build_series_dict, get_session

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
    from lan_streamer.db.models import Movie

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


def test_is_movie(mock_db_file) -> None:
    from lan_streamer.db import is_movie, get_session
    from lan_streamer.db.models import Movie

    # Initially, it should return False
    assert is_movie("/movies/inception.mkv") is False

    with get_session() as session:
        movie = Movie(
            name="Inception",
            library_name="Movies",
            path="/movies/inception.mkv",
        )
        session.add(movie)
        session.flush()

    assert is_movie("/movies/inception.mkv") is True
    assert is_movie("/movies/other.mkv") is False


def test_db_edge_cases() -> None:
    # natural_sort_key with None
    assert db.natural_sort_key(None) == []


def test_db_more_error_paths() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("General DB Error")
        # Ensure these functions don't raise but log exceptions
        db.update_season_watched_status("Lib", "Show", "S1", True)
        db.update_series_watched_status("Lib", "Show", True)
        db.update_item_runtime(1, "episode", 30)
        db.sync_watched_from_jellyfin_data({"id1"}, {"/path1"}, {("Show", "Ep1")})


def test_get_next_episode(mock_db_file) -> None:
    from lan_streamer.db import get_session, get_next_episode

    with get_session() as session:
        series = Series(name="Show", library_name="Lib", poster_path="/sp.jpg")
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()

        ep1 = Episode(
            season_id=season.id,
            name="S01E01.mkv",
            path="/p/S01E01.mkv",
            tmdb_name="Ep 1",
            tmdb_number=1,
            runtime=45,
        )
        ep2 = Episode(
            season_id=season.id,
            name="S01E02.mkv",
            path="/p/S01E02.mkv",
            tmdb_name="Ep 2",
            tmdb_number=2,
            runtime=45,
        )
        session.add_all([ep1, ep2])
        session.commit()

    # Call get_next_episode on ep1 path
    result = get_next_episode("/p/S01E01.mkv")
    assert result is not None
    assert result["title"] == "Ep 2"
    assert result["season"] == "Season 1"
    assert result["episode_number"] == 2
    assert result["path"] == "/p/S01E02.mkv"
    assert result["poster_path"] == "/sp.jpg"
    assert result["runtime"] == 45

    # Call get_next_episode on ep2 path (which is the last episode)
    assert get_next_episode("/p/S01E02.mkv") is None


def test_get_next_episode_skips_placeholder(mock_db_file) -> None:
    from lan_streamer.db import get_session, get_next_episode

    with get_session() as session:
        series = Series(
            name="ShowPlaceholder", library_name="Lib", poster_path="/sp.jpg"
        )
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()

        ep1 = Episode(
            season_id=season.id,
            name="S01E01.mkv",
            path="/p/S01E01.mkv",
            tmdb_name="Ep 1",
            tmdb_number=1,
            runtime=45,
        )
        ep2 = Episode(
            season_id=season.id,
            name="S01E02 - TBA",
            path=None,
            tmdb_name="Ep 2",
            tmdb_number=2,
            runtime=45,
        )
        session.add_all([ep1, ep2])
        session.commit()

    # Call get_next_episode on ep1 path, should return None because ep2 has no file path
    assert get_next_episode("/p/S01E01.mkv") is None
