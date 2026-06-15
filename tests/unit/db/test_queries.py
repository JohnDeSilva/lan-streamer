import pytest
from unittest.mock import patch

from lan_streamer import db
from lan_streamer.db.models import Series, Season, Episode


@pytest.fixture
def mock_db_file(tmp_path) -> None:
    return tmp_path / "library.db"


def test_update_watched_status(mock_db_file) -> None:
    test_lib = {
        "Test Series": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path/to/ep1.mkv",
                            "jellyfin_id": "ep123",
                            "watched": False,
                        }
                    ],
                }
            },
        }
    }
    db.save_library("MyLib", test_lib)

    db.update_episode_watched_status("/path/to/ep1.mkv", True)

    loaded = db.load_library("MyLib")
    eps = loaded["Test Series"]["seasons"]["Season 1"]["episodes"]
    assert eps[0]["watched"] is True


def test_db_error_handling(mock_db_file) -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("Mocked error")

        # These should catch the error and log it, not crash
        assert db.load_library("Lib") == {}
        db.save_library("Lib", {})
        db.update_episode_watched_status("path", True)


def test_update_season_watched_status(mock_db_file) -> None:
    test_lib = {
        "Test Series": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path1",
                            "watched": False,
                        },
                        {
                            "name": "Ep 2",
                            "path": "/path2",
                            "watched": False,
                        },
                    ],
                },
                "Season 2": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path3",
                            "watched": False,
                        }
                    ],
                },
            },
        }
    }
    db.save_library("MyLib", test_lib)

    db.update_season_watched_status("MyLib", "Test Series", "Season 1", True)

    loaded = db.load_library("MyLib")
    s1_eps = loaded["Test Series"]["seasons"]["Season 1"]["episodes"]
    assert all(ep["watched"] is True for ep in s1_eps)

    s2_eps = loaded["Test Series"]["seasons"]["Season 2"]["episodes"]
    assert all(ep["watched"] is False for ep in s2_eps)

    # Toggle back
    db.update_season_watched_status("MyLib", "Test Series", "Season 1", False)
    loaded = db.load_library("MyLib")
    s1_eps = loaded["Test Series"]["seasons"]["Season 1"]["episodes"]
    assert all(ep["watched"] is False for ep in s1_eps)


def test_update_series_watched_status(mock_db_file) -> None:
    test_lib = {
        "Test Series": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [{"name": "Ep 1", "path": "/path1", "watched": False}],
                },
                "Season 2": {
                    "metadata": {},
                    "episodes": [{"name": "Ep 1", "path": "/path2", "watched": False}],
                },
            },
        },
        "Other Series": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [{"name": "Ep 1", "path": "/path3", "watched": False}],
                }
            },
        },
    }
    db.save_library("MyLib", test_lib)

    db.update_series_watched_status("MyLib", "Test Series", True)

    loaded = db.load_library("MyLib")
    for season in loaded["Test Series"]["seasons"].values():
        for ep in season["episodes"]:
            assert ep["watched"] is True

    for season in loaded["Other Series"]["seasons"].values():
        for ep in season["episodes"]:
            assert ep["watched"] is False

    # Toggle back
    db.update_series_watched_status("MyLib", "Test Series", False)
    loaded = db.load_library("MyLib")
    for season in loaded["Test Series"]["seasons"].values():
        for ep in season["episodes"]:
            assert ep["watched"] is False


def test_update_episode_path(mock_db_file) -> None:
    test_lib = {
        "Show": {
            "seasons": {"S1": {"episodes": [{"name": "E1", "path": "/old/path.mkv"}]}}
        }
    }
    db.save_library("Lib", test_lib)
    db.update_episode_path("/old/path.mkv", "/new/path.mkv")

    loaded = db.load_library("Lib")
    ep = loaded["Show"]["seasons"]["S1"]["episodes"][0]
    assert ep["path"] == "/new/path.mkv"


def test_update_episode_path_missing(mock_db_file) -> None:
    # Should not crash or error out
    db.update_episode_path("/missing/path.mkv", "/new/path.mkv")


def test_db_error_handling_extended(mock_db_file) -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("Mocked error")
        # Test get_all_episodes_with_jellyfin_id error path
        assert db.get_all_episodes_with_jellyfin_id() == []
        # Test cleanup_library error path
        with pytest.raises(Exception):
            db.cleanup_library("Lib", [])
        # Test playback position error paths
        assert db.update_episode_playback_position("path", 100) is False
        assert db.get_episode_playback_position("path") == 0


def test_update_and_get_playback_position(mock_db_file) -> None:
    from lan_streamer.db import get_session

    with get_session() as session:
        series = Series(name="ShowPos", library_name="LibPos")
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="S1")
        session.add(season)
        session.flush()

        ep = Episode(
            season_id=season.id, name="E1", path="/path/to/pos.mkv", watched=False
        )
        session.add(ep)
        session.commit()

    assert db.get_episode_playback_position("/path/to/pos.mkv") == 0
    assert db.update_episode_playback_position("/path/to/pos.mkv", 350) is True
    assert db.get_episode_playback_position("/path/to/pos.mkv") == 350
    assert db.update_episode_playback_position("/nonexistent/path.mkv", 10) is False


def test_runtime_management_functions(mock_db_file) -> None:
    from lan_streamer.db import get_session
    from lan_streamer.db.models import Movie

    with get_session() as session:
        series = Series(name="RuntimeShow", library_name="RuntimeLib")
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="S1")
        session.add(season)
        session.flush()

        episode_missing = Episode(
            season_id=season.id, name="E1", path="/path/to/missing_ep.mkv", runtime=0
        )
        episode_present = Episode(
            season_id=season.id,
            name="E2",
            path="/path/to/present_ep.mkv",
            runtime=25,
            video_codec="h264",
        )
        episode_present.media_files[0].video_codec = "h264"
        episode_present.file_runtime = 25
        episode_present.resolution = "1920x1080"
        episode_present.bit_rate = 5000
        movie_missing = Movie(
            name="MissingMovie",
            path="/path/to/missing_movie.mkv",
            library_name="Movies",
            runtime=None,
        )
        session.add_all([episode_missing, episode_present, movie_missing])
        session.commit()

    items = db.get_items_missing_runtime()
    assert len(items) == 2
    paths = {item["path"] for item in items}
    assert "/path/to/missing_ep.mkv" in paths
    assert "/path/to/missing_movie.mkv" in paths

    # Update runtime
    for item in items:
        db.update_item_runtime(item["id"], item["type"], 45)

    with get_session() as session:
        from lan_streamer.db.models import MediaFile

        updated_episode = (
            session.query(Episode)
            .join(Episode.media_files)
            .filter(MediaFile.path == "/path/to/missing_ep.mkv")
            .first()
        )
        assert updated_episode is not None
        assert updated_episode.file_runtime == 45
        assert updated_episode.runtime == 0

        updated_movie = (
            session.query(Movie)
            .join(Movie.media_files)
            .filter(MediaFile.path == "/path/to/missing_movie.mkv")
            .first()
        )
        assert updated_movie is not None
        assert updated_movie.file_runtime == 45
        assert updated_movie.runtime is None


def test_build_episode_dict(mock_db_file) -> None:
    from lan_streamer.db import _build_episode_dict, get_session

    with get_session() as session:
        series = Series(name="S", library_name="L")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep = Episode(
            season_id=season.id,
            name="S01E01.mkv",
            path="/p/S01E01.mkv",
            watched=True,
            runtime=42,
            air_date="2022-01-01",
            tmdb_name="Pilot",
            tmdb_number=1,
            tmdb_episode_identifier="tmdb_ep_1",
            jellyfin_id="jf_ep_1",
        )
        session.add(ep)
        session.flush()
        result = _build_episode_dict(ep)

    assert result["name"] == "S01E01.mkv"
    assert result["path"] == "/p/S01E01.mkv"
    assert result["watched"] is True
    assert result["runtime"] == 42
    assert result["air_date"] == "2022-01-01"
    assert result["tmdb_name"] == "Pilot"
    assert result["tmdb_number"] == 1
    assert result["jellyfin_id"] == "jf_ep_1"


def test_build_episode_dict_defaults(mock_db_file) -> None:
    from lan_streamer.db import _build_episode_dict, get_session

    with get_session() as session:
        series = Series(name="S", library_name="L")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep = Episode(season_id=season.id, name="ep.mkv", path="/p/ep.mkv")
        session.add(ep)
        session.flush()
        result = _build_episode_dict(ep)

    assert result["runtime"] == 0
    assert result["air_date"] == ""
    assert result["watched"] is False


def test_build_season_dict(mock_db_file) -> None:
    from lan_streamer.db import _build_season_dict, get_session

    with get_session() as session:
        series = Series(name="S", library_name="L")
        session.add(series)
        session.flush()
        season = Season(
            series_id=series.id,
            name="Season 1",
            jellyfin_id="jf_s1",
            poster_path="/poster.jpg",
        )
        session.add(season)
        session.flush()
        ep1 = Episode(season_id=season.id, name="S01E02.mkv", path="/p2")
        ep2 = Episode(season_id=season.id, name="S01E01.mkv", path="/p1")
        session.add_all([ep1, ep2])
        session.flush()
        result = _build_season_dict(season)

    assert result["metadata"]["jellyfin_id"] == "jf_s1"
    assert result["metadata"]["poster_path"] == "/poster.jpg"
    assert result["episodes"][0]["name"] == "S01E01.mkv"
    assert result["episodes"][1]["name"] == "S01E02.mkv"


def test_build_series_dict(mock_db_file) -> None:
    from lan_streamer.db import _build_series_dict, get_session

    with get_session() as session:
        series = Series(
            name="MyShow",
            library_name="L",
            jellyfin_id="jf_s",
            tmdb_identifier="tmdb_s",
            poster_path="/sp.jpg",
            overview="Great show",
            tmdb_name="My Show",
            locked_metadata=True,
            first_air_date="2021-06-01",
        )
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()
        ep = Episode(season_id=season.id, name="S01E01.mkv", path="/p")
        session.add(ep)
        session.flush()
        result = _build_series_dict(series)

    assert result["metadata"]["jellyfin_id"] == "jf_s"
    assert result["metadata"]["tmdb_identifier"] == "tmdb_s"
    assert result["metadata"]["locked_metadata"] is True
    assert result["metadata"]["first_air_date"] == "2021-06-01"
    assert "Season 1" in result["seasons"]


def test_build_movie_dict(mock_db_file) -> None:
    from lan_streamer.db import _build_movie_dict, get_session
    from lan_streamer.db.models import Movie

    with get_session() as session:
        movie = Movie(
            name="Inception",
            library_name="Movies",
            path="/movies/inception.mkv",
            jellyfin_id="jf_m",
            tmdb_identifier="tt_inc",
            poster_path="/p.jpg",
            overview="Heist",
            tmdb_name="Inception",
            locked_metadata=False,
            date_added=1000,
            runtime=148,
            rating="8.8",
            genre="Thriller",
            year=2010,
            watched=True,
            last_played_position=60,
        )
        session.add(movie)
        session.flush()
        result = _build_movie_dict(movie)

    assert result["name"] == "Inception"
    assert result["runtime"] == 148
    assert result["rating"] == "8.8"
    assert result["genre"] == "Thriller"
    assert result["year"] == 2010
    assert result["watched"] is True
    assert result["last_played_position"] == 60


def test_is_movie(mock_db_file) -> None:
    from lan_streamer.db import is_movie, get_session
    from lan_streamer.db.models import Movie

    # Initially, it should return False
    assert is_movie("/movies/inception.mkv") is False

    with get_session() as session:
        movie = Movie(
            name="Inception",
            library_name="Movies",
            path="/movies/inception.mkv",
        )
        session.add(movie)
        session.flush()

    assert is_movie("/movies/inception.mkv") is True
    assert is_movie("/movies/other.mkv") is False


def test_db_edge_cases() -> None:
    # natural_sort_key with None
    assert db.natural_sort_key(None) == []


def test_db_more_error_paths() -> None:
    with patch("lan_streamer.db.connection.get_session") as mock_session:
        mock_session.side_effect = Exception("General DB Error")
        # Ensure these functions don't raise but log exceptions
        db.update_season_watched_status("Lib", "Show", "S1", True)
        db.update_series_watched_status("Lib", "Show", True)
        db.update_item_runtime(1, "episode", 30)
        db.sync_watched_from_jellyfin_data({"id1"}, {"/path1"}, {("Show", "Ep1")})


def test_get_next_episode(mock_db_file) -> None:
    from lan_streamer.db import get_session, get_next_episode

    with get_session() as session:
        series = Series(name="Show", library_name="Lib", poster_path="/sp.jpg")
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()

        ep1 = Episode(
            season_id=season.id,
            name="S01E01.mkv",
            path="/p/S01E01.mkv",
            tmdb_name="Ep 1",
            tmdb_number=1,
            runtime=45,
        )
        ep2 = Episode(
            season_id=season.id,
            name="S01E02.mkv",
            path="/p/S01E02.mkv",
            tmdb_name="Ep 2",
            tmdb_number=2,
            runtime=45,
        )
        session.add_all([ep1, ep2])
        session.commit()

    # Call get_next_episode on ep1 path
    result = get_next_episode("/p/S01E01.mkv")
    assert result is not None
    assert result["title"] == "Ep 2"
    assert result["season"] == "Season 1"
    assert result["episode_number"] == 2
    assert result["path"] == "/p/S01E02.mkv"
    assert result["poster_path"] == "/sp.jpg"
    assert result["runtime"] == 45

    # Call get_next_episode on ep2 path (which is the last episode)
    assert get_next_episode("/p/S01E02.mkv") is None


def test_get_next_episode_skips_placeholder(mock_db_file) -> None:
    from lan_streamer.db import get_session, get_next_episode

    with get_session() as session:
        series = Series(
            name="ShowPlaceholder", library_name="Lib", poster_path="/sp.jpg"
        )
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()

        ep1 = Episode(
            season_id=season.id,
            name="S01E01.mkv",
            path="/p/S01E01.mkv",
            tmdb_name="Ep 1",
            tmdb_number=1,
            runtime=45,
        )
        ep2 = Episode(
            season_id=season.id,
            name="S01E02 - TBA",
            path=None,
            tmdb_name="Ep 2",
            tmdb_number=2,
            runtime=45,
        )
        ep3 = Episode(
            season_id=season.id,
            name="S01E03.mkv",
            path="/p/S01E03.mkv",
            tmdb_name="Ep 3",
            tmdb_number=3,
            runtime=45,
        )
        session.add_all([ep1, ep2, ep3])
        session.commit()

    # Call get_next_episode on ep1 path, should skip ep2 (placeholder) and return ep3
    result = get_next_episode("/p/S01E01.mkv")
    assert result is not None
    assert result["title"] == "Ep 3"
    assert result["path"] == "/p/S01E03.mkv"
    assert result["episode_number"] == 3

    # Call get_next_episode on ep3 path, should return None
    assert get_next_episode("/p/S01E03.mkv") is None


def test_get_next_episode_placeholder_is_last(mock_db_file) -> None:
    from lan_streamer.db import get_session, get_next_episode

    with get_session() as session:
        series = Series(
            name="ShowPlaceholderLast", library_name="Lib", poster_path="/sp.jpg"
        )
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()

        ep1 = Episode(
            season_id=season.id,
            name="S01E01.mkv",
            path="/p/S01E01.mkv",
            tmdb_name="Ep 1",
            tmdb_number=1,
            runtime=45,
        )
        ep2 = Episode(
            season_id=season.id,
            name="S01E02 - TBA",
            path=None,
            tmdb_name="Ep 2",
            tmdb_number=2,
            runtime=45,
        )
        session.add_all([ep1, ep2])
        session.commit()

    # Call get_next_episode on ep1 path, should return None because there are no subsequent valid episodes
    assert get_next_episode("/p/S01E01.mkv") is None


def test_get_combined_next_up_ignores_placeholders(mock_db_file) -> None:
    from lan_streamer.db import get_session, get_combined_next_up

    with get_session() as session:
        # Create Series 1 (partially watched, has a season with 1 watched local episode and 1 placeholder episode)
        series1 = Series(
            name="Show 1", library_name="TV Shows", poster_path="/poster1.jpg"
        )
        session.add(series1)
        session.flush()

        season1 = Season(series_id=series1.id, name="Season 1")
        session.add(season1)
        session.flush()

        # ep1 is watched
        ep1 = Episode(
            season_id=season1.id,
            name="S01E01.mkv",
            path="/p/S01E01.mkv",
            watched=True,
            last_played_at=1000,
        )
        # ep2 is a placeholder
        ep2 = Episode(
            season_id=season1.id,
            name="S01E02 - TBA",
            path=None,
            watched=False,
        )
        session.add_all([ep1, ep2])

        # Create Series 2 (fully watched on local episodes, has 1 watched local episode and 1 placeholder episode in Season 1, and an unwatched local episode in Season 2)
        series2 = Series(
            name="Show 2", library_name="TV Shows", poster_path="/poster2.jpg"
        )
        session.add(series2)
        session.flush()

        s2_season1 = Season(series_id=series2.id, name="Season 1")
        s2_season2 = Season(series_id=series2.id, name="Season 2")
        session.add_all([s2_season1, s2_season2])
        session.flush()

        # Season 1 local episode is watched, placeholder is unwatched. Since we ignore placeholders, Season 1 is fully watched.
        s2_ep1 = Episode(
            season_id=s2_season1.id,
            name="S01E01.mkv",
            path="/p2/S01E01.mkv",
            watched=True,
            last_played_at=2000,
        )
        s2_ep2 = Episode(
            season_id=s2_season1.id,
            name="S01E02 - TBA",
            path=None,
            watched=False,
        )
        # Season 2 has an unwatched local episode
        s2_ep3 = Episode(
            season_id=s2_season2.id,
            name="S02E01.mkv",
            path="/p2/S02E01.mkv",
            watched=False,
        )
        session.add_all([s2_ep1, s2_ep2, s2_ep3])
        session.commit()

    # Call get_combined_next_up
    results = get_combined_next_up(["TV Shows"])

    # Show 1's Season 1 should NOT be returned because its only local episode (ep1) is watched.
    # Show 2's Season 1 is fully watched (ignoring placeholder s2_ep2), so next_season should be Season 2.
    # Therefore, we expect only Show 2 to be in the next up list, pointing to Season 2!
    assert len(results) == 1
    assert results[0]["series_name"] == "Show 2"
    assert results[0]["season_name"] == "Season 2"
    assert results[0]["total_count"] == 1  # only s2_ep3 is local
    assert results[0]["watched_count"] == 0


def test_get_combined_next_up_plex_style(mock_db_file) -> None:
    from lan_streamer.db import get_session, get_combined_next_up

    with get_session() as session:
        # 1. Show 3: S01E01 (watched), S01E02 (unwatched) -> IN PROGRESS (points to Season 1)
        s3 = Series(name="Show 3", library_name="TV Shows")
        session.add(s3)
        session.flush()
        s3_season1 = Season(series_id=s3.id, name="Season 1")
        session.add(s3_season1)
        session.flush()
        s3_ep1 = Episode(
            season_id=s3_season1.id,
            name="S01E01.mkv",
            path="/p/s3_ep1.mkv",
            watched=True,
            last_played_at=1000,
        )
        s3_ep2 = Episode(
            season_id=s3_season1.id,
            name="S01E02.mkv",
            path="/p/s3_ep2.mkv",
            watched=False,
        )
        session.add_all([s3_ep1, s3_ep2])

        # 2. Show 4: S01E01 (watched), S01E02 (watched) -> FULLY WATCHED (excluded)
        s4 = Series(name="Show 4", library_name="TV Shows")
        session.add(s4)
        session.flush()
        s4_season1 = Season(series_id=s4.id, name="Season 1")
        session.add(s4_season1)
        session.flush()
        s4_ep1 = Episode(
            season_id=s4_season1.id,
            name="S01E01.mkv",
            path="/p/s4_ep1.mkv",
            watched=True,
            last_played_at=1000,
        )
        s4_ep2 = Episode(
            season_id=s4_season1.id,
            name="S01E02.mkv",
            path="/p/s4_ep2.mkv",
            watched=True,
            last_played_at=1200,
        )
        session.add_all([s4_ep1, s4_ep2])

        # 3. Show 5: S01E01 (unwatched), S01E02 (watched) -> NO UNWATCHED EPISODES AFTER THE WATCHED ONE (excluded)
        s5 = Series(name="Show 5", library_name="TV Shows")
        session.add(s5)
        session.flush()
        s5_season1 = Season(series_id=s5.id, name="Season 1")
        session.add(s5_season1)
        session.flush()
        s5_ep1 = Episode(
            season_id=s5_season1.id,
            name="S01E01.mkv",
            path="/p/s5_ep1.mkv",
            watched=False,
        )
        s5_ep2 = Episode(
            season_id=s5_season1.id,
            name="S01E02.mkv",
            path="/p/s5_ep2.mkv",
            watched=True,
            last_played_at=1300,
        )
        session.add_all([s5_ep1, s5_ep2])

        # 4. Show 6: S01E01 (unwatched), S01E02 (unwatched) -> UNSTARTED (excluded)
        s6 = Series(name="Show 6", library_name="TV Shows")
        session.add(s6)
        session.flush()
        s6_season1 = Season(series_id=s6.id, name="Season 1")
        session.add(s6_season1)
        session.flush()
        s6_ep1 = Episode(
            season_id=s6_season1.id,
            name="S01E01.mkv",
            path="/p/s6_ep1.mkv",
            watched=False,
        )
        s6_ep2 = Episode(
            season_id=s6_season1.id,
            name="S01E02.mkv",
            path="/p/s6_ep2.mkv",
            watched=False,
        )
        session.add_all([s6_ep1, s6_ep2])

        # 5. Show 7 & Show 8: both have watched & unwatched after.
        # Let's test sorting:
        # Show 7: last_played_at=2000, air_date="2026-06-01"
        # Show 8: last_played_at=2000, air_date="2026-06-15" (should be first because of air_date tie breaker)
        s7 = Series(name="Show 7", library_name="TV Shows")
        session.add(s7)
        session.flush()
        s7_season1 = Season(series_id=s7.id, name="Season 1")
        session.add(s7_season1)
        session.flush()
        s7_ep1 = Episode(
            season_id=s7_season1.id,
            name="S01E01.mkv",
            path="/p/s7_ep1.mkv",
            watched=True,
            last_played_at=2000,
            air_date="2026-06-01",
        )
        s7_ep2 = Episode(
            season_id=s7_season1.id,
            name="S01E02.mkv",
            path="/p/s7_ep2.mkv",
            watched=False,
        )
        session.add_all([s7_ep1, s7_ep2])

        s8 = Series(name="Show 8", library_name="TV Shows")
        session.add(s8)
        session.flush()
        s8_season1 = Season(series_id=s8.id, name="Season 1")
        session.add(s8_season1)
        session.flush()
        s8_ep1 = Episode(
            season_id=s8_season1.id,
            name="S01E01.mkv",
            path="/p/s8_ep1.mkv",
            watched=True,
            last_played_at=2000,
            air_date="2026-06-15",
        )
        s8_ep2 = Episode(
            season_id=s8_season1.id,
            name="S01E02.mkv",
            path="/p/s8_ep2.mkv",
            watched=False,
        )
        session.add_all([s8_ep1, s8_ep2])

        session.commit()

    # Call get_combined_next_up
    results = get_combined_next_up(["TV Shows"])

    # We expect results to contain Show 8 (index 0), Show 7 (index 1), Show 3 (index 2)
    # Show 4, 5, 6 should be excluded.
    assert len(results) == 3
    assert results[0]["series_name"] == "Show 8"
    assert results[1]["series_name"] == "Show 7"
    assert results[2]["series_name"] == "Show 3"


def test_get_combined_next_up_ignores_specials_and_uses_default_grouping(
    mock_db_file,
) -> None:
    from lan_streamer.db import get_session, get_combined_next_up

    with get_session() as session:
        # Create a series with a Specials season and Season 1
        series = Series(name="Show X", library_name="TV Shows")
        session.add(series)
        session.flush()

        specials_season = Season(series_id=series.id, name="Specials")
        season1 = Season(series_id=series.id, name="Season 1")
        session.add_all([specials_season, season1])
        session.flush()

        # Episode in Specials (watched, last_played_at is highest)
        spec_ep = Episode(
            season_id=specials_season.id,
            name="Special Episode.mkv",
            path="/p/spec_ep.mkv",
            watched=True,
            last_played_at=2000,
            tmdb_number=1,
        )
        # Episodes in Season 1
        # ep1 is watched, but named "B Title.mkv"
        # ep2 is unwatched, but named "A Title.mkv"
        ep2 = Episode(
            season_id=season1.id,
            name="A Title.mkv",
            path="/p/ep2.mkv",
            watched=False,
            tmdb_number=2,
        )
        ep1 = Episode(
            season_id=season1.id,
            name="B Title.mkv",
            path="/p/ep1.mkv",
            watched=True,
            last_played_at=1000,
            tmdb_number=1,
        )
        session.add_all([spec_ep, ep1, ep2])
        session.commit()

    # Call get_combined_next_up
    results = get_combined_next_up(["TV Shows"])

    # Specials must be completely ignored.
    # The next up episode should be Ep 2 (unwatched) in Season 1.
    assert len(results) == 1
    assert results[0]["series_name"] == "Show X"
    assert results[0]["season_name"] == "Season 1"
    assert results[0]["last_played_at"] == 1000  # From ep1, spec_ep is ignored


def test_get_combined_smart_row_next_up(mock_db_file) -> None:
    from lan_streamer.db import get_session, get_combined_smart_row

    with get_session() as session:
        # Create Series A
        series_a = Series(
            name="Show A", library_name="TV Shows", first_air_date="2020-01-01"
        )
        session.add(series_a)
        session.flush()

        season_a = Season(series_id=series_a.id, name="Season 1")
        session.add(season_a)
        session.flush()

        ep_a1 = Episode(
            season_id=season_a.id,
            name="S01E01.mkv",
            path="/p/a1.mkv",
            watched=True,
            last_played_at=1000,
            date_added=5000,
            air_date="2020-01-01",
        )
        ep_a2 = Episode(
            season_id=season_a.id,
            name="S01E02.mkv",
            path="/p/a2.mkv",
            watched=False,
            last_played_at=0,
            date_added=5000,
            air_date="2020-01-08",
        )
        session.add_all([ep_a1, ep_a2])

        # Create Series B
        series_b = Series(
            name="Show B", library_name="TV Shows", first_air_date="2021-01-01"
        )
        session.add(series_b)
        session.flush()

        season_b = Season(series_id=series_b.id, name="Season 1")
        session.add(season_b)
        session.flush()

        ep_b1 = Episode(
            season_id=season_b.id,
            name="S01E01.mkv",
            path="/p/b1.mkv",
            watched=True,
            last_played_at=2000,
            date_added=4000,
            air_date="2021-01-01",
        )
        ep_b2 = Episode(
            season_id=season_b.id,
            name="S01E02.mkv",
            path="/p/b2.mkv",
            watched=False,
            last_played_at=0,
            date_added=4000,
            air_date="2021-01-08",
        )
        session.add_all([ep_b1, ep_b2])

        # Create Series C
        series_c = Series(
            name="Show C", library_name="TV Shows", first_air_date="2022-01-01"
        )
        session.add(series_c)
        session.flush()

        season_c = Season(series_id=series_c.id, name="Season 1")
        session.add(season_c)
        session.flush()

        ep_c1 = Episode(
            season_id=season_c.id,
            name="S01E01.mkv",
            path="/p/c1.mkv",
            watched=True,
            last_played_at=1500,
            date_added=6000,
            air_date="2022-01-01",
        )
        ep_c2 = Episode(
            season_id=season_c.id,
            name="S01E02.mkv",
            path="/p/c2.mkv",
            watched=False,
            last_played_at=0,
            date_added=6000,
            air_date="2022-01-08",
        )
        session.add_all([ep_c1, ep_c2])
        session.commit()

    # 1. Sort by "Next Up" (only returns next up items, ignores filter_mode since Next Up only targets unwatched)
    # Expected order: Show B (last_played_at=2000), Show C (last_played_at=1500), Show A (last_played_at=1000)
    # The returned objects are of type 'season' representing the next unplayed season.
    results = get_combined_smart_row(["TV Shows"], "Next Up", "All")
    assert len(results) == 3
    assert results[0]["type"] == "season"
    assert results[0]["series_name"] == "Show B"
    assert results[1]["type"] == "season"
    assert results[1]["series_name"] == "Show C"
    assert results[2]["type"] == "season"
    assert results[2]["series_name"] == "Show A"

    # 2. Sort by "Alphabetical" (returns standard series items, filtered by filter_mode)
    # Expected order: Show A, Show B, Show C
    results = get_combined_smart_row(["TV Shows"], "Alphabetical", "All")
    assert len(results) == 3
    assert results[0]["type"] == "series"
    assert results[0]["name"] == "Show A"
    assert results[1]["type"] == "series"
    assert results[1]["name"] == "Show B"
    assert results[2]["type"] == "series"
    assert results[2]["name"] == "Show C"

    # 3. Sort by "Recently Added"
    # Expected order: Show C (max date_added=6000), Show A (max date_added=5000), Show B (max date_added=4000)
    results = get_combined_smart_row(["TV Shows"], "Recently Added", "All")
    assert len(results) == 3
    assert results[0]["type"] == "series"
    assert results[0]["name"] == "Show C"
    assert results[1]["type"] == "series"
    assert results[1]["name"] == "Show A"
    assert results[2]["type"] == "series"
    assert results[2]["name"] == "Show B"

    # 4. Sort by "Recently Aired"
    # Expected order: Show C ("2022-01-08"), Show B ("2021-01-08"), Show A ("2020-01-08")
    results = get_combined_smart_row(["TV Shows"], "Recently Aired", "All")
    assert len(results) == 3
    assert results[0]["type"] == "series"
    assert results[0]["name"] == "Show C"
    assert results[1]["type"] == "series"
    assert results[1]["name"] == "Show B"
    assert results[2]["type"] == "series"
    assert results[2]["name"] == "Show A"


def test_delete_series_record(mock_db_file) -> None:
    test_lib = {
        "DeleteSeries": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path/to/del_ep1.mkv",
                        }
                    ],
                }
            },
        }
    }
    db.save_library("MyLib", test_lib)

    db.delete_series_record("MyLib", "DeleteSeries")

    loaded = db.load_library("MyLib")
    assert "DeleteSeries" not in loaded


def test_delete_episode_record(mock_db_file) -> None:
    test_lib = {
        "TestSeries": {
            "metadata": {},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "Ep 1",
                            "path": "/path/to/del_ep.mkv",
                        }
                    ],
                }
            },
        }
    }
    db.save_library("MyLib", test_lib)

    db.delete_episode_record("/path/to/del_ep.mkv")

    loaded = db.load_library("MyLib")
    eps = loaded["TestSeries"]["seasons"]["Season 1"]["episodes"]
    assert len(eps) == 0
