import json
from pathlib import Path
from unittest.mock import patch

import pytest

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
    assert config.subtitle_position == "Bottom"
    assert config.backup_directory.endswith("backups")
    assert config.config_backup_frequency == 1
    assert config.database_backup_frequency == 1
    assert config.config_backup_retention == 7
    assert config.database_backup_retention == 7


def test_config_load_existing(mock_config_file) -> None:
    mock_config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(mock_config_file, "w") as file_handle:
        json.dump(
            {
                "database_path": "/path/to/db.db",
                "log_directory": "/path/to/logs",
                "backup_directory": "/path/to/backups",
                "log_level": "DEBUG",
                "config_backup_frequency": 3,
                "database_backup_frequency": 5,
            },
            file_handle,
        )

    config = Config()
    assert config.database_path == "/path/to/db.db"
    assert config.log_directory == "/path/to/logs"
    assert config.backup_directory == "/path/to/backups"
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
            "management_type": "local",
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


def test_config_subtitle_position_roundtrip(mock_config_file) -> None:
    config = Config()
    config.load_from_db()
    assert config.subtitle_position == "Bottom"

    config.subtitle_position = "Top"
    config.save_to_db()

    loaded = Config()
    loaded.load_from_db()
    assert loaded.subtitle_position == "Top"


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

    with open(mock_config_file) as f:
        data = json.load(f)
    assert data["database_path"] == config.database_path
    assert data["log_level"] == "INFO"
    assert data["config_backup_frequency"] == 1
    assert data["database_backup_frequency"] == 1


def test_config_generates_and_backups_db_on_startup(tmp_path, mock_config_file) -> None:
    from lan_streamer.system import backup as backup_module
    from lan_streamer.system.backup import perform_scheduled_backups

    # 1. Create a dummy database file
    db_file = tmp_path / "library.db"
    db_file.write_text("dummy database content")

    # 2. Configure paths using mocks so Config and backup use test directories
    home_dir = tmp_path / "home"
    backup_dir = home_dir / ".config" / "lan-streamer" / "backups"

    # Directly save and override the backup module's singleton config properties
    # (can't use patch() on properties backed by a custom setter with no deleter)
    backup_cfg = backup_module.config
    orig_backup_dir = backup_cfg._backup_directory
    orig_db_path = backup_cfg.database_path
    orig_cfg_freq = backup_cfg.config_backup_frequency
    orig_db_freq = backup_cfg.database_backup_frequency
    orig_cfg_ret = backup_cfg.config_backup_retention
    orig_db_ret = backup_cfg.database_backup_retention

    backup_cfg._backup_directory = str(backup_dir)
    backup_cfg.database_path = str(db_file)
    backup_cfg.config_backup_frequency = 1
    backup_cfg.database_backup_frequency = 1
    backup_cfg.config_backup_retention = 7
    backup_cfg.database_backup_retention = 7

    try:
        with (
            patch("pathlib.Path.home", return_value=home_dir),
            patch("os.getenv", return_value=str(db_file)),
            patch("lan_streamer.system.config.CONFIG_FILE", mock_config_file),
            patch("lan_streamer.system.backup.CONFIG_FILE", mock_config_file),
        ):
            if mock_config_file.exists():
                mock_config_file.unlink()

            # Initialization should trigger self.save() and create the config file
            config = Config()  # noqa: F841

            # Verify config file is generated with backup frequencies set to 1
            assert mock_config_file.exists()
            with open(mock_config_file) as f:
                data = json.load(f)
            assert data["config_backup_frequency"] == 1
            assert data["database_backup_frequency"] == 1

            # Simulate the startup backup step (called from main.py after Config init)
            perform_scheduled_backups()

            # Verify the database was backed up in the expected backups subfolder
            assert backup_dir.exists()
            backup_files = list(backup_dir.iterdir())
            db_backups = [f for f in backup_files if f.name.endswith("_library.db")]
            assert len(db_backups) == 1
            assert db_backups[0].read_text() == "dummy database content"
    finally:
        # Restore the singleton to its original state
        backup_cfg._backup_directory = orig_backup_dir
        backup_cfg.database_path = orig_db_path
        backup_cfg.config_backup_frequency = orig_cfg_freq
        backup_cfg.database_backup_frequency = orig_db_freq
        backup_cfg.config_backup_retention = orig_cfg_ret
        backup_cfg.database_backup_retention = orig_db_ret


def test_config_custom_file_from_arguments() -> None:
    import sys
    from pathlib import Path
    from unittest.mock import patch

    from lan_streamer.system.config import _parse_config_path

    # Test parser when --config is passed
    with patch.object(sys, "argv", ["lan-streamer", "--config", "/tmp/custom-1.json"]):
        assert _parse_config_path() == Path("/tmp/custom-1.json")

    # Test parser when -c is passed
    with patch.object(sys, "argv", ["lan-streamer", "-c", "/tmp/custom-2.json"]):
        assert _parse_config_path() == Path("/tmp/custom-2.json")

    # Test parser when --config= is passed
    with patch.object(sys, "argv", ["lan-streamer", "--config=/tmp/custom-3.json"]):
        assert _parse_config_path() == Path("/tmp/custom-3.json")

    # Test parser fallback
    with patch.object(sys, "argv", ["lan-streamer"]):
        assert (
            _parse_config_path()
            == Path.home() / ".config" / "lan-streamer" / "config.json"
        )


def test_config_initialization_with_custom_file(tmp_path) -> None:
    custom_config_path = tmp_path / "my-custom-config.json"

    # We patch CONFIG_FILE dynamically to simulate the parsed config file
    with patch("lan_streamer.system.config.CONFIG_FILE", custom_config_path):
        config = Config()

        # Verify defaults are relative to the custom config file directory
        assert Path(config.database_path) == custom_config_path.parent / "library.db"
        assert Path(config.log_directory) == custom_config_path.parent / "logs"
        assert Path(config.cache_directory) == custom_config_path.parent / "cache"
        assert Path(config.backup_directory) == custom_config_path.parent / "backups"

        # Save config file, verifying it generates the file in the new location
        config.save()
        assert custom_config_path.exists()


def test_config_library_management_type_default(mock_config_file) -> None:
    config = Config()
    config.libraries = {
        "LocalSeries": {
            "type": "tv",
            "paths": ["/media/tv"],
            "show_future_episodes": True,
        }
    }
    config.save_to_db()

    reloaded_config = Config()
    reloaded_config.load_from_db()
    assert reloaded_config.libraries["LocalSeries"]["management_type"] == "local"


def test_config_library_management_type_remote_and_scan_agents(
    mock_config_file,
) -> None:
    config = Config()
    config.scan_agents = {
        "http://127.0.0.1:8800": {
            "name": "NAS Storage Agent",
            "url": "http://127.0.0.1:8800",
            "api_key": "secret-agent-key",
        }
    }
    config.libraries = {
        "LocalSeries": {
            "type": "tv",
            "management_type": "local",
            "paths": ["/local/media/tv"],
        },
        "RemoteSeries": {
            "type": "tv",
            "management_type": "remote",
            "agent_url": "http://127.0.0.1:8800",
            "remote_library_id": "lib-tv-01",
            "remote_root_path": "/storage/tv",
            "paths": ["/mnt/nas/tv"],
        },
    }
    config.save_to_db()

    reloaded_config = Config()
    reloaded_config.load_from_db()

    assert "http://127.0.0.1:8800" in reloaded_config.scan_agents
    assert (
        reloaded_config.scan_agents["http://127.0.0.1:8800"]["name"]
        == "NAS Storage Agent"
    )
    assert reloaded_config.libraries["LocalSeries"]["management_type"] == "local"
    assert reloaded_config.libraries["RemoteSeries"]["management_type"] == "remote"
    assert (
        reloaded_config.libraries["RemoteSeries"]["remote_root_path"] == "/storage/tv"
    )
    assert reloaded_config.libraries["RemoteSeries"]["paths"] == ["/mnt/nas/tv"]


def test_split_multi_root_libraries_single_path_unchanged() -> None:
    from lan_streamer.system.config import split_multi_root_libraries

    input_libraries = {
        "Movies": {
            "type": "movie",
            "paths": ["/media/movies"],
            "archive_paths": [],
        }
    }
    result_libraries, split_records = split_multi_root_libraries(input_libraries)
    assert len(result_libraries) == 1
    assert result_libraries["Movies"]["paths"] == ["/media/movies"]
    assert split_records == []


def test_split_multi_root_libraries_multi_paths() -> None:
    from lan_streamer.system.config import split_multi_root_libraries

    input_libraries = {
        "Anime": {
            "type": "tv",
            "paths": ["/media/anime1", "/media/anime2", "/media/anime3"],
            "archive_paths": ["/media/anime3"],
            "show_future_episodes": True,
        }
    }
    result_libraries, split_records = split_multi_root_libraries(input_libraries)

    assert len(result_libraries) == 1
    assert "Anime" in result_libraries
    assert result_libraries["Anime"]["paths"] == [
        "/media/anime1",
        "/media/anime2",
        "/media/anime3",
    ]
    assert result_libraries["Anime"]["archive_paths"] == ["/media/anime3"]
    assert result_libraries["Anime"]["show_future_episodes"] is True
    assert split_records == []


def test_split_multi_root_libraries_collision_handling() -> None:
    from lan_streamer.system.config import split_multi_root_libraries

    input_libraries = {
        "Anime": {
            "type": "tv",
            "paths": ["/disk1/shows", "/disk2/shows"],
        },
        "Anime (shows)": {
            "type": "tv",
            "paths": ["/disk3/other"],
        },
    }
    result_libraries, split_records = split_multi_root_libraries(input_libraries)

    assert "Anime" in result_libraries
    assert "Anime (shows)" in result_libraries
    assert result_libraries["Anime"]["paths"] == ["/disk1/shows", "/disk2/shows"]
    assert result_libraries["Anime (shows)"]["paths"] == ["/disk3/other"]
    assert split_records == []


def test_config_load_preserves_multi_root_libraries(
    mock_config_file,
) -> None:
    config = Config()
    config.libraries = {
        "Shows": {
            "type": "tv",
            "paths": ["/path/one", "/path/two"],
        }
    }
    config.save_to_db()

    reloaded = Config()
    reloaded.load_from_db()

    assert "Shows" in reloaded.libraries
    assert reloaded.libraries["Shows"]["paths"] == ["/path/one", "/path/two"]


def test_config_tabs_default_generation(mock_config_file) -> None:
    """When no tabs are saved, load_from_db should generate default 1:1 tabs from libraries."""
    config = Config()
    config.libraries = {
        "Anime": {"type": "tv", "paths": ["/anime"]},
        "Movies": {"type": "movie", "paths": ["/movies"]},
    }
    config.save_to_db()

    reloaded = Config()
    reloaded.load_from_db()

    assert len(reloaded.tabs) == 2
    tab_names = reloaded.get_tab_names()
    assert "Anime" in tab_names
    assert "Movies" in tab_names
    assert reloaded.get_tab_libraries("Anime") == ["Anime"]
    assert reloaded.get_tab_libraries("Movies") == ["Movies"]


def test_config_tabs_custom_save_and_load(mock_config_file) -> None:
    """Custom tabs grouping multiple libraries should persist and reload correctly."""
    config = Config()
    config.libraries = {
        "Anime TV": {"type": "tv", "paths": ["/anime/tv"]},
        "Anime OVAs": {"type": "tv", "paths": ["/anime/ovas"]},
        "Cinema": {"type": "movie", "paths": ["/movies"]},
    }
    config.tabs = [
        {"name": "All Anime", "libraries": ["Anime TV", "Anime OVAs"]},
        {"name": "Movies", "libraries": ["Cinema"]},
    ]
    config.save_to_db()

    reloaded = Config()
    reloaded.load_from_db()

    assert len(reloaded.tabs) == 2
    assert reloaded.get_tab_names() == ["All Anime", "Movies"]
    assert reloaded.get_tab_libraries("All Anime") == ["Anime TV", "Anime OVAs"]
    assert reloaded.get_tab_libraries("Movies") == ["Cinema"]
    # Fallback for unconfigured tab name
    assert reloaded.get_tab_libraries("NonExistent") == []


def test_split_multi_root_libraries_skips_remote_libraries() -> None:
    from lan_streamer.system.config import split_multi_root_libraries

    input_libraries = {
        "Remote Shows": {
            "type": "tv",
            "management_type": "remote",
            "agent_url": "http://127.0.0.1:8800",
            "remote_library_id": "remote-tv",
            "paths": ["/local/mount1", "/local/mount2"],
            "mount_mappings": {
                "/remote/shows1": "/local/mount1",
                "/remote/shows2": "/local/mount2",
            },
        },
        "Local TV": {
            "type": "tv",
            "management_type": "local",
            "paths": ["/local/tv1", "/local/tv2"],
        },
    }
    result_libraries, split_records = split_multi_root_libraries(input_libraries)

    # Neither remote nor local libraries should be split; paths are preserved
    assert "Remote Shows" in result_libraries
    assert "Remote Shows (mount2)" not in result_libraries
    assert result_libraries["Remote Shows"]["paths"] == [
        "/local/mount1",
        "/local/mount2",
    ]

    assert "Local TV" in result_libraries
    assert "Local TV (tv2)" not in result_libraries
    assert result_libraries["Local TV"]["paths"] == ["/local/tv1", "/local/tv2"]
    assert len(split_records) == 0


def test_get_library_sources_and_normalize_configuration() -> None:
    from lan_streamer.system.config import (
        get_library_sources,
        normalize_library_configuration,
    )

    # 1. Legacy local library coercion
    legacy_local = {
        "type": "tv",
        "management_type": "local",
        "paths": ["/local/tv1", "/local/tv2"],
        "archive_paths": ["/local/tv2"],
    }
    normalized_local = normalize_library_configuration(legacy_local)
    assert normalized_local["management_type"] == "local"
    assert "sources" in normalized_local
    assert len(normalized_local["sources"]) == 2
    assert normalized_local["sources"][0] == {
        "type": "local",
        "path": "/local/tv1",
        "is_archive": False,
    }
    assert normalized_local["sources"][1] == {
        "type": "local",
        "path": "/local/tv2",
        "is_archive": True,
    }

    # 2. Legacy remote library coercion
    legacy_remote = {
        "type": "tv",
        "management_type": "remote",
        "agent_url": "http://127.0.0.1:8800",
        "remote_library_id": "src-tv",
        "mount_mappings": {"/agent/tv": "/mnt/tv"},
    }
    normalized_remote = normalize_library_configuration(legacy_remote)
    assert normalized_remote["management_type"] == "remote"
    assert len(normalized_remote["sources"]) == 1
    assert normalized_remote["sources"][0]["type"] == "agent"
    assert normalized_remote["sources"][0]["agent_url"] == "http://127.0.0.1:8800"
    assert normalized_remote["sources"][0]["source_id"] == "src-tv"

    # 3. Explicit multi-source hybrid library
    hybrid_library = {
        "type": "tv",
        "sources": [
            {"type": "local", "path": "/storage/anime"},
            {
                "type": "agent",
                "agent_url": "http://127.0.0.1:8800",
                "source_id": "src-agent-anime",
                "mount_path": "/mnt/agent_anime",
            },
        ],
    }
    normalized_hybrid = normalize_library_configuration(hybrid_library)
    assert normalized_hybrid["management_type"] == "hybrid"
    assert normalized_hybrid["paths"] == ["/storage/anime"]
    sources = get_library_sources(normalized_hybrid)
    assert len(sources) == 2
    assert sources[0]["type"] == "local"
    assert sources[1]["type"] == "agent"


def test_config_get_local_and_remote_libraries_hybrid() -> None:
    config = Config()
    config.libraries = {
        "Local Only": {"type": "tv", "paths": ["/local/tv"]},
        "Remote Only": {
            "type": "tv",
            "management_type": "remote",
            "agent_url": "http://127.0.0.1:8800",
            "remote_library_id": "src-tv",
        },
        "Hybrid Library": {
            "type": "tv",
            "sources": [
                {"type": "local", "path": "/hybrid/local"},
                {
                    "type": "agent",
                    "agent_url": "http://127.0.0.1:8800",
                    "source_id": "src-tv",
                },
            ],
        },
    }

    local_libs = config.get_local_libraries()
    assert "Local Only" in local_libs
    assert "Hybrid Library" in local_libs
    assert "Remote Only" not in local_libs

    remote_libs = config.get_remote_libraries()
    assert "Remote Only" in remote_libs
    assert "Hybrid Library" in remote_libs
    assert "Local Only" not in remote_libs
