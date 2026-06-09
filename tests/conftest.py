import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

import pytest

# Force offscreen rendering so individual tests run seamlessly in GUI-less IDE test explorers
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Mock VLC globally for tests to prevent spawning real VLC processes and consuming high CPU/memory
import sys
from unittest.mock import MagicMock


class MockVLC:
    __name__ = "vlc"

    class EventType:
        MediaPlayerEndReached = 265

    class MediaStats:
        input_bitrate = 0.0
        demux_bitrate = 0.0
        decoded_video = 0
        displayed_pictures = 0
        lost_pictures = 0
        decoded_audio = 0
        lost_abuffers = 0

    def Instance(self, *args, **kwargs):
        mock_instance = MagicMock()
        mock_media_player = MagicMock()
        mock_media_player.get_length.return_value = 0
        mock_media_player.get_time.return_value = 0
        mock_media_player.video_get_size.return_value = (0, 0)
        mock_media_player.get_fps.return_value = 0.0
        mock_media_player.audio_output_device_enum.return_value = None
        mock_instance.media_player_new.return_value = mock_media_player
        return mock_instance

    def libvlc_audio_output_device_list_release(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        if name == "MediaStats":
            return MockVLC.MediaStats
        return MagicMock()


sys.modules["vlc"] = MockVLC()


_TEMPLATE_DB_PATH = None


def get_template_db(tmp_path_factory) -> Path:
    global _TEMPLATE_DB_PATH
    if _TEMPLATE_DB_PATH is None:
        temp_dir = tmp_path_factory.getbasetemp()
        template_db = temp_dir / "template_library.db"

        import lan_streamer.db

        orig_db_file = getattr(lan_streamer.db, "DB_FILE", None)
        lan_streamer.db.DB_FILE = template_db

        if hasattr(lan_streamer.db, "_engine") and lan_streamer.db._engine is not None:
            lan_streamer.db._engine.dispose()
        lan_streamer.db._engine = None
        lan_streamer.db._SessionLocal = None
        lan_streamer.db._db_initialized = False

        # Initialize schema once
        lan_streamer.db.init_db()

        if lan_streamer.db._engine is not None:
            lan_streamer.db._engine.dispose()
        lan_streamer.db._engine = None
        lan_streamer.db._SessionLocal = None
        lan_streamer.db._db_initialized = False

        if orig_db_file is not None:
            lan_streamer.db.DB_FILE = orig_db_file

        _TEMPLATE_DB_PATH = template_db

    return _TEMPLATE_DB_PATH


@pytest.fixture(autouse=True)
def protect_user_dirs(tmp_path, tmp_path_factory) -> None:
    """
    Ensure no test can ever overwrite the user's actual config or DB.
    We patch all the paths to point to tmp_path.
    """
    from lan_streamer.system.config import config
    import lan_streamer.db
    import lan_streamer.providers.tmdb
    from lan_streamer.providers.jellyfin import jellyfin_client
    from lan_streamer.providers.tmdb import tmdb_client

    # Save original state
    config_dict = dict(config.__dict__)
    jellyfin_dict = dict(jellyfin_client.__dict__)
    tmdb_dict = dict(tmdb_client.__dict__)

    config_file = tmp_path / "config.json"
    db_file = tmp_path / "library.db"
    cache_dir = tmp_path / "cache" / "images"

    # Properly dispose of the existing engine to avoid ResourceWarnings
    if hasattr(lan_streamer.db, "_engine") and lan_streamer.db._engine is not None:
        lan_streamer.db._engine.dispose()

    # Reset lazy database objects
    lan_streamer.db._engine = None
    lan_streamer.db._SessionLocal = None
    lan_streamer.db._db_initialized = False

    # Pre-create parent directory and copy the pre-migrated template database
    db_file.parent.mkdir(parents=True, exist_ok=True)
    template_db = get_template_db(tmp_path_factory)
    shutil.copy2(template_db, db_file)

    with (
        patch("lan_streamer.system.config.CONFIG_FILE", config_file),
        patch("lan_streamer.system.backup.CONFIG_FILE", config_file),
        patch("lan_streamer.system.CONFIG_FILE", config_file),
        patch("lan_streamer.db.DB_FILE", db_file),
        patch("lan_streamer.providers.tmdb.CACHE_DIR", cache_dir),
    ):
        # Already initialized via copy
        lan_streamer.db._db_initialized = True

        # Reload config instance so it points to the new path
        config.libraries = {}
        config.jellyfin_url = ""
        config.jellyfin_api_key = ""
        config.tmdb_api_key = ""
        config.database_path = str(db_file)
        config.log_directory = str(tmp_path / "logs")
        config.divide_logs_by_service = False
        config.sort_mode = "Alphabetical"
        config.sort_descending = False
        config.log_level = "INFO"

        yield

        # Dispose engine after test too
        if lan_streamer.db._engine is not None:
            lan_streamer.db._engine.dispose()

    # Restore original state
    config.__dict__.clear()
    config.__dict__.update(config_dict)
    jellyfin_client.__dict__.clear()
    jellyfin_client.__dict__.update(jellyfin_dict)
    tmdb_client.__dict__.clear()
    tmdb_client.__dict__.update(tmdb_dict)

    # Force garbage collection to reclaim PySide6/Qt and DB objects
    import gc

    gc.collect()


@pytest.fixture(scope="session")
def generated_video_asset(tmp_path_factory) -> str:
    """
    Dynamically generates a realistic 1x1 multi-language subtitle MKV test asset via ffmpeg.
    Returns the absolute file path to the asset. Skips tests requiring it if ffmpeg is not available.
    """
    asset_dir = tmp_path_factory.mktemp("video_assets")
    output_mkv = asset_dir / "test_video.mkv"

    subs = [
        ("spa", "Spanish", "Pista de subtítulos en español"),
        ("fre", "French", "Piste de sous-titres en français"),
        ("ger", "German", "Deutsche Untertitelspur"),
        ("eng", "English (Forced)", "Forced English Subtitle Track"),
        ("eng", "English [Signs]", "English Signs Subtitle Track"),
        ("eng", "English (Songs)", "English Songs Subtitle Track"),
        ("eng", "English", "Main Standard English Subtitle Track"),
    ]

    srt_inputs = []
    maps = ["-map", "0:v"]
    metadata_args = []

    for idx, (lang, title, text) in enumerate(subs):
        srt_file = asset_dir / f"sub{idx}.srt"
        srt_file.write_text(
            f"1\n00:00:00,000 --> 00:00:08,000\n{text}\n", encoding="utf-8"
        )
        srt_inputs.extend(["-i", str(srt_file)])
        maps.extend(["-map", f"{idx + 1}:s"])
        metadata_args.extend(
            [
                f"-metadata:s:s:{idx}",
                f"language={lang}",
                f"-metadata:s:s:{idx}",
                f"title={title}",
            ]
        )

    ffmpeg_bin = "/usr/bin/ffmpeg" if os.path.exists("/usr/bin/ffmpeg") else "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=1x1:d=10",
        *srt_inputs,
        *maps,
        *metadata_args,
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        "-c:s",
        "srt",
        str(output_mkv),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except Exception as e:
        stderr_output = getattr(e, "stderr", "")
        stdout_output = getattr(e, "stdout", "")
        msg = (
            f"ffmpeg is not available or failed to run to generate video test asset.\n"
            f"Error: {e}\n"
            f"stdout: {stdout_output}\n"
            f"stderr: {stderr_output}"
        )
        if os.environ.get("GITHUB_ACTIONS"):
            raise RuntimeError(msg) from e
        pytest.skip(msg)

    return str(output_mkv)


def pytest_xdist_auto_num_workers(config) -> int:
    """Dynamically determine the number of workers when -n auto is specified to use half of the available CPU cores."""
    import os

    num_cores = os.cpu_count() or 1
    return max(1, num_cores // 2)
