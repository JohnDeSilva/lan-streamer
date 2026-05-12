import json
import pytest
from unittest.mock import patch
from lan_streamer.config import Config


@pytest.fixture
def mock_config_file(tmp_path) -> None:
    test_config_path = tmp_path / "config.json"
    with patch("lan_streamer.config.CONFIG_FILE", test_config_path):
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


def test_config_load_existing(mock_config_file) -> None:
    mock_config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(mock_config_file, "w") as f:
        json.dump(
            {
                "libraries": {"TestLib": ["/path/to/test"]},
                "jellyfin_url": "http://test",
                "jellyfin_api_key": "test_key",
                "tmdb_api_key": "tmdb_key",
                "sync_history_on_start": False,
                "filter_out_watched": True,
                "sort_mode": "Date Added (Newest)",
                "max_cache_size_gb": 20.5,
            },
            f,
        )

    config = Config()
    assert config.libraries == {"TestLib": ["/path/to/test"]}
    assert config.jellyfin_url == "http://test"
    assert config.jellyfin_api_key == "test_key"
    assert config.tmdb_api_key == "tmdb_key"
    assert config.sync_history_on_start is False
    assert config.filter_out_watched is True
    assert config.sort_mode == "Date Added (Newest)"
    assert config.max_cache_size_gb == 20.5


def test_config_migrate_old_format(mock_config_file) -> None:
    mock_config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(mock_config_file, "w") as f:
        json.dump({"root_dirs": ["/old/path"]}, f)

    config = Config()
    assert config.libraries == {"Default": ["/old/path"]}
    assert config.jellyfin_url == ""


def test_config_backwards_compat_tvdb_api_key(mock_config_file) -> None:
    """Old config files using tvdb_api_key should migrate to tmdb_api_key."""
    mock_config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(mock_config_file, "w") as f:
        json.dump({"tvdb_api_key": "old_tvdb_key"}, f)

    config = Config()
    assert config.tmdb_api_key == "old_tvdb_key"


def test_config_add_remove_library(mock_config_file) -> None:
    config = Config()
    config.add_library("NewLib")
    assert "NewLib" in config.libraries

    config.add_root_dir("NewLib", "/some/path")
    assert "/some/path" in config.libraries["NewLib"]

    config.remove_root_dir("NewLib", "/some/path")
    assert "/some/path" not in config.libraries["NewLib"]

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
    assert config.max_log_retention_days == 7

    config.max_log_retention_days = 30
    config.save()

    loaded = Config()
    assert loaded.max_log_retention_days == 30
