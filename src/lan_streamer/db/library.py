import logging
import time
import json
from pathlib import Path
from typing import Dict, Any, List

from sqlalchemy import select, inspect
from sqlalchemy.orm import Session, selectinload

from lan_streamer.db.models import Series, Season, Episode, Movie, MediaFile
from lan_streamer.system.config import config
from lan_streamer.db.queries_file_discovery import (
    _build_series_dict,
    _build_movie_dict,
)


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


logger = logging.getLogger(__name__)


def _update_field_safely(existing_val: Any, incoming_val: Any) -> Any:
    """
    Prevents overwriting valid database values with null, empty, or placeholder "Unknown" values.
    """
    if incoming_val is None:
        return existing_val
    if isinstance(incoming_val, str) and incoming_val in ("", "Unknown"):
        return existing_val
    if isinstance(incoming_val, (list, dict)) and not incoming_val:
        return existing_val
    return incoming_val


def _sync_media_files(
    session: Session, owner: Any, versions_data: List[Dict[str, Any]] | None
) -> None:
    if versions_data is None:
        return

    incoming_paths = {v["path"] for v in versions_data if v.get("path")}

    # First, resolve/deduplicate any transient MediaFile objects created by setters
    # against existing database records to avoid UNIQUE constraint violations on flush.
    for path in incoming_paths:
        db_mf = session.scalars(select(MediaFile).where(MediaFile.path == path)).first()
        if not db_mf:
            for obj in session.new:
                if isinstance(obj, MediaFile) and obj.path == path:
                    db_mf = obj
                    break
        if db_mf:
            incorrect_mfs = [
                mf_obj
                for mf_obj in list(owner.media_files)
                if mf_obj.path == path and mf_obj != db_mf
            ]
            for mf_obj in incorrect_mfs:
                owner.media_files.remove(mf_obj)
                if mf_obj in session:
                    session.expunge(mf_obj)
            if db_mf not in owner.media_files:
                owner.media_files.append(db_mf)

    # Remove existing files not in incoming
    existing_files = {mf.path: mf for mf in owner.media_files}
    deleted_any = False
    for path, mf in list(existing_files.items()):
        if path not in incoming_paths:
            owner.media_files.remove(mf)
            # Only delete the media file from database if it's no longer referenced
            has_other_refs = any(ep != owner for ep in mf.episodes) or any(
                mv != owner for mv in mf.movies
            )
            if not has_other_refs:
                session.delete(mf)
                deleted_any = True

    # Flush deletes immediately so the database unique constraint is freed
    if deleted_any:
        session.flush()

    # Add or update files
    for v in versions_data:
        path = v.get("path")
        if not path:
            continue

        mf = None
        for existing_mf in owner.media_files:
            if existing_mf.path == path:
                mf = existing_mf
                break

        if not mf:
            # Look for the correct MediaFile in the database or session.new
            db_mf = session.scalars(
                select(MediaFile).where(MediaFile.path == path)
            ).first()
            if not db_mf:
                for obj in session.new:
                    if (
                        isinstance(obj, MediaFile)
                        and obj.path == path
                        and obj not in owner.media_files
                    ):
                        db_mf = obj
                        break

            if db_mf:
                if db_mf not in owner.media_files:
                    owner.media_files.append(db_mf)
                mf = db_mf
            else:
                mf = MediaFile(path=path)
                owner.media_files.append(mf)
                session.add(mf)

        mf.size_bytes = _update_field_safely(mf.size_bytes, v.get("size_bytes"))
        mf.video_type = _update_field_safely(mf.video_type, v.get("video_type"))
        mf.video_codec = _update_field_safely(mf.video_codec, v.get("video_codec"))
        mf.resolution = _update_field_safely(mf.resolution, v.get("resolution"))
        mf.bit_rate = _update_field_safely(mf.bit_rate, v.get("bit_rate"))

        incoming_audio = v.get("audio_tracks")
        if incoming_audio is not None and len(incoming_audio) > 0:
            mf.audio_tracks = json.dumps(incoming_audio)
        incoming_subs = v.get("subtitle_tracks")
        if incoming_subs is not None and len(incoming_subs) > 0:
            mf.subtitle_tracks = json.dumps(incoming_subs)


def _apply_movie_fields(movie: Movie, movie_data: Dict[str, Any]) -> None:
    """
    Applies all creative metadata fields from *movie_data* onto the *movie* ORM object.
    Only overrides existing values when the incoming value is non-falsy.
    """
    movie.jellyfin_id = movie_data.get("jellyfin_id") or movie.jellyfin_id
    movie.tmdb_identifier = movie_data.get("tmdb_identifier") or movie.tmdb_identifier
    movie.poster_path = movie_data.get("poster_path") or movie.poster_path
    movie.overview = movie_data.get("overview") or movie.overview
    movie.tmdb_name = movie_data.get("tmdb_name") or movie.tmdb_name
    if "locked_metadata" in movie_data:
        movie.locked_metadata = bool(movie_data["locked_metadata"])
    movie.date_added = movie_data.get("date_added") or movie.date_added or 0
    movie.runtime = movie_data.get("runtime") or movie.runtime or 0
    movie.rating = movie_data.get("rating") or movie.rating or ""
    movie.genre = movie_data.get("genre") or movie.genre or ""
    if "myanimelist_anime_id" in movie_data:
        movie.myanimelist_anime_id = movie_data["myanimelist_anime_id"]
    movie.year = movie_data.get("year") or movie.year or 0

    movie.video_codec = _update_field_safely(
        movie.video_codec, movie_data.get("video_codec")
    )
    movie.resolution = _update_field_safely(
        movie.resolution, movie_data.get("resolution")
    )
    movie.bit_rate = _update_field_safely(movie.bit_rate, movie_data.get("bit_rate"))
    incoming_audio = movie_data.get("audio_tracks")
    if incoming_audio is not None and len(incoming_audio) > 0:
        movie.audio_tracks = json.dumps(incoming_audio)
    incoming_subs = movie_data.get("subtitle_tracks")
    if incoming_subs is not None and len(incoming_subs) > 0:
        movie.subtitle_tracks = json.dumps(incoming_subs)

    movie.default_path = _update_field_safely(
        movie.default_path, movie_data.get("default_path") or movie_data.get("path")
    )

    watched = bool(movie_data.get("watched"))
    if watched:
        movie.watched = True


def _cleanup_movie_library(
    session: Session,
    library_name: str,
    stats: Dict[str, int],
) -> None:
    """Removes Movie records whose file path no longer exists on disk."""
    movie_list = session.scalars(
        select(Movie)
        .where(Movie.library_name == library_name)
        .options(selectinload(Movie.media_files))
    ).all()
    for movie in movie_list:
        path = movie.default_path or (
            movie.media_files[0].path if movie.media_files else None
        )
        if path and not Path(path).exists():
            logger.info(f"Cleanup: Removing missing movie '{movie.name}' at '{path}'")
            session.delete(movie)
            stats["movies"] += 1
            stats["movies_removed"] = stats.get("movies_removed", 0) + 1


def _cleanup_tv_library(
    session: Session,
    library_name: str,
    root_directories: List[str],
    stats: Dict[str, int],
) -> None:
    """
    Removes Series records whose folder no longer exists in any root directory.
    For series whose folder still exists, sets episode.default_path = None for any
    episode file that is no longer present on disk (rather than deleting the record).
    Season and episode records are never deleted independently — only cascade-deleted
    when the parent series record is removed.
    """
    series_list = session.scalars(
        select(Series)
        .where(Series.library_name == library_name)
        .options(
            selectinload(Series.seasons)
            .selectinload(Season.episodes)
            .selectinload(Episode.media_files)
        )
    ).all()

    for series in series_list:
        series_path_exists = any(
            series.name and (Path(root) / series.name).is_dir()
            for root in root_directories
        )
        if not series_path_exists:
            logger.info(f"Cleanup: Removing missing series '{series.name}'")
            stats["seasons"] += len(series.seasons)
            stats["seasons_removed"] = stats.get("seasons_removed", 0) + len(
                series.seasons
            )
            for season in series.seasons:
                stats["episodes"] += len(season.episodes)
                stats["episodes_removed"] = stats.get("episodes_removed", 0) + len(
                    season.episodes
                )
            session.delete(series)
            stats["series"] += 1
            stats["series_removed"] = stats.get("series_removed", 0) + 1
            continue

        # Series folder still exists — null out paths for files that are gone
        for season in series.seasons:
            for episode in season.episodes:
                path = episode.default_path or (
                    episode.media_files[0].path if episode.media_files else None
                )
                if episode.media_files == [] and episode.tmdb_number is None:
                    logger.info(
                        f"Cleanup: Removing unmatched episode S{season.name} E{episode.name} "
                        f"('{episode.name}') at '{path}'"
                    )
                    session.delete(episode)
                    stats["episodes_removed"] = stats.get("episodes_removed", 0) + 1
                elif path and not Path(path).exists():
                    logger.info(
                        f"Cleanup: Setting path=None for missing episode "
                        f"'{episode.name}' (was '{path}')"
                    )
                    episode.path = None
                    stats["episodes"] += 1


def load_library(library_name: str) -> Dict[str, Any]:
    """
    Loads the library from the database and constructs a nested dictionary structure.
    """

    start_time = time.time()
    library_data = {}
    stats = {"series": 0, "seasons": 0, "episodes": 0}

    try:
        with get_session() as session:
            series_list = session.scalars(
                select(Series)
                .where(Series.library_name == library_name)
                .options(
                    selectinload(Series.seasons)
                    .selectinload(Season.episodes)
                    .selectinload(Episode.media_files),
                    selectinload(Series.seasons)
                    .selectinload(Season.episodes)
                    .selectinload(Episode.playback_state),
                )
                .order_by(Series.name)
            ).all()

            for series in series_list:
                stats["series"] += 1
                stats["seasons"] += len(series.seasons)
                for season in series.seasons:
                    stats["episodes"] += len(season.episodes)
                if series.name is not None:
                    library_data[series.name] = _build_series_dict(series)

    except Exception:
        logger.exception(f"Error loading library '{library_name}' from database")
        return {}

    duration = time.time() - start_time
    logger.info(
        f"Loaded library '{library_name}' in {duration:.3f}s: {stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes."
    )
    return library_data


def _save_series_record(
    session: Session,
    library_name: str,
    series_name: str,
    series_data: Dict[str, Any],
    existing_series: Dict[str, Series],
    stats: Dict[str, Any],
) -> Series:
    series = existing_series.get(series_name)
    if not series:
        series = Series(library_name=library_name, name=series_name)
        session.add(series)
        stats["series_added"] = stats.get("series_added", 0) + 1
    stats["series"] += 1

    series_metadata = series_data.get("metadata", {})
    series.jellyfin_id = series_metadata.get("jellyfin_id") or series.jellyfin_id
    series.tmdb_identifier = (
        series_metadata.get("tmdb_identifier") or series.tmdb_identifier
    )
    series.poster_path = series_metadata.get("poster_path") or series.poster_path
    series.overview = series_metadata.get("overview") or series.overview
    series.tmdb_name = series_metadata.get("tmdb_name") or series.tmdb_name
    if "locked_metadata" in series_metadata:
        series.locked_metadata = bool(series_metadata["locked_metadata"])
    series.first_air_date = (
        series_metadata.get("first_air_date") or series.first_air_date
    )
    if "tmdb_episode_group_id" in series_metadata:
        series.tmdb_episode_group_id = series_metadata.get("tmdb_episode_group_id")
    return series


def _save_season_record(
    session: Session,
    series: Series,
    season_name: str,
    season_data: Dict[str, Any],
    existing_seasons: Dict[str, Season],
    stats: Dict[str, Any],
) -> Season:
    season = existing_seasons.get(season_name)
    if not season:
        season = Season(name=season_name, series=series)
        session.add(season)
        stats["seasons_added"] = stats.get("seasons_added", 0) + 1
    stats["seasons"] += 1

    season_metadata = season_data.get("metadata", {})
    season.jellyfin_id = season_metadata.get("jellyfin_id") or season.jellyfin_id
    season.poster_path = season_metadata.get("poster_path") or season.poster_path
    if "myanimelist_id" in season_metadata:
        season.myanimelist_id = season_metadata["myanimelist_id"]
    return season


def _save_episode_record(
    session: Session,
    season: Season,
    episode_data: Dict[str, Any],
    existing_by_path: Dict[str, Episode],
    existing_by_number: Dict[int, Episode],
    existing_by_name: Dict[str, Episode],
    stats: Dict[str, Any],
    processed_episodes: set[Episode] | None = None,
) -> Episode:
    path = episode_data.get("path") or None
    tmdb_num = episode_data.get("tmdb_number")
    name = episode_data.get("name")

    episode = None
    if path:
        episode = existing_by_path.get(path)
        if (
            episode
            and episode.tmdb_number is not None
            and episode.tmdb_number != tmdb_num
        ):
            if processed_episodes is None or episode not in processed_episodes:
                # File is being mapped to a different episode!
                # Clear path from the old episode record to remove the old mapping.
                logger.info(
                    f"File '{path}' is being remapped from episode S{season.name} E{episode.tmdb_number} to E{tmdb_num or 'None'}. "
                    f"Clearing path from the old episode record."
                )
                episode.path = None
                existing_by_path.pop(path, None)
                if episode.tmdb_number is not None:
                    existing_by_number[episode.tmdb_number] = episode
                episode = None
            else:
                # Shared/multi-episode path. We don't clear the path of the processed episode,
                # and we resolve episode to None so a new Episode is created/found.
                episode = None

        # If not found by path, check if there was a missing/future episode placeholder
        if not episode and tmdb_num is not None:
            episode = existing_by_number.get(tmdb_num)
            if episode:
                # Promote placeholder to local file
                logger.info(
                    f"Promoting placeholder episode S{season.name} E{tmdb_num} to local path {path}"
                )
                old_path = episode.path
                episode.path = path
                if old_path and old_path in existing_by_path:
                    existing_by_path.pop(old_path, None)
    elif tmdb_num is not None:
        episode = existing_by_number.get(tmdb_num)

    # Fallback to name-based matching if still not found, to avoid UNIQUE constraint violation on name
    if not episode and name:
        episode = existing_by_name.get(name)
        if episode:
            logger.debug(
                f"Matched existing episode by name fallback: S{season.name} '{name}'"
            )
            old_path = episode.path
            if path and not episode.path:
                episode.path = path
            if tmdb_num is not None and episode.tmdb_number is None:
                episode.tmdb_number = tmdb_num
            if old_path and old_path != episode.path and old_path in existing_by_path:
                existing_by_path.pop(old_path, None)

    if not episode:
        episode = Episode(path=path, season=season)
        session.add(episode)
        stats["episodes_added"] = stats.get("episodes_added", 0) + 1
    else:
        # Remove from tracking dicts so it's not reused/considered stale
        if episode.path in existing_by_path:
            existing_by_path.pop(episode.path, None)
        if episode.tmdb_number in existing_by_number:
            existing_by_number.pop(episode.tmdb_number, None)
        if episode.name in existing_by_name:
            existing_by_name.pop(episode.name, None)

    # If we newly added a path, make sure it is indexed
    if path:
        existing_by_path[path] = episode

    stats["episodes"] += 1

    # Deduplicate/merge any pre-existing Episode records that represent versions of this episode
    v_list = episode_data.get("versions")
    if v_list is None and episode_data.get("path"):
        v_list = [{"path": episode_data.get("path")}]
    if v_list:
        for v in v_list:
            v_path = v.get("path")
            if v_path:
                dup_ep = existing_by_path.get(v_path)
                if dup_ep and dup_ep != episode:
                    logger.info(
                        f"Merging duplicate episode record '{dup_ep.name}' (path={v_path}) "
                        f"into main episode '{episode.name or episode_data['name']}'"
                    )
                    # Transfer media files from duplicate to main episode
                    for mf in list(dup_ep.media_files):
                        if mf not in episode.media_files:
                            episode.media_files.append(mf)

                    # Transfer/merge playback state
                    if dup_ep.playback_state:
                        if not episode.playback_state:
                            from lan_streamer.db.models import _new_uuid_str

                            if not episode.id:
                                episode.id = _new_uuid_str()
                            episode.playback_state = dup_ep.playback_state
                            dup_ep.playback_state = None
                        else:
                            if (dup_ep.playback_state.last_played_at or 0) > (
                                episode.playback_state.last_played_at or 0
                            ):
                                episode.playback_state.last_played_at = (
                                    dup_ep.playback_state.last_played_at
                                )
                                episode.playback_state.last_played_position = (
                                    dup_ep.playback_state.last_played_position
                                )
                            if dup_ep.playback_state.watched:
                                episode.playback_state.watched = True
                            session.delete(dup_ep.playback_state)

                    # Delete duplicate from session and remove from tracking dicts
                    session.delete(dup_ep)
                    session.flush()
                    stats["deleted"] += 1
                    stats["episodes_removed"] = stats.get("episodes_removed", 0) + 1

                    dup_path = dup_ep.default_path or (
                        dup_ep.media_files[0].path if dup_ep.media_files else None
                    )
                    if dup_path in existing_by_path:
                        existing_by_path.pop(dup_path, None)
                    if dup_ep.tmdb_number in existing_by_number:
                        existing_by_number.pop(dup_ep.tmdb_number, None)
                    if dup_ep.name in existing_by_name:
                        existing_by_name.pop(dup_ep.name, None)

    target_name = episode_data["name"]
    # Ensure name is unique within the season to avoid UNIQUE constraint violation
    existing_names = {
        ep.name
        for ep in season.episodes
        if ep is not episode
        and ep.name is not None
        and ep in session
        and ep not in session.deleted
    }
    if target_name in existing_names:
        base_name = target_name
        counter = 1
        new_name = f"{base_name} ({counter})"
        while new_name in existing_names:
            counter += 1
            new_name = f"{base_name} ({counter})"
        target_name = new_name
        msg = (
            f"Duplicate episode name conflict in season '{season.name}': "
            f"'{base_name}' renamed to '{target_name}' to prevent UNIQUE constraint violation."
        )
        logger.warning(
            f"[SCAN_ISSUE] Type=Name Conflict Resolution | Item=Episode '{base_name}' (Season: '{season.name}') | Error={msg}"
        )
        if "issues" in stats:
            stats["issues"].append(
                {
                    "type": "Name Conflict Resolution",
                    "item": f"Episode '{base_name}' (Season: '{season.name}')",
                    "error": msg,
                }
            )
    episode.name = target_name
    episode.jellyfin_id = episode_data.get("jellyfin_id") or episode.jellyfin_id
    episode.tmdb_episode_identifier = (
        episode_data.get("tmdb_episode_identifier") or episode.tmdb_episode_identifier
    )
    episode.tmdb_name = episode_data.get("tmdb_name") or episode.tmdb_name
    if episode_data.get("tmdb_number") is not None:
        episode.tmdb_number = episode_data["tmdb_number"]
    episode.date_added = episode_data.get("date_added") or episode.date_added or 0
    episode.air_date = episode_data.get("air_date") or episode.air_date
    episode.runtime = episode_data.get("runtime") or episode.runtime or 0
    if "myanimelist_anime_id" in episode_data:
        episode.myanimelist_anime_id = episode_data["myanimelist_anime_id"]
    if "myanimelist_episode_number" in episode_data:
        episode.myanimelist_episode_number = episode_data["myanimelist_episode_number"]
    versions = episode_data.get("versions")
    if versions is None and episode_data.get("path"):
        versions = [
            {
                "path": episode_data.get("path"),
                "video_codec": episode_data.get("video_codec"),
                "resolution": episode_data.get("resolution"),
                "bit_rate": episode_data.get("bit_rate"),
                "audio_tracks": episode_data.get("audio_tracks"),
                "subtitle_tracks": episode_data.get("subtitle_tracks"),
            }
        ]
    _sync_media_files(session, episode, versions)

    episode.default_path = _update_field_safely(
        episode.default_path,
        episode_data.get("default_path") or episode_data.get("path"),
    )

    watched = bool(episode_data.get("watched"))
    if watched:
        episode.watched = True
    if processed_episodes is not None:
        processed_episodes.add(episode)
    return episode


def save_library(library_name: str, library: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates the database for the given library name using SQLAlchemy ORM.
    """

    start_time = time.time()
    stats: Dict[str, Any] = {
        "series": 0,
        "seasons": 0,
        "episodes": 0,
        "deleted": 0,
        "issues": [],
        "series_added": 0,
        "series_removed": 0,
        "seasons_added": 0,
        "seasons_removed": 0,
        "episodes_added": 0,
        "episodes_removed": 0,
        "movies_added": 0,
        "movies_removed": 0,
    }

    try:
        with get_session() as session:
            existing_series = {
                series_obj.name: series_obj
                for series_obj in session.scalars(
                    select(Series)
                    .where(Series.library_name == library_name)
                    .options(
                        selectinload(Series.seasons)
                        .selectinload(Season.episodes)
                        .selectinload(Episode.media_files),
                        selectinload(Series.seasons)
                        .selectinload(Season.episodes)
                        .selectinload(Episode.playback_state),
                    )
                ).all()
                if series_obj.name is not None
            }

            for series_name, series_data in library.items():
                series = _save_series_record(
                    session,
                    library_name,
                    series_name,
                    series_data,
                    existing_series,
                    stats,
                )

                existing_seasons = {
                    season_obj.name: season_obj
                    for season_obj in series.seasons
                    if season_obj.name is not None
                }

                for season_name, season_data in series_data.get("seasons", {}).items():
                    season = _save_season_record(
                        session,
                        series,
                        season_name,
                        season_data,
                        existing_seasons,
                        stats,
                    )

                    existing_by_path = {}
                    existing_by_number = {}
                    existing_by_name = {}
                    for episode_obj in season.episodes:
                        is_missing = False
                        if episode_obj.path is not None:
                            try:
                                if not Path(episode_obj.path).exists():
                                    is_missing = True
                            except Exception:
                                is_missing = True

                        if episode_obj.path is not None and not is_missing:
                            existing_by_path[episode_obj.path] = episode_obj
                        else:
                            if episode_obj.path is not None:
                                existing_by_path[episode_obj.path] = episode_obj
                            if episode_obj.tmdb_number is not None:
                                existing_by_number[episode_obj.tmdb_number] = (
                                    episode_obj
                                )

                        if episode_obj.name is not None:
                            existing_by_name[episode_obj.name] = episode_obj

                    processed_episodes = set()
                    for episode_data in season_data.get("episodes", []):
                        _save_episode_record(
                            session,
                            season,
                            episode_data,
                            existing_by_path,
                            existing_by_number,
                            existing_by_name,
                            stats,
                            processed_episodes,
                        )

                    # Delete stale placeholders (which have path=None)
                    stale_placeholders = set()
                    for ep_obj in list(existing_by_number.values()):
                        if ep_obj.path is None:
                            stale_placeholders.add(ep_obj)
                    for ep_obj in list(existing_by_name.values()):
                        if ep_obj.path is None:
                            stale_placeholders.add(ep_obj)

                    for ep_obj in stale_placeholders:
                        logger.info(
                            f"Removing stale placeholder episode S{season.name} E{ep_obj.tmdb_number} from database"
                        )
                        if ep_obj in season.episodes:
                            season.episodes.remove(ep_obj)
                        state = inspect(ep_obj)
                        if state.key is None:
                            if ep_obj in session:
                                session.expunge(ep_obj)
                        else:
                            session.delete(ep_obj)
                        stats["deleted"] += 1
                        stats["episodes_removed"] = stats.get("episodes_removed", 0) + 1

    except Exception as e:
        logger.exception(f"Error saving library '{library_name}' to database")
        stats["issues"].append(
            {
                "type": "Database Write Failure",
                "item": f"Library '{library_name}'",
                "error": str(e),
            }
        )

    duration = time.time() - start_time
    logger.info(
        f"Library '{library_name}' updated in {duration:.3f}s: "
        f"{stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes saved. "
        f"{stats['deleted']} stale items removed."
    )
    return stats


def load_movie_library(library_name: str) -> Dict[str, Any]:
    """
    Loads the movie library from the database and constructs a dictionary structure.
    """

    start_time = time.time()
    library_data = {}
    stats = {"movies": 0}

    try:
        with get_session() as session:
            movie_list = session.scalars(
                select(Movie)
                .where(Movie.library_name == library_name)
                .options(
                    selectinload(Movie.media_files), selectinload(Movie.playback_state)
                )
                .order_by(Movie.name)
            ).all()

            for movie in movie_list:
                stats["movies"] += 1
                if movie.name is not None:
                    library_data[movie.name] = _build_movie_dict(movie)
    except Exception:
        logger.exception(f"Error loading movie library '{library_name}' from database")
        return {}

    duration = time.time() - start_time
    logger.info(
        f"Loaded movie library '{library_name}' in {duration:.3f}s: {stats['movies']} movies."
    )
    return library_data


def save_movie_library(library_name: str, library: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates the database for the given movie library name using SQLAlchemy ORM.
    """

    start_time = time.time()
    stats: Dict[str, Any] = {
        "movies": 0,
        "deleted": 0,
        "issues": [],
        "movies_added": 0,
        "movies_removed": 0,
    }

    try:
        with get_session() as session:
            existing_movies_by_name = {
                m.name: m
                for m in session.scalars(
                    select(Movie)
                    .where(Movie.library_name == library_name)
                    .options(
                        selectinload(Movie.media_files),
                        selectinload(Movie.playback_state),
                    )
                ).all()
                if m.name is not None
            }
            incoming_paths = [
                data.get("path") for data in library.values() if data.get("path")
            ]
            existing_movies_by_path = {}
            if incoming_paths:
                existing_movies_by_path = {
                    m.path: m
                    for m in session.scalars(
                        select(Movie)
                        .join(Movie.media_files)
                        .where(MediaFile.path.in_(incoming_paths))
                        .options(
                            selectinload(Movie.media_files),
                            selectinload(Movie.playback_state),
                        )
                    ).all()
                    if m.path is not None
                }

            existing_movies_by_tmdb = {}
            for m in list(existing_movies_by_name.values()):
                if m.tmdb_identifier:
                    is_missing = False
                    if m.path:
                        try:
                            if not Path(m.path).exists():
                                is_missing = True
                        except Exception:
                            is_missing = True
                    if is_missing:
                        existing_movies_by_tmdb[m.tmdb_identifier] = m

            touched_movie_names = set()

            for movie_name, movie_data in library.items():
                touched_movie_names.add(movie_name)
                path = movie_data.get("path")

                movie = None
                if path and path in existing_movies_by_path:
                    movie = existing_movies_by_path[path]
                elif movie_name in existing_movies_by_name:
                    movie = existing_movies_by_name[movie_name]
                else:
                    tmdb_id = movie_data.get("tmdb_identifier")
                    if tmdb_id and tmdb_id in existing_movies_by_tmdb:
                        movie = existing_movies_by_tmdb[tmdb_id]

                if not movie:
                    movie = Movie(library_name=library_name, name=movie_name)
                    session.add(movie)
                    stats["movies_added"] = stats.get("movies_added", 0) + 1
                else:
                    if movie.name != movie_name:
                        stale_movie = existing_movies_by_name.get(movie_name)
                        if stale_movie and stale_movie is not movie:
                            logger.info(
                                f"Removing stale movie record '{movie_name}' to avoid name collision."
                            )
                            session.delete(stale_movie)
                            session.flush()
                            stats["movies_removed"] = stats.get("movies_removed", 0) + 1
                            del existing_movies_by_name[movie_name]
                    movie.library_name = library_name
                    movie.name = movie_name

                stats["movies"] += 1

                if path:
                    existing_movies_by_path[path] = movie
                existing_movies_by_name[movie_name] = movie

                versions = movie_data.get("versions")
                if versions is None and movie_data.get("path"):
                    versions = [
                        {
                            "path": movie_data.get("path"),
                            "video_codec": movie_data.get("video_codec"),
                            "resolution": movie_data.get("resolution"),
                            "bit_rate": movie_data.get("bit_rate"),
                            "audio_tracks": movie_data.get("audio_tracks"),
                            "subtitle_tracks": movie_data.get("subtitle_tracks"),
                        }
                    ]
                _sync_media_files(session, movie, versions)
                _apply_movie_fields(movie, movie_data)

    except Exception as e:
        logger.exception(f"Error saving movie library '{library_name}' to database")
        stats["issues"].append(
            {
                "type": "Database Write Failure",
                "item": f"Movie Library '{library_name}'",
                "error": str(e),
            }
        )

    duration = time.time() - start_time
    logger.info(
        f"Movie library '{library_name}' updated in {duration:.3f}s: "
        f"{stats['movies']} movies saved. "
    )
    return stats


def _cleanup_orphaned_media_files(
    session: Session, root_directories: List[str], stats: Dict[str, int]
) -> None:
    """Removes MediaFile records under root_directories whose physical file no longer exists on disk."""
    media_files = session.scalars(select(MediaFile)).all()
    removed_count = 0
    for mf in media_files:
        in_library = False
        try:
            mf_path = Path(mf.path)
            for root in root_directories:
                try:
                    mf_path.relative_to(Path(root))
                    in_library = True
                    break
                except ValueError:
                    continue
        except Exception:
            pass

        if in_library:
            try:
                if not Path(mf.path).exists():
                    logger.info(
                        f"Cleanup: Removing missing MediaFile record at '{mf.path}'"
                    )
                    session.delete(mf)
                    removed_count += 1
            except Exception:
                pass
    stats["media_files_removed"] = stats.get("media_files_removed", 0) + removed_count


def cleanup_library(library_name: str, root_directories: List[str]) -> Dict[str, int]:
    """
    Removes series/seasons/episodes or movies that are no longer present on the file system.
    Returns a dictionary with counts of deleted items.
    """

    start_time = time.time()
    stats = {
        "series": 0,
        "seasons": 0,
        "episodes": 0,
        "movies": 0,
        "media_files_removed": 0,
    }

    library_config = config.libraries.get(library_name, {})
    library_type = library_config.get("type", "tv")

    try:
        with get_session() as session:
            if library_type == "movie":
                _cleanup_movie_library(session, library_name, stats)
            else:
                _cleanup_tv_library(session, library_name, root_directories, stats)
            _cleanup_orphaned_media_files(session, root_directories, stats)

        duration = time.time() - start_time
        if library_type == "movie":
            logger.info(
                f"Cleanup for movie library '{library_name}' completed in {duration:.3f}s: "
                f"{stats['movies']} movies removed. "
                f"Removed {stats['media_files_removed']} missing MediaFile records."
            )
        else:
            logger.info(
                f"Cleanup for tv library '{library_name}' completed in {duration:.3f}s: "
                f"{stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes removed. "
                f"Removed {stats['media_files_removed']} missing MediaFile records."
            )
    except Exception:
        logger.exception(f"Error during library cleanup for '{library_name}'")
        raise

    return stats


def save_season_data(
    library_name: str,
    series_name: str,
    series_data: Dict[str, Any],
    season_name: str,
    season_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Saves or updates a single season of a series in the database.
    """
    stats: Dict[str, Any] = {
        "series": 0,
        "seasons": 0,
        "episodes": 0,
        "deleted": 0,
        "issues": [],
        "series_added": 0,
        "series_removed": 0,
        "seasons_added": 0,
        "seasons_removed": 0,
        "episodes_added": 0,
        "episodes_removed": 0,
        "movies_added": 0,
        "movies_removed": 0,
    }
    try:
        with get_session() as session:
            existing_series = {
                series_obj.name: series_obj
                for series_obj in session.scalars(
                    select(Series)
                    .where(Series.library_name == library_name)
                    .where(Series.name == series_name)
                    .options(
                        selectinload(Series.seasons)
                        .selectinload(Season.episodes)
                        .selectinload(Episode.media_files),
                        selectinload(Series.seasons)
                        .selectinload(Season.episodes)
                        .selectinload(Episode.playback_state),
                    )
                ).all()
                if series_obj.name is not None
            }
            series = _save_series_record(
                session,
                library_name,
                series_name,
                series_data,
                existing_series,
                stats,
            )

            existing_seasons = {
                season_obj.name: season_obj
                for season_obj in series.seasons
                if season_obj.name is not None
            }
            season = _save_season_record(
                session,
                series,
                season_name,
                season_data,
                existing_seasons,
                stats,
            )

            existing_by_path = {}
            existing_by_number = {}
            existing_by_name = {}
            for episode_obj in season.episodes:
                is_missing = False
                if episode_obj.path is not None:
                    try:
                        if not Path(episode_obj.path).exists():
                            is_missing = True
                    except Exception:
                        is_missing = True

                if episode_obj.path is not None and not is_missing:
                    existing_by_path[episode_obj.path] = episode_obj
                else:
                    if episode_obj.path is not None:
                        existing_by_path[episode_obj.path] = episode_obj
                    if episode_obj.tmdb_number is not None:
                        existing_by_number[episode_obj.tmdb_number] = episode_obj

                if episode_obj.name is not None:
                    existing_by_name[episode_obj.name] = episode_obj

            processed_episodes = set()
            for episode_data in season_data.get("episodes", []):
                _save_episode_record(
                    session,
                    season,
                    episode_data,
                    existing_by_path,
                    existing_by_number,
                    existing_by_name,
                    stats,
                    processed_episodes,
                )

            session.commit()
            stats["season_id"] = season.id
            logger.info(
                f"Successfully saved season '{season_name}' of series '{series_name}' to database. "
                f"Stats: {stats}"
            )
            return stats
    except Exception as e:
        logger.exception(
            f"Failed to save season '{season_name}' of series '{series_name}' to database: {e}"
        )
        raise e


def save_movie_data(
    library_name: str, movie_name: str, movie_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Saves or updates a single movie in the database.
    """
    stats: Dict[str, Any] = {
        "series": 0,
        "seasons": 0,
        "episodes": 0,
        "movies": 0,
        "deleted": 0,
        "issues": [],
        "series_added": 0,
        "series_removed": 0,
        "seasons_added": 0,
        "seasons_removed": 0,
        "episodes_added": 0,
        "episodes_removed": 0,
        "movies_added": 0,
        "movies_removed": 0,
    }
    try:
        with get_session() as session:
            existing_movie = session.scalars(
                select(Movie)
                .where(Movie.library_name == library_name)
                .where(Movie.name == movie_name)
                .options(
                    selectinload(Movie.media_files), selectinload(Movie.playback_state)
                )
            ).first()

            path = movie_data.get("path")
            movie = None
            if path:
                movie = session.scalars(
                    select(Movie)
                    .join(Movie.media_files)
                    .where(MediaFile.path == path)
                    .options(
                        selectinload(Movie.media_files),
                        selectinload(Movie.playback_state),
                    )
                ).first()

            if not movie:
                movie = existing_movie

            if not movie:
                tmdb_id = movie_data.get("tmdb_identifier")
                if tmdb_id:
                    movie = session.scalars(
                        select(Movie)
                        .where(Movie.library_name == library_name)
                        .where(Movie.tmdb_identifier == tmdb_id)
                        .options(
                            selectinload(Movie.media_files),
                            selectinload(Movie.playback_state),
                        )
                    ).first()

            if not movie:
                movie = Movie(library_name=library_name, name=movie_name)
                session.add(movie)
                stats["movies_added"] = stats.get("movies_added", 0) + 1
            else:
                if movie.name != movie_name:
                    stale_movie = existing_movie
                    if stale_movie and stale_movie is not movie:
                        logger.info(
                            f"Removing stale movie record '{movie_name}' to avoid name collision."
                        )
                        session.delete(stale_movie)
                        session.flush()
                        stats["movies_removed"] = stats.get("movies_removed", 0) + 1

                movie.library_name = library_name
                movie.name = movie_name

            stats["movies"] += 1

            versions = movie_data.get("versions")
            if versions is None and movie_data.get("path"):
                versions = [
                    {
                        "path": movie_data.get("path"),
                        "video_codec": movie_data.get("video_codec"),
                        "resolution": movie_data.get("resolution"),
                        "bit_rate": movie_data.get("bit_rate"),
                        "audio_tracks": movie_data.get("audio_tracks"),
                        "subtitle_tracks": movie_data.get("subtitle_tracks"),
                    }
                ]
            _sync_media_files(session, movie, versions)
            _apply_movie_fields(movie, movie_data)

            session.commit()
            stats["movie_id"] = movie.id
            logger.info(
                f"Successfully saved movie '{movie_name}' to database. Stats: {stats}"
            )
            return stats
    except Exception as e:
        logger.exception(f"Failed to save movie '{movie_name}' to database: {e}")
        raise e
