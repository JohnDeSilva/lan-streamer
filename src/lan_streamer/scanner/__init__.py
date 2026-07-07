from .parser import (
    VIDEO_EXTENSIONS,
    SUBTITLE_EXTENSIONS,
    _parse_episode_number,
    _parse_season_number,
    _parse_movie_folder,
    has_video_files,
    has_video_files_shallow,
)
from .file_property_scanner import (
    get_detailed_file_info,
    get_stub_file_info,
    _extract_video_runtime,
)
from lan_streamer.services.metadata_common import (
    _build_locked_movie_tmdb_stub,
    _build_locked_tv_tmdb_stub,
    _merge_season_episodes,
    _resolve_existing_jellyfin_id,
)
from lan_streamer.services.metadata_movie import (
    _apply_existing_movie_metadata,
    _apply_tmdb_movie_data,
    _build_movie_metadata_defaults,
    _resolve_movie_jellyfin_id,
    _resolve_movie_poster,
)
from lan_streamer.services.metadata_series import (
    _build_existing_episodes_index,
    _build_series_metadata_defaults,
    _detect_new_series_files,
    _process_series_metadata,
    _resolve_episode_jellyfin_id,
    _resolve_series_poster,
)
from lan_streamer.services.metadata_episode import (
    _process_episode_file,
    _process_season_metadata,
)
from lan_streamer.services.metadata_updates import clean_series_data
from .versioning import get_version_score_key, choose_active_version
from .core import (
    LibraryDict,
    scan_directories,
    get_scan_executor,
    shutdown_scan_executor,
)
from .pass1_file_discovery import scan_series_pass1, scan_movie_pass1
from .pass2_metadata import scan_series_pass2, scan_movie_pass2
from .pass3_technical import scan_series_pass3, scan_movie_pass3
from lan_streamer.providers.tmdb import tmdb_client
from lan_streamer.scanner.renamer import get_rename_preview, perform_rename
import concurrent.futures
import logging
from pathlib import Path
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def scan_series(
    series_directory: Path,
    existing_series_data: dict[str, Any] | None = None,
    force_refresh: bool = False,
    skip_metadata_resolution: bool = False,
    single_item_refresh: bool = False,
    jellyfin_data: dict[str, dict] | None = None,
    tmdb_series: dict[str, Any] | None = None,
    manual_jellyfin_id: str = "",
    show_future_episodes: bool = True,
    detail_callback: Callable | None = None,
    season_callback: Callable | None = None,
    offline: bool = False,
    metadata_only: bool = False,
    tmdb_prefetch_executor: concurrent.futures.ThreadPoolExecutor | None = None,
    is_interrupted: Callable | None = None,
) -> dict[str, Any] | None:
    """Scan a single TV series directory through all 3 passes.

    Wraps the new 3-pass pipeline for backward compatibility with callers
    that previously used the old ``scan_tv.scan_series``.
    """
    if manual_jellyfin_id and existing_series_data is None:
        existing_series_data = {"metadata": {}, "seasons": {}}
    if manual_jellyfin_id and existing_series_data is not None:
        existing_series_data.setdefault("metadata", {})["jellyfin_id"] = (
            manual_jellyfin_id
        )
    pass1_result = scan_series_pass1(
        series_directory,
        existing_series_data=existing_series_data,
        force_refresh=force_refresh,
        detail_callback=detail_callback,
    )
    if pass1_result is None:
        return None
    pass2_result = scan_series_pass2(
        series_directory,
        existing_series_data=pass1_result,
        tmdb_series=tmdb_series,
        jellyfin_data=jellyfin_data,
        force_refresh=force_refresh,
        single_item_refresh=single_item_refresh,
        show_future_episodes=show_future_episodes,
        detail_callback=detail_callback,
        season_callback=season_callback,
        tmdb_prefetch_executor=tmdb_prefetch_executor,
    )
    if pass2_result is None:
        return pass1_result
    pass3_result = scan_series_pass3(
        series_directory,
        pass2_result,
        force_refresh=force_refresh,
    )
    return pass3_result or pass2_result


def scan_movie(
    movie_directory: Path,
    existing_movie_data: dict[str, Any] | None = None,
    force_refresh: bool = False,
    detail_callback: Callable | None = None,
    jellyfin_data: dict[str, dict] | None = None,
    is_interrupted: Callable | None = None,
    tmdb_series: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Scan a single movie directory through all 3 passes.

    Wraps the new 3-pass pipeline for backward compatibility with callers
    that previously used the old ``scan_movie.scan_movie``.
    """
    pass1_result = scan_movie_pass1(
        movie_directory,
        existing_movie_data=existing_movie_data,
        force_refresh=force_refresh,
        detail_callback=detail_callback,
    )
    if pass1_result is None:
        return None
    pass2_result = scan_movie_pass2(
        movie_directory,
        existing_movie_data=pass1_result,
        jellyfin_data=jellyfin_data,
        force_refresh=force_refresh,
        detail_callback=detail_callback,
    )
    if pass2_result is None:
        return pass1_result
    pass3_result = scan_movie_pass3(
        movie_directory,
        pass2_result,
        force_refresh=force_refresh,
    )
    return pass3_result or pass2_result
