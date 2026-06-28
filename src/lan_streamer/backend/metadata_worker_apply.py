import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal, QThread

from lan_streamer.providers.tmdb import tmdb_client as _tmdb_default

logger = logging.getLogger("lan_streamer.backend")


class MetadataApplyWorker(QThread):
    """Downloads provider artwork and syncs TMDB episodes for a metadata match.

    Runs the blocking TMDB API calls in a background thread. The caller
    should apply the result (in-memory dict modifications + DB save) on
    the main thread after receiving the finished signal.

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
        poster_path: Optional[str] = None,
        is_movie: bool = False,
        show_future_episodes: bool = True,
        tmdb_client: Any = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._series_record: Dict[str, Any] = series_record
        self._tmdb_identifier: str = tmdb_identifier
        self._saved_group_id: Optional[str] = saved_group_id
        self._poster_path: Optional[str] = poster_path
        self._is_movie: bool = is_movie
        self._show_future_episodes: bool = show_future_episodes
        self._tmdb: Any = tmdb_client or _tmdb_default

    def run(self) -> None:
        try:
            logger.info(
                "MetadataApplyWorker starting TMDB sync for series "
                f"(TMDB ID: {self._tmdb_identifier})"
            )
            synced_data = self._sync_tmdb_episodes(
                self._series_record, self._tmdb_identifier, self._saved_group_id
            )

            cached_poster: Optional[str] = self._poster_path
            if self._poster_path and self._tmdb_identifier:
                prefix = "tmdb_movie_" if self._is_movie else "tmdb_series_"
                try:
                    cached_poster = (
                        self._tmdb.download_image(
                            self._poster_path,
                            f"{prefix}{self._tmdb_identifier}",
                        )
                        or self._poster_path
                    )
                except Exception as e:
                    logger.exception(f"Failed to download poster: {e}")
                    cached_poster = self._poster_path

            logger.info("MetadataApplyWorker completed successfully")
            self.finished.emit(synced_data, cached_poster or "")
        except Exception as exc:
            logger.exception(f"MetadataApplyWorker failed: {exc}")
            self.error.emit(str(exc))

    def _sync_tmdb_episodes(
        self,
        series_record: Dict[str, Any],
        tmdb_identifier: str,
        saved_group_id: Optional[str],
    ) -> Dict[str, Any]:
        """Fetch TMDB episode data and populate episode records.

        This method performs blocking TMDB API calls and returns an
        updated copy of the series_record dict.
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
                    from lan_streamer.scanner.scan_tv import (
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
