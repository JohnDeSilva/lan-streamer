"""uuid_blob_primary_keys

Revision ID: b3f9e1c2d4a5
Revises: a1b2c3d4e5f6
Create Date: 2026-06-11 13:40:00.000000

Converts all integer auto-increment primary keys to UUID4 values stored as
16-byte BLOBs.  Because SQLite does not support ALTER COLUMN, each affected
table is fully recreated using Alembic's batch mode with ``recreate='always'``.

Tables affected:
  - series      (id: Integer → BLOB, becomes the FK target for seasons)
  - seasons     (id: Integer → BLOB, series_id FK → BLOB, FK target for episodes)
  - episodes    (id: Integer → BLOB, season_id FK → BLOB)
  - movies      (id: Integer → BLOB)
  - app_secrets (secret_uuid: String → BLOB)

The migration strategy for tables with FK relationships (series → seasons →
episodes) is:
  1. Read all rows from each table into Python.
  2. Generate a UUID bytes value for every row, building an old_int → new_uuid
     mapping.
  3. Drop the old table and create the new one with BLOB PKs/FKs.
  4. Re-insert all rows with the mapped UUID values.
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "b3f9e1c2d4a5"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_bytes() -> bytes:
    return uuid.uuid4().bytes


def upgrade() -> None:
    """Upgrade schema: replace integer PKs with UUID BLOBs."""

    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. app_secrets: secret_uuid String → BLOB
    # ------------------------------------------------------------------
    # Read existing rows
    secrets_rows = bind.execute(
        text("SELECT secret_uuid, secret_type, secret FROM app_secrets")
    ).fetchall()

    # Map old string UUID → new bytes UUID
    secrets_map: dict[str, bytes] = {row[0]: _uuid_bytes() for row in secrets_rows}

    # Clear table before alter to avoid UNIQUE constraint violation if seeds exist
    bind.execute(text("DELETE FROM app_secrets"))

    with op.batch_alter_table("app_secrets", recreate="always") as batch_op:
        batch_op.alter_column(
            "secret_uuid",
            existing_type=sa.String(),
            type_=sa.LargeBinary(),
            nullable=False,
        )

    # Re-insert rows with bytes UUIDs (batch_alter_table preserves data for
    # simple type changes on SQLite, but the TEXT→BLOB coercion may not be
    # reliable, so we do an explicit re-insert via Python)
    for row in secrets_rows:
        bind.execute(
            text(
                "INSERT INTO app_secrets (secret_uuid, secret_type, secret) "
                "VALUES (:uuid, :stype, :secret)"
            ),
            {
                "uuid": secrets_map[row[0]],
                "stype": row[1],
                "secret": row[2],
            },
        )

    # ------------------------------------------------------------------
    # 2. series: id Integer → BLOB
    # ------------------------------------------------------------------
    series_rows = bind.execute(
        text(
            "SELECT id, library_name, name, jellyfin_id, tmdb_identifier, "
            "poster_path, overview, tmdb_name, locked_metadata, first_air_date, "
            "tmdb_episode_group_id, pref_hide_missing_future, pref_display_group_id "
            "FROM series"
        )
    ).fetchall()

    # old integer id → new bytes UUID
    series_id_map: dict[int, bytes] = {row[0]: _uuid_bytes() for row in series_rows}

    # Clear table before alter to avoid UNIQUE constraint violation
    bind.execute(text("DELETE FROM series"))

    # seasons and episodes still reference series.id (integer) at this point;
    # we'll handle them after series is migrated.

    with op.batch_alter_table(
        "series",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": False},
    ) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.Integer(),
            type_=sa.LargeBinary(),
            nullable=False,
        )

    for row in series_rows:
        bind.execute(
            text(
                "INSERT INTO series ("
                "  id, library_name, name, jellyfin_id, tmdb_identifier, "
                "  poster_path, overview, tmdb_name, locked_metadata, first_air_date, "
                "  tmdb_episode_group_id, pref_hide_missing_future, pref_display_group_id"
                ") VALUES ("
                "  :id, :library_name, :name, :jellyfin_id, :tmdb_identifier, "
                "  :poster_path, :overview, :tmdb_name, :locked_metadata, :first_air_date, "
                "  :tmdb_episode_group_id, :pref_hide_missing_future, :pref_display_group_id"
                ")"
            ),
            {
                "id": series_id_map[row[0]],
                "library_name": row[1],
                "name": row[2],
                "jellyfin_id": row[3],
                "tmdb_identifier": row[4],
                "poster_path": row[5],
                "overview": row[6],
                "tmdb_name": row[7],
                "locked_metadata": row[8],
                "first_air_date": row[9],
                "tmdb_episode_group_id": row[10],
                "pref_hide_missing_future": row[11],
                "pref_display_group_id": row[12],
            },
        )

    # ------------------------------------------------------------------
    # 3. seasons: id Integer → BLOB, series_id Integer FK → BLOB
    # ------------------------------------------------------------------
    seasons_rows = bind.execute(
        text(
            "SELECT id, series_id, name, jellyfin_id, poster_path, myanimelist_id "
            "FROM seasons"
        )
    ).fetchall()

    seasons_id_map: dict[int, bytes] = {row[0]: _uuid_bytes() for row in seasons_rows}

    # Clear table before alter to avoid UNIQUE constraint violation
    bind.execute(text("DELETE FROM seasons"))

    with op.batch_alter_table(
        "seasons",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": False},
    ) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.Integer(),
            type_=sa.LargeBinary(),
            nullable=False,
        )
        batch_op.alter_column(
            "series_id",
            existing_type=sa.Integer(),
            type_=sa.LargeBinary(),
            nullable=True,
        )

    for row in seasons_rows:
        old_series_id = row[1]
        new_series_id = (
            series_id_map.get(old_series_id) if old_series_id is not None else None
        )
        bind.execute(
            text(
                "INSERT INTO seasons (id, series_id, name, jellyfin_id, poster_path, myanimelist_id) "
                "VALUES (:id, :series_id, :name, :jellyfin_id, :poster_path, :myanimelist_id)"
            ),
            {
                "id": seasons_id_map[row[0]],
                "series_id": new_series_id,
                "name": row[2],
                "jellyfin_id": row[3],
                "poster_path": row[4],
                "myanimelist_id": row[5],
            },
        )

    # ------------------------------------------------------------------
    # 4. episodes: id Integer → BLOB, season_id Integer FK → BLOB
    # ------------------------------------------------------------------
    episodes_rows = bind.execute(
        text(
            "SELECT id, season_id, name, path, jellyfin_id, tmdb_episode_identifier, "
            "tmdb_name, tmdb_number, watched, date_added, air_date, runtime, "
            "myanimelist_anime_id, myanimelist_episode_number, last_played_position, "
            "last_played_at, video_codec, resolution, audio_tracks, subtitle_tracks "
            "FROM episodes"
        )
    ).fetchall()

    # Clear table before alter to avoid UNIQUE constraint violation
    bind.execute(text("DELETE FROM episodes"))

    with op.batch_alter_table(
        "episodes",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": False},
    ) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.Integer(),
            type_=sa.LargeBinary(),
            nullable=False,
        )
        batch_op.alter_column(
            "season_id",
            existing_type=sa.Integer(),
            type_=sa.LargeBinary(),
            nullable=True,
        )

    for row in episodes_rows:
        old_season_id = row[1]
        new_season_id = (
            seasons_id_map.get(old_season_id) if old_season_id is not None else None
        )
        bind.execute(
            text(
                "INSERT INTO episodes ("
                "  id, season_id, name, path, jellyfin_id, tmdb_episode_identifier, "
                "  tmdb_name, tmdb_number, watched, date_added, air_date, runtime, "
                "  myanimelist_anime_id, myanimelist_episode_number, last_played_position, "
                "  last_played_at, video_codec, resolution, audio_tracks, subtitle_tracks"
                ") VALUES ("
                "  :id, :season_id, :name, :path, :jellyfin_id, :tmdb_episode_identifier, "
                "  :tmdb_name, :tmdb_number, :watched, :date_added, :air_date, :runtime, "
                "  :myanimelist_anime_id, :myanimelist_episode_number, :last_played_position, "
                "  :last_played_at, :video_codec, :resolution, :audio_tracks, :subtitle_tracks"
                ")"
            ),
            {
                "id": _uuid_bytes(),
                "season_id": new_season_id,
                "name": row[2],
                "path": row[3],
                "jellyfin_id": row[4],
                "tmdb_episode_identifier": row[5],
                "tmdb_name": row[6],
                "tmdb_number": row[7],
                "watched": row[8],
                "date_added": row[9],
                "air_date": row[10],
                "runtime": row[11],
                "myanimelist_anime_id": row[12],
                "myanimelist_episode_number": row[13],
                "last_played_position": row[14],
                "last_played_at": row[15],
                "video_codec": row[16],
                "resolution": row[17],
                "audio_tracks": row[18],
                "subtitle_tracks": row[19],
            },
        )

    # ------------------------------------------------------------------
    # 5. movies: id Integer → BLOB
    # ------------------------------------------------------------------
    movies_rows = bind.execute(
        text(
            "SELECT id, library_name, name, jellyfin_id, tmdb_identifier, "
            "poster_path, overview, tmdb_name, locked_metadata, date_added, "
            "path, myanimelist_anime_id, runtime, rating, genre, year, watched, "
            "last_played_position, last_played_at, video_codec, resolution, "
            "audio_tracks, subtitle_tracks "
            "FROM movies"
        )
    ).fetchall()

    # Clear table before alter to avoid UNIQUE constraint violation
    bind.execute(text("DELETE FROM movies"))

    with op.batch_alter_table(
        "movies",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": False},
    ) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.Integer(),
            type_=sa.LargeBinary(),
            nullable=False,
        )

    for row in movies_rows:
        bind.execute(
            text(
                "INSERT INTO movies ("
                "  id, library_name, name, jellyfin_id, tmdb_identifier, "
                "  poster_path, overview, tmdb_name, locked_metadata, date_added, "
                "  path, myanimelist_anime_id, runtime, rating, genre, year, watched, "
                "  last_played_position, last_played_at, video_codec, resolution, "
                "  audio_tracks, subtitle_tracks"
                ") VALUES ("
                "  :id, :library_name, :name, :jellyfin_id, :tmdb_identifier, "
                "  :poster_path, :overview, :tmdb_name, :locked_metadata, :date_added, "
                "  :path, :myanimelist_anime_id, :runtime, :rating, :genre, :year, :watched, "
                "  :last_played_position, :last_played_at, :video_codec, :resolution, "
                "  :audio_tracks, :subtitle_tracks"
                ")"
            ),
            {
                "id": _uuid_bytes(),
                "library_name": row[1],
                "name": row[2],
                "jellyfin_id": row[3],
                "tmdb_identifier": row[4],
                "poster_path": row[5],
                "overview": row[6],
                "tmdb_name": row[7],
                "locked_metadata": row[8],
                "date_added": row[9],
                "path": row[10],
                "myanimelist_anime_id": row[11],
                "runtime": row[12],
                "rating": row[13],
                "genre": row[14],
                "year": row[15],
                "watched": row[16],
                "last_played_position": row[17],
                "last_played_at": row[18],
                "video_codec": row[19],
                "resolution": row[20],
                "audio_tracks": row[21],
                "subtitle_tracks": row[22],
            },
        )


def downgrade() -> None:
    """Downgrade schema: revert UUID BLOBs back to integer auto-increment PKs.

    Because the original integer IDs are permanently lost after upgrade, this
    downgrade assigns new sequential integers starting from 1.  Relational
    integrity between series → seasons → episodes is maintained via a fresh
    mapping built here.
    """

    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. app_secrets: BLOB → String (hex representation of the UUID bytes)
    # ------------------------------------------------------------------
    secrets_rows = bind.execute(
        text("SELECT secret_uuid, secret_type, secret FROM app_secrets")
    ).fetchall()

    # Clear table before alter to avoid UNIQUE constraint violation
    bind.execute(text("DELETE FROM app_secrets"))

    with op.batch_alter_table("app_secrets", recreate="always") as batch_op:
        batch_op.alter_column(
            "secret_uuid",
            existing_type=sa.LargeBinary(),
            type_=sa.String(),
            nullable=False,
        )

    for row in secrets_rows:
        blob = row[0]
        uuid_str = str(uuid.UUID(bytes=bytes(blob))) if blob else str(uuid.uuid4())
        bind.execute(
            text(
                "INSERT INTO app_secrets (secret_uuid, secret_type, secret) "
                "VALUES (:uuid, :stype, :secret)"
            ),
            {"uuid": uuid_str, "stype": row[1], "secret": row[2]},
        )

    # ------------------------------------------------------------------
    # 2. series: BLOB → Integer
    # ------------------------------------------------------------------
    series_rows = bind.execute(
        text(
            "SELECT id, library_name, name, jellyfin_id, tmdb_identifier, "
            "poster_path, overview, tmdb_name, locked_metadata, first_air_date, "
            "tmdb_episode_group_id, pref_hide_missing_future, pref_display_group_id "
            "FROM series"
        )
    ).fetchall()

    # blob → new integer
    series_blob_to_int: dict[bytes, int] = {
        bytes(row[0]): (i + 1) for i, row in enumerate(series_rows)
    }

    # Clear table before alter to avoid SQLite CAST UNIQUE constraint failure on BLOB->INT PK
    bind.execute(text("DELETE FROM series"))

    with op.batch_alter_table(
        "series",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.LargeBinary(),
            type_=sa.Integer(),
            nullable=False,
        )

    for i, row in enumerate(series_rows):
        bind.execute(
            text(
                "INSERT INTO series ("
                "  id, library_name, name, jellyfin_id, tmdb_identifier, "
                "  poster_path, overview, tmdb_name, locked_metadata, first_air_date, "
                "  tmdb_episode_group_id, pref_hide_missing_future, pref_display_group_id"
                ") VALUES ("
                "  :id, :library_name, :name, :jellyfin_id, :tmdb_identifier, "
                "  :poster_path, :overview, :tmdb_name, :locked_metadata, :first_air_date, "
                "  :tmdb_episode_group_id, :pref_hide_missing_future, :pref_display_group_id"
                ")"
            ),
            {
                "id": i + 1,
                "library_name": row[1],
                "name": row[2],
                "jellyfin_id": row[3],
                "tmdb_identifier": row[4],
                "poster_path": row[5],
                "overview": row[6],
                "tmdb_name": row[7],
                "locked_metadata": row[8],
                "first_air_date": row[9],
                "tmdb_episode_group_id": row[10],
                "pref_hide_missing_future": row[11],
                "pref_display_group_id": row[12],
            },
        )

    # ------------------------------------------------------------------
    # 3. seasons: BLOB → Integer
    # ------------------------------------------------------------------
    seasons_rows = bind.execute(
        text(
            "SELECT id, series_id, name, jellyfin_id, poster_path, myanimelist_id "
            "FROM seasons"
        )
    ).fetchall()

    seasons_blob_to_int: dict[bytes, int] = {
        bytes(row[0]): (i + 1) for i, row in enumerate(seasons_rows)
    }

    # Clear table before alter to avoid SQLite CAST UNIQUE constraint failure on BLOB->INT PK
    bind.execute(text("DELETE FROM seasons"))

    with op.batch_alter_table(
        "seasons",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.LargeBinary(),
            type_=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "series_id",
            existing_type=sa.LargeBinary(),
            type_=sa.Integer(),
            nullable=True,
        )

    for i, row in enumerate(seasons_rows):
        old_series_blob = bytes(row[1]) if row[1] is not None else None
        new_series_int = (
            series_blob_to_int.get(old_series_blob) if old_series_blob else None
        )
        bind.execute(
            text(
                "INSERT INTO seasons (id, series_id, name, jellyfin_id, poster_path, myanimelist_id) "
                "VALUES (:id, :series_id, :name, :jellyfin_id, :poster_path, :myanimelist_id)"
            ),
            {
                "id": i + 1,
                "series_id": new_series_int,
                "name": row[2],
                "jellyfin_id": row[3],
                "poster_path": row[4],
                "myanimelist_id": row[5],
            },
        )

    # ------------------------------------------------------------------
    # 4. episodes: BLOB → Integer
    # ------------------------------------------------------------------
    episodes_rows = bind.execute(
        text(
            "SELECT id, season_id, name, path, jellyfin_id, tmdb_episode_identifier, "
            "tmdb_name, tmdb_number, watched, date_added, air_date, runtime, "
            "myanimelist_anime_id, myanimelist_episode_number, last_played_position, "
            "last_played_at, video_codec, resolution, audio_tracks, subtitle_tracks "
            "FROM episodes"
        )
    ).fetchall()

    # Clear table before alter to avoid SQLite CAST UNIQUE constraint failure on BLOB->INT PK
    bind.execute(text("DELETE FROM episodes"))

    with op.batch_alter_table(
        "episodes",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.LargeBinary(),
            type_=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "season_id",
            existing_type=sa.LargeBinary(),
            type_=sa.Integer(),
            nullable=True,
        )

    for i, row in enumerate(episodes_rows):
        old_season_blob = bytes(row[1]) if row[1] is not None else None
        new_season_int = (
            seasons_blob_to_int.get(old_season_blob) if old_season_blob else None
        )
        bind.execute(
            text(
                "INSERT INTO episodes ("
                "  id, season_id, name, path, jellyfin_id, tmdb_episode_identifier, "
                "  tmdb_name, tmdb_number, watched, date_added, air_date, runtime, "
                "  myanimelist_anime_id, myanimelist_episode_number, last_played_position, "
                "  last_played_at, video_codec, resolution, audio_tracks, subtitle_tracks"
                ") VALUES ("
                "  :id, :season_id, :name, :path, :jellyfin_id, :tmdb_episode_identifier, "
                "  :tmdb_name, :tmdb_number, :watched, :date_added, :air_date, :runtime, "
                "  :myanimelist_anime_id, :myanimelist_episode_number, :last_played_position, "
                "  :last_played_at, :video_codec, :resolution, :audio_tracks, :subtitle_tracks"
                ")"
            ),
            {
                "id": i + 1,
                "season_id": new_season_int,
                "name": row[2],
                "path": row[3],
                "jellyfin_id": row[4],
                "tmdb_episode_identifier": row[5],
                "tmdb_name": row[6],
                "tmdb_number": row[7],
                "watched": row[8],
                "date_added": row[9],
                "air_date": row[10],
                "runtime": row[11],
                "myanimelist_anime_id": row[12],
                "myanimelist_episode_number": row[13],
                "last_played_position": row[14],
                "last_played_at": row[15],
                "video_codec": row[16],
                "resolution": row[17],
                "audio_tracks": row[18],
                "subtitle_tracks": row[19],
            },
        )

    # ------------------------------------------------------------------
    # 5. movies: BLOB → Integer
    # ------------------------------------------------------------------
    movies_rows = bind.execute(
        text(
            "SELECT id, library_name, name, jellyfin_id, tmdb_identifier, "
            "poster_path, overview, tmdb_name, locked_metadata, date_added, "
            "path, myanimelist_anime_id, runtime, rating, genre, year, watched, "
            "last_played_position, last_played_at, video_codec, resolution, "
            "audio_tracks, subtitle_tracks "
            "FROM movies"
        )
    ).fetchall()

    # Clear table before alter to avoid SQLite CAST UNIQUE constraint failure on BLOB->INT PK
    bind.execute(text("DELETE FROM movies"))

    with op.batch_alter_table(
        "movies",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.LargeBinary(),
            type_=sa.Integer(),
            nullable=False,
        )

    for i, row in enumerate(movies_rows):
        bind.execute(
            text(
                "INSERT INTO movies ("
                "  id, library_name, name, jellyfin_id, tmdb_identifier, "
                "  poster_path, overview, tmdb_name, locked_metadata, date_added, "
                "  path, myanimelist_anime_id, runtime, rating, genre, year, watched, "
                "  last_played_position, last_played_at, video_codec, resolution, "
                "  audio_tracks, subtitle_tracks"
                ") VALUES ("
                "  :id, :library_name, :name, :jellyfin_id, :tmdb_identifier, "
                "  :poster_path, :overview, :tmdb_name, :locked_metadata, :date_added, "
                "  :path, :myanimelist_anime_id, :runtime, :rating, :genre, :year, :watched, "
                "  :last_played_position, :last_played_at, :video_codec, :resolution, "
                "  :audio_tracks, :subtitle_tracks"
                ")"
            ),
            {
                "id": i + 1,
                "library_name": row[1],
                "name": row[2],
                "jellyfin_id": row[3],
                "tmdb_identifier": row[4],
                "poster_path": row[5],
                "overview": row[6],
                "tmdb_name": row[7],
                "locked_metadata": row[8],
                "date_added": row[9],
                "path": row[10],
                "myanimelist_anime_id": row[11],
                "runtime": row[12],
                "rating": row[13],
                "genre": row[14],
                "year": row[15],
                "watched": row[16],
                "last_played_position": row[17],
                "last_played_at": row[18],
                "video_codec": row[19],
                "resolution": row[20],
                "audio_tracks": row[21],
                "subtitle_tracks": row[22],
            },
        )
