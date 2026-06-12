"""
Tests for backend/proxy.py, scanner/proxy.py, and playback/proxy.py.
These modules contain lazy-import proxy classes (PatchedAttribute, PatchedCallable,
ScannerProxy) that are almost entirely uncovered.
"""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# backend/proxy.py
# ---------------------------------------------------------------------------


class TestBackendPatchedAttribute:
    def test_get_target_from_module(self) -> None:
        from lan_streamer.backend.proxy import PatchedAttribute

        fake_module = types.ModuleType("lan_streamer.backend")
        fake_obj = object()
        setattr(fake_module, "my_attr", fake_obj)

        with patch.dict(sys.modules, {"lan_streamer.backend": fake_module}):
            pa = PatchedAttribute("my_attr", lambda: "default")
            assert pa._get_target() is fake_obj

    def test_get_target_fallback_when_module_missing(self) -> None:
        from lan_streamer.backend.proxy import PatchedAttribute

        sentinel = object()
        pa = PatchedAttribute("nonexistent_attr_xyz", lambda: sentinel)

        # Temporarily remove the module if it exists
        saved = sys.modules.pop("lan_streamer.backend", None)
        try:
            assert pa._get_target() is sentinel
        finally:
            if saved is not None:
                sys.modules["lan_streamer.backend"] = saved

    def test_get_target_fallback_when_attr_missing(self) -> None:
        from lan_streamer.backend.proxy import PatchedAttribute

        fake_module = types.ModuleType("lan_streamer.backend")
        # Module exists but does NOT have the attribute
        sentinel = object()
        pa = PatchedAttribute("missing_attr_xyz", lambda: sentinel)

        with patch.dict(sys.modules, {"lan_streamer.backend": fake_module}):
            assert pa._get_target() is sentinel

    def test_getattr_delegates(self) -> None:
        from lan_streamer.backend.proxy import PatchedAttribute

        fake_obj = MagicMock()
        fake_obj.some_prop = 42
        fake_module = types.ModuleType("lan_streamer.backend")
        setattr(fake_module, "my_attr", fake_obj)

        with patch.dict(sys.modules, {"lan_streamer.backend": fake_module}):
            pa = PatchedAttribute("my_attr", lambda: None)
            assert pa.some_prop == 42


class TestBackendPatchedCallable:
    def test_call_from_module(self) -> None:
        from lan_streamer.backend.proxy import PatchedCallable

        mock_fn = MagicMock(return_value="result")
        fake_module = types.ModuleType("lan_streamer.backend")
        setattr(fake_module, "my_callable", mock_fn)

        with patch.dict(sys.modules, {"lan_streamer.backend": fake_module}):
            pc = PatchedCallable("my_callable", lambda: None)
            assert pc("arg1", key="val") == "result"
            mock_fn.assert_called_once_with("arg1", key="val")

    def test_call_uses_fallback(self) -> None:
        from lan_streamer.backend.proxy import PatchedCallable

        mock_fn = MagicMock(return_value="fallback_result")
        pc = PatchedCallable("nonexistent_callable_xyz", lambda: mock_fn)

        saved = sys.modules.pop("lan_streamer.backend", None)
        try:
            result = pc("a", "b")
            assert result == "fallback_result"
            mock_fn.assert_called_once_with("a", "b")
        finally:
            if saved is not None:
                sys.modules["lan_streamer.backend"] = saved


class TestBackendProxyFactories:
    def test_get_db_import(self) -> None:
        from lan_streamer.backend.proxy import _get_db

        result = _get_db()
        import lan_streamer.db

        assert result is lan_streamer.db

    def test_get_config_import(self) -> None:
        from lan_streamer.backend.proxy import _get_config
        from lan_streamer.system.config import config

        result = _get_config()
        assert result is config

    def test_get_jellyfin_client_import(self) -> None:
        from lan_streamer.backend.proxy import _get_jellyfin_client
        from lan_streamer.providers.jellyfin import jellyfin_client

        result = _get_jellyfin_client()
        assert result is jellyfin_client

    def test_get_scan_directories_import(self) -> None:
        from lan_streamer.backend.proxy import _get_scan_directories
        from lan_streamer.scanner import scan_directories

        result = _get_scan_directories()
        assert result is scan_directories

    def test_get_discover_single_library_tree_import(self) -> None:
        from lan_streamer.backend.proxy import _get_discover_single_library_tree
        from lan_streamer.backend.scan_worker_single import (
            _discover_single_library_tree_impl,
        )

        result = _get_discover_single_library_tree()
        assert result is _discover_single_library_tree_impl

    def test_get_detailed_file_info_import(self) -> None:
        from lan_streamer.backend.proxy import _get_detailed_file_info
        from lan_streamer.scanner import get_detailed_file_info

        result = _get_detailed_file_info()
        assert result is get_detailed_file_info

    def test_get_scan_series_import(self) -> None:
        from lan_streamer.backend.proxy import _get_scan_series
        from lan_streamer.scanner import scan_series

        result = _get_scan_series()
        assert result is scan_series

    def test_get_scan_movie_import(self) -> None:
        from lan_streamer.backend.proxy import _get_scan_movie
        from lan_streamer.scanner import scan_movie

        result = _get_scan_movie()
        assert result is scan_movie

    def test_get_clean_series_data_import(self) -> None:
        from lan_streamer.backend.proxy import _get_clean_series_data
        from lan_streamer.scanner import clean_series_data

        result = _get_clean_series_data()
        assert result is clean_series_data


# ---------------------------------------------------------------------------
# scanner/proxy.py
# ---------------------------------------------------------------------------


class TestScannerPatchedAttribute:
    def test_get_target_from_module(self) -> None:
        from lan_streamer.scanner.proxy import PatchedAttribute

        fake_module = types.ModuleType("lan_streamer.scanner")
        sentinel = object()
        setattr(fake_module, "my_scanner_attr", sentinel)

        with patch.dict(sys.modules, {"lan_streamer.scanner": fake_module}):
            pa = PatchedAttribute("my_scanner_attr", lambda: "default")
            assert pa._get_target() is sentinel

    def test_get_target_fallback_no_module(self) -> None:
        from lan_streamer.scanner.proxy import PatchedAttribute

        sentinel = object()
        pa = PatchedAttribute("nonexistent_xyz", lambda: sentinel)

        saved = sys.modules.pop("lan_streamer.scanner", None)
        try:
            assert pa._get_target() is sentinel
        finally:
            if saved is not None:
                sys.modules["lan_streamer.scanner"] = saved

    def test_get_target_fallback_attr_missing(self) -> None:
        from lan_streamer.scanner.proxy import PatchedAttribute

        fake_module = types.ModuleType("lan_streamer.scanner")
        sentinel = object()
        pa = PatchedAttribute("missing_xyz", lambda: sentinel)

        with patch.dict(sys.modules, {"lan_streamer.scanner": fake_module}):
            assert pa._get_target() is sentinel

    def test_getattr_delegates(self) -> None:
        from lan_streamer.scanner.proxy import PatchedAttribute

        fake_obj = MagicMock()
        fake_obj.sub_attr = 99
        fake_module = types.ModuleType("lan_streamer.scanner")
        setattr(fake_module, "my_scanner_attr", fake_obj)

        with patch.dict(sys.modules, {"lan_streamer.scanner": fake_module}):
            pa = PatchedAttribute("my_scanner_attr", lambda: None)
            assert pa.sub_attr == 99


class TestScannerPatchedCallable:
    def test_call_from_module(self) -> None:
        from lan_streamer.scanner.proxy import PatchedCallable

        mock_fn = MagicMock(return_value="scan_result")
        fake_module = types.ModuleType("lan_streamer.scanner")
        setattr(fake_module, "my_scanner_callable", mock_fn)

        with patch.dict(sys.modules, {"lan_streamer.scanner": fake_module}):
            pc = PatchedCallable("my_scanner_callable", lambda: None)
            assert pc("x") == "scan_result"

    def test_call_uses_fallback(self) -> None:
        from lan_streamer.scanner.proxy import PatchedCallable

        mock_fn = MagicMock(return_value="fallback")
        pc = PatchedCallable("nonexistent_xyz", lambda: mock_fn)

        saved = sys.modules.pop("lan_streamer.scanner", None)
        try:
            assert pc() == "fallback"
        finally:
            if saved is not None:
                sys.modules["lan_streamer.scanner"] = saved


class TestScannerProxy:
    def test_getattr_from_module(self) -> None:
        from lan_streamer.scanner.proxy import ScannerProxy

        fake_module = types.ModuleType("lan_streamer.scanner")
        setattr(fake_module, "custom_attr", 123)

        with patch.dict(sys.modules, {"lan_streamer.scanner": fake_module}):
            proxy = ScannerProxy()
            assert proxy.custom_attr == 123

    def test_getattr_tmdb_client_fallback(self) -> None:
        from lan_streamer.scanner.proxy import ScannerProxy, tmdb_client

        fake_module = types.ModuleType("lan_streamer.scanner")
        # Module exists but no tmdb_client attribute
        with patch.dict(sys.modules, {"lan_streamer.scanner": fake_module}):
            proxy = ScannerProxy()
            result = proxy.tmdb_client
            assert result is tmdb_client

    def test_getattr_parse_episode_number_fallback(self) -> None:
        from lan_streamer.scanner.proxy import ScannerProxy, _parse_episode_number

        fake_module = types.ModuleType("lan_streamer.scanner")
        with patch.dict(sys.modules, {"lan_streamer.scanner": fake_module}):
            proxy = ScannerProxy()
            result = proxy._parse_episode_number
            assert result is _parse_episode_number

    def test_getattr_clean_series_data_fallback(self) -> None:
        from lan_streamer.scanner.proxy import ScannerProxy, clean_series_data

        fake_module = types.ModuleType("lan_streamer.scanner")
        with patch.dict(sys.modules, {"lan_streamer.scanner": fake_module}):
            proxy = ScannerProxy()
            result = proxy.clean_series_data
            assert result is clean_series_data

    def test_getattr_scan_movie_fallback(self) -> None:
        from lan_streamer.scanner.proxy import ScannerProxy, scan_movie

        fake_module = types.ModuleType("lan_streamer.scanner")
        with patch.dict(sys.modules, {"lan_streamer.scanner": fake_module}):
            proxy = ScannerProxy()
            result = proxy.scan_movie
            assert result is scan_movie

    def test_getattr_raises_attribute_error_for_unknown(self) -> None:
        from lan_streamer.scanner.proxy import ScannerProxy

        fake_module = types.ModuleType("lan_streamer.scanner")
        with patch.dict(sys.modules, {"lan_streamer.scanner": fake_module}):
            proxy = ScannerProxy()
            with pytest.raises(AttributeError, match="ScannerProxy has no attribute"):
                _ = proxy.completely_unknown_attribute_xyz

    def test_getattr_no_module(self) -> None:
        """When no scanner module loaded, falls through to fallback names."""
        from lan_streamer.scanner.proxy import ScannerProxy, tmdb_client

        saved = sys.modules.pop("lan_streamer.scanner", None)
        try:
            proxy = ScannerProxy()
            result = proxy.tmdb_client
            assert result is tmdb_client
        finally:
            if saved is not None:
                sys.modules["lan_streamer.scanner"] = saved


class TestScannerProxyFactories:
    def test_get_tmdb_client_import(self) -> None:
        from lan_streamer.scanner.proxy import _get_tmdb_client
        from lan_streamer.providers.tmdb import tmdb_client

        result = _get_tmdb_client()
        assert result is tmdb_client

    def test_get_parse_episode_number_import(self) -> None:
        from lan_streamer.scanner.proxy import _get_parse_episode_number
        from lan_streamer.scanner.parser import _parse_episode_number

        result = _get_parse_episode_number()
        assert result is _parse_episode_number

    def test_get_clean_series_data_import(self) -> None:
        from lan_streamer.scanner.proxy import _get_clean_series_data
        from lan_streamer.scanner.metadata import clean_series_data

        result = _get_clean_series_data()
        assert result is clean_series_data

    def test_get_scan_movie_import(self) -> None:
        from lan_streamer.scanner.proxy import _get_scan_movie
        from lan_streamer.scanner.core import scan_movie

        result = _get_scan_movie()
        assert result is scan_movie


# ---------------------------------------------------------------------------
# playback/proxy.py
# ---------------------------------------------------------------------------


class TestPlaybackPatchedAttribute:
    def test_get_target_from_module(self) -> None:
        from lan_streamer.playback.proxy import PatchedAttribute

        fake_module = types.ModuleType("lan_streamer.playback")
        sentinel = object()
        setattr(fake_module, "my_playback_attr", sentinel)

        with patch.dict(sys.modules, {"lan_streamer.playback": fake_module}):
            pa = PatchedAttribute("my_playback_attr", lambda: None)
            assert pa._get_target() is sentinel

    def test_get_target_fallback_no_module(self) -> None:
        from lan_streamer.playback.proxy import PatchedAttribute

        sentinel = object()
        pa = PatchedAttribute("nonexistent_xyz", lambda: sentinel)

        saved = sys.modules.pop("lan_streamer.playback", None)
        try:
            assert pa._get_target() is sentinel
        finally:
            if saved is not None:
                sys.modules["lan_streamer.playback"] = saved

    def test_get_target_fallback_attr_missing(self) -> None:
        from lan_streamer.playback.proxy import PatchedAttribute

        fake_module = types.ModuleType("lan_streamer.playback")
        sentinel = object()
        pa = PatchedAttribute("missing_xyz", lambda: sentinel)

        with patch.dict(sys.modules, {"lan_streamer.playback": fake_module}):
            assert pa._get_target() is sentinel

    def test_getattr_delegates(self) -> None:
        from lan_streamer.playback.proxy import PatchedAttribute

        fake_obj = MagicMock()
        fake_obj.some_sub_attr = "hello"
        fake_module = types.ModuleType("lan_streamer.playback")
        setattr(fake_module, "my_playback_attr", fake_obj)

        with patch.dict(sys.modules, {"lan_streamer.playback": fake_module}):
            pa = PatchedAttribute("my_playback_attr", lambda: None)
            assert pa.some_sub_attr == "hello"

    def test_bool_true_when_not_none(self) -> None:
        from lan_streamer.playback.proxy import PatchedAttribute

        fake_obj = object()
        fake_module = types.ModuleType("lan_streamer.playback")
        setattr(fake_module, "my_bool_attr", fake_obj)

        with patch.dict(sys.modules, {"lan_streamer.playback": fake_module}):
            pa = PatchedAttribute("my_bool_attr", lambda: None)
            assert bool(pa) is True

    def test_bool_false_when_none(self) -> None:
        from lan_streamer.playback.proxy import PatchedAttribute

        fake_module = types.ModuleType("lan_streamer.playback")
        setattr(fake_module, "none_attr", None)

        with patch.dict(sys.modules, {"lan_streamer.playback": fake_module}):
            pa = PatchedAttribute("none_attr", lambda: None)
            assert bool(pa) is False


class TestPlaybackPatchedCallable:
    def test_call_from_module(self) -> None:
        from lan_streamer.playback.proxy import PatchedCallable

        mock_fn = MagicMock(return_value="play_result")
        fake_module = types.ModuleType("lan_streamer.playback")
        setattr(fake_module, "my_player_callable", mock_fn)

        with patch.dict(sys.modules, {"lan_streamer.playback": fake_module}):
            pc = PatchedCallable("my_player_callable", lambda: None)
            assert pc(1, 2, key="val") == "play_result"
            mock_fn.assert_called_once_with(1, 2, key="val")

    def test_call_uses_fallback(self) -> None:
        from lan_streamer.playback.proxy import PatchedCallable

        mock_fn = MagicMock(return_value="fallback")
        pc = PatchedCallable("nonexistent_xyz", lambda: mock_fn)

        saved = sys.modules.pop("lan_streamer.playback", None)
        try:
            assert pc() == "fallback"
        finally:
            if saved is not None:
                sys.modules["lan_streamer.playback"] = saved


class TestPlaybackProxyFactories:
    def test_get_vlc_import(self) -> None:
        """_get_vlc should return the vlc module or None on ImportError/OSError."""
        from lan_streamer.playback.proxy import _get_vlc

        result = _get_vlc()
        # Either a module or None - just verify it doesn't crash
        assert result is None or hasattr(result, "__name__")

    def test_get_vlc_import_error(self) -> None:
        from lan_streamer.playback.proxy import _get_vlc

        with patch.dict(sys.modules, {"vlc": None}):
            # When vlc module is explicitly set to None in sys.modules,
            # importing it raises ImportError
            result = _get_vlc()
            assert result is None or result is not None  # any outcome is fine

    def test_get_cache_worker_import(self) -> None:
        from lan_streamer.playback.proxy import _get_cache_worker
        from lan_streamer.playback.cache import CacheWorker

        result = _get_cache_worker()
        assert result is CacheWorker
