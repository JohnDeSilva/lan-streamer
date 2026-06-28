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
    fake_worker = MagicMock()
    fake_worker.isRunning.return_value = True
    slot._instance = fake_worker
    assert slot.is_running is True

    fake_worker.isRunning.return_value = False
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
    running_worker = MagicMock()
    running_worker.isRunning.return_value = True
    slot._instance = running_worker

    new_worker = MagicMock()
    factory = MagicMock(return_value=new_worker)

    with caplog.at_level("WARNING"):
        result = slot.start(factory)

    assert result is new_worker
    assert "replacing running" in caplog.text


def test_worker_slot_start_stops_previous_worker(slot: WorkerSlot) -> None:
    running_worker = MagicMock()
    running_worker.isRunning.return_value = True
    slot._instance = running_worker

    new_worker = MagicMock()
    factory = MagicMock(return_value=new_worker)

    slot.start(factory)

    running_worker.requestInterruption.assert_called_once()
    running_worker.quit.assert_called_once()


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
    running_worker = MagicMock()
    running_worker.isRunning.return_value = True
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
    fake_worker = MagicMock()
    fake_worker.isRunning.return_value = False  # Will finish immediately
    fake_worker.wait.return_value = True
    slot._instance = fake_worker

    slot.stop()

    fake_worker.requestInterruption.assert_called_once()
    fake_worker.quit.assert_called_once()


def test_worker_slot_stop_clears_instance(slot: WorkerSlot) -> None:
    fake_worker = MagicMock()
    fake_worker.isRunning.return_value = False
    fake_worker.wait.return_value = True
    slot._instance = fake_worker

    slot.stop()

    assert slot.instance is None


def test_worker_slot_stop_handles_runtime_error(slot: WorkerSlot, caplog) -> None:
    fake_worker = MagicMock()
    fake_worker.requestInterruption.side_effect = RuntimeError("C++ object destroyed")
    slot._instance = fake_worker

    with caplog.at_level("DEBUG"):
        slot.stop()

    assert "RuntimeError" in caplog.text
    assert slot.instance is None


def test_worker_slot_stop_raises_unexpected_runtime_error(slot: WorkerSlot) -> None:
    fake_worker = MagicMock()
    fake_worker.requestInterruption.side_effect = RuntimeError("unexpected failure")
    slot._instance = fake_worker

    with pytest.raises(RuntimeError, match="unexpected failure"):
        slot.stop()

    assert slot.instance is None


def test_worker_slot_stop_disconnects_external_signals(slot: WorkerSlot) -> None:
    fake_signal = MagicMock()
    fake_worker = MagicMock()
    fake_worker.finished = fake_signal
    fake_worker.wait.return_value = True
    slot_handler = MagicMock()

    slot.start(lambda: fake_worker, finished=slot_handler)
    slot.stop()

    fake_signal.disconnect.assert_called_once_with(slot_handler)


def test_worker_slot_deferred_cleanup_waits_for_finished_signal(
    slot: WorkerSlot,
) -> None:
    fake_worker = MagicMock()
    fake_worker.wait.return_value = False
    fake_worker.finished = MagicMock()
    slot._instance = fake_worker

    slot.stop()

    assert fake_worker in slot._stopping_workers
    fake_worker.finished.connect.assert_called_once()
    cleanup_func = fake_worker.finished.connect.call_args[0][0]
    assert callable(cleanup_func)

    # Run cleanup
    cleanup_func()
    assert fake_worker not in slot._stopping_workers
    fake_worker.deleteLater.assert_called_once()
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
        fake_worker = MagicMock()
        fake_worker.isRunning.return_value = False
        fake_worker.wait.return_value = True
        slot_instance._instance = fake_worker

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
    fake_worker = MagicMock()
    fake_worker.__class__.__name__ = "FakeWorker"
    fake_worker.isRunning.return_value = True
    slot._instance = fake_worker

    text = repr(slot)
    assert "FakeWorker" in text
    assert "running=True" in text
