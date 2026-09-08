"""FastAPI application factory for the scan-agent REST API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from scan_agent.api.routes_browse import browse_router
from scan_agent.api.routes_core import config_router, health_router, libraries_router
from scan_agent.api.routes_filesystem import filesystem_router
from scan_agent.api.routes_images import images_router
from scan_agent.api.routes_scan import events_router, scan_router
from scan_agent.api.routes_services import (
    metadata_router,
    rename_router,
    subtitles_router,
)
from scan_agent.api.routes_watch import watch_router
from scan_agent.config import AgentConfig, get_agent_config, install_into_lan_streamer
from scan_agent.db.connection import create_engine_for_database, init_database
from scan_agent.scan.orchestrator import ScanOrchestrator
from scan_agent.scan.progress import ProgressBroker

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

_API_PREFIX = "/api/v1"


def create_app(
    agent_config: AgentConfig | None = None, engine: Engine | None = None
) -> FastAPI:
    """Build the FastAPI application.

    The agent config singleton is used when none is given; a fresh SQLite
    engine is created and initialised from ``database_path``. The config
    bridge into the reused desktop scanner is installed before the API is
    served so lazy desktop imports read our settings.
    """
    resolved_config = agent_config or get_agent_config()
    resolved_engine = engine or create_engine_for_database(
        resolved_config.database_path
    )
    init_database(resolved_engine)
    install_into_lan_streamer(resolved_config)

    progress_broker = ProgressBroker()
    orchestrator = ScanOrchestrator(resolved_config, resolved_engine, progress_broker)

    application = FastAPI(
        title="LAN Streamer Scan Agent",
        version="0.1.0",
        description="Remote scanning, metadata resolution, and library database "
        "for LAN Streamer.",
    )
    application.state.agent_config = resolved_config
    application.state.engine = resolved_engine
    application.state.progress_broker = progress_broker
    application.state.orchestrator = orchestrator

    application.include_router(health_router, prefix=_API_PREFIX)
    application.include_router(config_router, prefix=_API_PREFIX)
    application.include_router(libraries_router, prefix=_API_PREFIX)
    application.include_router(scan_router, prefix=_API_PREFIX)
    application.include_router(events_router, prefix=_API_PREFIX)
    application.include_router(browse_router, prefix=_API_PREFIX)
    application.include_router(metadata_router, prefix=_API_PREFIX)
    application.include_router(rename_router, prefix=_API_PREFIX)
    application.include_router(subtitles_router, prefix=_API_PREFIX)
    application.include_router(watch_router, prefix=_API_PREFIX)
    application.include_router(filesystem_router, prefix=_API_PREFIX)
    application.include_router(images_router, prefix=_API_PREFIX)

    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    static_directory = Path(__file__).resolve().parent.parent / "static"
    if static_directory.exists():
        application.mount(
            "/static", StaticFiles(directory=static_directory), name="static"
        )

        @application.get("/", include_in_schema=False)
        def index_page() -> FileResponse:
            return FileResponse(static_directory / "index.html")

    return application
