from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from lan_streamer.db.models_cast import MediaCast, MediaImage
from sqlalchemy import (
    Integer,
    String,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
    LargeBinary,
    TypeDecorator,
    Float,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


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


class EncryptedString(TypeDecorator):
    """SQLAlchemy TypeDecorator that encrypts text on write to the database
    and decrypts it on read back from the database.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        from lan_streamer.system.encryption import encrypt_secret

        return encrypt_secret(value)

    def process_result_value(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        from lan_streamer.system.encryption import decrypt_secret

        # Support unencrypted legacy / seeded data transparently
        if value.strip().startswith("{"):
            return value
        try:
            return decrypt_secret(value)
        except Exception:
            return value


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
    secret: Mapped[Optional[str]] = mapped_column(EncryptedString, default="{}")

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
    rating: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    genre: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
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
    media_cast: Mapped[List["MediaCast"]] = relationship(
        "MediaCast",
        back_populates="series",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="MediaCast.series_id",
    )
    images: Mapped[List["MediaImage"]] = relationship(
        "MediaImage",
        back_populates="series",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="MediaImage.series_id",
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
    media_cast: Mapped[List["MediaCast"]] = relationship(
        "MediaCast",
        back_populates="season",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="MediaCast.season_id",
    )

    __table_args__ = (
        UniqueConstraint("series_id", "name", name="uq_seasons_series_id_name"),
        Index("idx_seasons_series_id", "series_id"),
    )


class CompatibilityMixin:
    """Mixin to provide backward-compatible properties and initialization logic for Episode and Movie."""

    id: Mapped[str]
    media_files: Mapped[List["MediaFile"]]
    default_path: Mapped[Optional[str]]
    playback_state: Mapped[Optional["PlaybackState"]]

    def __init__(self, **kwargs: Any) -> None:
        self._pending_media_attrs: dict[str, Any] = {}
        self._pending_playback_attrs: dict[str, Any] = {}
        super().__init__(**kwargs)

    def _flush_pending_to(self, mf: "MediaFile") -> None:
        """Apply any buffered media attributes onto a real MediaFile."""
        pending = getattr(self, "_pending_media_attrs", None)
        if pending:
            for attr, val in pending.items():
                setattr(mf, attr, val)
            pending.clear()

    def _ensure_playback_state(self) -> "PlaybackState":
        if not self.playback_state:
            from lan_streamer.db.models import PlaybackState

            if not self.id:
                self.id = _new_uuid_str()
            if hasattr(self, "season_id"):  # Episode
                self.playback_state = PlaybackState(episode_id=self.id)
            else:  # Movie
                self.playback_state = PlaybackState(movie_id=self.id)

            pending_pb = getattr(self, "_pending_playback_attrs", None)
            if pending_pb:
                for attr, val in pending_pb.items():
                    setattr(self.playback_state, attr, val)
                pending_pb.clear()
        return self.playback_state

    def _set_media_attr(self, attr: str, value: Any) -> None:
        """Set a media attribute on the first MediaFile, or buffer it if none exists."""
        if self.media_files:
            setattr(self.media_files[0], attr, value)
        else:
            if (
                not hasattr(self, "_pending_media_attrs")
                or self._pending_media_attrs is None
            ):
                self._pending_media_attrs = {}
            self._pending_media_attrs[attr] = value

    def _get_media_attr(self, attr: str) -> Any:
        """Read a media attribute from the first MediaFile, or from the pending buffer."""
        if self.media_files:
            return getattr(self.media_files[0], attr)
        pending = getattr(self, "_pending_media_attrs", None)
        if pending:
            return pending.get(attr)
        return None

    def _get_playback_attr(self, attr: str, default: Any) -> Any:
        if self.playback_state:
            return getattr(self.playback_state, attr)
        pending_pb = getattr(self, "_pending_playback_attrs", None)
        if pending_pb:
            return pending_pb.get(attr, default)
        return default

    def _set_playback_attr(self, attr: str, value: Any) -> None:
        if self.playback_state:
            setattr(self.playback_state, attr, value)
        else:
            if (
                not hasattr(self, "_pending_playback_attrs")
                or self._pending_playback_attrs is None
            ):
                self._pending_playback_attrs = {}
            self._pending_playback_attrs[attr] = value

    @property
    def path(self) -> Optional[str]:
        if self.default_path:
            return self.default_path
        if self.media_files:
            return self.media_files[0].path
        return None

    @path.setter
    def path(self, value: Optional[str]) -> None:
        if value == self.path:
            return
        self.default_path = value
        if value:
            exists = False
            for mf in self.media_files:
                if mf.path == value:
                    exists = True
                    self._flush_pending_to(mf)
                    break
            if not exists:
                mf = MediaFile(path=value)
                self._flush_pending_to(mf)
                self.media_files.append(mf)
        else:
            self.media_files.clear()

    @property
    def watched(self) -> bool:
        return self._get_playback_attr("watched", False)

    @watched.setter
    def watched(self, value: bool) -> None:
        self._ensure_playback_state()
        self._set_playback_attr("watched", value)

    @property
    def last_played_position(self) -> int:
        return self._get_playback_attr("last_played_position", 0)

    @last_played_position.setter
    def last_played_position(self, value: int) -> None:
        self._ensure_playback_state()
        self._set_playback_attr("last_played_position", value)

    @property
    def last_played_at(self) -> int:
        return self._get_playback_attr("last_played_at", 0)

    @last_played_at.setter
    def last_played_at(self, value: int) -> None:
        self._ensure_playback_state()
        self._set_playback_attr("last_played_at", value)

    @property
    def resolution(self) -> Optional[str]:
        return self._get_media_attr("resolution")

    @resolution.setter
    def resolution(self, value: Optional[str]) -> None:
        self._set_media_attr("resolution", value)

    @property
    def video_codec(self) -> Optional[str]:
        return self._get_media_attr("video_codec")

    @video_codec.setter
    def video_codec(self, value: Optional[str]) -> None:
        self._set_media_attr("video_codec", value)

    @property
    def audio_tracks(self) -> Optional[str]:
        return self._get_media_attr("audio_tracks")

    @audio_tracks.setter
    def audio_tracks(self, value: Optional[str]) -> None:
        self._set_media_attr("audio_tracks", value)

    @property
    def subtitle_tracks(self) -> Optional[str]:
        return self._get_media_attr("subtitle_tracks")

    @subtitle_tracks.setter
    def subtitle_tracks(self, value: Optional[str]) -> None:
        self._set_media_attr("subtitle_tracks", value)

    @property
    def bit_rate(self) -> Optional[int]:
        return self._get_media_attr("bit_rate")

    @bit_rate.setter
    def bit_rate(self, value: Optional[int]) -> None:
        self._set_media_attr("bit_rate", value)

    @property
    def file_runtime(self) -> Optional[int]:
        return self._get_media_attr("runtime")

    @file_runtime.setter
    def file_runtime(self, value: Optional[int]) -> None:
        self._set_media_attr("runtime", value)


class Episode(CompatibilityMixin, Base):
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
    date_added: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    air_date: Mapped[Optional[str]] = mapped_column(String)
    runtime: Mapped[Optional[int]] = mapped_column(Integer)
    myanimelist_anime_id: Mapped[Optional[int]] = mapped_column(Integer)
    myanimelist_episode_number: Mapped[Optional[int]] = mapped_column(Integer)
    default_path: Mapped[Optional[str]] = mapped_column(String)

    season: Mapped[Optional["Season"]] = relationship(
        "Season", back_populates="episodes"
    )
    media_files: Mapped[List["MediaFile"]] = relationship(
        "MediaFile",
        secondary="metadata_file_mappings",
        back_populates="episodes",
        passive_deletes=True,
        overlaps="media_files,episodes,movies",
    )
    playback_state: Mapped[Optional["PlaybackState"]] = relationship(
        "PlaybackState",
        back_populates="episode",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    media_cast: Mapped[List["MediaCast"]] = relationship(
        "MediaCast",
        back_populates="episode",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="MediaCast.episode_id",
    )

    __table_args__ = (
        UniqueConstraint("season_id", "name", name="uq_episodes_season_id_name"),
        Index("idx_episodes_jellyfin_id", "jellyfin_id"),
        Index("idx_episodes_season_id", "season_id"),
    )


class Movie(CompatibilityMixin, Base):
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
    default_path: Mapped[Optional[str]] = mapped_column(String)

    media_files: Mapped[List["MediaFile"]] = relationship(
        "MediaFile",
        secondary="metadata_file_mappings",
        back_populates="movies",
        passive_deletes=True,
        overlaps="media_files,episodes,movies",
    )
    playback_state: Mapped[Optional["PlaybackState"]] = relationship(
        "PlaybackState",
        back_populates="movie",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    media_cast: Mapped[List["MediaCast"]] = relationship(
        "MediaCast",
        back_populates="movie",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="MediaCast.movie_id",
    )
    images: Mapped[List["MediaImage"]] = relationship(
        "MediaImage",
        back_populates="movie",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="MediaImage.movie_id",
    )

    __table_args__ = (
        UniqueConstraint("library_name", "name", name="uq_movies_library_name_name"),
        Index("idx_movies_jellyfin_id", "jellyfin_id"),
    )


class MediaFile(Base):
    """Database model representing a physical media file mapped to an episode or movie."""

    __tablename__ = "media_files"

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    video_type: Mapped[Optional[str]] = mapped_column(String)
    video_codec: Mapped[Optional[str]] = mapped_column(String)
    resolution: Mapped[Optional[str]] = mapped_column(String)
    bit_rate: Mapped[Optional[int]] = mapped_column(Integer)
    audio_tracks: Mapped[Optional[str]] = mapped_column(String)
    subtitle_tracks: Mapped[Optional[str]] = mapped_column(String)
    runtime: Mapped[Optional[int]] = mapped_column(Integer)

    episodes: Mapped[List["Episode"]] = relationship(
        "Episode",
        secondary="metadata_file_mappings",
        back_populates="media_files",
        passive_deletes=True,
        overlaps="media_files,episodes,movies",
    )
    movies: Mapped[List["Movie"]] = relationship(
        "Movie",
        secondary="metadata_file_mappings",
        back_populates="media_files",
        passive_deletes=True,
        overlaps="media_files,episodes,movies",
    )
    # playback_state relationship removed, as playback state is now coupled to creative metadata.


class MetadataFileMapping(Base):
    """Many-to-many relationship mapping table between MediaFile and Episode or Movie."""

    __tablename__ = "metadata_file_mappings"

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    media_file_id: Mapped[str] = mapped_column(
        UUIDBLOB, ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB, ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True
    )
    movie_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB, ForeignKey("movies.id", ondelete="CASCADE"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "media_file_id", "episode_id", "movie_id", name="uq_metadata_file_mappings"
        ),
        Index("idx_metadata_file_mappings_episode", "episode_id", "media_file_id"),
        Index("idx_metadata_file_mappings_movie", "movie_id", "media_file_id"),
    )


class PlaybackState(Base):
    """Tracks playback/watch state for an episode or movie metadata record."""

    __tablename__ = "playback_states"

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    episode_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB,
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    movie_id: Mapped[Optional[str]] = mapped_column(
        UUIDBLOB,
        ForeignKey("movies.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    watched: Mapped[bool] = mapped_column(Boolean, default=False)
    last_played_position: Mapped[int] = mapped_column(Integer, default=0)
    last_played_at: Mapped[int] = mapped_column(Integer, default=0)

    episode: Mapped[Optional["Episode"]] = relationship(
        "Episode", back_populates="playback_state"
    )
    movie: Mapped[Optional["Movie"]] = relationship(
        "Movie", back_populates="playback_state"
    )


class SmartRowCache(Base):
    """Caches pre-computed smart row results for fast combined view rendering.

    Each row represents one item in one smart row configuration.
    The config_hash uniquely identifies a specific (libraries, sort_by, filter_mode)
    combination. Items are ordered by sort_order within each config_hash group.

    Foreign keys to ``series`` and ``movies`` provide live display data (name,
    poster_path, library_name), while computed aggregation fields (watched_count,
    date_added, etc.) avoid expensive recalculations on every render.
    """

    __tablename__ = "smart_row_cache"

    id: Mapped[str] = mapped_column(UUIDBLOB, primary_key=True, default=_new_uuid_str)
    config_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # "series", "season", "movie"

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

    season_name: Mapped[Optional[str]] = mapped_column(String)
    date_added: Mapped[int] = mapped_column(Integer, default=0)
    air_date: Mapped[Optional[str]] = mapped_column(String)
    watched_count: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=1)
    last_played_at: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[int] = mapped_column(Integer, default=0)

    series: Mapped[Optional["Series"]] = relationship(
        "Series",
        lazy="joined",
        foreign_keys=[series_id],
    )
    movie: Mapped[Optional["Movie"]] = relationship(
        "Movie",
        lazy="joined",
        foreign_keys=[movie_id],
    )

    __table_args__ = (Index("idx_smart_row_cache_config", "config_hash", "sort_order"),)


class ScannedDirectory(Base):
    """Stores the last scanned directory mtimes to minimize unnecessary scans."""

    __tablename__ = "scanned_directories"

    path: Mapped[str] = mapped_column(String, primary_key=True)
    last_scanned_mtime: Mapped[float] = mapped_column(Float, nullable=False)
