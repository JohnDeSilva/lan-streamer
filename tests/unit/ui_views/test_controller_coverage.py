from unittest.mock import MagicMock
from lan_streamer.ui_views import Controller


def test_controller_coverage_basics() -> None:
    c = Controller(db=MagicMock(), config=MagicMock())
    c.current_library_name = "Lib"

    # 1. task_manager property
    assert c.task_manager == c.async_task_manager

    # 2. toggle_series_lock when not in cached_library_data
    c.cached_library_data = {}
    c.toggle_series_lock("ShowX", True)  # should return early

    # 3. toggle_series_lock for movie library
    c.cached_library_data = {"MovieA": {}}
    c._config.libraries = {"Lib": {"type": "movie"}}
    emitted = []
    c.movie_selected.connect(emitted.append)
    c.toggle_series_lock("MovieA", True)
    assert c.cached_library_data["MovieA"]["locked_metadata"] is True
    assert emitted == ["MovieA"]


def test_controller_scheduled_scans() -> None:
    c = Controller(db=MagicMock(), config=MagicMock())
    c.scheduled_scan_service = MagicMock()

    # auto_scan_enabled is False
    c._config.auto_scan_enabled = False
    c.start_scheduled_scans()
    c.scheduled_scan_service.start.assert_not_called()

    # auto_scan_enabled is True
    c._config.auto_scan_enabled = True
    c.start_scheduled_scans()
    c.scheduled_scan_service.start.assert_called_once()

    # stop scheduled scans
    c.stop_scheduled_scans()
    c.scheduled_scan_service.stop.assert_called_once()


def test_controller_misc_edge_cases() -> None:
    c = Controller(db=MagicMock(), config=MagicMock())
    c.current_library_name = "Lib"

    # mark_series_watched when not in cache
    c.cached_library_data = {}
    c.mark_series_watched("UnknownShow")  # no crash

    # mark_season_watched when not in cache
    c.mark_season_watched("UnknownShow", "Season 1")  # no crash

    # mark_season_watched when season not in series
    c.cached_library_data = {"ShowA": {"seasons": {}}}
    c.mark_season_watched("ShowA", "Season 1")  # no crash

    # set_filter_out_watched
    emitted = []
    c.library_loaded.connect(lambda: emitted.append(True))
    c.set_filter_out_watched(True)
    assert c.filter_out_watched is True
    assert emitted == [True]

    # toggle same value does not emit
    emitted.clear()
    c.set_filter_out_watched(True)
    assert emitted == []
