import sqlite3
import pytest
from contextlib import closing
from lan_streamer import db


@pytest.fixture
def mock_db_file(tmp_path, monkeypatch):
    test_db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", test_db_path)
    return test_db_path


def test_init_db(mock_db_file):
    db.init_db()
    assert mock_db_file.exists()

    # Init again to test idempotency
    db.init_db()


def test_save_and_load_library(mock_db_file):
    db.init_db()

    test_lib = {
        "Test Series": {
            "metadata": {
                "jellyfin_id": "series123",
                "poster_path": "/img.jpg",
                "overview": "A test series",
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
    db.init_db()
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


def test_db_error_handling(mock_db_file, monkeypatch):
    def mock_connect(*args, **kwargs):
        import sqlite3

        raise sqlite3.OperationalError("Mocked error")

    monkeypatch.setattr("sqlite3.connect", mock_connect)

    # These should catch the error and log it, not crash
    db.init_db()
    assert db.load_library("Lib") == {}
    db.save_library("Lib", {})
    db.update_episode_watched_status("path", True)


def test_db_version_sync():
    from lan_streamer import __version__

    assert db.DB_VERSION == __version__


def test_sync_watched_from_paths(mock_db_file, monkeypatch):
    from lan_streamer.db import sync_watched_from_jellyfin_data, get_connection

    db.init_db()
    with closing(get_connection()) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO series (name, library_name) VALUES ('Show', 'Lib')"
            )
            series_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO seasons (series_id, name) VALUES (?, 'Season 1')",
                (series_id,),
            )
            season_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO episodes (season_id, name, path, watched) VALUES (?, 'Ep1', '/path1', 0)",
                (season_id,),
            )
            cursor.execute(
                "INSERT INTO episodes (season_id, name, path, watched) VALUES (?, 'Ep2', '/path2', 0)",
                (season_id,),
            )

    # Test with one path
    count = sync_watched_from_jellyfin_data(set(), {"/path1"}, set())
    assert count == 1
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT watched FROM episodes WHERE path='/path1'")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT watched FROM episodes WHERE path='/path2'")
        assert cursor.fetchone()[0] == 0

    # Test with name-based match
    # 'Ep2' in 'Season 1' of 'Show' -> needs series name 'Show'
    count = sync_watched_from_jellyfin_data(set(), set(), {("Show", "Ep2")})
    assert count == 1
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT watched FROM episodes WHERE path='/path2'")
        assert cursor.fetchone()[0] == 1

    # Test with empty sets
    assert sync_watched_from_jellyfin_data(set(), set(), set()) == 0


def test_is_less_than_0_2_0_negative_version(mock_db_file, monkeypatch):
    from lan_streamer.db import init_db
    # To hit line 50, we need to mock cursor.fetchone to return a version starting with negative
    # Actually, the function is defined INSIDE init_db. We can just test init_db with a mock version.

    with closing(sqlite3.connect(mock_db_file)) as conn:
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata (key, value) VALUES ('version', '-1.0.0')")
        conn.commit()

    # This should trigger recreation
    recreated = init_db()
    assert recreated is True


def test_sync_watched_from_paths_exception(monkeypatch):
    from lan_streamer.db import sync_watched_from_jellyfin_data

    def mock_get_conn():
        raise Exception("DB Error")

    monkeypatch.setattr("lan_streamer.db.get_connection", mock_get_conn)
    assert sync_watched_from_jellyfin_data(set(), {"/path"}, set()) == 0


def test_get_all_episodes_with_jellyfin_id(mock_db_file):
    from lan_streamer.db import get_all_episodes_with_jellyfin_id

    db.init_db()
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
    eps = get_all_episodes_with_jellyfin_id()
    assert len(eps) == 1
    assert eps[0]["jellyfin_id"] == "jf1"


def test_update_season_watched_status(mock_db_file):
    db.init_db()
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
