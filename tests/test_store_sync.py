"""Store sync: materialize ops and merge a diverged remote without dropping tasks."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from taskagent.oplog import append_op
from taskagent.store_sync import apply_ops, sync_store


def _git(path: Path, *args: str, env: dict[str, str]) -> None:
    subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _env(monkeypatch) -> dict[str, str]:
    monkeypatch.delenv("TA_NO_AUTO_COMMIT", raising=False)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    return os.environ.copy()


def _commit_task(
    repo: Path, slug: str, title: str, env: dict[str, str], writer: str
) -> None:
    task = repo / "pending" / slug
    task.mkdir(parents=True)
    (task / "README.md").write_text(
        f"---\ncreated_at: 2026-10-29T00:00:00+00:00\n---\n\n# {title}\n",
        encoding="utf-8",
    )
    append_op(
        repo,
        verb="create",
        slug=slug,
        payload={"name": title, "station": "pending"},
        writer=writer,
    )
    mission = repo / ".task-agent" / "mission.usv"
    line = f"{title}\x1f{slug}\x1f\x1f\n"
    existing = mission.read_text(encoding="utf-8") if mission.exists() else ""
    mission.parent.mkdir(parents=True, exist_ok=True)
    mission.write_text(existing + line, encoding="utf-8")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "--no-verify", "-m", f"task: create {slug}", env=env)


def test_apply_create_inserts_missing_mission_row(tmp_path):
    store = tmp_path / "store"
    (store / "pending" / "phone-task").mkdir(parents=True)
    (store / ".task-agent").mkdir()
    (store / "pending" / "phone-task" / "README.md").write_text(
        "# Phone task\n", encoding="utf-8"
    )
    (store / ".task-agent" / "mission.usv").write_text("", encoding="utf-8")
    append_op(
        store,
        verb="create",
        slug="phone-task",
        payload={"name": "Phone task", "station": "pending"},
        writer="handterm",
    )
    assert apply_ops(store) == ["applied"]
    mission = (store / ".task-agent" / "mission.usv").read_text(encoding="utf-8")
    assert "phone-task" in mission
    assert apply_ops(store) == ["noop"]


def test_create_issue_syncs_store_remote(tmp_path, monkeypatch):
    env = _env(monkeypatch)
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(bare), str(clone)], check=True, capture_output=True
    )
    for name in ("pending", "draft", "active", "completed", ".task-agent"):
        (clone / name).mkdir()
    (clone / "README").write_text("store\n", encoding="utf-8")
    _git(clone, "add", "-A", env=env)
    _git(clone, "commit", "--no-verify", "-m", "seed", env=env)
    _git(clone, "push", "-u", "origin", "HEAD", env=env)

    from taskagent.manager import TaskAgent

    mgr = TaskAgent(config_dir=str(clone))
    mgr.create_issue(
        title="Publish me",
        body="",
        as_dir=True,
        completion_criteria="on origin",
    )
    remote_tree = subprocess.run(
        ["git", "--git-dir", str(bare), "ls-tree", "-r", "--name-only", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "pending/publish-me/README.md" in remote_tree
    assert mgr.last_store_sync["mode"] == "pushed"


def test_no_auto_sync_env_keeps_commit_local(tmp_path, monkeypatch):
    env = _env(monkeypatch)
    monkeypatch.setenv("TA_NO_AUTO_SYNC", "1")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(bare), str(clone)], check=True, capture_output=True
    )
    for name in ("pending", "draft", "active", "completed", ".task-agent"):
        (clone / name).mkdir()
    (clone / "README").write_text("store\n", encoding="utf-8")
    _git(clone, "add", "-A", env=env)
    _git(clone, "commit", "--no-verify", "-m", "seed", env=env)
    _git(clone, "push", "-u", "origin", "HEAD", env=env)
    seed = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    from taskagent.manager import TaskAgent

    TaskAgent(config_dir=str(clone)).create_issue(
        title="Stay local",
        body="",
        draft=True,
        as_dir=True,
        completion_criteria="not pushed",
    )
    tip = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tip == seed


def test_sync_failure_keeps_local_commit(tmp_path, monkeypatch):
    env = _env(monkeypatch)
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(bare), str(clone)], check=True, capture_output=True
    )
    for name in ("pending", "draft", "active", "completed", ".task-agent"):
        (clone / name).mkdir()
    (clone / "README").write_text("store\n", encoding="utf-8")
    _git(clone, "add", "-A", env=env)
    _git(clone, "commit", "--no-verify", "-m", "seed", env=env)
    _git(clone, "push", "-u", "origin", "HEAD", env=env)
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"), env=env)

    from taskagent.manager import TaskAgent

    mgr = TaskAgent(config_dir=str(clone))
    mgr.create_issue(
        title="Kept local",
        body="",
        as_dir=True,
        completion_criteria="commit survives",
    )
    log = subprocess.run(
        ["git", "-C", str(clone), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "task: create kept-local" in log
    assert mgr.last_store_sync["mode"] == "failed"
    assert not (clone / ".git" / "MERGE_HEAD").exists()


def test_in_repo_tasks_are_not_auto_pushed(tmp_path, monkeypatch):
    env = _env(monkeypatch)
    bare = tmp_path / "code.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True)
    repo = tmp_path / "code"
    subprocess.run(
        ["git", "clone", str(bare), str(repo)], check=True, capture_output=True
    )
    tasks = repo / "docs" / "tasks"
    for name in ("pending", "draft", "active", "completed", ".task-agent"):
        (tasks / name).mkdir(parents=True)
    (repo / "README").write_text("code\n", encoding="utf-8")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "--no-verify", "-m", "seed", env=env)
    _git(repo, "push", "-u", "origin", "HEAD", env=env)
    seed = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    from taskagent.manager import TaskAgent

    TaskAgent(config_dir=str(tasks)).create_issue(
        title="Stay in the checkout",
        body="",
        as_dir=True,
        completion_criteria="not on origin",
    )
    tip = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert tip == seed
    assert "task: create stay-in-the-checkout" in log


def test_sync_pushes_when_ahead(tmp_path, monkeypatch):
    env = _env(monkeypatch)
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(bare), str(clone)], check=True, capture_output=True
    )
    (clone / "README").write_text("seed\n", encoding="utf-8")
    _git(clone, "add", "-A", env=env)
    _git(clone, "commit", "--no-verify", "-m", "seed", env=env)
    _git(clone, "push", "-u", "origin", "HEAD", env=env)
    (clone / "README").write_text("seed\nmore\n", encoding="utf-8")
    _git(clone, "add", "-A", env=env)
    _git(clone, "commit", "--no-verify", "-m", "local", env=env)

    report = sync_store(clone, push=True)
    assert report["mode"] == "pushed"
    tip = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    local = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tip == local


def test_sync_merges_divergent_creates(tmp_path, monkeypatch):
    env = _env(monkeypatch)
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True)
    left = tmp_path / "left"
    right = tmp_path / "right"
    subprocess.run(
        ["git", "clone", str(bare), str(left)], check=True, capture_output=True
    )
    (left / "README").write_text("seed\n", encoding="utf-8")
    (left / ".task-agent").mkdir()
    (left / ".task-agent" / "mission.usv").write_text("", encoding="utf-8")
    _git(left, "add", "-A", env=env)
    _git(left, "commit", "--no-verify", "-m", "seed", env=env)
    _git(left, "push", "-u", "origin", "HEAD", env=env)
    subprocess.run(
        ["git", "clone", str(bare), str(right)], check=True, capture_output=True
    )

    _commit_task(left, "from-wsl", "From WSL", env, "wsl")
    _git(left, "push", env=env)
    _commit_task(right, "from-phone", "From phone", env, "phone")

    report = sync_store(right, push=True)
    assert report["mode"] == "merged"
    mission = (right / ".task-agent" / "mission.usv").read_text(encoding="utf-8")
    assert "from-wsl" in mission
    assert "from-phone" in mission
    assert (right / "pending" / "from-wsl" / "README.md").is_file()
    assert (right / "pending" / "from-phone" / "README.md").is_file()

    subprocess.run(
        ["git", "-C", str(left), "pull", "--ff-only"],
        check=True,
        capture_output=True,
        env=env,
    )
    pulled = (left / ".task-agent" / "mission.usv").read_text(encoding="utf-8")
    assert "from-wsl" in pulled
    assert "from-phone" in pulled
