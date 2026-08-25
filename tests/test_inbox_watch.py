"""Tests for inotify inbox watch functionality."""

from pathlib import Path
import threading
import time


from taskagent.inbox import (
    send_message,
    watch_inbox,
)


def test_watch_inbox_immediate_unread(tmp_path: Path):
    store_dir = tmp_path / "store"
    store_dir.mkdir()

    # Pre-populate an unread message
    send_message(
        store_dir,
        from_moniker="sender_test",
        body="Immediate test message",
        kind="info",
    )

    msgs = watch_inbox(store_dir, timeout_seconds=1.0)
    assert len(msgs) == 1
    assert msgs[0].body.strip() == "Immediate test message"
    assert msgs[0].from_moniker == "sender_test"


def test_watch_inbox_timeout(tmp_path: Path):
    store_dir = tmp_path / "store"
    store_dir.mkdir()

    start = time.monotonic()
    msgs = watch_inbox(store_dir, timeout_seconds=0.3)
    elapsed = time.monotonic() - start

    assert len(msgs) == 0
    assert elapsed >= 0.25


def test_watch_inbox_blocks_until_message_arrives(tmp_path: Path):
    store_dir = tmp_path / "store"
    store_dir.mkdir()

    received_msgs = []

    def _sender_thread():
        time.sleep(0.2)
        send_message(
            store_dir,
            from_moniker="async_agent",
            body="Async arrived message",
            kind="info",
        )

    t = threading.Thread(target=_sender_thread)
    t.start()

    try:
        msgs = watch_inbox(store_dir, timeout_seconds=2.0)
        received_msgs.extend(msgs)
    finally:
        t.join()

    assert len(received_msgs) == 1
    assert received_msgs[0].body.strip() == "Async arrived message"
    assert received_msgs[0].from_moniker == "async_agent"
