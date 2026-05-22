import os
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator
from unittest.mock import patch

from sqlalchemy import create_engine, text

from lan_streamer.config import config
from lan_streamer import backup


@pytest.fixture
def backup_environment(tmp_path: Path) -> Generator[Path, None, None]:
    test_config_file: Path = tmp_path / "config.json"
    test_config_file.write_text(json.dumps({"sort_mode": "Alphabetical"}))

    test_database_file: Path = tmp_path / "library.db"
    test_engine = create_engine(f"sqlite:///{test_database_file}")
    with test_engine.connect() as connection_instance:
        connection_instance.execute(
            text(
                "CREATE TABLE IF NOT EXISTS series (id INTEGER PRIMARY KEY, library_name TEXT, name TEXT)"
            )
        )
    test_engine.dispose()

    test_backup_directory: Path = tmp_path / "backups"
    test_backup_directory.mkdir(parents=True, exist_ok=True)

    with (
        patch("lan_streamer.backup.CONFIG_FILE", test_config_file),
        patch("lan_streamer.config.CONFIG_FILE", test_config_file),
        patch.object(config, "backup_directory", str(test_backup_directory)),
        patch.object(config, "database_path", str(test_database_file)),
        patch.dict(os.environ, {"LAN_STREAMER_DB": str(test_database_file)}),
    ):
        yield tmp_path


def test_get_backup_time_from_filename() -> None:
    valid_time = backup.get_backup_time_from_filename("20260513_120055_config.json")
    assert valid_time is not None
    assert valid_time.year == 2026
    assert valid_time.month == 5
    assert valid_time.day == 13
    assert valid_time.hour == 12
    assert valid_time.minute == 0
    assert valid_time.second == 55

    invalid_time1 = backup.get_backup_time_from_filename("invalid_filename.json")
    assert invalid_time1 is None

    invalid_time2 = backup.get_backup_time_from_filename("99999999_999999_config.json")
    assert invalid_time2 is None


def test_cleanup_old_backups_retention(backup_environment: Path) -> None:
    backup_directory: Path = backup_environment / "backups"

    # Create 10 mock backup files with chronological timestamps relative to now
    base_time: datetime = datetime.now()
    for index in range(10):
        # index 0 is 9 days ago, index 9 is today (0 days ago)
        file_time: datetime = base_time - timedelta(days=(9 - index))
        filename: str = f"{file_time.strftime('%Y%m%d_%H%M%S')}_config.json"
        (backup_directory / filename).write_text("mock content")

    # Enforce retention limit of 3 days
    backup.cleanup_old_backups(backup_directory, "_config.json", 3)

    # Verify that files older than 3 days are deleted (leaving 0, 1, 2, and 3 days ago files remaining)
    remaining_files: list[Path] = sorted(list(backup_directory.glob("*_config.json")))
    assert len(remaining_files) == 4

    # The oldest timestamp remaining should be 3 days ago
    three_days_ago: datetime = base_time - timedelta(days=3)
    oldest_remaining: str = remaining_files[0].name
    assert oldest_remaining.startswith(three_days_ago.strftime("%Y%m%d"))


def test_create_config_backup(backup_environment: Path) -> None:
    backup_directory: Path = backup_environment / "backups"
    config.config_backup_retention = 5

    success: bool = backup.create_config_backup()
    assert success is True

    backup_files: list[Path] = list(backup_directory.glob("*_config.json"))
    assert len(backup_files) == 1
    assert "sort_mode" in backup_files[0].read_text()


def test_create_database_backup(backup_environment: Path) -> None:
    backup_directory: Path = backup_environment / "backups"
    config.database_backup_retention = 5

    success: bool = backup.create_database_backup()
    assert success is True

    backup_files: list[Path] = list(backup_directory.glob("*_library.db"))
    assert len(backup_files) == 1


def test_perform_scheduled_backups_frequency_zero(backup_environment: Path) -> None:
    backup_directory: Path = backup_environment / "backups"
    config.config_backup_frequency = 0
    config.database_backup_frequency = 0

    backup.perform_scheduled_backups()

    config_backups: list[Path] = list(backup_directory.glob("*_config.json"))
    database_backups: list[Path] = list(backup_directory.glob("*_library.db"))
    assert len(config_backups) == 1
    assert len(database_backups) == 1


def test_perform_scheduled_backups_frequency_interval(backup_environment: Path) -> None:
    backup_directory: Path = backup_environment / "backups"
    config.config_backup_frequency = 7
    config.database_backup_frequency = 7
    config.config_backup_retention = 10
    config.database_backup_retention = 10

    # 1. Initially empty backup directory -> should generate initial backups
    backup.perform_scheduled_backups()
    assert len(list(backup_directory.glob("*_config.json"))) == 1
    assert len(list(backup_directory.glob("*_library.db"))) == 1

    # Clear generated files to simulate precise old backups
    for file_item in backup_directory.iterdir():
        file_item.unlink()

    # 2. Simulate recent backup (1 day ago) -> should NOT generate backup
    recent_time: datetime = datetime.now() - timedelta(days=1)
    recent_filename: str = f"{recent_time.strftime('%Y%m%d_%H%M%S')}_config.json"
    (backup_directory / recent_filename).write_text("old config")

    backup.perform_scheduled_backups()
    assert (
        len(list(backup_directory.glob("*_config.json"))) == 1
    )  # Only old file remains

    # 3. Simulate stale backup (8 days ago) -> should generate fresh backup
    # Clear the recent backup first
    (backup_directory / recent_filename).unlink()
    stale_time: datetime = datetime.now() - timedelta(days=8)
    stale_filename: str = f"{stale_time.strftime('%Y%m%d_%H%M%S')}_config.json"
    (backup_directory / stale_filename).write_text("stale config")

    backup.perform_scheduled_backups()
    assert (
        len(list(backup_directory.glob("*_config.json"))) == 2
    )  # New backup generated


def test_restore_config_backup_success(backup_environment: Path) -> None:
    target_config_file: Path = backup_environment / "config.json"
    backup_file: Path = backup_environment / "valid_backup.json"
    backup_file.write_text(json.dumps({"restored_key": "success_value"}))

    success: bool = backup.restore_config_backup(str(backup_file))
    assert success is True

    # Active file should be updated
    assert "success_value" in target_config_file.read_text()


def test_restore_config_backup_invalid(backup_environment: Path) -> None:
    target_config_file: Path = backup_environment / "config.json"
    original_content: str = target_config_file.read_text()

    # 1. Non-existent file
    assert backup.restore_config_backup("/non/existent/path.json") is False

    # 2. Corrupt JSON content
    corrupt_backup: Path = backup_environment / "corrupt_backup.json"
    corrupt_backup.write_text("{invalid json structure")
    assert backup.restore_config_backup(str(corrupt_backup)) is False

    # Active file must remain completely untouched
    assert target_config_file.read_text() == original_content


def test_restore_database_backup_success(backup_environment: Path) -> None:
    target_database_file: Path = backup_environment / "library.db"
    valid_backup_db: Path = backup_environment / "valid_backup.db"

    # Generate a valid backup database containing the required schema tables
    test_engine = create_engine(f"sqlite:///{valid_backup_db}")
    with test_engine.connect() as connection_instance:
        connection_instance.execute(
            text(
                "CREATE TABLE IF NOT EXISTS series (id INTEGER PRIMARY KEY, library_name TEXT, name TEXT)"
            )
        )
    test_engine.dispose()

    success: bool = backup.restore_database_backup(str(valid_backup_db))
    assert success is True
    assert target_database_file.is_file()


def test_restore_database_backup_invalid(backup_environment: Path) -> None:
    # 1. Non-existent database file
    assert backup.restore_database_backup("/non/existent/db.db") is False

    # 2. Corrupt file content failing integrity inspection
    corrupt_db: Path = backup_environment / "corrupt.db"
    corrupt_db.write_text("plain text file not an sqlite database")
    assert backup.restore_database_backup(str(corrupt_db)) is False


# ---------------------------------------------------------------------------
# create_config_backup — missing source
# ---------------------------------------------------------------------------


def test_create_config_backup_missing_source(backup_environment: Path) -> None:
    """create_config_backup returns False when the config file does not exist."""
    with patch(
        "lan_streamer.backup.CONFIG_FILE", backup_environment / "nonexistent.json"
    ):
        result = backup.create_config_backup()
    assert result is False


# ---------------------------------------------------------------------------
# create_database_backup — missing source
# ---------------------------------------------------------------------------


def test_create_database_backup_missing_source(backup_environment: Path) -> None:
    """create_database_backup returns False when the database file does not exist."""
    with patch.dict(
        os.environ, {"LAN_STREAMER_DB": str(backup_environment / "no_db.db")}
    ):
        result = backup.create_database_backup()
    assert result is False


# ---------------------------------------------------------------------------
# cleanup_old_backups — guards
# ---------------------------------------------------------------------------


def test_cleanup_old_backups_zero_retention(backup_environment: Path) -> None:
    """Retention limit ≤ 0 should return immediately without deleting anything."""
    backup_directory: Path = backup_environment / "backups"
    (backup_directory / "20260101_000000_config.json").write_text("content")
    (backup_directory / "20260102_000000_config.json").write_text("content")

    backup.cleanup_old_backups(backup_directory, "_config.json", 0)

    remaining = list(backup_directory.glob("*_config.json"))
    assert len(remaining) == 2  # Nothing deleted


def test_cleanup_old_backups_non_dir_path(tmp_path: Path) -> None:
    """Passing a non-existent path should return immediately without error."""
    non_existent = tmp_path / "does_not_exist"
    # Should not raise
    backup.cleanup_old_backups(non_existent, "_config.json", 5)


# ---------------------------------------------------------------------------
# restore_config_backup — additional error paths
# ---------------------------------------------------------------------------


def test_restore_config_backup_non_dict_json(backup_environment: Path) -> None:
    """JSON that does not parse to a dict (e.g. a list) should return False."""
    bad_json_file: Path = backup_environment / "list_backup.json"
    bad_json_file.write_text("[1, 2, 3]")  # Valid JSON, but not a dict

    result = backup.restore_config_backup(str(bad_json_file))
    assert result is False


def test_restore_config_backup_copy_error(backup_environment: Path) -> None:
    """If shutil.copy2 raises during restore, the function should return False."""
    good_json_file: Path = backup_environment / "good_backup.json"
    good_json_file.write_text(json.dumps({"key": "value"}))

    with patch("shutil.copy2", side_effect=OSError("Permission denied")):
        result = backup.restore_config_backup(str(good_json_file))

    assert result is False


# ---------------------------------------------------------------------------
# restore_database_backup — additional error paths
# ---------------------------------------------------------------------------


def test_restore_database_backup_copy_error(backup_environment: Path) -> None:
    """If shutil.copy2 raises during DB restore, the function should return False."""
    valid_backup_db: Path = backup_environment / "valid2.db"

    test_engine = create_engine(f"sqlite:///{valid_backup_db}")
    with test_engine.connect() as connection_instance:
        connection_instance.execute(
            text(
                "CREATE TABLE IF NOT EXISTS series "
                "(id INTEGER PRIMARY KEY, library_name TEXT, name TEXT)"
            )
        )
    test_engine.dispose()

    with patch("shutil.copy2", side_effect=OSError("Disk full")):
        result = backup.restore_database_backup(str(valid_backup_db))

    assert result is False


# ---------------------------------------------------------------------------
# perform_scheduled_backups — directory creation error
# ---------------------------------------------------------------------------


def test_perform_scheduled_backups_dir_creation_failure(
    backup_environment: Path,
) -> None:
    """When the backup directory cannot be created, the function returns early."""
    with (
        patch.object(config, "backup_directory", "/root/cannot_create_this"),
        patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")),
    ):
        # Should NOT raise
        backup.perform_scheduled_backups()


def test_cleanup_old_backups_unlink_exception(backup_environment: Path) -> None:
    backup_directory: Path = backup_environment / "backups"
    (backup_directory / "20260101_000000_config.json").write_text("content")
    (backup_directory / "20260102_000000_config.json").write_text("content")

    with patch("pathlib.Path.unlink", side_effect=OSError("Access denied")):
        # Should not raise exception
        backup.cleanup_old_backups(backup_directory, "_config.json", 1)


def test_cleanup_old_backups_general_exception(backup_environment: Path) -> None:
    backup_directory: Path = backup_environment / "backups"
    with patch("pathlib.Path.iterdir", side_effect=OSError("Disk failure")):
        # Should not raise exception
        backup.cleanup_old_backups(backup_directory, "_config.json", 1)


def test_create_config_backup_exception(backup_environment: Path) -> None:
    with patch("shutil.copy2", side_effect=Exception("Copy failed")):
        assert backup.create_config_backup() is False


def test_create_database_backup_exception(backup_environment: Path) -> None:
    with patch("shutil.copy2", side_effect=Exception("Copy failed")):
        assert backup.create_database_backup() is False


def test_perform_scheduled_backups_database_recent_and_stale(
    backup_environment: Path,
) -> None:
    backup_directory: Path = backup_environment / "backups"
    config.database_backup_frequency = 5
    config.database_backup_retention = 10

    # 1. Recent database backup (2 days ago)
    recent_time = datetime.now() - timedelta(days=2)
    recent_name = f"{recent_time.strftime('%Y%m%d_%H%M%S')}_library.db"
    (backup_directory / recent_name).write_text("recent db content")

    backup.perform_scheduled_backups()
    # No new database backup should be generated (still 1 db backup in folder)
    db_backups = list(backup_directory.glob("*_library.db"))
    assert len(db_backups) == 1

    # Clear files
    for f in backup_directory.iterdir():
        f.unlink()

    # 2. Stale database backup (6 days ago)
    stale_time = datetime.now() - timedelta(days=6)
    stale_name = f"{stale_time.strftime('%Y%m%d_%H%M%S')}_library.db"
    (backup_directory / stale_name).write_text("stale db content")

    backup.perform_scheduled_backups()
    # Stale means a new backup should be generated, total 2 files
    db_backups = list(backup_directory.glob("*_library.db"))
    assert len(db_backups) == 2


def test_restore_database_integrity_fail(backup_environment: Path) -> None:
    corrupt_backup: Path = backup_environment / "corrupt_backup.db"
    corrupt_backup.write_text("mock sqlite file")

    with patch("sqlalchemy.engine.base.Connection.execute") as mock_execute:
        # Mock integrity_check result to be "corrupted"
        mock_execute.return_value.scalar.return_value = "corrupted"
        assert backup.restore_database_backup(str(corrupt_backup)) is False
