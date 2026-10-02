"""Background worker that synchronizes remote scan-agent libraries.

Remote library synchronization performs blocking network requests (fetching
the scanner items dictionary from the agent and downloading posters) and a
database write.  Those operations must never run on the Qt UI thread, so the
sync is executed from an :class:`AsyncWorkerBase` worker inside a thread-pool
executor.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lan_streamer.backend.async_worker_base import AsyncWorkerBase
from lan_streamer.system.async_utils import run_in_executor

logger = logging.getLogger(__name__)


def _download_posters_for_items(
    items_dict: dict[str, Any], library_type: str, agent_url: str
) -> None:
    from lan_streamer.services.scan_agent_client import scan_agent_client

    for item_dictionary in items_dict.values():
        if not isinstance(item_dictionary, dict):
            continue
        if library_type == "movie":
            remote_poster_path = item_dictionary.get("poster_path")
            if remote_poster_path and not Path(remote_poster_path).is_file():
                local_poster_path = scan_agent_client.download_poster(
                    agent_url, remote_poster_path
                )
                if local_poster_path:
                    item_dictionary["poster_path"] = local_poster_path
        else:
            series_metadata_dict = item_dictionary.get("metadata", {})
            remote_poster_path = series_metadata_dict.get("poster_path")
            if remote_poster_path and not Path(remote_poster_path).is_file():
                local_poster_path = scan_agent_client.download_poster(
                    agent_url, remote_poster_path
                )
                if local_poster_path:
                    series_metadata_dict["poster_path"] = local_poster_path
            for season_dictionary in item_dictionary.get("seasons", {}).values():
                if not isinstance(season_dictionary, dict):
                    continue
                season_metadata_dict = season_dictionary.get("metadata", {})
                remote_season_poster = season_metadata_dict.get("poster_path")
                if remote_season_poster and not Path(remote_season_poster).is_file():
                    local_season_poster = scan_agent_client.download_poster(
                        agent_url, remote_season_poster
                    )
                    if local_season_poster:
                        season_metadata_dict["poster_path"] = local_season_poster


def _back_sync_to_agents(
    agent_sources: list[dict[str, Any]],
    library_configuration: dict[str, Any],
    library_type: str,
    combined_items: dict[str, Any],
) -> None:
    """Synchronize local watch states and manual metadata mappings back to agent sources."""
    import requests

    from lan_streamer.services.path_mapping_service import map_local_path_to_remote
    from lan_streamer.services.scan_agent_client import (
        ScanAgentConnectionError,
        scan_agent_client,
    )

    for agent_source in agent_sources:
        agent_url = agent_source.get("agent_url", "")
        if not agent_url:
            continue
        mount_mappings = dict(library_configuration.get("mount_mappings", {}))
        if "mount_mappings" in agent_source:
            mount_mappings.update(agent_source.get("mount_mappings", {}))

        watch_events_to_sync: list[dict[str, Any]] = []
        metadata_mappings_to_sync: list[dict[str, Any]] = []

        for _item_name, item_data in combined_items.items():
            if library_type == "movie":
                movie_path = item_data.get("path")
                if movie_path and item_data.get("watched"):
                    remote_path = map_local_path_to_remote(movie_path, mount_mappings)
                    watch_events_to_sync.append(
                        {
                            "media_type": "movie",
                            "path": remote_path,
                            "event": "complete",
                            "watched": True,
                            "position_seconds": item_data.get("last_played_position"),
                        }
                    )
            else:
                for season_data in item_data.get("seasons", {}).values():
                    season_mal_id = season_data.get("metadata", {}).get(
                        "myanimelist_id"
                    )
                    for episode_data in season_data.get("episodes", []):
                        episode_path = episode_data.get("path")
                        if not episode_path:
                            continue
                        remote_path = map_local_path_to_remote(
                            episode_path, mount_mappings
                        )
                        if episode_data.get("watched"):
                            watch_events_to_sync.append(
                                {
                                    "media_type": "episode",
                                    "path": remote_path,
                                    "event": "complete",
                                    "watched": True,
                                    "position_seconds": episode_data.get(
                                        "last_played_position"
                                    ),
                                }
                            )
                        if episode_data.get("myanimelist_anime_id") or episode_data.get(
                            "tmdb_episode_identifier"
                        ):
                            metadata_mappings_to_sync.append(
                                {
                                    "path": remote_path,
                                    "tmdb_episode_identifier": episode_data.get(
                                        "tmdb_episode_identifier"
                                    ),
                                    "myanimelist_id": season_mal_id,
                                    "myanimelist_anime_id": episode_data.get(
                                        "myanimelist_anime_id"
                                    ),
                                    "myanimelist_episode_number": episode_data.get(
                                        "myanimelist_episode_number"
                                    ),
                                    "watched": episode_data.get("watched"),
                                }
                            )

        if watch_events_to_sync:
            try:
                scan_agent_client.sync_watch_events(agent_url, watch_events_to_sync)
            except (
                ScanAgentConnectionError,
                requests.RequestException,
                OSError,
                ValueError,
                KeyError,
            ) as sync_watch_error:
                logger.debug(
                    "Failed back-syncing watch events to agent '%s': %s",
                    agent_url,
                    sync_watch_error,
                )

        if metadata_mappings_to_sync:
            try:
                scan_agent_client.apply_manual_metadata_mappings(
                    agent_url, metadata_mappings_to_sync
                )
            except (
                ScanAgentConnectionError,
                requests.RequestException,
                OSError,
                ValueError,
                KeyError,
            ) as sync_metadata_error:
                logger.debug(
                    "Failed back-syncing metadata mappings to agent '%s': %s",
                    agent_url,
                    sync_metadata_error,
                )


def sync_remote_library_from_agent(
    library_name: str,
    library_configuration: dict[str, Any],
    database: Any,
) -> dict[str, Any]:
    """Fetch items for remote media sources from scan agents and persist them.

    This function performs all blocking work (network requests, poster
    downloads, database writes) and is designed to run on a background thread.
    Supports multi-source libraries with multiple scan agents and preserves
    existing local items in hybrid libraries.

    Arguments:
        library_name: Name of the library in the local configuration.
        library_configuration: Local configuration entry for the library.
        database: The ``lan_streamer.db`` module used to persist the library.

    Returns:
        A result dictionary with ``library_name``, ``success`` (bool),
        ``items`` (count of persisted items), and ``error`` (message on
        failure).
    """
    from lan_streamer.scanner.core import merge_series_data
    from lan_streamer.services.tab_consolidation_service import (
        _merge_movie_records,
    )
    from lan_streamer.system.config import get_library_sources

    sources = get_library_sources(library_configuration)
    agent_sources = [
        source_entry
        for source_entry in sources
        if source_entry.get("type") == "agent" and source_entry.get("agent_url")
    ]
    if not agent_sources and library_configuration.get("agent_url"):
        agent_sources = [
            {
                "type": "agent",
                "agent_url": library_configuration["agent_url"],
                "source_id": library_configuration.get("remote_library_id")
                or library_name,
            }
        ]

    result: dict[str, Any] = {
        "library_name": library_name,
        "success": False,
        "items": 0,
        "error": "",
    }
    if not agent_sources:
        result["error"] = "No agent URL configured"
        logger.warning(
            "Remote sync for library '%s' skipped: no agent media sources",
            library_name,
        )
        return result

    try:
        import requests
        from sqlalchemy.exc import SQLAlchemyError

        from lan_streamer.services.scan_agent_client import (
            ScanAgentConnectionError,
            scan_agent_client,
        )

        library_type = library_configuration.get("type", "tv")
        combined_items: dict[str, Any] = {}

        for agent_source in agent_sources:
            agent_url = agent_source.get("agent_url", "")
            source_identifier = (
                agent_source.get("source_id")
                or agent_source.get("remote_library_id")
                or library_name
            )

            remote_items = scan_agent_client.fetch_library_items(
                agent_url, str(source_identifier)
            )

            _download_posters_for_items(remote_items, library_type, agent_url)

            # Merge items across multiple agent sources
            for item_name, item_data in remote_items.items():
                if item_name in combined_items:
                    if library_type == "movie":
                        combined_items[item_name] = _merge_movie_records(
                            combined_items[item_name], item_data
                        )
                    else:
                        combined_items[item_name] = merge_series_data(
                            combined_items[item_name], item_data
                        )
                else:
                    combined_items[item_name] = item_data

        # Merge with existing items in database (preserves local items for hybrid libraries)
        try:
            if library_type == "movie":
                existing_items = database.load_movie_library(library_name)
            else:
                existing_items = database.load_library(library_name)
            if existing_items and isinstance(existing_items, dict):
                for existing_name, existing_data in existing_items.items():
                    if existing_name in combined_items:
                        if library_type == "movie":
                            combined_items[existing_name] = _merge_movie_records(
                                combined_items[existing_name], existing_data
                            )
                        else:
                            combined_items[existing_name] = merge_series_data(
                                existing_data, combined_items[existing_name]
                            )
                    else:
                        combined_items[existing_name] = existing_data
        except (
            KeyError,
            ValueError,
            TypeError,
            OSError,
            RuntimeError,
            SQLAlchemyError,
        ) as load_error:
            logger.debug(
                "Could not load existing items for library '%s' before sync: %s",
                library_name,
                load_error,
            )

        if library_type == "movie":
            database.save_movie_library(library_name, combined_items)
        else:
            database.save_library(library_name, combined_items)

        # Synchronize watch state and metadata maps back to agents
        _back_sync_to_agents(
            agent_sources=agent_sources,
            library_configuration=library_configuration,
            library_type=library_type,
            combined_items=combined_items,
        )

        result["success"] = True
        result["items"] = len(combined_items)
        logger.info(
            "Successfully synchronized remote sources for library '%s' (%d total items)",
            library_name,
            len(combined_items),
        )
    except (
        requests.RequestException,
        SQLAlchemyError,
        ScanAgentConnectionError,
        KeyError,
        ValueError,
        TypeError,
        OSError,
    ) as error_instance:
        result["error"] = str(error_instance)
        logger.warning(
            "Could not synchronize remote library '%s': %s",
            library_name,
            error_instance,
        )
    return result


class RemoteSyncWorker(AsyncWorkerBase):
    """Async worker that syncs one remote library off the UI thread.

    Signals
    -------
    finished : Signal(object)
        Emitted with the result dict from
        :func:`sync_remote_library_from_agent`.
    """

    def __init__(
        self,
        library_name: str,
        library_configuration: dict[str, Any],
        database: Any,
        async_task_manager: Any | None = None,
        parent: Any | None = None,
    ) -> None:
        super().__init__(async_task_manager=async_task_manager, parent=parent)
        self.library_name: str = library_name
        self._library_configuration: dict[str, Any] = dict(library_configuration)
        self._database: Any = database

    async def run_async(self) -> dict[str, Any]:
        """Run the blocking sync inside the thread-pool executor."""
        return await run_in_executor(
            sync_remote_library_from_agent,
            self.library_name,
            self._library_configuration,
            self._database,
        )
