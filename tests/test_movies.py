from unittest.mock import MagicMock, patch
from pathlib import Path
from typing import Any

from lan_streamer.scanner import _parse_movie_folder, scan_movie
from lan_streamer import db
from lan_streamer.ui_views import MovieDetailView, Controller


def test_parse_movie_folder() -> None:
    assert _parse_movie_folder("Avatar (2009)") == ("Avatar", 2009)
    assert _parse_movie_folder("The Godfather (1972)") == ("The Godfather", 1972)
    assert _parse_movie_folder("No Year Movie") == ("No Year Movie", None)


def test_scan_movie_no_video(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Empty Movie (2020)"
    movie_dir.mkdir()
    # No video files inside
    assert scan_movie(movie_dir) is None


def test_scan_movie_success(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Avatar (2009)"
    movie_dir.mkdir()
    video_file = movie_dir / "Avatar.mkv"
    video_file.touch()

    mock_tmdb = MagicMock()
    mock_tmdb.search_movie.return_value = {
        "id": 19995,
        "title": "Avatar",
        "overview": "On the lush alien world of Pandora...",
        "poster_path": "/avatar.jpg",
        "release_date": "2009-12-15",
        "runtime": 162,
        "vote_average": 7.9,
        "genres": [{"name": "Action"}, {"name": "Adventure"}],
    }
    mock_tmdb.download_image.return_value = "/cached/avatar.jpg"

    with patch("lan_streamer.scanner.tmdb_client", mock_tmdb):
        res = scan_movie(movie_dir)

    assert res is not None
    assert res["name"] == "Avatar (2009)"
    assert res["path"] == str(video_file.absolute())
    assert res["tmdb_identifier"] == "19995"
    assert res["tmdb_name"] == "Avatar"
    assert res["overview"] == "On the lush alien world of Pandora..."
    assert res["poster_path"] == "/cached/avatar.jpg"
    assert res["runtime"] == 162
    assert res["rating"] == "7.9"
    assert res["genre"] == "Action, Adventure"
    assert res["year"] == 2009
    assert res["watched"] is False


def test_scan_movie_reuse_existing(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Pulp Fiction (1994)"
    movie_dir.mkdir()
    video_file = movie_dir / "Pulp Fiction.mkv"
    video_file.touch()

    existing_data = {
        "tmdb_identifier": "680",
        "tmdb_name": "Pulp Fiction",
        "overview": "A burger-loving hit man...",
        "poster_path": "/pulp.jpg",
        "runtime": 154,
        "rating": "8.5",
        "genre": "Crime",
        "year": 1994,
        "watched": True,
        "last_played_position": 500,
        "locked_metadata": True,
    }

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
        res = scan_movie(
            movie_dir, existing_movie_data=existing_data, force_refresh=False
        )

        assert res is not None
        assert res["tmdb_identifier"] == "680"
        assert res["tmdb_name"] == "Pulp Fiction"
        assert res["watched"] is True
        assert res["last_played_position"] == 500
        assert res["locked_metadata"] is True
        mock_tmdb.search_movie.assert_not_called()


def test_scan_movie_jellyfin_correlation(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Correlated Movie (2021)"
    movie_dir.mkdir()
    video_file = movie_dir / "Movie.mp4"
    video_file.touch()

    jellyfin_data = {"path_map": {str(video_file.absolute()): {"id": "jf_movie_123"}}}

    mock_tmdb = MagicMock()
    mock_tmdb.search_movie.return_value = {"id": 101, "title": "Correlated Movie"}

    with patch("lan_streamer.scanner.tmdb_client", mock_tmdb):
        res = scan_movie(movie_dir, jellyfin_data=jellyfin_data)

    assert res is not None
    assert res["jellyfin_id"] == "jf_movie_123"


def test_db_movie_operations() -> None:
    library_name = "Cinematic Movies"
    movie_data = {
        "The Godfather (1972)": {
            "name": "The Godfather (1972)",
            "path": "/movies/Godfather/video.mkv",
            "jellyfin_id": "jf_godfather",
            "tmdb_identifier": "238",
            "poster_path": "/posters/godfather.jpg",
            "overview": "Spanning the years 1945 to 1955...",
            "tmdb_name": "The Godfather",
            "locked_metadata": False,
            "date_added": 12345,
            "runtime": 175,
            "rating": "8.7",
            "genre": "Crime, Drama",
            "year": 1972,
            "watched": False,
            "last_played_position": 0,
        }
    }

    # Save library
    db.save_movie_library(library_name, movie_data)

    # Load library
    loaded = db.load_movie_library(library_name)
    assert "The Godfather (1972)" in loaded
    item = loaded["The Godfather (1972)"]
    assert item["tmdb_name"] == "The Godfather"
    assert item["runtime"] == 175
    assert item["watched"] is False

    # Test playback update fallback to Movie
    target_path = "/movies/Godfather/video.mkv"
    db.update_episode_watched_status(target_path, True)

    assert db.update_episode_playback_position(target_path, 1200) is True
    assert db.get_episode_playback_position(target_path) == 1200

    # Reload library to verify persistent update
    reloaded = db.load_movie_library(library_name)
    assert reloaded["The Godfather (1972)"]["watched"] is True
    assert reloaded["The Godfather (1972)"]["last_played_position"] == 1200


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
        patch("lan_streamer.ui_views.Path.is_file", return_value=True),
        patch("lan_streamer.ui_views.QPixmap") as mock_pixmap,
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

    # Test No Poster branch
    view.populate_movie_details("Non Existent Movie")
    assert view.poster_label.text() == "No Poster"


def test_db_movie_exceptions() -> None:
    with patch("lan_streamer.db.get_session", side_effect=Exception("DB Fault")):
        assert db.load_movie_library("Cinematic Movies") == {}
        db.save_movie_library("Cinematic Movies", {"m": {}})


def test_db_movie_save_path_upsert() -> None:
    library_name: str = "Cinematic Movies"
    target_path: str = "/movies/Unique/video_remux.mkv"
    initial_data: dict[str, Any] = {
        "Unique Movie": {
            "name": "Unique Movie",
            "path": target_path,
            "tmdb_name": "Unique Movie",
        }
    }
    db.save_movie_library(library_name, initial_data)

    # Now simulate renaming the folder to include year
    updated_data: dict[str, Any] = {
        "Unique Movie (2026)": {
            "name": "Unique Movie (2026)",
            "path": target_path,
            "tmdb_name": "Unique Movie",
        }
    }
    db.save_movie_library(library_name, updated_data)

    loaded: dict[str, Any] = db.load_movie_library(library_name)
    assert "Unique Movie (2026)" in loaded
    assert loaded["Unique Movie (2026)"]["path"] == target_path


def test_db_movie_save_stale_name_collision() -> None:
    library_name: str = "Cinematic Movies"
    # Setup two distinct movies
    db.save_movie_library(
        library_name,
        {
            "Movie OldName": {"name": "Movie OldName", "path": "/path/target.mkv"},
            "Movie TargetName": {
                "name": "Movie TargetName",
                "path": "/path/other.mkv",
            },
        },
    )

    # 1. Verify path update on existing name (hits line 385)
    db.save_movie_library(
        library_name,
        {
            "Movie TargetName": {
                "name": "Movie TargetName",
                "path": "/path/new_other.mkv",
            }
        },
    )
    loaded: dict[str, Any] = db.load_movie_library(library_name)
    assert loaded["Movie TargetName"]["path"] == "/path/new_other.mkv"

    # 2. Verify stale record deletion on name collision during path upsert (hits lines 394-398)
    # Re-seed to have both old and target names present
    db.save_movie_library(
        library_name,
        {
            "Movie OldName": {"name": "Movie OldName", "path": "/path/target.mkv"},
            "Movie TargetName": {
                "name": "Movie TargetName",
                "path": "/path/stale.mkv",
            },
        },
    )

    # Now incoming data maps the target path to the target name
    db.save_movie_library(
        library_name,
        {
            "Movie TargetName": {
                "name": "Movie TargetName",
                "path": "/path/target.mkv",
            }
        },
    )
    reloaded: dict[str, Any] = db.load_movie_library(library_name)
    assert "Movie TargetName" in reloaded
    assert reloaded["Movie TargetName"]["path"] == "/path/target.mkv"
    assert "Movie OldName" not in reloaded


def test_movie_scanner_flat_dict_integration() -> None:
    from lan_streamer.scanner import scan_directories
    from lan_streamer.config import config

    config.libraries["TestMovieLibrary"] = {"type": "movie", "paths": []}

    # Simulate flat structure generated by scan_movie
    simulated_library: dict[str, Any] = {
        "Inception (2010)": {
            "name": "Inception (2010)",
            "path": "/movies/Inception/Inception.mkv",
            "jellyfin_id": "jf_inc",
            "tmdb_identifier": "27205",
            "poster_path": "/posters/inc.jpg",
            "overview": "A thief who steals corporate secrets...",
            "tmdb_name": "Inception",
            "locked_metadata": True,
            "date_added": 123456,
            "runtime": 148,
            "rating": "8.8",
            "genre": "Action, Sci-Fi",
            "year": 2010,
            "watched": True,
            "last_played_position": 0,
        }
    }

    # Test that scan_directories correctly merges/preserves flat dict entries for movie libraries
    # without expecting 'metadata' or 'seasons' dictionaries.
    res: dict[str, Any] = scan_directories(
        root_directories=[],
        library_type="movie",
        existing_library=simulated_library,
        force_refresh=False,
    )

    assert "Inception (2010)" in res
    assert res["Inception (2010)"]["locked_metadata"] is True
    assert "seasons" not in res["Inception (2010)"]

    # Verify Controller caching metrics for flat movie library dictionaries
    controller = Controller()
    controller.current_library_name = "TestMovieLibrary"
    controller.cached_library_data = res
    controller._cache_series_metrics()

    metrics: dict[str, Any] = res["Inception (2010)"]["metrics"]
    assert metrics["total_episodes"] == 1
    assert metrics["watched_episodes"] == 1
    assert metrics["max_air_date"] == "2010"

    # Verify signal routing when marking watched
    emitted_movies: list[str] = []
    controller.movie_selected.connect(emitted_movies.append)
    controller.selected_series_name = "Inception (2010)"

    with patch("lan_streamer.db.update_episode_watched_status"):
        controller.mark_episode_watched("/movies/Inception/Inception.mkv", False)

    assert emitted_movies == ["Inception (2010)"]
    assert res["Inception (2010)"]["watched"] is False


def test_scan_movie_uses_cached_image(tmp_path: Path) -> None:
    """Verify that scan_movie prioritizes cached movie posters."""
    from lan_streamer.scanner import scan_movie

    movie_dir = tmp_path / "Cached Movie (2026)"
    movie_dir.mkdir()
    (movie_dir / "video.mkv").touch()

    mock_tmdb = MagicMock()
    mock_tmdb.search_movie.return_value = {
        "id": 999,
        "title": "Cached Movie",
        "poster_path": "/remote_movie.jpg",
    }
    mock_tmdb.get_cached_image.return_value = "/local_cache/movie.jpg"
    mock_tmdb.download_image.return_value = ""

    with patch("lan_streamer.scanner.tmdb_client", mock_tmdb):
        res = scan_movie(movie_dir)

    assert res["poster_path"] == "/local_cache/movie.jpg"
    mock_tmdb.download_image.assert_not_called()
