from typing import Any
from unittest.mock import patch

from sqlalchemy import text

from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Episode, Season, Series, SeriesLibrary
from lan_streamer.db.models_cast import MediaCast, Person
from lan_streamer.ui_views import Controller, SeriesDetailView


def test_series_detail_cast_section(qtbot: Any) -> None:
    controller = Controller()
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        "Test Series": {
            "metadata": {
                "tmdb_name": "Test Series",
                "overview": "A test series.",
                "poster_path": "/path/to/poster.jpg",
            },
            "seasons": {},
        }
    }

    # Clean up existing data first in a separate transaction
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    # Setup database series row and cast entries
    with get_session() as session:
        series = Series(library_name="TV", name="Test Series")
        session.add(series)
        session.flush()

        person = Person(
            tmdb_identifier=12345, name="Test Actor"
        )  # no profile_path to avoid QPixmap load
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

    view = SeriesDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.series_detail.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.series_detail.QPixmap") as mock_pixmap,
        patch.object(view.poster_label, "setPixmap"),
    ):
        mock_pixmap.return_value.isNull.return_value = False
        view.populate_series_details("Test Series")

    # Check that cast grid is populated
    assert view._cast_grid.count() > 0


def test_series_detail_cast_member_click(qtbot: Any) -> None:
    controller = Controller()
    controller.current_library_name = "TV"
    controller.cached_library_data = {
        "Test Series": {
            "metadata": {
                "tmdb_name": "Test Series",
                "overview": "A test series.",
                "poster_path": "/path/to/poster.jpg",
            },
            "seasons": {},
        }
    }

    # Clean up existing data first in a separate transaction
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    # Setup database series row and cast entries
    with get_session() as session:
        series = Series(library_name="TV", name="Test Series")
        session.add(series)
        session.flush()

        person = Person(tmdb_identifier=12345, name="Test Actor")  # no profile_path
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

    view = SeriesDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.series_detail.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.series_detail.QPixmap") as mock_pixmap,
        patch.object(view.poster_label, "setPixmap"),
    ):
        mock_pixmap.return_value.isNull.return_value = False
        view.populate_series_details("Test Series")

    # Check that controller.cast_member_selected signal is emitted
    emitted_ids = []
    controller.cast_member_selected.connect(emitted_ids.append)

    # Manually trigger the click handler
    view._on_cast_member_clicked(person.id)
    assert emitted_ids == [person.id]


def test_series_detail_cast_via_junction_library(qtbot: Any) -> None:
    controller = Controller()
    controller.current_library_name = "Secondary TV"
    controller.cached_library_data = {
        "Shared Series": {
            "metadata": {
                "tmdb_name": "Shared Series",
                "overview": "A shared test series.",
                "poster_path": "/path/to/poster.jpg",
            },
            "seasons": {},
        }
    }

    # Clean up existing data first
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(SeriesLibrary.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    # Primary library is "Primary TV", linked to "Secondary TV" via SeriesLibrary
    with get_session() as session:
        series = Series(library_name="Primary TV", name="Shared Series")
        session.add(series)
        session.flush()

        junction_link = SeriesLibrary(series_id=series.id, library_name="Secondary TV")
        session.add(junction_link)

        person = Person(tmdb_identifier=54321, name="Junction Actor")
        session.add(person)
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            series_id=series.id,
            role="actor",
            character="Secondary Character",
            sort_order=1,
        )
        session.add(cast_entry)

    view = SeriesDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.series_detail.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.series_detail.QPixmap") as mock_pixmap,
        patch.object(view.poster_label, "setPixmap"),
    ):
        mock_pixmap.return_value.isNull.return_value = False
        view.populate_series_details("Shared Series")

    assert view._cast_grid.count() > 0
    assert view._lookup_series_id() == series.id
