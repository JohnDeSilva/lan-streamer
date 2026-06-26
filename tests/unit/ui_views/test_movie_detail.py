from unittest.mock import patch
from typing import Any
from lan_streamer.ui_views import MovieDetailView, Controller


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
