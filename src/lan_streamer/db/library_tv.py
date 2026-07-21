"""
TV library persistence functions — load, save, and cleanup of Series/Season/Episode records.
"""

import logging
import re
import time
from pathlib import Path
from typing import Dict, Any, List

from sqlalchemy import select, inspect
from sqlalchemy.orm import Session, selectinload

from lan_streamer.db.models import Series, Season, Episode
from lan_streamer.db.library_shared import (
    get_session,
    _update_field_safely,
    _sync_media_files,
)

logger = logging.getLogger(__name__)

_COUNTER_SUFFIX_RE = re.compile(r" \(\d+\)$")


def _strip_counter_suffix(name: str) -> str:
    """Strips a trailing counter suffix like `` (1)`` from *name*.

    The database appends ``(1)``, ``(2)`` etc. to avoid UNIQUE constraint
    violations when multiple episodes share the same TMDB name.  This
    helper recovers the base name so that name-based matching can find
    suffixed records.
    """
    return _COUNTER_SUFFIX_RE.sub("", name)


def load_library(library_name: str) -> Dict[str, Any]:
    """
    Loads the library from the database and constructs a nested dictionary structure.
    """
    from lan_streamer.db.orm_serialization import _build_series_dict

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
    is_new = False
    if not series:
        series = Series(library_name=library_name, name=series_name)
        session.add(series)
        stats["series_added"] = stats.get("series_added", 0) + 1
        logger.info(
            f"New series record created: '{series_name}' in library '{library_name}'"
        )
        is_new = True
    stats["series"] += 1
    stats["series_scanned"] = stats.get("series_scanned", 0) + 1

    series_metadata = series_data.get("metadata", {})
    changed = False

    for attr, key in [
        ("jellyfin_id", "jellyfin_id"),
        ("tmdb_identifier", "tmdb_identifier"),
        ("poster_path", "poster_path"),
        ("overview", "overview"),
        ("tmdb_name", "tmdb_name"),
        ("first_air_date", "first_air_date"),
        ("tmdb_episode_group_id", "tmdb_episode_group_id"),
    ]:
        val = series_metadata.get(key)
        if val is not None and getattr(series, attr) != val:
            setattr(series, attr, val)
            changed = True

    if "locked_metadata" in series_metadata:
        val = bool(series_metadata["locked_metadata"])
        if series.locked_metadata != val:
            series.locked_metadata = val
            changed = True

    if not is_new and changed:
        stats["series_updated"] = stats.get("series_updated", 0) + 1

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
    is_new = False
    if not season:
        season = Season(name=season_name, series=series)
        session.add(season)
        stats["seasons_added"] = stats.get("seasons_added", 0) + 1
        logger.info(
            f"New season record created: '{season_name}' for series '{series.name}'"
        )
        is_new = True
    stats["seasons"] += 1
    stats["seasons_scanned"] = stats.get("seasons_scanned", 0) + 1

    season_metadata = season_data.get("metadata", {})
    changed = False

    for attr, key in [
        ("jellyfin_id", "jellyfin_id"),
        ("poster_path", "poster_path"),
    ]:
        val = season_metadata.get(key)
        if val is not None and getattr(season, attr) != val:
            setattr(season, attr, val)
            changed = True

    if "myanimelist_id" in season_metadata:
        val = season_metadata["myanimelist_id"]
        if season.myanimelist_id != val:
            season.myanimelist_id = val
            changed = True

    if not is_new and changed:
        stats["seasons_updated"] = stats.get("seasons_updated", 0) + 1

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
    incoming_paths_in_season: set[str] | None = None,
) -> Episode:
    path = episode_data.get("path")
    tmdb_num = episode_data.get("tmdb_number")
    name = episode_data.get("name")

    is_new_file = False
    if path and path not in existing_by_path:
        is_new_file = True

    if path and processed_episodes:
        for processed_ep in processed_episodes:
            if (
                episode_data.get("tmdb_number") is not None
                and processed_ep.tmdb_number is not None
                and episode_data.get("tmdb_number") != processed_ep.tmdb_number
            ):
                continue
            if processed_ep.media_files:
                for mf in processed_ep.media_files:
                    if mf.path == path:
                        logger.info(
                            f"Skipping duplicate episode record save for path '{path}' "
                            f"as it is already mapped as a version to episode '{processed_ep.name}'."
                        )
                        return processed_ep

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
                for mf in list(episode.media_files):
                    if mf.path == path:
                        episode.media_files.remove(mf)
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
                if episode.path:
                    # Episode already has a path (another version) — merge existing
                    # MediaFiles into episode_data so _sync_media_files preserves them.
                    versions_val = episode_data.get("versions")
                    if versions_val is None:
                        new_versions = [
                            {
                                "path": episode_data.get("path"),
                                "video_codec": episode_data.get("video_codec"),
                                "resolution": episode_data.get("resolution"),
                                "bit_rate": episode_data.get("bit_rate"),
                                "audio_tracks": episode_data.get("audio_tracks"),
                                "subtitle_tracks": episode_data.get("subtitle_tracks"),
                            }
                        ]
                    else:
                        new_versions = list(versions_val)
                    incoming_paths = {
                        v.get("path") for v in new_versions if v.get("path")
                    }
                    for media_file in list(episode.media_files):
                        if (
                            media_file.path
                            and media_file.path not in incoming_paths
                            and Path(media_file.path).exists()
                            and (
                                incoming_paths_in_season is None
                                or media_file.path not in incoming_paths_in_season
                            )
                        ):
                            new_versions.append({"path": media_file.path})
                    episode_data["versions"] = new_versions
                    logger.info(
                        f"Linking additional file '{path}' to existing episode S{season.name} E{tmdb_num}"
                    )
                else:
                    # Promote placeholder to local file
                    logger.info(
                        f"Promoting placeholder episode S{season.name} E{tmdb_num} to local path {path}"
                    )
                    episode.path = path
                old_path = episode.path
                if old_path and old_path in existing_by_path:
                    existing_by_path.pop(old_path, None)
    elif tmdb_num is not None:
        episode = existing_by_number.get(tmdb_num)

    # Fallback to name-based matching if still not found, to avoid UNIQUE constraint violation on name.
    # The database appends counter suffixes like "TBA (1)" when multiple episodes
    # share the same name, so we also try matching suffixed variants.
    if not episode and name:
        episode = existing_by_name.get(name)
        if episode:
            logger.debug(
                f"Matched existing episode by name fallback: S{season.name} '{name}'"
            )
        else:
            # Try suffixed variants: "TBA (1)", "TBA (2)", etc.
            # This handles the case where the exact name was already consumed
            # by a previous episode and the DB stored it with a counter suffix.
            candidate_keys = [
                k
                for k in existing_by_name
                if _strip_counter_suffix(k) == name and k != name
            ]
            if candidate_keys:
                episode = existing_by_name[candidate_keys[0]]
                logger.debug(
                    f"Matched existing episode by suffixed name fallback: "
                    f"S{season.name} '{name}' -> '{episode.name}'"
                )
        if episode:
            old_path = episode.path
            if path and not episode.path:
                episode.path = path
            if tmdb_num is not None and episode.tmdb_number is None:
                episode.tmdb_number = tmdb_num
            if old_path and old_path != episode.path and old_path in existing_by_path:
                existing_by_path.pop(old_path, None)

    # Cross-root dedup: match by tmdb_episode_identifier when the same episode
    # exists in a different root directory with a different path.
    tmdb_ep_id = episode_data.get("tmdb_episode_identifier")
    if not episode and tmdb_ep_id:
        for existing_ep in season.episodes:
            if (
                existing_ep.tmdb_episode_identifier == tmdb_ep_id
                and existing_ep is not episode
            ):
                logger.info(
                    f"Cross-root dedup: merging '{path}' into existing episode "
                    f"'{existing_ep.name}' (tmdb_episode_identifier={tmdb_ep_id})"
                )
                episode = existing_ep
                old_path = episode.path
                if path and not episode.path:
                    episode.path = path
                if (
                    old_path
                    and old_path != episode.path
                    and old_path in existing_by_path
                ):
                    existing_by_path.pop(old_path, None)
                break

    is_new = False
    if not episode:
        episode = Episode(path=path, season=season)
        session.add(episode)
        stats["episodes_added"] = stats.get("episodes_added", 0) + 1
        is_new = True
    else:
        # Remove from tracking dicts so it's not reused/considered stale
        if episode.path in existing_by_path:
            existing_by_path.pop(episode.path, None)
        for mf in episode.media_files:
            if mf.path in existing_by_path:
                existing_by_path.pop(mf.path, None)
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

                    # Capture path before deleting — accessing ORM attrs after flush is unsafe.
                    dup_path = dup_ep.default_path or (
                        dup_ep.media_files[0].path if dup_ep.media_files else None
                    )
                    # Delete duplicate from session and remove from tracking dicts
                    session.delete(dup_ep)
                    session.flush()
                    stats["deleted"] += 1
                    stats["episodes_removed"] += 1

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
        stats["issues"].append(
            {
                "type": "Name Conflict Resolution",
                "item": f"Episode '{base_name}' (Season: '{season.name}')",
                "error": msg,
            }
        )
    # Check for changes if not a new episode record
    changed = False
    if not is_new:
        if episode.name != target_name:
            changed = True
        for attr, key in [
            ("jellyfin_id", "jellyfin_id"),
            ("tmdb_episode_identifier", "tmdb_episode_identifier"),
            ("tmdb_name", "tmdb_name"),
            ("air_date", "air_date"),
        ]:
            val = episode_data.get(key)
            if val and getattr(episode, attr) != val:
                changed = True
        if (
            episode_data.get("tmdb_number") is not None
            and episode.tmdb_number != episode_data["tmdb_number"]
        ):
            changed = True
        val_date = episode_data.get("date_added")
        if val_date and episode.date_added != int(val_date):
            changed = True
        val_runtime = episode_data.get("runtime")
        if val_runtime and episode.runtime != val_runtime:
            changed = True
        if (
            "myanimelist_anime_id" in episode_data
            and episode.myanimelist_anime_id != episode_data["myanimelist_anime_id"]
        ):
            changed = True
        if (
            "myanimelist_episode_number" in episode_data
            and episode.myanimelist_episode_number
            != episode_data["myanimelist_episode_number"]
        ):
            changed = True
        new_path = episode_data.get("default_path") or episode_data.get("path")
        if new_path is not None and episode.default_path != new_path:
            changed = True
        if is_new_file:
            changed = True
        watched = bool(episode_data.get("watched"))
        if watched and not episode.watched:
            changed = True

    episode.name = target_name
    episode.jellyfin_id = episode_data.get("jellyfin_id") or episode.jellyfin_id
    episode.tmdb_episode_identifier = (
        episode_data.get("tmdb_episode_identifier") or episode.tmdb_episode_identifier
    )
    episode.tmdb_name = episode_data.get("tmdb_name") or episode.tmdb_name
    if episode_data.get("tmdb_number") is not None:
        episode.tmdb_number = episode_data["tmdb_number"]
    raw_date_added = episode_data.get("date_added")
    episode.date_added = (
        int(raw_date_added) if raw_date_added is not None else episode.date_added or 0
    )
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

    if is_new_file:
        episode.watched = False
    watched = bool(episode_data.get("watched"))
    if watched:
        episode.watched = True
    if processed_episodes is not None:
        processed_episodes.add(episode)

    if not is_new and changed:
        stats["episodes_updated"] = stats.get("episodes_updated", 0) + 1

    stats["episodes_scanned"] = stats.get("episodes_scanned", 0) + 1
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
        "series_scanned": 0,
        "series_updated": 0,
        "seasons_scanned": 0,
        "seasons_updated": 0,
        "episodes_scanned": 0,
        "episodes_updated": 0,
    }

    try:
        from lan_streamer.db.models import ScannedDirectory

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
                        if episode_obj.path is not None:
                            existing_by_path[episode_obj.path] = episode_obj
                        for mf in episode_obj.media_files:
                            if mf.path:
                                existing_by_path[mf.path] = episode_obj

                        if episode_obj.tmdb_number is not None:
                            existing_by_number[episode_obj.tmdb_number] = episode_obj

                        if episode_obj.name is not None:
                            existing_by_name[episode_obj.name] = episode_obj

                    incoming_paths_in_season = set()
                    for ep_data in season_data.get("episodes", []):
                        p = ep_data.get("path")
                        if p:
                            incoming_paths_in_season.add(p)
                        for v in ep_data.get("versions", []):
                            if v.get("path"):
                                incoming_paths_in_season.add(v.get("path"))

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
                            incoming_paths_in_season=incoming_paths_in_season,
                        )

                    # Delete stale episode records (not present in incoming data).
                    # These are old episodes from a previously matched series that
                    # do not correspond to any episode in the newly matched TMDB structure.
                    stale_episodes = (
                        set(existing_by_path.values())
                        | set(existing_by_number.values())
                        | set(existing_by_name.values())
                    ) - processed_episodes

                    for ep_obj in stale_episodes:
                        logger.info(
                            f"Removing stale episode S{season.name} "
                            f"E{ep_obj.tmdb_number or '?'} ('{ep_obj.name}') from database"
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
                        stats["episodes_removed"] += 1

            # Persist directory mtimes for series and seasons
            for series_name, series_data in library.items():
                series_metadata = series_data.get("metadata", {})
                series_dir = series_metadata.get("series_directory_path")
                series_mtime = series_metadata.get("last_scanned_mtime")
                if series_dir and series_mtime is not None:
                    record = session.scalars(
                        select(ScannedDirectory).where(
                            ScannedDirectory.path == series_dir
                        )
                    ).first()
                    if record:
                        record.last_scanned_mtime = series_mtime
                    else:
                        session.add(
                            ScannedDirectory(
                                path=series_dir, last_scanned_mtime=series_mtime
                            )
                        )
                for season_name, season_data in series_data.get("seasons", {}).items():
                    season_metadata = season_data.get("metadata", {})
                    season_dir = season_metadata.get("season_directory_path")
                    season_mtime = season_metadata.get("last_scanned_mtime")
                    if season_dir and season_mtime is not None:
                        record = session.scalars(
                            select(ScannedDirectory).where(
                                ScannedDirectory.path == season_dir
                            )
                        ).first()
                        if record:
                            record.last_scanned_mtime = season_mtime
                        else:
                            session.add(
                                ScannedDirectory(
                                    path=season_dir,
                                    last_scanned_mtime=season_mtime,
                                )
                            )

            session.flush()

    except Exception as e:
        logger.exception(f"Error saving library '{library_name}' to database")
        stats["issues"].append(
            {
                "type": "Database Write Failure",
                "item": f"Library '{library_name}'",
                "error": str(e),
            }
        )
        raise

    duration = time.time() - start_time
    logger.info(
        f"Library '{library_name}' updated in {duration:.3f}s: "
        f"{stats['series']} series, {stats['seasons']} seasons, {stats['episodes']} episodes saved. "
        f"{stats['deleted']} stale items removed."
    )
    return stats


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
                default_path = episode.default_path or (
                    episode.media_files[0].path if episode.media_files else None
                )

                # Remove unmatched episodes (no media files, no TMDB metadata)
                if episode.media_files == [] and episode.tmdb_number is None:
                    logger.info(
                        f"Cleanup: Removing unmatched episode "
                        f"S{season.name} E{episode.name} "
                        f"('{episode.name}') at '{default_path}'"
                    )
                    session.delete(episode)
                    stats["episodes_removed"] = stats.get("episodes_removed", 0) + 1
                    continue

                # Remove stale MediaFile records whose files no longer exist on disk.
                stale_mfs = [
                    mf
                    for mf in list(episode.media_files)
                    if mf.path and not Path(mf.path).exists()
                ]
                for stale_mf in stale_mfs:
                    logger.info(
                        "Cleanup: Removing stale MediaFile '%s' for episode '%s'.",
                        stale_mf.path,
                        episode.name,
                    )
                    has_other_refs = any(
                        ep != episode for ep in stale_mf.episodes
                    ) or any(mv != episode for mv in stale_mf.movies)
                    episode.media_files.remove(stale_mf)
                    if not has_other_refs and stale_mf in session:
                        session.delete(stale_mf)
                        stats["episodes_removed"] = stats.get("episodes_removed", 0) + 1

                changed = bool(stale_mfs)

                if stale_mfs:
                    session.flush()

                # Update default_path if it points to a missing file.
                if default_path and not Path(default_path).exists():
                    changed = True
                    if episode.media_files:
                        valid_first = episode.media_files[0].path
                        if valid_first:
                            logger.info(
                                "Cleanup: Updating default_path for episode "
                                "'%s' from '%s' to '%s' "
                                "(valid media_files still exist)",
                                episode.name,
                                default_path,
                                valid_first,
                            )
                            episode.default_path = valid_first
                    else:
                        logger.info(
                            "Cleanup: Setting path=None for missing episode "
                            "'%s' (was '%s')",
                            episode.name,
                            default_path,
                        )
                        episode.path = None

                if changed:
                    stats["episodes"] = stats.get("episodes", 0) + 1


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
        "series_scanned": 0,
        "series_updated": 0,
        "seasons_scanned": 0,
        "seasons_updated": 0,
        "episodes_scanned": 0,
        "episodes_updated": 0,
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
            stats["series_id"] = series.id

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
                if episode_obj.path is not None:
                    existing_by_path[episode_obj.path] = episode_obj
                for mf in episode_obj.media_files:
                    if mf.path:
                        existing_by_path[mf.path] = episode_obj

                if episode_obj.tmdb_number is not None:
                    existing_by_number[episode_obj.tmdb_number] = episode_obj

                if episode_obj.name is not None:
                    existing_by_name[episode_obj.name] = episode_obj

            incoming_paths_in_season = set()
            for ep_data in season_data.get("episodes", []):
                p = ep_data.get("path")
                if p:
                    incoming_paths_in_season.add(p)
                for v in ep_data.get("versions", []):
                    if v.get("path"):
                        incoming_paths_in_season.add(v.get("path"))

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
                    incoming_paths_in_season=incoming_paths_in_season,
                )

            # Delete stale episode records (not present in incoming data)
            stale_episodes = (
                set(existing_by_path.values())
                | set(existing_by_number.values())
                | set(existing_by_name.values())
            ) - processed_episodes

            for ep_obj in stale_episodes:
                logger.info(
                    f"Removing stale episode S{season.name} "
                    f"E{ep_obj.tmdb_number or '?'} ('{ep_obj.name}') from database"
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
                stats["episodes_removed"] += 1

            # Save season directory mtime to scanned_directories table
            season_metadata = season_data.get("metadata", {})
            dir_path = season_metadata.get("season_directory_path")
            mtime = season_metadata.get("last_scanned_mtime")
            if dir_path and mtime is not None:
                from lan_streamer.db.models import ScannedDirectory

                record = session.scalars(
                    select(ScannedDirectory).where(ScannedDirectory.path == dir_path)
                ).first()
                if record:
                    record.last_scanned_mtime = mtime
                else:
                    record = ScannedDirectory(path=dir_path, last_scanned_mtime=mtime)
                    session.add(record)

            session.flush()
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
        raise
