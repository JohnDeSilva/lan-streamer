"""Unit tests for agent configuration and the desktop config bridge."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from scan_agent.config import (
    AgentConfig,
    get_agent_config,
    install_into_lan_streamer,
    reset_agent_config,
    resolve_default_config_path,
    resolve_default_data_directory,
)


def test_first_run_writes_defaults(tmp_path) -> None:
    config_path = tmp_path / "nested" / "config.json"
    config = AgentConfig(config_path)
    assert config_path.exists()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["scan_concurrency"] == 4
    assert config.tmdb_api_key == ""


def test_load_and_save_round_trip(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config = AgentConfig(config_path)
    config.set("tmdb_api_key", "abc123")
    config.set("scan_concurrency", 8)
    del config

    reloaded = AgentConfig(config_path)
    assert reloaded.tmdb_api_key == "abc123"
    assert reloaded.scan_concurrency == 8


def test_missing_keys_fall_back_to_defaults(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"tmdb_api_key": "keep"}), encoding="utf-8")
    config = AgentConfig(config_path)
    assert config.tmdb_api_key == "keep"
    assert config.scan_concurrency == 4


def test_corrupt_file_falls_back(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{not json!!!", encoding="utf-8")
    config = AgentConfig(config_path)
    assert config.scan_concurrency == 4


def test_get_agent_config_is_singleton(tmp_path) -> None:
    configured_path = tmp_path / "config.json"
    first = get_agent_config(configured_path)
    second = get_agent_config(tmp_path / "other.json")
    assert first is second


def test_install_into_lan_streamer_swaps_singleton(tmp_path, monkeypatch) -> None:
    config = AgentConfig(tmp_path / "config.json")
    config.database_path = str(tmp_path / "library.db")
    install_into_lan_streamer(config)

    import lan_streamer.system.config as desktop_config_module

    assert desktop_config_module.config is config
    assert os.environ["LAN_STREAMER_DB"] == config.database_path


def test_install_is_idempotent(tmp_path, monkeypatch) -> None:
    config = AgentConfig(tmp_path / "config.json")
    config.database_path = str(tmp_path / "library.db")
    install_into_lan_streamer(config)
    install_into_lan_streamer(config)

    import lan_streamer.system.config as desktop_config_module

    assert desktop_config_module.config is config


def test_installed_config_is_readable_by_reused_provider(tmp_path) -> None:
    config = AgentConfig(tmp_path / "config.json")
    config.tmdb_api_key = "agent-key"
    install_into_lan_streamer(config)

    import lan_streamer.providers.tmdb as tmdb_module

    assert tmdb_module.tmdb_client._effective_api_key == "agent-key"


@pytest.mark.parametrize(
    "attribute_name",
    [
        "tmdb_api_key",
        "opensubtitles_username",
        "opensubtitles_password",
        "scan_concurrency",
        "log_level",
    ],
)
def test_provider_required_attributes_exist(tmp_path, attribute_name) -> None:
    config = AgentConfig(tmp_path / "config.json")
    assert hasattr(config, attribute_name)


def test_bridge_never_loads_pyside6(tmp_path) -> None:
    config = AgentConfig(tmp_path / "config.json")
    install_into_lan_streamer(config)

    assert "PySide6" not in sys.modules


def test_resolve_default_config_path_prefers_environment_variable(
    tmp_path, monkeypatch
) -> None:
    custom_configuration_file = tmp_path / "custom" / "agent_config.json"
    monkeypatch.setenv("SCAN_AGENT_CONFIG", str(custom_configuration_file))
    resolved_configuration_path = resolve_default_config_path()
    assert resolved_configuration_path == custom_configuration_file


def test_resolve_default_data_directory_prefers_scan_agent_data(
    tmp_path, monkeypatch
) -> None:
    custom_data_directory = tmp_path / "custom_data"
    monkeypatch.setenv("SCAN_AGENT_DATA", str(custom_data_directory))
    resolved_data_directory = resolve_default_data_directory()
    assert resolved_data_directory == custom_data_directory


def test_data_directory_colocates_configs_databases_and_caches(tmp_path) -> None:
    data_directory = tmp_path / "agent_data"
    config = AgentConfig(data_directory=data_directory)

    assert config.data_directory == data_directory
    assert config._path == data_directory / "config.json"
    assert config.database_path == str(data_directory / "library.db")
    assert config.cache_directory == str(data_directory / "cache")
    assert config.log_directory == str(data_directory / "logs")

    config.save()
    assert (data_directory / "config.json").exists()
    assert (data_directory / "cache").is_dir()
    assert (data_directory / "logs").is_dir()


def test_install_into_lan_streamer_routes_tmdb_cache_to_data_directory(
    tmp_path, monkeypatch
) -> None:
    data_directory = tmp_path / "agent_data"
    config = AgentConfig(data_directory=data_directory)
    install_into_lan_streamer(config)

    import lan_streamer.providers.tmdb as tmdb_module

    expected_images_cache = data_directory / "cache" / "images"
    expected_people_cache = data_directory / "cache" / "people"
    assert expected_images_cache == tmdb_module.CACHE_DIR
    assert expected_people_cache == tmdb_module.PERSON_CACHE_DIR
    assert expected_images_cache == tmdb_module.tmdb_client._cache_dir
    assert expected_images_cache.is_dir()
    assert expected_people_cache.is_dir()


def test_get_agent_config_without_arguments_uses_default_resolution(
    tmp_path, monkeypatch
) -> None:
    reset_agent_config()
    custom_configuration_file = tmp_path / "environment_config.json"
    monkeypatch.setenv("SCAN_AGENT_CONFIG", str(custom_configuration_file))
    agent_config = get_agent_config()
    assert agent_config._path == custom_configuration_file
    reset_agent_config()


def test_resolve_default_data_directory_uses_writable_container_data(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("SCAN_AGENT_DATA", raising=False)
    monkeypatch.delenv("SCAN_AGENT_CONFIG", raising=False)
    fake_data_directory = tmp_path / "container_data"
    fake_data_directory.mkdir()
    monkeypatch.setattr(
        "scan_agent.config.Path",
        lambda *args: fake_data_directory if args == ("/data",) else Path(*args),
    )
    monkeypatch.setattr("os.access", lambda path, mode: True)
    resolved_data_directory = resolve_default_data_directory()
    assert resolved_data_directory == fake_data_directory


def test_resolve_default_config_path_without_environment_variable(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("SCAN_AGENT_CONFIG", raising=False)
    custom_data_directory = tmp_path / "resolved_data"
    monkeypatch.setenv("SCAN_AGENT_DATA", str(custom_data_directory))
    resolved_config_path = resolve_default_config_path()
    assert resolved_config_path == custom_data_directory / "config.json"


def test_get_agent_config_accepts_data_directory(tmp_path) -> None:
    reset_agent_config()
    custom_data_directory = tmp_path / "explicit_data"
    agent_config = get_agent_config(data_directory=custom_data_directory)
    assert agent_config.data_directory == custom_data_directory
    assert agent_config._path == custom_data_directory / "config.json"
    assert agent_config.database_path == str(custom_data_directory / "library.db")
    assert agent_config.cache_directory == str(custom_data_directory / "cache")
    reset_agent_config()


def test_log_level_default_and_round_trip(tmp_path) -> None:
    configuration_path = tmp_path / "config.json"
    agent_config = AgentConfig(configuration_path)
    assert agent_config.log_level == "INFO"

    agent_config.set("log_level", "DEBUG")
    reloaded_config = AgentConfig(configuration_path)
    assert reloaded_config.log_level == "DEBUG"
