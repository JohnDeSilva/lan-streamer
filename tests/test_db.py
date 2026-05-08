import pytest
from unittest.mock import patch
from lan_streamer import db
from lan_streamer.models import Series, Season, Episode


@pytest.fixture
def mock_db_file(tmp_path):
    # Already handled by conftest.py autouse fixture,
    # but kept here for tests that explicitly use it.
    return tmp_path / "library.db"


def test_init_db(mock_db_file):
    db.init_db()
    assert mock_db_file.parent.exists()


def test_save_and_load_library(mock_db_file):
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


def test_update_watched_status(mock_db_file):
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


def test_db_error_handling(mock_db_file):
    # Mocking get_session to raise an exception
    with patch("lan_streamer.db.get_session") as mock_session:
        mock_session.side_effect = Exception("Mocked error")

        # These should catch the error and log it, not crash
        assert db.load_library("Lib") == {}
        db.save_library("Lib", {})
        db.update_episode_watched_status("path", True)


def test_sync_watched_from_paths(mock_db_file):
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


def test_get_all_episodes_with_jellyfin_id(mock_db_file):
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


def test_update_season_watched_status(mock_db_file):
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
