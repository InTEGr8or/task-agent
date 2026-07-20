"""attach_store_remote: related vs unrelated history recovery."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from taskagent.store_registry import (
    _histories_related,
    _local_branch,
    attach_store_remote,
    looks_like_store,
    set_store_remote,
    write_store_meta,
)


def _run(cwd: Path, *args: str, env=None) -> None:
    e = {**os.environ, **(env or {})}
    e.setdefault("GIT_AUTHOR_NAME", "t")
    e.setdefault("GIT_AUTHOR_EMAIL", "t@t")
    e.setdefault("GIT_COMMITTER_NAME", "t")
    e.setdefault("GIT_COMMITTER_EMAIL", "t@t")
    subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        capture_output=True,
        env=e,
    )


def _seed_store(path: Path, msg: str) -> None:
    path.mkdir(parents=True)
    for d in ("pending", "draft", "active", "completed"):
        (path / d).mkdir()
    (path / ".task-agent").mkdir()
    (path / ".task-agent" / "mission.usv").write_text(
        "Name\x1fSlug\x1fDependencies\n", encoding="utf-8"
    )
    (path / "pending" / "note.md").write_text(f"# {msg}\n")
    write_store_meta(path, moniker="acme/app")
    _run(path, "git", "init", "-b", "main")
    _run(path, "git", "add", "-A")
    _run(path, "git", "commit", "-m", msg)


def test_histories_related_and_unrelated(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _seed_store(a, "commit-a")
    _seed_store(b, "commit-b")
    # clone a into c so related
    c = tmp_path / "c"
    subprocess.run(
        ["git", "clone", str(a), str(c)],
        check=True,
        capture_output=True,
    )
    assert _histories_related(c, "HEAD", "origin/main") or _histories_related(
        c, "HEAD", "HEAD"
    )
    # a and b are unrelated
    # add b as remote of a
    _run(a, "git", "remote", "add", "other", str(b))
    _run(a, "git", "fetch", "other")
    assert not _histories_related(a, "HEAD", "other/main")


def test_set_store_remote_only_configures(tmp_path):
    store = tmp_path / "store"
    _seed_store(store, "seed")
    remote_repo = tmp_path / "remote.git"
    _run(tmp_path, "git", "init", "--bare", str(remote_repo))
    info = set_store_remote(store, str(remote_repo), moniker="acme/app")
    assert info["action"] == "add"
    assert "origin" in info["remotes"]


def test_attach_empty_remote_publishes(tmp_path):
    store = tmp_path / "store"
    _seed_store(store, "local-seed")
    assert looks_like_store(store)
    remote_repo = tmp_path / "remote.git"
    _run(tmp_path, "git", "init", "--bare", str(remote_repo))

    info = attach_store_remote(
        store,
        str(remote_repo),
        moniker="acme/app",
        default_branch="main",
    )
    assert info["ok"]
    assert info["mode"] in ("empty_remote_publish", "fast_forward_or_push")
    # remote should have main
    out = subprocess.run(
        ["git", "ls-remote", "--heads", str(remote_repo)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "refs/heads/main" in out.stdout


def test_attach_unrelated_renames_then_publishes(tmp_path):
    """Remote has unrelated seed branch; tip is renamed, not deleted."""
    # Remote with only master seed (unrelated)
    remote_work = tmp_path / "remote-work"
    _seed_store(remote_work, "stale-eject-seed")
    # rename to master for old-style remote
    _run(remote_work, "git", "branch", "-m", "main", "master")
    remote_bare = tmp_path / "remote.git"
    _run(tmp_path, "git", "clone", "--bare", str(remote_work), str(remote_bare))

    store = tmp_path / "store"
    _seed_store(store, "fresh-local-after-migrate")

    info = attach_store_remote(
        store,
        str(remote_bare),
        moniker="acme/app",
        default_branch="main",
    )
    assert info["ok"]
    assert info["mode"] == "unrelated_rename_and_publish"
    assert info["mismatched"]
    assert info["mismatched"][0]["original"] == "master"
    assert info["mismatched"][0]["renamed_to"].startswith("mismatched_branch_master_")

    heads = subprocess.run(
        ["git", "ls-remote", "--heads", str(remote_bare)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "refs/heads/main" in heads
    assert "mismatched_branch_master_" in heads
    # Original tip is preserved under the mismatched_ name; we do not require
    # deleting master (rename is additive copy for comparison).
    stale_sha = info["mismatched"][0]["sha"]
    assert stale_sha[:8] in heads or stale_sha in heads


def test_local_branch_helper(tmp_path):
    store = tmp_path / "store"
    _seed_store(store, "x")
    assert _local_branch(store) == "main"
