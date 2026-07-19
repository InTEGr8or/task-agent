"""Fuzzy moniker/host resolution for cross-repo create/list."""

from __future__ import annotations

from pathlib import Path

import pytest

from taskagent.store_registry import (
    AmbiguousRepoMatchError,
    MachineRegistry,
    RepoNotFoundError,
    StoreEntry,
    fuzzy_match_repos,
    resolve_repo_query,
    write_store_meta,
)


def _register_store(
    data: Path, moniker: str, host_paths: list[str] | None = None
) -> Path:
    store = data / "stores" / moniker.replace("/", "_")
    store.mkdir(parents=True, exist_ok=True)
    (store / "pending").mkdir(exist_ok=True)
    (store / ".task-agent").mkdir(exist_ok=True)
    (store / ".task-agent" / "mission.usv").write_text(
        "Name\x1fSlug\x1fDependencies\n", encoding="utf-8"
    )
    write_store_meta(store, moniker=moniker)
    MachineRegistry(data).upsert(
        StoreEntry(
            moniker=moniker,
            store_path=str(store),
            host_paths=host_paths or [],
        )
    )
    return store


def test_resolve_exact_and_basename(tmp_path):
    data = tmp_path / "data"
    _register_store(data, "bizkite-co/stations")
    _register_store(data, "InTEGr8or/task-agent")

    hit = resolve_repo_query("stations", data_root=data)
    assert hit.moniker == "bizkite-co/stations"
    assert hit.reason == "exact moniker basename"

    hit2 = resolve_repo_query("InTEGr8or/task-agent", data_root=data)
    assert hit2.moniker == "InTEGr8or/task-agent"
    assert hit2.score == 100


def test_resolve_host_path_basename(tmp_path):
    data = tmp_path / "data"
    host = tmp_path / "repos" / "my-tool"
    host.mkdir(parents=True)
    _register_store(data, "acme/my-tool", host_paths=[str(host)])

    hit = resolve_repo_query("my-tool", data_root=data)
    assert hit.moniker == "acme/my-tool"


def test_ambiguous_match(tmp_path):
    data = tmp_path / "data"
    _register_store(data, "org/alpha-app")
    _register_store(data, "org/beta-app")

    with pytest.raises(AmbiguousRepoMatchError) as ei:
        resolve_repo_query("app", data_root=data)
    assert len(ei.value.candidates) == 2


def test_not_found(tmp_path):
    data = tmp_path / "data"
    _register_store(data, "org/only")
    with pytest.raises(RepoNotFoundError):
        resolve_repo_query("missing", data_root=data)


def test_fuzzy_rank_order(tmp_path):
    data = tmp_path / "data"
    _register_store(data, "bizkite-co/stations")
    _register_store(data, "other/stations-docs")
    hits = fuzzy_match_repos("stations", data_root=data)
    assert hits[0].moniker == "bizkite-co/stations"
    assert hits[0].score >= hits[1].score


def test_cross_repo_create_isolates_mission(tmp_path, monkeypatch):
    """Creating in target store must not write current store's mission."""
    from taskagent.manager import TaskAgent

    data = tmp_path / "data"
    monkeypatch.setenv("TA_DATA_ROOT", str(data))

    current = _register_store(data, "here/current")
    other = _register_store(data, "there/other")
    # Seed distinct mission content
    (current / ".task-agent" / "mission.usv").write_text(
        "Name\x1fSlug\x1fDependencies\nCurrent\x1fcurrent-task\x1f\n",
        encoding="utf-8",
    )
    (other / ".task-agent" / "mission.usv").write_text(
        "Name\x1fSlug\x1fDependencies\n",
        encoding="utf-8",
    )

    from taskagent.store_registry import manager_for_repo_query

    mgr, resolved = manager_for_repo_query("other", data_root=data)
    assert resolved.moniker == "there/other"
    assert mgr.issues_root.resolve() == other.resolve()

    issue = mgr.create_issue(
        title="Cross repo item",
        body="",
        draft=True,
        completion_criteria="done",
    )
    assert issue.slug

    # Current store mission unchanged
    cur_text = (current / ".task-agent" / "mission.usv").read_text(encoding="utf-8")
    assert "current-task" in cur_text
    assert "cross-repo-item" not in cur_text

    # Target got the task
    oth = TaskAgent(config_dir=str(other))
    slugs = {i.slug for i in oth.load_mission()}
    assert "cross-repo-item" in slugs
