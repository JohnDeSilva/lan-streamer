"""SQLAlchemy engine and session management for the agent database."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from scan_agent.db.models import SCHEMA_VERSION, Base, SchemaVersion

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_session_factories: dict[int, sessionmaker[Session]] = {}


def create_engine_for_database(database_path: str | Path) -> Engine:
    """Create a SQLite engine for *database_path* with WAL pragmas.

    The parent directory is created when missing.
    """
    path = Path(database_path).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    logger.info("Created SQLite engine for %s", path)
    return engine


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a cached sessionmaker bound to *engine*."""
    factory = _session_factories.get(id(engine))
    if factory is None:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        _session_factories[id(engine)] = factory
    return factory


@contextmanager
def get_session(engine: Engine) -> Generator[Session]:
    """Yield a :class:`Session` bound to *engine*, committing on success.

    Rolls back and re-raises on any exception; always closes the session.
    """
    session = get_session_factory(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_database(engine: Engine) -> None:
    """Create all tables and ensure the schema version row exists.

    Idempotent: safe to call on every boot.
    """
    Base.metadata.create_all(engine)
    with get_session(engine) as session:
        version_row = session.get(SchemaVersion, 1)
        if version_row is None:
            session.add(SchemaVersion(id=1, version=SCHEMA_VERSION))
            logger.info(
                "Initialised agent database at schema version %d", SCHEMA_VERSION
            )
        elif version_row.version != SCHEMA_VERSION:
            logger.warning(
                "Agent database schema version %d does not match expected %d",
                version_row.version,
                SCHEMA_VERSION,
            )
