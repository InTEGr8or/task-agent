"""Store moniker rebind after subject repo rename."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from taskagent.store_registry import (
    MachineRegistry,
    StoreEntry,
    rebind_store_moniker,
    store_path_for_moniker,
    write_host_store_config,
    write_store_meta,
)


def test_rebind_renames_store_and_host_pointer(tmp_path):
    data = tmp_path / "data"
    host = tmp_path / "host"
    host.mkdir()
    subprocess.run(["git", "init"], cwd=host, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(host),
            "remote",
            "add",
            "origin",
            "git@github.com:acme/new-name.git",
        ],
        check=True,
        capture_output=True,
    )

    old = "acme/old-name"
    store = store_path_for_moniker(old, data)
    store.mkdir(parents=True)
    (store / "pending").mkdir()
    (store / ".task-agent").mkdir()
    (store / ".task-agent" / "mission.usv").write_text("a\x1fb\x1f\n")
    write_store_meta(store, moniker=old)
    MachineRegistry(data).upsert(
        StoreEntry(moniker=old, store_path=str(store), host_paths=[str(host)])
    )
    write_host_store_config(host, old)

    info = rebind_store_moniker(host, data_root=data)
    assert info["old_moniker"] == old
    assert info["new_moniker"] == "acme/new-name"
    assert info["moved"] is True
    new_path = Path(info["store_path"])
    assert new_path.is_dir()
    assert not store.exists()
    meta = json.loads((new_path / ".task-agent" / "store.json").read_text())
    assert meta["moniker"] == "acme/new-name"
    cfg = json.loads((host / ".ta-config.json").read_text())
    assert cfg["store_moniker"] == "acme/new-name"
    reg = MachineRegistry(data)
    assert reg.get("acme/old-name") is None
    assert reg.get("acme/new-name") is not None
