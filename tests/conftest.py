import os
import pytest
from unittest.mock import patch

# Force offscreen rendering so individual tests run seamlessly in GUI-less IDE test explorers
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(autouse=True)
def protect_user_dirs(tmp_path) -> None:
    """
    Ensure no test can ever overwrite the user's actual config or DB.
    We patch all the paths to point to tmp_path.
    """
    import lan_streamer.config
    import lan_streamer.db
    import lan_streamer.tmdb

    config_file = tmp_path / "config.json"
    db_file = tmp_path / "library.db"
    cache_dir = tmp_path / "cache" / "images"

    # Properly dispose of the existing engine to avoid ResourceWarnings
    if hasattr(lan_streamer.db, "_engine") and lan_streamer.db._engine is not None:
        lan_streamer.db._engine.dispose()

    # Reset lazy database objects
    lan_streamer.db._engine = None
    lan_streamer.db._SessionLocal = None

    with (
        patch("lan_streamer.config.CONFIG_FILE", config_file),
        patch("lan_streamer.db.DB_FILE", db_file),
        patch("lan_streamer.tmdb.CACHE_DIR", cache_dir),
    ):
        # Initialize schema for tests
        lan_streamer.db.Base.metadata.create_all(lan_streamer.db.get_engine())

        # Reload config instance so it points to the new path
        lan_streamer.config.config.libraries = {}
        lan_streamer.config.config.jellyfin_url = ""
        lan_streamer.config.config.jellyfin_api_key = ""
        lan_streamer.config.config.tmdb_api_key = ""
        lan_streamer.config.config.database_path = str(db_file)
        lan_streamer.config.config.log_directory = str(tmp_path / "logs")
        lan_streamer.config.config.enable_global_file_logging = False

        yield

        # Dispose engine after test too
        if lan_streamer.db._engine is not None:
            lan_streamer.db._engine.dispose()
