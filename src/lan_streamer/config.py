import json
from pathlib import Path
from typing import List, Dict

CONFIG_FILE = Path.home() / ".config" / "lan-streamer" / "config.json"


class Config:
    def __init__(self):
        self.libraries: Dict[str, List[str]] = {}
        self.jellyfin_url: str = ""
        self.jellyfin_api_key: str = ""
        self.sync_on_start: bool = True
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)

                    self.jellyfin_url = data.get("jellyfin_url", "")
                    self.jellyfin_api_key = data.get("jellyfin_api_key", "")
                    self.sync_on_start = data.get("sync_on_start", True)

                    if "libraries" in data:
                        self.libraries = data["libraries"]
                    elif "root_dirs" in data:
                        # Migrate old format
                        self.libraries = {"Default": data.get("root_dirs", [])}
                        self.save()
                    else:
                        self.libraries = {}
            except Exception as e:
                print(f"Error loading config: {e}")
                self.libraries = {}
        else:
            self.libraries = {}

    def save(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(
                    {
                        "libraries": self.libraries,
                        "jellyfin_url": self.jellyfin_url,
                        "jellyfin_api_key": self.jellyfin_api_key,
                        "sync_on_start": self.sync_on_start,
                    },
                    f,
                    indent=4,
                )
        except Exception as e:
            print(f"Error saving config: {e}")

    def add_library(self, name: str):
        if name not in self.libraries:
            self.libraries[name] = []
            self.save()

    def remove_library(self, name: str):
        if name in self.libraries:
            del self.libraries[name]
            self.save()

    def add_root_dir(self, library_name: str, path: str):
        if library_name in self.libraries and path not in self.libraries[library_name]:
            self.libraries[library_name].append(path)
            self.save()

    def remove_root_dir(self, library_name: str, path: str):
        if library_name in self.libraries and path in self.libraries[library_name]:
            self.libraries[library_name].remove(path)
            self.save()


config = Config()
