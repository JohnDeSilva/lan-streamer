"""Unit tests for tab_consolidation_service."""

from __future__ import annotations

from lan_streamer.services.tab_consolidation_service import (
    consolidate_library_data,
)


def test_consolidate_single_library() -> None:
    """Consolidating a single library should return its series data with origin metadata."""
    library_data = {
        "Attack on Titan": {
            "metadata": {
                "tmdb_identifier": "1429",
                "overview": "Titans attack humanity.",
                "poster_path": "/aot.jpg",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "episode_number": 1,
                            "name": "To You, in 2000 Years",
                            "path": "/media/aot/s01e01.mkv",
                            "versions": [{"path": "/media/aot/s01e01.mkv"}],
                            "watched": True,
                        }
                    ]
                }
            },
        }
    }

    consolidated = consolidate_library_data([("Anime TV", library_data)])
    assert "Attack on Titan" in consolidated
    series = consolidated["Attack on Titan"]
    assert series["metadata"]["tmdb_identifier"] == "1429"
    assert "Anime TV" in series["_origin_libraries"]
    assert "Season 1" in series["seasons"]
    assert len(series["seasons"]["Season 1"]["episodes"]) == 1


def test_consolidate_multiple_libraries_same_tmdb_id() -> None:
    """Series in different libraries with the same TMDB ID should merge into a single series."""
    tv_data = {
        "Attack on Titan": {
            "metadata": {
                "tmdb_identifier": "1429",
                "overview": "Titans attack humanity.",
                "poster_path": "/aot.jpg",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "episode_number": 1,
                            "name": "To You, in 2000 Years",
                            "path": "/media/aot/s01e01.mkv",
                            "versions": [{"path": "/media/aot/s01e01.mkv"}],
                            "watched": True,
                        }
                    ]
                }
            },
        }
    }

    ovas_data = {
        "Shingeki no Kyojin: OVAs": {
            "metadata": {
                "tmdb_identifier": "1429",
                "overview": "Side stories.",
                "poster_path": "/ovas.jpg",
            },
            "seasons": {
                "Specials": {
                    "episodes": [
                        {
                            "episode_number": 1,
                            "name": "Ilse's Notebook",
                            "path": "/media/ovas/sp01.mkv",
                            "versions": [{"path": "/media/ovas/sp01.mkv"}],
                            "watched": False,
                        }
                    ]
                }
            },
        }
    }

    consolidated = consolidate_library_data(
        [
            ("Anime TV", tv_data),
            ("Anime OVAs", ovas_data),
        ]
    )

    assert len(consolidated) == 1
    assert "Attack on Titan" in consolidated
    series = consolidated["Attack on Titan"]
    assert series["metadata"]["tmdb_identifier"] == "1429"
    assert set(series["_origin_libraries"]) == {"Anime TV", "Anime OVAs"}
    assert "Season 1" in series["seasons"]
    assert "Specials" in series["seasons"]
    assert len(series["seasons"]["Season 1"]["episodes"]) == 1
    assert len(series["seasons"]["Specials"]["episodes"]) == 1


def test_consolidate_multiple_libraries_same_title_no_tmdb_id() -> None:
    """Series without TMDB IDs matching on name should be merged."""
    lib1_data = {
        "Home Movies": {
            "metadata": {"tmdb_identifier": None, "overview": "Trip 2020"},
            "seasons": {
                "2020": {
                    "episodes": [
                        {
                            "episode_number": 1,
                            "name": "Beach",
                            "path": "/media/trip/e01.mkv",
                            "versions": [{"path": "/media/trip/e01.mkv"}],
                        }
                    ]
                }
            },
        }
    }

    lib2_data = {
        "home movies": {
            "metadata": {"tmdb_identifier": None, "overview": "Trip 2021"},
            "seasons": {
                "2021": {
                    "episodes": [
                        {
                            "episode_number": 1,
                            "name": "Mountains",
                            "path": "/media/trip/e02.mkv",
                            "versions": [{"path": "/media/trip/e02.mkv"}],
                        }
                    ]
                }
            },
        }
    }

    consolidated = consolidate_library_data(
        [
            ("Local 1", lib1_data),
            ("Local 2", lib2_data),
        ]
    )

    assert len(consolidated) == 1
    series = next(iter(consolidated.values()))
    assert "2020" in series["seasons"]
    assert "2021" in series["seasons"]
    assert set(series["_origin_libraries"]) == {"Local 1", "Local 2"}


def test_consolidate_same_episode_combines_versions() -> None:
    """Episodes across libraries with same number in same season should combine versions."""
    lib1_data = {
        "Show": {
            "metadata": {"tmdb_identifier": "100"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "episode_number": 1,
                            "name": "Pilot",
                            "path": "/lib1/s01e01.mkv",
                            "versions": [{"path": "/lib1/s01e01.mkv"}],
                        }
                    ]
                }
            },
        }
    }

    lib2_data = {
        "Show": {
            "metadata": {"tmdb_identifier": "100"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "episode_number": 1,
                            "name": "Pilot",
                            "path": "/lib2/s01e01.mp4",
                            "versions": [{"path": "/lib2/s01e01.mp4"}],
                        }
                    ]
                }
            },
        }
    }

    consolidated = consolidate_library_data(
        [
            ("Lib1", lib1_data),
            ("Lib2", lib2_data),
        ]
    )

    episodes = consolidated["Show"]["seasons"]["Season 1"]["episodes"]
    assert len(episodes) == 1
    paths = [v["path"] for v in episodes[0]["versions"]]
    assert "/lib1/s01e01.mkv" in paths
    assert "/lib2/s01e01.mp4" in paths


def test_consolidate_distinct_series() -> None:
    """Distinct series in different libraries should remain distinct."""
    lib1_data = {"Show A": {"metadata": {"tmdb_identifier": "1"}, "seasons": {}}}
    lib2_data = {"Show B": {"metadata": {"tmdb_identifier": "2"}, "seasons": {}}}

    consolidated = consolidate_library_data(
        [
            ("Lib1", lib1_data),
            ("Lib2", lib2_data),
        ]
    )

    assert len(consolidated) == 2
    assert "Show A" in consolidated
    assert "Show B" in consolidated


def test_consolidate_movies() -> None:
    """Movie consolidation should merge by TMDB identifier or title and combine media files."""
    lib1_data = {
        "Inception": {
            "tmdb_id": 27205,
            "title": "Inception",
            "default_path": "/movies1/inception.mkv",
            "media_files": [{"path": "/movies1/inception.mkv"}],
            "versions": [{"path": "/movies1/inception.mkv"}],
        }
    }
    lib2_data = {
        "Inception (4K)": {
            "tmdb_id": 27205,
            "title": "Inception",
            "default_path": "/movies2/inception_4k.mkv",
            "media_files": [{"path": "/movies2/inception_4k.mkv"}],
            "versions": [{"path": "/movies2/inception_4k.mkv"}],
        }
    }

    consolidated = consolidate_library_data(
        [
            ("1080p Movies", lib1_data),
            ("4K Movies", lib2_data),
        ]
    )

    assert len(consolidated) == 1
    movie = next(iter(consolidated.values()))
    assert set(movie["_origin_libraries"]) == {"1080p Movies", "4K Movies"}
    paths = [v["path"] for v in movie["versions"]]
    assert "/movies1/inception.mkv" in paths
    assert "/movies2/inception_4k.mkv" in paths
