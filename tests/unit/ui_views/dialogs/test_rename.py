import pytest
from unittest.mock import patch
from PySide6.QtCore import Qt
from lan_streamer.ui_views import Controller
from lan_streamer.ui_views.dialogs.rename import EpisodeMatchDialog, RenamePreviewDialog


@pytest.fixture
def mock_rename_controller():
    controller = Controller()
    controller.cached_library_data = {
        "Cosmos": {
            "metadata": {
                "tmdb_identifier": "12345",
                "tmdb_name": "Cosmos",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "season_number": 1,
                    "episodes": [
                        {
                            "path": "/media/tv/Cosmos/Season 1/S01E01.mkv",
                            "name": "S01E01.mkv",
                            "tmdb_number": 1,
                            "air_date": "1980-01-01",
                        },
                        {
                            "path": "/media/tv/Cosmos/Season 1/S01E02.mkv",
                            "name": "S01E02.mkv",
                            "tmdb_number": 2,
                            "air_date": "1980-01-08",
                        },
                    ],
                }
            },
        }
    }
    controller.current_library_name = "TV"
    return controller


# ---------------------------------------------------------------------------
# EpisodeMatchDialog Tests
# ---------------------------------------------------------------------------


def test_episode_match_dialog_init_with_tmdb_id(mock_rename_controller, qtbot):
    mock_seasons = [{"season_number": 1, "name": "Season 1"}]
    mock_episodes = [
        {
            "id": 101,
            "episode_number": 1,
            "name": "The Shores of the Cosmic Ocean",
            "air_date": "1980-09-28",
            "overview": "Overview of episode 1",
            "runtime": 60,
        }
    ]

    with (
        patch(
            "lan_streamer.ui_views.dialogs.rename.tmdb_client.get_seasons",
            return_value=mock_seasons,
        ) as mock_get_seasons,
        patch(
            "lan_streamer.ui_views.dialogs.rename.tmdb_client.get_episodes",
            return_value=mock_episodes,
        ) as mock_get_episodes,
        patch(
            "lan_streamer.ui_views.dialogs.rename.tmdb_client.search_series"
        ) as mock_search_series,
    ):
        dialog = EpisodeMatchDialog(
            "Cosmos",
            "/media/tv/Cosmos/Season 1/S01E01.mkv",
            mock_rename_controller,
        )
        qtbot.addWidget(dialog)

        # Assert TMDB id was retrieved from controller metadata, not via search
        assert dialog.tmdb_identifier == "12345"
        mock_search_series.assert_not_called()
        mock_get_seasons.assert_called_once_with("12345")
        mock_get_episodes.assert_called_once_with("12345", 1)

        # Verify season combo box items
        assert dialog.season_selector.count() == 1
        assert dialog.season_selector.itemText(0) == "Season 1"

        # Verify results table population
        assert dialog.results_table.rowCount() == 1
        assert dialog.results_table.item(0, 0).text() == "1"
        assert (
            dialog.results_table.item(0, 1).text() == "The Shores of the Cosmic Ocean"
        )
        assert dialog.results_table.item(0, 2).text() == "1980-09-28"
        assert dialog.results_table.item(0, 3).text() == "Overview of episode 1"


def test_episode_match_dialog_init_without_tmdb_id(mock_rename_controller, qtbot):
    # Clear TMDB identifier to force TMDB search
    mock_rename_controller.cached_library_data["Cosmos"]["metadata"][
        "tmdb_identifier"
    ] = ""

    mock_search_result = {"id": 54321, "name": "Cosmos"}
    mock_seasons = [{"season_number": 2, "name": "Season 2"}]
    mock_episodes = []

    with (
        patch(
            "lan_streamer.ui_views.dialogs.rename.tmdb_client.search_series",
            return_value=mock_search_result,
        ) as mock_search,
        patch(
            "lan_streamer.ui_views.dialogs.rename.tmdb_client.get_seasons",
            return_value=mock_seasons,
        ) as mock_get_seasons,
        patch(
            "lan_streamer.ui_views.dialogs.rename.tmdb_client.get_episodes",
            return_value=mock_episodes,
        ) as mock_get_episodes,
    ):
        dialog = EpisodeMatchDialog(
            "Cosmos",
            "/media/tv/Cosmos/Season 1/S01E01.mkv",
            mock_rename_controller,
        )
        qtbot.addWidget(dialog)

        # Assert TMDB search series was called
        mock_search.assert_called_once_with("Cosmos")
        assert dialog.tmdb_identifier == "54321"
        mock_get_seasons.assert_called_once_with("54321")
        mock_get_episodes.assert_called_once_with("54321", 2)


def test_episode_match_dialog_apply_no_selection(mock_rename_controller, qtbot):
    mock_seasons = [{"season_number": 1, "name": "Season 1"}]
    mock_episodes = []

    with (
        patch(
            "lan_streamer.ui_views.dialogs.rename.tmdb_client.get_seasons",
            return_value=mock_seasons,
        ),
        patch(
            "lan_streamer.ui_views.dialogs.rename.tmdb_client.get_episodes",
            return_value=mock_episodes,
        ),
    ):
        dialog = EpisodeMatchDialog(
            "Cosmos",
            "/media/tv/Cosmos/Season 1/S01E01.mkv",
            mock_rename_controller,
        )
        qtbot.addWidget(dialog)

        with patch(
            "lan_streamer.ui_views.dialogs.rename.QMessageBox.warning"
        ) as mock_warning:
            dialog.apply_selected()
            mock_warning.assert_called_once()


def test_episode_match_dialog_apply_with_selection(mock_rename_controller, qtbot):
    mock_seasons = [{"season_number": 1, "name": "Season 1"}]
    mock_episodes = [
        {
            "id": 101,
            "episode_number": 1,
            "name": "The Shores of the Cosmic Ocean",
            "air_date": "1980-09-28",
            "overview": "Overview",
            "runtime": 60,
        }
    ]

    with (
        patch(
            "lan_streamer.ui_views.dialogs.rename.tmdb_client.get_seasons",
            return_value=mock_seasons,
        ),
        patch(
            "lan_streamer.ui_views.dialogs.rename.tmdb_client.get_episodes",
            return_value=mock_episodes,
        ),
    ):
        dialog = EpisodeMatchDialog(
            "Cosmos",
            "/media/tv/Cosmos/Season 1/S01E01.mkv",
            mock_rename_controller,
        )
        qtbot.addWidget(dialog)

        # Select the first row
        dialog.results_table.selectRow(0)

        with patch.object(
            mock_rename_controller, "apply_episode_metadata_match"
        ) as mock_apply:
            dialog.apply_selected()
            mock_apply.assert_called_once_with(
                "Cosmos",
                "/media/tv/Cosmos/Season 1/S01E01.mkv",
                {
                    "id": "101",
                    "episode_number": 1,
                    "name": "The Shores of the Cosmic Ocean",
                    "air_date": "1980-09-28",
                    "overview": "Overview",
                    "runtime": 60,
                },
            )


# ---------------------------------------------------------------------------
# RenamePreviewDialog Tests
# ---------------------------------------------------------------------------


def test_rename_preview_dialog_init_and_preview(mock_rename_controller, qtbot):
    mock_rename_preview_data = [
        {
            "old_path": "/media/tv/Cosmos/Season 1/S01E01.mkv",
            "new_name": "Cosmos S01E01 - The Shores of the Cosmic Ocean.mkv",
            "season": "Season 1",
            "is_subtitle": False,
        },
        {
            "old_path": "/media/tv/Cosmos/Season 1/S01E01.en.srt",
            "new_name": "Cosmos S01E01 - The Shores of the Cosmic Ocean.en.srt",
            "season": "Season 1",
            "is_subtitle": True,
        },
    ]

    with patch(
        "lan_streamer.scanner.renamer.get_rename_preview",
        return_value=mock_rename_preview_data,
    ) as mock_get_preview:
        dialog = RenamePreviewDialog("Cosmos", mock_rename_controller)
        qtbot.addWidget(dialog)

        # Verify preview tree structure
        # There should be 1 root item (Season 1) which has 1 child item (the video file, since subtitle is filtered out from display)
        assert dialog.preview_tree.topLevelItemCount() == 1
        season_item = dialog.preview_tree.topLevelItem(0)
        assert season_item.text(0) == "Season 1"
        assert season_item.childCount() == 1

        episode_item = season_item.child(0)
        assert episode_item.text(0) == "S01E01.mkv"
        assert (
            episode_item.text(1) == "Cosmos S01E01 - The Shores of the Cosmic Ocean.mkv"
        )
        mock_get_preview.assert_called_once()


def test_rename_preview_dialog_on_tree_item_changed(mock_rename_controller, qtbot):
    mock_rename_preview_data = [
        {
            "old_path": "/media/tv/Cosmos/Season 1/S01E01.mkv",
            "new_name": "Cosmos S01E01.mkv",
            "season": "Season 1",
            "is_subtitle": False,
        },
        {
            "old_path": "/media/tv/Cosmos/Season 1/S01E02.mkv",
            "new_name": "Cosmos S01E02.mkv",
            "season": "Season 1",
            "is_subtitle": False,
        },
    ]

    with patch(
        "lan_streamer.scanner.renamer.get_rename_preview",
        return_value=mock_rename_preview_data,
    ):
        dialog = RenamePreviewDialog("Cosmos", mock_rename_controller)
        qtbot.addWidget(dialog)

        season_item = dialog.preview_tree.topLevelItem(0)
        child1 = season_item.child(0)
        child2 = season_item.child(1)

        # Initially, all are checked
        assert season_item.checkState(0) == Qt.CheckState.Checked
        assert child1.checkState(0) == Qt.CheckState.Checked
        assert child2.checkState(0) == Qt.CheckState.Checked

        # 1. Check parent -> uncheck parent should uncheck both children
        season_item.setCheckState(0, Qt.CheckState.Unchecked)
        # Tree widget signals are handled, checking state of children:
        assert child1.checkState(0) == Qt.CheckState.Unchecked
        assert child2.checkState(0) == Qt.CheckState.Unchecked

        # 2. Check child1 -> parent should be partially checked
        child1.setCheckState(0, Qt.CheckState.Checked)
        assert season_item.checkState(0) == Qt.CheckState.PartiallyChecked

        # 3. Check child2 -> parent should become checked
        child2.setCheckState(0, Qt.CheckState.Checked)
        assert season_item.checkState(0) == Qt.CheckState.Checked


def test_rename_preview_apply_no_selection(mock_rename_controller, qtbot):
    mock_rename_preview_data = [
        {
            "old_path": "/media/tv/Cosmos/Season 1/S01E01.mkv",
            "new_name": "Cosmos S01E01.mkv",
            "season": "Season 1",
            "is_subtitle": False,
        }
    ]

    with patch(
        "lan_streamer.scanner.renamer.get_rename_preview",
        return_value=mock_rename_preview_data,
    ):
        dialog = RenamePreviewDialog("Cosmos", mock_rename_controller)
        qtbot.addWidget(dialog)

        # Uncheck the only item
        season_item = dialog.preview_tree.topLevelItem(0)
        season_item.setCheckState(0, Qt.CheckState.Unchecked)

        with patch(
            "lan_streamer.ui_views.dialogs.rename.QMessageBox.warning"
        ) as mock_warning:
            dialog.apply_renames()
            mock_warning.assert_called_once()


def test_rename_preview_apply_with_selection(mock_rename_controller, qtbot):
    mock_rename_preview_data = [
        {
            "old_path": "/media/tv/Cosmos/Season 1/S01E01.mkv",
            "new_name": "Cosmos S01E01.mkv",
            "season": "Season 1",
            "is_subtitle": False,
        },
        # Associated subtitle file
        {
            "old_path": "/media/tv/Cosmos/Season 1/S01E01.en.srt",
            "new_name": "Cosmos S01E01.en.srt",
            "season": "Season 1",
            "is_subtitle": True,
        },
        # Unrelated subtitle file
        {
            "old_path": "/media/tv/Cosmos/Season 1/S01E02.en.srt",
            "new_name": "Cosmos S01E02.en.srt",
            "season": "Season 1",
            "is_subtitle": True,
        },
    ]

    with patch(
        "lan_streamer.scanner.renamer.get_rename_preview",
        return_value=mock_rename_preview_data,
    ):
        dialog = RenamePreviewDialog("Cosmos", mock_rename_controller)
        qtbot.addWidget(dialog)

        with patch.object(mock_rename_controller, "apply_rename_batch") as mock_apply:
            dialog.apply_renames()
            mock_apply.assert_called_once()
            applied_list = mock_apply.call_args[0][0]
            # Should have the S01E01 video and S01E01 subtitle, but not S01E02 subtitle since its video is not checked/present
            assert len(applied_list) == 2
            video_paths = {p["old_path"] for p in applied_list}
            assert "/media/tv/Cosmos/Season 1/S01E01.mkv" in video_paths
            assert "/media/tv/Cosmos/Season 1/S01E01.en.srt" in video_paths
            assert "/media/tv/Cosmos/Season 1/S01E02.en.srt" not in video_paths
