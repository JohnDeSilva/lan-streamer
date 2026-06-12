import logging
import re
import time
import json
from typing import Dict, Any, List, Tuple, Optional, Callable

from sqlalchemy import select, update

from lan_streamer.db.models import (
    Series,
    Season,
    Episode,
    Movie,
    AppConfig,
    AppSecret,
    SecretType,
    MediaFile,
)


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


logger = logging.getLogger(__name__)


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


def _trigger_mal_push_async(anime_id: int, num_watched_episodes: int) -> None:
    """Helper to asynchronously push watch status to MyAnimeList."""
    from lan_streamer.providers.myanimelist import myanimelist_client

    if myanimelist_client.is_configured() and myanimelist_client.is_authenticated():
        import threading

        def _run() -> None:
            try:
                myanimelist_client.update_watched_status(anime_id, num_watched_episodes)
            except Exception:
                logger.exception(
                    f"Background MyAnimeList push failed for anime {anime_id}"
                )

        threading.Thread(target=_run, daemon=True).start()


def update_episode_watched_status(path: str, watched: bool) -> None:

    try:
        logger.info(f"Updating watched status for {path} to {watched}")
        with get_session() as session:
            from lan_streamer.db.models import MediaFile

            episode = session.scalars(
                select(Episode).join(MediaFile).where(MediaFile.path == path)
            ).first()
            if episode:
                episode.watched = watched
                if watched:
                    episode.last_played_at = int(time.time())
                    if (
                        episode.myanimelist_anime_id
                        and episode.myanimelist_episode_number
                    ):
                        _trigger_mal_push_async(
                            episode.myanimelist_anime_id,
                            episode.myanimelist_episode_number,
                        )
            else:
                movie = session.scalars(
                    select(Movie).join(MediaFile).where(MediaFile.path == path)
                ).first()
                if movie:
                    movie.watched = watched
                    if watched:
                        movie.last_played_at = int(time.time())
                        if movie.myanimelist_anime_id:
                            _trigger_mal_push_async(movie.myanimelist_anime_id, 1)
    except Exception:
        logger.exception(f"Error updating watched status for {path}")


def update_episode_path(old_path: str, new_path: str) -> None:
    """Updates the file path for an episode in the database."""

    try:
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
            else:
                episode = session.scalars(
                    select(Episode).join(MediaFile).where(MediaFile.path == old_path)
                ).first()
                if episode:
                    if episode.default_path == old_path:
                        episode.default_path = new_path
    except Exception:
        logger.exception(f"Error updating episode path from {old_path} to {new_path}")


def update_episode_playback_position(path: str, position: int) -> bool:
    """Saves the last played playback offset (in seconds) for a given episode."""

    try:
        logger.debug(f"Saving playback position for '{path}' to {position}s")
        with get_session() as session:
            from lan_streamer.db.models import MediaFile

            episode = session.scalars(
                select(Episode).join(MediaFile).where(MediaFile.path == path)
            ).first()
            if episode:
                episode.last_played_position = position
                episode.last_played_at = int(time.time())
                return True
            movie = session.scalars(
                select(Movie).join(MediaFile).where(MediaFile.path == path)
            ).first()
            if movie:
                movie.last_played_position = position
                movie.last_played_at = int(time.time())
                return True
    except Exception:
        logger.exception(f"Error updating playback position for {path}")
    return False


def get_episode_playback_position(path: str) -> int:
    """Retrieves the stored last played playback offset (in seconds) for a given episode."""

    try:
        logger.debug(f"Retrieving playback position for '{path}'")
        with get_session() as session:
            from lan_streamer.db.models import MediaFile

            episode = session.scalars(
                select(Episode).join(MediaFile).where(MediaFile.path == path)
            ).first()
            if episode and episode.last_played_position:
                logger.debug(
                    f"Playback position for episode '{path}' is {episode.last_played_position}s"
                )
                return int(episode.last_played_position)
            movie = session.scalars(
                select(Movie).join(MediaFile).where(MediaFile.path == path)
            ).first()
            if movie and movie.last_played_position:
                logger.debug(
                    f"Playback position for movie '{path}' is {movie.last_played_position}s"
                )
                return int(movie.last_played_position)
    except Exception:
        logger.exception(f"Error retrieving playback position for {path}")
    return 0


def is_movie(path: str) -> bool:
    """Returns True if the given path corresponds to a movie in the database."""
    try:
        with get_session() as session:
            from lan_streamer.db.models import MediaFile

            movie = session.scalars(
                select(Movie).join(MediaFile).where(MediaFile.path == path)
            ).first()
            return movie is not None
    except Exception:
        logger.exception(f"Error checking if path is movie: {path}")
        return False


def update_season_watched_status(
    library_name: str, series_name: str, season_name: str, watched: bool
) -> None:
    """
    Bulk updates the watched status for all episodes in a specific season.
    """

    try:
        logger.info(
            f"Updating watched status for {series_name} - {season_name} in {library_name} to {watched}"
        )
        with get_session() as session:
            season = session.scalars(
                select(Season)
                .join(Series)
                .where(
                    Series.library_name == library_name,
                    Series.name == series_name,
                    Season.name == season_name,
                )
            ).first()
            if season:
                session.execute(
                    update(Episode)
                    .where(Episode.season_id == season.id)
                    .values(watched=watched)
                )
                if watched:
                    mal_updates = {}
                    for ep in season.episodes:
                        if ep.myanimelist_anime_id and ep.myanimelist_episode_number:
                            mal_updates[ep.myanimelist_anime_id] = max(
                                mal_updates.get(ep.myanimelist_anime_id, 0),
                                ep.myanimelist_episode_number,
                            )
                    for anime_id, max_ep in mal_updates.items():
                        _trigger_mal_push_async(anime_id, max_ep)
    except Exception:
        logger.exception(
            f"Error updating watched status for {series_name} - {season_name}"
        )


def update_series_watched_status(
    library_name: str, series_name: str, watched: bool
) -> None:
    """
    Bulk updates the watched status for all episodes in an entire series.
    """

    try:
        logger.info(
            f"Updating watched status for entire series {series_name} in {library_name} to {watched}"
        )
        with get_session() as session:
            series = session.scalars(
                select(Series).where(
                    Series.library_name == library_name, Series.name == series_name
                )
            ).first()
            if series:
                mal_updates = {}
                for season in series.seasons:
                    for episode in season.episodes:
                        episode.watched = watched
                        if (
                            watched
                            and episode.myanimelist_anime_id
                            and episode.myanimelist_episode_number
                        ):
                            mal_updates[episode.myanimelist_anime_id] = max(
                                mal_updates.get(episode.myanimelist_anime_id, 0),
                                episode.myanimelist_episode_number,
                            )
                for anime_id, max_ep in mal_updates.items():
                    _trigger_mal_push_async(anime_id, max_ep)
    except Exception:
        logger.exception(f"Error updating watched status for series {series_name}")


def get_items_missing_runtime() -> List[Dict[str, Any]]:
    """Retrieves all episodes and movies whose runtime is 0/missing or whose technical metadata (codec, bit rate, resolution) is missing."""

    items_list: List[Dict[str, Any]] = []
    try:
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
                        {"id": episode.id, "path": episode.path, "type": "episode"}
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
    except Exception:
        logger.exception(
            f"Error updating runtime and technical info for {item_type} ID {item_identifier!r}"
        )


def get_next_episode(current_path: str) -> Optional[Dict[str, Any]]:
    """
    Finds the next episode in the same series for a given episode path.
    Sorts seasons and episodes naturally by name.
    """

    try:
        logger.debug(f"Determining next episode after: '{current_path}'")
        with get_session() as session:
            from lan_streamer.db.models import MediaFile

            current_episode: Optional[Episode] = session.scalars(
                select(Episode).join(MediaFile).where(MediaFile.path == current_path)
            ).first()
            if (
                not current_episode
                or not current_episode.season
                or not current_episode.season.series
            ):
                logger.debug(
                    "Current episode, season, or series not found in database."
                )
                return None

            series: Series = current_episode.season.series

            # Get all seasons of the series, sorted naturally by name
            seasons: List[Season] = sorted(
                series.seasons, key=lambda s: natural_sort_key(s.name)
            )

            # Construct flat list of all episodes in series in natural order
            ordered_episodes: List[Tuple[Episode, Season, int]] = []
            for season in seasons:
                # Sort episodes in this season naturally by name, excluding missing/future episodes (path is None or empty)
                valid_episodes = [e for e in season.episodes if e.path]
                season_episodes: List[Episode] = sorted(
                    valid_episodes, key=lambda e: natural_sort_key(e.name)
                )
                for index, episode in enumerate(season_episodes):
                    ordered_episodes.append((episode, season, index + 1))

            # Find current episode index in the ordered list
            current_index: int = -1
            for index, (episode, _, _) in enumerate(ordered_episodes):
                if episode.id == current_episode.id:
                    current_index = index
                    break

            if current_index == -1:
                logger.debug("Current episode index could not be determined.")
                return None

            if current_index == len(ordered_episodes) - 1:
                logger.info("Current episode is the last episode in the series.")
                return None

            # Retrieve next episode and its season / calculated episode number
            next_episode, next_season, calculated_episode_number = ordered_episodes[
                current_index + 1
            ]

            if not next_episode.path:
                logger.info("Next episode has no file path (placeholder).")
                return None

            result = {
                "title": next_episode.tmdb_name
                if next_episode.tmdb_name
                else (next_episode.name or "Unknown"),
                "season": next_season.name or "Unknown",
                "episode_number": next_episode.tmdb_number
                if next_episode.tmdb_number is not None
                else calculated_episode_number,
                "path": next_episode.path,
                "poster_path": series.poster_path if series.poster_path else "",
                "runtime": next_episode.runtime or 0,
            }
            logger.info(
                f"Resolved next episode: '{result['title']}' (S: '{result['season']}', E: {result['episode_number']}) at path '{result['path']}'"
            )
            return result
    except Exception:
        logger.exception(f"Error getting next episode for path {current_path}")
    return None


def get_combined_next_up(library_names: List[str]) -> List[Dict[str, Any]]:
    """
    For partially watched series (having at least one watched episode or playback position),
    returns the next unplayed season in the series.
    Ordered by the max(last_played_at) of any episode in the series (most recently played first).
    """

    try:
        logger.info(
            f"get_combined_next_up: fetching next up items for libraries={library_names}"
        )
        with get_session() as session:
            from lan_streamer.db.models import MediaFile

            # Find series that have any episode where watched is True or last_played_at > 0, and the episode has a file path (not missing/future)
            series_stmt = (
                select(Series)
                .join(Season)
                .join(Episode)
                .join(MediaFile)
                .where(
                    (MediaFile.path.isnot(None))
                    & (MediaFile.path != "")
                    & ((Episode.watched.is_(True)) | (Episode.last_played_at > 0))
                )
            )
            if library_names:
                series_stmt = series_stmt.where(Series.library_name.in_(library_names))
            series_list = session.scalars(series_stmt.distinct()).all()

            results = []
            for series in series_list:
                # Get all seasons of this series
                seasons = sorted(
                    series.seasons, key=lambda s: natural_sort_key(s.name or "")
                )
                next_season = None

                # Find the first season that is not fully watched
                for season in seasons:
                    # Do not consider missing or future episodes (those with no path)
                    episodes = [ep for ep in season.episodes if ep.path]
                    if not episodes:
                        continue
                    # Check if all episodes in this season are watched
                    fully_watched = all(ep.watched for ep in episodes)
                    if not fully_watched:
                        next_season = season
                        break

                if next_season:
                    # Find max last_played_at, date_added, and air_date across all episodes in the series that have a path
                    max_lp = 0
                    max_date_added = 0
                    max_air_date = ""
                    for s in series.seasons:
                        for ep in s.episodes:
                            if not ep.path:
                                continue
                            val = ep.last_played_at or 0
                            if val > max_lp:
                                max_lp = val
                            added_val = ep.date_added or 0
                            if added_val > max_date_added:
                                max_date_added = added_val
                            air_val = ep.air_date or ""
                            if air_val > max_air_date:
                                max_air_date = air_val

                    season_episodes = [ep for ep in next_season.episodes if ep.path]
                    watched_count = sum(1 for ep in season_episodes if ep.watched)
                    total_count = len(season_episodes)

                    results.append(
                        {
                            "type": "season",
                            "series_name": series.name,
                            "season_name": next_season.name,
                            "poster_path": next_season.poster_path
                            or series.poster_path,
                            "library_name": series.library_name,
                            "last_played_at": max_lp,
                            "date_added": max_date_added,
                            "air_date": max_air_date or series.first_air_date or "",
                            "watched_count": watched_count,
                            "total_count": total_count,
                        }
                    )

            # Sort by last_played_at descending
            results.sort(key=lambda x: int(x["last_played_at"] or 0), reverse=True)
            logger.info(f"get_combined_next_up: returning {len(results)} seasons")
            return results
    except Exception:
        logger.exception("Error in get_combined_next_up")
        return []


def get_combined_recently_added(library_names: List[str]) -> List[Dict[str, Any]]:
    """
    Returns series and movies sorted by their date_added (max episode date_added for series, movie date_added for movies).
    """
    logger.debug(f"get_combined_recently_added called with libraries={library_names}")
    return get_combined_smart_row(library_names, "Recently Added", "All")


def get_combined_smart_row(
    library_names: List[str], sort_by: str, filter_mode: str
) -> List[Dict[str, Any]]:
    """
    Returns filtered and sorted series and movies across the specified libraries.
    """

    try:
        logger.info(
            f"get_combined_smart_row processing request: libraries={library_names}, "
            f"sort_by='{sort_by}', filter_mode='{filter_mode}'"
        )
        if sort_by == "Next Up":
            results = get_combined_next_up(library_names)
            logger.info(
                f"get_combined_smart_row (Next Up) returned {len(results)} items"
            )
            return results

        with get_session() as session:
            results = []

            # 1. Fetch Series
            series_stmt = select(Series)
            if library_names:
                series_stmt = series_stmt.where(Series.library_name.in_(library_names))
            series_list = session.scalars(series_stmt).all()

            for series in series_list:
                total_episodes = 0
                watched_episodes = 0
                max_date_added = 0
                max_air_date = ""

                for season in series.seasons:
                    for ep in season.episodes:
                        if ep.path is None:
                            continue
                        total_episodes += 1
                        if ep.watched:
                            watched_episodes += 1
                        val = ep.date_added or 0
                        if val > max_date_added:
                            max_date_added = val
                        air_val = ep.air_date or ""
                        if air_val > max_air_date:
                            max_air_date = air_val

                if total_episodes == 0:
                    continue

                # Check filter
                keep = True
                if filter_mode == "Watched":
                    keep = (
                        (watched_episodes == total_episodes)
                        if total_episodes > 0
                        else False
                    )
                elif filter_mode == "Unwatched":
                    keep = watched_episodes < total_episodes

                if keep:
                    results.append(
                        {
                            "type": "series",
                            "name": series.name,
                            "poster_path": series.poster_path,
                            "library_name": series.library_name,
                            "date_added": max_date_added,
                            "air_date": max_air_date or series.first_air_date or "",
                            "watched_count": watched_episodes,
                            "total_count": total_episodes,
                        }
                    )

            # 2. Fetch Movies
            movie_stmt = select(Movie)
            if library_names:
                movie_stmt = movie_stmt.where(Movie.library_name.in_(library_names))
            movies = session.scalars(movie_stmt).all()

            for movie in movies:
                keep = True
                if filter_mode == "Watched":
                    keep = bool(movie.watched)
                elif filter_mode == "Unwatched":
                    keep = not bool(movie.watched)

                if keep:
                    results.append(
                        {
                            "type": "movie",
                            "name": movie.name,
                            "poster_path": movie.poster_path,
                            "library_name": movie.library_name,
                            "date_added": movie.date_added or 0,
                            "air_date": str(movie.year or ""),
                            "watched_count": 1 if movie.watched else 0,
                            "total_count": 1,
                        }
                    )

            # Apply sorting
            if sort_by == "Alphabetical":
                results.sort(key=lambda x: str(x["name"] or "").lower())
            elif sort_by == "Recently Added":
                results.sort(key=lambda x: int(x["date_added"] or 0), reverse=True)
            elif sort_by == "Recently Aired":
                results.sort(key=lambda x: str(x["air_date"] or ""), reverse=True)
            else:
                # Default fallback
                results.sort(key=lambda x: str(x["name"] or "").lower())

            logger.info(
                f"get_combined_smart_row: returning {len(results)} items (type counts: "
                f"Series={len([r for r in results if r['type'] == 'series'])} "
                f"Movies={len([r for r in results if r['type'] == 'movie'])})"
            )
            return results
    except Exception:
        logger.exception("Error in get_combined_smart_row")
        return []


def delete_series_record(library_name: str, series_name: str) -> None:
    """Deletes a series record from the database."""
    try:
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
    except Exception:
        logger.exception(f"Error deleting series '{series_name}'")


def delete_episode_record(path: str) -> None:
    """Deletes an episode record from the database."""
    try:
        logger.info(f"Deleting episode record for path: {path}")
        with get_session() as session:
            from lan_streamer.db.models import MediaFile

            episode = session.scalars(
                select(Episode).join(MediaFile).where(MediaFile.path == path)
            ).first()
            if episode:
                session.delete(episode)
    except Exception:
        logger.exception(f"Error deleting episode record for '{path}'")


# ---------------------------------------------------------------------------
# app_config helpers
# ---------------------------------------------------------------------------

_TYPE_COERCIONS: Dict[str, Callable[[Any], Any]] = {
    "bool": lambda v: v == "1",
    "int": int,
    "float": float,
    "json": json.loads,
    "str": str,
}


def get_app_config(key: str, default: Any = None) -> Any:
    """Returns the stored value for *key* from app_config, coerced to its declared type.

    Returns *default* when the key does not exist.  When the key is absent and
    *default* is not ``None`` the default is automatically persisted to the
    database so that the row exists on subsequent reads (i.e. missing rows are
    seeded on first access).
    """
    try:
        with get_session() as session:
            row = session.scalars(
                select(AppConfig).where(AppConfig.key == key)
            ).one_or_none()
            if row is None or row.value is None:
                logger.debug(
                    f"No value stored for app_config key '{key}' — returning default value"
                )
                # Seed the default into the DB so the key exists going forward.
                if default is not None:
                    # Use a deferred import to avoid circular references; this
                    # module already defines set_app_config below.
                    set_app_config(key, default)
                return default
            coerce = _TYPE_COERCIONS.get(row.type or "str", str)
            return coerce(row.value)
    except Exception:
        logger.warning(
            f"Error reading app_config key '{key}' — returning default value"
        )
        return default


def set_app_config(key: str, value: Any) -> None:
    """Upserts *value* for *key* in app_config.

    The type hint is inferred from the current Python type of *value* when
    no row exists yet; existing rows keep their declared type on update.
    """
    try:
        with get_session() as session:
            row = session.scalars(
                select(AppConfig).where(AppConfig.key == key)
            ).one_or_none()

            if row is None:
                # Infer type hint from value
                if isinstance(value, bool):
                    type_hint = "bool"
                elif isinstance(value, int):
                    type_hint = "int"
                elif isinstance(value, float):
                    type_hint = "float"
                elif isinstance(value, (list, dict)):
                    type_hint = "json"
                else:
                    type_hint = "str"
                row = AppConfig(key=key, type=type_hint)
                session.add(row)

            # Serialise to TEXT
            hint = row.type or "str"
            if hint == "json":
                row.value = json.dumps(value)
            elif hint == "bool":
                row.value = "1" if value else "0"
            else:
                row.value = str(value)
    except Exception:
        logger.exception(f"Error writing app_config key '{key}'")


def get_all_app_configs() -> Dict[str, Any]:
    """Returns all app_config rows as a dictionary of key -> coerced_value."""
    try:
        with get_session() as session:
            rows = session.scalars(select(AppConfig)).all()
            config_dict = {}
            for row in rows:
                logger.info(
                    f"Reading app_config row: key='{row.key}', type='{row.type}', value='{row.value}'"
                )
                if row.value is not None:
                    coerce = _TYPE_COERCIONS.get(row.type or "str", str)
                    config_dict[row.key] = coerce(row.value)
            return config_dict
    except Exception:
        logger.warning("Error reading all app_config rows")
        return {}


def bulk_set_app_configs(config_dict: Dict[str, Any]) -> None:
    """Upserts all key/value pairs in config_dict into app_config in a single session."""
    try:
        with get_session() as session:
            rows = session.scalars(select(AppConfig)).all()
            existing_map = {row.key: row for row in rows}

            for key, value in config_dict.items():
                row = existing_map.get(key)
                if row is None:
                    # Infer type hint from value
                    if isinstance(value, bool):
                        type_hint = "bool"
                    elif isinstance(value, int):
                        type_hint = "int"
                    elif isinstance(value, float):
                        type_hint = "float"
                    elif isinstance(value, (list, dict)):
                        type_hint = "json"
                    else:
                        type_hint = "str"
                    row = AppConfig(key=key, type=type_hint)
                    session.add(row)

                # Serialise to TEXT
                hint = row.type or "str"
                if hint == "json":
                    row.value = json.dumps(value)
                elif hint == "bool":
                    row.value = "1" if value else "0"
                else:
                    row.value = str(value)
            logging.info(f"Bulk upserted {len(config_dict)} app_config settings")
    except Exception:
        logger.exception("Error writing bulk app_config settings")


# ---------------------------------------------------------------------------
# app_secrets helpers
# ---------------------------------------------------------------------------


def get_secret(secret_type: SecretType) -> Dict[str, Any]:
    """Returns the credential payload dict for *secret_type*.

    Returns an empty dict when no row exists so callers can safely use
    ``.get()`` without checking for ``None``.
    """
    try:
        with get_session() as session:
            row = session.scalars(
                select(AppSecret).where(AppSecret.secret_type == secret_type.value)
            ).one_or_none()
            if row is None or not row.secret:
                logger.debug(
                    f"No secret stored for type '{secret_type}' — returning empty dict"
                )
                return {}
            return json.loads(row.secret)
    except Exception:
        logger.warning(
            f"Error reading secret for type '{secret_type}' — returning empty dict"
        )
        return {}


def get_all_secrets() -> Dict[str, Dict[str, Any]]:
    """Returns all app_secrets rows as a dictionary of secret_type string -> payload dict."""
    try:
        with get_session() as session:
            rows = session.scalars(select(AppSecret)).all()
            secrets_dict = {}
            for row in rows:
                if row.secret:
                    try:
                        secrets_dict[row.secret_type] = json.loads(row.secret)
                    except Exception:
                        logger.warning(
                            f"Error parsing secret for type '{row.secret_type}'"
                        )
            return secrets_dict
    except Exception:
        logger.warning("Error reading all secrets from database")
        return {}


def set_secret(secret_type: SecretType, payload: Dict[str, Any]) -> None:
    """Upserts the full credential payload for *secret_type*.

    On first insert a UUID4 primary key is generated automatically via the
    column default (stored as a 16-byte BLOB).
    """
    try:
        with get_session() as session:
            row = session.scalars(
                select(AppSecret).where(AppSecret.secret_type == secret_type.value)
            ).first()
            if row is None:
                row = AppSecret(secret_type=secret_type.value)
                session.add(row)
            row.secret = json.dumps(payload)
    except Exception:
        logger.exception(f"Error writing secret for type '{secret_type}'")


# ---------------------------------------------------------------------------
# Series preference helpers
# ---------------------------------------------------------------------------

_SERIES_PREF_COLUMNS = {
    "hide_missing_future": "pref_hide_missing_future",
    "display_group_id": "pref_display_group_id",
}


def get_series_pref(
    library_name: str, series_name: str, key: str, default: Any = None
) -> Any:
    """Returns the per-series preference *key* for the given series.

    Falls back to *default* when the series row or the column value is missing.
    """
    col = _SERIES_PREF_COLUMNS.get(key)
    if col is None:
        logger.warning(f"Unknown series preference key: '{key}'")
        return default
    try:
        with get_session() as session:
            series = session.scalars(
                select(Series).where(
                    Series.library_name == library_name,
                    Series.name == series_name,
                )
            ).first()
            if series is None:
                return default
            value = getattr(series, col, None)
            return default if value is None else value
    except Exception:
        logger.exception(
            f"Error reading series pref '{key}' for '{library_name}:{series_name}'"
        )
        return default


def set_series_pref(library_name: str, series_name: str, key: str, value: Any) -> None:
    """Persists the per-series preference *key* = *value* for the given series."""
    col = _SERIES_PREF_COLUMNS.get(key)
    if col is None:
        logger.warning(f"Unknown series preference key: '{key}'")
        return
    try:
        with get_session() as session:
            series = session.scalars(
                select(Series).where(
                    Series.library_name == library_name,
                    Series.name == series_name,
                )
            ).first()
            if series is None:
                logger.warning(
                    f"set_series_pref: series '{library_name}:{series_name}' not found"
                )
                return
            setattr(series, col, value)
    except Exception:
        logger.exception(
            f"Error writing series pref '{key}' for '{library_name}:{series_name}'"
        )
