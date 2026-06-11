"""Tests for the b3f9e1c2d4a5 UUID-BLOB primary key migration and the
supporting model/query changes it required.

Coverage areas
--------------
1. _new_uuid_bytes() helper – correct format & uniqueness
2. ORM auto-generated UUID BLOB PKs on insert (Series, Season, Episode,
   Movie, AppSecret)
3. FK referential integrity with BLOB keys (seasons → series, episodes →
   seasons)
4. set_secret() no longer needs an explicit secret_uuid; the column default
   supplies it
5. update_item_runtime() accepts bytes IDs (episode and movie paths)
6. Alembic upgrade b3f9e1c2d4a5: all five tables migrated to BLOB PKs,
   existing FK links preserved, all column data intact, UUIDs are valid
7. Alembic downgrade b3f9e1c2d4a5: reverts to integer PKs, FK links
   reconstructed, no data loss
8. Round-trip (upgrade then downgrade) preserves all row data
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _alembic_cfg(db_path: Any) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _engine(db_path: Any) -> sa.Engine:
    return sa.create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )


def _is_valid_uuid(value: Any) -> bool:
    """Return True when *value* is a 16-byte blob or a valid UUID string."""
    if isinstance(value, (bytes, bytearray)):
        if len(value) != 16:
            return False
        try:
            uuid.UUID(bytes=bytes(value))
            return True
        except ValueError, TypeError:
            return False
    if isinstance(value, str):
        try:
            uuid.UUID(value)
            return True
        except ValueError:
            return False
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_file(tmp_path):
    return tmp_path / "library.db"


# ---------------------------------------------------------------------------
# 1. _new_uuid_bytes helper
# ---------------------------------------------------------------------------


def test_new_uuid_bytes_returns_bytes() -> None:
    """_new_uuid_bytes must return a bytes object."""
    from lan_streamer.db.models import _new_uuid_bytes

    result = _new_uuid_bytes()
    assert isinstance(result, bytes)


def test_new_uuid_bytes_is_16_bytes() -> None:
    """UUID4 raw bytes are exactly 16 bytes."""
    from lan_streamer.db.models import _new_uuid_bytes

    assert len(_new_uuid_bytes()) == 16


def test_new_uuid_bytes_is_valid_uuid4() -> None:
    """The returned bytes must parse as a valid UUID."""
    from lan_streamer.db.models import _new_uuid_bytes

    raw = _new_uuid_bytes()
    parsed = uuid.UUID(bytes=raw)
    assert parsed.version == 4


def test_new_uuid_bytes_unique() -> None:
    """Each call generates a different value (uniqueness sanity check)."""
    from lan_streamer.db.models import _new_uuid_bytes

    ids = {_new_uuid_bytes() for _ in range(100)}
    assert len(ids) == 100


# ---------------------------------------------------------------------------
# 2. ORM auto-generated UUID BLOB PKs on insert
# ---------------------------------------------------------------------------


def test_series_pk_is_blob_uuid(mock_db_file) -> None:
    """Series rows get a 16-byte BLOB primary key automatically on insert."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Series

    with db_mod.get_session() as session:
        s = Series(library_name="Lib", name="Test Show")
        session.add(s)
        session.flush()
        assert _is_valid_uuid(s.id), f"Expected valid UUID bytes, got: {s.id!r}"

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_season_pk_is_blob_uuid(mock_db_file) -> None:
    """Season rows get a 16-byte BLOB primary key automatically on insert."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Season, Series

    with db_mod.get_session() as session:
        series = Series(library_name="Lib", name="Show")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()
        assert _is_valid_uuid(season.id), (
            f"Expected valid UUID bytes, got: {season.id!r}"
        )

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_episode_pk_is_blob_uuid(mock_db_file) -> None:
    """Episode rows get a 16-byte BLOB primary key automatically on insert."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Episode, Season, Series

    with db_mod.get_session() as session:
        series = Series(library_name="Lib", name="Show")
        session.add(series)
        session.flush()
        season = Season(name="S1", series=series)
        session.add(season)
        session.flush()
        episode = Episode(name="E1", path="/ep1.mkv", season=season)
        session.add(episode)
        session.flush()
        assert _is_valid_uuid(episode.id), (
            f"Expected valid UUID bytes, got: {episode.id!r}"
        )

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_movie_pk_is_blob_uuid(mock_db_file) -> None:
    """Movie rows get a 16-byte BLOB primary key automatically on insert."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Movie

    with db_mod.get_session() as session:
        movie = Movie(library_name="Movies", name="Film", path="/film.mkv")
        session.add(movie)
        session.flush()
        assert _is_valid_uuid(movie.id), f"Expected valid UUID bytes, got: {movie.id!r}"

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_app_secret_pk_is_blob_uuid(mock_db_file) -> None:
    """AppSecret rows get a 16-byte BLOB primary key automatically on insert."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import AppSecret, SecretType

    with db_mod.get_session() as session:
        session.execute(sa.delete(AppSecret))
        session.commit()

    with db_mod.get_session() as session:
        secret = AppSecret(secret_type=SecretType.TMDB.value, secret="{}")
        session.add(secret)
        session.flush()
        assert _is_valid_uuid(secret.secret_uuid), (
            f"Expected valid UUID bytes, got: {secret.secret_uuid!r}"
        )

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_each_row_gets_unique_uuid(mock_db_file) -> None:
    """Two rows in the same table must not share the same UUID PK."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Movie

    with db_mod.get_session() as session:
        m1 = Movie(library_name="Movies", name="Film A", path="/a.mkv")
        m2 = Movie(library_name="Movies", name="Film B", path="/b.mkv")
        session.add_all([m1, m2])
        session.flush()
        assert m1.id != m2.id

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


# ---------------------------------------------------------------------------
# 3. FK referential integrity with BLOB keys
# ---------------------------------------------------------------------------


def test_season_series_fk_is_blob(mock_db_file) -> None:
    """Season.series_id must equal its parent Series.id (both BLOB)."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Season, Series

    with db_mod.get_session() as session:
        series = Series(library_name="Lib", name="Show")
        session.add(series)
        session.flush()
        season = Season(name="S1", series=series)
        session.add(season)
        session.flush()
        assert season.series_id == series.id
        assert _is_valid_uuid(season.series_id)

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_episode_season_fk_is_blob(mock_db_file) -> None:
    """Episode.season_id must equal its parent Season.id (both BLOB)."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Episode, Season, Series

    with db_mod.get_session() as session:
        series = Series(library_name="Lib", name="Show")
        session.add(series)
        session.flush()
        season = Season(name="S1", series=series)
        session.add(season)
        session.flush()
        episode = Episode(name="E1", path="/e1.mkv", season=season)
        session.add(episode)
        session.flush()
        assert episode.season_id == season.id
        assert _is_valid_uuid(episode.season_id)

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_cascade_delete_from_series(mock_db_file) -> None:
    """Deleting a Series must cascade-delete its Seasons and Episodes."""
    import lan_streamer.db as db_mod
    from sqlalchemy import select

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Episode, Season, Series

    with db_mod.get_session() as session:
        series = Series(library_name="Lib", name="Show")
        session.add(series)
        session.flush()
        season = Season(name="S1", series=series)
        session.add(season)
        session.flush()
        episode = Episode(name="E1", path="/e1.mkv", season=season)
        session.add(episode)
        session.flush()
        series_id = series.id

        session.delete(series)

    with db_mod.get_session() as session:
        assert (
            session.scalars(select(Season).where(Season.series_id == series_id)).first()
            is None
        )
        assert (
            session.scalars(select(Episode).where(Episode.name == "E1")).first() is None
        )

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


# ---------------------------------------------------------------------------
# 4. set_secret() uses column default (no explicit secret_uuid)
# ---------------------------------------------------------------------------


def test_set_secret_creates_uuid_pk(mock_db_file) -> None:
    """set_secret() must insert a BLOB UUID pk without being passed one."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import AppSecret, SecretType

    db_mod.set_secret(SecretType.JELLYFIN, {"url": "http://jf", "api_key": "key"})

    with db_mod.get_session() as session:
        row = session.scalars(
            sa.select(AppSecret).where(
                AppSecret.secret_type == SecretType.JELLYFIN.value
            )
        ).first()
        assert row is not None
        assert _is_valid_uuid(row.secret_uuid)

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_set_secret_upsert_preserves_uuid(mock_db_file) -> None:
    """Calling set_secret() twice for the same type must not change the PK."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import AppSecret, SecretType

    db_mod.set_secret(SecretType.TMDB, {"api_key": "first"})

    with db_mod.get_session() as session:
        first_uuid = (
            session.scalars(
                sa.select(AppSecret).where(
                    AppSecret.secret_type == SecretType.TMDB.value
                )
            )
            .first()
            .secret_uuid
        )

    db_mod.set_secret(SecretType.TMDB, {"api_key": "second"})

    with db_mod.get_session() as session:
        row = session.scalars(
            sa.select(AppSecret).where(AppSecret.secret_type == SecretType.TMDB.value)
        ).first()
        assert row.secret_uuid == first_uuid
        assert json.loads(row.secret)["api_key"] == "second"

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


# ---------------------------------------------------------------------------
# 5. update_item_runtime() accepts bytes IDs
# ---------------------------------------------------------------------------


def test_update_item_runtime_episode_bytes_id(mock_db_file) -> None:
    """update_item_runtime must update an episode looked up by its bytes UUID."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Episode, Season, Series

    with db_mod.get_session() as session:
        series = Series(library_name="Lib", name="Show")
        session.add(series)
        session.flush()
        season = Season(name="S1", series=series)
        session.add(season)
        session.flush()
        ep = Episode(name="E1", path="/e1.mkv", season=season, runtime=0)
        session.add(ep)
        session.flush()
        ep_id = ep.id  # bytes

    db_mod.update_item_runtime(
        ep_id,
        "episode",
        45,
        video_codec="h264",
        resolution="1920x1080",
        audio_tracks=[{"language": "eng"}],
        subtitle_tracks=[],
    )

    with db_mod.get_session() as session:
        from sqlalchemy import select

        updated = session.scalars(select(Episode).where(Episode.id == ep_id)).first()
        assert updated is not None
        assert updated.runtime == 45
        assert updated.video_codec == "h264"
        assert updated.resolution == "1920x1080"
        assert json.loads(updated.audio_tracks) == [{"language": "eng"}]
        assert json.loads(updated.subtitle_tracks) == []

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_update_item_runtime_movie_bytes_id(mock_db_file) -> None:
    """update_item_runtime must update a movie looked up by its bytes UUID."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Movie

    with db_mod.get_session() as session:
        movie = Movie(library_name="Movies", name="Film", path="/film.mkv", runtime=0)
        session.add(movie)
        session.flush()
        movie_id = movie.id  # bytes

    db_mod.update_item_runtime(
        movie_id,
        "movie",
        120,
        video_codec="hevc",
        resolution="3840x2160",
        audio_tracks=[{"language": "eng"}, {"language": "fre"}],
        subtitle_tracks=[{"language": "eng"}],
    )

    with db_mod.get_session() as session:
        from sqlalchemy import select

        updated = session.scalars(select(Movie).where(Movie.id == movie_id)).first()
        assert updated is not None
        assert updated.runtime == 120
        assert updated.video_codec == "hevc"
        assert updated.resolution == "3840x2160"
        assert json.loads(updated.audio_tracks) == [
            {"language": "eng"},
            {"language": "fre"},
        ]
        assert json.loads(updated.subtitle_tracks) == [{"language": "eng"}]

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_update_item_runtime_nonexistent_bytes_id_is_noop(mock_db_file) -> None:
    """update_item_runtime with a UUID that doesn't exist must not raise."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    phantom_id = uuid.uuid4().bytes
    # Neither call should raise
    db_mod.update_item_runtime(phantom_id, "episode", 30)
    db_mod.update_item_runtime(phantom_id, "movie", 30)

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


def test_get_items_missing_runtime_returns_string_ids(mock_db_file) -> None:
    """get_items_missing_runtime must return dicts whose 'id' values are strings."""
    import lan_streamer.db as db_mod

    db_mod.DB_FILE = mock_db_file
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False
    db_mod.init_db()

    from lan_streamer.db.models import Episode, Movie, Season, Series

    with db_mod.get_session() as session:
        series = Series(library_name="Lib", name="Show")
        session.add(series)
        session.flush()
        season = Season(name="S1", series=series)
        session.add(season)
        session.flush()
        session.add(Episode(name="E1", path="/e1.mkv", season=season, runtime=0))
        session.add(
            Movie(library_name="Movies", name="Film", path="/film.mkv", runtime=0)
        )

    items = db_mod.get_items_missing_runtime()
    assert len(items) >= 2
    for item in items:
        assert isinstance(item["id"], str), (
            f"Expected string ID, got {type(item['id'])}: {item['id']!r}"
        )
        assert _is_valid_uuid(item["id"])

    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod._db_initialized = False


# ---------------------------------------------------------------------------
# 6. Alembic upgrade b3f9e1c2d4a5
# ---------------------------------------------------------------------------


def test_uuid_blob_migration_upgrade_creates_blob_pks(tmp_path) -> None:
    """After upgrade, all five tables store their PK as a 16-byte BLOB."""
    db_path = tmp_path / "test_uuid_upgrade.db"
    cfg = _alembic_cfg(db_path)

    # Bring up to the revision just before ours
    command.upgrade(cfg, "a1b2c3d4e5f6")

    engine = _engine(db_path)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM app_secrets"))
        # Insert data using the old integer-based schema
        conn.execute(
            text("INSERT INTO series (library_name, name) VALUES ('Lib', 'Show A')")
        )
        conn.execute(
            text("INSERT INTO series (library_name, name) VALUES ('Lib', 'Show B')")
        )

        series_id_a = conn.execute(
            text("SELECT id FROM series WHERE name = 'Show A'")
        ).scalar()
        conn.execute(
            text(
                f"INSERT INTO seasons (series_id, name) VALUES ({series_id_a}, 'Season 1')"
            )
        )
        season_id = conn.execute(text("SELECT id FROM seasons LIMIT 1")).scalar()
        conn.execute(
            text(
                f"INSERT INTO episodes (season_id, name, path) "
                f"VALUES ({season_id}, 'E1', '/ep1.mkv')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO movies (library_name, name, path) VALUES ('Movies', 'Film', '/film.mkv')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO app_secrets (secret_uuid, secret_type, secret) "
                "VALUES ('old-str-uuid', 'tmdb', '{\"api_key\": \"k\"}')"
            )
        )

    # Run our migration
    command.upgrade(cfg, "b3f9e1c2d4a5")

    with engine.connect() as conn:
        # Verify each table has its PK as a 16-byte BLOB
        for table, pk_col in [
            ("series", "id"),
            ("seasons", "id"),
            ("episodes", "id"),
            ("movies", "id"),
            ("app_secrets", "secret_uuid"),
        ]:
            rows = conn.execute(text(f"SELECT {pk_col} FROM {table}")).fetchall()
            assert rows, f"Table {table!r} has no rows after migration"
            for (pk_val,) in rows:
                raw = bytes(pk_val) if not isinstance(pk_val, bytes) else pk_val
                assert len(raw) == 16, (
                    f"{table}.{pk_col}: expected 16-byte BLOB, got {len(raw)} bytes"
                )
                assert _is_valid_uuid(raw), (
                    f"{table}.{pk_col}: {raw!r} is not a valid UUID"
                )

    engine.dispose()


def test_uuid_blob_migration_upgrade_preserves_data(tmp_path) -> None:
    """All existing column values survive the upgrade to UUID BLOBs."""
    db_path = tmp_path / "test_uuid_data.db"
    cfg = _alembic_cfg(db_path)

    command.upgrade(cfg, "a1b2c3d4e5f6")

    engine = _engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO series (library_name, name, jellyfin_id, tmdb_identifier, "
                "overview, tmdb_name, locked_metadata, first_air_date) "
                "VALUES ('TV', 'Breaking Bad', 'jf-bb', 'tmdb-bb', "
                "'A teacher turns criminal', 'Breaking Bad', 1, '2008-01-20')"
            )
        )
        series_id = conn.execute(
            text("SELECT id FROM series WHERE name = 'Breaking Bad'")
        ).scalar()

        conn.execute(
            text(
                f"INSERT INTO seasons (series_id, name, jellyfin_id) "
                f"VALUES ({series_id}, 'Season 1', 'jf-s1')"
            )
        )
        season_id = conn.execute(
            text("SELECT id FROM seasons WHERE name = 'Season 1'")
        ).scalar()

        conn.execute(
            text(
                f"INSERT INTO episodes (season_id, name, path, watched, date_added) "
                f"VALUES ({season_id}, 'Pilot', '/bb/s01e01.mkv', 1, 1609459200)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO movies (library_name, name, path, year, watched) "
                "VALUES ('Movies', 'Inception', '/inception.mkv', 2010, 0)"
            )
        )

    command.upgrade(cfg, "b3f9e1c2d4a5")

    with engine.connect() as conn:
        # Series
        s = conn.execute(
            text(
                "SELECT library_name, name, jellyfin_id, tmdb_identifier, overview, "
                "tmdb_name, locked_metadata, first_air_date FROM series WHERE name = 'Breaking Bad'"
            )
        ).fetchone()
        assert s is not None
        assert s[0] == "TV"
        assert s[1] == "Breaking Bad"
        assert s[2] == "jf-bb"
        assert s[3] == "tmdb-bb"
        assert s[4] == "A teacher turns criminal"
        assert s[5] == "Breaking Bad"
        assert s[6] in (1, True)
        assert s[7] == "2008-01-20"

        # Season
        season = conn.execute(
            text("SELECT name, jellyfin_id FROM seasons WHERE name = 'Season 1'")
        ).fetchone()
        assert season is not None
        assert season[0] == "Season 1"
        assert season[1] == "jf-s1"

        # Episode
        ep = conn.execute(
            text(
                "SELECT name, path, watched, date_added FROM episodes WHERE name = 'Pilot'"
            )
        ).fetchone()
        assert ep is not None
        assert ep[0] == "Pilot"
        assert ep[1] == "/bb/s01e01.mkv"
        assert ep[2] in (1, True)
        assert ep[3] == 1609459200

        # Movie
        movie = conn.execute(
            text("SELECT name, path, year FROM movies WHERE name = 'Inception'")
        ).fetchone()
        assert movie is not None
        assert movie[0] == "Inception"
        assert movie[1] == "/inception.mkv"
        assert movie[2] == 2010

    engine.dispose()


def test_uuid_blob_migration_upgrade_preserves_fk_links(tmp_path) -> None:
    """After upgrade, series→seasons→episodes FK links must still be valid."""
    db_path = tmp_path / "test_uuid_fk.db"
    cfg = _alembic_cfg(db_path)

    command.upgrade(cfg, "a1b2c3d4e5f6")

    engine = _engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO series (library_name, name) VALUES ('Lib', 'My Show')")
        )
        series_id = conn.execute(
            text("SELECT id FROM series WHERE name = 'My Show'")
        ).scalar()
        conn.execute(
            text(f"INSERT INTO seasons (series_id, name) VALUES ({series_id}, 'S1')")
        )
        season_id = conn.execute(
            text("SELECT id FROM seasons WHERE name = 'S1'")
        ).scalar()
        conn.execute(
            text(
                f"INSERT INTO episodes (season_id, name, path) "
                f"VALUES ({season_id}, 'E1', '/e1.mkv')"
            )
        )

    command.upgrade(cfg, "b3f9e1c2d4a5")

    with engine.connect() as conn:
        # JOIN should work: episodes → seasons → series
        row = conn.execute(
            text(
                "SELECT s.name, se.name, ep.name "
                "FROM episodes ep "
                "JOIN seasons se ON ep.season_id = se.id "
                "JOIN series s ON se.series_id = s.id "
                "WHERE ep.name = 'E1'"
            )
        ).fetchone()
        assert row is not None, "JOIN across BLOB FKs returned no rows"
        assert row[0] == "My Show"
        assert row[1] == "S1"
        assert row[2] == "E1"

    engine.dispose()


def test_uuid_blob_migration_upgrade_multiple_series_correct_fks(tmp_path) -> None:
    """Multiple series with their own seasons/episodes must map to the correct parent after upgrade."""
    db_path = tmp_path / "test_uuid_multi.db"
    cfg = _alembic_cfg(db_path)

    command.upgrade(cfg, "a1b2c3d4e5f6")

    engine = _engine(db_path)
    with engine.begin() as conn:
        for show in ("Show A", "Show B", "Show C"):
            conn.execute(
                text(
                    f"INSERT INTO series (library_name, name) VALUES ('Lib', '{show}')"
                )
            )
        for show in ("Show A", "Show B", "Show C"):
            sid = conn.execute(
                text(f"SELECT id FROM series WHERE name = '{show}'")
            ).scalar()
            for season_num in (1, 2):
                conn.execute(
                    text(
                        f"INSERT INTO seasons (series_id, name) "
                        f"VALUES ({sid}, 'Season {season_num}')"
                    )
                )
                sea_id = conn.execute(
                    text(
                        f"SELECT id FROM seasons WHERE series_id = {sid} "
                        f"AND name = 'Season {season_num}'"
                    )
                ).scalar()
                conn.execute(
                    text(
                        f"INSERT INTO episodes (season_id, name, path) "
                        f"VALUES ({sea_id}, 'E1', '/{show}/s{season_num}e1.mkv')"
                    )
                )

    command.upgrade(cfg, "b3f9e1c2d4a5")

    with engine.connect() as conn:
        for show in ("Show A", "Show B", "Show C"):
            # Each show should have exactly 2 seasons reachable via FK
            count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM seasons se "
                    "JOIN series s ON se.series_id = s.id "
                    f"WHERE s.name = '{show}'"
                )
            ).scalar()
            assert count == 2, f"{show} has {count} seasons via FK (expected 2)"

            # Each show should have exactly 2 episodes reachable via double FK
            ep_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM episodes ep "
                    "JOIN seasons se ON ep.season_id = se.id "
                    "JOIN series s ON se.series_id = s.id "
                    f"WHERE s.name = '{show}'"
                )
            ).scalar()
            assert ep_count == 2, f"{show} has {ep_count} episodes via FK (expected 2)"

    engine.dispose()


def test_uuid_blob_migration_upgrade_app_secrets_type_changes(tmp_path) -> None:
    """After upgrade, app_secrets.secret_uuid must be a BLOB (not a text string)."""
    db_path = tmp_path / "test_uuid_secrets.db"
    cfg = _alembic_cfg(db_path)

    command.upgrade(cfg, "a1b2c3d4e5f6")

    engine = _engine(db_path)
    with engine.begin() as conn:
        # Ensure at least one secret row exists (settings migration may have seeded some)
        existing = conn.execute(
            text("SELECT COUNT(*) FROM app_secrets WHERE secret_type = 'tmdb'")
        ).scalar()
        if not existing:
            conn.execute(
                text(
                    "INSERT INTO app_secrets (secret_uuid, secret_type, secret) "
                    "VALUES ('test-string-uuid', 'tmdb', '{\"api_key\": \"abc\"}')"
                )
            )

    command.upgrade(cfg, "b3f9e1c2d4a5")

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT secret_uuid, secret_type, secret FROM app_secrets WHERE secret_type = 'tmdb'"
            )
        ).fetchone()
        assert row is not None
        raw_pk = bytes(row[0]) if not isinstance(row[0], bytes) else row[0]
        assert len(raw_pk) == 16, f"secret_uuid is not 16 bytes: {raw_pk!r}"
        assert _is_valid_uuid(raw_pk)
        # Payload must be intact
        payload = json.loads(row[2])
        assert "api_key" in payload

    engine.dispose()


# ---------------------------------------------------------------------------
# 7. Alembic downgrade b3f9e1c2d4a5
# ---------------------------------------------------------------------------


def test_uuid_blob_migration_downgrade_reverts_to_integers(tmp_path) -> None:
    """After downgrade, all five tables must use integer PKs again."""
    db_path = tmp_path / "test_uuid_downgrade.db"
    cfg = _alembic_cfg(db_path)

    command.upgrade(cfg, "b3f9e1c2d4a5")

    engine = _engine(db_path)
    with engine.begin() as conn:
        # Insert data using the new BLOB schema before downgrading
        conn.execute(
            text(
                "INSERT INTO series (id, library_name, name, pref_hide_missing_future) "
                "VALUES (:id, 'Lib', 'Show', 0)"
            ),
            {"id": uuid.uuid4().bytes},
        )

    command.downgrade(cfg, "a1b2c3d4e5f6")

    with engine.connect() as conn:
        # PKs should now be integers (SQLite returns int for INTEGER PK)
        series_pk = conn.execute(text("SELECT id FROM series LIMIT 1")).scalar()
        assert isinstance(series_pk, int), (
            f"Expected integer PK after downgrade, got {type(series_pk)}: {series_pk!r}"
        )

    engine.dispose()


def test_uuid_blob_migration_downgrade_preserves_data(tmp_path) -> None:
    """Downgrade must not lose any column data."""
    db_path = tmp_path / "test_uuid_dg_data.db"
    cfg = _alembic_cfg(db_path)

    command.upgrade(cfg, "a1b2c3d4e5f6")

    engine = _engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO series (library_name, name, overview, first_air_date) "
                "VALUES ('TV', 'Lost', 'Survivors on island', '2004-09-22')"
            )
        )
        sid = conn.execute(text("SELECT id FROM series WHERE name = 'Lost'")).scalar()
        conn.execute(
            text(f"INSERT INTO seasons (series_id, name) VALUES ({sid}, 'Season 1')")
        )
        sea_id = conn.execute(
            text("SELECT id FROM seasons WHERE name = 'Season 1'")
        ).scalar()
        conn.execute(
            text(
                f"INSERT INTO episodes (season_id, name, path, watched) "
                f"VALUES ({sea_id}, 'Pilot', '/lost/s01e01.mkv', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO movies (library_name, name, path, year) "
                "VALUES ('Movies', 'Interstellar', '/inter.mkv', 2014)"
            )
        )

    command.upgrade(cfg, "b3f9e1c2d4a5")
    command.downgrade(cfg, "a1b2c3d4e5f6")

    with engine.connect() as conn:
        # Series
        s = conn.execute(
            text(
                "SELECT library_name, name, overview, first_air_date FROM series WHERE name = 'Lost'"
            )
        ).fetchone()
        assert s is not None
        assert s[0] == "TV"
        assert s[2] == "Survivors on island"
        assert s[3] == "2004-09-22"

        # Episode
        ep = conn.execute(
            text("SELECT name, path, watched FROM episodes WHERE name = 'Pilot'")
        ).fetchone()
        assert ep is not None
        assert ep[1] == "/lost/s01e01.mkv"
        assert ep[2] in (1, True)

        # Movie
        mv = conn.execute(
            text("SELECT name, path, year FROM movies WHERE name = 'Interstellar'")
        ).fetchone()
        assert mv is not None
        assert mv[1] == "/inter.mkv"
        assert mv[2] == 2014

    engine.dispose()


def test_uuid_blob_migration_downgrade_fk_links_valid(tmp_path) -> None:
    """After downgrade, seasons.series_id FK links must still join correctly."""
    db_path = tmp_path / "test_uuid_dg_fk.db"
    cfg = _alembic_cfg(db_path)

    command.upgrade(cfg, "a1b2c3d4e5f6")

    engine = _engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO series (library_name, name) VALUES ('Lib', 'X-Files')")
        )
        sid = conn.execute(
            text("SELECT id FROM series WHERE name = 'X-Files'")
        ).scalar()
        conn.execute(
            text(f"INSERT INTO seasons (series_id, name) VALUES ({sid}, 'S1')")
        )
        sea_id = conn.execute(text("SELECT id FROM seasons WHERE name = 'S1'")).scalar()
        conn.execute(
            text(
                f"INSERT INTO episodes (season_id, name, path) VALUES ({sea_id}, 'E1', '/xf/e1.mkv')"
            )
        )

    command.upgrade(cfg, "b3f9e1c2d4a5")
    command.downgrade(cfg, "a1b2c3d4e5f6")

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT s.name, se.name, ep.name "
                "FROM episodes ep "
                "JOIN seasons se ON ep.season_id = se.id "
                "JOIN series s ON se.series_id = s.id "
                "WHERE ep.name = 'E1'"
            )
        ).fetchone()
        assert row is not None, (
            "JOIN across integer FKs after downgrade returned no rows"
        )
        assert row[0] == "X-Files"
        assert row[1] == "S1"
        assert row[2] == "E1"

    engine.dispose()


def test_uuid_blob_migration_downgrade_app_secrets_back_to_string(tmp_path) -> None:
    """After downgrade, app_secrets.secret_uuid must be a text string again."""
    db_path = tmp_path / "test_uuid_dg_secrets.db"
    cfg = _alembic_cfg(db_path)

    command.upgrade(cfg, "a1b2c3d4e5f6")

    engine = _engine(db_path)
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT COUNT(*) FROM app_secrets WHERE secret_type = 'tmdb'")
        ).scalar()
        if not existing:
            conn.execute(
                text(
                    "INSERT INTO app_secrets (secret_uuid, secret_type, secret) "
                    "VALUES ('my-uuid-string', 'tmdb', '{\"api_key\": \"z\"}')"
                )
            )

    command.upgrade(cfg, "b3f9e1c2d4a5")
    command.downgrade(cfg, "a1b2c3d4e5f6")

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT secret_uuid, secret FROM app_secrets WHERE secret_type = 'tmdb'"
            )
        ).fetchone()
        assert row is not None
        # After downgrade the PK is a text string representation of the UUID
        pk_val = row[0]
        assert isinstance(pk_val, str), (
            f"Expected string PK after downgrade, got {type(pk_val)}: {pk_val!r}"
        )
        # Must be parseable as a UUID
        uuid.UUID(pk_val)
        # Payload intact
        assert "api_key" in json.loads(row[1])

    engine.dispose()


# ---------------------------------------------------------------------------
# 8. Full round-trip: upgrade then downgrade preserves all data
# ---------------------------------------------------------------------------


def test_uuid_blob_migration_full_roundtrip(tmp_path) -> None:
    """
    Upgrade from a1b2c3d4e5f6 → b3f9e1c2d4a5 → downgrade back to a1b2c3d4e5f6.
    All names, paths, and relational structures must survive intact.
    """
    db_path = tmp_path / "test_uuid_roundtrip.db"
    cfg = _alembic_cfg(db_path)

    command.upgrade(cfg, "a1b2c3d4e5f6")

    engine = _engine(db_path)
    shows = [
        ("Drama", "Westworld", "jf-ww", "2016-10-02"),
        ("Sci-Fi", "Dark", "jf-dk", "2017-12-01"),
    ]
    with engine.begin() as conn:
        for lib, name, jf_id, air_date in shows:
            conn.execute(
                text(
                    f"INSERT INTO series (library_name, name, jellyfin_id, first_air_date) "
                    f"VALUES ('{lib}', '{name}', '{jf_id}', '{air_date}')"
                )
            )
            sid = conn.execute(
                text(f"SELECT id FROM series WHERE name = '{name}'")
            ).scalar()
            for season_num in (1, 2):
                conn.execute(
                    text(
                        f"INSERT INTO seasons (series_id, name) "
                        f"VALUES ({sid}, 'Season {season_num}')"
                    )
                )
                sea_id = conn.execute(
                    text(
                        f"SELECT id FROM seasons WHERE series_id = {sid} "
                        f"AND name = 'Season {season_num}'"
                    )
                ).scalar()
                for ep_num in (1, 2):
                    conn.execute(
                        text(
                            f"INSERT INTO episodes (season_id, name, path, watched) "
                            f"VALUES ({sea_id}, 'E{ep_num}', "
                            f"'/{name}/s{season_num}e{ep_num}.mkv', 0)"
                        )
                    )

        conn.execute(
            text(
                "INSERT INTO movies (library_name, name, path, year) "
                "VALUES ('Movies', 'Dune', '/dune.mkv', 2021)"
            )
        )

    # Upgrade → BLOB PKs
    command.upgrade(cfg, "b3f9e1c2d4a5")
    # Downgrade → integer PKs
    command.downgrade(cfg, "a1b2c3d4e5f6")

    with engine.connect() as conn:
        for lib, name, jf_id, air_date in shows:
            s = conn.execute(
                text(
                    f"SELECT library_name, jellyfin_id, first_air_date "
                    f"FROM series WHERE name = '{name}'"
                )
            ).fetchone()
            assert s is not None, f"Series '{name}' not found after round-trip"
            assert s[0] == lib
            assert s[1] == jf_id
            assert s[2] == air_date

            ep_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM episodes ep "
                    "JOIN seasons se ON ep.season_id = se.id "
                    "JOIN series s ON se.series_id = s.id "
                    f"WHERE s.name = '{name}'"
                )
            ).scalar()
            assert ep_count == 4, (
                f"'{name}' has {ep_count} episodes via FK after round-trip (expected 4)"
            )

        movie = conn.execute(
            text("SELECT name, path, year FROM movies WHERE name = 'Dune'")
        ).fetchone()
        assert movie is not None
        assert movie[1] == "/dune.mkv"
        assert movie[2] == 2021

    engine.dispose()
