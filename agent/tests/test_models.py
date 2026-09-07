"""Unit tests for the agent ORM models and schema initialisation."""

from __future__ import annotations

from sqlalchemy import inspect, select

from scan_agent.db.connection import get_session, init_database
from scan_agent.db.models import (
    SCHEMA_VERSION,
    Episode,
    Library,
    MediaFile,
    Movie,
    ScannedDirectory,
    SchemaVersion,
    Season,
    Series,
    Subtitle,
    WatchEvent,
)


def test_all_tables_created(database_engine) -> None:
    inspector = inspect(database_engine)
    table_names = set(inspector.get_table_names())
    for model in [
        Library,
        Series,
        Season,
        Episode,
        Movie,
        MediaFile,
        Subtitle,
        ScannedDirectory,
        SchemaVersion,
        WatchEvent,
    ]:
        assert model.__tablename__ in table_names
    assert "libraries" in table_names


def test_init_database_is_idempotent(database_engine) -> None:
    init_database(database_engine)
    with get_session(database_engine) as session:
        version_row = session.get(SchemaVersion, 1)
        assert version_row is not None
        assert version_row.version == SCHEMA_VERSION


def test_season_and_episode_round_trip(database_engine, agent_config) -> None:
    # Build a minimal object graph manually to validate FK relationships.
    with get_session(database_engine) as session:
        library = Library(name="TV", media_type="tv", root_path="/media")
        session.add(library)
        session.flush()
        series = Series(library_id=library.id, folder_name="Test Show")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, season_number=1, name="Season 1")
        session.add(season)
        session.flush()
        episode = Episode(
            season_id=season.id,
            episode_number=1,
            name="Pilot",
            path="/media/s01e01.mkv",
        )
        session.add(episode)
        session.flush()
        media_file = MediaFile(
            media_type="episode",
            media_id=episode.id,
            path="/media/s01e01.mkv",
            size_bytes=100,
        )
        session.add(media_file)
        session.flush()
        series_id = series.id

    with get_session(database_engine) as session:
        loaded = session.get(Series, series_id)
        assert loaded is not None
        assert loaded.folder_name == "Test Show"
        assert len(loaded.seasons) == 1
        assert loaded.seasons[0].episodes[0].name == "Pilot"
        assert loaded.seasons[0].episodes[0].media_files[0].path == "/media/s01e01.mkv"


def test_scanned_directory_round_trip(database_engine) -> None:
    with get_session(database_engine) as session:
        session.add(
            ScannedDirectory(path="/media/Test Show", last_scanned_mtime=1234.5)
        )
        session.flush()

    with get_session(database_engine) as session:
        record = session.scalars(
            select(ScannedDirectory).where(ScannedDirectory.path == "/media/Test Show")
        ).first()
        assert record is not None
        assert record.last_scanned_mtime == 1234.5


def test_media_file_version_columns(database_engine) -> None:
    expected_columns = {
        "id",
        "media_type",
        "media_id",
        "path",
        "size_bytes",
        "codec",
        "resolution",
        "container",
        "active",
    }
    actual_columns = {column.name for column in MediaFile.__table__.columns}
    assert expected_columns <= actual_columns


def test_watch_event_columns(database_engine) -> None:
    with get_session(database_engine) as session:
        event = WatchEvent(
            media_type="episode",
            media_id=1,
            event="play",
            position_seconds=0.0,
            client_id="desktop-1",
        )
        session.add(event)
        session.flush()

    with get_session(database_engine) as session:
        persisted = session.scalars(select(WatchEvent)).first()
        assert persisted is not None
        assert persisted.event == "play"
        assert persisted.client_id == "desktop-1"
