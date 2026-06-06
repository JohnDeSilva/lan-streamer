import pytest
from unittest.mock import patch
from lan_streamer.ui_views import Controller
from lan_streamer.ui_views.dialogs.metadata_match import (
    MetadataMatchDialog,
    JellyfinMatchDialog,
)
from lan_streamer.system.config import config


@pytest.fixture
def mock_match_controller():
    controller = Controller()
    controller.current_library_name = "TV"
    return controller


# ---------------------------------------------------------------------------
# MetadataMatchDialog Tests
# ---------------------------------------------------------------------------


def test_metadata_match_dialog_search_tv(mock_match_controller, qtbot):
    # Setup library config
    config.libraries = {"TV": {"type": "tv"}}
    mock_match_controller.current_library_name = "TV"

    mock_search_results = [
        {
            "id": 12345,
            "name": "Cosmos",
            "first_air_date": "1980-09-28",
            "overview": "Overview of Cosmos",
            "poster_path": "/poster.jpg",
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.metadata_match.tmdb_client.search_series_full",
        return_value=mock_search_results,
    ) as mock_search:
        dialog = MetadataMatchDialog("Cosmos", mock_match_controller)
        qtbot.addWidget(dialog)

        assert dialog.search_input.text() == "Cosmos"

        dialog.execute_search()
        mock_search.assert_called_once_with("Cosmos")

        # Verify results table population
        assert dialog.results_table.rowCount() == 1
        assert dialog.results_table.item(0, 0).text() == "12345"
        assert dialog.results_table.item(0, 1).text() == "Cosmos"
        assert dialog.results_table.item(0, 2).text() == "1980-09-28"
        assert dialog.results_table.item(0, 3).text() == "Overview of Cosmos"


def test_metadata_match_dialog_search_movie(mock_match_controller, qtbot):
    # Setup library config
    config.libraries = {"Movies": {"type": "movie"}}
    mock_match_controller.current_library_name = "Movies"

    mock_search_results = [
        {
            "id": 54321,
            "title": "Interstellar",
            "release_date": "2014-11-07",
            "overview": "Overview of Interstellar",
            "poster_path": "/interstellar_poster.jpg",
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.metadata_match.tmdb_client.search_movie_full",
        return_value=mock_search_results,
    ) as mock_search:
        dialog = MetadataMatchDialog("Interstellar", mock_match_controller)
        qtbot.addWidget(dialog)

        dialog.execute_search()
        mock_search.assert_called_once_with("Interstellar")

        # Verify results table population
        assert dialog.results_table.rowCount() == 1
        assert dialog.results_table.item(0, 0).text() == "54321"
        assert dialog.results_table.item(0, 1).text() == "Interstellar"
        assert dialog.results_table.item(0, 2).text() == "2014-11-07"
        assert dialog.results_table.item(0, 3).text() == "Overview of Interstellar"


def test_metadata_match_dialog_apply(mock_match_controller, qtbot):
    config.libraries = {"TV": {"type": "tv"}}
    mock_match_controller.current_library_name = "TV"

    mock_search_results = [
        {
            "id": 12345,
            "name": "Cosmos",
            "first_air_date": "1980-09-28",
            "overview": "Overview of Cosmos",
            "poster_path": "/poster.jpg",
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.metadata_match.tmdb_client.search_series_full",
        return_value=mock_search_results,
    ):
        dialog = MetadataMatchDialog("Cosmos", mock_match_controller)
        qtbot.addWidget(dialog)
        dialog.execute_search()

        # Apply with no selection
        with patch(
            "lan_streamer.ui_views.dialogs.metadata_match.QMessageBox.warning"
        ) as mock_warning:
            dialog.apply_selected()
            mock_warning.assert_called_once()

        # Apply with selection
        dialog.results_table.selectRow(0)
        with patch.object(mock_match_controller, "apply_metadata_match") as mock_apply:
            dialog.apply_selected()
            mock_apply.assert_called_once_with(
                "Cosmos",
                {
                    "id": "12345",
                    "tmdb_id": "12345",
                    "name": "Cosmos",
                    "first_air_date": "1980-09-28",
                    "overview": "Overview of Cosmos",
                    "poster_path": "/poster.jpg",
                    "provider": "TMDB",
                },
            )


# ---------------------------------------------------------------------------
# JellyfinMatchDialog Tests
# ---------------------------------------------------------------------------


def test_jellyfin_match_dialog_search_tv(mock_match_controller, qtbot):
    config.libraries = {"TV": {"type": "tv"}}
    mock_match_controller.current_library_name = "TV"

    mock_search_results = [
        {
            "Id": "jf-cosmos-123",
            "Name": "Cosmos",
            "ProductionYear": 1980,
            "Overview": "Jellyfin Overview of Cosmos",
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.metadata_match.jellyfin_client.search_series",
        return_value=mock_search_results,
    ) as mock_search:
        dialog = JellyfinMatchDialog("Cosmos", mock_match_controller)
        qtbot.addWidget(dialog)

        assert dialog.search_input.text() == "Cosmos"

        dialog.execute_search()
        mock_search.assert_called_once_with("Cosmos")

        # Verify results table population
        assert dialog.results_table.rowCount() == 1
        assert dialog.results_table.item(0, 0).text() == "jf-cosmos-123"
        assert dialog.results_table.item(0, 1).text() == "Cosmos"
        assert dialog.results_table.item(0, 2).text() == "1980"
        assert dialog.results_table.item(0, 3).text() == "Jellyfin Overview of Cosmos"


def test_jellyfin_match_dialog_search_movie(mock_match_controller, qtbot):
    config.libraries = {"Movies": {"type": "movie"}}
    mock_match_controller.current_library_name = "Movies"

    mock_search_results = [
        {
            "Id": "jf-interstellar-321",
            "Name": "Interstellar",
            "ProductionYear": 2014,
            "Overview": "Jellyfin Overview of Interstellar",
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.metadata_match.jellyfin_client.search_movie",
        return_value=mock_search_results,
    ) as mock_search:
        dialog = JellyfinMatchDialog("Interstellar", mock_match_controller)
        qtbot.addWidget(dialog)

        dialog.execute_search()
        mock_search.assert_called_once_with("Interstellar")

        # Verify results table population
        assert dialog.results_table.rowCount() == 1
        assert dialog.results_table.item(0, 0).text() == "jf-interstellar-321"
        assert dialog.results_table.item(0, 1).text() == "Interstellar"
        assert dialog.results_table.item(0, 2).text() == "2014"
        assert (
            dialog.results_table.item(0, 3).text()
            == "Jellyfin Overview of Interstellar"
        )


def test_jellyfin_match_dialog_apply(mock_match_controller, qtbot):
    config.libraries = {"TV": {"type": "tv"}}
    mock_match_controller.current_library_name = "TV"

    mock_search_results = [
        {
            "Id": "jf-cosmos-123",
            "Name": "Cosmos",
            "ProductionYear": 1980,
            "Overview": "Jellyfin Overview of Cosmos",
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.metadata_match.jellyfin_client.search_series",
        return_value=mock_search_results,
    ):
        dialog = JellyfinMatchDialog("Cosmos", mock_match_controller)
        qtbot.addWidget(dialog)
        dialog.execute_search()

        # Apply with no selection
        with patch(
            "lan_streamer.ui_views.dialogs.metadata_match.QMessageBox.warning"
        ) as mock_warning:
            dialog.apply_selected()
            mock_warning.assert_called_once()

        # Apply with selection
        dialog.results_table.selectRow(0)
        with patch.object(
            mock_match_controller, "apply_jellyfin_watch_match"
        ) as mock_apply:
            dialog.apply_selected()
            mock_apply.assert_called_once_with(
                "Cosmos",
                {
                    "id": "jf-cosmos-123",
                    "name": "Cosmos",
                    "first_air_date": "1980",
                    "overview": "Jellyfin Overview of Cosmos",
                    "provider": "Jellyfin",
                },
            )


# ---------------------------------------------------------------------------
# Extra Edge Case and Non-Standard Title Variety Tests
# ---------------------------------------------------------------------------


def test_metadata_match_dialog_search_non_ascii(mock_match_controller, qtbot):
    config.libraries = {"TV": {"type": "tv"}}
    mock_match_controller.current_library_name = "TV"

    # Anime title with Japanese characters
    mock_search_results = [
        {
            "id": 209867,
            "name": "葬送のフリーレン",
            "first_air_date": "2023-09-29",
            "overview": "Frieren: Beyond Journey's End overview in Japanese.",
            "poster_path": "/frieren_poster.jpg",
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.metadata_match.tmdb_client.search_series_full",
        return_value=mock_search_results,
    ) as mock_search:
        dialog = MetadataMatchDialog("葬送のフリーレン", mock_match_controller)
        qtbot.addWidget(dialog)

        assert dialog.search_input.text() == "葬送のフリーレン"

        dialog.execute_search()
        mock_search.assert_called_once_with("葬送のフリーレン")

        # Verify Unicode name populated correctly
        assert dialog.results_table.rowCount() == 1
        assert dialog.results_table.item(0, 1).text() == "葬送のフリーレン"


def test_metadata_match_dialog_search_special_characters(mock_match_controller, qtbot):
    config.libraries = {"TV": {"type": "tv"}}
    mock_match_controller.current_library_name = "TV"

    # Title with ampersands, commas, periods, quotes
    mock_search_results = [
        {
            "id": 86248,
            "name": "Love, Death & Robots",
            "first_air_date": "2019-03-15",
            "overview": "This collection of animated stories spans several genres.",
            "poster_path": "/ldr.jpg",
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.metadata_match.tmdb_client.search_series_full",
        return_value=mock_search_results,
    ) as mock_search:
        dialog = MetadataMatchDialog("Love, Death & Robots", mock_match_controller)
        qtbot.addWidget(dialog)

        dialog.execute_search()
        mock_search.assert_called_once_with("Love, Death & Robots")

        # Verify table name handles special chars correctly
        assert dialog.results_table.rowCount() == 1
        assert dialog.results_table.item(0, 1).text() == "Love, Death & Robots"


def test_metadata_match_dialog_search_null_api_fields(mock_match_controller, qtbot):
    config.libraries = {"TV": {"type": "tv"}}
    mock_match_controller.current_library_name = "TV"

    # API returns None for various fields
    mock_search_results = [
        {
            "id": None,
            "name": None,
            "first_air_date": None,
            "overview": None,
            "poster_path": None,
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.metadata_match.tmdb_client.search_series_full",
        return_value=mock_search_results,
    ):
        dialog = MetadataMatchDialog("NullShow", mock_match_controller)
        qtbot.addWidget(dialog)

        # Triggers execute_search and verifies it parses null fields without TypeError/AttributeError
        dialog.execute_search()

        assert dialog.results_table.rowCount() == 1
        # ID gets mapped via str(None or "") -> ""
        assert dialog.results_table.item(0, 0).text() == ""
        # Others mapped via None or "" -> ""
        assert dialog.results_table.item(0, 1).text() == ""
        assert dialog.results_table.item(0, 2).text() == ""
        assert dialog.results_table.item(0, 3).text() == ""


def test_jellyfin_match_dialog_search_null_api_fields(mock_match_controller, qtbot):
    config.libraries = {"TV": {"type": "tv"}}
    mock_match_controller.current_library_name = "TV"

    # Jellyfin returns null values for fields
    mock_search_results = [
        {
            "Id": None,
            "Name": None,
            "ProductionYear": None,
            "Overview": None,
        }
    ]

    with patch(
        "lan_streamer.ui_views.dialogs.metadata_match.jellyfin_client.search_series",
        return_value=mock_search_results,
    ):
        dialog = JellyfinMatchDialog("NullShow", mock_match_controller)
        qtbot.addWidget(dialog)

        # Triggers execute_search and verifies it parses null fields without TypeError
        dialog.execute_search()

        assert dialog.results_table.rowCount() == 1
        assert dialog.results_table.item(0, 0).text() == ""
        assert dialog.results_table.item(0, 1).text() == ""
        assert dialog.results_table.item(0, 2).text() == ""
        assert dialog.results_table.item(0, 3).text() == ""
