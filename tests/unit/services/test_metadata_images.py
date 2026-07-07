"""Tests for the metadata_images service layer."""

from unittest.mock import patch, MagicMock
from sqlalchemy import select

from lan_streamer.db import get_session
from lan_streamer.db.models import Series, Movie
from lan_streamer.db.models_cast import MediaImage
from lan_streamer.services.metadata_images import (
    fetch_and_store_series_images,
    fetch_and_store_movie_images,
)


class TestMetadataImagesService:
    """Test suite for fetching and storing images in metadata_images."""

    @patch("lan_streamer.services.metadata_images.tmdb_client")
    def test_fetch_and_store_series_images(self, mock_tmdb: MagicMock) -> None:
        """Test fetching series images from TMDB and persisting to database."""
        # Arrange
        with get_session() as session:
            series = Series(
                name="Image TV Show", library_name="TV", tmdb_identifier="12345"
            )
            session.add(series)
            session.commit()
            series_id = series.id

        mock_tmdb.get_series_images.return_value = {
            "posters": [
                {
                    "file_path": "/poster1.jpg",
                    "width": 500,
                    "height": 750,
                }
            ],
            "backdrops": [
                {
                    "file_path": "/backdrop1.jpg",
                    "width": 1920,
                    "height": 1080,
                }
            ],
            "logos": [],
        }
        mock_tmdb.download_and_cache_image.side_effect = lambda path, size: (
            f"/cached{path}"
        )

        # Act
        fetch_and_store_series_images(series_id, 12345)

        # Assert
        with get_session() as session:
            images = session.scalars(
                select(MediaImage)
                .where(MediaImage.series_id == series_id)
                .order_by(MediaImage.image_type)
            ).all()
            assert len(images) == 2

            backdrops = [img for img in images if img.image_type == "backdrop"]
            posters = [img for img in images if img.image_type == "poster"]

            assert len(backdrops) == 1
            assert (
                backdrops[0].remote_url
                == "https:/" + "/image.tmdb.org/t/p/original/backdrop1.jpg"
            )
            assert backdrops[0].local_path == "/cached/backdrop1.jpg"

            assert len(posters) == 1
            assert (
                posters[0].remote_url
                == "https:/" + "/image.tmdb.org/t/p/original/poster1.jpg"
            )

    @patch("lan_streamer.services.metadata_images.tmdb_client")
    def test_fetch_and_store_movie_images(self, mock_tmdb: MagicMock) -> None:
        """Test fetching movie images from TMDB and persisting to database."""
        # Arrange
        with get_session() as session:
            movie = Movie(
                name="Image Movie", library_name="Movies", tmdb_identifier="54321"
            )
            session.add(movie)
            session.commit()
            movie_id = movie.id

        mock_tmdb.get_movie_images.return_value = {
            "posters": [
                {
                    "file_path": "/poster2.jpg",
                    "width": 500,
                    "height": 750,
                }
            ],
            "backdrops": [],
            "logos": [],
        }
        mock_tmdb.download_and_cache_image.side_effect = lambda path, size: (
            f"/cached{path}"
        )

        # Act
        fetch_and_store_movie_images(movie_id, 54321)

        # Assert
        with get_session() as session:
            images = session.scalars(
                select(MediaImage).where(MediaImage.movie_id == movie_id)
            ).all()
            assert len(images) == 1
            assert images[0].image_type == "poster"
            assert (
                images[0].remote_url
                == "https:/" + "/image.tmdb.org/t/p/original/poster2.jpg"
            )
            assert images[0].local_path == "/cached/poster2.jpg"

    def test_lookup_series_id_not_found(self) -> None:
        from lan_streamer.services.metadata_images import _lookup_series_id

        assert _lookup_series_id("nonexistent_tmdb_id") is None

    def test_lookup_movie_id_not_found(self) -> None:
        from lan_streamer.services.metadata_images import _lookup_movie_id

        assert _lookup_movie_id("nonexistent_tmdb_id") is None

    @patch("lan_streamer.services.metadata_images.tmdb_client")
    def test_fetch_and_store_series_images_no_data(self, mock_tmdb: MagicMock) -> None:
        mock_tmdb.get_series_images.return_value = None
        fetch_and_store_series_images("some_id", 123)

    @patch("lan_streamer.services.metadata_images.tmdb_client")
    def test_fetch_and_store_movie_images_no_data(self, mock_tmdb: MagicMock) -> None:
        mock_tmdb.get_movie_images.return_value = None
        fetch_and_store_movie_images("some_id", 123)

    @patch("lan_streamer.services.metadata_images.tmdb_client")
    def test_store_images_from_tmdb_empty_file_path(self, mock_tmdb: MagicMock) -> None:
        with get_session() as session:
            series = Series(
                name="Empty Path Show", library_name="TV", tmdb_identifier="999"
            )
            session.add(series)
            session.commit()
            series_id = series.id

        mock_tmdb.get_series_images.return_value = {
            "posters": [{"file_path": ""}],
            "backdrops": [],
            "logos": [],
        }
        fetch_and_store_series_images(series_id, 999)
        with get_session() as session:
            images = session.scalars(
                select(MediaImage).where(MediaImage.series_id == series_id)
            ).all()
            assert len(images) == 0
