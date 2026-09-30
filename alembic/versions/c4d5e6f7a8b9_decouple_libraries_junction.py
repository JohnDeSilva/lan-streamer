"""decouple_libraries_junction

Revision ID: c4d5e6f7a8b9
Revises: bbd1b7ccd143
Create Date: 2026-09-30 11:20:00.000000

"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "bbd1b7ccd143"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: Create junction tables, migrate and deduplicate data, drop old unique constraints."""
    # 1. Create series_libraries table
    op.create_table(
        "series_libraries",
        sa.Column("id", sa.LargeBinary(), nullable=False),
        sa.Column("series_id", sa.LargeBinary(), nullable=False),
        sa.Column("library_name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "series_id",
            "library_name",
            name="uq_series_libraries_series_id_library_name",
        ),
    )
    op.create_index(
        op.f("ix_series_libraries_series_id"),
        "series_libraries",
        ["series_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_series_libraries_library_name"),
        "series_libraries",
        ["library_name"],
        unique=False,
    )

    # 2. Create movie_libraries table
    op.create_table(
        "movie_libraries",
        sa.Column("id", sa.LargeBinary(), nullable=False),
        sa.Column("movie_id", sa.LargeBinary(), nullable=False),
        sa.Column("library_name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "movie_id", "library_name", name="uq_movie_libraries_movie_id_library_name"
        ),
    )
    op.create_index(
        op.f("ix_movie_libraries_movie_id"),
        "movie_libraries",
        ["movie_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_movie_libraries_library_name"),
        "movie_libraries",
        ["library_name"],
        unique=False,
    )

    # 3. Data Migration & Deduplication
    conn = op.get_bind()

    # --- Deduplicate & Populate TV Series ---
    series_rows = conn.execute(
        sa.text(
            "SELECT id, library_name, name, tmdb_identifier FROM series ORDER BY name, id"
        )
    ).fetchall()

    series_groups: dict[str, list[sa.Row]] = {}
    for row in series_rows:
        row_dict = row._mapping
        tmdb_identifier = row_dict.get("tmdb_identifier")
        series_name = row_dict.get("name") or ""
        key = (
            f"tmdb:{tmdb_identifier}"
            if tmdb_identifier
            else f"name:{series_name.strip().lower()}"
        )
        series_groups.setdefault(key, []).append(row)

    for group in series_groups.values():
        primary_row = group[0]._mapping
        primary_id = primary_row["id"]

        recorded_libraries: set[str] = set()

        for index, item_row in enumerate(group):
            mapping = item_row._mapping
            item_id = mapping["id"]
            library_name = mapping.get("library_name")

            if library_name and library_name not in recorded_libraries:
                conn.execute(
                    sa.text(
                        "INSERT OR IGNORE INTO series_libraries (id, series_id, library_name) "
                        "VALUES (:id, :series_id, :library_name)"
                    ),
                    {
                        "id": uuid.uuid4().bytes,
                        "series_id": primary_id,
                        "library_name": library_name,
                    },
                )
                recorded_libraries.add(library_name)

            if index > 0:
                # Merge seasons from duplicate series into primary series
                dup_seasons = conn.execute(
                    sa.text(
                        "SELECT id, name FROM seasons WHERE series_id = :series_id"
                    ),
                    {"series_id": item_id},
                ).fetchall()

                for dup_season in dup_seasons:
                    dup_season_mapping = dup_season._mapping
                    dup_season_id = dup_season_mapping["id"]
                    dup_season_name = dup_season_mapping["name"]

                    # Check if matching season exists in primary
                    existing_primary_season = conn.execute(
                        sa.text(
                            "SELECT id FROM seasons WHERE series_id = :series_id AND name = :name"
                        ),
                        {"series_id": primary_id, "name": dup_season_name},
                    ).fetchone()

                    if existing_primary_season:
                        primary_season_id = existing_primary_season[0]
                        # Move episodes to existing season
                        conn.execute(
                            sa.text(
                                "UPDATE episodes SET season_id = :primary_season_id WHERE season_id = :dup_season_id"
                            ),
                            {
                                "primary_season_id": primary_season_id,
                                "dup_season_id": dup_season_id,
                            },
                        )
                        # Delete duplicate season
                        conn.execute(
                            sa.text("DELETE FROM seasons WHERE id = :dup_season_id"),
                            {"dup_season_id": dup_season_id},
                        )
                    else:
                        # Move season to primary series
                        conn.execute(
                            sa.text(
                                "UPDATE seasons SET series_id = :primary_id WHERE id = :dup_season_id"
                            ),
                            {"primary_id": primary_id, "dup_season_id": dup_season_id},
                        )

                # Move cast and images
                conn.execute(
                    sa.text(
                        "UPDATE media_cast SET series_id = :primary_id WHERE series_id = :item_id"
                    ),
                    {"primary_id": primary_id, "item_id": item_id},
                )
                conn.execute(
                    sa.text(
                        "UPDATE media_images SET series_id = :primary_id WHERE series_id = :item_id"
                    ),
                    {"primary_id": primary_id, "item_id": item_id},
                )
                # Delete duplicate series record
                conn.execute(
                    sa.text("DELETE FROM series WHERE id = :item_id"),
                    {"item_id": item_id},
                )

    # --- Deduplicate & Populate Movies ---
    movie_rows = conn.execute(
        sa.text(
            "SELECT id, library_name, name, tmdb_identifier FROM movies ORDER BY name, id"
        )
    ).fetchall()

    movie_groups: dict[str, list[sa.Row]] = {}
    for row in movie_rows:
        row_dict = row._mapping
        tmdb_identifier = row_dict.get("tmdb_identifier")
        movie_name = row_dict.get("name") or ""
        key = (
            f"tmdb:{tmdb_identifier}"
            if tmdb_identifier
            else f"name:{movie_name.strip().lower()}"
        )
        movie_groups.setdefault(key, []).append(row)

    for group in movie_groups.values():
        primary_row = group[0]._mapping
        primary_id = primary_row["id"]

        recorded_movie_libraries: set[str] = set()

        for index, item_row in enumerate(group):
            mapping = item_row._mapping
            item_id = mapping["id"]
            library_name = mapping.get("library_name")

            if library_name and library_name not in recorded_movie_libraries:
                conn.execute(
                    sa.text(
                        "INSERT OR IGNORE INTO movie_libraries (id, movie_id, library_name) "
                        "VALUES (:id, :movie_id, :library_name)"
                    ),
                    {
                        "id": uuid.uuid4().bytes,
                        "movie_id": primary_id,
                        "library_name": library_name,
                    },
                )
                recorded_movie_libraries.add(library_name)

            if index > 0:
                # Re-parent file mappings
                conn.execute(
                    sa.text(
                        "UPDATE metadata_file_mappings SET movie_id = :primary_id WHERE movie_id = :item_id"
                    ),
                    {"primary_id": primary_id, "item_id": item_id},
                )
                # Re-parent cast & images
                conn.execute(
                    sa.text(
                        "UPDATE media_cast SET movie_id = :primary_id WHERE movie_id = :item_id"
                    ),
                    {"primary_id": primary_id, "item_id": item_id},
                )
                conn.execute(
                    sa.text(
                        "UPDATE media_images SET movie_id = :primary_id WHERE movie_id = :item_id"
                    ),
                    {"primary_id": primary_id, "item_id": item_id},
                )
                # Re-parent playback_state if primary has none
                conn.execute(
                    sa.text(
                        "UPDATE playback_states SET movie_id = :primary_id "
                        "WHERE movie_id = :item_id AND NOT EXISTS ("
                        "  SELECT 1 FROM playback_states WHERE movie_id = :primary_id"
                        ")"
                    ),
                    {"primary_id": primary_id, "item_id": item_id},
                )
                # Delete duplicate movie record
                conn.execute(
                    sa.text("DELETE FROM movies WHERE id = :item_id"),
                    {"item_id": item_id},
                )

    # 4. Drop unique constraints and add indexes.
    # We temporarily drop existing triggers and restore them so SQLite does not fail foreign trigger validation on table rename.
    triggers = conn.execute(
        sa.text(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND sql IS NOT NULL"
        )
    ).fetchall()

    for trigger_row in triggers:
        trigger_name = trigger_row[0]
        conn.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger_name}"))

    with op.batch_alter_table("series") as batch_op:
        batch_op.drop_constraint("uq_series_library_name_name", type_="unique")
        batch_op.create_index(
            "ix_series_tmdb_identifier", ["tmdb_identifier"], unique=False
        )
        batch_op.create_index("ix_series_name", ["name"], unique=False)

    with op.batch_alter_table("movies") as batch_op:
        batch_op.drop_constraint("uq_movies_library_name_name", type_="unique")
        batch_op.create_index(
            "ix_movies_tmdb_identifier", ["tmdb_identifier"], unique=False
        )
        batch_op.create_index("ix_movies_name", ["name"], unique=False)

    for trigger_row in triggers:
        trigger_sql = trigger_row[1]
        conn.execute(sa.text(trigger_sql))


def downgrade() -> None:
    """Downgrade schema: Restore unique constraints, drop indexes, drop junction tables."""
    conn = op.get_bind()
    triggers = conn.execute(
        sa.text(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND sql IS NOT NULL"
        )
    ).fetchall()

    for trigger_row in triggers:
        trigger_name = trigger_row[0]
        conn.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger_name}"))

    with op.batch_alter_table("movies") as batch_op:
        batch_op.drop_index("ix_movies_name")
        batch_op.drop_index("ix_movies_tmdb_identifier")
        batch_op.create_unique_constraint(
            "uq_movies_library_name_name", ["library_name", "name"]
        )

    with op.batch_alter_table("series") as batch_op:
        batch_op.drop_index("ix_series_name")
        batch_op.drop_index("ix_series_tmdb_identifier")
        batch_op.create_unique_constraint(
            "uq_series_library_name_name", ["library_name", "name"]
        )

    for trigger_row in triggers:
        trigger_sql = trigger_row[1]
        conn.execute(sa.text(trigger_sql))

    op.drop_index(op.f("ix_movie_libraries_library_name"), table_name="movie_libraries")
    op.drop_index(op.f("ix_movie_libraries_movie_id"), table_name="movie_libraries")
    op.drop_table("movie_libraries")

    op.drop_index(
        op.f("ix_series_libraries_library_name"), table_name="series_libraries"
    )
    op.drop_index(op.f("ix_series_libraries_series_id"), table_name="series_libraries")
    op.drop_table("series_libraries")
