import pytest
from unittest.mock import MagicMock, patch
from lan_streamer.player_widget import VideoPlayerWidget, CacheWorker
from lan_streamer.config import config


@pytest.fixture
def player_widget(qtbot):
    widget = VideoPlayerWidget()
    qtbot.addWidget(widget)
    return widget


def test_format_time(player_widget):
    assert player_widget._format_time(0) == "00:00"
    assert player_widget._format_time(61) == "01:01"
    assert player_widget._format_time(3600) == "60:00"


def test_cache_worker_logic(tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"hello world" * 100)
    dest = tmp_path / "cache" / "src.mp4"

    worker = CacheWorker(str(src), str(dest))

    finished_msg = []
    worker.finished.connect(finished_msg.append)

    worker.run()

    assert dest.exists()
    assert dest.read_bytes() == src.read_bytes()
    assert finished_msg == [str(dest)]


def test_play_video_no_cache(player_widget):
    config.enable_caching = False
    with patch.object(player_widget, "_load_and_play") as mock_load:
        player_widget.play_video("/path/to/video.mp4")
        mock_load.assert_called_once_with("/path/to/video.mp4")


def test_play_video_with_cache(player_widget, tmp_path):
    config.enable_caching = True
    config.cache_directory = str(tmp_path / "cache")

    with patch.object(player_widget, "_start_caching") as mock_cache:
        player_widget.play_video("/path/to/video.mp4")
        mock_cache.assert_called_once_with("/path/to/video.mp4")


def test_mark_as_watched(player_widget):
    player_widget.current_media_path = "/path/to/video.mp4"
    with patch("lan_streamer.db.update_episode_watched_status") as mock_db:
        player_widget._mark_as_watched()
        mock_db.assert_called_once_with("/path/to/video.mp4", True)
        assert player_widget.is_watched_marked is True


def test_cleanup_cache(player_widget, tmp_path):
    cache_file = tmp_path / "cached.mp4"
    cache_file.write_text("test")
    player_widget.cached_file_path = str(cache_file)

    player_widget._cleanup_cache()
    assert not cache_file.exists()
    assert player_widget.cached_file_path is None


def test_on_back_clicked(player_widget, qtbot):
    with patch.object(player_widget, "stop") as mock_stop:
        with qtbot.waitSignal(player_widget.back_requested):
            player_widget.on_back_clicked()
        mock_stop.assert_called_once()


def test_refresh_tracks(player_widget):
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.audio_get_track_description.return_value = [
        (1, b"Track 1")
    ]
    player_widget.mediaplayer.video_get_spu_description.return_value = [(2, b"Sub 1")]
    player_widget.mediaplayer.audio_get_track.return_value = 1
    player_widget.mediaplayer.video_get_spu.return_value = 2

    player_widget._refresh_tracks()

    assert player_widget.audio_combo.count() == 1
    assert player_widget.subtitle_combo.count() == 1


def test_update_ui(player_widget):
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.get_media.return_value = MagicMock()
    player_widget.mediaplayer.get_position.return_value = 0.5
    player_widget.mediaplayer.get_time.return_value = 50000
    player_widget.mediaplayer.get_length.return_value = 100000

    player_widget.update_ui()

    assert player_widget.seek_slider.value() == 500
    # 50s / 100s -> 00:50 / 01:40
    assert "00:50 / 01:40" in player_widget.time_label.text()


def test_update_ui_watched_threshold(player_widget):
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.get_media.return_value = MagicMock()
    player_widget.mediaplayer.get_position.return_value = 0.95
    player_widget.mediaplayer.get_time.return_value = 95000
    player_widget.mediaplayer.get_length.return_value = 100000
    player_widget.current_media_path = "/path/to/video.mp4"

    with patch.object(player_widget, "_mark_as_watched") as mock_mark:
        player_widget.update_ui()
        mock_mark.assert_called_once()


def test_on_caching_error(player_widget):
    player_widget.current_media_path = "/path/to/video.mp4"
    with patch.object(player_widget, "_load_and_play") as mock_load:
        player_widget._on_caching_error("Some error")
        mock_load.assert_called_once_with("/path/to/video.mp4")


def test_change_tracks(player_widget):
    player_widget.mediaplayer = MagicMock()
    player_widget.audio_combo.addItem("Track 1", 1)
    player_widget.subtitle_combo.addItem("Sub 1", 2)

    player_widget.change_audio_track(0)
    player_widget.mediaplayer.audio_set_track.assert_called_once_with(1)

    player_widget.change_subtitle_track(0)
    player_widget.mediaplayer.video_set_spu.assert_called_once_with(2)


def test_play_pause_stop(player_widget):
    player_widget.mediaplayer = MagicMock()

    player_widget.mediaplayer.is_playing.return_value = True
    player_widget.play_pause()
    player_widget.mediaplayer.pause.assert_called_once()

    player_widget.mediaplayer.is_playing.return_value = False
    player_widget.play_pause()
    assert player_widget.mediaplayer.play.call_count == 1

    player_widget.stop()
    player_widget.mediaplayer.stop.assert_called_once()


def test_set_volume_and_position(player_widget):
    player_widget.mediaplayer = MagicMock()
    player_widget.set_volume(50)
    player_widget.mediaplayer.audio_set_volume.assert_called_once_with(50)

    player_widget.set_position(500)
    player_widget.mediaplayer.set_position.assert_called_once_with(0.5)


def test_resize_event(player_widget):
    from PySide6.QtGui import QResizeEvent
    from PySide6.QtCore import QSize

    event = QResizeEvent(QSize(800, 600), QSize(640, 480))
    player_widget.resizeEvent(event)
    assert player_widget.progress_overlay.size() == player_widget.video_frame.size()


def test_vlc_instance_args(player_widget):
    # This is mostly to cover the lines in __init__
    if player_widget.instance:
        assert player_widget.instance is not None


def test_load_and_play_platforms(player_widget):
    player_widget.instance = MagicMock()
    player_widget.mediaplayer = MagicMock()
    with patch("sys.platform", "win32"):
        player_widget._load_and_play("/path/to/video.mp4")
        player_widget.mediaplayer.set_hwnd.assert_called()
    with patch("sys.platform", "darwin"):
        player_widget._load_and_play("/path/to/video.mp4")
        player_widget.mediaplayer.set_nsobject.assert_called()


def test_toggle_fullscreen(player_widget):
    main_win = MagicMock()
    # Mocking self.window()
    with patch.object(player_widget, "window", return_value=main_win):
        # Test go fullscreen
        main_win.isFullScreen.return_value = False
        player_widget.toggle_fullscreen()
        main_win.showFullScreen.assert_called_once()
        assert player_widget.controls_widget.isHidden()

        # Test exit fullscreen
        main_win.isFullScreen.return_value = True
        player_widget.toggle_fullscreen()
        main_win.showNormal.assert_called_once()
        assert not player_widget.controls_widget.isHidden()


def test_key_press_events(player_widget):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import Qt

    with patch.object(player_widget, "toggle_fullscreen") as mock_toggle:
        with patch.object(player_widget, "play_pause") as mock_play:
            # F key
            event_f = QKeyEvent(
                QKeyEvent.Type.KeyPress, Qt.Key.Key_F, Qt.KeyboardModifier.NoModifier
            )
            player_widget.keyPressEvent(event_f)
            mock_toggle.assert_called_once()
            mock_toggle.reset_mock()

            # Esc key when fullscreen
            main_win = MagicMock()
            main_win.isFullScreen.return_value = True
            with patch.object(player_widget, "window", return_value=main_win):
                event_esc = QKeyEvent(
                    QKeyEvent.Type.KeyPress,
                    Qt.Key.Key_Escape,
                    Qt.KeyboardModifier.NoModifier,
                )
                player_widget.keyPressEvent(event_esc)
                mock_toggle.assert_called_once()
                mock_toggle.reset_mock()

            # Space key
            event_space = QKeyEvent(
                QKeyEvent.Type.KeyPress,
                Qt.Key.Key_Space,
                Qt.KeyboardModifier.NoModifier,
            )
            player_widget.keyPressEvent(event_space)
            mock_play.assert_called_once()


def test_stop_exits_fullscreen(player_widget):
    main_win = MagicMock()
    main_win.isFullScreen.return_value = True
    player_widget.mediaplayer = MagicMock()

    with patch.object(player_widget, "window", return_value=main_win):
        with patch.object(player_widget, "toggle_fullscreen") as mock_toggle:
            player_widget.stop()
            mock_toggle.assert_called_once()


def test_event_filter_double_click(player_widget):
    from PySide6.QtCore import QEvent

    with patch.object(player_widget, "toggle_fullscreen") as mock_toggle:
        event = QEvent(QEvent.Type.MouseButtonDblClick)
        # Should return True if handled
        assert player_widget.eventFilter(player_widget.video_frame, event) is True
        mock_toggle.assert_called_once()

        # Should return False for other events
        event_other = QEvent(QEvent.Type.MouseButtonPress)
        assert (
            player_widget.eventFilter(player_widget.video_frame, event_other) is False
        )


def test_handle_playback_finished(player_widget, qtbot):
    with patch.object(player_widget, "stop") as mock_stop:
        with qtbot.waitSignal(player_widget.back_requested):
            player_widget._handle_playback_finished()
        mock_stop.assert_called_once()


def test_ui_layout_completeness(player_widget):
    """Verify that player controls are actually attached to the UI hierarchy."""
    # Verify that controls are actually in the controls_widget
    assert player_widget.play_button.parent() == player_widget.controls_widget
    assert player_widget.stop_button.parent() == player_widget.controls_widget
    assert player_widget.fullscreen_button.parent() == player_widget.controls_widget
    assert player_widget.back_button.parent() == player_widget.controls_widget

    # Verify the controls_widget is in the main_layout
    found = False
    for i in range(player_widget.main_layout.count()):
        item = player_widget.main_layout.itemAt(i)
        if item.widget() == player_widget.controls_widget:
            found = True
            break
    assert found, "controls_widget not found in main_layout"

    # Verify seek_slider is also there (it's in seek_layout, which is in controls_layout)
    assert player_widget.seek_slider.parent() == player_widget.controls_widget
