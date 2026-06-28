from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject

from lan_streamer.system.threading_manager import WorkerSlot, WorkerManager


class _StubQObject(QObject):
    """Minimal QObject for testing WorkerSlot/WorkerManager parent relationships."""


@pytest.fixture
def stub_parent() -> _StubQObject:
    return _StubQObject()


@pytest.fixture
def slot(stub_parent: _StubQObject) -> WorkerSlot:
    return WorkerSlot(parent=stub_parent)


@pytest.fixture
def manager(stub_parent: _StubQObject) -> WorkerManager:
    return WorkerManager(parent=stub_parent)


# ---------------------------------------------------------------------------
# WorkerSlot — construction & properties
# ---------------------------------------------------------------------------


def test_worker_slot_initial_state(slot: WorkerSlot) -> None:
    assert slot.is_running is False
    assert slot.instance is None


def test_worker_slot_is_running_property(slot: WorkerSlot) -> None:
    worker = _FakeAsyncWorker()
    worker._running = True
    slot._instance = worker
    assert slot.is_running is True

    worker._running = False
    assert slot.is_running is False


def test_worker_slot_is_running_returns_false_when_instance_none(
    slot: WorkerSlot,
) -> None:
    slot._instance = None
    assert slot.is_running is False


def test_worker_slot_instance_property(slot: WorkerSlot) -> None:
    fake_worker = MagicMock()
    slot._instance = fake_worker
    assert slot.instance is fake_worker


# ---------------------------------------------------------------------------
# WorkerSlot — start()
# ---------------------------------------------------------------------------


def test_worker_slot_start_creates_worker_and_starts(slot: WorkerSlot) -> None:
    fake_worker = MagicMock()
    factory = MagicMock(return_value=fake_worker)

    result = slot.start(factory)

    assert result is fake_worker
    factory.assert_called_once()
    fake_worker.start.assert_called_once()


def test_worker_slot_start_connects_signals(slot: WorkerSlot) -> None:
    fake_signal = MagicMock()
    fake_worker = MagicMock()
    fake_worker.finished = fake_signal
    factory = MagicMock(return_value=fake_worker)
    slot_handler = MagicMock()

    slot.start(factory, finished=slot_handler)

    fake_signal.connect.assert_called_once_with(slot_handler)


def test_worker_slot_start_skips_none_slot(slot: WorkerSlot) -> None:
    fake_worker = MagicMock()
    factory = MagicMock(return_value=fake_worker)

    slot.start(factory, finished=None)

    fake_worker.finished.connect.assert_not_called()


def test_worker_slot_start_returns_worker(slot: WorkerSlot) -> None:
    fake_worker = MagicMock()
    factory = MagicMock(return_value=fake_worker)

    result = slot.start(factory)

    assert result is fake_worker


def test_worker_slot_start_sets_instance(slot: WorkerSlot) -> None:
    fake_worker = MagicMock()
    factory = MagicMock(return_value=fake_worker)

    slot.start(factory)

    assert slot.instance is fake_worker


def test_worker_slot_start_warns_on_replacement(slot: WorkerSlot, caplog) -> None:
    running_worker = _FakeAsyncWorker()
    running_worker._running = True
    slot._instance = running_worker

    new_worker = MagicMock()
    factory = MagicMock(return_value=new_worker)

    with caplog.at_level("WARNING"):
        result = slot.start(factory)

    assert result is new_worker
    assert "replacing running" in caplog.text


def test_worker_slot_start_stops_previous_worker(slot: WorkerSlot) -> None:
    running_worker = _FakeAsyncWorker()
    running_worker._running = True
    slot._instance = running_worker

    new_worker = MagicMock()
    factory = MagicMock(return_value=new_worker)

    slot.start(factory)

    assert running_worker._running is False


def test_worker_slot_start_unknown_signal_warns(slot: WorkerSlot, caplog) -> None:
    fake_worker = MagicMock()
    fake_worker.nonexistent_signal = None
    factory = MagicMock(return_value=fake_worker)

    with caplog.at_level("WARNING"):
        slot.start(factory, nonexistent_signal=MagicMock())

    assert "has no signal" in caplog.text
    assert "nonexistent_signal" in caplog.text


# ---------------------------------------------------------------------------
# WorkerSlot — start_if_not_running()
# ---------------------------------------------------------------------------


def test_worker_slot_start_if_not_running_when_idle(slot: WorkerSlot) -> None:
    fake_worker = MagicMock()
    factory = MagicMock(return_value=fake_worker)

    result = slot.start_if_not_running(factory)

    assert result is fake_worker
    fake_worker.start.assert_called_once()


def test_worker_slot_start_if_not_running_when_running(slot: WorkerSlot) -> None:
    running_worker = _FakeAsyncWorker()
    running_worker._running = True
    slot._instance = running_worker

    factory = MagicMock()
    result = slot.start_if_not_running(factory)

    assert result is None
    factory.assert_not_called()


# ---------------------------------------------------------------------------
# WorkerSlot — stop()
# ---------------------------------------------------------------------------


def test_worker_slot_stop_without_worker(slot: WorkerSlot) -> None:
    slot._instance = None
    slot.stop()


def test_worker_slot_stop_interrupts_and_quits(slot: WorkerSlot) -> None:
    worker = _FakeAsyncWorker()
    worker._running = True
    slot._instance = worker

    slot.stop()

    assert worker._running is False


def test_worker_slot_stop_clears_instance(slot: WorkerSlot) -> None:
    fake_worker = MagicMock()
    slot._instance = fake_worker

    slot.stop()

    assert slot.instance is None


def test_worker_slot_stop_handles_runtime_error(slot: WorkerSlot, caplog) -> None:
    fake_worker = MagicMock()
    fake_worker._is_async_worker = True
    fake_worker.stop.side_effect = RuntimeError("C++ object destroyed")
    slot._instance = fake_worker

    with caplog.at_level("DEBUG"):
        slot.stop()

    assert "RuntimeError" in caplog.text
    assert slot.instance is None


def test_worker_slot_stop_raises_unexpected_runtime_error(slot: WorkerSlot) -> None:
    fake_worker = MagicMock()
    fake_worker._is_async_worker = True
    fake_worker.stop.side_effect = RuntimeError("unexpected failure")
    slot._instance = fake_worker

    with pytest.raises(RuntimeError, match="unexpected failure"):
        slot.stop()

    assert slot.instance is None


def test_worker_slot_stop_disconnects_external_signals(slot: WorkerSlot) -> None:
    fake_signal = MagicMock()
    fake_worker = MagicMock()
    fake_worker.finished = fake_signal
    slot_handler = MagicMock()

    slot.start(lambda: fake_worker, finished=slot_handler)
    slot.stop()

    fake_signal.disconnect.assert_called_once_with(slot_handler)


def test_worker_slot_stop_calls_worker_stop_method(slot: WorkerSlot) -> None:
    worker = _FakeAsyncWorker()
    worker._running = True
    slot._instance = worker

    slot.stop()

    assert worker._running is False
    assert slot.instance is None


# ---------------------------------------------------------------------------
# WorkerManager — construction
# ---------------------------------------------------------------------------


def test_worker_manager_creates_all_slots(manager: WorkerManager) -> None:
    assert isinstance(manager.scan, WorkerSlot)
    assert isinstance(manager.scan_all, WorkerSlot)
    assert isinstance(manager.cleanup, WorkerSlot)
    assert isinstance(manager.cleanup_global, WorkerSlot)
    assert isinstance(manager.cleanup_scan_update, WorkerSlot)
    assert isinstance(manager.jellyfin_pull, WorkerSlot)
    assert isinstance(manager.jellyfin_push, WorkerSlot)
    assert isinstance(manager.file_property, WorkerSlot)
    assert isinstance(manager.subtitle_merge, WorkerSlot)
    assert isinstance(manager.metadata_embed, WorkerSlot)
    assert isinstance(manager.metadata_apply, WorkerSlot)
    assert isinstance(manager.refresh, WorkerSlot)
    assert isinstance(manager.scan_series, WorkerSlot)


def test_worker_manager_slots_returns_all_slots(manager: WorkerManager) -> None:
    all_slots = manager._slots()
    assert len(all_slots) >= 13
    assert manager.scan in all_slots
    assert manager.cleanup_global in all_slots
    assert manager.cleanup_scan_update in all_slots


def test_worker_manager_stop_all_stops_every_slot(manager: WorkerManager) -> None:
    for slot_instance in manager._slots():
        worker = _FakeAsyncWorker()
        worker._running = True
        slot_instance._instance = worker

    manager.stop_all()

    for slot_instance in manager._slots():
        assert slot_instance.instance is None


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


def test_worker_slot_repr_empty(slot: WorkerSlot) -> None:
    text = repr(slot)
    assert "empty" in text


def test_worker_slot_repr_with_worker(slot: WorkerSlot) -> None:
    worker = _FakeAsyncWorker()
    worker._running = True
    slot._instance = worker

    text = repr(slot)
    assert "_FakeAsyncWorker" in text
    assert "running=True" in text


# ---------------------------------------------------------------------------
# WorkerSlot — async worker support
# ---------------------------------------------------------------------------


class _FakeAsyncWorker(QObject):
    """A fake async worker with signals and lifecycle for WorkerSlot testing."""

    _is_async_worker = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running


def test_worker_slot_async_detection(slot: WorkerSlot) -> None:
    """Verify _is_async detects async workers."""
    async_worker = _FakeAsyncWorker()
    assert slot._is_async(async_worker) is True

    sync_worker = MagicMock(spec=[])
    assert slot._is_async(sync_worker) is False


def test_worker_slot_start_async_worker(slot: WorkerSlot) -> None:
    """Verify start() works with async workers."""
    factory = MagicMock(return_value=_FakeAsyncWorker())

    result = slot.start(factory)

    assert isinstance(result, _FakeAsyncWorker)
    assert result._running is True
    assert slot.instance is result


def test_worker_slot_stop_async_worker(slot: WorkerSlot) -> None:
    """Verify stop() calls stop() on async workers."""
    worker = _FakeAsyncWorker()
    worker._running = True
    slot._instance = worker

    slot.stop()

    assert worker._running is False
    assert slot.instance is None


def test_worker_slot_is_running_async(slot: WorkerSlot) -> None:
    """Verify is_running works with async workers."""
    worker = _FakeAsyncWorker()
    worker._running = True
    slot._instance = worker

    assert slot.is_running is True

    worker._running = False
    assert slot.is_running is False


def test_worker_slot_async_start_if_not_running(slot: WorkerSlot) -> None:
    """Verify start_if_not_running with async workers."""
    worker = _FakeAsyncWorker()
    worker._running = True
    slot._instance = worker

    factory = MagicMock()
    result = slot.start_if_not_running(factory)

    assert result is None
    factory.assert_not_called()


def test_worker_slot_async_connect_signals(slot: WorkerSlot) -> None:
    """Verify signal connections work with async workers."""
    finished_handler = MagicMock()
    worker = _FakeAsyncWorker()
    # Add signal attribute that the slot can connect to
    worker.finished = MagicMock()

    factory = MagicMock(return_value=worker)
    slot.start(factory, finished=finished_handler)
    worker.finished.connect.assert_called_once_with(finished_handler)
