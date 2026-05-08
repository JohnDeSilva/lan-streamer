import sqlite3
import logging
import time
import re
from pathlib import Path
from typing import Dict, Any
from contextlib import closing
from . import __version__ as DB_VERSION

logger = logging.getLogger(__name__)

DB_FILE = Path.home() / ".config" / "lan-streamer" / "library.db"


def natural_sort_key(s):
    """
    Key function for natural sorting (e.g., "Season 2" < "Season 10").
    """
    if s is None:
        return []
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split("([0-9]+)", str(s))
    ]


def get_connection():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    # Enable WAL mode and busy timeout for better concurrency and responsiveness
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def version_to_tuple(version: str):
    try:
        return tuple(map(int, (version or "0.0.0").split(".")))
    except ValueError, AttributeError:
        return (0, 0, 0)


def migrate_0_3_0(cursor):
    """TVDB to TMDB migration."""
    try:
        cursor.execute("ALTER TABLE series ADD COLUMN tmdb_identifier TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute(
            "UPDATE series SET tmdb_identifier = tvdb_id WHERE tmdb_identifier IS NULL AND tvdb_id IS NOT NULL"
        )
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE episodes ADD COLUMN tmdb_episode_identifier TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute(
            "UPDATE episodes SET tmdb_episode_identifier = tvdb_episode_id WHERE tmdb_episode_identifier IS NULL AND tvdb_episode_id IS NOT NULL"
        )
    except sqlite3.OperationalError:
        pass


def migrate_0_3_1(cursor):
    """Added tmdb_name, tmdb_number, and replaced is_manual_match with locked_metadata."""
    try:
        cursor.execute("ALTER TABLE episodes ADD COLUMN tmdb_name TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE episodes ADD COLUMN tmdb_number INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute(
            "ALTER TABLE series ADD COLUMN locked_metadata BOOLEAN DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute(
            "UPDATE series SET locked_metadata = is_manual_match WHERE is_manual_match IS NOT NULL"
        )
    except sqlite3.OperationalError:
        pass


def migrate_0_4_0(cursor):
    """Added tmdb_name and renamed tmdb_id/tmdb_episode_id."""
    try:
        cursor.execute("ALTER TABLE series ADD COLUMN tmdb_name TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE series RENAME COLUMN tmdb_id TO tmdb_identifier")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute(
            "ALTER TABLE episodes RENAME COLUMN tmdb_episode_id TO tmdb_episode_identifier"
        )
    except sqlite3.OperationalError:
        pass


def migrate_0_4_1(cursor):
    """Added indexes for performance."""
    try:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodes_jellyfin_id ON episodes(jellyfin_id)"
        )
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_seasons_series_id ON seasons(series_id)"
        )
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodes_season_id ON episodes(season_id)"
        )
    except sqlite3.OperationalError:
        pass


def init_db() -> bool:
    """
    Initializes the database.
    Returns True if the database was recreated (triggering a need for sync).
    """
    recreated = False
    start_time = time.time()
    logger.info(f"Initializing database at {DB_FILE}")
    try:
        with closing(get_connection()) as connection:
            with connection:
                cursor = connection.cursor()

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
                database_version = row["value"] if row else "0.0.0"

                # Check if we need to migrate/recreate
                # If version is < 0.2.0, we drop and recreate
                # Simplified version comparison:

                if version_to_tuple(database_version) < version_to_tuple("0.2.0"):
                    logger.info(
                        f"Database version {database_version} is less than 0.2.0. Recreating database..."
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
                        tmdb_identifier TEXT,
                        poster_path TEXT,
                        overview TEXT,
                        tmdb_name TEXT,
                        locked_metadata BOOLEAN DEFAULT 0,
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
                        tmdb_episode_identifier TEXT,
                        tmdb_name TEXT,
                        tmdb_number INTEGER,
                        watched BOOLEAN DEFAULT 0,
                        date_added INTEGER DEFAULT 0,
                        FOREIGN KEY(season_id) REFERENCES seasons(id) ON DELETE CASCADE,
                        UNIQUE(season_id, name),
                        UNIQUE(path)
                    )
                """)

                # Update version in database
                # Staged Migrations
                migrations = [
                    ("0.3.0", migrate_0_3_0),
                    ("0.3.1", migrate_0_3_1),
                    ("0.4.0", migrate_0_4_0),
                    ("0.4.1", migrate_0_4_1),
                ]

                current_version = version_to_tuple(database_version)
                for target_v_str, migrate_func in migrations:
                    target_v = version_to_tuple(target_v_str)
                    # Run if DB is older, OR if it's the current version (to catch incremental updates)
                    if current_version < target_v or (
                        current_version == target_v and target_v_str == DB_VERSION
                    ):
                        logger.info(f"Applying migration {target_v_str}...")
                        migrate_func(cursor)

                # Always ensure the version is set to the current app version
                cursor.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('version', ?)",
                    (DB_VERSION,),
                )
        duration = time.time() - start_time
        logger.info(f"Database initialization complete in {duration:.3f}s")

    except Exception as e:
        logger.error(f"Error initializing database: {e}")

    return recreated


def load_library(library_name: str) -> Dict[str, Any]:
    """
    Loads the library from the database and constructs a nested dictionary structure.
    Uses a single JOIN query for maximum performance.
    """
    start_time = time.time()
    library_data = {}
    stats = {"series": 0, "seasons": 0, "episodes": 0}
    try:
        with closing(get_connection()) as connection:
            cursor = connection.cursor()

            # Single query to fetch everything
            cursor.execute(
                """
                SELECT 
                    series.id as series_id, series.name as series_name, series.jellyfin_id as series_jellyfin_id,
                    series.tmdb_identifier as series_tmdb_identifier, series.poster_path as series_poster_path,
                    series.overview as series_overview, series.tmdb_name as series_tmdb_name,
                    series.locked_metadata as series_locked_metadata,
                    seasons.id as season_id, seasons.name as season_name, seasons.jellyfin_id as season_jellyfin_id,
                    seasons.poster_path as season_poster_path,
                    episodes.id as episode_id, episodes.name as episode_name, episodes.path as episode_path,
                    episodes.jellyfin_id as episode_jellyfin_id, episodes.tmdb_episode_identifier,
                    episodes.tmdb_name as episode_tmdb_name, episodes.tmdb_number as episode_tmdb_number,
                    episodes.watched as episode_watched, episodes.date_added as episode_date_added
                FROM series
                LEFT JOIN seasons ON series.id = seasons.series_id
                LEFT JOIN episodes ON seasons.id = episodes.season_id
                WHERE series.library_name = ?
                ORDER BY series.name, seasons.name, episodes.name
            """,
                (library_name,),
            )

            rows = cursor.fetchall()

            # Process rows to build the nested structure
            for row in rows:
                series_name = row["series_name"]
                if series_name not in library_data:
                    stats["series"] += 1
                    library_data[series_name] = {
                        "metadata": {
                            "jellyfin_id": row["series_jellyfin_id"],
                            "tmdb_identifier": row["series_tmdb_identifier"],
                            "poster_path": row["series_poster_path"],
                            "overview": row["series_overview"],
                            "tmdb_name": row["series_tmdb_name"],
                            "locked_metadata": bool(row["series_locked_metadata"]),
                        },
                        "seasons": {},
                    }

                season_name = row["season_name"]
                if season_name is None:
                    continue

                if season_name not in library_data[series_name]["seasons"]:
                    stats["seasons"] += 1
                    library_data[series_name]["seasons"][season_name] = {
                        "metadata": {
                            "jellyfin_id": row["season_jellyfin_id"],
                            "poster_path": row["season_poster_path"],
                        },
                        "episodes": [],
                    }

                episode_name = row["episode_name"]
                if episode_name is None:
                    continue

                stats["episodes"] += 1
                library_data[series_name]["seasons"][season_name]["episodes"].append(
                    {
                        "name": episode_name,
                        "path": row["episode_path"],
                        "jellyfin_id": row["episode_jellyfin_id"],
                        "tmdb_episode_identifier": row["tmdb_episode_identifier"],
                        "tmdb_name": row["episode_tmdb_name"],
                        "tmdb_number": row["episode_tmdb_number"],
                        "watched": bool(row["episode_watched"]),
                        "date_added": row["episode_date_added"] or 0,
                    }
                )

            # Ensure episodes within each season are naturally sorted
            for s_name in library_data:
                for sea_name in library_data[s_name]["seasons"]:
                    library_data[s_name]["seasons"][sea_name]["episodes"].sort(
                        key=lambda x: natural_sort_key(x["name"])
                    )

        duration = time.time() - start_time
        logger.info(
            f"Loaded library '{library_name}' in {duration:.3f}s: {stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes."
        )

    except Exception as e:
        logger.error(f"Error loading library '{library_name}' from database: {e}")

    return library_data


def save_library(library_name: str, library: Dict[str, Any]):
    """
    Updates the database for the given library name using upserts.
    Preserves existing data and only deletes what is no longer present.
    """
    start_time = time.time()
    stats = {"series": 0, "seasons": 0, "episodes": 0, "deleted": 0}
    try:
        with closing(get_connection()) as connection:
            with connection:
                cursor = connection.cursor()
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
                        INSERT INTO series (library_name, name, jellyfin_id, tmdb_identifier, poster_path, overview, tmdb_name, locked_metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(library_name, name) DO UPDATE SET
                            jellyfin_id = excluded.jellyfin_id,
                            tmdb_identifier = excluded.tmdb_identifier,
                            poster_path = excluded.poster_path,
                            overview = excluded.overview,
                            tmdb_name = excluded.tmdb_name,
                            locked_metadata = excluded.locked_metadata
                        RETURNING id
                    """,
                        (
                            library_name,
                            series_name,
                            series_metadata.get("jellyfin_id"),
                            series_metadata.get("tmdb_identifier"),
                            series_metadata.get("poster_path"),
                            series_metadata.get("overview"),
                            series_metadata.get("tmdb_name"),
                            1 if series_metadata.get("locked_metadata") else 0,
                        ),
                    )
                    series_id = cursor.fetchone()[0]
                    stats["series"] += 1
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
                        stats["seasons"] += 1
                        cursor.execute(
                            "INSERT INTO touched_seasons (id) VALUES (?)", (season_id,)
                        )

                        for episode in season_data.get("episodes", []):
                            # Upsert Episode — preserve existing watched=True when scan sets False
                            cursor.execute(
                                """
                                INSERT INTO episodes (season_id, name, path, jellyfin_id, tmdb_episode_identifier, tmdb_name, tmdb_number, watched, date_added)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(path) DO UPDATE SET
                                    season_id = excluded.season_id,
                                    name = excluded.name,
                                    jellyfin_id = excluded.jellyfin_id,
                                    tmdb_episode_identifier = excluded.tmdb_episode_identifier,
                                    tmdb_name = excluded.tmdb_name,
                                    tmdb_number = excluded.tmdb_number,
                                    watched = MAX(watched, excluded.watched),
                                    date_added = excluded.date_added
                                ON CONFLICT(season_id, name) DO UPDATE SET
                                    path = excluded.path,
                                    jellyfin_id = excluded.jellyfin_id,
                                    tmdb_episode_identifier = excluded.tmdb_episode_identifier,
                                    tmdb_name = excluded.tmdb_name,
                                    tmdb_number = excluded.tmdb_number,
                                    watched = MAX(watched, excluded.watched),
                                    date_added = excluded.date_added
                                RETURNING id
                            """,
                                (
                                    season_id,
                                    episode["name"],
                                    episode["path"],
                                    episode.get("jellyfin_id"),
                                    episode.get("tmdb_episode_identifier"),
                                    episode.get("tmdb_name"),
                                    episode.get("tmdb_number"),
                                    1 if episode.get("watched") else 0,
                                    episode.get("date_added", 0),
                                ),
                            )
                            episode_id = cursor.fetchone()[0]
                            stats["episodes"] += 1
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
                stats["deleted"] += cursor.rowcount

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
                stats["deleted"] += cursor.rowcount

                # Delete series not in current scan for this library
                cursor.execute(
                    """
                    DELETE FROM series 
                    WHERE id NOT IN (SELECT id FROM touched_series)
                    AND library_name = ?
                """,
                    (library_name,),
                )
                stats["deleted"] += cursor.rowcount

                duration = time.time() - start_time
                logger.info(
                    f"Library '{library_name}' updated in {duration:.3f}s: "
                    f"{stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes saved. "
                    f"{stats['deleted']} stale items removed."
                )
    except Exception as e:
        logger.error(f"Error saving library '{library_name}' to database: {e}")


def update_episode_watched_status(path: str, watched: bool):
    try:
        logger.info(f"Updating watched status for {path} to {watched}")
        with closing(get_connection()) as connection:
            with connection:
                cursor = connection.cursor()
                cursor.execute(
                    "UPDATE episodes SET watched = ? WHERE path = ?",
                    (1 if watched else 0, path),
                )
    except Exception as e:
        logger.error(f"Error updating watched status for {path}: {e}")


def update_season_watched_status(
    library_name: str, series_name: str, season_name: str, watched: bool
):
    """
    Bulk updates the watched status for all episodes in a specific season.
    """
    try:
        logger.info(
            f"Updating watched status for {series_name} - {season_name} in {library_name} to {watched}"
        )
        with closing(get_connection()) as connection:
            with connection:
                cursor = connection.cursor()
                cursor.execute(
                    """
                    UPDATE episodes 
                    SET watched = ? 
                    WHERE season_id IN (
                        SELECT seasons.id 
                        FROM seasons 
                        JOIN series ON seasons.series_id = series.id 
                        WHERE series.library_name = ? AND series.name = ? AND seasons.name = ?
                    )
                """,
                    (1 if watched else 0, library_name, series_name, season_name),
                )
    except Exception as e:
        logger.error(
            f"Error updating watched status for {series_name} - {season_name}: {e}"
        )


def sync_watched_from_jellyfin_data(
    watched_ids: set, watched_paths: set, watched_names: set = None
) -> int:
    """
    Bulk-updates watched=True for all episodes whose Jellyfin ID is in watched_ids
    OR whose file path is in watched_paths
    OR whose (series_name, episode_name) is in watched_names.
    Returns the total number of rows updated.
    """
    if not watched_ids and not watched_paths and not watched_names:
        logger.info("No watched IDs, paths, or names provided for Jellyfin sync.")
        return 0

    start_time = time.time()
    logger.info(
        f"Starting bulk watched status sync: {len(watched_ids)} IDs, {len(watched_paths)} paths, {len(watched_names or [])} names."
    )
    updated_count = 0
    try:
        with closing(get_connection()) as connection:
            with connection:
                cursor = connection.cursor()

                # Reset all to unwatched first
                cursor.execute("UPDATE episodes SET watched = 0")

                # 1. Mark by Jellyfin ID (Most reliable)
                if watched_ids:
                    id_list = list(watched_ids)
                    chunk_size = 500
                    for index in range(0, len(id_list), chunk_size):
                        chunk = id_list[index : index + chunk_size]
                        placeholders = ",".join("?" * len(chunk))
                        cursor.execute(
                            f"UPDATE episodes SET watched = 1 WHERE jellyfin_id IN ({placeholders})",
                            tuple(chunk),
                        )
                        updated_count += cursor.rowcount

                # 2. Mark by Path (Fallback for unlinked items)
                if watched_paths:
                    path_list = list(watched_paths)
                    chunk_size = 500
                    for index in range(0, len(path_list), chunk_size):
                        chunk = path_list[index : index + chunk_size]
                        placeholders = ",".join("?" * len(chunk))
                        # Only update those not already marked by ID
                        cursor.execute(
                            f"UPDATE episodes SET watched = 1 WHERE watched = 0 AND path IN ({placeholders})",
                            tuple(chunk),
                        )
                        updated_count += cursor.rowcount

                # 3. Mark by Name (Fallback for items with no ID yet)
                if watched_names:
                    cursor.execute(
                        "CREATE TEMP TABLE IF NOT EXISTS sync_names (series_name TEXT, episode_name TEXT)"
                    )
                    cursor.execute("DELETE FROM sync_names")
                    cursor.executemany(
                        "INSERT INTO sync_names VALUES (?, ?)", list(watched_names)
                    )

                    cursor.execute("""
                        UPDATE episodes 
                        SET watched = 1 
                        WHERE watched = 0 
                        AND EXISTS (
                            SELECT 1 FROM sync_names
                            JOIN series ON LOWER(series.name) = LOWER(sync_names.series_name)
                            JOIN seasons ON seasons.series_id = series.id
                            WHERE seasons.id = episodes.season_id
                            AND LOWER(episodes.name) = LOWER(sync_names.episode_name)
                        )
                    """)
                    updated_count += cursor.rowcount

                duration = time.time() - start_time
                logger.info(
                    f"sync_watched_from_jellyfin_data: marked {updated_count} episodes as watched in {duration:.3f}s."
                )
    except Exception as exception:
        logger.error(f"Error in sync_watched_from_jellyfin_data: {exception}")

    return updated_count


def get_all_episodes_with_jellyfin_id() -> list:
    """Returns a list of all episodes that have a Jellyfin ID associated."""
    episodes = []
    try:
        with closing(get_connection()) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT name, path, jellyfin_id, watched FROM episodes WHERE jellyfin_id IS NOT NULL AND jellyfin_id != ''"
            )
            rows = cursor.fetchall()
            for row in rows:
                episodes.append(dict(row))
    except Exception as e:
        logger.error(f"Error fetching episodes with Jellyfin ID: {e}")
    return episodes
