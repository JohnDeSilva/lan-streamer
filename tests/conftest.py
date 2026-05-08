import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def protect_user_dirs(tmp_path):
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

    with (
        patch("lan_streamer.config.CONFIG_FILE", config_file),
        patch("lan_streamer.db.DB_FILE", db_file),
        patch("lan_streamer.tmdb.CACHE_DIR", cache_dir),
    ):
        # Reload config instance so it points to the new path
        # But note that the Config() instance in lan_streamer.config
        # has already been initialized with the old path.
        # So we should also patch the already-initialized object or reset it.
        lan_streamer.config.config.libraries = {}
        lan_streamer.config.config.jellyfin_url = ""
        lan_streamer.config.config.jellyfin_api_key = ""
        lan_streamer.config.config.tmdb_api_key = ""
        yield
