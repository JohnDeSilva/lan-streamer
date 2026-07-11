"""Tests for the cast/crew database query functions."""

from sqlalchemy import select

from lan_streamer.db import get_session
from lan_streamer.db.models import Series, Movie, Season, Episode
from lan_streamer.db.models_cast import Person, MediaCast, MediaImage
from lan_streamer.db.queries_cast import (
    get_cast_for_series,
    get_cast_for_season,
    get_cast_for_episode,
    get_cast_for_movie,
    get_person_by_id,
    get_person_by_tmdb_id,
    get_or_create_person,
    get_filmography,
    delete_cast_for_media,
    get_images_for_media,
    set_selected_image,
    add_media_image,
)


class TestCastQueries:
    """Test suite for cast-related query functions."""

    def test_get_cast_for_series_empty(self) -> None:
        """Test that getting cast for a series with no cast returns empty list."""
        with get_session() as session:
            series = Series(name="Empty Cast Series", library_name="TV")
            session.add(series)
            session.commit()
            series_id = series.id

        result = get_cast_for_series(series_id)
        assert result == []

    def test_get_cast_for_series_with_data(self) -> None:
        """Test getting all cast entries for a series."""
        with get_session() as session:
            series = Series(name="Cast Series", library_name="TV")
            actor = Person(tmdb_identifier=1001, name="Actor One")
            director = Person(tmdb_identifier=1002, name="Director One")
            session.add_all([series, actor, director])
            session.flush()

            cast1 = MediaCast(
                person_id=actor.id,
                series_id=series.id,
                role="actor",
                character="Hero",
                sort_order=0,
            )
            cast2 = MediaCast(
                person_id=director.id,
                series_id=series.id,
                role="director",
                sort_order=1,
            )
            session.add_all([cast1, cast2])
            session.commit()
            series_id = series.id

        result = get_cast_for_series(series_id)
        assert len(result) == 2
        assert result[0].character == "Hero"
        assert result[0].person.name == "Actor One"
        assert result[1].role == "director"
        assert result[1].person.name == "Director One"

    def test_get_cast_for_season_empty(self) -> None:
        """Test getting cast for a season with no cast returns empty list."""
        with get_session() as session:
            series = Series(name="Season Cast Series", library_name="TV")
            season = Season(series_id=series.id, name="Season 1")
            session.add_all([series, season])
            session.commit()
            season_id = season.id

        result = get_cast_for_season(season_id)
        assert result == []

    def test_get_cast_for_season_with_data(self) -> None:
        """Test getting cast for a season."""
        with get_session() as session:
            series = Series(name="Season Cast Series", library_name="TV")
            season = Season(series_id=series.id, name="Season 1")
            actor = Person(tmdb_identifier=3001, name="Season Actor")
            session.add_all([series, season, actor])
            session.flush()

            cast_entry = MediaCast(
                person_id=actor.id,
                series_id=series.id,
                season_id=season.id,
                role="actor",
                character="Season Regular",
                sort_order=0,
            )
            session.add(cast_entry)
            session.commit()
            season_id = season.id

        result = get_cast_for_season(season_id)
        assert len(result) == 1
        assert result[0].character == "Season Regular"
        assert result[0].person.name == "Season Actor"

    def test_get_cast_for_episode_empty(self) -> None:
        """Test that getting cast for an episode with no cast returns empty list."""
        with get_session() as session:
            series = Series(name="Ep Cast Series", library_name="TV")
            season = Season(series_id=series.id, name="Season 1")
            episode = Episode(season_id=season.id, name="Ep 1", tmdb_number=1)
            session.add_all([series, season, episode])
            session.commit()
            episode_id = episode.id

        result = get_cast_for_episode(episode_id)
        assert result == []

    def test_get_cast_for_episode_with_data(self) -> None:
        """Test getting cast for an episode."""
        with get_session() as session:
            series = Series(name="Ep Cast Series", library_name="TV")
            season = Season(series_id=series.id, name="Season 1")
            episode = Episode(season_id=season.id, name="Ep 1", tmdb_number=1)
            actor = Person(tmdb_identifier=4001, name="Episode Actor")
            session.add_all([series, season, episode, actor])
            session.flush()

            cast_entry = MediaCast(
                person_id=actor.id,
                series_id=series.id,
                season_id=season.id,
                episode_id=episode.id,
                role="actor",
                character="Guest Star",
                sort_order=0,
            )
            session.add(cast_entry)
            session.commit()
            episode_id = episode.id

        result = get_cast_for_episode(episode_id)
        assert len(result) == 1
        assert result[0].character == "Guest Star"
        assert result[0].person.name == "Episode Actor"

    def test_get_cast_for_movie_empty(self) -> None:
        """Test that getting cast for a movie with no cast returns empty list."""
        with get_session() as session:
            movie = Movie(name="Empty Cast Movie", library_name="Movies")
            session.add(movie)
            session.commit()
            movie_id = movie.id

        result = get_cast_for_movie(movie_id)
        assert result == []

    def test_get_cast_for_movie_with_data(self) -> None:
        """Test getting all cast entries for a movie."""
        with get_session() as session:
            movie = Movie(name="Cast Movie", library_name="Movies")
            actor = Person(tmdb_identifier=2001, name="Movie Actor")
            session.add_all([movie, actor])
            session.flush()

            cast_entry = MediaCast(
                person_id=actor.id,
                movie_id=movie.id,
                role="actor",
                character="Lead",
                sort_order=0,
            )
            session.add(cast_entry)
            session.commit()
            movie_id = movie.id

        result = get_cast_for_movie(movie_id)
        assert len(result) == 1
        assert result[0].character == "Lead"
        assert result[0].person.name == "Movie Actor"


class TestPersonQueries:
    """Test suite for person-related query functions."""

    def test_get_person_by_id_found(self) -> None:
        """Test finding a person by their ID."""
        with get_session() as session:
            person = Person(tmdb_identifier=3001, name="Find Me")
            session.add(person)
            session.commit()
            person_id = person.id

        result = get_person_by_id(person_id)
        assert result is not None
        assert result.name == "Find Me"
        assert result.tmdb_identifier == 3001

    def test_get_person_by_id_not_found(self) -> None:
        """Test that looking up a non-existent person ID returns None."""
        result = get_person_by_id("00000000-0000-0000-0000-000000000000")
        assert result is None

    def test_get_person_by_tmdb_id_found(self) -> None:
        """Test finding a person by their TMDB identifier."""
        with get_session() as session:
            person = Person(tmdb_identifier=4001, name="TMDB Person")
            session.add(person)
            session.commit()

        result = get_person_by_tmdb_id(4001)
        assert result is not None
        assert result.name == "TMDB Person"

    def test_get_person_by_tmdb_id_not_found(self) -> None:
        """Test that looking up a non-existent TMDB ID returns None."""
        result = get_person_by_tmdb_id(999999)
        assert result is None

    def test_get_or_create_person_creates_new(self) -> None:
        """Test that get_or_create_person creates a new person when not found."""
        person = get_or_create_person(
            tmdb_identifier=5001,
            name="New Person",
            profile_path="/profiles/new.jpg",
        )
        assert person is not None
        assert person.name == "New Person"
        assert person.tmdb_identifier == 5001
        assert person.profile_path == "/profiles/new.jpg"

        # Verify it's persisted
        retrieved = get_person_by_tmdb_id(5001)
        assert retrieved is not None
        assert retrieved.id == person.id

    def test_get_or_create_person_returns_existing(self) -> None:
        """Test that get_or_create_person returns existing person."""
        with get_session() as session:
            person = Person(
                tmdb_identifier=6001,
                name="Existing Person",
                profile_path="/old/path.jpg",
            )
            session.add(person)
            session.commit()

        result = get_or_create_person(
            tmdb_identifier=6001,
            name="Existing Person",
        )
        assert result.name == "Existing Person"
        assert result.profile_path == "/old/path.jpg"

    def test_get_or_create_person_updates_existing(self) -> None:
        """Test that get_or_create_person updates data on existing person."""
        with get_session() as session:
            person = Person(
                tmdb_identifier=7001,
                name="Old Name",
                profile_path="/old/path.jpg",
            )
            session.add(person)
            session.commit()

        result = get_or_create_person(
            tmdb_identifier=7001,
            name="Updated Name",
            profile_path="/new/path.jpg",
        )
        assert result.name == "Updated Name"
        assert result.profile_path == "/new/path.jpg"


class TestFilmography:
    """Test suite for filmography query."""

    def test_get_filmography_empty(self) -> None:
        """Test that getting filmography for a person with no roles returns empty list."""
        with get_session() as session:
            person = Person(tmdb_identifier=8001, name="No Roles")
            session.add(person)
            session.commit()

        result = get_filmography(person.id)
        assert result == []

    def test_get_filmography_with_roles(self) -> None:
        """Test getting all media a person appears in."""
        with get_session() as session:
            person = Person(tmdb_identifier=9001, name="Busy Actor")
            series = Series(name="TV Show", library_name="TV")
            movie = Movie(name="Feature Film", library_name="Movies")
            session.add_all([person, series, movie])
            session.flush()

            cast_series = MediaCast(
                person_id=person.id,
                series_id=series.id,
                role="actor",
                character="TV Character",
                sort_order=0,
            )
            cast_movie = MediaCast(
                person_id=person.id,
                movie_id=movie.id,
                role="actor",
                character="Movie Character",
                sort_order=1,
            )
            session.add_all([cast_series, cast_movie])
            session.commit()

        result = get_filmography(person.id)
        assert len(result) == 2
        # Verify relationships are loaded
        series_role = next(r for r in result if r.series_id is not None)
        movie_role = next(r for r in result if r.movie_id is not None)
        assert series_role.series is not None
        assert series_role.series.name == "TV Show"
        assert movie_role.movie is not None
        assert movie_role.movie.name == "Feature Film"


class TestDeleteCast:
    """Test suite for delete_cast_for_media."""

    def test_delete_cast_for_series(self) -> None:
        """Test deleting all cast entries for a series."""
        with get_session() as session:
            series = Series(name="Delete Cast Series", library_name="TV")
            person = Person(tmdb_identifier=10001, name="Delete Actor")
            session.add_all([series, person])
            session.flush()

            cast_entry = MediaCast(
                person_id=person.id,
                series_id=series.id,
                role="actor",
            )
            session.add(cast_entry)
            session.commit()
            series_id = series.id

        delete_cast_for_media(series_id=series_id)

        result = get_cast_for_series(series_id)
        assert result == []

    def test_delete_cast_for_movie(self) -> None:
        """Test deleting all cast entries for a movie."""
        with get_session() as session:
            movie = Movie(name="Delete Cast Movie", library_name="Movies")
            person = Person(tmdb_identifier=11001, name="Movie Delete")
            session.add_all([movie, person])
            session.flush()

            cast_entry = MediaCast(
                person_id=person.id,
                movie_id=movie.id,
                role="actor",
            )
            session.add(cast_entry)
            session.commit()
            movie_id = movie.id

        delete_cast_for_media(movie_id=movie_id)

        result = get_cast_for_movie(movie_id)
        assert result == []

    def test_delete_cast_does_not_affect_other_media(self) -> None:
        """Test that deleting cast for one series does not affect another."""
        with get_session() as session:
            series1 = Series(name="Series A", library_name="TV")
            series2 = Series(name="Series B", library_name="TV")
            person = Person(tmdb_identifier=12001, name="Shared Actor")
            session.add_all([series1, series2, person])
            session.flush()

            cast1 = MediaCast(
                person_id=person.id,
                series_id=series1.id,
                role="actor",
            )
            cast2 = MediaCast(
                person_id=person.id,
                series_id=series2.id,
                role="actor",
            )
            session.add_all([cast1, cast2])
            session.commit()
            series1_id = series1.id
            series2_id = series2.id

        delete_cast_for_media(series_id=series1_id)

        assert len(get_cast_for_series(series1_id)) == 0
        assert len(get_cast_for_series(series2_id)) == 1


class TestImageQueries:
    """Test suite for image-related query functions."""

    def test_get_images_for_media_empty(self) -> None:
        """Test that getting images for media with none returns empty list."""
        with get_session() as session:
            series = Series(name="No Images Series", library_name="TV")
            session.add(series)
            session.commit()

        result = get_images_for_media(series_id=series.id)
        assert result == []

    def test_get_images_for_media_series(self) -> None:
        """Test getting all images for a series."""
        with get_session() as session:
            series = Series(name="Has Images", library_name="TV")
            session.add(series)
            session.flush()

            img1 = MediaImage(
                series_id=series.id,
                image_type="poster",
                source="tmdb",
                remote_url="https://example.invalid/p1.jpg",
                is_selected=True,
                sort_order=0,
            )
            img2 = MediaImage(
                series_id=series.id,
                image_type="backdrop",
                source="tmdb",
                remote_url="https://example.invalid/b1.jpg",
                is_selected=True,
                sort_order=0,
            )
            session.add_all([img1, img2])
            session.commit()
            series_id = series.id

        result = get_images_for_media(series_id=series_id)
        assert len(result) == 2

    def test_get_images_for_media_filtered_by_type(self) -> None:
        """Test filtering images by type."""
        with get_session() as session:
            series = Series(name="Filtered Images", library_name="TV")
            session.add(series)
            session.flush()

            poster = MediaImage(
                series_id=series.id,
                image_type="poster",
                source="tmdb",
                remote_url="https://example.invalid/p.jpg",
                is_selected=True,
                sort_order=0,
            )
            backdrop = MediaImage(
                series_id=series.id,
                image_type="backdrop",
                source="tmdb",
                remote_url="https://example.invalid/b.jpg",
                is_selected=True,
                sort_order=0,
            )
            session.add_all([poster, backdrop])
            session.commit()
            series_id = series.id

        posters = get_images_for_media(series_id=series_id, image_type="poster")
        assert len(posters) == 1
        assert posters[0].image_type == "poster"

        backdrops = get_images_for_media(series_id=series_id, image_type="backdrop")
        assert len(backdrops) == 1
        assert backdrops[0].image_type == "backdrop"

    def test_get_images_for_media_movie(self) -> None:
        """Test getting images for a movie."""
        with get_session() as session:
            movie = Movie(name="Movie Image", library_name="Movies")
            session.add(movie)
            session.flush()

            image = MediaImage(
                movie_id=movie.id,
                image_type="poster",
                source="tmdb",
                remote_url="https://example.invalid/movie.jpg",
                is_selected=True,
                sort_order=0,
            )
            session.add(image)
            session.commit()
            movie_id = movie.id

        result = get_images_for_media(movie_id=movie_id)
        assert len(result) == 1
        assert result[0].remote_url == "https://example.invalid/movie.jpg"

    def test_set_selected_image(self) -> None:
        """Test setting a specific image as selected."""
        with get_session() as session:
            series = Series(name="Select Image", library_name="TV")
            session.add(series)
            session.flush()

            img1 = MediaImage(
                series_id=series.id,
                image_type="poster",
                source="tmdb",
                remote_url="https://example.invalid/p1.jpg",
                is_selected=True,
                sort_order=0,
            )
            img2 = MediaImage(
                series_id=series.id,
                image_type="poster",
                source="tmdb",
                remote_url="https://example.invalid/p2.jpg",
                is_selected=False,
                sort_order=1,
            )
            session.add_all([img1, img2])
            session.commit()
            img2_id = img2.id

        set_selected_image(img2_id)

        with get_session() as session:
            series_statement = select(Series).where(Series.name == "Select Image")
            series = session.execute(series_statement).unique().scalar_one_or_none()
            assert series is not None

            images = (
                session.execute(
                    select(MediaImage)
                    .where(MediaImage.series_id == series.id)
                    .order_by(MediaImage.sort_order)
                )
                .unique()
                .scalars()
                .all()
            )
            assert images[0].is_selected is False
            assert images[1].is_selected is True

    def test_set_selected_image_not_found(self) -> None:
        """Test that setting a non-existent image ID logs a warning (does not raise)."""
        # Should not raise any exception
        set_selected_image("00000000-0000-0000-0000-000000000000")

    def test_add_media_image_first_is_selected(self) -> None:
        """Test that the first image added is automatically selected."""
        with get_session() as session:
            series = Series(name="First Image", library_name="TV")
            session.add(series)
            session.commit()
            series_id = series.id

        image = add_media_image(
            series_id=series_id,
            image_type="poster",
            source="tmdb",
            remote_url="https://example.invalid/first.jpg",
        )
        assert image.is_selected is True
        assert image.sort_order == 0

    def test_add_media_image_subsequent_not_selected(self) -> None:
        """Test that subsequent images are not auto-selected."""
        with get_session() as session:
            series = Series(name="Second Image", library_name="TV")
            session.add(series)
            session.commit()
            series_id = series.id

        # Add first - should be selected
        first = add_media_image(
            series_id=series_id,
            image_type="poster",
            source="tmdb",
        )
        assert first.is_selected is True

        # Add second - should not be selected
        second = add_media_image(
            series_id=series_id,
            image_type="poster",
            source="tmdb",
        )
        assert second.is_selected is False
        assert second.sort_order == 1

    def test_add_media_image_different_types_independent(self) -> None:
        """Test that different image types have independent selection."""
        with get_session() as session:
            series = Series(name="Multi Type", library_name="TV")
            session.add(series)
            session.commit()
            series_id = series.id

        # First poster and first backdrop should both be selected
        poster = add_media_image(
            series_id=series_id,
            image_type="poster",
            source="tmdb",
        )
        backdrop = add_media_image(
            series_id=series_id,
            image_type="backdrop",
            source="tmdb",
        )
        assert poster.is_selected is True
        assert poster.sort_order == 0
        assert backdrop.is_selected is True
        assert backdrop.sort_order == 0
