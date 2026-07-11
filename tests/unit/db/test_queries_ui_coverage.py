"""Coverage tests for queries_ui.py — targeting uncovered lines."""

from __future__ import annotations

from lan_streamer.db import get_session
from lan_streamer.db.queries_ui import (
    get_combined_smart_row,
    get_combined_next_up,
    get_next_episode,
    search_media_names,
)
from lan_streamer.db.models import (
    Series,
    Season,
    Episode,
    Movie,
    MediaFile,
    MetadataFileMapping,
    PlaybackState,
)

import pytest


@pytest.fixture
def mock_db_file(tmp_path):
    return tmp_path / "library.db"


class TestNextUpSpecialsFiltering:
    """Lines 74, 82: specials/special season filtering."""

    def test_specials_season_skipped(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(name="SpecialsShow", library_name="TV")
            session.add(series)
            session.flush()

            specials = Season(series_id=series.id, name="Specials")
            session.add(specials)
            session.flush()

            s1 = Season(series_id=series.id, name="Season 1")
            session.add(s1)
            session.flush()

            ep_special = Episode(
                season_id=specials.id,
                name="Special Ep",
                default_path="/path/special.mkv",
            )
            session.add(ep_special)
            session.flush()

            ep_s1_watched = Episode(
                season_id=s1.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
            )
            ep_s1_next = Episode(
                season_id=s1.id,
                name="Ep2",
                default_path="/path/ep2.mkv",
            )
            session.add_all([ep_s1_watched, ep_s1_next])
            session.flush()

            state_special = PlaybackState(
                episode_id=ep_special.id, watched=True, last_played_at=2000
            )
            state_s1_w = PlaybackState(
                episode_id=ep_s1_watched.id, watched=True, last_played_at=1000
            )
            state_s1_nw = PlaybackState(
                episode_id=ep_s1_next.id, watched=False, last_played_at=0
            )
            session.add_all([state_special, state_s1_w, state_s1_nw])
            session.commit()

        results = get_combined_next_up(["TV"])
        assert len(results) == 1
        assert results[0]["season_name"] == "Season 1"

    def test_season_zero_skipped(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(name="S0Show", library_name="TV")
            session.add(series)
            session.flush()

            s0 = Season(series_id=series.id, name="Season 0")
            session.add(s0)
            session.flush()

            ep = Episode(
                season_id=s0.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
            )
            session.add(ep)
            session.flush()
            state = PlaybackState(episode_id=ep.id, watched=True, last_played_at=1000)
            session.add(state)
            session.commit()

        results = get_combined_next_up(["TV"])
        assert len(results) == 0


class TestNextUpNoNextEpisode:
    """Lines 114, 126: no watched episodes or fully watched."""

    def test_fully_watched_returns_empty(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(name="FullyWatched", library_name="TV")
            session.add(series)
            session.flush()
            s1 = Season(series_id=series.id, name="Season 1")
            session.add(s1)
            session.flush()
            ep = Episode(
                season_id=s1.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
            )
            session.add(ep)
            session.flush()
            state = PlaybackState(episode_id=ep.id, watched=True, last_played_at=1000)
            session.add(state)
            session.commit()

        results = get_combined_next_up(["TV"])
        assert len(results) == 0


class TestNextUpMaxValues:
    """Lines 139, 146, 149: max date_added and air_date calculations."""

    def test_max_values_used(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(
                name="MaxShow",
                library_name="TV",
                first_air_date="2020-01-01",
            )
            session.add(series)
            session.flush()
            s1 = Season(series_id=series.id, name="Season 1")
            session.add(s1)
            session.flush()
            ep_watched = Episode(
                season_id=s1.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
                date_added=5000,
                air_date="2023-06-01",
            )
            ep_unwatched = Episode(
                season_id=s1.id,
                name="Ep2",
                default_path="/path/ep2.mkv",
                date_added=6000,
                air_date="2023-07-01",
            )
            session.add_all([ep_watched, ep_unwatched])
            session.flush()
            state = PlaybackState(
                episode_id=ep_watched.id, watched=True, last_played_at=2000
            )
            session.add(state)
            session.commit()

        results = get_combined_next_up(["TV"])
        assert len(results) == 1
        assert results[0]["date_added"] == 6000
        assert results[0]["air_date"] == "2023-07-01"


class TestNextUpNoNextSeason:
    """Line 130: next_up_episode has no season."""

    def test_empty_series_no_results(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(name="EmptyShow", library_name="TV")
            session.add(series)
            session.commit()

        results = get_combined_next_up(["TV"])
        assert len(results) == 0


class TestSmartRowNextUpDelegation:
    """Lines 206-210: smart row delegates to next_up when sort_by='Next Up'."""

    def test_next_up_sort_delegates(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(name="NUSort", library_name="TV")
            session.add(series)
            session.flush()
            s1 = Season(series_id=series.id, name="Season 1")
            session.add(s1)
            session.flush()
            ep = Episode(
                season_id=s1.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
            )
            session.add(ep)
            session.flush()
            state = PlaybackState(episode_id=ep.id, watched=True, last_played_at=1000)
            session.add(state)

            ep2 = Episode(
                season_id=s1.id,
                name="Ep2",
                default_path="/path/ep2.mkv",
            )
            session.add(ep2)
            session.flush()
            state2 = PlaybackState(
                episode_id=ep2.id, watched=False, last_played_at=1000
            )
            session.add(state2)
            session.commit()

        results = get_combined_smart_row(["TV"], "Next Up", "All")
        assert len(results) == 1
        assert results[0]["type"] == "season"


class TestSmartRowSortModes:
    """Lines 314-322: various sort modes."""

    def test_alphabetical_sort(self, mock_db_file) -> None:
        with get_session() as session:
            for name in ["Zebra Show", "Alpha Show"]:
                series = Series(name=name, library_name="TV")
                session.add(series)
                session.flush()
                s = Season(series_id=series.id, name="Season 1")
                session.add(s)
                session.flush()
                ep = Episode(
                    season_id=s.id,
                    name="Ep1",
                    default_path=f"/path/{name}.mkv",
                )
                session.add(ep)
            session.commit()

        results = get_combined_smart_row(["TV"], "Alphabetical", "All")
        assert len(results) == 2
        assert results[0]["name"] == "Alpha Show"
        assert results[1]["name"] == "Zebra Show"

    def test_recently_added_sort(self, mock_db_file) -> None:
        with get_session() as session:
            s1 = Series(name="OldShow", library_name="TV")
            session.add(s1)
            session.flush()
            seas1 = Season(series_id=s1.id, name="Season 1")
            session.add(seas1)
            session.flush()
            ep1 = Episode(
                season_id=seas1.id,
                name="Ep1",
                default_path="/path/old.mkv",
                date_added=100,
            )
            session.add(ep1)

            s2 = Series(name="NewShow", library_name="TV")
            session.add(s2)
            session.flush()
            seas2 = Season(series_id=s2.id, name="Season 1")
            session.add(seas2)
            session.flush()
            ep2 = Episode(
                season_id=seas2.id,
                name="Ep1",
                default_path="/path/new.mkv",
                date_added=999,
            )
            session.add(ep2)
            session.commit()

        results = get_combined_smart_row(["TV"], "Recently Added", "All")
        assert len(results) == 2
        assert results[0]["name"] == "NewShow"
        assert results[1]["name"] == "OldShow"

    def test_recently_aired_sort(self, mock_db_file) -> None:
        with get_session() as session:
            s1 = Series(name="OldAired", library_name="TV")
            session.add(s1)
            session.flush()
            seas1 = Season(series_id=s1.id, name="Season 1")
            session.add(seas1)
            session.flush()
            ep1 = Episode(
                season_id=seas1.id,
                name="Ep1",
                default_path="/path/old.mkv",
                air_date="2020-01-01",
            )
            session.add(ep1)

            s2 = Series(name="NewAired", library_name="TV")
            session.add(s2)
            session.flush()
            seas2 = Season(series_id=s2.id, name="Season 1")
            session.add(seas2)
            session.flush()
            ep2 = Episode(
                season_id=seas2.id,
                name="Ep1",
                default_path="/path/new.mkv",
                air_date="2024-01-01",
            )
            session.add(ep2)
            session.commit()

        results = get_combined_smart_row(["TV"], "Recently Aired", "All")
        assert len(results) == 2
        assert results[0]["name"] == "NewAired"


class TestSmartRowDefaultSort:
    """Line 322: default fallback sort."""

    def test_unknown_sort_uses_alphabetical(self, mock_db_file) -> None:
        with get_session() as session:
            for name in ["Bravo", "Alpha"]:
                series = Series(name=name, library_name="TV")
                session.add(series)
                session.flush()
                s = Season(series_id=series.id, name="Season 1")
                session.add(s)
                session.flush()
                ep = Episode(
                    season_id=s.id,
                    name="Ep1",
                    default_path=f"/path/{name}.mkv",
                )
                session.add(ep)
            session.commit()

        results = get_combined_smart_row(["TV"], "UnknownSort", "All")
        assert len(results) == 2
        assert results[0]["name"] == "Alpha"


class TestSmartRowException:
    """Lines 331-333: exception handling."""

    def test_exception_returns_empty(self, mock_db_file) -> None:
        from unittest.mock import patch as mock_patch

        with mock_patch(
            "lan_streamer.db.queries_ui.get_session",
            side_effect=Exception("db error"),
        ):
            results = get_combined_smart_row(["TV"], "Alphabetical", "All")
            assert results == []


class TestNextEpisodeNotFound:
    """Lines 356-359, 376-377: current episode or series not found."""

    def test_unknown_path_returns_none(self, mock_db_file) -> None:
        result = get_next_episode("/nonexistent/path.mkv")
        assert result is None


class TestNextEpisodeLastEpisode:
    """Lines 413-414, 417-418: current is last episode."""

    def test_last_episode_returns_none(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(name="LastShow", library_name="TV")
            session.add(series)
            session.flush()
            s1 = Season(series_id=series.id, name="Season 1")
            session.add(s1)
            session.flush()
            ep = Episode(
                season_id=s1.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
                tmdb_number=1,
            )
            session.add(ep)
            session.flush()
            mf = MediaFile(path="/path/ep1.mkv")
            session.add(mf)
            session.flush()
            mapping = MetadataFileMapping(
                media_file_id=mf.id,
                episode_id=ep.id,
            )
            session.add(mapping)
            session.commit()

        result = get_next_episode("/path/ep1.mkv")
        assert result is None


class TestNextEpisodePlaceholderNext:
    """Lines 429-430: next episode has no file path."""

    def test_placeholder_next_returns_none(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(name="PlaceholderNext", library_name="TV")
            session.add(series)
            session.flush()
            s1 = Season(series_id=series.id, name="Season 1")
            session.add(s1)
            session.flush()
            ep1 = Episode(
                season_id=s1.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
                tmdb_number=1,
            )
            ep2 = Episode(
                season_id=s1.id,
                name="Ep2",
                default_path=None,
                tmdb_number=2,
            )
            session.add_all([ep1, ep2])
            session.flush()
            mf1 = MediaFile(path="/path/ep1.mkv")
            session.add(mf1)
            session.flush()
            mapping = MetadataFileMapping(
                media_file_id=mf1.id,
                episode_id=ep1.id,
            )
            session.add(mapping)
            session.commit()

        result = get_next_episode("/path/ep1.mkv")
        assert result is None


class TestNextEpisodeException:
    """Lines 448-450: exception handling."""

    def test_exception_returns_none(self, mock_db_file) -> None:
        from unittest.mock import patch as mock_patch

        with mock_patch(
            "lan_streamer.db.queries_ui.get_session",
            side_effect=Exception("db error"),
        ):
            result = get_next_episode("/any/path.mkv")
            assert result is None


class TestSearchMediaNames:
    """Lines 473-533: search_media_names."""

    def test_empty_query_returns_empty(self, mock_db_file) -> None:
        assert search_media_names("") == []
        assert search_media_names("a") == []
        assert search_media_names(None) == []

    def test_exact_match_first(self, mock_db_file) -> None:
        with get_session() as session:
            s1 = Series(name="Test Show", library_name="TV")
            session.add(s1)
            s2 = Series(name="Best Test Show", library_name="TV")
            session.add(s2)
            s3 = Series(name="Testing Grounds", library_name="TV")
            session.add(s3)
            session.commit()

        results = search_media_names("test show")
        assert len(results) == 2
        assert results[0]["name"] == "Test Show"
        assert results[1]["name"] == "Best Test Show"

    def test_with_library_filter(self, mock_db_file) -> None:
        with get_session() as session:
            s1 = Series(name="Filtered Show", library_name="TV")
            session.add(s1)
            m1 = Movie(name="Filtered Show", library_name="Movies")
            session.add(m1)
            session.commit()

        results = search_media_names("Filtered", library_names=["TV"])
        assert len(results) == 1
        assert results[0]["type"] == "series"

    def test_short_query_returns_empty(self, mock_db_file) -> None:
        assert search_media_names("x") == []

    def test_limit_respected(self, mock_db_file) -> None:
        with get_session() as session:
            for i in range(10):
                s = Series(name=f"Limit Show {i}", library_name="TV")
                session.add(s)
            session.commit()

        results = search_media_names("Limit Show", limit=3)
        assert len(results) == 3

    def test_movie_in_results(self, mock_db_file) -> None:
        with get_session() as session:
            m = Movie(name="Test Movie", library_name="Movies")
            session.add(m)
            session.commit()

        results = search_media_names("Test Movie")
        assert len(results) == 1
        assert results[0]["type"] == "movie"

    def test_exception_returns_empty(self, mock_db_file) -> None:
        from unittest.mock import patch as mock_patch

        with mock_patch(
            "lan_streamer.db.queries_ui.get_session",
            side_effect=Exception("db error"),
        ):
            results = search_media_names("anything")
            assert results == []


class TestNextUpEmptySeasonName:
    """Line 74: season with empty name is skipped."""

    def test_empty_name_season_skipped(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(name="EmptyNameShow", library_name="TV")
            session.add(series)
            session.flush()
            s1 = Season(series_id=series.id, name="")
            session.add(s1)
            session.flush()
            ep = Episode(
                season_id=s1.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
            )
            session.add(ep)
            session.flush()
            state = PlaybackState(episode_id=ep.id, watched=True, last_played_at=1000)
            session.add(state)
            session.commit()

        results = get_combined_next_up(["TV"])
        assert len(results) == 0


class TestSmartRowWatchedFilter:
    """Lines 252, 257: watched filter mode in smart row."""

    def test_watched_filter_series(self, mock_db_file) -> None:
        with get_session() as session:
            s = Series(name="WatchedSeries", library_name="TV")
            session.add(s)
            session.flush()
            seas = Season(series_id=s.id, name="Season 1")
            session.add(seas)
            session.flush()
            ep = Episode(
                season_id=seas.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
            )
            session.add(ep)
            session.flush()
            state = PlaybackState(episode_id=ep.id, watched=True, last_played_at=1000)
            session.add(state)
            session.commit()

        results = get_combined_smart_row(["TV"], "Alphabetical", "Watched")
        assert len(results) == 1
        assert results[0]["watched_count"] == results[0]["total_count"]

    def test_unwatched_filter_series(self, mock_db_file) -> None:
        with get_session() as session:
            s = Series(name="UnwatchedSeries", library_name="TV")
            session.add(s)
            session.flush()
            seas = Season(series_id=s.id, name="Season 1")
            session.add(seas)
            session.flush()
            ep = Episode(
                season_id=seas.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
            )
            session.add(ep)
            session.commit()

        results = get_combined_smart_row(["TV"], "Alphabetical", "Unwatched")
        assert len(results) == 1
        assert results[0]["watched_count"] == 0

    def test_empty_series_excluded(self, mock_db_file) -> None:
        with get_session() as session:
            s = Series(name="EmptySeries", library_name="TV")
            session.add(s)
            session.commit()

        results = get_combined_smart_row(["TV"], "Alphabetical", "All")
        assert len(results) == 0


class TestSmartRowMovieFilter:
    """Lines 288-298: movie filter in smart row."""

    def test_watched_movie_included(self, mock_db_file) -> None:
        with get_session() as session:
            m = Movie(name="WatchedMovie", library_name="Movies")
            session.add(m)
            session.flush()
            state = PlaybackState(movie_id=m.id, watched=True, last_played_at=1000)
            session.add(state)
            session.commit()

        results = get_combined_smart_row(["Movies"], "Alphabetical", "Watched")
        assert len(results) == 1
        assert results[0]["type"] == "movie"

    def test_unwatched_movie_included(self, mock_db_file) -> None:
        with get_session() as session:
            m = Movie(name="UnwatchedMovie", library_name="Movies")
            session.add(m)
            session.commit()

        results = get_combined_smart_row(["Movies"], "Alphabetical", "Unwatched")
        assert len(results) == 1
        assert results[0]["watched_count"] == 0


class TestNextEpisodeSuccess:
    """Lines 421-447: successful next episode resolution."""

    def test_returns_next_episode(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(
                name="NextShow",
                library_name="TV",
                poster_path="/posters/next.jpg",
            )
            session.add(series)
            session.flush()
            s1 = Season(series_id=series.id, name="Season 1")
            session.add(s1)
            session.flush()
            ep1 = Episode(
                season_id=s1.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
                tmdb_number=1,
                tmdb_name="Episode One",
                runtime=30,
            )
            ep2 = Episode(
                season_id=s1.id,
                name="Ep2",
                default_path="/path/ep2.mkv",
                tmdb_number=2,
                tmdb_name="Episode Two",
                runtime=25,
            )
            session.add_all([ep1, ep2])
            session.flush()
            mf1 = MediaFile(path="/path/ep1.mkv")
            mf2 = MediaFile(path="/path/ep2.mkv")
            session.add_all([mf1, mf2])
            session.flush()
            mapping1 = MetadataFileMapping(media_file_id=mf1.id, episode_id=ep1.id)
            mapping2 = MetadataFileMapping(media_file_id=mf2.id, episode_id=ep2.id)
            session.add_all([mapping1, mapping2])
            session.commit()

        result = get_next_episode("/path/ep1.mkv")
        assert result is not None
        assert result["title"] == "Episode Two"
        assert result["season"] == "Season 1"
        assert result["episode_number"] == 2
        assert result["path"] == "/path/ep2.mkv"


class TestNextEpisodeFromMediaFiles:
    """Lines 425-427: next episode path from media_files when no default_path."""

    def test_falls_back_to_media_file(self, mock_db_file) -> None:
        with get_session() as session:
            series = Series(name="FallbackShow", library_name="TV")
            session.add(series)
            session.flush()
            s1 = Season(series_id=series.id, name="Season 1")
            session.add(s1)
            session.flush()
            ep1 = Episode(
                season_id=s1.id,
                name="Ep1",
                default_path="/path/ep1.mkv",
                tmdb_number=1,
            )
            ep2 = Episode(
                season_id=s1.id,
                name="Ep2",
                default_path=None,
                tmdb_number=2,
            )
            session.add_all([ep1, ep2])
            session.flush()
            mf1 = MediaFile(path="/path/ep1.mkv")
            mf2 = MediaFile(path="/media/ep2.mkv")
            session.add_all([mf1, mf2])
            session.flush()
            mapping1 = MetadataFileMapping(media_file_id=mf1.id, episode_id=ep1.id)
            mapping2 = MetadataFileMapping(media_file_id=mf2.id, episode_id=ep2.id)
            session.add_all([mapping1, mapping2])
            session.commit()

        result = get_next_episode("/path/ep1.mkv")
        assert result is not None
        assert result["path"] == "/media/ep2.mkv"
