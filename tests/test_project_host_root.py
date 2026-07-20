"""project_host_root: worktree / .gwt unwrap for reliable migrate."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from taskagent.store_registry import (
    detect_legacy_store,
    is_nested_git_repo,
    plan_migrate,
    project_host_root,
)


def _git_env() -> dict:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, env=_git_env())


def test_project_host_root_unwraps_gwt(tmp_path):
    main = tmp_path / "turboship"
    main.mkdir()
    gwt = main / ".gwt" / "uat"
    gwt.mkdir(parents=True)
    assert project_host_root(gwt) == main.resolve()
    assert project_host_root(gwt / "src" / "deep") == main.resolve()


def test_project_host_root_git_worktree_common_dir(tmp_path):
    """Linked git worktree resolves to main via --git-common-dir."""
    main = tmp_path / "proj"
    main.mkdir()
    _run(main, "git", "init", "-b", "main")
    # need a commit for worktree add on some git versions
    (main / "README").write_text("x\n")
    _run(main, "git", "add", "README")
    _run(main, "git", "commit", "-m", "seed")
    wt = tmp_path / "linked-wt"
    _run(main, "git", "worktree", "add", str(wt), "-b", "feature")
    assert project_host_root(wt) == main.resolve()
    assert project_host_root(wt / "subdir") == main.resolve()


def test_plan_migrate_from_gwt_finds_main_nested_store(tmp_path):
    """Reproduce turboship: run migrate from .gwt/uat, store on main tree."""
    main = tmp_path / "turboship"
    main.mkdir()
    _run(main, "git", "init", "-b", "main")
    _run(
        main,
        "git",
        "remote",
        "add",
        "origin",
        "git@github.com:bizkite-co/turboship.git",
    )
    (main / "README").write_text("x\n")
    _run(main, "git", "add", "README")
    _run(main, "git", "commit", "-m", "seed")

    # Nested task store with its own remote (like turboship-tasks)
    store = main / ".task-agent" / "tasks"
    store.mkdir(parents=True)
    for d in ("pending", "active", "draft", "completed"):
        (store / d).mkdir()
    (store / ".task-agent").mkdir()
    (store / ".task-agent" / "mission.usv").write_text(
        "Name\x1fSlug\x1fDependencies\nT\x1ft\x1f\n", encoding="utf-8"
    )
    (store / "pending" / "hello").mkdir()
    (store / "pending" / "hello" / "README.md").write_text("# Hello\n")
    _run(store, "git", "init", "-b", "master")
    _run(
        store,
        "git",
        "remote",
        "add",
        "origin",
        "git@github.com:InTEGr8or/turboship-tasks.git",
    )
    _run(store, "git", "add", "-A")
    _run(store, "git", "commit", "-m", "tasks seed")

    # Worktree under .gwt/uat (where user ran ta store migrate)
    gwt = main / ".gwt" / "uat"
    _run(main, "git", "worktree", "add", str(gwt), "-b", "uat")

    assert project_host_root(gwt) == main.resolve()
    legacy = detect_legacy_store(gwt)
    assert legacy is not None
    assert legacy == store.resolve()
    assert is_nested_git_repo(legacy)

    data = tmp_path / "data"
    plan = plan_migrate(gwt, data_root=data)
    assert plan.errors == []
    assert plan.kind == "nested_git"
    assert plan.source == str(store.resolve())
    assert plan.host_path == str(main.resolve())
    assert plan.moniker == "bizkite-co/turboship"
    assert plan.remotes_before.get("origin") == (
        "git@github.com:InTEGr8or/turboship-tasks.git"
    )
    assert plan.subject_origin == "git@github.com:bizkite-co/turboship.git"
