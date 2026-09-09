"""Integration tests for the repository layer against a real scan result."""

from __future__ import annotations

import copy
from pathlib import Path

from sqlalchemy import select

from scan_agent.db.connection import get_session
from scan_agent.db.models import Episode, MediaFile, Movie, Series
from scan_agent.db.repository import (
    _sync_series_tmdb_fallback,
    count_library_items,
    get_library,
    get_movie,
    get_series,
    list_episodes,
    list_movies,
    list_scan_jobs,
    list_series,
    load_library_dict,
    preserve_live_watch_state,
    record_missing_files,
    set_movie_metadata_match,
    set_series_metadata_match,
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
        assert len(list_series(session, library_type="tv")) == 1
        assert len(list_series(session, library_type="anime")) == 0
        assert (
            len(
                list_series(
                    session, library_identifier=payload["name"], library_type="tv"
                )
            )
            == 1
        )
        assert (
            len(
                list_series(
                    session, library_identifier=payload["name"], library_type="anime"
                )
            )
            == 0
        )


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


def test_upsert_library_handles_nine_unnumbered_episodes_without_dropping_any(
    database_engine, agent_config
) -> None:
    nine_episodes = [
        {
            "name": f"Show - {index:02d}",
            "path": f"/media/tv/Test Show/Season 1/Show - {index:02d}.mkv",
            "episode_number": None,
            "tmdb_number": None,
            "versions": [
                {"path": f"/media/tv/Test Show/Season 1/Show - {index:02d}.mkv"}
            ],
        }
        for index in range(1, 10)
    ]
    items = {
        "Test Show": {
            "name": "Test Show",
            "path": "/media/tv/Test Show",
            "metadata": {"name": "Test Show"},
            "seasons": {
                "Season 1": {
                    "name": "Season 1",
                    "metadata": {"season_number": 1},
                    "episodes": nine_episodes,
                }
            },
        }
    }
    payload = {
        "name": agent_config.libraries["tv"]["name"],
        "media_type": "tv",
        "root_path": agent_config.libraries["tv"]["root_path"],
        "items": items,
    }
    with get_session(database_engine) as session:
        stats = upsert_library(session, payload)
    assert stats["episodes"] == 9

    with get_session(database_engine) as session:
        series_list = list_series(session)
        assert len(series_list) == 1
        episodes = series_list[0]["seasons"][0]["episodes"]
        assert len(episodes) == 9
        saved_episodes = session.scalars(select(Episode)).all()
        assert len(saved_episodes) == 9


def test_merge_season_episodes_combines_versions_and_paths() -> None:
    from scan_agent.db.repository import _merge_season_episodes

    existing = [
        {
            "name": "Ep 1",
            "path": "/media/tv/show/s1/ep1.mkv",
            "episode_number": 1,
            "versions": [{"path": "/media/tv/show/s1/ep1.mkv"}],
            "watched": True,
        }
    ]
    incoming = [
        {
            "name": "Ep 1 Renamed",
            "path": "/media/tv/show/s1/ep1.mp4",
            "episode_number": 1,
            "versions": [{"path": "/media/tv/show/s1/ep1.mp4"}],
            "watched": False,
        },
        {
            "name": "Ep 2",
            "path": "/media/tv/show/s1/ep2.mkv",
            "episode_number": 2,
            "versions": [{"path": "/media/tv/show/s1/ep2.mkv"}],
        },
    ]
    merged = _merge_season_episodes(existing, incoming)
    assert len(merged) == 2
    ep1 = next(ep for ep in merged if ep["episode_number"] == 1)
    assert len(ep1["versions"]) == 2
    assert ep1["watched"] is False


def test_preserve_live_watch_state_overlays_tv_episode_watched(
    database_engine, agent_config, scanned_series_data
) -> None:
    """A rescan must not clobber watched/playback fields touched meanwhile."""
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)
        library_row = get_library(session, agent_config.libraries["tv"]["name"])
        assert library_row is not None
        episode_row = session.scalars(
            select(Episode).where(Episode.episode_number == 1)
        ).first()
        assert episode_row is not None
        episode_row.watched = True
        episode_row.last_played_at = 1735743845.0
        episode_row.resume_position_seconds = 42
        session.commit()

    result_copy = copy.deepcopy(scanned_series_data)
    # Simulate a stale rescan whose episode dicts carry no live fields.
    season = next(iter(result_copy["Test Show"]["seasons"].values()))
    for episode in season["episodes"]:
        episode.pop("watched", None)
        episode.pop("last_played_position", None)

    with get_session(database_engine) as session:
        library_row = get_library(session, agent_config.libraries["tv"]["name"])
        assert library_row is not None
        preserve_live_watch_state(session, library_row, result_copy)

    season_data = next(iter(result_copy["Test Show"]["seasons"].values()))
    first_episode = next(
        episode
        for episode in season_data["episodes"]
        if episode.get("episode_number") == 1
    )
    assert first_episode["watched"] is True
    assert first_episode["last_played_position"] == 42
    assert first_episode["last_played_at"] == 1735743845.0

    with get_session(database_engine) as session:
        library_row = get_library(session, agent_config.libraries["tv"]["name"])
        assert library_row is not None
        stats = upsert_library(session, {**payload, "items": result_copy})
        assert stats["episodes"] == 2
        episode_row = session.scalars(
            select(Episode).where(Episode.episode_number == 1)
        ).first()
        assert episode_row is not None
        assert episode_row.watched is True
        assert episode_row.resume_position_seconds == 42


def test_preserve_live_watch_state_overlays_movie_watched(
    database_engine, agent_config, scanned_movie_data
) -> None:
    payload = _movie_library_payload(agent_config, scanned_movie_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)
        movie_row = session.scalars(select(Movie)).first()
        assert movie_row is not None
        movie_row.watched = True
        movie_row.resume_position_seconds = 60
        session.commit()

    result_copy = copy.deepcopy(scanned_movie_data)
    movie_item = next(iter(result_copy.values()))
    movie_item.pop("watched", None)
    movie_item.pop("last_played_position", None)

    with get_session(database_engine) as session:
        library_row = get_library(session, agent_config.libraries["movie"]["name"])
        assert library_row is not None
        preserve_live_watch_state(session, library_row, result_copy)

    restored_item = next(iter(result_copy.values()))
    assert restored_item["watched"] is True
    assert restored_item["last_played_position"] == 60


def test_versions_none_preserves_existing_multi_version_episode(
    database_engine, agent_config, scanned_series_data
) -> None:
    """Episode dicts without a versions key must keep existing media files."""
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        stats = upsert_library(session, payload)
    assert stats["media_files"] == 3

    reduced = copy.deepcopy(scanned_series_data)
    season = next(iter(reduced["Test Show"]["seasons"].values()))
    for episode in season["episodes"]:
        if episode.get("episode_number") == 1:
            version_paths = [
                version["path"] for version in (episode.get("versions") or [])
            ]
            episode.pop("versions", None)
            episode["path"] = next(
                path for path in version_paths if path.endswith(".mkv")
            )

    with get_session(database_engine) as session:
        stats = upsert_library(session, {**payload, "items": reduced})
    assert stats["media_files"] == 3

    with get_session(database_engine) as session:
        series_row = session.scalars(select(Series)).first()
        assert series_row is not None
        first_episode = next(
            episode
            for episode in series_row.seasons[0].episodes
            if episode.episode_number == 1
        )
        media_paths = sorted(
            media_file.path for media_file in first_episode.media_files
        )
        assert len(media_paths) == 2
        assert any(path.endswith(".mkv") for path in media_paths)
        assert any(path.endswith(".mp4") for path in media_paths)


def test_upsert_library_handles_reassigned_or_duplicate_media_file_paths(
    database_engine, agent_config, scanned_series_data
) -> None:
    """Reassigning a media file path across seasons or duplicate entries must not raise IntegrityError."""
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)

    # Modify payload so that a file previously belonging to Season 1 is now in Season 2,
    # and add duplicate version paths to test deduplication.
    reassigned_data = copy.deepcopy(scanned_series_data)
    reassigned_data["Test Show"]["seasons"]["Season 02"] = {
        "name": "Season 2",
        "episodes": [
            {
                "episode_number": 1,
                "name": "Moved Episode",
                "path": "/fake/tv/Test Show/Season 01/Test.Show.S01E01.mkv",
                "versions": [
                    {"path": "/fake/tv/Test Show/Season 01/Test.Show.S01E01.mkv"},
                    {
                        "path": "/fake/tv/Test Show/Season 01/Test.Show.S01E01.mkv"
                    },  # duplicate in versions
                ],
            }
        ],
        "metadata": {},
    }

    with get_session(database_engine) as session:
        stats = upsert_library(session, {**payload, "items": reassigned_data})
        assert stats["series"] == 1
        assert stats["seasons"] == 2

    # Verify that MediaFile uniqueness was maintained and the path exists once
    with get_session(database_engine) as session:
        matching_media_files = session.scalars(
            select(MediaFile).where(
                MediaFile.path == "/fake/tv/Test Show/Season 01/Test.Show.S01E01.mkv"
            )
        ).all()
        assert len(matching_media_files) == 1


def test_upsert_series_isolated_error_does_not_abort_library(
    database_engine, agent_config, scanned_series_data, monkeypatch
) -> None:
    """An unhandled error in one series must not prevent other series in the library from upserting."""
    import scan_agent.db.repository as repo

    multi_series_data = copy.deepcopy(scanned_series_data)
    multi_series_data["Good Show"] = {
        "name": "Good Show",
        "seasons": {
            "Season 01": {
                "name": "Season 1",
                "episodes": [
                    {
                        "episode_number": 1,
                        "name": "Good Episode",
                        "path": "/fake/tv/Good Show/Season 01/Good.Show.S01E01.mkv",
                        "versions": [
                            {
                                "path": "/fake/tv/Good Show/Season 01/Good.Show.S01E01.mkv"
                            }
                        ],
                    }
                ],
                "metadata": {},
            }
        },
        "metadata": {},
    }

    original_upsert_seasons = repo._upsert_seasons

    def flaky_upsert_seasons(connection, series, seasons_data):
        if series.folder_name == "Test Show":
            raise RuntimeError("Corrupt metadata in Test Show")
        return original_upsert_seasons(connection, series, seasons_data)

    monkeypatch.setattr(repo, "_upsert_seasons", flaky_upsert_seasons)

    payload = _tv_library_payload(agent_config, multi_series_data)
    with get_session(database_engine) as session:
        stats = upsert_library(session, payload)
        assert stats["series"] >= 1

    with get_session(database_engine) as session:
        series_list = list_series(session)
        assert any(entry["folder_name"] == "Good Show" for entry in series_list)


def test_list_episodes_filter_and_sort(
    database_engine, agent_config, scanned_series_data
) -> None:
    tv_payload = _tv_library_payload(agent_config, scanned_series_data)
    anime_series_data = {
        "Frieren": {
            "name": "Frieren: Beyond Journey's End",
            "seasons": {
                "Season 01": {
                    "name": "Season 1",
                    "episodes": [
                        {
                            "episode_number": 1,
                            "name": "The Journey's End",
                            "air_date": "2023-09-29",
                            "path": "/fake/anime/Frieren/Season 01/Frieren.S01E01.mkv",
                            "versions": [
                                {
                                    "path": "/fake/anime/Frieren/Season 01/Frieren.S01E01.mkv"
                                }
                            ],
                        },
                        {
                            "episode_number": 2,
                            "name": "It Didn't Have to Be Magic",
                            "air_date": "2023-09-29",
                            "path": "/fake/anime/Frieren/Season 01/Frieren.S01E02.mkv",
                            "versions": [
                                {
                                    "path": "/fake/anime/Frieren/Season 01/Frieren.S01E02.mkv"
                                }
                            ],
                        },
                    ],
                    "metadata": {},
                }
            },
            "metadata": {},
        }
    }
    anime_payload = {
        "name": "Anime Collection",
        "media_type": "anime",
        "root_path": "/fake/anime",
        "items": anime_series_data,
    }

    with get_session(database_engine) as session:
        upsert_library(session, tv_payload)
        upsert_library(session, anime_payload)

        first_anime_episode = session.scalars(
            select(Episode).where(Episode.name == "The Journey's End")
        ).first()
        assert first_anime_episode is not None
        first_anime_episode.watched = True
        session.flush()

        all_episodes = list_episodes(session)
        assert len(all_episodes) >= 4

        anime_episodes = list_episodes(session, library_type="anime")
        assert len(anime_episodes) == 2
        assert all(episode["library_type"] == "anime" for episode in anime_episodes)
        assert anime_episodes[0]["series_name"] == "Frieren: Beyond Journey's End"
        assert anime_episodes[0]["season_number"] == 1

        watched_anime = list_episodes(session, library_type="anime", watched=True)
        assert len(watched_anime) == 1
        assert watched_anime[0]["name"] == "The Journey's End"

        unwatched_anime = list_episodes(session, library_type="anime", watched=False)
        assert len(unwatched_anime) == 1
        assert unwatched_anime[0]["name"] == "It Didn't Have to Be Magic"

        query_results = list_episodes(session, library_type="anime", query="Magic")
        assert len(query_results) == 1
        assert query_results[0]["name"] == "It Didn't Have to Be Magic"

        query_series = list_episodes(session, library_type="anime", query="Frieren")
        assert len(query_series) == 2

        anime_library = get_library(session, "Anime Collection")
        assert anime_library is not None
        library_episodes = list_episodes(session, library_identifier=anime_library.id)
        assert len(library_episodes) == 2

        assert list_episodes(session, library_identifier=99999) == []
        assert (
            list_episodes(session, library_type="anime", sort="name_desc")[0][
                "episode_number"
            ]
            == 2
        )
        assert (
            len(list_episodes(session, library_type="anime", sort="air_date_desc")) == 2
        )


def test_set_metadata_match_not_found(database_engine) -> None:
    with get_session(database_engine) as session:
        assert set_series_metadata_match(session, 999999, "100", {"name": "X"}) is None
        assert set_movie_metadata_match(session, 999999, "200", {"name": "Y"}) is None


def test_set_series_metadata_match_fallback_sync(
    database_engine, agent_config, scanned_series_data, tmdb_mock
) -> None:
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        upsert_library(session, payload)
        series_row = session.scalars(select(Series)).first()
        assert series_row is not None
        series_identifier = series_row.id

        # Point path and folder_name to nonexistent so scanner pipeline falls back to in-memory sync
        series_row.path = "/nonexistent/path/for/series"
        series_row.folder_name = "Nonexistent Show"
        session.flush()

        result = set_series_metadata_match(
            session,
            series_identifier,
            "100",
            {
                "name": "Fallback Test Show",
                "overview": "Fallback overview",
                "poster_path": "/fallback_poster.jpg",
                "year": 2024,
            },
            tmdb_client=tmdb_mock,
        )
        assert result is not None
        assert result["name"] == "Fallback Test Show"
        assert result["locked_metadata"] is True

        updated_series = session.get(Series, series_identifier)
        assert updated_series is not None
        assert updated_series.locked_metadata is True
        episodes_by_number = {
            episode.episode_number: episode.name
            for season in updated_series.seasons
            for episode in season.episodes
        }
        assert episodes_by_number[1] == "Pilot"
        assert episodes_by_number[2] == "Second"


def test_sync_series_tmdb_fallback_edge_cases(tmdb_mock) -> None:
    series_record = {
        "name": "Show",
        "seasons": {
            "Specials": {
                "metadata": {},
                "episodes": [
                    {"name": "Show Special S00E01", "path": "/media/special1.mkv"},
                    {"name": "Behind The Scenes", "path": "/media/bts.mkv"},
                ],
            },
            "Invalid Season": {
                "metadata": {},
                "episodes": [],
            },
        },
    }
    special_episodes = [
        {
            "id": 10,
            "episode_number": 1,
            "name": "Special 1",
            "air_date": "2024-01-01",
            "runtime": 15,
        },
        {
            "id": 11,
            "episode_number": 2,
            "name": "Behind The Scenes",
            "air_date": "2024-01-02",
            "runtime": 20,
        },
    ]
    tmdb_mock.get_episodes.side_effect = lambda identifier, season_number: (
        special_episodes if season_number == 0 else []
    )

    synced = _sync_series_tmdb_fallback(series_record, "100", tmdb_mock)
    specials = synced["seasons"]["Specials"]["episodes"]
    assert specials[0]["name"] == "Special 1"
    assert specials[0]["episode_number"] == 1
    assert specials[1]["name"] == "Behind The Scenes"
    assert specials[1]["episode_number"] == 2

    # Test error in client.get_episodes handled gracefully
    tmdb_mock.get_episodes.side_effect = RuntimeError("TMDB error")
    synced_error = _sync_series_tmdb_fallback(series_record, "100", tmdb_mock)
    assert synced_error is not None


def test_upsert_library_omits_series_with_no_episode_files(
    database_engine, agent_config
) -> None:
    empty_series_payload = {
        "name": agent_config.libraries["tv"]["name"],
        "media_type": "tv",
        "root_path": agent_config.libraries["tv"]["root_path"],
        "items": {
            "Empty Show": {
                "name": "Empty Show",
                "seasons": {
                    "Season 01": {
                        "metadata": {},
                        "episodes": [],
                    }
                },
            },
            "Placeholder Only Show": {
                "name": "Placeholder Only Show",
                "seasons": {
                    "Season 01": {
                        "metadata": {},
                        "episodes": [
                            {
                                "name": "Placeholder Ep 1",
                                "episode_number": 1,
                                "path": None,
                                "versions": [],
                            }
                        ],
                    }
                },
            },
        },
    }
    with get_session(database_engine) as session:
        stats = upsert_library(session, empty_series_payload)
        assert stats["series"] == 0
        assert stats["episodes"] == 0

        series_list = list_series(session)
        assert len(series_list) == 0


def test_list_series_excludes_series_without_episode_files(
    database_engine, agent_config
) -> None:
    from scan_agent.db.models import Episode, Library, Season, Series

    with get_session(database_engine) as session:
        library = Library(
            name="Manual Library",
            media_type="tv",
            root_path="/media/tv",
        )
        session.add(library)
        session.flush()

        empty_series = Series(
            library_id=library.id,
            folder_name="Empty Series Folder",
            name="Empty Series Folder",
        )
        session.add(empty_series)
        session.flush()

        season_empty = Season(
            series_id=empty_series.id,
            season_number=1,
            name="Season 1",
        )
        session.add(season_empty)
        session.flush()

        placeholder_episode = Episode(
            season_id=season_empty.id,
            episode_number=1,
            name="Placeholder Ep",
            path=None,
        )
        session.add(placeholder_episode)
        session.commit()

    with get_session(database_engine) as session:
        series_results = list_series(session)
        assert len(series_results) == 0


def test_upsert_series_scan_deletes_series_when_files_removed(
    database_engine, agent_config, scanned_series_data
) -> None:
    payload = _tv_library_payload(agent_config, scanned_series_data)
    with get_session(database_engine) as session:
        stats = upsert_library(session, payload)
        assert stats["series"] == 1
        tv_library = get_library(session, agent_config.libraries["tv"]["name"])
        assert tv_library is not None
        library_identifier = tv_library.id

    with get_session(database_engine) as session:
        series_results = list_series(session)
        assert len(series_results) == 1

    # Now simulate a scan where all episodes were deleted
    empty_series_data = {
        "name": "Test Show",
        "seasons": {
            "Season 01": {
                "metadata": {},
                "episodes": [],
            }
        },
    }
    with get_session(database_engine) as session:
        stats = upsert_series_scan(
            session, library_identifier, "Test Show", empty_series_data
        )
        assert stats["series"] == 0

    with get_session(database_engine) as session:
        series_results = list_series(session)
        assert len(series_results) == 0
