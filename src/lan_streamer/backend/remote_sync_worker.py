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


def sync_remote_library_from_agent(
    library_name: str,
    library_configuration: dict[str, Any],
    database: Any,
) -> dict[str, Any]:
    """Fetch items for a remote library from its scan agent and persist them.

    This function performs all blocking work (network requests, poster
    downloads, database writes) and is designed to run on a background thread.

    Arguments:
        library_name: Name of the remote library in the local configuration.
        library_configuration: Local configuration entry for the library
            (must have ``management_type == 'remote'`` plus ``agent_url`` and
            optionally ``remote_library_id``).
        database: The ``lan_streamer.db`` module used to persist the library.

    Returns:
        A result dictionary with ``library_name``, ``success`` (bool),
        ``items`` (count of persisted items), and ``error`` (message on
        failure).
    """
    agent_url = library_configuration.get("agent_url", "")
    remote_library_identifier = (
        library_configuration.get("remote_library_id") or library_name
    )
    result: dict[str, Any] = {
        "library_name": library_name,
        "success": False,
        "items": 0,
        "error": "",
    }
    if not agent_url:
        result["error"] = "No agent URL configured"
        logger.warning(
            "Remote sync for library '%s' skipped: no agent URL", library_name
        )
        return result

    try:
        import requests
        from sqlalchemy.exc import SQLAlchemyError

        from lan_streamer.services.scan_agent_client import (
            ScanAgentConnectionError,
            scan_agent_client,
        )

        remote_items = scan_agent_client.fetch_library_items(
            agent_url, str(remote_library_identifier)
        )
        library_type = library_configuration.get("type", "tv")
        for item_dictionary in remote_items.values():
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
                    if (
                        remote_season_poster
                        and not Path(remote_season_poster).is_file()
                    ):
                        local_season_poster = scan_agent_client.download_poster(
                            agent_url, remote_season_poster
                        )
                        if local_season_poster:
                            season_metadata_dict["poster_path"] = local_season_poster

        if library_type == "movie":
            database.save_movie_library(library_name, remote_items)
        else:
            database.save_library(library_name, remote_items)
        result["success"] = True
        result["items"] = len(remote_items)
        logger.info(
            "Successfully synchronized remote library '%s' (%d items) from agent %s",
            library_name,
            len(remote_items),
            agent_url,
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
            "Could not synchronize remote library '%s' from agent %s: %s",
            library_name,
            agent_url,
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
