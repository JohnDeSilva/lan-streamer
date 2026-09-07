"""Integration tests for the repository layer against a real scan result."""

from __future__ import annotations

import copy
from pathlib import Path

from sqlalchemy import select

from scan_agent.db.connection import get_session
from scan_agent.db.models import Episode, MediaFile, Series
from scan_agent.db.repository import (
    count_library_items,
    get_library,
    get_movie,
    get_series,
    list_movies,
    list_scan_jobs,
    list_series,
    load_library_dict,
    record_missing_files,
    upsert_library,
    upsert_series_scan,
)


def _tv_library_payload(agent_config, scanned_series_data) -> dict:
    return {
        "name": agent_config.libraries["tv"]["name"],
        "media_type": "tv",
        "root_path": agent_config.libraries["tv"]["root_path"],
        "items": scanned_series_data,
    }


def _movie_library_payload(agent_config, scanned_movie_data) -> dict:
    return {
        "name": agent_config.libraries["movie"]["name"],
        "media_type": "movie",
        "root_path": agent_config.libraries["movie"]["root_path"],
        "items": scanned_movie_data,
    }


def test_upsert_library_persists_series_and_seasons(
    database_engine, agent_config, scanned_series_data
) -> None:
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        stats = upsert_library(session, payload)
    assert stats["series"] == 1
    assert stats["seasons"] == 1
    assert stats["episodes"] == 2

    with get_session(database_engine) as session:
        series_list = list_series(session)
        assert len(series_list) == 1
        assert series_list[0]["folder_name"] == "Test Show"
        assert series_list[0]["name"] == "Test Show"
        seasons = series_list[0]["seasons"]
        assert len(seasons) == 1
        episodes = seasons[0]["episodes"]
        assert len(episodes) == 2


def test_upsert_library_preserves_multiple_media_versions(
    database_engine, agent_config, scanned_series_data
) -> None:
    """The critical AGENTS.md section 7 invariant: 2 files => 2 MediaFile rows."""
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        stats = upsert_library(session, payload)
    assert stats["media_files"] == 3  # S01E01.mkv + S01E01.mp4 + S01E02.mkv

    with get_session(database_engine) as session:
        series = session.scalars(select(Series)).first()
        assert series is not None
        episode_numbers = list_series(session)[0]["seasons"][0]["episodes"]
        first_episode = next(
            episode for episode in episode_numbers if episode["episode_number"] == 1
        )
        version_paths = [version["path"] for version in first_episode["versions"]]
        assert len(version_paths) == 2
        assert any(version_path.endswith(".mkv") for version_path in version_paths)
        assert any(version_path.endswith(".mp4") for version_path in version_paths)


def test_rescan_cleans_stale_media_versions(
    database_engine, agent_config, scanned_series_data
) -> None:
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)

    reduced = copy.deepcopy(scanned_series_data)
    season = next(iter(reduced["Test Show"]["seasons"].values()))
    for episode in season["episodes"]:
        if episode.get("episode_number") == 1:
            episode["versions"] = [
                version
                for version in episode["versions"]
                if version["path"].endswith(".mkv")
            ]
            episode["path"] = episode["versions"][0]["path"]

    with get_session(database_engine) as session:
        upsert_library(session, payload)
        upsert_library(session, {**payload, "items": reduced})

    with get_session(database_engine) as session:
        rows = session.execute(select(MediaFile)).scalars().all()
        quick_media_paths = [row.path for row in rows if "E01" in row.path]
        assert len(quick_media_paths) == 1
        assert quick_media_paths[0].endswith(".mkv")


def test_movie_library_upsert(
    database_engine, agent_config, scanned_movie_data
) -> None:
    payload = _movie_library_payload(agent_config, scanned_movie_data)
    with get_session(database_engine) as session:
        stats = upsert_library(session, payload)
    assert stats["movies"] == 1
    assert stats["media_files"] == 1

    with get_session(database_engine) as session:
        movies = list_movies(session)
        assert len(movies) == 1
        assert movies[0]["folder_name"] == "Some Movie (2020)"


def test_get_series_returns_nested_episodes(
    database_engine, agent_config, scanned_series_data
) -> None:
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)
        series_list = list_series(session)
        series_identifier = series_list[0]["id"]

    with get_session(database_engine) as session:
        detail = get_series(session, series_identifier)
        assert detail is not None
        first_episode = detail["seasons"][0]["episodes"][0]
        assert first_episode["episode_number"] == 1
        assert first_episode["name"].startswith("Test.Show.S01E01")
        season_directory = (
            Path(agent_config.libraries["tv"]["root_path"]) / "Test Show" / "Season 01"
        )
        assert {version["path"] for version in first_episode["versions"]} == {
            str(season_directory / "Test.Show.S01E01.mkv"),
            str(season_directory / "Test.Show.S01E01.mp4"),
        }


def test_get_movie_returns_detail(
    database_engine, agent_config, scanned_movie_data
) -> None:
    payload = _movie_library_payload(agent_config, scanned_movie_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)
        movies = list_movies(session)
        movie_identifier = movies[0]["id"]

    with get_session(database_engine) as session:
        detail = get_movie(session, movie_identifier)
        assert detail is not None
        assert detail["path"] is not None


def test_list_series_filter_and_sort(
    database_engine, agent_config, scanned_series_data
) -> None:
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)
        assert len(list_series(session, query="Test")) == 1
        assert len(list_series(session, query="Missing")) == 0
        assert len(list_series(session, sort="date_added")) == 1


def test_list_scan_jobs(database_engine) -> None:
    from scan_agent.db.models import ScanJob

    with get_session(database_engine) as session:
        session.add(ScanJob(status="done", started_at=100.0))
        session.add(ScanJob(status="running", started_at=200.0))
        session.flush()

    with get_session(database_engine) as session:
        jobs = list_scan_jobs(session, limit=1)
        assert len(jobs) == 1
        assert jobs[0]["status"] == "running"
        assert len(list_scan_jobs(session)) == 2


def test_count_library_items(
    database_engine, agent_config, scanned_series_data, scanned_movie_data
) -> None:
    with get_session(database_engine) as session:
        upsert_library(session, _tv_library_payload(agent_config, scanned_series_data))
        upsert_library(
            session, _movie_library_payload(agent_config, scanned_movie_data)
        )
        counts = count_library_items(session)
    assert counts["series"] == 1
    assert counts["movies"] == 1
    assert counts["episodes"] == 2


def test_load_library_dict_round_trips_into_scanner(
    database_engine, agent_config, scanned_series_data, monkeypatch
) -> None:
    """Prove the existing_library shape we emit is accepted by scan_directories."""
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)
        tv_library = get_library(session, agent_config.libraries["tv"]["name"])
        assert tv_library is not None
        loaded = load_library_dict(session, tv_library.id)

    from lan_streamer.scanner.core import scan_directories

    from scan_agent.config import install_into_lan_streamer

    install_into_lan_streamer(agent_config)
    root_path = agent_config.libraries["tv"]["root_path"]
    result = scan_directories(
        root_directories=[root_path],
        library_type="tv",
        existing_library=loaded,
        force_refresh=False,
        pass_number=1,
    )
    assert "Test Show" in result


def test_upsert_series_scan_persists_single_series(
    database_engine, agent_config, scanned_series_data, scanned_movie_data
) -> None:
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)
        tv_library = get_library(session, agent_config.libraries["tv"]["name"])
        assert tv_library is not None
        series_data = scanned_series_data["Test Show"]
        stats = upsert_series_scan(session, tv_library.id, "Test Show", series_data)
    assert stats["episodes"] == 2


def test_record_missing_files_marks_removed_episodes(
    database_engine, agent_config, scanned_series_data, tmp_path
) -> None:
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)
        tv_library = get_library(session, agent_config.libraries["tv"]["name"])
        assert tv_library is not None

    # Simulate a scan where every episode file is gone.
    emptied = copy.deepcopy(scanned_series_data)
    season = next(iter(emptied["Test Show"]["seasons"].values()))
    for episode in season["episodes"]:
        episode["path"] = None

    with get_session(database_engine) as session:
        missing_count = record_missing_files(session, tv_library.id, emptied)
    assert missing_count == 2

    with get_session(database_engine) as session:
        episodes = session.scalars(select(Episode)).all()
        assert all(episode.is_missing for episode in episodes)
