import os
import sys
import logging

if __name__ == "__main__" and len(sys.argv) > 1:
    if sys.argv[1] in ("--version", "-v", "-V"):
        from lan_streamer import __version__

        print(f"lan-streamer {__version__}")
        sys.exit(0)
    elif any(argument in sys.argv for argument in ("--help", "-h")):
        print("Usage: lan-streamer [options]")
        print()
        print("Options:")
        print("  -c, --config PATH      Path to custom JSON configuration file.")
        print("  -v, -V, --version      Show version information and exit.")
        print("  -h, --help             Show this help message and exit.")
        sys.exit(0)


def setup_vlc_environment() -> None:
    import ctypes
    import platform

    logger = logging.getLogger("lan_streamer.entrypoint")
    try:
        from lan_streamer.system.config import config

        log_level_string = config.log_level.upper()
    except Exception:
        log_level_string = "INFO"

    log_level = getattr(logging, log_level_string, logging.INFO)
    logger.setLevel(log_level)

    console_handler = logging.StreamHandler(sys.stdout)
    log_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)
    logger.propagate = False

    logger.info(
        "OS Platform: %s, OS Release: %s, Architecture: %s, Frozen Executable: %s",
        sys.platform,
        platform.release(),
        platform.machine(),
        getattr(sys, "frozen", False),
    )

    try:
        # macOS PyInstaller compatibility for system VLC
        if sys.platform == "darwin" and getattr(sys, "frozen", False):
            vlc_library_path = os.environ.get("PYTHON_VLC_LIB_PATH")
            if vlc_library_path:
                logger.info("PYTHON_VLC_LIB_PATH is set to: %s", vlc_library_path)
                if "libvlc.dylib" in vlc_library_path:
                    # Pre-load libvlccore so libvlc can find its dependencies when frozen
                    vlc_core_path = vlc_library_path.replace(
                        "libvlc.dylib", "libvlccore.dylib"
                    )
                    logger.info("Pre-loading libvlccore from: %s", vlc_core_path)
                    try:
                        ctypes.CDLL(vlc_core_path)
                        logger.info("Successfully pre-loaded libvlccore.")
                    except Exception as exception:
                        logger.error(
                            "Failed to pre-load libvlccore from %s: %s",
                            vlc_core_path,
                            exception,
                        )
                else:
                    logger.warning(
                        "PYTHON_VLC_LIB_PATH does not contain libvlc.dylib; skipping libvlccore pre-load."
                    )
            else:
                logger.info("PYTHON_VLC_LIB_PATH environment variable is not set.")

            # Also set VLC_PLUGIN_PATH if not set, as plugins are needed for actual playback
            if "VLC_PLUGIN_PATH" in os.environ:
                logger.info(
                    "VLC_PLUGIN_PATH is already set to: %s",
                    os.environ["VLC_PLUGIN_PATH"],
                )
            else:
                logger.info("VLC_PLUGIN_PATH environment variable is not set.")
                common_plugin_paths = [
                    "/Applications/VLC.app/Contents/MacOS/plugins",
                    os.path.expanduser("~/Applications/VLC.app/Contents/MacOS/plugins"),
                    "/opt/homebrew/lib/vlc/plugins",
                    "/usr/local/lib/vlc/plugins",
                    "/opt/local/lib/vlc/plugins",
                ]
                logger.info("Checking common plugin paths: %s", common_plugin_paths)
                chosen_path = None
                for plugin_path in common_plugin_paths:
                    logger.info("Checking plugin path: %s", plugin_path)
                    if os.path.isdir(plugin_path):
                        chosen_path = plugin_path
                        logger.info("Found valid plugin path: %s", chosen_path)
                        break
                if chosen_path:
                    os.environ["VLC_PLUGIN_PATH"] = chosen_path
                    logger.info("VLC_PLUGIN_PATH has been set to: %s", chosen_path)
                else:
                    fallback_path = "/Applications/VLC.app/Contents/MacOS/plugins"
                    os.environ["VLC_PLUGIN_PATH"] = fallback_path
                    logger.info(
                        "None of the common plugin paths exist. Falling back to default path: %s",
                        fallback_path,
                    )

        # Linux/Windows PyInstaller compatibility for system VLC plugins
        elif getattr(sys, "frozen", False):
            if "VLC_PLUGIN_PATH" in os.environ:
                logger.info(
                    "VLC_PLUGIN_PATH is already set to: %s",
                    os.environ["VLC_PLUGIN_PATH"],
                )
            else:
                logger.info("VLC_PLUGIN_PATH environment variable is not set.")
                if sys.platform == "linux":
                    common_plugin_paths = [
                        "/usr/lib/x86_64-linux-gnu/vlc/plugins",
                        "/usr/lib/aarch64-linux-gnu/vlc/plugins",
                        "/usr/lib64/vlc/plugins",
                        "/usr/lib/vlc/plugins",
                    ]
                    logger.info(
                        "Checking common plugin paths for Linux: %s",
                        common_plugin_paths,
                    )
                    chosen_path = None
                    for plugin_path in common_plugin_paths:
                        logger.info("Checking plugin path: %s", plugin_path)
                        if os.path.isdir(plugin_path):
                            chosen_path = plugin_path
                            logger.info("Found valid plugin path: %s", chosen_path)
                            break
                    if chosen_path:
                        os.environ["VLC_PLUGIN_PATH"] = chosen_path
                        logger.info("VLC_PLUGIN_PATH has been set to: %s", chosen_path)
                    else:
                        logger.warning(
                            "None of the common plugin paths were found. VLC_PLUGIN_PATH was not set."
                        )
                elif sys.platform == "win32":
                    common_plugin_paths = [
                        r"C:\Program Files\VideoLAN\VLC\plugins",
                        r"C:\Program Files (x86)\VideoLAN\VLC\plugins",
                    ]
                    logger.info(
                        "Checking common plugin paths for Windows: %s",
                        common_plugin_paths,
                    )
                    chosen_path = None
                    for plugin_path in common_plugin_paths:
                        logger.info("Checking plugin path: %s", plugin_path)
                        if os.path.isdir(plugin_path):
                            chosen_path = plugin_path
                            logger.info("Found valid plugin path: %s", chosen_path)
                            break
                    if chosen_path:
                        os.environ["VLC_PLUGIN_PATH"] = chosen_path
                        logger.info("VLC_PLUGIN_PATH has been set to: %s", chosen_path)
                    else:
                        logger.warning(
                            "None of the common plugin paths were found. VLC_PLUGIN_PATH was not set."
                        )
        else:
            logger.info(
                "Application is not running in a frozen executable context; skipping automatic environment configuration checks."
            )
            if "VLC_PLUGIN_PATH" in os.environ:
                logger.info(
                    "VLC_PLUGIN_PATH is currently set to: %s",
                    os.environ["VLC_PLUGIN_PATH"],
                )
            else:
                logger.info("VLC_PLUGIN_PATH is not set in environment.")

    finally:
        logger.removeHandler(console_handler)
        logger.propagate = True


setup_vlc_environment()

from lan_streamer.main import run_main  # noqa: E402

if __name__ == "__main__":
    run_main()
