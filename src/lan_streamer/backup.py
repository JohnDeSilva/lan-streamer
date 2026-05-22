import os
import re
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

from sqlalchemy import create_engine, text

from .config import config, CONFIG_FILE

logger = logging.getLogger(__name__)


def get_backup_time_from_filename(filename: str) -> Optional[datetime]:
    """
    Extracts the backup timestamp from a standardized backup filename.
    Format: YYYYMMDD_HHMMSS_filename
    """
    match_object = re.match(r"^(\d{8}_\d{6})_", filename)
    if match_object:
        try:
            return datetime.strptime(match_object.group(1), "%Y%m%d_%H%M%S")
        except ValueError:
            return None
    return None


def cleanup_old_backups(
    backup_directory_path: Path, target_suffix: str, retention_limit: int
) -> None:
    """
    Enforces the retention policy by removing backup files matching the specified
    suffix when their age exceeds retention_limit in days.
    """
    if not backup_directory_path.is_dir() or retention_limit <= 0:
        return

    try:
        backup_files: List[Tuple[datetime, Path]] = []
        for file_item in backup_directory_path.iterdir():
            if file_item.is_file() and file_item.name.endswith(target_suffix):
                parsed_time: Optional[datetime] = get_backup_time_from_filename(
                    file_item.name
                )
                if parsed_time is not None:
                    backup_files.append((parsed_time, file_item))

        current_time: datetime = datetime.now()
        for parsed_time, file_path_to_delete in backup_files:
            days_old: int = (current_time - parsed_time).days
            if days_old > retention_limit:
                try:
                    file_path_to_delete.unlink()
                    logger.info(
                        f"Deleted old backup: {file_path_to_delete.name} (age: {days_old} days, limit: {retention_limit} days)"
                    )
                except Exception as exception_instance:
                    logger.warning(
                        f"Failed to delete old backup file {file_path_to_delete}: {exception_instance}"
                    )
    except Exception as exception_instance:
        logger.exception(f"Error during backup retention cleanup: {exception_instance}")


def create_config_backup() -> bool:
    """
    Creates a snapshot backup of the configuration file.
    """
    source_path: Path = CONFIG_FILE
    if not source_path.is_file():
        logger.info("Configuration file does not exist yet; skipping backup.")
        return False

    backup_directory: Path = Path(config.backup_directory)
    try:
        backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp_string: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename: str = f"{timestamp_string}_{source_path.name}"
        destination_path: Path = backup_directory / backup_filename

        shutil.copy2(source_path, destination_path)
        logger.info(f"Successfully created configuration backup: {destination_path}")

        cleanup_old_backups(
            backup_directory, f"_{source_path.name}", config.config_backup_retention
        )
        return True
    except Exception as exception_instance:
        logger.exception(f"Failed to create configuration backup: {exception_instance}")
        return False


def create_database_backup() -> bool:
    """
    Creates a snapshot backup of the main SQLite database file.
    """
    source_path: Path = Path(os.getenv("LAN_STREAMER_DB", config.database_path))
    if not source_path.is_file():
        logger.info("Database file does not exist yet; skipping backup.")
        return False

    backup_directory: Path = Path(config.backup_directory)
    try:
        backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp_string: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename: str = f"{timestamp_string}_{source_path.name}"
        destination_path: Path = backup_directory / backup_filename

        shutil.copy2(source_path, destination_path)
        logger.info(f"Successfully created database backup: {destination_path}")

        cleanup_old_backups(
            backup_directory, f"_{source_path.name}", config.database_backup_retention
        )
        return True
    except Exception as exception_instance:
        logger.exception(f"Failed to create database backup: {exception_instance}")
        return False


def perform_scheduled_backups() -> None:
    """
    Executed at startup to ensure automatic configuration and database backups
    are generated according to configured frequency schedules.
    """
    logger.info("Evaluating scheduled backup criteria at application startup.")
    backup_directory: Path = Path(config.backup_directory)
    try:
        backup_directory.mkdir(parents=True, exist_ok=True)
    except Exception as exception_instance:
        logger.warning(
            f"Could not initialize backup directory {backup_directory}: {exception_instance}"
        )
        return

    current_time: datetime = datetime.now()

    # 1. Process Configuration Backup Schedule
    config_source: Path = CONFIG_FILE
    config_frequency: int = config.config_backup_frequency
    config_suffix: str = f"_{config_source.name}"

    if config_frequency == 0:
        logger.info("Configuration backup frequency is set to 0 (startup); backing up.")
        create_config_backup()
    elif config_frequency > 0:
        latest_backup_time: Optional[datetime] = None
        for file_item in backup_directory.iterdir():
            if file_item.is_file() and file_item.name.endswith(config_suffix):
                parsed_time: Optional[datetime] = get_backup_time_from_filename(
                    file_item.name
                )
                if parsed_time is not None:
                    if latest_backup_time is None or parsed_time > latest_backup_time:
                        latest_backup_time = parsed_time

        if latest_backup_time is None:
            logger.info(
                "No existing configuration backup found; generating initial copy."
            )
            create_config_backup()
        else:
            days_elapsed: int = (current_time - latest_backup_time).days
            if days_elapsed >= config_frequency:
                logger.info(
                    f"Configuration backup interval threshold reached ({days_elapsed} >= {config_frequency} days); generating backup."
                )
                create_config_backup()
            else:
                logger.debug(
                    f"Configuration backup interval not yet reached ({days_elapsed} < {config_frequency} days)."
                )

    # 2. Process Database Backup Schedule
    database_source: Path = Path(os.getenv("LAN_STREAMER_DB", config.database_path))
    database_frequency: int = config.database_backup_frequency
    database_suffix: str = f"_{database_source.name}"

    if database_frequency == 0:
        logger.info("Database backup frequency is set to 0 (startup); backing up.")
        create_database_backup()
    elif database_frequency > 0:
        latest_backup_time = None
        for file_item in backup_directory.iterdir():
            if file_item.is_file() and file_item.name.endswith(database_suffix):
                parsed_time = get_backup_time_from_filename(file_item.name)
                if parsed_time is not None:
                    if latest_backup_time is None or parsed_time > latest_backup_time:
                        latest_backup_time = parsed_time

        if latest_backup_time is None:
            logger.info("No existing database backup found; generating initial copy.")
            create_database_backup()
        else:
            days_elapsed = (current_time - latest_backup_time).days
            if days_elapsed >= database_frequency:
                logger.info(
                    f"Database backup interval threshold reached ({days_elapsed} >= {database_frequency} days); generating backup."
                )
                create_database_backup()
            else:
                logger.debug(
                    f"Database backup interval not yet reached ({days_elapsed} < {database_frequency} days)."
                )


def restore_config_backup(backup_file_path: str) -> bool:
    """
    Safely validates and restores a configuration backup file.
    Attempts to parse the file before overwriting active configuration.
    """
    logger.info(f"Initiating configuration restore from {backup_file_path}")
    source_backup_path: Path = Path(backup_file_path)

    if not source_backup_path.is_file():
        logger.error(
            f"Configuration backup target file does not exist: {backup_file_path}"
        )
        return False

    # Attempt to read and validate JSON contents
    try:
        with open(source_backup_path, "r") as file_handle:
            parsed_data = json.load(file_handle)
            if not isinstance(parsed_data, dict):
                logger.error(
                    "Configuration backup does not contain a valid JSON dictionary structure."
                )
                return False
    except Exception as exception_instance:
        logger.exception(
            f"Validation failed: unable to parse configuration backup file: {exception_instance}"
        )
        return False

    # Perform active configuration file replacement
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_backup_path, CONFIG_FILE)
        logger.info("Configuration file successfully overwritten with backup contents.")

        # Refresh active in-memory configuration state
        config.load()
        return True
    except Exception as exception_instance:
        logger.exception(
            f"Critical error overwriting configuration file: {exception_instance}"
        )
        return False


def restore_database_backup(backup_file_path: str) -> bool:
    """
    Safely validates and restores a SQLite database backup file.
    Inspects integrity and schema presence prior to replacing active tables.
    """
    logger.info(f"Initiating database restore from {backup_file_path}")
    source_backup_path: Path = Path(backup_file_path)

    if not source_backup_path.is_file():
        logger.error(f"Database backup target file does not exist: {backup_file_path}")
        return False

    # Validate database integrity via temporary isolated engine connection
    try:
        validation_engine = create_engine(f"sqlite:///{source_backup_path}")
        with validation_engine.connect() as connection_instance:
            integrity_result: Optional[str] = connection_instance.execute(
                text("PRAGMA integrity_check")
            ).scalar()
            if integrity_result != "ok":
                logger.error(
                    f"Database backup failed integrity inspection: {integrity_result}"
                )
                return False

            # Verify standard schema table inclusion
            connection_instance.execute(text("SELECT count(*) FROM series")).scalar()
        validation_engine.dispose()
    except Exception as exception_instance:
        logger.exception(
            f"Validation failed: database backup file is corrupt or unreadable: {exception_instance}"
        )
        return False

    # Perform active database file replacement
    target_database_path: Path = Path(
        os.getenv("LAN_STREAMER_DB", config.database_path)
    )
    try:
        from .db import get_engine

        # Explicitly terminate shared connection pool to release operational file handles
        get_engine().dispose()

        target_database_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_backup_path, target_database_path)
        logger.info(
            "Database file successfully overwritten with verified backup state."
        )
        return True
    except Exception as exception_instance:
        logger.exception(
            f"Critical error overwriting database file: {exception_instance}"
        )
        return False
