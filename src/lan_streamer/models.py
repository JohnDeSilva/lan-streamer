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
    pass


class Series(Base):
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
    last_played_position: Mapped[Optional[int]] = mapped_column(Integer, default=0)

    season: Mapped[Optional["Season"]] = relationship(
        "Season", back_populates="episodes"
    )

    __table_args__ = (
        UniqueConstraint("season_id", "name", name="uq_episodes_season_id_name"),
        Index("idx_episodes_jellyfin_id", "jellyfin_id"),
        Index("idx_episodes_season_id", "season_id"),
    )
