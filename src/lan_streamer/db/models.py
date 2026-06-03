from typing import Optional, List
from sqlalchemy import (
    Integer,
    String,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for database models."""

    pass


class Series(Base):
    """Database model representing a television series, containing references to seasons and metadata."""

    __tablename__ = "series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    library_name: Mapped[Optional[str]] = mapped_column(String)
    name: Mapped[Optional[str]] = mapped_column(String)
    jellyfin_id: Mapped[Optional[str]] = mapped_column(String)
    tmdb_identifier: Mapped[Optional[str]] = mapped_column(String)
    poster_path: Mapped[Optional[str]] = mapped_column(String)
    overview: Mapped[Optional[str]] = mapped_column(String)
    tmdb_name: Mapped[Optional[str]] = mapped_column(String)
    locked_metadata: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    first_air_date: Mapped[Optional[str]] = mapped_column(String)
    tmdb_episode_group_id: Mapped[Optional[str]] = mapped_column(String)

    seasons: Mapped[List["Season"]] = relationship(
        "Season",
        back_populates="series",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("library_name", "name", name="uq_series_library_name_name"),
    )


class Season(Base):
    """Database model representing a specific season of a television series."""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("series.id", ondelete="CASCADE")
    )
    name: Mapped[Optional[str]] = mapped_column(String)
    jellyfin_id: Mapped[Optional[str]] = mapped_column(String)
    poster_path: Mapped[Optional[str]] = mapped_column(String)

    series: Mapped[Optional["Series"]] = relationship(
        "Series", back_populates="seasons"
    )
    episodes: Mapped[List["Episode"]] = relationship(
        "Episode",
        back_populates="season",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("series_id", "name", name="uq_seasons_series_id_name"),
        Index("idx_seasons_series_id", "series_id"),
    )


class Episode(Base):
    """Database model representing a single television show episode, including technical video characteristics and watch status."""

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("seasons.id", ondelete="CASCADE")
    )
    name: Mapped[Optional[str]] = mapped_column(String)
    path: Mapped[Optional[str]] = mapped_column(String, unique=True)
    jellyfin_id: Mapped[Optional[str]] = mapped_column(String)
    tmdb_episode_identifier: Mapped[Optional[str]] = mapped_column(String)
    tmdb_name: Mapped[Optional[str]] = mapped_column(String)
    tmdb_number: Mapped[Optional[int]] = mapped_column(Integer)
    watched: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    date_added: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    air_date: Mapped[Optional[str]] = mapped_column(String)
    runtime: Mapped[Optional[int]] = mapped_column(Integer)
    last_played_position: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    last_played_at: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    video_codec: Mapped[Optional[str]] = mapped_column(String)
    resolution: Mapped[Optional[str]] = mapped_column(String)
    audio_tracks: Mapped[Optional[str]] = mapped_column(String)
    subtitle_tracks: Mapped[Optional[str]] = mapped_column(String)

    season: Mapped[Optional["Season"]] = relationship(
        "Season", back_populates="episodes"
    )

    __table_args__ = (
        UniqueConstraint("season_id", "name", name="uq_episodes_season_id_name"),
        Index("idx_episodes_jellyfin_id", "jellyfin_id"),
        Index("idx_episodes_season_id", "season_id"),
    )


class Movie(Base):
    """Database model representing a movie, including technical properties and watch status."""

    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    library_name: Mapped[Optional[str]] = mapped_column(String)
    name: Mapped[Optional[str]] = mapped_column(String)
    jellyfin_id: Mapped[Optional[str]] = mapped_column(String)
    tmdb_identifier: Mapped[Optional[str]] = mapped_column(String)
    poster_path: Mapped[Optional[str]] = mapped_column(String)
    overview: Mapped[Optional[str]] = mapped_column(String)
    tmdb_name: Mapped[Optional[str]] = mapped_column(String)
    locked_metadata: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    date_added: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    path: Mapped[Optional[str]] = mapped_column(String, unique=True)
    runtime: Mapped[Optional[int]] = mapped_column(Integer)
    rating: Mapped[Optional[str]] = mapped_column(String)
    genre: Mapped[Optional[str]] = mapped_column(String)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    watched: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    last_played_position: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    last_played_at: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    video_codec: Mapped[Optional[str]] = mapped_column(String)
    resolution: Mapped[Optional[str]] = mapped_column(String)
    audio_tracks: Mapped[Optional[str]] = mapped_column(String)
    subtitle_tracks: Mapped[Optional[str]] = mapped_column(String)

    __table_args__ = (
        UniqueConstraint("library_name", "name", name="uq_movies_library_name_name"),
        Index("idx_movies_jellyfin_id", "jellyfin_id"),
    )
