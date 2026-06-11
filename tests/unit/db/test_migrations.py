import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic import command


def test_air_date_migration_with_fake_data(tmp_path) -> None:
    """
    Robustly test Alembic migration cd94beb4248b -> 8dbcde9fc7de and downgrade
    using simulated real database rows to ensure complete schema compatibility.
    """
    db_path = tmp_path / "test_migration_fake_data.db"
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # 1. Upgrade to initial revision cd94beb4248b
    command.upgrade(alembic_cfg, "cd94beb4248b")

    # 2. Insert fake data representing user records before migration
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO series (id, library_name, name) VALUES ('1', 'Lib', 'Fake Show')"
            )
        )
        series_id = conn.execute(
            sa.text("SELECT id FROM series WHERE name='Fake Show'")
        ).scalar()

        conn.execute(
            sa.text(
                "INSERT INTO seasons (id, series_id, name) VALUES ('1', :series_id, 'Season 1')"
            ),
            {"series_id": series_id},
        )
        season_id = conn.execute(
            sa.text("SELECT id FROM seasons WHERE name='Season 1'")
        ).scalar()

        conn.execute(
            sa.text(
                "INSERT INTO episodes (id, season_id, name, path) VALUES ('1', :season_id, 'Ep 1', '/fake/path')"
            ),
            {"season_id": season_id},
        )

    # 3. Upgrade to our target revision 8dbcde9fc7de
    command.upgrade(alembic_cfg, "8dbcde9fc7de")

    # 4. Verify fake data preservation and confirm new columns exist
    with engine.connect() as conn:
        series_row = conn.execute(
            sa.text("SELECT name, first_air_date FROM series WHERE id='1'")
        ).fetchone()
        assert series_row[0] == "Fake Show"
        assert series_row[1] is None

        ep_row = conn.execute(
            sa.text("SELECT name, air_date FROM episodes WHERE id='1'")
        ).fetchone()
        assert ep_row[0] == "Ep 1"
        assert ep_row[1] is None

        conn.execute(
            sa.text("UPDATE series SET first_air_date='2025-01-01' WHERE id='1'")
        )
        conn.execute(sa.text("UPDATE episodes SET air_date='2025-01-02' WHERE id='1'"))
        conn.commit()

        updated_series = conn.execute(
            sa.text("SELECT first_air_date FROM series WHERE id='1'")
        ).scalar()
        assert updated_series == "2025-01-01"

    # 5. Verify downgrade functionality cleanly strips schema extensions while preserving core items
    command.downgrade(alembic_cfg, "cd94beb4248b")
    with engine.connect() as conn:
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(sa.text("SELECT first_air_date FROM series")).fetchall()
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(sa.text("SELECT air_date FROM episodes")).fetchall()

        assert (
            conn.execute(sa.text("SELECT name FROM series WHERE id='1'")).scalar()
            == "Fake Show"
        )

    engine.dispose()


def test_playback_position_migration_with_fake_data(tmp_path) -> None:
    """
    Robustly test Alembic migration 8dbcde9fc7de -> e5421f98bc12 and downgrade
    verifying preservation of existing fields and default NULL availability.
    """
    db_path = tmp_path / "test_migration_fake_data_pos.db"
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # 1. Upgrade to previous revision 8dbcde9fc7de
    command.upgrade(alembic_cfg, "8dbcde9fc7de")

    # 2. Insert fake data representing user records before migration
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO series (id, library_name, name) VALUES ('1', 'Lib', 'Fake Series')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO seasons (id, series_id, name) VALUES ('1', '1', 'Season 1')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO episodes (id, season_id, name, path) VALUES ('1', '1', 'Ep 1', '/fake/path/pos')"
            )
        )

    # 3. Upgrade to our target revision e5421f98bc12
    command.upgrade(alembic_cfg, "e5421f98bc12")

    # 4. Verify fake data preservation and confirm new column exists
    with engine.connect() as conn:
        ep_row = conn.execute(
            sa.text("SELECT name, last_played_position FROM episodes WHERE id='1'")
        ).fetchone()
        assert ep_row[0] == "Ep 1"
        assert ep_row[1] is None

        conn.execute(
            sa.text("UPDATE episodes SET last_played_position=120 WHERE id='1'")
        )
        conn.commit()

        updated_pos = conn.execute(
            sa.text("SELECT last_played_position FROM episodes WHERE id='1'")
        ).scalar()
        assert updated_pos == 120

    # 5. Verify downgrade functionality cleanly strips the column
    command.downgrade(alembic_cfg, "8dbcde9fc7de")
    with engine.connect() as conn:
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(
                sa.text("SELECT last_played_position FROM episodes")
            ).fetchall()

        assert (
            conn.execute(sa.text("SELECT name FROM episodes WHERE id='1'")).scalar()
            == "Ep 1"
        )

    engine.dispose()


def test_movies_table_migration_with_fake_data(tmp_path) -> None:
    """
    Robustly test Alembic migration e5421f98bc12 -> 1d504caf3889 and downgrade
    verifying creation and removal of the movies table.
    """
    db_path = tmp_path / "test_migration_fake_data_movies.db"
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # 1. Upgrade to previous revision e5421f98bc12
    command.upgrade(alembic_cfg, "e5421f98bc12")

    # 2. Insert fake data representing user records before migration
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO series (id, library_name, name) VALUES ('1', 'Lib', 'Fake Series')"
            )
        )

    # 3. Upgrade to our target revision 1d504caf3889
    command.upgrade(alembic_cfg, "1d504caf3889")

    # 4. Verify new table exists and insert data
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO movies (id, library_name, name, path) VALUES ('1', 'Movies', 'Fake Movie', '/fake/movie.mp4')"
            )
        )

    with engine.connect() as conn:
        movie_row = conn.execute(
            sa.text("SELECT name, path FROM movies WHERE id='1'")
        ).fetchone()
        assert movie_row[0] == "Fake Movie"
        assert movie_row[1] == "/fake/movie.mp4"

    # 5. Verify downgrade functionality cleanly drops the table
    command.downgrade(alembic_cfg, "e5421f98bc12")
    with engine.connect() as conn:
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(sa.text("SELECT * FROM movies")).fetchall()

        assert (
            conn.execute(sa.text("SELECT name FROM series WHERE id='1'")).scalar()
            == "Fake Series"
        )

    engine.dispose()


def test_episodes_runtime_migration_with_fake_data(tmp_path) -> None:
    """
    Robustly test Alembic migration 1d504caf3889 -> fa4ad8226f3a and downgrade
    verifying clean addition, nullability, update preservation, and column drop of runtime.
    """
    db_path = tmp_path / "test_migration_fake_data_runtime.db"
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # 1. Upgrade to previous revision 1d504caf3889
    command.upgrade(alembic_cfg, "1d504caf3889")

    # 2. Insert fake data representing user records before migration
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO series (id, library_name, name) VALUES ('1', 'Lib', 'Fake Series')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO seasons (id, series_id, name) VALUES ('1', '1', 'Season 1')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO episodes (id, season_id, name, path) VALUES ('1', '1', 'Ep 1', '/fake/path/runtime')"
            )
        )

    # 3. Upgrade to our target revision fa4ad8226f3a
    command.upgrade(alembic_cfg, "fa4ad8226f3a")

    # 4. Verify fake data preservation and confirm new column exists as nullable
    with engine.connect() as conn:
        ep_row = conn.execute(
            sa.text("SELECT name, runtime FROM episodes WHERE id='1'")
        ).fetchone()
        assert ep_row[0] == "Ep 1"
        assert ep_row[1] is None

        conn.execute(sa.text("UPDATE episodes SET runtime=45 WHERE id='1'"))
        conn.commit()

        updated_runtime = conn.execute(
            sa.text("SELECT runtime FROM episodes WHERE id='1'")
        ).scalar()
        assert updated_runtime == 45

    # 5. Verify downgrade functionality cleanly strips the column
    command.downgrade(alembic_cfg, "1d504caf3889")
    with engine.connect() as conn:
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(sa.text("SELECT runtime FROM episodes")).fetchall()

        assert (
            conn.execute(sa.text("SELECT name FROM episodes WHERE id='1'")).scalar()
            == "Ep 1"
        )

    engine.dispose()


def test_last_played_at_migration_with_fake_data(tmp_path) -> None:
    """
    Robustly test Alembic migration fa4ad8226f3a -> ce128c6d8aec and downgrade
    verifying clean addition, default value, update preservation, and column drop of last_played_at.
    """
    db_path = tmp_path / "test_migration_fake_data_last_played_at.db"
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # 1. Upgrade to previous revision fa4ad8226f3a
    command.upgrade(alembic_cfg, "fa4ad8226f3a")

    # 2. Insert fake data representing user records before migration
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO series (id, library_name, name) VALUES ('1', 'Lib', 'Fake Series')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO seasons (id, series_id, name) VALUES ('1', '1', 'Season 1')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO episodes (id, season_id, name, path) VALUES ('1', '1', 'Ep 1', '/fake/path/lp_ep')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO movies (id, library_name, name, path) VALUES ('1', 'Movies', 'Fake Movie', '/fake/path/lp_mv')"
            )
        )

    # 3. Upgrade to our target revision ce128c6d8aec
    command.upgrade(alembic_cfg, "ce128c6d8aec")

    # 4. Verify fake data preservation and confirm new column exists with default 0
    with engine.connect() as conn:
        ep_row = conn.execute(
            sa.text("SELECT name, last_played_at FROM episodes WHERE id='1'")
        ).fetchone()
        assert ep_row[0] == "Ep 1"
        assert ep_row[1] == 0 or ep_row[1] is None

        mv_row = conn.execute(
            sa.text("SELECT name, last_played_at FROM movies WHERE id='1'")
        ).fetchone()
        assert mv_row[0] == "Fake Movie"
        assert mv_row[1] == 0 or mv_row[1] is None

        conn.execute(sa.text("UPDATE episodes SET last_played_at=12345 WHERE id='1'"))
        conn.execute(sa.text("UPDATE movies SET last_played_at=67890 WHERE id='1'"))
        conn.commit()

        assert (
            conn.execute(
                sa.text("SELECT last_played_at FROM episodes WHERE id='1'")
            ).scalar()
            == 12345
        )
        assert (
            conn.execute(
                sa.text("SELECT last_played_at FROM movies WHERE id='1'")
            ).scalar()
            == 67890
        )

    # 5. Verify downgrade functionality cleanly strips the column
    command.downgrade(alembic_cfg, "fa4ad8226f3a")
    with engine.connect() as conn:
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(sa.text("SELECT last_played_at FROM episodes")).fetchall()
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(sa.text("SELECT last_played_at FROM movies")).fetchall()

        assert (
            conn.execute(sa.text("SELECT name FROM episodes WHERE id='1'")).scalar()
            == "Ep 1"
        )
        assert (
            conn.execute(sa.text("SELECT name FROM movies WHERE id='1'")).scalar()
            == "Fake Movie"
        )

    engine.dispose()


def test_settings_to_db_migration(tmp_path) -> None:
    """Test seeding from config.json to app_config/app_secrets/series tables during alembic migration."""
    import json

    fake_home = tmp_path / "fake_home"
    config_file = fake_home / ".config" / "lan-streamer" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "test_migration_settings.db"

    with open(config_file, "w") as f:
        json.dump(
            {
                "root_dirs": ["/old/path"],
                "tvdb_api_key": "old_tvdb_key",
                "jellyfin_url": "http://jellyfin",
                "jellyfin_api_key": "jf_key",
                "libraries": {"OldLib": ["/some/path"]},
                "series_preferences": {
                    "TV:Breaking Bad": {
                        "hide_missing_future": True,
                        "display_group_id": "group1",
                    }
                },
            },
            f,
        )

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # 90c0fcb92ee7 is one of the heads before our settings migration. We need to merge them.
    # Actually, we can upgrade to 90c0fcb92ee7 then migrate.
    command.upgrade(alembic_cfg, "90c0fcb92ee7")

    # Insert a dummy series representing TV:Breaking Bad to check back-fill
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO series (id, library_name, name) VALUES ('1', 'TV', 'Breaking Bad')"
            )
        )

    from unittest.mock import patch

    with patch("pathlib.Path.home", return_value=fake_home):
        command.upgrade(alembic_cfg, "a1b2c3d4e5f6")

    # Verify the database has migrated settings
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT key, value FROM app_config")).fetchall()
        cfg_dict = dict(rows)
        libraries = json.loads(cfg_dict["libraries"])
        assert libraries["OldLib"]["paths"] == ["/some/path"]
        assert libraries["OldLib"]["type"] == "tv"

        secrets = conn.execute(
            sa.text("SELECT secret_type, secret FROM app_secrets")
        ).fetchall()
        sec_dict = {r[0]: json.loads(r[1]) for r in secrets}
        assert sec_dict["jellyfin"]["url"] == "http://jellyfin"
        assert sec_dict["jellyfin"]["api_key"] == "jf_key"
        assert sec_dict["tmdb"]["api_key"] == "old_tvdb_key"

        series_pref = conn.execute(
            sa.text(
                "SELECT pref_hide_missing_future, pref_display_group_id FROM series WHERE name='Breaking Bad'"
            )
        ).fetchone()
        assert series_pref[0] == 1 or series_pref[0] is True
        assert series_pref[1] == "group1"

    engine.dispose()
