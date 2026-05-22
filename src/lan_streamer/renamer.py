import re
import logging
from pathlib import Path
from typing import Dict, List, Any
from .scanner import SUBTITLE_EXTENSIONS

logger = logging.getLogger(__name__)


def sanitize_filename(filename: str) -> str:
    """
    Removes illegal characters from a filename.
    """
    # Remove characters that are illegal on Windows/Linux/macOS
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    # Also remove control characters
    sanitized = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", sanitized)
    # Strip leading/trailing whitespace and periods (trailing periods are bad on Windows)
    sanitized = sanitized.strip().strip(".")
    return sanitized


def is_safe_filename(filename: str) -> tuple[bool, str | None]:
    """
    Checks if a filename is safe for the filesystem.
    Returns (is_safe, error_message).
    """
    if not filename:
        return False, "Filename cannot be empty"

    # Check for reserved names (Windows specifically, but good practice)
    reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
    stem = Path(filename).stem.upper()
    if stem in reserved_names:
        return False, f"Filename '{stem}' is a reserved system name"

    # Check for length (standard 255 chars for most filesystems)
    if len(filename.encode("utf-8")) > 255:
        return False, "Filename is too long (max 255 bytes)"

    # Check for invalid characters we might have missed
    if any(c in '\\/*?:"<>|' for c in filename):
        return False, "Filename contains illegal characters"

    return True, None


def format_name(template: str, data: Dict[str, Any]) -> str:
    """
    Formats a name using a template and a data dictionary.
    Supports tokens like {SeriesTitle}, {SeasonNumber}, {EpisodeNumber}, {EpisodeTitle}.
    Supports Python string formatting syntax (e.g. {SeasonNumber:02}).
    """
    # Map friendly names to the keys expected in the template
    context = {
        "SeriesTitle": data.get("SeriesTitle", ""),
        "SeasonNumber": data.get("SeasonNumber", 0),
        "EpisodeNumber": data.get("EpisodeNumber", 0),
        "EpisodeTitle": data.get("EpisodeTitle", ""),
        "OriginalTitle": data.get("OriginalTitle", ""),
    }

    try:
        # We use str.format() which natively supports {Token:format}
        # But we need to be careful if the user provides extra braces or invalid tokens
        # We'll sanitize the SeriesTitle and EpisodeTitle within the context
        context["SeriesTitle"] = sanitize_filename(str(context["SeriesTitle"]))
        context["EpisodeTitle"] = sanitize_filename(str(context["EpisodeTitle"]))
        context["OriginalTitle"] = sanitize_filename(str(context["OriginalTitle"]))

        return template.format(**context)
    except KeyError as e:
        logger.warning(f"Invalid token in template: {e}")
        return template  # Return template as is if it fails
    except Exception:
        logger.exception(f"Error formatting name with template '{template}'")
        return template


def get_rename_preview(
    series_data: Dict[str, Any], file_template: str
) -> List[Dict[str, Any]]:
    """
    Generates a list of preview items for renaming.
    Each item contains old_path, new_name, and new_path.
    """
    previews = []

    logger.info(f"Generating rename preview for template: '{file_template}'")

    # Get series level info
    series_title = series_data.get("metadata", {}).get("tmdb_name") or series_data.get(
        "metadata", {}
    ).get("name", "Unknown Series")

    # Iterate through all seasons and episodes
    for season_name, season_data in series_data.get("seasons", {}).items():
        # Try to extract season number from name (e.g. "Season 1" -> 1)
        season_num = 0
        match = re.search(r"\d+", season_name)
        if match:
            season_num = int(match.group())

        for episode in season_data.get("episodes", []):
            old_path = Path(episode["path"])

            data = {
                "SeriesTitle": series_title,
                "SeasonNumber": season_num,
                "EpisodeNumber": episode.get("tmdb_number") or 0,
                "EpisodeTitle": episode.get("tmdb_name")
                or episode.get("name")
                or "Unknown Episode",
                "OriginalTitle": old_path.stem,
            }

            # Generate new name
            new_filename = format_name(file_template, data)
            extension = old_path.suffix

            # Ensure extension is preserved and only added once
            if not new_filename.lower().endswith(extension.lower()):
                new_filename += extension

            new_path = old_path.parent / new_filename
            new_stem = Path(new_filename).stem

            safe, error = is_safe_filename(new_filename)

            previews.append(
                {
                    "old_name": old_path.name,
                    "old_path": str(old_path),
                    "new_name": new_filename,
                    "new_path": str(new_path),
                    "series": series_title,
                    "season": season_name,
                    "episode": episode.get("name"),
                    "safe": safe,
                    "error": error,
                    "is_subtitle": False,
                }
            )

            # Check for subtitle files with same stem
            if old_path.parent.exists():
                old_stem = old_path.stem
                for sibling in old_path.parent.iterdir():
                    if (
                        sibling.is_file()
                        and sibling.stem.startswith(old_stem)
                        and sibling != old_path
                    ):
                        # Ensure it's a subtitle file or has a subtitle extension
                        if sibling.suffix.lower() in SUBTITLE_EXTENSIONS or any(
                            ext in sibling.name.lower() for ext in SUBTITLE_EXTENSIONS
                        ):
                            # Calculate new name: new_stem + original suffix(es)
                            # e.g. old_stem="ep1", sibling="ep1.en.srt", new_stem="Show S01E01" -> "Show S01E01.en.srt"
                            extra_suffix = sibling.name[len(old_stem) :]
                            sibling_new_name = new_stem + extra_suffix
                            sibling_new_path = sibling.parent / sibling_new_name

                            s_safe, s_error = is_safe_filename(sibling_new_name)

                            previews.append(
                                {
                                    "old_name": sibling.name,
                                    "old_path": str(sibling),
                                    "new_name": sibling_new_name,
                                    "new_path": str(sibling_new_path),
                                    "series": series_title,
                                    "season": season_name,
                                    "episode": f"{episode.get('name')} (Subtitle)",
                                    "safe": s_safe,
                                    "error": s_error,
                                    "is_subtitle": True,
                                }
                            )

    return previews


def perform_rename(
    previews: List[Dict[str, Any]], db_callback: Any = None
) -> List[Dict[str, Any]]:
    """
    Executes the renames.
    db_callback is an optional function to update the database for each successful rename.
    """
    results = []
    logger.info(f"Starting batch rename for {len(previews)} items")
    for item in previews:
        old_path = Path(item["old_path"])
        new_path = Path(item["new_path"])
        logger.debug(f"Attempting to rename '{old_path}' -> '{new_path}'")

        result = {
            "old_path": item["old_path"],
            "new_path": item["new_path"],
            "success": False,
            "error": None,
        }

        if not item.get("safe", True):
            result["error"] = item.get("error", "Unsafe filename")
            results.append(result)
            continue

        if old_path == new_path:
            result["success"] = True
            result["error"] = "No change"
            results.append(result)
            continue

        if not old_path.exists():
            result["error"] = "Source file missing"
            results.append(result)
            continue

        if new_path.exists():
            result["error"] = "Destination already exists"
            results.append(result)
            continue

        try:
            # Final safety check before rename
            safe, err = is_safe_filename(new_path.name)
            if not safe:
                result["error"] = err
                results.append(result)
                continue

            # Create parent directories if they don't exist
            new_path.parent.mkdir(parents=True, exist_ok=True)

            # Perform rename
            old_path.rename(new_path)

            # Update database if callback provided (only for video files, not subtitles)
            if db_callback and not item.get("is_subtitle"):
                try:
                    db_callback(str(old_path), str(new_path))
                except Exception:
                    logger.exception(f"Failed to update DB for {old_path}")
                    # We still count the file rename as a success

            result["success"] = True
            results.append(result)
            logger.info(f"Renamed: {old_path} -> {new_path}")

        except Exception as e:
            result["error"] = str(e)
            results.append(result)
            logger.exception(f"Rename failed: {old_path} -> {new_path}")

    return results
