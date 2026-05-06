import json
import pytest
from lan_streamer.config import Config


@pytest.fixture
def mock_config_file(tmp_path, monkeypatch):
    test_config_path = tmp_path / "config.json"
    import lan_streamer.config

    monkeypatch.setattr(lan_streamer.config, "CONFIG_FILE", test_config_path)
    return test_config_path


def test_config_initialization(mock_config_file):
    config = Config()
    assert config.libraries == {}
    assert config.jellyfin_url == ""
    assert config.jellyfin_api_key == ""


def test_config_load_existing(mock_config_file):
    mock_config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(mock_config_file, "w") as f:
        json.dump(
            {
                "libraries": {"TestLib": ["/path/to/test"]},
                "jellyfin_url": "http://test",
                "jellyfin_api_key": "test_key",
            },
            f,
        )

    config = Config()
    assert config.libraries == {"TestLib": ["/path/to/test"]}
    assert config.jellyfin_url == "http://test"
    assert config.jellyfin_api_key == "test_key"


def test_config_migrate_old_format(mock_config_file):
    mock_config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(mock_config_file, "w") as f:
        json.dump({"root_dirs": ["/old/path"]}, f)

    config = Config()
    assert config.libraries == {"Default": ["/old/path"]}
    assert config.jellyfin_url == ""


def test_config_add_remove_library(mock_config_file):
    config = Config()
    config.add_library("NewLib")
    assert "NewLib" in config.libraries

    config.add_root_dir("NewLib", "/some/path")
    assert "/some/path" in config.libraries["NewLib"]

    config.remove_root_dir("NewLib", "/some/path")
    assert "/some/path" not in config.libraries["NewLib"]

    config.remove_library("NewLib")
    assert "NewLib" not in config.libraries


def test_config_save_error(mock_config_file, monkeypatch):
    config = Config()

    def mock_open(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr("builtins.open", mock_open)
    # Should not raise exception
    config.save()


def test_config_load_error(mock_config_file, monkeypatch):
    mock_config_file.touch()

    def mock_open(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr("builtins.open", mock_open)
    config = Config()
    assert config.libraries == {}


def test_config_load_no_keys(mock_config_file):
    # Test line 31 of config.py
    with open(mock_config_file, "w") as f:
        json.dump({"other": "data"}, f)

    config = Config()
    assert config.libraries == {}
