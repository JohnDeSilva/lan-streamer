import os
import time
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import sys

from PySide6.QtWidgets import (
    QWidget,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QLabel,
    QFrame,
    QComboBox,
    QSizePolicy,
    QProgressBar,
    QMessageBox,
    QMenu,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QEvent, QSize
from PySide6.QtGui import QFont

from lan_streamer.system.config import config
from lan_streamer import db
from lan_streamer.playback.wakelock import WakeLock
from lan_streamer.playback.proxy import vlc, CacheWorker

logger = logging.getLogger("lan_streamer.player_widget")


class VerticalMediaButton(QWidget):
    """Custom widget wrapper containing a QPushButton and QLabel."""

    button: QPushButton
    label: QLabel


class VideoPlayerWidget(QWidget):
    """Embedded VLC media player widget with caching and advanced controls."""

    back_requested = Signal()
    watched_marked = Signal(str)  # path
    fullscreen_changed = Signal(bool)
    _playback_finished_signal = Signal()  # Internal for cross-thread VLC events

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        if vlc:
            # Base arguments for high quality and smooth playback
            args = [
                "--quiet",
                "--no-video-title-show",
                "--no-xlib",
                "--disable-screensaver",
                "--video-filter=deinterlace",
                "--deinterlace=1",
                "--deinterlace-mode=yadif",
                # Caching to ensure smooth delivery
                f"--file-caching={config.vlc_buffer_ms}",
                f"--network-caching={config.vlc_buffer_ms}",
                f"--live-caching={config.vlc_buffer_ms}",
                # High quality scaling and decoding
                "--swscale-mode=2",  # Lanczos
                "--avcodec-skiploopfilter=0",
                # Enable multi-threaded decoding
                "--avcodec-threads=0",  # Auto-detect cores
            ]

            if config.enable_hw_accel:
                # 'auto' or 'any' lets VLC choose the best hardware decoder
                args.append("--avcodec-hw=auto")
            else:
                args.append("--avcodec-hw=none")

            # Add any user-defined extra arguments
            if config.vlc_extra_args:
                args.extend(config.vlc_extra_args)

            if sys.platform == "linux":
                args.append("--aout=pulse")

            logger.info(f"Initializing VLC Instance with args: {args}")
            self.instance = vlc.Instance(args)

            # Fallback for environments missing swscale plugin (e.g. PyInstaller executables)
            if self.instance is None and "--swscale-mode=2" in args:
                logger.warning(
                    "VLC initialization failed. Retrying without --swscale-mode=2"
                )
                args.remove("--swscale-mode=2")
                self.instance = vlc.Instance(args)

            if self.instance is not None:
                self.mediaplayer = self.instance.media_player_new()
            else:
                self.mediaplayer = None
                logger.error(
                    "VLC Instance could not be initialized even after fallback."
                )

            if self.mediaplayer:
                # Event manager for detecting end of playback
                self.event_manager = self.mediaplayer.event_manager()
                self.event_manager.event_attach(
                    vlc.EventType.MediaPlayerEndReached, self._on_playback_finished
                )
        else:
            self.instance = None
            self.mediaplayer = None
        self.current_media_path: str | None = None
        self.cached_file_path: str | None = None
        self.pending_resume_position: int = 0
        self.is_watched_marked = False
        self._is_playback_finished = False
        self.is_muted = False
        self.previous_volume = 80
        self.wakelock = WakeLock()
        self.next_episode_popup_shown: bool = False
        self.next_episode_info: Optional[Dict[str, Any]] = None
        self.is_transitioning_to_next: bool = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Timer for auto-hiding fullscreen controls
        self.hide_controls_timer = QTimer(self)
        self.hide_controls_timer.setInterval(3000)  # 3 seconds
        self.hide_controls_timer.setSingleShot(True)
        self.hide_controls_timer.timeout.connect(self._hide_fullscreen_controls)

        # Timer for next episode popup countdown
        self.countdown_seconds: int = 20
        self.popup_countdown_timer = QTimer(self)
        self.popup_countdown_timer.setInterval(1000)
        self.popup_countdown_timer.setSingleShot(False)
        self.popup_countdown_timer.timeout.connect(self._on_popup_countdown_tick)

        self._setup_ui()

        # Timer for updating UI (seek bar, time labels, watched threshold)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_ui)

    def _apply_fullscreen_styles(self) -> None:
        """Applies styling to fullscreen overlay based on config."""
        pass

    def _create_vertical_media_button(
        self, icon: str, label_text: str, slot: Any, font_size: int = 20
    ) -> VerticalMediaButton:
        container = VerticalMediaButton()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn = QPushButton(icon)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: #f8fafc;
                border: none;
                font-size: {font_size}px;
                min-width: 40px;
                min-height: 40px;
            }}
            QPushButton:hover {{
                color: #38bdf8;
            }}
            QPushButton:pressed {{
                color: #0284c7;
            }}
        """)

        lbl = QLabel(label_text)
        lbl.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #94a3b8; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(btn)
        layout.addWidget(lbl)
        container.button = btn
        container.label = lbl
        return container

    def _create_volume_layout(self, is_fullscreen: bool = False) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        vol_icon = QPushButton("🔊")
        vol_icon.setObjectName("volumeIcon")
        vol_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        vol_icon.setFixedSize(20, 40)
        vol_icon.setStyleSheet("""
            QPushButton#volumeIcon {
                background: transparent;
                background-color: transparent;
                color: #f8fafc;
                border: none;
                border-radius: 0px;
                font-size: 14px;
                min-height: 40px;
                max-height: 40px;
                padding: 0px;
                margin: 0px;
            }
        """)
        vol_icon.clicked.connect(self.toggle_mute)

        minus_btn = QPushButton("−")
        minus_btn.setObjectName("volumeMinusBtn")
        minus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        minus_btn.setFixedSize(12, 12)
        minus_btn.setStyleSheet("""
            QPushButton#volumeMinusBtn {
                background: transparent;
                background-color: transparent;
                color: #94a3b8;
                border: none;
                border-radius: 0px;
                font-size: 12px;
                font-weight: bold;
                min-width: 12px;
                max-width: 12px;
                min-height: 12px;
                max-height: 12px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton#volumeMinusBtn:hover {
                color: #38bdf8;
            }
            QPushButton#volumeMinusBtn:pressed {
                color: #0284c7;
            }
        """)
        minus_btn.clicked.connect(self.decrease_volume)

        slider = self.fs_volume_slider if is_fullscreen else self.volume_slider
        slider.setOrientation(Qt.Orientation.Horizontal)
        slider.setFixedWidth(100)
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #475569;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #38bdf8;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #f8fafc;
                width: 12px;
                height: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #38bdf8;
            }
        """)

        plus_btn = QPushButton("+")
        plus_btn.setObjectName("volumePlusBtn")
        plus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        plus_btn.setFixedSize(12, 12)
        plus_btn.setStyleSheet("""
            QPushButton#volumePlusBtn {
                background: transparent;
                background-color: transparent;
                color: #94a3b8;
                border: none;
                border-radius: 0px;
                font-size: 12px;
                font-weight: bold;
                min-width: 12px;
                max-width: 12px;
                min-height: 12px;
                max-height: 12px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton#volumePlusBtn:hover {
                color: #38bdf8;
            }
            QPushButton#volumePlusBtn:pressed {
                color: #0284c7;
            }
        """)
        plus_btn.clicked.connect(self.increase_volume)

        row.addWidget(vol_icon, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(6)
        row.addWidget(minus_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(8)
        row.addWidget(slider, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(8)
        row.addWidget(plus_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(row)

        percent_lbl = QLabel(f"VOLUME: {slider.value()}%")
        percent_lbl.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        percent_lbl.setStyleSheet("color: #94a3b8; background: transparent;")
        percent_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(percent_lbl)

        if is_fullscreen:
            self.fs_vol_percent_label = percent_lbl
            self.fs_vol_icon = vol_icon
            self.fs_volume_minus_btn = minus_btn
            self.fs_volume_plus_btn = plus_btn
        else:
            self.vol_percent_label = percent_lbl
            self.vol_icon = vol_icon
            self.volume_minus_btn = minus_btn
            self.volume_plus_btn = plus_btn

        return layout

    def _create_controls_set(
        self, is_fullscreen: bool = False
    ) -> tuple[
        VerticalMediaButton,
        VerticalMediaButton,
        VerticalMediaButton,
        VerticalMediaButton,
        VerticalMediaButton,
        VerticalMediaButton,
    ]:
        """Creates and returns the vertical media buttons set to avoid code duplication."""
        rew_btn = self._create_vertical_media_button(
            "◀◀", "REWIND", lambda: self.skip_backward(10)
        )
        play_btn = self._create_vertical_media_button(
            "▶", "PLAY/PAUSE", self.play_pause, font_size=32
        )
        stop_btn = self._create_vertical_media_button(
            "■", "STOP", self._on_stop_clicked, font_size=26
        )
        ff_btn = self._create_vertical_media_button(
            "▶▶", "FAST FORWARD", lambda: self.skip_forward(10)
        )
        rate_btn = self._create_vertical_media_button(
            "1.0x", "SPEED", self.toggle_fast_forward
        )
        fullscreen_btn = self._create_vertical_media_button(
            "⛶", "FULLSCREEN", self.toggle_fullscreen, font_size=32
        )

        if is_fullscreen:
            self.fs_new_rew_btn = rew_btn
            self.fs_new_play_btn = play_btn
            self.fs_new_stop_btn = stop_btn
            self.fs_new_ff_btn = ff_btn
            self.fs_new_rate_btn = rate_btn
            self.fs_new_fullscreen_btn = fullscreen_btn
        else:
            self.new_rew_btn = rew_btn
            self.new_play_btn = play_btn
            self.new_stop_btn = stop_btn
            self.new_ff_btn = ff_btn
            self.new_rate_btn = rate_btn
            self.new_fullscreen_btn = fullscreen_btn

        return rew_btn, play_btn, stop_btn, ff_btn, rate_btn, fullscreen_btn

    def _show_subtitles_audio_menu(self) -> None:
        self._refresh_tracks()
        sender = self.sender()
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #38bdf8;
                color: #0f172a;
            }
            QMenu::separator {
                height: 1px;
                background-color: #334155;
                margin: 4px 0px;
            }
        """)

        audio_menu = menu.addMenu("Audio Tracks")
        audio_menu.setStyleSheet(menu.styleSheet())
        for idx in range(self.audio_combo.count()):
            track_name = self.audio_combo.itemText(idx)
            action = audio_menu.addAction(track_name)

            def make_audio_slot(i: int) -> Any:
                return lambda: self._select_audio_track_from_menu(i)

            action.triggered.connect(make_audio_slot(idx))

        sub_menu = menu.addMenu("Subtitles")
        sub_menu.setStyleSheet(menu.styleSheet())
        for idx in range(self.subtitle_combo.count()):
            track_name = self.subtitle_combo.itemText(idx)
            action = sub_menu.addAction(track_name)

            def make_sub_slot(i: int) -> Any:
                return lambda: self._select_subtitle_track_from_menu(i)

            action.triggered.connect(make_sub_slot(idx))

        # Audio Output Devices
        device_menu = menu.addMenu("Audio Devices")
        device_menu.setStyleSheet(menu.styleSheet())
        has_devices = False
        if vlc and self.mediaplayer:
            try:
                mods = self.mediaplayer.audio_output_device_enum()
                if mods:
                    current_device = self.mediaplayer.audio_output_device_get()
                    if isinstance(current_device, bytes):
                        current_device = current_device.decode("utf-8", errors="ignore")

                    curr = mods
                    while curr:
                        try:
                            dev_id = curr.contents.device
                            if isinstance(dev_id, bytes):
                                dev_id = dev_id.decode("utf-8", errors="ignore")
                            dev_desc = curr.contents.description
                            if isinstance(dev_desc, bytes):
                                dev_desc = dev_desc.decode("utf-8", errors="ignore")

                            if dev_id:
                                has_devices = True
                                action = device_menu.addAction(dev_desc or dev_id)
                                action.setCheckable(True)

                                is_active = current_device and dev_id == current_device
                                is_preferred = (
                                    config.preferred_audio_device
                                    and dev_id == config.preferred_audio_device
                                )
                                if is_active or (not current_device and is_preferred):
                                    action.setChecked(True)

                                def make_device_slot(d_id: str) -> Any:
                                    return lambda: self._select_audio_device(d_id)

                                action.triggered.connect(make_device_slot(dev_id))
                        except Exception:
                            logger.exception("Error parsing VLC audio device item")
                        curr = curr.contents.next

                    vlc.libvlc_audio_output_device_list_release(mods)
            except Exception:
                logger.exception("Failed to enumerate VLC audio devices")

        if not has_devices:
            action = device_menu.addAction("No Audio Devices Found")
            action.setEnabled(False)

        if isinstance(sender, QWidget):
            menu.exec(sender.mapToGlobal(sender.rect().bottomLeft()))
        else:
            menu.exec(
                self.subtitles_audio_button.mapToGlobal(
                    self.subtitles_audio_button.rect().bottomLeft()
                )
            )

    def _select_audio_device(self, device_id: str) -> None:
        if self.mediaplayer:
            logger.info(f"Setting audio output device to: {device_id}")
            self.mediaplayer.audio_output_device_set(None, device_id)
            config.preferred_audio_device = device_id
            config.save_to_db()
            self._show_osd("Audio Output Changed")

    def _select_audio_track_from_menu(self, index: int) -> None:
        self.audio_combo.setCurrentIndex(index)
        self._update_subtitles_audio_pane_text()

    def _select_subtitle_track_from_menu(self, index: int) -> None:
        self.subtitle_combo.setCurrentIndex(index)
        self._update_subtitles_audio_pane_text()

    def _update_subtitles_audio_pane_text(self) -> None:
        audio_text = self.audio_combo.currentText() or "None"
        sub_text = self.subtitle_combo.currentText() or "None"
        if len(audio_text) > 30:
            audio_text = audio_text[:27] + "..."
        if len(sub_text) > 30:
            sub_text = sub_text[:27] + "..."
        pane_text = f"AUDIO: {audio_text}\nSUBTITLES: {sub_text}"
        if hasattr(self, "subtitles_audio_button"):
            self.subtitles_audio_button.setText(pane_text)
        if hasattr(self, "fs_subtitles_audio_button"):
            self.fs_subtitles_audio_button.setText(pane_text)

    def _setup_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # Video Frame
        self.video_frame = QFrame()
        self.video_frame.setWindowFlags(
            Qt.WindowType.Widget | Qt.WindowType.FramelessWindowHint
        )
        self.video_frame.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.video_frame.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.video_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.video_frame.setStyleSheet("background-color: black;")
        self.video_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.video_frame.setMouseTracking(True)
        self.video_frame.installEventFilter(self)
        self.main_layout.addWidget(self.video_frame)

        # Progress Overlay (for caching)
        self.progress_overlay = QWidget(self)
        self.progress_overlay.setStyleSheet("background-color: rgba(0, 0, 0, 150);")
        overlay_layout = QVBoxLayout(self.progress_overlay)
        self.progress_label = QLabel("Caching video... Please wait.")
        self.progress_label.setStyleSheet("color: white; font-size: 16px;")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(400)
        overlay_layout.addStretch()
        overlay_layout.addWidget(self.progress_label, 0, Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(self.progress_bar, 0, Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addStretch()
        self.progress_overlay.hide()

        # Fullscreen Overlay
        self.fullscreen_overlay = QFrame(self)
        self.fullscreen_overlay.setObjectName("fullscreenOverlay")
        self.fullscreen_overlay.setStyleSheet("""
            QFrame#fullscreenOverlay {
                background-color: rgba(15, 23, 42, 220);
                border: 1px solid rgba(255, 255, 255, 15);
                border-radius: 12px;
            }
        """)
        self.fullscreen_overlay.setFixedWidth(1150)

        # Legacy fs controls for test compatibility
        self.fs_pause_button = QPushButton("Pause", self.fullscreen_overlay)
        self.fs_pause_button.hide()
        self.fs_skip_back_button = QPushButton("<<", self.fullscreen_overlay)
        self.fs_skip_back_button.hide()
        self.fs_skip_fwd_button = QPushButton(">>", self.fullscreen_overlay)
        self.fs_skip_fwd_button.hide()
        self.fs_time_label = QLabel("00:00 / 00:00", self.fullscreen_overlay)
        self.fs_time_label.hide()
        self.fs_vol_label = QLabel("Volume:", self.fullscreen_overlay)
        self.fs_vol_label.hide()

        # Volume sliders for layout parent checks in test_widget.py
        self.fs_volume_slider = QSlider(
            Qt.Orientation.Horizontal, self.fullscreen_overlay
        )
        self.fs_volume_slider.setMaximum(200)
        self.fs_volume_slider.setValue(80)
        self.fs_volume_slider.valueChanged.connect(self.set_volume)

        self.fs_seek_slider = QSlider(
            Qt.Orientation.Horizontal, self.fullscreen_overlay
        )
        self.fs_seek_slider.setMaximum(1000)
        self.fs_seek_slider.sliderMoved.connect(self.set_position)

        fs_main_layout = QVBoxLayout(self.fullscreen_overlay)
        fs_main_layout.setContentsMargins(20, 15, 20, 15)
        fs_main_layout.setSpacing(10)

        # 1. Fullscreen Seek Row
        fs_seek_layout = QHBoxLayout()
        fs_seek_layout.setContentsMargins(0, 0, 0, 0)
        fs_seek_layout.setSpacing(10)

        self.fs_elapsed_label = QLabel("00:00")
        self.fs_elapsed_label.setFont(QFont("Inter", 10))
        self.fs_elapsed_label.setStyleSheet("color: #94a3b8; background: transparent;")

        self.fs_duration_label = QLabel("00:00")
        self.fs_duration_label.setFont(QFont("Inter", 10))
        self.fs_duration_label.setStyleSheet("color: #94a3b8; background: transparent;")

        fs_seek_layout.addWidget(self.fs_elapsed_label)
        fs_seek_layout.addWidget(self.fs_seek_slider)
        fs_seek_layout.addWidget(self.fs_duration_label)
        fs_main_layout.addLayout(fs_seek_layout)

        # 2. Fullscreen Buttons Row
        fs_buttons_layout = QHBoxLayout()
        fs_buttons_layout.setContentsMargins(0, 0, 0, 0)
        fs_buttons_layout.setSpacing(15)

        fs_rew_btn, fs_play_btn, fs_stop_btn, fs_ff_btn, fs_rate_btn, fs_fs_btn = (
            self._create_controls_set(is_fullscreen=True)
        )

        fs_buttons_layout.addWidget(fs_rew_btn)
        fs_buttons_layout.addWidget(fs_play_btn)
        fs_buttons_layout.addWidget(fs_stop_btn)
        fs_buttons_layout.addWidget(fs_ff_btn)
        fs_buttons_layout.addWidget(fs_rate_btn)

        fs_buttons_layout.addStretch()

        self.fs_subtitles_audio_button = QPushButton()
        self.fs_subtitles_audio_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fs_subtitles_audio_button.setText("AUDIO: None\nSUBTITLES: None")
        self.fs_subtitles_audio_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(30, 41, 59, 120);
                border: 1px solid rgba(255, 255, 255, 15);
                border-radius: 8px;
                padding: 6px 16px;
                color: #f8fafc;
                font-family: 'Inter';
                font-size: 11px;
                text-align: center;
                line-height: 14px;
            }
            QPushButton:hover {
                background-color: rgba(30, 41, 59, 200);
                border-color: #38bdf8;
            }
        """)
        self.fs_subtitles_audio_button.clicked.connect(self._show_subtitles_audio_menu)
        fs_buttons_layout.addWidget(self.fs_subtitles_audio_button)

        fs_volume_layout = self._create_volume_layout(is_fullscreen=True)
        fs_buttons_layout.addLayout(fs_volume_layout)

        fs_buttons_layout.addWidget(fs_fs_btn)

        fs_main_layout.addLayout(fs_buttons_layout)

        self._apply_fullscreen_styles()
        self.fullscreen_overlay.hide()

        # Volume OSD
        self.osd_label = QLabel(self)
        self.osd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.osd_label.setStyleSheet(
            "color: white; font-size: 32px; font-weight: bold; background-color: rgba(0, 0, 0, 150); padding: 15px; border-radius: 10px;"
        )
        self.osd_label.hide()
        self.osd_timer = QTimer(self)
        self.osd_timer.setInterval(2000)
        self.osd_timer.setSingleShot(True)
        self.osd_timer.timeout.connect(self.osd_label.hide)

        # Next Episode Popup Overlay
        self.next_episode_popup_frame = QFrame(self)
        self.next_episode_popup_frame.setObjectName("nextEpisodePopupFrame")
        self.next_episode_popup_frame.setStyleSheet("""
            QFrame#nextEpisodePopupFrame {
                background-color: rgba(15, 15, 20, 210);
                border: 1px solid rgba(255, 255, 255, 15);
                border-radius: 16px;
            }
            QLabel {
                background: transparent;
                color: #f8fafc;
            }
        """)

        popup_layout = QHBoxLayout(self.next_episode_popup_frame)
        popup_layout.setContentsMargins(15, 15, 15, 15)
        popup_layout.setSpacing(15)

        self.popup_thumbnail_label = QLabel()
        self.popup_thumbnail_label.setFixedSize(90, 130)
        self.popup_thumbnail_label.setStyleSheet(
            "border-radius: 8px; background-color: #1e293b; border: 1px solid #334155;"
        )
        self.popup_thumbnail_label.setScaledContents(True)
        popup_layout.addWidget(self.popup_thumbnail_label)

        right_column = QWidget()
        right_column.setStyleSheet("background: transparent;")
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        header_label = QLabel("NEXT EPISODE")
        header_label.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        header_label.setStyleSheet("color: #38bdf8;")
        right_layout.addWidget(header_label)

        self.popup_title_label = QLabel("EPISODE TITLE")
        self.popup_title_label.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        self.popup_title_label.setWordWrap(True)
        self.popup_title_label.setStyleSheet("color: #f8fafc;")
        right_layout.addWidget(self.popup_title_label)

        self.popup_info_label = QLabel("Season X, Episode Y")
        self.popup_info_label.setFont(QFont("Inter", 11))
        self.popup_info_label.setStyleSheet("color: #94a3b8;")
        right_layout.addWidget(self.popup_info_label)

        self.popup_countdown_progress = QProgressBar()
        self.popup_countdown_progress.setObjectName("countdownBar")
        self.popup_countdown_progress.setRange(0, 20)
        self.popup_countdown_progress.setValue(20)
        self.popup_countdown_progress.setTextVisible(False)
        self.popup_countdown_progress.setFixedHeight(4)
        self.popup_countdown_progress.setStyleSheet("""
            QProgressBar#countdownBar {
                background-color: rgba(255, 255, 255, 40);
                border: none;
                border-radius: 2px;
            }
            QProgressBar#countdownBar::chunk {
                background-color: #38bdf8;
                border-radius: 2px;
            }
        """)
        right_layout.addWidget(self.popup_countdown_progress)

        self.popup_countdown_label = QLabel("Playing in 20s...")
        self.popup_countdown_label.setFont(QFont("Inter", 9))
        self.popup_countdown_label.setStyleSheet("color: #64748b;")
        right_layout.addWidget(self.popup_countdown_label)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.popup_ignore_button = QPushButton("Ignore")
        self.popup_ignore_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.popup_ignore_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 14px;
                padding: 5px 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 10);
                color: #f8fafc;
            }
        """)
        self.popup_ignore_button.clicked.connect(self.ignore_next_episode)

        self.popup_play_next_button = QPushButton("PLAY NOW")
        self.popup_play_next_button.setObjectName("playNextPill")
        self.popup_play_next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.popup_play_next_button.setStyleSheet("""
            QPushButton#playNextPill {
                background-color: #ffffff;
                color: #0f0f11;
                border-radius: 14px;
                font-weight: bold;
                padding: 5px 16px;
                font-size: 11px;
                border: none;
            }
            QPushButton#playNextPill:hover {
                background-color: #e2e8f0;
            }
        """)
        self.popup_play_next_button.clicked.connect(self.play_next_episode)

        button_layout.addWidget(self.popup_ignore_button)
        button_layout.addWidget(self.popup_play_next_button)
        button_layout.addStretch()
        right_layout.addLayout(button_layout)

        popup_layout.addWidget(right_column)

        self.next_episode_popup_frame.hide()

        # Stats Overlay
        self.stats_overlay = QFrame(self)
        self.stats_overlay.setStyleSheet(
            "background-color: rgba(0, 0, 0, 220); color: white; border: 1px solid #555; border-radius: 5px;"
        )
        stats_layout = QVBoxLayout(self.stats_overlay)
        self.stats_label = QLabel("Playback Information")
        self.stats_label.setStyleSheet(
            "font-family: monospace; font-size: 10px; color: white;"
        )
        stats_layout.addWidget(self.stats_label)
        self.stats_overlay.hide()

        # Controls Widget (container for easy hiding in fullscreen)
        self.controls_widget = QWidget()
        self.controls_widget.setObjectName("controlsWidget")
        self.controls_widget.setStyleSheet("""
            QWidget#controlsWidget {
                background-color: rgba(15, 23, 42, 220);
                border-top: 1px solid rgba(255, 255, 255, 10);
            }
            QLabel {
                background: transparent;
                color: #f8fafc;
            }
        """)
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(20, 15, 20, 15)
        controls_layout.setSpacing(10)

        # Legacy controls for test compatibility
        self.time_label = QLabel("00:00 / 00:00", self.controls_widget)
        self.time_label.hide()
        self.play_button = QPushButton("Play", self.controls_widget)
        self.play_button.hide()
        self.stop_button = QPushButton("Stop", self.controls_widget)
        self.stop_button.hide()
        self.skip_back_button = QPushButton("<< 10s", self.controls_widget)
        self.skip_back_button.hide()
        self.skip_fwd_button = QPushButton("10s >>", self.controls_widget)
        self.skip_fwd_button.hide()
        self.rate_button = QPushButton("1.0x", self.controls_widget)
        self.rate_button.hide()
        self.audio_combo = QComboBox(self.controls_widget)
        self.audio_combo.setPlaceholderText("Audio Track")
        self.audio_combo.hide()
        self.subtitle_combo = QComboBox(self.controls_widget)
        self.subtitle_combo.setPlaceholderText("Subtitles")
        self.subtitle_combo.hide()
        self.mute_button = QPushButton("Mute", self.controls_widget)
        self.mute_button.hide()
        self.back_button = QPushButton("Back", self.controls_widget)
        self.back_button.hide()
        self.fullscreen_button = QPushButton("Fullscreen", self.controls_widget)
        self.fullscreen_button.hide()

        # Connect legacy combos to the track changes slots
        self.audio_combo.currentIndexChanged.connect(self.change_audio_track)
        self.subtitle_combo.currentIndexChanged.connect(self.change_subtitle_track)

        # 1. Seek Slider Row
        seek_layout = QHBoxLayout()
        seek_layout.setContentsMargins(0, 0, 0, 0)
        seek_layout.setSpacing(10)

        self.elapsed_label = QLabel("00:00")
        self.elapsed_label.setFont(QFont("Inter", 10))
        self.elapsed_label.setStyleSheet("color: #94a3b8;")

        self.seek_slider = QSlider(Qt.Orientation.Horizontal, self.controls_widget)
        self.seek_slider.setMaximum(1000)
        self.seek_slider.sliderMoved.connect(self.set_position)
        self.seek_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #334155;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #38bdf8;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #f8fafc;
                width: 14px;
                height: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #38bdf8;
                width: 16px;
                height: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
        """)

        self.duration_label = QLabel("00:00")
        self.duration_label.setFont(QFont("Inter", 10))
        self.duration_label.setStyleSheet("color: #94a3b8;")

        seek_layout.addWidget(self.elapsed_label)
        seek_layout.addWidget(self.seek_slider)
        seek_layout.addWidget(self.duration_label)
        controls_layout.addLayout(seek_layout)

        # 2. Buttons / Pane Row
        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(15)

        rew_btn, play_btn, stop_btn, ff_btn, rate_btn, fs_btn = (
            self._create_controls_set(is_fullscreen=False)
        )

        buttons_layout.addWidget(rew_btn)
        buttons_layout.addWidget(play_btn)
        buttons_layout.addWidget(stop_btn)
        buttons_layout.addWidget(ff_btn)
        buttons_layout.addWidget(rate_btn)

        buttons_layout.addStretch()

        self.subtitles_audio_button = QPushButton()
        self.subtitles_audio_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subtitles_audio_button.setText("AUDIO: None\nSUBTITLES: None")
        self.subtitles_audio_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(30, 41, 59, 120);
                border: 1px solid rgba(255, 255, 255, 15);
                border-radius: 8px;
                padding: 6px 16px;
                color: #f8fafc;
                font-family: 'Inter';
                font-size: 11px;
                text-align: center;
                line-height: 14px;
            }
            QPushButton:hover {
                background-color: rgba(30, 41, 59, 200);
                border-color: #38bdf8;
            }
        """)
        self.subtitles_audio_button.clicked.connect(self._show_subtitles_audio_menu)
        buttons_layout.addWidget(self.subtitles_audio_button)

        buttons_layout.addSpacing(10)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal, self.controls_widget)
        self.volume_slider.setMaximum(200)
        self.volume_slider.setValue(80)
        self.volume_slider.valueChanged.connect(self.set_volume)

        volume_layout = self._create_volume_layout(is_fullscreen=False)
        buttons_layout.addLayout(volume_layout)

        buttons_layout.addSpacing(10)

        buttons_layout.addWidget(fs_btn)

        controls_layout.addLayout(buttons_layout)
        self.main_layout.addWidget(self.controls_widget)

    def eventFilter(self, watched: Any, event: Any) -> bool:
        if watched == self.video_frame:
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self.toggle_fullscreen()
                return True
            elif event.type() == QEvent.Type.MouseMove:
                self._handle_mouse_move()
        return super().eventFilter(watched, event)

    def _handle_mouse_move(self) -> None:
        if self.window().isFullScreen():
            self._show_fullscreen_controls()
            self.hide_controls_timer.start()

    def _show_fullscreen_controls(self) -> None:
        self.fullscreen_overlay.show()
        self.fullscreen_overlay.raise_()
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _hide_fullscreen_controls(self) -> None:
        if self.window().isFullScreen() and self.mediaplayer:
            if (
                hasattr(self, "next_episode_popup_frame")
                and not self.next_episode_popup_frame.isHidden()
            ):
                self.setCursor(Qt.CursorShape.ArrowCursor)
                return
            self.fullscreen_overlay.hide()
            self.setCursor(Qt.CursorShape.BlankCursor)

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape and self.window().isFullScreen():
            self.toggle_fullscreen()
        elif event.key() == Qt.Key.Key_F:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key.Key_Space:
            self.play_pause()
        elif event.key() == Qt.Key.Key_Up:
            self.increase_volume()
        elif event.key() == Qt.Key.Key_Down:
            self.decrease_volume()
        elif event.key() == Qt.Key.Key_Left or event.key() == Qt.Key.Key_J:
            self.skip_backward(10)
        elif event.key() == Qt.Key.Key_Right or event.key() == Qt.Key.Key_L:
            self.skip_forward(10)
        elif event.key() == Qt.Key.Key_K:
            self.play_pause()
        elif event.key() == Qt.Key.Key_S:
            self.toggle_fast_forward()
        elif event.key() == Qt.Key.Key_M:
            self.toggle_mute()
        elif event.key() == Qt.Key.Key_I:
            self.toggle_stats()
        else:
            super().keyPressEvent(event)

    def toggle_fullscreen(self) -> None:
        main_win = self.window()
        if main_win.isFullScreen():
            logger.info("Exiting fullscreen mode")
            main_win.showNormal()
            self.controls_widget.show()
            self.fullscreen_overlay.hide()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.hide_controls_timer.stop()
            self.fullscreen_changed.emit(False)
            # Show menu bar and status bar if they exist
            if isinstance(main_win, QMainWindow):
                main_win.menuBar().show()
                main_win.statusBar().show()
        else:
            logger.info("Entering fullscreen mode")
            main_win.showFullScreen()
            self.controls_widget.hide()
            # Position overlay at bottom center
            self._show_fullscreen_controls()
            self.hide_controls_timer.start()
            self.fullscreen_changed.emit(True)
            self._reposition_overlays()
            if isinstance(main_win, QMainWindow):
                main_win.menuBar().hide()
                main_win.statusBar().hide()
        self._reposition_overlays()

    def _reposition_overlays(self) -> None:
        self.progress_overlay.resize(self.video_frame.size())

        # Center the fullscreen overlay at the bottom
        fs_size = QSize(1150, 120)
        self.fullscreen_overlay.resize(fs_size)

        # Position relative to video_frame's geometry in case it's shifted
        v_geom = self.video_frame.geometry()
        x = v_geom.x() + (v_geom.width() - fs_size.width()) // 2
        y = v_geom.y() + v_geom.height() - fs_size.height() - 20
        self.fullscreen_overlay.move(x, y)

        # Center OSD label
        self.osd_label.adjustSize()
        v_geom = self.video_frame.geometry()
        osd_x = v_geom.x() + (v_geom.width() - self.osd_label.width()) // 2
        osd_y = v_geom.y() + (v_geom.height() - self.osd_label.height()) // 2
        self.osd_label.move(osd_x, osd_y)

        # Position Next Episode Popup Overlay at the bottom-right corner
        if hasattr(self, "next_episode_popup_frame"):
            popup_size = QSize(500, 200)
            self.next_episode_popup_frame.resize(popup_size)
            popup_x = v_geom.x() + v_geom.width() - popup_size.width() - 20
            popup_y = v_geom.y() + v_geom.height() - popup_size.height() - 20
            self.next_episode_popup_frame.move(popup_x, popup_y)

        # Position Stats Overlay at top-left
        self.stats_overlay.move(v_geom.x() + 20, v_geom.y() + 20)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._reposition_overlays()

    def play_video(self, file_path: str) -> None:
        """Starts the playback process (caching if enabled)."""
        logger.info(f"Request to play video: {file_path}")
        self.setFocus()
        self.stop()
        self.current_media_path = file_path
        self.is_watched_marked = False
        self._is_playback_finished = False
        self.next_episode_popup_shown = False
        self.next_episode_info = db.get_next_episode(file_path)
        self.pending_resume_position = 0

        saved_pos = db.get_episode_playback_position(file_path)
        if saved_pos > 60:
            formatted_time = self._format_time(saved_pos)
            if self._ask_resume_playback(formatted_time):
                logger.info(f"User chose to resume playback from {saved_pos}s")
                self.pending_resume_position = saved_pos
            else:
                logger.info("User chose to start playback from the beginning")
                db.update_episode_playback_position(file_path, 0)
        elif saved_pos > 0:
            logger.info(
                f"Saved position {saved_pos}s is <= 60s, starting from beginning without prompt"
            )
            db.update_episode_playback_position(file_path, 0)

        if config.enable_caching:
            logger.info("Caching is enabled, starting cache process")
            self._start_caching(file_path)
        else:
            logger.info("Caching is disabled, playing directly")
            self._load_and_play(file_path)

    def _ask_resume_playback(self, formatted_time: str) -> bool:
        """Prompts the user with custom buttons to resume or restart."""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Resume Playback")
        msg_box.setText(
            f"Do you want to resume playback from {formatted_time} or start from the beginning?"
        )
        resume_btn = msg_box.addButton(
            "Resume Playback", QMessageBox.ButtonRole.AcceptRole
        )
        msg_box.addButton("Start from Beginning", QMessageBox.ButtonRole.RejectRole)
        msg_box.exec()
        return msg_box.clickedButton() == resume_btn

    def _start_caching(self, file_path: str) -> None:
        self.progress_overlay.show()
        self.progress_overlay.raise_()
        self.progress_bar.setValue(0)

        # Create destination path in cache directory
        cache_dir = Path(config.cache_directory)
        cache_dir.mkdir(parents=True, exist_ok=True)

        dest_path = cache_dir / Path(file_path).name
        self.cached_file_path = str(dest_path)

        try:
            source_path = Path(file_path)
            if (
                dest_path.exists()
                and source_path.exists()
                and dest_path.stat().st_size == source_path.stat().st_size
            ):
                logger.info(f"File already cached: {dest_path}, playing directly")
                dest_path.touch()
                self.progress_overlay.hide()
                self._load_and_play(str(dest_path))
                return
        except Exception:
            logger.exception("Could not verify existing cache file size")

        self._cleanup_cache()

        self.cache_worker = CacheWorker(file_path, str(dest_path))
        self.cache_worker.progress.connect(self.progress_bar.setValue)
        self.cache_worker.finished.connect(self._on_caching_finished)
        self.cache_worker.error.connect(self._on_caching_error)
        self.cache_worker.start()

    @Slot(str)
    def _on_caching_finished(self, cached_path: str) -> None:
        self.progress_overlay.hide()
        self._load_and_play(cached_path)

    @Slot(str)
    def _on_caching_error(self, error_msg: str) -> None:
        self.progress_overlay.hide()
        logger.error(f"Caching error: {error_msg}")
        # Fallback to direct playback
        if self.current_media_path:
            self._load_and_play(self.current_media_path)

    def _load_and_play(self, file_path: str) -> None:
        if not vlc or not self.instance:
            error_msg = "VLC library could not be loaded."
            if sys.platform == "darwin":
                error_msg += (
                    "\n\nCAUSE: Architecture Mismatch.\nYou are likely running the app on Apple Silicon (M1/M2/M3) "
                    "using a native ARM64 Python, but you have an Intel (x86_64) version of VLC installed."
                    "\n\nFIX: Download the 'Apple Silicon' version of VLC from the official VideoLAN website."
                )

            QMessageBox.critical(self, "VLC Error", error_msg)
            logger.error(error_msg)
            return

        logger.info(f"Initializing VLC playback for: {file_path}")
        # Ensure the widget is realized before getting winId
        self.video_frame.show()

        self.media = self.instance.media_new(file_path)
        self.mediaplayer.set_media(self.media)

        # Set the window handle for video output
        win_id = int(self.video_frame.winId())
        if sys.platform == "linux":
            self.mediaplayer.set_xwindow(win_id)
        elif sys.platform == "win32":
            self.mediaplayer.set_hwnd(win_id)
        elif sys.platform == "darwin":
            self.mediaplayer.set_nsobject(win_id)

        self.mediaplayer.play()
        self.wakelock.inhibit(f"Playing {os.path.basename(file_path)}")
        self.timer.start()
        self.play_button.setText("Pause")
        self.fs_pause_button.setText("Pause")
        if hasattr(self, "new_play_btn"):
            self.new_play_btn.button.setText("⏸")
        if hasattr(self, "fs_new_play_btn"):
            self.fs_new_play_btn.button.setText("⏸")
        self._update_subtitles_audio_pane_text()

        # Initial volume
        self.mediaplayer.audio_set_volume(self.volume_slider.value())

        # Initial audio output device
        if getattr(config, "preferred_audio_device", None):
            logger.info(
                f"Applying preferred audio output device: {config.preferred_audio_device}"
            )
            self.mediaplayer.audio_output_device_set(
                None, config.preferred_audio_device
            )

        # Schedule playback resumption seek and track refresh
        QTimer.singleShot(500, self._apply_pending_resume)
        QTimer.singleShot(1000, self._refresh_tracks)

    def _apply_pending_resume(self) -> None:
        if self.pending_resume_position > 0 and self.mediaplayer:
            logger.info(f"Seeking to resumed position: {self.pending_resume_position}s")
            self.mediaplayer.set_time(self.pending_resume_position * 1000)
            self._show_osd(
                f"Resumed from {self._format_time(self.pending_resume_position)}"
            )
            self.pending_resume_position = 0

    def _refresh_tracks(self) -> None:
        if not self.mediaplayer:
            return
        # Audio tracks
        self.audio_combo.blockSignals(True)
        self.audio_combo.clear()
        audio_tracks = self.mediaplayer.audio_get_track_description()
        decoded_audio = []
        for track_id, track_name in audio_tracks:
            decoded_name = (
                track_name.decode() if isinstance(track_name, bytes) else track_name
            )
            self.audio_combo.addItem(decoded_name, track_id)
            decoded_audio.append((track_id, decoded_name))

        selected_audio = None
        active_audio = [
            (t_id, t_name)
            for t_id, t_name in decoded_audio
            if t_id != -1 and "disable" not in t_name.lower()
        ]

        if active_audio:
            english_audio = [
                (t_id, t_name)
                for t_id, t_name in active_audio
                if "english" in t_name.lower()
            ]
            if english_audio:
                if len(english_audio) == 1:
                    selected_audio = english_audio[0][0]
                else:
                    excluded_words = [
                        "commentary",
                        "description",
                        "descriptive",
                        "director",
                    ]
                    preferred_audio = [
                        (t_id, t_name)
                        for t_id, t_name in english_audio
                        if not any(word in t_name.lower() for word in excluded_words)
                    ]
                    if preferred_audio:
                        selected_audio = preferred_audio[0][0]
                    else:
                        selected_audio = english_audio[0][0]

        if selected_audio is not None:
            logger.info(f"Automatically selecting audio track ID: {selected_audio}")
            self.mediaplayer.audio_set_track(selected_audio)
            current_audio = selected_audio
        else:
            current_audio = self.mediaplayer.audio_get_track()

        idx = self.audio_combo.findData(current_audio)
        if idx != -1:
            self.audio_combo.setCurrentIndex(idx)
        self.audio_combo.blockSignals(False)

        # Subtitle tracks (SPU)
        self.subtitle_combo.blockSignals(True)
        self.subtitle_combo.clear()
        subtitle_tracks = self.mediaplayer.video_get_spu_description()
        decoded_subs = []
        if subtitle_tracks:
            for track_id, track_name in subtitle_tracks:
                decoded_name = (
                    track_name.decode() if isinstance(track_name, bytes) else track_name
                )
                self.subtitle_combo.addItem(decoded_name, track_id)
                decoded_subs.append((track_id, decoded_name))

        selected_spu = None
        active_subs = [
            (t_id, t_name)
            for t_id, t_name in decoded_subs
            if t_id != -1 and "disable" not in t_name.lower()
        ]

        if active_subs:
            english_subs = [
                (t_id, t_name)
                for t_id, t_name in active_subs
                if "english" in t_name.lower()
            ]
            if english_subs:
                if len(english_subs) == 1:
                    selected_spu = english_subs[0][0]
                else:
                    excluded_words = ["forced", "signs", "songs"]
                    preferred_subs = [
                        (t_id, t_name)
                        for t_id, t_name in english_subs
                        if not any(word in t_name.lower() for word in excluded_words)
                    ]
                    if preferred_subs:
                        selected_spu = preferred_subs[0][0]
                    else:
                        selected_spu = english_subs[0][0]
            else:
                selected_spu = active_subs[0][0]

        if selected_spu is not None:
            logger.info(f"Automatically selecting subtitle track ID: {selected_spu}")
            self.mediaplayer.video_set_spu(selected_spu)
            current_sub = selected_spu
        else:
            current_sub = self.mediaplayer.video_get_spu()

        idx = self.subtitle_combo.findData(current_sub)
        if idx != -1:
            self.subtitle_combo.setCurrentIndex(idx)
        self.subtitle_combo.blockSignals(False)
        self._update_subtitles_audio_pane_text()

    def change_audio_track(self, index: int) -> None:
        track_id = self.audio_combo.itemData(index)
        if track_id is not None:
            logger.info(f"Changing audio track to ID: {track_id}")
            self.mediaplayer.audio_set_track(track_id)

    def change_subtitle_track(self, index: int) -> None:
        track_id = self.subtitle_combo.itemData(index)
        if track_id is not None:
            logger.info(f"Changing subtitle track to ID: {track_id}")
            self.mediaplayer.video_set_spu(track_id)

    def play_pause(self) -> None:
        if self.mediaplayer.is_playing():
            logger.info("Pausing playback")
            self.mediaplayer.pause()
            self.play_button.setText("Play")
            self.fs_pause_button.setText("Play")
            if hasattr(self, "new_play_btn"):
                self.new_play_btn.button.setText("▶")
            if hasattr(self, "fs_new_play_btn"):
                self.fs_new_play_btn.button.setText("▶")
        else:
            logger.info("Resuming playback")
            self.mediaplayer.play()
            self.play_button.setText("Pause")
            self.fs_pause_button.setText("Pause")
            if hasattr(self, "new_play_btn"):
                self.new_play_btn.button.setText("⏸")
            if hasattr(self, "fs_new_play_btn"):
                self.fs_new_play_btn.button.setText("⏸")

    def stop(self) -> None:
        logger.info("Stopping playback")
        self.popup_countdown_timer.stop()
        if self.window().isFullScreen() and not getattr(
            self, "is_transitioning_to_next", False
        ):
            self.toggle_fullscreen()
        if hasattr(self, "next_episode_popup_frame"):
            self.next_episode_popup_frame.hide()
        if self.mediaplayer:
            media = self.mediaplayer.get_media()
            if media and self.current_media_path:
                curr_time = self.mediaplayer.get_time() // 1000
                duration = self.mediaplayer.get_length() // 1000
                if duration > 0:
                    is_completed = (
                        self._is_playback_finished
                        or (curr_time / duration) >= config.watched_threshold
                    )
                    if not self.is_watched_marked and is_completed:
                        logger.info(
                            f"Playback completed or exceeded watched threshold. Marking as watched for {self.current_media_path}"
                        )
                        self._mark_as_watched()
                        db.update_episode_playback_position(self.current_media_path, 0)
                    elif not self.is_watched_marked:
                        if curr_time > 60:
                            logger.info(
                                f"Saving playback position for {self.current_media_path} at {curr_time}s"
                            )
                            db.update_episode_playback_position(
                                self.current_media_path, curr_time
                            )
                        else:
                            logger.info(
                                f"Playback stopped before 1 minute ({curr_time}s), clearing saved position for {self.current_media_path}"
                            )
                            db.update_episode_playback_position(
                                self.current_media_path, 0
                            )
                    else:
                        logger.info(
                            f"Video already marked watched, clearing saved position for {self.current_media_path}"
                        )
                        db.update_episode_playback_position(self.current_media_path, 0)

            self.mediaplayer.stop()
        self.wakelock.uninhibit()
        self.timer.stop()
        self.play_button.setText("Play")
        if hasattr(self, "new_play_btn"):
            self.new_play_btn.button.setText("▶")
        if hasattr(self, "fs_new_play_btn"):
            self.fs_new_play_btn.button.setText("▶")
        if hasattr(self, "new_rate_btn") and self.new_rate_btn:
            self.new_rate_btn.button.setText("1.0x")
        if hasattr(self, "fs_new_rate_btn") and self.fs_new_rate_btn:
            self.fs_new_rate_btn.button.setText("1.0x")
        self.seek_slider.setValue(0)
        self.fs_seek_slider.setValue(0)
        self.time_label.setText("00:00 / 00:00")
        if hasattr(self, "elapsed_label"):
            self.elapsed_label.setText("00:00")
            self.duration_label.setText("00:00")
        if hasattr(self, "fs_elapsed_label"):
            self.fs_elapsed_label.setText("00:00")
            self.fs_duration_label.setText("00:00")
        self._cleanup_cache()
        self._is_playback_finished = False

    def _on_stop_clicked(self) -> None:
        """Called when user clicks the stop button."""
        self.stop()
        self.back_requested.emit()

    def _on_playback_finished(self, event: Any) -> None:
        """Called by VLC thread when video ends."""
        self._playback_finished_signal.emit()

    @Slot()
    def _handle_playback_finished(self) -> None:
        """Handles the end of playback on the UI thread."""
        self._is_playback_finished = True
        self.stop()
        self.back_requested.emit()

    def set_volume(self, volume: int) -> None:
        logger.debug(f"Setting playback volume to {volume}%")
        if self.mediaplayer:
            self.mediaplayer.audio_set_volume(volume)

        # Sync sliders
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(volume)
        self.volume_slider.blockSignals(False)

        self.fs_volume_slider.blockSignals(True)
        self.fs_volume_slider.setValue(volume)
        self.fs_volume_slider.blockSignals(False)

        if hasattr(self, "vol_percent_label"):
            self.vol_percent_label.setText(f"{volume}%")
        if hasattr(self, "fs_vol_percent_label"):
            self.fs_vol_percent_label.setText(f"{volume}%")

        if volume > 0 and self.is_muted:
            self.is_muted = False
            self._update_mute_ui()

    def increase_volume(self) -> None:
        new_vol = min(self.volume_slider.value() + 5, 200)
        self.set_volume(new_vol)
        self._show_volume_osd(new_vol)

    def decrease_volume(self) -> None:
        new_vol = max(self.volume_slider.value() - 5, 0)
        self.set_volume(new_vol)
        self._show_volume_osd(new_vol)

    def toggle_mute(self) -> None:
        if self.is_muted:
            self.is_muted = False
            self.set_volume(self.previous_volume)
        else:
            self.previous_volume = self.volume_slider.value()
            self.is_muted = True
            self.set_volume(0)
        self._update_mute_ui()
        self._show_volume_osd(
            0 if self.is_muted else self.volume_slider.value(), muted=self.is_muted
        )

    def _update_mute_ui(self) -> None:
        text = "Unmute" if self.is_muted else "Mute"
        self.mute_button.setText(text)
        icon = "🔇" if self.is_muted else "🔊"
        if hasattr(self, "vol_icon"):
            self.vol_icon.setText(icon)
        if hasattr(self, "fs_vol_icon"):
            self.fs_vol_icon.setText(icon)

    def _show_volume_osd(self, volume: int, muted: bool = False) -> None:
        if muted:
            self.osd_label.setText("Muted")
        else:
            self.osd_label.setText(f"Volume: {volume}%")

        self._reposition_overlays()
        self.osd_label.show()
        self.osd_timer.start()

    def skip_forward(self, seconds: int) -> None:
        if self.mediaplayer:
            curr_time = self.mediaplayer.get_time()
            self.mediaplayer.set_time(curr_time + (seconds * 1000))
            self._show_osd(f"Skip Forward {seconds}s")

    def skip_backward(self, seconds: int) -> None:
        if self.mediaplayer:
            curr_time = self.mediaplayer.get_time()
            self.mediaplayer.set_time(max(0, curr_time - (seconds * 1000)))
            self._show_osd(f"Skip Backward {seconds}s")

    def toggle_fast_forward(self) -> None:
        if not self.mediaplayer:
            return

        current_rate = self.mediaplayer.get_rate()
        if current_rate < 1.4:
            new_rate = 1.5
        elif current_rate < 1.9:
            new_rate = 2.0
        else:
            new_rate = 1.0

        self.mediaplayer.set_rate(new_rate)
        text = f"{new_rate}x"
        self.rate_button.setText(text)
        if hasattr(self, "new_rate_btn") and self.new_rate_btn:
            self.new_rate_btn.button.setText(text)
        if hasattr(self, "fs_new_rate_btn") and self.fs_new_rate_btn:
            self.fs_new_rate_btn.button.setText(text)
        self._show_osd(f"Playback Speed: {text}")

    def _show_osd(self, text: str) -> None:
        self.osd_label.setText(text)
        self._reposition_overlays()
        self.osd_label.show()
        self.osd_label.raise_()
        self.osd_timer.start()

    def set_position(self, position: int) -> None:
        logger.debug(f"Seeking player position to: {position}/1000")
        self.mediaplayer.set_position(position / 1000.0)

    def toggle_stats(self) -> None:
        if self.stats_overlay.isHidden():
            self.stats_overlay.show()
            self.stats_overlay.raise_()
            self._update_stats()
            self._show_osd("Playback Stats: ON")
        else:
            self.stats_overlay.hide()
            self._show_osd("Playback Stats: OFF")

    def _update_stats(self) -> None:
        if not self.mediaplayer or self.stats_overlay.isHidden():
            return

        self.stats_overlay.raise_()
        media = self.mediaplayer.get_media()
        if not media:
            return

        stats = vlc.MediaStats()
        if media.get_stats(stats):
            # Resolution & FPS
            size = self.mediaplayer.video_get_size(0)
            width, height = size if size and len(size) == 2 else (0, 0)
            fps = self.mediaplayer.get_fps()

            # Calculate bitrates in Mbps
            in_br = (stats.input_bitrate * 8) / 1024.0
            demux_br = (stats.demux_bitrate * 8) / 1024.0

            text = (
                f"<b>Playback Information</b><br/>"
                f"Resolution: {width}x{height}<br/>"
                f"Frame Rate: {fps:.2f} fps<br/>"
                f"Input Bitrate: {in_br:.2f} Mbps<br/>"
                f"Demux Bitrate: {demux_br:.2f} Mbps<br/>"
                f"Video Decoded: {stats.decoded_video}<br/>"
                f"Frames Displayed: {stats.displayed_pictures}<br/>"
                f"Frames Lost: <font color='{'red' if stats.lost_pictures > 0 else 'white'}'>{stats.lost_pictures}</font><br/>"
                f"Audio Decoded: {stats.decoded_audio}<br/>"
                f"Audio Buffers Lost: <font color='{'red' if stats.lost_abuffers > 0 else 'white'}'>{stats.lost_abuffers}</font>"
            )
            self.stats_label.setText(text)
            self.stats_overlay.adjustSize()

    def update_ui(self) -> None:
        if not self.mediaplayer.get_media():
            return

        # Update seek bar
        pos = self.mediaplayer.get_position()
        self.seek_slider.setValue(int(pos * 1000))
        self.fs_seek_slider.setValue(int(pos * 1000))

        # Update stats if visible
        self._update_stats()

        # Update time label
        curr_time = self.mediaplayer.get_time() // 1000
        duration = self.mediaplayer.get_length() // 1000

        if duration > 0:
            time_text = (
                f"{self._format_time(curr_time)} / {self._format_time(duration)}"
            )
            self.time_label.setText(time_text)
            self.fs_time_label.setText(time_text)

            # Update our new labels
            if hasattr(self, "elapsed_label"):
                self.elapsed_label.setText(self._format_time(curr_time))
            if hasattr(self, "duration_label"):
                self.duration_label.setText(self._format_time(duration))
            if hasattr(self, "fs_elapsed_label"):
                self.fs_elapsed_label.setText(self._format_time(curr_time))
            if hasattr(self, "fs_duration_label"):
                self.fs_duration_label.setText(self._format_time(duration))

            # Show next episode popup if playback reaches 98% watched and a next episode exists
            if (
                config.enable_next_episode_popup
                and not self.next_episode_popup_shown
                and self.next_episode_info is not None
                and self.next_episode_info.get("path")
                and (curr_time / duration) >= 0.98
            ):
                self.show_next_episode_popup()

    def show_next_episode_popup(self) -> None:
        """Shows the next episode popup overlay with next episode details."""
        if not self.next_episode_info or not self.next_episode_info.get("path"):
            return

        self.next_episode_popup_shown = True
        logger.info(f"Showing next episode popup overlay: {self.next_episode_info}")

        title: str = self.next_episode_info.get("title") or "Unknown Title"
        season: str = self.next_episode_info.get("season") or "Unknown Season"
        episode_number: Optional[Any] = self.next_episode_info.get("episode_number")
        poster_path: str = self.next_episode_info.get("poster_path") or ""

        # Load poster if path exists
        if poster_path and os.path.exists(poster_path):
            from PySide6.QtGui import QPixmap

            pixmap = QPixmap(poster_path)
            if not pixmap.isNull():
                self.popup_thumbnail_label.setPixmap(pixmap)
            else:
                self.popup_thumbnail_label.setText("No Image")
        else:
            self.popup_thumbnail_label.setText("No Image")

        episode_string: str = (
            f"Episode {episode_number}"
            if episode_number is not None
            else "Next Episode"
        )
        info_text: str = f'{season}, {episode_string}\n"{title}"'
        self.popup_info_label.setText(info_text)
        self.popup_title_label.setText(title.upper())

        self.countdown_seconds = 20
        self.popup_countdown_label.setText("Closing in 20 seconds...")
        if hasattr(self, "popup_countdown_progress"):
            self.popup_countdown_progress.setValue(20)
        self.popup_countdown_timer.start()

        if self.window().isFullScreen():
            self.setCursor(Qt.CursorShape.ArrowCursor)

        self.next_episode_popup_frame.show()
        self.next_episode_popup_frame.raise_()
        self._reposition_overlays()

    def ignore_next_episode(self) -> None:
        """Dismisses the next episode popup overlay and continues playing."""
        logger.info("User ignored the next episode popup")
        self.popup_countdown_timer.stop()
        self.next_episode_popup_frame.hide()
        self.setFocus()

    def play_next_episode(self) -> None:
        """Plays the next episode immediately, preserving fullscreen state."""
        logger.info("User requested to play the next episode immediately")
        self.popup_countdown_timer.stop()
        next_episode_path: Optional[str] = (
            self.next_episode_info.get("path") if self.next_episode_info else None
        )
        self.next_episode_popup_frame.hide()

        if self.current_media_path:
            self._mark_as_watched()
            db.update_episode_playback_position(self.current_media_path, 0)

        self.is_transitioning_to_next = True
        try:
            self.stop()
            if next_episode_path:
                self.play_video(next_episode_path)
        finally:
            self.is_transitioning_to_next = False

    @Slot()
    def _on_popup_countdown_tick(self) -> None:
        self.countdown_seconds -= 1
        logger.debug(
            f"Popup countdown tick: {self.countdown_seconds} seconds remaining"
        )
        self.popup_countdown_label.setText(
            f"Closing in {self.countdown_seconds} seconds..."
        )
        if hasattr(self, "popup_countdown_progress"):
            self.popup_countdown_progress.setValue(self.countdown_seconds)
        if self.countdown_seconds <= 0:
            logger.info("Countdown expired. Dismissing next episode popup.")
            self.popup_countdown_timer.stop()
            self.ignore_next_episode()

    def _format_time(self, seconds: int) -> str:
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _mark_as_watched(self) -> None:
        if self.current_media_path:
            logger.info(f"Marking as watched: {self.current_media_path}")
            db.update_episode_watched_status(self.current_media_path, True)
            self.is_watched_marked = True
            self.watched_marked.emit(self.current_media_path)

    def _cleanup_cache(self) -> None:
        cache_dir = Path(config.cache_directory)
        if not cache_dir.exists():
            return

        try:
            current_time = time.time()
            # 1. Delete files older than 24 hours
            for file_path in cache_dir.iterdir():
                if file_path.is_file():
                    try:
                        if current_time - file_path.stat().st_mtime > 86400:
                            logger.info(
                                f"Deleting cached file older than 24 hours: {file_path}"
                            )
                            file_path.unlink()
                            if self.cached_file_path == str(file_path):
                                self.cached_file_path = None
                    except Exception:
                        logger.exception(
                            f"Error checking or deleting old cache file {file_path}"
                        )

            # 2. Enforce maximum cache size
            max_size_bytes = config.max_cache_size_gb * 1024 * 1024 * 1024
            cached_files = []
            total_size_bytes = 0
            for file_path in cache_dir.iterdir():
                if file_path.is_file():
                    try:
                        file_status = file_path.stat()
                        cached_files.append(
                            (file_status.st_mtime, file_status.st_size, file_path)
                        )
                        total_size_bytes += file_status.st_size
                    except Exception:
                        logger.exception(f"Error stating cache file {file_path}")

            if total_size_bytes > max_size_bytes:
                cached_files.sort(key=lambda item: item[0])
                for modification_time, file_size, file_path in cached_files:
                    if total_size_bytes <= max_size_bytes:
                        break
                    try:
                        logger.info(
                            f"Deleting cached file to free space (cache exceeds max size): {file_path}"
                        )
                        file_path.unlink()
                        total_size_bytes -= file_size
                        if self.cached_file_path == str(file_path):
                            self.cached_file_path = None
                    except Exception:
                        logger.exception(
                            f"Error deleting cache file {file_path} for size enforcement"
                        )

        except Exception:
            logger.exception("Error during cache cleanup")

    def on_back_clicked(self) -> None:
        self.stop()
        self.back_requested.emit()

    def closeEvent(self, event: Any) -> None:
        self.stop()
        super().closeEvent(event)
