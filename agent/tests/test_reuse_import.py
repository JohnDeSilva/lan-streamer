"""Headless reuse proof: the desktop scanner runs in a non-Qt process."""

from __future__ import annotations

import sys

from scan_agent.config import AgentConfig, install_into_lan_streamer
from scan_agent.db.connection import get_session


def _install_and_patch_tmdb(agent_config: AgentConfig, tmdb_mock, monkeypatch) -> None:
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


def test_pyside6_never_imported() -> None:
    assert "PySide6" not in sys.modules


def test_scan_resolves_metadata_and_preserves_versions(
    agent_config, media_tree, tmdb_mock, monkeypatch, database_engine
) -> None:
    _install_and_patch_tmdb(agent_config, tmdb_mock, monkeypatch)

    from lan_streamer.scanner.core import LibraryDict, scan_directories

    tv_root = str(agent_config.libraries["tv"]["root_path"])

    discovered = scan_directories(
        root_directories=[tv_root],
        library_type="tv",
        pass_number=1,
        force_refresh=True,
    )
    assert isinstance(discovered, LibraryDict)
    assert "Test Show" in discovered

    resolved = scan_directories(
        root_directories=[tv_root],
        library_type="tv",
        existing_library=discovered,
        pass_number=2,
    )
    series = resolved["Test Show"]
    metadata = series["metadata"]
    assert metadata["tmdb_name"] == "Test Show"
    assert metadata["tmdb_identifier"] == "100"
    assert tmdb_mock.search_series.called

    first_episode = next(iter(series["seasons"].values()))["episodes"][0]
    version_paths = [version["path"] for version in first_episode["versions"]]
    assert len(version_paths) == 2
    assert any(version_path.endswith(".mkv") for version_path in version_paths)
    assert any(version_path.endswith(".mp4") for version_path in version_paths)


def test_full_pipeline_with_agent_database(
    agent_config, media_tree, tmdb_mock, monkeypatch, database_engine
) -> None:
    """Pass 1 -> repository persist -> load_library_dict -> pass 2 end-to-end."""
    _install_and_patch_tmdb(agent_config, tmdb_mock, monkeypatch)

    from lan_streamer.scanner.core import scan_directories

    from scan_agent.db.repository import (
        get_library,
        load_library_dict,
        upsert_library,
    )

    tv_root = str(agent_config.libraries["tv"]["root_path"])
    discovered = scan_directories(
        root_directories=[tv_root],
        library_type="tv",
        pass_number=1,
        force_refresh=True,
    )
    tv_name = agent_config.libraries["tv"]["name"]
    with get_session(database_engine) as session:
        upsert_library(
            session,
            {
                "name": tv_name,
                "media_type": "tv",
                "root_path": tv_root,
                "items": discovered,
            },
        )

    with get_session(database_engine) as session:
        library_row = get_library(session, tv_name)
        assert library_row is not None
        persisted = load_library_dict(session, library_row.id)

    resolved = scan_directories(
        root_directories=[tv_root],
        library_type="tv",
        existing_library=persisted,
        pass_number=2,
    )
    metadata = resolved["Test Show"]["metadata"]
    assert metadata["tmdb_name"] == "Test Show"
