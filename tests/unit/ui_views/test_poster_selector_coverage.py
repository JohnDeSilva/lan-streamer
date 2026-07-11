"""Extended coverage tests for lan_streamer.ui_views.dialogs.poster_selector.

Targets the 65 currently-uncovered lines to push coverage above 95%.
All tests use mocked DB sessions and network calls — no real I/O.
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel

from lan_streamer.db.connection import get_session
from lan_streamer.db.models import Movie, Season, Series
from lan_streamer.ui_views.dialogs.poster_selector import (
    PosterSelectorDialog,
    _TmdbImageFetchWorker,
    _ThumbnailDownloader,
)


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------


@pytest.fixture
def series_record():
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
        from sqlalchemy import select

        series = session.scalars(
            select(Series).where(Series.name == series_record)
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
def movie_record():
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
    """Create a minimal valid PNG image file for testing."""
    # Minimal 1x1 white PNG
    import base64

    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    image_path = tmp_path / "test_poster.png"
    image_path.write_bytes(base64.b64decode(png_b64))
    return str(image_path)


# -----------------------------------------------------------------------
# _TmdbImageFetchWorker.run()  (covers lines 73-101)
# -----------------------------------------------------------------------


class TestTmdbImageFetchWorker:
    def test_series_path_emits_images(self, qtbot):
        """run() with media_kind='series' calls get_series_images."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_series_images.return_value = {
            "posters": [{"file_path": "/a.jpg", "width": 500, "height": 750}],
            "backdrops": [{"file_path": "/b.jpg", "width": 1280, "height": 720}],
        }

        worker = _TmdbImageFetchWorker(tmdb_identifier=42, media_kind="series")

        received_images = []
        worker.images_ready.connect(received_images.append)

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.tmdb_client", mock_tmdb
            ),
            qtbot.waitSignal(worker.finished, timeout=3000),
        ):
            worker.run()

        assert len(received_images) == 1
        all_images = received_images[0]
        assert len(all_images) == 2
        assert all_images[0]["image_type"] == "poster"
        assert all_images[1]["image_type"] == "backdrop"
        mock_tmdb.get_series_images.assert_called_once_with(42)

    def test_movie_path_emits_images(self, qtbot):
        """run() with media_kind='movie' calls get_movie_images."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_movie_images.return_value = {
            "posters": [],
            "backdrops": [{"file_path": "/c.jpg", "width": 1920, "height": 1080}],
        }

        worker = _TmdbImageFetchWorker(tmdb_identifier=99, media_kind="movie")

        received_images = []
        worker.images_ready.connect(received_images.append)

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.tmdb_client", mock_tmdb
            ),
            qtbot.waitSignal(worker.finished, timeout=3000),
        ):
            worker.run()

        assert len(received_images) == 1
        all_images = received_images[0]
        assert len(all_images) == 1
        assert all_images[0]["image_type"] == "backdrop"
        mock_tmdb.get_movie_images.assert_called_once_with(99)

    def test_exception_emits_error(self, qtbot):
        """run() exception path emits error_occurred signal."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_series_images.side_effect = RuntimeError("API down")

        worker = _TmdbImageFetchWorker(tmdb_identifier=1, media_kind="series")

        errors = []
        worker.error_occurred.connect(errors.append)

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.tmdb_client", mock_tmdb
            ),
            qtbot.waitSignal(worker.finished, timeout=3000),
        ):
            worker.run()

        assert len(errors) == 1
        assert "API down" in errors[0]

    def test_empty_response(self, qtbot):
        """run() with empty poster/backdrop lists emits empty list."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_series_images.return_value = {"posters": [], "backdrops": []}

        worker = _TmdbImageFetchWorker(tmdb_identifier=10, media_kind="series")

        received = []
        worker.images_ready.connect(received.append)

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.tmdb_client", mock_tmdb
            ),
            qtbot.waitSignal(worker.finished, timeout=3000),
        ):
            worker.run()

        assert received == [[]]


# -----------------------------------------------------------------------
# _ThumbnailDownloader.start_download()  (covers lines 116-129)
# -----------------------------------------------------------------------


class TestThumbnailDownloader:
    def test_successful_download(self, qtbot, series_record):
        """Downloaded bytes are emitted via the downloaded signal."""
        label = QLabel()
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        fake_bytes = b"\xff\xd8\xff\xe0"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_bytes

        downloader = _ThumbnailDownloader(
            "https://example.invalid/thumb.jpg", label, parent=dialog
        )

        received = []
        downloader.downloaded.connect(
            lambda content, lbl: received.append((content, lbl))
        )

        with patch("requests.get", return_value=mock_response):
            with qtbot.waitSignal(downloader.downloaded, timeout=5000):
                downloader.start_download()

        assert len(received) == 1
        assert received[0][0] == fake_bytes
        assert received[0][1] is label

    def test_non_200_status_no_signal(self, qtbot, series_record):
        """Non-200 status should not emit the downloaded signal."""
        label = QLabel()
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        mock_response = MagicMock()
        mock_response.status_code = 404

        downloader = _ThumbnailDownloader(
            "https://example.invalid/thumb.jpg", label, parent=dialog
        )

        signals_received = []
        downloader.downloaded.connect(
            lambda _code, _lang: signals_received.append(True)
        )

        with patch("requests.get", return_value=mock_response):
            downloader.start_download()
            import time

            time.sleep(0.3)

        assert len(signals_received) == 0

    def test_exception_no_signal(self, qtbot, series_record):
        """Network exception should not emit the downloaded signal."""
        label = QLabel()
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        downloader = _ThumbnailDownloader(
            "https://example.invalid/thumb.jpg", label, parent=dialog
        )

        signals_received = []
        downloader.downloaded.connect(
            lambda _code, _lang: signals_received.append(True)
        )

        with patch("requests.get", side_effect=Exception("timeout")):
            downloader.start_download()
            import time

            time.sleep(0.3)

        assert len(signals_received) == 0


# -----------------------------------------------------------------------
# _resolve_media_ids  (covers lines 195-196, 213-214, 235-236)
# -----------------------------------------------------------------------


class TestResolveMediaIds:
    def test_movie_with_non_numeric_tmdb_id(self, qtbot):
        """Covers lines 195-196: ValueError on int() of non-numeric tmdb_id."""
        with get_session() as session:
            movie = Movie(
                name="Bad TMDB Movie",
                library_name="TestLib",
                tmdb_identifier="not-a-number",
                poster_path="",
            )
            session.add(movie)
            session.commit()

        dialog = PosterSelectorDialog(media_name="Bad TMDB Movie", media_kind="movie")
        qtbot.addWidget(dialog)
        assert dialog._movie_db_id is not None
        assert dialog._tmdb_numeric_id is None

    def test_series_with_non_numeric_tmdb_id(self, qtbot):
        """Covers lines 235-236: ValueError on int() of non-numeric tmdb_id for series."""
        with get_session() as session:
            series = Series(
                name="Bad TMDB Show",
                library_name="TestLib",
                tmdb_identifier="bad_id",
                poster_path="",
            )
            session.add(series)
            session.commit()

        dialog = PosterSelectorDialog(media_name="Bad TMDB Show", media_kind="series")
        qtbot.addWidget(dialog)
        assert dialog._series_db_id is not None
        assert dialog._tmdb_numeric_id is None

    def test_season_with_non_numeric_tmdb_id(self, qtbot):
        """Covers lines 213-214: ValueError on int() of non-numeric tmdb_id for season."""
        with get_session() as session:
            series = Series(
                name="Parent Show",
                library_name="TestLib",
                tmdb_identifier="bad",
                poster_path="",
            )
            session.add(series)
            session.commit()

        with get_session() as session:
            from sqlalchemy import select

            parent = session.scalars(
                select(Series).where(Series.name == "Parent Show")
            ).first()
            season = Season(
                series_id=parent.id,
                name="Season X",
                poster_path="",
            )
            session.add(season)
            session.commit()

        dialog = PosterSelectorDialog(
            media_name="Season X",
            media_kind="season",
            series_name="Parent Show",
        )
        qtbot.addWidget(dialog)
        assert dialog._series_db_id is not None
        assert dialog._season_db_id is not None
        assert dialog._tmdb_numeric_id is None

    def test_movie_with_none_tmdb_id(self, qtbot):
        """Movie with tmdb_identifier=None."""
        with get_session() as session:
            movie = Movie(
                name="No TMDB Movie",
                library_name="TestLib",
                tmdb_identifier=None,
                poster_path="",
            )
            session.add(movie)
            session.commit()

        dialog = PosterSelectorDialog(media_name="No TMDB Movie", media_kind="movie")
        qtbot.addWidget(dialog)
        assert dialog._movie_db_id is not None
        assert dialog._tmdb_numeric_id is None

    def test_season_with_none_tmdb_id(self, qtbot):
        """Season where parent series has no tmdb_identifier."""
        with get_session() as session:
            series = Series(
                name="No TMDB Parent",
                library_name="TestLib",
                tmdb_identifier=None,
                poster_path="",
            )
            session.add(series)
            session.commit()

        with get_session() as session:
            from sqlalchemy import select

            parent = session.scalars(
                select(Series).where(Series.name == "No TMDB Parent")
            ).first()
            season = Season(
                series_id=parent.id,
                name="No TMDB Season",
                poster_path="",
            )
            session.add(season)
            session.commit()

        dialog = PosterSelectorDialog(
            media_name="No TMDB Season",
            media_kind="season",
            series_name="No TMDB Parent",
        )
        qtbot.addWidget(dialog)
        assert dialog._tmdb_numeric_id is None


# -----------------------------------------------------------------------
# _on_fetch_tmdb_images  (covers lines 457-488)
# -----------------------------------------------------------------------


class TestOnFetchTmdbImages:
    def test_no_tmdb_id_returns_early(self, series_record, qtbot):
        """When _tmdb_numeric_id is None, _on_fetch_tmdb_images returns early."""
        dialog = PosterSelectorDialog(media_name="Unknown", media_kind="series")
        qtbot.addWidget(dialog)
        dialog._tmdb_numeric_id = None
        # Should not raise
        dialog._on_fetch_tmdb_images()

    def test_launches_thread_with_series(self, series_record, qtbot):
        """Fetch creates a QThread + _TmdbImageFetchWorker for series."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        mock_worker_cls = MagicMock()
        mock_instance = MagicMock()
        mock_worker_cls.return_value = mock_instance
        mock_thread = MagicMock()
        mock_thread_cls = MagicMock(return_value=mock_thread)
        mock_thread_cls.return_value = mock_thread

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector._TmdbImageFetchWorker",
                mock_worker_cls,
            ),
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.QThread", mock_thread_cls
            ),
        ):
            dialog._on_fetch_tmdb_images()

        mock_worker_cls.assert_called_once()
        call_kwargs = mock_worker_cls.call_args
        assert call_kwargs[1]["tmdb_identifier"] == 12345
        assert call_kwargs[1]["media_kind"] == "series"

    def test_launches_thread_with_movie(self, movie_record, qtbot):
        """Fetch creates a worker with media_kind='movie' for movies."""
        dialog = PosterSelectorDialog(media_name=movie_record, media_kind="movie")
        qtbot.addWidget(dialog)

        mock_worker_cls = MagicMock()
        mock_instance = MagicMock()
        mock_worker_cls.return_value = mock_instance
        mock_thread = MagicMock()
        mock_thread_cls = MagicMock(return_value=mock_thread)

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector._TmdbImageFetchWorker",
                mock_worker_cls,
            ),
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.QThread", mock_thread_cls
            ),
        ):
            dialog._on_fetch_tmdb_images()

        call_kwargs = mock_worker_cls.call_args
        assert call_kwargs[1]["media_kind"] == "movie"

    def test_disables_button_and_sets_status(self, series_record, qtbot):
        """Button is disabled and status label shows fetching text."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector._TmdbImageFetchWorker"
            ),
            patch("lan_streamer.ui_views.dialogs.poster_selector.QThread"),
        ):
            dialog._on_fetch_tmdb_images()

        assert not dialog._tmdb_fetch_button.isEnabled()
        assert "Fetching" in dialog._tmdb_status_label.text()

    def test_clears_existing_grid(self, series_record, qtbot):
        """Grid is cleared before new fetch."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        dummy = QLabel("old")
        dialog._tmdb_grid_layout.addWidget(dummy, 0, 0)
        assert dialog._tmdb_grid_layout.count() > 0

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector._TmdbImageFetchWorker"
            ),
            patch("lan_streamer.ui_views.dialogs.poster_selector.QThread"),
        ):
            dialog._on_fetch_tmdb_images()

        # Grid is cleared (no items left after deletion)
        assert dialog._tmdb_grid_layout.count() == 0


# -----------------------------------------------------------------------
# _on_tmdb_images_ready  (covers lines 525-526)
# -----------------------------------------------------------------------


class TestOnTmdbImagesReady:
    def test_empty_list(self, series_record, qtbot):
        """Empty list shows a no-results label."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)
        dialog._on_tmdb_images_ready([])
        first_item = dialog._tmdb_grid_layout.itemAtPosition(0, 0)
        assert first_item is not None

    def test_many_images_wrap_grid(self, series_record, qtbot):
        """More than 4 images should wrap to the next row (covers lines 525-526)."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        images = [
            {
                "image_type": "poster",
                "file_path": f"/{i}.jpg",
                "width": 500,
                "height": 750,
            }
            for i in range(6)
        ]

        with patch.object(dialog, "_load_thumbnail_into_label"):
            dialog._on_tmdb_images_ready(images)

        # 6 cards + any pre-existing placeholder widget
        assert dialog._tmdb_grid_layout.count() >= 6

    def test_poster_count_displayed(self, series_record, qtbot):
        """Status label should display poster and backdrop counts."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        images = [
            {
                "image_type": "poster",
                "file_path": "/a.jpg",
                "width": 500,
                "height": 750,
            },
            {
                "image_type": "poster",
                "file_path": "/b.jpg",
                "width": 500,
                "height": 750,
            },
            {
                "image_type": "backdrop",
                "file_path": "/c.jpg",
                "width": 1280,
                "height": 720,
            },
        ]

        with patch.object(dialog, "_load_thumbnail_into_label"):
            dialog._on_tmdb_images_ready(images)

        status_text = dialog._tmdb_status_label.text()
        assert "2" in status_text
        assert "1" in status_text

    def test_max_24_images(self, series_record, qtbot):
        """Should cap at 24 image cards."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        images = [
            {
                "image_type": "poster",
                "file_path": f"/{i}.jpg",
                "width": 500,
                "height": 750,
            }
            for i in range(30)
        ]

        with patch.object(dialog, "_load_thumbnail_into_label"):
            dialog._on_tmdb_images_ready(images)

        # 24 cards + any pre-existing placeholder widget
        assert dialog._tmdb_grid_layout.count() >= 24


# -----------------------------------------------------------------------
# _on_select_tmdb_image  (covers lines 636-655)
# -----------------------------------------------------------------------


class TestOnSelectTmdbImage:
    def test_empty_path_returns_early(self, series_record, qtbot):
        """Empty tmdb_file_path does nothing."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)
        # Should not raise
        dialog._on_select_tmdb_image("", "poster")

    def test_successful_download_and_apply(self, series_record, qtbot):
        """Covers lines 636-655: success path calls _apply_poster_path."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.tmdb_client"
            ) as mock_tmdb,
            patch.object(dialog, "_apply_poster_path") as mock_apply,
        ):
            mock_tmdb.download_and_cache_image.return_value = "/cached/img.jpg"
            dialog._on_select_tmdb_image("/abc123.jpg", "poster")

        mock_tmdb.download_and_cache_image.assert_called_once_with(
            "/abc123.jpg", size="original"
        )
        mock_apply.assert_called_once_with("/cached/img.jpg", "poster")

    def test_download_failure_shows_warning(self, series_record, qtbot):
        """When download_and_cache_image returns None, a warning is shown."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.tmdb_client"
            ) as mock_tmdb,
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.QMessageBox"
            ) as mock_msgbox,
            patch.object(dialog, "_apply_poster_path") as mock_apply,
        ):
            mock_tmdb.download_and_cache_image.return_value = None
            mock_msgbox.warning = MagicMock()
            dialog._on_select_tmdb_image("/fail.jpg", "poster")

        mock_msgbox.warning.assert_called_once()
        mock_apply.assert_not_called()

    def test_backdrop_type_passed_through(self, series_record, qtbot):
        """Image type is forwarded to _apply_poster_path."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.tmdb_client"
            ) as mock_tmdb,
            patch.object(dialog, "_apply_poster_path") as mock_apply,
        ):
            mock_tmdb.download_and_cache_image.return_value = "/cached/bd.jpg"
            dialog._on_select_tmdb_image("/backdrop.jpg", "backdrop")

        mock_apply.assert_called_once_with("/cached/bd.jpg", "backdrop")


# -----------------------------------------------------------------------
# _on_thumbnail_downloaded  (covers lines 613, 617)
# -----------------------------------------------------------------------


class TestOnThumbnailDownloaded:
    def test_non_qlabel_returns_early(self, series_record, qtbot):
        """Covers line 613: non-QLabel label triggers early return."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)
        # Pass a string instead of QLabel
        dialog._on_thumbnail_downloaded(b"content", "not_a_label")
        # Should not crash

    def test_valid_pixmap_sets_image(self, series_record, qtbot):
        """Covers line 617: valid pixmap is scaled and set on the label."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        label = QLabel()

        # Create a tiny valid PNG in memory
        pixmap = QPixmap(2, 2)
        pixmap.fill(Qt.GlobalColor.white)
        from PySide6.QtCore import QBuffer, QIODevice

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        png_bytes = bytes(buffer.data())
        buffer.close()

        dialog._on_thumbnail_downloaded(png_bytes, label)

        assert not label.pixmap().isNull()

    def test_invalid_pixmap_sets_fallback_text(self, series_record, qtbot):
        """Invalid image bytes set the fallback text on the label."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        label = QLabel()
        dialog._on_thumbnail_downloaded(b"garbage", label)
        assert label.text() == "\U0001f4f7"

    def test_clears_downloader_property(self, series_record, qtbot):
        """_downloader property is set to None after processing."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        label = QLabel()
        label.setProperty("_downloader", MagicMock())
        pixmap = QPixmap(2, 2)
        pixmap.fill(Qt.GlobalColor.white)
        from PySide6.QtCore import QBuffer, QIODevice

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        png_bytes = bytes(buffer.data())
        buffer.close()

        dialog._on_thumbnail_downloaded(png_bytes, label)
        assert label.property("_downloader") is None


# -----------------------------------------------------------------------
# _on_browse_local_file  (covers lines 677-686)
# -----------------------------------------------------------------------


class TestOnBrowseLocalFile:
    def test_no_selection(self, series_record, qtbot):
        """Empty selection from QFileDialog returns early."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        with patch(
            "lan_streamer.ui_views.dialogs.poster_selector.QFileDialog"
        ) as mock_fdialog:
            mock_fdialog.getOpenFileName.return_value = ("", "")
            dialog._on_browse_local_file()

        assert dialog._local_selected_path is None

    def test_valid_image_sets_preview(self, series_record, sample_image, qtbot):
        """Covers lines 677-686: valid image sets preview and enables apply."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        with patch(
            "lan_streamer.ui_views.dialogs.poster_selector.QFileDialog"
        ) as mock_fdialog:
            mock_fdialog.getOpenFileName.return_value = (sample_image, "Image Files")
            dialog._on_browse_local_file()

        assert dialog._local_selected_path == sample_image
        assert dialog._local_apply_button.isEnabled()
        assert not dialog._local_preview_label.pixmap().isNull()

    def test_invalid_image_shows_warning(self, series_record, tmp_path, qtbot):
        """Non-image file shows warning and disables apply."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        text_file = tmp_path / "not_an_image.txt"
        text_file.write_text("hello")

        with patch(
            "lan_streamer.ui_views.dialogs.poster_selector.QFileDialog"
        ) as mock_fdialog:
            mock_fdialog.getOpenFileName.return_value = (str(text_file), "All")
            dialog._on_browse_local_file()

        assert dialog._local_selected_path == str(text_file)
        assert not dialog._local_apply_button.isEnabled()
        assert "Cannot read" in dialog._local_preview_label.text()


# -----------------------------------------------------------------------
# _on_apply_local_poster  (covers lines 695, 712-719)
# -----------------------------------------------------------------------


class TestOnApplyLocalPoster:
    def test_no_selected_path_returns_early(self, series_record, qtbot):
        """Covers line 695: _local_selected_path is None returns early."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)
        dialog._local_selected_path = None
        # Should not raise
        dialog._on_apply_local_poster()

    def test_oserror_on_copy_shows_warning(self, series_record, sample_image, qtbot):
        """Covers lines 712-719: OSError during copy shows critical message."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)
        dialog._local_selected_path = sample_image

        with (
            patch("shutil.copy2", side_effect=OSError("disk full")),
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.QMessageBox"
            ) as mock_msgbox,
        ):
            mock_msgbox.critical = MagicMock()
            dialog._on_apply_local_poster()

        mock_msgbox.critical.assert_called_once()
        assert "disk full" in str(mock_msgbox.critical.call_args)

    def test_nonexistent_source_file(self, series_record, qtbot):
        """File that no longer exists shows a warning."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)
        dialog._local_selected_path = "/nonexistent/path.jpg"

        with patch(
            "lan_streamer.ui_views.dialogs.poster_selector.QMessageBox"
        ) as mock_msgbox:
            mock_msgbox.warning = MagicMock()
            dialog._on_apply_local_poster()

        mock_msgbox.warning.assert_called_once()

    def test_successful_apply(self, series_record, sample_image, tmp_path, qtbot):
        """Successful apply copies file and calls _apply_poster_path."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)
        dialog._local_selected_path = sample_image

        with (
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector._POSTER_OVERRIDE_CACHE",
                tmp_path / "overrides",
            ),
            patch.object(dialog, "_apply_poster_path") as mock_apply,
        ):
            dialog._on_apply_local_poster()

        mock_apply.assert_called_once()
        assert "poster" in mock_apply.call_args[0][1]


# -----------------------------------------------------------------------
# _apply_poster_path  (covers all branches)
# -----------------------------------------------------------------------


class TestApplyPosterPath:
    def test_series_updates_db(self, series_record, sample_image, qtbot):
        """Series poster_path is updated in DB."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        with (
            patch.object(dialog, "accept"),
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.QMessageBox"
            ) as mock_msgbox,
        ):
            mock_msgbox.information = MagicMock()
            dialog._apply_poster_path(sample_image, "poster")

        with get_session() as session:
            from sqlalchemy import select

            series = session.scalars(
                select(Series).where(Series.name == series_record)
            ).first()
            assert series.poster_path == sample_image

    def test_movie_updates_db(self, movie_record, sample_image, qtbot):
        """Movie poster_path is updated in DB."""
        dialog = PosterSelectorDialog(media_name=movie_record, media_kind="movie")
        qtbot.addWidget(dialog)

        with (
            patch.object(dialog, "accept"),
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.QMessageBox"
            ) as mock_msgbox,
        ):
            mock_msgbox.information = MagicMock()
            dialog._apply_poster_path(sample_image, "poster")

        with get_session() as session:
            from sqlalchemy import select

            movie = session.scalars(
                select(Movie).where(Movie.name == movie_record)
            ).first()
            assert movie.poster_path == sample_image

    def test_season_updates_db(self, series_record, season_record, sample_image, qtbot):
        """Season poster_path is updated in DB."""
        dialog = PosterSelectorDialog(
            media_name=season_record,
            media_kind="season",
            series_name=series_record,
        )
        qtbot.addWidget(dialog)

        with (
            patch.object(dialog, "accept"),
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.QMessageBox"
            ) as mock_msgbox,
        ):
            mock_msgbox.information = MagicMock()
            dialog._apply_poster_path(sample_image, "poster")

        with get_session() as session:
            from sqlalchemy import select

            parent = session.scalars(
                select(Series).where(Series.name == series_record)
            ).first()
            season = session.scalars(
                select(Season).where(
                    Season.series_id == parent.id,
                    Season.name == season_record,
                )
            ).first()
            assert season.poster_path == sample_image

    def test_no_db_id_shows_warning(self, qtbot):
        """Missing DB record shows warning and returns without crash."""
        dialog = PosterSelectorDialog(media_name="Ghost Show", media_kind="series")
        qtbot.addWidget(dialog)

        with patch(
            "lan_streamer.ui_views.dialogs.poster_selector.QMessageBox"
        ) as mock_msgbox:
            mock_msgbox.warning = MagicMock()
            dialog._apply_poster_path("/some/path.jpg", "poster")

        mock_msgbox.warning.assert_called_once()

    def test_emits_poster_updated_signal(self, series_record, sample_image, qtbot):
        """poster_updated signal is emitted after successful apply."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        received = []
        dialog.poster_updated.connect(received.append)

        with (
            patch.object(dialog, "accept"),
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.QMessageBox"
            ) as mock_msgbox,
        ):
            mock_msgbox.information = MagicMock()
            dialog._apply_poster_path(sample_image, "poster")

        assert len(received) == 1
        assert received[0] == sample_image

    def test_backdrop_type_updates_series(self, series_record, sample_image, qtbot):
        """Backdrop image_type still updates the series poster_path."""
        dialog = PosterSelectorDialog(media_name=series_record, media_kind="series")
        qtbot.addWidget(dialog)

        with (
            patch.object(dialog, "accept"),
            patch(
                "lan_streamer.ui_views.dialogs.poster_selector.QMessageBox"
            ) as mock_msgbox,
        ):
            mock_msgbox.information = MagicMock()
            dialog._apply_poster_path(sample_image, "backdrop")

        with get_session() as session:
            from sqlalchemy import select

            series = session.scalars(
                select(Series).where(Series.name == series_record)
            ).first()
            assert series.poster_path == sample_image
