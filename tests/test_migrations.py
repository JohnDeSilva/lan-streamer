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
