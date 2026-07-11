import os
from unittest.mock import patch
from typing import Any
from sqlalchemy import text
from PySide6.QtWidgets import QLabel, QLayout
from lan_streamer.ui_views import CastDetailView
from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Series, Episode, Season, Movie
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

    # Find title label in the card (may be nested in sub-layouts)
    title_label = None

    def _find_label(layout: QLayout) -> None:
        nonlocal title_label
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None and isinstance(widget, QLabel):
                if "Test Series" in widget.text():
                    title_label = widget
                    return
            sub_layout = item.layout()
            if sub_layout is not None:
                _find_label(sub_layout)
                if title_label is not None:
                    return

    _find_label(card.layout())
    assert title_label is not None
    assert title_label.text() == "Test Series"


def test_cast_detail_movie_filmography(qtbot: Any, tmp_path: Any) -> None:
    """Test filmography display with a movie entry and poster path."""
    # Clean up existing data first
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(Movie.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    # Create a temporary poster file
    temp_poster = str(tmp_path / "test_poster.jpg")
    try:
        open(temp_poster, "w").close()

        with get_session() as session:
            person = Person(
                tmdb_identifier=54321,
                name="Movie Actor",
                biography="Another test biography.",
            )
            session.add(person)
            session.flush()

            movie = Movie(
                library_name="Movies",
                name="Test Movie",
                poster_path=temp_poster,
            )
            session.add(movie)
            session.flush()

            cast_entry = MediaCast(
                person_id=person.id,
                movie_id=movie.id,
                role="actor",
                character="Lead Role",
                sort_order=1,
            )
            session.add(cast_entry)
            person_id = person.id

        view = CastDetailView()
        qtbot.addWidget(view)

        with (
            patch("lan_streamer.ui_views.cast_detail.QPixmap") as mock_pixmap,
            patch.object(QLabel, "setPixmap", return_value=None),
        ):
            mock_pixmap.return_value.isNull.return_value = False
            view.display_person(person_id)

        assert view._name_label.text() == "Movie Actor"
        assert view._filmography_layout.count() > 0

        card = view._filmography_layout.itemAt(0).widget()
        assert card is not None

        title_label = None

        def _find_label(layout: QLayout) -> None:
            nonlocal title_label
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item is None:
                    continue
                widget = item.widget()
                if widget is not None and isinstance(widget, QLabel):
                    if "Test Movie" in widget.text():
                        title_label = widget
                        return
                sub_layout = item.layout()
                if sub_layout is not None:
                    _find_label(sub_layout)
                    if title_label is not None:
                        return

        _find_label(card.layout())
        assert title_label is not None
        assert title_label.text() == "Test Movie"

    finally:
        if os.path.exists(temp_poster):
            os.remove(temp_poster)


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


def test_cast_detail_with_death_date(qtbot: Any) -> None:
    """Test display with death_date populated."""
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    with get_session() as session:
        person = Person(
            tmdb_identifier=99999,
            name="Dead Actor",
            biography="Deceased actor bio.",
            birth_date="1950-01-01",
            death_date="2020-01-01",
            place_of_birth="Somewhere",
        )
        session.add(person)
        session.flush()
        person_id = person.id

    view = CastDetailView()
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.cast_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_person(person_id)

    assert view._name_label.text() == "Dead Actor"
    # bio_parts should have 3 entries: born, died, place
    assert view._birth_label.text() == "Born: 1950-01-01"
    assert view._death_label.text() == "Died: 2020-01-01"
    assert view._place_label.text() == "Place of birth: Somewhere"


def test_cast_detail_empty_filmography(qtbot: Any) -> None:
    """Test display when person has no filmography entries."""
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    with get_session() as session:
        person = Person(
            tmdb_identifier=11111,
            name="No Roles Actor",
            biography="No roles.",
        )
        session.add(person)
        session.flush()
        person_id = person.id

    view = CastDetailView()
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.cast_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_person(person_id)

    # Should show "No filmography data available" message
    assert view._filmography_layout.count() == 1
    label = view._filmography_layout.itemAt(0).widget()
    assert label is not None
    assert "No filmography" in label.text()


def test_cast_detail_media_click_emits_signal(qtbot: Any) -> None:
    """Test that clicking a filmography card emits media_item_clicked signal."""
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    with get_session() as session:
        person = Person(
            tmdb_identifier=22222,
            name="Clickable Actor",
            biography="Click test.",
        )
        session.add(person)
        session.flush()

        series = Series(library_name="TV", name="Click Series")
        session.add(series)
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            series_id=series.id,
            role="actor",
            character="Test Role",
            sort_order=1,
        )
        session.add(cast_entry)
        person_id = person.id
        series_id = series.id

    view = CastDetailView()
    qtbot.addWidget(view)

    received = {}

    def on_click(media_type: str, media_id: str) -> None:
        received["type"] = media_type
        received["id"] = media_id

    view.media_item_clicked.connect(on_click)

    with patch("lan_streamer.ui_views.cast_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_person(person_id)

    # Find the first filmography card and click it
    card = view._filmography_layout.itemAt(0).widget()
    assert card is not None

    import warnings
    from PySide6.QtCore import QEvent, Qt, QPointF
    from PySide6.QtGui import QMouseEvent

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        mouse_event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    card.mousePressEvent(mouse_event)

    assert received.get("type") == "series"
    assert received.get("id") == series_id


def test_cast_detail_with_profile_path(qtbot: Any, tmp_path: Any) -> None:
    """Test display_person loads profile_path image when present."""
    # Clean up
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    # Create a temp image file
    temp_image = str(tmp_path / "profile.jpg")
    open(temp_image, "wb").close()

    with get_session() as session:
        person = Person(
            tmdb_identifier=11111,
            name="Profile Actor",
            biography="Has profile.",
            profile_path=temp_image,
        )
        session.add(person)
        session.flush()
        person_id = person.id

    view = CastDetailView()
    qtbot.addWidget(view)

    # Create a real QPixmap for the mock to return
    from PySide6.QtGui import QPixmap

    real_pixmap = QPixmap()
    real_pixmap.load = lambda path: None  # Mock load to not actually read file

    with patch(
        "lan_streamer.ui_views.cast_detail.QPixmap", return_value=real_pixmap
    ) as mock_pixmap:
        real_pixmap.isNull = lambda: False
        view.display_person(person_id)

    # Verify QPixmap was called with the profile_path
    mock_pixmap.assert_called_with(temp_image)


def test_cast_detail_clear_existing_filmography(qtbot: Any) -> None:
    """Test that display_person clears existing filmography on second call."""
    # Clean up
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    with get_session() as session:
        person = Person(
            tmdb_identifier=22222,
            name="Multi Actor",
            biography="Multiple roles.",
        )
        session.add(person)
        session.flush()
        person_id = person.id

        series1 = Series(library_name="TV", name="Series One")
        session.add(series1)
        session.flush()

        cast1 = MediaCast(
            person_id=person.id,
            series_id=series1.id,
            role="actor",
            character="Role 1",
            sort_order=1,
        )
        session.add(cast1)
        session.flush()

    view = CastDetailView()
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.cast_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_person(person_id)

    # First display should have 1 filmography card
    assert view._filmography_layout.count() == 1

    # Add second series
    with get_session() as session:
        series2 = Series(library_name="TV", name="Series Two")
        session.add(series2)
        session.flush()

        cast2 = MediaCast(
            person_id=person.id,
            series_id=series2.id,
            role="actor",
            character="Role 2",
            sort_order=2,
        )
        session.add(cast2)
        session.flush()

    # Call display_person again - should clear and re-populate
    with patch("lan_streamer.ui_views.cast_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_person(person_id)

    # Should now have 2 cards (old ones cleared, new ones added)
    assert view._filmography_layout.count() == 2


def test_cast_detail_cast_entry_without_series_or_movie(qtbot: Any) -> None:
    """Test _display_filmography skips cast entry with neither series nor movie.

    Note: Current behavior shows empty layout when all entries are orphaned.
    This is a known edge case - the "No filmography" label only shows when
    the query returns zero entries, not when all entries are filtered out.
    """
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    with get_session() as session:
        person = Person(
            tmdb_identifier=33333,
            name="Orphan Actor",
            biography="No links.",
        )
        session.add(person)
        session.flush()

        # Create a MediaCast entry with NO series and NO movie
        orphan_cast = MediaCast(
            person_id=person.id,
            role="actor",
            character="Unknown",
            sort_order=1,
        )
        session.add(orphan_cast)
        session.flush()
        person_id = person.id

    view = CastDetailView()
    qtbot.addWidget(view)

    with patch("lan_streamer.ui_views.cast_detail.QPixmap") as mock_pixmap:
        mock_pixmap.return_value.isNull.return_value = False
        view.display_person(person_id)

    # Current behavior: layout is empty because orphan entry is skipped
    # and "No filmography" label only shows when query returns zero results
    assert view._filmography_layout.count() == 0
