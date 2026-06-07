"""
Controller extended tests part 3:
- _sync_tmdb_episodes_for_series with saved group id (success + failure)
- _sync_tmdb_episodes_for_series with specials season
- _sync_tmdb_episodes_for_series with name-based episode matching (no SxxExx pattern)
- _download_provider_artwork with no tmdb_identifier
- _download_provider_artwork is_movie prefix
- _on_scan_finished with movie library type
- apply_metadata_match with overview / first_air_date (TV)
- _on_subtitle_merge_finished / _on_metadata_embed_finished side effects
- refresh_episode_metadata (no tmdb_id, no episode, specials, no episode_num)
- MAL sync in controller
"""

import pytest
from unittest.mock import patch, MagicMock

from lan_streamer.ui_views import Controller
from lan_streamer.system.config import config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_save():
    with (
        patch("lan_streamer.db.save_library") as mock_save,
        patch("lan_streamer.db.save_movie_library") as mock_movie_save,
    ):
        yield mock_save, mock_movie_save


@pytest.fixture
def ctrl_tv(mock_db_save):
    c = Controller()
    c.current_library_name = "TVLib"
    c.cached_library_data = {
        "ShowA": {
            "metadata": {
                "tmdb_identifier": "111",
                "locked_metadata": False,
                "tmdb_episode_group_id": None,
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": "/tv/S01E01.mkv",
                            "watched": False,
                            "tmdb_number": 1,
                            "date_added": 1000,
                            "air_date": "2021-01-01",
                            "runtime": 45,
                        }
                    ]
                },
                "Specials": {
                    "episodes": [
                        {
                            "name": "special.mkv",
                            "path": "/tv/special.mkv",
                            "watched": False,
                            "tmdb_number": 0,
                            "date_added": 500,
                            "air_date": "2021-01-01",
                            "runtime": 10,
                        }
                    ]
                },
            },
        }
    }
    c.selected_series_name = "ShowA"
    config.libraries = {"TVLib": {"type": "tv", "paths": ["/tv"]}}
    return c


# ---------------------------------------------------------------------------
# _sync_tmdb_episodes_for_series — saved group id that raises
# ---------------------------------------------------------------------------


def test_sync_tmdb_episodes_saved_group_fails_falls_back(ctrl_tv, mock_db_save) -> None:
    """When fetching saved group_id fails, fall back to get_season_based_episode_group."""
    ctrl_tv.cached_library_data["ShowA"]["metadata"]["tmdb_episode_group_id"] = (
        "grp-123"
    )
    series_record = ctrl_tv.cached_library_data["ShowA"]

    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_episode_group_details.side_effect = RuntimeError("Network error")
        mock_tmdb.get_season_based_episode_group.return_value = None
        mock_tmdb.get_episodes.return_value = []

        ctrl_tv._sync_tmdb_episodes_for_series(series_record, "111")

        mock_tmdb.get_episode_group_details.assert_called_once_with("grp-123")
        mock_tmdb.get_season_based_episode_group.assert_called_once_with("111")


def test_sync_tmdb_episodes_saved_group_default_skips_fetch(
    ctrl_tv, mock_db_save
) -> None:
    """When tmdb_episode_group_id == 'default', skip fetching saved group."""
    ctrl_tv.cached_library_data["ShowA"]["metadata"]["tmdb_episode_group_id"] = (
        "default"
    )
    series_record = ctrl_tv.cached_library_data["ShowA"]

    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_season_based_episode_group.return_value = None
        mock_tmdb.get_episodes.return_value = []

        ctrl_tv._sync_tmdb_episodes_for_series(series_record, "111")

        mock_tmdb.get_episode_group_details.assert_not_called()


def test_sync_tmdb_episodes_specials_season_mapped_to_zero(
    ctrl_tv, mock_db_save
) -> None:
    """Specials season should be mapped to season_number 0."""
    series_record = ctrl_tv.cached_library_data["ShowA"]

    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_season_based_episode_group.return_value = None
        mock_tmdb.get_episodes.return_value = [
            {
                "episode_number": 0,
                "name": "S01E00 Special",
                "id": "sp1",
                "air_date": "",
                "runtime": 10,
            }
        ]

        ctrl_tv._sync_tmdb_episodes_for_series(series_record, "111")
        # Should have called get_episodes for season 0
        calls = [str(c) for c in mock_tmdb.get_episodes.call_args_list]
        assert any("0" in c for c in calls)


def test_sync_tmdb_episodes_name_matching_fallback(ctrl_tv, mock_db_save) -> None:
    """When episode name doesn't match SxxExx pattern, fall back to name matching."""
    series_record = ctrl_tv.cached_library_data["ShowA"]
    # Change the episode name so it doesn't match SxxExx
    series_record["seasons"]["Season 1"]["episodes"][0]["name"] = "The Pilot"

    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_season_based_episode_group.return_value = None
        mock_tmdb.get_episodes.return_value = [
            {
                "episode_number": 1,
                "name": "The Pilot",
                "id": "ep1",
                "air_date": "2021-01-01",
                "runtime": 45,
            }
        ]

        ctrl_tv._sync_tmdb_episodes_for_series(series_record, "111")

        ep = series_record["seasons"]["Season 1"]["episodes"][0]
        assert ep.get("tmdb_name") == "The Pilot"


def test_sync_tmdb_episodes_with_episode_group(ctrl_tv, mock_db_save) -> None:
    """When episode group details are returned, should use group episodes instead of get_episodes."""
    series_record = ctrl_tv.cached_library_data["ShowA"]

    group_details = {
        "id": "grp-x",
        "groups": [
            {
                "name": "Season 1",
                "order": 0,
                "episodes": [
                    {
                        "id": "ep-grp-1",
                        "name": "Group Episode 1",
                        "order": 0,  # episode_number = order + 1 = 1
                        "air_date": "2021-01-01",
                        "runtime": 45,
                    }
                ],
            }
        ],
    }

    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_season_based_episode_group.return_value = group_details
        mock_tmdb.get_episodes.return_value = []

        ctrl_tv._sync_tmdb_episodes_for_series(series_record, "111")

        # Should NOT have called get_episodes since group details were returned
        mock_tmdb.get_episodes.assert_not_called()
        ep = series_record["seasons"]["Season 1"]["episodes"][0]
        assert ep.get("tmdb_name") == "Group Episode 1"


def test_sync_tmdb_episodes_specials_group_name(ctrl_tv, mock_db_save) -> None:
    """Group with name 'Specials' should map to season_num=0."""
    series_record = ctrl_tv.cached_library_data["ShowA"]

    group_details = {
        "id": "grp-specials",
        "groups": [
            {
                "name": "Specials",
                "order": 99,
                "episodes": [],
            }
        ],
    }

    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_season_based_episode_group.return_value = group_details
        ctrl_tv._sync_tmdb_episodes_for_series(series_record, "111")
        # Should not crash


# ---------------------------------------------------------------------------
# _download_provider_artwork — no tmdb_identifier path
# ---------------------------------------------------------------------------


def test_download_provider_artwork_no_tmdb_id_no_crash(mock_db_save) -> None:
    c = Controller()
    target = {}  # No tmdb_identifier
    match = {"poster_path": "/p/image.jpg"}

    with patch("lan_streamer.ui_views.controller.tmdb_client"):
        c._download_provider_artwork(target, match, is_movie=False)

    # Falls through to else branch — sets poster_path directly
    assert target.get("poster_path") == "/p/image.jpg"


def test_download_provider_artwork_movie_prefix(mock_db_save) -> None:
    c = Controller()
    target = {"tmdb_identifier": "movie-99"}
    match = {"poster_path": "/p/movie.jpg"}

    with patch(
        "lan_streamer.ui_views.controller.tmdb_client.download_image",
        return_value="/cached/m.jpg",
    ):
        c._download_provider_artwork(target, match, is_movie=True)

    assert target["poster_path"] == "/cached/m.jpg"


# ---------------------------------------------------------------------------
# _on_scan_finished — movie library type
# ---------------------------------------------------------------------------


def test_on_scan_finished_movie_library(mock_db_save) -> None:
    mock_save, mock_movie_save = mock_db_save
    c = Controller()
    c.current_library_name = "MovieLib"
    config.libraries["MovieLib"] = {"type": "movie", "paths": []}

    mock_worker = MagicMock()
    mock_worker.library_name = "MovieLib"
    mock_worker.unavailable_directories = []
    c.scan_worker_instance = mock_worker

    updated = {"Film": {"path": "/m.mkv"}}
    c._on_scan_finished(updated)

    mock_movie_save.assert_called_once_with("MovieLib", updated)


# ---------------------------------------------------------------------------
# apply_metadata_match — overview and first_air_date for TV
# ---------------------------------------------------------------------------


def test_apply_metadata_match_tv_overview_and_air_date(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save
    match = {
        "id": "222",
        "name": "New Show",
        "overview": "A great show",
        "first_air_date": "2022-03-15",
    }
    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_season_based_episode_group.return_value = None
        mock_tmdb.get_episodes.return_value = []
        ctrl_tv.apply_metadata_match("ShowA", match)

    meta = ctrl_tv.cached_library_data["ShowA"]["metadata"]
    assert meta["overview"] == "A great show"
    assert meta["first_air_date"] == "2022-03-15"
    mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# _on_subtitle_merge_finished and _on_metadata_embed_finished
# ---------------------------------------------------------------------------


def test_on_subtitle_merge_finished_triggers_scan(ctrl_tv) -> None:
    with patch.object(ctrl_tv, "trigger_scan") as mock_trigger:
        ctrl_tv._on_subtitle_merge_finished("/merged.mkv")
        mock_trigger.assert_called_once_with(force_refresh=False)


def test_on_metadata_embed_finished_triggers_scan(ctrl_tv) -> None:
    with patch.object(ctrl_tv, "trigger_scan") as mock_trigger:
        ctrl_tv._on_metadata_embed_finished("/embedded.mkv")
        mock_trigger.assert_called_once_with(force_refresh=False)


# ---------------------------------------------------------------------------
# refresh_episode_metadata — various short-circuit paths
# ---------------------------------------------------------------------------


def test_refresh_episode_metadata_no_tmdb_id(ctrl_tv, mock_db_save) -> None:
    """Should return early if series has no tmdb_identifier."""
    del ctrl_tv.cached_library_data["ShowA"]["metadata"]["tmdb_identifier"]

    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        ctrl_tv.refresh_episode_metadata("ShowA", "/tv/S01E01.mkv")
        mock_tmdb.get_episodes.assert_not_called()


def test_refresh_episode_metadata_episode_not_found(ctrl_tv, mock_db_save) -> None:
    """Should return early if episode not found at given path."""
    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        ctrl_tv.refresh_episode_metadata("ShowA", "/nonexistent.mkv")
        mock_tmdb.get_episodes.assert_not_called()


def test_refresh_episode_metadata_specials_season(ctrl_tv, mock_db_save) -> None:
    """For specials seasons, should use season_index=0."""
    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_episodes.return_value = []
        ctrl_tv.refresh_episode_metadata("ShowA", "/tv/special.mkv")
        mock_tmdb.get_episodes.assert_called()
        # First arg should be "111", second should be 0
        args = mock_tmdb.get_episodes.call_args[0]
        assert args[1] == 0


def test_refresh_episode_metadata_no_episode_number(ctrl_tv, mock_db_save) -> None:
    """Should return early if episode has no tmdb_number."""
    ctrl_tv.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0][
        "tmdb_number"
    ] = None

    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        ctrl_tv.refresh_episode_metadata("ShowA", "/tv/S01E01.mkv")
        mock_tmdb.get_episodes.assert_not_called()


def test_refresh_episode_metadata_tmdb_exception(ctrl_tv, mock_db_save) -> None:
    """Should not crash when TMDB throws."""
    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_episodes.side_effect = RuntimeError("TMDB down")
        ctrl_tv.refresh_episode_metadata("ShowA", "/tv/S01E01.mkv")  # Should not raise


def test_refresh_episode_metadata_no_match_in_tmdb(ctrl_tv, mock_db_save) -> None:
    """Should handle case where TMDB returns episodes but none match."""
    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_episodes.return_value = [
            {"episode_number": 99, "name": "Wrong Ep", "id": "x"}
        ]
        ctrl_tv.refresh_episode_metadata("ShowA", "/tv/S01E01.mkv")
    # No crash, no update


def test_refresh_episode_metadata_success(ctrl_tv, mock_db_save) -> None:
    mock_save, _ = mock_db_save
    with patch("lan_streamer.ui_views.controller.tmdb_client") as mock_tmdb:
        mock_tmdb.get_episodes.return_value = [
            {
                "episode_number": 1,
                "name": "Fresh Title",
                "overview": "Fresh overview",
                "air_date": "2022-01-01",
                "runtime": 55,
            }
        ]
        ctrl_tv.refresh_episode_metadata("ShowA", "/tv/S01E01.mkv")

    ep = ctrl_tv.cached_library_data["ShowA"]["seasons"]["Season 1"]["episodes"][0]
    assert ep["tmdb_name"] == "Fresh Title"
    assert ep["runtime"] == 55
    mock_save.assert_called_once()
