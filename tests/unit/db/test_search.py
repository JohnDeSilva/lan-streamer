"""
Tests for db/queries_ui.py – search_series_names
"""

import pytest

from lan_streamer.db import get_session
from lan_streamer.db.queries_ui import search_series_names
from lan_streamer.db.models import Series


@pytest.fixture
def mock_db_file(tmp_path):
    return tmp_path / "library.db"


def _create_series(session, name: str, library_name: str = "TV Shows") -> Series:
    series = Series(name=name, library_name=library_name)
    session.add(series)
    session.flush()
    return series


class TestSearchSeriesNames:
    """Tests for search_series_names function."""

    def test_exact_match_first(self, mock_db_file) -> None:
        """Exact matches should appear before partial matches."""
        with get_session() as session:
            _create_series(session, "Attack on Titan", "Anime")
            _create_series(session, "Attack on Titan: Junior High", "Anime")
            _create_series(session, "Attack on Titan: The Final Season", "Anime")
            session.commit()

        results = search_series_names("Attack on Titan", ["Anime"])
        assert len(results) >= 1
        assert results[0]["name"] == "Attack on Titan"

    def test_filters_by_library(self, mock_db_file) -> None:
        """Search should filter results when library_names is provided."""
        with get_session() as session:
            _create_series(session, "Breaking Bad", "TV Shows")
            _create_series(session, "Breaking Bad", "Anime")
            session.commit()

        results = search_series_names("Breaking Bad", ["TV Shows"])
        assert len(results) == 1
        assert results[0]["library_name"] == "TV Shows"

    def test_empty_query_returns_empty(self, mock_db_file) -> None:
        """Query with fewer than 2 characters returns empty list."""
        assert search_series_names("") == []
        assert search_series_names("a") == []

    def test_no_matches_returns_empty(self, mock_db_file) -> None:
        """Search with no matching results returns empty list."""
        with get_session() as session:
            _create_series(session, "Existing Show", "TV Shows")
            session.commit()

        results = search_series_names("Nonexistent Show")
        assert results == []

    def test_case_insensitive(self, mock_db_file) -> None:
        """Search should be case-insensitive."""
        with get_session() as session:
            _create_series(session, "Star Trek: The Next Generation", "TV Shows")
            session.commit()

        results_lower = search_series_names("star trek", ["TV Shows"])
        results_upper = search_series_names("STAR TREK", ["TV Shows"])
        results_mixed = search_series_names("Star Trek", ["TV Shows"])
        assert len(results_lower) == 1
        assert len(results_upper) == 1
        assert len(results_mixed) == 1

    def test_all_libraries_when_none(self, mock_db_file) -> None:
        """When library_names is None, search all libraries."""
        with get_session() as session:
            _create_series(session, "Show A", "Library 1")
            _create_series(session, "Show A", "Library 2")
            session.commit()

        results = search_series_names("Show A")
        assert len(results) == 2

    def test_empty_library_list_searches_all(self, mock_db_file) -> None:
        """When library_names is empty list, search all libraries."""
        with get_session() as session:
            _create_series(session, "Show B", "Library 1")
            _create_series(session, "Show B", "Library 2")
            session.commit()

        results = search_series_names("Show B", [])
        assert len(results) == 2

    def test_respects_limit(self, mock_db_file) -> None:
        """Search should not return more than limit results."""
        with get_session() as session:
            for i in range(100):
                _create_series(session, f"Test Series {i:03d}", "Library")
            session.commit()

        results = search_series_names("Test Series", limit=10)
        assert len(results) <= 10

    def test_returns_correct_fields(self, mock_db_file) -> None:
        """Results should contain name, library_name, poster_path."""
        with get_session() as session:
            series = _create_series(session, "Test Show", "TV")
            series.poster_path = "/path/to/poster.jpg"
            session.commit()

        results = search_series_names("Test Show")
        assert len(results) == 1
        assert results[0]["name"] == "Test Show"
        assert results[0]["library_name"] == "TV"
        assert results[0]["poster_path"] == "/path/to/poster.jpg"

    def test_starts_with_before_contains(self, mock_db_file) -> None:
        """Results starting with query should appear before containing query."""
        with get_session() as session:
            _create_series(session, "The Man Show", "TV")
            _create_series(session, "Man vs. Wild", "TV")
            _create_series(session, "The Man in the High Castle", "TV")
            _create_series(session, "Iron Man", "TV")
            session.commit()

        results = search_series_names("Man", ["TV"])
        names = [r["name"] for r in results]
        # "Man vs. Wild" starts with "Man" -> should be before "Iron Man" (contains)
        man_index = names.index("Man vs. Wild")
        iron_man_index = names.index("Iron Man")
        assert man_index < iron_man_index

    def test_whitespace_only_returns_empty(self, mock_db_file) -> None:
        """Whitespace-only query returns empty list."""
        with get_session() as session:
            _create_series(session, "Some Show", "TV")
            session.commit()

        assert search_series_names("   ") == []

    def test_whitespace_padded_query(self, mock_db_file) -> None:
        """Query with surrounding whitespace is trimmed."""
        with get_session() as session:
            _create_series(session, "Trimmed Show", "TV")
            session.commit()

        results = search_series_names("  Trimmed Show  ", ["TV"])
        assert len(results) == 1
        assert results[0]["name"] == "Trimmed Show"

    def test_special_characters_handled(self, mock_db_file) -> None:
        """Search handles special characters in query."""
        with get_session() as session:
            _create_series(session, "Dr. Who (2005)", "TV")
            _create_series(session, "100% Wolf", "TV")
            session.commit()

        results = search_series_names("Dr. Who", ["TV"])
        assert len(results) == 1
        assert results[0]["name"] == "Dr. Who (2005)"

        results2 = search_series_names("100%", ["TV"])
        assert len(results2) == 1
        assert results2[0]["name"] == "100% Wolf"

    def test_poster_path_none_becomes_empty(self, mock_db_file) -> None:
        """When poster_path is None, result contains empty string."""
        with get_session() as session:
            series = _create_series(session, "No Poster", "TV")
            series.poster_path = None
            session.commit()

        results = search_series_names("No Poster", ["TV"])
        assert results[0]["poster_path"] == ""
