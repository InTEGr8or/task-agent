"""Phase 1: data root, moniker, and machine registry (no migration)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from taskagent.store_registry import (
    MachineRegistry,
    StoreEntry,
    detect_legacy_store,
    get_data_root,
    get_stores_dir,
    inspect_host,
    is_nested_git_repo,
    moniker_from_path,
    moniker_from_remote,
    moniker_to_dir_name,
    read_store_meta,
    store_path_for_moniker,
    write_store_meta,
)


# ---------------------------------------------------------------------------
# Data root
# ---------------------------------------------------------------------------


def test_get_data_root_default(monkeypatch, tmp_path):
    monkeypatch.delenv("TA_DATA_ROOT", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr("taskagent.store_registry.Path.home", lambda: tmp_path)
    root = get_data_root()
    assert root == (tmp_path / ".local" / "share" / "task-agent").resolve()


def test_get_data_root_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("TA_DATA_ROOT", raising=False)
    xdg = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    assert get_data_root() == (xdg / "task-agent").resolve()


def test_get_data_root_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom-ta"
    monkeypatch.setenv("TA_DATA_ROOT", str(custom))
    assert get_data_root() == custom.resolve()


def test_get_stores_dir(tmp_path):
    assert get_stores_dir(tmp_path) == tmp_path / "stores"


# ---------------------------------------------------------------------------
# Moniker parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("git@github.com:bizkite-co/stations.git", "bizkite-co/stations"),
        ("git@github.com:InTEGr8or/task-agent.git", "InTEGr8or/task-agent"),
        ("https://github.com/InTEGr8or/task-agent.git", "InTEGr8or/task-agent"),
        ("https://github.com/InTEGr8or/task-agent", "InTEGr8or/task-agent"),
        ("ssh://git@github.com/owner/repo.git", "owner/repo"),
        ("git@gitlab.com:group/sub/repo.git", "group/sub/repo"),
        ("https://gitlab.com/group/sub/repo.git", "group/sub/repo"),
    ],
)
def test_moniker_from_remote(url, expected):
    assert moniker_from_remote(url) == expected


def test_moniker_from_remote_empty():
    with pytest.raises(ValueError):
        moniker_from_remote("")


def test_moniker_to_dir_name():
    assert moniker_to_dir_name("bizkite-co/stations") == "bizkite-co_stations"
    assert moniker_to_dir_name("group/sub/repo") == "group_sub_repo"


def test_moniker_from_path_stable(tmp_path):
    p = tmp_path / "my-folder"
    p.mkdir()
    a = moniker_from_path(p)
    b = moniker_from_path(p)
    assert a == b
    assert a.startswith("local/my-folder-")


def test_store_path_for_moniker(tmp_path):
    path = store_path_for_moniker("bizkite-co/stations", tmp_path)
    assert path == tmp_path / "stores" / "bizkite-co_stations"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_atomic_save_and_load(tmp_path):
    reg = MachineRegistry(tmp_path)
    entry = StoreEntry(
        moniker="acme/app",
        store_path=str(tmp_path / "stores" / "acme_app"),
        host_paths=["/home/u/repos/app"],
        remote="git@github.com:acme/app-tasks.git",
    )
    reg.upsert(entry)

    assert reg.registry_path.is_file()
    raw = json.loads(reg.registry_path.read_text())
    assert raw["version"] == 1
    assert "acme/app" in raw["stores"]

    loaded = reg.get("acme/app")
    assert loaded is not None
    assert loaded.store_path == entry.store_path
    assert loaded.host_paths == ["/home/u/repos/app"]
    assert loaded.remote == entry.remote
    assert loaded.registered_at  # set on first upsert


def test_registry_upsert_merges_host_paths(tmp_path):
    reg = MachineRegistry(tmp_path)
    reg.upsert(
        StoreEntry(
            moniker="acme/app",
            store_path="/stores/acme_app",
            host_paths=["/a"],
        )
    )
    reg.upsert(
        StoreEntry(
            moniker="acme/app",
            store_path="/stores/acme_app",
            host_paths=["/b"],
            remote="git@example.com:acme/app.git",
        )
    )
    entry = reg.get("acme/app")
    assert entry is not None
    assert entry.host_paths == ["/a", "/b"]
    assert entry.remote == "git@example.com:acme/app.git"


def test_registry_find_by_host_path(tmp_path):
    host = tmp_path / "repos" / "app"
    host.mkdir(parents=True)
    store = tmp_path / "stores" / "acme_app"
    store.mkdir(parents=True)

    reg = MachineRegistry(tmp_path)
    reg.upsert(
        StoreEntry(
            moniker="acme/app",
            store_path=str(store),
            host_paths=[str(host)],
        )
    )
    # Exact and nested path
    assert reg.find_by_host_path(host) is not None
    nested = host / "src"
    nested.mkdir()
    found = reg.find_by_host_path(nested)
    assert found is not None
    assert found.moniker == "acme/app"


def test_rebuild_from_stores_preserves_host_paths(tmp_path):
    stores = tmp_path / "stores"
    store = stores / "acme_app"
    store.mkdir(parents=True)
    write_store_meta(store, moniker="acme/app", remote="git@gh.com:acme/app.git")

    reg = MachineRegistry(tmp_path)
    reg.upsert(
        StoreEntry(
            moniker="acme/app",
            store_path=str(store),
            host_paths=["/old/host"],
        )
    )
    # Drop registry body and rebuild
    reg.registry_path.unlink()
    # Re-seed host_paths then rebuild would lose them without prior load —
    # simulate: write registry with host_paths, then rebuild
    reg.upsert(
        StoreEntry(
            moniker="acme/app",
            store_path=str(store),
            host_paths=["/old/host"],
        )
    )
    rebuilt = reg.rebuild_from_stores()
    assert "acme/app" in rebuilt
    assert rebuilt["acme/app"].host_paths == ["/old/host"]
    assert rebuilt["acme/app"].remote == "git@gh.com:acme/app.git"
    assert Path(rebuilt["acme/app"].store_path) == store.resolve()


def test_rebuild_drops_missing_stores(tmp_path):
    reg = MachineRegistry(tmp_path)
    reg.upsert(
        StoreEntry(
            moniker="gone/app",
            store_path=str(tmp_path / "stores" / "gone_app"),
            host_paths=["/x"],
        )
    )
    # No actual store dir
    rebuilt = reg.rebuild_from_stores()
    assert "gone/app" not in rebuilt


def test_write_and_read_store_meta(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    write_store_meta(store, moniker="a/b", remote="r")
    meta = read_store_meta(store)
    assert meta is not None
    assert meta["moniker"] == "a/b"
    assert meta["remote"] == "r"


# ---------------------------------------------------------------------------
# Legacy detection (read-only)
# ---------------------------------------------------------------------------


def test_detect_legacy_task_agent_tasks(tmp_path):
    legacy = tmp_path / ".task-agent" / "tasks"
    legacy.mkdir(parents=True)
    assert detect_legacy_store(tmp_path) == legacy.resolve()


def test_detect_legacy_via_symlink(tmp_path):
    real = tmp_path / "real-store"
    real.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    link = docs / "tasks"
    link.symlink_to(real)
    assert detect_legacy_store(tmp_path) == real.resolve()


def test_is_nested_git_repo(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    subprocess.run(["git", "init"], cwd=nested, check=True, capture_output=True)
    assert is_nested_git_repo(nested) is True
    assert is_nested_git_repo(tmp_path) is False


def test_inspect_host_no_side_effects(tmp_path, monkeypatch):
    data = tmp_path / "data"
    host = tmp_path / "hostproj"
    host.mkdir()
    legacy = host / ".task-agent" / "tasks"
    legacy.mkdir(parents=True)
    (legacy / "pending").mkdir()
    (legacy / ".task-agent").mkdir()
    (legacy / ".task-agent" / "mission.usv").write_text("Name\x1fSlug\x1f\n")

    monkeypatch.setenv("TA_DATA_ROOT", str(data))
    report = inspect_host(host, data_root=data)

    assert report["legacy_store_path"] == str(legacy.resolve())
    assert report["legacy_kind"] == "host_tree"
    assert report["canonical_store_exists"] is False
    assert report["migrated"] is False
    assert report["registry_entry"] is None
    # Must not create data root or registry as side effect of inspect
    assert not data.exists() or not (data / "registry.json").exists()


# ---------------------------------------------------------------------------
# Migration (Phase 2)
# ---------------------------------------------------------------------------


def _make_host_tree_store(host: Path) -> Path:
    store = host / ".task-agent" / "tasks"
    store.mkdir(parents=True)
    (store / "pending").mkdir()
    (store / "active").mkdir()
    (store / "draft").mkdir()
    (store / "completed").mkdir()
    mission_dir = store / ".task-agent"
    mission_dir.mkdir()
    (mission_dir / "mission.usv").write_text(
        "Name\x1fSlug\x1fDependencies\nHello\x1fhello\x1f\n", encoding="utf-8"
    )
    task = store / "pending" / "hello"
    task.mkdir()
    (task / "README.md").write_text("# Hello\n", encoding="utf-8")
    docs = host / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "tasks").symlink_to(store.resolve())
    return store


def _make_nested_git_store(host: Path, remote_url: str) -> Path:
    import os

    store = _make_host_tree_store(host)
    subprocess.run(["git", "init"], cwd=store, check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(store), "remote", "add", "origin", remote_url],
        check=True,
        capture_output=True,
    )
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(
        ["git", "-C", str(store), "add", "-A"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(store), "commit", "-m", "init"],
        check=True,
        capture_output=True,
        env=env,
    )
    return store


def test_migrate_host_tree_dry_run_no_changes(tmp_path):
    from taskagent.store_registry import migrate_store, plan_migrate

    data = tmp_path / "data"
    host = tmp_path / "proj"
    host.mkdir()
    store = _make_host_tree_store(host)

    plan = plan_migrate(host, data_root=data)
    assert plan.kind == "host_tree"
    assert plan.errors == []
    assert plan.source == str(store.resolve())

    result = migrate_store(host, dry_run=True, data_root=data)
    assert result.success
    assert result.dry_run
    assert store.is_dir()
    assert not (data / "stores").exists() or not any((data / "stores").iterdir())


def test_migrate_host_tree_apply(tmp_path):
    from taskagent.store_registry import (
        MachineRegistry,
        inspect_host,
        migrate_store,
    )

    data = tmp_path / "data"
    host = tmp_path / "proj"
    host.mkdir()
    # No git remote → path moniker
    store = _make_host_tree_store(host)
    mission_before = (store / ".task-agent" / "mission.usv").read_text(encoding="utf-8")

    result = migrate_store(host, dry_run=False, data_root=data)
    assert result.success, result.message

    dest = Path(result.plan.destination)
    assert dest.is_dir()
    assert (dest / ".task-agent" / "mission.usv").read_text(
        encoding="utf-8"
    ) == mission_before
    assert (dest / "pending" / "hello" / "README.md").is_file()
    assert (dest / ".git").exists()  # host_tree gets its own repo
    # No origin invented
    rem = subprocess.run(
        ["git", "-C", str(dest), "remote"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert rem.stdout.strip() == ""

    eject = host / ".task-agent" / "tasks"
    assert eject.is_symlink()
    assert eject.resolve() == dest.resolve()
    docs = host / "docs" / "tasks"
    assert docs.is_symlink()
    assert docs.resolve() == dest.resolve()

    env_text = (host / ".env").read_text(encoding="utf-8")
    assert f"TA_EJECTED_TASKS_PATH={dest.resolve()}" in env_text

    reg = MachineRegistry(data)
    entry = reg.get(result.plan.moniker)
    assert entry is not None
    assert Path(entry.store_path).resolve() == dest.resolve()

    report = inspect_host(host, data_root=data)
    assert report["migrated"] is True
    assert report["pointers_ok"] is True

    # Idempotent second run
    result2 = migrate_store(host, dry_run=False, data_root=data)
    assert result2.success
    assert result2.plan.already_migrated


def test_migrate_nested_git_preserves_remote(tmp_path):
    from taskagent.store_registry import migrate_store

    data = tmp_path / "data"
    host = tmp_path / "proj"
    host.mkdir()
    remote = "git@github.com:acme/proj-tasks.git"
    _make_nested_git_store(host, remote)

    result = migrate_store(host, dry_run=False, data_root=data)
    assert result.success, result.message
    assert result.plan.kind == "nested_git"
    dest = Path(result.plan.destination)
    assert (dest / ".git").exists()
    url = subprocess.run(
        ["git", "-C", str(dest), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert url == remote


def test_mission_remote_status_states(tmp_path):
    from taskagent.store_registry import (
        format_remote_status_line,
        mission_remote_status,
    )

    none = mission_remote_status(None)
    assert none["state"] == "no_git"
    assert "no git" in format_remote_status_line(none)

    bare = tmp_path / "bare"
    bare.mkdir()
    local = mission_remote_status(bare)
    # no .git
    assert local["state"] == "no_git"

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    only = mission_remote_status(repo)
    assert only["state"] == "local_only"
    assert "local only" in format_remote_status_line(only)

    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@gh.com:a/b.git"],
        check=True,
        capture_output=True,
    )
    ok = mission_remote_status(repo)
    assert ok["state"] == "configured"
    assert ok["origin"] == "git@gh.com:a/b.git"
    assert "Store remote" in format_remote_status_line(ok)


def test_github_remote_suggestions():
    from taskagent.plugins.github import GitHubTasksRemoteProvider

    p = GitHubTasksRemoteProvider()
    sug = p.suggest_remote("git@github.com:acme/app.git", "acme/app")
    labels = {s.label: s.url for s in sug}
    assert labels["sibling-tasks"] == "git@github.com:acme/app-tasks.git"
    assert labels["wiki"] == "git@github.com:acme/app.wiki.git"
    assert labels["same-repo"] == "git@github.com:acme/app.git"

    sug_https = p.suggest_remote("https://github.com/acme/app.git", "acme/app")
    assert sug_https[0].url.startswith("https://github.com/")
    assert p.suggest_remote("git@gitlab.com:g/r.git", "g/r") == []


def test_set_store_remote(tmp_path):
    from taskagent.store_registry import (
        _list_git_remotes,
        migrate_store,
        set_store_remote,
    )

    data = tmp_path / "data"
    host = tmp_path / "proj"
    host.mkdir()
    _make_host_tree_store(host)
    result = migrate_store(host, dry_run=False, data_root=data)
    assert result.success
    dest = Path(result.plan.destination)

    info = set_store_remote(
        dest,
        "git@github.com:acme/proj-tasks.git",
        moniker=result.plan.moniker,
        data_root=data,
    )
    assert info["action"] == "add"
    assert _list_git_remotes(dest)["origin"] == "git@github.com:acme/proj-tasks.git"

    info2 = set_store_remote(
        dest,
        "git@github.com:acme/proj-tasks-v2.git",
        moniker=result.plan.moniker,
        data_root=data,
    )
    assert info2["action"] == "set-url"
    assert _list_git_remotes(dest)["origin"] == "git@github.com:acme/proj-tasks-v2.git"


def test_migrate_refuses_overwrite_existing_dest(tmp_path):
    from taskagent.store_registry import migrate_store

    data = tmp_path / "data"
    host = tmp_path / "proj"
    host.mkdir()
    _make_host_tree_store(host)

    # Pre-create conflicting destination with different content
    # moniker from path is local/...
    plan_dest_parent = data / "stores"
    plan_dest_parent.mkdir(parents=True)
    # Run plan first to learn moniker
    from taskagent.store_registry import plan_migrate

    plan = plan_migrate(host, data_root=data)
    dest = Path(plan.destination)
    dest.mkdir(parents=True)
    (dest / "pending").mkdir()
    (dest / "README_CONFLICT").write_text("nope")

    result = migrate_store(host, dry_run=False, data_root=data)
    assert not result.success
    assert "already exists" in result.message.lower()
    # Source untouched
    assert (host / ".task-agent" / "tasks" / ".task-agent" / "mission.usv").is_file()
