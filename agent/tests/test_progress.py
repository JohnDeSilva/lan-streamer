"""Unit tests for the ProgressBroker used by SSE scan streaming."""

from __future__ import annotations

from threading import Thread

from scan_agent.scan.progress import ProgressBroker


def test_publish_appends_and_increments_sequence() -> None:
    broker = ProgressBroker()
    first_event = broker.publish("scan.progress", {"step": 1})
    second_event = broker.publish("scan.log", {"line": "hi"})
    assert first_event["sequence"] == 1
    assert second_event["sequence"] == 2
    assert first_event["event"] == "scan.progress"


def test_subscribe_receives_events() -> None:
    broker = ProgressBroker()
    received: list[dict] = []
    handle = broker.subscribe(lambda event: received.append(event))  # noqa: PLW0108
    broker.publish("scan.progress", {"step": 1})
    broker.publish("scan.finished", {})
    assert len(received) == 2
    broker.unsubscribe(handle)
    broker.publish("scan.log", {"line": "ignored"})
    assert len(received) == 2


def test_subscribe_invalid_handle_is_safe() -> None:
    broker = ProgressBroker()
    broker.unsubscribe(999)


def test_subscriber_exceptions_are_swallowed() -> None:
    broker = ProgressBroker()

    def raise_on_event(event: dict) -> None:
        raise RuntimeError("boom")

    broker.subscribe(raise_on_event)
    broker.publish("scan.progress", {})  # must not raise


def test_pending_since_catches_up() -> None:
    broker = ProgressBroker()
    broker.publish("first", {})
    catch_up_sequence = broker.latest_sequence
    broker.publish("second", {})
    broker.publish("third", {})
    caught_up = list(broker.pending_since(catch_up_sequence))
    assert len(caught_up) == 2
    assert caught_up[0]["event"] == "second"
    assert caught_up[1]["event"] == "third"


def test_history_is_bounded() -> None:
    broker = ProgressBroker(max_history=5)
    for index in range(20):
        broker.publish("scan.progress", {"index": index})
    assert broker.latest_sequence == 20
    events = list(broker.pending_since(0))
    assert len(events) <= 5


def test_publish_log_uses_log_event() -> None:
    broker = ProgressBroker()
    event = broker.publish_log("some log line")
    assert event["event"] == "scan.log"
    assert event["payload"]["line"] == "some log line"
    assert event["payload"]["level"] == "INFO"


def test_publish_log_preserves_or_detects_level() -> None:
    broker = ProgressBroker()
    event_debug = broker.publish_log("debug message", level="DEBUG")
    assert event_debug["payload"]["level"] == "DEBUG"

    event_error = broker.publish_log("ERROR: scan failed")
    assert event_error["payload"]["level"] == "ERROR"

    event_warning = broker.publish_log("WARNING: missing directory")
    assert event_warning["payload"]["level"] == "WARNING"


def test_thread_safety_smoke() -> None:
    broker = ProgressBroker()
    threads = [
        Thread(target=lambda: [broker.publish("scan.progress", {}) for _ in range(50)])
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert broker.latest_sequence == 200
    events = list(broker.pending_since(100))
    assert len(events) == 100
