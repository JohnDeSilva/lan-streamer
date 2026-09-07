"""REST API package exposing the scan agent over HTTP."""

from scan_agent.api.main import create_app

__all__ = ["create_app"]
