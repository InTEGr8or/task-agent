"""Per-writer op log: append, union, and reduce."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from taskagent.oplog import append_op, list_ops, reduce_ops


def _at(offset_s: int) -> datetime:
    return datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc) + timedelta(
        seconds=offset_s
    )


def test_two_writers_creates_both_survive(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    append_op(
        store,
        verb="create",
        slug="from-wsl",
        payload={"name": "From WSL", "station": "pending"},
        writer="wsl",
        at=_at(0),
    )
    append_op(
        store,
        verb="create",
        slug="from-phone",
        payload={"name": "From phone", "station": "pending"},
        writer="phone",
        at=_at(1),
    )

    state = reduce_ops(list_ops(store))
    assert set(state) == {"from-wsl", "from-phone"}
    assert state["from-phone"].name == "From phone"
    assert state["from-wsl"].station == "pending"


def test_later_move_wins_for_same_slug(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    append_op(
        store,
        verb="create",
        slug="shared",
        payload={"name": "Shared", "station": "pending"},
        writer="wsl",
        at=_at(0),
    )
    append_op(
        store,
        verb="move",
        slug="shared",
        payload={"station": "active", "from_station": "pending"},
        writer="wsl",
        at=_at(1),
    )
    append_op(
        store,
        verb="move",
        slug="shared",
        payload={"station": "completed", "from_station": "active"},
        writer="phone",
        at=_at(2),
    )

    state = reduce_ops(list_ops(store))
    assert state["shared"].station == "completed"


def test_first_create_wins(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    append_op(
        store,
        verb="create",
        slug="once",
        payload={"name": "First", "station": "draft"},
        writer="a",
        at=_at(0),
    )
    append_op(
        store,
        verb="create",
        slug="once",
        payload={"name": "Second", "station": "pending"},
        writer="b",
        at=_at(1),
    )
    state = reduce_ops(list_ops(store))
    assert state["once"].name == "First"
    assert state["once"].station == "draft"


def test_edges_and_rename(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    append_op(
        store,
        verb="create",
        slug="old-name",
        payload={"name": "Old", "station": "pending"},
        writer="a",
        at=_at(0),
    )
    append_op(
        store,
        verb="edges",
        slug="old-name",
        payload={"blocked_by": ["other"], "subtask_of": "parent"},
        writer="a",
        at=_at(1),
    )
    append_op(
        store,
        verb="rename",
        slug="old-name",
        payload={"new_slug": "new-name", "name": "New"},
        writer="b",
        at=_at(2),
    )
    state = reduce_ops(list_ops(store))
    assert "old-name" not in state
    task = state["new-name"]
    assert task.name == "New"
    assert task.blocked_by == ["other"]
    assert task.subtask_of == "parent"


def test_append_does_not_overwrite(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    when = _at(0)
    append_op(
        store,
        verb="lease",
        slug="job",
        payload={"worker_id": "pid-1"},
        writer="a",
        op_id="fixed",
        at=when,
    )
    try:
        append_op(
            store,
            verb="release",
            slug="job",
            writer="a",
            op_id="fixed",
            at=when,
        )
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("expected existing op to be refused")

    raw = json.loads(
        next((store / ".task-agent" / "ops" / "a").glob("*.op.json")).read_text()
    )
    assert raw["verb"] == "lease"
    assert raw["v"] == 1


def test_create_issue_records_op(tmp_path, monkeypatch):
    import os
    import subprocess

    from taskagent.manager import TaskAgent

    monkeypatch.delenv("TA_NO_AUTO_COMMIT", raising=False)
    monkeypatch.setenv("TA_WRITER_ID", "test-writer")
    store = tmp_path / "store"
    store.mkdir()
    for name in ("pending", "draft", "active", "completed", ".task-agent"):
        (store / name).mkdir()
    subprocess.run(["git", "init"], cwd=store, check=True, capture_output=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    (store / "README").write_text("store\n")
    subprocess.run(["git", "add", "-A"], cwd=store, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=store,
        check=True,
        capture_output=True,
        env=env,
    )

    mgr = TaskAgent(config_dir=str(store))
    issue = mgr.create_issue(
        title="Record an op",
        body="body",
        draft=True,
        as_dir=True,
        completion_criteria="op file committed",
    )
    ops = list_ops(store)
    assert len(ops) == 1
    assert ops[0].verb == "create"
    assert ops[0].slug == issue.slug
    assert ops[0].writer == "test-writer"
    assert ops[0].payload["station"] == "draft"

    tracked = subprocess.run(
        ["git", "-C", str(store), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ".task-agent/ops/test-writer/" in tracked
    assert ".op.json" in tracked
