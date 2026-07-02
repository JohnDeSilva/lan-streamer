from unittest.mock import patch
from typing import Any
from sqlalchemy import text
from PySide6.QtWidgets import QLabel
from lan_streamer.ui_views import CastDetailView
from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Series, Episode, Season
from lan_streamer.db.models_cast import Person, MediaCast


def test_cast_detail_display(qtbot: Any) -> None:
    """Test that display_person shows name, biography, birth/death/place labels, and filmography."""
    # Clean up existing data first in a separate transaction
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    # Setup database with test data
    with get_session() as session:
        person = Person(
            tmdb_identifier=12345,
            name="Test Actor",
            biography="A test biography.",
            birth_date="1970-01-01",
            place_of_birth="Somewhere",
        )
        session.add(person)
        session.flush()

        series = Series(library_name="TV", name="Test Series")
        session.add(series)
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            series_id=series.id,
            role="actor",
            character="Main Character",
            sort_order=1,
        )
        session.add(cast_entry)

        person_id = person.id

    # Create and test the view
    view = CastDetailView()
    qtbot.addWidget(view)

    # Mock QPixmap to avoid loading actual image
    with patch("lan_streamer.ui_views.cast_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_person(person_id)

    # Test name label
    assert view._name_label.text() == "Test Actor"

    # Test biography label
    assert view._biography_label.text() == "A test biography."

    # Test birth/death/place labels
    # Note: the view fills labels sequentially from bio_parts list
    assert view._birth_label.text() == "Born: 1970-01-01"
    assert view._death_label.text() == "Place of birth: Somewhere"
    assert view._place_label.text() == ""

    # Test filmography - check that cards were created
    # The filmography layout should have at least one card
    assert view._filmography_layout.count() > 0

    # Check that the card contains the series title
    card = view._filmography_layout.itemAt(0).widget()
    assert card is not None

    # Find title label in the card
    title_label = None
    for i in range(card.layout().count()):
        item = card.layout().itemAt(i)
        if item.widget() and isinstance(item.widget(), QLabel):
            if "Test Series" in item.widget().text():
                title_label = item.widget()
                break

    assert title_label is not None
    assert title_label.text() == "Test Series"


def test_cast_detail_not_found(qtbot: Any) -> None:
    """Test display of 'Person not found' when invalid ID given."""
    # Create and test the view
    view = CastDetailView()
    qtbot.addWidget(view)

    # Use an invalid person ID
    invalid_person_id = "invalid-uuid"

    # Mock get_person_by_id to return None
    with patch("lan_streamer.ui_views.cast_detail.get_person_by_id", return_value=None):
        view.display_person(invalid_person_id)

    # Test that name label shows "Person not found"
    assert view._name_label.text() == "Person not found"

    # Test that other labels are empty
    assert view._birth_label.text() == ""
    assert view._death_label.text() == ""
    assert view._place_label.text() == ""
    assert view._biography_label.text() == ""

    # Filmography is not shown when person is not found (early return)
    assert view._filmography_layout.count() == 0
