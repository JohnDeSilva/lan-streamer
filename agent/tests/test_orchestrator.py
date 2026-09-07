"""Integration tests for the ScanOrchestrator background scan lifecycle."""

from __future__ import annotations

import time

import pytest

from scan_agent.db.connection import get_session
from scan_agent.db.repository import list_scan_jobs, list_series
from scan_agent.scan.orchestrator import ScanOrchestrator
from scan_agent.scan.progress import ProgressBroker


def _wait_for_scan_finish(
    orchestrator: ScanOrchestrator, timeout_seconds: float = 30.0
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = orchestrator.status()
        if status["running"] is None:
            return status
        time.sleep(0.05)
    raise AssertionError("Scan did not finish within timeout")


def test_start_scan_runs_pass_one_and_persists(database_engine, agent_config) -> None:
    broker = ProgressBroker()
    events: list[dict] = []
    broker.subscribe(lambda event: events.append(event))  # noqa: PLW0108
    orchestrator = ScanOrchestrator(agent_config, database_engine, broker)

    job = orchestrator.start_scan(library_identifier="tv", pass_number=1)
    status = _wait_for_scan_finish(orchestrator)

    assert job.status == "pending"
    assert status["running"] is None
    assert status["last_job"]["status"] == "done"
    assert status["last_job"]["pass_number"] == 1
    assert any(event["event"] == "scan.finished" for event in events)

    with get_session(database_engine) as session:
        series_list = list_series(session)
        assert len(series_list) == 1
        assert series_list[0]["folder_name"] == "Test Show"
        seasons = series_list[0]["seasons"]
        assert len(seasons) == 1
        first_episode_versions = seasons[0]["episodes"][0]["versions"]
        assert len(first_episode_versions) == 2


def test_full_scan_degrades_gracefully_without_ffprobe(
    database_engine, agent_config, monkeypatch, caplog
) -> None:
    import shutil

    monkeypatch.setattr(
        shutil,
        "which",
        lambda command: None if command == "ffprobe" else shutil.which(command),
    )
    orchestrator = ScanOrchestrator(agent_config, database_engine, ProgressBroker())

    orchestrator.start_scan(library_identifier="tv", pass_number=0)
    status = _wait_for_scan_finish(orchestrator)

    assert status["last_job"]["status"] == "done"
    assert any("ffprobe not found" in record.message for record in caplog.records)


def test_cancel_stops_running_scan(database_engine, tmp_path, agent_config) -> None:
    # Build a wide library so the scan takes long enough to cancel mid-flight.
    wide_root = tmp_path / "wide"
    for index in range(80):
        show_directory = wide_root / f"Wide Show {index:02d}" / "Season 01"
        show_directory.mkdir(parents=True)
        (show_directory / f"Wide.Show.{index:02d}.S01E01.mkv").write_bytes(b"fake")
    agent_config.libraries["tv"] = {
        "name": "TV Shows",
        "media_type": "tv",
        "root_path": str(wide_root),
    }

    orchestrator = ScanOrchestrator(agent_config, database_engine, ProgressBroker())
    orchestrator.start_scan(library_identifier="tv", pass_number=1)
    orchestrator.cancel()
    status = _wait_for_scan_finish(orchestrator)
    assert status["is_interrupted"] is True
    assert status["last_job"]["status"] == "cancelled"


def test_concurrent_scan_raises_runtime_error(
    database_engine, tmp_path, agent_config
) -> None:
    wide_root = tmp_path / "wide"
    for index in range(80):
        show_directory = wide_root / f"Wide Show {index:02d}" / "Season 01"
        show_directory.mkdir(parents=True)
        (show_directory / f"Wide.Show.{index:02d}.S01E01.mkv").write_bytes(b"fake")
    agent_config.libraries["tv"] = {
        "name": "TV Shows",
        "media_type": "tv",
        "root_path": str(wide_root),
    }

    orchestrator = ScanOrchestrator(agent_config, database_engine, ProgressBroker())
    orchestrator.start_scan(library_identifier="tv", pass_number=1)
    with pytest.raises(RuntimeError, match="already running"):
        orchestrator.start_scan(library_identifier="movie", pass_number=1)
    _wait_for_scan_finish(orchestrator)


def test_unknown_library_raises_value_error(database_engine, agent_config) -> None:
    orchestrator = ScanOrchestrator(agent_config, database_engine, ProgressBroker())
    with pytest.raises(ValueError, match="Unknown library"):
        orchestrator.start_scan(library_identifier="does-not-exist", pass_number=1)


def test_scan_all_libraries_when_no_identifier(database_engine, agent_config) -> None:
    orchestrator = ScanOrchestrator(agent_config, database_engine, ProgressBroker())
    job = orchestrator.start_scan(pass_number=1)
    status = _wait_for_scan_finish(orchestrator)
    assert job.status == "pending"
    assert status["last_job"]["status"] == "done"
    with get_session(database_engine) as session:
        series_list = list_series(session)
        assert any(entry["folder_name"] == "Test Show" for entry in series_list)


def test_scan_jobs_are_recorded(database_engine, agent_config) -> None:
    orchestrator = ScanOrchestrator(agent_config, database_engine, ProgressBroker())
    orchestrator.start_scan(library_identifier="tv", pass_number=1)
    _wait_for_scan_finish(orchestrator)
    with get_session(database_engine) as session:
        jobs = list_scan_jobs(session)
        assert len(jobs) == 1
        assert jobs[0]["status"] == "done"
