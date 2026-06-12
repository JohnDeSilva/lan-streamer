try:
    import vlc
except ImportError, OSError:
    vlc = None

from lan_streamer.playback.widget import VideoPlayerWidget
from lan_streamer.playback.cache import CacheWorker
from lan_streamer.playback.player import play_video
from lan_streamer.playback.wakelock import WakeLock
