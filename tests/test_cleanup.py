import shutil
from lan_streamer import db


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
    # Repopulate
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

    # Delete Season 2 folder (which doesn't exist but we'll simulate it by having a DB entry with no folder)
    stats = db.cleanup_library(library_name, [str(root_dir)])
    # Season 2 path would be root_dir / "Series 1" / "Season 2"
    # It doesn't exist, so it should be removed.
    assert stats["seasons"] == 1
    assert stats["episodes"] == 1
