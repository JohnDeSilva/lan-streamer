"""MyAnimeList authentication, search, and detail routes for the scan agent."""

from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

mal_router = APIRouter(tags=["myanimelist"])


class MalAuthExchangeRequest(BaseModel):
    """Payload for exchanging a MyAnimeList OAuth2 authorization code."""

    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1)
    code_verifier: str | None = None


def _myanimelist_client() -> Any:
    """Return the bridged MyAnimeListClient singleton."""
    from lan_streamer.providers.myanimelist import myanimelist_client

    return myanimelist_client


def _extract_authorization_code(raw_input: str) -> str:
    """Extract the OAuth ``code`` parameter if a full redirect URL was pasted."""
    cleaned = raw_input.strip()
    if cleaned.startswith(("http://", "https://")) or "code=" in cleaned:
        parsed = urlparse(cleaned)
        query_params = parse_qs(parsed.query)
        codes = query_params.get("code")
        if codes and codes[0].strip():
            return codes[0].strip()
    return cleaned


@mal_router.get("/services/myanimelist/status")
def mal_status(request: Request) -> dict[str, Any]:
    """Return MyAnimeList configuration and authentication status."""
    config = request.app.state.agent_config
    client = _myanimelist_client()
    return {
        "configured": bool(client.is_configured()),
        "authenticated": bool(client.is_authenticated()),
        "client_id": config.myanimelist_client_id,
        "has_client_secret": bool(config.myanimelist_client_secret.strip()),
        "expires_at": config.myanimelist_token_expires_at,
    }


@mal_router.post("/services/myanimelist/auth/url")
def mal_auth_url(request: Request) -> dict[str, Any]:
    """Generate a MyAnimeList OAuth2 PKCE authorization URL."""
    client = _myanimelist_client()
    if not client.is_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MyAnimeList Client ID must be configured on the agent first.",
        )
    code_verifier = secrets.token_urlsafe(64)[:128]
    request.app.state.mal_code_verifier = code_verifier
    auth_url = client.generate_auth_url(code_verifier)
    return {"auth_url": auth_url, "code_verifier": code_verifier}


@mal_router.post("/services/myanimelist/auth/exchange")
def mal_auth_exchange(
    request: Request,
    payload: MalAuthExchangeRequest,
) -> dict[str, Any]:
    """Exchange a MyAnimeList OAuth2 authorization code (or redirect URL) for tokens."""
    client = _myanimelist_client()
    if not client.is_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MyAnimeList Client ID is not configured on the agent.",
        )
    code_verifier = (
        payload.code_verifier
        or getattr(request.app.state, "mal_code_verifier", None)
        or ""
    ).strip()
    if not code_verifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing PKCE code_verifier. Generate a new authorization URL first.",
        )
    authorization_code = _extract_authorization_code(payload.code)
    success, message = client.exchange_auth_code(authorization_code, code_verifier)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    request.app.state.mal_code_verifier = None
    return {
        "authenticated": True,
        "message": message,
        "expires_at": request.app.state.agent_config.myanimelist_token_expires_at,
    }


@mal_router.post("/services/myanimelist/auth/disconnect")
def mal_auth_disconnect() -> dict[str, Any]:
    """Clear stored MyAnimeList OAuth2 tokens on the agent."""
    client = _myanimelist_client()
    client.remove_connection()
    return {"authenticated": False}


@mal_router.get("/services/myanimelist/search")
def mal_search(
    query: str = Query(min_length=1, max_length=200),
) -> dict[str, Any]:
    """Search MyAnimeList for anime entries using the agent's credentials."""
    client = _myanimelist_client()
    if not client.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MyAnimeList Client ID is not configured on the agent.",
        )
    results = client.search_anime(query)
    return {"results": results}


@mal_router.get("/services/myanimelist/anime/{anime_id}")
def mal_anime_details(
    anime_id: int = Path(ge=1),
) -> dict[str, Any]:
    """Fetch full MyAnimeList details for a single anime ID."""
    client = _myanimelist_client()
    if not client.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MyAnimeList Client ID is not configured on the agent.",
        )
    details = client.get_anime_details(anime_id)
    if details is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MyAnimeList entry {anime_id} not found.",
        )
    return details
