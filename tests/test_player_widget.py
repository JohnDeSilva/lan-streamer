import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import Qt

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
    assert player_widget.volume_slider.value() == 50
    assert player_widget.fs_volume_slider.value() == 50

    player_widget.set_position(500)
    player_widget.mediaplayer.set_position.assert_called_once_with(0.5)


def test_wakelock_integration(player_widget):
    player_widget.instance = MagicMock()
    player_widget.mediaplayer = MagicMock()
    player_widget.wakelock = MagicMock()

    # Test inhibit on play
    player_widget._load_and_play("/path/to/video.mp4")
    player_widget.wakelock.inhibit.assert_called_once()

    # Test uninhibit on stop
    player_widget.stop()
    player_widget.wakelock.uninhibit.assert_called_once()


def test_fullscreen_mouse_move(player_widget, qtbot):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QMouseEvent

    main_win = MagicMock()
    main_win.isFullScreen.return_value = True

    with patch.object(player_widget, "window", return_value=main_win):
        # Initial state: controls might be hidden
        player_widget.fullscreen_overlay.hide()

        # Simulate mouse move by calling eventFilter directly
        event = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPoint(100, 100),
            QPoint(100, 100),  # global pos
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        player_widget.eventFilter(player_widget.video_frame, event)

        assert not player_widget.fullscreen_overlay.isHidden()
        assert player_widget.hide_controls_timer.isActive()

        # Simulate timer timeout
        player_widget.mediaplayer = MagicMock()
        player_widget.mediaplayer.is_playing.return_value = True
        player_widget._hide_fullscreen_controls()

        assert player_widget.fullscreen_overlay.isHidden()


def test_toggle_stats(player_widget, qtbot):
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.video_get_size.return_value = (1920, 1080)
    player_widget.mediaplayer.get_fps.return_value = 23.976
    mock_media = MagicMock()
    player_widget.mediaplayer.get_media.return_value = mock_media

    # Initially hidden
    assert player_widget.stats_overlay.isHidden()

    # Toggle on
    player_widget.toggle_stats()
    assert not player_widget.stats_overlay.isHidden()
    mock_media.get_stats.assert_called()

    # Toggle off
    player_widget.toggle_stats()
    assert player_widget.stats_overlay.isHidden()


def test_skip_logic(player_widget):
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.get_time.return_value = 50000  # 50s

    # Skip forward 10s
    player_widget.skip_forward(10)
    player_widget.mediaplayer.set_time.assert_called_with(60000)

    # Skip backward 10s
    player_widget.skip_backward(10)
    player_widget.mediaplayer.set_time.assert_called_with(40000)


def test_toggle_fast_forward(player_widget):
    player_widget.mediaplayer = MagicMock()

    # 1.0 -> 1.5
    player_widget.mediaplayer.get_rate.return_value = 1.0
    player_widget.toggle_fast_forward()
    player_widget.mediaplayer.set_rate.assert_called_with(1.5)
    assert player_widget.rate_button.text() == "1.5x"

    # 1.5 -> 2.0
    player_widget.mediaplayer.get_rate.return_value = 1.5
    player_widget.toggle_fast_forward()
    player_widget.mediaplayer.set_rate.assert_called_with(2.0)
    assert player_widget.rate_button.text() == "2.0x"

    # 2.0 -> 1.0
    player_widget.mediaplayer.get_rate.return_value = 2.0
    player_widget.toggle_fast_forward()
    player_widget.mediaplayer.set_rate.assert_called_with(1.0)
    assert player_widget.rate_button.text() == "1.0x"


def test_mute_functionality(player_widget):
    player_widget.mediaplayer = MagicMock()
    player_widget.volume_slider.setValue(80)

    # Mute
    player_widget.toggle_mute()
    assert player_widget.is_muted is True
    player_widget.mediaplayer.audio_set_volume.assert_called_with(0)
    assert player_widget.mute_button.text() == "Unmute"
    assert player_widget.fs_mute_button.text() == "Unmute"

    # Unmute
    player_widget.toggle_mute()
    assert player_widget.is_muted is False
    player_widget.mediaplayer.audio_set_volume.assert_called_with(80)
    assert player_widget.mute_button.text() == "Mute"


def test_volume_boost(player_widget):
    player_widget.mediaplayer = MagicMock()
    player_widget.set_volume(150)
    player_widget.mediaplayer.audio_set_volume.assert_called_with(150)
    assert player_widget.volume_slider.value() == 150
    assert player_widget.fs_volume_slider.value() == 150


def test_volume_osd(player_widget):
    player_widget.mediaplayer = MagicMock()
    player_widget._show_volume_osd(120)
    assert not player_widget.osd_label.isHidden()
    assert "120%" in player_widget.osd_label.text()

    player_widget._show_volume_osd(0, muted=True)
    assert "Muted" in player_widget.osd_label.text()


def test_resize_event(player_widget):
    from PySide6.QtGui import QResizeEvent
    from PySide6.QtCore import QSize

    event = QResizeEvent(QSize(800, 600), QSize(640, 480))
    player_widget.resizeEvent(event)
    assert player_widget.progress_overlay.size() == player_widget.video_frame.size()


def test_vlc_instance_args(qtbot):
    with patch("vlc.Instance") as mock_vlc:
        config.enable_hw_accel = True
        config.vlc_extra_args = ["--test-arg"]

        VideoPlayerWidget()

        args = mock_vlc.call_args[0][0]
        assert "--avcodec-hw=auto" in args
        assert "--test-arg" in args
        assert "--deinterlace=1" in args
        assert "--file-caching=3000" in args


def test_vlc_instance_args_no_hw(qtbot):
    with patch("vlc.Instance") as mock_vlc:
        config.enable_hw_accel = False
        config.vlc_extra_args = []

        VideoPlayerWidget()

        args = mock_vlc.call_args[0][0]
        assert "--avcodec-hw=none" in args
        assert "--avcodec-hw=auto" not in args


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

    # Volume shortcuts
    player_widget.mediaplayer = MagicMock()
    player_widget.volume_slider.setValue(100)

    # Up arrow
    event_up = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier
    )
    player_widget.keyPressEvent(event_up)
    assert player_widget.volume_slider.value() == 105

    # Down arrow
    event_down = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier
    )
    player_widget.keyPressEvent(event_down)
    assert player_widget.volume_slider.value() == 100

    # M key
    event_m = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_M, Qt.KeyboardModifier.NoModifier
    )
    player_widget.keyPressEvent(event_m)
    assert player_widget.is_muted is True


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

    # Verify volume controls
    assert player_widget.volume_slider.parent() == player_widget.controls_widget
    assert player_widget.mute_button.parent() == player_widget.controls_widget

    # Verify fullscreen volume controls
    assert player_widget.fs_volume_slider.parent() == player_widget.fullscreen_overlay
    assert player_widget.fs_mute_button.parent() == player_widget.fullscreen_overlay
