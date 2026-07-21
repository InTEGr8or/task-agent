"""Inbox messaging: send, list, ack, GC day boundaries."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from taskagent.inbox import (
    DEFAULT_RETENTION_DAYS,
    ack_message,
    format_unread_banner,
    gc_inbox,
    list_unread,
    send_message,
    unread_count,
)
from taskagent.store_registry import (
    MachineRegistry,
    StoreEntry,
    write_store_meta,
)


def _store(tmp_path: Path, name: str = "demo") -> Path:
    store = tmp_path / "stores" / name
    store.mkdir(parents=True)
    (store / ".task-agent").mkdir()
    (store / "pending").mkdir()
    (store / ".task-agent" / "mission.usv").write_text(
        "Name\x1fSlug\x1fDependencies\n", encoding="utf-8"
    )
    write_store_meta(store, moniker=f"org/{name}")
    return store


def test_send_list_ack_roundtrip(tmp_path):
    store = _store(tmp_path)
    msg = send_message(
        store,
        from_moniker="org/sender",
        body="Hello from sender",
        kind="update",
        thread="my-task",
        task_snapshot={
            "slug": "my-task",
            "title": "My Task",
            "status": "active",
            "completion_criteria": "done",
        },
        message_id="fixed-id-1",
        created_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
    )
    assert msg.id == "fixed-id-1"
    assert unread_count(store) == 1
    assert list_unread(store, thread="other") == []
    assert len(list_unread(store, thread="my-task")) == 1

    banner = format_unread_banner(store, moniker="org/demo")
    assert banner is not None
    assert "1 unread" in banner
    # Banner is idempotent / non-mutating
    assert unread_count(store) == 1

    acked = ack_message(store, "fixed-id-1", ack_day=date(2026, 7, 21))
    assert acked.status == "read"
    assert "2026/07/21" in str(acked.path).replace("\\", "/")
    assert unread_count(store) == 0
    assert format_unread_banner(store) is None
    assert acked.path.is_file()
    assert "Hello from sender" in acked.path.read_text(encoding="utf-8")
    assert "My Task" in acked.path.read_text(encoding="utf-8")


def test_ack_prefix_match(tmp_path):
    store = _store(tmp_path)
    send_message(
        store,
        from_moniker="a",
        body="x",
        message_id="20260721T100000-aabbcc",
    )
    msg = ack_message(store, "20260721T100000")
    assert msg.id == "20260721T100000-aabbcc"


def test_gc_day_boundary_precision(tmp_path):
    """retention_days=7 on 2026-07-21 keeps 07-14..07-21; drops 07-13 and older."""
    store = _store(tmp_path)
    read = store / ".task-agent" / "inbox" / "read"
    days = {
        "2026/07/13": "drop",
        "2026/07/14": "keep",
        "2026/07/21": "keep",
        "2026/07/22": "keep-future",
    }
    for rel, tag in days.items():
        d = read.joinpath(*rel.split("/"))
        d.mkdir(parents=True)
        (d / f"{tag}.msg.md").write_text("---\nfrom: x\nkind: info\n---\n\nbody\n")

    # Unread must never be GC'd
    unread = store / ".task-agent" / "inbox" / "unread"
    unread.mkdir(parents=True)
    (unread / "keep-unread.msg.md").write_text("---\nfrom: x\nkind: info\n---\n\nhi\n")

    today = date(2026, 7, 21)
    dry = gc_inbox(store, retention_days=7, today=today, dry_run=True)
    assert any("2026/07/13" in p.replace("\\", "/") for p in dry)
    assert not any("2026/07/14" in p.replace("\\", "/") for p in dry)

    deleted = gc_inbox(store, retention_days=7, today=today, dry_run=False)
    assert any("2026/07/13" in p.replace("\\", "/") for p in deleted)
    assert not (read / "2026" / "07" / "13").exists()
    assert (read / "2026" / "07" / "14").exists()
    assert (read / "2026" / "07" / "21").exists()
    assert (unread / "keep-unread.msg.md").exists()

    # Idempotent re-run
    again = gc_inbox(store, retention_days=7, today=today, dry_run=False)
    assert again == []


def test_gc_zero_retention_deletes_all_past(tmp_path):
    store = _store(tmp_path)
    read = store / ".task-agent" / "inbox" / "read"
    old = read / "2020" / "01" / "01"
    old.mkdir(parents=True)
    (old / "x.msg.md").write_text("---\nfrom: x\nkind: info\n---\n\n\n")
    today_dir = read / "2026" / "07" / "21"
    today_dir.mkdir(parents=True)
    (today_dir / "y.msg.md").write_text("---\nfrom: x\nkind: info\n---\n\n\n")

    deleted = gc_inbox(
        store, retention_days=0, today=date(2026, 7, 21), dry_run=False
    )
    assert any("2020/01/01" in p.replace("\\", "/") for p in deleted)
    # today == cutoff for retention 0 → keep
    assert today_dir.exists()
    assert not old.exists()


def test_invalid_kind_rejected(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="Invalid kind"):
        send_message(store, from_moniker="a", kind="nope", body="")


def test_send_to_repo_fuzzy(tmp_path, monkeypatch):
    from taskagent.inbox import send_to_repo

    data = tmp_path / "data"
    monkeypatch.setenv("TA_DATA_ROOT", str(data))
    store = data / "stores" / "InTEGr8or_task-agent"
    store.mkdir(parents=True)
    (store / ".task-agent").mkdir(parents=True, exist_ok=True)
    (store / "pending").mkdir(exist_ok=True)
    (store / ".task-agent" / "mission.usv").write_text(
        "Name\x1fSlug\x1fDependencies\n", encoding="utf-8"
    )
    write_store_meta(store, moniker="InTEGr8or/task-agent")
    MachineRegistry(data).upsert(
        StoreEntry(
            moniker="InTEGr8or/task-agent",
            store_path=str(store),
            host_paths=[],
        )
    )

    msg, resolved = send_to_repo(
        "task-agent",
        from_moniker="bizkite-co/cocli",
        body="Please look at this",
        kind="question",
        thread="inbox-work",
    )
    assert resolved.moniker == "InTEGr8or/task-agent"
    assert msg.path.parent.name == "unread"
    assert unread_count(store) == 1


def test_default_retention_constant():
    assert DEFAULT_RETENTION_DAYS == 7
