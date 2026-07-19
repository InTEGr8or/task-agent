"""Auto-commit task-store changes after state transitions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


from taskagent.manager import TaskAgent


def _git_store(tmp_path: Path, monkeypatch) -> TaskAgent:
    """Create a dual-repo-style store (own git) with auto-commit enabled."""
    monkeypatch.delenv("TA_NO_AUTO_COMMIT", raising=False)
    store = tmp_path / "store"
    store.mkdir()
    for d in ("pending", "draft", "active", "completed"):
        (store / d).mkdir()
    (store / ".task-agent").mkdir()
    subprocess.run(["git", "init"], cwd=store, check=True, capture_output=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    # seed empty commit so HEAD exists
    (store / "README").write_text("store\n")
    subprocess.run(["git", "add", "-A"], cwd=store, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=store,
        check=True,
        capture_output=True,
        env=env,
    )
    return TaskAgent(config_dir=str(store))


def _log(store: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(store), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_create_issue_auto_commits(tmp_path, monkeypatch):
    mgr = _git_store(tmp_path, monkeypatch)
    before = len(_log(mgr.issues_root).splitlines())
    issue = mgr.create_issue(
        title="Auto commit me",
        body="",
        draft=True,
        as_dir=True,
        completion_criteria="ok",
    )
    after = _log(mgr.issues_root)
    assert issue.slug == "auto-commit-me"
    # create may also trigger ingest via init_project → 1–2 new commits
    assert len(after.splitlines()) >= before + 1
    assert "task: create auto-commit-me" in after


def test_promote_auto_commits(tmp_path, monkeypatch):
    mgr = _git_store(tmp_path, monkeypatch)
    mgr.create_issue(
        title="Promo", body="", draft=True, as_dir=True, completion_criteria="ok"
    )
    before = len(_log(mgr.issues_root).splitlines())
    mgr.promote_issue("promo")
    after = _log(mgr.issues_root)
    assert len(after.splitlines()) == before + 1
    assert "task: promote promo" in after


def test_no_auto_commit_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TA_NO_AUTO_COMMIT", "1")
    store = tmp_path / "store"
    store.mkdir()
    for d in ("pending", "draft", "active"):
        (store / d).mkdir()
    (store / ".task-agent").mkdir()
    subprocess.run(["git", "init"], cwd=store, check=True, capture_output=True)
    mgr = TaskAgent(config_dir=str(store))
    # no commits yet; create should not fail without git history either
    issue = mgr.create_issue(
        title="No commit", body="", draft=True, as_dir=True, completion_criteria="ok"
    )
    assert issue.slug == "no-commit"
    log = subprocess.run(
        ["git", "-C", str(store), "log", "--oneline"],
        capture_output=True,
        text=True,
    )
    # either no commits or no create message
    assert "task: create" not in (log.stdout or "")
