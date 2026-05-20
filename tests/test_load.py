import pytest
import time
import random
from lan_streamer import db


def generate_large_library(num_series=500, eps_per_series=20) -> None:
    """
    Generates a large library structure for testing.
    Default: 500 series * 20 episodes = 10,000 episodes.
    """
    library = {}
    for i in range(num_series):
        series_name = f"Series {i:03d}"
        series_data = {
            "metadata": {
                "jellyfin_id": f"sid_{i}",
                "tmdb_identifier": f"tmdb_{i}",
                "poster_path": f"/posters/s{i}.jpg",
                "overview": f"Overview for series {i}. " * 5,
                "tmdb_name": f"Official Series {i}",
                "locked_metadata": random.choice([True, False]),
            },
            "seasons": {},
        }

        # Split episodes into 2 seasons
        for s in range(1, 3):
            season_name = f"Season {s}"
            episodes = []
            for e in range(1, (eps_per_series // 2) + 1):
                ep_num = (s - 1) * (eps_per_series // 2) + e
                episodes.append(
                    {
                        "name": f"Episode {ep_num}",
                        "path": f"/media/Series {i}/Season {s}/E{e:02d}.mkv",
                        "jellyfin_id": f"eid_{i}_{s}_{e}",
                        "tmdb_episode_identifier": f"teid_{i}_{s}_{e}",
                        "tmdb_name": f"Ep Name {ep_num}",
                        "tmdb_number": ep_num,
                        "watched": random.choice([True, False]),
                        "date_added": int(time.time()) - random.randint(0, 1000000),
                    }
                )

            series_data["seasons"][season_name] = {
                "metadata": {
                    "jellyfin_id": f"ssid_{i}_{s}",
                    "poster_path": f"/posters/s{i}_sea{s}.jpg",
                },
                "episodes": episodes,
            }

        library[series_name] = series_data
    return library


@pytest.mark.load
def test_db_load_and_save_benchmark() -> None:
    """
    Benchmark saving and loading a large library.
    """
    db.init_db()
    lib_name = "BenchmarkLib"

    print("\nGenerating large library (500 series, 10,000 episodes)...")
    start_gen = time.perf_counter()
    large_lib = generate_large_library(500, 20)
    gen_duration = time.perf_counter() - start_gen
    print(f"Generation took: {gen_duration:.3f}s")

    print("Saving large library to database...")
    start_save = time.perf_counter()
    db.save_library(lib_name, large_lib)
    save_duration = time.perf_counter() - start_save
    print(f"SAVE duration: {save_duration:.3f}s")

    print("Loading large library from database...")
    start_load = time.perf_counter()
    loaded_lib = db.load_library(lib_name)
    load_duration = time.perf_counter() - start_load
    print(f"LOAD duration: {load_duration:.3f}s")

    # Correctness check
    assert len(loaded_lib) == 500
    series_0 = loaded_lib.get("Series 000")
    assert series_0 is not None
    assert len(series_0["seasons"]) == 2
    assert len(series_0["seasons"]["Season 1"]["episodes"]) == 10

    print(f"Benchmark summary for {lib_name}:")
    print("  - Series: 500")
    print("  - Episodes: 10,000")
    print(f"  - Save Time: {save_duration:.3f}s")
    print(f"  - Load Time: {load_duration:.3f}s")


@pytest.mark.load
def test_sync_performance_large_data() -> None:
    """
    Benchmark the sync_watched_from_jellyfin_data function with large inputs.
    """
    db.init_db()
    lib_name = "SyncBenchmarkLib"
    large_lib = generate_large_library(500, 20)
    db.save_library(lib_name, large_lib)

    # Collect all jellyfin IDs and paths to simulate a full sync
    all_jellyfin_ids = set()
    all_paths = set()
    all_names = set()

    for series_name, series_data in large_lib.items():
        for season_data in series_data["seasons"].values():
            for ep in season_data["episodes"]:
                all_jellyfin_ids.add(ep["jellyfin_id"])
                all_paths.add(ep["path"])
                all_names.add((series_name, ep["name"]))

    # Take a random subset of 5000 items to mark as watched
    watched_ids = set(random.sample(list(all_jellyfin_ids), 2000))
    watched_paths = set(random.sample(list(all_paths), 2000))
    watched_names = set(random.sample(list(all_names), 1000))

    print(
        f"\nBenchmarking sync_watched_from_jellyfin_data with {len(watched_ids)} IDs, {len(watched_paths)} paths, {len(watched_names)} names..."
    )
    start_sync = time.perf_counter()
    count = db.sync_watched_from_jellyfin_data(
        watched_ids, watched_paths, watched_names
    )
    sync_duration = time.perf_counter() - start_sync
    print(f"SYNC duration: {sync_duration:.3f}s (Updated {count} episodes)")

    assert count > 0


@pytest.mark.load
def test_movie_library_load_and_save_benchmark() -> None:
    """
    Benchmark saving and loading a large movie library.
    Default: 1,000 movies.
    """
    db.init_db()
    lib_name = "MovieBenchmarkLib"
    num_movies = 1000

    print(f"\nGenerating movie library ({num_movies} movies)...")
    start_gen = time.perf_counter()
    movie_library = {}
    for i in range(num_movies):
        movie_name = f"Movie Title {i:04d} ({2000 + (i % 24)})"
        movie_library[movie_name] = {
            "name": movie_name,
            "path": f"/media/movies/movie_{i:04d}/movie.mkv",
            "jellyfin_id": f"mjid_{i}",
            "tmdb_identifier": f"mtmdb_{i}",
            "poster_path": f"/posters/m{i}.jpg",
            "overview": f"Overview for movie {i}. " * 5,
            "tmdb_name": f"Official Movie Title {i}",
            "locked_metadata": random.choice([True, False]),
            "date_added": int(time.time()) - random.randint(0, 1000000),
            "runtime": random.randint(80, 180),
            "rating": f"{random.uniform(4.0, 9.5):.1f}",
            "genre": random.choice(["Action", "Drama", "Comedy", "Sci-Fi"]),
            "year": 2000 + (i % 24),
            "watched": random.choice([True, False]),
            "last_played_position": 0,
        }
    gen_duration = time.perf_counter() - start_gen
    print(f"Generation took: {gen_duration:.3f}s")

    print("Saving movie library to database...")
    start_save = time.perf_counter()
    db.save_movie_library(lib_name, movie_library)
    save_duration = time.perf_counter() - start_save
    print(f"SAVE duration: {save_duration:.3f}s")

    print("Loading movie library from database...")
    start_load = time.perf_counter()
    loaded_lib = db.load_movie_library(lib_name)
    load_duration = time.perf_counter() - start_load
    print(f"LOAD duration: {load_duration:.3f}s")

    assert len(loaded_lib) == num_movies

    print(f"Benchmark summary for {lib_name}:")
    print(f"  - Movies: {num_movies}")
    print(f"  - Save Time: {save_duration:.3f}s")
    print(f"  - Load Time: {load_duration:.3f}s")


@pytest.mark.load
def test_update_season_watched_status_benchmark() -> None:
    """
    Benchmark bulk-updating watched status for a large season via
    update_season_watched_status, verifying the result is correct.
    Uses 500 series * 50 episodes per season = 25,000 episodes total.
    """
    db.init_db()
    lib_name = "SeasonWatchedBenchmarkLib"
    num_series = 500
    eps_per_season = 50

    print(f"\nGenerating library ({num_series} series, {eps_per_season} eps/season)...")
    library = {}
    for i in range(num_series):
        series_name = f"WatchedSeries {i:03d}"
        library[series_name] = {
            "metadata": {"jellyfin_id": f"wsid_{i}", "tmdb_identifier": f"wtmdb_{i}"},
            "seasons": {
                "Season 1": {
                    "metadata": {"jellyfin_id": f"wssid_{i}"},
                    "episodes": [
                        {
                            "name": f"Episode {e}",
                            "path": f"/media/WatchedSeries {i}/Season 1/E{e:02d}.mkv",
                            "watched": False,
                        }
                        for e in range(1, eps_per_season + 1)
                    ],
                }
            },
        }
    db.save_library(lib_name, library)

    print(f"Bulk-marking Season 1 of all {num_series} series as watched...")
    start_update = time.perf_counter()
    for i in range(num_series):
        db.update_season_watched_status(
            lib_name, f"WatchedSeries {i:03d}", "Season 1", True
        )
    update_duration = time.perf_counter() - start_update
    print(f"UPDATE duration: {update_duration:.3f}s")

    # Spot-check a few series
    loaded = db.load_library(lib_name)
    sample = loaded["WatchedSeries 000"]["seasons"]["Season 1"]["episodes"]
    assert all(ep["watched"] for ep in sample), "All episodes should be marked watched"

    print("Benchmark summary:")
    print(f"  - Series: {num_series}")
    print(f"  - Episodes per season: {eps_per_season}")
    print(f"  - Total episodes updated: {num_series * eps_per_season}")
    print(f"  - Update Time: {update_duration:.3f}s")
