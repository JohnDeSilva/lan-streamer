from unittest.mock import patch
from lan_streamer.backend import ScanAllLibrariesWorker
from lan_streamer.scanner.core import LibraryDict


def test_scan_all_libraries_pass1_exception_emits_fail_library() -> None:
    """When a library fails in Pass 1, ScanAllLibrariesWorker emits fail_library."""
    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=RuntimeError("Pass 1 failure"),
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
    ):
        mock_config.libraries = {
            "TVLib": {"paths": ["/tv"], "type": "tv"},
        }

        detail_events = []
        worker = ScanAllLibrariesWorker(run_pass2=False)
        worker.detail_progress_batch.connect(
            lambda batch: [
                detail_events.append((e["event"], e["payload"])) for e in batch
            ]
        )
        worker.run()

        # Check for fail_library event
        fail_events = [pl for ev, pl in detail_events if ev == "fail_library"]
        assert len(fail_events) == 1
        assert fail_events[0]["library"] == "TVLib"


def test_scan_all_libraries_pass2_exception_emits_fail_library() -> None:
    """When a library fails in Pass 2, ScanAllLibrariesWorker emits fail_library."""
    pass1_lib = LibraryDict({})
    pass1_lib.unavailable_directories = []

    def _scan_side_effect(*args, **kwargs):
        pass_number = kwargs.get("pass_number", 0)
        if pass_number == 1:
            return pass1_lib
        raise RuntimeError("Pass 2 failure")

    with (
        patch("lan_streamer.backend.scan_worker_all.config") as mock_config,
        patch(
            "lan_streamer.backend.scan_worker_all.jellyfin_client.is_configured",
            return_value=False,
        ),
        patch(
            "lan_streamer.backend.scan_worker_all.scan_directories",
            side_effect=_scan_side_effect,
        ),
        patch("lan_streamer.backend.scan_worker_all.db.load_library", return_value={}),
        patch("lan_streamer.backend.scan_worker_all.db.save_library"),
    ):
        mock_config.libraries = {
            "TVLib": {"paths": ["/tv"], "type": "tv"},
        }

        detail_events = []
        worker = ScanAllLibrariesWorker(run_pass1=True, run_pass2=True)
        worker.detail_progress_batch.connect(
            lambda batch: [
                detail_events.append((e["event"], e["payload"])) for e in batch
            ]
        )
        worker.run()

        # Check for fail_library event
        fail_events = [pl for ev, pl in detail_events if ev == "fail_library"]
        assert len(fail_events) == 1
        assert fail_events[0]["library"] == "TVLib"
