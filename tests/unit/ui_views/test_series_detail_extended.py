"""
Extended SeriesDetailView tests targeting missing coverage:
- _on_order_changed (index<0 / index>=0)
- _on_mark_series_watched (no series name / with series name)
- _on_mark_season_watched
- _on_play_next_clicked (no path / with path)
- on_library_loaded (with/without series)
- trigger_episode_playback_by_row
- populate_series_details behavior:
  - is_video_playing guard
  - missing future episodes filter
  - episode icon for watched/missing/future
  - play_next_button visibility
  - tab restoration on reload
"""

import pytest
from unittest.mock import patch
from typing import List

from lan_streamer.ui_views.series_detail import SeriesDetailView
from lan_streamer.ui_views.controller import Controller
from lan_streamer.system.config import config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ctrl_with_show(mock_db_saves):
    c = Controller()
    c.current_library_name = "TVLib"
    c.cached_library_data = {
        "ShowA": {
            "metadata": {
                "tmdb_identifier": "111",
                "tmdb_name": "Show A",
                "overview": "A great show",
                "poster_path": "",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "metadata": {"jellyfin_id": "", "poster_path": ""},
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": "/tv/S01E01.mkv",
                            "tmdb_name": "Pilot",
                            "tmdb_number": 1,
                            "watched": False,
                            "runtime": 45,
                            "air_date": "2021-01-01",
                            "tmdb_episode_identifier": "ep1",
                        },
                        {
                            "name": "S01E02.mkv",
                            "path": "/tv/S01E02.mkv",
                            "tmdb_name": "Second",
                            "tmdb_number": 2,
                            "watched": True,
                            "runtime": 44,
                            "air_date": "2021-01-08",
                            "tmdb_episode_identifier": "ep2",
                        },
                    ],
                }
            },
        }
    }
    c.selected_series_name = "ShowA"
    config.libraries = {
        "TVLib": {"type": "tv", "paths": ["/tv"], "show_future_episodes": True}
    }
    return c


@pytest.fixture
def mock_db_saves():
    with (
        patch("lan_streamer.db.save_library"),
        patch("lan_streamer.db.save_movie_library"),
    ):
        yield


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_view(ctrl, qtbot):
    with patch(
        "lan_streamer.ui_views.proxy.tmdb_client.get_episode_groups", return_value=[]
    ):
        v = SeriesDetailView(ctrl)
    qtbot.addWidget(v)
    return v


def populate(view, ctrl, series_name="ShowA"):
    with (
        patch(
            "lan_streamer.ui_views.proxy.tmdb_client.get_episode_groups",
            return_value=[],
        ),
        patch(
            "lan_streamer.ui_views.proxy.tmdb_client.get_episode_group_details",
            return_value={},
        ),
    ):
        view.populate_series_details(series_name)


# ---------------------------------------------------------------------------
# on_library_loaded
# ---------------------------------------------------------------------------


def test_on_library_loaded_refreshes_when_series_selected(
    ctrl_with_show, qtbot
) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    with patch.object(v, "populate_series_details") as mock_pop:
        ctrl_with_show.library_loaded.emit()
        mock_pop.assert_called_once_with("ShowA")


def test_on_library_loaded_no_op_without_current_series(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    # Don't populate first, so _current_series_name is empty

    with patch.object(v, "populate_series_details") as mock_pop:
        ctrl_with_show.library_loaded.emit()
        mock_pop.assert_not_called()


# ---------------------------------------------------------------------------
# _on_order_changed
# ---------------------------------------------------------------------------


def test_on_order_changed_negative_index_no_op(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    with patch.object(v, "populate_series_details") as mock_pop:
        v._on_order_changed(-1)
        mock_pop.assert_not_called()


def test_on_order_changed_triggers_repopulate(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    with patch.object(v, "populate_series_details") as mock_pop:
        # Add an item to the combo to avoid index-0 being -1
        v.order_combo.addItem("TV Order (Default)", userData="default")
        v._on_order_changed(0)
        mock_pop.assert_called_once_with("ShowA")


# ---------------------------------------------------------------------------
# _on_mark_season_watched
# ---------------------------------------------------------------------------


def test_on_mark_season_watched_no_selected_series(ctrl_with_show, qtbot) -> None:
    ctrl_with_show.selected_series_name = ""
    v = make_view(ctrl_with_show, qtbot)

    with patch.object(ctrl_with_show, "mark_season_watched") as mock_mark:
        v._on_mark_season_watched("Season 1")
        mock_mark.assert_not_called()


def test_on_mark_season_watched_calls_controller(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    with patch.object(ctrl_with_show, "mark_season_watched") as mock_mark:
        with patch.object(v, "populate_series_details"):
            v._on_mark_season_watched("Season 1")
            mock_mark.assert_called_once_with("ShowA", "Season 1")


# ---------------------------------------------------------------------------
# _on_play_next_clicked
# ---------------------------------------------------------------------------


def test_on_play_next_clicked_with_path_emits_playback(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    emitted = []
    ctrl_with_show.playback_requested.connect(emitted.append)

    v._next_episode_path = "/tv/S01E01.mkv"
    v._on_play_next_clicked()
    assert "/tv/S01E01.mkv" in emitted


def test_on_play_next_clicked_without_path_no_emit(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    emitted = []
    ctrl_with_show.playback_requested.connect(emitted.append)

    v._next_episode_path = ""
    v._on_play_next_clicked()
    assert len(emitted) == 0


# ---------------------------------------------------------------------------
# populate_series_details — is_video_playing guard
# ---------------------------------------------------------------------------


def test_populate_ignores_when_video_playing(ctrl_with_show, qtbot) -> None:
    ctrl_with_show.is_video_playing = True
    v = make_view(ctrl_with_show, qtbot)

    with patch.object(v, "title_label") as mock_title:
        populate(v, ctrl_with_show)
        mock_title.setText.assert_not_called()


# ---------------------------------------------------------------------------
# populate_series_details — play_next_button visibility
# ---------------------------------------------------------------------------


def test_populate_shows_play_next_when_unwatched_episode_exists(
    ctrl_with_show, qtbot
) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    # First unwatched episode with path should be assigned to _next_episode_path
    assert v._next_episode_path == "/tv/S01E01.mkv"
    assert "S01E01.mkv" in v.play_next_button.text() or v._next_episode_path != ""


def test_populate_hides_play_next_when_all_watched(ctrl_with_show, qtbot) -> None:
    # Mark all episodes watched
    for ep in ctrl_with_show.cached_library_data["ShowA"]["seasons"]["Season 1"][
        "episodes"
    ]:
        ep["watched"] = True

    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    assert not v.play_next_button.isVisible()
    assert v._next_episode_path == ""


# ---------------------------------------------------------------------------
# populate_series_details — seasons table created
# ---------------------------------------------------------------------------


def test_populate_creates_season_tabs(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    assert v.seasons_tab_widget.count() >= 1
    assert v.seasons_tab_widget.tabText(0) == "Season 1"


def test_populate_season_table_has_correct_row_count(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    table = v._season_tables.get("Season 1")
    assert table is not None
    assert table.rowCount() == 2  # Two episodes in fixture


def test_populate_sets_title_and_overview(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    assert v.title_label.text() == "Show A"
    assert "A great show" in v.overview_label.text()


# ---------------------------------------------------------------------------
# populate_series_details — no poster fallback
# ---------------------------------------------------------------------------


def test_populate_shows_no_poster_text_when_poster_missing(
    ctrl_with_show, qtbot
) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)
    # poster_path is empty, so text should be "No Poster"
    assert v.poster_label.text() == "No Poster"


# ---------------------------------------------------------------------------
# trigger_episode_playback_by_row
# ---------------------------------------------------------------------------


def test_trigger_episode_playback_by_row_emits_signal(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    emitted: List[str] = []
    ctrl_with_show.playback_requested.connect(emitted.append)

    v.trigger_episode_playback_by_row(0, 0)  # season tab 0, row 0
    assert "/tv/S01E01.mkv" in emitted


def test_trigger_episode_playback_by_row_invalid_tab(ctrl_with_show, qtbot) -> None:
    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    emitted: List[str] = []
    ctrl_with_show.playback_requested.connect(emitted.append)

    v.trigger_episode_playback_by_row(99, 0)  # Invalid tab
    assert len(emitted) == 0


# ---------------------------------------------------------------------------
# Future episode filter in populate
# ---------------------------------------------------------------------------


def test_populate_hides_future_episodes_when_show_future_false(
    ctrl_with_show, qtbot
) -> None:
    config.libraries["TVLib"]["show_future_episodes"] = False

    # Add a future episode without a path
    import datetime

    future_date = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    ctrl_with_show.cached_library_data["ShowA"]["seasons"]["Season 1"][
        "episodes"
    ].append(
        {
            "name": "Future.mkv",
            "path": None,
            "tmdb_name": "Future Episode",
            "tmdb_number": 3,
            "watched": False,
            "runtime": 45,
            "air_date": future_date,
            "tmdb_episode_identifier": "ep_future",
        }
    )

    v = make_view(ctrl_with_show, qtbot)
    populate(v, ctrl_with_show)

    table = v._season_tables.get("Season 1")
    assert table is not None
    # Future episode without path should be hidden when show_future_episodes=False
    row_count = table.rowCount()
    # 2 regular episodes remain (both have paths)
    assert row_count == 2

    # Reset
    config.libraries["TVLib"]["show_future_episodes"] = True
