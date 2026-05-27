import os
import pytest
import subprocess
from unittest.mock import patch

# Force offscreen rendering so individual tests run seamlessly in GUI-less IDE test explorers
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(autouse=True)
def protect_user_dirs(tmp_path) -> None:
    """
    Ensure no test can ever overwrite the user's actual config or DB.
    We patch all the paths to point to tmp_path.
    """
    import lan_streamer.config
    import lan_streamer.db
    import lan_streamer.tmdb

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

    with (
        patch("lan_streamer.config.CONFIG_FILE", config_file),
        patch("lan_streamer.db.DB_FILE", db_file),
        patch("lan_streamer.tmdb.CACHE_DIR", cache_dir),
    ):
        # Initialize schema for tests
        lan_streamer.db.init_db()

        # Reload config instance so it points to the new path
        lan_streamer.config.config.libraries = {}
        lan_streamer.config.config.jellyfin_url = ""
        lan_streamer.config.config.jellyfin_api_key = ""
        lan_streamer.config.config.tmdb_api_key = ""
        lan_streamer.config.config.database_path = str(db_file)
        lan_streamer.config.config.log_directory = str(tmp_path / "logs")
        lan_streamer.config.config.divide_logs_by_service = False
        lan_streamer.config.config.sort_mode = "Alphabetical"
        lan_streamer.config.config.sort_descending = False

        yield

        # Dispose engine after test too
        if lan_streamer.db._engine is not None:
            lan_streamer.db._engine.dispose()


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
