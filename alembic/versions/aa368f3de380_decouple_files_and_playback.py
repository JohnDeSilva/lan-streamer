"""decouple_files_and_playback

Revision ID: aa368f3de380
Revises: 701d935de074
Create Date: 2026-06-12 16:44:32.903601

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import lan_streamer.db.models
import uuid


# revision identifiers, used by Alembic.
revision: str = "aa368f3de380"
down_revision: Union[str, Sequence[str], None] = "701d935de074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Create playback_states and metadata_file_mappings tables
    op.create_table(
        "playback_states",
        sa.Column("media_file_id", lan_streamer.db.models.UUIDBLOB(), nullable=False),
        sa.Column("watched", sa.Boolean(), nullable=False),
        sa.Column("last_played_position", sa.Integer(), nullable=False),
        sa.Column("last_played_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_file_id"], ["media_files.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("media_file_id"),
    )
    op.create_table(
        "metadata_file_mappings",
        sa.Column("id", lan_streamer.db.models.UUIDBLOB(), nullable=False),
        sa.Column("media_file_id", lan_streamer.db.models.UUIDBLOB(), nullable=False),
        sa.Column("episode_id", lan_streamer.db.models.UUIDBLOB(), nullable=True),
        sa.Column("movie_id", lan_streamer.db.models.UUIDBLOB(), nullable=True),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["media_file_id"], ["media_files.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "media_file_id", "episode_id", "movie_id", name="uq_metadata_file_mappings"
        ),
    )

    # 2. Extract mappings and insert them into metadata_file_mappings
    media_files = bind.execute(
        sa.text("SELECT id, episode_id, movie_id FROM media_files")
    ).fetchall()
    for mf_id, ep_id, mv_id in media_files:
        if ep_id or mv_id:
            mapping_uuid = uuid.uuid4().bytes
            bind.execute(
                sa.text(
                    "INSERT INTO metadata_file_mappings (id, media_file_id, episode_id, movie_id) "
                    "VALUES (:id, :media_file_id, :episode_id, :movie_id)"
                ),
                {
                    "id": mapping_uuid,
                    "media_file_id": mf_id,
                    "episode_id": ep_id,
                    "movie_id": mv_id,
                },
            )

    # 3. Extract and insert playback_states
    episode_playback = bind.execute(
        sa.text(
            "SELECT m.id, e.watched, e.last_played_position, e.last_played_at "
            "FROM episodes e JOIN media_files m ON m.episode_id = e.id"
        )
    ).fetchall()
    for mf_id, watched, last_pos, last_at in episode_playback:
        bind.execute(
            sa.text(
                "INSERT INTO playback_states (media_file_id, watched, last_played_position, last_played_at) "
                "VALUES (:media_file_id, :watched, :last_played_position, :last_played_at)"
            ),
            {
                "media_file_id": mf_id,
                "watched": bool(watched),
                "last_played_position": last_pos or 0,
                "last_played_at": last_at or 0,
            },
        )

    movie_playback = bind.execute(
        sa.text(
            "SELECT m.id, mv.watched, mv.last_played_position, mv.last_played_at "
            "FROM movies mv JOIN media_files m ON m.movie_id = mv.id"
        )
    ).fetchall()
    for mf_id, watched, last_pos, last_at in movie_playback:
        bind.execute(
            sa.text(
                "INSERT INTO playback_states (media_file_id, watched, last_played_position, last_played_at) "
                "VALUES (:media_file_id, :watched, :last_played_position, :last_played_at)"
            ),
            {
                "media_file_id": mf_id,
                "watched": bool(watched),
                "last_played_position": last_pos or 0,
                "last_played_at": last_at or 0,
            },
        )

    # 4. Alter tables to drop old columns
    with op.batch_alter_table("episodes", recreate="always") as batch_op:
        batch_op.drop_column("last_played_position")
        batch_op.drop_column("last_played_at")
        batch_op.drop_column("video_codec")
        batch_op.drop_column("watched")

    with op.batch_alter_table("movies", recreate="always") as batch_op:
        batch_op.drop_column("last_played_position")
        batch_op.drop_column("last_played_at")
        batch_op.drop_column("video_codec")
        batch_op.drop_column("watched")

    with op.batch_alter_table("media_files", recreate="always") as batch_op:
        batch_op.drop_column("episode_id")
        batch_op.drop_column("movie_id")


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    # 1. Restore columns
    with op.batch_alter_table("movies", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("watched", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("video_codec", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "last_played_at",
                sa.Integer(),
                server_default=sa.text("'0'"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("last_played_position", sa.Integer(), nullable=True)
        )

    with op.batch_alter_table("episodes", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("watched", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("video_codec", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "last_played_at",
                sa.Integer(),
                server_default=sa.text("'0'"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("last_played_position", sa.Integer(), nullable=True)
        )

    with op.batch_alter_table("media_files", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column("movie_id", lan_streamer.db.models.UUIDBLOB(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("episode_id", lan_streamer.db.models.UUIDBLOB(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_media_files_episode",
            "episodes",
            ["episode_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_media_files_movie", "movies", ["movie_id"], ["id"], ondelete="CASCADE"
        )

    # 2. Restore episode playback states
    ep_playback = bind.execute(
        sa.text(
            "SELECT map.episode_id, ps.watched, ps.last_played_position, ps.last_played_at "
            "FROM playback_states ps "
            "JOIN metadata_file_mappings map ON map.media_file_id = ps.media_file_id "
            "WHERE map.episode_id IS NOT NULL"
        )
    ).fetchall()
    for ep_id, watched, last_pos, last_at in ep_playback:
        bind.execute(
            sa.text(
                "UPDATE episodes SET watched = :watched, last_played_position = :last_pos, last_played_at = :last_at "
                "WHERE id = :id"
            ),
            {"id": ep_id, "watched": watched, "last_pos": last_pos, "last_at": last_at},
        )

    # 3. Restore movie playback states
    mv_playback = bind.execute(
        sa.text(
            "SELECT map.movie_id, ps.watched, ps.last_played_position, ps.last_played_at "
            "FROM playback_states ps "
            "JOIN metadata_file_mappings map ON map.media_file_id = ps.media_file_id "
            "WHERE map.movie_id IS NOT NULL"
        )
    ).fetchall()
    for mv_id, watched, last_pos, last_at in mv_playback:
        bind.execute(
            sa.text(
                "UPDATE movies SET watched = :watched, last_played_position = :last_pos, last_played_at = :last_at "
                "WHERE id = :id"
            ),
            {"id": mv_id, "watched": watched, "last_pos": last_pos, "last_at": last_at},
        )

    # 4. Restore media_files foreign keys
    mappings = bind.execute(
        sa.text(
            "SELECT media_file_id, episode_id, movie_id FROM metadata_file_mappings"
        )
    ).fetchall()
    for mf_id, ep_id, mv_id in mappings:
        bind.execute(
            sa.text(
                "UPDATE media_files SET episode_id = :episode_id, movie_id = :movie_id WHERE id = :id"
            ),
            {"id": mf_id, "episode_id": ep_id, "movie_id": mv_id},
        )

    # 5. Drop tables
    op.drop_table("metadata_file_mappings")
    op.drop_table("playback_states")
