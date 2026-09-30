from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text

import lan_streamer.db as db_mod


def _alembic_cfg(db_path: Any) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _engine(db_path: Any) -> sa.Engine:
    return sa.create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )


@pytest.fixture
def mock_db_file(tmp_path):
    return tmp_path / "library.db"


@pytest.fixture
def _db_setup(mock_db_file):
    old_engine = db_mod._engine
    old_session = db_mod._SessionLocal
    old_init = db_mod._db_initialized
    if old_engine is not None:
        old_engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False

    yield

    if db_mod._engine is not None:
        db_mod._engine.dispose()
    db_mod._engine = old_engine
    db_mod._SessionLocal = old_session
    db_mod._db_initialized = old_init


@pytest.mark.usefixtures("_db_setup")
def test_decouple_libraries_migration_and_deduplication(mock_db_file) -> None:
    """Test that decoupling libraries into junction tables preserves existing data,
    deduplicates duplicate series and movies across libraries, and merges seasons and files.
    """
    if mock_db_file.exists():
        mock_db_file.unlink()

    cfg = _alembic_cfg(mock_db_file)
    engine = _engine(mock_db_file)

    # 1. Upgrade to the revision BEFORE the library decoupling migration
    command.upgrade(cfg, "bbd1b7ccd143")

    # 2. Insert dummy series, seasons, episodes, movies, media files across split libraries
    series_id_1 = uuid.uuid4().bytes
    series_id_2 = uuid.uuid4().bytes
    season_id_1 = uuid.uuid4().bytes
    season_id_2 = uuid.uuid4().bytes
    episode_id_1 = uuid.uuid4().bytes
    episode_id_2 = uuid.uuid4().bytes

    movie_id_1 = uuid.uuid4().bytes
    movie_id_2 = uuid.uuid4().bytes
    media_file_id_1 = uuid.uuid4().bytes
    media_file_id_2 = uuid.uuid4().bytes
    mapping_id_1 = uuid.uuid4().bytes
    mapping_id_2 = uuid.uuid4().bytes

    with engine.begin() as conn:
        # Series 1 in "TV"
        conn.execute(
            text(
                "INSERT INTO series (id, library_name, name, tmdb_identifier) "
                "VALUES (:id, :lib, :name, :tmdb)"
            ),
            {"id": series_id_1, "lib": "TV", "name": "Breaking Bad", "tmdb": "1396"},
        )
        conn.execute(
            text(
                "INSERT INTO seasons (id, series_id, name) VALUES (:id, :series_id, :name)"
            ),
            {"id": season_id_1, "series_id": series_id_1, "name": "Season 1"},
        )
        conn.execute(
            text(
                "INSERT INTO episodes (id, season_id, name) VALUES (:id, :season_id, :name)"
            ),
            {"id": episode_id_1, "season_id": season_id_1, "name": "Pilot"},
        )

        # Series 2 in "TV (disk2)" (same show, duplicate record with Season 2)
        conn.execute(
            text(
                "INSERT INTO series (id, library_name, name, tmdb_identifier) "
                "VALUES (:id, :lib, :name, :tmdb)"
            ),
            {
                "id": series_id_2,
                "lib": "TV (disk2)",
                "name": "Breaking Bad",
                "tmdb": "1396",
            },
        )
        conn.execute(
            text(
                "INSERT INTO seasons (id, series_id, name) VALUES (:id, :series_id, :name)"
            ),
            {"id": season_id_2, "series_id": series_id_2, "name": "Season 2"},
        )
        conn.execute(
            text(
                "INSERT INTO episodes (id, season_id, name) VALUES (:id, :season_id, :name)"
            ),
            {
                "id": episode_id_2,
                "season_id": season_id_2,
                "name": "Seven Thirty-Seven",
            },
        )

        # Movie 1 in "Movies" (1080p)
        conn.execute(
            text(
                "INSERT INTO movies (id, library_name, name, tmdb_identifier) "
                "VALUES (:id, :lib, :name, :tmdb)"
            ),
            {"id": movie_id_1, "lib": "Movies", "name": "The Matrix", "tmdb": "603"},
        )
        conn.execute(
            text("INSERT INTO media_files (id, path) VALUES (:id, :path)"),
            {"id": media_file_id_1, "path": "/nas1/matrix.mkv"},
        )
        conn.execute(
            text(
                "INSERT INTO metadata_file_mappings (id, media_file_id, movie_id, file_path, movie_name) "
                "VALUES (:id, :media_file_id, :movie_id, :file_path, :movie_name)"
            ),
            {
                "id": mapping_id_1,
                "media_file_id": media_file_id_1,
                "movie_id": movie_id_1,
                "file_path": "/nas1/matrix.mkv",
                "movie_name": "The Matrix",
            },
        )

        # Movie 2 in "4K Movies" (4K version of same movie)
        conn.execute(
            text(
                "INSERT INTO movies (id, library_name, name, tmdb_identifier) "
                "VALUES (:id, :lib, :name, :tmdb)"
            ),
            {"id": movie_id_2, "lib": "4K Movies", "name": "The Matrix", "tmdb": "603"},
        )
        conn.execute(
            text("INSERT INTO media_files (id, path) VALUES (:id, :path)"),
            {"id": media_file_id_2, "path": "/nas2/matrix_4k.mkv"},
        )
        conn.execute(
            text(
                "INSERT INTO metadata_file_mappings (id, media_file_id, movie_id, file_path, movie_name) "
                "VALUES (:id, :media_file_id, :movie_id, :file_path, :movie_name)"
            ),
            {
                "id": mapping_id_2,
                "media_file_id": media_file_id_2,
                "movie_id": movie_id_2,
                "file_path": "/nas2/matrix_4k.mkv",
                "movie_name": "The Matrix",
            },
        )

    # 3. Upgrade to target revision
    command.upgrade(cfg, "c4d5e6f7a8b9")

    # 4. Verify deduplication and junction records
    with engine.connect() as conn:
        # Check series: should be deduplicated into 1 row
        series_rows = conn.execute(
            text(
                "SELECT id, name, tmdb_identifier FROM series WHERE name='Breaking Bad'"
            )
        ).fetchall()
        assert len(series_rows) == 1
        surviving_series_id = series_rows[0][0]

        # Both Season 1 and Season 2 should belong to the surviving series
        season_rows = conn.execute(
            text("SELECT name FROM seasons WHERE series_id=:series_id ORDER BY name"),
            {"series_id": surviving_series_id},
        ).fetchall()
        assert len(season_rows) == 2
        assert [r[0] for r in season_rows] == ["Season 1", "Season 2"]

        # Check series_libraries junction table: should have both "TV" and "TV (disk2)"
        junction_series = conn.execute(
            text(
                "SELECT library_name FROM series_libraries WHERE series_id=:series_id ORDER BY library_name"
            ),
            {"series_id": surviving_series_id},
        ).fetchall()
        assert [r[0] for r in junction_series] == ["TV", "TV (disk2)"]

        # Check movies: should be deduplicated into 1 row
        movie_rows = conn.execute(
            text("SELECT id, name, tmdb_identifier FROM movies WHERE name='The Matrix'")
        ).fetchall()
        assert len(movie_rows) == 1
        surviving_movie_id = movie_rows[0][0]

        # Both file mappings should now point to surviving_movie_id
        mapping_rows = conn.execute(
            text(
                "SELECT file_path FROM metadata_file_mappings WHERE movie_id=:movie_id ORDER BY file_path"
            ),
            {"movie_id": surviving_movie_id},
        ).fetchall()
        assert len(mapping_rows) == 2
        assert [r[0] for r in mapping_rows] == [
            "/nas1/matrix.mkv",
            "/nas2/matrix_4k.mkv",
        ]

        # Check movie_libraries junction table: should have both "4K Movies" and "Movies"
        junction_movies = conn.execute(
            text(
                "SELECT library_name FROM movie_libraries WHERE movie_id=:movie_id ORDER BY library_name"
            ),
            {"movie_id": surviving_movie_id},
        ).fetchall()
        assert [r[0] for r in junction_movies] == ["4K Movies", "Movies"]

    # 5. Downgrade back to bbd1b7ccd143
    command.downgrade(cfg, "bbd1b7ccd143")

    with engine.connect() as conn:
        # Tables series_libraries and movie_libraries should be dropped
        res = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('series_libraries', 'movie_libraries')"
            )
        ).fetchall()
        assert len(res) == 0
