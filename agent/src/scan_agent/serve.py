"""Standalone entrypoint launching the scan-agent REST API via uvicorn."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_SEARCH_PATH = Path(__file__).resolve().parent


def _ensure_import_path() -> None:
    """Make the agent and desktop packages importable when run directly.

    The agent package lives under ``agent/src``; scanning reuses the desktop
    ``lan_streamer`` package from the repository root ``src`` directory. Both
    are added when they exist so the entrypoint works from a source checkout
    without an installed desktop package.
    """
    agent_src = _SEARCH_PATH.parent.parent
    for candidate in (agent_src, agent_src.parent.parent / "src"):
        resolved = str(candidate)
        if resolved not in sys.path and candidate.exists():
            sys.path.insert(0, resolved)


def main() -> None:
    """Start the uvicorn server for the agent API."""
    _ensure_import_path()
    import argparse
    import os

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    import uvicorn

    from scan_agent.api.main import create_app
    from scan_agent.config import get_agent_config

    parser = argparse.ArgumentParser(description="LAN Streamer Scan Agent")
    parser.add_argument(
        "--data-dir",
        dest="data_directory",
        default=os.environ.get("SCAN_AGENT_DATA", None),
        help="Path to agent data directory (stores config, database, and cache)",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=os.environ.get("SCAN_AGENT_CONFIG", None),
        help="Path to agent configuration file",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("SCAN_AGENT_HOST", "0.0.0.0"),
        help="Host address to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SCAN_AGENT_PORT", "8800")),
        help="Port to bind to (default: 8800)",
    )
    parsed_arguments = parser.parse_args()

    agent_config = (
        get_agent_config(
            path=parsed_arguments.config_path,
            data_directory=parsed_arguments.data_directory,
        )
        if (
            parsed_arguments.config_path is not None
            or parsed_arguments.data_directory is not None
        )
        else None
    )
    application = create_app(agent_config=agent_config)
    host = parsed_arguments.host
    port = parsed_arguments.port
    logger.info("Scan agent API listening on http://%s:%s", host, port)
    uvicorn.run(application, host=host, port=port)


if __name__ == "__main__":
    main()
