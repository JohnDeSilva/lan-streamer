from unittest.mock import patch

from sqlalchemy import select

from lan_streamer.db import get_session
from lan_streamer.db.smart_row_cache import (
    compute_config_hash,
    get_cached_smart_rows,
    rebuild_cache_for_config,
    rebuild_all_cache,
    get_affected_config_hashes_for_libraries,
    _row_to_dict,
    _resolve_series_ids,
    _resolve_movie_ids,
    _lookup_series_id,
    _lookup_movie_id,
)
from lan_streamer.db.models import (
    SmartRowCache,
    Series,
    Movie,
)


def test_compute_config_hash_deterministic() -> None:
    hash1 = compute_config_hash(["A", "B"], "Alphabetical", "All")
    hash2 = compute_config_hash(["A", "B"], "Alphabetical", "All")
    assert hash1 == hash2


def test_compute_config_hash_different_inputs() -> None:
    hash1 = compute_config_hash(["A"], "Alphabetical", "All")
    hash2 = compute_config_hash(["B"], "Alphabetical", "All")
    hash3 = compute_config_hash(["A"], "Recently Added", "All")
    hash4 = compute_config_hash(["A"], "Alphabetical", "Watched")
    assert len({hash1, hash2, hash3, hash4}) == 4


def test_compute_config_hash_order_independent() -> None:
    hash1 = compute_config_hash(["B", "A"], "Alphabetical", "All")
    hash2 = compute_config_hash(["A", "B"], "Alphabetical", "All")
    assert hash1 == hash2


def test_get_cached_smart_rows_miss_falls_through() -> None:
    with patch(
        "lan_streamer.db.smart_row_cache.compute_smart_row",
        return_value=[{"type": "series", "name": "Test"}],
    ) as mock_compute:
        result = get_cached_smart_rows([], "Alphabetical", "All")
        assert len(result) == 1
        assert result[0]["name"] == "Test"
        mock_compute.assert_called_once_with([], "Alphabetical", "All")


def test_get_cached_smart_rows_hit_returns_cached() -> None:
    config_hash = compute_config_hash([], "Alphabetical", "All")
    with get_session() as session:
        series = Series(name="Test Series", library_name="TV")
        session.add(series)
        session.flush()
        cache_entry = SmartRowCache(
            config_hash=config_hash,
            sort_order=0,
            item_type="series",
            series_id=series.id,
            date_added=100,
            watched_count=5,
            total_count=10,
            updated_at=123,
        )
        session.add(cache_entry)
        session.commit()

    with patch("lan_streamer.db.smart_row_cache.compute_smart_row") as mock_compute:
        result = get_cached_smart_rows([], "Alphabetical", "All")
        assert len(result) == 1
        assert result[0]["type"] == "series"
        assert result[0]["watched_count"] == 5
        assert result[0]["total_count"] == 10
        mock_compute.assert_not_called()


def test_rebuild_cache_for_config_stores_entries() -> None:
    with get_session() as session:
        series = Series(name="Test Show", library_name="TV")
        session.add(series)
        session.flush()
        movie = Movie(name="Test Movie", library_name="Movies")
        session.add(movie)
        session.commit()

    with patch(
        "lan_streamer.db.smart_row_cache.compute_smart_row",
        return_value=[
            {
                "type": "series",
                "name": "Test Show",
                "library_name": "TV",
                "poster_path": "/poster.jpg",
                "date_added": 100,
                "air_date": "2024-01-01",
                "watched_count": 3,
                "total_count": 10,
                "last_played_at": 500,
            },
            {
                "type": "movie",
                "name": "Test Movie",
                "library_name": "Movies",
                "poster_path": "/movie.jpg",
                "date_added": 200,
                "air_date": "2024",
                "watched_count": 0,
                "total_count": 1,
                "last_played_at": 0,
            },
        ],
    ):
        rebuild_cache_for_config(["TV", "Movies"], "Alphabetical", "All")

    config_hash = compute_config_hash(["TV", "Movies"], "Alphabetical", "All")
    with get_session() as session:
        entries = list(
            session.scalars(
                select(SmartRowCache)
                .where(SmartRowCache.config_hash == config_hash)
                .order_by(SmartRowCache.sort_order)
            ).all()
        )
        assert len(entries) == 2
        assert entries[0].item_type == "series"
        assert entries[0].sort_order == 0
        assert entries[1].item_type == "movie"
        assert entries[1].sort_order == 1


def test_rebuild_cache_for_config_clears_existing() -> None:
    config_hash = compute_config_hash([], "Alphabetical", "All")
    with get_session() as session:
        old_entry = SmartRowCache(
            config_hash=config_hash,
            sort_order=0,
            item_type="series",
            series_id=None,
            updated_at=0,
        )
        session.add(old_entry)
        session.commit()

    with patch(
        "lan_streamer.db.smart_row_cache.compute_smart_row",
        return_value=[{"type": "series", "name": "New"}],
    ):
        rebuild_cache_for_config([], "Alphabetical", "All")

    with get_session() as session:
        entries = list(
            session.scalars(
                select(SmartRowCache).where(SmartRowCache.config_hash == config_hash)
            ).all()
        )
        assert len(entries) == 1


def test_rebuild_cache_for_config_handles_empty() -> None:
    with patch(
        "lan_streamer.db.smart_row_cache.compute_smart_row",
        return_value=[],
    ):
        rebuild_cache_for_config([], "Alphabetical", "All")

    config_hash = compute_config_hash([], "Alphabetical", "All")
    with get_session() as session:
        entries = list(
            session.scalars(
                select(SmartRowCache).where(SmartRowCache.config_hash == config_hash)
            ).all()
        )
        assert len(entries) == 0


def test_rebuild_all_cache_iterates_configs() -> None:
    config_backup = [
        {
            "name": "Row 1",
            "enabled": True,
            "libraries": ["TV"],
            "sort_by": "Alphabetical",
            "filter_mode": "All",
        },
        {
            "name": "Row 2",
            "enabled": True,
            "libraries": ["Movies"],
            "sort_by": "Recently Added",
            "filter_mode": "Unwatched",
        },
        {
            "name": "Row 3",
            "enabled": False,
            "libraries": [],
            "sort_by": "Alphabetical",
            "filter_mode": "All",
        },
    ]
    with (
        patch(
            "lan_streamer.db.smart_row_cache.app_config.combined_views",
            config_backup,
        ),
        patch("lan_streamer.db.smart_row_cache.app_config.load") as mock_load,
        patch(
            "lan_streamer.db.smart_row_cache.rebuild_cache_for_config"
        ) as mock_rebuild,
    ):
        rebuild_all_cache()
        assert mock_load.called
        assert mock_rebuild.call_count == 2


def test_get_affected_config_hashes_for_libraries() -> None:
    configs = [
        {
            "name": "TV Row",
            "enabled": True,
            "libraries": ["TV", "Anime"],
            "sort_by": "Alphabetical",
            "filter_mode": "All",
        },
        {
            "name": "Movies Row",
            "enabled": True,
            "libraries": ["Movies"],
            "sort_by": "Recently Added",
            "filter_mode": "All",
        },
        {
            "name": "Disabled",
            "enabled": False,
            "libraries": ["Disabled Lib"],
            "sort_by": "Alphabetical",
            "filter_mode": "All",
        },
    ]
    with (
        patch(
            "lan_streamer.db.smart_row_cache.app_config.combined_views",
            configs,
        ),
        patch("lan_streamer.db.smart_row_cache.app_config.load"),
    ):
        hashes = get_affected_config_hashes_for_libraries(["TV"])
        assert len(hashes) == 1


def test_get_affected_config_hashes_empty_lib_matches_all() -> None:
    configs = [
        {
            "name": "All Libs",
            "enabled": True,
            "libraries": [],
            "sort_by": "Alphabetical",
            "filter_mode": "All",
        },
    ]
    with (
        patch(
            "lan_streamer.db.smart_row_cache.app_config.combined_views",
            configs,
        ),
        patch("lan_streamer.db.smart_row_cache.app_config.load"),
    ):
        hashes = get_affected_config_hashes_for_libraries(["TV"])
        assert len(hashes) == 1


def test_row_to_dict_series() -> None:
    with get_session() as session:
        series = Series(
            name="Test Series",
            library_name="TV",
            poster_path="/poster.jpg",
            first_air_date="2024-01-01",
        )
        session.add(series)
        session.flush()
        row = SmartRowCache(
            config_hash="h",
            sort_order=0,
            item_type="series",
            series_id=series.id,
            date_added=100,
            air_date="2024-06-01",
            watched_count=3,
            total_count=10,
            last_played_at=500,
            updated_at=1000,
        )
        session.add(row)
        session.commit()

        # Re-fetch with joinedload to match production behavior
        from sqlalchemy.orm import joinedload
        from sqlalchemy import select

        fetched = (
            session.scalars(
                select(SmartRowCache)
                .options(
                    joinedload(SmartRowCache.series),
                    joinedload(SmartRowCache.movie),
                )
                .where(SmartRowCache.id == row.id)
            )
            .unique()
            .first()
        )
        assert fetched is not None

        d = _row_to_dict(fetched)
        assert d["type"] == "series"
        assert d["name"] == "Test Series"
        assert d["series_name"] == "Test Series"
        assert d["poster_path"] == "/poster.jpg"
        assert d["library_name"] == "TV"
        assert d["date_added"] == 100
        assert d["watched_count"] == 3
        assert d["total_count"] == 10
        assert d["last_played_at"] == 500


def test_row_to_dict_movie() -> None:
    with get_session() as session:
        movie = Movie(
            name="Test Movie",
            library_name="Movies",
            poster_path="/movie.jpg",
            year=2024,
        )
        session.add(movie)
        session.flush()
        row = SmartRowCache(
            config_hash="h",
            sort_order=0,
            item_type="movie",
            movie_id=movie.id,
            date_added=200,
            watched_count=0,
            total_count=1,
            updated_at=1000,
        )
        session.add(row)
        session.commit()

        from sqlalchemy.orm import joinedload
        from sqlalchemy import select

        fetched = (
            session.scalars(
                select(SmartRowCache)
                .options(
                    joinedload(SmartRowCache.series),
                    joinedload(SmartRowCache.movie),
                )
                .where(SmartRowCache.id == row.id)
            )
            .unique()
            .first()
        )

        d = _row_to_dict(fetched)
        assert d["type"] == "movie"
        assert d["name"] == "Test Movie"
        assert d["library_name"] == "Movies"
        assert d["poster_path"] == "/movie.jpg"
        assert d["total_count"] == 1


def test_row_to_dict_season() -> None:
    with get_session() as session:
        series = Series(name="Anime Show", library_name="Anime")
        session.add(series)
        session.flush()
        row = SmartRowCache(
            config_hash="h",
            sort_order=0,
            item_type="season",
            series_id=series.id,
            season_name="Season 1",
            date_added=300,
            watched_count=5,
            total_count=12,
            updated_at=1000,
        )
        session.add(row)
        session.commit()

        from sqlalchemy.orm import joinedload
        from sqlalchemy import select

        fetched = (
            session.scalars(
                select(SmartRowCache)
                .options(
                    joinedload(SmartRowCache.series),
                    joinedload(SmartRowCache.movie),
                )
                .where(SmartRowCache.id == row.id)
            )
            .unique()
            .first()
        )

        d = _row_to_dict(fetched)
        assert d["type"] == "season"
        assert d["season_name"] == "Season 1"
        assert d["name"] == "Anime Show"
        assert d["series_name"] == "Anime Show"


def test_row_to_dict_no_fk() -> None:
    row = SmartRowCache(
        config_hash="h",
        sort_order=0,
        item_type="series",
        series_id=None,
        movie_id=None,
        date_added=0,
        watched_count=0,
        total_count=1,
        updated_at=0,
    )
    d = _row_to_dict(row)
    assert d["name"] == ""
    assert d["poster_path"] == ""
    assert d["library_name"] == ""


def test_resolve_series_ids_empty() -> None:
    assert _resolve_series_ids([]) == {}


def test_resolve_series_ids_found() -> None:
    with get_session() as session:
        series = Series(name="Test", library_name="TV")
        session.add(series)
        session.commit()

    items = [
        {"type": "series", "name": "Test", "library_name": "TV"},
    ]
    result = _resolve_series_ids(items)
    assert "TV|Test" in result
    assert result["TV|Test"]


def test_resolve_series_ids_not_found() -> None:
    items = [
        {"type": "series", "name": "Nonexistent", "library_name": "TV"},
    ]
    result = _resolve_series_ids(items)
    assert result == {}


def test_resolve_movie_ids_empty() -> None:
    assert _resolve_movie_ids([]) == {}


def test_resolve_movie_ids_found() -> None:
    with get_session() as session:
        movie = Movie(name="Test Movie", library_name="Movies")
        session.add(movie)
        session.commit()

    items = [
        {"type": "movie", "name": "Test Movie", "library_name": "Movies"},
    ]
    result = _resolve_movie_ids(items)
    assert "Movies|Test Movie" in result
    assert result["Movies|Test Movie"]


def test_resolve_movie_ids_skips_non_movie() -> None:
    items = [
        {"type": "series", "name": "Test Show", "library_name": "TV"},
    ]
    result = _resolve_movie_ids(items)
    assert result == {}


def test_lookup_series_id_movie_type() -> None:
    result = _lookup_series_id(
        {"type": "movie", "name": "M", "library_name": "L"},
        {},
        "movie",
    )
    assert result is None


def test_lookup_series_id_found() -> None:
    series_ids = {"TV|Test": "id-123"}
    result = _lookup_series_id(
        {"type": "series", "name": "Test", "library_name": "TV"},
        series_ids,
        "series",
    )
    assert result == "id-123"


def test_lookup_movie_id_series_type() -> None:
    result = _lookup_movie_id(
        {"type": "series", "name": "S", "library_name": "L"},
        {},
        "series",
    )
    assert result is None


def test_lookup_movie_id_found() -> None:
    movie_ids = {"Movies|Test": "id-456"}
    result = _lookup_movie_id(
        {"type": "movie", "name": "Test", "library_name": "Movies"},
        movie_ids,
        "movie",
    )
    assert result == "id-456"
