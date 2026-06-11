"""add_media_files_and_remove_unused_columns

Revision ID: 49d186288d29
Revises: b3f9e1c2d4a5
Create Date: 2026-06-11 15:34:23.281014

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "49d186288d29"
down_revision: Union[str, Sequence[str], None] = "b3f9e1c2d4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create media_files and migrate existing paths and technical columns."""
    bind = op.get_bind()

    # 1. Create the new media_files table
    op.create_table(
        "media_files",
        sa.Column("id", sa.LargeBinary(), nullable=False),
        sa.Column("episode_id", sa.LargeBinary(), nullable=True),
        sa.Column("movie_id", sa.LargeBinary(), nullable=True),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("video_type", sa.String(), nullable=True),
        sa.Column("video_codec", sa.String(), nullable=True),
        sa.Column("resolution", sa.String(), nullable=True),
        sa.Column("bit_rate", sa.Integer(), nullable=True),
        sa.Column("audio_tracks", sa.String(), nullable=True),
        sa.Column("subtitle_tracks", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )

    # 2. Select existing episodes data to migrate
    episode_rows = bind.execute(
        sa.text(
            "SELECT id, path, video_codec, resolution, audio_tracks, subtitle_tracks FROM episodes"
        )
    ).fetchall()

    # 3. Select existing movies data to migrate
    movie_rows = bind.execute(
        sa.text(
            "SELECT id, path, video_codec, resolution, audio_tracks, subtitle_tracks FROM movies"
        )
    ).fetchall()

    # 4. Alter episodes table
    with op.batch_alter_table("episodes", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("default_path", sa.String(), nullable=True))
        batch_op.drop_column("subtitle_tracks")
        batch_op.drop_column("audio_tracks")
        batch_op.drop_column("resolution")
        batch_op.drop_column("path")

    # 5. Alter movies table
    with op.batch_alter_table("movies", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("default_path", sa.String(), nullable=True))
        batch_op.drop_column("subtitle_tracks")
        batch_op.drop_column("audio_tracks")
        batch_op.drop_column("resolution")
        batch_op.drop_column("path")

    # 6. Insert migrated rows into media_files and update default_path
    import uuid

    for row in episode_rows:
        ep_id, path, codec, res, audio, sub = row
        if path:
            mf_id = uuid.uuid4().bytes
            bind.execute(
                sa.text(
                    "INSERT INTO media_files (id, episode_id, path, video_codec, resolution, audio_tracks, subtitle_tracks) "
                    "VALUES (:id, :episode_id, :path, :codec, :res, :audio, :sub)"
                ),
                {
                    "id": mf_id,
                    "episode_id": ep_id,
                    "path": path,
                    "codec": codec,
                    "res": res,
                    "audio": audio,
                    "sub": sub,
                },
            )
            bind.execute(
                sa.text("UPDATE episodes SET default_path = :path WHERE id = :id"),
                {"path": path, "id": ep_id},
            )

    for row in movie_rows:
        mv_id, path, codec, res, audio, sub = row
        if path:
            mf_id = uuid.uuid4().bytes
            bind.execute(
                sa.text(
                    "INSERT INTO media_files (id, movie_id, path, video_codec, resolution, audio_tracks, subtitle_tracks) "
                    "VALUES (:id, :movie_id, :path, :codec, :res, :audio, :sub)"
                ),
                {
                    "id": mf_id,
                    "movie_id": mv_id,
                    "path": path,
                    "codec": codec,
                    "res": res,
                    "audio": audio,
                    "sub": sub,
                },
            )
            bind.execute(
                sa.text("UPDATE movies SET default_path = :path WHERE id = :id"),
                {"path": path, "id": mv_id},
            )


def downgrade() -> None:
    """Downgrade schema: restore path and tech columns to episodes/movies, dropping media_files."""
    bind = op.get_bind()

    # 1. Add back the dropped columns to episodes and movies
    with op.batch_alter_table("movies", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("path", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("resolution", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("audio_tracks", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("subtitle_tracks", sa.String(), nullable=True))

    with op.batch_alter_table("episodes", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("path", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("resolution", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("audio_tracks", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("subtitle_tracks", sa.String(), nullable=True))

    # 2. Query migrated media_files data
    media_rows = bind.execute(
        sa.text(
            "SELECT episode_id, movie_id, path, video_codec, resolution, audio_tracks, subtitle_tracks "
            "FROM media_files"
        )
    ).fetchall()

    # 3. Restore data to episodes
    for row in media_rows:
        ep_id, mv_id, path, codec, res, audio, sub = row
        if ep_id:
            bind.execute(
                sa.text(
                    "UPDATE episodes SET path = :path, video_codec = :codec, resolution = :res, "
                    "audio_tracks = :audio, subtitle_tracks = :sub WHERE id = :id"
                ),
                {
                    "path": path,
                    "codec": codec,
                    "res": res,
                    "audio": audio,
                    "sub": sub,
                    "id": ep_id,
                },
            )
        elif mv_id:
            bind.execute(
                sa.text(
                    "UPDATE movies SET path = :path, video_codec = :codec, resolution = :res, "
                    "audio_tracks = :audio, subtitle_tracks = :sub WHERE id = :id"
                ),
                {
                    "path": path,
                    "codec": codec,
                    "res": res,
                    "audio": audio,
                    "sub": sub,
                    "id": mv_id,
                },
            )

    # 4. Drop the default_path columns and drop media_files table
    with op.batch_alter_table("movies", recreate="always") as batch_op:
        batch_op.drop_column("default_path")

    with op.batch_alter_table("episodes", recreate="always") as batch_op:
        batch_op.drop_column("default_path")

    op.drop_table("media_files")
