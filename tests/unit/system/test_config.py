import json
import pytest
from unittest.mock import patch
from lan_streamer.system.config import Config


@pytest.fixture
def mock_config_file(tmp_path) -> None:
    test_config_path = tmp_path / "config.json"
    with patch("lan_streamer.system.config.CONFIG_FILE", test_config_path):
        yield test_config_path


def test_config_initialization(mock_config_file) -> None:
    config = Config()
    assert config.libraries == {}
    assert config.jellyfin_url == ""
    assert config.jellyfin_api_key == ""
    assert config.tmdb_api_key == ""
    assert config.sync_history_on_start is True
    assert config.filter_out_watched is False
    assert config.sort_mode == "Alphabetical"
    assert config.max_cache_size_gb == 15.0
    assert config.vlc_buffer_ms == 3000
    assert config.backup_directory.endswith("backups")
    assert config.config_backup_frequency == 0
    assert config.database_backup_frequency == 0
    assert config.config_backup_retention == 7
    assert config.database_backup_retention == 7


def test_config_load_existing(mock_config_file) -> None:
    mock_config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(mock_config_file, "w") as f:
        json.dump(
            {
                "database_path": "/path/to/db.db",
                "log_directory": "/path/to/logs",
                "log_level": "DEBUG",
                "config_backup_frequency": 3,
                "database_backup_frequency": 5,
            },
            f,
        )

    config = Config()
    assert config.database_path == "/path/to/db.db"
    assert config.log_directory == "/path/to/logs"
    assert config.log_level == "DEBUG"
    assert config.config_backup_frequency == 3
    assert config.database_backup_frequency == 5

    # DB-backed settings
    config.libraries = {
        "TestLib": {
            "type": "tv",
            "paths": ["/path/to/test"],
            "show_future_episodes": True,
        }
    }
    config.jellyfin_url = "http://test"
    config.jellyfin_api_key = "test_key"
    config.tmdb_api_key = "tmdb_key"
    config.sync_history_on_start = False
    config.filter_out_watched = True
    config.sort_mode = "Date Added (Newest)"
    config.max_cache_size_gb = 20.5
    config.vlc_buffer_ms = 7500

    config.save_to_db()

    config2 = Config()
    config2.load_from_db()
    assert config2.libraries == {
        "TestLib": {
            "type": "tv",
            "paths": ["/path/to/test"],
            "show_future_episodes": True,
        }
    }
    assert config2.jellyfin_url == "http://test"
    assert config2.jellyfin_api_key == "test_key"
    assert config2.tmdb_api_key == "tmdb_key"
    assert config2.sync_history_on_start is False
    assert config2.filter_out_watched is True
    assert config2.sort_mode == "Date Added (Newest)"
    assert config2.max_cache_size_gb == 20.5
    assert config2.vlc_buffer_ms == 7500


def test_config_add_remove_library(mock_config_file) -> None:
    config = Config()
    config.libraries = {}
    config.add_library("NewLib")
    assert "NewLib" in config.libraries

    config.add_root_dir("NewLib", "/some/path")
    assert "/some/path" in config.libraries["NewLib"]["paths"]

    config.remove_root_dir("NewLib", "/some/path")
    assert "/some/path" not in config.libraries["NewLib"]["paths"]

    config.remove_library("NewLib")
    assert "NewLib" not in config.libraries


def test_config_save_error(mock_config_file) -> None:
    config = Config()

    def mock_open(*args, **kwargs) -> None:
        raise OSError("Permission denied")

    with patch("builtins.open", mock_open):
        # Should not raise exception
        config.save()


def test_config_load_error(mock_config_file) -> None:
    mock_config_file.touch()

    def mock_open(*args, **kwargs) -> None:
        raise OSError("Permission denied")

    with patch("builtins.open", mock_open):
        config = Config()
        assert config.libraries == {}


def test_config_load_no_keys(mock_config_file) -> None:
    # Test line 31 of config.py
    with open(mock_config_file, "w") as f:
        json.dump({"other": "data"}, f)

    config = Config()
    assert config.libraries == {}


def test_config_max_log_retention(mock_config_file) -> None:
    config = Config()
    config.load_from_db()
    assert config.max_log_retention_days == 7

    config.max_log_retention_days = 30
    config.save_to_db()

    loaded = Config()
    loaded.load_from_db()
    assert loaded.max_log_retention_days == 30


def test_config_divide_logs_by_service(mock_config_file) -> None:
    config = Config()
    config.load_from_db()
    assert config.divide_logs_by_service is False

    config.divide_logs_by_service = True
    config.save_to_db()

    loaded = Config()
    loaded.load_from_db()
    assert loaded.divide_logs_by_service is True


def test_config_backup_settings(mock_config_file) -> None:
    config = Config()
    config.backup_directory = "/custom/backups"
    config.config_backup_frequency = 3
    config.database_backup_frequency = 5
    config.config_backup_retention = 10
    config.database_backup_retention = 14
    config.save()
    config.save_to_db()

    loaded = Config()
    loaded.load_from_db()
    assert loaded.backup_directory == "/custom/backups"
    assert loaded.config_backup_frequency == 3
    assert loaded.database_backup_frequency == 5
    assert loaded.config_backup_retention == 10
    assert loaded.database_backup_retention == 14


def test_config_series_preferences(mock_config_file) -> None:
    from lan_streamer.db.connection import get_session
    from lan_streamer.db.models import Series

    with get_session() as session:
        series = Series(library_name="TV", name="Breaking Bad")
        session.add(series)

    config = Config()
    config.set_series_preference("TV", "Breaking Bad", "hide_missing_future", True)
    assert (
        config.get_series_preference("TV", "Breaking Bad", "hide_missing_future")
        is True
    )
    assert (
        config.get_series_preference("TV", "Breaking Bad", "nonexistent", "default_val")
        == "default_val"
    )


def test_config_generates_on_startup_if_not_exists(mock_config_file) -> None:
    if mock_config_file.exists():
        mock_config_file.unlink()

    # Initialization should trigger self.save() and create the file
    config = Config()
    assert mock_config_file.exists()

    with open(mock_config_file, "r") as f:
        data = json.load(f)
    assert data["database_path"] == config.database_path
    assert data["log_level"] == "INFO"
