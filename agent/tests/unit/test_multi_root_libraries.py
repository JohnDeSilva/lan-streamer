"""Unit tests for multi-root libraries on the remote scan agent."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from scan_agent.api.main import create_app
from scan_agent.config import AgentConfig
from scan_agent.db.connection import create_engine_for_database, init_database
from scan_agent.scan.orchestrator import ScanOrchestrator
from scan_agent.scan.progress import ProgressBroker
from scan_agent.scan.watcher import match_library_for_path

if TYPE_CHECKING:
    from pathlib import Path


def test_create_and_patch_multi_root_library(tmp_path: Path) -> None:
    config = AgentConfig(data_directory=tmp_path)
    engine = create_engine_for_database(config.database_path)
    init_database(engine)
    client = TestClient(create_app(agent_config=config, engine=engine))

    create_resp = client.post(
        "/api/v1/sources",
        json={
            "name": "Combined TV",
            "media_type": "tv",
            "root_paths": ["/media/tv", "/archive/tv", "/media/tv"],
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["root_path"] == "/media/tv"
    assert created["root_paths"] == ["/media/tv", "/archive/tv"]

    patch_resp = client.patch(
        f"/api/v1/sources/{created['id']}",
        json={"root_paths": ["/media/tv", "/archive/tv", "/extra/tv"]},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["root_paths"] == [
        "/media/tv",
        "/archive/tv",
        "/extra/tv",
    ]


def test_orchestrator_passes_all_root_paths_and_watcher_matches_all(
    tmp_path: Path,
) -> None:
    config = AgentConfig(data_directory=tmp_path)
    engine = create_engine_for_database(config.database_path)
    init_database(engine)
    broker = ProgressBroker()
    orchestrator = ScanOrchestrator(
        agent_config=config,
        engine=engine,
        progress_broker=broker,
    )

    mock_result = MagicMock()
    mock_result.unavailable_directories = set()
    mock_result.items.return_value = []
    mock_result.__iter__.return_value = iter([])

    with patch(
        "lan_streamer.scanner.core.scan_directories", return_value=mock_result
    ) as mock_scan:
        orchestrator._scan_single_library(
            {
                "name": "Combined TV",
                "media_type": "tv",
                "root_path": "/media/tv",
                "root_paths": ["/media/tv", "/archive/tv"],
            },
            pass_number=1,
            force_refresh=False,
        )
        mock_scan.assert_called_once()
        assert mock_scan.call_args.kwargs["root_directories"] == [
            "/media/tv",
            "/archive/tv",
        ]

    libraries = {
        "combined_tv": {
            "name": "Combined TV",
            "enabled": True,
            "root_path": "/media/tv",
            "root_paths": ["/media/tv", "/archive/tv"],
        }
    }
    assert (
        match_library_for_path("/archive/tv/Show A/S01E01.mkv", libraries)
        == "combined_tv"
    )
