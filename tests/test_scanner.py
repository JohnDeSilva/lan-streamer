from lan_streamer.scanner import scan_directories
import lan_streamer.scanner as scanner
from unittest.mock import MagicMock


def test_scan_directories_with_mock(tmp_path, monkeypatch):
    """
    Test scanning using dynamically created mock directories and files.
    """
    # Create the test directory structure
    series_a = tmp_path / "Series A"
    season_1 = series_a / "Season 1"
    season_2 = series_a / "Season 2"

    series_b = tmp_path / "Series B"
    season_b_1 = series_b / "Season 1"

    # Create the actual directories
    season_1.mkdir(parents=True)
    season_2.mkdir(parents=True)
    season_b_1.mkdir(parents=True)

    # Create mock video files
    ep1_path = season_1 / "S01E01.mkv"
    ep2_path = season_1 / "S01E02.mp4"
    ep3_path = season_2 / "S02E01.avi"
    ep4_path = season_b_1 / "S01E01.mkv"

    # Create a non-video file that should be ignored
    ignored_path = season_b_1 / "notes.txt"

    for f in [ep1_path, ep2_path, ep3_path, ep4_path, ignored_path]:
        f.touch()

    # Mock Jellyfin responses
    mock_jf = MagicMock()
    mock_jf.search_series.return_value = {"Id": "series123", "Overview": "Desc"}
    mock_jf.download_image.return_value = "/fake/image.jpg"
    mock_jf.get_seasons.return_value = [
        {"Id": "season_1_id", "IndexNumber": 1},
        {"Id": "season_b_1_id", "Name": "Season 1"},
    ]
    mock_jf.get_episodes.return_value = [
        {"Id": "ep1_id", "Path": str(ep1_path.absolute()), "UserData": {"Played": True}}
    ]
    monkeypatch.setattr(scanner, "jellyfin_client", mock_jf)

    library = scan_directories([str(tmp_path)])

    # Verify Series A
    assert "Series A" in library
    assert "Season 1" in library["Series A"]["seasons"]
    assert "Season 2" in library["Series A"]["seasons"]

    s1_eps = library["Series A"]["seasons"]["Season 1"]["episodes"]
    assert len(s1_eps) == 2
    assert s1_eps[0]["name"] == "S01E01.mkv"
    assert s1_eps[0]["path"] == str(ep1_path.absolute())

    # Verify Series B and ensure non-video file was ignored
    assert "Series B" in library
    assert "Season 1" in library["Series B"]["seasons"]

    sb_eps = library["Series B"]["seasons"]["Season 1"]["episodes"]
    assert len(sb_eps) == 1
    assert sb_eps[0]["name"] == "S01E01.mkv"


def test_scan_directories_empty_list():
    assert scan_directories([]) == {}


def test_scan_directories_oserror(tmp_path, monkeypatch):
    import os

    series_a = tmp_path / "Series A"
    season_1 = series_a / "Season 1"
    season_1.mkdir(parents=True)
    ep = season_1 / "S01E01.mkv"
    ep.touch()

    def mock_getctime(*args):
        raise OSError("Permission denied")

    monkeypatch.setattr(os.path, "getctime", mock_getctime)

    library = scan_directories([str(tmp_path)])
    episodes = library["Series A"]["seasons"]["Season 1"]["episodes"]
    assert episodes[0]["date_added"] == 0


def test_scan_directories_nonexistent_path():
    from lan_streamer.scanner import scan_directories

    # Should not raise error
    assert scan_directories(["/path/does/not/exist/at/all/123456789"]) == {}


def test_scan_series(tmp_path):
    from lan_streamer.scanner import scan_series
    from unittest.mock import patch

    series_dir = tmp_path / "Test Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "Test Show S01E01.mkv"
    episode_file.write_text("video content")

    # Mock jellyfin
    with patch("lan_streamer.scanner.jellyfin_client") as mock_jf:
        mock_jf.search_series.return_value = {"Id": "series123", "Name": "Test Show"}
        mock_jf.get_seasons.return_value = [
            {"Id": "season123", "IndexNumber": 1, "Name": "Season 1"}
        ]
        mock_jf.get_episodes.return_value = [
            {
                "Id": "ep123",
                "Name": "Episode 1",
                "Path": str(episode_file),
                "UserData": {"Played": True},
            }
        ]
        mock_jf.download_image.return_value = "/path/to/poster.jpg"

        series_data = scan_series(series_dir)

        assert series_data["metadata"]["jellyfin_id"] == "series123"
        assert "Season 1" in series_data["seasons"]
        episodes = series_data["seasons"]["Season 1"]["episodes"]
        assert len(episodes) == 1
        assert episodes[0]["jellyfin_id"] == "ep123"
        assert episodes[0]["watched"] is True


def test_scan_series_manual_match(tmp_path):
    from lan_streamer.scanner import scan_series
    from unittest.mock import patch

    series_dir = tmp_path / "Mismatched Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "Show S01E01.mkv"
    episode_file.write_text("video")

    selected_series = {"Id": "real_id", "Name": "Correct Show"}

    with patch("lan_streamer.scanner.jellyfin_client") as mock_jf:
        mock_jf.get_seasons.return_value = []
        mock_jf.download_image.return_value = None

        # Call with explicit jellyfin_series
        series_data = scan_series(series_dir, jellyfin_series=selected_series)

        assert series_data["metadata"]["jellyfin_id"] == "real_id"
        mock_jf.search_series.assert_not_called()


def test_scan_directories_respects_manual_match(tmp_path, monkeypatch):
    from lan_streamer.scanner import scan_directories

    series_dir = tmp_path / "Manual Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Manual Show": {
            "metadata": {"jellyfin_id": "manual_id", "is_manual_match": True},
            "seasons": {"Season 1": {"episodes": []}},
        }
    }

    # Mock jellyfin
    mock_jf = MagicMock()
    mock_jf.get_seasons.return_value = []
    mock_jf.download_image.return_value = None
    mock_jf.get_series_by_id.return_value = {
        "Id": "manual_id",
        "Name": "Manual Show",
        "Overview": "Mock",
    }
    monkeypatch.setattr(scanner, "jellyfin_client", mock_jf)

    # Scan with existing library
    library = scan_directories([str(tmp_path)], existing_library=existing_library)

    assert library["Manual Show"]["metadata"]["jellyfin_id"] == "manual_id"
    assert library["Manual Show"]["metadata"]["is_manual_match"] is True
    mock_jf.search_series.assert_not_called()
