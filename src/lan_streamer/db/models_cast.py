"""Cast, crew, and image database models for media metadata.

This module defines the database models for tracking people (actors, directors,
crew members), their roles in media items (cast/crew assignments), and images
associated with series and movies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lan_streamer.db.models import UUIDBLOB, _new_uuid_str, Base

if TYPE_CHECKING:
    from lan_streamer.db.models import Series, Season, Episode, Movie


class Person(Base):
    """Database model representing a person (actor, director, crew member).

    Each person is uniquely identified by their TMDB identifier when available,
    and stores profile metadata such as biography, birth/death dates, and
    alternate names.
    """

    __tablename__ = "people"

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    tmdb_identifier: Mapped[Optional[int]] = mapped_column(
        Integer, unique=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    biography: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    birth_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    death_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    place_of_birth: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    also_known_as: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )  # JSON string
    updated_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    media_cast: Mapped[List["MediaCast"]] = relationship(
        "MediaCast",
        back_populates="person",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_people_tmdb_identifier", "tmdb_identifier"),
        Index("idx_people_name", "name"),
    )


class MediaCast(Base):
    """Database model linking a person to a media item with role information.

    Records the role (actor, director, writer, etc.), character name, job title,
    and department for a person's involvement in a series, season, episode, or movie.
    """

    __tablename__ = "media_cast"

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    person_id: Mapped[str] = mapped_column(
        UUIDBLOB,
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    series_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB,
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    season_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB,
        ForeignKey("seasons.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    episode_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB,
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    movie_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB,
        ForeignKey("movies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    character: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    job: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tmdb_credit_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    person: Mapped["Person"] = relationship("Person", back_populates="media_cast")
    series: Mapped[Optional["Series"]] = relationship(
        "Series", back_populates="media_cast", foreign_keys=[series_id]
    )
    season: Mapped[Optional["Season"]] = relationship(
        "Season", back_populates="media_cast", foreign_keys=[season_id]
    )
    episode: Mapped[Optional["Episode"]] = relationship(
        "Episode", back_populates="media_cast", foreign_keys=[episode_id]
    )
    movie: Mapped[Optional["Movie"]] = relationship(
        "Movie", back_populates="media_cast", foreign_keys=[movie_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "person_id", "tmdb_credit_id", name="uq_media_cast_person_credit"
        ),
    )


class MediaImage(Base):
    """Database model representing images associated with media items.

    Stores poster, backdrop, logo, and other image types linked to a series or
    movie, with support for multiple sources (TMDB, local) and selected state.
    """

    __tablename__ = "media_images"

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    series_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB,
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    movie_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB,
        ForeignKey("movies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    image_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    remote_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    series: Mapped[Optional["Series"]] = relationship(
        "Series", back_populates="images", foreign_keys=[series_id]
    )
    movie: Mapped[Optional["Movie"]] = relationship(
        "Movie", back_populates="images", foreign_keys=[movie_id]
    )
