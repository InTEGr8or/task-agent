import json
import time
from pathlib import Path
import pytest

from taskagent.manager import TaskAgent


def test_acquire_and_get_lease(tmp_path: Path):
    tasks_dir = tmp_path / "docs" / "tasks"
    mission_dir = tasks_dir / ".task-agent"
    mission_dir.mkdir(parents=True)
    (mission_dir / "mission.usv").write_text("Task Lease\x1ftask-lease\x1f\x1f\n")
    (mission_dir / "datapackage.json").write_text("{}")

    active_dir = tasks_dir / "active" / "task-lease"
    active_dir.mkdir(parents=True)
    (active_dir / "README.md").write_text("# Task Lease\n")

    manager = TaskAgent(config_dir=str(tasks_dir))
    manager.sync_mission(ingest=True)

    # Acquire lease
    lease = manager.acquire_lease("task-lease", ttl_seconds=3600, worker_id="worker-1")
    assert lease["slug"] == "task-lease"
    assert lease["worker_id"] == "worker-1"
    assert lease["status"] == "active"
    assert lease["is_expired"] is False

    # Get lease
    fetched = manager.get_lease("task-lease")
    assert fetched is not None
    assert fetched["worker_id"] == "worker-1"
    assert fetched["is_expired"] is False


def test_lease_conflict_prevention(tmp_path: Path):
    tasks_dir = tmp_path / "docs" / "tasks"
    mission_dir = tasks_dir / ".task-agent"
    mission_dir.mkdir(parents=True)
    (mission_dir / "mission.usv").write_text("Task Conflict\x1ftask-conflict\x1f\x1f\n")
    (mission_dir / "datapackage.json").write_text("{}")

    active_dir = tasks_dir / "active" / "task-conflict"
    active_dir.mkdir(parents=True)
    (active_dir / "README.md").write_text("# Task Conflict\n")

    manager = TaskAgent(config_dir=str(tasks_dir))
    manager.sync_mission(ingest=True)

    # Worker 1 acquires lease
    manager.acquire_lease("task-conflict", ttl_seconds=3600, worker_id="worker-1")

    # Worker 2 attempts to acquire -> raises ValueError
    with pytest.raises(ValueError, match="currently leased by worker 'worker-1'"):
        manager.acquire_lease("task-conflict", ttl_seconds=3600, worker_id="worker-2")

    # Worker 2 with force=True succeeds
    forced_lease = manager.acquire_lease(
        "task-conflict", ttl_seconds=3600, worker_id="worker-2", force=True
    )
    assert forced_lease["worker_id"] == "worker-2"


def test_release_lease(tmp_path: Path):
    tasks_dir = tmp_path / "docs" / "tasks"
    mission_dir = tasks_dir / ".task-agent"
    mission_dir.mkdir(parents=True)
    (mission_dir / "mission.usv").write_text("Task Release\x1ftask-release\x1f\x1f\n")
    (mission_dir / "datapackage.json").write_text("{}")

    active_dir = tasks_dir / "active" / "task-release"
    active_dir.mkdir(parents=True)
    (active_dir / "README.md").write_text("# Task Release\n")

    manager = TaskAgent(config_dir=str(tasks_dir))
    manager.sync_mission(ingest=True)

    manager.acquire_lease("task-release", ttl_seconds=3600, worker_id="worker-1")
    assert manager.get_lease("task-release") is not None

    # Release lease
    released = manager.release_lease("task-release")
    assert released is True
    assert manager.get_lease("task-release") is None
