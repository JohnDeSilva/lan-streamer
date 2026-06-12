import logging
import json
from typing import Dict, Any, List, Optional
from sqlalchemy import select

from lan_streamer.db.models import Episode, Movie, MediaFile

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
            episodes = session.scalars(
                select(Episode)
                .outerjoin(Episode.media_files)
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
            ).all()
            for episode in episodes:
                if episode.path:
                    items_list.append(
                        {
                            "id": episode.id,
                            "path": episode.path,
                            "type": "episode",
                            "season_id": episode.season_id,
                        }
                    )

            movies = session.scalars(
                select(Movie)
                .outerjoin(Movie.media_files)
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
            ).all()
            for movie in movies:
                if movie.path:
                    items_list.append(
                        {"id": movie.id, "path": movie.path, "type": "movie"}
                    )
        logger.debug(
            f"get_items_missing_runtime query response: found {len(items_list)} items"
        )
    except Exception:
        logger.exception("Error fetching items missing runtime")
    return items_list


def update_item_runtime(
    item_identifier: bytes | str,
    item_type: str,
    runtime_minutes: Optional[int],
    video_codec: Optional[str] = None,
    resolution: Optional[str] = None,
    audio_tracks: Optional[List[Dict[str, Any]]] = None,
    subtitle_tracks: Optional[List[Dict[str, Any]]] = None,
    bit_rate: Optional[int] = None,
    size_bytes: Optional[int] = None,
) -> None:
    """Updates the runtime and technical info fields for a given episode or movie."""
    try:
        logger.debug(
            f"Executing DB update_item_runtime for {item_type} ID {item_identifier!r} "
            f"with runtime={runtime_minutes}, codec={video_codec}, resolution={resolution}, size={size_bytes}"
        )
        with get_session() as session:
            if item_type == "episode":
                episode = session.scalars(
                    select(Episode).where(Episode.id == item_identifier)
                ).first()
                if episode:
                    if runtime_minutes is not None and (
                        runtime_minutes > 0 or not episode.file_runtime
                    ):
                        episode.file_runtime = runtime_minutes
                    if video_codec:
                        episode.video_codec = video_codec
                        if episode.media_files:
                            episode.media_files[0].video_codec = video_codec
                    if resolution:
                        episode.resolution = resolution
                    if bit_rate is not None:
                        episode.bit_rate = bit_rate
                    if audio_tracks is not None:
                        episode.audio_tracks = json.dumps(audio_tracks)
                    if subtitle_tracks is not None:
                        episode.subtitle_tracks = json.dumps(subtitle_tracks)
                    if size_bytes is not None:
                        if episode.media_files:
                            episode.media_files[0].size_bytes = size_bytes
            elif item_type == "movie":
                movie = session.scalars(
                    select(Movie).where(Movie.id == item_identifier)
                ).first()
                if movie:
                    if runtime_minutes is not None and (
                        runtime_minutes > 0 or not movie.file_runtime
                    ):
                        movie.file_runtime = runtime_minutes
                    if video_codec:
                        movie.video_codec = video_codec
                        if movie.media_files:
                            movie.media_files[0].video_codec = video_codec
                    if resolution:
                        movie.resolution = resolution
                    if bit_rate is not None:
                        movie.bit_rate = bit_rate
                    if audio_tracks is not None:
                        movie.audio_tracks = json.dumps(audio_tracks)
                    if subtitle_tracks is not None:
                        movie.subtitle_tracks = json.dumps(subtitle_tracks)
                    if size_bytes is not None:
                        if movie.media_files:
                            movie.media_files[0].size_bytes = size_bytes
        logger.debug(f"Saved DB updates for {item_type} ID {item_identifier!r}")
    except Exception:
        logger.exception(
            f"Error updating runtime and technical info for {item_type} ID {item_identifier!r}"
        )


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
                        select(Episode).where(Episode.id == item_identifier)
                    ).first()
                    if episode:
                        if runtime_minutes is not None and (
                            runtime_minutes > 0 or not episode.file_runtime
                        ):
                            episode.file_runtime = runtime_minutes
                        if video_codec:
                            episode.video_codec = video_codec
                            if episode.media_files:
                                episode.media_files[0].video_codec = video_codec
                        if resolution:
                            episode.resolution = resolution
                        if bit_rate is not None:
                            episode.bit_rate = bit_rate
                        if audio_tracks is not None:
                            episode.audio_tracks = json.dumps(audio_tracks)
                        if subtitle_tracks is not None:
                            episode.subtitle_tracks = json.dumps(subtitle_tracks)
                        if size_bytes is not None:
                            if episode.media_files:
                                episode.media_files[0].size_bytes = size_bytes
                elif item_type == "movie":
                    movie = session.scalars(
                        select(Movie).where(Movie.id == item_identifier)
                    ).first()
                    if movie:
                        if runtime_minutes is not None and (
                            runtime_minutes > 0 or not movie.file_runtime
                        ):
                            movie.file_runtime = runtime_minutes
                        if video_codec:
                            movie.video_codec = video_codec
                            if movie.media_files:
                                movie.media_files[0].video_codec = video_codec
                        if resolution:
                            movie.resolution = resolution
                        if bit_rate is not None:
                            movie.bit_rate = bit_rate
                        if audio_tracks is not None:
                            movie.audio_tracks = json.dumps(audio_tracks)
                        if subtitle_tracks is not None:
                            movie.subtitle_tracks = json.dumps(subtitle_tracks)
                        if size_bytes is not None:
                            if movie.media_files:
                                movie.media_files[0].size_bytes = size_bytes
        logger.debug(f"Saved DB batch updates for {len(updates)} items")
    except Exception:
        logger.exception("Error during batch update of runtimes and technical info")


def has_tech_and_metadata(item_identifier: bytes | str, item_type: str) -> bool:
    """Returns True if the item already has both complete technical metadata and creative metadata."""
    try:
        logger.debug(
            f"Executing has_tech_and_metadata for {item_type} ID {item_identifier!r}"
        )
        with get_session() as session:
            if item_type == "episode":
                episode = session.scalars(
                    select(Episode).where(Episode.id == item_identifier)
                ).first()
                if episode:
                    # Creative metadata check
                    has_metadata = bool(
                        episode.tmdb_episode_identifier
                        or episode.name
                        or episode.jellyfin_id
                    )
                    # Technical metadata check
                    has_tech = False
                    if episode.media_files:
                        mf = episode.media_files[0]
                        has_tech = bool(
                            mf.video_codec
                            and mf.video_codec != "Unknown"
                            and mf.video_codec != ""
                            and mf.resolution
                            and mf.resolution != "Unknown"
                            and mf.resolution != ""
                            and (mf.runtime or 0) > 0
                        )
                    result = has_metadata and has_tech
                    logger.debug(
                        f"has_tech_and_metadata response for episode ID {item_identifier!r}: {result}"
                    )
                    return result
            elif item_type == "movie":
                movie = session.scalars(
                    select(Movie).where(Movie.id == item_identifier)
                ).first()
                if movie:
                    # Creative metadata check
                    has_metadata = bool(
                        movie.tmdb_identifier or movie.name or movie.jellyfin_id
                    )
                    # Technical metadata check
                    has_tech = False
                    if movie.media_files:
                        mf = movie.media_files[0]
                        has_tech = bool(
                            mf.video_codec
                            and mf.video_codec != "Unknown"
                            and mf.video_codec != ""
                            and mf.resolution
                            and mf.resolution != "Unknown"
                            and mf.resolution != ""
                            and (mf.runtime or 0) > 0
                        )
                    result = has_metadata and has_tech
                    logger.debug(
                        f"has_tech_and_metadata response for movie ID {item_identifier!r}: {result}"
                    )
                    return result
    except Exception:
        pass
    return False
