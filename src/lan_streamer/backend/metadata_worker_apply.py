import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncio
from PySide6.QtCore import QObject, Signal

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.scanner.pass1_file_discovery import scan_series_pass1
from lan_streamer.scanner.pass2_metadata import scan_series_pass2
from lan_streamer.services.metadata_updates import clean_series_data
from lan_streamer.system.async_task_manager import AsyncTaskManager
from lan_streamer.providers.tmdb import tmdb_client as _tmdb_default

logger = logging.getLogger("lan_streamer.backend")


class MetadataApplyWorker(AsyncWorkerBase):
    """Downloads provider artwork and syncs TMDB episodes for a metadata match.

    Uses the scanner pipeline (pass 1 + pass 2) to re-discover files on disk
    and match them against the newly selected TMDB series. This ensures all
    files are properly remapped even when the series structure or numbering
    differs from the previously matched series.

    Signals:
        finished: Emitted with (updated_series_record, poster_path) on success.
        error: Emitted with an error message string on failure.
    """

    finished = Signal(dict, str)
    error = Signal(str)

    def __init__(
        self,
        series_record: Dict[str, Any],
        tmdb_identifier: str,
        saved_group_id: Optional[str],
        series_directory: Optional[Path] = None,
        async_task_manager: Optional[AsyncTaskManager] = None,
        poster_path: Optional[str] = None,
        is_movie: bool = False,
        show_future_episodes: bool = True,
        tmdb_client: Any = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self._series_record: Dict[str, Any] = series_record
        self._tmdb_identifier: str = tmdb_identifier
        self._saved_group_id: Optional[str] = saved_group_id
        self._series_directory: Optional[Path] = series_directory
        self._poster_path: Optional[str] = poster_path
        self._is_movie: bool = is_movie
        self._show_future_episodes: bool = show_future_episodes
        self._tmdb: Any = tmdb_client or _tmdb_default

    async def run_async(self) -> tuple[Dict[str, Any], str]:
        logger.info(
            "MetadataApplyWorker starting TMDB sync for series "
            f"(TMDB ID: {self._tmdb_identifier})"
        )
        synced_data = await asyncio.to_thread(
            self._sync_tmdb_episodes,
            self._series_record,
            self._tmdb_identifier,
            self._saved_group_id,
        )

        cached_poster: Optional[str] = self._poster_path
        if self._poster_path and self._tmdb_identifier:
            prefix = "tmdb_movie_" if self._is_movie else "tmdb_series_"
            try:
                downloaded = await asyncio.to_thread(
                    self._tmdb.download_image,
                    self._poster_path,
                    f"{prefix}{self._tmdb_identifier}",
                )
                cached_poster = downloaded or self._poster_path
            except Exception as e:
                logger.exception(f"Failed to download poster: {e}")
                cached_poster = self._poster_path

        logger.info("MetadataApplyWorker completed successfully")
        poster_result = cached_poster or ""
        return synced_data, poster_result

    async def _run_wrapper(self) -> None:
        """Override to emit finished with two arguments."""
        try:
            self.started.emit()
            synced_data, poster_result = await self.run_async()
            if not self._cancelled:
                self.finished.emit(synced_data, poster_result)
        except asyncio.CancelledError:
            logger.info("%s was cancelled.", self.__class__.__name__)
        except Exception as exception:
            logger.exception("%s failed with error.", self.__class__.__name__)
            if not self._cancelled:
                self.error.emit(str(exception))

    def _sync_tmdb_episodes(
        self,
        series_record: Dict[str, Any],
        tmdb_identifier: str,
        saved_group_id: Optional[str],
    ) -> Dict[str, Any]:
        """Re-scan the series directory against the new TMDB series.

        Uses the 2-pass scanner pipeline:
          1. Pass 1: walk the filesystem, discover all video files (creates stubs)
          2. Pass 2: match stubs against the new TMDB metadata

        If the series directory cannot be resolved, falls back to the old
        in-memory matching approach.
        """
        # Use the series directory resolved by the controller, if available.
        # This is the authoritative path and avoids unsafe filesystem inference.
        series_directory: Optional[Path] = self._series_directory

        # Fetch the full TMDB series data for the new identifier
        try:
            tmdb_series_data: Optional[Dict[str, Any]] = self._tmdb.get_series_by_id(
                tmdb_identifier
            )
        except Exception as exc:
            logger.exception(
                f"Failed to fetch TMDB series data for ID {tmdb_identifier}: {exc}"
            )
            tmdb_series_data = None

        if series_directory is not None and tmdb_series_data is not None:
            logger.info(
                f"Using scanner pipeline for series directory: {series_directory}"
            )
            # Pass 1: discover files on disk
            pass1_result = scan_series_pass1(
                series_directory,
                existing_series_data=series_record,
                force_refresh=True,
            )
            if pass1_result is None:
                logger.warning("Pass 1 returned None, falling back to in-memory sync")
                return self._fallback_sync(
                    series_record, tmdb_identifier, saved_group_id
                )

            # Pass 2: match against the new TMDB series
            pass2_result = scan_series_pass2(
                series_directory,
                existing_series_data=pass1_result,
                tmdb_series=tmdb_series_data,
                force_refresh=True,
                single_item_refresh=True,
                show_future_episodes=self._show_future_episodes,
            )
            if pass2_result is None:
                logger.warning("Pass 2 returned None, falling back to in-memory sync")
                return self._fallback_sync(
                    series_record, tmdb_identifier, saved_group_id
                )

            result = clean_series_data(pass2_result) or pass2_result
            # Preserve the locked_metadata flag set by the controller
            if series_record.get("metadata", {}).get("locked_metadata"):
                result.setdefault("metadata", {})["locked_metadata"] = True
            # Preserve the poster path from the match
            if self._poster_path:
                result.setdefault("metadata", {})["poster_path"] = self._poster_path
            return result

        logger.info("Series directory or TMDB data unavailable, using in-memory sync")
        return self._fallback_sync(series_record, tmdb_identifier, saved_group_id)

    def _fallback_sync(
        self,
        series_record: Dict[str, Any],
        tmdb_identifier: str,
        saved_group_id: Optional[str],
    ) -> Dict[str, Any]:
        """Legacy fallback: match existing episode dicts against new TMDB episodes.

        Used when the series directory cannot be resolved or the scanner
        pipeline is unavailable.
        """
        import copy

        result = copy.deepcopy(series_record)

        episode_group_details: Optional[Dict[str, Any]] = None
        if saved_group_id and saved_group_id != "default":
            try:
                episode_group_details = self._tmdb.get_episode_group_details(
                    saved_group_id
                )
            except Exception as e:
                logger.exception(
                    f"Failed to fetch saved group details {saved_group_id}: {e}"
                )
        if not episode_group_details:
            episode_group_details = self._tmdb.get_season_based_episode_group(
                tmdb_identifier
            )

        group_seasons: Dict[int, List[Dict[str, Any]]] = {}
        if (
            episode_group_details
            and isinstance(episode_group_details, dict)
            and "groups" in episode_group_details
        ):
            for group in episode_group_details.get("groups", []):
                group_name = group.get("name") or ""
                season_num_match = re.search(r"\d+", group_name)
                season_num = (
                    int(season_num_match.group())
                    if season_num_match
                    else group.get("order", -1)
                )
                if group_name.lower() == "specials":
                    season_num = 0
                if season_num >= 0:
                    group_seasons[season_num] = group.get("episodes", [])
        else:
            episode_group_details = None

        for season_folder_name, season_data_dict in result.get("seasons", {}).items():
            if season_folder_name.lower() == "specials":
                target_season_number: int = 0
            else:
                parsed_season_match = re.search(r"\d+", season_folder_name)
                target_season_number = (
                    int(parsed_season_match.group()) if parsed_season_match else -1
                )

            if target_season_number >= 0:
                if (
                    episode_group_details
                    and isinstance(episode_group_details, dict)
                    and "groups" in episode_group_details
                ):
                    fetched_episodes_list = []
                    for group_ep in group_seasons.get(target_season_number, []):
                        fetched_episodes_list.append(
                            {
                                "id": group_ep.get("id"),
                                "name": group_ep.get("name"),
                                "episode_number": (group_ep.get("order") or 0) + 1,
                                "air_date": group_ep.get("air_date") or "",
                                "runtime": group_ep.get("runtime") or 0,
                            }
                        )
                else:
                    fetched_episodes_list = self._tmdb.get_episodes(
                        tmdb_identifier, target_season_number
                    )

                for episode_item_dict in season_data_dict.get("episodes", []):
                    episode_filename: str = str(
                        episode_item_dict.get("name")
                        or Path(str(episode_item_dict.get("path", ""))).name
                    )
                    matched_tmdb_episode: Optional[Dict[str, Any]] = None

                    episode_number_match = re.search(
                        r"[Ss]\d+[Ee](\d+)", episode_filename
                    )
                    if episode_number_match:
                        target_episode_number: int = int(episode_number_match.group(1))
                        for candidate_episode in fetched_episodes_list:
                            if (
                                candidate_episode.get("episode_number")
                                == target_episode_number
                            ):
                                matched_tmdb_episode = candidate_episode
                                break
                    else:
                        stem_lower: str = Path(episode_filename).stem.lower()
                        for candidate_episode in fetched_episodes_list:
                            candidate_name: str = str(
                                candidate_episode.get("name") or ""
                            ).lower()
                            if candidate_name and candidate_name in stem_lower:
                                matched_tmdb_episode = candidate_episode
                                break

                    if matched_tmdb_episode:
                        matched_id_str: str = str(matched_tmdb_episode.get("id", ""))
                        episode_item_dict["tmdb_identifier"] = matched_id_str
                        episode_item_dict["tmdb_episode_identifier"] = matched_id_str
                        if matched_tmdb_episode.get("name"):
                            episode_item_dict["tmdb_name"] = matched_tmdb_episode.get(
                                "name", ""
                            )
                        if matched_tmdb_episode.get("episode_number") is not None:
                            episode_item_dict["tmdb_number"] = matched_tmdb_episode.get(
                                "episode_number"
                            )
                        if matched_tmdb_episode.get("air_date"):
                            episode_item_dict["air_date"] = matched_tmdb_episode.get(
                                "air_date", ""
                            )
                        if matched_tmdb_episode.get("runtime"):
                            episode_item_dict["runtime"] = matched_tmdb_episode.get(
                                "runtime", 0
                            )

                if self._show_future_episodes:
                    from lan_streamer.scanner.pass2_metadata import (
                        _create_tmdb_placeholder_episodes,
                    )

                    season_metadata = season_data_dict.get("metadata", {})
                    placeholders = _create_tmdb_placeholder_episodes(
                        fetched_episodes_list,
                        season_data_dict.get("episodes", []),
                        season_folder_name,
                        season_metadata,
                        show_future_episodes=self._show_future_episodes,
                    )
                    season_data_dict["episodes"].extend(placeholders)

        return result
