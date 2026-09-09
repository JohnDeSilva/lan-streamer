"""FastAPI application factory for the scan-agent REST API."""

from __future__ import annotations

import logging
import time
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
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

http_access_logger = logging.getLogger("scan_agent.http")


class HttpAccessLoggingMiddleware:
    """ASGI middleware to log HTTP and HTTPS requests."""

    def __init__(self, application: ASGIApp) -> None:
        self.application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return

        start_time = time.perf_counter()
        status_code = 200

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.application(scope, receive, send_wrapper)
        finally:
            duration_milliseconds = (time.perf_counter() - start_time) * 1000.0
            method = scope.get("method", "GET")
            path = scope.get("path", "/")

            raw_headers = scope.get("headers", [])
            headers_dictionary = {
                header_name.decode("latin1").lower(): header_value.decode("latin1")
                for header_name, header_value in raw_headers
            }

            forwarded_protocol = headers_dictionary.get("x-forwarded-proto")
            if forwarded_protocol:
                protocol = forwarded_protocol.split(",")[0].strip().upper()
            else:
                protocol = scope.get("scheme", "http").upper()

            forwarded_client_address = headers_dictionary.get("x-forwarded-for")
            if forwarded_client_address:
                client_address = forwarded_client_address.split(",")[0].strip()
            elif scope.get("client"):
                client_address = scope["client"][0]
            else:
                client_address = "unknown"

            if path not in ("/api/v1/scan/logs", "/api/v1/events"):
                is_static_asset = path.startswith("/static/")
                log_level = logging.DEBUG if is_static_asset else logging.INFO

                http_access_logger.log(
                    log_level,
                    '%s - "%s %s %s" %d (%.1fms)',
                    client_address,
                    method,
                    path,
                    protocol,
                    status_code,
                    duration_milliseconds,
                )


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
    progress_broker.attach_to_logger(logging.getLogger("scan_agent"))
    progress_broker.attach_to_logger(logging.getLogger("lan_streamer"))

    orchestrator = ScanOrchestrator(resolved_config, resolved_engine, progress_broker)

    application = FastAPI(
        title="LAN Streamer Scan Agent",
        version="0.1.0",
        description="Remote scanning, metadata resolution, and library database "
        "for LAN Streamer.",
    )
    application.add_middleware(HttpAccessLoggingMiddleware)
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
