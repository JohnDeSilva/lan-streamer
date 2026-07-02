from unittest.mock import patch
from typing import Any
from sqlalchemy import text
from lan_streamer.ui_views import MovieDetailView, Controller
from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Movie, Series, Season, Episode
from lan_streamer.db.models_cast import Person, MediaCast


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
