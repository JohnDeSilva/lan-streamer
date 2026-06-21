from pathlib import Path
from typing import Any

from lan_streamer.scanner import scan_directories
import lan_streamer.scanner as scanner
from unittest.mock import MagicMock, patch


def _mock_tmdb(search_return=None, seasons=None, episodes=None) -> None:
    """Helper that returns a preconfigured mock."""
    mock = MagicMock()
    mock.search_series.return_value = search_return
    mock.get_series_by_id.return_value = search_return
    mock.get_seasons.return_value = seasons or []
    mock.get_episodes.return_value = episodes or []
    mock.download_image.return_value = ""
    return mock


def test_scan_directories_with_mock(tmp_path) -> None:
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

    def search_series(name) -> None:
        if "Series A" in name:
            return {
                "id": "series_a_id",
                "tmdb_identifier": "111",
                "overview": "Desc A",
                "poster_path": "",
            }
        return {
            "id": "series_b_id",
            "tmdb_identifier": "222",
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
    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
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
    assert len(sb_eps) == 2
    assert sb_eps[0]["name"] == "S01E01.mkv"
    assert sb_eps[1]["name"] == "S01E02 - TBA"
    assert sb_eps[1]["path"] is None


def test_scan_directories_empty_list() -> None:
    assert scan_directories([]) == {}


def test_scan_directories_oserror(tmp_path) -> None:

    series_a = tmp_path / "Series A"
    season_1 = series_a / "Season 1"
    season_1.mkdir(parents=True)
    ep = season_1 / "S01E01.mkv"
    ep.touch()

    def mock_getctime(*args) -> None:
        raise OSError("Permission denied")

    with (
        patch("os.path.getctime", mock_getctime),
        patch("lan_streamer.services.metadata_tv.tmdb_client", _mock_tmdb()),
    ):
        library = scan_directories([str(tmp_path)])
        episodes = library["Series A"]["seasons"]["Season 1"]["episodes"]
        assert episodes[0]["date_added"] == 0


def test_scan_directories_nonexistent_path() -> None:
    result = scan_directories(["/path/does/not/exist/at/all/123456789"])
    assert result == {}
    assert result.unavailable_directories == ["/path/does/not/exist/at/all/123456789"]


def test_scan_directories_mixed_availability(tmp_path: Path) -> None:
    valid_path = tmp_path / "valid_dir"
    valid_path.mkdir()
    invalid_path = "/path/does/not/exist/123"

    result = scan_directories([str(valid_path), invalid_path])
    assert result == {}
    assert result.unavailable_directories == [invalid_path]


def test_scan_series(tmp_path) -> None:
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Test Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "Test Show S01E01.mkv"
    episode_file.write_text("video content")

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.is_configured.return_value = True
        mock_tmdb.search_series.return_value = {
            "id": "series123",
            "tmdb_identifier": "series123",
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

        assert series_data["metadata"]["tmdb_identifier"] == "series123"
        assert "Season 1" in series_data["seasons"]
        episodes = series_data["seasons"]["Season 1"]["episodes"]
        assert len(episodes) == 1
        assert episodes[0]["tmdb_identifier"] == "ep123"
        # watched defaults to False; history sync sets it later
        assert episodes[0]["watched"] is False


def test_scan_series_manual_match(tmp_path) -> None:
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Mismatched Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "Show S01E01.mkv"
    episode_file.write_text("video")

    selected_series = {
        "id": "real_id",
        "tmdb_identifier": "real_id",
        "name": "Correct Show",
        "poster_path": "",
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.get_seasons.return_value = []
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(series_dir, tmdb_series=selected_series)

        assert series_data["metadata"]["tmdb_identifier"] == "real_id"
        mock_tmdb.search_series.assert_not_called()


def test_scan_series_manual_match_fetch_by_id(tmp_path) -> None:
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
        "tmdb_identifier": "fetch_me",
        "name": "Some Show",
        "poster_path": "",
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.get_series_by_id.return_value = full_record
        mock_tmdb.get_seasons.return_value = []
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(series_dir, tmdb_series=stub_only_id)
        mock_tmdb.get_series_by_id.assert_called_once_with("fetch_me")
        assert series_data["metadata"]["tmdb_identifier"] == "fetch_me"


def test_scan_directories_respects_manual_match(tmp_path) -> None:
    series_dir = tmp_path / "Manual Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Manual Show": {
            "metadata": {
                "tmdb_identifier": "manual_tmdb_identifier",
                "locked_metadata": True,
            },
            "seasons": {"Season 1": {"episodes": []}},
        }
    }

    mock_tmdb = MagicMock()
    mock_tmdb.get_series_by_id.return_value = {
        "id": "manual_tmdb_identifier",
        "tmdb_identifier": "manual_tmdb_identifier",
        "name": "Manual Show",
        "poster_path": "",
    }
    mock_tmdb.get_seasons.return_value = []
    mock_tmdb.download_image.return_value = ""
    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        library = scan_directories([str(tmp_path)], existing_library=existing_library)

    assert (
        library["Manual Show"]["metadata"]["tmdb_identifier"]
        == "manual_tmdb_identifier"
    )
    assert library["Manual Show"]["metadata"]["locked_metadata"] is True
    mock_tmdb.search_series.assert_not_called()


def test_clean_series_data_none() -> None:
    assert scanner.clean_series_data({"seasons": {}}) is None
    assert scanner.clean_series_data({"seasons": {"S1": {"episodes": []}}}) is None


def test_scan_directories_gaps(tmp_path) -> None:
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
    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        res = scanner.scan_directories([str(root_dir)])
    assert "Valid Series" in res
    assert "Season 1" in res["Valid Series"]["seasons"]


def test_parse_episode_number() -> None:
    from lan_streamer.scanner import _parse_episode_number

    assert _parse_episode_number("Show.S01E05.mkv") == (1, 5)
    assert _parse_episode_number("s02e10.mp4") == (2, 10)
    assert _parse_episode_number("no_episode.mkv") is None


def test_scan_tmdb_no_merge_differently_named_folders(tmp_path) -> None:
    """Two differently-named folders with same TMDB ID should NOT be merged per user requirement."""
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
        "tmdb_identifier": "shared_id",
        "name": "Show",
        "poster_path": "",
    }
    mock_tmdb.get_series_by_id.return_value = {
        "id": "shared_id",
        "tmdb_identifier": "shared_id",
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
    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        library = scan_directories([str(tmp_path)])
    # Both folders should be kept separate per updated requirement
    assert len(library) == 2
    assert "Show Part 1" in library
    assert "Show Part 2" in library


def test_scan_directories_merge_branches(tmp_path) -> None:
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

    # We can just manually construct the library and pass it to scan_directories
    existing_library = {
        "Show A": {
            "metadata": {"tmdb_identifier": "id1"},
            "seasons": {
                "Season 1": {
                    "episodes": [{"name": "S01E01.mkv", "path": "/other/path"}]
                }
            },
        }
    }

    with (
        patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner._parse_episode_number", lambda x: (1, 1)),
    ):
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


def test_scan_directories_clean_none(tmp_path) -> None:
    # Hit scanner.py line 91
    from lan_streamer.scanner import scan_directories

    root = tmp_path / "root_gap"
    root.mkdir()
    (root / "Show A").mkdir()

    # Mock scan_series to return something that clean_series_data returns None for
    with (
        patch(
            "lan_streamer.scanner.scan_series", lambda *args, **kwargs: {"seasons": {}}
        ),
        patch("lan_streamer.scanner.clean_series_data", lambda x: None),
    ):
        res = scan_directories([str(root)])
        assert res == {}


def test_scan_series_no_poster_branch(tmp_path) -> None:
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

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        data = scan_series(series_dir)
        assert data["metadata"]["poster_path"] == ""
        assert data["seasons"]["Season 1"]["metadata"]["poster_path"] == ""


def test_scan_series_tmdb_correlation(tmp_path) -> None:
    """Test that jellyfin_id is pulled via TMDB ID fallback if path doesn't match."""
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Correlation Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "S01E01.mkv"
    episode_file.touch()

    jellyfin_data = {
        "path_map": {
            "/different/path/S01E01.mkv": {
                "id": "jf_ep_123",
                "series_id": "jf_series_456",
            }
        },
        "tmdb_episode_map": {"tmdb_ep_1": "jf_ep_123"},
        "tmdb_series_map": {"tmdb_series_1": "jf_series_456"},
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.search_series.return_value = {
            "id": "tmdb_series_1",
            "name": "Correlation Show",
        }
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 1, "id": "tmdb_season_1"}
        ]
        mock_tmdb.get_episodes.return_value = [{"episode_number": 1, "id": "tmdb_ep_1"}]
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(series_dir, jellyfin_data=jellyfin_data)

        # Check episode correlation
        ep = series_data["seasons"]["Season 1"]["episodes"][0]
        assert ep["jellyfin_id"] == "jf_ep_123"

        # Check series correlation
        assert series_data["metadata"]["jellyfin_id"] == "jf_series_456"


def test_scan_series_name_correlation(tmp_path) -> None:
    """Test that jellyfin_id is pulled via Name fallback if path/TMDB fail."""
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Name Correlation Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "S01E01.mkv"
    episode_file.touch()

    jellyfin_data = {
        "path_map": {},
        "tmdb_episode_map": {},
        "name_map": {("name correlation show", "episode one"): "jf_ep_name_123"},
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.search_series.return_value = {
            "id": "tmdb_series_2",
            "name": "Name Correlation Show",
        }
        mock_tmdb.get_seasons.return_value = [
            {"season_number": 1, "id": "tmdb_season_2"}
        ]
        mock_tmdb.get_episodes.return_value = [
            {"episode_number": 1, "id": "tmdb_ep_2", "name": "Episode One"}
        ]
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(series_dir, jellyfin_data=jellyfin_data)

        # Check episode correlation
        ep = series_data["seasons"]["Season 1"]["episodes"][0]
        assert ep["jellyfin_id"] == "jf_ep_name_123"


def test_scan_series_manual_jellyfin_correlation(tmp_path) -> None:
    """Test that jellyfin_id is pulled via series_id_map when manual_jellyfin_id is provided."""
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Manual JF Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "S01E01.mkv"
    episode_file.touch()

    jellyfin_data = {
        "path_map": {},
        "tmdb_episode_map": {},
        "series_id_map": {
            "jf_manual_id": {
                "episodes": {(1, 1): "jf_ep_manual_123"},
                "names": {"manual episode": "jf_ep_manual_456"},
            }
        },
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.search_series.return_value = {
            "id": "tmdb123",
            "name": "Manual JF Show",
        }
        mock_tmdb.get_seasons.return_value = [{"season_number": 1, "id": "tmdb_s1"}]
        mock_tmdb.get_episodes.return_value = [{"episode_number": 1, "id": "tmdb_e1"}]
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(
            series_dir, jellyfin_data=jellyfin_data, manual_jellyfin_id="jf_manual_id"
        )

        # Check episode correlation via SxxExx
        ep = series_data["seasons"]["Season 1"]["episodes"][0]
        assert ep["jellyfin_id"] == "jf_ep_manual_123"
        assert series_data["metadata"]["jellyfin_id"] == "jf_manual_id"


def test_parse_season_number() -> None:
    from lan_streamer.scanner import _parse_season_number

    assert _parse_season_number("Season 1") == 1
    assert _parse_season_number("Season 02") == 2
    assert _parse_season_number("S03") is None
    assert _parse_season_number("Season1") == 1
    assert _parse_season_number("season 5") == 5
    assert _parse_season_number("Specials") == 0


def test_scan_series_tmdb_name_fallback(tmp_path) -> None:
    """Test that TMDB episode is matched by name if SxxExx parsing fails."""
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Name Match Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "Pilot Episode.mkv"  # No S01E01
    episode_file.touch()

    jellyfin_data = {
        "tmdb_series_map": {"tmdb1": "jf_series1"},
        "series_id_map": {
            "jf_series1": {
                "episodes": {(1, 1): "jf_ep1"},
                "names": {},
            }
        },
        "path_map": {},
        "tmdb_episode_map": {},
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.search_series.return_value = {
            "id": "tmdb1",
            "name": "Name Match Show",
        }
        mock_tmdb.get_seasons.return_value = [{"season_number": 1, "id": "s1"}]
        mock_tmdb.get_episodes.return_value = [
            {"episode_number": 1, "id": "ep1", "name": "Pilot Episode"}
        ]
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(series_dir, jellyfin_data=jellyfin_data)
        ep = series_data["seasons"]["Season 1"]["episodes"][0]
        assert ep["tmdb_identifier"] == "ep1"
        assert ep["tmdb_name"] == "Pilot Episode"
        assert ep["tmdb_number"] == 1
        assert ep["jellyfin_id"] == "jf_ep1"


def test_scan_series_initial_jellyfin_lookup(tmp_path) -> None:
    """Test that series jellyfin_id is looked up via TMDB ID at the start."""
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Initial Lookup Show"
    series_dir.mkdir()

    jellyfin_data = {
        "tmdb_series_map": {"tmdb_999": "jf_999"},
        "series_id_map": {},
        "path_map": {},
        "tmdb_episode_map": {},
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.search_series.return_value = {
            "id": "tmdb_999",
            "name": "Initial Lookup Show",
        }
        mock_tmdb.get_seasons.return_value = []
        mock_tmdb.download_image.return_value = ""

        series_data = scan_series(series_dir, jellyfin_data=jellyfin_data)
        assert series_data["metadata"]["jellyfin_id"] == "jf_999"


def test_scan_series_force_refresh_false(tmp_path) -> None:
    """Test that existing metadata is reused when force_refresh=False."""
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Reuse Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "S01E01.mkv"
    episode_file.touch()

    existing_series = {
        "metadata": {
            "tmdb_identifier": "tmdb_old",
            "tmdb_name": "Old Name",
            "overview": "Old Overview",
            "poster_path": "old_poster.jpg",
        },
        "seasons": {
            "Season 1": {
                "metadata": {},
                "episodes": [
                    {
                        "path": str(episode_file.absolute()),
                        "tmdb_identifier": "ep_old",
                        "tmdb_name": "Old Episode",
                        "tmdb_number": 1,
                        "jellyfin_id": "jf_old",
                    }
                ],
            }
        },
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        # If reuse works, tmdb_client should NOT be called for searching series or episodes
        series_data = scan_series(
            series_dir, existing_series_data=existing_series, force_refresh=False
        )

        assert series_data["metadata"]["tmdb_identifier"] == "tmdb_old"
        assert series_data["metadata"]["tmdb_name"] == "Old Name"

        ep = series_data["seasons"]["Season 1"]["episodes"][0]
        assert ep["tmdb_identifier"] == "ep_old"
        assert ep["tmdb_name"] == "Old Episode"
        assert ep["jellyfin_id"] == "jf_old"

        # Verify no TMDB search/episode calls
        assert mock_tmdb.search_series.call_count == 0
        assert mock_tmdb.get_episodes.call_count == 0


def test_scan_series_preserves_watched_status(tmp_path) -> None:
    """Test that watched status is preserved even during a force_refresh scan."""
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Watched Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "S01E01.mkv"
    episode_file.touch()

    existing_series = {
        "metadata": {
            "tmdb_identifier": "tmdb_123",
            "tmdb_name": "Watched Show",
        },
        "seasons": {
            "Season 1": {
                "metadata": {},
                "episodes": [
                    {
                        "path": str(episode_file.absolute()),
                        "watched": True,
                        "tmdb_identifier": "ep_123",
                    }
                ],
            }
        },
    }

    # Mock TMDB to return some metadata so the scan succeeds
    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.get_seasons.return_value = [
            {"id": 1, "season_number": 1, "name": "Season 1"}
        ]
        mock_tmdb.get_episodes.return_value = [
            {"id": "ep_123", "episode_number": 1, "name": "Pilot"}
        ]

        # Run scan with force_refresh=True
        series_data = scan_series(
            series_dir, existing_series_data=existing_series, force_refresh=True
        )

        ep = series_data["seasons"]["Season 1"]["episodes"][0]
        # Should be True because it was True in existing_series
        assert ep["watched"] is True

        # Verify metadata WAS refreshed (to confirm it was indeed a full scan)
        assert mock_tmdb.get_seasons.call_count == 1


def test_scan_directories_non_destructive_cleanup(tmp_path) -> None:
    """Test non-destructive preservation vs cleanup purging behavior."""
    from lan_streamer.scanner import scan_directories

    root = tmp_path / "cleanup_root"
    root.mkdir()
    show_dir = root / "Active Show"
    show_dir.mkdir()
    season_dir = show_dir / "Season 1"
    season_dir.mkdir()
    ep_file = season_dir / "S01E01.mkv"
    ep_file.touch()

    existing_library = {
        "Offline Show": {
            "metadata": {"tmdb_identifier": "off1"},
            "seasons": {},
        },
        "Active Show": {
            "metadata": {"tmdb_identifier": "act1"},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": str(ep_file.absolute()),
                            "watched": True,
                        },
                        {
                            "name": "S01E02.mkv",
                            "path": "/missing/path/S01E02.mkv",
                            "watched": False,
                        },
                    ],
                },
                "Season 2 (Offline)": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "S02E01.mkv",
                            "path": "/missing/path/S02E01.mkv",
                            "watched": False,
                        }
                    ],
                },
            },
        },
    }

    mock_tmdb = MagicMock()
    mock_tmdb.search_series.return_value = {"id": "act1", "name": "Active Show"}
    mock_tmdb.get_seasons.return_value = [{"season_number": 1, "id": "s1"}]
    mock_tmdb.get_episodes.return_value = [{"episode_number": 1, "id": "e1"}]
    mock_tmdb.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        # 1. Non-destructive scan (cleanup=False)
        lib_preserved = scan_directories(
            [str(root)], existing_library=existing_library, cleanup=False
        )
        assert "Offline Show" in lib_preserved
        active_seasons = lib_preserved["Active Show"]["seasons"]
        assert "Season 2 (Offline)" in active_seasons
        eps = active_seasons["Season 1"]["episodes"]
        assert len(eps) == 2
        assert any(ep["path"] == "/missing/path/S01E02.mkv" for ep in eps)

        # 2. Cleanup scan (cleanup=True)
        lib_cleaned = scan_directories(
            [str(root)], existing_library=existing_library, cleanup=True
        )
        assert "Offline Show" not in lib_cleaned
        active_seasons_cleaned = lib_cleaned["Active Show"]["seasons"]
        assert "Season 2 (Offline)" not in active_seasons_cleaned
        eps_cleaned = active_seasons_cleaned["Season 1"]["episodes"]
        assert len(eps_cleaned) == 1
        assert eps_cleaned[0]["path"] == str(ep_file.absolute())


def test_scan_distinct_series_metadata_collision(tmp_path) -> None:
    """Verify that similar folder names with unique TMDB IDs map to distinct library series without collisions."""
    folder_daredevil = tmp_path / "DareDevil"
    folder_born_again = tmp_path / "DareDevil - born again"

    for folder in [folder_daredevil, folder_born_again]:
        s = folder / "Season 1"
        s.mkdir(parents=True)

    (folder_daredevil / "Season 1" / "S01E01.mkv").touch()
    (folder_born_again / "Season 1" / "S01E01.mkv").touch()

    mock_tmdb = MagicMock()

    def mock_search_series(query: str) -> dict | None:
        if "born again" in query.lower():
            return {"id": "208857", "name": "Daredevil: Born Again"}
        return {"id": "61889", "name": "Daredevil"}

    def mock_get_series_by_id(tmdb_id: str | int) -> dict:
        target_id = str(tmdb_id)
        if target_id == "208857":
            return {"id": "208857", "name": "Daredevil: Born Again"}
        return {"id": "61889", "name": "Daredevil"}

    mock_tmdb.search_series.side_effect = mock_search_series
    mock_tmdb.get_series_by_id.side_effect = mock_get_series_by_id
    mock_tmdb.get_seasons.return_value = [
        {"id": "s1", "episode_number": 1, "season_number": 1, "image": ""}
    ]
    mock_tmdb.get_episodes.return_value = [{"id": "e1", "episode_number": 1}]
    mock_tmdb.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        library = scan_directories([str(tmp_path)])

    assert len(library) == 2
    assert "DareDevil" in library
    assert "DareDevil - born again" in library
    assert library["DareDevil"]["metadata"]["tmdb_identifier"] == "61889"
    assert library["DareDevil - born again"]["metadata"]["tmdb_identifier"] == "208857"


def test_scan_directories_locked_metadata_bypasses_refresh(tmp_path) -> None:
    """Verify that series with locked metadata bypass automatic updates during library refresh."""
    series_dir = tmp_path / "Locked Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Locked Show": {
            "metadata": {
                "tmdb_identifier": "locked_id",
                "tmdb_name": "Locked Custom Title",
                "overview": "Preserved overview",
                "locked_metadata": True,
            },
            "seasons": {},
        }
    }

    mock_tmdb = MagicMock()
    mock_tmdb.get_seasons.return_value = []
    mock_tmdb.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        library = scan_directories(
            [str(tmp_path)], existing_library=existing_library, force_refresh=True
        )

    assert library["Locked Show"]["metadata"]["tmdb_identifier"] == "locked_id"
    assert library["Locked Show"]["metadata"]["tmdb_name"] == "Locked Custom Title"
    assert library["Locked Show"]["metadata"]["overview"] == "Preserved overview"
    assert library["Locked Show"]["metadata"]["locked_metadata"] is True
    mock_tmdb.search_series.assert_not_called()
    mock_tmdb.get_series_by_id.assert_not_called()


def test_scan_directories_force_refresh_calls_tmdb_for_unlocked_series(
    tmp_path,
) -> None:
    """Test that scan_directories with force_refresh=True calls TMDB for unlocked series even if they already have metadata."""
    series_dir = tmp_path / "Unlocked Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Unlocked Show": {
            "metadata": {
                "tmdb_identifier": "unlocked_id",
                "tmdb_name": "Old Title",
                "overview": "Old overview",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "metadata": {"jellyfin_id": ""},
                    "episodes": [
                        {
                            "name": "S01E01 - Pilot",
                            "path": str(season_dir / "S01E01.mkv"),
                            "tmdb_number": 1,
                        }
                    ],
                }
            },
        }
    }

    mock_tmdb = MagicMock()
    mock_tmdb.get_series_by_id.return_value = {
        "id": "unlocked_id",
        "name": "Fresh Title",
        "overview": "Fresh overview",
    }
    mock_tmdb.get_seasons.return_value = [
        {"season_number": 1, "id": "s1_id", "poster_path": ""}
    ]
    mock_tmdb.get_episodes.return_value = [
        {"episode_number": 1, "name": "Pilot", "id": "ep1_id"},
        {"episode_number": 2, "name": "Episode 2", "id": "ep2_id"},
    ]
    mock_tmdb.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        library = scan_directories(
            [str(tmp_path)], existing_library=existing_library, force_refresh=True
        )

    mock_tmdb.get_series_by_id.assert_called_with("unlocked_id")
    mock_tmdb.get_episodes.assert_called_with("unlocked_id", 1)

    assert library["Unlocked Show"]["metadata"]["tmdb_name"] == "Fresh Title"
    episodes = library["Unlocked Show"]["seasons"]["Season 1"]["episodes"]
    assert len(episodes) == 2
    paths = [ep.get("path") for ep in episodes]
    assert None in paths


def test_scan_series_auto_refresh_new_files(tmp_path) -> None:
    series_dir = tmp_path / "AutoShow"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    new_file = season_dir / "S01E02.mkv"
    new_file.touch()

    existing_library = {
        "AutoShow": {
            "metadata": {
                "tmdb_identifier": "old_id",
                "tmdb_name": "Old Title",
                "overview": "Old overview",
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": str(season_dir / "S01E01.mkv"),
                        }
                    ]
                }
            },
        }
    }

    mock_tmdb = MagicMock()
    mock_tmdb.get_series_by_id.return_value = {
        "id": "old_id",
        "name": "Fresh Title",
        "overview": "Fresh overview",
    }
    mock_tmdb.get_seasons.return_value = []

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        res = scanner.scan_directories(
            [str(tmp_path)], existing_library=existing_library, force_refresh=False
        )

    assert res["AutoShow"]["metadata"]["tmdb_name"] == "Fresh Title"
    mock_tmdb.get_series_by_id.assert_called_once_with("old_id")


def test_scan_movie_auto_refresh_new_files(tmp_path) -> None:
    movie_dir = tmp_path / "Avatar (2009)"
    movie_dir.mkdir()
    new_file = movie_dir / "avatar_extended.mkv"
    new_file.touch()

    existing_library = {
        "Avatar (2009)": {
            "tmdb_identifier": "m_id",
            "tmdb_name": "Old Movie",
            "path": "/old/path/avatar.mkv",
        }
    }

    mock_tmdb = MagicMock()
    mock_tmdb.get_movie_by_id.return_value = {
        "id": "m_id",
        "title": "Fresh Avatar",
        "overview": "Fresh Avatar overview",
        "runtime": 162,
    }

    with (
        patch("lan_streamer.services.metadata_movie.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.scan_movie.tmdb_client", mock_tmdb),
    ):
        res = scanner.scan_directories(
            [str(tmp_path)],
            library_type="movie",
            existing_library=existing_library,
            force_refresh=False,
        )

    assert res["Avatar (2009)"]["tmdb_name"] == "Fresh Avatar"
    mock_tmdb.get_movie_by_id.assert_called_once_with("m_id")


def test_scan_movie_early_return_jellyfin_mapping(tmp_path) -> None:
    movie_dir = tmp_path / "Inception (2010)"
    movie_dir.mkdir()
    video_file = movie_dir / "inception.mkv"
    video_file.touch()
    video_path = str(video_file.absolute())

    existing_movie = {
        "path": video_path,
        "tmdb_identifier": "tmdb_inc",
        "tmdb_name": "Inception",
    }

    jellyfin_data = {
        "path_map": {video_path: {"id": "jf_inc_path"}},
        "tmdb_episode_map": {"tmdb_inc": "jf_inc_tmdb"},
    }

    res = scanner.scan_movie(
        movie_dir, existing_movie_data=existing_movie, jellyfin_data=jellyfin_data
    )
    assert res["jellyfin_id"] == "jf_inc_path"

    # Test tmdb map fallback when path not in map
    jellyfin_data_tmdb = {
        "path_map": {},
        "tmdb_episode_map": {"tmdb_inc": "jf_inc_tmdb"},
    }
    res2 = scanner.scan_movie(
        movie_dir, existing_movie_data=existing_movie, jellyfin_data=jellyfin_data_tmdb
    )
    assert res2["jellyfin_id"] == "jf_inc_tmdb"


def test_scan_series_early_return_jellyfin_mapping(tmp_path) -> None:
    series_dir = tmp_path / "Fast Series"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    ep_file = season_dir / "S01E01.mkv"
    ep_file.touch()
    ep_path = str(ep_file.absolute())

    def get_existing() -> dict:
        return {
            "metadata": {"tmdb_identifier": "tmdb_series_fast"},
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "path": ep_path,
                            "tmdb_identifier": "tmdb_ep_fast",
                            "tmdb_episode_identifier": "tmdb_ep_fast_id",
                        }
                    ]
                }
            },
        }

    jellyfin_data = {
        "tmdb_series_map": {"tmdb_series_fast": "jf_series_fast"},
        "path_map": {ep_path: {"id": "jf_ep_path"}},
        "tmdb_episode_map": {},
    }

    res = scanner.scan_series(
        series_dir, existing_series_data=get_existing(), jellyfin_data=jellyfin_data
    )
    assert res["metadata"]["jellyfin_id"] == "jf_series_fast"
    assert res["seasons"]["Season 1"]["episodes"][0]["jellyfin_id"] == "jf_ep_path"

    # Test episode map fallback via tmdb_identifier / tmdb_episode_identifier
    jellyfin_data_tmdb = {
        "tmdb_series_map": {},
        "path_map": {},
        "tmdb_episode_map": {"tmdb_ep_fast": "jf_ep_tmdb"},
    }
    res2 = scanner.scan_series(
        series_dir,
        existing_series_data=get_existing(),
        jellyfin_data=jellyfin_data_tmdb,
    )
    assert res2["seasons"]["Season 1"]["episodes"][0]["jellyfin_id"] == "jf_ep_tmdb"

    jellyfin_data_tmdb2 = {
        "tmdb_series_map": {},
        "path_map": {},
        "tmdb_episode_map": {"tmdb_ep_fast_id": "jf_ep_tmdb_id"},
    }
    existing_series_no_tmdb = {
        "metadata": {},
        "seasons": {
            "Season 1": {
                "episodes": [
                    {
                        "path": ep_path,
                        "tmdb_episode_identifier": "tmdb_ep_fast_id",
                    }
                ]
            }
        },
    }
    res3 = scanner.scan_series(
        series_dir,
        existing_series_data=existing_series_no_tmdb,
        jellyfin_data=jellyfin_data_tmdb2,
    )
    assert res3["seasons"]["Season 1"]["episodes"][0]["jellyfin_id"] == "jf_ep_tmdb_id"


def test_scan_directories_merge_existing_episodes(tmp_path) -> None:
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    for r in [root1, root2]:
        s = r / "Merged Show" / "Season 1"
        s.mkdir(parents=True)

    file1 = root1 / "Merged Show" / "Season 1" / "S01E01.mkv"
    file1.touch()
    file2 = root2 / "Merged Show" / "Season 1" / "S01E02.mkv"
    file2.touch()
    file3 = root2 / "Merged Show" / "Season 1" / "S01E01.mkv"  # exact name dup
    file3.touch()

    mock_tmdb = MagicMock()
    mock_tmdb.search_series.return_value = {"id": "m_id", "name": "Merged Show"}
    mock_tmdb.get_seasons.return_value = [{"season_number": 1, "id": "s1"}]
    mock_tmdb.get_episodes.return_value = [
        {"episode_number": 1, "id": "e1"},
        {"episode_number": 2, "id": "e2"},
    ]
    mock_tmdb.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        lib = scanner.scan_directories([str(root1), str(root2)])

    assert "Merged Show" in lib
    eps = lib["Merged Show"]["seasons"]["Season 1"]["episodes"]
    assert len(eps) >= 2


def test_scan_series_uses_cached_image(tmp_path) -> None:
    """Verify that cached posters are used directly without internet downloads."""
    series_dir = tmp_path / "Cached Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    mock_tmdb = MagicMock()
    mock_tmdb.search_series.return_value = {
        "id": "cached_id",
        "name": "Cached Show",
        "poster_path": "/remote.jpg",
    }
    mock_tmdb.get_seasons.return_value = [
        {"season_number": 1, "id": "season_cached_id", "poster_path": "/remote_s1.jpg"}
    ]
    mock_tmdb.get_episodes.return_value = [{"episode_number": 1, "id": "e1"}]

    def mock_get_cached(key: str) -> str:
        if "season" in key:
            return "/local_cache/season.jpg"
        return "/local_cache/series.jpg"

    mock_tmdb.get_cached_image.side_effect = mock_get_cached
    mock_tmdb.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        lib = scanner.scan_directories([str(tmp_path)])

    assert "Cached Show" in lib
    meta = lib["Cached Show"]["metadata"]
    assert meta["poster_path"] == "/local_cache/series.jpg"
    s_meta = lib["Cached Show"]["seasons"]["Season 1"]["metadata"]
    assert s_meta["poster_path"] == "/local_cache/season.jpg"
    mock_tmdb.download_image.assert_not_called()


def test_extract_video_runtime_ffprobe_success(tmp_path) -> None:
    from lan_streamer.scanner import _extract_video_runtime

    video_file = tmp_path / "test_video.mkv"
    video_file.touch()

    mock_completed_process = MagicMock()
    mock_completed_process.returncode = 0
    mock_completed_process.stdout = " 1234.56 \n"

    with patch("subprocess.run", return_value=mock_completed_process) as mock_run:
        runtime_minutes = _extract_video_runtime(str(video_file.absolute()))
        assert runtime_minutes == 21  # round(1234.56 / 60) = round(20.576) = 21
        mock_run.assert_called_once()


def test_extract_video_runtime_vlc_fallback(tmp_path) -> None:
    from lan_streamer.scanner import _extract_video_runtime

    video_file = tmp_path / "test_video_vlc.mkv"
    video_file.touch()

    # Make subprocess.run raise an Exception or returncode != 0 to trigger vlc fallback
    mock_completed_process = MagicMock()
    mock_completed_process.returncode = 1

    mock_media = MagicMock()
    mock_media.get_duration.return_value = 1500000  # 25 minutes in ms

    mock_instance = MagicMock()
    mock_instance.media_new.return_value = mock_media

    mock_vlc_module = MagicMock()
    mock_vlc_module.Instance.return_value = mock_instance

    with (
        patch("subprocess.run", return_value=mock_completed_process),
        patch.dict("sys.modules", {"vlc": mock_vlc_module}),
    ):
        runtime_minutes = _extract_video_runtime(str(video_file.absolute()))
        assert runtime_minutes == 25
        mock_media.parse.assert_called_once()


def test_extract_video_runtime_failure(tmp_path) -> None:
    from lan_streamer.scanner import _extract_video_runtime

    # Test nonexistent file
    assert _extract_video_runtime("") is None
    assert _extract_video_runtime("/nonexistent/file.mkv") is None

    video_file = tmp_path / "fail_video.mkv"
    video_file.touch()

    # Both ffprobe and vlc raise exceptions
    with (
        patch("subprocess.run", side_effect=Exception("ffprobe error")),
        patch.dict(
            "sys.modules",
            {"vlc": MagicMock(Instance=MagicMock(side_effect=Exception("vlc error")))},
        ),
    ):
        assert _extract_video_runtime(str(video_file.absolute())) is None


def test_get_ffprobe_command_path_resolved() -> None:
    from lan_streamer.scanner.file_property_scanner import _get_ffprobe_command

    _get_ffprobe_command.cache_clear()

    with patch("shutil.which", return_value="/usr/bin/ffprobe"):
        cmd = _get_ffprobe_command()
        assert cmd == "/usr/bin/ffprobe"


def test_get_ffprobe_command_mac_fallback() -> None:
    from lan_streamer.scanner.file_property_scanner import _get_ffprobe_command

    _get_ffprobe_command.cache_clear()

    # Mocks for os.path.exists
    def mock_exists(path: str) -> bool:
        return path == "/opt/homebrew/bin/ffprobe"

    with (
        patch("shutil.which", return_value=None),
        patch("os.path.exists", side_effect=mock_exists),
        patch("os.access", return_value=True),
    ):
        cmd = _get_ffprobe_command()
        assert cmd == "/opt/homebrew/bin/ffprobe"


def test_get_ffprobe_command_default() -> None:
    from lan_streamer.scanner.file_property_scanner import _get_ffprobe_command

    _get_ffprobe_command.cache_clear()

    with (
        patch("shutil.which", return_value=None),
        patch("os.path.exists", return_value=False),
    ):
        cmd = _get_ffprobe_command()
        assert cmd == "ffprobe"


# ---------------------------------------------------------------------------
# Granular unit tests for extracted scanner helper functions
# ---------------------------------------------------------------------------


def test_is_video_file_positive(tmp_path: Path) -> None:
    from lan_streamer.scanner import _is_video_file

    for ext in [".mkv", ".mp4", ".avi", ".mov", ".wmv"]:
        f = tmp_path / f"episode{ext}"
        f.touch()
        assert _is_video_file(f) is True


def test_is_video_file_negative(tmp_path: Path) -> None:
    from lan_streamer.scanner import _is_video_file

    text_file = tmp_path / "notes.txt"
    text_file.touch()
    assert _is_video_file(text_file) is False
    non_existent = tmp_path / "ghost.mkv"
    assert _is_video_file(non_existent) is False


def test_is_video_file_directory(tmp_path: Path) -> None:
    from lan_streamer.scanner import _is_video_file

    subdir = tmp_path / "Season 1"
    subdir.mkdir()
    assert _is_video_file(subdir) is False


def test_build_locked_tv_tmdb_stub() -> None:
    from lan_streamer.scanner import _build_locked_tv_tmdb_stub

    existing = {
        "metadata": {
            "tmdb_identifier": "tt_123",
            "tmdb_name": "Great Show",
            "overview": "A show.",
            "poster_path": "/p.jpg",
            "first_air_date": "2020-01-01",
        }
    }
    stub = _build_locked_tv_tmdb_stub(existing)
    assert stub["id"] == "tt_123"
    assert stub["name"] == "Great Show"
    assert stub["_is_prefetched"] is True


def test_build_locked_tv_tmdb_stub_empty() -> None:
    from lan_streamer.scanner import _build_locked_tv_tmdb_stub

    stub = _build_locked_tv_tmdb_stub({})
    assert stub["id"] is None
    assert stub["_is_prefetched"] is True


def test_build_locked_movie_tmdb_stub() -> None:
    from lan_streamer.scanner import _build_locked_movie_tmdb_stub

    existing = {
        "tmdb_identifier": "m_1",
        "tmdb_name": "Movie",
        "overview": "Desc.",
        "poster_path": "/p.jpg",
    }
    stub = _build_locked_movie_tmdb_stub(existing, "Movie (2020)")
    assert stub["id"] == "m_1"
    assert stub["title"] == "Movie"
    assert stub["_is_prefetched"] is True


def test_build_locked_movie_tmdb_stub_fallback_title() -> None:
    from lan_streamer.scanner import _build_locked_movie_tmdb_stub

    stub = _build_locked_movie_tmdb_stub({}, "Avatar (2009)")
    assert stub["title"] == "Avatar (2009)"
    assert stub["id"] is None


def test_resolve_existing_jellyfin_id_tv() -> None:
    from lan_streamer.scanner import _resolve_existing_jellyfin_id

    existing = {"metadata": {"jellyfin_id": "jf_series_abc"}}
    assert _resolve_existing_jellyfin_id(existing, "tv") == "jf_series_abc"


def test_resolve_existing_jellyfin_id_tv_missing() -> None:
    from lan_streamer.scanner import _resolve_existing_jellyfin_id

    assert _resolve_existing_jellyfin_id({}, "tv") is None
    assert _resolve_existing_jellyfin_id({"metadata": {}}, "tv") is None


def test_resolve_existing_jellyfin_id_movie() -> None:
    from lan_streamer.scanner import _resolve_existing_jellyfin_id

    existing = {"jellyfin_id": "jf_movie_xyz"}
    assert _resolve_existing_jellyfin_id(existing, "movie") == "jf_movie_xyz"


def test_resolve_existing_jellyfin_id_movie_empty_string() -> None:
    from lan_streamer.scanner import _resolve_existing_jellyfin_id

    assert _resolve_existing_jellyfin_id({"jellyfin_id": ""}, "movie") is None


def test_merge_season_episodes_new_episodes() -> None:
    from lan_streamer.scanner import _merge_season_episodes

    existing: list = [{"name": "S01E01.mkv", "path": "/a/S01E01.mkv"}]
    _merge_season_episodes(
        existing, [{"name": "S01E02.mkv", "path": "/a/S01E02.mkv"}], "Season 1"
    )
    assert len(existing) == 2


def test_merge_season_episodes_path_duplicate() -> None:
    from lan_streamer.scanner import _merge_season_episodes

    existing: list = [{"name": "S01E01.mkv", "path": "/a/S01E01.mkv"}]
    _merge_season_episodes(
        existing, [{"name": "S01E01.mkv", "path": "/a/S01E01.mkv"}], "Season 1"
    )
    assert len(existing) == 1


def test_merge_season_episodes_name_duplicate_skips() -> None:
    """When a new episode has the same name but different path, it is skipped."""
    from lan_streamer.scanner import _merge_season_episodes

    existing: list = [{"name": "S01E01.mkv", "path": "/a/S01E01.mkv"}]
    _merge_season_episodes(
        existing, [{"name": "S01E01.mkv", "path": "/b/S01E01.mkv"}], "Season 1"
    )
    # Episode count must not grow — name duplicate is rejected
    assert len(existing) == 1


def test_build_movie_metadata_defaults() -> None:
    from lan_streamer.scanner import _build_movie_metadata_defaults

    d = _build_movie_metadata_defaults()
    for key in (
        "tmdb_identifier",
        "overview",
        "poster_path",
        "tmdb_name",
        "jellyfin_id",
        "runtime",
        "rating",
        "genre",
        "year",
    ):
        assert key in d
    assert d["runtime"] == 0
    assert d["year"] == 0


def test_apply_existing_movie_metadata_copies_fields() -> None:
    from lan_streamer.scanner import (
        _build_movie_metadata_defaults,
        _apply_existing_movie_metadata,
    )

    metadata = _build_movie_metadata_defaults()
    _apply_existing_movie_metadata(
        metadata, {"tmdb_identifier": "old_id", "overview": "Desc", "runtime": 90}, None
    )
    assert metadata["tmdb_identifier"] == "old_id"
    assert metadata["runtime"] == 90


def test_apply_existing_movie_metadata_manual_jellyfin_id() -> None:
    from lan_streamer.scanner import (
        _build_movie_metadata_defaults,
        _apply_existing_movie_metadata,
    )

    metadata = _build_movie_metadata_defaults()
    _apply_existing_movie_metadata(
        metadata, {"jellyfin_id": "jf_original"}, "jf_manual"
    )
    assert metadata["jellyfin_id"] == "jf_manual"


def test_apply_existing_movie_metadata_ignores_falsy() -> None:
    from lan_streamer.scanner import (
        _build_movie_metadata_defaults,
        _apply_existing_movie_metadata,
    )

    metadata = _build_movie_metadata_defaults()
    metadata["tmdb_identifier"] = "keep_me"
    _apply_existing_movie_metadata(metadata, {"tmdb_identifier": ""}, None)
    assert metadata["tmdb_identifier"] == "keep_me"


def test_resolve_movie_jellyfin_id_no_data() -> None:
    from lan_streamer.scanner import _resolve_movie_jellyfin_id

    assert (
        _resolve_movie_jellyfin_id({"jellyfin_id": "existing"}, "/p.mkv", None)
        == "existing"
    )


def test_resolve_movie_jellyfin_id_path_map() -> None:
    from lan_streamer.scanner import _resolve_movie_jellyfin_id

    metadata = {"jellyfin_id": ""}
    jd = {"path_map": {"/path/movie.mkv": {"id": "jf_path"}}}
    assert _resolve_movie_jellyfin_id(metadata, "/path/movie.mkv", jd) == "jf_path"


def test_resolve_movie_jellyfin_id_tmdb_map() -> None:
    from lan_streamer.scanner import _resolve_movie_jellyfin_id

    metadata = {"jellyfin_id": "", "tmdb_identifier": "tmdb_99"}
    jd = {"path_map": {}, "tmdb_episode_map": {"tmdb_99": "jf_tmdb"}}
    assert _resolve_movie_jellyfin_id(metadata, "/p.mkv", jd) == "jf_tmdb"


def test_resolve_movie_jellyfin_id_no_match() -> None:
    from lan_streamer.scanner import _resolve_movie_jellyfin_id

    metadata = {"jellyfin_id": "preexisting", "tmdb_identifier": "unknown"}
    jd = {"path_map": {}, "tmdb_episode_map": {}}
    assert _resolve_movie_jellyfin_id(metadata, "/p.mkv", jd) == "preexisting"


def test_build_existing_episodes_index() -> None:
    from lan_streamer.scanner import _build_existing_episodes_index

    ep1 = {"path": "/a/S01E01.mkv", "name": "S01E01.mkv"}
    ep2 = {"path": "/a/S01E02.mkv", "name": "S01E02.mkv"}
    index = _build_existing_episodes_index(
        {"seasons": {"Season 1": {"episodes": [ep1, ep2]}}}
    )
    assert "/a/S01E01.mkv" in index
    assert index["/a/S01E01.mkv"] is ep1


def test_build_existing_episodes_index_empty() -> None:
    from lan_streamer.scanner import _build_existing_episodes_index

    assert _build_existing_episodes_index({}) == {}


def test_detect_new_series_files_finds_new(tmp_path: Path) -> None:
    from lan_streamer.scanner import _detect_new_series_files

    series_dir = tmp_path / "Show"
    (series_dir / "Season 1").mkdir(parents=True)
    (series_dir / "Season 1" / "S01E01.mkv").touch()
    assert _detect_new_series_files(series_dir, {}) is True


def test_detect_new_series_files_all_indexed(tmp_path: Path) -> None:
    from lan_streamer.scanner import _detect_new_series_files

    series_dir = tmp_path / "Show"
    (series_dir / "Season 1").mkdir(parents=True)
    f = series_dir / "Season 1" / "S01E01.mkv"
    f.touch()
    assert _detect_new_series_files(series_dir, {str(f.absolute()): {}}) is False


def test_build_series_metadata_defaults_all_keys() -> None:
    from lan_streamer.scanner import _build_series_metadata_defaults

    d = _build_series_metadata_defaults(None)
    for key in (
        "tmdb_identifier",
        "overview",
        "poster_path",
        "tmdb_name",
        "first_air_date",
        "jellyfin_id",
    ):
        assert key in d
    assert d["jellyfin_id"] == ""


def test_build_series_metadata_defaults_with_id() -> None:
    from lan_streamer.scanner import _build_series_metadata_defaults

    assert _build_series_metadata_defaults("jf_123")["jellyfin_id"] == "jf_123"


def test_resolve_series_poster_cached() -> None:
    from lan_streamer.scanner import _resolve_series_poster

    mock_tmdb = MagicMock()
    mock_tmdb.get_cached_image.return_value = "/cache/series.jpg"
    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        result = _resolve_series_poster({"poster_path": "/remote.jpg"}, "tmdb_1", None)
    assert result == "/cache/series.jpg"
    mock_tmdb.download_image.assert_not_called()


def test_resolve_series_poster_existing_local(tmp_path: Path) -> None:
    from lan_streamer.scanner import _resolve_series_poster

    local = tmp_path / "poster.jpg"
    local.touch()
    mock_tmdb = MagicMock()
    mock_tmdb.get_cached_image.return_value = ""
    existing = {"metadata": {"poster_path": str(local)}}
    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        result = _resolve_series_poster({"poster_path": ""}, "tmdb_2", existing)
    assert result == str(local)
    mock_tmdb.download_image.assert_not_called()


def test_resolve_series_poster_downloads() -> None:
    from lan_streamer.scanner import _resolve_series_poster

    mock_tmdb = MagicMock()
    mock_tmdb.get_cached_image.return_value = ""
    mock_tmdb.download_image.return_value = "/dl/series.jpg"
    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        result = _resolve_series_poster(
            {"poster_path": "/remote/poster.jpg"}, "tmdb_3", None
        )
    assert result == "/dl/series.jpg"
    mock_tmdb.download_image.assert_called_once()


def test_resolve_series_poster_no_poster() -> None:
    from lan_streamer.scanner import _resolve_series_poster

    mock_tmdb = MagicMock()
    mock_tmdb.get_cached_image.return_value = ""
    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        assert _resolve_series_poster({"poster_path": ""}, "tmdb_4", None) == ""


def test_resolve_series_poster_prefetched_local() -> None:
    from lan_streamer.scanner import _resolve_series_poster

    mock_tmdb = MagicMock()
    mock_tmdb.get_cached_image.return_value = ""
    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        result = _resolve_series_poster(
            {"poster_path": "local.jpg", "_is_prefetched": True}, "tmdb_5", None
        )
    assert result == "local.jpg"
    mock_tmdb.download_image.assert_not_called()


def test_resolve_episode_jellyfin_id_path_map() -> None:
    from lan_streamer.scanner import _resolve_episode_jellyfin_id

    series_data: dict = {"metadata": {"jellyfin_id": ""}}
    season_metadata: dict = {"jellyfin_id": ""}
    jf_id, series_jf, season_jf = _resolve_episode_jellyfin_id(
        episode_path="/shows/S01E01.mkv",
        episode_name="S01E01.mkv",
        episode_file=Path("/shows/S01E01.mkv"),
        tmdb_episode_identifier=None,
        tmdb_name=None,
        tmdb_number=None,
        season_name="Season 1",
        series_directory=Path("/shows"),
        series_data=series_data,
        season_metadata=season_metadata,
        tmdb_series=None,
        jellyfin_data={
            "path_map": {
                "/shows/S01E01.mkv": {
                    "id": "jf_ep_1",
                    "series_id": "jf_s",
                    "season_id": "jf_ss",
                }
            },
            "tmdb_episode_map": {},
        },
    )
    assert jf_id == "jf_ep_1"
    assert series_jf == "jf_s"
    assert season_jf == "jf_ss"


def test_resolve_episode_jellyfin_id_no_data() -> None:
    from lan_streamer.scanner import _resolve_episode_jellyfin_id

    jf_id, s, ss = _resolve_episode_jellyfin_id(
        episode_path="/p/ep.mkv",
        episode_name="ep.mkv",
        episode_file=Path("/p/ep.mkv"),
        tmdb_episode_identifier=None,
        tmdb_name=None,
        tmdb_number=None,
        season_name="Season 1",
        series_directory=Path("/p"),
        series_data={"metadata": {"jellyfin_id": ""}},
        season_metadata={"jellyfin_id": ""},
        tmdb_series=None,
        jellyfin_data=None,
    )
    assert jf_id == "" and s == "" and ss == ""


def test_resolve_episode_jellyfin_id_tmdb_map() -> None:
    from lan_streamer.scanner import _resolve_episode_jellyfin_id

    jf_id, _, _ = _resolve_episode_jellyfin_id(
        episode_path="/p/ep.mkv",
        episode_name="ep.mkv",
        episode_file=Path("/p/ep.mkv"),
        tmdb_episode_identifier="tmdb_ep_42",
        tmdb_name=None,
        tmdb_number=None,
        season_name="Season 1",
        series_directory=Path("/p"),
        series_data={"metadata": {"jellyfin_id": ""}},
        season_metadata={"jellyfin_id": ""},
        tmdb_series=None,
        jellyfin_data={
            "path_map": {},
            "tmdb_episode_map": {"tmdb_ep_42": "jf_ep_tmdb"},
        },
    )
    assert jf_id == "jf_ep_tmdb"


def test_resolve_episode_jellyfin_id_name_map() -> None:
    from lan_streamer.scanner import _resolve_episode_jellyfin_id

    jf_id, _, _ = _resolve_episode_jellyfin_id(
        episode_path="/p/Pilot.mkv",
        episode_name="Pilot.mkv",
        episode_file=Path("/p/Pilot.mkv"),
        tmdb_episode_identifier=None,
        tmdb_name="Pilot Episode",
        tmdb_number=1,
        season_name="Season 1",
        series_directory=Path("/shows/Great Show"),
        series_data={"metadata": {"jellyfin_id": ""}},
        season_metadata={"jellyfin_id": ""},
        tmdb_series={"name": "Great Show"},
        jellyfin_data={
            "path_map": {},
            "tmdb_episode_map": {},
            "name_map": {("great show", "pilot episode"): "jf_ep_name"},
        },
    )
    assert jf_id == "jf_ep_name"


def test_resolve_episode_jellyfin_id_series_id_map_sxxexx() -> None:
    from lan_streamer.scanner import _resolve_episode_jellyfin_id

    jf_id, _, _ = _resolve_episode_jellyfin_id(
        episode_path="/p/S01E03.mkv",
        episode_name="S01E03.mkv",
        episode_file=Path("/p/S01E03.mkv"),
        tmdb_episode_identifier=None,
        tmdb_name=None,
        tmdb_number=None,
        season_name="Season 1",
        series_directory=Path("/p"),
        series_data={"metadata": {"jellyfin_id": "jf_series_id"}},
        season_metadata={"jellyfin_id": ""},
        tmdb_series=None,
        jellyfin_data={
            "path_map": {},
            "tmdb_episode_map": {},
            "series_id_map": {
                "jf_series_id": {"episodes": {(1, 3): "jf_ep_s01e03"}, "names": {}}
            },
        },
    )
    assert jf_id == "jf_ep_s01e03"


# ---------------------------------------------------------------------------
# get_detailed_file_info
# ---------------------------------------------------------------------------


def test_get_detailed_file_info_missing_path() -> None:
    """Missing or empty path should return a dict with None values."""
    info = scanner.get_detailed_file_info("")
    assert info["size_bytes"] is None
    assert info["resolution"] is None
    assert info["audio_tracks"] == []

    info2 = scanner.get_detailed_file_info("/nonexistent/file.mkv")
    assert info2["size_bytes"] is None


def test_get_detailed_file_info_ffprobe_success(tmp_path: Path) -> None:
    """When ffprobe succeeds, resolution and track data should be populated."""
    import json

    video_file = tmp_path / "movie.mkv"
    video_file.write_bytes(b"\x00" * 16)  # Non-empty file

    ffprobe_output = json.dumps(
        {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "tags": {},
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "tags": {"language": "eng", "title": "English"},
                },
                {
                    "index": 2,
                    "codec_type": "subtitle",
                    "codec_name": "srt",
                    "tags": {"language": "spa", "title": "Spanish"},
                },
            ],
            "format": {},
        }
    )

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ffprobe_output

    with patch("subprocess.run", return_value=mock_result):
        info = scanner.get_detailed_file_info(str(video_file))

    assert info["resolution"] == "1920x1080"
    assert info["video_codec"] == "h264"
    assert len(info["audio_tracks"]) == 1
    assert info["audio_tracks"][0]["language"] == "eng"
    assert len(info["subtitle_tracks"]) == 1
    assert info["subtitle_tracks"][0]["language"] == "spa"


def test_get_detailed_file_info_ffprobe_exception(tmp_path: Path) -> None:
    """Exceptions from ffprobe should be swallowed; info dict returned with defaults."""

    video_file = tmp_path / "movie.mkv"
    video_file.write_bytes(b"\x00" * 16)

    with patch("subprocess.run", side_effect=OSError("ffprobe not found")):
        info = scanner.get_detailed_file_info(str(video_file))

    assert info["resolution"] is None
    assert info["audio_tracks"] == []


def test_get_detailed_file_info_ffprobe_nonzero_return(tmp_path: Path) -> None:
    """Non-zero ffprobe returncode should leave resolution as None."""

    video_file = tmp_path / "bad.mkv"
    video_file.write_bytes(b"\x00" * 8)

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch("subprocess.run", return_value=mock_result):
        info = scanner.get_detailed_file_info(str(video_file))

    assert info["resolution"] is None


# ---------------------------------------------------------------------------
# _extract_video_runtime
# ---------------------------------------------------------------------------


def test_extract_video_runtime_missing_file() -> None:
    """Empty path and non-existent path should return None."""
    from lan_streamer.scanner import _extract_video_runtime

    assert _extract_video_runtime("") is None
    assert _extract_video_runtime("/nonexistent/video.mkv") is None


def test_extract_video_runtime_ffprobe_success_explicit_minutes(tmp_path: Path) -> None:
    """Successful ffprobe output should be converted from seconds to minutes."""
    from lan_streamer.scanner import _extract_video_runtime

    video_file = tmp_path / "video.mkv"
    video_file.touch()

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "3660.0\n"  # 61 minutes

    with patch("subprocess.run", return_value=mock_result):
        runtime = _extract_video_runtime(str(video_file))

    assert runtime == 61


def test_extract_video_runtime_ffprobe_fails_vlc_fallback(tmp_path: Path) -> None:
    """When ffprobe fails, the function should fall back to vlc."""
    from lan_streamer.scanner import _extract_video_runtime

    video_file = tmp_path / "video.mkv"
    video_file.touch()

    ffprobe_result = MagicMock()
    ffprobe_result.returncode = 1
    ffprobe_result.stdout = ""

    mock_vlc = MagicMock()
    mock_instance = MagicMock()
    mock_media = MagicMock()
    mock_media.get_duration.return_value = 5400000  # 90 minutes in ms
    mock_instance.media_new.return_value = mock_media
    mock_vlc.Instance.return_value = mock_instance

    with (
        patch("subprocess.run", return_value=ffprobe_result),
        patch.dict("sys.modules", {"vlc": mock_vlc}),
    ):
        runtime = _extract_video_runtime(str(video_file))

    assert runtime == 90


def test_extract_video_runtime_both_fail(tmp_path: Path) -> None:
    """When both ffprobe and vlc fail, the function should return None."""
    from lan_streamer.scanner import _extract_video_runtime

    video_file = tmp_path / "video.mkv"
    video_file.touch()

    with (
        patch("subprocess.run", side_effect=FileNotFoundError("ffprobe not found")),
        patch.dict("sys.modules", {"vlc": None}),
    ):
        runtime = _extract_video_runtime(str(video_file))

    assert runtime is None


def test_scanner_additional_coverage(tmp_path: Path) -> None:
    from lan_streamer.scanner import scan_directories, _resolve_episode_jellyfin_id

    # 1. _resolve_episode_jellyfin_id names map match
    episode_file = tmp_path / "Avatar S01E01.mkv"
    episode_file.touch()
    jellyfin_data = {
        "series_id_map": {
            "jf_series_id": {"episodes": {}, "names": {"avatar": "jf_ep_avatar"}}
        }
    }
    jellyfin_id, new_series_id, new_season_id = _resolve_episode_jellyfin_id(
        episode_path=str(episode_file),
        episode_name="Avatar S01E01.mkv",
        episode_file=episode_file,
        tmdb_episode_identifier=None,
        tmdb_name="Avatar",
        tmdb_number=1,
        season_name="Season 1",
        series_directory=tmp_path,
        series_data={"metadata": {"jellyfin_id": "jf_series_id"}},
        season_metadata={},
        tmdb_series=None,
        jellyfin_data=jellyfin_data,
    )
    assert jellyfin_id == "jf_ep_avatar"

    # 2. Movie library with locked metadata
    movie_dir = tmp_path / "movies"
    movie_dir.mkdir()
    (movie_dir / "Inception").mkdir()
    (movie_dir / "Inception" / "Inception.mkv").touch()

    existing_library = {
        "Inception": {
            "tmdb_identifier": "tmdb_inception_123",
            "locked_metadata": True,
            "tmdb_name": "Inception (Locked)",
            "overview": "Overview",
            "poster_path": "poster.jpg",
            "year": 2010,
            "path": str(movie_dir / "Inception" / "Inception.mkv"),
        }
    }

    mock_tmdb = MagicMock()
    # Ensure tmdb search/get series are not called since they are locked
    with (
        patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.core.scan_movie") as mock_scan_movie,
    ):
        scan_directories(
            [str(movie_dir)], library_type="movie", existing_library=existing_library
        )
        # Should be called with tmdb_movie having build stub fields from existing
        mock_scan_movie.assert_called_once()
        called_args = mock_scan_movie.call_args[1]
        assert called_args["tmdb_movie"]["id"] == "tmdb_inception_123"
        assert called_args["tmdb_movie"]["title"] == "Inception (Locked)"

    # 3. Preserving missing season folder when cleanup is False
    from lan_streamer.scanner import scan_series

    show_dir = tmp_path / "My Show"
    show_dir.mkdir()
    # On disk we only have Season 2
    (show_dir / "Season 2").mkdir()
    (show_dir / "Season 2" / "S02E01.mkv").touch()

    # In DB we have Season 1 and Season 2
    existing_series_data = {
        "metadata": {"tmdb_identifier": "show123", "tmdb_name": "My Show"},
        "seasons": {
            "Season 1": {
                "metadata": {},
                "episodes": [{"name": "S01E01.mkv", "path": "/path/to/S01E01.mkv"}],
            },
            "Season 2": {
                "metadata": {},
                "episodes": [
                    {
                        "name": "S02E01.mkv",
                        "path": str(show_dir / "Season 2" / "S02E01.mkv"),
                    }
                ],
            },
        },
    }

    mock_tmdb_series = MagicMock()
    mock_tmdb_series.get_seasons.return_value = []
    mock_tmdb_series.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb_series):
        scanned_data = scan_series(
            series_directory=show_dir,
            existing_series_data=existing_series_data,
            cleanup=False,
        )
        # Season 1 should be preserved since cleanup=False
        assert "Season 1" in scanned_data["seasons"]
        assert len(scanned_data["seasons"]["Season 1"]["episodes"]) == 1


def test_scan_directories_skips_empty_folders(tmp_path) -> None:
    """Verify that scan_directories completely skips directories without video files."""
    from lan_streamer.scanner import has_video_files

    # 1. Test has_video_files helper
    empty_dir = tmp_path / "EmptyDir"
    empty_dir.mkdir()
    assert not has_video_files(empty_dir)

    non_video_dir = tmp_path / "NonVideoDir"
    non_video_dir.mkdir()
    (non_video_dir / "file.txt").touch()
    (non_video_dir / "image.jpg").touch()
    assert not has_video_files(non_video_dir)

    video_dir = tmp_path / "VideoDir"
    video_dir.mkdir()
    (video_dir / "movie.mp4").touch()
    assert has_video_files(video_dir)

    nested_video_dir = tmp_path / "NestedVideoDir"
    nested_video_dir.mkdir()
    (nested_video_dir / "Season 1").mkdir()
    (nested_video_dir / "Season 1" / "ep1.mkv").touch()
    assert has_video_files(nested_video_dir)

    # 2. Test scan_directories skips empty/non-video directories for TV libraries
    mock_tmdb = MagicMock()
    mock_tmdb.search_series.return_value = {
        "id": "1",
        "tmdb_identifier": "1",
        "overview": "desc",
        "poster_path": "",
    }
    mock_tmdb.get_series_by_id.return_value = {
        "id": "1",
        "tmdb_identifier": "1",
        "overview": "desc",
        "poster_path": "",
    }
    mock_tmdb.get_seasons.return_value = []
    mock_tmdb.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        library = scan_directories([str(tmp_path)], library_type="tv")

    # NestedVideoDir contains a Season folder with video file
    assert "NestedVideoDir" in library
    assert "EmptyDir" not in library
    assert "NonVideoDir" not in library
    # VideoDir contains a video file directly, but for TV libraries it lacks Season subfolders,
    # so clean_series_data returns None for it.
    assert "VideoDir" not in library

    # 3. Test for movie library
    mock_tmdb_movie = MagicMock()
    mock_tmdb_movie.search_movie.return_value = {
        "id": "2",
        "title": "VideoDir",
        "tmdb_identifier": "2",
        "overview": "desc",
        "poster_path": "",
    }
    mock_tmdb_movie.get_movie_by_id.return_value = {
        "id": "2",
        "title": "VideoDir",
        "tmdb_identifier": "2",
        "overview": "desc",
        "poster_path": "",
    }
    mock_tmdb_movie.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_movie.tmdb_client", mock_tmdb_movie):
        library_movies = scan_directories([str(tmp_path)], library_type="movie")

    assert "VideoDir" in library_movies
    assert "NestedVideoDir" in library_movies
    assert "EmptyDir" not in library_movies
    assert "NonVideoDir" not in library_movies


def test_scan_series_warns_on_files_outside_seasons(tmp_path) -> None:
    """Verify that scan_series logs a warning when there are video files outside of season/specials folders."""
    series_dir = tmp_path / "MyShow"
    series_dir.mkdir()
    # Create a video file directly in the root of the series
    (series_dir / "MyShow - S01E01.mkv").touch()

    # Also create a valid season directory with a video file (to make sure it scans)
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "MyShow - S01E02.mkv").touch()

    mock_tmdb = MagicMock()
    mock_tmdb.search_series.return_value = {
        "id": "1",
        "name": "MyShow",
        "tmdb_identifier": "1",
        "overview": "desc",
        "poster_path": "",
    }
    mock_tmdb.get_seasons.return_value = []

    with (
        patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.logger.warning") as mock_warn,
    ):
        scanner.scan_series(series_dir)

        # Verify logger.warning was called
        mock_warn.assert_any_call(
            "Series 'MyShow' has 1 video file(s) outside of season or specials/extras folders. "
            "Example: 'MyShow - S01E01.mkv'"
        )


def test_scan_series_warns_on_nested_too_deep_files(tmp_path) -> None:
    """Verify that scan_series logs a warning when there are video files nested too deeply under season folders."""
    series_dir = tmp_path / "MyShow"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    # Create an immediate child episode (so it passes normal scanner paths)
    (season_dir / "MyShow - S01E01.mkv").touch()

    # Create a nested subdirectory and a video file inside it
    nested_dir = season_dir / "Featurettes"
    nested_dir.mkdir()
    (nested_dir / "Menu Art.mkv").touch()

    mock_tmdb = MagicMock()
    mock_tmdb.search_series.return_value = {
        "id": "1",
        "name": "MyShow",
        "tmdb_identifier": "1",
        "overview": "desc",
        "poster_path": "",
    }
    mock_tmdb.get_seasons.return_value = []

    with (
        patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.logger.warning") as mock_warn,
    ):
        scanner.scan_series(series_dir)

        # Verify logger.warning was called for the nested file
        mock_warn.assert_any_call(
            "Series 'MyShow' has 1 video file(s) nested too deeply inside season folders. "
            "These files will not be indexed. "
            "Example: 'Season 1/Featurettes/Menu Art.mkv'"
        )
        # Verify logger.warning was called for ignoring subdirectory
        mock_warn.assert_any_call(
            "Ignoring subdirectory in season folder: 'Season 1/Featurettes'"
        )


def test_get_detailed_file_info_and_runtime_worker(tmp_path) -> None:
    """Verify that get_detailed_file_info parses technical metadata and FilePropertyExtractionWorker saves it to the DB."""
    import json
    from lan_streamer.scanner import get_detailed_file_info
    from lan_streamer.backend import FilePropertyExtractionWorker
    import lan_streamer.db as db

    video_file = tmp_path / "detailed_video.mkv"
    video_file.touch()

    # Mock ffprobe JSON output
    mock_ffprobe_data = {
        "format": {
            "duration": "3600.00"  # 60 minutes
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
            },
            {
                "codec_type": "audio",
                "codec_name": "ac3",
                "index": 1,
                "tags": {"language": "eng", "title": "Surround 5.1"},
            },
            {
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "index": 2,
                "tags": {"language": "eng", "title": "English SDH"},
            },
        ],
    }

    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = json.dumps(mock_ffprobe_data)

    with patch("subprocess.run", return_value=mock_process) as mock_run:
        info = get_detailed_file_info(str(video_file.absolute()))
        assert info["runtime"] == 60
        assert info["video_codec"] == "hevc"
        assert info["resolution"] == "3840x2160"
        assert len(info["audio_tracks"]) == 1
        assert info["audio_tracks"][0]["codec"] == "ac3"
        assert len(info["subtitle_tracks"]) == 1
        assert info["subtitle_tracks"][0]["language"] == "eng"
        mock_run.assert_called_once()

    # Now let's test that the RuntimeExtractionWorker updates the database with these fields
    # First, insert a movie and an episode missing runtime
    with db.get_session() as session:
        # Clear any existing movies/episodes
        session.query(db.Episode).delete()
        session.query(db.Movie).delete()
        session.query(db.Season).delete()
        session.query(db.Series).delete()

        series = db.Series(library_name="TV Shows", name="Test Show")
        session.add(series)
        session.flush()

        season = db.Season(series_id=series.id, name="Season 1")
        session.add(season)
        session.flush()

        episode = db.Episode(
            season_id=season.id,
            name="S01E01",
            path=str(video_file.absolute()),
            runtime=0,
        )
        session.add(episode)

        movie = db.Movie(
            library_name="Movies",
            name="Test Movie",
            path=str(video_file.absolute()) + ".movie.mkv",
            runtime=0,
        )
        session.add(movie)
        session.commit()

        episode_id = episode.id
        movie_id = movie.id
        season_id = season.id

    # Touch the movie file too so it exists
    Path(str(video_file.absolute()) + ".movie.mkv").touch()

    # Mock get_items_missing_runtime to return our test items
    with patch("lan_streamer.db.get_items_missing_runtime") as mock_get_missing:
        mock_get_missing.return_value = [
            {
                "id": episode_id,
                "path": str(video_file.absolute()),
                "type": "episode",
                "season_id": season_id,
            },
            {
                "id": movie_id,
                "path": str(video_file.absolute()) + ".movie.mkv",
                "type": "movie",
            },
        ]

        worker = FilePropertyExtractionWorker()

        # Mock subprocess.run inside the worker's run thread
        with patch("subprocess.run", return_value=mock_process):
            worker.run()

    # Verify that the database now has the runtime and technical metadata populated
    with db.get_session() as session:
        db_episode = session.get(db.Episode, episode_id)
        assert db_episode.file_runtime == 60
        assert db_episode.video_codec == "hevc"
        assert db_episode.resolution == "3840x2160"

        db_movie = session.get(db.Movie, movie_id)
        assert db_movie.file_runtime == 60
        assert db_movie.video_codec == "hevc"
        assert db_movie.resolution == "3840x2160"

        # Verify JSON decoding
        ep_dict = db._build_episode_dict(db_episode)
        assert len(ep_dict["audio_tracks"]) == 1
        assert ep_dict["audio_tracks"][0]["title"] == "Surround 5.1"
        assert len(ep_dict["subtitle_tracks"]) == 1
        assert ep_dict["subtitle_tracks"][0]["title"] == "English SDH"


# ---------------------------------------------------------------------------
# Movie Scanner Tests (from tests/test_movies.py)
# ---------------------------------------------------------------------------


def test_parse_movie_folder() -> None:
    from lan_streamer.scanner.core import _parse_movie_folder

    assert _parse_movie_folder("Avatar (2009)") == ("Avatar", 2009)
    assert _parse_movie_folder("The Godfather (1972)") == ("The Godfather", 1972)
    assert _parse_movie_folder("No Year Movie") == ("No Year Movie", None)


def test_scan_movie_no_video(tmp_path: Path) -> None:
    from lan_streamer.scanner.core import scan_movie

    movie_dir = tmp_path / "Empty Movie (2020)"
    movie_dir.mkdir()
    assert scan_movie(movie_dir) is None


def test_scan_movie_success(tmp_path: Path) -> None:
    from lan_streamer.scanner.core import scan_movie

    movie_dir = tmp_path / "Avatar (2009)"
    movie_dir.mkdir()
    video_file = movie_dir / "Avatar.mkv"
    video_file.touch()

    mock_tmdb = MagicMock()
    mock_tmdb.search_movie.return_value = {
        "id": 19995,
        "title": "Avatar",
        "overview": "On the lush alien world of Pandora...",
        "poster_path": "/avatar.jpg",
        "release_date": "2009-12-15",
        "runtime": 162,
        "vote_average": 7.9,
        "genres": [{"name": "Action"}, {"name": "Adventure"}],
    }
    mock_tmdb.download_image.return_value = "/cached/avatar.jpg"

    with (
        patch("lan_streamer.services.metadata_movie.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.scan_movie.tmdb_client", mock_tmdb),
    ):
        res = scan_movie(movie_dir)

    assert res is not None
    assert res["name"] == "Avatar (2009)"
    assert res["path"] == str(video_file.absolute())
    assert res["tmdb_identifier"] == "19995"
    assert res["tmdb_name"] == "Avatar"
    assert res["overview"] == "On the lush alien world of Pandora..."
    assert res["poster_path"] == "/cached/avatar.jpg"
    assert res["runtime"] == 162
    assert res["rating"] == "7.9"
    assert res["genre"] == "Action, Adventure"
    assert res["year"] == 2009
    assert res["watched"] is False


def test_scan_movie_reuse_existing(tmp_path: Path) -> None:
    from lan_streamer.scanner.core import scan_movie

    movie_dir = tmp_path / "Pulp Fiction (1994)"
    movie_dir.mkdir()
    video_file = movie_dir / "Pulp Fiction.mkv"
    video_file.touch()

    existing_data = {
        "tmdb_identifier": "680",
        "tmdb_name": "Pulp Fiction",
        "overview": "A burger-loving hit man...",
        "poster_path": "/pulp.jpg",
        "runtime": 154,
        "rating": "8.5",
        "genre": "Crime",
        "year": 1994,
        "watched": True,
        "last_played_position": 500,
        "locked_metadata": True,
    }

    with patch("lan_streamer.services.metadata_movie.tmdb_client") as mock_tmdb:
        res = scan_movie(
            movie_dir, existing_movie_data=existing_data, force_refresh=False
        )

        assert res is not None
        assert res["tmdb_identifier"] == "680"
        assert res["tmdb_name"] == "Pulp Fiction"
        assert res["watched"] is True
        assert res["last_played_position"] == 500
        assert res["locked_metadata"] is True
        mock_tmdb.search_movie.assert_not_called()


def test_scan_movie_jellyfin_correlation(tmp_path: Path) -> None:
    from lan_streamer.scanner.core import scan_movie

    movie_dir = tmp_path / "Correlated Movie (2021)"
    movie_dir.mkdir()
    video_file = movie_dir / "Movie.mp4"
    video_file.touch()

    jellyfin_data = {"path_map": {str(video_file.absolute()): {"id": "jf_movie_123"}}}

    mock_tmdb = MagicMock()
    mock_tmdb.search_movie.return_value = {"id": 101, "title": "Correlated Movie"}

    with patch("lan_streamer.services.metadata_movie.tmdb_client", mock_tmdb):
        res = scan_movie(movie_dir, jellyfin_data=jellyfin_data)

    assert res is not None
    assert res["jellyfin_id"] == "jf_movie_123"


def test_scan_movie_uses_cached_image(tmp_path: Path) -> None:
    """Verify that scan_movie prioritizes cached movie posters."""
    from lan_streamer.scanner.core import scan_movie

    movie_dir = tmp_path / "Cached Movie (2026)"
    movie_dir.mkdir()
    (movie_dir / "video.mkv").touch()

    mock_tmdb = MagicMock()
    mock_tmdb.search_movie.return_value = {
        "id": 999,
        "title": "Cached Movie",
        "poster_path": "/remote_movie.jpg",
    }
    mock_tmdb.get_cached_image.return_value = "/local_cache/movie.jpg"
    mock_tmdb.download_image.return_value = ""

    with (
        patch("lan_streamer.services.metadata_movie.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.scan_movie.tmdb_client", mock_tmdb),
    ):
        res = scan_movie(movie_dir)

    assert res["poster_path"] == "/local_cache/movie.jpg"
    mock_tmdb.download_image.assert_not_called()


def test_movie_scanner_flat_dict_integration() -> None:
    from lan_streamer.scanner.core import scan_directories
    from lan_streamer.system.config import config
    from lan_streamer.ui_views import Controller

    config.libraries["TestMovieLibrary"] = {"type": "movie", "paths": []}

    # Simulate flat structure generated by scan_movie
    simulated_library: dict[str, Any] = {
        "Inception (2010)": {
            "name": "Inception (2010)",
            "path": "/movies/Inception/Inception.mkv",
            "jellyfin_id": "jf_inc",
            "tmdb_identifier": "27205",
            "poster_path": "/posters/inc.jpg",
            "overview": "A thief who steals corporate secrets...",
            "tmdb_name": "Inception",
            "locked_metadata": True,
            "date_added": 123456,
            "runtime": 148,
            "rating": "8.8",
            "genre": "Action, Sci-Fi",
            "year": 2010,
            "watched": True,
            "last_played_position": 0,
        }
    }

    res: dict[str, Any] = scan_directories(
        root_directories=[],
        library_type="movie",
        existing_library=simulated_library,
        force_refresh=False,
    )

    assert "Inception (2010)" in res
    assert res["Inception (2010)"]["locked_metadata"] is True
    assert "seasons" not in res["Inception (2010)"]

    controller = Controller()
    controller.current_library_name = "TestMovieLibrary"
    controller.cached_library_data = res
    controller._cache_series_metrics()

    metrics: dict[str, Any] = res["Inception (2010)"]["metrics"]
    assert metrics["total_episodes"] == 1
    assert metrics["watched_episodes"] == 1
    assert metrics["max_air_date"] == "2010"

    emitted_movies: list[str] = []
    controller.movie_selected.connect(emitted_movies.append)
    controller.selected_series_name = "Inception (2010)"

    with patch("lan_streamer.db.update_episode_watched_status"):
        controller.mark_episode_watched("/movies/Inception/Inception.mkv", False)

    assert emitted_movies == []
    assert res["Inception (2010)"]["watched"] is False


# ---------------------------------------------------------------------------
# Scanner Lock / Optimization Tests (from tests/test_metadata_optimization.py)
# ---------------------------------------------------------------------------


def test_scanner_respects_lock_metadata(tmp_path):
    from lan_streamer.scanner.core import scan_directories

    series_dir = tmp_path / "Locked Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Locked Show": {
            "metadata": {
                "tmdb_identifier": "locked_id",
                "tmdb_name": "Locked Title",
                "locked_metadata": True,
            },
            "seasons": {},
        }
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.get_seasons.return_value = []
        res = scan_directories(
            [str(tmp_path)], existing_library=existing_library, force_refresh=True
        )

        assert res["Locked Show"]["metadata"]["tmdb_name"] == "Locked Title"
        mock_tmdb.search_series.assert_not_called()
        mock_tmdb.get_series_by_id.assert_not_called()


def test_scanner_skips_tmdb_during_global_scan(tmp_path):
    from lan_streamer.scanner.core import scan_directories

    series_dir = tmp_path / "Existing Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Existing Show": {
            "metadata": {
                "tmdb_identifier": "existing_id",
                "tmdb_name": "Existing Title",
                "locked_metadata": False,
            },
            "seasons": {
                "Season 1": {
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": str(season_dir / "S01E01.mkv"),
                        }
                    ]
                }
            },
        }
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        res = scan_directories(
            [str(tmp_path)],
            existing_library=existing_library,
            force_refresh=False,
            single_item_refresh=False,
        )

        assert res["Existing Show"]["metadata"]["tmdb_name"] == "Existing Title"
        mock_tmdb.search_series.assert_not_called()
        mock_tmdb.get_series_by_id.assert_not_called()


def test_scanner_queries_tmdb_when_single_item_refresh_true(tmp_path):
    from lan_streamer.scanner.core import scan_directories

    series_dir = tmp_path / "Refresh Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    existing_library = {
        "Refresh Show": {
            "metadata": {
                "tmdb_identifier": "refresh_id",
                "tmdb_name": "Old Title",
                "locked_metadata": False,
            },
            "seasons": {},
        }
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.get_series_by_id.return_value = {
            "id": "refresh_id",
            "name": "Fresh Title",
            "overview": "Fresh overview",
        }
        mock_tmdb.get_seasons.return_value = []
        res = scan_directories(
            [str(tmp_path)],
            existing_library=existing_library,
            force_refresh=True,
            single_item_refresh=True,
        )

        assert res["Refresh Show"]["metadata"]["tmdb_name"] == "Fresh Title"
        mock_tmdb.get_series_by_id.assert_called_once_with("refresh_id")


def test_scan_series_show_future_episodes(tmp_path) -> None:
    from lan_streamer.scanner import scan_series
    import datetime

    series_dir = tmp_path / "Future Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "Future Show S01E01.mkv"
    episode_file.touch()

    today = datetime.date.today()
    past_date = (today - datetime.timedelta(days=5)).isoformat()
    future_date = (today + datetime.timedelta(days=5)).isoformat()

    with patch("lan_streamer.services.metadata_tv.tmdb_client") as mock_tmdb:
        mock_tmdb.is_configured.return_value = True
        mock_tmdb.search_series.return_value = {
            "id": "series123",
            "tmdb_identifier": "series123",
            "name": "Future Show",
            "overview": "A future show",
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
        # TMDB returns:
        # S01E01 (aired past, exists locally)
        # S01E02 (aired past, missing locally)
        # S01E03 (aired future, missing locally)
        mock_tmdb.get_episodes.return_value = [
            {
                "id": "ep1",
                "episode_number": 1,
                "name": "Episode 1",
                "air_date": past_date,
            },
            {
                "id": "ep2",
                "episode_number": 2,
                "name": "Episode 2",
                "air_date": past_date,
            },
            {
                "id": "ep3",
                "episode_number": 3,
                "name": "Episode 3",
                "air_date": future_date,
            },
        ]
        mock_tmdb.download_image.return_value = ""

        # Test with show_future_episodes=True (default)
        res_true = scan_series(series_dir, show_future_episodes=True)
        eps_true = res_true["seasons"]["Season 1"]["episodes"]
        assert len(eps_true) == 3
        assert any(e["tmdb_number"] == 1 for e in eps_true)
        assert any(e["tmdb_number"] == 2 for e in eps_true)
        assert any(e["tmdb_number"] == 3 for e in eps_true)

        # Test with show_future_episodes=False
        res_false = scan_series(series_dir, show_future_episodes=False)
        eps_false = res_false["seasons"]["Season 1"]["episodes"]
        assert len(eps_false) == 2
        assert any(e["tmdb_number"] == 1 for e in eps_false)
        assert any(e["tmdb_number"] == 2 for e in eps_false)
        assert not any(e["tmdb_number"] == 3 for e in eps_false)


def test_scan_series_preserves_only_past_missing_episodes(tmp_path) -> None:
    from lan_streamer.scanner import scan_series
    import datetime

    series_dir = tmp_path / "Preserve Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").touch()

    today = datetime.date.today()
    past_date = (today - datetime.timedelta(days=5)).isoformat()
    future_date = (today + datetime.timedelta(days=5)).isoformat()

    existing_series = {
        "metadata": {
            "tmdb_identifier": "series123",
            "tmdb_name": "Preserve Show",
        },
        "seasons": {
            "Season 1": {
                "metadata": {},
                "episodes": [
                    {
                        "name": "S01E01.mkv",
                        "path": str((season_dir / "S01E01.mkv").absolute()),
                        "tmdb_number": 1,
                    },
                    {
                        "name": "S01E02 - TBA",
                        "path": None,
                        "tmdb_number": 2,
                        "air_date": past_date,
                    },
                    {
                        "name": "S01E03 - TBA",
                        "path": None,
                        "tmdb_number": 3,
                        "air_date": future_date,
                    },
                ],
            }
        },
    }

    with patch("lan_streamer.services.metadata_tv.tmdb_client"):
        # Simulate scanning with show_future_episodes=False to verify preservation filter
        res = scan_series(
            series_dir,
            existing_series_data=existing_series,
            show_future_episodes=False,
            force_refresh=False,
        )
        eps = res["seasons"]["Season 1"]["episodes"]
        assert len(eps) == 2
        assert any(e["tmdb_number"] == 1 for e in eps)
        assert any(e["tmdb_number"] == 2 for e in eps)
        assert not any(e["tmdb_number"] == 3 for e in eps)


def test_save_library_prunes_placeholders() -> None:
    from lan_streamer.db.library import save_library
    from lan_streamer.db.models import Series, Season, Episode

    mock_session = MagicMock()
    mock_series = Series(library_name="TestLib", name="TestShow")
    mock_season = Season(name="Season 1", series=mock_series)

    # Let's create two episode DB records:
    # 1. Ep 1 (a local episode with a path)
    # 2. Ep 2 (a placeholder episode with path = None)
    ep1_db = Episode(path="/path/to/ep1.mkv", season=mock_season, tmdb_number=1)
    ep2_db = Episode(path=None, season=mock_season, tmdb_number=2)
    mock_season.episodes = [ep1_db, ep2_db]

    # Incoming scan only has ep1 (no placeholder for ep2)
    library_data = {
        "TestShow": {
            "metadata": {"tmdb_identifier": "123"},
            "seasons": {
                "Season 1": {
                    "metadata": {},
                    "episodes": [
                        {
                            "name": "S01E01.mkv",
                            "path": "/path/to/ep1.mkv",
                            "tmdb_number": 1,
                        }
                    ],
                }
            },
        }
    }

    with (
        patch("lan_streamer.db.library_tv.get_session") as mock_get_session,
        patch(
            "lan_streamer.db.library_tv._save_series_record", return_value=mock_series
        ),
        patch(
            "lan_streamer.db.library_tv._save_season_record", return_value=mock_season
        ),
        patch("lan_streamer.db.library_tv._save_episode_record") as mock_save_ep_rec,
        patch("lan_streamer.db.library_tv.inspect") as mock_inspect,
    ):
        mock_get_session.return_value.__enter__.return_value = mock_session
        mock_session.scalars.return_value.all.return_value = [mock_series]
        mock_inspect.return_value.key = ("Episode", (2,))

        save_library("TestLib", library_data)

        # Verify mock_save_ep_rec was called for ep1
        assert mock_save_ep_rec.called
        # Verify mock_session.delete was called for the leftover placeholder (ep2_db)
        mock_session.delete.assert_called_once_with(ep2_db)


def test_scan_series_with_episode_groups(tmp_path) -> None:
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Group Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    episode_file = season_dir / "Group Show S01E01.mkv"
    episode_file.touch()

    # Episode Group details representing TVDB / Season-based ordering where the TMDB id matches,
    # mapping group episode order to episode_number.
    mock_group_details = {
        "id": "group-id-123",
        "name": "TVDB Seasons",
        "groups": [
            {
                "name": "Season 1",
                "order": 1,
                "episodes": [
                    {
                        "id": "ep-999",
                        "name": "Episode from Group Details",
                        "order": 0,
                        "season_number": 1,
                        "episode_number": 5,  # absolute number, but group order is 0 (first ep)
                        "air_date": "2020-01-01",
                        "runtime": 45,
                    }
                ],
            }
        ],
    }

    mock_tmdb = MagicMock()
    mock_tmdb.is_configured.return_value = True
    mock_tmdb.search_series.return_value = {
        "id": "series123",
        "tmdb_identifier": "series123",
        "name": "Group Show",
        "overview": "A group show",
        "poster_path": "",
    }
    mock_tmdb.get_season_based_episode_group.return_value = mock_group_details
    mock_tmdb.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        res = scan_series(series_dir, force_refresh=True)

    # Bypassed standard seasons and episodes endpoints
    mock_tmdb.get_seasons.assert_not_called()
    mock_tmdb.get_episodes.assert_not_called()

    # Metadata seasons resolved from groups
    assert "Season 1" in res["seasons"]
    eps = res["seasons"]["Season 1"]["episodes"]
    assert len(eps) == 1
    assert eps[0]["tmdb_name"] == "Episode from Group Details"
    # Order inside the group becomes tmdb_number
    assert eps[0]["tmdb_number"] == 1
    assert eps[0]["tmdb_episode_identifier"] == "ep-999"


def test_scan_series_myanimelist_auto_mapping(tmp_path) -> None:
    from lan_streamer.scanner import scan_series

    series_dir = tmp_path / "Anime Show"
    series_dir.mkdir()
    season_dir = series_dir / "Season 1"
    season_dir.mkdir()
    ep1_file = season_dir / "S01E01.mkv"
    ep2_file = season_dir / "S01E02.mkv"
    ep1_file.touch()
    ep2_file.touch()

    # S01E01 is an existing episode. S01E02 is a new episode.
    existing_series = {
        "metadata": {
            "tmdb_identifier": "anime_series_id",
            "tmdb_name": "Anime Show",
        },
        "seasons": {
            "Season 1": {
                "metadata": {
                    "myanimelist_id": 12345,
                },
                "episodes": [
                    {
                        "name": "S01E01.mkv",
                        "path": str(ep1_file.absolute()),
                        "tmdb_identifier": "tmdb_ep_1",
                        "tmdb_episode_identifier": "tmdb_ep_1",
                        "tmdb_number": 1,
                        "myanimelist_anime_id": 12345,
                        "myanimelist_episode_number": 1,
                    }
                ],
            }
        },
    }

    mock_tmdb = MagicMock()
    mock_tmdb.is_configured.return_value = True
    mock_tmdb.get_series_by_id.return_value = {
        "id": "anime_series_id",
        "name": "Anime Show",
    }
    mock_tmdb.get_seasons.return_value = [{"season_number": 1, "id": "season_1_id"}]
    # Return three episodes to force a placeholder for episode 3
    mock_tmdb.get_episodes.return_value = [
        {"id": "tmdb_ep_1", "episode_number": 1, "name": "Episode 1"},
        {"id": "tmdb_ep_2", "episode_number": 2, "name": "Episode 2"},
        {"id": "tmdb_ep_3", "episode_number": 3, "name": "Episode 3"},
    ]
    mock_tmdb.download_image.return_value = ""

    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        res = scan_series(
            series_dir, existing_series_data=existing_series, force_refresh=True
        )

    # 1. Season myanimelist_id should be preserved
    assert res["seasons"]["Season 1"]["metadata"]["myanimelist_id"] == 12345

    eps = res["seasons"]["Season 1"]["episodes"]
    # Sort them by name/number to be sure
    eps.sort(key=lambda x: x.get("tmdb_number") or 0)

    assert len(eps) == 3

    # 2. Existing S01E01 mapping should be preserved
    assert eps[0]["name"] == "S01E01.mkv"
    assert eps[0]["myanimelist_anime_id"] == 12345
    assert eps[0]["myanimelist_episode_number"] == 1

    # 3. New S01E02 should be automatically mapped using season's myanimelist_id
    assert eps[1]["name"] == "S01E02.mkv"
    assert eps[1]["myanimelist_anime_id"] == 12345
    assert eps[1]["myanimelist_episode_number"] == 2

    # 4. Placeholder S01E03 should also be automatically mapped
    assert eps[2]["path"] is None
    assert eps[2]["myanimelist_anime_id"] == 12345
    assert eps[2]["myanimelist_episode_number"] == 3


def test_scan_directories_metadata_only_offline() -> None:
    """
    Test that scan_directories with metadata_only=True runs completely offline relative
    to the filesystem (i.e. handles non-existent paths, doesn't walk directories, etc.).
    """
    # Define an existing library for TV show
    existing_tv_library = {
        "Series A": {
            "metadata": {
                "tmdb_identifier": "123",
                "tmdb_name": "Series A Name",
                "poster_path": "/series_a_old_poster.jpg",
            },
            "seasons": {
                "Season 1": {
                    "metadata": {
                        "tmdb_identifier": "456",
                        "poster_path": "/season_1_old_poster.jpg",
                    },
                    "episodes": [
                        {
                            "name": "S01E01 - Episode 1",
                            "path": "/nonexistent/path/Series A/Season 1/S01E01.mkv",
                            "tmdb_identifier": "789",
                            "tmdb_number": 1,
                            "versions": [
                                {
                                    "path": "/nonexistent/path/Series A/Season 1/S01E01.mkv",
                                    "resolution": "1080p",
                                    "video_codec": "h264",
                                }
                            ],
                        }
                    ],
                }
            },
        }
    }

    # Define an existing library for Movie
    existing_movie_library = {
        "Movie A": {
            "tmdb_identifier": "999",
            "tmdb_name": "Movie A",
            "poster_path": "/old/movie_poster.jpg",
            "path": "/old/path/movie.mkv",
            "versions": [
                {
                    "path": "/nonexistent/path/Movie A/movie.mkv",
                    "resolution": "1080p",
                    "video_codec": "h264",
                }
            ],
        }
    }

    mock_tmdb = MagicMock()
    mock_tmdb.is_configured.return_value = True

    # Mock TMDB returns for series and movie
    mock_tmdb.get_series_by_id.return_value = {
        "id": "123",
        "name": "Series A Updated Name",
        "overview": "Updated overview for Series A",
        "first_air_date": "2026-01-01",
        "poster_path": "/new_series_poster.jpg",
        "seasons": [
            {
                "season_number": 1,
                "id": "456",
                "name": "Season 1",
                "poster_path": "/new_season_poster.jpg",
            }
        ],
    }
    mock_tmdb.get_episodes.return_value = [
        {
            "id": "789",
            "episode_number": 1,
            "name": "Episode 1 Updated Name",
            "runtime": 45,
            "air_date": "2026-01-01",
        },
        {
            "id": "888",
            "episode_number": 2,
            "name": "Episode 2 TBA",
            "runtime": 45,
            "air_date": "2026-01-08",
        },
    ]
    mock_tmdb.get_movie_by_id.return_value = {
        "id": "999",
        "title": "Movie A Updated Title",
        "overview": "Updated overview for Movie A",
        "poster_path": "/movie_new_poster.jpg",
    }

    def mock_download(path, key):
        return f"/cached{path}"

    mock_tmdb.download_image.side_effect = mock_download
    mock_tmdb.get_cached_image.return_value = ""

    # Patch TMDB client and run the TV scan
    with patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb):
        tv_res = scan_directories(
            ["/this/directory/does/not/exist"],
            library_type="tv",
            existing_library=existing_tv_library,
            metadata_only=True,
            force_refresh=True,
        )

    # Verify that the Series metadata is updated without filesystem access errors
    assert "Series A" in tv_res
    assert tv_res["Series A"]["metadata"]["tmdb_name"] == "Series A Updated Name"
    assert tv_res["Series A"]["metadata"]["overview"] == "Updated overview for Series A"
    assert (
        tv_res["Series A"]["metadata"]["poster_path"] == "/cached/new_series_poster.jpg"
    )

    # Verify that Season 1 is preserved and resolved
    assert "Season 1" in tv_res["Series A"]["seasons"]
    season_metadata = tv_res["Series A"]["seasons"]["Season 1"]["metadata"]
    assert season_metadata["poster_path"] == "/cached/new_season_poster.jpg"

    # Verify S01E01 is updated, and S01E02 placeholder is created
    eps = tv_res["Series A"]["seasons"]["Season 1"]["episodes"]
    assert len(eps) == 2
    assert eps[0]["name"] == "S01E01.mkv"
    assert eps[0]["path"] == "/nonexistent/path/Series A/Season 1/S01E01.mkv"
    assert eps[0]["versions"][0]["resolution"] == "1080p"

    assert eps[1]["path"] is None
    assert eps[1]["tmdb_number"] == 2

    # Patch TMDB client and run the Movie scan
    with (
        patch("lan_streamer.services.metadata_movie.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.scan_movie.tmdb_client", mock_tmdb),
    ):
        movie_res = scan_directories(
            ["/this/directory/does/not/exist"],
            library_type="movie",
            existing_library=existing_movie_library,
            metadata_only=True,
            force_refresh=True,
        )

    # Verify Movie A is updated and preserved
    assert "Movie A" in movie_res
    assert movie_res["Movie A"]["tmdb_name"] == "Movie A Updated Title"
    assert movie_res["Movie A"]["overview"] == "Updated overview for Movie A"
    assert movie_res["Movie A"]["poster_path"] == "/cached/movie_new_poster.jpg"
    assert movie_res["Movie A"]["path"] == "/nonexistent/path/Movie A/movie.mkv"


def test_scan_directories_metadata_only_preserves_existing_poster_files(
    tmp_path,
) -> None:
    """Verify that scan_directories with metadata_only=True preserves existing valid local poster files."""
    old_movie_poster = tmp_path / "movie_old_poster.jpg"
    old_movie_poster.touch()
    old_series_poster = tmp_path / "series_old_poster.jpg"
    old_series_poster.touch()
    old_season_poster = tmp_path / "season_old_poster.jpg"
    old_season_poster.touch()

    existing_tv_library = {
        "Series A": {
            "metadata": {
                "tmdb_identifier": "123",
                "tmdb_name": "Series A Name",
                "poster_path": str(old_series_poster),
            },
            "seasons": {
                "Season 1": {
                    "metadata": {
                        "tmdb_identifier": "456",
                        "poster_path": str(old_season_poster),
                    },
                    "episodes": [
                        {
                            "name": "S01E01 - Episode 1",
                            "path": "/nonexistent/path/Series A/Season 1/S01E01.mkv",
                            "tmdb_identifier": "789",
                            "tmdb_number": 1,
                            "versions": [
                                {
                                    "path": "/nonexistent/path/Series A/Season 1/S01E01.mkv",
                                    "resolution": "1080p",
                                    "video_codec": "h264",
                                }
                            ],
                        }
                    ],
                }
            },
        }
    }

    existing_movie_library = {
        "Movie A": {
            "tmdb_identifier": "999",
            "tmdb_name": "Movie A",
            "poster_path": str(old_movie_poster),
            "path": "/old/path/movie.mkv",
            "versions": [
                {
                    "path": "/nonexistent/path/Movie A/movie.mkv",
                    "resolution": "1080p",
                    "video_codec": "h264",
                }
            ],
        }
    }

    mock_tmdb = MagicMock()
    mock_tmdb.is_configured.return_value = True
    mock_tmdb.get_series_by_id.return_value = {
        "id": "123",
        "name": "Series A Updated Name",
        "overview": "Updated overview for Series A",
        "first_air_date": "2026-01-01",
        "poster_path": "/new_series_poster.jpg",
        "seasons": [
            {
                "season_number": 1,
                "id": "456",
                "name": "Season 1",
                "poster_path": "/new_season_poster.jpg",
            }
        ],
    }
    mock_tmdb.get_episodes.return_value = [
        {
            "id": "789",
            "episode_number": 1,
            "name": "Episode 1 Updated Name",
            "runtime": 45,
            "air_date": "2026-01-01",
        }
    ]
    mock_tmdb.get_movie_by_id.return_value = {
        "id": "999",
        "title": "Movie A Updated Title",
        "overview": "Updated overview for Movie A",
        "poster_path": "/movie_new_poster.jpg",
    }
    mock_tmdb.get_cached_image.return_value = ""

    with (
        patch("lan_streamer.services.metadata_tv.tmdb_client", mock_tmdb),
        patch("lan_streamer.services.metadata_movie.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.scan_movie.tmdb_client", mock_tmdb),
    ):
        tv_res = scan_directories(
            ["/this/directory/does/not/exist"],
            library_type="tv",
            existing_library=existing_tv_library,
            metadata_only=True,
            force_refresh=True,
        )
        movie_res = scan_directories(
            ["/this/directory/does/not/exist"],
            library_type="movie",
            existing_library=existing_movie_library,
            metadata_only=True,
            force_refresh=True,
        )

    # Verify that the existing local files were preserved rather than re-resolved/downloaded
    assert tv_res["Series A"]["metadata"]["poster_path"] == str(old_series_poster)
    assert tv_res["Series A"]["seasons"]["Season 1"]["metadata"]["poster_path"] == str(
        old_season_poster
    )
    assert movie_res["Movie A"]["poster_path"] == str(old_movie_poster)
    mock_tmdb.download_image.assert_not_called()
