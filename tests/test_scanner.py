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
    with patch("lan_streamer.scanner.tmdb_client", mock_tmdb):
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
        patch("lan_streamer.scanner.tmdb_client", _mock_tmdb()),
    ):
        library = scan_directories([str(tmp_path)])
        episodes = library["Series A"]["seasons"]["Season 1"]["episodes"]
        assert episodes[0]["date_added"] == 0


def test_scan_directories_nonexistent_path() -> None:
    assert scan_directories(["/path/does/not/exist/at/all/123456789"]) == {}


def test_scan_series(tmp_path) -> None:
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

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
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

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
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
    with patch("lan_streamer.scanner.tmdb_client", mock_tmdb):
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
    with patch("lan_streamer.scanner.tmdb_client", mock_tmdb):
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
    with patch("lan_streamer.scanner.tmdb_client", mock_tmdb):
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
        patch("lan_streamer.scanner.tmdb_client", mock_tmdb),
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

    with patch("lan_streamer.scanner.tmdb_client", mock_tmdb):
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

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
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

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
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

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
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
    assert _parse_season_number("Specials") is None


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

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
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

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
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

    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
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
    with patch("lan_streamer.scanner.tmdb_client") as mock_tmdb:
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

    with patch("lan_streamer.scanner.tmdb_client", mock_tmdb):
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

    with patch("lan_streamer.scanner.tmdb_client", mock_tmdb):
        library = scan_directories([str(tmp_path)])

    assert len(library) == 2
    assert "DareDevil" in library
    assert "DareDevil - born again" in library
    assert library["DareDevil"]["metadata"]["tmdb_identifier"] == "61889"
    assert library["DareDevil - born again"]["metadata"]["tmdb_identifier"] == "208857"
