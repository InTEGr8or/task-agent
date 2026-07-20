"""ta store symlink on|off — docs/tasks human convenience only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taskagent.store_registry import (
    StoreSymlinkError,
    docs_tasks_symlink_status,
    set_docs_tasks_symlink,
    store_symlink_preferred,
    write_host_store_config,
    write_store_meta,
)


def _make_store(path: Path) -> Path:
    path.mkdir(parents=True)
    for d in ("pending", "active", "draft", "completed"):
        (path / d).mkdir()
    (path / ".task-agent").mkdir()
    (path / ".task-agent" / "mission.usv").write_text(
        "Name\x1fSlug\x1fDependencies\n", encoding="utf-8"
    )
    write_store_meta(path, moniker="acme/app")
    return path


def test_symlink_on_creates_and_gitignores(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("TA_DATA_ROOT", str(data))
    host = tmp_path / "proj"
    host.mkdir()
    store = _make_store(data / "stores" / "acme_app")
    write_host_store_config(host, moniker="acme/app", store_symlink=False)
    # registry so inspect finds store via moniker... moniker from path local/
    # Force store path via registry
    from taskagent.store_registry import MachineRegistry, StoreEntry

    MachineRegistry(data).upsert(
        StoreEntry(
            moniker="acme/app",
            store_path=str(store),
            host_paths=[str(host)],
        )
    )
    # moniker from path won't match — pass store_path explicitly
    result = set_docs_tasks_symlink(host, enabled=True, store_path=store)
    assert result["enabled"] is True
    link = host / "docs" / "tasks"
    assert link.is_symlink()
    assert link.resolve() == store.resolve()
    assert "docs/tasks" in (host / ".gitignore").read_text()
    cfg = json.loads((host / ".ta-config.json").read_text())
    assert cfg["store_symlink"] is True
    assert store_symlink_preferred(host) is True


def test_symlink_on_rejects_populated_directory(tmp_path):
    host = tmp_path / "proj"
    host.mkdir()
    store = _make_store(tmp_path / "store")
    docs = host / "docs" / "tasks"
    docs.mkdir(parents=True)
    (docs / "README.md").write_text("# my own docs\n")

    with pytest.raises(StoreSymlinkError) as ei:
        set_docs_tasks_symlink(host, enabled=True, store_path=store)
    assert "real directory" in str(ei.value).lower()
    assert (docs / "README.md").is_file()  # untouched


def test_symlink_on_rejects_file(tmp_path):
    host = tmp_path / "proj"
    host.mkdir()
    store = _make_store(tmp_path / "store")
    (host / "docs").mkdir()
    (host / "docs" / "tasks").write_text("not a dir\n")

    with pytest.raises(StoreSymlinkError) as ei:
        set_docs_tasks_symlink(host, enabled=True, store_path=store)
    assert "regular file" in str(ei.value).lower()


def test_symlink_off_removes_store_link_keeps_preference(tmp_path):
    host = tmp_path / "proj"
    host.mkdir()
    store = _make_store(tmp_path / "store")
    set_docs_tasks_symlink(host, enabled=True, store_path=store)
    assert (host / "docs" / "tasks").is_symlink()

    result = set_docs_tasks_symlink(host, enabled=False, store_path=store)
    assert result["enabled"] is False
    assert not (host / "docs" / "tasks").exists()
    assert store_symlink_preferred(host) is False
    # store still there
    assert store.is_dir()


def test_symlink_off_leaves_foreign_real_dir(tmp_path):
    host = tmp_path / "proj"
    host.mkdir()
    store = _make_store(tmp_path / "store")
    docs = host / "docs" / "tasks"
    docs.mkdir(parents=True)
    (docs / "mine.md").write_text("x\n")
    write_host_store_config(host, moniker="acme/app", store_symlink=True)

    result = set_docs_tasks_symlink(host, enabled=False, store_path=store)
    assert (docs / "mine.md").is_file()
    assert any("left" in a for a in result["actions"])


def test_symlink_status(tmp_path):
    host = tmp_path / "proj"
    host.mkdir()
    store = _make_store(tmp_path / "store")
    set_docs_tasks_symlink(host, enabled=True, store_path=store)
    st = docs_tasks_symlink_status(host, store)
    assert st["kind"] == "symlink"
    assert st["points_to_store"] is True
    assert st["preferred"] is True
    assert st["gitignore_has_docs_tasks"] is True
