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
                "INSERT INTO series (library_name, name) VALUES ('Lib', 'Fake Show')"
            )
        )
        series_id = conn.execute(
            sa.text("SELECT id FROM series WHERE name='Fake Show'")
        ).scalar()

        conn.execute(
            sa.text(
                f"INSERT INTO seasons (series_id, name) VALUES ({series_id}, 'Season 1')"
            )
        )
        season_id = conn.execute(
            sa.text("SELECT id FROM seasons WHERE name='Season 1'")
        ).scalar()

        conn.execute(
            sa.text(
                f"INSERT INTO episodes (season_id, name, path) VALUES ({season_id}, 'Ep 1', '/fake/path')"
            )
        )

    # 3. Upgrade to our target revision 8dbcde9fc7de
    command.upgrade(alembic_cfg, "8dbcde9fc7de")

    # 4. Verify fake data preservation and confirm new columns exist
    with engine.connect() as conn:
        series_row = conn.execute(
            sa.text("SELECT name, first_air_date FROM series WHERE id=1")
        ).fetchone()
        assert series_row[0] == "Fake Show"
        assert series_row[1] is None

        ep_row = conn.execute(
            sa.text("SELECT name, air_date FROM episodes WHERE id=1")
        ).fetchone()
        assert ep_row[0] == "Ep 1"
        assert ep_row[1] is None

        conn.execute(
            sa.text("UPDATE series SET first_air_date='2025-01-01' WHERE id=1")
        )
        conn.execute(sa.text("UPDATE episodes SET air_date='2025-01-02' WHERE id=1"))
        conn.commit()

        updated_series = conn.execute(
            sa.text("SELECT first_air_date FROM series WHERE id=1")
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
            conn.execute(sa.text("SELECT name FROM series WHERE id=1")).scalar()
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
                "INSERT INTO series (library_name, name) VALUES ('Lib', 'Fake Series')"
            )
        )
        conn.execute(
            sa.text("INSERT INTO seasons (series_id, name) VALUES (1, 'Season 1')")
        )
        conn.execute(
            sa.text(
                "INSERT INTO episodes (season_id, name, path) VALUES (1, 'Ep 1', '/fake/path/pos')"
            )
        )

    # 3. Upgrade to our target revision e5421f98bc12
    command.upgrade(alembic_cfg, "e5421f98bc12")

    # 4. Verify fake data preservation and confirm new column exists
    with engine.connect() as conn:
        ep_row = conn.execute(
            sa.text("SELECT name, last_played_position FROM episodes WHERE id=1")
        ).fetchone()
        assert ep_row[0] == "Ep 1"
        assert ep_row[1] is None

        conn.execute(sa.text("UPDATE episodes SET last_played_position=120 WHERE id=1"))
        conn.commit()

        updated_pos = conn.execute(
            sa.text("SELECT last_played_position FROM episodes WHERE id=1")
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
            conn.execute(sa.text("SELECT name FROM episodes WHERE id=1")).scalar()
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
                "INSERT INTO series (library_name, name) VALUES ('Lib', 'Fake Series')"
            )
        )

    # 3. Upgrade to our target revision 1d504caf3889
    command.upgrade(alembic_cfg, "1d504caf3889")

    # 4. Verify new table exists and insert data
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO movies (library_name, name, path) VALUES ('Movies', 'Fake Movie', '/fake/movie.mp4')"
            )
        )

    with engine.connect() as conn:
        movie_row = conn.execute(
            sa.text("SELECT name, path FROM movies WHERE id=1")
        ).fetchone()
        assert movie_row[0] == "Fake Movie"
        assert movie_row[1] == "/fake/movie.mp4"

    # 5. Verify downgrade functionality cleanly drops the table
    command.downgrade(alembic_cfg, "e5421f98bc12")
    with engine.connect() as conn:
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(sa.text("SELECT * FROM movies")).fetchall()

        assert (
            conn.execute(sa.text("SELECT name FROM series WHERE id=1")).scalar()
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
                "INSERT INTO series (library_name, name) VALUES ('Lib', 'Fake Series')"
            )
        )
        conn.execute(
            sa.text("INSERT INTO seasons (series_id, name) VALUES (1, 'Season 1')")
        )
        conn.execute(
            sa.text(
                "INSERT INTO episodes (season_id, name, path) VALUES (1, 'Ep 1', '/fake/path/runtime')"
            )
        )

    # 3. Upgrade to our target revision fa4ad8226f3a
    command.upgrade(alembic_cfg, "fa4ad8226f3a")

    # 4. Verify fake data preservation and confirm new column exists as nullable
    with engine.connect() as conn:
        ep_row = conn.execute(
            sa.text("SELECT name, runtime FROM episodes WHERE id=1")
        ).fetchone()
        assert ep_row[0] == "Ep 1"
        assert ep_row[1] is None

        conn.execute(sa.text("UPDATE episodes SET runtime=45 WHERE id=1"))
        conn.commit()

        updated_runtime = conn.execute(
            sa.text("SELECT runtime FROM episodes WHERE id=1")
        ).scalar()
        assert updated_runtime == 45

    # 5. Verify downgrade functionality cleanly strips the column
    command.downgrade(alembic_cfg, "1d504caf3889")
    with engine.connect() as conn:
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(sa.text("SELECT runtime FROM episodes")).fetchall()

        assert (
            conn.execute(sa.text("SELECT name FROM episodes WHERE id=1")).scalar()
            == "Ep 1"
        )

    engine.dispose()
