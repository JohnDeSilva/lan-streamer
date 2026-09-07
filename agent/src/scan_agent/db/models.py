"""SQLAlchemy 2.0 ORM models for the scan agent database.

Schema follows ``agent/docs/ARCHITECTURE.md`` section 4.3. Two additions:

- ``SchemaVersion`` — single-row schema version marker (MVP migration
  discipline, no Alembic yet).
- ``ScannedDirectory`` — mirrors the desktop table of the same name. The
  reused scanner's pass 1/pass 2 call ``lan_streamer.db.get_directory_mtime``
  / ``save_directory_mtime`` unguarded; those helpers query this table
  through the desktop session (bound to our ``database_path``), so the table
  must exist in the agent schema or every season scan raises and is skipped.
"""

from __future__ import annotations

import time

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    and_,  # noqa: F401  (resolved from this namespace by relationship string)
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    foreign,  # noqa: F401  (resolved from this namespace by relationship string)
    mapped_column,
    relationship,
)

SCHEMA_VERSION = 1


class Base(DeclarativeBase):
    """Declarative base for all agent ORM models."""


class Library(Base):
    """A media library root: either TV series or movies."""

    __tablename__ = "libraries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # "tv" | "anime" | "movie"
    root_path: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    series: Mapped[list[Series]] = relationship(
        back_populates="library", cascade="all, delete-orphan", passive_deletes=True
    )
    movies: Mapped[list[Movie]] = relationship(
        back_populates="library", cascade="all, delete-orphan", passive_deletes=True
    )


class Series(Base):
    """A television series belonging to a library."""

    __tablename__ = "series"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    folder_name: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    overview: Mapped[str | None] = mapped_column(String)
    poster_path: Mapped[str | None] = mapped_column(String)
    backdrop_path: Mapped[str | None] = mapped_column(String)
    tmdb_identifier: Mapped[str | None] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String)
    air_date_first: Mapped[str | None] = mapped_column(String)
    air_date_last: Mapped[str | None] = mapped_column(String)
    locked_metadata: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    last_modified: Mapped[float | None] = mapped_column(Float)
    date_added: Mapped[float | None] = mapped_column(Float)
    watched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    path: Mapped[str | None] = mapped_column(String)

    library: Mapped[Library] = relationship(back_populates="series")
    seasons: Mapped[list[Season]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Season.season_number",
    )

    __table_args__ = (
        UniqueConstraint("library_id", "folder_name", name="uq_series_library_folder"),
    )


class Season(Base):
    """A season of a series."""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    overview: Mapped[str | None] = mapped_column(String)
    poster_path: Mapped[str | None] = mapped_column(String)
    tmdb_identifier: Mapped[str | None] = mapped_column(String)
    air_date: Mapped[str | None] = mapped_column(String)
    watched_episode_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    episode_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    series: Mapped[Series] = relationship(back_populates="seasons")
    episodes: Mapped[list[Episode]] = relationship(
        back_populates="season",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Episode.episode_number",
    )

    __table_args__ = (
        UniqueConstraint("series_id", "season_number", name="uq_seasons_series_number"),
    )


class Episode(Base):
    """A single episode of a season."""

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    episode_number: Mapped[int | None] = mapped_column(Integer)
    tmdb_number: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String)
    overview: Mapped[str | None] = mapped_column(String)
    path: Mapped[str | None] = mapped_column(String)
    runtime_seconds: Mapped[int | None] = mapped_column(Integer)
    air_date: Mapped[str | None] = mapped_column(String)
    is_missing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    watched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_played_at: Mapped[float | None] = mapped_column(Float)
    resume_position_seconds: Mapped[float | None] = mapped_column(Float)

    season: Mapped[Season] = relationship(back_populates="episodes")
    media_files: Mapped[list[MediaFile]] = relationship(
        "MediaFile",
        primaryjoin=(
            "and_(MediaFile.media_id == foreign(Episode.id), "
            "MediaFile.media_type == 'episode')"
        ),
        viewonly=True,
        uselist=True,
        order_by="MediaFile.path",
    )

    __table_args__ = (
        UniqueConstraint(
            "season_id", "episode_number", name="uq_episodes_season_number"
        ),
    )


class Movie(Base):
    """A movie belonging to a library."""

    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    folder_name: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    overview: Mapped[str | None] = mapped_column(String)
    poster_path: Mapped[str | None] = mapped_column(String)
    backdrop_path: Mapped[str | None] = mapped_column(String)
    tmdb_identifier: Mapped[str | None] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer)
    runtime_seconds: Mapped[int | None] = mapped_column(Integer)
    path: Mapped[str | None] = mapped_column(String)
    locked_metadata: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    last_modified: Mapped[float | None] = mapped_column(Float)
    date_added: Mapped[float | None] = mapped_column(Float)
    watched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_played_at: Mapped[float | None] = mapped_column(Float)
    resume_position_seconds: Mapped[float | None] = mapped_column(Float)

    library: Mapped[Library] = relationship(back_populates="movies")
    media_files: Mapped[list[MediaFile]] = relationship(
        "MediaFile",
        primaryjoin=(
            "and_(MediaFile.media_id == foreign(Movie.id), "
            "MediaFile.media_type == 'movie')"
        ),
        viewonly=True,
        uselist=True,
        order_by="MediaFile.path",
    )

    __table_args__ = (
        UniqueConstraint("library_id", "folder_name", name="uq_movies_library_folder"),
    )


class MediaFile(Base):
    """One physical video file (one version) for an episode or movie.

    Polymorphic ownership: ``media_type`` is ``"episode"`` or ``"movie"`` and
    ``media_id`` references the owning row's primary key. No database foreign
    key is possible for a polymorphic reference; the repository manages
    lifecycle explicitly.
    """

    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    media_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    path: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    codec: Mapped[str | None] = mapped_column(String)
    resolution: Mapped[str | None] = mapped_column(String)
    container: Mapped[str | None] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Subtitle(Base):
    """A subtitle file attached to an episode or movie."""

    __tablename__ = "subtitles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    media_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    path: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str | None] = mapped_column(String)
    forced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[str | None] = mapped_column(String)
    downloaded_at: Mapped[float | None] = mapped_column(Float)


class ScanJob(Base):
    """A scan job record: pending, running, cancelled, done, or error."""

    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int | None] = mapped_column(
        ForeignKey("libraries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    pass_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    started_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)
    finished_at: Mapped[float | None] = mapped_column(Float)
    stats_json: Mapped[str | None] = mapped_column(String)
    error_text: Mapped[str | None] = mapped_column(String)


class WatchEvent(Base):
    """A playback watch event posted by a desktop client."""

    __tablename__ = "watch_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    media_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event: Mapped[str] = mapped_column(String, nullable=False)  # play|stop|complete
    position_seconds: Mapped[float | None] = mapped_column(Float)
    client_id: Mapped[str | None] = mapped_column(String)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)


class SchemaVersion(Base):
    """Single-row schema version marker (id is always 1)."""

    __tablename__ = "schema_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class ScannedDirectory(Base):
    """Last-scanned mtime per directory, consumed by the reused scanner."""

    __tablename__ = "scanned_directories"

    path: Mapped[str] = mapped_column(String, primary_key=True)
    last_scanned_mtime: Mapped[float] = mapped_column(Float, nullable=False)
