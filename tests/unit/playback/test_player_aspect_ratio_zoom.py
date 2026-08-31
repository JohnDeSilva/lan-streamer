"""Unit tests for VideoPlayerWidget aspect ratio, fill screen (zoom), and crop modes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from lan_streamer.playback.widget import VideoPlayerWidget
from lan_streamer.system.config import config


def _create_mock_mediaplayer() -> MagicMock:
    mediaplayer = MagicMock()
    mediaplayer.get_state.return_value = 3  # Playing
    mediaplayer.get_time.return_value = 10000
    mediaplayer.get_length.return_value = 60000
    mediaplayer.video_get_spu_count.return_value = 0
    mediaplayer.audio_get_track_count.return_value = 0
    return mediaplayer


def test_set_video_aspect_mode_fit(qtbot) -> None:
    player = VideoPlayerWidget()
    qtbot.addWidget(player)
    player.mediaplayer = _create_mock_mediaplayer()

    player.set_video_aspect_mode("fit", show_osd=True)

    assert player.current_aspect_mode == "fit"
    player.mediaplayer.video_set_aspect_ratio.assert_called_with(None)
    player.mediaplayer.video_set_crop_geometry.assert_called_with(None)
    player.mediaplayer.video_set_scale.assert_called_with(0.0)


def test_set_video_aspect_mode_fill_zoom(qtbot) -> None:
    player = VideoPlayerWidget()
    qtbot.addWidget(player)
    player.mediaplayer = _create_mock_mediaplayer()
    player.video_frame.resize(1920, 1080)

    player.set_video_aspect_mode("fill", show_osd=True)

    assert player.current_aspect_mode == "fill"
    player.mediaplayer.video_set_aspect_ratio.assert_called_with(None)
    player.mediaplayer.video_set_crop_geometry.assert_called_with("1920:1080")
    player.mediaplayer.video_set_scale.assert_called_with(0.0)


def test_set_video_aspect_mode_stretch(qtbot) -> None:
    player = VideoPlayerWidget()
    qtbot.addWidget(player)
    player.mediaplayer = _create_mock_mediaplayer()
    player.video_frame.resize(1920, 1080)

    player.set_video_aspect_mode("stretch", show_osd=True)

    assert player.current_aspect_mode == "stretch"
    player.mediaplayer.video_set_crop_geometry.assert_called_with(None)
    player.mediaplayer.video_set_aspect_ratio.assert_called_with("1920:1080")
    player.mediaplayer.video_set_scale.assert_called_with(0.0)


def test_set_video_aspect_mode_fixed_ratios(qtbot) -> None:
    player = VideoPlayerWidget()
    qtbot.addWidget(player)
    player.mediaplayer = _create_mock_mediaplayer()

    for ratio in ["16:9", "21:9", "4:3", "16:10", "2.35:1"]:
        player.set_video_aspect_mode(ratio, show_osd=False)
        assert player.current_aspect_mode == ratio
        player.mediaplayer.video_set_crop_geometry.assert_called_with(None)
        player.mediaplayer.video_set_aspect_ratio.assert_called_with(ratio)
        player.mediaplayer.video_set_scale.assert_called_with(0.0)


def test_set_video_zoom_scale(qtbot) -> None:
    player = VideoPlayerWidget()
    qtbot.addWidget(player)
    player.mediaplayer = _create_mock_mediaplayer()

    player.set_video_zoom_scale(1.25, show_osd=True)

    assert player.current_aspect_mode == "zoom:1.25"
    player.mediaplayer.video_set_aspect_ratio.assert_called_with(None)
    player.mediaplayer.video_set_crop_geometry.assert_called_with(None)
    player.mediaplayer.video_set_scale.assert_called_with(1.25)


def test_cycle_video_aspect_mode(qtbot) -> None:
    player = VideoPlayerWidget()
    qtbot.addWidget(player)
    player.mediaplayer = _create_mock_mediaplayer()

    player.set_video_aspect_mode("fit", show_osd=False)
    player.cycle_video_aspect_mode()
    assert player.current_aspect_mode == "fill"

    player.cycle_video_aspect_mode()
    assert player.current_aspect_mode == "stretch"

    player.cycle_video_aspect_mode()
    assert player.current_aspect_mode == "16:9"

    player.cycle_video_aspect_mode()
    assert player.current_aspect_mode == "21:9"

    player.cycle_video_aspect_mode()
    assert player.current_aspect_mode == "4:3"

    player.cycle_video_aspect_mode()
    assert player.current_aspect_mode == "fit"


def test_key_press_z_cycles_aspect_mode(qtbot) -> None:
    player = VideoPlayerWidget()
    qtbot.addWidget(player)
    player.mediaplayer = _create_mock_mediaplayer()
    player.current_aspect_mode = "fit"

    with patch.object(player, "cycle_video_aspect_mode") as mock_cycle:
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Z,
            Qt.KeyboardModifier.NoModifier,
            "z",
        )
        player.keyPressEvent(event)
        mock_cycle.assert_called_once()


def test_reposition_overlays_reapplies_dynamic_aspect_modes(qtbot) -> None:
    player = VideoPlayerWidget()
    qtbot.addWidget(player)
    player.mediaplayer = _create_mock_mediaplayer()

    player.set_video_aspect_mode("fill", show_osd=False)
    player.video_frame.resize(2560, 1440)
    player._reposition_overlays()

    player.mediaplayer.video_set_crop_geometry.assert_called_with("2560:1440")


def test_settings_dialog_default_aspect_mode(qtbot) -> None:
    from lan_streamer.ui_views.dialogs.settings import SettingsDialog

    with patch.object(config, "default_video_aspect_mode", "fill"):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)

        assert dialog.default_aspect_mode_selector.currentData() == "fill"

        dialog.default_aspect_mode_selector.setCurrentIndex(
            dialog.default_aspect_mode_selector.findData("21:9")
        )
        with patch.object(config, "save"), patch.object(config, "save_to_db"):
            dialog.save_config()
            assert config.default_video_aspect_mode == "21:9"
