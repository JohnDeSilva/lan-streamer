from unittest.mock import MagicMock, patch

from lan_streamer.services.smart_row_service import SmartRowService


class TestSmartRowService:
    """Tests for SmartRowService."""

    def setup_method(self) -> None:
        self.service = SmartRowService()
        self.service._rebuild_affected_configs = MagicMock(return_value=["hash-1"])

    def test_on_scan_completed_no_libraries(self) -> None:
        with patch(
            "lan_streamer.services.smart_row_service.db.rebuild_all_cache"
        ) as mock_rebuild:
            self.service.on_scan_completed(affected_libraries=None)
            mock_rebuild.assert_called_once()

    def test_on_scan_completed_with_libraries(self) -> None:
        affected = ["TV"]
        with (
            patch(
                "lan_streamer.services.smart_row_service.db.get_affected_config_hashes_for_libraries",
                return_value=["hash-1"],
            ),
            patch(
                "lan_streamer.services.smart_row_service.db.clear_cache_for_config_hashes"
            ) as mock_clear,
        ):
            self.service._rebuild_affected_configs = MagicMock()
            self.service.on_scan_completed(affected_libraries=affected)
            mock_clear.assert_called_once_with(["hash-1"])
            self.service._rebuild_affected_configs.assert_called_once_with(affected)

    def test_on_scan_completed_background_runner(self) -> None:
        runner = MagicMock()
        service = SmartRowService(background_runner=runner)
        service.on_scan_completed(affected_libraries=None)
        runner.assert_called_once()
        # The runner should have been called with a callable
        callable_fn = runner.call_args[0][0]
        with patch(
            "lan_streamer.services.smart_row_service.db.rebuild_all_cache"
        ) as mock_rebuild:
            callable_fn()
            mock_rebuild.assert_called_once()

    def test_on_episode_watched_resolves_libraries(self) -> None:
        with patch.object(
            self.service, "_resolve_libraries_for_path", return_value=["TV"]
        ) as mock_resolve:
            result = self.service.on_episode_watched("/path/to/episode.mkv")
            mock_resolve.assert_called_once_with("/path/to/episode.mkv")
            self.service._rebuild_affected_configs.assert_called_once_with(["TV"])
            assert result == ["hash-1"]

    def test_on_episode_watched_no_libraries(self) -> None:
        with patch.object(self.service, "_resolve_libraries_for_path", return_value=[]):
            result = self.service.on_episode_watched("/path/to/episode.mkv")
            assert result == []

    def test_on_movie_watched(self) -> None:
        result = self.service.on_movie_watched("Test Movie", "Movies")
        self.service._rebuild_affected_configs.assert_called_once_with(["Movies"])
        assert result == ["hash-1"]

    def test_rebuild_for_libraries(self) -> None:
        result = self.service.rebuild_for_libraries(["TV"])
        self.service._rebuild_affected_configs.assert_called_once_with(["TV"])
        assert result == ["hash-1"]

    def test_on_libraries_changed(self) -> None:
        with patch(
            "lan_streamer.services.smart_row_service.db.rebuild_all_cache"
        ) as mock_rebuild:
            self.service.on_libraries_changed()
            mock_rebuild.assert_called_once()

    def test_on_libraries_changed_with_runner(self) -> None:
        runner = MagicMock()
        service = SmartRowService(background_runner=runner)
        service.on_libraries_changed()
        runner.assert_called_once()
        callable_fn = runner.call_args[0][0]
        with patch(
            "lan_streamer.services.smart_row_service.db.rebuild_all_cache"
        ) as mock_rebuild:
            callable_fn()
            mock_rebuild.assert_called_once()

    def test_rebuild_no_libraries(self) -> None:
        with patch(
            "lan_streamer.services.smart_row_service.db.rebuild_all_cache"
        ) as mock_rebuild:
            self.service._rebuild(affected_libraries=None)
            mock_rebuild.assert_called_once()

    def test_rebuild_with_libraries(self) -> None:
        with (
            patch(
                "lan_streamer.services.smart_row_service.db.get_affected_config_hashes_for_libraries",
                return_value=["hash-1"],
            ),
            patch(
                "lan_streamer.services.smart_row_service.db.clear_cache_for_config_hashes"
            ) as mock_clear,
        ):
            service = SmartRowService()
            service._rebuild_affected_configs = MagicMock(return_value=["hash-1"])
            service._rebuild(affected_libraries=["TV"])
            mock_clear.assert_called_once_with(["hash-1"])
            service._rebuild_affected_configs.assert_called_once_with(["TV"])

    def test_rebuild_with_libraries_skips_if_no_hashes(self) -> None:
        with (
            patch(
                "lan_streamer.services.smart_row_service.db.get_affected_config_hashes_for_libraries",
                return_value=[],
            ),
            patch(
                "lan_streamer.services.smart_row_service.db.clear_cache_for_config_hashes"
            ) as mock_clear,
        ):
            service = SmartRowService()
            service._rebuild_affected_configs = MagicMock()
            service._rebuild(affected_libraries=["TV"])
            mock_clear.assert_not_called()
            service._rebuild_affected_configs.assert_not_called()

    def test_rebuild_affected_configs(self) -> None:
        test_configs = [
            {
                "name": "TV Row",
                "enabled": True,
                "libraries": ["TV"],
                "sort_by": "Alphabetical",
                "filter_mode": "All",
            },
        ]
        with (
            patch(
                "lan_streamer.services.smart_row_service.app_config.combined_views",
                test_configs,
            ),
            patch("lan_streamer.services.smart_row_service.app_config.load"),
            patch(
                "lan_streamer.services.smart_row_service.db.rebuild_cache_for_config"
            ) as mock_rebuild,
        ):
            service = SmartRowService()
            result = service._rebuild_affected_configs(["TV"])
            assert len(result) > 0
            mock_rebuild.assert_called_once()

    def test_rebuild_affected_configs_skips_non_matching(self) -> None:
        test_configs = [
            {
                "name": "Movies Row",
                "enabled": True,
                "libraries": ["Movies"],
                "sort_by": "Alphabetical",
                "filter_mode": "All",
            },
        ]
        with (
            patch(
                "lan_streamer.services.smart_row_service.app_config.combined_views",
                test_configs,
            ),
            patch("lan_streamer.services.smart_row_service.app_config.load"),
            patch(
                "lan_streamer.services.smart_row_service.db.rebuild_cache_for_config"
            ) as mock_rebuild,
        ):
            service = SmartRowService()
            result = service._rebuild_affected_configs(["TV"])
            # TV is not in "Movies" library, so nothing to rebuild
            assert len(result) == 0
            mock_rebuild.assert_not_called()

    def test_resolve_libraries_for_path_not_found(self) -> None:
        with patch("lan_streamer.db.connection.get_session"):
            result = self.service._resolve_libraries_for_path("/nonexistent.mkv")
            assert isinstance(result, list)

    def test_resolve_libraries_for_path_error(self) -> None:
        with patch(
            "lan_streamer.db.connection.get_session",
            side_effect=Exception("DB error"),
        ):
            result = self.service._resolve_libraries_for_path("/path/file.mkv")
            assert result == []

    def test_rebuild_affected_configs_empty_library_matches_all(self) -> None:
        test_configs = [
            {
                "name": "All Libraries",
                "enabled": True,
                "libraries": [],
                "sort_by": "Alphabetical",
                "filter_mode": "All",
            },
        ]
        with (
            patch(
                "lan_streamer.services.smart_row_service.app_config.combined_views",
                test_configs,
            ),
            patch("lan_streamer.services.smart_row_service.app_config.load"),
            patch(
                "lan_streamer.services.smart_row_service.db.rebuild_cache_for_config"
            ) as mock_rebuild,
        ):
            service = SmartRowService()
            result = service._rebuild_affected_configs(["TV"])
            assert len(result) > 0
            mock_rebuild.assert_called_once()
