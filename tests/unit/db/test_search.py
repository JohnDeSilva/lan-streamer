"""
Tests for db/queries_ui.py – search_media_names (series + movies)
"""

import pytest

from lan_streamer.db import get_session
from lan_streamer.db.queries_ui import search_media_names
from lan_streamer.db.models import Series, Movie


@pytest.fixture
def mock_db_file(tmp_path):
    return tmp_path / "library.db"


def _create_series(session, name: str, library_name: str = "TV Shows") -> Series:
    series = Series(name=name, library_name=library_name)
    session.add(series)
    session.flush()
    return series


def _create_movie(session, name: str, library_name: str = "Movies") -> Movie:
    movie = Movie(name=name, library_name=library_name)
    session.add(movie)
    session.flush()
    return movie


class TestSearchMediaNames:
    """Tests for search_media_names function."""

    def test_exact_match_first(self, mock_db_file) -> None:
        """Exact matches should appear before partial matches."""
        with get_session() as session:
            _create_series(session, "Attack on Titan", "Anime")
            _create_series(session, "Attack on Titan: Junior High", "Anime")
            session.commit()

        results = search_media_names("Attack on Titan", ["Anime"])
        assert len(results) >= 1
        assert results[0]["name"] == "Attack on Titan"

    def test_filters_by_library(self, mock_db_file) -> None:
        """Search should filter results when library_names is provided."""
        with get_session() as session:
            _create_series(session, "Breaking Bad", "TV Shows")
            _create_series(session, "Breaking Bad", "Anime")
            session.commit()

        results = search_media_names("Breaking Bad", ["TV Shows"])
        assert len(results) == 1
        assert results[0]["library_name"] == "TV Shows"

    def test_empty_query_returns_empty(self, mock_db_file) -> None:
        """Query with fewer than 2 characters returns empty list."""
        assert search_media_names("") == []
        assert search_media_names("a") == []

    def test_no_matches_returns_empty(self, mock_db_file) -> None:
        """Search with no matching results returns empty list."""
        with get_session() as session:
            _create_series(session, "Existing Show", "TV Shows")
            session.commit()

        results = search_media_names("Nonexistent")
        assert results == []

    def test_case_insensitive(self, mock_db_file) -> None:
        """Search should be case-insensitive."""
        with get_session() as session:
            _create_series(session, "Star Trek: The Next Generation", "TV Shows")
            session.commit()

        results_lower = search_media_names("star trek", ["TV Shows"])
        results_upper = search_media_names("STAR TREK", ["TV Shows"])
        assert len(results_lower) == 1
        assert len(results_upper) == 1

    def test_all_libraries_when_none(self, mock_db_file) -> None:
        """When library_names is None, search all libraries."""
        with get_session() as session:
            _create_series(session, "Show A", "Library 1")
            _create_series(session, "Show A", "Library 2")
            session.commit()

        results = search_media_names("Show A")
        assert len(results) == 2

    def test_empty_library_list_searches_all(self, mock_db_file) -> None:
        """When library_names is empty list, search all libraries."""
        with get_session() as session:
            _create_series(session, "Show B", "Library 1")
            _create_series(session, "Show B", "Library 2")
            session.commit()

        results = search_media_names("Show B", [])
        assert len(results) == 2

    def test_respects_limit(self, mock_db_file) -> None:
        """Search should not return more than limit results."""
        with get_session() as session:
            for i in range(100):
                _create_series(session, f"Test Series {i:03d}", "Library")
            session.commit()

        results = search_media_names("Test Series", limit=10)
        assert len(results) <= 10

    def test_returns_correct_fields(self, mock_db_file) -> None:
        """Results should contain name, library_name, poster_path, type."""
        with get_session() as session:
            series = _create_series(session, "Test Show", "TV")
            series.poster_path = "/path/to/poster.jpg"
            session.commit()

        results = search_media_names("Test Show")
        assert len(results) == 1
        assert results[0]["name"] == "Test Show"
        assert results[0]["library_name"] == "TV"
        assert results[0]["poster_path"] == "/path/to/poster.jpg"
        assert results[0]["type"] == "series"

    def test_starts_with_before_contains(self, mock_db_file) -> None:
        """Results starting with query should appear before containing query."""
        with get_session() as session:
            _create_series(session, "The Man Show", "TV")
            _create_series(session, "Man vs. Wild", "TV")
            _create_series(session, "Iron Man", "TV")
            session.commit()

        results = search_media_names("Man", ["TV"])
        names = [r["name"] for r in results]
        man_index = names.index("Man vs. Wild")
        iron_man_index = names.index("Iron Man")
        assert man_index < iron_man_index

    def test_whitespace_only_returns_empty(self, mock_db_file) -> None:
        """Whitespace-only query returns empty list."""
        with get_session() as session:
            _create_series(session, "Some Show", "TV")
            session.commit()

        assert search_media_names("   ") == []

    def test_poster_path_none_becomes_empty(self, mock_db_file) -> None:
        """When poster_path is None, result contains empty string."""
        with get_session() as session:
            series = _create_series(session, "No Poster", "TV")
            series.poster_path = None
            session.commit()

        results = search_media_names("No Poster", ["TV"])
        assert results[0]["poster_path"] == ""

    def test_returns_movie_type(self, mock_db_file) -> None:
        """Movie results should have type 'movie'."""
        with get_session() as session:
            _create_movie(session, "Interstellar", "Movies")
            session.commit()

        results = search_media_names("Interstellar", ["Movies"])
        assert len(results) == 1
        assert results[0]["type"] == "movie"

    def test_returns_series_type(self, mock_db_file) -> None:
        """Series results should have type 'series'."""
        with get_session() as session:
            _create_series(session, "Breaking Bad", "TV")
            session.commit()

        results = search_media_names("Breaking Bad", ["TV"])
        assert len(results) == 1
        assert results[0]["type"] == "series"

    def test_returns_both_types(self, mock_db_file) -> None:
        """Search should return both series and movies."""
        with get_session() as session:
            _create_series(session, "The Dark Knight", "TV")
            _create_movie(session, "The Dark Knight", "Movies")
            session.commit()

        results = search_media_names("The Dark Knight")
        assert len(results) == 2
        types = {r["type"] for r in results}
        assert types == {"series", "movie"}

    def test_movie_library_filter(self, mock_db_file) -> None:
        """Movie search should filter by library."""
        with get_session() as session:
            _create_movie(session, "Inception", "Sci-Fi")
            _create_movie(session, "Inception", "Action")
            session.commit()

        results = search_media_names("Inception", ["Sci-Fi"])
        assert len(results) == 1
        assert results[0]["library_name"] == "Sci-Fi"
        assert results[0]["type"] == "movie"

    def test_movie_poster_path(self, mock_db_file) -> None:
        """Movie poster_path should be included in results."""
        with get_session() as session:
            movie = _create_movie(session, "The Matrix", "Movies")
            movie.poster_path = "/posters/matrix.jpg"
            session.commit()

        results = search_media_names("The Matrix", ["Movies"])
        assert results[0]["poster_path"] == "/posters/matrix.jpg"
