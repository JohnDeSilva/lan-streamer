from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from lan_streamer.db.models import Series, Season, Episode, Movie, MediaFile
import lan_streamer.db as db_mod


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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

    with patch.object(db_mod, "DB_FILE", mock_db_file):
        db_mod._engine = None
        db_mod._SessionLocal = None
        db_mod._db_initialized = False
        db_mod.init_db()
        yield

    if db_mod._engine is not None:
        db_mod._engine.dispose()
    db_mod._engine = old_engine
    db_mod._SessionLocal = old_session
    db_mod._db_initialized = old_init


# ---------------------------------------------------------------------------
# Migration Tests (Upgrade & Downgrade)
# ---------------------------------------------------------------------------


def test_media_files_migration_data_flow(tmp_path) -> None:
    """Test upgrade from b3f9e1c2d4a5 to 49d186288d29 and downgrade back to b3f9e1c2d4a5.

    Verifies that old path/technical columns are migrated into the new media_files table
    on upgrade, and restored back on downgrade.
    """
    db_path = tmp_path / "test_media_migration.db"
    cfg = _alembic_cfg(db_path)

    # 1. Upgrade to revision b3f9e1c2d4a5 (UUID Blob migration)
    command.upgrade(cfg, "b3f9e1c2d4a5")

    engine = _engine(db_path)

    # Generate some UUIDs for our test rows
    series_id = uuid.uuid4().bytes
    season_id = uuid.uuid4().bytes
    ep1_id = uuid.uuid4().bytes
    ep2_id = uuid.uuid4().bytes
    movie_id = uuid.uuid4().bytes

    # 2. Insert test data before the multiple media files migration
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO series (id, library_name, name) VALUES (:id, 'TV', 'Show A')"
            ),
            {"id": series_id},
        )
        conn.execute(
            text(
                "INSERT INTO seasons (id, series_id, name) VALUES (:id, :series_id, 'Season 1')"
            ),
            {"id": season_id, "series_id": series_id},
        )
        # Episodes with old path and technical columns
        conn.execute(
            text(
                "INSERT INTO episodes (id, season_id, name, path, video_codec, resolution, audio_tracks, subtitle_tracks) "
                "VALUES (:id, :season_id, 'Ep 1', '/show/s01e01.mp4', 'h264', '1080p', 'aac', 'srt')"
            ),
            {"id": ep1_id, "season_id": season_id},
        )
        conn.execute(
            text(
                "INSERT INTO episodes (id, season_id, name, path, video_codec, resolution, audio_tracks, subtitle_tracks) "
                "VALUES (:id, :season_id, 'Ep 2', '/show/s01e02.mkv', 'hevc', '4k', 'ac3', 'vtt')"
            ),
            {"id": ep2_id, "season_id": season_id},
        )
        # Movie with old path and technical columns
        conn.execute(
            text(
                "INSERT INTO movies (id, library_name, name, path, video_codec, resolution, audio_tracks, subtitle_tracks) "
                "VALUES (:id, 'Movies', 'Movie A', '/movies/movie.mkv', 'hevc', '2160p', 'dts', 'ass')"
            ),
            {"id": movie_id},
        )

    # 3. Upgrade to 49d186288d29 (multiple media files table creation & migration)
    command.upgrade(cfg, "49d186288d29")

    # 4. Verify table schema changes and migrated data
    with engine.connect() as conn:
        # Check episodes: path and tech columns dropped, default_path exists
        # In SQLite, checking if column is missing can be done by trying to query it and catching OperationalError
        for col in ("path", "resolution", "audio_tracks", "subtitle_tracks"):
            with pytest.raises(sa.exc.OperationalError):
                conn.execute(text(f"SELECT {col} FROM episodes")).fetchall()
            with pytest.raises(sa.exc.OperationalError):
                conn.execute(text(f"SELECT {col} FROM movies")).fetchall()

        # Check default_path column on episodes and movies
        ep1_default = conn.execute(
            text("SELECT default_path FROM episodes WHERE id = :id"), {"id": ep1_id}
        ).scalar()
        assert ep1_default == "/show/s01e01.mp4"

        ep2_default = conn.execute(
            text("SELECT default_path FROM episodes WHERE id = :id"), {"id": ep2_id}
        ).scalar()
        assert ep2_default == "/show/s01e02.mkv"

        movie_default = conn.execute(
            text("SELECT default_path FROM movies WHERE id = :id"), {"id": movie_id}
        ).scalar()
        assert movie_default == "/movies/movie.mkv"

        # Check media_files entries
        mf_rows = conn.execute(
            text(
                "SELECT id, episode_id, movie_id, path, video_codec, resolution, audio_tracks, subtitle_tracks FROM media_files"
            )
        ).fetchall()

        assert len(mf_rows) == 3
        # Map by path for assertion convenience
        mfs = {row[3]: row for row in mf_rows}

        assert "/show/s01e01.mp4" in mfs
        assert mfs["/show/s01e01.mp4"][1] == ep1_id
        assert mfs["/show/s01e01.mp4"][2] is None
        assert mfs["/show/s01e01.mp4"][4] == "h264"
        assert mfs["/show/s01e01.mp4"][5] == "1080p"
        assert mfs["/show/s01e01.mp4"][6] == "aac"
        assert mfs["/show/s01e01.mp4"][7] == "srt"

        assert "/show/s01e02.mkv" in mfs
        assert mfs["/show/s01e02.mkv"][1] == ep2_id
        assert mfs["/show/s01e02.mkv"][2] is None
        assert mfs["/show/s01e02.mkv"][4] == "hevc"
        assert mfs["/show/s01e02.mkv"][5] == "4k"
        assert mfs["/show/s01e02.mkv"][6] == "ac3"
        assert mfs["/show/s01e02.mkv"][7] == "vtt"

        assert "/movies/movie.mkv" in mfs
        assert mfs["/movies/movie.mkv"][1] is None
        assert mfs["/movies/movie.mkv"][2] == movie_id
        assert mfs["/movies/movie.mkv"][4] == "hevc"
        assert mfs["/movies/movie.mkv"][5] == "2160p"
        assert mfs["/movies/movie.mkv"][6] == "dts"
        assert mfs["/movies/movie.mkv"][7] == "ass"

    # 5. Downgrade back to b3f9e1c2d4a5
    command.downgrade(cfg, "b3f9e1c2d4a5")

    # 6. Verify tables returned to old schema and data was restored
    with engine.connect() as conn:
        # Check media_files table is dropped
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(text("SELECT * FROM media_files")).fetchall()

        # Check default_path is dropped
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(text("SELECT default_path FROM episodes")).fetchall()
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(text("SELECT default_path FROM movies")).fetchall()

        # Check restored data on episodes
        ep1_row = conn.execute(
            text(
                "SELECT path, video_codec, resolution, audio_tracks, subtitle_tracks FROM episodes WHERE id = :id"
            ),
            {"id": ep1_id},
        ).fetchone()
        assert ep1_row is not None
        assert ep1_row[0] == "/show/s01e01.mp4"
        assert ep1_row[1] == "h264"
        assert ep1_row[2] == "1080p"
        assert ep1_row[3] == "aac"
        assert ep1_row[4] == "srt"

        ep2_row = conn.execute(
            text(
                "SELECT path, video_codec, resolution, audio_tracks, subtitle_tracks FROM episodes WHERE id = :id"
            ),
            {"id": ep2_id},
        ).fetchone()
        assert ep2_row is not None
        assert ep2_row[0] == "/show/s01e02.mkv"
        assert ep2_row[1] == "hevc"
        assert ep2_row[2] == "4k"
        assert ep2_row[3] == "ac3"
        assert ep2_row[4] == "vtt"

        # Check restored data on movies
        movie_row = conn.execute(
            text(
                "SELECT path, video_codec, resolution, audio_tracks, subtitle_tracks FROM movies WHERE id = :id"
            ),
            {"id": movie_id},
        ).fetchone()
        assert movie_row is not None
        assert movie_row[0] == "/movies/movie.mkv"
        assert movie_row[1] == "hevc"
        assert movie_row[2] == "2160p"
        assert movie_row[3] == "dts"
        assert movie_row[4] == "ass"

    engine.dispose()


# ---------------------------------------------------------------------------
# ORM Relationship & Cascade Tests
# ---------------------------------------------------------------------------


def test_media_files_orm_relationships_and_cascade(_db_setup) -> None:
    """Test ORM relationships & cascade deletes between Series, Season, Episode, Movie and MediaFile."""

    # 1. Test Episode -> MediaFiles relationship and cascade delete
    with db_mod.get_session() as session:
        series = Series(library_name="TV", name="Breaking Bad")
        season = Season(name="Season 1", series=series)
        episode = Episode(name="Pilot", season=season)

        # Add multiple media files
        mf1 = MediaFile(
            path="/tv/bb_s01e01_1080p.mkv", video_codec="hevc", resolution="1080p"
        )
        mf2 = MediaFile(
            path="/tv/bb_s01e01_720p.mp4", video_codec="h264", resolution="720p"
        )
        episode.media_files.append(mf1)
        episode.media_files.append(mf2)

        session.add_all([series, season, episode, mf1, mf2])
        session.commit()

        ep_id = episode.id
        mf1_id = mf1.id
        mf2_id = mf2.id

    with db_mod.get_session() as session:
        ep = session.get(Episode, ep_id)
        assert ep is not None
        assert len(ep.media_files) == 2
        paths = {m.path for m in ep.media_files}
        assert "/tv/bb_s01e01_1080p.mkv" in paths
        assert "/tv/bb_s01e01_720p.mp4" in paths

        # Test back_populates
        for m in ep.media_files:
            assert ep in m.episodes

        # Delete episode, verify media_files are NOT deleted (independent)
        session.delete(ep)
        session.commit()

    with db_mod.get_session() as session:
        assert session.get(Episode, ep_id) is None
        assert session.get(MediaFile, mf1_id) is not None
        assert session.get(MediaFile, mf2_id) is not None

    # 2. Test Movie -> MediaFiles relationship
    with db_mod.get_session() as session:
        movie = Movie(library_name="Movies", name="Inception")
        mf1 = MediaFile(
            path="/movies/inception_4k.mkv", video_codec="hevc", resolution="4k"
        )
        mf2 = MediaFile(
            path="/movies/inception_1080p.mkv", video_codec="h264", resolution="1080p"
        )
        movie.media_files.append(mf1)
        movie.media_files.append(mf2)

        session.add_all([movie, mf1, mf2])
        session.commit()

        movie_id = movie.id
        mf1_id = mf1.id
        mf2_id = mf2.id

    with db_mod.get_session() as session:
        mv = session.get(Movie, movie_id)
        assert mv is not None
        assert len(mv.media_files) == 2
        paths = {m.path for m in mv.media_files}
        assert "/movies/inception_4k.mkv" in paths
        assert "/movies/inception_1080p.mkv" in paths

        # Test back_populates
        for m in mv.media_files:
            assert mv in m.movies

        # Delete movie, verify media_files are NOT deleted
        session.delete(mv)
        session.commit()

    with db_mod.get_session() as session:
        assert session.get(Movie, movie_id) is None
        assert session.get(MediaFile, mf1_id) is not None
        assert session.get(MediaFile, mf2_id) is not None

    # 3. Test Series -> Season -> Episode -> MediaFile cascade delete paths
    with db_mod.get_session() as session:
        series = Series(library_name="TV", name="Traversing Cascade")
        season = Season(name="Season 1", series=series)
        episode = Episode(name="Ep 1", season=season)
        mf = MediaFile(path="/tv/traverse_s01e01.mkv")
        episode.media_files.append(mf)

        session.add_all([series, season, episode, mf])
        session.commit()

        series_id = series.id
        season_id = season.id
        ep_id = episode.id
        mf_id = mf.id

    with db_mod.get_session() as session:
        s = session.get(Series, series_id)
        assert s is not None
        session.delete(s)
        session.commit()

    with db_mod.get_session() as session:
        assert session.get(Series, series_id) is None
        assert session.get(Season, season_id) is None
        assert session.get(Episode, ep_id) is None
        assert session.get(MediaFile, mf_id) is not None

    # 4. Test Season -> Episode -> MediaFile cascade delete paths
    with db_mod.get_session() as session:
        series = Series(library_name="TV", name="Traversing Cascade 2")
        season = Season(name="Season 1", series=series)
        episode = Episode(name="Ep 1", season=season)
        mf = MediaFile(path="/tv/traverse_s01e01_2.mkv")
        episode.media_files.append(mf)

        session.add_all([series, season, episode, mf])
        session.commit()

        season_id = season.id
        ep_id = episode.id
        mf_id = mf.id

    with db_mod.get_session() as session:
        se = session.get(Season, season_id)
        assert se is not None
        session.delete(se)
        session.commit()

    with db_mod.get_session() as session:
        assert session.get(Season, season_id) is None
        assert session.get(Episode, ep_id) is None
        assert session.get(MediaFile, mf_id) is not None


# ---------------------------------------------------------------------------
# Helper and Redirect Property Tests
# ---------------------------------------------------------------------------


def test_episode_movie_properties_and_helpers(_db_setup) -> None:
    """Test properties (path, resolution, audio_tracks, subtitle_tracks, bit_rate) on Episode and Movie models."""

    with db_mod.get_session() as session:
        series = Series(library_name="TV", name="Helpers Show")
        season = Season(name="Season 1", series=series)
        episode = Episode(name="Pilot", season=season)
        session.add_all([series, season, episode])
        session.flush()

        # 1. Test Episode helper properties with no initial media files
        assert episode.path is None
        assert episode.resolution is None
        assert episode.audio_tracks is None
        assert episode.subtitle_tracks is None
        assert episode.bit_rate is None

        # Setter path creates a MediaFile
        episode.path = "/tv/helper_s01e01.mp4"
        assert episode.path == "/tv/helper_s01e01.mp4"
        assert len(episode.media_files) == 1
        assert episode.media_files[0].path == "/tv/helper_s01e01.mp4"

        # Setter path ignores duplicate path setting
        episode.path = "/tv/helper_s01e01.mp4"
        assert len(episode.media_files) == 1

        # Setter of resolution, audio_tracks, subtitle_tracks, bit_rate updates the MediaFile
        episode.resolution = "1080p"
        episode.audio_tracks = "aac"
        episode.subtitle_tracks = "eng"
        episode.bit_rate = 5000000

        assert episode.resolution == "1080p"
        assert episode.audio_tracks == "aac"
        assert episode.subtitle_tracks == "eng"
        assert episode.bit_rate == 5000000
        assert episode.media_files[0].resolution == "1080p"

        # Setter path with a new path appends a new MediaFile
        episode.path = "/tv/helper_s01e01_alt.mp4"
        # Since we set default_path (in setter path), default_path is now "/tv/helper_s01e01_alt.mp4"
        assert episode.path == "/tv/helper_s01e01_alt.mp4"
        assert len(episode.media_files) == 2
        # Set to None clears all media files
        episode.path = None
        assert len(episode.media_files) == 0
        assert episode.path is None

    with db_mod.get_session() as session:
        movie = Movie(library_name="Movies", name="Helpers Movie")
        session.add(movie)
        session.flush()

        # 2. Test Movie helper properties with no initial media files
        assert movie.path is None
        assert movie.resolution is None
        assert movie.audio_tracks is None
        assert movie.subtitle_tracks is None
        assert movie.bit_rate is None

        movie.path = "/movies/helper_movie.mp4"
        assert movie.path == "/movies/helper_movie.mp4"
        assert len(movie.media_files) == 1
        assert movie.media_files[0].path == "/movies/helper_movie.mp4"

        movie.resolution = "2160p"
        movie.audio_tracks = "dts"
        movie.subtitle_tracks = "spa"
        movie.bit_rate = 12000000

        assert movie.resolution == "2160p"
        assert movie.audio_tracks == "dts"
        assert movie.subtitle_tracks == "spa"
        assert movie.bit_rate == 12000000
        assert movie.media_files[0].resolution == "2160p"

        movie.path = "/movies/helper_movie_alt.mp4"
        assert movie.path == "/movies/helper_movie_alt.mp4"
        assert len(movie.media_files) == 2

        movie.path = None
        assert len(movie.media_files) == 0
        assert movie.path is None
