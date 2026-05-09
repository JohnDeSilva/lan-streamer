import os
import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QLabel,
    QFrame,
    QComboBox,
    QSizePolicy,
    QProgressBar,
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, Slot

try:
    import vlc
except ImportError:
    vlc = None
import sys

from .config import config
from . import db

logger = logging.getLogger(__name__)


class CacheWorker(QThread):
    """Thread for copying media files to local cache."""

    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, src_path, dest_path):
        super().__init__()
        self.src_path = Path(src_path)
        self.dest_path = Path(dest_path)

    def run(self):
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
        except Exception as e:
            self.error.emit(str(e))


class VideoPlayerWidget(QWidget):
    """Embedded VLC media player widget with caching and advanced controls."""

    back_requested = Signal()
    watched_marked = Signal(str)  # path

    def __init__(self, parent=None):
        super().__init__(parent)
        if vlc:
            args = [
                "--quiet",
                "--no-video-title-show",
                "--no-xlib",
                "--ignore-config",
            ]
            if sys.platform == "linux":
                # Disable problematic hardware acceleration if it fails
                args.append("--avcodec-hw=none")
            self.instance = vlc.Instance(args)
            self.mediaplayer = self.instance.media_player_new()
        else:
            self.instance = None
            self.mediaplayer = None
        self.current_media_path = None
        self.cached_file_path = None
        self.is_watched_marked = False

        self._setup_ui()

        # Timer for updating UI (seek bar, time labels, watched threshold)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_ui)

    def _setup_ui(self):
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
        self.main_layout.addWidget(self.video_frame)

        # Progress Overlay (for caching)
        self.progress_overlay = QWidget(self.video_frame)
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

        # Controls Layout
        controls_layout = QVBoxLayout()

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

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)

        self.audio_combo = QComboBox()
        self.audio_combo.setPlaceholderText("Audio Track")
        self.audio_combo.currentIndexChanged.connect(self.change_audio_track)

        self.subtitle_combo = QComboBox()
        self.subtitle_combo.setPlaceholderText("Subtitles")
        self.subtitle_combo.currentIndexChanged.connect(self.change_subtitle_track)

        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("Vol:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.set_volume)
        volume_layout.addWidget(self.volume_slider)

        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.on_back_clicked)

        buttons_layout.addWidget(self.play_button)
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(QLabel("Audio:"))
        buttons_layout.addWidget(self.audio_combo)
        buttons_layout.addWidget(QLabel("Subs:"))
        buttons_layout.addWidget(self.subtitle_combo)
        buttons_layout.addSpacing(20)
        buttons_layout.addLayout(volume_layout)
        buttons_layout.addSpacing(20)
        buttons_layout.addWidget(self.back_button)

        controls_layout.addLayout(buttons_layout)
        self.main_layout.addLayout(controls_layout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.progress_overlay.resize(self.video_frame.size())

    def play_video(self, file_path):
        """Starts the playback process (caching if enabled)."""
        self.stop()
        self.current_media_path = file_path
        self.is_watched_marked = False

        if config.enable_caching:
            self._start_caching(file_path)
        else:
            self._load_and_play(file_path)

    def _start_caching(self, file_path):
        self.progress_overlay.show()
        self.progress_bar.setValue(0)

        # Create destination path in cache directory
        cache_dir = Path(config.cache_directory)
        cache_dir.mkdir(parents=True, exist_ok=True)

        dest_path = cache_dir / Path(file_path).name
        self.cached_file_path = str(dest_path)

        self.cache_worker = CacheWorker(file_path, dest_path)
        self.cache_worker.progress.connect(self.progress_bar.setValue)
        self.cache_worker.finished.connect(self._on_caching_finished)
        self.cache_worker.error.connect(self._on_caching_error)
        self.cache_worker.start()

    @Slot(str)
    def _on_caching_finished(self, cached_path):
        self.progress_overlay.hide()
        self._load_and_play(cached_path)

    @Slot(str)
    def _on_caching_error(self, error_msg):
        self.progress_overlay.hide()
        logger.error(f"Caching error: {error_msg}")
        # Fallback to direct playback
        self._load_and_play(self.current_media_path)

    def _load_and_play(self, file_path):
        if not vlc or not self.instance:
            logger.error("VLC not initialized, cannot play video.")
            return

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
        self.timer.start()
        self.play_button.setText("Pause")

        # Initial volume
        self.mediaplayer.audio_set_volume(self.volume_slider.value())

        # Wait a bit for tracks to be available
        QTimer.singleShot(1000, self._refresh_tracks)

    def _refresh_tracks(self):
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
        for track_id, track_name in subtitle_tracks:
            self.subtitle_combo.addItem(
                track_name.decode() if isinstance(track_name, bytes) else track_name,
                track_id,
            )
        current_sub = self.mediaplayer.video_get_spu()
        idx = self.subtitle_combo.findData(current_sub)
        if idx != -1:
            self.subtitle_combo.setCurrentIndex(idx)
        self.subtitle_combo.blockSignals(False)

    def change_audio_track(self, index):
        track_id = self.audio_combo.itemData(index)
        if track_id is not None:
            self.mediaplayer.audio_set_track(track_id)

    def change_subtitle_track(self, index):
        track_id = self.subtitle_combo.itemData(index)
        if track_id is not None:
            self.mediaplayer.video_set_spu(track_id)

    def play_pause(self):
        if self.mediaplayer.is_playing():
            self.mediaplayer.pause()
            self.play_button.setText("Play")
        else:
            self.mediaplayer.play()
            self.play_button.setText("Pause")

    def stop(self):
        self.mediaplayer.stop()
        self.timer.stop()
        self.play_button.setText("Play")
        self.seek_slider.setValue(0)
        self.time_label.setText("00:00 / 00:00")
        self._cleanup_cache()

    def set_volume(self, volume):
        self.mediaplayer.audio_set_volume(volume)

    def set_position(self, position):
        self.mediaplayer.set_position(position / 1000.0)

    def update_ui(self):
        if not self.mediaplayer.get_media():
            return

        # Update seek bar
        pos = self.mediaplayer.get_position()
        self.seek_slider.setValue(int(pos * 1000))

        # Update time label
        curr_time = self.mediaplayer.get_time() // 1000
        duration = self.mediaplayer.get_length() // 1000

        if duration > 0:
            self.time_label.setText(
                f"{self._format_time(curr_time)} / {self._format_time(duration)}"
            )

            # Check 90% threshold
            if (
                not self.is_watched_marked
                and (curr_time / duration) >= config.watched_threshold
            ):
                self._mark_as_watched()

    def _format_time(self, seconds):
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins:02d}:{secs:02d}"

    def _mark_as_watched(self):
        if self.current_media_path:
            logger.info(
                f"Marking as watched (90% threshold reached): {self.current_media_path}"
            )
            db.update_episode_watched_status(self.current_media_path, True)
            self.is_watched_marked = True
            self.watched_marked.emit(self.current_media_path)

    def _cleanup_cache(self):
        if self.cached_file_path and os.path.exists(self.cached_file_path):
            try:
                os.remove(self.cached_file_path)
                logger.info(f"Cleaned up cached file: {self.cached_file_path}")
                self.cached_file_path = None
            except Exception as e:
                logger.error(f"Error cleaning up cache: {e}")

    def on_back_clicked(self):
        self.stop()
        self.back_requested.emit()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
