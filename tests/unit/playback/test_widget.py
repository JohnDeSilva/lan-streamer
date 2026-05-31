import pytest
from unittest.mock import MagicMock, patch
import os
import time
from PySide6.QtCore import Qt
from typing import Any

from lan_streamer.playback import VideoPlayerWidget, CacheWorker
from lan_streamer.system.config import config


@pytest.fixture
def player_widget(qtbot) -> None:
    widget = VideoPlayerWidget()
    qtbot.addWidget(widget)
    return widget


def test_format_time(player_widget) -> None:
    assert player_widget._format_time(0) == "00:00"
    assert player_widget._format_time(61) == "01:01"
    assert player_widget._format_time(3600) == "01:00:00"


def test_cache_worker_logic(tmp_path) -> None:
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


def test_play_video_no_cache(player_widget) -> None:
    config.enable_caching = False
    with patch.object(player_widget, "_load_and_play") as mock_load:
        player_widget.play_video("/path/to/video.mp4")
        mock_load.assert_called_once_with("/path/to/video.mp4")


def test_play_video_with_cache(player_widget, tmp_path) -> None:
    config.enable_caching = True
    config.cache_directory = str(tmp_path / "cache")

    with patch.object(player_widget, "_start_caching") as mock_cache:
        player_widget.play_video("/path/to/video.mp4")
        mock_cache.assert_called_once_with("/path/to/video.mp4")


def test_mark_as_watched(player_widget) -> None:
    player_widget.current_media_path = "/path/to/video.mp4"
    with patch("lan_streamer.db.update_episode_watched_status") as mock_db:
        player_widget._mark_as_watched()
        mock_db.assert_called_once_with("/path/to/video.mp4", True)
        assert player_widget.is_watched_marked is True


def test_cleanup_cache_older_than_24h(player_widget, tmp_path) -> None:
    cache_directory = tmp_path / "cache"
    cache_directory.mkdir()
    config.cache_directory = str(cache_directory)
    config.max_cache_size_gb = 15.0

    old_file = cache_directory / "old.mp4"
    old_file.write_text("old content")
    twenty_five_hours_ago = time.time() - (25 * 3600)
    os.utime(old_file, (twenty_five_hours_ago, twenty_five_hours_ago))

    new_file = cache_directory / "new.mp4"
    new_file.write_text("new content")

    player_widget.cached_file_path = str(old_file)
    player_widget._cleanup_cache()

    assert not old_file.exists()
    assert new_file.exists()
    assert player_widget.cached_file_path is None


def test_cleanup_cache_size_limit(player_widget, tmp_path) -> None:
    cache_directory = tmp_path / "cache"
    cache_directory.mkdir()
    config.cache_directory = str(cache_directory)
    config.max_cache_size_gb = 1000 / (1024 * 1024 * 1024)

    file_one = cache_directory / "file1.mp4"
    file_one.write_bytes(b"a" * 600)
    time_one = time.time() - 3600
    os.utime(file_one, (time_one, time_one))

    file_two = cache_directory / "file2.mp4"
    file_two.write_bytes(b"b" * 600)
    time_two = time.time() - 1800
    os.utime(file_two, (time_two, time_two))

    file_three = cache_directory / "file3.mp4"
    file_three.write_bytes(b"c" * 200)

    player_widget._cleanup_cache()

    assert not file_one.exists()
    assert file_two.exists()
    assert file_three.exists()


def test_play_video_already_cached(player_widget, tmp_path) -> None:
    config.enable_caching = True
    cache_directory = tmp_path / "cache"
    cache_directory.mkdir()
    config.cache_directory = str(cache_directory)

    src_file = tmp_path / "video.mp4"
    src_file.write_text("content")

    dest_file = cache_directory / "video.mp4"
    dest_file.write_text("content")

    with patch.object(player_widget, "_load_and_play") as mock_load:
        with patch("lan_streamer.playback.cache.CacheWorker") as mock_worker:
            player_widget.play_video(str(src_file))
            mock_worker.assert_not_called()
            mock_load.assert_called_once_with(str(dest_file))


def test_on_back_clicked(player_widget, qtbot) -> None:
    with patch.object(player_widget, "stop") as mock_stop:
        with qtbot.waitSignal(player_widget.back_requested):
            player_widget.on_back_clicked()
        mock_stop.assert_called_once()


def test_refresh_tracks(player_widget) -> None:
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


def test_update_ui(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.get_media.return_value = MagicMock()
    player_widget.mediaplayer.get_position.return_value = 0.5
    player_widget.mediaplayer.get_time.return_value = 50000
    player_widget.mediaplayer.get_length.return_value = 100000

    player_widget.update_ui()

    assert player_widget.seek_slider.value() == 500
    # 50s / 100s -> 00:50 / 01:40
    assert "00:50 / 01:40" in player_widget.time_label.text()


def test_stop_marks_watched_beyond_threshold(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.get_media.return_value = MagicMock()
    player_widget.mediaplayer.get_position.return_value = 0.95
    player_widget.mediaplayer.get_time.return_value = 95000
    player_widget.mediaplayer.get_length.return_value = 100000
    player_widget.current_media_path = "/path/to/video.mp4"
    config.watched_threshold = 0.95

    with patch.object(player_widget, "_mark_as_watched") as mock_mark:
        player_widget.stop()
        mock_mark.assert_called_once()


def test_on_caching_error(player_widget) -> None:
    player_widget.current_media_path = "/path/to/video.mp4"
    with patch.object(player_widget, "_load_and_play") as mock_load:
        player_widget._on_caching_error("Some error")
        mock_load.assert_called_once_with("/path/to/video.mp4")


def test_change_tracks(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.audio_combo.addItem("Track 1", 1)
    player_widget.subtitle_combo.addItem("Sub 1", 2)

    player_widget.change_audio_track(0)
    player_widget.mediaplayer.audio_set_track.assert_called_once_with(1)

    player_widget.change_subtitle_track(0)
    player_widget.mediaplayer.video_set_spu.assert_called_once_with(2)


def test_play_pause_stop(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()

    player_widget.mediaplayer.is_playing.return_value = True
    player_widget.play_pause()
    player_widget.mediaplayer.pause.assert_called_once()

    player_widget.mediaplayer.is_playing.return_value = False
    player_widget.play_pause()
    assert player_widget.mediaplayer.play.call_count == 1

    player_widget.stop()
    player_widget.mediaplayer.stop.assert_called_once()


def test_set_volume_and_position(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.set_volume(50)
    player_widget.mediaplayer.audio_set_volume.assert_called_once_with(50)
    assert player_widget.volume_slider.value() == 50
    assert player_widget.fs_volume_slider.value() == 50

    player_widget.set_position(500)
    player_widget.mediaplayer.set_position.assert_called_once_with(0.5)


def test_wakelock_integration(player_widget) -> None:
    player_widget.instance = MagicMock()
    player_widget.mediaplayer = MagicMock()
    player_widget.wakelock = MagicMock()

    # Test inhibit on play
    player_widget._load_and_play("/path/to/video.mp4")
    player_widget.wakelock.inhibit.assert_called_once()

    # Test uninhibit on stop
    player_widget.stop()
    player_widget.wakelock.uninhibit.assert_called_once()


def test_fullscreen_mouse_move(player_widget, qtbot) -> None:
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

        # Simulate timer timeout (controls hide regardless of playing/paused state)
        player_widget.mediaplayer = MagicMock()
        player_widget._hide_fullscreen_controls()

        assert player_widget.fullscreen_overlay.isHidden()


def test_toggle_stats(player_widget, qtbot) -> None:
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


def test_skip_logic(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.get_time.return_value = 50000  # 50s

    # Skip forward 10s
    player_widget.skip_forward(10)
    player_widget.mediaplayer.set_time.assert_called_with(60000)

    # Skip backward 10s
    player_widget.skip_backward(10)
    player_widget.mediaplayer.set_time.assert_called_with(40000)


def test_toggle_fast_forward(player_widget) -> None:
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


def test_mute_functionality(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.volume_slider.setValue(80)

    # Mute
    player_widget.toggle_mute()
    assert player_widget.is_muted is True
    player_widget.mediaplayer.audio_set_volume.assert_called_with(0)
    assert player_widget.mute_button.text() == "Unmute"

    # Unmute
    player_widget.toggle_mute()
    assert player_widget.is_muted is False
    player_widget.mediaplayer.audio_set_volume.assert_called_with(80)
    assert player_widget.mute_button.text() == "Mute"


def test_volume_boost(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.set_volume(150)
    player_widget.mediaplayer.audio_set_volume.assert_called_with(150)
    assert player_widget.volume_slider.value() == 150
    assert player_widget.fs_volume_slider.value() == 150


def test_volume_osd(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget._show_volume_osd(120)
    assert not player_widget.osd_label.isHidden()
    assert "120%" in player_widget.osd_label.text()

    player_widget._show_volume_osd(0, muted=True)
    assert "Muted" in player_widget.osd_label.text()


def test_resize_event(player_widget) -> None:
    from PySide6.QtGui import QResizeEvent
    from PySide6.QtCore import QSize

    event = QResizeEvent(QSize(800, 600), QSize(640, 480))
    player_widget.resizeEvent(event)
    assert player_widget.progress_overlay.size() == player_widget.video_frame.size()


def test_vlc_instance_args(qtbot) -> None:
    with patch("vlc.Instance") as mock_vlc:
        config.enable_hw_accel = True
        config.vlc_extra_args = ["--test-arg"]

        VideoPlayerWidget()

        args = mock_vlc.call_args[0][0]
        assert "--avcodec-hw=auto" in args
        assert "--test-arg" in args
        assert "--deinterlace=1" in args
        assert "--file-caching=3000" in args


def test_vlc_instance_args_no_hw(qtbot) -> None:
    with patch("vlc.Instance") as mock_vlc:
        config.enable_hw_accel = False
        config.vlc_extra_args = []

        VideoPlayerWidget()

        args = mock_vlc.call_args[0][0]
        assert "--avcodec-hw=none" in args
        assert "--avcodec-hw=auto" not in args


def test_load_and_play_platforms(player_widget) -> None:
    player_widget.instance = MagicMock()
    player_widget.mediaplayer = MagicMock()
    with patch("sys.platform", "win32"):
        player_widget._load_and_play("/path/to/video.mp4")
        player_widget.mediaplayer.set_hwnd.assert_called()
    with patch("sys.platform", "darwin"):
        player_widget._load_and_play("/path/to/video.mp4")
        player_widget.mediaplayer.set_nsobject.assert_called()


def test_toggle_fullscreen(player_widget) -> None:
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


def test_key_press_events(player_widget) -> None:
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


def test_stop_exits_fullscreen(player_widget) -> None:
    main_win = MagicMock()
    main_win.isFullScreen.return_value = True
    player_widget.mediaplayer = MagicMock()

    with patch.object(player_widget, "window", return_value=main_win):
        with patch.object(player_widget, "toggle_fullscreen") as mock_toggle:
            player_widget.stop()
            mock_toggle.assert_called_once()


def test_event_filter_double_click(player_widget) -> None:
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


def test_handle_playback_finished(player_widget, qtbot) -> None:
    with patch.object(player_widget, "stop") as mock_stop:
        with qtbot.waitSignal(player_widget.back_requested):
            player_widget._handle_playback_finished()
        mock_stop.assert_called_once()


def test_ui_layout_completeness(player_widget) -> None:
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

    # Verify fullscreen controls
    assert player_widget.fs_volume_slider.parent() == player_widget.fullscreen_overlay
    assert player_widget.fs_seek_slider.parent() == player_widget.fullscreen_overlay
    assert player_widget.fs_pause_button.parent() == player_widget.fullscreen_overlay


def test_stop_saves_playback_position_incomplete(player_widget) -> None:
    from unittest.mock import MagicMock

    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.get_media.return_value = MagicMock()
    player_widget.current_media_path = "/path/to/ep.mkv"
    player_widget.is_watched_marked = False

    # Simulate stopping at 40% (400s / 1000s) -> > 60s
    player_widget.mediaplayer.get_time.return_value = 400000
    player_widget.mediaplayer.get_length.return_value = 1000000
    config.watched_threshold = 0.9

    with patch("lan_streamer.db.update_episode_playback_position") as mock_db:
        player_widget.stop()
        mock_db.assert_called_once_with("/path/to/ep.mkv", 400)


def test_stop_clears_playback_position_under_one_minute(player_widget) -> None:
    from unittest.mock import MagicMock

    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.get_media.return_value = MagicMock()
    player_widget.current_media_path = "/path/to/ep.mkv"
    player_widget.is_watched_marked = False

    # Simulate stopping at 45s -> <= 60s
    player_widget.mediaplayer.get_time.return_value = 45000
    player_widget.mediaplayer.get_length.return_value = 1000000
    config.watched_threshold = 0.9

    with patch("lan_streamer.db.update_episode_playback_position") as mock_db:
        player_widget.stop()
        mock_db.assert_called_once_with("/path/to/ep.mkv", 0)


def test_stop_resets_playback_position_complete(player_widget) -> None:
    from unittest.mock import MagicMock

    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.get_media.return_value = MagicMock()
    player_widget.current_media_path = "/path/to/ep.mkv"

    # Simulate stopping at 95% (950s / 1000s)
    player_widget.mediaplayer.get_time.return_value = 950000
    player_widget.mediaplayer.get_length.return_value = 1000000
    config.watched_threshold = 0.9
    player_widget.is_watched_marked = False

    with patch("lan_streamer.db.update_episode_playback_position") as mock_db:
        player_widget.stop()
        mock_db.assert_called_once_with("/path/to/ep.mkv", 0)


def test_play_video_prompts_resume(player_widget) -> None:
    with patch("lan_streamer.db.get_episode_playback_position", return_value=300):
        with patch.object(
            player_widget, "_ask_resume_playback", return_value=True
        ) as mock_ask:
            with patch.object(player_widget, "_load_and_play"):
                config.enable_caching = False
                player_widget.play_video("/path/to/resume.mkv")
                mock_ask.assert_called_once_with("05:00")
                assert player_widget.pending_resume_position == 300

        # Simulate applying resume
        player_widget.mediaplayer = MagicMock()
        player_widget.mediaplayer.get_media.return_value = None
        player_widget._apply_pending_resume()
        player_widget.mediaplayer.set_time.assert_called_once_with(300000)
        assert player_widget.pending_resume_position == 0

        # Simulate clicking start from beginning
        with patch.object(player_widget, "_ask_resume_playback", return_value=False):
            with patch(
                "lan_streamer.db.update_episode_playback_position"
            ) as mock_update:
                with patch.object(player_widget, "_load_and_play"):
                    player_widget.play_video("/path/to/resume.mkv")
                    mock_update.assert_called_once_with("/path/to/resume.mkv", 0)
                    assert player_widget.pending_resume_position == 0


def test_play_video_no_prompt_under_one_minute(player_widget) -> None:
    with patch("lan_streamer.db.get_episode_playback_position", return_value=45):
        with patch.object(player_widget, "_ask_resume_playback") as mock_ask:
            with patch(
                "lan_streamer.db.update_episode_playback_position"
            ) as mock_update:
                with patch.object(player_widget, "_load_and_play"):
                    player_widget.play_video("/path/to/short.mkv")
                    mock_ask.assert_not_called()
                    mock_update.assert_called_once_with("/path/to/short.mkv", 0)
                    assert player_widget.pending_resume_position == 0


def test_ask_resume_playback(player_widget) -> None:
    from PySide6.QtWidgets import QMessageBox

    with patch.object(QMessageBox, "exec") as mock_exec:
        with patch.object(QMessageBox, "clickedButton") as mock_clicked:
            added_buttons = []

            def side_effect_add(*args, **kwargs):
                text = args[0] if args else kwargs.get("text", "")
                btn = MagicMock()
                btn.text.return_value = text
                added_buttons.append(btn)
                return btn

            with patch.object(QMessageBox, "addButton", side_effect=side_effect_add):
                mock_clicked.side_effect = lambda: (
                    added_buttons[0] if added_buttons else None
                )
                res = player_widget._ask_resume_playback("05:00")
                assert res is True
                mock_exec.assert_called_once()
                assert len(added_buttons) == 2
                assert added_buttons[0].text() == "Resume Playback"
                assert added_buttons[1].text() == "Start from Beginning"


def test_subtitle_selection_single_english(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.audio_get_track_description.return_value = []
    player_widget.mediaplayer.video_get_spu_description.return_value = [
        (-1, b"Disable"),
        (1, b"English"),
        (2, b"Spanish"),
    ]
    player_widget.mediaplayer.video_get_spu.return_value = -1

    player_widget._refresh_tracks()

    player_widget.mediaplayer.video_set_spu.assert_called_once_with(1)


def test_subtitle_selection_multiple_english_filtered(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.audio_get_track_description.return_value = []
    player_widget.mediaplayer.video_get_spu_description.return_value = [
        (-1, b"Disable"),
        (1, b"English (Forced)"),
        (2, b"English [Signs]"),
        (3, b"English (Songs)"),
        (4, b"English"),
    ]
    player_widget.mediaplayer.video_get_spu.return_value = -1

    player_widget._refresh_tracks()

    player_widget.mediaplayer.video_set_spu.assert_called_once_with(4)


def test_subtitle_selection_multiple_english_all_excluded(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.audio_get_track_description.return_value = []
    player_widget.mediaplayer.video_get_spu_description.return_value = [
        (-1, b"Disable"),
        (1, b"English (Forced)"),
        (2, b"English [Signs]"),
    ]
    player_widget.mediaplayer.video_get_spu.return_value = -1

    player_widget._refresh_tracks()

    # Should fallback to the first English track if all contain excluded words
    player_widget.mediaplayer.video_set_spu.assert_called_once_with(1)


def test_subtitle_selection_no_english_fallback(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.audio_get_track_description.return_value = []
    player_widget.mediaplayer.video_get_spu_description.return_value = [
        (-1, b"Disable"),
        (2, b"French"),
    ]
    player_widget.mediaplayer.video_get_spu.return_value = -1

    player_widget._refresh_tracks()

    player_widget.mediaplayer.video_set_spu.assert_called_once_with(2)


def test_subtitle_selection_no_active_tracks(player_widget) -> None:
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.audio_get_track_description.return_value = []
    player_widget.mediaplayer.video_get_spu_description.return_value = [
        (-1, b"Disable"),
    ]
    player_widget.mediaplayer.video_get_spu.return_value = -1

    player_widget._refresh_tracks()

    player_widget.mediaplayer.video_set_spu.assert_not_called()


def test_realistic_e2e_video_playback_with_subtitles(
    player_widget: Any, generated_video_asset: str
) -> None:
    """
    Validates end to end playback using the pre-generated 1x1 video asset with multiple subtitle tracks.
    Ensures tracks are loaded and parsed realistically.
    """
    config.enable_caching = False
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.get_media.return_value = MagicMock()
    player_widget.mediaplayer.get_position.return_value = 0.5
    player_widget.mediaplayer.get_time.return_value = 50000
    player_widget.mediaplayer.get_length.return_value = 100000
    player_widget.mediaplayer.video_get_spu_description.return_value = [
        (-1, b"Disable"),
        (1, b"Spanish"),
        (2, b"French"),
        (3, b"German"),
        (4, b"English (Forced)"),
        (5, b"English [Signs]"),
        (6, b"English (Songs)"),
        (7, b"English"),
    ]
    player_widget.mediaplayer.video_get_spu.return_value = -1

    with patch.object(player_widget, "_load_and_play") as mock_load:
        player_widget.play_video(generated_video_asset)
        assert player_widget.current_media_path == generated_video_asset
        mock_load.assert_called_once_with(generated_video_asset)

        player_widget._refresh_tracks()

        assert player_widget.subtitle_combo.count() == 8
        player_widget.mediaplayer.video_set_spu.assert_called_with(7)


def test_vlc_instance_fallback_swscale_mode(qtbot) -> None:
    """Test that if vlc.Instance returns None and --swscale-mode=2 is present, it retries without the flag."""

    # We will mock vlc.Instance so that it returns None the FIRST time it's called with --swscale-mode=2
    # And returns a valid mock instance the second time (when the flag is removed).

    with patch("lan_streamer.playback.vlc") as mock_vlc_module:
        mock_vlc_module.Instance.side_effect = lambda args: (
            None if "--swscale-mode=2" in args else MagicMock()
        )
        mock_vlc_module.EventType = MagicMock()

        # Instantiate the widget
        widget = VideoPlayerWidget()

        # Verify Instance was called twice
        assert mock_vlc_module.Instance.call_count == 2

        # The second call should not have the flag
        second_call_args = mock_vlc_module.Instance.call_args_list[1][0][0]
        assert "--swscale-mode=2" not in second_call_args

        # The mediaplayer should have been successfully created from the fallback instance
        assert widget.mediaplayer is not None


def test_vlc_instance_complete_failure(qtbot) -> None:
    """Test when VLC fails to initialize completely even after fallback."""
    with patch("lan_streamer.playback.vlc") as mock_vlc_module:
        mock_vlc_module.Instance.return_value = None
        mock_vlc_module.EventType = MagicMock()

        widget = VideoPlayerWidget()
        assert widget.instance is None
        assert widget.mediaplayer is None


def test_next_episode_popup_triggers_and_interactions(qtbot) -> None:
    """Test that the next episode popup triggers at >=95% playback progress and interactions function properly."""
    with patch("lan_streamer.playback.vlc") as mock_vlc_module:
        mock_vlc_module.Instance.return_value = MagicMock()
        mock_vlc_module.EventType = MagicMock()

        widget = VideoPlayerWidget()
        qtbot.addWidget(widget)

        # Mock database queries and settings
        widget.next_episode_info = {
            "title": "Episode 2 Title",
            "season": "Season 1",
            "episode_number": 2,
            "path": "/path/s1e2.mkv",
        }
        widget.current_media_path = "/path/s1e1.mkv"

        # Mock VLC player progress at 94% (should not trigger)
        widget.mediaplayer.get_media.return_value = MagicMock()
        widget.mediaplayer.get_time.return_value = 94000
        widget.mediaplayer.get_length.return_value = 100000
        widget.mediaplayer.get_position.return_value = 0.94

        widget.update_ui()
        assert widget.next_episode_popup_frame.isHidden() is True
        assert widget.next_episode_popup_shown is False

        # Mock VLC player progress at 98% (should trigger)
        widget.mediaplayer.get_time.return_value = 98000
        widget.mediaplayer.get_position.return_value = 0.98

        widget.update_ui()
        assert widget.next_episode_popup_frame.isHidden() is False
        assert widget.next_episode_popup_shown is True
        assert "Episode 2 Title" in widget.popup_info_label.text()

        # Test ignoring the popup
        widget.ignore_next_episode()
        assert widget.next_episode_popup_frame.isHidden() is True

        # Re-trigger popup
        widget.next_episode_popup_shown = False
        widget.update_ui()
        assert widget.next_episode_popup_frame.isHidden() is False

        # Test playing next episode
        with (
            patch("lan_streamer.db.update_episode_watched_status") as mock_watched,
            patch("lan_streamer.db.update_episode_playback_position") as mock_position,
            patch.object(widget, "play_video") as mock_play_video,
            patch.object(widget, "stop") as mock_stop,
        ):
            widget.play_next_episode()

            assert widget.next_episode_popup_frame.isHidden() is True
            mock_watched.assert_called_once_with("/path/s1e1.mkv", True)
            mock_position.assert_any_call("/path/s1e1.mkv", 0)
            mock_stop.assert_called_once()
            mock_play_video.assert_called_once_with("/path/s1e2.mkv")


def test_next_episode_popup_fullscreen_and_cursor(qtbot) -> None:
    """Test that cursor visibility and fullscreen transitions are handled properly."""
    with patch("lan_streamer.playback.vlc") as mock_vlc_module:
        mock_vlc_module.Instance.return_value = MagicMock()
        mock_vlc_module.EventType = MagicMock()

        widget = VideoPlayerWidget()
        qtbot.addWidget(widget)

        widget.next_episode_info = {
            "title": "Episode 2 Title",
            "season": "Season 1",
            "episode_number": 2,
            "path": "/path/s1e2.mkv",
        }
        widget.current_media_path = "/path/s1e1.mkv"

        # Mock window in fullscreen mode
        mock_window = MagicMock()
        mock_window.isFullScreen.return_value = True
        with patch.object(widget, "window", return_value=mock_window):
            # Trigger popup
            widget.mediaplayer.get_media.return_value = MagicMock()
            widget.mediaplayer.get_time.return_value = 98000
            widget.mediaplayer.get_length.return_value = 100000
            widget.update_ui()

            # Cursor should be ArrowCursor since popup is shown
            assert widget.cursor().shape() == Qt.CursorShape.ArrowCursor

            # When hiding fullscreen controls, cursor should stay ArrowCursor
            widget._hide_fullscreen_controls()
            assert widget.cursor().shape() == Qt.CursorShape.ArrowCursor

            # Test stop() bypasses exiting fullscreen when transitioning to next episode
            with patch.object(widget, "toggle_fullscreen") as mock_toggle:
                widget.is_transitioning_to_next = True
                widget.stop()
                mock_toggle.assert_not_called()


def test_next_episode_popup_positioning(qtbot: Any) -> None:
    """Test that the next episode popup is correctly positioned in the bottom-right corner."""
    with patch("lan_streamer.playback.vlc") as mock_vlc_module:
        mock_vlc_module.Instance.return_value = MagicMock()
        mock_vlc_module.EventType = MagicMock()

        widget = VideoPlayerWidget()
        qtbot.addWidget(widget)

        # Mock the geometry of video_frame
        widget.video_frame.setGeometry(0, 0, 1024, 768)

        # Trigger reposition overlays
        widget._reposition_overlays()

        # Expected position calculation:
        # popup_x = 0 + 1024 - 500 - 20 = 504
        # popup_y = 0 + 768 - 200 - 20 = 548
        popup_geom = widget.next_episode_popup_frame.geometry()
        assert popup_geom.x() == 504
        assert popup_geom.y() == 548
        assert popup_geom.width() == 500
        assert popup_geom.height() == 200


def test_next_episode_popup_countdown_flow(qtbot: Any) -> None:
    """Test that the next episode popup countdown timer ticks down and auto-dismisses the popup."""
    with patch("lan_streamer.playback.vlc") as mock_vlc_module:
        mock_vlc_module.Instance.return_value = MagicMock()
        mock_vlc_module.EventType = MagicMock()

        widget = VideoPlayerWidget()
        qtbot.addWidget(widget)

        widget.next_episode_info = {
            "title": "Episode 2 Title",
            "season": "Season 1",
            "episode_number": 2,
            "path": "/path/s1e2.mkv",
        }

        # Initially popup is hidden
        assert widget.next_episode_popup_frame.isHidden() is True
        assert widget.popup_countdown_timer.isActive() is False

        # Show popup
        widget.show_next_episode_popup()
        assert widget.next_episode_popup_frame.isHidden() is False
        assert widget.popup_countdown_timer.isActive() is True
        assert widget.countdown_seconds == 20
        assert "Closing in 20 seconds" in widget.popup_countdown_label.text()

        # Simulate timer tick
        widget._on_popup_countdown_tick()
        assert widget.countdown_seconds == 19
        assert "Closing in 19 seconds" in widget.popup_countdown_label.text()
        assert widget.next_episode_popup_frame.isHidden() is False

        # Fast forward countdown to 1
        widget.countdown_seconds = 1
        widget._on_popup_countdown_tick()
        # Now it should be 0 and dismissed
        assert widget.countdown_seconds == 0
        assert widget.popup_countdown_timer.isActive() is False
        assert widget.next_episode_popup_frame.isHidden() is True


def test_next_episode_popup_video_ends_before_countdown_completes(qtbot: Any) -> None:
    """Test that the countdown timer is stopped and popup is hidden if the video ends early."""
    with patch("lan_streamer.playback.vlc") as mock_vlc_module:
        mock_vlc_module.Instance.return_value = MagicMock()
        mock_vlc_module.EventType = MagicMock()

        widget = VideoPlayerWidget()
        qtbot.addWidget(widget)

        widget.next_episode_info = {
            "title": "Episode 2 Title",
            "season": "Season 1",
            "episode_number": 2,
            "path": "/path/s1e2.mkv",
        }

        widget.show_next_episode_popup()
        assert widget.next_episode_popup_frame.isHidden() is False
        assert widget.popup_countdown_timer.isActive() is True

        # Simulate video ending
        with patch.object(widget, "back_requested"):
            widget._handle_playback_finished()
            assert widget.popup_countdown_timer.isActive() is False
            assert widget.next_episode_popup_frame.isHidden() is True


def test_next_episode_popup_setting(qtbot: Any) -> None:
    """Test that next episode popup triggers only when enable_next_episode_popup is True."""
    with patch("lan_streamer.playback.vlc") as mock_vlc_module:
        mock_vlc_module.Instance.return_value = MagicMock()
        mock_vlc_module.EventType = MagicMock()

        widget = VideoPlayerWidget()
        qtbot.addWidget(widget)

        widget.next_episode_info = {
            "title": "Episode 2 Title",
            "season": "Season 1",
            "episode_number": 2,
            "path": "/path/s1e2.mkv",
        }
        widget.current_media_path = "/path/s1e1.mkv"

        widget.mediaplayer.get_media.return_value = MagicMock()
        widget.mediaplayer.get_time.return_value = 98000
        widget.mediaplayer.get_length.return_value = 100000
        widget.mediaplayer.get_position.return_value = 0.98

        # Case 1: config setting is False -> should not trigger
        config.enable_next_episode_popup = False
        widget.next_episode_popup_shown = False
        widget.update_ui()
        assert widget.next_episode_popup_frame.isHidden() is True
        assert widget.next_episode_popup_shown is False

        # Case 2: config setting is True -> should trigger
        config.enable_next_episode_popup = True
        widget.next_episode_popup_shown = False
        widget.update_ui()
        assert widget.next_episode_popup_frame.isHidden() is False
        assert widget.next_episode_popup_shown is True


def test_show_subtitles_audio_menu(player_widget) -> None:
    """Test that _show_subtitles_audio_menu refreshes tracks, updates pane text, and displays the menu."""
    player_widget.mediaplayer = MagicMock()
    player_widget.mediaplayer.audio_get_track_description.return_value = [
        (1, b"English Dolby Digital 5.1"),
        (2, b"French Stereo"),
    ]
    player_widget.mediaplayer.video_get_spu_description.return_value = [
        (-1, b"Disable"),
        (10, b"English [CC]"),
        (11, b"Spanish"),
    ]
    player_widget.mediaplayer.audio_get_track.return_value = 1
    player_widget.mediaplayer.video_get_spu.return_value = 10

    with patch("lan_streamer.playback.widget.QMenu") as MockQMenu:
        mock_menu_instance = MagicMock()
        MockQMenu.return_value = mock_menu_instance

        # We also mock sub-menus returned by addMenu
        mock_sub_menu = MagicMock()
        mock_menu_instance.addMenu.return_value = mock_sub_menu

        player_widget._show_subtitles_audio_menu()

        # Verify that _refresh_tracks was called and combos are populated
        assert player_widget.audio_combo.count() == 2
        assert player_widget.subtitle_combo.count() == 3

        # Verify that the text displayed in the pane is correct
        assert "English Dolby" in player_widget.subtitles_audio_button.text()
        assert "English [CC]" in player_widget.subtitles_audio_button.text()

        mock_menu_instance.exec.assert_called_once()


def test_select_track_from_menu(player_widget) -> None:
    """Test that selecting audio/subtitle tracks from menu index correctly updates comboboxes and calls VLC."""
    player_widget.mediaplayer = MagicMock()
    player_widget.audio_combo.addItem("Track 1", 1)
    player_widget.audio_combo.addItem("Track 2", 2)
    player_widget.subtitle_combo.addItem("Sub 1", 10)
    player_widget.subtitle_combo.addItem("Sub 2", 11)

    player_widget._select_audio_track_from_menu(1)
    player_widget.mediaplayer.audio_set_track.assert_called_once_with(2)

    player_widget._select_subtitle_track_from_menu(1)
    player_widget.mediaplayer.video_set_spu.assert_called_once_with(11)


def test_movie_vs_episode_navigation_buttons(player_widget) -> None:
    """Test that next/prev episode buttons are hidden for movies and shown for episodes."""
    config.enable_caching = False
    player_widget._load_and_play = MagicMock()

    # Case 1: Playing a movie
    with patch("lan_streamer.db.is_movie", return_value=True):
        player_widget.play_video("/movies/some_movie.mkv")

        assert player_widget.new_prev_btn.isHidden() is True
        assert player_widget.new_next_btn.isHidden() is True
        assert player_widget.fs_new_prev_btn.isHidden() is True
        assert player_widget.fs_new_next_btn.isHidden() is True

    # Case 2: Playing a TV episode (not a movie)
    with patch("lan_streamer.db.is_movie", return_value=False):
        player_widget.play_video("/tv/some_episode.mkv")

        assert player_widget.new_prev_btn.isHidden() is False
        assert player_widget.new_next_btn.isHidden() is False
        assert player_widget.fs_new_prev_btn.isHidden() is False
        assert player_widget.fs_new_next_btn.isHidden() is False


def test_playback_speed_toggling(player_widget) -> None:
    """Test that speed buttons correctly cycle through playback rates (1.0x -> 1.5x -> 2.0x -> 1.0x)."""
    player_widget.mediaplayer = MagicMock()

    # Initial text verification
    assert player_widget.new_rate_btn.button.text() == "1.0x"
    assert player_widget.fs_new_rate_btn.button.text() == "1.0x"

    # Cycle 1: 1.0 -> 1.5
    player_widget.mediaplayer.get_rate.return_value = 1.0
    player_widget.toggle_fast_forward()
    player_widget.mediaplayer.set_rate.assert_called_with(1.5)
    assert player_widget.new_rate_btn.button.text() == "1.5x"
    assert player_widget.fs_new_rate_btn.button.text() == "1.5x"

    # Cycle 2: 1.5 -> 2.0
    player_widget.mediaplayer.get_rate.return_value = 1.5
    player_widget.toggle_fast_forward()
    player_widget.mediaplayer.set_rate.assert_called_with(2.0)
    assert player_widget.new_rate_btn.button.text() == "2.0x"
    assert player_widget.fs_new_rate_btn.button.text() == "2.0x"

    # Cycle 3: 2.0 -> 1.0
    player_widget.mediaplayer.get_rate.return_value = 2.0
    player_widget.toggle_fast_forward()
    player_widget.mediaplayer.set_rate.assert_called_with(1.0)
    assert player_widget.new_rate_btn.button.text() == "1.0x"
    assert player_widget.fs_new_rate_btn.button.text() == "1.0x"

    # Verify stop resets back to 1.0x
    player_widget.new_rate_btn.button.setText("2.0x")
    player_widget.fs_new_rate_btn.button.setText("2.0x")
    player_widget.stop()
    assert player_widget.new_rate_btn.button.text() == "1.0x"
    assert player_widget.fs_new_rate_btn.button.text() == "1.0x"
