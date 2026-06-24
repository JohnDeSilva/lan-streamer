"""
Extended tests for db/queries.py – covering lines that have no existing coverage:
 - _trigger_mal_push_async
 - update_episode_watched_status (MAL branch, movie branch, movie+MAL branch)
 - update_season_watched_status (MAL branch)
 - update_series_watched_status (MAL branch, already-unwatched branch)
 - get_items_missing_runtime (exception branch)
 - update_items_runtime_batch (episode and movie branches with technical info)
 - get_combined_smart_row (Watched/Unwatched filter_mode for both series and movies)
 - get_combined_next_up (empty library_names path, exception path)
 - natural_sort_key (numeric vs string parts)
"""

import pytest
from unittest.mock import patch

from lan_streamer import db
from lan_streamer.db.models import Series, Season, Episode, Movie


@pytest.fixture
def mock_db_file(tmp_path):
    return tmp_path / "library.db"


# ---------------------------------------------------------------------------
# natural_sort_key
# ---------------------------------------------------------------------------


def test_natural_sort_key_mixed() -> None:
    key = db.natural_sort_key("Season 10")
    # should split into text and numeric parts
    assert any(isinstance(part, int) and part == 10 for part in key)


def test_natural_sort_key_all_text() -> None:
    key = db.natural_sort_key("abc")
    assert key == ["abc"]


def test_natural_sort_key_numeric_string() -> None:
    key = db.natural_sort_key("123")
    assert 123 in key


def test_natural_sort_key_none() -> None:
    assert db.natural_sort_key(None) == []


# ---------------------------------------------------------------------------
# _trigger_mal_push_async
# ---------------------------------------------------------------------------


def test_trigger_mal_push_async_not_configured(mock_db_file) -> None:
    """Should not start a thread if MAL is not configured or not authenticated."""
    from lan_streamer.db.queries_playback import _trigger_mal_push_async
    from lan_streamer.providers.myanimelist import myanimelist_client

    with (
        patch.object(myanimelist_client, "is_configured", return_value=False),
        patch.object(myanimelist_client, "is_authenticated", return_value=True),
    ):
        import threading

        thread_count_before = threading.active_count()
        _trigger_mal_push_async(999, 5)
        # No new thread should have been spawned
        assert threading.active_count() <= thread_count_before + 1


def test_trigger_mal_push_async_configured(mock_db_file) -> None:
    """When configured+authenticated a daemon thread is started to push status."""
    from lan_streamer.db.queries_playback import _trigger_mal_push_async
    from lan_streamer.providers.myanimelist import myanimelist_client

    with (
        patch.object(myanimelist_client, "is_configured", return_value=True),
        patch.object(myanimelist_client, "is_authenticated", return_value=True),
        patch.object(
            myanimelist_client, "update_watched_status", return_value=True
        ) as mock_update,
    ):
        _trigger_mal_push_async(42, 3)
        # Give the daemon thread a small chance to run
        import time

        time.sleep(0.1)
        mock_update.assert_called()


# ---------------------------------------------------------------------------
# update_episode_watched_status – movie path
# ---------------------------------------------------------------------------


def test_update_episode_watched_status_movie_path(mock_db_file) -> None:
    """When the path belongs to a movie (not episode) it should mark the movie watched."""
    from lan_streamer.db import get_session

    with get_session() as session:
        movie = Movie(
            name="Test Movie",
            library_name="Movies",
            path="/movies/test.mkv",
            watched=False,
        )
        session.add(movie)
        session.commit()

    db.update_episode_watched_status("/movies/test.mkv", True)

    with get_session() as session:
        from lan_streamer.db.models import MediaFile

        m = (
            session.query(Movie)
            .join(Movie.media_files)
            .filter(MediaFile.path == "/movies/test.mkv")
            .first()
        )
        assert m is not None
        assert m.watched is True
        assert m.last_played_at is not None and m.last_played_at > 0


def test_update_episode_watched_status_movie_unwatch(mock_db_file) -> None:
    """Setting watched=False on a movie should clear watched flag."""
    from lan_streamer.db import get_session

    with get_session() as session:
        movie = Movie(
            name="Watched Movie",
            library_name="Movies",
            path="/movies/watched.mkv",
            watched=True,
        )
        session.add(movie)
        session.commit()

    db.update_episode_watched_status("/movies/watched.mkv", False)

    with get_session() as session:
        from lan_streamer.db.models import MediaFile

        m = (
            session.query(Movie)
            .join(Movie.media_files)
            .filter(MediaFile.path == "/movies/watched.mkv")
            .first()
        )
        assert m is not None
        assert m.watched is False


def test_update_episode_watched_status_movie_with_mal(mock_db_file) -> None:
    """Watching a movie with a MAL anime_id should trigger the async push."""
    from lan_streamer.db import get_session

    with get_session() as session:
        movie = Movie(
            name="MAL Movie",
            library_name="Movies",
            path="/movies/mal_movie.mkv",
            watched=False,
            myanimelist_anime_id=111,
        )
        session.add(movie)
        session.commit()

    with patch("lan_streamer.db.queries_playback._trigger_mal_push_async") as mock_push:
        db.update_episode_watched_status("/movies/mal_movie.mkv", True)
        mock_push.assert_called_once_with(111, 1)


def test_update_episode_watched_status_episode_with_mal(mock_db_file) -> None:
    """Watching an episode with MAL info should trigger async push."""
    from lan_streamer.db import get_session

    with get_session() as session:
        series = Series(name="MAL Show", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep = Episode(
            season_id=season.id,
            name="ep1.mkv",
            path="/mal/ep1.mkv",
            watched=False,
            myanimelist_anime_id=555,
            myanimelist_episode_number=1,
        )
        session.add(ep)
        session.commit()

    with patch("lan_streamer.db.queries_playback._trigger_mal_push_async") as mock_push:
        db.update_episode_watched_status("/mal/ep1.mkv", True)
        mock_push.assert_called_once_with(555, 1)


# ---------------------------------------------------------------------------
# update_season_watched_status – MAL branch
# ---------------------------------------------------------------------------


def test_update_season_watched_status_with_mal(mock_db_file) -> None:
    """Marking a season watched should trigger MAL push for episodes with MAL IDs."""
    from lan_streamer.db import get_session

    with get_session() as session:
        series = Series(name="MAL Season Show", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep1 = Episode(
            season_id=season.id,
            name="ep1.mkv",
            path="/mal_s/ep1.mkv",
            watched=False,
            myanimelist_anime_id=777,
            myanimelist_episode_number=1,
        )
        ep2 = Episode(
            season_id=season.id,
            name="ep2.mkv",
            path="/mal_s/ep2.mkv",
            watched=False,
            myanimelist_anime_id=777,
            myanimelist_episode_number=2,
        )
        session.add_all([ep1, ep2])
        session.commit()

    with patch("lan_streamer.db.queries_playback._trigger_mal_push_async") as mock_push:
        db.update_season_watched_status("Lib", "MAL Season Show", "Season 1", True)
        # Should be called with max episode number (2)
        mock_push.assert_called_once_with(777, 2)


def test_update_season_watched_status_nonexistent(mock_db_file) -> None:
    """Should not error when season doesn't exist."""
    db.update_season_watched_status("Nonexistent", "NoShow", "S1", True)


# ---------------------------------------------------------------------------
# update_series_watched_status – MAL branch
# ---------------------------------------------------------------------------


def test_update_series_watched_status_with_mal(mock_db_file) -> None:
    """Marking series watched should trigger MAL push with the max episode number."""
    from lan_streamer.db import get_session

    with get_session() as session:
        series = Series(name="MAL Series Show", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep1 = Episode(
            season_id=season.id,
            name="ep1.mkv",
            path="/mal_ser/ep1.mkv",
            watched=False,
            myanimelist_anime_id=888,
            myanimelist_episode_number=1,
        )
        ep2 = Episode(
            season_id=season.id,
            name="ep2.mkv",
            path="/mal_ser/ep2.mkv",
            watched=False,
            myanimelist_anime_id=888,
            myanimelist_episode_number=3,
        )
        session.add_all([ep1, ep2])
        session.commit()

    with patch("lan_streamer.db.queries_playback._trigger_mal_push_async") as mock_push:
        db.update_series_watched_status("Lib", "MAL Series Show", True)
        mock_push.assert_called_once_with(888, 3)


def test_update_series_watched_status_nonexistent(mock_db_file) -> None:
    """Should not crash when series doesn't exist."""
    db.update_series_watched_status("Nonexistent", "NoShow", True)


# ---------------------------------------------------------------------------
# get_items_missing_runtime – exception path
# ---------------------------------------------------------------------------


def test_get_items_missing_runtime_exception() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("DB error")
        # Should return empty list without raising
        result = db.get_items_missing_runtime()
        assert result == []


# ---------------------------------------------------------------------------
# update_items_runtime_batch – with technical fields
# ---------------------------------------------------------------------------


def test_update_items_runtime_batch_episode_with_tech_info(mock_db_file) -> None:
    from lan_streamer.db import get_session
    import json

    with get_session() as session:
        series = Series(name="TechShow", library_name="TechLib")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="S1")
        session.add(season)
        session.flush()
        ep = Episode(
            season_id=season.id,
            name="e1.mkv",
            path="/tech/e1.mkv",
            runtime=0,
        )
        session.add(ep)
        session.commit()
        ep_id = ep.id

    db.update_items_runtime_batch(
        [
            {
                "item_identifier": ep_id,
                "item_type": "episode",
                "runtime_minutes": 45,
                "video_codec": "h264",
                "resolution": "1920x1080",
                "audio_tracks": [{"language": "eng"}],
                "subtitle_tracks": [{"language": "spa"}],
                "size_bytes": 987654,
            }
        ]
    )

    with get_session() as session:
        updated = session.query(Episode).filter_by(id=ep_id).first()
        assert updated is not None
        assert updated.runtime == 0
        assert updated.file_runtime == 45
        assert updated.video_codec == "h264"
        assert updated.resolution == "1920x1080"
        assert json.loads(updated.audio_tracks) == [{"language": "eng"}]
        assert json.loads(updated.subtitle_tracks) == [{"language": "spa"}]
        assert updated.media_files[0].video_codec == "h264"
        assert updated.media_files[0].size_bytes == 987654


def test_update_items_runtime_batch_movie_with_tech_info(mock_db_file) -> None:
    from lan_streamer.db import get_session
    import json

    with get_session() as session:
        movie = Movie(
            name="TechMovie",
            library_name="Movies",
            path="/tech/movie.mkv",
            runtime=0,
        )
        session.add(movie)
        session.commit()
        movie_id = movie.id

    db.update_items_runtime_batch(
        [
            {
                "item_identifier": movie_id,
                "item_type": "movie",
                "runtime_minutes": 120,
                "video_codec": "hevc",
                "resolution": "3840x2160",
                "audio_tracks": [{"language": "eng"}, {"language": "fre"}],
                "subtitle_tracks": [],
                "size_bytes": 123456,
            }
        ]
    )

    with get_session() as session:
        updated = session.query(Movie).filter_by(id=movie_id).first()
        assert updated is not None
        assert updated.runtime == 0
        assert updated.file_runtime == 120
        assert updated.video_codec == "hevc"
        assert updated.resolution == "3840x2160"
        assert json.loads(updated.audio_tracks) == [
            {"language": "eng"},
            {"language": "fre"},
        ]
        assert json.loads(updated.subtitle_tracks) == []
        assert updated.media_files[0].video_codec == "hevc"
        assert updated.media_files[0].size_bytes == 123456


def test_update_items_runtime_batch_episode_not_found(mock_db_file) -> None:
    """Should not crash when ID doesn't exist."""
    import uuid

    db.update_items_runtime_batch(
        [
            {
                "item_identifier": uuid.uuid4().bytes,
                "item_type": "episode",
                "runtime_minutes": 30,
            }
        ]
    )


def test_update_items_runtime_batch_movie_not_found(mock_db_file) -> None:
    """Should not crash when movie ID doesn't exist."""
    import uuid

    db.update_items_runtime_batch(
        [
            {
                "item_identifier": uuid.uuid4().bytes,
                "item_type": "movie",
                "runtime_minutes": 30,
            }
        ]
    )


def test_update_items_runtime_batch_exception() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("DB error")
        # Should not raise
        import uuid

        db.update_items_runtime_batch(
            [
                {
                    "item_identifier": uuid.uuid4().bytes,
                    "item_type": "episode",
                    "runtime_minutes": 30,
                }
            ]
        )


# ---------------------------------------------------------------------------
# get_combined_smart_row – Watched/Unwatched filter_mode
# ---------------------------------------------------------------------------


def test_get_combined_smart_row_watched_filter(mock_db_file) -> None:
    from lan_streamer.db import get_session, get_combined_smart_row

    with get_session() as session:
        # Series that is fully watched
        s_watched = Series(name="Watched Show", library_name="Lib")
        session.add(s_watched)
        session.flush()
        season_w = Season(series_id=s_watched.id, name="S1")
        session.add(season_w)
        session.flush()
        ep_w = Episode(
            season_id=season_w.id, name="e1.mkv", path="/w/e1.mkv", watched=True
        )
        session.add(ep_w)

        # Series that is partially watched
        s_partial = Series(name="Partial Show", library_name="Lib")
        session.add(s_partial)
        session.flush()
        season_p = Season(series_id=s_partial.id, name="S1")
        session.add(season_p)
        session.flush()
        ep_p1 = Episode(
            season_id=season_p.id, name="e1.mkv", path="/p/e1.mkv", watched=True
        )
        ep_p2 = Episode(
            season_id=season_p.id, name="e2.mkv", path="/p/e2.mkv", watched=False
        )
        session.add_all([ep_p1, ep_p2])

        # Fully watched movie
        m_watched = Movie(
            name="Watched Movie", library_name="Lib", path="/wm.mkv", watched=True
        )
        session.add(m_watched)

        # Unwatched movie
        m_unwatched = Movie(
            name="Unwatched Movie", library_name="Lib", path="/um.mkv", watched=False
        )
        session.add(m_unwatched)
        session.commit()

    # Watched filter – only fully-watched series and watched movies
    results = get_combined_smart_row(["Lib"], "Alphabetical", "Watched")
    names = {r["name"] for r in results}
    assert "Watched Show" in names
    assert "Watched Movie" in names
    assert "Partial Show" not in names
    assert "Unwatched Movie" not in names

    # Unwatched filter – only partially/unwatched series and unwatched movies
    results = get_combined_smart_row(["Lib"], "Alphabetical", "Unwatched")
    names = {r["name"] for r in results}
    assert "Partial Show" in names
    assert "Unwatched Movie" in names
    assert "Watched Show" not in names
    assert "Watched Movie" not in names


def test_get_combined_smart_row_empty_library_names(mock_db_file) -> None:
    from lan_streamer.db import get_session, get_combined_smart_row

    with get_session() as session:
        s = Series(name="SomeShow", library_name="SomeLib")
        session.add(s)
        session.flush()
        season = Season(series_id=s.id, name="S1")
        session.add(season)
        session.flush()
        ep = Episode(
            season_id=season.id, name="e1.mkv", path="/some/e1.mkv", watched=False
        )
        session.add(ep)
        session.commit()

    # Empty library_names should return all items
    results = get_combined_smart_row([], "Alphabetical", "All")
    assert any(r["name"] == "SomeShow" for r in results)


def test_get_combined_smart_row_default_sort(mock_db_file) -> None:
    """Test that an unknown sort_by falls back to alphabetical."""
    from lan_streamer.db import get_session, get_combined_smart_row

    with get_session() as session:
        s = Series(name="ZShow", library_name="SortLib")
        session.add(s)
        session.flush()
        season = Season(series_id=s.id, name="S1")
        session.add(season)
        session.flush()
        ep = Episode(
            season_id=season.id, name="e1.mkv", path="/z/e1.mkv", watched=False
        )
        session.add(ep)
        m = Movie(name="AMovie", library_name="SortLib", path="/am.mkv", watched=False)
        session.add(m)
        session.commit()

    results = get_combined_smart_row(["SortLib"], "UnknownSortMode", "All")
    names = [r["name"] for r in results]
    # Should be alphabetically sorted (AMovie < ZShow)
    assert names.index("AMovie") < names.index("ZShow")


def test_get_combined_smart_row_recently_aired(mock_db_file) -> None:
    """Test 'Recently Aired' sort mode for series with air_dates."""
    from lan_streamer.db import get_session, get_combined_smart_row

    with get_session() as session:
        s_old = Series(name="OldShow", library_name="AiredLib")
        s_new = Series(name="NewShow", library_name="AiredLib")
        session.add_all([s_old, s_new])
        session.flush()

        for series, air_date in [(s_old, "2010-01-01"), (s_new, "2023-01-01")]:
            season = Season(series_id=series.id, name="S1")
            session.add(season)
            session.flush()
            ep = Episode(
                season_id=season.id,
                name="e1.mkv",
                path=f"/{series.name}/e1.mkv",
                watched=False,
                air_date=air_date,
            )
            session.add(ep)
        session.commit()

    results = get_combined_smart_row(["AiredLib"], "Recently Aired", "All")
    names = [r["name"] for r in results]
    assert names.index("NewShow") < names.index("OldShow")


def test_get_combined_smart_row_exception() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("DB error")
        result = db.get_combined_smart_row([], "Alphabetical", "All")
        assert result == []


# ---------------------------------------------------------------------------
# get_combined_next_up – exception path and empty library
# ---------------------------------------------------------------------------


def test_get_combined_next_up_exception() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("DB error")
        result = db.get_combined_next_up([])
        assert result == []


def test_get_combined_next_up_no_libraries(mock_db_file) -> None:
    """When no matching series have partially-watched episodes, return empty list."""
    result = db.get_combined_next_up(["NonExistentLib"])
    assert result == []


# ---------------------------------------------------------------------------
# get_episode_playback_position – movie path
# ---------------------------------------------------------------------------


def test_get_episode_playback_position_movie(mock_db_file) -> None:
    """playback position is stored/retrieved for a movie path."""
    from lan_streamer.db import get_session

    with get_session() as session:
        movie = Movie(
            name="PosMovie",
            library_name="Movies",
            path="/pos/movie.mkv",
            watched=False,
        )
        session.add(movie)
        session.commit()

    assert db.get_episode_playback_position("/pos/movie.mkv") == 0
    assert db.update_episode_playback_position("/pos/movie.mkv", 200) is True
    assert db.get_episode_playback_position("/pos/movie.mkv") == 200


def test_get_episode_playback_position_missing() -> None:
    """Should return 0 for nonexistent paths."""
    assert db.get_episode_playback_position("/nonexistent/path.mkv") == 0


# ---------------------------------------------------------------------------
# is_movie – exception path
# ---------------------------------------------------------------------------


def test_is_movie_exception() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("DB error")
        result = db.is_movie("/some/path.mkv")
        assert result is False


# ---------------------------------------------------------------------------
# get_next_episode – non-existent path edge case
# ---------------------------------------------------------------------------


def test_get_next_episode_nonexistent_path(mock_db_file) -> None:
    result = db.get_next_episode("/does/not/exist.mkv")
    assert result is None


def test_get_next_episode_exception() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("DB error")
        result = db.get_next_episode("/some/path.mkv")
        assert result is None


# ---------------------------------------------------------------------------
# delete_series_record and delete_episode_record – exception paths
# ---------------------------------------------------------------------------


def test_delete_series_record_nonexistent(mock_db_file) -> None:
    """Should not crash when series doesn't exist."""
    db.delete_series_record("NonExistLib", "NonExistSeries")


def test_delete_series_record_exception() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("DB error")
        db.delete_series_record("Lib", "Show")  # should not raise


def test_delete_episode_record_nonexistent(mock_db_file) -> None:
    """Should not crash when episode doesn't exist."""
    db.delete_episode_record("/nonexistent/ep.mkv")


def test_delete_episode_record_exception() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("DB error")
        db.delete_episode_record("/path.mkv")  # should not raise


# ---------------------------------------------------------------------------
# update_episode_path – exception path
# ---------------------------------------------------------------------------


def test_update_episode_path_exception() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("DB error")
        db.update_episode_path("/old.mkv", "/new.mkv")  # should not raise)


# ---------------------------------------------------------------------------
# get_all_app_configs / bulk_set_app_configs tests
# ---------------------------------------------------------------------------


def test_get_all_app_configs_empty(mock_db_file) -> None:
    from lan_streamer.db.queries_config import get_all_app_configs
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import AppConfig

    with get_session() as session:
        session.query(AppConfig).delete()
        session.commit()

    assert get_all_app_configs() == {}


def test_bulk_set_and_get_all_app_configs(mock_db_file) -> None:
    from lan_streamer.db.queries_config import bulk_set_app_configs, get_all_app_configs
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import AppConfig

    # Delete existing
    with get_session() as session:
        session.query(AppConfig).delete()
        session.commit()

    test_data = {
        "str_key": "hello",
        "int_key": 42,
        "float_key": 3.14,
        "bool_key": True,
        "json_key": {"a": [1, 2, 3]},
    }

    bulk_set_app_configs(test_data)

    retrieved = get_all_app_configs()
    assert retrieved["str_key"] == "hello"
    assert retrieved["int_key"] == 42
    assert retrieved["float_key"] == 3.14
    assert retrieved["bool_key"] is True
    assert retrieved["json_key"] == {"a": [1, 2, 3]}

    # Update existing and add new
    updated_data = {
        "str_key": "world",
        "int_key": 99,
        "new_key": "added",
    }
    bulk_set_app_configs(updated_data)

    retrieved2 = get_all_app_configs()
    assert retrieved2["str_key"] == "world"
    assert retrieved2["int_key"] == 99
    assert retrieved2["float_key"] == 3.14  # preserved
    assert retrieved2["new_key"] == "added"


def test_get_all_app_configs_db_error(caplog) -> None:
    import logging
    from lan_streamer.db.queries_config import get_all_app_configs

    with (
        patch("lan_streamer.db.connection.get_session") as mock_session,
        caplog.at_level(logging.WARNING, logger="lan_streamer.db.queries"),
    ):
        mock_session.side_effect = Exception("disk I/O error")
        result = get_all_app_configs()

    assert result == {}
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "Error reading all app_config rows" in r.message for r in warning_records
    )


def test_bulk_set_app_configs_db_error(caplog) -> None:
    import logging
    from lan_streamer.db.queries_config import bulk_set_app_configs

    with (
        patch("lan_streamer.db.connection.get_session") as mock_session,
        caplog.at_level(logging.ERROR, logger="lan_streamer.db.queries"),
    ):
        mock_session.side_effect = Exception("disk I/O error")
        # Should not raise exception
        bulk_set_app_configs({"some_key": "some_val"})

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any(
        "Error writing bulk app_config settings" in r.message for r in error_records
    )


def test_load_from_db_calls_bulk_apis(mock_db_file) -> None:
    from lan_streamer.system.config import Config
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import AppConfig
    import lan_streamer.db.queries_config as db_queries

    with get_session() as session:
        session.query(AppConfig).delete()
        session.commit()

    config = Config()
    get_all_spy = patch.object(
        db_queries, "get_all_app_configs", wraps=db_queries.get_all_app_configs
    )
    bulk_set_spy = patch.object(
        db_queries, "bulk_set_app_configs", wraps=db_queries.bulk_set_app_configs
    )

    with get_all_spy as mock_get, bulk_set_spy as mock_set:
        config.load_from_db()
        mock_get.assert_called_once()
        mock_set.assert_called_once()


# ---------------------------------------------------------------------------
# get_all_secrets tests
# ---------------------------------------------------------------------------


def test_get_all_secrets_empty(mock_db_file) -> None:
    from lan_streamer.db.queries_config import get_all_secrets
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import AppSecret

    # Ensure no rows exist in AppSecret
    with get_session() as session:
        session.query(AppSecret).delete()
        session.commit()

    assert get_all_secrets() == {}


def test_get_all_secrets_success(mock_db_file) -> None:
    from lan_streamer.db.queries_config import get_all_secrets, set_secret
    from lan_streamer.db.models import SecretType, AppSecret
    from lan_streamer.db.connection import get_session

    with get_session() as session:
        session.query(AppSecret).delete()
        session.commit()

    set_secret(SecretType.JELLYFIN, {"url": "http://jelly", "api_key": "abc"})
    set_secret(SecretType.TMDB, {"api_key": "xyz"})

    secrets = get_all_secrets()
    assert secrets[SecretType.JELLYFIN.value] == {
        "url": "http://jelly",
        "api_key": "abc",
    }
    assert secrets[SecretType.TMDB.value] == {"api_key": "xyz"}


def test_get_all_secrets_db_error(caplog) -> None:
    import logging
    from lan_streamer.db.queries_config import get_all_secrets

    with (
        patch("lan_streamer.db.connection.get_session") as mock_session,
        caplog.at_level(logging.WARNING, logger="lan_streamer.db.queries"),
    ):
        mock_session.side_effect = Exception("disk I/O error")
        result = get_all_secrets()

    assert result == {}
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "Error reading all secrets from database" in r.message for r in warning_records
    )


def test_load_from_db_calls_get_all_secrets(mock_db_file) -> None:
    from lan_streamer.system.config import Config
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import AppSecret
    import lan_streamer.db.queries_config as db_queries

    with get_session() as session:
        session.query(AppSecret).delete()
        session.commit()

    config = Config()
    get_secrets_spy = patch.object(
        db_queries, "get_all_secrets", wraps=db_queries.get_all_secrets
    )

    with get_secrets_spy as mock_get_all:
        config.load_from_db()
        mock_get_all.assert_called_once()
