"""couple_playback_to_metadata

Revision ID: 2e8292adc104
Revises: aa368f3de380
Create Date: 2026-06-15 11:46:14.476149

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import lan_streamer.db.models
import uuid


# revision identifiers, used by Alembic.
revision: str = "2e8292adc104"
down_revision: Union[str, Sequence[str], None] = "aa368f3de380"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Rename existing playback_states table
    op.rename_table("playback_states", "_playback_states_old")

    # 2. Create new playback_states table
    op.create_table(
        "playback_states",
        sa.Column("id", lan_streamer.db.models.UUIDBLOB(), nullable=False),
        sa.Column("episode_id", lan_streamer.db.models.UUIDBLOB(), nullable=True),
        sa.Column("movie_id", lan_streamer.db.models.UUIDBLOB(), nullable=True),
        sa.Column("watched", sa.Boolean(), nullable=False),
        sa.Column("last_played_position", sa.Integer(), nullable=False),
        sa.Column("last_played_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("episode_id", name="uq_playback_states_episode_id"),
        sa.UniqueConstraint("movie_id", name="uq_playback_states_movie_id"),
    )

    # 3. Retrieve and migrate data
    old_records = bind.execute(
        sa.text(
            "SELECT sa.media_file_id, sa.watched, sa.last_played_position, sa.last_played_at, "
            "       map.episode_id, map.movie_id "
            "FROM _playback_states_old sa "
            "LEFT JOIN metadata_file_mappings map ON map.media_file_id = sa.media_file_id"
        )
    ).fetchall()

    # Aggregated state by metadata ID: (type, target_id) -> record
    aggregated = {}

    for mf_id, watched, last_pos, last_at, ep_id, mv_id in old_records:
        target_id = ep_id or mv_id
        if not target_id:
            continue
        is_ep = ep_id is not None
        key = ("episode" if is_ep else "movie", target_id)

        # Merge strategy: take the one with higher last_played_at, or if equal, watched=True
        if key not in aggregated:
            aggregated[key] = {
                "watched": bool(watched),
                "last_played_position": last_pos or 0,
                "last_played_at": last_at or 0,
            }
        else:
            existing = aggregated[key]
            if (last_at or 0) > existing["last_played_at"]:
                existing["last_played_at"] = last_at or 0
                existing["last_played_position"] = last_pos or 0
            if watched:
                existing["watched"] = True

    # Insert merged records into the new table
    for (item_type, target_id), data in aggregated.items():
        new_id = uuid.uuid4().bytes
        ep_val = target_id if item_type == "episode" else None
        mv_val = target_id if item_type == "movie" else None

        bind.execute(
            sa.text(
                "INSERT INTO playback_states (id, episode_id, movie_id, watched, last_played_position, last_played_at) "
                "VALUES (:id, :episode_id, :movie_id, :watched, :last_played_position, :last_played_at)"
            ),
            {
                "id": new_id,
                "episode_id": ep_val,
                "movie_id": mv_val,
                "watched": 1 if data["watched"] else 0,
                "last_played_position": data["last_played_position"],
                "last_played_at": data["last_played_at"],
            },
        )

    # 4. Drop old table
    op.drop_table("_playback_states_old")


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    # 1. Rename new table
    op.rename_table("playback_states", "_playback_states_new")

    # 2. Recreate old table
    op.create_table(
        "playback_states",
        sa.Column("media_file_id", lan_streamer.db.models.UUIDBLOB(), nullable=False),
        sa.Column("watched", sa.Boolean(), nullable=False),
        sa.Column("last_played_position", sa.Integer(), nullable=False),
        sa.Column("last_played_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("media_file_id"),
        sa.ForeignKeyConstraint(
            ["media_file_id"], ["media_files.id"], ondelete="CASCADE"
        ),
    )

    # 3. Retrieve and migrate data
    new_records = bind.execute(
        sa.text(
            "SELECT sa.episode_id, sa.movie_id, sa.watched, sa.last_played_position, sa.last_played_at, "
            "       map.media_file_id "
            "FROM _playback_states_new sa "
            "JOIN metadata_file_mappings map ON (map.episode_id = sa.episode_id OR map.movie_id = sa.movie_id)"
        )
    ).fetchall()

    # Insert into old table, avoiding duplicate primary key (media_file_id) issues
    seen_media_files = set()
    for ep_id, mv_id, watched, last_pos, last_at, mf_id in new_records:
        if mf_id in seen_media_files:
            continue
        seen_media_files.add(mf_id)

        bind.execute(
            sa.text(
                "INSERT INTO playback_states (media_file_id, watched, last_played_position, last_played_at) "
                "VALUES (:media_file_id, :watched, :last_played_position, :last_played_at)"
            ),
            {
                "media_file_id": mf_id,
                "watched": 1 if watched else 0,
                "last_played_position": last_pos,
                "last_played_at": last_at,
            },
        )

    # 4. Drop new table
    op.drop_table("_playback_states_new")
