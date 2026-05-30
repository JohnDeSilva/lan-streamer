import logging
import os
import sys
from pathlib import Path
from typing import Any, Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine

from lan_streamer.system.config import config

logger = logging.getLogger(__name__)

# Fallback default DB_FILE
_DEFAULT_DB_FILE = Path(os.getenv("LAN_STREAMER_DB", config.database_path))


def _get_runtime_db_file() -> Path:
    db_module = sys.modules.get("lan_streamer.db")
    if db_module and hasattr(db_module, "DB_FILE"):
        return Path(getattr(db_module, "DB_FILE"))
    return _DEFAULT_DB_FILE


def get_engine() -> Engine:
    db_module = sys.modules.get("lan_streamer.db")
    _engine = getattr(db_module, "_engine", None) if db_module else None
    if _engine is None:
        db_file = _get_runtime_db_file()
        _engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

        if db_module:
            setattr(db_module, "_engine", _engine)

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    db_module = sys.modules.get("lan_streamer.db")
    _SessionLocal = getattr(db_module, "_SessionLocal", None) if db_module else None
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
        if db_module:
            setattr(db_module, "_SessionLocal", _SessionLocal)
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    session = session_factory()
    logger.debug("Database session opened.")
    try:
        yield session
        logger.debug("Database session committing...")
        session.commit()
        logger.debug("Database session committed successfully.")
    except Exception as exc:
        logger.warning(f"Database session rollback triggered due to error: {exc}")
        session.rollback()
        raise
    finally:
        logger.debug("Database session closed.")
        session.close()


def init_db() -> bool:
    """
    Initializes the database by running Alembic migrations.
    Ensures the DB directory exists.
    Returns True if the database was successfully initialized/upgraded.
    """
    db_module = sys.modules.get("lan_streamer.db")
    _db_initialized = (
        getattr(db_module, "_db_initialized", False) if db_module else False
    )
    if _db_initialized:
        logger.debug(
            "Database already initialized in this session; skipping migration check."
        )
        return False

    db_file = _get_runtime_db_file()
    logger.info(f"Initializing database at: '{db_file}'")
    try:
        db_file.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning(f"Could not create database directory {db_file.parent}: {exc}")
        return False

    try:
        from alembic.config import Config
        from alembic import command

        if getattr(sys, "frozen", False):
            base_path: Path = Path(getattr(sys, "_MEIPASS"))
        else:
            base_path = Path(__file__).parent.parent.parent.parent

        alembic_ini_path: Path = base_path / "alembic.ini"
        alembic_directory_path: Path = base_path / "alembic"

        logger.info(f"Loading Alembic configuration from: '{alembic_ini_path}'")
        alembic_config: Config = Config(str(alembic_ini_path))

        # Dynamically set options to reference the absolute runtime paths
        alembic_config.set_main_option("script_location", str(alembic_directory_path))
        alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")

        logger.info("Executing database migration to latest revision (head)...")
        command.upgrade(alembic_config, "head")
        logger.info("Database migration completed successfully.")

        if db_module:
            setattr(db_module, "_db_initialized", True)
        return True
    except Exception as exc:
        logger.error(f"Failed to run database migrations: {exc}", exc_info=True)
        return False
