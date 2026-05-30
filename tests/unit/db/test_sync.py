import pytest

from lan_streamer import db
from lan_streamer.db.models import Series, Season, Episode


@pytest.fixture
def mock_db_file(tmp_path) -> None:
    return tmp_path / "library.db"


def test_sync_watched_from_paths(mock_db_file) -> None:
    from lan_streamer.db import sync_watched_from_jellyfin_data, get_session

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

    count = sync_watched_from_jellyfin_data(set(), {"/path1"}, set())
    assert count == 1

    loaded = db.load_library("Lib")
    eps = loaded["Show"]["seasons"]["Season 1"]["episodes"]
    ep1_data = next(e for e in eps if e["path"] == "/path1")
    ep2_data = next(e for e in eps if e["path"] == "/path2")
    assert ep1_data["watched"] is True
    assert ep2_data["watched"] is False

    count = sync_watched_from_jellyfin_data(set(), set(), {("Show", "Ep2")})
    assert count == 1

    loaded = db.load_library("Lib")
    eps = loaded["Show"]["seasons"]["Season 1"]["episodes"]
    ep2_data = next(e for e in eps if e["path"] == "/path2")
    assert ep2_data["watched"] is True

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


def test_sync_watched_names_bulk() -> None:
    db.init_db()
    test_lib = {
        "Show": {
            "seasons": {
                "S1": {
                    "episodes": [
                        {"name": "E1", "path": "/p1", "watched": False},
                        {"name": "E2", "path": "/p2", "watched": False},
                    ]
                }
            }
        }
    }
    db.save_library("Lib", test_lib)

    watched_names = {("Show", "E1"), ("Show", "E2")}
    count = db.sync_watched_from_jellyfin_data(set(), set(), watched_names)
    assert count == 2

    loaded = db.load_library("Lib")
    eps = loaded["Show"]["seasons"]["S1"]["episodes"]
    assert all(ep["watched"] for ep in eps)


def test_sync_watched_ids_paths() -> None:
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
                            "watched": False,
                        },
                        {
                            "name": "E2",
                            "path": "/p2",
                            "jellyfin_id": "jf2",
                            "watched": False,
                        },
                        {
                            "name": "E3",
                            "path": "/p3",
                            "jellyfin_id": "jf3",
                            "watched": False,
                        },
                    ]
                }
            }
        }
    }
    db.save_library("Lib", test_lib)

    count = db.sync_watched_from_jellyfin_data({"jf1"}, {"/p2"}, set())
    assert count == 2

    loaded = db.load_library("Lib")
    eps = {ep["name"]: ep for ep in loaded["Show"]["seasons"]["S1"]["episodes"]}
    assert eps["E1"]["watched"] is True
    assert eps["E2"]["watched"] is True
    assert eps["E3"]["watched"] is False


def test_sync_watched_by_ids(mock_db_file) -> None:
    from lan_streamer.db import _sync_watched_by_ids, get_session

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
