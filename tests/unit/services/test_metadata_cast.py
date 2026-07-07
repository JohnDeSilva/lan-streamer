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

    def test_lookup_series_id_not_found(self) -> None:
        from lan_streamer.services.metadata_cast import _lookup_series_id

        assert _lookup_series_id("nonexistent_tmdb_id") is None

    def test_lookup_movie_id_not_found(self) -> None:
        from lan_streamer.services.metadata_cast import _lookup_movie_id

        assert _lookup_movie_id("nonexistent_tmdb_id") is None

    def test_map_tmdb_role_variations(self) -> None:
        from lan_streamer.services.metadata_cast import _map_tmdb_role

        assert _map_tmdb_role("Actor", "Acting") == "actor"
        assert _map_tmdb_role("Director", "Directing") == "director"
        assert _map_tmdb_role("Screenplay", "Writing") == "writer"
        assert _map_tmdb_role("Executive Producer", "Production") == "producer"
        assert _map_tmdb_role("Key Grip", "Camera") == "key grip"

    @patch("lan_streamer.services.metadata_cast.tmdb_client")
    def test_fetch_and_store_series_credits_no_data(self, mock_tmdb: MagicMock) -> None:
        mock_tmdb.get_series_credits.return_value = None
        fetch_and_store_series_credits("00000000-0000-0000-0000-000000000000", 123)

    @patch("lan_streamer.services.metadata_cast.tmdb_client")
    def test_fetch_and_store_movie_credits_no_data(self, mock_tmdb: MagicMock) -> None:
        mock_tmdb.get_movie_credits.return_value = None
        fetch_and_store_movie_credits("00000000-0000-0000-0000-000000000000", 123)

    @patch("lan_streamer.services.metadata_cast.tmdb_client")
    def test_fetch_and_store_episode_credits_no_data(
        self, mock_tmdb: MagicMock
    ) -> None:
        mock_tmdb.get_episode_credits.return_value = None
        fetch_and_store_episode_credits(
            "00000000-0000-0000-0000-000000000000", 123, 1, 1
        )

    @patch("lan_streamer.services.metadata_cast.tmdb_client")
    def test_fetch_and_store_credits_missing_ids_and_duplicates(
        self, mock_tmdb: MagicMock
    ) -> None:
        with get_session() as session:
            series = Series(name="Dup Show", library_name="TV", tmdb_identifier="8888")
            session.add(series)
            session.commit()
            series_id = series.id

        mock_tmdb.get_series_credits.return_value = {
            "cast": [
                {"id": None, "name": "No ID Actor"},  # Should be skipped
                {
                    "id": 9991,
                    "name": "Dup Actor",
                    "character": "Main",
                    "credit_id": "c1",
                },
                {
                    "id": 9991,
                    "name": "Dup Actor",
                    "character": "Main",
                    "credit_id": "c1",
                },  # Duplicate, should be filtered
            ],
            "crew": [
                {"id": None, "job": "No ID Crew"},  # Should be skipped
                {
                    "id": 9992,
                    "name": "Dup Crew",
                    "job": "Director",
                    "department": "Directing",
                    "credit_id": "c2",
                },
                {
                    "id": 9992,
                    "name": "Dup Crew",
                    "job": "Director",
                    "department": "Directing",
                    "credit_id": "c2",
                },  # Duplicate, should be filtered
            ],
        }
        fetch_and_store_series_credits(series_id, 8888)
        with get_session() as session:
            credits_list = session.scalars(
                select(MediaCast).where(MediaCast.series_id == series_id)
            ).all()
            assert len(credits_list) == 2
