from unittest.mock import patch
from lan_streamer.backend.scan_series_worker import ScanSingleSeriesWorker


def test_scan_single_series_worker_success(tmp_path, mock_db_save):
    mock_save, _ = mock_db_save
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    root1.mkdir()
    root2.mkdir()

    # Create series directories in both roots
    series_dir1 = root1 / "Test Series"
    series_dir1.mkdir()
    series_dir2 = root2 / "Test Series"
    series_dir2.mkdir()

    existing = {
        "Test Series": {
            "metadata": {"tmdb_identifier": "12345"},
            "seasons": {"Season 1": {"metadata": {}, "episodes": []}},
        }
    }

    worker = ScanSingleSeriesWorker(
        library_name="TV",
        series_name="Test Series",
        library_type="tv",
        root_directories=[str(root1), str(root2)],
        existing_library=existing,
    )

    with (
        patch("lan_streamer.scanner.pass2_metadata.scan_series_pass2") as mock_scan,
        patch("lan_streamer.backend.scan_series_worker.clean_series_data", lambda x: x),
    ):
        # We will return dummy scanned data
        mock_scan.side_effect = [
            # First scan (root1)
            {
                "metadata": {"tmdb_identifier": "12345", "name": "Test Series"},
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "name": "Episode 1",
                                "path": str(series_dir1 / "S01E01.mp4"),
                            }
                        ],
                    }
                },
            },
            # Second scan (root2)
            {
                "metadata": {"tmdb_identifier": "12345", "name": "Test Series"},
                "seasons": {
                    "Season 1": {
                        "metadata": {},
                        "episodes": [
                            {
                                "name": "Episode 1",
                                "path": str(series_dir1 / "S01E01.mp4"),
                            },
                            {
                                "name": "Episode 2",
                                "path": str(series_dir2 / "S01E02.mp4"),
                            },
                        ],
                    }
                },
            },
        ]

        # Catch finished signal
        finished_data = None

        def on_finished(d):
            nonlocal finished_data
            finished_data = d

        worker.finished.connect(on_finished)

        worker.run()

        assert finished_data is not None
        assert "Test Series" in finished_data
        episodes = finished_data["Test Series"]["seasons"]["Season 1"]["episodes"]
        assert len(episodes) == 2
        assert mock_scan.call_count == 2
        mock_save.assert_called_once()
        # Verify it passed force_refresh=True
        mock_scan.assert_any_call(
            series_dir1,
            existing_series_data=existing["Test Series"],
            tmdb_series=None,
            jellyfin_data=None,
            force_refresh=True,
            single_item_refresh=True,
            show_future_episodes=True,
        )


def test_scan_single_series_worker_movie_success(tmp_path, mock_db_save):
    _, mock_movie_save = mock_db_save
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    root1.mkdir()
    root2.mkdir()

    # Create movie directories in both roots
    movie_dir1 = root1 / "Test Movie"
    movie_dir1.mkdir()
    movie_dir2 = root2 / "Test Movie"
    movie_dir2.mkdir()

    existing = {
        "Test Movie": {
            "tmdb_identifier": "54321",
            "path": str(movie_dir1 / "movie.mp4"),
        }
    }

    worker = ScanSingleSeriesWorker(
        library_name="Movies",
        series_name="Test Movie",
        library_type="movie",
        root_directories=[str(root1), str(root2)],
        existing_library=existing,
    )

    with patch("lan_streamer.scanner.pass2_metadata.scan_movie_pass2") as mock_scan:
        mock_scan.side_effect = [
            # First scan (root1)
            {
                "tmdb_identifier": "54321",
                "path": str(movie_dir1 / "movie.mp4"),
                "versions": [{"path": str(movie_dir1 / "movie.mp4")}],
            },
            # Second scan (root2)
            {
                "tmdb_identifier": "54321",
                "path": str(movie_dir2 / "movie_1080p.mp4"),
                "versions": [
                    {"path": str(movie_dir1 / "movie.mp4")},
                    {"path": str(movie_dir2 / "movie_1080p.mp4")},
                ],
            },
        ]

        # Catch finished signal
        finished_data = None

        def on_finished(d):
            nonlocal finished_data
            finished_data = d

        worker.finished.connect(on_finished)

        worker.run()

        assert finished_data is not None
        assert "Test Movie" in finished_data
        versions = finished_data["Test Movie"]["versions"]
        assert len(versions) == 2
        assert mock_scan.call_count == 2
        mock_movie_save.assert_called_once()
        # Verify it passed force_refresh=True
        mock_scan.assert_any_call(
            movie_dir1,
            existing_movie_data=existing["Test Movie"],
            tmdb_movie=None,
            jellyfin_data=None,
            force_refresh=True,
            single_item_refresh=True,
        )


def test_scan_single_series_worker_not_found(tmp_path):
    worker = ScanSingleSeriesWorker(
        library_name="TV",
        series_name="Missing Show",
        library_type="tv",
        root_directories=[str(tmp_path)],
        existing_library={},
    )

    error_msg = None

    def on_error(msg):
        nonlocal error_msg
        error_msg = msg

    worker.error.connect(on_error)
    worker.run()
    assert error_msg is not None
