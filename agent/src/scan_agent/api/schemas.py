"""Pydantic request/response schemas for the agent REST API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LibraryMediaType = Literal["tv", "anime", "movie"]
MediaTypeTv = LibraryMediaType
RenameTarget = Literal["series", "movie"]
WatchMediaType = Literal["episode", "movie"]
WatchEventName = Literal["play", "stop", "complete"]


class ConfigUpdate(BaseModel):
    """Subset of the agent config that can be updated in place."""

    model_config = ConfigDict(extra="ignore")

    tmdb_api_key: str | None = None
    scan_concurrency: int | None = Field(default=None, ge=1, le=32)
    opensubtitles_api_key: str | None = None
    opensubtitles_username: str | None = None
    opensubtitles_password: str | None = None
    cache_directory: str | None = None
    log_directory: str | None = None


class LibraryWrite(BaseModel):
    """Create/replace a library definition."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    media_type: MediaTypeTv
    root_path: str = Field(min_length=1)
    enabled: bool = True


class LibraryPatch(BaseModel):
    """Partial update of a library definition."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, min_length=1)
    media_type: MediaTypeTv | None = None
    root_path: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None


class ScanRequest(BaseModel):
    """Trigger a scan for one library or all libraries."""

    model_config = ConfigDict(extra="ignore")

    library_id: str | None = None
    pass_number: int = Field(default=0, ge=0, le=3)
    force_refresh: bool = False


class MetadataMatch(BaseModel):
    """Point a series/movie at a specific TMDB identifier."""

    model_config = ConfigDict(extra="ignore")

    tmdb_identifier: str = Field(min_length=1)


class RenameRequest(BaseModel):
    """Preview or apply a rename for a media item."""

    model_config = ConfigDict(extra="ignore")

    media_type: RenameTarget
    media_id: int
    template: str | None = None
    dry_run: bool = True


class SubtitleDownload(BaseModel):
    """Search and download a subtitle for an episode or movie."""

    model_config = ConfigDict(extra="ignore")

    media_type: WatchMediaType
    media_id: int
    language: str = "en"
    forced: bool = False


class WatchEventWrite(BaseModel):
    """Record a playback event from a desktop client."""

    model_config = ConfigDict(extra="ignore")

    media_type: WatchMediaType
    media_id: int
    event: WatchEventName
    position_seconds: float | None = None
    client_id: str | None = None


class ManualEpisodeMapping(BaseModel):
    """Manual mapping of a local file to a TMDB episode."""

    model_config = ConfigDict(extra="ignore")

    path: str = Field(min_length=1)
    episode_identifier: int | None = None
    tmdb_identifier: str | None = None
    tmdb_episode_identifier: str | None = None
    name: str | None = None
    episode_number: int | None = None
    season_number: int | None = None
    air_date: str | None = None
    overview: str | None = None
    runtime_seconds: int | None = None


class ManualMetadataMappingRequest(BaseModel):
    """Request payload to manually map episodes for a series."""

    model_config = ConfigDict(extra="ignore")

    episode_mappings: list[ManualEpisodeMapping]
