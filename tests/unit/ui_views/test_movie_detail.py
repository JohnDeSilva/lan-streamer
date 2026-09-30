from typing import Any
from unittest.mock import patch

from sqlalchemy import text

from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Episode, Movie, MovieLibrary, Season, Series
from lan_streamer.db.models_cast import MediaCast, Person
from lan_streamer.ui_views import Controller, MovieDetailView


def test_movie_detail_view(qtbot: Any) -> None:
    controller = Controller()
    controller.cached_library_data = {
        "Avatar (2009)": {
            "name": "Avatar (2009)",
            "path": "/movies/Avatar/video.mkv",
            "tmdb_name": "Avatar",
            "year": 2009,
            "runtime": 162,
            "rating": "7.9",
            "genre": "Action, Adventure",
            "overview": "Pandora space doc.",
            "poster_path": "/path/to/poster.jpg",
        }
    }

    view = MovieDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.movie_detail.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.movie_detail.QPixmap") as mock_pixmap,
        patch.object(view.poster_label, "setPixmap") as mock_set_pixmap,
    ):
        mock_pixmap.return_value.isNull.return_value = False
        view.populate_movie_details("Avatar (2009)")
        mock_set_pixmap.assert_called_once()

    assert view.title_label.text() == "Avatar"
    assert view.metadata_label.text() == "2009 • 162 min • ★ 7.9 • Action, Adventure"
    assert view.overview_label.text() == "Pandora space doc."

    # Test playback requested signal emission
    emitted_paths = []
    controller.playback_requested.connect(emitted_paths.append)

    view.play_button.click()
    assert emitted_paths == ["/movies/Avatar/video.mkv"]

    # Test trailers button click
    with patch("webbrowser.open") as mock_open:
        view.trailers_button.click()
        opened_url = mock_open.call_args.args[0]
        assert "search_query=Avatar%20trailer" in opened_url
        assert opened_url.startswith("https://")

    # Test No Poster branch
    view.populate_movie_details("Non Existent Movie")
    assert view.poster_label.text() == "No Poster"


def test_movie_detail_cast_section(qtbot: Any) -> None:
    """Test that movie detail view displays cast members."""
    controller = Controller()
    controller.current_library_name = "Movies"
    controller.cached_library_data = {
        "Test Movie": {
            "name": "Test Movie",
            "path": "/movies/Test Movie/video.mkv",
            "tmdb_name": "Test Movie",
            "year": 2020,
            "overview": "A test movie.",
            "poster_path": "/path/to/poster.jpg",
        }
    }

    # Setup database
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Movie.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    with get_session() as session:
        movie = Movie(library_name="Movies", name="Test Movie")
        session.add(movie)
        session.flush()

        person = Person(tmdb_identifier=12345, name="Test Actor")
        session.add(person)
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            movie_id=movie.id,
            role="actor",
            character="Main Character",
            sort_order=1,
        )
        session.add(cast_entry)
        session.commit()

    view = MovieDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.movie_detail.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.movie_detail.QPixmap") as mock_pixmap,
        patch.object(view.poster_label, "setPixmap"),
    ):
        mock_pixmap.return_value.isNull.return_value = False
        view.populate_movie_details("Test Movie")

    # Check that cast grid is populated
    assert view._cast_grid.count() > 0


def test_movie_detail_cast_via_junction_library(qtbot: Any) -> None:
    controller = Controller()
    controller.current_library_name = "Secondary Movies"
    controller.cached_library_data = {
        "Shared Movie": {
            "name": "Shared Movie",
            "path": "/movies/Shared Movie/video.mkv",
            "tmdb_name": "Shared Movie",
            "year": 2021,
            "overview": "A shared test movie.",
            "poster_path": "/path/to/poster.jpg",
        }
    }

    # Setup database
    with get_session() as cleanup_session:
        cleanup_session.execute(text("PRAGMA foreign_keys = OFF"))
        cleanup_session.execute(MediaCast.__table__.delete())
        cleanup_session.execute(Person.__table__.delete())
        cleanup_session.execute(MovieLibrary.__table__.delete())
        cleanup_session.execute(Episode.__table__.delete())
        cleanup_session.execute(Season.__table__.delete())
        cleanup_session.execute(Movie.__table__.delete())
        cleanup_session.execute(Series.__table__.delete())
        cleanup_session.execute(text("PRAGMA foreign_keys = ON"))

    with get_session() as session:
        movie = Movie(library_name="Primary Movies", name="Shared Movie")
        session.add(movie)
        session.flush()

        junction_link = MovieLibrary(movie_id=movie.id, library_name="Secondary Movies")
        session.add(junction_link)

        person = Person(tmdb_identifier=65432, name="Junction Movie Actor")
        session.add(person)
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            movie_id=movie.id,
            role="actor",
            character="Lead Role",
            sort_order=1,
        )
        session.add(cast_entry)
        session.commit()

    view = MovieDetailView(controller)
    qtbot.addWidget(view)

    with (
        patch("lan_streamer.ui_views.movie_detail.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.movie_detail.QPixmap") as mock_pixmap,
        patch.object(view.poster_label, "setPixmap"),
    ):
        mock_pixmap.return_value.isNull.return_value = False
        view.populate_movie_details("Shared Movie")

    assert view._cast_grid.count() > 0
    assert view._lookup_movie_id() == movie.id
