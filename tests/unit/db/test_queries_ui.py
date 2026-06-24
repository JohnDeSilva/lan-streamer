import pytest
from lan_streamer.db import get_session
from lan_streamer.db.queries_ui import (
    get_combined_smart_row,
    get_combined_next_up,
    get_next_episode,
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


@pytest.fixture
def mock_db_file(tmp_path):
    return tmp_path / "library.db"


def test_get_combined_smart_row_filters(mock_db_file) -> None:
    """Test get_combined_smart_row Watched and Unwatched filter modes."""
    with get_session() as session:
        # Fully watched series
        series_watched = Series(name="Watched Show", library_name="TV Shows")
        session.add(series_watched)
        session.flush()
        season_watched = Season(series_id=series_watched.id, name="Season 1")
        session.add(season_watched)
        session.flush()
        episode_watched = Episode(
            season_id=season_watched.id,
            name="Episode 1",
            default_path="/path/watched_episode.mkv",
        )
        session.add(episode_watched)
        session.flush()
        state_watched = PlaybackState(episode_id=episode_watched.id, watched=True)
        session.add(state_watched)

        # Unwatched series (partially watched)
        series_unwatched = Series(name="Unwatched Show", library_name="TV Shows")
        session.add(series_unwatched)
        session.flush()
        season_unwatched = Season(series_id=series_unwatched.id, name="Season 1")
        session.add(season_unwatched)
        session.flush()
        episode_unwatched_1 = Episode(
            season_id=season_unwatched.id,
            name="Episode 1",
            default_path="/path/unwatched_episode_1.mkv",
        )
        episode_unwatched_2 = Episode(
            season_id=season_unwatched.id,
            name="Episode 2",
            default_path="/path/unwatched_episode_2.mkv",
        )
        session.add_all([episode_unwatched_1, episode_unwatched_2])
        session.flush()
        state_unwatched_1 = PlaybackState(
            episode_id=episode_unwatched_1.id, watched=True
        )
        state_unwatched_2 = PlaybackState(
            episode_id=episode_unwatched_2.id, watched=False
        )
        session.add_all([state_unwatched_1, state_unwatched_2])

        # Watched movie
        movie_watched = Movie(
            name="Watched Movie",
            library_name="Movies",
            default_path="/path/watched_movie.mkv",
        )
        session.add(movie_watched)
        session.flush()
        state_movie_watched = PlaybackState(movie_id=movie_watched.id, watched=True)
        session.add(state_movie_watched)

        # Unwatched movie
        movie_unwatched = Movie(
            name="Unwatched Movie",
            library_name="Movies",
            default_path="/path/unwatched_movie.mkv",
        )
        session.add(movie_unwatched)
        session.flush()
        state_movie_unwatched = PlaybackState(
            movie_id=movie_unwatched.id, watched=False
        )
        session.add(state_movie_unwatched)

        session.commit()

    # Watched filter
    results_watched = get_combined_smart_row(
        ["TV Shows", "Movies"], "Alphabetical", "Watched"
    )
    names_watched = {item["name"] for item in results_watched}
    assert "Watched Show" in names_watched
    assert "Watched Movie" in names_watched
    assert "Unwatched Show" not in names_watched
    assert "Unwatched Movie" not in names_watched

    # Unwatched filter
    results_unwatched = get_combined_smart_row(
        ["TV Shows", "Movies"], "Alphabetical", "Unwatched"
    )
    names_unwatched = {item["name"] for item in results_unwatched}
    assert "Unwatched Show" in names_unwatched
    assert "Unwatched Movie" in names_unwatched
    assert "Watched Show" not in names_unwatched
    assert "Watched Movie" not in names_unwatched


def test_get_combined_next_up_logic(mock_db_file) -> None:
    """Test get_combined_next_up correctly calculates next unwatched season."""
    with get_session() as session:
        series = Series(name="Next Up Show", library_name="TV Shows")
        session.add(series)
        session.flush()

        season_1 = Season(series_id=series.id, name="Season 1")
        season_2 = Season(series_id=series.id, name="Season 2")
        session.add_all([season_1, season_2])
        session.flush()

        # Season 1 fully watched
        episode_1 = Episode(
            season_id=season_1.id, name="Episode 1", default_path="/path/e1.mkv"
        )
        session.add(episode_1)
        session.flush()
        state_1 = PlaybackState(
            episode_id=episode_1.id, watched=True, last_played_at=1000
        )
        session.add(state_1)

        # Season 2 unwatched
        episode_2 = Episode(
            season_id=season_2.id, name="Episode 1", default_path="/path/e2.mkv"
        )
        session.add(episode_2)
        session.flush()
        state_2 = PlaybackState(episode_id=episode_2.id, watched=False)
        session.add(state_2)

        session.commit()

    results = get_combined_next_up(["TV Shows"])
    assert len(results) == 1
    assert results[0]["series_name"] == "Next Up Show"
    assert results[0]["season_name"] == "Season 2"


def test_get_next_episode_finding(mock_db_file) -> None:
    """Test get_next_episode finds the next physical episode and skips placeholders."""
    with get_session() as session:
        series = Series(name="Show", library_name="TV Shows")
        session.add(series)
        session.flush()

        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()

        episode_1 = Episode(
            season_id=season.id,
            name="Episode 1",
            default_path="/path/e1.mkv",
            tmdb_number=1,
        )
        episode_2 = Episode(
            season_id=season.id, name="Episode 2", default_path=None, tmdb_number=2
        )  # Placeholder
        episode_3 = Episode(
            season_id=season.id,
            name="Episode 3",
            default_path="/path/e3.mkv",
            tmdb_number=3,
        )
        session.add_all([episode_1, episode_2, episode_3])
        session.flush()

        media_file_1 = MediaFile(path="/path/e1.mkv")
        media_file_3 = MediaFile(path="/path/e3.mkv")
        session.add_all([media_file_1, media_file_3])
        session.flush()

        mapping_1 = MetadataFileMapping(
            media_file_id=media_file_1.id, episode_id=episode_1.id
        )
        mapping_3 = MetadataFileMapping(
            media_file_id=media_file_3.id, episode_id=episode_3.id
        )
        session.add_all([mapping_1, mapping_3])

        session.commit()

    # Next episode after episode 1 should be episode 3, skipping the placeholder episode 2
    next_episode_info = get_next_episode("/path/e1.mkv")
    assert next_episode_info is not None
    assert next_episode_info["title"] == "Episode 3"
    assert next_episode_info["path"] == "/path/e3.mkv"
