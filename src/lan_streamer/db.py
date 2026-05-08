import sqlite3
import logging
from pathlib import Path
from typing import Dict, Any
from contextlib import closing
from . import __version__ as DB_VERSION

logger = logging.getLogger(__name__)

DB_FILE = Path.home() / ".config" / "lan-streamer" / "library.db"


def get_connection():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> bool:
    """
    Initializes the database.
    Returns True if the database was recreated (triggering a need for sync).
    """
    recreated = False
    try:
        with closing(get_connection()) as conn:
            with conn:
                cursor = conn.cursor()

                # Create metadata table if it doesn't exist
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)

                # Get current DB version
                cursor.execute("SELECT value FROM metadata WHERE key = 'version'")
                row = cursor.fetchone()
                db_version = row["value"] if row else "0.0.0"

                # Check if we need to migrate/recreate
                # If version is < 0.2.0, we drop and recreate
                # Simplified version comparison:
                def is_less_than_0_2_0(v):
                    parts = [int(p) for p in v.split(".")]
                    if parts[0] < 0:
                        return True
                    if parts[0] == 0 and parts[1] < 2:
                        return True
                    return False

                if is_less_than_0_2_0(db_version):
                    logger.info(
                        f"Database version {db_version} is less than 0.2.0. Recreating database..."
                    )
                    cursor.execute("DROP TABLE IF EXISTS episodes")
                    cursor.execute("DROP TABLE IF EXISTS seasons")
                    cursor.execute("DROP TABLE IF EXISTS series")
                    cursor.execute("DROP TABLE IF EXISTS library")
                    recreated = True

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS series (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        library_name TEXT,
                        name TEXT,
                        jellyfin_id TEXT,
                        tmdb_id TEXT,
                        poster_path TEXT,
                        overview TEXT,
                        is_manual_match BOOLEAN DEFAULT 0,
                        UNIQUE(library_name, name)
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS seasons (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        series_id INTEGER,
                        name TEXT,
                        jellyfin_id TEXT,
                        poster_path TEXT,
                        FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE,
                        UNIQUE(series_id, name)
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS episodes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        season_id INTEGER,
                        name TEXT,
                        path TEXT,
                        jellyfin_id TEXT,
                        tmdb_episode_id TEXT,
                        watched BOOLEAN DEFAULT 0,
                        date_added INTEGER DEFAULT 0,
                        FOREIGN KEY(season_id) REFERENCES seasons(id) ON DELETE CASCADE,
                        UNIQUE(season_id, name),
                        UNIQUE(path)
                    )
                """)

                # Update version in database
                cursor.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('version', ?)",
                    (DB_VERSION,),
                )

                # Ensure date_added column exists (for very old DBs that might still exist)
                try:
                    cursor.execute(
                        "ALTER TABLE episodes ADD COLUMN date_added INTEGER DEFAULT 0"
                    )
                except sqlite3.OperationalError:
                    pass

                # Ensure tmdb_id column exists on series (migration: tvdb_id → tmdb_id)
                try:
                    cursor.execute("ALTER TABLE series ADD COLUMN tmdb_id TEXT")
                except sqlite3.OperationalError:
                    pass
                # Migrate old tvdb_id data to tmdb_id if the old column exists
                try:
                    cursor.execute(
                        "UPDATE series SET tmdb_id = tvdb_id WHERE tmdb_id IS NULL AND tvdb_id IS NOT NULL"
                    )
                except sqlite3.OperationalError:
                    pass

                # Ensure tmdb_episode_id column exists on episodes (migration: tvdb_episode_id → tmdb_episode_id)
                try:
                    cursor.execute(
                        "ALTER TABLE episodes ADD COLUMN tmdb_episode_id TEXT"
                    )
                except sqlite3.OperationalError:
                    pass
                # Migrate old tvdb_episode_id data to tmdb_episode_id if old column exists
                try:
                    cursor.execute(
                        "UPDATE episodes SET tmdb_episode_id = tvdb_episode_id WHERE tmdb_episode_id IS NULL AND tvdb_episode_id IS NOT NULL"
                    )
                except sqlite3.OperationalError:
                    pass

    except Exception as e:
        logger.error(f"Error initializing database: {e}")

    return recreated


def load_library(library_name: str) -> Dict[str, Any]:
    """
    Loads the library from the database and constructs a nested dictionary structure.
    """
    library = {}
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM series WHERE library_name = ?", (library_name,)
            )
            series_rows = cursor.fetchall()

            for series_row in series_rows:
                series_name = series_row["name"]
                library[series_name] = {
                    "metadata": {
                        "jellyfin_id": series_row["jellyfin_id"],
                        "tmdb_id": series_row["tmdb_id"]
                        if "tmdb_id" in series_row.keys()
                        else None,
                        "poster_path": series_row["poster_path"],
                        "overview": series_row["overview"],
                        "is_manual_match": bool(series_row["is_manual_match"]),
                    },
                    "seasons": {},
                }

                cursor.execute(
                    "SELECT * FROM seasons WHERE series_id = ?", (series_row["id"],)
                )
                season_rows = cursor.fetchall()

                for season_row in season_rows:
                    season_name = season_row["name"]
                    library[series_name]["seasons"][season_name] = {
                        "metadata": {
                            "jellyfin_id": season_row["jellyfin_id"],
                            "poster_path": season_row["poster_path"],
                        },
                        "episodes": [],
                    }

                    cursor.execute(
                        "SELECT * FROM episodes WHERE season_id = ?",
                        (season_row["id"],),
                    )
                    episode_rows = cursor.fetchall()

                    for episode_row in episode_rows:
                        date_added = (
                            episode_row["date_added"]
                            if "date_added" in episode_row.keys()
                            else 0
                        )
                        keys = episode_row.keys()
                        library[series_name]["seasons"][season_name]["episodes"].append(
                            {
                                "name": episode_row["name"],
                                "path": episode_row["path"],
                                "jellyfin_id": episode_row["jellyfin_id"],
                                "tmdb_episode_id": episode_row["tmdb_episode_id"]
                                if "tmdb_episode_id" in keys
                                else None,
                                "watched": bool(episode_row["watched"]),
                                "date_added": date_added,
                            }
                        )

                    library[series_name]["seasons"][season_name]["episodes"].sort(
                        key=lambda x: x["name"]
                    )

    except Exception as e:
        logger.error(f"Error loading library '{library_name}' from database: {e}")

    return library


def save_library(library_name: str, library: Dict[str, Any]):
    """
    Updates the database for the given library name using upserts.
    Preserves existing data and only deletes what is no longer present.
    """
    try:
        with closing(get_connection()) as conn:
            with conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")

                # Create temporary tables to track touched IDs
                cursor.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS touched_series (id INTEGER)"
                )
                cursor.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS touched_seasons (id INTEGER)"
                )
                cursor.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS touched_episodes (id INTEGER)"
                )

                cursor.execute("DELETE FROM touched_series")
                cursor.execute("DELETE FROM touched_seasons")
                cursor.execute("DELETE FROM touched_episodes")

                for series_name, series_data in library.items():
                    series_metadata = series_data.get("metadata", {})
                    # Upsert Series
                    cursor.execute(
                        """
                        INSERT INTO series (library_name, name, jellyfin_id, tmdb_id, poster_path, overview, is_manual_match)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(library_name, name) DO UPDATE SET
                            jellyfin_id = excluded.jellyfin_id,
                            tmdb_id = excluded.tmdb_id,
                            poster_path = excluded.poster_path,
                            overview = excluded.overview,
                            is_manual_match = excluded.is_manual_match
                        RETURNING id
                    """,
                        (
                            library_name,
                            series_name,
                            series_metadata.get("jellyfin_id"),
                            series_metadata.get("tmdb_id"),
                            series_metadata.get("poster_path"),
                            series_metadata.get("overview"),
                            1 if series_metadata.get("is_manual_match") else 0,
                        ),
                    )
                    series_id = cursor.fetchone()[0]
                    cursor.execute(
                        "INSERT INTO touched_series (id) VALUES (?)", (series_id,)
                    )

                    for season_name, season_data in series_data.get(
                        "seasons", {}
                    ).items():
                        season_metadata = season_data.get("metadata", {})
                        # Upsert Season
                        cursor.execute(
                            """
                            INSERT INTO seasons (series_id, name, jellyfin_id, poster_path)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(series_id, name) DO UPDATE SET
                                jellyfin_id = excluded.jellyfin_id,
                                poster_path = excluded.poster_path
                            RETURNING id
                        """,
                            (
                                series_id,
                                season_name,
                                season_metadata.get("jellyfin_id"),
                                season_metadata.get("poster_path"),
                            ),
                        )
                        season_id = cursor.fetchone()[0]
                        cursor.execute(
                            "INSERT INTO touched_seasons (id) VALUES (?)", (season_id,)
                        )

                        for episode in season_data.get("episodes", []):
                            # Upsert Episode — preserve existing watched=True when scan sets False
                            cursor.execute(
                                """
                                INSERT INTO episodes (season_id, name, path, jellyfin_id, tmdb_episode_id, watched, date_added)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(path) DO UPDATE SET
                                    season_id = excluded.season_id,
                                    name = excluded.name,
                                    jellyfin_id = excluded.jellyfin_id,
                                    tmdb_episode_id = excluded.tmdb_episode_id,
                                    watched = MAX(watched, excluded.watched),
                                    date_added = excluded.date_added
                                ON CONFLICT(season_id, name) DO UPDATE SET
                                    path = excluded.path,
                                    jellyfin_id = excluded.jellyfin_id,
                                    tmdb_episode_id = excluded.tmdb_episode_id,
                                    watched = MAX(watched, excluded.watched),
                                    date_added = excluded.date_added
                                RETURNING id
                            """,
                                (
                                    season_id,
                                    episode["name"],
                                    episode["path"],
                                    episode.get("jellyfin_id"),
                                    episode.get("tmdb_episode_id"),
                                    1 if episode.get("watched") else 0,
                                    episode.get("date_added", 0),
                                ),
                            )
                            episode_id = cursor.fetchone()[0]
                            cursor.execute(
                                "INSERT INTO touched_episodes (id) VALUES (?)",
                                (episode_id,),
                            )

                # Cleanup stale entries
                # Delete episodes not in current scan for this library
                cursor.execute(
                    """
                    DELETE FROM episodes 
                    WHERE id NOT IN (SELECT id FROM touched_episodes)
                    AND season_id IN (
                        SELECT id FROM seasons 
                        WHERE series_id IN (
                            SELECT id FROM series WHERE library_name = ?
                        )
                    )
                """,
                    (library_name,),
                )

                # Delete seasons not in current scan for this library
                cursor.execute(
                    """
                    DELETE FROM seasons 
                    WHERE id NOT IN (SELECT id FROM touched_seasons)
                    AND series_id IN (
                        SELECT id FROM series WHERE library_name = ?
                    )
                """,
                    (library_name,),
                )

                # Delete series not in current scan for this library
                cursor.execute(
                    """
                    DELETE FROM series 
                    WHERE id NOT IN (SELECT id FROM touched_series)
                    AND library_name = ?
                """,
                    (library_name,),
                )

                logger.info(
                    f"Library '{library_name}' successfully updated in database."
                )
    except Exception as e:
        logger.error(f"Error saving library '{library_name}' to database: {e}")


def update_episode_watched_status(path: str, watched: bool):
    try:
        with closing(get_connection()) as conn:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE episodes SET watched = ? WHERE path = ?",
                    (1 if watched else 0, path),
                )
    except Exception as e:
        logger.error(f"Error updating watched status for {path}: {e}")


def sync_watched_from_paths(watched_paths: set) -> int:
    """
    Bulk-updates watched=True for all episodes whose file path is in watched_paths,
    and watched=False for all others.
    Returns the total number of rows updated.
    """
    if not watched_paths:
        return 0
    updated = 0
    try:
        with closing(get_connection()) as conn:
            with conn:
                cursor = conn.cursor()
                # Mark matching paths as watched
                cursor.execute(
                    f"UPDATE episodes SET watched = 1 WHERE path IN ({','.join('?' * len(watched_paths))})",
                    tuple(watched_paths),
                )
                updated = cursor.rowcount
                logger.info(
                    f"sync_watched_from_paths: marked {updated} episodes as watched."
                )
    except Exception as e:
        logger.error(f"Error in sync_watched_from_paths: {e}")
    return updated
