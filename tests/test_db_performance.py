from lan_streamer import db
from sqlalchemy import text


def test_wal_mode_enabled() -> None:
    db.init_db()
    with db.get_session() as session:
        result = session.execute(text("PRAGMA journal_mode")).fetchone()
        assert result[0].lower() == "wal"


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
                        },
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
    # Episodes are sorted by name
    assert s1["episodes"][0]["name"] == "Ep 1"
    assert s1["episodes"][0]["watched"] is True
    assert s1["episodes"][0]["date_added"] == 100

    show_b = loaded["Show B"]
    assert len(show_b["seasons"]) == 0


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

    # Sync by ID for E1, by Path for E2, leave E3 unwatched
    count = db.sync_watched_from_jellyfin_data({"jf1"}, {"/p2"}, set())
    assert count == 2

    loaded = db.load_library("Lib")
    eps = {ep["name"]: ep for ep in loaded["Show"]["seasons"]["S1"]["episodes"]}
    assert eps["E1"]["watched"] is True
    assert eps["E2"]["watched"] is True
    assert eps["E3"]["watched"] is False
