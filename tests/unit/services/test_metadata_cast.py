"""Tests for the metadata_cast service layer."""

from unittest.mock import patch, MagicMock
from sqlalchemy import select

from lan_streamer.db import get_session
from lan_streamer.db.models import Series, Movie, Episode
from lan_streamer.db.models_cast import Person, MediaCast
from lan_streamer.services.metadata_cast import (
    fetch_and_store_series_credits,
    fetch_and_store_movie_credits,
    fetch_and_store_episode_credits,
)


class TestMetadataCastService:
    """Test suite for fetching and storing credits in metadata_cast."""

    @patch("lan_streamer.services.metadata_cast.tmdb_client")
    def test_fetch_and_store_series_credits(self, mock_tmdb: MagicMock) -> None:
        """Test fetching series credits from TMDB and persisting to database."""
        # Arrange
        with get_session() as session:
            series = Series(
                name="Cast TV Show", library_name="TV", tmdb_identifier="12345"
            )
            session.add(series)
            session.commit()
            series_id = series.id

        mock_tmdb.get_series_credits.return_value = {
            "cast": [
                {
                    "id": 9901,
                    "name": "Actor One",
                    "profile_path": "/profile1.jpg",
                    "character": "Protagonist",
                    "credit_id": "cr_001",
                    "order": 0,
                }
            ],
            "crew": [
                {
                    "id": 9902,
                    "name": "Director One",
                    "profile_path": "/profile2.jpg",
                    "job": "Director",
                    "department": "Directing",
                    "credit_id": "cr_002",
                }
            ],
        }
        mock_tmdb.download_and_cache_profile.side_effect = lambda path, person_id: (
            f"/cached{path}"
        )

        # Act
        fetch_and_store_series_credits(series_id, 12345)

        # Assert
        with get_session() as session:
            # Check Person records created
            person1 = session.scalars(
                select(Person).where(Person.tmdb_identifier == 9901)
            ).first()
            assert person1 is not None
            assert person1.name == "Actor One"
            assert person1.profile_path == "/cached/profile1.jpg"

            person2 = session.scalars(
                select(Person).where(Person.tmdb_identifier == 9902)
            ).first()
            assert person2 is not None
            assert person2.name == "Director One"

            # Check MediaCast records created
            credits_list = session.scalars(
                select(MediaCast)
                .where(MediaCast.series_id == series_id)
                .order_by(MediaCast.sort_order)
            ).all()
            assert len(credits_list) == 2
            assert credits_list[0].role == "actor"
            assert credits_list[0].character == "Protagonist"
            assert credits_list[0].person_id == person1.id
            assert credits_list[1].role == "director"
            assert credits_list[1].person_id == person2.id

    @patch("lan_streamer.services.metadata_cast.tmdb_client")
    def test_fetch_and_store_movie_credits(self, mock_tmdb: MagicMock) -> None:
        """Test fetching movie credits from TMDB and persisting to database."""
        # Arrange
        with get_session() as session:
            movie = Movie(
                name="Cast Movie", library_name="Movies", tmdb_identifier="54321"
            )
            session.add(movie)
            session.commit()
            movie_id = movie.id

        mock_tmdb.get_movie_credits.return_value = {
            "cast": [
                {
                    "id": 9903,
                    "name": "Movie Star",
                    "profile_path": None,
                    "character": "Hero",
                    "credit_id": "cr_003",
                    "order": 1,
                }
            ],
            "crew": [],
        }

        # Act
        fetch_and_store_movie_credits(movie_id, 54321)

        # Assert
        with get_session() as session:
            person = session.scalars(
                select(Person).where(Person.tmdb_identifier == 9903)
            ).first()
            assert person is not None
            assert person.name == "Movie Star"
            assert person.profile_path is None

            credits_list = session.scalars(
                select(MediaCast).where(MediaCast.movie_id == movie_id)
            ).all()
            assert len(credits_list) == 1
            assert credits_list[0].role == "actor"
            assert credits_list[0].character == "Hero"

    @patch("lan_streamer.services.metadata_cast.tmdb_client")
    def test_fetch_and_store_episode_credits(self, mock_tmdb: MagicMock) -> None:
        """Test fetching episode credits from TMDB and persisting to database."""
        # Arrange
        with get_session() as session:
            episode = Episode(name="Episode One", default_path="/path/to/ep.mp4")
            session.add(episode)
            session.commit()
            episode_id = episode.id

        mock_tmdb.get_episode_credits.return_value = {
            "cast": [
                {
                    "id": 9904,
                    "name": "Guest Star",
                    "profile_path": "",
                    "character": "Guest",
                    "credit_id": "cr_004",
                    "order": 5,
                }
            ],
            "crew": [],
        }

        # Act
        fetch_and_store_episode_credits(episode_id, 12345, 1, 1)

        # Assert
        with get_session() as session:
            credits_list = session.scalars(
                select(MediaCast).where(MediaCast.episode_id == episode_id)
            ).all()
            assert len(credits_list) == 1
            assert credits_list[0].role == "actor"
            assert credits_list[0].character == "Guest"
