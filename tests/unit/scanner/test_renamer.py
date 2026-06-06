from lan_streamer.scanner.renamer import (
    format_name,
    get_rename_preview,
    sanitize_filename,
    perform_rename,
    is_safe_filename,
)


def test_sanitize_filename() -> None:
    assert sanitize_filename("Show: Special? Title*") == "Show Special Title"
    assert sanitize_filename("File/Path\\Illegal") == "FilePathIllegal"
    assert sanitize_filename("  Leading Trailing  ") == "Leading Trailing"
    assert sanitize_filename("") == ""
    assert sanitize_filename("   ") == ""
    assert sanitize_filename(':*?"<>|') == ""
    assert (
        sanitize_filename("Filename with trailing dots...")
        == "Filename with trailing dots"
    )
    assert sanitize_filename("Control\x00Chars") == "ControlChars"


def test_is_safe_filename() -> None:
    # Safe names
    assert is_safe_filename("Simple Name.mkv")[0] is True
    assert is_safe_filename("Show - S01E01.mp4")[0] is True

    # Empty
    assert is_safe_filename("")[0] is False

    # Reserved names
    assert is_safe_filename("CON.mkv")[0] is False
    assert is_safe_filename("aux.mp4")[0] is False
    assert is_safe_filename("LPT1")[0] is False

    # Length
    long_name = "a" * 256
    assert is_safe_filename(long_name)[0] is False

    # Illegal chars
    assert is_safe_filename("File/Name.mkv")[0] is False
    assert is_safe_filename("File?Name.mkv")[0] is False


def test_format_name() -> None:
    data = {
        "SeriesTitle": "The Great Show",
        "SeasonNumber": 1,
        "EpisodeNumber": 5,
        "EpisodeTitle": "The Beginning",
        "OriginalTitle": "show.s01e05.hdtv",
    }

    # Test standard template
    template = "{SeriesTitle} - S{SeasonNumber:02}E{EpisodeNumber:02} - {EpisodeTitle}"
    assert format_name(template, data) == "The Great Show - S01E05 - The Beginning"

    # Test simple tokens
    template = "{SeriesTitle} S{SeasonNumber}E{EpisodeNumber}"
    assert format_name(template, data) == "The Great Show S1E5"

    # Test original title
    template = "{OriginalTitle} [Fixed]"
    assert format_name(template, data) == "show.s01e05.hdtv [Fixed]"


def test_get_rename_preview() -> None:
    series_data = {
        "metadata": {"tmdb_name": "Breaking Bad"},
        "seasons": {
            "Season 1": {
                "episodes": [
                    {
                        "name": "Pilot",
                        "path": "/data/Breaking Bad/Season 1/pilot.mkv",
                        "tmdb_number": 1,
                        "tmdb_name": "Pilot",
                    }
                ]
            }
        },
    }

    template = "{SeriesTitle} - S{SeasonNumber:02}E{EpisodeNumber:02}"
    previews = get_rename_preview(series_data, template)

    assert len(previews) == 1
    assert previews[0]["old_name"] == "pilot.mkv"
    assert previews[0]["new_name"] == "Breaking Bad - S01E01.mkv"
    assert previews[0]["new_path"].endswith("Breaking Bad - S01E01.mkv")


def test_perform_rename(tmp_path) -> None:
    # Setup mock file system
    video_file = tmp_path / "old.mkv"
    video_file.touch()

    previews = [
        {
            "old_path": str(video_file),
            "new_name": "new.mkv",
            "new_path": str(tmp_path / "new.mkv"),
        }
    ]

    # Test callback
    updated_paths = []

    def db_callback(old, new) -> None:
        updated_paths.append((old, new))

    results = perform_rename(previews, db_callback=db_callback)

    assert results[0]["success"]
    assert not video_file.exists()
    assert (tmp_path / "new.mkv").exists()
    assert len(updated_paths) == 1
    assert updated_paths[0] == (str(video_file), str(tmp_path / "new.mkv"))


def test_perform_rename_errors(tmp_path) -> None:
    # Destination already exists
    old = tmp_path / "old.mkv"
    old.touch()
    dest = tmp_path / "dest.mkv"
    dest.touch()

    previews = [{"old_path": str(old), "new_name": "dest.mkv", "new_path": str(dest)}]
    results = perform_rename(previews)
    assert not results[0]["success"]
    assert "already exists" in results[0]["error"]

    # Source missing
    previews = [
        {"old_path": "missing.mkv", "new_name": "new.mkv", "new_path": "new.mkv"}
    ]
    results = perform_rename(previews)
    assert not results[0]["success"]
    assert "missing" in results[0]["error"]

    # Unsafe filename
    previews = [
        {
            "old_path": "old.mkv",
            "new_name": "CON.mkv",
            "new_path": "CON.mkv",
            "safe": False,
            "error": "Reserved name",
        }
    ]
    results = perform_rename(previews)
    assert not results[0]["success"]
    assert "Reserved name" in results[0]["error"]


def test_format_name_errors() -> None:
    # Invalid token
    assert format_name("{InvalidToken}", {"SeriesTitle": "Title"}) == "{InvalidToken}"
    # Empty template
    assert format_name("", {"SeriesTitle": "Title"}) == ""
    # Braces mismatch
    assert format_name("{SeriesTitle", {"SeriesTitle": "Title"}) == "{SeriesTitle"
    # Exception during format
    assert (
        format_name("{SeriesTitle:invalid_format}", {"SeriesTitle": "Title"})
        == "{SeriesTitle:invalid_format}"
    )
    # KeyError (token not in context)
    assert format_name("{UnknownToken}", {"SeriesTitle": "Title"}) == "{UnknownToken}"


def test_get_rename_preview_missing_data() -> None:
    series_data = {
        "metadata": {},
        "seasons": {
            "Unknown": {
                "episodes": [
                    {
                        "name": None,
                        "path": "/data/file.mkv",
                    }
                ]
            }
        },
    }
    template = "{SeriesTitle} - {EpisodeTitle}"
    previews = get_rename_preview(series_data, template)
    assert len(previews) == 1
    assert "Unknown Series" in previews[0]["new_name"]
    assert "Unknown Episode" in previews[0]["new_name"]


def test_perform_rename_db_callback_error(tmp_path) -> None:
    old = tmp_path / "old.mkv"
    old.touch()
    previews = [
        {
            "old_path": str(old),
            "new_name": "new.mkv",
            "new_path": str(tmp_path / "new.mkv"),
        }
    ]

    def bad_callback(o, n) -> None:
        raise Exception("DB Error")

    results = perform_rename(previews, db_callback=bad_callback)
    assert results[0]["success"]  # Still success for file rename


def test_perform_rename_same_path(tmp_path) -> None:
    old = tmp_path / "old.mkv"
    old.touch()
    previews = [{"old_path": str(old), "new_name": "old.mkv", "new_path": str(old)}]
    results = perform_rename(previews)
    assert results[0]["success"]
    assert results[0]["error"] == "No change"


def test_perform_rename_exception(tmp_path, monkeypatch) -> None:
    old = tmp_path / "old.mkv"
    old.touch()
    previews = [
        {
            "old_path": str(old),
            "new_name": "new.mkv",
            "new_path": str(tmp_path / "new.mkv"),
        }
    ]

    def mock_rename(*args) -> None:
        raise OSError("Rename failed")

    import pathlib

    monkeypatch.setattr(pathlib.Path, "rename", mock_rename)

    results = perform_rename(previews)
    assert not results[0]["success"]
    assert "Rename failed" in results[0]["error"]


def test_get_rename_preview_with_subtitles(tmp_path) -> None:
    series_data = {
        "metadata": {"tmdb_name": "Show"},
        "seasons": {
            "Season 1": {
                "episodes": [
                    {
                        "name": "Ep 1",
                        "path": str(tmp_path / "ep1.mkv"),
                        "tmdb_number": 1,
                    }
                ]
            }
        },
    }

    # Create video and subtitles
    (tmp_path / "ep1.mkv").touch()
    (tmp_path / "ep1.srt").touch()
    (tmp_path / "ep1.en.srt").touch()
    (tmp_path / "other.srt").touch()  # Should be ignored

    template = "{SeriesTitle} - S{SeasonNumber:02}E{EpisodeNumber:02}"
    previews = get_rename_preview(series_data, template)

    # Should have 3 previews: 1 video + 2 subtitles
    assert len(previews) == 3

    video_preview = next(p for p in previews if not p["is_subtitle"])
    assert video_preview["old_name"] == "ep1.mkv"
    assert video_preview["new_name"] == "Show - S01E01.mkv"

    sub1 = next(p for p in previews if p["new_name"] == "Show - S01E01.srt")
    assert sub1["old_name"] == "ep1.srt"
    assert sub1["is_subtitle"] is True

    sub2 = next(p for p in previews if p["new_name"] == "Show - S01E01.en.srt")
    assert sub2["old_name"] == "ep1.en.srt"
    assert sub2["is_subtitle"] is True


def test_get_rename_preview_with_none_path() -> None:
    series_data = {
        "metadata": {"tmdb_name": "Show"},
        "seasons": {
            "Season 1": {
                "episodes": [
                    {
                        "name": "Ep 1",
                        "path": "/data/ep1.mkv",
                        "tmdb_number": 1,
                    },
                    {
                        "name": "Ep 2",
                        "path": None,  # Placeholder episode
                        "tmdb_number": 2,
                    },
                ]
            }
        },
    }
    template = "{SeriesTitle} - S{SeasonNumber:02}E{EpisodeNumber:02}"
    previews = get_rename_preview(series_data, template)
    assert len(previews) == 1
    assert previews[0]["old_name"] == "ep1.mkv"
