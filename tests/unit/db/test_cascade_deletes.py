import uuid
from sqlalchemy import select, text
from lan_streamer.db import get_session
from lan_streamer.db.models import (
    Series,
    Season,
    Episode,
    PlaybackState,
    MediaFile,
    MetadataFileMapping,
)
from lan_streamer.db.models_cast import Person, MediaCast, MediaImage


def test_cascade_delete_series() -> None:
    """
    Test cascade deletes when a Series is deleted:
    - Seasons are deleted
    - media_cast records are deleted
    - media_images records are deleted
    """
    with get_session() as session:
        # 1. Create a Series
        series = Series(library_name="TV", name="Test Cascade Series")
        session.add(series)
        session.flush()

        series_id = series.id

        # 2. Create a Season
        season = Season(name="Season 1", series=series)
        session.add(season)
        session.flush()
        season_id = season.id

        # 3. Create a Person
        person = Person(tmdb_identifier=99901, name="Cast Actor 1")
        session.add(person)
        session.flush()

        # 4. Create MediaCast linked to Series
        cast_entry = MediaCast(
            person_id=person.id,
            series_id=series_id,
            role="actor",
            character="Cast Member",
        )
        session.add(cast_entry)

        # 5. Create MediaImage linked to Series
        image_entry = MediaImage(
            series_id=series_id,
            image_type="poster",
            source="tmdb",
            remote_url="https://example.invalid/img.jpg",
        )
        session.add(image_entry)
        session.commit()

        cast_id = cast_entry.id
        image_id = image_entry.id

    # Now verify all records exist in DB
    with get_session() as session:
        assert session.get(Series, series_id) is not None
        assert session.get(Season, season_id) is not None
        assert session.get(MediaCast, cast_id) is not None
        assert session.get(MediaImage, image_id) is not None

        # Delete the Series
        series = session.get(Series, series_id)
        session.delete(series)
        session.commit()

    # Verify they are all deleted
    with get_session() as session:
        assert session.get(Series, series_id) is None
        assert session.get(Season, season_id) is None
        assert session.get(MediaCast, cast_id) is None
        assert session.get(MediaImage, image_id) is None


def test_cascade_delete_season_to_episodes() -> None:
    """
    Test cascade deletes when a Season is deleted:
    - Episodes are deleted
    """
    with get_session() as session:
        series = Series(library_name="TV", name="Test Season Cascade Series")
        season = Season(name="Season 1", series=series)
        episode1 = Episode(name="Episode 1", season=season)
        episode2 = Episode(name="Episode 2", season=season)

        session.add_all([series, season, episode1, episode2])
        session.commit()

        season_id = season.id
        ep1_id = episode1.id
        ep2_id = episode2.id

    with get_session() as session:
        assert session.get(Season, season_id) is not None
        assert session.get(Episode, ep1_id) is not None
        assert session.get(Episode, ep2_id) is not None

        # Delete the Season
        season = session.get(Season, season_id)
        session.delete(season)
        session.commit()

    with get_session() as session:
        assert session.get(Season, season_id) is None
        assert session.get(Episode, ep1_id) is None
        assert session.get(Episode, ep2_id) is None


def test_cascade_delete_episode_to_details() -> None:
    """
    Test cascade deletes when an Episode is deleted:
    - playback states record is deleted
    - metadata_file_mappings record is deleted
    """
    with get_session() as session:
        series = Series(library_name="TV", name="Test Episode Cascade Series")
        season = Season(name="Season 1", series=series)
        episode = Episode(name="Episode 1", season=season)
        media_file = MediaFile(path="/tv/cascade_ep1.mkv")
        episode.media_files.append(media_file)

        # Force playback state creation
        episode.watched = True

        session.add_all([series, season, episode, media_file])
        session.commit()

        ep_id = episode.id
        playback_id = episode.playback_state.id
        mf_id = media_file.id

        # Get mapping ID
        mapping_stmt = select(MetadataFileMapping).where(
            MetadataFileMapping.episode_id == ep_id,
            MetadataFileMapping.media_file_id == mf_id,
        )
        mapping = session.execute(mapping_stmt).scalar_one()
        mapping_id = mapping.id

    with get_session() as session:
        assert session.get(Episode, ep_id) is not None
        assert session.get(PlaybackState, playback_id) is not None
        assert session.get(MetadataFileMapping, mapping_id) is not None

        # Delete the Episode
        episode = session.get(Episode, ep_id)
        session.delete(episode)
        session.commit()

    with get_session() as session:
        assert session.get(Episode, ep_id) is None
        assert session.get(PlaybackState, playback_id) is None
        assert session.get(MetadataFileMapping, mapping_id) is None
        # MediaFile itself should survive
        assert session.get(MediaFile, mf_id) is not None


def test_cascade_delete_media_file_to_mappings() -> None:
    """
    Test cascade deletes when a Media File is deleted:
    - metadata_file_mappings record is deleted
    """
    with get_session() as session:
        series = Series(library_name="TV", name="Test Media File Cascade Series")
        season = Season(name="Season 1", series=series)
        episode = Episode(name="Episode 1", season=season)
        media_file = MediaFile(path="/tv/cascade_ep_mf.mkv")
        episode.media_files.append(media_file)

        session.add_all([series, season, episode, media_file])
        session.commit()

        ep_id = episode.id
        mf_id = media_file.id

        # Get mapping ID
        mapping_stmt = select(MetadataFileMapping).where(
            MetadataFileMapping.episode_id == ep_id,
            MetadataFileMapping.media_file_id == mf_id,
        )
        mapping = session.execute(mapping_stmt).scalar_one()
        mapping_id = mapping.id

    with get_session() as session:
        assert session.get(MediaFile, mf_id) is not None
        assert session.get(MetadataFileMapping, mapping_id) is not None

        # Delete the MediaFile
        media_file = session.get(MediaFile, mf_id)
        session.delete(media_file)
        session.commit()

    with get_session() as session:
        assert session.get(MediaFile, mf_id) is None
        assert session.get(MetadataFileMapping, mapping_id) is None
        # Episode itself should survive
        assert session.get(Episode, ep_id) is not None


def test_manual_database_deletes_cascade() -> None:
    """
    Verify database-level cascade deletes when manual SQL deletes are executed:
    - Delete series directly in the DB -> seasons, media_cast, media_images deleted
    - Delete season directly in the DB -> episodes deleted
    - Delete episode directly in the DB -> playback_states, metadata_file_mappings deleted
    - Delete media_file directly in the DB -> metadata_file_mappings deleted
    """
    with get_session() as session:
        # Create full structure
        series = Series(library_name="TV", name="SQL Cascade Series")
        season = Season(name="Season 1", series=series)
        episode = Episode(name="Episode 1", season=season)
        episode.watched = True

        person = Person(tmdb_identifier=99902, name="Cast Actor 2")
        cast_entry = MediaCast(person=person, series=series, role="actor")
        image_entry = MediaImage(series=series, image_type="poster", source="tmdb")

        media_file = MediaFile(path="/tv/sql_cascade_ep.mkv")
        episode.media_files.append(media_file)

        session.add_all(
            [series, season, episode, person, cast_entry, image_entry, media_file]
        )
        session.commit()

        series_id = series.id
        season_id = season.id
        ep_id = episode.id
        playback_id = episode.playback_state.id
        cast_id = cast_entry.id
        image_id = image_entry.id
        mf_id = media_file.id

        # Get mapping ID
        mapping_stmt = select(MetadataFileMapping).where(
            MetadataFileMapping.episode_id == ep_id,
            MetadataFileMapping.media_file_id == mf_id,
        )
        mapping = session.execute(mapping_stmt).scalar_one()
        mapping_id = mapping.id

    # Verify everything exists
    with get_session() as session:
        assert session.get(Series, series_id) is not None
        assert session.get(Season, season_id) is not None
        assert session.get(Episode, ep_id) is not None
        assert session.get(PlaybackState, playback_id) is not None
        assert session.get(MediaCast, cast_id) is not None
        assert session.get(MediaImage, image_id) is not None
        assert session.get(MetadataFileMapping, mapping_id) is not None

        # 1. Execute direct database delete on the Episode table (simulating direct DB edit)
        session.execute(
            text("DELETE FROM episodes WHERE id = :ep_id"),
            {"ep_id": uuid.UUID(ep_id).bytes},
        )
        session.commit()

    with get_session() as session:
        # Verify direct Episode deletion cascaded to playback_states and metadata_file_mappings tables
        assert session.get(Episode, ep_id) is None
        assert session.get(PlaybackState, playback_id) is None
        assert session.get(MetadataFileMapping, mapping_id) is None

        # Re-create mapping for MediaFile deletion test
        episode2 = Episode(name="Episode 2", season_id=season_id)
        media_file = session.get(MediaFile, mf_id)
        episode2.media_files.append(media_file)
        session.add(episode2)
        session.commit()
        ep2_id = episode2.id

        mapping_stmt = select(MetadataFileMapping).where(
            MetadataFileMapping.episode_id == ep2_id,
            MetadataFileMapping.media_file_id == mf_id,
        )
        mapping = session.execute(mapping_stmt).scalar_one()
        mapping_id2 = mapping.id

    with get_session() as session:
        # 2. Execute direct database delete on the MediaFile table
        session.execute(
            text("DELETE FROM media_files WHERE id = :mf_id"),
            {"mf_id": uuid.UUID(mf_id).bytes},
        )
        session.commit()

    with get_session() as session:
        assert session.get(MediaFile, mf_id) is None
        assert session.get(MetadataFileMapping, mapping_id2) is None

        # 3. Execute direct database delete on the Series table
        session.execute(
            text("DELETE FROM series WHERE id = :series_id"),
            {"series_id": uuid.UUID(series_id).bytes},
        )
        session.commit()

    with get_session() as session:
        # Verify deleting Series directly from DB cascaded to Seasons, MediaCast, and MediaImages
        assert session.get(Series, series_id) is None
        assert session.get(Season, season_id) is None
        assert session.get(MediaCast, cast_id) is None
        assert session.get(MediaImage, image_id) is None
