from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import (
    declarative_base,
    relationship,
)

Base = declarative_base()


class Series(Base):
    __tablename__ = "series"

    id = Column(Integer, primary_key=True, autoincrement=True)
    library_name = Column(String)
    name = Column(String)
    jellyfin_id = Column(String)
    tmdb_identifier = Column(String)
    poster_path = Column(String)
    overview = Column(String)
    tmdb_name = Column(String)
    locked_metadata = Column(Boolean, default=False)

    seasons = relationship(
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(Integer, ForeignKey("series.id", ondelete="CASCADE"))
    name = Column(String)
    jellyfin_id = Column(String)
    poster_path = Column(String)

    series = relationship("Series", back_populates="seasons")
    episodes = relationship(
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    season_id = Column(Integer, ForeignKey("seasons.id", ondelete="CASCADE"))
    name = Column(String)
    path = Column(String, unique=True)
    jellyfin_id = Column(String)
    tmdb_episode_identifier = Column(String)
    tmdb_name = Column(String)
    tmdb_number = Column(Integer)
    watched = Column(Boolean, default=False)
    date_added = Column(Integer, default=0)

    season = relationship("Season", back_populates="episodes")

    __table_args__ = (
        UniqueConstraint("season_id", "name", name="uq_episodes_season_id_name"),
        Index("idx_episodes_jellyfin_id", "jellyfin_id"),
        Index("idx_episodes_season_id", "season_id"),
    )
