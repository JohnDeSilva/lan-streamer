"""
Targeted tests for db/library.py covering:
 - _save_episode_record: promote placeholder, fallback name-match, stale placeholder deletion
 - _apply_movie_fields: audio_tracks / subtitle_tracks json fields
 - save_movie_library: TMDB id-based match, stale movie name collision
 - cleanup_library: tv library (episode path null'd out, series removed)
 - cleanup_library: movie library (missing movie removed)
 - load_library exception path
 - save_library exception path

Missing lines to hit: 46, 53, 55, 58, 64, 218, 243-246, 258, 293, 295, 297, 299, 302, 308,
  369-370, 373, 402-403, 488-496, 512, 563, 569
"""

import pytest
import json
from typing import Any, Dict
from unittest.mock import patch

import lan_streamer.db as db
from lan_streamer.db import get_session
from lan_streamer.db.models import Series, Season, Episode, Movie
from lan_streamer.system.config import config


# ---------------------------------------------------------------------------
# _apply_movie_fields - audio/subtitle json fields and remaining branches
# ---------------------------------------------------------------------------


def test_apply_movie_fields_audio_subtitle_json(mock_db_file) -> None:
    """_apply_movie_fields should JSON-encode audio and subtitle tracks."""
    from lan_streamer.db.library import _apply_movie_fields

    with get_session() as session:
        movie = Movie(name="TestMovie", library_name="Lib")
        session.add(movie)
        session.flush()

        movie_data = {
            "path": "/movies/test.mkv",
            "audio_tracks": [{"lang": "en"}, {"lang": "fr"}],
            "subtitle_tracks": [{"lang": "de"}],
            "myanimelist_anime_id": 12345,
            "video_codec": "H.264",
            "resolution": "1080p",
        }
        _apply_movie_fields(movie, movie_data)
        session.commit()

        assert json.loads(movie.audio_tracks) == [{"lang": "en"}, {"lang": "fr"}]
        assert json.loads(movie.subtitle_tracks) == [{"lang": "de"}]
        assert movie.myanimelist_anime_id == 12345
        assert movie.video_codec == "H.264"
        assert movie.resolution == "1080p"


def test_apply_movie_fields_date_added_int_comparison(mock_db_file) -> None:
    """_apply_movie_fields should normalize float date_added to int to avoid false changed flag."""
    from lan_streamer.db.library import _apply_movie_fields

    with get_session() as session:
        movie = Movie(
            name="DateAddedMovie",
            library_name="Lib",
            date_added=1234567890,
        )
        session.add(movie)
        session.flush()

        movie_data = {
            "date_added": 1234567890.999,
        }

        changed = _apply_movie_fields(movie, movie_data)
        session.commit()

        assert changed is False
        assert movie.date_added == 1234567890


def test_apply_movie_fields_empty_audio_subtitle_keeps_existing(mock_db_file) -> None:
    """When audio_tracks/subtitle_tracks are empty, keeps the existing value."""
    from lan_streamer.db.library import _apply_movie_fields

    with get_session() as session:
        movie = Movie(
            name="ExistingMovie",
            library_name="Lib",
            audio_tracks=json.dumps([{"lang": "es"}]),
            subtitle_tracks=json.dumps([{"lang": "jp"}]),
        )
        session.add(movie)
        session.flush()

        movie_data = {
            "audio_tracks": [],  # empty – should keep existing
            "subtitle_tracks": [],  # empty – should keep existing
        }
        _apply_movie_fields(movie, movie_data)
        session.commit()

        # Existing values should be preserved
        assert json.loads(movie.audio_tracks) == [{"lang": "es"}]
        assert json.loads(movie.subtitle_tracks) == [{"lang": "jp"}]


# ---------------------------------------------------------------------------
# _save_episode_record - placeholder promotion
# ---------------------------------------------------------------------------


def test_strip_counter_suffix() -> None:
    from lan_streamer.db.library_tv import _strip_counter_suffix

    assert _strip_counter_suffix("TBA") == "TBA"
    assert _strip_counter_suffix("TBA (1)") == "TBA"
    assert _strip_counter_suffix("TBA (42)") == "TBA"
    assert _strip_counter_suffix("Episode 1") == "Episode 1"
    assert _strip_counter_suffix("Episode 1 (1)") == "Episode 1"


def test_save_episode_record_promotes_placeholder(mock_db_file) -> None:
    """When a placeholder episode (path=None) is found by tmdb_number, it should be promoted."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="PlaceholderShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        # Create a placeholder episode
        placeholder = Episode(
            season=season,
            name="S01E01",
            path=None,
            tmdb_number=1,
        )
        session.add(placeholder)
        session.flush()

        existing_by_path = {}
        existing_by_number = {1: placeholder}
        existing_by_name = {"S01E01": placeholder}
        stats = {"episodes": 0}

        episode_data = {
            "name": "S01E01",
            "path": "/shows/Season 1/S01E01.mkv",
            "tmdb_number": 1,
        }

        _save_episode_record(
            session,
            season,
            episode_data,
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        # The placeholder should now have a path
        assert placeholder.path == "/shows/Season 1/S01E01.mkv"
        assert stats["episodes"] == 1


def test_save_episode_record_name_fallback(mock_db_file) -> None:
    """Fallback to name-matching when path and tmdb_number don't match.
    Path gets assigned when episode has no existing path (placeholder)."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="NameFallbackShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        # A placeholder episode with no path
        existing_ep = Episode(
            season=season,
            name="SpecialEp",
            path=None,  # placeholder, no path
            tmdb_number=None,
        )
        session.add(existing_ep)
        session.flush()

        existing_by_path = {}
        existing_by_number = {}
        existing_by_name = {"SpecialEp": existing_ep}
        stats = {"episodes": 0}

        # New episode with same name and now has a path
        episode_data = {
            "name": "SpecialEp",
            "path": "/new/path.mkv",
            "tmdb_number": None,
        }

        _save_episode_record(
            session,
            season,
            episode_data,
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        # Should have assigned path via name fallback (since existing_ep.path was None)
        assert existing_ep.path == "/new/path.mkv"


def test_save_episode_record_name_fallback_strips_counter_suffix(mock_db_file) -> None:
    """When DB has 'TBA (1)' and exact 'TBA' was already consumed, scanning
    another file with name 'TBA' should match 'TBA (1)' via suffix lookup."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="CounterSuffixShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        ep_b = Episode(season=season, name="TBA (1)", path="/b/TBA.mkv")
        session.add(ep_b)
        session.flush()

        # Simulate state AFTER first "TBA" was already consumed:
        # only "TBA (1)" remains in existing_by_name
        existing_by_path = {"/b/TBA.mkv": ep_b}
        existing_by_number = {}
        existing_by_name = {"TBA (1)": ep_b}
        stats = {"episodes": 0, "issues": []}

        # Scanner computes name="TBA" (TMDB returned TBA), file moved to new path
        episode_data = {
            "name": "TBA",
            "path": "/new/TBA.mkv",
            "tmdb_number": None,
        }

        _save_episode_record(
            session,
            season,
            episode_data,
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        # ep_b should be matched via suffixed name fallback
        assert ep_b.path == "/new/TBA.mkv"


def test_save_episode_record_name_fallback_strips_suffix_no_number(
    mock_db_file,
) -> None:
    """Two files with the same TMDB name 'Episode 1' and no tmdb_number.
    After the first is consumed, the second should match the suffixed record."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="SuffixFallbackShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        ep_a = Episode(season=season, name="Episode 1", path="/a/ep1.mkv")
        ep_b = Episode(season=season, name="Episode 1 (1)", path="/b/ep1.mkv")
        session.add_all([ep_a, ep_b])
        session.flush()

        existing_by_path = {"/a/ep1.mkv": ep_a, "/b/ep1.mkv": ep_b}
        existing_by_number = {}
        existing_by_name = {"Episode 1": ep_a, "Episode 1 (1)": ep_b}
        stats = {"episodes": 0, "issues": []}

        # First scan: matches ep_a by exact name
        _save_episode_record(
            session,
            season,
            {"name": "Episode 1", "path": "/a/ep1.mkv", "tmdb_number": None},
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        # Second scan: different path, same name, should match "Episode 1 (1)"
        _save_episode_record(
            session,
            season,
            {"name": "Episode 1", "path": "/new/ep1.mkv", "tmdb_number": None},
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        assert ep_a.path == "/a/ep1.mkv"
        assert ep_b.path == "/new/ep1.mkv"


def test_save_episode_record_two_tba_files_incremental_scan(mock_db_file) -> None:
    """Bug B exact scenario: two files both scan as 'TBA' from TMDB.
    First matches 'TBA', second must match 'TBA (1)' via suffix fallback.
    No tmdb_number available (offline scan)."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="TBAShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        ep_a = Episode(season=season, name="TBA", path="/tv/Show S01E05.mkv")
        ep_b = Episode(season=season, name="TBA (1)", path="/tv/Show S01E06.mkv")
        session.add_all([ep_a, ep_b])
        session.flush()

        existing_by_path = {"/tv/Show S01E05.mkv": ep_a, "/tv/Show S01E06.mkv": ep_b}
        existing_by_number = {}
        existing_by_name = {"TBA": ep_a, "TBA (1)": ep_b}
        stats = {"episodes": 0, "issues": []}

        # Scan first file — matches by exact name "TBA"
        _save_episode_record(
            session,
            season,
            {"name": "TBA", "path": "/tv/Show S01E05.mkv", "tmdb_number": None},
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        # Scan second file — must match "TBA (1)" via suffix fallback
        _save_episode_record(
            session,
            season,
            {"name": "TBA", "path": "/new/Show S01E06.mkv", "tmdb_number": None},
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        assert ep_a.path == "/tv/Show S01E05.mkv"
        assert ep_b.path == "/new/Show S01E06.mkv"


def test_save_episode_record_three_same_name_creates_new(mock_db_file) -> None:
    """Three files all named 'Episode 1': first matches exact, second matches
    suffix, third creates a new record."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="TripleShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        ep_a = Episode(season=season, name="Episode 1", path="/a/ep1.mkv")
        ep_b = Episode(season=season, name="Episode 1 (1)", path="/b/ep1.mkv")
        session.add_all([ep_a, ep_b])
        session.flush()

        existing_by_path = {"/a/ep1.mkv": ep_a, "/b/ep1.mkv": ep_b}
        existing_by_number = {}
        existing_by_name = {"Episode 1": ep_a, "Episode 1 (1)": ep_b}
        stats = {"episodes": 0, "issues": []}

        # First scan — matches exact "Episode 1"
        _save_episode_record(
            session,
            season,
            {"name": "Episode 1", "path": "/a/ep1.mkv", "tmdb_number": None},
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        # Second scan — matches suffixed "Episode 1 (1)"
        _save_episode_record(
            session,
            season,
            {"name": "Episode 1", "path": "/new/ep1.mkv", "tmdb_number": None},
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        # Third scan — no match, creates new Episode
        ep_c = _save_episode_record(
            session,
            season,
            {"name": "Episode 1", "path": "/c/ep1.mkv", "tmdb_number": None},
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        assert ep_a.path == "/a/ep1.mkv"
        assert ep_b.path == "/new/ep1.mkv"
        assert ep_c.path == "/c/ep1.mkv"
        assert ep_c.name == "Episode 1 (2)"  # counter suffix applied


def test_save_episode_record_tmdb_number_takes_priority_over_name(mock_db_file) -> None:
    """When tmdb_number matches, it takes priority over name fallback —
    even if the name would also match a different suffixed record."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="PriorityShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        ep_a = Episode(season=season, name="TBA", path="/a/TBA.mkv", tmdb_number=5)
        ep_b = Episode(season=season, name="TBA (1)", path="/b/TBA.mkv", tmdb_number=6)
        session.add_all([ep_a, ep_b])
        session.flush()

        existing_by_path = {"/a/TBA.mkv": ep_a, "/b/TBA.mkv": ep_b}
        existing_by_number = {5: ep_a, 6: ep_b}
        existing_by_name = {"TBA": ep_a, "TBA (1)": ep_b}
        stats = {"episodes": 0, "issues": []}

        # Scan file with name "TBA" but tmdb_number=6 — should match ep_b by number
        _save_episode_record(
            session,
            season,
            {"name": "TBA", "path": "/new/TBA.mkv", "tmdb_number": 6},
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        assert ep_b.path == "/new/TBA.mkv"
        assert ep_a.path == "/a/TBA.mkv"


def test_save_episode_record_no_match_creates_new_episode(mock_db_file) -> None:
    """When no path, tmdb_number, or name matches, a new Episode is created."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="NoMatchShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        ep_a = Episode(season=season, name="Other", path="/a/other.mkv")
        session.add(ep_a)
        session.flush()

        existing_by_path = {"/a/other.mkv": ep_a}
        existing_by_number = {}
        existing_by_name = {"Other": ep_a}
        stats = {"episodes": 0, "issues": []}

        new_ep = _save_episode_record(
            session,
            season,
            {"name": "Brand New", "path": "/x/new.mkv", "tmdb_number": None},
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        assert new_ep.path == "/x/new.mkv"
        assert new_ep.name == "Brand New"
        assert stats["episodes"] == 1


def test_save_episode_record_exact_name_match_takes_priority(mock_db_file) -> None:
    """Exact name match takes priority over suffixed fallback."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="ExactPriorityShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        ep_a = Episode(season=season, name="Special", path=None)
        ep_b = Episode(season=season, name="Special (1)", path=None)
        session.add_all([ep_a, ep_b])
        session.flush()

        existing_by_path = {}
        existing_by_number = {}
        existing_by_name = {"Special": ep_a, "Special (1)": ep_b}
        stats = {"episodes": 0, "issues": []}

        # Should match exact "Special", not "Special (1)"
        _save_episode_record(
            session,
            season,
            {"name": "Special", "path": "/new/special.mkv", "tmdb_number": None},
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        assert ep_a.path == "/new/special.mkv"
        assert ep_b.path is None


def test_save_episode_record_myanimelist_fields(mock_db_file) -> None:
    """Episode records should save myanimelist fields."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="MALShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        existing_by_path = {}
        existing_by_number = {}
        existing_by_name = {}
        stats = {"episodes": 0}

        episode_data = {
            "name": "ep1.mkv",
            "path": "/mal/ep1.mkv",
            "myanimelist_anime_id": 55555,
            "myanimelist_episode_number": 3,
            "audio_tracks": [{"lang": "ja"}],
            "subtitle_tracks": [{"lang": "en"}],
            "video_codec": "HEVC",
            "resolution": "4K",
        }

        ep = _save_episode_record(
            session,
            season,
            episode_data,
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        assert ep.myanimelist_anime_id == 55555
        assert ep.myanimelist_episode_number == 3
        assert json.loads(ep.audio_tracks) == [{"lang": "ja"}]
        assert json.loads(ep.subtitle_tracks) == [{"lang": "en"}]
        assert ep.video_codec == "HEVC"
        assert ep.resolution == "4K"


def test_save_episode_record_date_added_int_comparison(mock_db_file) -> None:
    """date_added from fs (float) should not trigger false 'updated' when DB stores int."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="DateAddedShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        existing_ep = Episode(
            season=season,
            name="ep1.mkv",
            path="/existing/ep1.mkv",
            tmdb_number=1,
            date_added=1234567890,
        )
        session.add(existing_ep)
        session.flush()

        existing_by_path = {"/existing/ep1.mkv": existing_ep}
        existing_by_number = {1: existing_ep}
        existing_by_name = {"ep1.mkv": existing_ep}
        stats: Dict[str, Any] = {"episodes": 0}

        # Simulate os.path.getctime() returning a float with fractional part
        episode_data = {
            "name": "ep1.mkv",
            "path": "/existing/ep1.mkv",
            "tmdb_number": 1,
            "date_added": 1234567890.1234567,
        }

        _save_episode_record(
            session,
            season,
            episode_data,
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        # The float vs int comparison should NOT trigger an update
        assert stats.get("episodes_updated", 0) == 0
        # The stored value should be int
        assert existing_ep.date_added == 1234567890


def test_save_episode_record_date_added_no_false_update_on_repeat(mock_db_file) -> None:
    """Repeated saves with same float date_added should not count as updates."""
    from lan_streamer.db.library import _save_episode_record

    with get_session() as session:
        series = Series(name="RepeatDateShow", library_name="Lib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()

        existing_ep = Episode(
            season=season,
            name="ep1.mkv",
            path="/repeat/ep1.mkv",
            tmdb_number=1,
            date_added=987654321,
        )
        session.add(existing_ep)
        session.flush()

        existing_by_path = {"/repeat/ep1.mkv": existing_ep}
        existing_by_number = {1: existing_ep}
        existing_by_name = {"ep1.mkv": existing_ep}
        stats: Dict[str, Any] = {"episodes": 0}

        # First save with float date_added
        episode_data = {
            "name": "ep1.mkv",
            "path": "/repeat/ep1.mkv",
            "tmdb_number": 1,
            "date_added": 987654321.999,
        }

        _save_episode_record(
            session,
            season,
            episode_data,
            existing_by_path,
            existing_by_number,
            existing_by_name,
            stats,
        )
        session.commit()

        # The DB now stores 987654321 as int.
        # On next scan, the compare is: int(987654321) != int(987654321.999) → False (no update)
        assert stats.get("episodes_updated", 0) == 0


# ---------------------------------------------------------------------------
# _save_season_record - myanimelist_id field
# ---------------------------------------------------------------------------


def test_save_season_record_myanimelist_id(mock_db_file) -> None:
    """Season records should save myanimelist_id from metadata."""
    from lan_streamer.db.library import _save_season_record

    with get_session() as session:
        series = Series(name="MALSeason", library_name="Lib")
        session.add(series)
        session.flush()

        stats = {"seasons": 0}
        season_data = {"metadata": {"myanimelist_id": 99999, "jellyfin_id": ""}}

        season = _save_season_record(
            session, series, "Season 1", season_data, {}, stats
        )
        session.commit()

        assert season.myanimelist_id == 99999
        assert stats["seasons"] == 1


# ---------------------------------------------------------------------------
# save_movie_library - TMDB ID fallback match
# ---------------------------------------------------------------------------


def test_save_movie_library_tmdb_id_fallback(mock_db_file, tmp_path) -> None:
    """When path changed but tmdb_identifier matches, reuse existing record."""
    # Create existing movie record with a non-existent path (so it's considered missing)
    with get_session() as session:
        movie = Movie(
            name="OldName",
            library_name="Movies",
            path="/old/nonexistent.mkv",
            tmdb_identifier="tmdb_abc",
        )
        session.add(movie)
        session.commit()

    # Save library with same TMDB ID but new path/name
    new_movie_file = tmp_path / "NewName.mkv"
    new_movie_file.write_bytes(b"\x00")

    library = {
        "NewName": {
            "path": str(new_movie_file),
            "tmdb_identifier": "tmdb_abc",
            "tmdb_name": "New Name",
        }
    }
    db.save_movie_library("Movies", library)

    result = db.load_movie_library("Movies")
    # The movie should be updated (via TMDB id match) rather than duplicated
    assert len(result) == 1


# ---------------------------------------------------------------------------
# cleanup_library - movie: removes missing movies
# ---------------------------------------------------------------------------


def test_cleanup_library_movie_removes_missing(mock_db_file) -> None:
    """cleanup_library for movie type should remove Movie records with missing files."""
    # Create a movie that points to a non-existent path
    with get_session() as session:
        movie = Movie(
            name="Orphan",
            library_name="Movies",
            path="/nonexistent/movie.mkv",
        )
        session.add(movie)
        session.commit()

    config.libraries["Movies"] = {"type": "movie", "paths": []}
    stats = db.cleanup_library("Movies", [])
    assert stats["movies"] == 1


# ---------------------------------------------------------------------------
# cleanup_library - tv: nulls out missing episode paths
# ---------------------------------------------------------------------------


def test_cleanup_library_tv_nulls_missing_episode_path(mock_db_file, tmp_path) -> None:
    """cleanup_library for tv type should null out episode paths for missing files."""
    series_dir = tmp_path / "MyShow"
    series_dir.mkdir()

    with get_session() as session:
        series = Series(name="MyShow", library_name="TVLib")
        session.add(series)
        session.flush()
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()
        ep = Episode(
            name="S01E01.mkv",
            path="/nonexistent/s01e01.mkv",  # file doesn't exist
            season=season,
        )
        session.add(ep)
        session.commit()

    config.libraries["TVLib"] = {"type": "tv", "paths": [str(tmp_path)]}
    db.cleanup_library("TVLib", [str(tmp_path)])

    # Check the episode path is now None
    with get_session() as session:
        ep_row = session.scalars(
            __import__("sqlalchemy").select(Episode).where(Episode.name == "S01E01.mkv")
        ).first()
        assert ep_row is None or ep_row.path is None


def test_cleanup_library_tv_removes_missing_series(mock_db_file, tmp_path) -> None:
    """cleanup_library for tv type should remove Series records not on disk."""
    with get_session() as session:
        series = Series(name="GoneShow", library_name="TVLib2")
        session.add(series)
        session.flush()
        season = Season(name="S1", series=series)
        session.add(season)
        session.flush()
        ep = Episode(name="ep.mkv", path="/gone/ep.mkv", season=season)
        session.add(ep)
        session.commit()

    config.libraries["TVLib2"] = {"type": "tv", "paths": [str(tmp_path)]}
    stats = db.cleanup_library("TVLib2", [str(tmp_path)])

    # GoneShow folder doesn't exist in tmp_path → should be removed
    assert stats["series"] == 1


# ---------------------------------------------------------------------------
# load_library exception path
# ---------------------------------------------------------------------------


def test_load_library_handles_exception(mock_db_file) -> None:
    """load_library should return {} on database errors."""
    with patch(
        "lan_streamer.db.library.get_session", side_effect=RuntimeError("DB fail")
    ):
        result = db.load_library("SomeLib")
    assert result == {}


# ---------------------------------------------------------------------------
# cleanup_library: prunes missing MediaFile records
# ---------------------------------------------------------------------------


def test_cleanup_library_prunes_missing_media_files(mock_db_file, tmp_path) -> None:
    """cleanup_library should prune MediaFile records when the physical file is missing from disk,
    but only if they are within the library's root directories.
    """
    from lan_streamer.db.models import MediaFile

    # Setup directories
    library_root = tmp_path / "TV"
    library_root.mkdir()
    other_root = tmp_path / "Other"
    other_root.mkdir()

    # Create dummy files
    existing_file = library_root / "existing.mp4"
    existing_file.touch()

    # Paths for DB entries
    path_existing = str(existing_file)
    path_missing_in_root = str(library_root / "missing.mp4")
    path_missing_outside_root = str(other_root / "missing_outside.mp4")

    # Add to DB
    with get_session() as session:
        mf_existing = MediaFile(path=path_existing)
        mf_missing_in_root = MediaFile(path=path_missing_in_root)
        mf_missing_outside_root = MediaFile(path=path_missing_outside_root)
        session.add_all([mf_existing, mf_missing_in_root, mf_missing_outside_root])
        session.commit()

    config.libraries["TVLib"] = {"type": "tv", "paths": [str(library_root)]}

    # Run cleanup
    stats = db.cleanup_library("TVLib", [str(library_root)])

    # Verify return stats
    assert stats["media_files_removed"] == 1

    # Verify DB state
    with get_session() as session:
        from sqlalchemy import select

        mfs = session.scalars(select(MediaFile)).all()
        mf_paths = {mf.path for mf in mfs}

        # Existing file within root must remain
        assert path_existing in mf_paths
        # Missing file within root must be removed
        assert path_missing_in_root not in mf_paths
        # Missing file outside root must remain (ignored during this library's cleanup)
        assert path_missing_outside_root in mf_paths


def test_save_library_shared_media_files_no_unique_constraint_failure(
    mock_db_file,
) -> None:
    """save_library should succeed without UNIQUE constraint failures on media_files.path
    when multiple episodes or movies reference the exact same media file path,
    and both records should successfully map to the same MediaFile record.
    """
    from lan_streamer.db.models import MediaFile
    from sqlalchemy import select

    # Mock TV library structure
    shared_path = "/storage/nas/tv/SharedShow/Season 1/SharedFile_S01E01_S01E02.mkv"
    library_data = {
        "SharedShow": {
            "metadata": {
                "tmdb_identifier": "1234",
                "tmdb_name": "SharedShow",
            },
            "seasons": {
                "Season 1": {
                    "metadata": {
                        "tmdb_identifier": "5678",
                    },
                    "episodes": [
                        {
                            "name": "S01E01 - Episode 1",
                            "path": shared_path,
                            "tmdb_identifier": "ep1_id",
                            "tmdb_number": 1,
                            "versions": [
                                {
                                    "path": shared_path,
                                    "size_bytes": 1024,
                                    "video_type": "MKV",
                                }
                            ],
                        },
                        {
                            "name": "S01E02 - Episode 2",
                            "path": shared_path,
                            "tmdb_identifier": "ep2_id",
                            "tmdb_number": 2,
                            "versions": [
                                {
                                    "path": shared_path,
                                    "size_bytes": 1024,
                                    "video_type": "MKV",
                                }
                            ],
                        },
                    ],
                }
            },
        }
    }

    # Call save_library
    # This should execute cleanly without raising sqlite3.IntegrityError
    db.save_library("TV", library_data)

    # Verify database state
    with get_session() as session:
        # Check that there is only exactly one MediaFile created for that path
        media_files = session.scalars(
            select(MediaFile).where(MediaFile.path == shared_path)
        ).all()
        assert len(media_files) == 1

        # Verify that both Episode 1 and Episode 2 are associated with this MediaFile
        mf = media_files[0]
        assert len(mf.episodes) == 2
        episode_names = {ep.name for ep in mf.episodes}
        assert "S01E01 - Episode 1" in episode_names
        assert "S01E02 - Episode 2" in episode_names


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_file(tmp_path):
    return tmp_path / "library.db"
