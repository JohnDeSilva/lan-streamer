import logging
import re
import json
from typing import Dict, Any, List, Optional
from sqlalchemy import select

from lan_streamer.db.models import Series, Season, Episode, Movie

logger = logging.getLogger("lan_streamer.db.queries")


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


def natural_sort_key(s: Optional[str]) -> List[Any]:
    """
    Key function for natural sorting (e.g., "Season 2" < "Season 10").
    """
    if s is None:
        return []
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split("([0-9]+)", str(s))
    ]


def _build_episode_dict(episode: Episode) -> Dict[str, Any]:
    """Maps a single Episode ORM row to its plain dictionary representation."""
    try:
        audio_tracks = json.loads(episode.audio_tracks) if episode.audio_tracks else []
    except Exception:
        audio_tracks = []
    try:
        subtitle_tracks = (
            json.loads(episode.subtitle_tracks) if episode.subtitle_tracks else []
        )
    except Exception:
        subtitle_tracks = []

    versions = []
    for mf in episode.media_files:
        try:
            audio = json.loads(mf.audio_tracks) if mf.audio_tracks else []
        except Exception:
            audio = []
        try:
            subs = json.loads(mf.subtitle_tracks) if mf.subtitle_tracks else []
        except Exception:
            subs = []
        versions.append(
            {
                "path": mf.path,
                "size_bytes": mf.size_bytes or 0,
                "video_type": mf.video_type or "",
                "video_codec": mf.video_codec or "",
                "resolution": mf.resolution or "",
                "bit_rate": mf.bit_rate or 0,
                "audio_tracks": audio,
                "subtitle_tracks": subs,
                "runtime": mf.runtime,
            }
        )

    return {
        "name": episode.name,
        "path": episode.path,
        "jellyfin_id": episode.jellyfin_id,
        "tmdb_episode_identifier": episode.tmdb_episode_identifier,
        "tmdb_name": episode.tmdb_name,
        "tmdb_number": episode.tmdb_number,
        "myanimelist_anime_id": episode.myanimelist_anime_id,
        "myanimelist_episode_number": episode.myanimelist_episode_number,
        "watched": bool(episode.watched),
        "date_added": episode.date_added or 0,
        "air_date": episode.air_date or "",
        "runtime": episode.runtime or 0,
        "file_runtime": episode.file_runtime or 0,
        "last_played_at": episode.last_played_at or 0,
        "video_codec": episode.video_codec or "",
        "resolution": episode.resolution or "",
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
        "bit_rate": episode.bit_rate or 0,
        "versions": versions,
        "default_path": episode.default_path or "",
    }


def _build_season_dict(season: Season) -> Dict[str, Any]:
    """Maps a single Season ORM row (with its episodes) to a plain dict."""
    episodes = [_build_episode_dict(episode) for episode in season.episodes]
    episodes.sort(key=lambda x: natural_sort_key(x["name"]))
    return {
        "metadata": {
            "jellyfin_id": season.jellyfin_id,
            "poster_path": season.poster_path,
            "myanimelist_id": season.myanimelist_id,
        },
        "episodes": episodes,
    }


def _build_series_dict(series: Series) -> Dict[str, Any]:
    """Maps a single Series ORM row (with seasons and episodes) to a plain dict."""
    seasons: Dict[str, Any] = {}
    for season in series.seasons:
        if season.name is not None:
            seasons[season.name] = _build_season_dict(season)
    return {
        "metadata": {
            "jellyfin_id": series.jellyfin_id,
            "tmdb_identifier": series.tmdb_identifier,
            "poster_path": series.poster_path,
            "overview": series.overview,
            "tmdb_name": series.tmdb_name,
            "locked_metadata": bool(series.locked_metadata),
            "first_air_date": series.first_air_date or "",
            "tmdb_episode_group_id": series.tmdb_episode_group_id,
        },
        "seasons": seasons,
    }


def _build_movie_dict(movie: Movie) -> Dict[str, Any]:
    """Maps a single Movie ORM row to its plain dictionary representation."""
    try:
        audio_tracks = json.loads(movie.audio_tracks) if movie.audio_tracks else []
    except Exception:
        audio_tracks = []
    try:
        subtitle_tracks = (
            json.loads(movie.subtitle_tracks) if movie.subtitle_tracks else []
        )
    except Exception:
        subtitle_tracks = []

    versions = []
    for mf in movie.media_files:
        try:
            audio = json.loads(mf.audio_tracks) if mf.audio_tracks else []
        except Exception:
            audio = []
        try:
            subs = json.loads(mf.subtitle_tracks) if mf.subtitle_tracks else []
        except Exception:
            subs = []
        versions.append(
            {
                "path": mf.path,
                "size_bytes": mf.size_bytes or 0,
                "video_type": mf.video_type or "",
                "video_codec": mf.video_codec or "",
                "resolution": mf.resolution or "",
                "bit_rate": mf.bit_rate or 0,
                "audio_tracks": audio,
                "subtitle_tracks": subs,
                "runtime": mf.runtime,
            }
        )

    return {
        "name": movie.name,
        "path": movie.path,
        "jellyfin_id": movie.jellyfin_id,
        "tmdb_identifier": movie.tmdb_identifier,
        "poster_path": movie.poster_path,
        "overview": movie.overview,
        "tmdb_name": movie.tmdb_name,
        "locked_metadata": bool(movie.locked_metadata),
        "date_added": movie.date_added or 0,
        "myanimelist_anime_id": movie.myanimelist_anime_id,
        "runtime": movie.runtime or 0,
        "file_runtime": movie.file_runtime or 0,
        "rating": movie.rating or "",
        "genre": movie.genre or "",
        "year": movie.year or 0,
        "watched": bool(movie.watched),
        "last_played_position": movie.last_played_position or 0,
        "last_played_at": movie.last_played_at or 0,
        "video_codec": movie.video_codec or "",
        "resolution": movie.resolution or "",
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
        "bit_rate": movie.bit_rate or 0,
        "versions": versions,
        "default_path": movie.default_path or "",
    }


def update_episode_path(old_path: str, new_path: str) -> None:
    """Updates the file path for an episode in the database."""
    try:
        logger.debug(
            f"Executing DB update_episode_path: old_path={old_path}, new_path={new_path}"
        )
        logger.info(f"Updating episode path from {old_path} to {new_path}")
        with get_session() as session:
            from lan_streamer.db.models import MediaFile

            mf = session.scalars(
                select(MediaFile).where(MediaFile.path == old_path)
            ).first()
            if mf:
                mf.path = new_path
                if mf.episode:
                    if mf.episode.default_path == old_path:
                        mf.episode.default_path = new_path
                logger.debug(f"Updated MediaFile path to {new_path}")
            else:
                episode = session.scalars(
                    select(Episode).join(MediaFile).where(MediaFile.path == old_path)
                ).first()
                if episode:
                    if episode.default_path == old_path:
                        episode.default_path = new_path
                    logger.debug(f"Updated Episode default_path to {new_path}")
                else:
                    logger.debug(f"No MediaFile or Episode found for path: {old_path}")
    except Exception:
        logger.exception(f"Error updating episode path from {old_path} to {new_path}")


def is_movie(path: str) -> bool:
    """Returns True if the given path corresponds to a movie in the database."""
    try:
        logger.debug(f"Executing DB is_movie check: path={path}")
        with get_session() as session:
            from lan_streamer.db.models import MediaFile

            movie = session.scalars(
                select(Movie).join(MediaFile).where(MediaFile.path == path)
            ).first()
            result = movie is not None
            logger.debug(f"is_movie query response for path={path}: {result}")
            return result
    except Exception:
        logger.exception(f"Error checking if path is movie: {path}")
        return False


def delete_series_record(library_name: str, series_name: str) -> None:
    """Deletes a series record from the database."""
    try:
        logger.debug(
            f"Executing DB delete_series_record: library={library_name}, series={series_name}"
        )
        logger.info(
            f"Deleting series '{series_name}' from library '{library_name}' in database"
        )
        with get_session() as session:
            series = session.scalars(
                select(Series).where(
                    Series.library_name == library_name, Series.name == series_name
                )
            ).first()
            if series:
                session.delete(series)
                logger.debug(
                    f"Deleted series '{series_name}' from library '{library_name}' successfully"
                )
            else:
                logger.debug(
                    f"Series '{series_name}' not found for deletion in library '{library_name}'"
                )
    except Exception:
        logger.exception(f"Error deleting series '{series_name}'")


def delete_episode_record(path: str) -> None:
    """Deletes an episode record from the database."""
    try:
        logger.debug(f"Executing DB delete_episode_record: path={path}")
        logger.info(f"Deleting episode record for path: {path}")
        with get_session() as session:
            from lan_streamer.db.models import MediaFile

            episode = session.scalars(
                select(Episode).join(MediaFile).where(MediaFile.path == path)
            ).first()
            if episode:
                session.delete(episode)
                logger.debug(f"Deleted episode record for path: {path} successfully")
            else:
                logger.debug(f"Episode record not found for deletion for path: {path}")
    except Exception:
        logger.exception(f"Error deleting episode record for '{path}'")
