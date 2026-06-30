"""
Tests for:
 - system/logging_handler.py  (lines 30-31 – handler error path, setup_qt_logging with divide_logs_by_service)
 - system/config.py           (lines 245, 272-273 – config load/save edge cases)
 - providers/myanimelist.py   (remaining uncovered lines: exchange_auth_code failure json,
                               exchange_auth_code non-200 with error_msg None,
                               get_anime_details not configured,
                               search_anime not configured, search_anime exception,
                               update_watched_status not configured/not authenticated,
                               update_watched_status HTTP non-200, update_watched_status exception)
  - backend/scan_workers.py    (discover_single_library_tree_impl edge cases,
                               ScanAllLibrariesWorker with no root dirs,
                               ScanAllLibrariesWorker movie library)
 - playback/cache.py          (CacheWorker run – exception path)
"""

import logging
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# system/logging_handler.py
# ---------------------------------------------------------------------------


class TestQtLogHandler:
    def test_emit_handles_format_exception(self) -> None:
        """When format() raises, handleError should be called instead of crashing."""
        from lan_streamer.system.logging_handler import QtLogHandler

        handler = QtLogHandler()
        # Make format() raise to hit the except branch (line 30-31)
        handler.format = MagicMock(side_effect=Exception("format error"))
        handler.handleError = MagicMock()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        handler.handleError.assert_called_once_with(record)

    def test_emit_appends_to_buffer(self) -> None:
        from lan_streamer.system.logging_handler import QtLogHandler

        handler = QtLogHandler(capacity=5)
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="warning message",
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        assert len(handler.buffer) == 1
        assert "warning message" in handler.buffer[0][0]
        assert handler.buffer[0][1] == "WARNING"

    def test_buffer_capacity(self) -> None:
        from lan_streamer.system.logging_handler import QtLogHandler

        handler = QtLogHandler(capacity=3)
        for i in range(5):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=f"msg {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)
        # Only last 3 should remain due to maxlen
        assert len(handler.buffer) == 3


class TestSetupQtLogging:
    def test_setup_with_divide_logs_by_service(self) -> None:
        """When divide_logs_by_service=True, each service logger gets the handler."""
        from lan_streamer.system.logging_handler import (
            setup_qt_logging,
            qt_log_handler,
            SERVICE_LOGGERS,
        )
        from lan_streamer.system.config import config

        formatter = logging.Formatter("%(message)s")
        original = config.divide_logs_by_service
        config.divide_logs_by_service = True
        try:
            setup_qt_logging(formatter)
            # Verify root logger has the handler
            root = logging.getLogger()
            assert qt_log_handler in root.handlers

            # Verify at least one service logger got it
            svc_logger = logging.getLogger(SERVICE_LOGGERS[0])
            assert qt_log_handler in svc_logger.handlers
        finally:
            config.divide_logs_by_service = original

    def test_setup_without_divide_logs(self) -> None:
        from lan_streamer.system.logging_handler import setup_qt_logging, qt_log_handler
        from lan_streamer.system.config import config

        formatter = logging.Formatter("%(message)s")
        config.divide_logs_by_service = False
        setup_qt_logging(formatter)
        root = logging.getLogger()
        assert qt_log_handler in root.handlers


class TestSetApplicationLogLevel:
    @pytest.fixture(autouse=True)
    def _restore_logger_level(self) -> None:
        """Save and restore root logger level to avoid polluting other tests."""
        logger = logging.getLogger()
        original_level = logger.level
        yield
        logger.setLevel(original_level)

    def test_set_level_debug(self) -> None:
        from lan_streamer.system.logging_handler import set_application_log_level

        set_application_log_level("DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_set_level_error(self) -> None:
        from lan_streamer.system.logging_handler import set_application_log_level

        set_application_log_level("ERROR")
        assert logging.getLogger().level == logging.ERROR

    def test_set_level_invalid_falls_back_to_info(self) -> None:
        from lan_streamer.system.logging_handler import set_application_log_level

        # getattr(logging, "UNKNOWN", logging.INFO) => logging.INFO
        set_application_log_level("UNKNOWN_LEVEL_XYZ")
        assert logging.getLogger().level == logging.INFO


# ---------------------------------------------------------------------------
# system/config.py – edge cases
# ---------------------------------------------------------------------------


class TestConfigSaveLoadEdgeCases:
    def test_save_cannot_create_directory(self, tmp_path) -> None:
        """If mkdir fails, save should log a warning but still try to write."""
        from lan_streamer.system.config import Config

        cfg = Config.__new__(Config)
        cfg.__dict__.update(
            {
                "libraries": {},
                "jellyfin_url": "",
                "jellyfin_api_key": "",
                "tmdb_api_key": "",
                "myanimelist_client_id": "",
                "myanimelist_client_secret": "",
                "myanimelist_access_token": "",
                "myanimelist_refresh_token": "",
                "myanimelist_token_expires_at": 0.0,
                "opensubtitles_username": "",
                "opensubtitles_password": "",
                "opensubtitles_api_key": "",
                "sync_history_on_start": False,
                "filter_out_watched": False,
                "sort_mode": "Alphabetical",
                "sort_descending": False,
                "database_path": str(tmp_path / "library.db"),
                "log_directory": str(tmp_path / "logs"),
                "log_level": "INFO",
                "divide_logs_by_service": False,
                "enable_caching": False,
                "watched_threshold": 90,
                "cache_directory": str(tmp_path / "cache"),
                "use_embedded_player": False,
                "enable_hw_accel": False,
                "vlc_extra_args": "",
                "vlc_buffer_ms": 1000,
                "player_overlay_opacity": 0.5,
                "player_overlay_color": "#000000",
                "max_cache_size_gb": 10,
                "enable_next_episode_popup": True,
                "max_log_retention_days": 30,
                "backup_directory": str(tmp_path / "backups"),
                "config_backup_frequency": "weekly",
                "database_backup_frequency": "weekly",
                "config_backup_retention": 5,
                "database_backup_retention": 5,
                "enable_combined_view": False,
                "combined_views": [],
                "series_preferences": {},
            }
        )

        config_file = tmp_path / "subdir" / "config.json"
        with patch("lan_streamer.system.config.CONFIG_FILE", config_file):
            with patch.object(
                config_file.parent.__class__,
                "mkdir",
                side_effect=PermissionError("cannot mkdir"),
            ):
                # Should not raise even if mkdir fails
                cfg.save()

    def test_load_config_startup_paths_expansion(self, tmp_path) -> None:
        """Test that database_path and log_directory tildes are expanded correctly."""
        import json
        from pathlib import Path
        from lan_streamer.system.config import Config

        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "database_path": "~/my_test_library.db",
                    "log_directory": "~/my_test_logs",
                }
            )
        )

        with patch("lan_streamer.system.config.CONFIG_FILE", config_file):
            cfg = Config()
            assert cfg.database_path == str(
                Path("~/my_test_library.db").expanduser().absolute()
            )
            assert cfg.log_directory == str(
                Path("~/my_test_logs").expanduser().absolute()
            )

    def test_load_config_properties_expansion(self) -> None:
        """Test that properties like cache_directory expand tilde on setting."""
        from pathlib import Path
        from lan_streamer.system.config import Config

        cfg = Config()
        cfg.cache_directory = "~/my_cache"
        assert cfg.cache_directory == str(Path("~/my_cache").expanduser().absolute())

    def test_load_config_exception(self, tmp_path) -> None:
        """When config file is corrupted, should not crash."""
        from lan_streamer.system.config import Config

        config_file = tmp_path / "config.json"
        config_file.write_text("this is not json {{{")

        cfg = Config.__new__(Config)
        cfg.series_preferences = {}
        cfg.libraries = {}
        with patch("lan_streamer.system.config.CONFIG_FILE", config_file):
            cfg.load()  # Should catch the JSON parse error

        assert cfg.libraries == {}


# ---------------------------------------------------------------------------
# providers/myanimelist.py – remaining uncovered paths
# ---------------------------------------------------------------------------


@pytest.fixture
def mal_client():
    import time
    from lan_streamer.providers.myanimelist import MyAnimeListClient
    from lan_streamer.system.config import config

    with (
        patch.object(config, "myanimelist_client_id", "test-client"),
        patch.object(config, "myanimelist_client_secret", "test-secret"),
        patch.object(config, "myanimelist_access_token", "test-token"),
        patch.object(config, "myanimelist_refresh_token", "test-refresh"),
        patch.object(config, "myanimelist_token_expires_at", time.time() + 3600),
    ):
        yield MyAnimeListClient()


def test_exchange_auth_code_non200_with_error_description(mal_client) -> None:
    """Tests the non-200 branch where error_description is in JSON."""
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"error_description": "invalid_grant"}
    mal_client.session.post = MagicMock(return_value=mock_resp)

    success, msg = mal_client.exchange_auth_code("code", "verifier")
    assert success is False
    assert "invalid_grant" in msg


def test_exchange_auth_code_non200_with_message_field(mal_client) -> None:
    """Tests the non-200 branch where 'message' key is in JSON."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"message": "Unauthorized"}
    mal_client.session.post = MagicMock(return_value=mock_resp)

    success, msg = mal_client.exchange_auth_code("code", "verifier")
    assert success is False
    assert "Unauthorized" in msg


def test_exchange_auth_code_non200_json_parse_error(mal_client) -> None:
    """Tests the non-200 branch where JSON parsing of error fails and text is used."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.json.side_effect = Exception("not json")
    mock_resp.text = "Internal Server Error"
    mal_client.session.post = MagicMock(return_value=mock_resp)

    success, msg = mal_client.exchange_auth_code("code", "verifier")
    assert success is False
    assert "Internal Server Error" in msg or "500" in msg


def test_exchange_auth_code_non200_no_error_info(mal_client) -> None:
    """Tests non-200 where JSON has no error fields and text is empty."""
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.json.return_value = {}  # no error_description/message/error
    mock_resp.text = ""
    mal_client.session.post = MagicMock(return_value=mock_resp)

    success, msg = mal_client.exchange_auth_code("code", "verifier")
    assert success is False


def test_search_anime_not_configured() -> None:
    """search_anime returns [] when not configured."""
    from lan_streamer.providers.myanimelist import MyAnimeListClient
    from lan_streamer.system.config import config

    with patch.object(config, "myanimelist_client_id", "  "):
        client = MyAnimeListClient()
        result = client.search_anime("Naruto")
        assert result == []


def test_search_anime_exception(mal_client) -> None:
    """search_anime returns [] when request fails."""
    mal_client.session.get = MagicMock(side_effect=Exception("Network error"))
    result = mal_client.search_anime("Naruto")
    assert result == []


def test_search_anime_no_main_picture(mal_client) -> None:
    """search_anime handles anime nodes without main_picture gracefully."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {
                "node": {
                    "id": 1,
                    "title": "Show Without Picture",
                    "num_episodes": 12,
                    "main_picture": None,
                    "start_date": "2020-01-01",
                }
            }
        ]
    }
    mal_client.session.get = MagicMock(return_value=mock_resp)
    results = mal_client.search_anime("Show")
    assert len(results) == 1
    assert results[0]["poster_path"] == ""


def test_get_anime_details_not_configured() -> None:
    """get_anime_details returns None when not configured."""
    from lan_streamer.providers.myanimelist import MyAnimeListClient
    from lan_streamer.system.config import config

    with patch.object(config, "myanimelist_client_id", ""):
        client = MyAnimeListClient()
        result = client.get_anime_details(123)
        assert result is None


def test_get_anime_details_exception(mal_client) -> None:
    """get_anime_details returns None when request fails."""
    mal_client.session.get = MagicMock(side_effect=Exception("Timeout"))
    result = mal_client.get_anime_details(999)
    assert result is None


def test_update_watched_status_not_configured() -> None:
    """update_watched_status returns False when not configured."""
    from lan_streamer.providers.myanimelist import MyAnimeListClient
    from lan_streamer.system.config import config

    with (
        patch.object(config, "myanimelist_client_id", ""),
        patch.object(config, "myanimelist_access_token", "token"),
    ):
        client = MyAnimeListClient()
        result = client.update_watched_status(1, 5)
        assert result is False


def test_update_watched_status_not_authenticated() -> None:
    """update_watched_status returns False when not authenticated."""
    from lan_streamer.providers.myanimelist import MyAnimeListClient
    from lan_streamer.system.config import config

    with (
        patch.object(config, "myanimelist_client_id", "client-id"),
        patch.object(config, "myanimelist_access_token", ""),
    ):
        client = MyAnimeListClient()
        result = client.update_watched_status(1, 5)
        assert result is False


def test_update_watched_status_http_non_200(mal_client) -> None:
    """update_watched_status returns False on non-200 HTTP response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden"
    mal_client.session.put = MagicMock(return_value=mock_resp)

    result = mal_client.update_watched_status(1, 5)
    assert result is False


def test_update_watched_status_exception(mal_client) -> None:
    """update_watched_status returns False on request exception."""
    mal_client.session.put = MagicMock(side_effect=Exception("Network error"))
    result = mal_client.update_watched_status(1, 5)
    assert result is False


def test_refresh_access_token_includes_client_secret(mal_client) -> None:
    """When client_secret is set, it's included in the refresh token request."""
    from lan_streamer.system.config import config

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "access_token": "new_token",
        "refresh_token": "new_refresh",
        "expires_in": 3600,
    }
    mal_client.session.post = MagicMock(return_value=mock_resp)

    with patch.object(config, "save"):
        result = mal_client.refresh_access_token()
        assert result is True

    call_data = mal_client.session.post.call_args[1]["data"]
    assert "client_secret" in call_data
    assert call_data["client_secret"] == "test-secret"


def test_exchange_auth_code_includes_client_secret(mal_client) -> None:
    """When client_secret is set, exchange_auth_code includes it in POST."""
    from lan_streamer.system.config import config

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "tok",
        "refresh_token": "ref",
        "expires_in": 3600,
    }
    mal_client.session.post = MagicMock(return_value=mock_resp)

    with patch.object(config, "save"):
        success, msg = mal_client.exchange_auth_code("code", "verifier")
        assert success is True

    call_data = mal_client.session.post.call_args[1]["data"]
    assert "client_secret" in call_data


# ---------------------------------------------------------------------------
# backend/scan_workers.py – additional coverage
# ---------------------------------------------------------------------------


def test_discover_single_library_tree_nonexistent_dir(tmp_path) -> None:
    """When a root dir doesn't exist, it maps to an empty list."""
    from lan_streamer.backend.scan_worker_base import (
        discover_single_library_tree_impl,
    )

    result = discover_single_library_tree_impl(["/nonexistent/dir/xyz_12345"], "tv")
    assert "/nonexistent/dir/xyz_12345" in result
    assert result["/nonexistent/dir/xyz_12345"] == []


def test_discover_single_library_tree_existing_dir(tmp_path) -> None:
    """Pre-discovery works for actual directories containing video files."""
    from lan_streamer.backend.scan_worker_base import (
        discover_single_library_tree_impl,
    )

    # Create a fake series folder with a video file
    series_dir = tmp_path / "My Show"
    series_dir.mkdir()
    (series_dir / "episode.mkv").write_bytes(b"\x00" * 100)

    result = discover_single_library_tree_impl([str(tmp_path)], "tv")
    assert str(tmp_path) in result
    assert "My Show" in result[str(tmp_path)]


def test_scan_all_libraries_worker_no_root_dirs() -> None:
    """ScanAllLibrariesWorker handles a library with no root directories."""
    from lan_streamer.backend import ScanAllLibrariesWorker
    from lan_streamer.scanner import LibraryDict

    empty_lib = LibraryDict({})
    empty_lib.unavailable_directories = []

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            return_value=empty_lib,
        ) as mock_scan,
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch("lan_streamer.backend.scan_worker_all.db.save_library") as mock_save,
    ):
        mock_config.libraries = {
            "EmptyLib": {"paths": [], "type": "tv"},
        }

        finished = []
        worker = ScanAllLibrariesWorker()
        worker.finished.connect(lambda: finished.append(True))
        worker.run()

        assert finished == [True]
        assert mock_scan.call_count == 2
        assert mock_save.call_count == 2


def test_scan_all_libraries_worker_movie_library() -> None:
    """ScanAllLibrariesWorker uses save_movie_library for movie-type libraries."""
    from lan_streamer.backend import ScanAllLibrariesWorker
    from lan_streamer.scanner import LibraryDict

    movie_lib = LibraryDict({})
    movie_lib.unavailable_directories = []

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            return_value=movie_lib,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.load_movie_library",
            return_value={},
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.db.save_movie_library"
        ) as mock_save_movie,
    ):
        mock_config.libraries = {
            "MovieLib": {"paths": ["/movies"], "type": "movie"},
        }

        finished = []
        worker = ScanAllLibrariesWorker()
        worker.finished.connect(lambda: finished.append(True))
        worker.run()

        assert finished == [True]
        mock_save_movie.assert_called()


# ---------------------------------------------------------------------------
# playback/cache.py – CacheWorker exception path
# ---------------------------------------------------------------------------


def test_cache_worker_run_exception(tmp_path, qtbot) -> None:
    """CacheWorker emits error when source file doesn't exist."""
    from lan_streamer.playback.cache import CacheWorker

    src = tmp_path / "nonexistent_source.mkv"
    dst = tmp_path / "dest.mkv"

    errors = []
    worker = CacheWorker(str(src), str(dst))
    worker.error.connect(errors.append)
    worker.run()

    assert len(errors) == 1  # FileNotFoundError should emit error signal


def test_cache_worker_run_success(tmp_path, qtbot) -> None:
    """CacheWorker copies file and emits finished with dest path."""
    from lan_streamer.playback.cache import CacheWorker

    src = tmp_path / "source.mkv"
    src.write_bytes(b"\x00" * 2048)  # 2KB file

    dst = tmp_path / "subdir" / "dest.mkv"

    finished = []
    progress_values = []

    worker = CacheWorker(str(src), str(dst))
    worker.finished.connect(finished.append)
    worker.progress.connect(progress_values.append)
    worker.run()

    assert len(finished) == 1
    assert finished[0] == str(dst)
    assert dst.exists()
    assert dst.read_bytes() == src.read_bytes()
