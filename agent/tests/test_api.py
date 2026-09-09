"""End-to-end REST API tests for the scan agent."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from scan_agent.db.connection import create_engine_for_database, init_database

if TYPE_CHECKING:
    from collections.abc import Iterator
    from unittest.mock import MagicMock

    from fastapi import FastAPI

    from scan_agent.config import AgentConfig


@pytest.fixture
def api_app(
    agent_config: AgentConfig,
    tmdb_mock: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[FastAPI]:
    """Build a FastAPI app bound to a fresh tmp database with TMDB mocked."""
    init_database(create_engine_for_database(agent_config.database_path))
    from tests.conftest import _install_and_patch_tmdb

    _install_and_patch_tmdb(agent_config, tmdb_mock, monkeypatch)
    from scan_agent.api.main import create_app

    application = create_app(agent_config=agent_config)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def api_client(api_app: FastAPI) -> Iterator[TestClient]:
    """Yield a TestClient wrapping the API app."""
    with TestClient(api_app) as client:
        yield client


def _start_scan_and_wait(api_app: FastAPI, **payload: Any) -> None:
    """Start a scan and poll until the orchestrator reports idle."""
    orchestrator = api_app.state.orchestrator
    orchestrator.start_scan(**payload)
    _wait_for_idle(api_app)


def _wait_for_idle(api_app: FastAPI) -> None:
    """Poll the orchestrator until no scan is running."""
    orchestrator = api_app.state.orchestrator
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if orchestrator.status()["running"] is None:
            return
        time.sleep(0.05)
    raise AssertionError("Scan did not finish within timeout")


def test_health_reports_providers(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tmdb_configured"] is True
    assert isinstance(body["libraries"], int)


def test_config_get_masks_password(api_app: FastAPI, api_client: TestClient) -> None:
    api_app.state.agent_config.opensubtitles_password = "hunter2"
    body = api_client.get("/api/v1/config").json()
    assert body["opensubtitles_password"] == "*****"


def test_config_put_keeps_password_when_blank_or_masked(
    api_app: FastAPI, api_client: TestClient
) -> None:
    config = api_app.state.agent_config
    config.opensubtitles_password = "old-secret"
    for blank_value in ("", "*****"):
        response = api_client.put(
            "/api/v1/config", json={"opensubtitles_password": blank_value}
        )
        assert response.status_code == 200
        assert config.opensubtitles_password == "old-secret"
    response = api_client.put(
        "/api/v1/config", json={"opensubtitles_password": "new-secret"}
    )
    assert response.json()["opensubtitles_password"] == "*****"
    assert config.opensubtitles_password == "new-secret"


def test_config_put_updates_other_keys(api_client: TestClient) -> None:
    response = api_client.put(
        "/api/v1/config", json={"scan_concurrency": 4, "tmdb_api_key": "abc123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scan_concurrency"] == 4
    assert body["tmdb_api_key"] == "abc123"


def test_config_get_and_put_log_level(api_client: TestClient) -> None:
    initial_config = api_client.get("/api/v1/config").json()
    assert initial_config["log_level"] == "INFO"

    response = api_client.put("/api/v1/config", json={"log_level": "DEBUG"})
    assert response.status_code == 200
    assert response.json()["log_level"] == "DEBUG"

    updated_config = api_client.get("/api/v1/config").json()
    assert updated_config["log_level"] == "DEBUG"


def test_libraries_crud(api_client: TestClient) -> None:
    listing = api_client.get("/api/v1/libraries").json()
    assert {entry["id"] for entry in listing} == {"tv", "movie"}

    created = api_client.post(
        "/api/v1/libraries",
        json={
            "name": "Anime",
            "media_type": "anime",
            "root_path": "/srv/anime",
            "enabled": True,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["id"] == "anime"
    assert body["media_type"] == "anime"
    assert body["counts"]["series"] == 0

    patched = api_client.patch(
        "/api/v1/libraries/anime", json={"root_path": "/srv/renamed-anime"}
    )
    assert patched.status_code == 200
    assert patched.json()["root_path"] == "/srv/renamed-anime"

    response = api_client.delete("/api/v1/libraries/anime")
    assert response.status_code == 204
    detail = api_client.patch("/api/v1/libraries/anime", json={"name": "gone"})
    assert detail.status_code == 404


def test_scan_unknown_library_returns_404(
    api_client: TestClient, api_app: FastAPI
) -> None:
    response = api_client.post("/api/v1/scan", json={"library_id": "does-not-exist"})
    assert response.status_code == 404


def test_scan_conflict_when_already_running(
    api_app: FastAPI, api_client: TestClient
) -> None:
    api_app.state.orchestrator._running_job_id = 999
    response = api_client.post("/api/v1/scan", json={"library_id": "tv"})
    assert response.status_code == 409


def test_scan_cancel_returns_accepted(api_app: FastAPI, api_client: TestClient) -> None:
    response = api_client.post("/api/v1/scan/cancel")
    assert response.status_code == 202
    assert response.json()["status"] == "cancellation_requested"


def test_scan_jobs_and_browse_after_scan(
    api_app: FastAPI, api_client: TestClient
) -> None:
    job_id = api_client.post(
        "/api/v1/scan", json={"library_id": "tv", "pass_number": 1}
    ).json()["job"]["id"]
    _wait_for_idle(api_app)

    jobs = api_client.get("/api/v1/scan/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id

    series = api_client.get("/api/v1/library/series").json()
    assert len(series) == 1
    assert series[0]["folder_name"] == "Test Show"

    tv_series = api_client.get(
        "/api/v1/library/series", params={"library_type": "tv"}
    ).json()
    assert len(tv_series) == 1
    assert tv_series[0]["folder_name"] == "Test Show"

    anime_series = api_client.get(
        "/api/v1/library/series", params={"library_type": "anime"}
    ).json()
    assert len(anime_series) == 0

    series_identifier = series[0]["id"]
    detail = api_client.get(f"/api/v1/library/series/{series_identifier}").json()
    assert len(detail["seasons"]) == 1

    episodes = detail["seasons"][0]["episodes"]
    assert len(episodes) == 2
    assert len(episodes[0]["versions"]) == 2

    flattened = api_client.get(
        f"/api/v1/library/series/{series_identifier}/episodes"
    ).json()
    assert len(flattened) == 2
    assert flattened[0]["season_number"] == 1
    assert len(flattened[0]["versions"]) == 2


def test_browse_library_id_filtering(api_app: FastAPI, api_client: TestClient) -> None:
    api_client.post("/api/v1/scan", json={"library_id": "tv", "pass_number": 1})
    _wait_for_idle(api_app)
    api_client.post("/api/v1/scan", json={"library_id": "movie", "pass_number": 1})
    _wait_for_idle(api_app)

    # Filter series by config key "tv"
    series_results = api_client.get(
        "/api/v1/library/series", params={"library_id": "tv"}
    ).json()
    assert len(series_results) == 1
    assert series_results[0]["name"] == "Test Show"

    # Filter series by non-matching library_id (e.g. "movie")
    empty_series_results = api_client.get(
        "/api/v1/library/series", params={"library_id": "movie"}
    ).json()
    assert len(empty_series_results) == 0

    # Filter movies by config key "movie"
    movie_results = api_client.get(
        "/api/v1/library/movies", params={"library_id": "movie"}
    ).json()
    assert len(movie_results) == 1
    assert movie_results[0]["name"] == "Some Movie (2020)"

    # Filter movies by non-matching library_id (e.g. "tv")
    empty_movie_results = api_client.get(
        "/api/v1/library/movies", params={"library_id": "tv"}
    ).json()
    assert len(empty_movie_results) == 0

    # Filter episodes by config key "tv"
    episode_results = api_client.get(
        "/api/v1/library/episodes", params={"library_id": "tv"}
    ).json()
    assert len(episode_results) >= 2

    # Filter episodes by non-matching library_id (e.g. "movie")
    empty_episode_results = api_client.get(
        "/api/v1/library/episodes", params={"library_id": "movie"}
    ).json()
    assert len(empty_episode_results) == 0


def test_browse_episodes_filter_and_scan_logs(
    api_app: FastAPI, api_client: TestClient
) -> None:
    api_client.post("/api/v1/scan", json={"library_id": "tv", "pass_number": 1})
    _wait_for_idle(api_app)

    all_episodes = api_client.get("/api/v1/library/episodes").json()
    assert len(all_episodes) == 2
    assert all_episodes[0]["series_name"] == "Test Show"

    tv_episodes = api_client.get(
        "/api/v1/library/episodes", params={"library_type": "tv"}
    ).json()
    assert len(tv_episodes) == 2

    anime_episodes = api_client.get(
        "/api/v1/library/episodes", params={"library_type": "anime"}
    ).json()
    assert len(anime_episodes) == 0

    query_episodes = api_client.get(
        "/api/v1/library/episodes", params={"query": "S01E01"}
    ).json()
    assert len(query_episodes) == 1
    assert query_episodes[0]["episode_number"] == 1

    unwatched_episodes = api_client.get(
        "/api/v1/library/episodes", params={"watched": False}
    ).json()
    assert len(unwatched_episodes) == 2

    broker = api_app.state.progress_broker
    broker.publish_log("Test runner log message", level="INFO")

    logs = api_client.get("/api/v1/scan/logs").json()
    assert len(logs) >= 1
    assert any("Test runner log message" in log["message"] for log in logs)


def test_scan_logs_level_filtering(api_app: FastAPI, api_client: TestClient) -> None:
    broker = api_app.state.progress_broker
    broker.publish_log("Debug detail line", level="DEBUG")
    broker.publish_log("Standard info line", level="INFO")
    broker.publish_log("Warning notice line", level="WARNING")
    broker.publish_log("Error critical failure line", level="ERROR")

    all_logs = api_client.get("/api/v1/scan/logs", params={"level": "ALL"}).json()
    all_messages = [log["message"] for log in all_logs]
    assert "Debug detail line" in all_messages
    assert "Standard info line" in all_messages
    assert "Warning notice line" in all_messages
    assert "Error critical failure line" in all_messages

    debug_logs = api_client.get("/api/v1/scan/logs", params={"level": "DEBUG"}).json()
    debug_messages = [log["message"] for log in debug_logs]
    assert "Debug detail line" in debug_messages
    assert "Standard info line" in debug_messages

    info_logs = api_client.get("/api/v1/scan/logs", params={"level": "INFO"}).json()
    info_messages = [log["message"] for log in info_logs]
    assert "Debug detail line" not in info_messages
    assert "Standard info line" in info_messages
    assert "Warning notice line" in info_messages
    assert "Error critical failure line" in info_messages

    warning_logs = api_client.get(
        "/api/v1/scan/logs", params={"level": "WARNING"}
    ).json()
    warning_messages = [log["message"] for log in warning_logs]
    assert "Debug detail line" not in warning_messages
    assert "Standard info line" not in warning_messages
    assert "Warning notice line" in warning_messages
    assert "Error critical failure line" in warning_messages

    error_logs = api_client.get("/api/v1/scan/logs", params={"level": "ERROR"}).json()
    error_messages = [log["message"] for log in error_logs]
    assert "Debug detail line" not in error_messages
    assert "Standard info line" not in error_messages
    assert "Warning notice line" not in error_messages
    assert "Error critical failure line" in error_messages


def test_library_items_export_endpoint(
    api_app: FastAPI, api_client: TestClient
) -> None:
    api_client.post("/api/v1/scan", json={"library_id": "tv", "pass_number": 1})
    _wait_for_idle(api_app)

    items_response = api_client.get("/api/v1/libraries/tv/items")
    assert items_response.status_code == 200
    items = items_response.json()
    assert "Test Show" in items
    assert "seasons" in items["Test Show"]

    not_found = api_client.get("/api/v1/libraries/nonexistent_lib/items")
    assert not_found.status_code == 404

    # Configured but unscanned library should return empty dict rather than 404
    empty_response = api_client.get("/api/v1/libraries/movie/items")
    assert empty_response.status_code == 200
    assert empty_response.json() == {}


def test_browse_movies_and_query_filter(
    api_app: FastAPI, api_client: TestClient
) -> None:
    api_client.post("/api/v1/scan", json={"library_id": "movie", "pass_number": 1})
    _wait_for_idle(api_app)

    movies = api_client.get("/api/v1/library/movies").json()
    assert len(movies) == 1
    assert movies[0]["folder_name"] == "Some Movie (2020)"

    movies_identifier = movies[0]["id"]
    detail = api_client.get(f"/api/v1/library/movie/{movies_identifier}").json()
    assert len(detail["versions"]) == 1
    detail_plural = api_client.get(f"/api/v1/library/movies/{movies_identifier}").json()
    assert len(detail_plural["versions"]) == 1

    filtered = api_client.get(
        "/api/v1/library/movies", params={"query": "Some Movie"}
    ).json()
    assert len(filtered) == 1
    filtered = api_client.get("/api/v1/library/movies", params={"query": "Nope"}).json()
    assert filtered == []


def test_watch_state_and_events(api_app: FastAPI, api_client: TestClient) -> None:
    api_client.post("/api/v1/scan", json={"library_id": "tv", "pass_number": 1})
    _wait_for_idle(api_app)
    episode_identifier = api_client.get("/api/v1/library/series").json()[0]["seasons"][
        0
    ]["episodes"][0]["id"]

    created = api_client.post(
        "/api/v1/watch/events",
        json={
            "media_type": "episode",
            "media_id": episode_identifier,
            "event": "complete",
            "position_seconds": 1234.5,
        },
    )
    assert created.status_code == 201
    assert created.json()["event"] == "complete"

    state = api_client.get(f"/api/v1/watch/episode/{episode_identifier}/state").json()
    assert state["watched"] is True
    assert state["position_seconds"] == 1234.5

    events = api_client.get(f"/api/v1/watch/episode/{episode_identifier}/events").json()
    assert events[0]["event"] == "complete"


def test_watch_event_updates_movie_watched_flag(
    api_app: FastAPI, api_client: TestClient
) -> None:
    api_client.post("/api/v1/scan", json={"library_id": "movie", "pass_number": 1})
    _wait_for_idle(api_app)
    movie_identifier = api_client.get("/api/v1/library/movies").json()[0]["id"]
    created = api_client.post(
        "/api/v1/watch/events",
        json={
            "media_type": "movie",
            "media_id": movie_identifier,
            "event": "complete",
        },
    )
    assert created.status_code == 201
    state = api_client.get(f"/api/v1/watch/movie/{movie_identifier}/state").json()
    assert state["watched"] is True


def test_metadata_search_and_match(api_client: TestClient) -> None:
    response = api_client.get(
        "/api/v1/services/metadata/search",
        params={"type": "series", "query": "Test"},
    )
    assert response.status_code == 200
    matches = response.json()["matches"]
    assert matches[0]["name"] == "Test Show"

    # Also test media_type param and "tv" alias normalization
    response_tv = api_client.get(
        "/api/v1/services/metadata/search",
        params={"media_type": "tv", "query": "Test"},
    )
    assert response_tv.status_code == 200
    assert response_tv.json()["type"] == "series"

    # Missing media_type/type parameter returns 422
    response_missing = api_client.get(
        "/api/v1/services/metadata/search",
        params={"query": "Test"},
    )
    assert response_missing.status_code == 422

    response = api_client.get(
        "/api/v1/services/metadata/search",
        params={"type": "movie", "query": "Some Movie"},
    )
    assert response.status_code == 200
    assert response.json()["matches"][0]["title"] == "Some Movie"


def test_metadata_match_updates_series(
    api_app: FastAPI, api_client: TestClient
) -> None:
    api_client.post("/api/v1/scan", json={"library_id": "tv", "pass_number": 1})
    _wait_for_idle(api_app)
    series_identifier = api_client.get("/api/v1/library/series").json()[0]["id"]

    # Before match, episode names are from file discovery stubs
    initial_detail = api_client.get(
        f"/api/v1/library/series/{series_identifier}"
    ).json()
    assert initial_detail["seasons"][0]["episodes"][0]["name"] != "Pilot"

    response = api_client.post(
        f"/api/v1/services/metadata/series/{series_identifier}/match",
        json={"tmdb_identifier": "999"},
    )
    assert response.status_code == 202
    assert response.json()["rescan_required"] is False
    assert response.json()["media"]["tmdb_identifier"] == "999"

    detail = api_client.get(f"/api/v1/library/series/{series_identifier}").json()
    assert detail["tmdb_identifier"] == "999"
    assert detail["locked_metadata"] is True
    assert detail["name"] == "Test Show"
    assert detail["year"] == 2024

    # Assert episodes have their names updated to TMDB episode names
    assert len(detail["seasons"]) >= 1
    season_one = detail["seasons"][0]
    episodes = season_one["episodes"]
    assert len(episodes) >= 2
    episode_by_number = {episode["episode_number"]: episode for episode in episodes}
    assert episode_by_number[1]["name"] == "Pilot"
    assert episode_by_number[2]["name"] == "Second"
    # Verify versions are preserved on episode 1 (which had two files: .mkv and .mp4)
    assert len(episode_by_number[1]["versions"]) == 2

    # Also test "tv" alias in path
    response_tv_match = api_client.post(
        f"/api/v1/services/metadata/tv/{series_identifier}/match",
        json={"tmdb_identifier": "888"},
    )
    assert response_tv_match.status_code == 202
    assert response_tv_match.json()["rescan_required"] is False
    assert response_tv_match.json()["media"]["tmdb_identifier"] == "888"


def test_metadata_match_unknown_media_returns_404(
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/v1/services/metadata/series/424242/match",
        json={"tmdb_identifier": "999"},
    )
    assert response.status_code == 404

    response_movie = api_client.post(
        "/api/v1/services/metadata/movie/424242/match",
        json={"tmdb_identifier": "999"},
    )
    assert response_movie.status_code == 404


def test_metadata_match_updates_movie(api_app: FastAPI, api_client: TestClient) -> None:
    api_client.post("/api/v1/scan", json={"library_id": "movie", "pass_number": 1})
    _wait_for_idle(api_app)
    movie_identifier = api_client.get("/api/v1/library/movies").json()[0]["id"]

    response = api_client.post(
        f"/api/v1/services/metadata/movie/{movie_identifier}/match",
        json={"tmdb_identifier": "200"},
    )
    assert response.status_code == 202
    assert response.json()["rescan_required"] is False
    assert response.json()["media"]["tmdb_identifier"] == "200"

    detail = api_client.get(f"/api/v1/library/movies/{movie_identifier}").json()
    assert detail["tmdb_identifier"] == "200"
    assert detail["locked_metadata"] is True
    assert detail["name"] == "Some Movie"
    assert detail["runtime_seconds"] == 120 * 60


def test_metadata_tmdb_series_seasons_and_episodes(api_client: TestClient) -> None:
    seasons_response = api_client.get(
        "/api/v1/services/metadata/tmdb/series/999/seasons"
    )
    assert seasons_response.status_code == 200
    seasons = seasons_response.json()["seasons"]
    assert len(seasons) >= 1
    assert seasons[0]["season_number"] == 1

    episodes_response = api_client.get(
        "/api/v1/services/metadata/tmdb/series/999/episodes",
        params={"season_number": 1},
    )
    assert episodes_response.status_code == 200
    episodes = episodes_response.json()["episodes"]
    assert len(episodes) >= 1
    assert episodes[0]["name"] == "Pilot"


def test_metadata_manual_map_updates_episodes(
    api_app: FastAPI, api_client: TestClient
) -> None:
    api_client.post("/api/v1/scan", json={"library_id": "tv", "pass_number": 1})
    _wait_for_idle(api_app)
    series_identifier = api_client.get("/api/v1/library/series").json()[0]["id"]

    series_detail = api_client.get(f"/api/v1/library/series/{series_identifier}").json()
    episode_target = series_detail["seasons"][0]["episodes"][0]
    target_path = episode_target["path"]
    assert target_path is not None

    mapping_payload = {
        "episode_mappings": [
            {
                "path": target_path,
                "tmdb_identifier": "999",
                "tmdb_episode_identifier": "1001",
                "name": "Manually Mapped Episode",
                "episode_number": 1,
                "season_number": 1,
                "air_date": "2024-01-01",
                "overview": "Manually mapped overview description",
                "runtime_seconds": 1800,
            }
        ]
    }

    response = api_client.post(
        f"/api/v1/services/metadata/series/{series_identifier}/manual-map",
        json=mapping_payload,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "applied"

    updated_detail = api_client.get(
        f"/api/v1/library/series/{series_identifier}"
    ).json()
    assert updated_detail["locked_metadata"] is True
    updated_episode = updated_detail["seasons"][0]["episodes"][0]
    assert updated_episode["name"] == "Manually Mapped Episode"
    assert updated_episode["overview"] == "Manually mapped overview description"
    assert updated_episode["runtime_seconds"] == 1800


def test_metadata_manual_map_unknown_series_returns_404(
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/v1/services/metadata/series/999999/manual-map",
        json={"episode_mappings": []},
    )
    assert response.status_code == 404


def test_metadata_tmdb_series_seasons_and_episodes_error_cases(
    api_client: TestClient,
) -> None:
    # Invalid non-numeric TMDB identifier for episodes returns 422
    response_invalid = api_client.get(
        "/api/v1/services/metadata/tmdb/series/invalid-id/episodes"
    )
    assert response_invalid.status_code == 422

    # Unknown series for seasons returns 404 when get_series_by_id returns None
    from lan_streamer.providers.tmdb import tmdb_client

    original_get_series = tmdb_client.get_series_by_id
    try:
        tmdb_client.get_series_by_id = lambda identifier: None
        response_not_found = api_client.get(
            "/api/v1/services/metadata/tmdb/series/999999/seasons"
        )
        assert response_not_found.status_code == 404
    finally:
        tmdb_client.get_series_by_id = original_get_series


def test_rename_preview_and_apply(api_app: FastAPI, api_client: TestClient) -> None:
    api_client.post("/api/v1/scan", json={"library_id": "tv", "pass_number": 1})
    _wait_for_idle(api_app)
    series_identifier = api_client.get("/api/v1/library/series").json()[0]["id"]

    preview_response = api_client.get(
        "/api/v1/services/rename/preview",
        params={
            "media_type": "series",
            "media_id": series_identifier,
            "template": "{SeriesTitle} - S{SeasonNumber:02d}E{EpisodeNumber:02d}",
        },
    )
    assert preview_response.status_code == 200
    previews = preview_response.json()
    assert len(previews) == 3
    assert all(item["safe"] is True for item in previews)
    assert any("Test Show - S01E01" in item["new_name"] for item in previews)

    dry_run = api_client.post(
        "/api/v1/services/rename/apply",
        json={
            "media_type": "series",
            "media_id": series_identifier,
            "template": "{SeriesTitle} - S{SeasonNumber:02d}E{EpisodeNumber:02d}",
            "dry_run": True,
        },
    )
    assert dry_run.status_code == 200
    assert dry_run.json()["dry_run"] is True
    assert len(dry_run.json()["previews"]) == 3


def test_rename_movie_returns_501(api_client: TestClient) -> None:
    response = api_client.get(
        "/api/v1/services/rename/preview",
        params={"media_type": "movie", "media_id": 1},
    )
    assert response.status_code == 501
    response = api_client.post(
        "/api/v1/services/rename/apply",
        json={"media_type": "movie", "media_id": 1, "dry_run": True},
    )
    assert response.status_code == 501


def test_rename_preview_unknown_series_returns_404(
    api_client: TestClient,
) -> None:
    response = api_client.get(
        "/api/v1/services/rename/preview",
        params={"media_type": "series", "media_id": 424242},
    )
    assert response.status_code == 404


def test_subtitle_search_and_download(
    api_app: FastAPI,
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOpenSubtitlesClient:
        def login(self) -> bool:
            return True

        def get_download_link(self, file_identifier: int) -> str:
            return "http://127.0.0.1/subtitles/test.srt"

        def download_subtitle(self, download_url: str) -> bytes:
            return b"WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.000\nHello"

        def search_subtitles(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"file_id": 7, "language": kwargs.get("languages")}]

    monkeypatch.setattr(
        "lan_streamer.providers.opensubtitles.OpenSubtitlesClient",
        FakeOpenSubtitlesClient,
    )
    import shutil

    monkeypatch.setattr(
        shutil,
        "which",
        lambda command: None if command == "ffprobe" else shutil.which(command),
    )
    api_client.post("/api/v1/scan", json={"library_id": "tv", "pass_number": 0})
    _wait_for_idle(api_app)
    series = api_client.get("/api/v1/library/series").json()[0]
    assert series["tmdb_identifier"] == "100"
    episode_identifier = series["seasons"][0]["episodes"][0]["id"]

    response = api_client.get(
        "/api/v1/services/subtitles",
        params={"media_type": "episode", "media_id": episode_identifier},
    )
    assert response.status_code == 200
    assert response.json() == []

    search = api_client.get(
        "/api/v1/services/subtitles/search",
        params={"media_type": "episode", "media_id": episode_identifier},
    )
    assert search.status_code == 200
    assert search.json()[0]["file_id"] == 7

    downloaded = api_client.post(
        "/api/v1/services/subtitles/7/download",
        json={
            "media_type": "episode",
            "media_id": episode_identifier,
            "language": "en",
        },
    )
    assert downloaded.status_code == 200, (
        f"Expected 200 but got {downloaded.status_code}: {downloaded.text}"
    )
    body = downloaded.json()
    assert body["language"] == "en"
    assert body["path"].endswith(".en.srt")

    stored = api_client.get(
        "/api/v1/services/subtitles",
        params={"media_type": "episode", "media_id": episode_identifier},
    ).json()
    assert len(stored) == 1
    subtitle_path = stored[0]["path"]
    with open(subtitle_path, encoding="utf-8") as subtitle_file:
        assert subtitle_file.read().startswith("WEBVTT")


def test_subtitle_download_rejects_no_file_on_disk(
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/v1/services/subtitles/7/download",
        json={"media_type": "episode", "media_id": 424242, "language": "en"},
    )
    assert response.status_code == 404


def test_sse_resumes_history_and_finishes_on_scan_done(
    api_app: FastAPI, api_client: TestClient
) -> None:
    _start_scan_and_wait(api_app, library_identifier="tv", pass_number=1)

    with api_client.stream("GET", "/api/v1/events?until_finished=1") as response:
        assert response.status_code == 200
        payload = list(response.iter_lines())
    payload_text = "\n".join(payload)
    assert "event: scan.log" in payload_text
    assert "event: scan.finished" in payload_text
    assert (
        f'"sequence": {api_app.state.progress_broker.latest_sequence}' in payload_text
    )


def test_sse_live_event_and_sequence_resume(
    api_app: FastAPI, api_client: TestClient
) -> None:
    broker = api_app.state.progress_broker

    # Publish an event followed by scan.finished to close the stream cleanly
    broker.publish("test.first", {"val": 1})
    broker.publish("scan.finished", {"job_id": 1, "status": "done"})

    with api_client.stream("GET", "/api/v1/events?until_finished=1") as response:
        assert response.status_code == 200
        first_payload = list(response.iter_lines())

    first_text = "\n".join(first_payload)
    assert "event: test.first" in first_text
    assert "event: scan.finished" in first_text

    # Record sequence before publishing second batch
    resume_sequence = broker.latest_sequence

    # Publish a second event followed by scan.finished
    broker.publish("test.second", {"val": 2})
    broker.publish("scan.finished", {"job_id": 2, "status": "done"})

    # Connect with Last-Event-ID header to resume after resume_sequence
    headers = {"last-event-id": str(resume_sequence)}
    with api_client.stream(
        "GET", "/api/v1/events?until_finished=1", headers=headers
    ) as response:
        assert response.status_code == 200
        resumed_payload = list(response.iter_lines())

    resumed_text = "\n".join(resumed_payload)
    # The resumed stream must contain the fresh event but NOT the prior event
    assert "event: test.second" in resumed_text
    assert "event: test.first" not in resumed_text

    # 3. Test live queue event dispatch during an active stream
    def _publish_live() -> None:
        time.sleep(0.05)
        broker.publish("test.live", {"live": True})
        time.sleep(0.05)
        broker.publish("scan.finished", {"job_id": 3, "status": "done"})

    live_thread = threading.Thread(target=_publish_live, daemon=True)
    live_thread.start()

    with api_client.stream(
        "GET",
        "/api/v1/events?until_finished=1",
        headers={"last-event-id": str(broker.latest_sequence)},
    ) as response:
        assert response.status_code == 200
        live_payload = list(response.iter_lines())

    live_thread.join(timeout=1.0)
    live_text = "\n".join(live_payload)
    assert "event: test.live" in live_text
    assert "event: scan.finished" in live_text


def test_count_items_per_library_endpoint(
    api_app: FastAPI, api_client: TestClient
) -> None:
    libraries = api_client.get("/api/v1/libraries").json()
    by_name = {entry["name"]: entry["counts"] for entry in libraries}
    assert by_name["TV Shows"]["series"] == 0
    assert all(value == 0 for counts in by_name.values() for value in counts.values())


def test_static_files_served(api_client: TestClient) -> None:
    response = api_client.get("/")
    assert response.status_code == 200
    assert "LAN Streamer" in response.text

    for filename in ["style.css", "logic.js", "api.js", "app.js", "index.html"]:
        static_response = api_client.get(f"/static/{filename}")
        assert static_response.status_code == 200


def test_serve_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    import uvicorn

    from scan_agent import serve

    serve._ensure_import_path()
    monkeypatch.setattr(sys, "argv", ["scan-agent"])
    mock_run = MagicMock()
    monkeypatch.setattr(uvicorn, "run", mock_run)
    monkeypatch.setattr("scan_agent.api.main.create_app", MagicMock())
    serve.main()
    assert mock_run.called


def test_filesystem_browse_default(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/filesystem/browse")
    assert response.status_code == 200
    payload = response.json()
    assert "current_path" in payload
    assert "directories" in payload
    assert "shortcuts" in payload
    assert isinstance(payload["directories"], list)
    assert isinstance(payload["shortcuts"], list)


def test_filesystem_browse_custom_path(api_client: TestClient, tmp_path: Path) -> None:
    first_folder = tmp_path / "SubfolderA"
    second_folder = tmp_path / "SubfolderB"
    hidden_folder = tmp_path / ".hidden_folder"
    regular_file = tmp_path / "video.mkv"

    first_folder.mkdir()
    second_folder.mkdir()
    hidden_folder.mkdir()
    regular_file.write_text("dummy video content")

    response = api_client.get(
        "/api/v1/filesystem/browse", params={"path": str(tmp_path)}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_path"] == str(tmp_path.resolve())

    directory_names = [entry["name"] for entry in payload["directories"]]
    assert "SubfolderA" in directory_names
    assert "SubfolderB" in directory_names
    assert ".hidden_folder" not in directory_names
    assert "video.mkv" not in directory_names


def test_filesystem_browse_nonexistent_path(api_client: TestClient) -> None:
    response = api_client.get(
        "/api/v1/filesystem/browse",
        params={"path": "/nonexistent/directory/path/that/does/not/exist"},
    )
    assert response.status_code == 404
    assert "Directory does not exist" in response.json()["detail"]


def test_images_poster_empty_path(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/images/poster", params={"path": ""})
    assert response.status_code == 400


def test_images_poster_not_found(api_client: TestClient) -> None:
    response = api_client.get(
        "/api/v1/images/poster", params={"path": "/nonexistent/poster.jpg"}
    )
    assert response.status_code == 404


def test_images_poster_direct_file(api_client: TestClient, tmp_path: Path) -> None:
    image_file = tmp_path / "poster.jpg"
    image_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIFfakejpeg")

    response = api_client.get("/api/v1/images/poster", params={"path": str(image_file)})
    assert response.status_code == 200
    assert response.content == b"\xff\xd8\xff\xe0\x00\x10JFIFfakejpeg"


def test_images_poster_from_cache(
    api_client: TestClient, api_app: FastAPI, tmp_path: Path
) -> None:
    cache_dir = Path(api_app.state.agent_config.cache_directory)
    images_dir = cache_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    cached_image = images_dir / "tmdb_series_test99.jpg"
    cached_image.write_bytes(b"cached_poster_bytes")

    response = api_client.get(
        "/api/v1/images/poster",
        params={"path": "/remote/agent/path/tmdb_series_test99.jpg"},
    )
    assert response.status_code == 200
    assert response.content == b"cached_poster_bytes"


def test_images_poster_from_direct_cache_directory(
    api_client: TestClient, api_app: FastAPI, tmp_path: Path
) -> None:
    cache_dir = Path(api_app.state.agent_config.cache_directory)
    cache_dir.mkdir(parents=True, exist_ok=True)
    direct_image = cache_dir / "direct_poster_test.jpg"
    direct_image.write_bytes(b"direct_cached_poster")

    response = api_client.get(
        "/api/v1/images/poster",
        params={"path": "direct_poster_test.jpg"},
    )
    assert response.status_code == 200
    assert response.content == b"direct_cached_poster"


def test_images_poster_from_tmdb_cached(
    api_client: TestClient,
    api_app: FastAPI,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached_tmdb_file = tmp_path / "tmdb_mocked_poster.jpg"
    cached_tmdb_file.write_bytes(b"tmdb_mock_bytes")

    from lan_streamer.providers.tmdb import tmdb_client

    monkeypatch.setattr(
        tmdb_client, "get_cached_image", lambda stem: str(cached_tmdb_file)
    )

    response = api_client.get(
        "/api/v1/images/poster",
        params={"path": "tmdb_mocked_poster.jpg"},
    )
    assert response.status_code == 200
    assert response.content == b"tmdb_mock_bytes"


def test_sse_queue_drops_oldest_when_full() -> None:
    """The per-client SSE queue is bounded and drops the oldest event."""
    import asyncio

    from scan_agent.api.routes_scan import _put_message_on_queue

    async def run() -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2)
        await queue.put({"sequence": 1})
        await queue.put({"sequence": 2})
        _put_message_on_queue(queue, {"sequence": 3})
        _put_message_on_queue(queue, {"sequence": 4})
        remaining = [await queue.get() for _ in range(queue.qsize())]
        assert [entry["sequence"] for entry in remaining] == [3, 4]

    asyncio.run(run())


def test_sse_enqueue_ignores_closed_event_loop() -> None:
    """Enqueueing after the loop closed must not raise."""
    import asyncio

    from scan_agent.api.routes_scan import _enqueue_after_loop_close_safe

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    loop.close()
    _enqueue_after_loop_close_safe(
        loop, queue, {"sequence": 1, "event": "ping", "payload": {}}
    )
