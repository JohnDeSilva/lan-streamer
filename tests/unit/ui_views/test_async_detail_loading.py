import asyncio
from unittest.mock import patch, MagicMock
from typing import Any

from lan_streamer.ui_views import SeriesDetailView, MovieDetailView, Controller


def test_series_detail_view_async_loading_flow(qtbot: Any) -> None:
    """Test that SeriesDetailView async loading executes and updates UI correctly in an event loop."""
    controller_instance = Controller()
    controller_instance.current_library_name = "TVLib"
    controller_instance.cached_library_data = {
        "ShowA": {
            "metadata": {
                "tmdb_name": "Show A Name",
                "overview": "Overview of Show A",
                "poster_path": "",
                "tmdb_identifier": 12345,
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "Episode 1",
                            "path": "/media/ShowA/S01E01.mkv",
                            "watched": False,
                            "tmdb_number": 1,
                        }
                    ]
                }
            },
        }
    }

    series_detail_view = SeriesDetailView(controller_instance)
    qtbot.addWidget(series_detail_view)

    # Prepare mocked return data
    mock_cast_entries = [
        {
            "person_id": "person-1",
            "name": "Actor One",
            "profile_path": None,
            "character": "Hero",
        }
    ]
    mock_groups_list = [{"id": "group-1", "name": "Story Order"}]
    mock_group_details = {"groups": []}

    # Setup the mock patches
    with (
        patch.object(
            series_detail_view,
            "_fetch_series_db_and_cast",
            return_value=("series-db-id", mock_cast_entries),
        ),
        patch(
            "lan_streamer.ui_views.proxy.tmdb_client.get_episode_groups",
            return_value=mock_groups_list,
        ),
        patch(
            "lan_streamer.ui_views.proxy.tmdb_client.get_episode_group_details",
            return_value=mock_group_details,
        ),
        patch.object(series_detail_view, "_update_series_ui") as mock_update_ui,
    ):
        # Trigger async loading
        asyncio.run(series_detail_view._load_details_async("ShowA"))

        # Verify that all components are loaded and update helper is called with correct arguments
        mock_update_ui.assert_called_once_with(
            series_name="ShowA",
            series_database_identifier="series-db-id",
            cast_entries=mock_cast_entries,
            available_groups=[
                {"id": "default", "name": "TV Order (Default)"},
                {"id": "group-1", "name": "Story Order"},
            ],
            group_details=None,  # Because saved preference is default
            saved_group_identifier="default",
        )


def test_movie_detail_view_async_loading_flow(qtbot: Any) -> None:
    """Test that MovieDetailView async loading executes and updates UI correctly."""
    controller_instance = Controller()
    controller_instance.current_library_name = "MovieLib"
    controller_instance.cached_library_data = {
        "MovieA": {
            "name": "MovieA",
            "path": "/movies/MovieA.mkv",
            "tmdb_name": "Movie A",
            "overview": "Overview of Movie A",
            "poster_path": "",
        }
    }

    movie_detail_view = MovieDetailView(controller_instance)
    qtbot.addWidget(movie_detail_view)

    mock_cast_entries = [
        {
            "person_id": "person-2",
            "name": "Actor Two",
            "profile_path": None,
            "character": "Sidekick",
        }
    ]

    with (
        patch.object(
            movie_detail_view,
            "_fetch_movie_db_and_cast",
            return_value=("movie-db-id", mock_cast_entries),
        ),
        patch.object(movie_detail_view, "_update_movie_ui") as mock_update_ui,
    ):
        asyncio.run(movie_detail_view._load_movie_details_async("MovieA"))
        mock_update_ui.assert_called_once_with(
            "MovieA", "movie-db-id", mock_cast_entries
        )


def test_series_detail_view_scanning_cache_check(qtbot: Any) -> None:
    """Verify that during scanning, redundant reloads are skipped if cached data has not changed."""
    controller_instance = Controller()
    controller_instance.current_library_name = "TVLib"
    controller_instance.worker_manager = MagicMock()
    # Mock scanning worker running state
    controller_instance.worker_manager.scan.is_running = True

    library_data_record = {
        "ShowA": {
            "metadata": {
                "tmdb_name": "Show A",
                "overview": "Overview",
                "poster_path": "",
            },
            "seasons": {},
        }
    }
    controller_instance.cached_library_data = library_data_record

    series_detail_view = SeriesDetailView(controller_instance)
    qtbot.addWidget(series_detail_view)

    series_detail_view._current_series_name = "ShowA"
    # Populate the cache copy
    series_detail_view._cached_series_data_copy = library_data_record["ShowA"].copy()

    with patch.object(series_detail_view, "populate_series_details") as mock_populate:
        # Emit library_loaded when scan is running and data is identical
        series_detail_view.on_library_loaded()
        mock_populate.assert_not_called()

        # Disable scanning worker state; reload should always occur regardless of cache copy equality
        controller_instance.worker_manager.scan.is_running = False
        series_detail_view.on_library_loaded()
        mock_populate.assert_called_once_with("ShowA")
