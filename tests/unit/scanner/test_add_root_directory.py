from pathlib import Path
from unittest.mock import patch, MagicMock
from lan_streamer.scanner import scan_directories


def test_add_root_directory_scans_correctly(tmp_path: Path) -> None:
    # Set up root_dir_1 (the original root directory)
    root_1 = tmp_path / "root1"
    root_1.mkdir()
    series_1 = root_1 / "Show A"
    series_1.mkdir()
    (series_1 / "Season 1").mkdir()
    ep_1 = series_1 / "Season 1" / "S01E01.mp4"
    ep_1.touch()

    # Set up root_dir_2 (the newly added root directory)
    root_2 = tmp_path / "root2"
    root_2.mkdir()
    series_2 = root_2 / "Show B"
    series_2.mkdir()
    (series_2 / "Season 1").mkdir()
    ep_2 = series_2 / "Season 1" / "S01E01.mp4"
    ep_2.touch()

    # Mock TMDB client
    mock_tmdb = MagicMock()
    mock_tmdb.is_configured.return_value = True

    # Define a search behavior that resolves both series names
    def search_series(name):
        return {"id": name + "_id", "name": name, "overview": "", "poster_path": ""}

    mock_tmdb.search_series.side_effect = search_series

    mock_tmdb.get_seasons.return_value = [{"season_number": 1, "id": "season_1_id"}]
    mock_tmdb.get_episodes.return_value = [
        {"id": "ep1_id", "episode_number": 1, "name": "Episode 1"},
    ]
    mock_tmdb.download_image.return_value = ""

    # Phase 1: Scan only root_1 (initial state)
    with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
        lib_phase_1 = scan_directories([str(root_1)])

    assert "Show A" in lib_phase_1
    assert "Show B" not in lib_phase_1

    # Phase 2: Add root_2 to config (simulated here by scanning both paths)
    # We pass the phase 1 result as existing_library
    with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
        lib_phase_2 = scan_directories(
            [str(root_1), str(root_2)], existing_library=lib_phase_1
        )

    # Check if Show B from the new root directory has been scanned
    assert "Show B" in lib_phase_2
    assert "Show A" in lib_phase_2


def test_add_root_directory_same_series_new_season(tmp_path: Path) -> None:
    # Set up root_dir_1 (original) with Show A, Season 1
    root_1 = tmp_path / "root1"
    root_1.mkdir()
    series_1 = root_1 / "Show A"
    series_1.mkdir()
    (series_1 / "Season 1").mkdir()
    ep_1 = series_1 / "Season 1" / "S01E01.mp4"
    ep_1.touch()

    # Set up root_dir_2 (newly added) with Show A, Season 2
    root_2 = tmp_path / "root2"
    root_2.mkdir()
    series_2 = root_2 / "Show A"
    series_2.mkdir()
    (series_2 / "Season 2").mkdir()
    ep_2 = series_2 / "Season 2" / "S02E01.mp4"
    ep_2.touch()

    # Mock TMDB
    mock_tmdb = MagicMock()
    mock_tmdb.is_configured.return_value = True
    mock_tmdb.search_series.return_value = {
        "id": "show_a_id",
        "name": "Show A",
        "overview": "",
        "poster_path": "",
    }

    # Make get_seasons return both season 1 and season 2
    mock_tmdb.get_seasons.return_value = [
        {"season_number": 1, "id": "s1_id"},
        {"season_number": 2, "id": "s2_id"},
    ]
    mock_tmdb.get_episodes.side_effect = lambda series_id, season_num: (
        [{"id": "ep1_id", "episode_number": 1, "name": "Episode 1"}]
        if season_num == 1
        else [{"id": "ep2_id", "episode_number": 1, "name": "Episode 2"}]
    )
    mock_tmdb.download_image.return_value = ""

    # Phase 1: Scan root_1 only
    with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
        lib_phase_1 = scan_directories([str(root_1)])

    assert "Show A" in lib_phase_1
    assert "Season 1" in lib_phase_1["Show A"]["seasons"]
    assert "Season 2" not in lib_phase_1["Show A"]["seasons"]

    # Phase 2: Scan both root_1 and root_2
    with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
        lib_phase_2 = scan_directories(
            [str(root_1), str(root_2)], existing_library=lib_phase_1
        )

    # Check if Season 2 has been scanned and merged
    assert "Show A" in lib_phase_2
    assert "Season 1" in lib_phase_2["Show A"]["seasons"]
    assert "Season 2" in lib_phase_2["Show A"]["seasons"]


def test_add_root_directory_one_by_one(tmp_path: Path) -> None:
    # Set up root_dir_1 (original) with Show A, Season 1
    root_1 = tmp_path / "root1"
    root_1.mkdir()
    series_1 = root_1 / "Show A"
    series_1.mkdir()
    (series_1 / "Season 1").mkdir()
    ep_1 = series_1 / "Season 1" / "S01E01.mp4"
    ep_1.touch()

    # Set up root_dir_2 (newly added) with Show A, Season 2
    root_2 = tmp_path / "root2"
    root_2.mkdir()
    series_2 = root_2 / "Show A"
    series_2.mkdir()
    (series_2 / "Season 2").mkdir()
    ep_2 = series_2 / "Season 2" / "S02E01.mp4"
    ep_2.touch()

    # Mock TMDB
    mock_tmdb = MagicMock()
    mock_tmdb.is_configured.return_value = True
    mock_tmdb.search_series.return_value = {
        "id": "show_a_id",
        "name": "Show A",
        "overview": "",
        "poster_path": "",
    }

    # Make get_seasons return both season 1 and season 2
    mock_tmdb.get_seasons.return_value = [
        {"season_number": 1, "id": "s1_id"},
        {"season_number": 2, "id": "s2_id"},
    ]
    mock_tmdb.get_episodes.side_effect = lambda series_id, season_num: (
        [{"id": "ep1_id", "episode_number": 1, "name": "Episode 1"}]
        if season_num == 1
        else [{"id": "ep2_id", "episode_number": 1, "name": "Episode 2"}]
    )
    mock_tmdb.download_image.return_value = ""

    # Phase 1: Scan root_1 only
    with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
        lib_phase_1 = scan_directories([str(root_1)])

    # Phase 2: Scan root_2 only, with existing_library = lib_phase_1
    with patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb):
        lib_phase_2 = scan_directories([str(root_2)], existing_library=lib_phase_1)

    # Check if Season 2 and Season 1 are both in lib_phase_2
    assert "Show A" in lib_phase_2
    assert "Season 1" in lib_phase_2["Show A"]["seasons"]
    assert "Season 2" in lib_phase_2["Show A"]["seasons"]
