"""FastAPI routes for serving media artwork and cached images."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

images_router = APIRouter(tags=["images"])


@images_router.get("/images/poster")
def get_poster_image(
    request: Request,
    path: str = Query(..., description="Path or filename of poster image on agent"),
) -> FileResponse:
    """Serve a poster image from the agent filesystem or cache directory."""
    cleaned_path = path.strip()
    if not cleaned_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty image path"
        )

    # 1. Direct file on agent filesystem
    target_path = Path(cleaned_path)
    if target_path.is_file():
        media_type, _ = mimetypes.guess_type(str(target_path))
        return FileResponse(str(target_path), media_type=media_type or "image/jpeg")

    # 2. Check within the agent cache directory
    agent_config = request.app.state.agent_config
    cache_directory = Path(agent_config.cache_directory)
    candidate_cache_file = cache_directory / "images" / target_path.name
    if candidate_cache_file.is_file():
        media_type, _ = mimetypes.guess_type(str(candidate_cache_file))
        return FileResponse(
            str(candidate_cache_file), media_type=media_type or "image/jpeg"
        )

    direct_cache_file = cache_directory / target_path.name
    if direct_cache_file.is_file():
        media_type, _ = mimetypes.guess_type(str(direct_cache_file))
        return FileResponse(
            str(direct_cache_file), media_type=media_type or "image/jpeg"
        )

    # 3. Check if TMDB client has it cached or can download it if it's a TMDB path
    try:
        from lan_streamer.providers.tmdb import tmdb_client

        cached_file = tmdb_client.get_cached_image(target_path.stem)
        if cached_file and Path(cached_file).is_file():
            media_type, _ = mimetypes.guess_type(str(cached_file))
            return FileResponse(str(cached_file), media_type=media_type or "image/jpeg")

        if cleaned_path.startswith("/") and cleaned_path.count("/") == 1:
            downloaded = tmdb_client.download_image(
                cleaned_path, f"tmdb_poster_{target_path.stem}"
            )
            if downloaded and Path(downloaded).is_file():
                media_type, _ = mimetypes.guess_type(str(downloaded))
                return FileResponse(
                    str(downloaded), media_type=media_type or "image/jpeg"
                )
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        logger.debug(
            "Could not resolve TMDB image for path '%s': %s", cleaned_path, error
        )

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
