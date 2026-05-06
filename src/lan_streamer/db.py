import sqlite3
import logging
from pathlib import Path
from typing import Dict, Any
from contextlib import closing

logger = logging.getLogger(__name__)

DB_FILE = Path.home() / ".config" / "lan-streamer" / "library.db"


def get_connection():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    try:
        with closing(get_connection()) as conn:
            with conn:
                cursor = conn.cursor()

                # Drop old flat table if it exists
                cursor.execute("DROP TABLE IF EXISTS library")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS series (
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
                    CREATE TABLE IF NOT EXISTS seasons (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        series_id INTEGER,
                        name TEXT,
                        jellyfin_id TEXT,
                        poster_path TEXT,
                        FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS episodes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        season_id INTEGER,
                        name TEXT,
                        path TEXT,
                        jellyfin_id TEXT,
                        watched BOOLEAN DEFAULT 0,
                        date_added INTEGER DEFAULT 0,
                        FOREIGN KEY(season_id) REFERENCES seasons(id) ON DELETE CASCADE
                    )
                """)

                # Migrations for existing databases
                try:
                    cursor.execute(
                        "ALTER TABLE episodes ADD COLUMN date_added INTEGER DEFAULT 0"
                    )
                except sqlite3.OperationalError:
                    pass

                try:
                    cursor.execute(
                        "ALTER TABLE series ADD COLUMN is_manual_match BOOLEAN DEFAULT 0"
                    )
                except sqlite3.OperationalError:
                    pass
    except Exception as e:
        logger.error(f"Error initializing database: {e}")


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
                        # Fallback to 0 if 'date_added' doesn't exist in row (should be handled by migration, but just in case)
                        date_added = (
                            episode_row["date_added"]
                            if "date_added" in episode_row.keys()
                            else 0
                        )
                        library[series_name]["seasons"][season_name]["episodes"].append(
                            {
                                "name": episode_row["name"],
                                "path": episode_row["path"],
                                "jellyfin_id": episode_row["jellyfin_id"],
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
    Clears the database for the given library name and populates it.
    """
    try:
        with closing(get_connection()) as conn:
            with conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute(
                    "DELETE FROM series WHERE library_name = ?", (library_name,)
                )

                for series_name, series_data in library.items():
                    series_metadata = series_data.get("metadata", {})
                    cursor.execute(
                        "INSERT INTO series (library_name, name, jellyfin_id, poster_path, overview, is_manual_match) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            library_name,
                            series_name,
                            series_metadata.get("jellyfin_id"),
                            series_metadata.get("poster_path"),
                            series_metadata.get("overview"),
                            1 if series_metadata.get("is_manual_match") else 0,
                        ),
                    )
                    series_id = cursor.lastrowid

                    for season_name, season_data in series_data.get(
                        "seasons", {}
                    ).items():
                        season_metadata = season_data.get("metadata", {})
                        cursor.execute(
                            "INSERT INTO seasons (series_id, name, jellyfin_id, poster_path) VALUES (?, ?, ?, ?)",
                            (
                                series_id,
                                season_name,
                                season_metadata.get("jellyfin_id"),
                                season_metadata.get("poster_path"),
                            ),
                        )
                        season_id = cursor.lastrowid

                        for episode in season_data.get("episodes", []):
                            cursor.execute(
                                "INSERT INTO episodes (season_id, name, path, jellyfin_id, watched, date_added) VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    season_id,
                                    episode["name"],
                                    episode["path"],
                                    episode.get("jellyfin_id"),
                                    1 if episode.get("watched") else 0,
                                    episode.get("date_added", 0),
                                ),
                            )
                logger.info(f"Library '{library_name}' successfully saved to database.")
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
