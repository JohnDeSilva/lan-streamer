from unittest.mock import patch

import pytest
from sqlalchemy import text

from lan_streamer import db


@pytest.fixture
def mock_db_file(tmp_path) -> None:
    return tmp_path / "library.db"


def test_init_db(mock_db_file) -> None:
    db._db_initialized = False
    db.init_db()
    assert mock_db_file.parent.exists()


def test_get_session_rollback() -> None:
    from lan_streamer.db import get_session

    with pytest.raises(ValueError), get_session():
        raise ValueError("Test rollback trigger")


def test_db_edge_cases() -> None:
    # Reset initialized flag to test full init_db path
    db._db_initialized = False
    # init_db with mkdir exception
    with patch("pathlib.Path.mkdir", side_effect=OSError("Write error")):
        assert db.init_db() is False


def test_wal_mode_enabled() -> None:
    db.init_db()
    with db.get_session() as session:
        result = session.execute(text("PRAGMA journal_mode")).fetchone()
        assert result[0].lower() == "wal"


def test_unicode_aware_lower_function_registered() -> None:
    """SQLite's lower() must be unicode-aware so ilike/func.lower match non-ASCII."""
    db.init_db()
    with db.get_session() as session:
        result = session.execute(text("SELECT lower('Schön')")).fetchone()
        assert result[0] == "schön"
        result = session.execute(text("SELECT lower('DIE ÄRZTE')")).fetchone()
        assert result[0] == "die ärzte"
