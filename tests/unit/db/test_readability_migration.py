from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from lan_streamer.db.models import (
    Season,
    PlaybackState,
    MetadataFileMapping,
)
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


def test_readability_migration_and_data_preservation(mock_db_file, _db_setup) -> None:
    """Test that readability columns migration on all tables preserves existing data and triggers populating names/paths."""
    if mock_db_file.exists():
        mock_db_file.unlink()

    cfg = _alembic_cfg(mock_db_file)
    engine = _engine(mock_db_file)

    # 1. Upgrade to the revision BEFORE the readability migration
    command.upgrade(cfg, "b7c8d9e0f1a2")

    # 2. Insert dummy series, season, episode, movie, media_file, playback_states, and metadata_file_mappings data using connection
    with engine.begin() as conn:
        series_id = uuid.uuid4().bytes
        season_id = uuid.uuid4().bytes
        episode_id = uuid.uuid4().bytes
        movie_id = uuid.uuid4().bytes
        media_file_id = uuid.uuid4().bytes
        playback_ep_id = uuid.uuid4().bytes
        playback_movie_id = uuid.uuid4().bytes
        mapping_id = uuid.uuid4().bytes

        conn.execute(
            text(
                "INSERT INTO series (id, library_name, name) VALUES (:id, :lib, :name)"
            ),
            {"id": series_id, "lib": "TV", "name": "Migration Show"},
        )
        conn.execute(
            text(
                "INSERT INTO seasons (id, series_id, name) VALUES (:id, :series_id, :name)"
            ),
            {"id": season_id, "series_id": series_id, "name": "Season 1"},
        )
        conn.execute(
            text(
                "INSERT INTO episodes (id, season_id, name) VALUES (:id, :season_id, :name)"
            ),
            {"id": episode_id, "season_id": season_id, "name": "Episode 1"},
        )
        conn.execute(
            text(
                "INSERT INTO movies (id, library_name, name) VALUES (:id, :lib, :name)"
            ),
            {"id": movie_id, "lib": "Movies", "name": "Migration Movie"},
        )
        conn.execute(
            text("INSERT INTO media_files (id, path) VALUES (:id, :path)"),
            {"id": media_file_id, "path": "/movies/mig.mkv"},
        )
        conn.execute(
            text(
                "INSERT INTO playback_states (id, episode_id, watched, last_played_position, last_played_at) VALUES (:id, :ep_id, :watched, 0, 0)"
            ),
            {"id": playback_ep_id, "ep_id": episode_id, "watched": 1},
        )
        conn.execute(
            text(
                "INSERT INTO playback_states (id, movie_id, watched, last_played_position, last_played_at) VALUES (:id, :movie_id, :watched, 0, 0)"
            ),
            {"id": playback_movie_id, "movie_id": movie_id, "watched": 0},
        )
        conn.execute(
            text(
                "INSERT INTO metadata_file_mappings (id, media_file_id, episode_id) VALUES (:id, :mf_id, :ep_id)"
            ),
            {"id": mapping_id, "mf_id": media_file_id, "ep_id": episode_id},
        )

    # 3. Upgrade to our target revision
    command.upgrade(cfg, "bbd1b7ccd143")

    # 4. Verify existing records survive and columns are populated by the migration
    with engine.connect() as conn:
        series_row = (
            conn.execute(
                text("SELECT name FROM series WHERE id = :id"), {"id": series_id}
            )
            .mappings()
            .first()
        )
        assert series_row is not None
        assert series_row["name"] == "Migration Show"

        season_row = (
            conn.execute(
                text("SELECT name, series_name FROM seasons WHERE id = :id"),
                {"id": season_id},
            )
            .mappings()
            .first()
        )
        assert season_row is not None
        assert season_row["series_name"] == "Migration Show"

        playback_ep_row = (
            conn.execute(
                text(
                    "SELECT episode_id, series_name, season_name, episode_name FROM playback_states WHERE id = :id"
                ),
                {"id": playback_ep_id},
            )
            .mappings()
            .first()
        )
        assert playback_ep_row["episode_name"] == "Episode 1"
        assert playback_ep_row["season_name"] == "Season 1"
        assert playback_ep_row["series_name"] == "Migration Show"

        mapping_row = (
            conn.execute(
                text(
                    "SELECT media_file_id, file_path, episode_name, series_name, season_name FROM metadata_file_mappings WHERE id = :id"
                ),
                {"id": mapping_id},
            )
            .mappings()
            .first()
        )
        assert mapping_row["file_path"] == "/movies/mig.mkv"
        assert mapping_row["episode_name"] == "Episode 1"
        assert mapping_row["series_name"] == "Migration Show"
        assert mapping_row["season_name"] == "Season 1"

    # 5. Connect via SQLAlchemy ORM to verify that our new event listeners populate columns on updates
    db_mod.DB_FILE = mock_db_file
    db_mod.init_db()

    with db_mod.get_session() as session:
        # Trigger updates to populate columns via event listeners
        season = session.get(Season, uuid.UUID(bytes=season_id).hex)
        season.name = "Season 1 Updated"

        playback_ep = session.get(PlaybackState, uuid.UUID(bytes=playback_ep_id).hex)
        playback_ep.watched = True

        playback_movie = session.get(
            PlaybackState, uuid.UUID(bytes=playback_movie_id).hex
        )
        playback_movie.watched = False

        mapping = session.get(MetadataFileMapping, uuid.UUID(bytes=mapping_id).hex)
        mapping.movie_id = uuid.UUID(bytes=movie_id).hex

        session.commit()

    with db_mod.get_session() as session:
        season = session.get(Season, uuid.UUID(bytes=season_id).hex)
        assert season.series_name == "Migration Show"

        playback_ep = session.get(PlaybackState, uuid.UUID(bytes=playback_ep_id).hex)
        assert playback_ep.series_name == "Migration Show"
        assert playback_ep.season_name == "Season 1 Updated"
        assert playback_ep.episode_name == "Episode 1"

        playback_movie = session.get(
            PlaybackState, uuid.UUID(bytes=playback_movie_id).hex
        )
        assert playback_movie.movie_name == "Migration Movie"

        mapping = session.get(MetadataFileMapping, uuid.UUID(bytes=mapping_id).hex)
        assert mapping.file_path == "/movies/mig.mkv"
        assert mapping.movie_name == "Migration Movie"

    # 6. Verify database-level triggers prevent drift when interacting with it directly
    with engine.begin() as conn:
        # A. Trigger test: Direct update of Series name
        conn.execute(
            text("UPDATE series SET name = :new_name WHERE id = :id"),
            {"new_name": "Totally New Show Name", "id": series_id},
        )

    with engine.connect() as conn:
        # Season, Episode, PlaybackState, and MetadataFileMapping series_name columns should have automatically updated via trigger
        season_row = (
            conn.execute(
                text("SELECT series_name FROM seasons WHERE id = :id"),
                {"id": season_id},
            )
            .mappings()
            .first()
        )
        assert season_row["series_name"] == "Totally New Show Name"

        episode_row = (
            conn.execute(
                text("SELECT series_name FROM episodes WHERE id = :id"),
                {"id": episode_id},
            )
            .mappings()
            .first()
        )
        assert episode_row["series_name"] == "Totally New Show Name"

        playback_ep_row = (
            conn.execute(
                text("SELECT series_name FROM playback_states WHERE id = :id"),
                {"id": playback_ep_id},
            )
            .mappings()
            .first()
        )
        assert playback_ep_row["series_name"] == "Totally New Show Name"

        mapping_row = (
            conn.execute(
                text("SELECT series_name FROM metadata_file_mappings WHERE id = :id"),
                {"id": mapping_id},
            )
            .mappings()
            .first()
        )
        assert mapping_row["series_name"] == "Totally New Show Name"

    with engine.begin() as conn:
        # B. Trigger test: Direct update of MediaFile path
        conn.execute(
            text("UPDATE media_files SET path = :new_path WHERE id = :id"),
            {"new_path": "/movies/new_mig.mkv", "id": media_file_id},
        )

    with engine.connect() as conn:
        # MetadataFileMapping file_path should update
        mapping_row = (
            conn.execute(
                text("SELECT file_path FROM metadata_file_mappings WHERE id = :id"),
                {"id": mapping_id},
            )
            .mappings()
            .first()
        )
        assert mapping_row["file_path"] == "/movies/new_mig.mkv"

    with engine.begin() as conn:
        # C. Trigger test: Direct SQL Insert of new PlaybackState
        # Since an episode can only have one playback state, we insert a new episode first
        direct_ep_id_for_ps = uuid.uuid4().bytes
        conn.execute(
            text(
                "INSERT INTO episodes (id, season_id, name) VALUES (:id, :season_id, :name)"
            ),
            {
                "id": direct_ep_id_for_ps,
                "season_id": season_id,
                "name": "Direct Episode for PS",
            },
        )

        direct_ps_id = uuid.uuid4().bytes
        conn.execute(
            text(
                "INSERT INTO playback_states (id, episode_id, watched, last_played_position, last_played_at) VALUES (:id, :ep_id, 0, 0, 0)"
            ),
            {"id": direct_ps_id, "ep_id": direct_ep_id_for_ps},
        )

    with engine.connect() as conn:
        ps_row = (
            conn.execute(
                text(
                    "SELECT series_name, season_name, episode_name FROM playback_states WHERE id = :id"
                ),
                {"id": direct_ps_id},
            )
            .mappings()
            .first()
        )
        assert ps_row["series_name"] == "Totally New Show Name"
        assert ps_row["episode_name"] == "Direct Episode for PS"
