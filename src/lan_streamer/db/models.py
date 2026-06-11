import enum
import uuid
from typing import Optional, List, Any
from sqlalchemy import (
    Integer,
    String,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
    LargeBinary,
    TypeDecorator,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


def _new_uuid_bytes() -> bytes:
    """Generate a new UUID4 as raw bytes for use as a BLOB primary key."""
    return uuid.uuid4().bytes


def _new_uuid_str() -> str:
    """Generate a new UUID4 as a standard string."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for database models."""

    pass


class UUIDBLOB(TypeDecorator):
    """Platform-independent UUID type stored as 16-byte BLOB/LargeBinary,
    but exposed as standard canonical UUID hex string in Python/application code.
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[bytes]:
        if value is None:
            return None
        if isinstance(value, bytes):
            if len(value) == 16:
                return value
            return value
        if isinstance(value, uuid.UUID):
            return value.bytes
        try:
            return uuid.UUID(value).bytes
        except ValueError, TypeError, AttributeError:
            return value

    def process_result_value(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, bytes) and len(value) == 16:
            return str(uuid.UUID(bytes=value))
        return value


class SecretType(str, enum.Enum):
    """Enumeration of supported external-service secret types."""

    JELLYFIN = "jellyfin"
    TMDB = "tmdb"
    MYANIMELIST = "myanimelist"
    OPENSUBTITLES = "opensubtitles"


class AppSecret(Base):
    """Stores service credentials as opaque JSON blobs, one row per service.

    Each row is keyed by a generated UUID primary key and a unique ``secret_type``
    string (one of the ``SecretType`` enum values).  All fields for a given service
    are serialised together into the ``secret`` JSON column so that adding new
    fields never requires a schema migration.
    """

    __tablename__ = "app_secrets"

    secret_uuid: Mapped[str] = mapped_column(
        UUIDBLOB, primary_key=True, default=_new_uuid_str
    )
    secret_type: Mapped[str] = mapped_column(String, nullable=False)
    secret: Mapped[Optional[str]] = mapped_column(String, default="{}")

    __table_args__ = (UniqueConstraint("secret_type", name="uq_app_secrets_type"),)


class AppConfig(Base):
    """Key/value store for non-secret application configuration.

    The ``type`` column carries a short hint used by the query helpers to
    coerce the stored text back to the correct Python type on read:
    ``'str'``, ``'int'``, ``'float'``, ``'bool'``, or ``'json'``.
    """

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(String)
    type: Mapped[str] = mapped_column(String, default="str")


class Series(Base):
    """Database model representing a television series, containing references to seasons and metadata."""

    __tablename__ = "series"

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
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
    # Per-series user preferences
    pref_hide_missing_future: Mapped[Optional[bool]] = mapped_column(
        Boolean, default=False
    )
    pref_display_group_id: Mapped[Optional[str]] = mapped_column(String, default=None)

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

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    series_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB, ForeignKey("series.id", ondelete="CASCADE")
    )
    name: Mapped[Optional[str]] = mapped_column(String)
    jellyfin_id: Mapped[Optional[str]] = mapped_column(String)
    poster_path: Mapped[Optional[str]] = mapped_column(String)
    myanimelist_id: Mapped[Optional[int]] = mapped_column(Integer)

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

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    season_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB, ForeignKey("seasons.id", ondelete="CASCADE")
    )
    name: Mapped[Optional[str]] = mapped_column(String)
    jellyfin_id: Mapped[Optional[str]] = mapped_column(String)
    tmdb_episode_identifier: Mapped[Optional[str]] = mapped_column(String)
    tmdb_name: Mapped[Optional[str]] = mapped_column(String)
    tmdb_number: Mapped[Optional[int]] = mapped_column(Integer)
    watched: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    date_added: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    air_date: Mapped[Optional[str]] = mapped_column(String)
    runtime: Mapped[Optional[int]] = mapped_column(Integer)
    myanimelist_anime_id: Mapped[Optional[int]] = mapped_column(Integer)
    myanimelist_episode_number: Mapped[Optional[int]] = mapped_column(Integer)
    last_played_position: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    last_played_at: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    video_codec: Mapped[Optional[str]] = mapped_column(String)
    default_path: Mapped[Optional[str]] = mapped_column(String)

    season: Mapped[Optional["Season"]] = relationship(
        "Season", back_populates="episodes"
    )
    media_files: Mapped[List["MediaFile"]] = relationship(
        "MediaFile",
        back_populates="episode",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def _get_or_create_media_file(self) -> "MediaFile":
        if not self.media_files:
            mf = MediaFile(path=f"pending_{uuid.uuid4()}")
            self.media_files.append(mf)
            return mf
        return self.media_files[0]

    @property
    def path(self) -> Optional[str]:
        if self.default_path:
            return self.default_path
        if self.media_files:
            p = self.media_files[0].path
            if p and p.startswith("pending_"):
                return None
            return p
        return None

    @path.setter
    def path(self, value: Optional[str]) -> None:
        if value == self.path:
            return
        self.default_path = value
        if value:
            if len(self.media_files) == 1 and self.media_files[0].path.startswith(
                "pending_"
            ):
                self.media_files[0].path = value
            else:
                exists = False
                for mf in self.media_files:
                    if mf.path == value:
                        exists = True
                        break
                if not exists:
                    self.media_files.append(MediaFile(path=value))
        else:
            self.media_files.clear()

    @property
    def resolution(self) -> Optional[str]:
        if self.media_files:
            return self.media_files[0].resolution
        return None

    @resolution.setter
    def resolution(self, value: Optional[str]) -> None:
        self._get_or_create_media_file().resolution = value

    @property
    def audio_tracks(self) -> Optional[str]:
        if self.media_files:
            return self.media_files[0].audio_tracks
        return None

    @audio_tracks.setter
    def audio_tracks(self, value: Optional[str]) -> None:
        self._get_or_create_media_file().audio_tracks = value

    @property
    def subtitle_tracks(self) -> Optional[str]:
        if self.media_files:
            return self.media_files[0].subtitle_tracks
        return None

    @subtitle_tracks.setter
    def subtitle_tracks(self, value: Optional[str]) -> None:
        self._get_or_create_media_file().subtitle_tracks = value

    @property
    def bit_rate(self) -> Optional[int]:
        if self.media_files:
            return self.media_files[0].bit_rate
        return None

    @bit_rate.setter
    def bit_rate(self, value: Optional[int]) -> None:
        self._get_or_create_media_file().bit_rate = value

    @property
    def file_runtime(self) -> Optional[int]:
        if self.media_files:
            return self.media_files[0].runtime
        return None

    @file_runtime.setter
    def file_runtime(self, value: Optional[int]) -> None:
        self._get_or_create_media_file().runtime = value

    __table_args__ = (
        UniqueConstraint("season_id", "name", name="uq_episodes_season_id_name"),
        Index("idx_episodes_jellyfin_id", "jellyfin_id"),
        Index("idx_episodes_season_id", "season_id"),
    )


class Movie(Base):
    """Database model representing a movie, including technical properties and watch status."""

    __tablename__ = "movies"

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    library_name: Mapped[Optional[str]] = mapped_column(String)
    name: Mapped[Optional[str]] = mapped_column(String)
    jellyfin_id: Mapped[Optional[str]] = mapped_column(String)
    tmdb_identifier: Mapped[Optional[str]] = mapped_column(String)
    poster_path: Mapped[Optional[str]] = mapped_column(String)
    overview: Mapped[Optional[str]] = mapped_column(String)
    tmdb_name: Mapped[Optional[str]] = mapped_column(String)
    locked_metadata: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    date_added: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    myanimelist_anime_id: Mapped[Optional[int]] = mapped_column(Integer)
    runtime: Mapped[Optional[int]] = mapped_column(Integer)
    rating: Mapped[Optional[str]] = mapped_column(String)
    genre: Mapped[Optional[str]] = mapped_column(String)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    watched: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    last_played_position: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    last_played_at: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    video_codec: Mapped[Optional[str]] = mapped_column(String)
    default_path: Mapped[Optional[str]] = mapped_column(String)

    media_files: Mapped[List["MediaFile"]] = relationship(
        "MediaFile",
        back_populates="movie",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def _get_or_create_media_file(self) -> "MediaFile":
        if not self.media_files:
            mf = MediaFile(path=f"pending_{uuid.uuid4()}")
            self.media_files.append(mf)
            return mf
        return self.media_files[0]

    @property
    def path(self) -> Optional[str]:
        if self.default_path:
            return self.default_path
        if self.media_files:
            p = self.media_files[0].path
            if p and p.startswith("pending_"):
                return None
            return p
        return None

    @path.setter
    def path(self, value: Optional[str]) -> None:
        if value == self.path:
            return
        self.default_path = value
        if value:
            if len(self.media_files) == 1 and self.media_files[0].path.startswith(
                "pending_"
            ):
                self.media_files[0].path = value
            else:
                exists = False
                for mf in self.media_files:
                    if mf.path == value:
                        exists = True
                        break
                if not exists:
                    self.media_files.append(MediaFile(path=value))
        else:
            self.media_files.clear()

    @property
    def resolution(self) -> Optional[str]:
        if self.media_files:
            return self.media_files[0].resolution
        return None

    @resolution.setter
    def resolution(self, value: Optional[str]) -> None:
        self._get_or_create_media_file().resolution = value

    @property
    def audio_tracks(self) -> Optional[str]:
        if self.media_files:
            return self.media_files[0].audio_tracks
        return None

    @audio_tracks.setter
    def audio_tracks(self, value: Optional[str]) -> None:
        self._get_or_create_media_file().audio_tracks = value

    @property
    def subtitle_tracks(self) -> Optional[str]:
        if self.media_files:
            return self.media_files[0].subtitle_tracks
        return None

    @subtitle_tracks.setter
    def subtitle_tracks(self, value: Optional[str]) -> None:
        self._get_or_create_media_file().subtitle_tracks = value

    @property
    def bit_rate(self) -> Optional[int]:
        if self.media_files:
            return self.media_files[0].bit_rate
        return None

    @bit_rate.setter
    def bit_rate(self, value: Optional[int]) -> None:
        self._get_or_create_media_file().bit_rate = value

    @property
    def file_runtime(self) -> Optional[int]:
        if self.media_files:
            return self.media_files[0].runtime
        return None

    @file_runtime.setter
    def file_runtime(self, value: Optional[int]) -> None:
        self._get_or_create_media_file().runtime = value

    __table_args__ = (
        UniqueConstraint("library_name", "name", name="uq_movies_library_name_name"),
        Index("idx_movies_jellyfin_id", "jellyfin_id"),
    )


class MediaFile(Base):
    """Database model representing a physical media file mapped to an episode or movie."""

    __tablename__ = "media_files"

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    episode_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB, ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True
    )
    movie_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB, ForeignKey("movies.id", ondelete="CASCADE"), nullable=True
    )
    path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    video_type: Mapped[Optional[str]] = mapped_column(String)
    video_codec: Mapped[Optional[str]] = mapped_column(String)
    resolution: Mapped[Optional[str]] = mapped_column(String)
    bit_rate: Mapped[Optional[int]] = mapped_column(Integer)
    audio_tracks: Mapped[Optional[str]] = mapped_column(String)
    subtitle_tracks: Mapped[Optional[str]] = mapped_column(String)
    runtime: Mapped[Optional[int]] = mapped_column(Integer)

    episode: Mapped[Optional["Episode"]] = relationship(
        "Episode", back_populates="media_files"
    )
    movie: Mapped[Optional["Movie"]] = relationship(
        "Movie", back_populates="media_files"
    )
