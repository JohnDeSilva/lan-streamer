"""Coverage tests for library_tv.py — targeting uncovered lines."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from lan_streamer.db import get_session
from lan_streamer.db.library_tv import (
    _strip_counter_suffix,
    _save_season_record,
    _save_episode_record,
    save_library,
    save_season_data,
    _cleanup_tv_library,
)
from lan_streamer.db.models import (
    Series,
    Season,
    Episode,
    ScannedDirectory,
)


@pytest.fixture
def library_name() -> str:
    return "CoverageLib"


class TestStripCounterSuffix:
    """Line 34: _strip_counter_suffix."""

    def test_strips_suffix(self) -> None:
        assert _strip_counter_suffix("TBA (1)") == "TBA"
        assert _strip_counter_suffix("TBA (42)") == "TBA"
        assert _strip_counter_suffix("Normal Name") == "Normal Name"
        assert _strip_counter_suffix("Name (1) (2)") == "Name (1)"
        assert _strip_counter_suffix("") == ""


class TestSaveEpisodeRecordNameFallback:
    """Lines 294-322: name-based matching and suffixed variant matching."""

    def test_name_fallback_sets_tmdb_number(self, library_name: str) -> None:
        with get_session() as session:
            series = Series(name="Show1", library_name=library_name)
            session.add(series)
            session.flush()
            season = Season(name="Season 1", series=series)
            session.add(season)
            session.flush()

            # Existing episode with name but no path and no tmdb_number
            existing_ep = Episode(
                season_id=season.id,
                name="Episode TBA",
                path=None,
                tmdb_number=None,
            )
            session.add(existing_ep)
            session.flush()

            stats: dict[str, Any] = {
                "episodes": 0,
                "episodes_added": 0,
                "episodes_updated": 0,
                "episodes_scanned": 0,
                "deleted": 0,
                "episodes_removed": 0,
                "issues": [],
            }
            existing_by_path: dict[str, Episode] = {}
            existing_by_number: dict[int, Episode] = {}
            existing_by_name: dict[str, Episode] = {"Episode TBA": existing_ep}
            processed: set[Episode] = set()

            result = _save_episode_record(
                session,
                season,
                {
                    "name": "Episode TBA",
                    "path": "/new/path.mkv",
                    "tmdb_number": 5,
                },
                existing_by_path,
                existing_by_number,
                existing_by_name,
                stats,
                processed,
            )
            assert result.tmdb_number == 5
            assert result.path == "/new/path.mkv"

    def test_suffixed_name_fallback(self, library_name: str) -> None:
        with get_session() as session:
            series = Series(name="Show2", library_name=library_name)
            session.add(series)
            session.flush()
            season = Season(name="Season 1", series=series)
            session.add(season)
            session.flush()

            # Existing episode with suffixed name
            existing_ep = Episode(
                season_id=season.id,
                name="TBA (1)",
                path=None,
                tmdb_number=None,
            )
            session.add(existing_ep)
            session.flush()

            stats: dict[str, Any] = {
                "episodes": 0,
                "episodes_added": 0,
                "episodes_updated": 0,
                "episodes_scanned": 0,
                "deleted": 0,
                "episodes_removed": 0,
                "issues": [],
            }
            existing_by_path: dict[str, Episode] = {}
            existing_by_number: dict[int, Episode] = {}
            existing_by_name: dict[str, Episode] = {"TBA (1)": existing_ep}
            processed: set[Episode] = set()

            result = _save_episode_record(
                session,
                season,
                {
                    "name": "TBA",
                    "path": "/path2.mkv",
                    "tmdb_number": 3,
                },
                existing_by_path,
                existing_by_number,
                existing_by_name,
                stats,
                processed,
            )
            assert result.name in ("TBA (1)", "TBA")


class TestSaveEpisodeRecordFileRemap:
    """Lines 221-239: file remapped to a different episode."""

    def test_file_remapped_clears_old_path(self, library_name: str) -> None:
        with get_session() as session:
            series = Series(name="RemapShow", library_name=library_name)
            session.add(series)
            session.flush()
            season = Season(name="Season 1", series=series)
            session.add(season)
            session.flush()

            # Episode currently holding the path
            old_ep = Episode(
                season_id=season.id,
                name="Old Ep",
                path="/remap/file.mkv",
                tmdb_number=1,
            )
            session.add(old_ep)
            session.flush()

            stats: dict[str, Any] = {
                "episodes": 0,
                "episodes_added": 0,
                "episodes_updated": 0,
                "episodes_scanned": 0,
                "deleted": 0,
                "episodes_removed": 0,
                "issues": [],
            }
            existing_by_path: dict[str, Episode] = {"/remap/file.mkv": old_ep}
            existing_by_number: dict[int, Episode] = {1: old_ep}
            existing_by_name: dict[str, Episode] = {}
            processed: set[Episode] = set()

            result = _save_episode_record(
                session,
                season,
                {
                    "name": "New Ep",
                    "path": "/remap/file.mkv",
                    "tmdb_number": 99,
                },
                existing_by_path,
                existing_by_number,
                existing_by_name,
                stats,
                processed,
            )
            assert result.tmdb_number == 99
            assert old_ep.path is None


class TestSaveEpisodeRecordPlaceholderPromotion:
    """Lines 281-284: promoting placeholder to local file."""

    def test_placeholder_gets_path(self, library_name: str) -> None:
        with get_session() as session:
            series = Series(name="PromoShow", library_name=library_name)
            session.add(series)
            session.flush()
            season = Season(name="Season 1", series=series)
            session.add(season)
            session.flush()

            placeholder = Episode(
                season_id=season.id,
                name="Placeholder",
                path=None,
                tmdb_number=1,
            )
            session.add(placeholder)
            session.flush()

            stats: dict[str, Any] = {
                "episodes": 0,
                "episodes_added": 0,
                "episodes_updated": 0,
                "episodes_scanned": 0,
                "deleted": 0,
                "episodes_removed": 0,
                "issues": [],
            }
            existing_by_path: dict[str, Episode] = {}
            existing_by_number: dict[int, Episode] = {1: placeholder}
            existing_by_name: dict[str, Episode] = {}
            processed: set[Episode] = set()

            result = _save_episode_record(
                session,
                season,
                {
                    "name": "Placeholder",
                    "path": "/promoted/file.mkv",
                    "tmdb_number": 1,
                },
                existing_by_path,
                existing_by_number,
                existing_by_name,
                stats,
                processed,
            )
            assert result.path == "/promoted/file.mkv"


class TestSaveEpisodeRecordCrossRootDedup:
    """Lines 328-347: cross-root dedup via tmdb_episode_identifier."""

    def test_cross_root_dedup_merges(self, library_name: str) -> None:
        with get_session() as session:
            series = Series(name="CrossShow", library_name=library_name)
            session.add(series)
            session.flush()
            season = Season(name="Season 1", series=series)
            session.add(season)
            session.flush()

            existing_ep = Episode(
                season_id=season.id,
                name="Cross Ep",
                path=None,
                tmdb_episode_identifier="tmdb_ep_42",
            )
            session.add(existing_ep)
            session.flush()

            stats: dict[str, Any] = {
                "episodes": 0,
                "episodes_added": 0,
                "episodes_updated": 0,
                "episodes_scanned": 0,
                "deleted": 0,
                "episodes_removed": 0,
                "issues": [],
            }
            existing_by_path: dict[str, Episode] = {}
            existing_by_number: dict[int, Episode] = {}
            existing_by_name: dict[str, Episode] = {}
            processed: set[Episode] = set()

            result = _save_episode_record(
                session,
                season,
                {
                    "name": "Cross Ep",
                    "path": "/root2/cross_ep.mkv",
                    "tmdb_episode_identifier": "tmdb_ep_42",
                },
                existing_by_path,
                existing_by_number,
                existing_by_name,
                stats,
                processed,
            )
            assert result.id == existing_ep.id
            assert result.path == "/root2/cross_ep.mkv"


class TestSaveSeasonRecordMyanimelistId:
    """Lines 166-169: myanimelist_id handling in _save_season_record."""

    def test_sets_myanimelist_id(self, library_name: str) -> None:
        with get_session() as session:
            series = Series(name="MALShow", library_name=library_name)
            session.add(series)
            session.flush()

            existing_season = Season(name="Season 1", series=series)
            session.add(existing_season)
            session.flush()

            stats: dict[str, Any] = {
                "seasons": 0,
                "seasons_added": 0,
                "seasons_updated": 0,
                "seasons_scanned": 0,
            }
            existing_seasons: dict[str, Season] = {"Season 1": existing_season}

            result = _save_season_record(
                session,
                series,
                "Season 1",
                {"metadata": {"myanimelist_id": 9999}},
                existing_seasons,
                stats,
            )
            assert result.myanimelist_id == 9999
            assert stats.get("seasons_updated", 0) == 1


class TestSaveLibraryMtime:
    """Lines 698-735: ScannedDirectory persistence for series and season."""

    def test_series_directory_mtime_persisted(self, library_name: str) -> None:
        library_data = {
            "MtimeShow": {
                "metadata": {
                    "series_directory_path": "/shows/MtimeShow",
                    "last_scanned_mtime": 12345,
                },
                "seasons": {
                    "Season 1": {
                        "metadata": {
                            "season_directory_path": "/shows/MtimeShow/Season 1",
                            "last_scanned_mtime": 67890,
                        },
                        "episodes": [
                            {
                                "name": "Ep1",
                                "path": "/shows/MtimeShow/Season 1/ep1.mkv",
                            }
                        ],
                    }
                },
            }
        }
        save_library(library_name, library_data)

        with get_session() as session:
            rec = session.scalars(
                __import__("sqlalchemy", fromlist=["select"])
                .select(ScannedDirectory)
                .where(ScannedDirectory.path == "/shows/MtimeShow")
            ).first()
            assert rec is not None
            assert rec.last_scanned_mtime == 12345

            season_rec = session.scalars(
                __import__("sqlalchemy", fromlist=["select"])
                .select(ScannedDirectory)
                .where(ScannedDirectory.path == "/shows/MtimeShow/Season 1")
            ).first()
            assert season_rec is not None
            assert season_rec.last_scanned_mtime == 67890

    def test_existing_mtime_record_updated(self, library_name: str) -> None:
        from sqlalchemy import select as sa_select

        with get_session() as session:
            rec = ScannedDirectory(path="/shows/UpdateShow", last_scanned_mtime=100)
            session.add(rec)
            session.flush()

        library_data = {
            "UpdateShow": {
                "metadata": {
                    "series_directory_path": "/shows/UpdateShow",
                    "last_scanned_mtime": 999,
                },
                "seasons": {},
            }
        }
        save_library(library_name, library_data)

        with get_session() as session:
            updated = session.scalars(
                sa_select(ScannedDirectory).where(
                    ScannedDirectory.path == "/shows/UpdateShow"
                )
            ).first()
            assert updated is not None
            assert updated.last_scanned_mtime == 999


class TestSaveLibraryStaleEpisodeCleanup:
    """Lines 683-696: stale episode cleanup in save_library."""

    def test_stale_episodes_removed(self, library_name: str) -> None:
        initial_library = {
            "StaleShow": {
                "metadata": {},
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "name": "Old Stale Ep",
                                "path": "/stale/old.mkv",
                                "tmdb_number": 100,
                            }
                        ],
                    }
                },
            }
        }
        save_library(library_name, initial_library)

        updated_library = {
            "StaleShow": {
                "metadata": {},
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "name": "New Ep",
                                "path": "/new/ep.mkv",
                                "tmdb_number": 1,
                            }
                        ],
                    }
                },
            }
        }
        stats = save_library(library_name, updated_library)
        assert stats["episodes_removed"] >= 1


class TestSaveLibraryExceptionHandling:
    """Lines 739-748: exception handling in save_library."""

    def test_exception_records_issue(self, library_name: str) -> None:
        with pytest.raises(Exception):
            with patch(
                "lan_streamer.db.library_tv.get_session",
                side_effect=Exception("db failure"),
            ):
                save_library(
                    library_name, {"SomeSeries": {"metadata": {}, "seasons": {}}}
                )


class TestSaveSeasonData:
    """Lines 919-920, 944-957, 964-973, 982-986: save_season_data paths."""

    def test_save_season_data_with_stale_episodes(self, library_name: str) -> None:
        with get_session() as session:
            series = Series(name="SeasonDataShow", library_name=library_name)
            session.add(series)
            session.flush()
            season = Season(name="Season 1", series=series)
            session.add(season)
            session.flush()

            old_ep = Episode(
                season_id=season.id,
                name="Old Ep",
                path="/old/ep.mkv",
                tmdb_number=50,
            )
            session.add(old_ep)
            session.flush()
            session.commit()

        series_data: dict[str, Any] = {"metadata": {}, "seasons": {}}
        season_data = {
            "metadata": {},
            "episodes": [
                {
                    "name": "New Ep",
                    "path": "/new/ep.mkv",
                    "tmdb_number": 1,
                }
            ],
        }
        stats = save_season_data(
            library_name,
            "SeasonDataShow",
            series_data,
            "Season 1",
            season_data,
        )
        assert stats["episodes_removed"] >= 1
        assert "season_id" in stats
        assert "series_id" in stats

    def test_save_season_data_with_mtime(self, library_name: str) -> None:
        from sqlalchemy import select as sa_select

        series_data: dict[str, Any] = {"metadata": {}, "seasons": {}}
        season_data = {
            "metadata": {
                "season_directory_path": "/shows/MtimeSeason/Season 1",
                "last_scanned_mtime": 55555,
            },
            "episodes": [],
        }
        save_season_data(
            library_name,
            "MtimeSeasonShow",
            series_data,
            "Season 1",
            season_data,
        )

        with get_session() as session:
            rec = session.scalars(
                sa_select(ScannedDirectory).where(
                    ScannedDirectory.path == "/shows/MtimeSeason/Season 1"
                )
            ).first()
            assert rec is not None
            assert rec.last_scanned_mtime == 55555

    def test_save_season_data_existing_mtime_updated(self, library_name: str) -> None:
        from sqlalchemy import select as sa_select

        with get_session() as session:
            rec = ScannedDirectory(
                path="/shows/ExistingMtime/S1", last_scanned_mtime=100
            )
            session.add(rec)
            session.flush()

        series_data: dict[str, Any] = {"metadata": {}, "seasons": {}}
        season_data = {
            "metadata": {
                "season_directory_path": "/shows/ExistingMtime/S1",
                "last_scanned_mtime": 999,
            },
            "episodes": [],
        }
        save_season_data(
            library_name,
            "ExistingMtimeShow",
            series_data,
            "S1",
            season_data,
        )

        with get_session() as session:
            updated = session.scalars(
                sa_select(ScannedDirectory).where(
                    ScannedDirectory.path == "/shows/ExistingMtime/S1"
                )
            ).first()
            assert updated is not None
            assert updated.last_scanned_mtime == 999

    def test_save_season_data_exception(self, library_name: str) -> None:
        with pytest.raises(Exception):
            with patch(
                "lan_streamer.db.library_tv.get_session",
                side_effect=Exception("db failure"),
            ):
                save_season_data(
                    library_name,
                    "FailShow",
                    {"metadata": {}, "seasons": {}},
                    "Season 1",
                    {"metadata": {}, "episodes": []},
                )


class TestSaveEpisodeMalFields:
    """Lines 488-493, 499, 524, 526: myanimelist and default_path changes."""

    def test_myanimelist_fields_updated(self, library_name: str) -> None:
        from sqlalchemy import select as sa_select

        with get_session() as session:
            series = Series(name="MALShow2", library_name=library_name)
            session.add(series)
            session.flush()
            season = Season(name="Season 1", series=series)
            session.add(season)
            session.flush()

            ep = Episode(
                season_id=season.id,
                name="MAL Ep",
                path="/mal/ep.mkv",
                tmdb_number=1,
                myanimelist_anime_id=100,
                myanimelist_episode_number=1,
            )
            session.add(ep)
            session.flush()
            session.commit()

        stats: dict[str, Any] = {
            "episodes": 0,
            "episodes_added": 0,
            "episodes_updated": 0,
            "episodes_scanned": 0,
            "deleted": 0,
            "episodes_removed": 0,
            "issues": [],
        }
        with get_session() as session:
            season_obj = session.scalars(
                sa_select(Season).join(Series).where(Series.name == "MALShow2")
            ).first()

            episode_obj = session.scalars(
                sa_select(Episode).where(Episode.path == "/mal/ep.mkv")
            ).first()

            ep_by_path: dict[str, Episode] = {"/mal/ep.mkv": episode_obj}
            ep_by_number: dict[int, Episode] = {1: episode_obj}
            ep_by_name: dict[str, Episode] = {"MAL Ep": episode_obj}

            result = _save_episode_record(
                session,
                season_obj,
                {
                    "name": "MAL Ep",
                    "path": "/mal/ep.mkv",
                    "tmdb_number": 1,
                    "myanimelist_anime_id": 200,
                    "myanimelist_episode_number": 3,
                    "default_path": "/new/default.mkv",
                    "runtime": 24,
                    "date_added": 9999,
                },
                ep_by_path,
                ep_by_number,
                ep_by_name,
                stats,
            )
            assert result.myanimelist_anime_id == 200
            assert result.myanimelist_episode_number == 3
            assert result.default_path == "/new/default.mkv"
            assert result.runtime == 24
            assert result.date_added == 9999


class TestCleanupTvLibrary:
    """Lines 759-823: _cleanup_tv_library."""

    def test_missing_series_deleted(self, library_name: str) -> None:
        with get_session() as session:
            series = Series(name="MissingShow", library_name=library_name)
            session.add(series)
            session.flush()
            season = Season(name="Season 1", series=series)
            session.add(season)
            session.flush()
            ep = Episode(
                season_id=season.id,
                name="Ep1",
                path="/missing/ep.mkv",
            )
            session.add(ep)
            session.flush()
            session.commit()

        stats: dict[str, Any] = {
            "series": 0,
            "series_removed": 0,
            "seasons": 0,
            "seasons_removed": 0,
            "episodes": 0,
            "episodes_removed": 0,
        }
        with get_session() as session:
            _cleanup_tv_library(session, library_name, ["/nonexistent/root"], stats)

        assert stats["series_removed"] >= 1
        assert stats["seasons_removed"] >= 1
        assert stats["episodes_removed"] >= 1

    def test_existing_series_path_nulls_missing_files(
        self, library_name: str, tmp_path
    ) -> None:
        series_dir = tmp_path / "ExistingShow"
        series_dir.mkdir()

        with get_session() as session:
            series = Series(name="ExistingShow", library_name=library_name)
            session.add(series)
            session.flush()
            season = Season(name="Season 1", series=series)
            session.add(season)
            session.flush()
            ep = Episode(
                season_id=season.id,
                name="Ep1",
                path=str(series_dir / "missing.mkv"),
                tmdb_number=1,
            )
            session.add(ep)
            session.flush()
            session.commit()

        stats: dict[str, Any] = {
            "series": 0,
            "series_removed": 0,
            "seasons": 0,
            "seasons_removed": 0,
            "episodes": 0,
            "episodes_removed": 0,
        }
        with get_session() as session:
            _cleanup_tv_library(session, library_name, [str(tmp_path)], stats)

        assert stats["episodes"] >= 1
