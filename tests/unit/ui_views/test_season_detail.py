from unittest.mock import patch
from typing import Any

from lan_streamer.ui_views import SeasonDetailView
from sqlalchemy import text
from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Series, Season, Episode
from lan_streamer.db.models_cast import Person, MediaCast


def test_season_detail_display(qtbot: Any) -> None:
    """Test that display_season populates the UI with correct data."""
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    with get_session() as session:
        series = Series(library_name="TV", name="Test Series")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()

        episode = Episode(
            season_id=season.id,
            name="Pilot",
            tmdb_number=1,
            air_date="2020-01-01",
            runtime=30,
        )
        session.add(episode)

        person = Person(tmdb_identifier=12345, name="Test Actor")
        session.add(person)
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            series_id=series.id,
            role="actor",
            character="Main Character",
            sort_order=1,
        )
        session.add(cast_entry)

    view = SeasonDetailView()
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_season("Test Series", "Season 1")

    assert view._title_label.text() == "Season 1"
    assert view._series_label.text() == "Series: Test Series"
    assert view._episode_count_label.text() == "1 episodes"
    assert view._episode_table.rowCount() == 1
    assert view._episode_table.item(0, 0).text() == "1"
    assert view._episode_table.item(0, 1).text() == "Pilot"
    assert view._episode_table.item(0, 2).text() == "2020-01-01"
    assert view._episode_table.item(0, 3).text() == "30 min"
    assert view._cast_grid.count() > 0


def test_season_detail_cast_member_click(qtbot: Any) -> None:
    """Test that cast_member_clicked signal is emitted when cast member is clicked."""
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    with get_session() as session:
        series = Series(library_name="TV", name="Test Series")
        session.add(series)
        session.flush()
        season = Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()

        person = Person(tmdb_identifier=12345, name="Test Actor")
        session.add(person)
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            series_id=series.id,
            role="actor",
            character="Main Character",
            sort_order=1,
        )
        session.add(cast_entry)

    view = SeasonDetailView()
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.season_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_season("Test Series", "Season 1")

    emitted_person_ids = []
    view.cast_member_clicked.connect(emitted_person_ids.append)

    view._on_cast_clicked(person.id)
    assert emitted_person_ids == [person.id]
