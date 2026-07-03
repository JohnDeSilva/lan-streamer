from unittest.mock import MagicMock, patch

from lan_streamer.services.smart_row_service import SmartRowService


class TestSmartRowService:
    """Tests for SmartRowService."""

    def setup_method(self) -> None:
        self.service = SmartRowService()
        self.service._rebuild_affected_configs = MagicMock(return_value=["hash-1"])

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

    def test_rebuild_for_libraries(self) -> None:
        result = self.service.rebuild_for_libraries(["TV"])
        self.service._rebuild_affected_configs.assert_called_once_with(["TV"])
        assert result == ["hash-1"]

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
