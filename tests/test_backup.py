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

    # Create 10 mock backup files with chronological timestamps
    base_time: datetime = datetime(2026, 1, 1, 10, 0, 0)
    for index in range(10):
        current_time: datetime = base_time + timedelta(days=index)
        filename: str = f"{current_time.strftime('%Y%m%d_%H%M%S')}_config.json"
        (backup_directory / filename).write_text("mock content")

    # Enforce retention limit of 3 files
    backup.cleanup_old_backups(backup_directory, "_config.json", 3)

    # Verify exactly 3 newest files remain
    remaining_files: list[Path] = sorted(list(backup_directory.glob("*_config.json")))
    assert len(remaining_files) == 3

    # The oldest timestamp remaining should be day 7 (index 7, 8, 9 remain)
    oldest_remaining: str = remaining_files[0].name
    assert oldest_remaining.startswith("20260108")


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
