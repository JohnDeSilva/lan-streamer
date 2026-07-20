import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from lan_streamer.scanner import scan_directories


_MOCK_TMDB_PATHS = [
    "lan_streamer.services.metadata_series.tmdb_client",
    "lan_streamer.services.metadata_episode.tmdb_client",
    "lan_streamer.scanner.pass2_metadata.tmdb_client",
]


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
    with (
        patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb),
        patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock_tmdb),
    ):
        lib_phase_1 = scan_directories([str(root_1)])

    assert "Show A" in lib_phase_1
    assert "Show B" not in lib_phase_1

    # Phase 2: Add root_2 to config (simulated here by scanning both paths)
    # We pass the phase 1 result as existing_library
    with (
        patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb),
        patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock_tmdb),
    ):
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
    with (
        patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb),
        patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock_tmdb),
    ):
        lib_phase_1 = scan_directories([str(root_1)])

    assert "Show A" in lib_phase_1
    assert "Season 1" in lib_phase_1["Show A"]["seasons"]
    # Season 2 is a TMDB-only season with placeholder episodes (added by
    # _add_tmdb_only_seasons during Pass 2 metadata resolution).
    assert "Season 2" in lib_phase_1["Show A"]["seasons"]

    # Phase 2: Scan both root_1 and root_2
    with (
        patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb),
        patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock_tmdb),
    ):
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
    with (
        patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb),
        patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock_tmdb),
    ):
        lib_phase_1 = scan_directories([str(root_1)])

    # Phase 2: Scan root_2 only, with existing_library = lib_phase_1
    with (
        patch("lan_streamer.services.metadata_series.tmdb_client", mock_tmdb),
        patch("lan_streamer.services.metadata_episode.tmdb_client", mock_tmdb),
        patch("lan_streamer.scanner.pass2_metadata.tmdb_client", mock_tmdb),
    ):
        lib_phase_2 = scan_directories([str(root_2)], existing_library=lib_phase_1)

    # Check if Season 2 and Season 1 are both in lib_phase_2
    assert "Show A" in lib_phase_2
    assert "Season 1" in lib_phase_2["Show A"]["seasons"]
    assert "Season 2" in lib_phase_2["Show A"]["seasons"]


def test_file_moved_between_roots_preserves_episode_and_watched(tmp_path: Path) -> None:
    """Given a series with a watched episode in root_a, copy the series folder
    to root_b, delete the season from root_a, and run a full scan: the episode
    must survive with watched state intact, and only the media-file records
    should change to reflect the new location.

    This is a regression test for the scanner pipeline's cross-root file-move
    handling.
    """
    from lan_streamer import db as _db

    # ------------------------------------------------------------------
    #  Setup: two library root directories
    # ------------------------------------------------------------------
    root_a = tmp_path / "RootA"
    root_b = tmp_path / "RootB"
    root_a.mkdir()
    root_b.mkdir()

    series_a = root_a / "Test Show"
    series_a.mkdir()
    season_a = series_a / "Season 1"
    season_a.mkdir()
    ep_a = season_a / "Test Show S01E01.mkv"
    ep_a.write_text("video data")

    # ------------------------------------------------------------------
    #  TMDB mock
    # ------------------------------------------------------------------
    mock_tmdb = MagicMock()
    mock_tmdb.is_configured.return_value = True
    mock_tmdb.search_series.return_value = {
        "id": "series_1",
        "name": "Test Show",
        "overview": "A test",
        "poster_path": "",
        "first_air_date": "2020-01-01",
        "seasons": [{"season_number": 1}],
    }
    mock_tmdb.get_series_by_id.return_value = {
        "id": "series_1",
        "name": "Test Show",
        "overview": "A test",
        "poster_path": "",
        "first_air_date": "2020-01-01",
        "seasons": [{"season_number": 1}],
    }
    mock_tmdb.get_seasons.return_value = [
        {"season_number": 1, "id": "s1", "name": "Season 1"},
    ]
    mock_tmdb.get_episodes.return_value = [
        {"id": "ep1", "episode_number": 1, "name": "Episode 1"},
    ]
    mock_tmdb.download_image.return_value = ""

    tmdb_patch_paths = (
        "lan_streamer.services.metadata_series.tmdb_client",
        "lan_streamer.services.metadata_episode.tmdb_client",
        "lan_streamer.scanner.pass2_metadata.tmdb_client",
    )

    # ------------------------------------------------------------------
    #  Phase 1 — initial scan of root_a only
    # ------------------------------------------------------------------
    with (
        patch(tmdb_patch_paths[0], mock_tmdb),
        patch(tmdb_patch_paths[1], mock_tmdb),
        patch(tmdb_patch_paths[2], mock_tmdb),
    ):
        lib = scan_directories([str(root_a)])

    assert "Test Show" in lib
    season = lib["Test Show"]["seasons"]["Season 1"]
    assert len(season["episodes"]) == 1

    # Save to DB and mark watched
    _db.save_library("TestLib", lib)
    _db.update_episode_watched_status(str(ep_a.absolute()), True)

    # Load the existing state that the app would pass to the next scan
    existing_library = _db.load_library("TestLib")
    existing_eps = existing_library["Test Show"]["seasons"]["Season 1"]["episodes"]
    assert len(existing_eps) == 1
    assert existing_eps[0]["watched"] is True
    old_path = existing_eps[0]["path"]
    assert old_path is not None and "RootA" in old_path

    # ------------------------------------------------------------------
    #  Phase 2 — copy series to root_b, delete season from root_a
    # ------------------------------------------------------------------
    series_b = root_b / "Test Show"
    shutil.copytree(str(series_a), str(series_b))
    shutil.rmtree(str(season_a))  # Season 1 folder gone from root_a
    ep_b = series_b / "Season 1" / "Test Show S01E01.mkv"
    assert ep_b.exists()

    # ------------------------------------------------------------------
    #  Phase 3 — re-scan both roots with existing library data
    # ------------------------------------------------------------------
    with (
        patch(tmdb_patch_paths[0], mock_tmdb),
        patch(tmdb_patch_paths[1], mock_tmdb),
        patch(tmdb_patch_paths[2], mock_tmdb),
    ):
        lib = scan_directories(
            [str(root_a), str(root_b)],
            existing_library=existing_library,
        )

    _db.save_library("TestLib", lib)

    # Run cleanup pass (as the production flow does after every scan).
    _db.cleanup_library("TestLib", [str(root_a), str(root_b)])

    # ------------------------------------------------------------------
    #  Verify final DB state
    # ------------------------------------------------------------------
    final = _db.load_library("TestLib")

    assert "Test Show" in final, "Series must survive"
    assert "Season 1" in final["Test Show"]["seasons"], "Season must survive"

    eps = final["Test Show"]["seasons"]["Season 1"]["episodes"]
    # Must have exactly one episode (no duplicates)
    assert len(eps) == 1, f"Expected 1 episode, got {len(eps)}"

    ep = eps[0]
    # Watched flag must be preserved
    assert ep["watched"] is True, "Watched flag must survive the move"

    # The episode should have a valid default_path (not nulled by cleanup)
    assert ep.get("path") is not None, (
        f"Episode path must not be None after cleanup; got {ep.get('path')!r}"
    )

    # The episode's media-file records should point to the new location
    versions = ep.get("versions", [])
    version_paths = {v["path"] for v in versions if v.get("path")}

    new_path_str = str(ep_b.absolute())
    assert any(new_path_str in vp for vp in version_paths), (
        f"New path ({new_path_str}) must be in versions; got {version_paths}"
    )

    # The old path must NOT be in versions (cleaned up)
    old_path_str = str(ep_a.absolute())
    assert not any(old_path_str in vp for vp in version_paths), (
        f"Old path ({old_path_str}) must be removed from versions; got {version_paths}"
    )

    # ------------------------------------------------------------------
    #  The episode was loaded with watched state intact and has exactly
    #  one version — the new file.  No stale references remain.
    # ------------------------------------------------------------------
    assert len(versions) == 1, (
        f"Expected exactly 1 version after cleanup; got {len(versions)}"
    )
