"""Unit tests for MyAnimeList agent routes and watch-event sync."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from scan_agent.api.main import create_app
from scan_agent.config import AgentConfig
from scan_agent.db.connection import create_engine_for_database, init_database
from scan_agent.db.models import Episode, Library, Season, Series


def _build_test_client(tmp_path: Path) -> tuple[TestClient, AgentConfig, object]:
    config = AgentConfig(data_directory=tmp_path)
    engine = create_engine_for_database(config.database_path)
    init_database(engine)
    app = create_app(agent_config=config, engine=engine)
    return TestClient(app), config, engine


def test_mal_config_and_auth_routes(tmp_path: Path) -> None:
    client, config, _ = _build_test_client(tmp_path)

    resp = client.get("/api/v1/services/myanimelist/status")
    assert resp.status_code == 200
    assert resp.json()["configured"] is False
    assert resp.json()["authenticated"] is False

    update_resp = client.put(
        "/api/v1/config",
        json={"myanimelist_client_id": "test-client-id", "myanimelist_client_secret": "secret"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["myanimelist_client_id"] == "test-client-id"
    assert update_resp.json()["myanimelist_client_secret"] == "*****"

    mock_mal = MagicMock()
    mock_mal.is_configured.return_value = True
    mock_mal.is_authenticated.return_value = False
    mock_mal.generate_auth_url.return_value = "https://myanimelist.example.invalid/auth"
    mock_mal.exchange_auth_code.return_value = (True, "Authentication successful!")

    with patch("scan_agent.api.routes_mal._myanimelist_client", return_value=mock_mal):
        url_resp = client.post("/api/v1/services/myanimelist/auth/url")
        assert url_resp.status_code == 200
        assert url_resp.json()["auth_url"] == "https://myanimelist.example.invalid/auth"

        exchange_resp = client.post(
            "/api/v1/services/myanimelist/auth/exchange",
            json={"code": "http://localhost/?code=auth-code-123"},
        )
        assert exchange_resp.status_code == 200
        mock_mal.exchange_auth_code.assert_called_once()
        assert mock_mal.exchange_auth_code.call_args[0][0] == "auth-code-123"


def test_watch_event_triggers_agent_mal_update(tmp_path: Path) -> None:
    from sqlalchemy.orm import Session

    client, _, engine = _build_test_client(tmp_path)

    with Session(engine) as session:
        lib = Library(name="Anime", media_type="anime", root_path="/media/anime")
        session.add(lib)
        session.flush()
        series = Series(library_id=lib.id, name="Test Anime")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1", myanimelist_id=5555)
        session.add(season)
        session.flush()
        episode = Episode(
            season_id=season.id,
            episode_number=3,
            path="/media/anime/Test Anime/S01E03.mkv",
            myanimelist_anime_id=5555,
            myanimelist_episode_number=3,
        )
        session.add(episode)
        session.commit()
        episode_id = episode.id

    with patch(
        "lan_streamer.providers.myanimelist.trigger_mal_push_async"
    ) as mock_push:
        resp = client.post(
            "/api/v1/watch/events",
            json={
                "media_type": "episode",
                "media_id": episode_id,
                "event": "complete",
                "watched": True,
            },
        )
        assert resp.status_code == 201
        mock_push.assert_called_once_with(5555, 3)
