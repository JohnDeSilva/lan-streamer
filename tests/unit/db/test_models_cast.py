"""Tests for the cast/crew database models."""

from sqlalchemy import select

from lan_streamer.db import get_session
from lan_streamer.db.models import Series, Movie
from lan_streamer.db.models_cast import Person, MediaCast, MediaImage


def test_create_person() -> None:
    """Test creating a basic Person record."""
    with get_session() as session:
        person = Person(tmdb_identifier=12345, name="Test Actor")
        session.add(person)
        session.commit()

    with get_session() as session:
        statement = select(Person).where(Person.tmdb_identifier == 12345)
        result = session.execute(statement).unique().scalar_one_or_none()
        assert result is not None
        assert result.name == "Test Actor"
        assert result.tmdb_identifier == 12345


def test_person_with_optional_fields() -> None:
    """Test creating a Person with all optional fields populated."""
    with get_session() as session:
        person = Person(
            tmdb_identifier=67890,
            name="Full Person",
            profile_path="/path/to/profile.jpg",
            biography="A biography",
            birth_date="1970-01-01",
            place_of_birth="Somewhere",
            also_known_as='["Other Name"]',
        )
        session.add(person)
        session.commit()

    with get_session() as session:
        statement = select(Person).where(Person.tmdb_identifier == 67890)
        result = session.execute(statement).unique().scalar_one_or_none()
        assert result is not None
        assert result.profile_path == "/path/to/profile.jpg"
        assert result.biography == "A biography"
        assert result.birth_date == "1970-01-01"
        assert result.place_of_birth == "Somewhere"


def test_create_media_cast_for_series() -> None:
    """Test creating a MediaCast entry linked to a series."""
    with get_session() as session:
        series = Series(name="Test Series", library_name="TV")
        person = Person(tmdb_identifier=111, name="Series Actor")
        session.add_all([series, person])
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            series_id=series.id,
            role="actor",
            character="Main Character",
            sort_order=1,
        )
        session.add(cast_entry)
        session.commit()

    with get_session() as session:
        series_statement = select(Series).where(Series.name == "Test Series")
        series = session.execute(series_statement).unique().scalar_one_or_none()
        assert series is not None

        cast_statement = (
            select(MediaCast)
            .where(MediaCast.series_id == series.id)
            .order_by(MediaCast.sort_order)
        )
        cast_result = session.execute(cast_statement).unique().scalars().all()
        assert len(cast_result) == 1
        assert cast_result[0].character == "Main Character"
        assert cast_result[0].role == "actor"


def test_create_media_cast_for_movie() -> None:
    """Test creating a MediaCast entry linked to a movie."""
    with get_session() as session:
        movie = Movie(name="Test Movie", library_name="Movies")
        person = Person(tmdb_identifier=222, name="Movie Actor")
        session.add_all([movie, person])
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            movie_id=movie.id,
            role="actor",
            character="Movie Character",
            sort_order=0,
        )
        session.add(cast_entry)
        session.commit()

    with get_session() as session:
        movie_statement = select(Movie).where(Movie.name == "Test Movie")
        movie = session.execute(movie_statement).unique().scalar_one_or_none()
        assert movie is not None

        cast_statement = (
            select(MediaCast)
            .where(MediaCast.movie_id == movie.id)
            .order_by(MediaCast.sort_order)
        )
        result = session.execute(cast_statement).unique().scalars().all()
        assert len(result) == 1
        assert result[0].character == "Movie Character"


def test_media_cast_sort_order() -> None:
    """Test that multiple cast entries are ordered by sort_order."""
    with get_session() as session:
        series = Series(name="Sort Series", library_name="TV")
        person1 = Person(tmdb_identifier=333, name="Actor One")
        person2 = Person(tmdb_identifier=444, name="Actor Two")
        person3 = Person(tmdb_identifier=555, name="Actor Three")
        session.add_all([series, person1, person2, person3])
        session.flush()

        cast1 = MediaCast(
            person_id=person1.id,
            series_id=series.id,
            role="actor",
            character="Second",
            sort_order=1,
        )
        cast2 = MediaCast(
            person_id=person2.id,
            series_id=series.id,
            role="actor",
            character="First",
            sort_order=0,
        )
        cast3 = MediaCast(
            person_id=person3.id,
            series_id=series.id,
            role="actor",
            character="Third",
            sort_order=2,
        )
        session.add_all([cast1, cast2, cast3])
        session.commit()

    with get_session() as session:
        series_statement = select(Series).where(Series.name == "Sort Series")
        series = session.execute(series_statement).unique().scalar_one_or_none()
        assert series is not None

        cast_statement = (
            select(MediaCast)
            .where(MediaCast.series_id == series.id)
            .order_by(MediaCast.sort_order)
        )
        result = session.execute(cast_statement).unique().scalars().all()
        assert len(result) == 3
        assert result[0].character == "First"
        assert result[1].character == "Second"
        assert result[2].character == "Third"


def test_cascade_delete_person() -> None:
    """Test that deleting a Person cascades to delete their MediaCast entries."""
    with get_session() as session:
        series = Series(name="Cascade Series", library_name="TV")
        person = Person(tmdb_identifier=666, name="Cascade Person")
        session.add_all([series, person])
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            series_id=series.id,
            role="actor",
        )
        session.add(cast_entry)
        session.commit()

        person_id = person.id
        cast_id = cast_entry.id

    # Delete person
    with get_session() as session:
        statement = select(Person).where(Person.id == person_id)
        person = session.execute(statement).unique().scalar_one_or_none()
        assert person is not None
        session.delete(person)
        session.commit()

    # Verify cast entry is also deleted
    with get_session() as session:
        statement = select(MediaCast).where(MediaCast.id == cast_id)
        result = session.execute(statement).unique().scalar_one_or_none()
        assert result is None


def test_create_media_image() -> None:
    """Test creating a MediaImage record linked to a series."""
    with get_session() as session:
        series = Series(name="Image Series", library_name="TV")
        session.add(series)
        session.flush()

        image = MediaImage(
            series_id=series.id,
            image_type="poster",
            source="tmdb",
            remote_url="https://example.com/poster.jpg",
            local_path="/cache/posters/poster.jpg",
            is_selected=True,
            sort_order=0,
        )
        session.add(image)
        session.commit()

    with get_session() as session:
        series_statement = select(Series).where(Series.name == "Image Series")
        series = session.execute(series_statement).unique().scalar_one_or_none()
        assert series is not None

        image_statement = (
            select(MediaImage)
            .where(MediaImage.series_id == series.id)
            .order_by(MediaImage.sort_order)
        )
        result = session.execute(image_statement).unique().scalars().all()
        assert len(result) == 1
        assert result[0].image_type == "poster"
        assert result[0].is_selected is True


def test_media_image_for_movie() -> None:
    """Test creating a MediaImage linked to a movie."""
    with get_session() as session:
        movie = Movie(name="Image Movie", library_name="Movies")
        session.add(movie)
        session.flush()

        image = MediaImage(
            movie_id=movie.id,
            image_type="backdrop",
            source="tmdb",
            remote_url="https://example.com/backdrop.jpg",
            is_selected=False,
            sort_order=0,
        )
        session.add(image)
        session.commit()

    with get_session() as session:
        movie_statement = select(Movie).where(Movie.name == "Image Movie")
        movie = session.execute(movie_statement).unique().scalar_one_or_none()
        assert movie is not None

        image_statement = (
            select(MediaImage)
            .where(MediaImage.movie_id == movie.id)
            .order_by(MediaImage.sort_order)
        )
        result = session.execute(image_statement).unique().scalars().all()
        assert len(result) == 1
        assert result[0].image_type == "backdrop"
        assert result[0].remote_url == "https://example.com/backdrop.jpg"


def test_person_tmdb_identifier_unique() -> None:
    """Test that TMDB identifier is unique across Person records."""
    with get_session() as session:
        person1 = Person(tmdb_identifier=777, name="Person One")
        session.add(person1)
        session.commit()

    with get_session() as session:
        person2 = Person(tmdb_identifier=777, name="Person Two")
        session.add(person2)
        import pytest

        with pytest.raises(Exception):
            session.commit()
        session.rollback()


def test_media_cast_person_relationship() -> None:
    """Test the relationship between MediaCast and Person."""
    with get_session() as session:
        person = Person(tmdb_identifier=888, name="Relationship Person")
        series = Series(name="Relationship Series", library_name="TV")
        session.add_all([person, series])
        session.flush()

        cast_entry = MediaCast(
            person_id=person.id,
            series_id=series.id,
            role="director",
            job="Director",
            department="Directing",
        )
        session.add(cast_entry)
        session.commit()

        # Verify the relationship works both ways
        assert cast_entry.person.name == "Relationship Person"
        assert len(person.media_cast) == 1
        assert person.media_cast[0].role == "director"


def test_media_image_multiple_types() -> None:
    """Test multiple images of different types for the same media."""
    with get_session() as session:
        series = Series(name="Multi Image Series", library_name="TV")
        session.add(series)
        session.flush()

        poster1 = MediaImage(
            series_id=series.id,
            image_type="poster",
            source="tmdb",
            remote_url="https://example.com/poster1.jpg",
            is_selected=True,
            sort_order=0,
        )
        poster2 = MediaImage(
            series_id=series.id,
            image_type="poster",
            source="tmdb",
            remote_url="https://example.com/poster2.jpg",
            is_selected=False,
            sort_order=1,
        )
        backdrop = MediaImage(
            series_id=series.id,
            image_type="backdrop",
            source="tmdb",
            remote_url="https://example.com/backdrop.jpg",
            is_selected=True,
            sort_order=0,
        )
        session.add_all([poster1, poster2, backdrop])
        session.commit()

    with get_session() as session:
        series_statement = select(Series).where(Series.name == "Multi Image Series")
        series = session.execute(series_statement).unique().scalar_one_or_none()
        assert series is not None

        all_images = (
            session.execute(
                select(MediaImage)
                .where(MediaImage.series_id == series.id)
                .order_by(MediaImage.sort_order)
            )
            .unique()
            .scalars()
            .all()
        )
        assert len(all_images) == 3

        posters = [img for img in all_images if img.image_type == "poster"]
        backdrops = [img for img in all_images if img.image_type == "backdrop"]
        assert len(posters) == 2
        assert len(backdrops) == 1
        assert posters[0].is_selected is True
        assert posters[1].is_selected is False
        assert backdrops[0].is_selected is True
