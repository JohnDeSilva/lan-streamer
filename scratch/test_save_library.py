from lan_streamer.db.library import save_library

# Sample library data with placeholder episodes (path=None)
library_data = {
    "series": {
        "Test Series": {
            "seasons": {
                "Season 1": {
                    "episodes": {
                        "Episode 1": {
                            "name": "Episode 1",
                            "tmdb_number": 1,
                            "path": None,
                            "tmdb_episode_identifier": None,
                            "watched": False,
                        },
                        "Episode 2": {
                            "name": "Episode 2",
                            "tmdb_number": 2,
                            "path": "/tmp/episode2.mkv",
                            "tmdb_episode_identifier": None,
                            "watched": False,
                        },
                    }
                }
            }
        }
    }
}

# Attempt to save the library (replace 'TV' with your library name)
save_library("TV", library_data)
print("save_library completed")
