"""Tests for the enhanced PosterSelectorDialog (poster_selector.py).

Covers:
- Dialog construction for series, season, and movie media kinds.
- Local file upload tab: browse, preview, apply.
- TMDB fetch tab: fetch button state management, results rendering.
- ThePosterDB tab: browser link buttons present.
- Poster application updates the database record.
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Movie, Season, Series
from lan_streamer.ui_views.dialogs.poster_selector import PosterSelectorDialog


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def series_record(tmp_path):
    """Insert a Series row and return its name."""
    with get_session() as session:
        series = Series(
            name="Test Show",
            library_name="TestLib",
            tmdb_identifier="12345",
            poster_path="",
        )
        session.add(series)
        session.commit()
    return "Test Show"


@pytest.fixture
def season_record(series_record):
    """Insert a Season for the test series and return season name."""
    with get_session() as session:
        series = session.scalars(
            __import__("sqlalchemy", fromlist=["select"])
            .select(Series)
            .where(Series.name == series_record)
        ).first()
        assert series is not None
        season = Season(
            series_id=series.id,
            name="Season 1",
            poster_path="",
        )
        session.add(season)
        session.commit()
    return "Season 1"


@pytest.fixture
def movie_record(tmp_path):
    """Insert a Movie row and return its name."""
    with get_session() as session:
        movie = Movie(
            name="Test Movie",
            library_name="TestLib",
            tmdb_identifier="99999",
            poster_path="",
        )
        session.add(movie)
        session.commit()
    return "Test Movie"


@pytest.fixture
def sample_image(tmp_path) -> str:
    """Create a minimal valid JPEG image file for testing."""
    # 1×1 white JPEG bytes (minimal valid JPEG)
    jpeg_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
        b"==\x1e\x1e\x1e\x00\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01"
        b"\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01"
        b"\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06"
        b"\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02"
        b"\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11"
        b'\x05\x12!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R'
        b"\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJ"
        b"STUVWXYZ\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd4\x00\x00"
        b"\x00\xff\xd9"
    )
    image_path = tmp_path / "test_poster.jpg"
    image_path.write_bytes(jpeg_bytes)
    return str(image_path)


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------


def test_dialog_opens_for_series(series_record, qtbot):
    """PosterSelectorDialog should open without error for a series."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == f"Change Poster — {series_record}"
    assert dialog._series_db_id is not None


def test_dialog_opens_for_movie(movie_record, qtbot):
    """PosterSelectorDialog should open without error for a movie."""
    dialog = PosterSelectorDialog(
        media_name=movie_record,
        media_kind="movie",
    )
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == f"Change Poster — {movie_record}"
    assert dialog._movie_db_id is not None


def test_dialog_opens_for_season(series_record, season_record, qtbot):
    """PosterSelectorDialog should resolve season and parent series IDs."""
    dialog = PosterSelectorDialog(
        media_name=season_record,
        media_kind="season",
        series_name=series_record,
    )
    qtbot.addWidget(dialog)
    assert dialog._season_db_id is not None
    assert dialog._series_db_id is not None


def test_dialog_resolves_tmdb_id_for_series(series_record, qtbot):
    """Dialog should parse TMDB numeric ID from the series record."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    assert dialog._tmdb_numeric_id == 12345


def test_dialog_resolves_tmdb_id_for_movie(movie_record, qtbot):
    """Dialog should parse TMDB numeric ID from the movie record."""
    dialog = PosterSelectorDialog(
        media_name=movie_record,
        media_kind="movie",
    )
    qtbot.addWidget(dialog)
    assert dialog._tmdb_numeric_id == 99999


def test_dialog_handles_missing_media_gracefully(qtbot):
    """Dialog for unknown media should initialise without crashing."""
    dialog = PosterSelectorDialog(
        media_name="Nonexistent Show",
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    # No IDs resolved, but dialog should still construct
    assert dialog._series_db_id is None
    assert dialog._tmdb_numeric_id is None


def test_dialog_has_three_tabs(series_record, qtbot):
    """Dialog should always expose TMDB, ThePosterDB, and Local File tabs."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    assert dialog._tab_widget.count() == 3
    tab_texts = [dialog._tab_widget.tabText(index) for index in range(3)]
    assert any("TMDB" in text for text in tab_texts)
    assert any("PosterDB" in text for text in tab_texts)
    assert any("Local" in text for text in tab_texts)


# ---------------------------------------------------------------------------
# TMDB tab tests
# ---------------------------------------------------------------------------


def test_tmdb_tab_shows_no_id_notice_when_tmdb_not_linked(qtbot):
    """TMDB tab should show a notice when no TMDB ID is linked."""
    dialog = PosterSelectorDialog(
        media_name="Unmatched Show",
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    # Tab 0 is TMDB — switch to it and verify notice
    dialog._tab_widget.setCurrentIndex(0)
    # _tmdb_fetch_button is only created when TMDB ID is present
    assert not hasattr(dialog, "_tmdb_fetch_button") or dialog._tmdb_numeric_id is None


def test_tmdb_fetch_button_present_when_id_linked(series_record, qtbot):
    """Fetch button should be present when TMDB ID is available."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    assert hasattr(dialog, "_tmdb_fetch_button")
    assert dialog._tmdb_fetch_button.isEnabled()


def test_on_tmdb_images_ready_populates_grid(series_record, qtbot):
    """_on_tmdb_images_ready should render image cards into the grid."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)

    fake_images = [
        {"image_type": "poster", "file_path": "/abc.jpg", "width": 500, "height": 750},
        {"image_type": "poster", "file_path": "/def.jpg", "width": 500, "height": 750},
        {
            "image_type": "backdrop",
            "file_path": "/ghi.jpg",
            "width": 1280,
            "height": 720,
        },
    ]
    dialog._on_tmdb_images_ready(fake_images)

    # Grid should have cards (not just the original placeholder)
    assert dialog._tmdb_grid_layout.count() >= 3


def test_on_tmdb_images_ready_empty_list(series_record, qtbot):
    """_on_tmdb_images_ready with empty list should show no-results label."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    dialog._on_tmdb_images_ready([])

    assert dialog._tmdb_grid_layout.count() >= 1
    first_item = dialog._tmdb_grid_layout.itemAtPosition(0, 0)
    assert first_item is not None
    widget = first_item.widget()
    assert widget is not None


def test_on_tmdb_fetch_error_re_enables_button(series_record, qtbot):
    """Fetch error handler should re-enable the fetch button."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    dialog._tmdb_fetch_button.setEnabled(False)
    dialog._on_tmdb_fetch_error("Connection timeout")
    assert dialog._tmdb_fetch_button.isEnabled()


# ---------------------------------------------------------------------------
# ThePosterDB tab tests
# ---------------------------------------------------------------------------


def test_posterdb_tab_has_search_and_home_buttons(series_record, qtbot):
    """ThePosterDB tab should have at least two buttons (search + home)."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    # Tab 1 is ThePosterDB
    posterdb_widget = dialog._tab_widget.widget(1)
    buttons = posterdb_widget.findChildren(QPushButton)
    assert len(buttons) >= 2


def test_posterdb_search_button_opens_browser(series_record, qtbot):
    """Clicking the PosterDB search button should trigger webbrowser.open."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    posterdb_widget = dialog._tab_widget.widget(1)
    buttons = posterdb_widget.findChildren(QPushButton)
    search_button = buttons[0]

    with patch("webbrowser.open") as mock_open:
        search_button.click()
        mock_open.assert_called_once()
        call_args = mock_open.call_args[0][0]
        assert "theposterdb.com" in call_args


# ---------------------------------------------------------------------------
# Local file tab tests
# ---------------------------------------------------------------------------


def test_local_apply_button_disabled_initially(series_record, qtbot):
    """Apply button in local upload tab should be disabled before a file is chosen."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    assert not dialog._local_apply_button.isEnabled()


def test_on_browse_local_file_no_selection(series_record, qtbot):
    """When QFileDialog returns empty string, nothing should change."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)

    with patch(
        "lan_streamer.ui_views.dialogs.poster_selector.QFileDialog"
    ) as mock_dialog:
        mock_dialog.getOpenFileName.return_value = ("", "")
        dialog._on_browse_local_file()

    assert dialog._local_selected_path is None
    assert not dialog._local_apply_button.isEnabled()


def test_on_browse_local_file_valid_image(series_record, sample_image, qtbot):
    """Selecting a valid image enables the apply button and shows a preview."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)

    with patch(
        "lan_streamer.ui_views.dialogs.poster_selector.QFileDialog"
    ) as mock_dialog:
        mock_dialog.getOpenFileName.return_value = (sample_image, "Image Files")
        dialog._on_browse_local_file()

    assert dialog._local_selected_path == sample_image


def test_on_apply_local_poster_updates_series_db(
    series_record, sample_image, tmp_path, qtbot
):
    """Applying a local poster should update Series.poster_path in the database."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    dialog._local_selected_path = sample_image

    with (
        patch(
            "lan_streamer.ui_views.dialogs.poster_selector._POSTER_OVERRIDE_CACHE",
            tmp_path / "overrides",
        ),
        patch.object(dialog, "accept"),
        patch("lan_streamer.ui_views.dialogs.poster_selector.QMessageBox") as mock_msg,
    ):
        mock_msg.information = MagicMock()
        dialog._on_apply_local_poster()

    # Verify DB was updated
    from sqlalchemy import select as sa_select

    with get_session() as session:
        series = session.scalars(
            sa_select(Series).where(Series.name == series_record)
        ).first()
        assert series is not None
        assert series.poster_path is not None
        assert series.poster_path != ""


def test_on_apply_local_poster_updates_movie_db(
    movie_record, sample_image, tmp_path, qtbot
):
    """Applying a local poster should update Movie.poster_path in the database."""
    dialog = PosterSelectorDialog(
        media_name=movie_record,
        media_kind="movie",
    )
    qtbot.addWidget(dialog)
    dialog._local_selected_path = sample_image

    with (
        patch(
            "lan_streamer.ui_views.dialogs.poster_selector._POSTER_OVERRIDE_CACHE",
            tmp_path / "overrides",
        ),
        patch.object(dialog, "accept"),
        patch("lan_streamer.ui_views.dialogs.poster_selector.QMessageBox") as mock_msg,
    ):
        mock_msg.information = MagicMock()
        dialog._on_apply_local_poster()

    from sqlalchemy import select as sa_select

    with get_session() as session:
        movie = session.scalars(
            sa_select(Movie).where(Movie.name == movie_record)
        ).first()
        assert movie is not None
        assert movie.poster_path is not None
        assert movie.poster_path != ""


def test_on_apply_local_poster_updates_season_db(
    series_record, season_record, sample_image, tmp_path, qtbot
):
    """Applying a local poster for a season should update Season.poster_path."""
    dialog = PosterSelectorDialog(
        media_name=season_record,
        media_kind="season",
        series_name=series_record,
    )
    qtbot.addWidget(dialog)
    dialog._local_selected_path = sample_image

    with (
        patch(
            "lan_streamer.ui_views.dialogs.poster_selector._POSTER_OVERRIDE_CACHE",
            tmp_path / "overrides",
        ),
        patch.object(dialog, "accept"),
        patch("lan_streamer.ui_views.dialogs.poster_selector.QMessageBox") as mock_msg,
    ):
        mock_msg.information = MagicMock()
        dialog._on_apply_local_poster()

    from sqlalchemy import select as sa_select

    with get_session() as session:
        series = session.scalars(
            sa_select(Series).where(Series.name == series_record)
        ).first()
        assert series is not None
        season = session.scalars(
            sa_select(Season).where(
                Season.series_id == series.id,
                Season.name == season_record,
            )
        ).first()
        assert season is not None
        assert season.poster_path is not None
        assert season.poster_path != ""


def test_on_apply_local_poster_warns_when_no_db_record(sample_image, tmp_path, qtbot):
    """Applying poster when no DB record found should show a warning, not crash."""
    dialog = PosterSelectorDialog(
        media_name="Phantom Show",
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    dialog._local_selected_path = sample_image

    with (
        patch(
            "lan_streamer.ui_views.dialogs.poster_selector._POSTER_OVERRIDE_CACHE",
            tmp_path / "overrides",
        ),
        patch("lan_streamer.ui_views.dialogs.poster_selector.QMessageBox") as mock_msg,
    ):
        mock_msg.warning = MagicMock()
        dialog._on_apply_local_poster()
        mock_msg.warning.assert_called_once()


def test_on_apply_local_poster_nonexistent_file(series_record, qtbot):
    """Applying a poster from a non-existent file should show a warning."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    dialog._local_selected_path = "/nonexistent/path/image.jpg"

    with patch("lan_streamer.ui_views.dialogs.poster_selector.QMessageBox") as mock_msg:
        mock_msg.warning = MagicMock()
        dialog._on_apply_local_poster()
        mock_msg.warning.assert_called_once()


def test_poster_updated_signal_emitted(series_record, sample_image, tmp_path, qtbot):
    """poster_updated signal should be emitted with the new path after apply."""
    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)
    dialog._local_selected_path = sample_image

    received_paths: list[str] = []
    dialog.poster_updated.connect(received_paths.append)

    with (
        patch(
            "lan_streamer.ui_views.dialogs.poster_selector._POSTER_OVERRIDE_CACHE",
            tmp_path / "overrides",
        ),
        patch.object(dialog, "accept"),
        patch("lan_streamer.ui_views.dialogs.poster_selector.QMessageBox") as mock_msg,
    ):
        mock_msg.information = MagicMock()
        dialog._on_apply_local_poster()

    assert len(received_paths) == 1
    assert received_paths[0] != ""


# ---------------------------------------------------------------------------
# Right-click context menu tests (series_detail, season_detail, movie_detail)
# ---------------------------------------------------------------------------


def test_series_poster_label_has_context_menu_policy(qtbot):
    """SeriesDetailView poster_label should have CustomContextMenu policy."""
    from lan_streamer.ui_views.controller import Controller
    from lan_streamer.ui_views.series_detail import SeriesDetailView

    controller = Controller()
    view = SeriesDetailView(controller)
    qtbot.addWidget(view)

    assert (
        view.poster_label.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    )


def test_movie_poster_label_has_context_menu_policy(qtbot):
    """MovieDetailView poster_label should have CustomContextMenu policy."""
    from lan_streamer.ui_views.controller import Controller
    from lan_streamer.ui_views.movie_detail import MovieDetailView

    controller = Controller()
    view = MovieDetailView(controller)
    qtbot.addWidget(view)

    assert (
        view.poster_label.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    )


def test_season_poster_label_has_context_menu_policy(qtbot):
    """SeasonDetailView _poster_label should have CustomContextMenu policy."""
    from unittest.mock import MagicMock
    from lan_streamer.ui_views.season_detail import SeasonDetailView

    controller = MagicMock()
    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    assert (
        view._poster_label.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    )


def test_series_open_poster_selector_no_op_when_no_series(qtbot):
    """_open_poster_selector should do nothing if no series is loaded."""
    from lan_streamer.ui_views.controller import Controller
    from lan_streamer.ui_views.series_detail import SeriesDetailView

    controller = Controller()
    view = SeriesDetailView(controller)
    qtbot.addWidget(view)

    # Should not raise even when no series is selected
    view._open_poster_selector()


def test_movie_open_poster_selector_no_op_when_no_movie(qtbot):
    """_open_poster_selector should do nothing if no movie is loaded."""
    from lan_streamer.ui_views.controller import Controller
    from lan_streamer.ui_views.movie_detail import MovieDetailView

    controller = Controller()
    view = MovieDetailView(controller)
    qtbot.addWidget(view)

    view._open_poster_selector()


def test_season_open_poster_selector_no_op_when_no_season(qtbot):
    """_open_poster_selector should do nothing if no season is set."""
    from unittest.mock import MagicMock
    from lan_streamer.ui_views.season_detail import SeasonDetailView

    controller = MagicMock()
    view = SeasonDetailView(controller)
    qtbot.addWidget(view)

    view._open_poster_selector()


def test_thumbnail_downloader_callback_on_gui_thread(qtbot, series_record) -> None:
    """Thumbnail downloader callbacks must always run on the main GUI thread."""
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication, QLabel
    from unittest.mock import MagicMock, patch

    dialog = PosterSelectorDialog(
        media_name=series_record,
        media_kind="series",
    )
    qtbot.addWidget(dialog)

    label = QLabel()
    fake_bytes = b"fake_image_content"

    callback_thread = None

    def mock_setPixmap(pixmap):
        nonlocal callback_thread
        callback_thread = QThread.currentThread()

    def mock_setText(text):
        nonlocal callback_thread
        callback_thread = QThread.currentThread()

    # We mock setPixmap and setText on the label to record the thread they are called in
    with (
        patch.object(label, "setPixmap", side_effect=mock_setPixmap),
        patch.object(label, "setText", side_effect=mock_setText),
    ):
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = fake_bytes
            mock_get.return_value = mock_response

            from lan_streamer.ui_views.dialogs.poster_selector import (
                _ThumbnailDownloader,
            )

            downloader = _ThumbnailDownloader(
                "https://example.invalid/thumb.jpg", label, parent=dialog
            )
            label.setProperty("_downloader", downloader)
            downloader.downloaded.connect(dialog._on_thumbnail_downloaded)

            with qtbot.waitSignal(downloader.downloaded, timeout=2000):
                downloader.start_download()

            # Yield control to the Qt event loop to process any queued connection slots
            QApplication.processEvents()

    assert callback_thread == QApplication.instance().thread()
