import os
import time
import logging
from pathlib import Path
from typing import Any
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
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, Slot, QEvent, QSize
import sys
from .config import config
from . import db
from .wakelock import WakeLock

logger = logging.getLogger(__name__)

try:
    import vlc
except (ImportError, OSError) as e:
    logger.warning(f"VLC library could not be loaded: {e}")
    vlc = None


class CacheWorker(QThread):
    """Thread for copying media files to local cache."""

    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, src_path: str, dest_path: str) -> None:
        super().__init__()
        self.src_path = Path(src_path)
        self.dest_path = Path(dest_path)

    def run(self) -> None:
        logger.info(f"Starting cache of {self.src_path} to {self.dest_path}")
        try:
            self.dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Use a simple copy for now, could be improved with progress
            total_size = self.src_path.stat().st_size
            copied = 0
            chunk_size = 1024 * 1024  # 1MB

            with open(self.src_path, "rb") as fsrc:
                with open(self.dest_path, "wb") as fdst:
                    while True:
                        buf = fsrc.read(chunk_size)
                        if not buf:
                            break
                        fdst.write(buf)
                        copied += len(buf)
                        self.progress.emit(int((copied / total_size) * 100))

            self.finished.emit(str(self.dest_path))
            logger.info(f"Caching finished: {self.dest_path}")
        except Exception as e:
            logger.exception("Caching failed")
            self.error.emit(str(e))


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
                "--file-caching=3000",
                "--network-caching=5000",
                "--live-caching=5000",
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

            logger.info(f"Initializing VLC Instance with args: {args}")
            self.instance = vlc.Instance(args)
            self.mediaplayer = self.instance.media_player_new()

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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Timer for auto-hiding fullscreen controls
        self.hide_controls_timer = QTimer(self)
        self.hide_controls_timer.setInterval(3000)  # 3 seconds
        self.hide_controls_timer.setSingleShot(True)
        self.hide_controls_timer.timeout.connect(self._hide_fullscreen_controls)

        self._setup_ui()

        # Timer for updating UI (seek bar, time labels, watched threshold)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_ui)

    def _apply_fullscreen_styles(self) -> None:
        """Applies styling to fullscreen overlay based on config."""
        opacity = int(config.player_overlay_opacity * 255)
        color_scheme = config.player_overlay_color.lower()

        if color_scheme == "white":
            bg_rgba = f"rgba(255, 255, 255, {opacity})"
            text_color = "black"
            border_rgba = "rgba(0, 0, 0, 50)"
        else:
            bg_rgba = f"rgba(0, 0, 0, {opacity})"
            text_color = "white"
            border_rgba = "rgba(255, 255, 255, 50)"

        self.fullscreen_overlay.setStyleSheet(
            f"background-color: {bg_rgba}; border-radius: 0px;"
        )

        btn_style = f"color: {text_color}; background-color: transparent; border: 1px solid {border_rgba};"
        self.fs_pause_button.setStyleSheet(btn_style)
        self.fs_skip_back_button.setStyleSheet(btn_style)
        self.fs_skip_fwd_button.setStyleSheet(btn_style)

        label_style = f"color: {text_color}; font-size: 12px;"
        self.fs_time_label.setStyleSheet(label_style)
        self.fs_vol_label.setStyleSheet(label_style)

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

        # Fullscreen Overlay (minimal controls)
        self.fullscreen_overlay = QFrame(self)
        self.fullscreen_overlay.setStyleSheet("border-radius: 0px;")
        self.fullscreen_overlay.setFixedWidth(650)

        # We'll define the buttons properly here first
        self.fs_pause_button = QPushButton("Pause")
        self.fs_pause_button.setFixedWidth(70)
        self.fs_skip_back_button = QPushButton("<<")
        self.fs_skip_back_button.setFixedWidth(50)
        self.fs_skip_fwd_button = QPushButton(">>")
        self.fs_skip_fwd_button.setFixedWidth(50)
        fs_main_layout = QVBoxLayout(self.fullscreen_overlay)
        fs_main_layout.setContentsMargins(15, 10, 15, 10)
        fs_main_layout.setSpacing(5)

        # Seek Slider Row
        self.fs_seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.fs_seek_slider.setMaximum(1000)
        self.fs_seek_slider.setStyleSheet("height: 20px;")
        self.fs_seek_slider.sliderMoved.connect(self.set_position)
        fs_main_layout.addWidget(self.fs_seek_slider)

        # Controls Row
        fs_controls_layout = QHBoxLayout()

        self.fs_pause_button.clicked.connect(self.play_pause)

        self.fs_skip_back_button.clicked.connect(lambda: self.skip_backward(10))

        self.fs_skip_fwd_button.clicked.connect(lambda: self.skip_forward(10))

        self.fs_time_label = QLabel("00:00 / 00:00")

        self.fs_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.fs_volume_slider.setMaximum(200)
        self.fs_volume_slider.setValue(80)
        self.fs_volume_slider.setFixedWidth(120)
        self.fs_volume_slider.valueChanged.connect(self.set_volume)

        fs_controls_layout.addWidget(self.fs_pause_button)
        fs_controls_layout.addWidget(self.fs_skip_back_button)
        fs_controls_layout.addWidget(self.fs_skip_fwd_button)
        fs_controls_layout.addStretch()
        fs_controls_layout.addWidget(self.fs_time_label)
        fs_controls_layout.addSpacing(15)

        self.fs_vol_label = QLabel("Volume:")
        fs_controls_layout.addWidget(self.fs_vol_label)
        fs_controls_layout.addWidget(self.fs_volume_slider)

        fs_main_layout.addLayout(fs_controls_layout)
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

        # Stats Overlay (for troubleshooting)
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
        controls_layout = QVBoxLayout(self.controls_widget)

        # Seek Bar
        seek_layout = QHBoxLayout()
        self.time_label = QLabel("00:00 / 00:00")
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setMaximum(1000)
        self.seek_slider.sliderMoved.connect(self.set_position)
        seek_layout.addWidget(self.time_label)
        seek_layout.addWidget(self.seek_slider)
        controls_layout.addLayout(seek_layout)

        # Buttons and Menus
        buttons_layout = QHBoxLayout()

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.play_pause)

        self.skip_back_button = QPushButton("<< 10s")
        self.skip_back_button.clicked.connect(lambda: self.skip_backward(10))

        self.skip_fwd_button = QPushButton("10s >>")
        self.skip_fwd_button.clicked.connect(lambda: self.skip_forward(10))

        self.rate_button = QPushButton("1.0x")
        self.rate_button.setFixedWidth(50)
        self.rate_button.clicked.connect(self.toggle_fast_forward)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self._playback_finished_signal.connect(self._handle_playback_finished)

        self.audio_combo = QComboBox()
        self.audio_combo.setPlaceholderText("Audio Track")
        self.audio_combo.currentIndexChanged.connect(self.change_audio_track)

        self.subtitle_combo = QComboBox()
        self.subtitle_combo.setPlaceholderText("Subtitles")
        self.subtitle_combo.currentIndexChanged.connect(self.change_subtitle_track)

        volume_layout = QHBoxLayout()
        self.mute_button = QPushButton("Mute")
        self.mute_button.setFixedWidth(60)
        self.mute_button.clicked.connect(self.toggle_mute)
        volume_layout.addWidget(self.mute_button)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setMaximum(200)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.set_volume)
        volume_layout.addWidget(self.volume_slider)

        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.on_back_clicked)

        self.fullscreen_button = QPushButton("Fullscreen")
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)

        buttons_layout.addWidget(self.play_button)
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addWidget(self.skip_back_button)
        buttons_layout.addWidget(self.skip_fwd_button)
        buttons_layout.addWidget(self.rate_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(QLabel("Audio:"))
        buttons_layout.addWidget(self.audio_combo)
        buttons_layout.addWidget(QLabel("Subs:"))
        buttons_layout.addWidget(self.subtitle_combo)
        buttons_layout.addSpacing(20)
        buttons_layout.addLayout(volume_layout)
        buttons_layout.addSpacing(20)
        buttons_layout.addWidget(self.fullscreen_button)
        buttons_layout.addWidget(self.back_button)

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
        fs_size = QSize(650, 90)
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

        # Initial volume
        self.mediaplayer.audio_set_volume(self.volume_slider.value())

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
        # Audio tracks
        self.audio_combo.blockSignals(True)
        self.audio_combo.clear()
        audio_tracks = self.mediaplayer.audio_get_track_description()
        for track_id, track_name in audio_tracks:
            self.audio_combo.addItem(
                track_name.decode() if isinstance(track_name, bytes) else track_name,
                track_id,
            )
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
            self.mediaplayer.pause()
            self.play_button.setText("Play")
            self.fs_pause_button.setText("Play")
        else:
            self.mediaplayer.play()
            self.play_button.setText("Pause")
            self.fs_pause_button.setText("Pause")

    def stop(self) -> None:
        logger.info("Stopping playback")
        if self.window().isFullScreen():
            self.toggle_fullscreen()
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
        self.seek_slider.setValue(0)
        self.time_label.setText("00:00 / 00:00")
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
        if self.mediaplayer:
            self.mediaplayer.audio_set_volume(volume)

        # Sync sliders
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(volume)
        self.volume_slider.blockSignals(False)

        self.fs_volume_slider.blockSignals(True)
        self.fs_volume_slider.setValue(volume)
        self.fs_volume_slider.blockSignals(False)

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
        self._show_osd(f"Playback Speed: {text}")

    def _show_osd(self, text: str) -> None:
        self.osd_label.setText(text)
        self._reposition_overlays()
        self.osd_label.show()
        self.osd_label.raise_()
        self.osd_timer.start()

    def set_position(self, position: int) -> None:
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
