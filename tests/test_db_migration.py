import pytest
import sqlite3
from lan_streamer import db


@pytest.fixture
def old_db(tmp_path, monkeypatch):
    test_db = tmp_path / "old_library.db"
    monkeypatch.setattr(db, "DB_FILE", test_db)

    # Create an OLD schema DB
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            library_name TEXT,
            name TEXT,
            jellyfin_id TEXT,
            poster_path TEXT,
            overview TEXT,
            is_manual_match BOOLEAN DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER,
            name TEXT,
            jellyfin_id TEXT,
            poster_path TEXT,
            FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id INTEGER,
            name TEXT,
            path TEXT,
            jellyfin_id TEXT,
            watched BOOLEAN DEFAULT 0
        )
    """)
    # Insert some data
    cursor.execute("INSERT INTO series (library_name, name) VALUES ('Lib', 'Show')")
    cursor.execute("INSERT INTO seasons (series_id, name) VALUES (1, 'Season 1')")
    cursor.execute(
        "INSERT INTO episodes (season_id, name, path) VALUES (1, 'Ep 1', '/p1')"
    )
    conn.commit()
    conn.close()

    return test_db


def test_migration_to_unique_constraints(old_db):
    # Run init_db which should trigger recreate (version will be 0.0.0 initially)
    recreated = db.init_db()
    assert recreated is True

    # Verify the schema has UNIQUE constraints now
    conn = sqlite3.connect(old_db)
    cursor = conn.cursor()

    # Check series table unique constraint
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='series'")
    sql = cursor.fetchone()[0]
    assert "UNIQUE(library_name, name)" in sql

    # Check version is updated
    cursor.execute("SELECT value FROM metadata WHERE key = 'version'")
    assert cursor.fetchone()[0] == db.DB_VERSION

    # Verify data was NOT preserved (as per new strategy: drop and recreate)
    cursor.execute("SELECT COUNT(*) FROM series")
    assert cursor.fetchone()[0] == 0

    conn.close()


def test_migration_already_migrated(old_db):
    # Run migration once (recreate)
    db.init_db()
    # Run again - should NOT recreate (return False)
    recreated = db.init_db()
    assert recreated is False

    conn = sqlite3.connect(old_db)
    cursor = conn.cursor()
    # Insert one item
    cursor.execute("INSERT INTO series (library_name, name) VALUES ('L', 'S')")
    conn.commit()
    conn.close()

    # Run again - should still be False and data preserved
    recreated = db.init_db()
    assert recreated is False

    conn = sqlite3.connect(old_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM series")
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_migration_older_version_trigger(tmp_path, monkeypatch):
    test_db = tmp_path / "old_version.db"
    monkeypatch.setattr(db, "DB_FILE", test_db)

    # Create DB with older version
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("INSERT INTO metadata (key, value) VALUES ('version', '0.1.0')")
    cursor.execute(
        "CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT)"
    )  # Old schema
    cursor.execute("INSERT INTO series (name) VALUES ('Test')")
    conn.commit()
    conn.close()

    # Run init_db - should trigger recreate because 0.1.0 < 0.2.0
    recreated = db.init_db()
    assert recreated is True

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    # Check version is updated
    cursor.execute("SELECT value FROM metadata WHERE key = 'version'")
    assert cursor.fetchone()[0] == db.DB_VERSION
    # Check data is gone
    cursor.execute("SELECT COUNT(*) FROM series")
    assert cursor.fetchone()[0] == 0
    conn.close()
