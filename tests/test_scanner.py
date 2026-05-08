from lan_streamer.scanner import scan_directories
import lan_streamer.scanner as scanner
from unittest.mock import MagicMock, patch


def _mock_tmdb(monkeypatch, search_return=None, seasons=None, episodes=None):
    """Helper that patches scanner.tmdb_client with a preconfigured mock."""
    mock = MagicMock()
    mock.search_series.return_value = search_return
    mock.get_series_by_id.return_value = search_return
    mock.get_seasons.return_value = seasons or []
    mock.get_episodes.return_value = episodes or []
    mock.download_image.return_value = ""
    monkeypatch.setattr(scanner, "tmdb_client", mock)
    return mock


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

    season_1.mkdir(parents=True)
    season_2.mkdir(parents=True)
    season_b_1.mkdir(parents=True)

    ep1_path = season_1 / "S01E01.mkv"
    ep2_path = season_1 / "S01E02.mp4"
    ep3_path = season_2 / "S02E01.avi"
    ep4_path = season_b_1 / "S01E01.mkv"
    ignored_path = season_b_1 / "notes.txt"

    for f in [ep1_path, ep2_path, ep3_path, ep4_path, ignored_path]:
        f.touch()

    # Mock TMDB responses
    mock_tmdb = MagicMock()

    def search_series(name):
        if "Series A" in name:
            return {
                "id": "series_a_id",
                "tmdb_id": "111",
                "overview": "Desc A",
                "poster_path": "",
            }
        return {
            "id": "series_b_id",
            "tmdb_id": "222",
            "overview": "Desc B",
            "poster_path": "",
        }

    mock_tmdb.search_series.side_effect = search_series
    mock_tmdb.get_series_by_id.side_effect = search_series
    mock_tmdb.download_image.return_value = ""
    mock_tmdb.get_seasons.return_value = [
        {"id": "s1", "episode_number": 1, "season_number": 1},
    ]
    mock_tmdb.get_episodes.return_value = [
        {"id": "ep1", "episode_number": 1},
        {"id": "ep2", "episode_number": 2},
    ]
    monkeypatch.setattr(scanner, "tmdb_client", mock_tmdb)

    library = scan_directories([str(tmp_path)])

    assert "Series A" in library
    assert "Season 1" in library["Series A"]["seasons"]
    assert "Season 2" in library["Series A"]["seasons"]

    s1_eps = library["Series A"]["seasons"]["Season 1"]["episodes"]
    assert len(s1_eps) == 2
    assert s1_eps[0]["name"] == "S01E01.mkv"
    assert s1_eps[0]["path"] == str(ep1_path.absolute())

    assert "Series B" in library
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
    _mock_tmdb(monkeypatch)

    library = scan_directories([str(tmp_path)])
    episodes = library["Series A"]["seasons"]["Season 1"]["episodes"]
    assert episodes[0]["date_added"] == 0


def test_scan_directories_nonexistent_path():
    assert scan_directories(["/path/does/not/exist/at/all/123456789"]) == {}


def test_scan_series(tmp_path, monkeypatch):
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Test Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "Test Show S01E01.mkv"
    episode_file.write_text("video content")

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
        mock_tmdb.is_configured.return_value = True
        mock_tmdb.search_series.return_value = {
            "id": "series123",
            "tmdb_id": "series123",
            "name": "Test Show",
            "overview": "A test show",
            "poster_path": "",
        }
        mock_tmdb.get_seasons.return_value = [
            {
                "id": "season123",
                "episode_number": 1,
                "name": "Season 1",
                "season_number": 1,
                "image": "",
            }
        ]
        mock_tmdb.get_episodes.return_value = [
            {"id": "ep123", "episode_number": 1, "name": "Episode 1"}
        ]
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(series_dir)

        assert series_data["metadata"]["tmdb_id"] == "series123"
        assert "Season 1" in series_data["seasons"]
        episodes = series_data["seasons"]["Season 1"]["episodes"]
        assert len(episodes) == 1
        assert episodes[0]["tmdb_episode_id"] == "ep123"
        # watched defaults to False; history sync sets it later
        assert episodes[0]["watched"] is False


def test_scan_series_manual_match(tmp_path, monkeypatch):
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Mismatched Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "Show S01E01.mkv"
    episode_file.write_text("video")

    selected_series = {
        "id": "real_id",
        "tmdb_id": "real_id",
        "name": "Correct Show",
        "poster_path": "",
    }

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
        mock_tmdb.get_seasons.return_value = []
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(series_dir, tmdb_series=selected_series)

        assert series_data["metadata"]["tmdb_id"] == "real_id"
        mock_tmdb.search_series.assert_not_called()


def test_scan_series_manual_match_fetch_by_id(tmp_path, monkeypatch):
    """When manual match only has 'id' (not 'name'), should fetch full record."""
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Some Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    stub_only_id = {"id": "fetch_me"}
    full_record = {
        "id": "fetch_me",
        "tmdb_id": "fetch_me",
        "name": "Some Show",
        "poster_path": "",
    }

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
        mock_tmdb.get_series_by_id.return_value = full_record
        mock_tmdb.get_seasons.return_value = []
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(series_dir, tmdb_series=stub_only_id)
        mock_tmdb.get_series_by_id.assert_called_once_with("fetch_me")
        assert series_data["metadata"]["tmdb_id"] == "fetch_me"


def test_scan_directories_respects_manual_match(tmp_path, monkeypatch):
    series_dir = tmp_path / "Manual Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Manual Show": {
            "metadata": {"tmdb_id": "manual_tmdb_id", "is_manual_match": True},
            "seasons": {"Season 1": {"episodes": []}},
        }
    }

    mock_tmdb = MagicMock()
    mock_tmdb.get_series_by_id.return_value = {
        "id": "manual_tmdb_id",
        "tmdb_id": "manual_tmdb_id",
        "name": "Manual Show",
        "poster_path": "",
    }
    mock_tmdb.get_seasons.return_value = []
    mock_tmdb.download_image.return_value = ""
    monkeypatch.setattr(scanner, "tmdb_client", mock_tmdb)

    library = scan_directories([str(tmp_path)], existing_library=existing_library)

    assert library["Manual Show"]["metadata"]["tmdb_id"] == "manual_tmdb_id"
    assert library["Manual Show"]["metadata"]["is_manual_match"] is True
    mock_tmdb.search_series.assert_not_called()


def test_clean_series_data_none():
    assert scanner.clean_series_data({"seasons": {}}) is None
    assert scanner.clean_series_data({"seasons": {"S1": {"episodes": []}}}) is None


def test_scan_directories_gaps(tmp_path, monkeypatch):
    # root_path is not a dir
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("not a dir")
    assert scanner.scan_directories([str(not_a_dir)]) == {}

    # series_dir is not a dir or starts with .
    root_dir = tmp_path / "root"
    root_dir.mkdir()
    (root_dir / ".hidden_series").mkdir()
    (root_dir / "file_series").write_text("file")

    # season_dir is not a dir or starts with .
    series_dir = root_dir / "Valid Series"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "ep1.mkv").write_text("video")
    (series_dir / ".hidden_season").mkdir()
    (series_dir / "file_season").write_text("file")

    mock_tmdb = MagicMock()
    mock_tmdb.search_series.return_value = None
    monkeypatch.setattr(scanner, "tmdb_client", mock_tmdb)

    res = scanner.scan_directories([str(root_dir)])
    assert "Valid Series" in res
    assert "Season 1" in res["Valid Series"]["seasons"]


def test_parse_episode_num():
    from lan_streamer.scanner import _parse_episode_num

    assert _parse_episode_num("Show.S01E05.mkv") == (1, 5)
    assert _parse_episode_num("s02e10.mp4") == (2, 10)
    assert _parse_episode_num("no_episode.mkv") is None


def test_scan_tmdb_merge_by_tmdb_id(tmp_path, monkeypatch):
    """Two differently-named folders with same TMDB ID should be merged."""
    folder_a = tmp_path / "Show Part 1"
    folder_b = tmp_path / "Show Part 2"
    for folder in [folder_a, folder_b]:
        s = folder / "Season 1"
        s.mkdir(parents=True)

    (folder_a / "Season 1" / "S01E01.mkv").touch()
    (folder_b / "Season 1" / "S01E02.mkv").touch()

    mock_tmdb = MagicMock()
    mock_tmdb.search_series.return_value = {
        "id": "shared_id",
        "tmdb_id": "shared_id",
        "name": "Show",
        "poster_path": "",
    }
    mock_tmdb.get_series_by_id.return_value = {
        "id": "shared_id",
        "tmdb_id": "shared_id",
        "name": "Show",
        "poster_path": "",
    }
    mock_tmdb.get_seasons.return_value = [
        {"id": "s1", "episode_number": 1, "season_number": 1, "image": ""}
    ]
    mock_tmdb.get_episodes.return_value = [
        {"id": "e1", "episode_number": 1},
        {"id": "e2", "episode_number": 2},
    ]
    mock_tmdb.download_image.return_value = ""
    monkeypatch.setattr(scanner, "tmdb_client", mock_tmdb)

    library = scan_directories([str(tmp_path)])
    # Both folders should be merged under one entry
    assert len(library) == 1
    merged = list(library.values())[0]
    episodes = merged["seasons"]["Season 1"]["episodes"]
    assert len(episodes) == 2


def test_scan_directories_merge_branches(tmp_path, monkeypatch):
    from lan_streamer.scanner import scan_directories

    # 1. Fallback to name match (line 104)
    # 2. Duplicate episode name (lines 131-134)
    # 3. New season for existing series (line 143)

    root = tmp_path / "root"
    root.mkdir()
    show_dir = root / "Show A"
    show_dir.mkdir()
    (show_dir / "Season 1").mkdir()
    (show_dir / "Season 1" / "S01E01.mkv").touch()

    mock_tmdb = MagicMock()
    mock_tmdb.search_series.return_value = {"id": "id1", "name": "Show A"}
    mock_tmdb.get_seasons.return_value = [{"season_number": 1, "id": "s1"}]
    mock_tmdb.get_episodes.return_value = [{"episode_number": 1, "id": "e1"}]
    mock_tmdb.download_image.return_value = ""
    monkeypatch.setattr(scanner, "tmdb_client", mock_tmdb)

    # Initial scan
    lib = scan_directories([str(root)])
    assert "Show A" in lib

    # Now scan again with a new folder that has SAME NAME but DIFFERENT ID (if we were to mock it so)
    # But here we'll just force the name match fallback by making search return NO result or different ID
    mock_tmdb.search_series.return_value = None  # Force fallback to name

    # Let's test the episode duplicate branch
    (
        show_dir / "Season 1" / "S01E01_alt.mkv"
    ).touch()  # Same episode name "S01E01.mkv" if we don't parse?
    # Wait, the name in lib is the filename.
    # If filenames are different, they are different episodes unless parsed?
    # Line 121: ep_names = {ep["name"] for ep in existing_episodes}
    # Filenames are unique usually.

    # Let's mock _parse_episode_num to return same for different files
    monkeypatch.setattr(scanner, "_parse_episode_num", lambda x: (1, 1))

    # To hit line 131-134, we need same name but different path.
    # We can just manually construct the library and pass it to scan_directories
    existing_library = {
        "Show A": {
            "metadata": {"tmdb_id": "id1"},
            "seasons": {
                "Season 1": {
                    "episodes": [{"name": "S01E01.mkv", "path": "/other/path"}]
                }
            },
        }
    }

    lib = scan_directories([str(root)], existing_library=existing_library)
    # This should hit "Skipping episode because an episode with the same name already exists"

    # To hit line 143 (new season for existing series)
    (show_dir / "Season 2").mkdir()
    (show_dir / "Season 2" / "S02E01.mkv").touch()
    mock_tmdb.get_seasons.return_value = [
        {"season_number": 1, "id": "s1"},
        {"season_number": 2, "id": "s2"},
    ]
    mock_tmdb.get_episodes.side_effect = lambda id, s: (
        [{"episode_number": 1, "id": "e1"}]
        if s == 1
        else [{"episode_number": 1, "id": "e2"}]
    )

    lib = scan_directories([str(root)], existing_library=existing_library)
    assert "Season 2" in lib["Show A"]["seasons"]


def test_scan_directories_clean_none(tmp_path, monkeypatch):
    # Hit scanner.py line 91
    from lan_streamer.scanner import scan_directories

    root = tmp_path / "root_gap"
    root.mkdir()
    (root / "Show A").mkdir()

    # Mock scan_series to return something that clean_series_data returns None for
    monkeypatch.setattr(scanner, "scan_series", lambda *args, **kwargs: {"seasons": {}})
    monkeypatch.setattr(scanner, "clean_series_data", lambda x: None)

    res = scan_directories([str(root)])
    assert res == {}


def test_scan_series_no_poster_branch(tmp_path, monkeypatch):
    # Hit scanner.py lines 178 and 223
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "ShowNoPoster"
    series_dir.mkdir()
    (series_dir / "Season 1").mkdir()
    (series_dir / "Season 1" / "S01E01.mkv").touch()

    mock_tmdb = MagicMock()
    # No poster_path
    mock_tmdb.search_series.return_value = {"id": 1, "name": "Show", "overview": "..."}
    mock_tmdb.get_seasons.return_value = [
        {"season_number": 1, "id": 101}
    ]  # No poster_path in season either
    mock_tmdb.get_episodes.return_value = []

    monkeypatch.setattr(scanner, "tmdb_client", mock_tmdb)

    data = scan_series(series_dir)
    assert data["metadata"]["poster_path"] == ""
    assert data["seasons"]["Season 1"]["metadata"]["poster_path"] == ""
