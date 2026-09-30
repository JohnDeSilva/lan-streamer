"""
Unit tests for multi-library relational decoupling.

Verifies that Series and Movies deduplicate across multiple libraries,
link via SeriesLibrary and MovieLibrary junction tables, and correctly load
unified records across single or multiple library queries.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from sqlalchemy import select

from lan_streamer import db
from lan_streamer.db.connection import get_session
from lan_streamer.db.library_movie import _cleanup_movie_library
from lan_streamer.db.library_tv import _cleanup_tv_library
from lan_streamer.db.models import Movie, MovieLibrary, Series, SeriesLibrary
from lan_streamer.db.queries_ui import (
    get_combined_next_up,
    get_combined_smart_row,
    search_media_names,
)


def test_series_deduplication_across_multiple_libraries() -> None:
    first_library_payload: dict[str, Any] = {
        "Breaking Bad": {
            "metadata": {
                "tmdb_identifier": "1396",
                "overview": "A chemistry teacher turned manufacturer.",
                "poster_path": "/poster_season1.jpg",
                "locked_metadata": True,
            },
            "seasons": {
                "Season 1": {
                    "metadata": {"poster_path": "/s1.jpg"},
                    "episodes": [
                        {
                            "name": "Pilot",
                            "episode_number": 1,
                            "tmdb_number": 1,
                            "path": "/storage/disk1/tv/Breaking Bad/S01E01.mkv",
                            "versions": [
                                {"path": "/storage/disk1/tv/Breaking Bad/S01E01.mkv"}
                            ],
                            "watched": True,
                        }
                    ],
                }
            },
        }
    }

    second_library_payload: dict[str, Any] = {
        "Breaking Bad": {
            "metadata": {
                "tmdb_identifier": "1396",
                "overview": "A chemistry teacher turned manufacturer.",
                "poster_path": "/poster_season2.jpg",
                "locked_metadata": True,
            },
            "seasons": {
                "Season 2": {
                    "metadata": {"poster_path": "/s2.jpg"},
                    "episodes": [
                        {
                            "name": "Seven Thirty-Seven",
                            "episode_number": 1,
                            "tmdb_number": 1,
                            "path": "/storage/disk2/tv/Breaking Bad/S02E01.mkv",
                            "versions": [
                                {"path": "/storage/disk2/tv/Breaking Bad/S02E01.mkv"}
                            ],
                            "watched": False,
                        }
                    ],
                }
            },
        }
    }

    # Save to first library
    db.save_library("TV Disk 1", first_library_payload)

    # Save to second library
    db.save_library("TV Disk 2", second_library_payload)

    # Verify only 1 Series record exists in the database
    with get_session() as session:
        all_series = session.scalars(select(Series)).all()
        assert len(all_series) == 1
        series_record = all_series[0]
        assert series_record.name == "Breaking Bad"

        # Verify junction records
        junction_records = session.scalars(
            select(SeriesLibrary).where(SeriesLibrary.series_id == series_record.id)
        ).all()
        junction_library_names = {record.library_name for record in junction_records}
        assert "TV Disk 1" in junction_library_names
        assert "TV Disk 2" in junction_library_names

    # Verify loading via first library returns both seasons
    first_library_data = db.load_library("TV Disk 1")
    assert "Breaking Bad" in first_library_data
    series_from_first = first_library_data["Breaking Bad"]
    assert "Season 1" in series_from_first["seasons"]
    assert "Season 2" in series_from_first["seasons"]
    assert set(series_from_first["_origin_libraries"]) == {"TV Disk 1", "TV Disk 2"}

    # Verify loading via second library returns both seasons
    second_library_data = db.load_library("TV Disk 2")
    assert "Breaking Bad" in second_library_data
    series_from_second = second_library_data["Breaking Bad"]
    assert "Season 1" in series_from_second["seasons"]
    assert "Season 2" in series_from_second["seasons"]

    # Verify loading with both library names in batch returns deduplicated record
    batch_library_data = db.load_library(["TV Disk 1", "TV Disk 2"])
    assert len(batch_library_data) == 1
    assert "Breaking Bad" in batch_library_data
    series_batch = batch_library_data["Breaking Bad"]
    assert len(series_batch["seasons"]) == 2


def test_movie_deduplication_across_multiple_libraries() -> None:
    first_movie_payload: dict[str, Any] = {
        "Inception": {
            "name": "Inception",
            "tmdb_identifier": "27205",
            "year": 2010,
            "path": "/storage/disk1/movies/Inception.1080p.mkv",
            "default_path": "/storage/disk1/movies/Inception.1080p.mkv",
            "versions": [
                {
                    "path": "/storage/disk1/movies/Inception.1080p.mkv",
                    "resolution": "1080p",
                }
            ],
            "watched": False,
        }
    }

    second_movie_payload: dict[str, Any] = {
        "Inception": {
            "name": "Inception",
            "tmdb_identifier": "27205",
            "year": 2010,
            "path": "/storage/disk2/movies/Inception.2160p.mkv",
            "default_path": "/storage/disk2/movies/Inception.2160p.mkv",
            "versions": [
                {
                    "path": "/storage/disk2/movies/Inception.2160p.mkv",
                    "resolution": "4K",
                }
            ],
            "watched": True,
        }
    }

    # Save to first library
    db.save_movie_library("Movies 1080p", first_movie_payload)

    # Save to second library
    db.save_movie_library("Movies 4K", second_movie_payload)

    # Verify only 1 Movie record exists in the database
    with get_session() as session:
        all_movies = session.scalars(select(Movie)).all()
        assert len(all_movies) == 1
        movie_record = all_movies[0]
        assert movie_record.name == "Inception"

        # Verify junction records
        junction_records = session.scalars(
            select(MovieLibrary).where(MovieLibrary.movie_id == movie_record.id)
        ).all()
        junction_library_names = {record.library_name for record in junction_records}
        assert "Movies 1080p" in junction_library_names
        assert "Movies 4K" in junction_library_names

    # Verify loading via first library returns both versions
    first_library_data = db.load_movie_library("Movies 1080p")
    assert "Inception" in first_library_data
    movie_from_first = first_library_data["Inception"]
    paths_first = {version["path"] for version in movie_from_first["versions"]}
    assert "/storage/disk1/movies/Inception.1080p.mkv" in paths_first
    assert "/storage/disk2/movies/Inception.2160p.mkv" in paths_first
    assert set(movie_from_first["_origin_libraries"]) == {"Movies 1080p", "Movies 4K"}

    # Verify loading via second library returns both versions
    second_library_data = db.load_movie_library("Movies 4K")
    assert "Inception" in second_library_data
    movie_from_second = second_library_data["Inception"]
    paths_second = {version["path"] for version in movie_from_second["versions"]}
    assert paths_second == paths_first

    # Verify loading batch returns deduplicated record
    batch_library_data = db.load_movie_library(["Movies 1080p", "Movies 4K"])
    assert len(batch_library_data) == 1
    assert "Inception" in batch_library_data


def test_partial_cleanup_preserves_shared_series_and_movie() -> None:
    # Set up shared series
    series_payload: dict[str, Any] = {
        "Shared Series": {
            "metadata": {"tmdb_identifier": "9999", "overview": "Test series"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "episode_number": 1,
                            "path": "/disk1/ep1.mkv",
                        }
                    ]
                }
            },
        }
    }
    db.save_library("Library One", series_payload)
    db.save_library("Library Two", series_payload)

    # Set up shared movie
    movie_payload: dict[str, Any] = {
        "Shared Movie": {
            "name": "Shared Movie",
            "tmdb_identifier": "8888",
            "path": "/disk1/movie.mkv",
        }
    }
    db.save_movie_library("Movie Lib One", movie_payload)
    db.save_movie_library("Movie Lib Two", movie_payload)

    # Perform cleanup of Library One with no valid root directories
    with get_session() as session:
        stats: dict[str, int] = {}
        _cleanup_tv_library(
            session, "Library One", root_directories=["/nonexistent_path"], stats=stats
        )
        session.commit()

    # Series must still exist because Library Two is still linked
    with get_session() as session:
        series_record = session.scalars(
            select(Series).where(Series.name == "Shared Series")
        ).first()
        assert series_record is not None
        # Library One should no longer be in the junction records
        junctions = session.scalars(
            select(SeriesLibrary).where(SeriesLibrary.series_id == series_record.id)
        ).all()
        junction_names = {junction.library_name for junction in junctions}
        assert "Library One" not in junction_names

    # Perform cleanup of Movie Lib One (file /disk1/movie.mkv does not exist on disk)
    with get_session() as session:
        movie_stats: dict[str, int] = {}
        _cleanup_movie_library(session, "Movie Lib One", stats=movie_stats)
        session.commit()

    # Movie must still exist because Movie Lib Two is still linked
    with get_session() as session:
        movie_record = session.scalars(
            select(Movie).where(Movie.name == "Shared Movie")
        ).first()
        assert movie_record is not None
        junctions = session.scalars(
            select(MovieLibrary).where(MovieLibrary.movie_id == movie_record.id)
        ).all()
        junction_names = {junction.library_name for junction in junctions}
        assert "Movie Lib One" not in junction_names


def test_ui_queries_support_junction_libraries() -> None:
    # Setup series linked to Primary, with junction in Secondary
    series_payload: dict[str, Any] = {
        "Better Call Saul": {
            "metadata": {"tmdb_identifier": "60059", "first_air_date": "2015-02-08"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Uno",
                            "episode_number": 1,
                            "tmdb_number": 1,
                            "air_date": "2015-02-08",
                            "path": "/disk/saul/s01e01.mkv",
                            "watched": True,
                        },
                        {
                            "name": "Mijo",
                            "episode_number": 2,
                            "tmdb_number": 2,
                            "air_date": "2015-02-09",
                            "path": "/disk/saul/s01e02.mkv",
                            "watched": False,
                        },
                    ]
                }
            },
        }
    }
    db.save_library("Primary TV", series_payload)
    db.save_library("Secondary TV", series_payload)

    # Setup movie linked to Primary, with junction in Secondary
    movie_payload: dict[str, Any] = {
        "Interstellar": {
            "name": "Interstellar",
            "tmdb_identifier": "157336",
            "year": 2014,
            "path": "/disk/interstellar.mkv",
            "watched": False,
        }
    }
    db.save_movie_library("Primary Movies", movie_payload)
    db.save_movie_library("Secondary Movies", movie_payload)

    # Test Next Up with Secondary TV
    next_up_items = get_combined_next_up(["Secondary TV"])
    assert len(next_up_items) == 1
    assert next_up_items[0]["series_name"] == "Better Call Saul"
    assert next_up_items[0]["season_name"] == "Season 1"

    # Test Combined Smart Row with Secondary TV
    smart_row_tv = get_combined_smart_row(
        ["Secondary TV"], sort_by="Alphabetical", filter_mode="All"
    )
    assert len(smart_row_tv) == 1
    assert smart_row_tv[0]["name"] == "Better Call Saul"

    # Test Combined Smart Row with Secondary Movies
    smart_row_movies = get_combined_smart_row(
        ["Secondary Movies"], sort_by="Alphabetical", filter_mode="All"
    )
    assert len(smart_row_movies) == 1
    assert smart_row_movies[0]["name"] == "Interstellar"

    # Test Search with Secondary TV
    search_results = search_media_names("Saul", library_names=["Secondary TV"])
    assert len(search_results) == 1
    assert search_results[0]["name"] == "Better Call Saul"

    # Test Search with Secondary Movies
    search_movie_results = search_media_names(
        "Interstellar", library_names=["Secondary Movies"]
    )
    assert len(search_movie_results) == 1
    assert search_movie_results[0]["name"] == "Interstellar"


def test_mark_series_and_season_watched_via_junction_library() -> None:
    from lan_streamer.db.queries_playback import (
        update_season_watched_status,
        update_series_watched_status,
    )

    series_payload: dict[str, Any] = {
        "Fargo": {
            "metadata": {"tmdb_identifier": "57532"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "The Crocodile's Dilemma",
                            "episode_number": 1,
                            "path": "/disk1/fargo/s01e01.mkv",
                            "watched": False,
                        }
                    ]
                },
                "Season 2": {
                    "episodes": [
                        {
                            "name": "Waiting for Dutch",
                            "episode_number": 1,
                            "path": "/disk2/fargo/s02e01.mkv",
                            "watched": False,
                        }
                    ]
                },
            },
        }
    }
    db.save_library("Primary TV", series_payload)
    db.save_library("Secondary TV", series_payload)

    # Mark Season 1 watched from Secondary TV
    update_season_watched_status("Secondary TV", "Fargo", "Season 1", True)
    loaded_data = db.load_library("Secondary TV")
    season_one_episodes = loaded_data["Fargo"]["seasons"]["Season 1"]["episodes"]
    assert season_one_episodes[0]["watched"] is True
    season_two_episodes = loaded_data["Fargo"]["seasons"]["Season 2"]["episodes"]
    assert season_two_episodes[0]["watched"] is False

    # Mark Entire Series watched from Secondary TV
    update_series_watched_status("Secondary TV", "Fargo", True)
    loaded_data = db.load_library("Secondary TV")
    season_two_episodes = loaded_data["Fargo"]["seasons"]["Season 2"]["episodes"]
    assert season_two_episodes[0]["watched"] is True


def test_delete_series_record_preserves_other_libraries() -> None:
    from lan_streamer.db.orm_serialization import delete_series_record

    series_payload: dict[str, Any] = {
        "True Detective": {
            "metadata": {"tmdb_identifier": "46648"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "The Long Bright Dark",
                            "episode_number": 1,
                            "path": "/disk1/td/s01e01.mkv",
                        }
                    ]
                }
            },
        }
    }
    db.save_library("Primary TV", series_payload)
    db.save_library("Secondary TV", series_payload)

    # Delete from Secondary TV
    delete_series_record("Secondary TV", "True Detective")

    # True Detective must still exist in Primary TV
    primary_data = db.load_library("Primary TV")
    assert "True Detective" in primary_data

    # Secondary TV should no longer have True Detective
    secondary_data = db.load_library("Secondary TV")
    assert "True Detective" not in secondary_data

    # Now delete from Primary TV as well
    delete_series_record("Primary TV", "True Detective")
    primary_data_after = db.load_library("Primary TV")
    assert "True Detective" not in primary_data_after


def test_cleanup_tv_library_ignores_files_on_other_roots(tmp_path: Path) -> None:
    from lan_streamer.db.models import MediaFile

    # Create the series directory so cleanup knows the series itself is present on disk
    series_directory = tmp_path / "Severance"
    series_directory.mkdir(parents=True)

    series_payload: dict[str, Any] = {
        "Severance": {
            "metadata": {"tmdb_identifier": "95557"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Good News About Hell",
                            "episode_number": 1,
                            "path": str(series_directory / "s01e01.mkv"),
                            "versions": [
                                {"path": str(series_directory / "s01e01.mkv")},
                                {"path": "/disk2/archive/Severance/s01e01.mkv"},
                            ],
                        }
                    ]
                }
            },
        }
    }
    db.save_library("Active TV", series_payload)

    from unittest.mock import patch

    from lan_streamer.system.config import config

    with patch.dict(
        config.libraries,
        {
            "Active TV": {"type": "tv", "paths": [str(tmp_path)]},
            "Archive TV": {"type": "tv", "paths": ["/disk2/archive"]},
        },
    ):
        # Run cleanup on Active TV (which only manages tmp_path)
        with get_session() as session:
            stats: dict[str, int] = {}
            _cleanup_tv_library(
                session,
                "Active TV",
                root_directories=[str(tmp_path)],
                stats=stats,
            )
            session.commit()

        # The archive file on /disk2 should NOT have been removed as stale
        with get_session() as session:
            disk2_media_file = session.scalars(
                select(MediaFile).where(
                    MediaFile.path == "/disk2/archive/Severance/s01e01.mkv"
                )
            ).first()
            assert disk2_media_file is not None


def test_get_and_set_series_pref_via_junction_library() -> None:
    from lan_streamer.db.queries_config import get_series_pref, set_series_pref

    series_payload: dict[str, Any] = {
        "Dark": {
            "metadata": {"tmdb_identifier": "70523"},
            "seasons": {},
        }
    }
    db.save_library("Primary TV", series_payload)
    db.save_library("Secondary TV", series_payload)

    # Set preference referencing Secondary TV
    set_series_pref("Secondary TV", "Dark", "hide_missing_future", True)

    # Get preference referencing Secondary TV
    value = get_series_pref("Secondary TV", "Dark", "hide_missing_future")
    assert value is True
