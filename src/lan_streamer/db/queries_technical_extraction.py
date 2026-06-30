import logging
import json
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from lan_streamer.db.models import Episode, Movie, MediaFile, Season

logger = logging.getLogger("lan_streamer.db.queries")


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


def get_items_missing_runtime() -> List[Dict[str, Any]]:
    """Retrieves all episodes and movies whose runtime is 0/missing or whose technical metadata (codec, bit rate, resolution) is missing."""
    items_list: List[Dict[str, Any]] = []
    try:
        logger.debug("Executing DB query: get_items_missing_runtime")
        with get_session() as session:
            from lan_streamer.db.models import MetadataFileMapping

            episodes = (
                session.scalars(
                    select(Episode)
                    .options(
                        joinedload(Episode.season).joinedload(Season.series),
                        joinedload(Episode.media_files),
                    )
                    .outerjoin(
                        MetadataFileMapping,
                        MetadataFileMapping.episode_id == Episode.id,
                    )
                    .outerjoin(
                        MediaFile, MediaFile.id == MetadataFileMapping.media_file_id
                    )
                    .where(
                        (MediaFile.id.is_(None))
                        | (MediaFile.runtime.is_(None))
                        | (MediaFile.runtime == 0)
                        | (MediaFile.video_codec.is_(None))
                        | (MediaFile.video_codec == "Unknown")
                        | (MediaFile.video_codec == "")
                        | (MediaFile.resolution.is_(None))
                        | (MediaFile.resolution == "Unknown")
                        | (MediaFile.resolution == "")
                        | (MediaFile.bit_rate.is_(None))
                        | (MediaFile.bit_rate <= 0)
                    )
                    .distinct()
                )
                .unique()
                .all()
            )
            for episode in episodes:
                path = episode.default_path or (
                    episode.media_files[0].path if episode.media_files else None
                )
                if path:
                    library_name: Optional[str] = None
                    if episode.season and episode.season.series:
                        library_name = episode.season.series.library_name
                    items_list.append(
                        {
                            "id": episode.id,
                            "path": path,
                            "type": "episode",
                            "season_id": episode.season_id,
                            "library_name": library_name,
                        }
                    )

            movies = (
                session.scalars(
                    select(Movie)
                    .options(joinedload(Movie.media_files))
                    .outerjoin(
                        MetadataFileMapping, MetadataFileMapping.movie_id == Movie.id
                    )
                    .outerjoin(
                        MediaFile, MediaFile.id == MetadataFileMapping.media_file_id
                    )
                    .where(
                        (MediaFile.id.is_(None))
                        | (MediaFile.runtime.is_(None))
                        | (MediaFile.runtime == 0)
                        | (MediaFile.video_codec.is_(None))
                        | (MediaFile.video_codec == "Unknown")
                        | (MediaFile.video_codec == "")
                        | (MediaFile.resolution.is_(None))
                        | (MediaFile.resolution == "Unknown")
                        | (MediaFile.resolution == "")
                        | (MediaFile.bit_rate.is_(None))
                        | (MediaFile.bit_rate <= 0)
                    )
                    .distinct()
                )
                .unique()
                .all()
            )
            for movie in movies:
                path = movie.default_path or (
                    movie.media_files[0].path if movie.media_files else None
                )
                if path:
                    items_list.append(
                        {
                            "id": movie.id,
                            "path": path,
                            "type": "movie",
                            "library_name": movie.library_name,
                        }
                    )
        logger.debug(
            f"get_items_missing_runtime query response: found {len(items_list)} items"
        )
    except Exception:
        logger.exception("Error fetching items missing runtime")
    return items_list


def update_items_runtime_batch(updates: List[Dict[str, Any]]) -> None:
    """Updates the runtime and technical info fields for multiple episodes or movies in a single transaction."""
    try:
        logger.debug(
            f"Executing DB update_items_runtime_batch with {len(updates)} updates: {updates}"
        )
        with get_session() as session:
            for update in updates:
                item_identifier = update["item_identifier"]
                item_type = update["item_type"]
                runtime_minutes = update.get("runtime_minutes")
                video_codec = update.get("video_codec")
                resolution = update.get("resolution")
                audio_tracks = update.get("audio_tracks")
                subtitle_tracks = update.get("subtitle_tracks")
                bit_rate = update.get("bit_rate")
                size_bytes = update.get("size_bytes")

                if item_type == "episode":
                    episode = session.scalars(
                        select(Episode)
                        .where(Episode.id == item_identifier)
                        .options(joinedload(Episode.media_files))
                    ).first()
                    if episode:
                        if runtime_minutes is not None and (
                            runtime_minutes > 0 or not episode.file_runtime
                        ):
                            episode.file_runtime = runtime_minutes
                        if episode.media_files:
                            mf = episode.media_files[0]
                            if video_codec:
                                mf.video_codec = video_codec
                            if resolution:
                                mf.resolution = resolution
                            if bit_rate is not None:
                                mf.bit_rate = bit_rate
                            if audio_tracks is not None:
                                mf.audio_tracks = json.dumps(audio_tracks)
                            if subtitle_tracks is not None:
                                mf.subtitle_tracks = json.dumps(subtitle_tracks)
                            if size_bytes is not None:
                                mf.size_bytes = size_bytes
                            if runtime_minutes is not None:
                                mf.runtime = runtime_minutes
                elif item_type == "movie":
                    movie = session.scalars(
                        select(Movie)
                        .where(Movie.id == item_identifier)
                        .options(joinedload(Movie.media_files))
                    ).first()
                    if movie:
                        if runtime_minutes is not None and (
                            runtime_minutes > 0 or not movie.file_runtime
                        ):
                            movie.file_runtime = runtime_minutes
                        if movie.media_files:
                            mf = movie.media_files[0]
                            if video_codec:
                                mf.video_codec = video_codec
                            if resolution:
                                mf.resolution = resolution
                            if bit_rate is not None:
                                mf.bit_rate = bit_rate
                            if audio_tracks is not None:
                                mf.audio_tracks = json.dumps(audio_tracks)
                            if subtitle_tracks is not None:
                                mf.subtitle_tracks = json.dumps(subtitle_tracks)
                            if size_bytes is not None:
                                mf.size_bytes = size_bytes
                            if runtime_minutes is not None:
                                mf.runtime = runtime_minutes
        logger.debug(f"Saved DB batch updates for {len(updates)} items")
    except Exception:
        logger.exception("Error during batch update of runtimes and technical info")
