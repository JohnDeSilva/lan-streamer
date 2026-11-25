"""Unit tests for live in-memory smart row computation for remote libraries."""

from __future__ import annotations

from typing import Any

from lan_streamer.services.smart_row_service import compute_smart_rows_from_memory


def test_compute_smart_rows_from_memory_tv_and_movies() -> None:
    library_configs: dict[str, dict[str, Any]] = {
        "Remote TV": {"type": "tv", "management_type": "remote"},
        "Remote Movies": {"type": "movie", "management_type": "remote"},
    }
    remote_data: dict[str, dict[str, Any]] = {
        "Remote TV": {
            "Alpha Show": {
                "metadata": {
                    "poster_path": "/posters/alpha.jpg",
                    "first_air_date": "2020-01-01",
                },
                "seasons": {
                    "Season 01": {
                        "episodes": [
                            {
                                "path": "/media/tv/Alpha/S01E01.mkv",
                                "watched": True,
                                "date_added": 100,
                                "air_date": "2020-01-01",
                                "last_played_at": 500,
                            },
                            {
                                "path": "/media/tv/Alpha/S01E02.mkv",
                                "watched": False,
                                "date_added": 200,
                                "air_date": "2020-01-08",
                                "last_played_at": 0,
                            },
                        ]
                    }
                },
            },
            "Beta Show": {
                "metadata": {
                    "poster_path": "/posters/beta.jpg",
                    "first_air_date": "2021-01-01",
                },
                "seasons": {
                    "Season 01": {
                        "episodes": [
                            {
                                "path": "/media/tv/Beta/S01E01.mkv",
                                "watched": True,
                                "date_added": 300,
                                "air_date": "2021-01-01",
                                "last_played_at": 200,
                            }
                        ]
                    }
                },
            },
        },
        "Remote Movies": {
            "Zeta Movie": {
                "poster_path": "/posters/zeta.jpg",
                "watched": False,
                "date_added": 400,
                "year": 2024,
            }
        },
    }

    all_alpha = compute_smart_rows_from_memory(
        remote_data,
        library_configs,
        ["Remote TV", "Remote Movies"],
        "Alphabetical",
        "All",
    )
    assert [item["name"] for item in all_alpha] == [
        "Alpha Show",
        "Beta Show",
        "Zeta Movie",
    ]

    watched_only = compute_smart_rows_from_memory(
        remote_data,
        library_configs,
        ["Remote TV", "Remote Movies"],
        "Alphabetical",
        "Watched",
    )
    assert [item["name"] for item in watched_only] == ["Beta Show"]

    unwatched_recent = compute_smart_rows_from_memory(
        remote_data,
        library_configs,
        ["Remote TV", "Remote Movies"],
        "Recently Added",
        "Unwatched",
    )
    assert [item["name"] for item in unwatched_recent] == ["Zeta Movie", "Alpha Show"]

    next_up = compute_smart_rows_from_memory(
        remote_data, library_configs, ["Remote TV"], "Next Up", "All"
    )
    assert [item["name"] for item in next_up] == ["Alpha Show"]
