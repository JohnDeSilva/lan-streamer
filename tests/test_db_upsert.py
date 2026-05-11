from lan_streamer import db


def test_save_library_upsert():
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


def test_upsert_preserves_ids_across_libraries():
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
