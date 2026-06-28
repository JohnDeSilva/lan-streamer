"""
Async database session management using SQLAlchemy's ``AsyncSession``.

Provides :func:`get_async_engine`, :func:`get_async_session_factory`,
and :func:`get_async_session` for async database access via ``aiosqlite``.
The sync ``Engine`` continues unchanged (dual-engine setup).
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lan_streamer.system.config import config

logger = logging.getLogger(__name__)

_DEFAULT_DB_FILE = Path(os.getenv("LAN_STREAMER_DB", config.database_path))

# Module-level singletons (reset by tests)
_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def _get_runtime_db_file() -> Path:
    db_module = sys.modules.get("lan_streamer.db")
    if db_module and hasattr(db_module, "DB_FILE"):
        return Path(getattr(db_module, "DB_FILE"))
    return _DEFAULT_DB_FILE


def get_async_engine() -> AsyncEngine:
    """Return (or create) the shared async engine with WAL configuration."""
    global _async_engine
    if _async_engine is None:
        db_file = _get_runtime_db_file()
        _async_engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_file}",
            connect_args={"check_same_thread": False},
        )
    return _async_engine


_dispose_engine = get_async_engine  # alias for test cleanup


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return (or create) the shared async session factory."""
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_async_engine(),
        )
    return _AsyncSessionLocal


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding an :class:`AsyncSession`.

    Usage::

        async with get_async_session() as session:
            result = await session.execute(select(Series))
    """
    factory = get_async_session_factory()
    async with factory() as session:
        logger.debug("Async database session opened.")
        try:
            yield session
            logger.debug("Async database session committing...")
            await session.commit()
            logger.debug("Async database session committed successfully.")
        except Exception as exc:
            logger.warning(
                f"Async database session rollback triggered due to error: {exc}"
            )
            await session.rollback()
            raise
        finally:
            logger.debug("Async database session closed.")
            await session.close()
