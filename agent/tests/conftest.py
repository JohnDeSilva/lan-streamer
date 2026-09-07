"""Shared fixtures for the scan agent test suite.

Every scan-oriented fixture follows the verified recipe:

1. Build a tmp media tree under ``tmp_path``.
2. Create an :class:`AgentConfig` pointing at a tmp database and the media tree.
3. Create + initialise the agent SQLite engine (``init_database`` must run
   before any scan because the reused desktop pass 1 queries the
   ``scanned_directories`` table).
4. Install the agent config into ``lan_streamer.system.config`` and set
   ``LAN_STREAMER_DB``.
5. Import ``lan_streamer.scanner`` and the metadata services *before*
   monkeypatching their ``tmdb_client`` attribute.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from scan_agent.config import (
    AgentConfig,
    install_into_lan_streamer,
    reset_agent_config,
)
from scan_agent.db.connection import create_engine_for_database, init_database

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from lan_streamer.scanner.core import LibraryDict
    from sqlalchemy.engine import Engine


@pytest.fixture(autouse=True)
def _fresh_lan_streamer_database_modules(tmp_path: Path) -> None:
    """Reset desktop DB module state so ``LAN_STREAMER_DB`` re-resolves per test.

    The desktop ``lan_streamer.db`` package resolves ``DB_FILE`` from the
    environment at import time; each test uses its own tmp database, so the
    package must be re-imported fresh after ``install_into_lan_streamer``
    points the environment at the new file. ``HOME`` is pinned to a tmp
    directory so the desktop config module never touches the real home.
    """
    os.environ["HOME"] = str(tmp_path / "home")
    reset_agent_config()
    db_module = sys.modules.get("lan_streamer.db")
    if db_module is not None:
        engine = getattr(db_module, "_engine", None)
        if engine is not None:
            engine.dispose()
    stale_modules = [
        module_name
        for module_name in list(sys.modules)
        if module_name == "lan_streamer.db"
        or module_name.startswith("lan_streamer.db.")
    ]
    for module_name in stale_modules:
        del sys.modules[module_name]
    yield
    reset_agent_config()
    db_module = sys.modules.get("lan_streamer.db")
    if db_module is not None:
        engine = getattr(db_module, "_engine", None)
        if engine is not None:
            engine.dispose()


@pytest.fixture
def media_tree(tmp_path: Path) -> Path:
    """Create a small media tree with a two-version TV episode and one movie."""
    season_directory = tmp_path / "Shows" / "Test Show" / "Season 01"
    season_directory.mkdir(parents=True)
    (season_directory / "Test.Show.S01E01.mkv").write_bytes(b"fake mkv")
    (season_directory / "Test.Show.S01E01.mp4").write_bytes(b"fake mp4")
    (season_directory / "Test.Show.S01E02.mkv").write_bytes(b"fake mkv 2")
    movie_directory = tmp_path / "Movies" / "Some Movie (2020)"
    movie_directory.mkdir(parents=True)
    (movie_directory / "Some.Movie.2020.mkv").write_bytes(b"fake movie")
    return tmp_path


@pytest.fixture
def agent_config(tmp_path: Path, media_tree: Path) -> AgentConfig:
    """Return an :class:`AgentConfig` pointing at a tmp database and media tree."""
    config = AgentConfig(tmp_path / "config.json")
    config.database_path = str(tmp_path / "library.db")
    config.libraries = {
        "tv": {
            "name": "TV Shows",
            "media_type": "tv",
            "root_path": str(media_tree / "Shows"),
        },
        "movie": {
            "name": "Movies",
            "media_type": "movie",
            "root_path": str(media_tree / "Movies"),
        },
    }
    return config


@pytest.fixture
def database_engine(tmp_path: Path) -> Iterator[Engine]:
    """Create and initialise a fresh SQLite engine for the test database."""
    engine = create_engine_for_database(tmp_path / "library.db")
    init_database(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def tmdb_mock() -> MagicMock:
    """Return a MagicMock standing in for the desktop TMDB client."""
    series = {
        "id": 100,
        "name": "Test Show",
        "overview": "o",
        "poster_path": "/p.jpg",
        "first_air_date": "2024-01-01",
        "seasons": [{"season_number": 1, "episode_count": 5}],
        "number_of_seasons": 1,
    }
    season = {
        "season_number": 1,
        "name": "Season 1",
        "overview": "s",
        "poster_path": "/s.jpg",
        "episodes": [
            {
                "episode_number": 1,
                "name": "Pilot",
                "overview": "e",
                "air_date": "2024-01-01",
                "runtime": 30,
            },
            {
                "episode_number": 2,
                "name": "Second",
                "overview": "e2",
                "air_date": "2024-01-08",
                "runtime": 30,
            },
        ],
    }
    movie = {
        "id": 200,
        "title": "Some Movie",
        "overview": "mo",
        "poster_path": "/m.jpg",
        "release_date": "2020-05-01",
        "runtime": 120,
    }
    mock = MagicMock()
    mock.is_configured.return_value = True
    mock.search_series.return_value = series
    mock.search_series_full.return_value = [series]
    mock.get_series_by_id.return_value = series
    mock.get_seasons.return_value = [season]
    mock.get_episodes.return_value = season["episodes"]
    mock.download_image.return_value = None
    mock.search_movie.return_value = movie
    mock.search_movie_full.return_value = [movie]
    mock.get_movie_by_id.return_value = movie
    mock.get_episode_group_details.return_value = None
    mock.get_season_based_episode_group.return_value = None
    return mock


def _install_and_patch_tmdb(
    agent_config: AgentConfig,
    tmdb_mock: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Install the agent config bridge and patch the desktop TMDB client."""
    install_into_lan_streamer(agent_config)
    import lan_streamer.scanner
    import lan_streamer.scanner.pass2_metadata
    import lan_streamer.services.metadata_episode
    import lan_streamer.services.metadata_series

    monkeypatch.setattr(lan_streamer.services.metadata_series, "tmdb_client", tmdb_mock)
    monkeypatch.setattr(
        lan_streamer.services.metadata_episode, "tmdb_client", tmdb_mock
    )
    monkeypatch.setattr(lan_streamer.scanner.pass2_metadata, "tmdb_client", tmdb_mock)
    import lan_streamer.providers.tmdb

    monkeypatch.setattr(lan_streamer.providers.tmdb, "tmdb_client", tmdb_mock)


@pytest.fixture
def scanned_series_data(
    agent_config: AgentConfig,
    database_engine: Engine,
    tmdb_mock: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> LibraryDict:
    """Run the real scanner (pass 1) over the TV root and return the result."""
    _install_and_patch_tmdb(agent_config, tmdb_mock, monkeypatch)
    from lan_streamer.scanner.core import scan_directories

    tv_root = str(agent_config.libraries["tv"]["root_path"])
    return scan_directories(
        root_directories=[tv_root],
        library_type="tv",
        pass_number=1,
        force_refresh=True,
    )


@pytest.fixture
def scanned_movie_data(
    agent_config: AgentConfig,
    database_engine: Engine,
    tmdb_mock: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> LibraryDict:
    """Run the real scanner (pass 1) over the movie root and return the result."""
    _install_and_patch_tmdb(agent_config, tmdb_mock, monkeypatch)
    from lan_streamer.scanner.core import scan_directories

    movie_root = str(agent_config.libraries["movie"]["root_path"])
    return scan_directories(
        root_directories=[movie_root],
        library_type="movie",
        pass_number=1,
        force_refresh=True,
    )
